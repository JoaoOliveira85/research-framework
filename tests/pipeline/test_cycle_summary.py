"""Tests for cycle_summary.write_summary aggregation behaviour."""

from __future__ import annotations

import json
from pathlib import Path

from research_framework.pipeline.cycle_summary import write_summary


def _seed(vault: Path, cycle: int) -> None:
    cycles = vault / "_pipeline" / "cycles"
    cycles.mkdir(parents=True, exist_ok=True)
    (cycles / f"cycle-{cycle:03d}-scout.json").write_text(
        json.dumps(
            {
                "topics_found": {
                    "new": [
                        {"title": "Topic A"},
                        {"title": "Topic B"},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    (cycles / f"cycle-{cycle:03d}-research.json").write_text(
        json.dumps(
            {
                "notes_created": ["data_vault/01 - Concepts/Topic A.md"],
                "notes_updated": ["data_vault/05 - Data Stores/Existing.md"],
                "topics_found": {"existing": ["Topic X"]},
                "cumulative_cost_usd": 1.23,
                "capture_failures": [
                    # Ten different GitHub URLs with identical reason — should
                    # collapse to a single "github.com × 10" line.
                    *[
                        {
                            "url": f"https://github.com/acme/foo/pull/{i}",
                            "reason": "python scripts/raw_capture.py exited 1 "
                            "with network error",
                        }
                        for i in range(10)
                    ],
                    {
                        "url": "https://other.example.org/page",
                        "reason": "HTTP 503",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (cycles / f"cycle-{cycle:03d}-quality-report.json").write_text(
        json.dumps(
            {
                "gates": {
                    "SG-001": {
                        "gate_id": "SG-001",
                        "status": "PASS",
                        "message": "ok",
                    },
                    "SG-005": {
                        "gate_id": "SG-005",
                        "status": "FAIL",
                        "message": "batch 9: zero notes",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    (vault / "_pipeline" / f"cycle-{cycle:03d}-skill-check.json").write_text(
        json.dumps({"scanned": 24, "repaired": [], "unrecoverable": [], "ok": True}),
        encoding="utf-8",
    )


def test_write_summary_aggregates_capture_failures(tmp_path: Path) -> None:
    _seed(tmp_path, cycle=6)
    out = write_summary(tmp_path, 6, exit_code=0)
    text = out.read_text(encoding="utf-8")

    # The 10 github.com URLs collapse to ONE bullet showing the count.
    assert "github.com" in text
    assert "× 10" in text
    # The unique other.example.org failure still appears.
    assert "other.example.org" in text


def test_write_summary_reports_failed_gates(tmp_path: Path) -> None:
    _seed(tmp_path, cycle=6)
    out = write_summary(tmp_path, 6, exit_code=2, exit_reason="cycle aborted")
    text = out.read_text(encoding="utf-8")

    assert "SG-005" in text
    assert "batch 9: zero notes" in text
    assert "ABORT" in text
    assert "cycle aborted" in text


def test_write_summary_lists_notes_created_and_updated(tmp_path: Path) -> None:
    _seed(tmp_path, cycle=6)
    out = write_summary(tmp_path, 6, exit_code=0)
    text = out.read_text(encoding="utf-8")

    assert "Notes created: **1**" in text
    assert "Notes updated: **1**" in text
    assert "Cumulative cost: $1.23" in text


def test_write_summary_handles_missing_sidecars(tmp_path: Path) -> None:
    # Bare vault: no scout/research/quality JSONs at all. The summary must
    # still write something rather than raise (early-abort cycles need a
    # diagnostic file to look at).
    (tmp_path / "_pipeline" / "cycles").mkdir(parents=True)
    out = write_summary(tmp_path, 1, exit_code=2, exit_reason="missing scout report")
    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    assert "ABORT" in text
    assert "missing scout report" in text
