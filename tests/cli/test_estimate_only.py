"""`--estimate-only`: a cost preflight that dispatches nothing (#238).

With every shipped profile capping nothing until issue #230, the first signal
an operator got about a run's cost was the bill. The estimator that answers
"what will this dispatch cost" has existed since spec 033 —
``cost_estimator.estimate_dispatch`` is where the approval marker's
``estimated_cost_usd`` comes from — and nothing ever ran it ahead of a whole
cycle.

Two properties matter and both are pinned here: the numbers are the guard's
own (same estimator, same ceilings, same agent/tier precedence), and the mode
is inert — no agent is dispatched, no marker is written, no vault state moves.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.pipeline.budget_preflight import (
    estimate_cycle,
    render_estimate_text,
)

_SETTINGS = """
pipeline:
  max_cycles: 4
  budget_usd: 20.0
  note_writer_batch_size: 3
tiers:
  basic: fake-basic
  standard: fake-standard
stages:
  scout:
    tier: standard
  note_writer:
    tier: standard
  verifier:
    enabled: true
    tier: basic
cycle_yield:
  base_notes_per_cycle: 6
  min_floor: 1
  max_ceiling: 50
limits:
  cycle_budget_usd: 5.0
"""

_NO_CAP_SETTINGS = _SETTINGS.replace("limits:\n  cycle_budget_usd: 5.0\n", "")


def _vault(tmp_path: Path, settings: str = _SETTINGS) -> Path:
    vault = tmp_path / "vault"
    (vault / "_pipeline").mkdir(parents=True)
    (vault / "settings.yaml").write_text(settings, encoding="utf-8")
    (vault / "cost-estimates.yaml").write_text(
        "ceilings:\n  default: 0.50\n  scout: 1.00\n  note_writer: 2.00\n"
        "  verifier: 0.25\n",
        encoding="utf-8",
    )
    return vault


def _with_coverage_gap(vault: Path) -> Path:
    from research_framework.pipeline.coverage import save_targets
    from research_framework.spec.schema import CoverageCategory, CoverageTargets

    save_targets(
        vault,
        CoverageTargets(
            categories=[
                CoverageCategory(
                    name="services", note_type="service", target_count=10, met_count=1
                )
            ]
        ),
    )
    return vault


# --- the estimate itself ---------------------------------------------------


def test_estimate_covers_every_stage_the_guard_can_see(tmp_path: Path) -> None:
    vault = _with_coverage_gap(_vault(tmp_path))

    est = estimate_cycle(vault, cycle_num=1)

    assert [row.stage for row in est.stages] == ["scout", "note_writer", "verifier"]


def test_estimate_uses_the_stage_ceilings_the_guard_uses(tmp_path: Path) -> None:
    vault = _with_coverage_gap(_vault(tmp_path))

    est = estimate_cycle(vault, cycle_num=1)
    by_stage = {row.stage: row for row in est.stages}

    assert by_stage["scout"].per_dispatch_usd == pytest.approx(1.00)
    assert by_stage["note_writer"].per_dispatch_usd == pytest.approx(2.00)
    assert by_stage["verifier"].per_dispatch_usd == pytest.approx(0.25)


def test_estimate_projects_dispatch_counts_from_the_yield_model(
    tmp_path: Path,
) -> None:
    """note_writer runs once per batch, verifier once per note — a total that
    assumed one dispatch each would understate, and an estimator that
    understates is the failure mode spec 033 forbids."""
    vault = _with_coverage_gap(_vault(tmp_path))

    est = estimate_cycle(vault, cycle_num=1)
    by_stage = {row.stage: row for row in est.stages}

    assert by_stage["scout"].dispatches == 1
    assert est.projected_notes >= 1
    assert by_stage["verifier"].dispatches == est.projected_notes
    assert by_stage["note_writer"].dispatches == -(-est.projected_notes // 3)


def test_total_is_the_sum_of_the_rows(tmp_path: Path) -> None:
    vault = _with_coverage_gap(_vault(tmp_path))

    est = estimate_cycle(vault, cycle_num=1)

    assert est.total_usd == pytest.approx(sum(row.subtotal_usd for row in est.stages))


def test_a_disabled_verifier_is_not_projected(tmp_path: Path) -> None:
    vault = _with_coverage_gap(
        _vault(tmp_path, _SETTINGS.replace("    enabled: true", "    enabled: false"))
    )

    est = estimate_cycle(vault, cycle_num=1)

    assert "verifier" not in [row.stage for row in est.stages]


def test_projection_never_drops_below_the_yield_floor(tmp_path: Path) -> None:
    """A fully covered vault has no MANDATORY yield; it can still write notes."""
    from research_framework.pipeline.coverage import save_targets
    from research_framework.spec.schema import CoverageCategory, CoverageTargets

    vault = _vault(tmp_path)
    save_targets(
        vault,
        CoverageTargets(
            categories=[
                CoverageCategory(
                    name="services", note_type="service", target_count=1, met_count=1
                )
            ]
        ),
    )

    est = estimate_cycle(vault, cycle_num=1)

    assert est.projected_notes >= 1


def test_estimate_reports_the_resolved_cap_and_its_source(tmp_path: Path) -> None:
    vault = _with_coverage_gap(_vault(tmp_path))

    est = estimate_cycle(vault, cycle_num=1)

    assert est.cycle_budget_usd == pytest.approx(5.0)


def test_estimate_reports_an_absent_cap_as_none(tmp_path: Path) -> None:
    vault = _with_coverage_gap(_vault(tmp_path, _NO_CAP_SETTINGS))

    est = estimate_cycle(vault, cycle_num=1)

    assert est.cycle_budget_usd is None


def test_estimate_flags_a_projection_that_would_trip_the_cap(tmp_path: Path) -> None:
    vault = _with_coverage_gap(
        _vault(
            tmp_path,
            _SETTINGS.replace("cycle_budget_usd: 5.0", "cycle_budget_usd: 0.10"),
        )
    )

    est = estimate_cycle(vault, cycle_num=1)

    assert est.total_usd > 0.10
    assert est.exceeds_cycle_budget is True


def test_render_names_every_stage_and_the_total(tmp_path: Path) -> None:
    vault = _with_coverage_gap(_vault(tmp_path))

    text = render_estimate_text(estimate_cycle(vault, cycle_num=1))

    assert "scout" in text and "note_writer" in text and "verifier" in text
    assert "TOTAL" in text


# --- the CLI mode ----------------------------------------------------------


def _generate_args(vault: Path, **over: object):
    from argparse import Namespace

    base: dict[str, object] = {
        "vault_dir": vault,
        "output": None,
        "spec": None,
        "estimate_only": True,
        "cycle": None,
        "max_cycles": None,
        "max_usd": None,
        "more_cycles": None,
        "max_usd_this_run": None,
        "regenerate_plan_only": False,
        "legacy_cycle_runner": False,
        "dry_run": False,
        "resume": False,
    }
    base.update(over)
    return Namespace(**base)


def test_generate_estimate_only_prints_and_exits_without_dispatching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from research_framework.cli.research_generate import _cmd_generate

    vault = _with_coverage_gap(_vault(tmp_path))

    def _boom(*_a: object, **_k: object) -> int:
        raise AssertionError("--estimate-only must dispatch nothing")

    monkeypatch.setattr("research_framework.pipeline.orchestrator.run_cycles", _boom)

    rc = _cmd_generate(_generate_args(vault))

    assert rc == 0
    out = capsys.readouterr().out
    assert "TOTAL" in out and "scout" in out


def test_estimate_only_writes_nothing_into_the_vault(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from research_framework.cli.research_generate import _cmd_generate

    vault = _with_coverage_gap(_vault(tmp_path))
    before = sorted(p.relative_to(vault).as_posix() for p in vault.rglob("*"))

    assert _cmd_generate(_generate_args(vault)) == 0
    capsys.readouterr()

    after = sorted(p.relative_to(vault).as_posix() for p in vault.rglob("*"))
    assert after == before


def test_estimate_only_refuses_when_the_run_would_be_unsupervised_and_uncapped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The preflight's verdict IS "is this safe to leave alone?" (#238)."""
    from research_framework.cli.research_generate import _cmd_generate

    vault = _with_coverage_gap(_vault(tmp_path, _NO_CAP_SETTINGS))

    rc = _cmd_generate(_generate_args(vault))

    assert rc == 2
    captured = capsys.readouterr()
    assert "TOTAL" in captured.out, "the estimate is still printed"
    assert "limits.cycle_budget_usd" in captured.err


def test_estimate_only_refuses_an_archived_vault(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec 071: no cycle will ever run there, so there is nothing to price."""
    from research_framework.cli.research_generate import _cmd_generate

    vault = _with_coverage_gap(_vault(tmp_path, _SETTINGS + "\narchived: true\n"))

    assert _cmd_generate(_generate_args(vault)) == 2

    captured = capsys.readouterr()
    assert "archived" in captured.err
    assert "TOTAL" not in captured.out


def test_estimate_only_on_the_cycle_verb_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from argparse import Namespace

    from research_framework.cli.research_cycles import _cmd_cycle

    vault = _with_coverage_gap(_vault(tmp_path))

    def _boom(*_a: object, **_k: object) -> int:
        raise AssertionError("--estimate-only must dispatch nothing")

    monkeypatch.setattr(
        "research_framework.pipeline.orchestrator.run_single_cycle", _boom
    )

    rc = _cmd_cycle(
        Namespace(
            vault=vault,
            cycle=2,
            budget_cap=None,
            target_topics=None,
            estimate_only=True,
        )
    )

    assert rc == 0
    assert "TOTAL" in capsys.readouterr().out


def test_estimate_only_json_shape_is_stable(tmp_path: Path) -> None:
    vault = _with_coverage_gap(_vault(tmp_path))

    doc = json.loads(json.dumps(estimate_cycle(vault, cycle_num=1).to_json_dict()))

    assert doc["cycle_number"] == 1
    assert doc["total_usd"] > 0
    assert {"stage", "dispatches", "per_dispatch_usd", "subtotal_usd"} <= set(
        doc["stages"][0]
    )
