"""Tests for rolling cycle verdict history on watermark entries."""

from __future__ import annotations

import json
from pathlib import Path

from research_framework.pipeline.source_bridge.cache import (
    WatermarkEntry,
    append_cycle_verdict,
    load_watermarks,
    save_watermarks,
)


def _sample_entry(**overrides: object) -> WatermarkEntry:
    base = {
        "source_version": "v1",
        "bridge_version": "0.8.0",
        "extracted_at": "2026-06-01T00:00:00Z",
        "verdict": "ok",
    }
    base.update(overrides)
    return WatermarkEntry(**base)  # type: ignore[arg-type]


def test_append_verdict_retains_only_last_three() -> None:
    entry = _sample_entry()
    for verdict in ("ok", "empty", "error", "ok"):
        entry = append_cycle_verdict(entry, verdict)
    assert entry.recent_cycle_verdicts == ["empty", "error", "ok"]
    assert entry.verdict == "ok"


def test_append_cycle_verdict_advances_latest_verdict_field() -> None:
    entry = append_cycle_verdict(_sample_entry(verdict="ok"), "error")
    assert entry.recent_cycle_verdicts == ["error"]
    assert entry.verdict == "error"


def test_load_back_compat_missing_recent_cycle_verdicts(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    wm_path = vault / "_pipeline" / "sources" / "youtube" / "watermarks.json"
    wm_path.parent.mkdir(parents=True)
    wm_path.write_text(
        json.dumps(
            {
                "vid-1": {
                    "source_version": "v1",
                    "bridge_version": "0.8.0",
                    "extracted_at": "2026-06-01T00:00:00Z",
                    "verdict": "ok",
                    "consecutive_empty_cycles": 0,
                }
            }
        ),
        encoding="utf-8",
    )
    loaded = load_watermarks(vault, "youtube")
    assert loaded["vid-1"].recent_cycle_verdicts == []


def test_save_watermarks_atomic_round_trip(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    entry = append_cycle_verdict(_sample_entry(), "error")
    entry = append_cycle_verdict(entry, "empty")
    save_watermarks(vault, "rss", {"feed-a": entry})
    loaded = load_watermarks(vault, "rss")
    assert loaded["feed-a"].recent_cycle_verdicts == ["error", "empty"]
