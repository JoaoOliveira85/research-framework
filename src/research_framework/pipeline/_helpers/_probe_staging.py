"""Probe-retrieval staging sub-leaf (SC-001 escape hatch under source_signals concern)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml

from ._io import _vault_notes_content_sha1

_LOG = logging.getLogger(__name__)


def _probe_retrieval_enabled(vault_dir: Path) -> bool:
    """True unless ``stages.probe_retrieval.enabled`` is explicitly false."""
    settings_path = vault_dir / "settings.yaml"
    if not settings_path.is_file():
        return True
    try:
        data = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return True
    if not isinstance(data, dict):
        return True
    stages = data.get("stages") or {}
    if not isinstance(stages, dict):
        return True
    stage_cfg = stages.get("probe_retrieval") or {}
    if not isinstance(stage_cfg, dict):
        return True
    if "enabled" not in stage_cfg:
        return True
    return bool(stage_cfg.get("enabled"))


def _run_probe_retrieval_and_cache(vault_dir: Path, spec, cycle_num: int) -> None:
    """Stage probe candidates via cache + optional ``agent_call`` retrieval (T092, A2)."""
    try:
        from research_framework.pipeline.probes import generate_probes

        cand_path = (
            vault_dir
            / "_pipeline"
            / "cycles"
            / f"cycle-{cycle_num:03d}-probe-candidates.json"
        )
        vault_hash = _vault_notes_content_sha1(vault_dir)
        cache_path = vault_dir / "_pipeline" / "probe-cache.json"
        cache: dict = {"version": 1, "probes": {}}
        if cache_path.is_file():
            try:
                cache = json.loads(cache_path.read_text(encoding="utf-8")) or cache
            except (OSError, json.JSONDecodeError):
                pass
        probe_map: dict[str, list[dict]] = {}
        if cand_path.is_file():
            try:
                raw = json.loads(cand_path.read_text(encoding="utf-8"))
                pm = raw.get("probes")
                if isinstance(pm, dict):
                    probe_map = {
                        str(k): list(v) if isinstance(v, list) else []
                        for k, v in pm.items()
                    }
            except (OSError, json.JSONDecodeError):
                probe_map = {}

        probe_rows = generate_probes(spec)
        cache_probes = cache.setdefault("probes", {})
        assert isinstance(cache_probes, dict)

        missing_prompt = False
        for probe in probe_rows:
            pid = probe.probe_id
            key = f"{pid}|{vault_hash}"
            entry = cache_probes.get(key)
            if isinstance(entry, list) and entry:
                probe_map[pid] = entry
                continue
            missing_prompt = True

        if missing_prompt and _probe_retrieval_enabled(vault_dir):
            from ..plan_narrator import _bootstrap_scripts_agent_call, _load_vault_tier

            probe_lines = "\n".join(f"- {p.probe_id}: {p.question}" for p in probe_rows)
            prompt = (
                "Return ONLY compact JSON (no markdown fences) with shape:\n"
                '{"probes": {"<probe_id>": [\n'
                '  {"filename": "<note.md under data_vault>", "confidence": "high"|"medium"|"low"}\n'
                "]}}\n"
                f"Cycle {cycle_num}. Candidate vault note filenames only.\n\n"
                f"Probes:\n{probe_lines}\n"
            )
            cycle_dir = vault_dir / "_pipeline" / "cycles" / f"cycle-{cycle_num:03d}"
            tier = _load_vault_tier(vault_dir, "probe_retrieval")
            agent_call = _bootstrap_scripts_agent_call(vault_dir=vault_dir)
            call_result = None
            try:
                call_result = agent_call.dispatch(
                    stage="probe_retrieval",
                    prompt=prompt,
                    tier=tier,
                    vault_dir=vault_dir,
                    cycle_dir=cycle_dir,
                    timeout_s=120,
                )
            except Exception:
                call_result = None
            if (
                call_result is not None
                and call_result.exit_code == 0
                and (call_result.stdout or "").strip()
            ):
                try:
                    parsed = json.loads(call_result.stdout.strip())
                except json.JSONDecodeError:
                    parsed = {}
                pm = parsed.get("probes") if isinstance(parsed, dict) else None
                if isinstance(pm, dict):
                    for pid, rows in pm.items():
                        if not isinstance(rows, list):
                            continue
                        cleaned: list[dict] = []
                        for row in rows:
                            if not isinstance(row, dict):
                                continue
                            fn = str(row.get("filename") or "").strip()
                            if not fn:
                                continue
                            conf = str(row.get("confidence") or "medium").lower()
                            if conf not in ("high", "medium", "low"):
                                conf = "medium"
                            cleaned.append({"filename": fn, "confidence": conf})
                        if cleaned:
                            probe_map[str(pid)] = cleaned
                            cache_probes[f"{pid}|{vault_hash}"] = cleaned

        if probe_map:
            from ..atomic_write import write_json as _write_json

            _write_json(
                cand_path,
                {"cycle_number": cycle_num, "probes": probe_map},
            )
            _write_json(cache_path, cache)

        from research_framework.pipeline import probes as _probes_mod

        _probes_mod.run_cycle_probes(
            vault_dir=vault_dir, spec=spec, cycle_number=cycle_num
        )
    except Exception as exc:
        _LOG.warning("[cycle_runner] probe staging failed: %s", exc)
