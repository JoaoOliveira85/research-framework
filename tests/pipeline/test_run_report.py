"""Tests for ``research_framework.pipeline.run_report``."""

from __future__ import annotations

import json
from pathlib import Path

from research_framework.pipeline.run_report import write_run_report


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _seed_cycle(
    vault_dir: Path,
    cycle: int,
    *,
    notes_created: list[str],
    notes_updated: list[str],
    topics_new: list[str],
    stage_durations: list[tuple[str, float]],
    cost_sidecars: list[dict],
    exit_code: int = 0,
) -> None:
    cycles_dir = vault_dir / "_pipeline" / "cycles"
    c3 = f"{cycle:03d}"

    _write(
        cycles_dir / f"cycle-{c3}-timings.json",
        {
            "schema_version": "1",
            "cycle": cycle,
            "started_at": "2026-05-17T10:00:00Z",
            "total_duration_s": sum(d for _, d in stage_durations),
            "exit_code": exit_code,
            "stages": [
                {"stage": name, "started_at": "2026-05-17T10:00:00Z", "duration_s": d}
                for name, d in stage_durations
            ],
        },
    )
    _write(
        cycles_dir / f"cycle-{c3}-research.json",
        {
            "schema_version": "2.0",
            "cycle": cycle,
            "phase": "research",
            "notes_created": notes_created,
            "notes_updated": notes_updated,
        },
    )
    _write(
        cycles_dir / f"cycle-{c3}-scout.json",
        {
            "schema_version": "2.0",
            "cycle": cycle,
            "phase": "scout",
            "topics_found": {
                "new": topics_new,
                "existing": [],
                "total": len(topics_new),
            },
        },
    )
    agent_calls = cycles_dir / f"cycle-{c3}" / "agent-calls"
    agent_calls.mkdir(parents=True, exist_ok=True)
    for i, payload in enumerate(cost_sidecars, start=1):
        stage_name = payload.pop("_stage", f"stage{i}")
        sidecar_payload = {
            "schema_version": "1.1",
            "cost_usd": payload.get("cost_usd", 0.0),
            "tokens_in": payload.get("input_tokens", payload.get("tokens_in", 0)),
            "tokens_out": payload.get("output_tokens", payload.get("tokens_out", 0)),
            "cache_read_input_tokens": payload.get("cache_read_input_tokens", 0),
            "cache_creation_input_tokens": payload.get(
                "cache_creation_input_tokens", 0
            ),
        }
        filename = (
            f"{stage_name}-batch-{i}.json"
            if stage_name == "research"
            else f"{stage_name}.json"
        )
        _write(agent_calls / filename, sidecar_payload)


def test_writes_report_with_grand_totals(tmp_path: Path) -> None:
    _seed_cycle(
        tmp_path,
        cycle=1,
        notes_created=["a.md", "b.md"],
        notes_updated=["c.md"],
        topics_new=["topic-x", "topic-y", "topic-z"],
        stage_durations=[("Step 1 - scout", 12.5), ("Step 3 - research", 47.2)],
        cost_sidecars=[
            {
                "_stage": "scout",
                "cost_usd": 0.42,
                "input_tokens": 1000,
                "output_tokens": 500,
                "cache_read_input_tokens": 800,
            },
            {
                "_stage": "research",
                "cost_usd": 1.08,
                "input_tokens": 6000,
                "output_tokens": 2400,
                "cache_read_input_tokens": 4500,
            },
        ],
    )

    path = write_run_report(
        tmp_path,
        final_exit_code=0,
        final_exit_reason="vault complete — coverage met",
    )

    assert path == tmp_path / "_pipeline" / "run-report.md"
    text = path.read_text(encoding="utf-8")
    assert "# Run report" in text
    assert "Run exit**: CONTINUE" in text
    assert "vault complete" in text
    assert "Cycles run: **1**" in text
    assert "Notes created: **2**" in text
    assert "Notes updated: **1**" in text
    assert "New scout topics: **3**" in text
    # Cost total = 0.42 + 1.08 = $1.50
    assert "$1.50" in text
    # Token totals = 7,000 input / 2,900 output
    assert "7,000" in text
    assert "2,900" in text
    # Per-cycle table row
    assert "| 1 " in text
    # Top stage shows Step 3 first (longer)
    assert "Step 3 - research" in text


def test_handles_missing_sidecars_gracefully(tmp_path: Path) -> None:
    cycles_dir = tmp_path / "_pipeline" / "cycles"
    cycles_dir.mkdir(parents=True)
    # Only a research.json — no timings, no scout, no cost sidecar.
    _write(
        cycles_dir / "cycle-002-research.json",
        {"schema_version": "2.0", "notes_created": ["only.md"]},
    )

    path = write_run_report(tmp_path, final_exit_code=1, final_exit_reason="test")
    text = path.read_text(encoding="utf-8")
    assert "Cycles run: **1**" in text
    # No timings → wall column is "—"
    assert "| — " in text
    # Cost defaults to $0.0000
    assert "$0.0000" in text
    # No stage section rendered (timings absent)
    assert "_no timings sidecars recorded_" in text


def test_writes_empty_run_with_no_cycles(tmp_path: Path) -> None:
    path = write_run_report(tmp_path, final_exit_code=0, final_exit_reason="empty")
    text = path.read_text(encoding="utf-8")
    assert "Cycles run: **0**" in text
    assert "_no cycles ran_" in text


def test_exit_label_maps_correctly(tmp_path: Path) -> None:
    _seed_cycle(
        tmp_path,
        cycle=3,
        notes_created=[],
        notes_updated=[],
        topics_new=[],
        stage_durations=[("Step 1", 1.0)],
        cost_sidecars=[],
        exit_code=1,
    )
    path = write_run_report(tmp_path, final_exit_code=2, final_exit_reason="boom")
    text = path.read_text(encoding="utf-8")
    assert "Run exit**: ABORT" in text
    # Cycle 3's own exit was TERMINATE (rc=1)
    assert "TERMINATE" in text


def test_multi_cycle_aggregation(tmp_path: Path) -> None:
    for n in (1, 2, 3):
        _seed_cycle(
            tmp_path,
            cycle=n,
            notes_created=[f"n{n}.md"],
            notes_updated=[],
            topics_new=[f"t{n}"],
            stage_durations=[("Step 1", 10.0 * n), ("Step 3", 5.0 * n)],
            cost_sidecars=[
                {"_stage": "scout", "cost_usd": 0.10 * n, "input_tokens": 100 * n}
            ],
        )
    path = write_run_report(tmp_path, final_exit_code=0, final_exit_reason="ok")
    text = path.read_text(encoding="utf-8")
    # 3 cycles, 3 notes created total
    assert "Cycles run: **3**" in text
    assert "Notes created: **3**" in text
    # Cost total = 0.10 + 0.20 + 0.30 = $0.60
    assert "$0.60" in text
    # Total tokens input = 600
    assert "600" in text


def test_a_report_that_cannot_be_written_leaves_the_previous_one_in_place(
    tmp_path: Path,
) -> None:
    """A failed rewrite must not cost the operator the report already there.

    ``Path.write_text`` truncates the file and only then encodes. An exit
    reason carrying a lone surrogate — what a file name that is not UTF-8
    becomes inside an error message — cannot be encoded, so the rewrite left a
    zero-byte ``run-report.md`` behind, and ``write_run_report`` swallows the
    error by design, so nothing said the report was gone.
    """
    _seed_cycle(
        tmp_path,
        cycle=1,
        notes_created=["a.md"],
        notes_updated=[],
        topics_new=["t"],
        stage_durations=[("Step 1", 1.0)],
        cost_sidecars=[],
    )
    path = write_run_report(tmp_path, final_exit_code=0, final_exit_reason="ok")
    before = path.read_text(encoding="utf-8")
    assert "Run exit" in before

    write_run_report(
        tmp_path, final_exit_code=2, final_exit_reason="cannot read b\udcffd.md"
    )

    assert path.read_text(encoding="utf-8") == before
