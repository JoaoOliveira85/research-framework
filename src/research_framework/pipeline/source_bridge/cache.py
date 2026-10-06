"""Watermark + signal cache under ``_pipeline/sources/<module>/``."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..atomic_write import write_json
from .signal import SignalPayload, Verdict

logger = logging.getLogger(__name__)


@dataclass
class WatermarkEntry:
    source_version: str
    bridge_version: str
    extracted_at: str
    verdict: Verdict
    consensus: dict[str, Any] | None = None
    consecutive_empty_cycles: int = 0
    recent_cycle_verdicts: list[str] = field(default_factory=list)


_MAX_RECENT_CYCLE_VERDICTS = 3


def append_cycle_verdict(entry: WatermarkEntry, verdict: str) -> WatermarkEntry:
    """Append *verdict* to the rolling window and advance ``entry.verdict``.

    ``recent_cycle_verdicts`` holds the last three **cycle** outcomes for this
    source (oldest→newest). ``verdict`` is the latest single-cycle outcome used
    by cache-hit logic; both fields are updated together here so callers cannot
    accidentally leave a stale ``verdict`` when recording history.
    """
    updated = list(entry.recent_cycle_verdicts) + [verdict]
    if len(updated) > _MAX_RECENT_CYCLE_VERDICTS:
        updated = updated[-_MAX_RECENT_CYCLE_VERDICTS:]
    return WatermarkEntry(
        source_version=entry.source_version,
        bridge_version=entry.bridge_version,
        extracted_at=entry.extracted_at,
        verdict=verdict,  # type: ignore[arg-type]
        consensus=entry.consensus,
        consecutive_empty_cycles=entry.consecutive_empty_cycles,
        recent_cycle_verdicts=updated,
    )


def module_sources_dir(vault_dir: Path, module: str) -> Path:
    return vault_dir / "_pipeline" / "sources" / module


def watermarks_path(vault_dir: Path, module: str) -> Path:
    return module_sources_dir(vault_dir, module) / "watermarks.json"


def signals_dir(vault_dir: Path, module: str) -> Path:
    return module_sources_dir(vault_dir, module) / "signals"


def quarantine_dir(vault_dir: Path, module: str) -> Path:
    return module_sources_dir(vault_dir, module) / "quarantine"


def atomic_write_json(path: Path, data: Any) -> None:
    """Kept as a thin, name-stable wrapper — many call sites import this
    symbol from ``cache`` rather than the canonical helper directly."""
    write_json(path, data)


def load_watermarks(vault_dir: Path, module: str) -> dict[str, WatermarkEntry]:
    path = watermarks_path(vault_dir, module)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Unreadable watermarks.json for module %s", module)
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, WatermarkEntry] = {}
    for source_id, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        out[str(source_id)] = WatermarkEntry(
            source_version=str(entry["source_version"]),
            bridge_version=str(entry["bridge_version"]),
            extracted_at=str(entry["extracted_at"]),
            verdict=entry["verdict"],  # type: ignore[arg-type]
            consensus=entry.get("consensus"),
            consecutive_empty_cycles=int(entry.get("consecutive_empty_cycles", 0)),
            recent_cycle_verdicts=list(entry.get("recent_cycle_verdicts", [])),
        )
    return out


def save_watermarks(
    vault_dir: Path, module: str, watermarks: dict[str, WatermarkEntry]
) -> None:
    data = {sid: asdict(entry) for sid, entry in watermarks.items()}
    atomic_write_json(watermarks_path(vault_dir, module), data)


def source_stem(source_id: str) -> str:
    """Derive filesystem-safe stem from ``source_id`` (research R20)."""
    if "/" in source_id or source_id.startswith("."):
        base = Path(source_id).name or "source"
    else:
        base = source_id.rstrip("/").split("/")[-1] or "source"
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", base).strip("-") or "source"
    digest = hashlib.sha256(source_id.encode()).hexdigest()[:12]
    return f"{slug[:48]}-{digest}"


def signal_path(
    vault_dir: Path, module: str, source_id: str, source_version: str
) -> Path:
    stem = source_stem(source_id)
    safe_version = re.sub(r"[^a-zA-Z0-9._-]+", "-", source_version)[:64]
    return signals_dir(vault_dir, module) / f"{stem}-{safe_version}.json"


def read_signal(path: Path) -> SignalPayload | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    return SignalPayload.from_dict(raw)


def write_signal(vault_dir: Path, payload: SignalPayload) -> Path:
    path = signal_path(
        vault_dir, payload.module, payload.source_id, payload.source_version
    )
    atomic_write_json(path, payload.to_dict())
    return path


def is_cache_hit(
    *,
    watermark: WatermarkEntry | None,
    source_version: str,
    bridge_version: str,
    signal_file: Path,
) -> bool:
    if watermark is None:
        return False
    if watermark.source_version != source_version:
        return False
    if watermark.bridge_version != bridge_version:
        return False
    if not signal_file.is_file():
        return False
    return read_signal(signal_file) is not None


def gc_old_signals(
    vault_dir: Path,
    module: str,
    *,
    retention_days: int = 30,
) -> None:
    if retention_days <= 0:
        return
    sig_dir = signals_dir(vault_dir, module)
    if not sig_dir.is_dir():
        return
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    for path in sig_dir.glob("*.json"):
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        if mtime < cutoff:
            path.unlink(missing_ok=True)


def append_bridge_log(vault_dir: Path, module: str, line: str) -> None:
    log_path = module_sources_dir(vault_dir, module) / "bridge.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip() + "\n")


def build_source_signals_sidecar(vault_dir: Path, cycle: int) -> Path | None:
    """Aggregate latest signal payloads for scout consumption (FR-008)."""
    cycle_3 = f"{cycle:03d}"
    out_path = (
        vault_dir / "_pipeline" / "cycles" / f"cycle-{cycle_3}" / "source-signals.json"
    )
    modules_root = vault_dir / "_pipeline" / "sources"
    if not modules_root.is_dir():
        return None
    payloads: list[dict[str, Any]] = []
    for mod_dir in sorted(modules_root.iterdir()):
        if not mod_dir.is_dir():
            continue
        sig_dir = mod_dir / "signals"
        if not sig_dir.is_dir():
            continue
        latest: Path | None = None
        for path in sig_dir.glob("*.json"):
            if latest is None or path.stat().st_mtime > latest.stat().st_mtime:
                latest = path
        if latest is None:
            continue
        payload = read_signal(latest)
        if payload is not None:
            payloads.append(payload.to_dict())
    if not payloads:
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out_path, {"cycle": cycle, "signals": payloads})
    return out_path
