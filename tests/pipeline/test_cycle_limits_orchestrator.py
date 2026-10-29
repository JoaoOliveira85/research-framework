"""Issue #33 at the orchestrator: an unlimited lifetime ceiling, a per-run cap.

``run_cycles`` iterated ``range(start_cycle, max_cycles + 1)``, so a ceiling of
``0`` would run nothing at all and log spec 070 F5's "nothing to do" error. A
``pipeline.max_cycles: 0`` vault must instead run until something else stops
it (coverage, fuel, the dollar cap). ``pipeline.cycles_per_run`` must stop a
run exactly where ``--more-cycles`` would: the cycle loop runs out, the exit is
the ordinary constrained one, and no cycle is marked aborted.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from research_framework.cli._budget_resolve import (
    BudgetResolution,
    resolve_cycle_budget_from_path,
)
from research_framework.pipeline.settings import DEFAULT_MAX_CYCLES


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
        name="cycle-limits-test",
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


def _sidecar(vault: Path, cycle: int, cost: float) -> None:
    calls = vault / "_pipeline" / "cycles" / f"cycle-{cycle:03d}" / "agent-calls"
    calls.mkdir(parents=True, exist_ok=True)
    (calls / "run.json").write_text(
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


def _vault(tmp_path: Path, *, completed: int = 0, pipeline: str = "") -> Path:
    from research_framework.pipeline.coverage import save_targets
    from research_framework.spec.schema import CoverageCategory, CoverageTargets

    vault = tmp_path / "vault"
    cycles = vault / "_pipeline" / "cycles"
    cycles.mkdir(parents=True)
    for n in range(1, completed + 1):
        (cycles / f"cycle-{n:03d}-quality-report.json").write_text(json.dumps({}))
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
    if pipeline:
        (vault / "settings.yaml").write_text(
            f"pipeline:\n  budget_usd: 0\n{pipeline}", encoding="utf-8"
        )
    return vault


def _stub_cycles(
    monkeypatch: pytest.MonkeyPatch, *, per_cycle: float = 0.0, rc: int = 0
) -> list[int]:
    """Every cycle has fuel and coverage is never met, so only a cap stops it."""
    from research_framework.pipeline import orchestrator as orch

    ran: list[int] = []

    def _one_cycle(vault_dir, cycle_num, *args, **kwargs):
        ran.append(cycle_num)
        if per_cycle:
            _sidecar(vault_dir, cycle_num, per_cycle)
        (
            vault_dir / "_pipeline" / "cycles" / f"cycle-{cycle_num:03d}-scout.json"
        ).write_text(json.dumps({"topics_found": {"new": ["t"]}}), encoding="utf-8")
        return rc

    monkeypatch.setattr(orch, "run_single_cycle", _one_cycle)
    monkeypatch.setattr(orch, "merge_expected_filenames_from_scan", lambda _v: None)
    monkeypatch.setattr(orch, "_run_health_gate", lambda _v: [])
    monkeypatch.setattr(orch, "scan_stubs", lambda _v, _s: [])
    monkeypatch.setattr(orch, "all_targets_met", lambda _v: False)
    return ran


def _budget(**over) -> BudgetResolution:
    kwargs = {
        "max_cycles": 0,
        "max_cycles_source": "settings",
        "max_usd": None,
        "max_usd_source": "default",
    }
    kwargs.update(over)
    return BudgetResolution(**kwargs)


def _aborted(vault: Path) -> list[Path]:
    return sorted((vault / "_pipeline" / "cycles").glob("cycle-*-aborted.json"))


# --- max_cycles: 0 ----------------------------------------------------------


def test_unlimited_ceiling_runs_past_the_default_until_another_cap_stops_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from research_framework.pipeline import orchestrator as orch

    vault = _vault(tmp_path)
    ran = _stub_cycles(monkeypatch, per_cycle=1.0)
    cycles = DEFAULT_MAX_CYCLES + 5

    rc = orch.run_cycles(_spec(vault), vault, budget=_budget(max_usd=float(cycles)))

    assert ran == list(range(1, cycles + 1)), "no cycle ceiling — the $ cap stopped it"
    assert rc == 1
    report = json.loads((vault / "_pipeline" / "run-report.json").read_text())
    assert "budget cap" in report["final_exit_reason"]


def test_unlimited_resume_far_past_any_old_ceiling_is_not_nothing_to_do(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """``start_cycle > 0`` must not trip spec 070 F5's empty-range diagnostic."""
    from research_framework.pipeline import orchestrator as orch

    vault = _vault(tmp_path, completed=40)
    ran = _stub_cycles(monkeypatch, per_cycle=1.0)

    with caplog.at_level(logging.WARNING):
        rc = orch.run_cycles(
            _spec(vault),
            vault,
            start_cycle=41,
            resume=True,
            budget=_budget(max_usd_this_run=2.0),
        )

    assert ran == [41, 42]
    assert rc == 1
    assert not [r for r in caplog.records if "nothing to do" in r.getMessage()]


def test_unlimited_ceiling_logs_unlimited_not_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from research_framework.pipeline import orchestrator as orch

    vault = _vault(tmp_path)
    _stub_cycles(monkeypatch, per_cycle=1.0)

    with caplog.at_level(logging.INFO):
        orch.run_cycles(_spec(vault), vault, budget=_budget(max_usd=1.0))

    starts = [
        r.getMessage() for r in caplog.records if "starting cycle" in r.getMessage()
    ]
    assert starts == ["[orchestrator] starting cycle 1/unlimited"]


# --- pipeline.cycles_per_run --------------------------------------------------


def test_cycles_per_run_from_settings_stops_cleanly_at_the_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No explicit budget: ``run_cycles`` resolves settings anchored at its start."""
    from research_framework.pipeline import orchestrator as orch

    vault = _vault(
        tmp_path, completed=25, pipeline="  max_cycles: 0\n  cycles_per_run: 2\n"
    )
    ran = _stub_cycles(monkeypatch)

    rc = orch.run_cycles(_spec(vault), vault, start_cycle=26, resume=True)

    assert ran == [26, 27]
    assert rc == 1, "the ordinary constrained exit, as --more-cycles gives"
    assert _aborted(vault) == [], "a per-run cap is not an abort"
    report = json.loads((vault / "_pipeline" / "run-report.json").read_text())
    assert report["cycle_budget"]["exit_status"] == "constrained"


def test_cycles_per_run_stops_where_more_cycles_would(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from research_framework.pipeline import orchestrator as orch

    outcomes = []
    for label, pipeline, flag in (
        ("setting", "  max_cycles: 0\n  cycles_per_run: 3\n", None),
        ("flag", "  max_cycles: 0\n", 3),
    ):
        vault = _vault(tmp_path / label, completed=9, pipeline=pipeline)
        ran = _stub_cycles(monkeypatch)
        budget = resolve_cycle_budget_from_path(
            vault / "settings.yaml", flag_more_cycles=flag, start_cycle=10
        )
        rc = orch.run_cycles(
            _spec(vault), vault, start_cycle=10, resume=True, budget=budget
        )
        report = json.loads((vault / "_pipeline" / "run-report.json").read_text())
        outcomes.append((list(ran), rc, report["final_exit_reason"], _aborted(vault)))

    assert outcomes[0] == outcomes[1]
    assert outcomes[0][0] == [10, 11, 12]


def test_a_cycle_terminating_at_the_per_run_cap_is_not_an_abort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Condition A at the cap returns TERMINATE (rc=1) from the cycle runner."""
    from research_framework.pipeline import orchestrator as orch

    vault = _vault(tmp_path, pipeline="  max_cycles: 0\n  cycles_per_run: 1\n")
    ran = _stub_cycles(monkeypatch, rc=1)

    rc = orch.run_cycles(_spec(vault), vault)

    assert ran == [1]
    assert rc == 1
    assert _aborted(vault) == []


# --- run_single_cycle backfills the ceiling anchored at its own cycle -------


def _ceiling_spy(seen: list[int]):
    def _run(
        vault_dir: Path,
        cycle_num: int,
        budget_cap: float | None = None,
        max_cycles: int | None = None,
        scripts_dir: Path | None = None,
    ) -> int:
        _ = vault_dir, cycle_num, budget_cap, scripts_dir
        seen.append(max_cycles)  # type: ignore[arg-type]
        return 1

    return _run


@pytest.mark.parametrize(
    ("pipeline", "expected"),
    [
        ("  max_cycles: 0\n", 0),
        ("  max_cycles: 0\n  cycles_per_run: 3\n", 9),
        ("  max_cycles: 8\n  cycles_per_run: 3\n", 8),
    ],
)
def test_run_single_cycle_backfills_the_ceiling_from_its_own_cycle(
    tmp_path: Path, pipeline: str, expected: int
) -> None:
    from research_framework.pipeline import orchestrator as orch

    vault = _vault(tmp_path, completed=6, pipeline=pipeline)
    seen: list[int] = []

    orch.run_single_cycle(vault, 7, cycle_runner=_ceiling_spy(seen))

    assert seen == [expected]


def test_cycle_runner_backfill_anchors_cycles_per_run_at_its_cycle(
    tmp_path: Path,
) -> None:
    """``run_cycle_steps`` called with no ceiling resolves the same way."""
    from research_framework.pipeline import cycle_runner

    vault = _vault(tmp_path, pipeline="  max_cycles: 0\n  cycles_per_run: 2\n")

    assert cycle_runner._resolved_budget(vault, None, None, cycle_num=30) == (0.0, 31)


def test_the_ceiling_a_cycles_per_run_run_passes_down_stays_constant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anchoring end to end: the run resolves k+N-1 ONCE and every cycle of it
    hands that same ceiling to the cycle runner. A per-cycle re-anchor would
    move the ceiling with each cycle and never stop the run."""
    from research_framework.pipeline import cycle_runner
    from research_framework.pipeline import orchestrator as orch

    vault = _vault(
        tmp_path, completed=9, pipeline="  max_cycles: 0\n  cycles_per_run: 3\n"
    )
    seen: list[tuple[int, int | None, int]] = []
    real_single_cycle = orch.run_single_cycle

    def _runner(
        vault_dir: Path,
        cycle_num: int,
        budget_cap: float | None = None,
        max_cycles: int | None = None,
        scripts_dir: Path | None = None,
    ) -> int:
        _ = scripts_dir
        resolved = cycle_runner._resolved_budget(
            vault_dir, budget_cap, max_cycles, cycle_num=cycle_num
        )[1]
        seen.append((cycle_num, max_cycles, resolved))
        (
            vault_dir / "_pipeline" / "cycles" / f"cycle-{cycle_num:03d}-scout.json"
        ).write_text(json.dumps({"topics_found": {"new": ["t"]}}), encoding="utf-8")
        return 1

    def _through_the_real_single_cycle(vault_dir, cycle, budget_cap, max_cycles, **kw):
        return real_single_cycle(
            vault_dir,
            cycle,
            budget_cap,
            max_cycles,
            resume=kw.get("resume", False),
            cycle_runner=_runner,
        )

    monkeypatch.setattr(orch, "run_single_cycle", _through_the_real_single_cycle)
    monkeypatch.setattr(orch, "merge_expected_filenames_from_scan", lambda _v: None)
    monkeypatch.setattr(orch, "_run_health_gate", lambda _v: [])
    monkeypatch.setattr(orch, "scan_stubs", lambda _v, _s: [])
    monkeypatch.setattr(orch, "all_targets_met", lambda _v: False)

    rc = orch.run_cycles(_spec(vault), vault, start_cycle=10, resume=True)

    assert rc == 1
    assert seen == [(10, 12, 12), (11, 12, 12), (12, 12, 12)]


# --- an unbounded multi-cycle run is refused (review of #33) ----------------


def _runaway_stubs(monkeypatch: pytest.MonkeyPatch, *, rc: int) -> list[int]:
    """The reviewer's probe: one stub the agent never fixes is enough fuel, the
    scout finds nothing, each cycle costs $1 and returns `rc`. Without a bound
    this ran 300+ cycles."""
    from research_framework.pipeline import orchestrator as orch

    ran: list[int] = []

    def _one_cycle(vault_dir, cycle_num, *args, **kwargs):
        ran.append(cycle_num)
        if len(ran) > 50:
            raise AssertionError("runaway: the run has no bound")
        _sidecar(vault_dir, cycle_num, 1.0)
        return rc

    monkeypatch.setattr(orch, "run_single_cycle", _one_cycle)
    monkeypatch.setattr(orch, "merge_expected_filenames_from_scan", lambda _v: None)
    monkeypatch.setattr(orch, "_run_health_gate", lambda _v: [])
    monkeypatch.setattr(orch, "scan_stubs", lambda _v, _s: ["stuck-stub.md"])
    monkeypatch.setattr(orch, "all_targets_met", lambda _v: False)
    return ran


@pytest.mark.parametrize("rc", [0, 1])
def test_an_unbounded_run_is_refused_before_any_cycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    rc: int,
) -> None:
    from research_framework.pipeline import orchestrator as orch

    vault = _vault(tmp_path, completed=85, pipeline="  max_cycles: 0\n")
    ran = _runaway_stubs(monkeypatch, rc=rc)

    with caplog.at_level(logging.ERROR):
        result = orch.run_cycles(_spec(vault), vault, start_cycle=86, resume=True)

    assert result == 2
    assert ran == [], "refused before any cycle runs"
    assert not (vault / "_pipeline" / "run-report.json").exists()
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "pipeline.cycles_per_run" in joined


def test_an_explicit_unbounded_budget_is_refused_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller that resolved the budget itself gets the same answer."""
    from research_framework.pipeline import orchestrator as orch

    vault = _vault(tmp_path, completed=85)
    ran = _runaway_stubs(monkeypatch, rc=1)

    result = orch.run_cycles(
        _spec(vault), vault, start_cycle=86, resume=True, budget=_budget()
    )

    assert result == 2
    assert ran == []


def test_an_archived_unbounded_vault_gets_the_archived_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """#26's archived guard stays the first refusal: an archived vault that is
    also unbounded is told it is archived, not asked to
    add a cycle cap it has no use for."""
    from research_framework.pipeline import orchestrator as orch
    from research_framework.pipeline.archived import ARCHIVED_EXIT

    vault = _vault(tmp_path, completed=85, pipeline="  max_cycles: 0\n")
    settings = vault / "settings.yaml"
    settings.write_text(
        "archived: true\n" + settings.read_text(encoding="utf-8"), encoding="utf-8"
    )
    ran = _runaway_stubs(monkeypatch, rc=1)

    with caplog.at_level(logging.ERROR):
        result = orch.run_cycles(_spec(vault), vault, start_cycle=86, resume=True)

    assert result == ARCHIVED_EXIT
    assert ran == []
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "archived" in joined
    assert "pipeline.cycles_per_run" not in joined


@pytest.mark.parametrize(
    ("pipeline", "flags", "expected_ran"),
    [
        ("  max_cycles: 0\n  cycles_per_run: 2\n", {}, [86, 87]),
        ("  max_cycles: 87\n", {}, [86, 87]),
        ("  max_cycles: 0\n", {"flag_more_cycles": 2}, [86, 87]),
        ("  max_cycles: 0\n", {"flag_max_cycles": 87}, [86, 87]),
        ("  max_cycles: 0\n", {"flag_max_usd_this_run": 2.0}, [86, 87]),
        ("  max_cycles: 0\n", {"flag_max_usd": 2.0}, [86, 87]),
    ],
    ids=[
        "cycles_per_run",
        "finite-max_cycles",
        "--more-cycles",
        "--max-cycles",
        "--max-usd-this-run",
        "--max-usd",
    ],
)
def test_each_escape_hatch_lets_the_run_proceed_and_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pipeline: str,
    flags: dict,
    expected_ran: list[int],
) -> None:
    from research_framework.pipeline import orchestrator as orch

    vault = _vault(tmp_path, completed=85, pipeline=pipeline)
    ran = _runaway_stubs(monkeypatch, rc=1)
    budget = resolve_cycle_budget_from_path(
        vault / "settings.yaml", start_cycle=86, **flags
    )

    result = orch.run_cycles(
        _spec(vault), vault, start_cycle=86, resume=True, budget=budget
    )

    assert ran == expected_ran
    assert result == 1


def test_a_settings_dollar_cap_lets_the_run_proceed_and_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from research_framework.pipeline import orchestrator as orch

    vault = _vault(tmp_path)
    (vault / "settings.yaml").write_text(
        "pipeline:\n  max_cycles: 0\n  budget_usd: 2.0\n", encoding="utf-8"
    )
    ran = _runaway_stubs(monkeypatch, rc=1)

    result = orch.run_cycles(_spec(vault), vault)

    assert ran == [1, 2]
    assert result == 1
