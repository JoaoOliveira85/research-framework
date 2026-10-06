"""report.json / report.md shape + dated-run retention (spec 056 §1–5; T016, T017, T032)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.benchmark import reporter


def _cells() -> list[dict]:
    return [
        {
            "task": "scout",
            "executor": "claude",
            "model": "sonnet",
            "status": "ok",
            "quality": 1.0,
            "quality_detail": {"topics_proposed": 4},
            "cost_usd": 0.041,
            "cost_source": "sidecar",
            "latency_ms": 5200,
            "artifact_dir": "cells/scout__claude__sonnet",
        },
        {
            "task": "note-writer",
            "executor": "codex",
            "model": "default",
            "status": "ok",
            "quality": 1.0,
            "quality_detail": {},
            "cost_usd": 0.021,
            "cost_source": "sidecar",
            "latency_ms": 4800,
            "artifact_dir": "cells/note-writer__codex__default",
        },
        {
            "task": "verifier",
            "executor": "claude",
            "model": "haiku",
            "status": "failed",
            "reason": "verifier output not valid JSON",
            "cost_usd": None,
            "cost_source": "n/a",
            "artifact_dir": "cells/verifier__claude__haiku",
        },
    ]


def _build(run_id: str = "20260603T143022Z") -> dict:
    return reporter.build_report(
        run_id=run_id,
        matrix_path=Path("tests/fixtures/benchmark/benchmark-matrix.yaml"),
        fixture_dir=Path("tests/fixtures/benchmark"),
        cells=_cells(),
        started_at="2026-06-03T14:30:22Z",
        completed_at="2026-06-03T14:45:10Z",
        estimated_usd=1.2,
        ack_mode="tty",
        max_usd=None,
    )


def test_report_json_schema(tmp_path: Path) -> None:
    """report.json carries the §2 top-level keys and §3 cell fields (FR-008)."""
    run_dir = reporter.create_run_dir(tmp_path, "20260603T143022Z")
    reporter.write_report(run_dir, _build())
    doc = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))

    assert doc["schema_version"] == "1.0"
    assert doc["run_id"] == "20260603T143022Z"
    assert doc["sample_count"] == 1
    assert set(doc["cost_gate"]) == {"estimated_usd", "ack_mode", "max_usd"}
    assert doc["cost_gate"]["ack_mode"] == "tty"
    assert len(doc["cells"]) == 3
    first = doc["cells"][0]
    for field in ("task", "executor", "model", "status", "cost_usd", "cost_source"):
        assert field in first
    # FR-013: a non-ok cell with no sidecar cost is null + n/a, never a fake $0.
    failed = next(c for c in doc["cells"] if c["status"] == "failed")
    assert failed["cost_usd"] is None
    assert failed["cost_source"] == "n/a"


def test_report_md_per_task_tables() -> None:
    """report.md has one section per task and NO cross-task aggregate (FR-015, SC-008)."""
    md = reporter.render_markdown(_build())
    for task in ("scout", "note-writer", "verifier"):
        assert f"## Task: `{task}`" in md
    assert md.count("## Task:") == 3
    # Per-task tables only — no blended leaderboard across tasks.
    lowered = md.lower()
    assert "overall" not in lowered
    assert "aggregate" not in lowered
    # Failures appendix surfaces the non-ok cell with its reason.
    assert "Failures & skips" in md
    assert "not valid JSON" in md


def test_second_run_preserves_first(tmp_path: Path) -> None:
    """Two run-ids coexist; a repeated run-id refuses to clobber (FR-009, SC-006)."""
    first = reporter.create_run_dir(tmp_path, "20260603T143022Z")
    reporter.write_report(first, _build("20260603T143022Z"))
    second = reporter.create_run_dir(tmp_path, "20260603T150000Z")
    reporter.write_report(second, _build("20260603T150000Z"))

    assert first.exists() and second.exists()
    assert (first / "report.json").is_file()
    assert (second / "report.json").is_file()
    with pytest.raises(FileExistsError):
        reporter.create_run_dir(tmp_path, "20260603T143022Z")


def test_run_id_format_validated(tmp_path: Path) -> None:
    """A malformed run-id is rejected before any directory is created."""
    with pytest.raises(ValueError, match="YYYYMMDDTHHMMSSZ"):
        reporter.create_run_dir(tmp_path, "not-a-timestamp")


def test_cost_summary_splits_measured_vs_estimated() -> None:
    """report.md keeps billed (sidecar) and fallback (estimated) dollars distinct (Copilot review)."""
    cells = [
        {
            "task": "scout",
            "executor": "claude",
            "model": "sonnet",
            "status": "ok",
            "quality": 1.0,
            "cost_usd": 0.04,
            "cost_source": "sidecar",
            "latency_ms": 1,
            "artifact_dir": "cells/a",
        },
        {
            "task": "scout",
            "executor": "cursor-agent",
            "model": "gpt-5",
            "status": "ok",
            "quality": 0.5,
            "cost_usd": 0.10,
            "cost_source": "estimated",
            "latency_ms": 1,
            "artifact_dir": "cells/b",
        },
    ]
    report = reporter.build_report(
        run_id="20260603T143022Z",
        matrix_path=Path("m.yaml"),
        fixture_dir=Path("f"),
        cells=cells,
        started_at="t0",
        completed_at="t1",
        estimated_usd=0.2,
        ack_mode="yes",
        max_usd=None,
    )
    md = reporter.render_markdown(report)
    assert "Measured (cost_source=sidecar)**: $0.0400" in md
    assert "Estimated fallback (cost_source=estimated)**: $0.1000" in md
    assert "Reported total (measured + estimated)**: $0.1400" in md
