"""A zero `--budget-cap` means UNLIMITED here too (spec 061 FR3-Z amendment).

Spec 061's 2026-09-07 amendment settled that a zero dollar budget is
uncapped, and ``_budget_resolve._resolve_usd`` implements it — but only for
the two readers that existed when it was written (the resolver and
``orchestrator.run_cycles``' ``cumulative >= budget_cap > 0`` guard).

``validate_cycle.py`` is the third reader. Its Condition C is a bare
``cumulative_cost >= budget_cap``, so a zero arrives as "you have spent
everything you were given" and TERMINATEs the cycle before its first note. It
never saw a zero while ``cycle --budget-cap`` defaulted to a hardcoded $10.00
(issue #233); routing that verb through the ladder is what handed it one, and
the disagreement was there the whole time.

Which is the point of one ladder: the value is decided in a single place, and
every consumer has to mean the same thing by it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "validate_cycle.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("validate_cycle_uncapped", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def vc() -> Any:
    return _load_module()


def _v2_report(cost: float, **extra: Any) -> dict[str, Any]:
    """Minimal v2 research report (same shape as test_validate_cycle_budget_aliases)."""
    report: dict[str, Any] = {
        "schema_version": "2.0",
        "cycle": 1,
        "phase": "research",
        "timestamp": "2026-09-07T00:00:00Z",
        "sources_consulted": ["GitHub repos"],
        "termination_condition": None,
        "cumulative_cost_usd": cost,
    }
    report.update(extra)
    return report


@pytest.mark.parametrize("cap", [0.0, 0, -0.0])
def test_zero_cap_does_not_terminate_a_cycle_that_has_spent_nothing(
    vc: Any, cap: float, tmp_path: Path
) -> None:
    result = vc.check_termination_v2(_v2_report(0.0), 5, cap, tmp_path, None)
    assert "Condition C" not in (result.reason or "")


@pytest.mark.parametrize("cap", [0.0, -1.0])
def test_zero_cap_does_not_terminate_a_cycle_that_has_spent_money(
    vc: Any, cap: float, tmp_path: Path
) -> None:
    """Uncapped means uncapped — the tally is reported, never enforced."""
    result = vc.check_termination_v2(_v2_report(42.0), 5, cap, tmp_path, None)
    assert "Condition C" not in (result.reason or "")


def test_a_positive_cap_still_terminates(vc: Any, tmp_path: Path) -> None:
    result = vc.check_termination_v2(_v2_report(6.0), 5, 5.0, tmp_path, None)
    assert result.status == "TERMINATE"
    assert "Condition C" in result.reason


def test_an_explicit_termination_c_is_still_honoured_under_a_zero_cap(
    vc: Any, tmp_path: Path
) -> None:
    """The scout may declare C for a reason this validator cannot see.

    Only the DERIVED check is disabled by an uncapped budget. A report that
    says "I stopped for budget" is testimony, not arithmetic, and this
    validator has never been in a position to overrule it.
    """
    report = _v2_report(0.0, termination_condition="C")
    result = vc.check_termination_v2(report, 5, 0.0, tmp_path, None)
    assert result.status == "TERMINATE"
    assert "Condition C" in result.reason


def _v1_report(cost: float) -> dict[str, Any]:
    return {
        "cycle": 1,
        "phase": "scout",
        "timestamp": "2026-09-07T00:00:00Z",
        "sources_consulted": {"s": {"results": 1}},
        "topics_found": {"new": [], "known": []},
        "cost_estimate_usd": cost,
        "cumulative_cost_usd": cost,
    }


def test_v1_path_agrees_with_v2(vc: Any, tmp_path: Path) -> None:
    """Both validators read the same flag; they must read it the same way."""
    result = vc.check_termination(_v1_report(9.0), None, [], [], 5, 0.0, tmp_path)
    assert "Condition C" not in (result.reason or "")


def test_v1_path_still_enforces_a_positive_cap(vc: Any, tmp_path: Path) -> None:
    result = vc.check_termination(_v1_report(9.0), None, [], [], 5, 5.0, tmp_path)
    assert result.status == "TERMINATE"
    assert "Condition C" in result.reason


@pytest.mark.parametrize("cap", ["nan", "-5"])
def test_a_nan_or_negative_cap_is_refused(tmp_path: Path, cap: str) -> None:
    """``nan`` (and a negative) failed every comparison that makes a cap
    bite, so the cycle ran uncapped with no word: the hole commit 0922f4a
    closed for ``--max-usd`` in the budget resolver."""
    import json
    import subprocess

    report = tmp_path / "cycle-001-research.json"
    report.write_text(json.dumps(_v2_report(1000.0)), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(_SCRIPT), str(report), "--budget-cap", cap],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "--budget-cap" in result.stderr
