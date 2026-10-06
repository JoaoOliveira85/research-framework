"""`--max-usd` / `--max-cycles` are LIFETIME ceilings, and now say so (#239).

Spec 070 open questions 4/4a filed this and nobody fixed it: both flags read
as per-run budgets — the help text literally said "Per-run" — and both are in
fact lifetime ceilings, so "give it $10" is unachievable on a vault that has
already spent more. The evidence is in the code, not the prose:

* ``orchestrator.run_cycles`` compares against
  ``_cumulative_sidecar_cost(vault_dir, up_to=cycle)``, which sums cycles
  ``1..cycle`` — every cycle the vault ever ran, not this process's.
* ``for cycle in range(start_cycle, max_cycles + 1)`` makes ``--max-cycles``
  an absolute cycle NUMBER ceiling; spec 070 F5 already says so in an error
  message the flag's own help contradicted.

The fix is deliberately additive (the issue's own proposal): the two existing
flags keep their meaning and gain honest help, and two new flags give the
per-run reading its own name.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from research_framework.cli import build_parser
from research_framework.cli._budget_resolve import (
    BudgetError,
    resolve_cycle_budget,
)


def _flag_help(verb: str, flag: str) -> str:
    parser = build_parser()
    sub = next(
        a
        for a in parser._actions
        if hasattr(a, "choices") and isinstance(a.choices, dict) and verb in a.choices
    )
    action = next(
        a for a in sub.choices[verb]._actions if flag in (a.option_strings or [])
    )
    return action.help or ""


# --- the help text must stop promising the other semantics -----------------


@pytest.mark.parametrize("flag", ["--max-cycles", "--max-usd"])
def test_lifetime_flags_no_longer_advertise_themselves_as_per_run(flag: str) -> None:
    text = _flag_help("generate", flag).lower()
    assert "per-run" not in text, (
        f"`{flag}`'s help still says 'per-run'; the guard treats it as a "
        "lifetime ceiling and the two must agree (#239)."
    )
    assert "lifetime" in text, f"`{flag}`'s help must name the semantics it has"


@pytest.mark.parametrize("flag", ["--more-cycles", "--max-usd-this-run"])
def test_per_run_flags_exist_and_say_so(flag: str) -> None:
    text = _flag_help("generate", flag).lower()
    assert "this run" in text or "per-run" in text


def test_budget_cap_help_names_the_ladder() -> None:
    text = _flag_help("cycle", "--budget-cap").lower()
    assert "lifetime" in text


# --- --more-cycles: N more cycles from wherever the vault stands -----------


def test_more_cycles_is_relative_to_the_resume_anchor() -> None:
    res = resolve_cycle_budget({}, flag_more_cycles=3, start_cycle=7)
    assert res.max_cycles == 9, "cycles 7, 8, 9 — three more from here"
    assert res.max_cycles_source == "flag"


def test_more_cycles_leaves_no_second_copy_of_the_ceiling() -> None:
    """It is an INPUT to the ceiling, not a field beside it.

    A ``more_cycles`` attribute would be a number no consumer reads — the
    shape issue #235 called out ("a parameter no caller passes is the defect
    itself"), and the shape #329's parser-flag guard exists to keep out.
    """
    res = resolve_cycle_budget({}, flag_more_cycles=3, start_cycle=7)
    assert not hasattr(res, "more_cycles")


def test_more_cycles_from_a_fresh_vault_is_just_a_count() -> None:
    res = resolve_cycle_budget({}, flag_more_cycles=2, start_cycle=1)
    assert res.max_cycles == 2


def test_more_cycles_beats_settings() -> None:
    res = resolve_cycle_budget(
        {"pipeline": {"max_cycles": 3}}, flag_more_cycles=2, start_cycle=6
    )
    assert res.max_cycles == 7


def test_more_cycles_and_max_cycles_together_is_a_usage_error() -> None:
    with pytest.raises(BudgetError) as exc:
        resolve_cycle_budget({}, flag_max_cycles=5, flag_more_cycles=2)
    assert "--more-cycles" in str(exc.value) and "--max-cycles" in str(exc.value)


@pytest.mark.parametrize("bad", [0, -1, True])
def test_more_cycles_must_be_a_positive_int(bad: object) -> None:
    with pytest.raises(BudgetError):
        resolve_cycle_budget({}, flag_more_cycles=bad)  # type: ignore[arg-type]


def test_absent_more_cycles_leaves_the_ladder_untouched() -> None:
    res = resolve_cycle_budget({"pipeline": {"max_cycles": 4}}, start_cycle=9)
    assert res.max_cycles == 4
    assert res.max_cycles_source == "settings"


# --- --max-usd-this-run: a per-run dollar ceiling on top of the lifetime one


def test_max_usd_this_run_is_flag_only_and_defaults_to_absent() -> None:
    res = resolve_cycle_budget({"pipeline": {"budget_usd": 5.0}})
    assert res.max_usd == pytest.approx(5.0)
    assert res.max_usd_this_run is None


def test_max_usd_this_run_is_independent_of_the_lifetime_cap() -> None:
    res = resolve_cycle_budget(
        {"pipeline": {"budget_usd": 40.0}}, flag_max_usd_this_run=10.0
    )
    assert res.max_usd == pytest.approx(40.0)
    assert res.max_usd_this_run == pytest.approx(10.0)


def test_max_usd_this_run_zero_is_unlimited_like_every_other_zero() -> None:
    """FR3-Z2: one ladder cannot hold two meanings of zero."""
    res = resolve_cycle_budget({}, flag_max_usd_this_run=0)
    assert res.max_usd_this_run is None


def test_max_usd_this_run_rejects_a_negative() -> None:
    with pytest.raises(BudgetError) as exc:
        resolve_cycle_budget({}, flag_max_usd_this_run=-0.5)
    assert "--max-usd-this-run" in str(exc.value)


# --- the run ceiling actually stops a run ----------------------------------


def _spec(vault_dir: Path):
    from research_framework.spec.schema import (
        BudgetConfig,
        CoverageCategory,
        CoverageTargets,
        NoteTypeConfig,
        ScopeConfig,
        SpecConfig,
    )

    return SpecConfig(
        name="run-budget-test",
        location=vault_dir,
        owner="test",
        scope=ScopeConfig(domain="d", organization="o"),
        note_types=[
            NoteTypeConfig(
                name="service",
                description="d",
                folder="01 - Services",
                authoritative_role="behaviour",
            )
        ],
        data_sources=[],
        search_dimensions=["domain"],
        coverage_targets=CoverageTargets(
            categories=[
                CoverageCategory(name="services", note_type="service", target_count=3)
            ]
        ),
        budget=BudgetConfig(),
    )


def _sidecar(vault: Path, cycle: int, cost: float, name: str) -> None:
    calls = vault / "_pipeline" / "cycles" / f"cycle-{cycle:03d}" / "agent-calls"
    calls.mkdir(parents=True, exist_ok=True)
    (calls / f"{name}.json").write_text(
        json.dumps(
            {
                "schema_version": "1.1",
                "stage": "scout",
                "agent": "claude",
                "agent_kind": "fake",
                "tier": "standard",
                "status": "ok",
                "exit_code": 0,
                "cost_usd": cost,
                "tokens_in": 1,
                "tokens_out": 1,
                "latency_ms": 1,
                "cycle": cycle,
            }
        ),
        encoding="utf-8",
    )


def _vault_with_history(tmp_path: Path, *, completed: int, spend: float) -> Path:
    from research_framework.pipeline.coverage import save_targets
    from research_framework.spec.schema import CoverageCategory, CoverageTargets

    vault = tmp_path / "vault"
    cycles = vault / "_pipeline" / "cycles"
    cycles.mkdir(parents=True)
    for n in range(1, completed + 1):
        (cycles / f"cycle-{n:03d}-quality-report.json").write_text(json.dumps({}))
        _sidecar(vault, n, spend / completed, "history")
    save_targets(
        vault,
        CoverageTargets(
            categories=[
                CoverageCategory(
                    name="services", note_type="service", target_count=3, met_count=1
                )
            ]
        ),
    )
    return vault


def _budget(**over):
    from research_framework.cli._budget_resolve import BudgetResolution

    kwargs = {
        "max_cycles": 20,
        "max_cycles_source": "flag",
        "max_usd": None,
        "max_usd_source": "default",
    }
    kwargs.update(over)
    return BudgetResolution(**kwargs)


def _stub_orchestrator(monkeypatch: pytest.MonkeyPatch, vault: Path, per_cycle: float):
    from research_framework.pipeline import orchestrator as orch

    ran: list[int] = []

    def _one_cycle(vault_dir, cycle_num, *args, **kwargs):
        ran.append(cycle_num)
        _sidecar(vault_dir, cycle_num, per_cycle, "run")
        (vault_dir / "_pipeline" / "cycles").mkdir(parents=True, exist_ok=True)
        (
            vault_dir / "_pipeline" / "cycles" / f"cycle-{cycle_num:03d}-scout.json"
        ).write_text(json.dumps({"topics_found": {"new": ["t"]}}), encoding="utf-8")
        return 0

    monkeypatch.setattr(orch, "run_single_cycle", _one_cycle)
    monkeypatch.setattr(orch, "merge_expected_filenames_from_scan", lambda _v: None)
    monkeypatch.setattr(orch, "_run_health_gate", lambda _v: [])
    monkeypatch.setattr(orch, "scan_stubs", lambda _v, _s: [])
    monkeypatch.setattr(orch, "all_targets_met", lambda _v: False)
    return ran


def test_run_ceiling_stops_a_run_the_lifetime_ceiling_would_have_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The whole point of #239: $8 already spent, "$2 more this run" is legal."""
    from research_framework.pipeline import orchestrator as orch

    vault = _vault_with_history(tmp_path, completed=4, spend=8.0)
    ran = _stub_orchestrator(monkeypatch, vault, per_cycle=1.5)

    with caplog.at_level(logging.INFO):
        rc = orch.run_cycles(
            _spec(vault),
            vault,
            start_cycle=5,
            resume=True,
            budget=_budget(max_usd=100.0, max_usd_this_run=2.0),
        )

    assert rc == 1, "constrained exit"
    assert ran == [5, 6], "two cycles at $1.50 crosses $2 of this run's spend"
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "run budget" in joined.lower()


def test_run_ceiling_absent_leaves_the_lifetime_guard_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from research_framework.pipeline import orchestrator as orch

    vault = _vault_with_history(tmp_path, completed=4, spend=8.0)
    ran = _stub_orchestrator(monkeypatch, vault, per_cycle=1.5)

    rc = orch.run_cycles(
        _spec(vault),
        vault,
        start_cycle=5,
        resume=True,
        budget=_budget(max_cycles=6, max_usd=9.0),
    )

    assert rc == 1
    assert ran == [5], "the LIFETIME cap ($9) trips first — 8.0 + 1.5 >= 9"


def test_run_ceiling_baseline_excludes_money_this_run_did_not_spend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A vault already past the run ceiling in LIFETIME terms must still run."""
    from research_framework.pipeline import orchestrator as orch

    vault = _vault_with_history(tmp_path, completed=4, spend=50.0)
    ran = _stub_orchestrator(monkeypatch, vault, per_cycle=0.25)

    rc = orch.run_cycles(
        _spec(vault),
        vault,
        start_cycle=5,
        resume=True,
        budget=_budget(max_cycles=6, max_usd_this_run=2.0),
    )

    assert rc == 1, "max_cycles constrained exit, not a budget one"
    assert ran == [5, 6], "$50 of history must not consume a $2 run ceiling"
