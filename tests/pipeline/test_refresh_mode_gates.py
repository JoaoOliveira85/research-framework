"""``no new topics`` is a legitimate outcome when the cycle has update work
(spec 087 US4, FR-017): the scout gates, Condition B and the loop's fuel."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from research_framework.pipeline import backlog, currency, orchestrator
from research_framework.pipeline.gates_step import SG001_topics_new_nonempty
from research_framework.spec.schema import NoteTypeConfig, SpecConfig
from tests._helpers.vault_factory import build_minimal_vault, commit_vault

REPO = Path(__file__).resolve().parents[2]
SPEC = SpecConfig.from_dict({"name": "g", "owner": "t"})


def _report(n_new: int) -> dict[str, Any]:
    return {
        "topics_found": {
            "new": [{"title": f"T{i}", "coverage_category": "c"} for i in range(n_new)]
        }
    }


def test_sg001_passes_with_no_new_topics_in_refresh() -> None:
    result = SG001_topics_new_nonempty(
        _report(0), SPEC, 124, new_wanted=0, updates_planned=37
    )

    assert result.status == "PASS"
    assert "no new topics were asked for" in result.message
    # new topics nobody asked for are not a failure either
    assert (
        SG001_topics_new_nonempty(
            _report(3), SPEC, 124, new_wanted=0, updates_planned=37
        ).status
        == "PASS"
    )


def test_sg001_warns_when_new_topics_were_wanted_but_updates_are_planned() -> None:
    result = SG001_topics_new_nonempty(
        _report(0), SPEC, 124, new_wanted=87, updates_planned=37
    )

    assert result.status == "WARN"
    assert "37 planned update(s)" in result.message
    assert result.metric_value == 0 and result.threshold == 87


def test_sg001_still_fails_with_nothing_to_do() -> None:
    result = SG001_topics_new_nonempty(
        _report(0), SPEC, 124, new_wanted=87, updates_planned=0
    )
    assert result.status == "FAIL" and result.correction_hint
    # and with no split information at all it is exactly the old gate
    assert SG001_topics_new_nonempty(_report(0), SPEC, 5).status == "FAIL"
    assert SG001_topics_new_nonempty(_report(2), SPEC, 5).status == "WARN"
    assert SG001_topics_new_nonempty(_report(5), SPEC, 5).status == "PASS"
    with pytest.raises(ValueError):
        SG001_topics_new_nonempty(_report(1), SPEC, 0)


def test_sg001_compares_against_the_new_topic_share_not_the_whole_quota() -> None:
    # 20 topics against a cycle quota of 124 that includes 37 updates: the new
    # share is 87 of it... and when the split asks for 20, 20 topics MEET it.
    meets = SG001_topics_new_nonempty(
        _report(20), SPEC, 124, new_wanted=20, updates_planned=37
    )
    assert meets.status == "PASS" and meets.threshold == 20
    short = SG001_topics_new_nonempty(
        _report(20), SPEC, 124, new_wanted=87, updates_planned=37
    )
    assert short.status == "WARN" and short.threshold == 87
    assert SG001_topics_new_nonempty(_report(20), SPEC, 124).status == "WARN"


def test_the_gate_expectations_follow_the_mode_and_the_vault(tmp_path: Path) -> None:
    vault = build_minimal_vault(
        tmp_path,
        num_categories=1,
        num_targets_per_category=20,
        max_cycles=1,
        spec_overrides={
            "note_types": [
                NoteTypeConfig(
                    name="concept",
                    description="d",
                    folder="01 - Concepts",
                    min_word_count=30,
                    review_after_days=30,
                )
            ]
        },
    )
    spec = SpecConfig.from_dict(
        json.loads((vault / "_pipeline" / "spec-parse.json").read_text("utf-8"))
    )
    assert backlog.update(
        vault,
        "review",
        lambda tx: [tx.observe_update(f"n{i}", "review_due") for i in range(5)],
    )
    commit_vault(vault)

    import dataclasses

    refresh = dataclasses.replace(spec, research_mode="refresh")
    assert currency.cycle_expectations(vault, refresh, 10) == (0, 5)
    bootstrap = dataclasses.replace(spec, research_mode="bootstrap")
    assert currency.cycle_expectations(vault, bootstrap, 10) == (10, 0)
    new_wanted, planned = currency.cycle_expectations(vault, spec, 10)
    assert (new_wanted, planned) == (7, 3)  # the 70 / 30 split
    # the scout's own updates rows count as work too
    assert currency.cycle_expectations(vault, refresh, 10, scout_updates=2) == (0, 7)


# --- Condition B ----------------------------------------------------------


@pytest.fixture(scope="module")
def vc() -> Any:
    path = REPO / "scripts" / "validate_cycle.py"
    spec = importlib.util.spec_from_file_location("_vc_refresh", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def _research_report(update_work: dict | None) -> dict[str, Any]:
    report: dict[str, Any] = {
        "cycle": 1,
        "phase": "research",
        "timestamp": "2026-11-23T00:00:00Z",
        "sources_consulted": {},
        "topics_found": {"new": [], "existing": [], "total": 0},
        "cost_estimate_usd": 0.0,
        "cumulative_cost_usd": 0.0,
        "notes_created": [],
        "notes_updated": [],
    }
    if update_work is not None:
        report["update_work"] = update_work
    return report


def _termination(vc: Any, report: dict) -> Any:
    return vc.check_termination(report, None, [], [], 10, 0.0, None)


def test_termination_does_not_call_a_cycle_with_update_work_source_exhausted(
    vc: Any,
) -> None:
    exhausted = _termination(vc, _research_report(None))
    assert exhausted.status == "TERMINATE" and "Condition B" in exhausted.reason

    # updates worked and more are queued: the cycle goes on
    going = _termination(
        vc, _research_report({"worked": 3, "failed": 0, "open_after": 5})
    )
    assert going.status == "CONTINUE" and "update work" in going.reason

    # everything queued has been worked: nothing is left, Condition B stands
    done = _termination(
        vc, _research_report({"worked": 3, "failed": 0, "open_after": 0})
    )
    assert done.status == "TERMINATE"
    # updates all failed: no progress, so no reprieve (the attempts limit bounds it)
    stuck = _termination(
        vc, _research_report({"worked": 0, "failed": 2, "open_after": 4})
    )
    assert stuck.status == "TERMINATE"

    # the v2 report's own "termination_condition: B" is not exempt either
    v2 = {
        "schema_version": "2",
        "cycle": 1,
        "phase": "research",
        "timestamp": "2026-11-23T00:00:00Z",
        "sources_consulted": [],
        "budget_consumed_usd": 0.0,
        "termination_condition": "B",
    }
    assert vc.check_termination_v2(v2, 10, 0.0, None, None).status == "TERMINATE"
    v2["update_work"] = {"worked": 1, "failed": 0, "open_after": 2}
    assert vc.check_termination_v2(v2, 10, 0.0, None, None).status == "CONTINUE"


# --- the loop ---------------------------------------------------------------


def _write_report(vault: Path, cycle: int, **doc: Any) -> None:
    path = vault / "_pipeline" / "cycles" / f"cycle-{cycle:03d}-research.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def test_an_update_only_cycle_is_progress_and_fuel_only_while_it_holds(
    tmp_path: Path,
) -> None:
    held = {"worked": 1, "failed": 0, "open_after": 3}
    _write_report(
        tmp_path,
        1,
        notes_created=[],
        notes_updated=[],  # a `confirmed` outcome writes no note
        update_outcome_results=[
            {"note": "n", "status": "passed", "outcome": "confirmed"}
        ],
        update_work=held,
    )
    assert orchestrator._cycle_made_progress(tmp_path, 1) is True
    assert orchestrator._update_fuel(tmp_path, 1) is True

    _write_report(
        tmp_path,
        2,
        notes_created=[],
        notes_updated=[],
        update_outcome_results=[{"note": "n", "status": "failed"}],
        update_work={"worked": 0, "failed": 1, "open_after": 3},
    )
    assert orchestrator._cycle_made_progress(tmp_path, 2) is False  # all failed
    assert orchestrator._update_fuel(tmp_path, 2) is False

    _write_report(tmp_path, 3, update_work={"worked": 2, "failed": 0, "open_after": 0})
    assert orchestrator._update_fuel(tmp_path, 3) is False  # nothing left to do
    assert orchestrator._update_fuel(tmp_path, 4) is False  # no report at all


def test_the_scout_prompt_in_refresh_mode_says_no_new_topics_are_wanted(
    tmp_path: Path,
) -> None:
    import dataclasses

    from research_framework.generator.templates import render_scout_prompt
    from research_framework.spec.parser import parse

    base = parse(REPO / "tests" / "fixtures" / "specs" / "code-first-vault-spec.md")

    def render(mode: str) -> str:
        vault = tmp_path / mode
        (vault / "_pipeline" / "prompts").mkdir(parents=True)
        spec = dataclasses.replace(base, research_mode=mode)
        return render_scout_prompt(
            spec, vault, existing_notes=["Kafka Streams.md"]
        ).read_text(encoding="utf-8")

    refresh = render("refresh")
    assert "NO new topics are wanted" in refresh
    assert "Leave `topics_found.new` EMPTY" in refresh
    assert "`topics_found.updates`" in refresh
    assert "70%" not in refresh  # the focus rule is for new topics
    assert "MUST be non-empty" not in refresh
    assert "SG-002 diversity gate" not in refresh
    assert "- Kafka Streams.md" in refresh  # what to look for updates about

    expand = render("expand")
    assert "NO new topics are wanted" not in expand
    assert "70%" in expand
    assert "MUST be non-empty" in expand
