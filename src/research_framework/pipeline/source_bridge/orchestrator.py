"""Source-extraction stage orchestration."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from research_framework.pipeline.settings import load_vault_settings

from . import BRIDGE_VERSION
from .cache import (
    WatermarkEntry,
    append_cycle_verdict,
    build_source_signals_sidecar,
    gc_old_signals,
    is_cache_hit,
    load_watermarks,
    read_signal,
    save_watermarks,
    signal_path,
    write_signal,
)
from .consensus import run_consensus, tier_to_n, write_consensus_result
from .discovery import build_trigger_registry, order_modules, walk_modules
from .extractor import (
    extract_source,
    get_source_version,
    partial_to_signal,
)
from .isolation import isolated_call
from .preflight_runner import run_preflight
from .signal import apply_payload_size_cap, utc_now_iso
from .sources_loader import load_module_sources
from .validators import validate_payload

logger = logging.getLogger(__name__)


def run_extraction(
    vault_dir: Path,
    cycle: int,
    *,
    force_stale_schema: bool = False,
) -> dict[str, Any]:
    """Enumerate sources via ``sources_loader`` only (FR-013a/FR-013c).

    ``force_stale_schema`` is reserved for task T111 (schema-gen wired into the
    extraction/cycle-runner path); the ``source_bridge`` CLI accepts the flag today.
    """
    _ = force_stale_schema
    settings = load_vault_settings(vault_dir)
    stage = settings.stage("source_extraction")
    if not stage.enabled:
        return {"skipped": True, "reason": "source_extraction disabled"}

    listed = list(settings.modules)
    manifests = order_modules(walk_modules(vault_dir), listed)
    build_trigger_registry(manifests)

    retention = int(stage.extras.get("signal_retention_days", 30))
    tier_map = (
        stage.extras.get("consensus", {}).get("tiers")
        if isinstance(stage.extras.get("consensus"), dict)
        else None
    )

    summary: dict[str, Any] = {
        "cycle": cycle,
        "modules": [],
        "cache_hits": 0,
        "extractions": 0,
    }

    for manifest in manifests:
        sources = load_module_sources(vault_dir, manifest.name, manifest)
        watermarks = load_watermarks(vault_dir, manifest.name)
        module_stats: dict[str, Any] = {"name": manifest.name, "sources": len(sources)}
        source_health_lines: list[str] = []

        # spec 051 FR4: validate the module's sources before extraction.
        preflight = run_preflight(vault_dir, manifest)
        module_stats["preflight"] = preflight.to_dict()
        module_stats["preflight_policy"] = manifest.failure_policy
        if preflight.verdict == "fatal_fail":
            policy = manifest.failure_policy
            detail = "; ".join(preflight.messages) or "(no message)"
            if policy == "defer":
                module_stats["preflight_deferred"] = True
                logger.warning(
                    "Preflight deferred for module %s (retry next cycle): %s",
                    manifest.name,
                    detail,
                )
            elif policy == "degrade_gracefully":
                module_stats["preflight_degraded"] = True
                logger.warning(
                    "Preflight degraded for module %s — skipping contribution: %s",
                    manifest.name,
                    detail,
                )
            else:
                logger.warning(
                    "Preflight failed for module %s — skipping this cycle: %s",
                    manifest.name,
                    detail,
                )
            summary["modules"].append(module_stats)
            continue
        for msg in preflight.messages:  # warning verdict — surfaced, not fatal
            logger.warning("Preflight [%s]: %s", manifest.name, msg)

        for src in sources:
            status = _process_source(
                vault_dir,
                cycle,
                manifest=manifest,
                src=src,
                watermarks=watermarks,
                retention_days=retention,
                tier_map=tier_map,
            )
            _log_source_status(src.module, src.source_id, status)
            line = status.get("source_health_line")
            if isinstance(line, str):
                source_health_lines.append(line)
            if status.get("cache_hit"):
                summary["cache_hits"] += 1
            elif status.get("extracted"):
                summary["extractions"] += 1

        save_watermarks(vault_dir, manifest.name, watermarks)
        gc_old_signals(vault_dir, manifest.name, retention_days=retention)
        if source_health_lines:
            module_stats["source_health"] = source_health_lines
        summary["modules"].append(module_stats)

    build_source_signals_sidecar(vault_dir, cycle)
    return summary


def _process_source(
    vault_dir: Path,
    cycle: int,
    *,
    manifest: Any,
    src: Any,
    watermarks: dict[str, WatermarkEntry],
    retention_days: int,
    tier_map: dict[str, int] | None,
) -> dict[str, Any]:
    version = isolated_call(
        get_source_version,
        vault_dir,
        manifest,
        src.record,
        vault_dir=vault_dir,
        module=manifest.name,
        source_id=src.source_id,
        kind="version_probe",
        cycle=cycle,
    )
    if version is None:
        return {"failed": True, "source_id": src.source_id}

    sig_path = signal_path(vault_dir, manifest.name, src.source_id, version)
    wm = watermarks.get(src.source_id)
    if is_cache_hit(
        watermark=wm,
        source_version=version,
        bridge_version=BRIDGE_VERSION,
        signal_file=sig_path,
    ):
        cached = read_signal(sig_path)
        if cached is None:
            logger.warning(
                "Corrupt signal for %s/%s — treating as cache miss",
                manifest.name,
                src.source_id,
            )
        else:
            _record_watermark(
                watermarks,
                src.source_id,
                source_version=version,
                verdict=cached.verdict,
                extracted_at=cached.extracted_at,
            )
            return {"cache_hit": True, "source_id": src.source_id}

    def _spawn() -> Any:
        return extract_source(
            vault_dir,
            manifest,
            source=src.record,
            source_id=src.source_id,
            bridge_version=BRIDGE_VERSION,
        )

    n = tier_to_n(src.value_tier, tier_map)
    if n <= 1:
        payload = isolated_call(
            _spawn,
            vault_dir=vault_dir,
            module=manifest.name,
            source_id=src.source_id,
            kind="extractor",
            cycle=cycle,
        )
        if payload is None:
            return _maybe_salvage_failed(
                vault_dir,
                manifest,
                src.source_id,
                bridge_version=BRIDGE_VERSION,
                cycle=cycle,
            )
    else:

        def _spawn_isolated() -> Any:
            return isolated_call(
                _spawn,
                vault_dir=vault_dir,
                module=manifest.name,
                source_id=src.source_id,
                kind="extractor",
                cycle=cycle,
            )

        payload, consensus = run_consensus(
            spawn_extractor=_spawn_isolated,
            module=manifest.name,
            source_id=src.source_id,
            cycle=cycle,
            value_tier=src.value_tier,
            tier_map=tier_map,
            bridge_version=BRIDGE_VERSION,
            source_version=version,
        )
        write_consensus_result(vault_dir, consensus)

    val_errors = validate_payload(vault_dir, manifest, payload)
    if val_errors:
        logger.warning(
            "Validation failed for %s/%s: %s",
            manifest.name,
            src.source_id,
            val_errors,
        )
        payload.verdict = "error"
    payload = apply_payload_size_cap(payload)
    payload.extracted_at = utc_now_iso()
    write_signal(vault_dir, payload)
    _record_watermark(
        watermarks,
        src.source_id,
        source_version=version,
        verdict=payload.verdict,
        extracted_at=payload.extracted_at,
    )
    result: dict[str, Any] = {
        "extracted": True,
        "source_id": src.source_id,
        "verdict": payload.verdict,
    }
    if payload.verdict == "error":
        error_msg = str(
            payload.facts.get("error") or "; ".join(val_errors) or "unknown error"
        )
        result["source_health_line"] = (
            f"source health: {manifest.name} FAILED with {error_msg}"
        )
    return result


def _maybe_salvage_failed(
    vault_dir: Path,
    manifest: Any,
    source_id: str,
    *,
    bridge_version: str,
    cycle: int,
) -> dict[str, Any]:
    from .cache import quarantine_dir

    qdir = quarantine_dir(vault_dir, manifest.name)
    safe = source_id.replace("/", "_")[:120]
    partial_path = qdir / f"{safe}.partial.json"
    if partial_path.is_file():
        try:
            partial = json.loads(partial_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            partial = None
        if isinstance(partial, dict):
            payload = partial_to_signal(
                partial,
                manifest=manifest,
                source_id=source_id,
                bridge_version=bridge_version,
            )
            payload.extracted_at = utc_now_iso()
            write_signal(vault_dir, payload)
            return {
                "extracted": True,
                "source_id": source_id,
                "verdict": "error",
                "partial": True,
                "source_health_line": (
                    f"source health: {manifest.name} FAILED with partial extraction error"
                ),
            }
    return {"failed": True, "source_id": source_id}


def _record_watermark(
    watermarks: dict[str, WatermarkEntry],
    source_id: str,
    *,
    source_version: str,
    verdict: str,
    extracted_at: str,
) -> None:
    prev = watermarks.get(source_id)
    base = WatermarkEntry(
        source_version=source_version,
        bridge_version=BRIDGE_VERSION,
        extracted_at=extracted_at,
        verdict=verdict,  # type: ignore[arg-type]
        consensus=prev.consensus if prev else None,
        consecutive_empty_cycles=prev.consecutive_empty_cycles if prev else 0,
        recent_cycle_verdicts=prev.recent_cycle_verdicts if prev else [],
    )
    watermarks[source_id] = append_cycle_verdict(base, verdict)


def _log_source_status(module: str, source_id: str, status: dict[str, Any]) -> None:
    """Emit per-source telemetry. INFO level — this fires for every source.

    Was previously ``print(..., file=sys.stderr)`` so the default behaviour
    was "always show". Migrated to INFO (not WARNING) per spec-048 Copilot
    review: WARNING for routine per-source telemetry would overwhelm
    operators and CI at the non-TTY default ``--log-level warning``.
    A failed extraction surfaces via the orchestrator's own error path
    in ``invoke_extractor``; this function only reports outcome metadata.
    """
    record = {"module": module, "source_id": source_id, **status}
    logger.info(json.dumps(record))
