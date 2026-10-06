"""H1 regression: DFS budget cap must honor all three budget-field aliases.

Background (spec-019 / 0.2.28):

``scripts/validate_cycle.py`` v0.2.25 accepts three field names for the
v2 research-phase cumulative-cost report:

    BUDGET_FIELDS_V2_RESEARCH = (
        "budget_consumed_usd",
        "cumulative_cost_usd",
        "cost_estimate_usd",
    )

…but at the same time, the termination check (line 592 in v0.2.27) reads
``report.get("budget_consumed_usd", 0)`` ONLY. The result: a research
report that emits ``cumulative_cost_usd: 49.5`` (which the prompt example
in ``dfs-prompt.md.j2`` historically encouraged) satisfies the structural
gate AND silently shows the cap check ``$0.00 / $50.00`` — Condition C
never fires.

This is the same bug class as 0.2.25 (validator accepts one shape,
producer emits another) but applied to a VALUE, not just a field's
presence. Tests below lock the v0.2.28 fix.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "validate_cycle.py"


def _load_vc():
    """Load validate_cycle.py as a module (sys.modules registration so
    @dataclass works — see test_validate_cycle_source_file_shapes for the
    full explanation)."""
    module_name = "validate_cycle_budget_aliases_under_test"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


@pytest.fixture(scope="module")
def vc():
    return _load_vc()


def _research_report(extra: dict) -> dict:
    """Minimal v2 research-phase report that satisfies
    ``REQUIRED_REPORT_FIELDS_V2_RESEARCH``. Caller injects budget-field
    permutations via ``extra``."""
    base = {
        "schema_version": "2.0",
        "cycle": 5,
        "phase": "research",
        "timestamp": "2026-05-17T22:30:00Z",
        "sources_consulted": ["GitHub repos"],
        "termination_condition": None,
    }
    base.update(extra)
    return base


@pytest.mark.parametrize(
    "budget_field",
    ["budget_consumed_usd", "cumulative_cost_usd", "cost_estimate_usd"],
)
def test_research_phase_budget_cap_fires_for_each_alias(vc, budget_field: str) -> None:
    """For each of the three accepted budget-field names, a report
    at-or-over the cap must trigger Condition C. Pre-v0.2.28 this only
    passed for budget_consumed_usd."""
    cap = 50.0
    spent = 60.0  # >= cap so Condition C must fire
    report = _research_report({budget_field: spent})

    result = vc.check_termination_v2(
        report,
        max_cycles=10,
        budget_cap=cap,
        vault_dir=None,
        pipeline_dir=None,
    )

    assert result.status == "TERMINATE", (
        f"With ``{budget_field}: {spent}`` at >= ${cap} cap, Condition C "
        f"must fire. Got status={result.status!r}, reason={result.reason!r}"
    )
    assert "Condition C" in result.reason
    assert f"${spent:.2f}" in result.reason or f"{spent:.2f}" in result.reason


def test_research_phase_continues_when_all_three_budgets_well_under_cap(
    vc,
) -> None:
    """Sanity: when every alias reports a value safely under the cap,
    the cycle continues (we're not over-triggering)."""
    report = _research_report(
        {
            "budget_consumed_usd": 5.0,
            "cumulative_cost_usd": 5.0,
            "cost_estimate_usd": 5.0,
        }
    )

    result = vc.check_termination_v2(
        report,
        max_cycles=10,
        budget_cap=100.0,
        vault_dir=None,
        pipeline_dir=None,
    )
    assert result.status == "CONTINUE", result.reason


def test_research_phase_resolver_prefers_canonical_when_aliases_conflict(
    vc,
) -> None:
    """If multiple budget aliases are present with different values (an
    agent bug we can't prevent), use the canonical
    ``budget_consumed_usd`` as the source of truth. This locks the
    resolution order so future readers can rely on it."""
    cap = 50.0
    report = _research_report(
        {
            # The cumulative says we're safe; the canonical says we're at cap.
            "cumulative_cost_usd": 1.0,
            "cost_estimate_usd": 1.0,
            "budget_consumed_usd": 60.0,
        }
    )

    result = vc.check_termination_v2(
        report,
        max_cycles=10,
        budget_cap=cap,
        vault_dir=None,
        pipeline_dir=None,
    )
    assert result.status == "TERMINATE", (
        "canonical budget_consumed_usd takes precedence over aliases; "
        f"got {result.status}: {result.reason}"
    )


def test_research_phase_resolver_falls_back_to_cumulative_then_estimate(
    vc,
) -> None:
    """When the canonical field is absent, fall back to
    ``cumulative_cost_usd``, then to ``cost_estimate_usd``. Locks the
    documented fallback order (same as the BUDGET_FIELDS_V2_RESEARCH
    tuple definition order)."""
    cap = 50.0
    report = _research_report({"cumulative_cost_usd": 60.0})

    result = vc.check_termination_v2(
        report,
        max_cycles=10,
        budget_cap=cap,
        vault_dir=None,
        pipeline_dir=None,
    )
    assert result.status == "TERMINATE"
    assert "Condition C" in result.reason

    # Only cost_estimate_usd present
    report = _research_report({"cost_estimate_usd": 60.0})
    result = vc.check_termination_v2(
        report,
        max_cycles=10,
        budget_cap=cap,
        vault_dir=None,
        pipeline_dir=None,
    )
    assert result.status == "TERMINATE"
    assert "Condition C" in result.reason
