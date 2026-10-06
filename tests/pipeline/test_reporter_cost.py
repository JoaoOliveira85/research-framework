"""Tier-3 cycle cost report tests (spec 033)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from research_framework.pipeline.budget_guard import (
    ApprovalDecision,
    CycleSpendTally,
    record_approval_decision,
    refresh_actuals,
)
from research_framework.pipeline.reporter import append_cycle_cost_report
from research_framework.pipeline.settings import LimitsSettings

_FIXTURE_VAULT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "cost_enforcement" / "vault"
)


def _report_payload(vault: Path, cycle: int) -> dict:
    text = (vault / "_pipeline/cycles" / f"cycle-{cycle:03d}-report.md").read_text(
        encoding="utf-8"
    )
    start = text.index("```json") + len("```json")
    end = text.index("```", start)
    return json.loads(text[start:end].strip())


def test_cycle_report_includes_approval_gates_fired_and_tty_mode(
    tmp_path: Path, monkeypatch
) -> None:
    """Issue #235: the rows come from the persisted decision record.

    This test used to pass ``approval_gates_fired=[...]`` straight into the
    reporter — a keyword no production caller ever supplied, so it proved only
    that the reporter could echo its own argument. The value now has exactly
    one source: a verdict the resume CLI recorded.
    """
    import shutil

    vault = tmp_path / "vault"
    shutil.copytree(_FIXTURE_VAULT, vault)
    record_approval_decision(
        vault,
        ApprovalDecision(
            stage_name="research",
            cycle_number=1,
            approved=True,
            decided_by_mode="headless",
        ),
    )
    tally = CycleSpendTally(cycle_num=1)
    limits = LimitsSettings(tier_thresholds={"basic": 0.05})
    append_cycle_cost_report(vault, 1, tally=tally, limits=limits)
    payload = _report_payload(vault, 1)
    assert payload["approval_gates_fired"] == [
        {
            "stage": "research",
            "approved": True,
            "decided_at": payload["approval_gates_fired"][0]["decided_at"],
            "decided_by_mode": "headless",
        }
    ]
    assert "tty_mode" in payload


def test_cycle_report_includes_tier_cost_warnings_fields(tmp_path: Path) -> None:
    import shutil

    vault = tmp_path / "vault"
    shutil.copytree(_FIXTURE_VAULT, vault)
    tally = CycleSpendTally(cycle_num=1)
    limits = LimitsSettings(tier_thresholds={"basic": 0.05, "standard": 0.05})
    append_cycle_cost_report(vault, 1, tally=tally, limits=limits)
    payload = _report_payload(vault, 1)
    assert payload["tier_cost_warnings"]
    row = payload["tier_cost_warnings"][0]
    assert {"stage", "tier", "cost_usd", "threshold", "delta"} <= set(row.keys())


def test_cycle_report_fr011_per_stage_and_per_tier_breakdown(tmp_path: Path) -> None:
    import shutil

    vault = tmp_path / "vault"
    shutil.copytree(_FIXTURE_VAULT, vault)
    tally = CycleSpendTally(cycle_num=1)
    refresh_actuals(vault, 1, tally)
    limits = LimitsSettings()
    append_cycle_cost_report(vault, 1, tally=tally, limits=limits)
    payload = _report_payload(vault, 1)
    assert payload["per_stage_breakdown"]
    assert payload["per_tier_breakdown"]


def test_cycle_report_includes_estimation_methods_used(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    tally = CycleSpendTally(cycle_num=1)
    tally.estimation_methods_used.append(
        {"stage": "scout", "method": "default_ceiling"}
    )
    limits = LimitsSettings()
    append_cycle_cost_report(vault, 1, tally=tally, limits=limits)
    payload = _report_payload(vault, 1)
    assert payload["estimation_methods_used"] == [
        {"stage": "scout", "method": "default_ceiling"}
    ]


def test_cycle_report_fr011_full_cost_summary_sections(tmp_path: Path) -> None:
    import shutil

    vault = tmp_path / "vault"
    shutil.copytree(_FIXTURE_VAULT, vault)
    sources = vault / "_pipeline/sources/mod/cache-stats.json"
    sources.parent.mkdir(parents=True)
    sources.write_text(
        json.dumps({"cache_hits": 8, "cache_misses": 2}),
        encoding="utf-8",
    )
    tally = CycleSpendTally(cycle_num=1)
    limits = LimitsSettings()
    append_cycle_cost_report(vault, 1, tally=tally, limits=limits)
    payload = _report_payload(vault, 1)
    assert payload["cumulative_spend_usd"] is not None
    assert payload["cache_summary"]["status"] == "ok"


def test_phase1_report_skips_cycle_json_that_is_not_an_object(
    tmp_path: Path,
) -> None:
    """``cycle-NNN-step-gates.json`` is a JSON list and matches the reporter's
    ``cycle-*-*.json`` glob. Calling ``.get`` on it crashed Phase 3 on every
    vault that had scout gate records."""
    from research_framework.pipeline.reporter import generate_report

    cycles = tmp_path / "_pipeline" / "cycles"
    cycles.mkdir(parents=True)
    (cycles / "cycle-001-research.json").write_text(
        json.dumps({"notes_created": ["a.md", "b.md"]}), encoding="utf-8"
    )
    (cycles / "cycle-001-step-gates.json").write_text(
        json.dumps([{"gate_id": "SG-001", "verdict": "PASS"}]), encoding="utf-8"
    )

    out = generate_report(tmp_path)

    text = out.read_text(encoding="utf-8")
    assert "| 1 | research | 2 | 0 |" in text
    assert "step" not in text.split("## Coverage Status")[0]


def _bad_counts(path: Path) -> None:
    path.write_text(
        json.dumps({"notes_created": None, "dimensions_covered": 3}),
        encoding="utf-8",
    )


def _not_utf8(path: Path) -> None:
    path.write_bytes(b'{"notes_created": ["caf\xe9.md"]}')


def _unreadable(path: Path) -> None:
    path.mkdir()


@pytest.mark.parametrize(
    ("write_bad", "bad_row"),
    [
        (_bad_counts, "| 2 | research | 0 | 0 |"),
        (_not_utf8, None),
        (_unreadable, None),
    ],
    ids=["null-and-number-counts", "not-utf8", "unreadable"],
)
def test_phase1_report_survives_a_malformed_cycle_file(
    write_bad: Callable[[Path], None], bad_row: str | None, tmp_path: Path
) -> None:
    """``len(data.get("notes_created", []))`` raised on ``null`` or a number,
    and only ``JSONDecodeError`` was caught around the read, so one bad cycle
    file meant no Phase 3 report at all. A count that is not a list reads as 0;
    a file that cannot be read or decoded is skipped like malformed JSON."""
    from research_framework.pipeline.reporter import generate_report

    cycles = tmp_path / "_pipeline" / "cycles"
    cycles.mkdir(parents=True)
    (cycles / "cycle-001-research.json").write_text(
        json.dumps({"notes_created": ["a.md", "b.md"]}), encoding="utf-8"
    )
    write_bad(cycles / "cycle-002-research.json")

    text = generate_report(tmp_path).read_text(encoding="utf-8")

    summary = text.split("## Coverage Status")[0]
    assert "| 1 | research | 2 | 0 |" in summary
    if bad_row is None:
        assert "\n| 2 | research |" not in summary
    else:
        assert bad_row in summary
