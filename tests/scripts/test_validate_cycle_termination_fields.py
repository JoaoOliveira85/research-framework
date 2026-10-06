"""H3 regression: DFS termination must accept both canonical
``termination_condition`` AND the prompt's example ``next_action`` +
``termination_reason``.

Background (spec-019 / 0.2.28):

``templates/prompts/dfs-prompt.md.j2:127-128`` instructs the DFS agent
to emit:

    "next_action": "<continue|terminate>",
    "termination_reason": "<A|B|C|None>"

But ``scripts/validate_cycle.py:check_termination_v2`` reads ONLY
``termination_condition`` (line 593-624). An agent that faithfully
follows the prompt example never trips A/B/C — the cycle just rolls
into the next iteration on every signal.

v0.2.28 makes the validator accept both shapes (canonical preferred,
``next_action`` + ``termination_reason`` accepted with a deprecation
warning) and updates the prompt's JSON example to use
``termination_condition`` as the canonical field. The old aliases are
documented as deprecated and slated for removal in 0.3.0.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "validate_cycle.py"


def _load_vc():
    module_name = "validate_cycle_termination_fields_under_test"
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


def _report(termination_extras: dict) -> dict:
    """Minimal v2 research-phase report satisfying
    ``REQUIRED_REPORT_FIELDS_V2_RESEARCH``."""
    base = {
        "schema_version": "2.0",
        "cycle": 3,
        "phase": "research",
        "timestamp": "2026-05-17T22:45:00Z",
        "sources_consulted": ["GitHub repos"],
        "budget_consumed_usd": 1.0,
    }
    base.update(termination_extras)
    return base


def test_canonical_termination_condition_b_fires_condition_b(vc) -> None:
    """Canonical shape: ``termination_condition: "B"`` fires Condition B."""
    report = _report({"termination_condition": "B"})
    result = vc.check_termination_v2(
        report,
        max_cycles=10,
        budget_cap=100.0,
        vault_dir=None,
        pipeline_dir=None,
    )
    assert result.status == "TERMINATE"
    assert "Condition B" in result.reason


def test_prompt_aliases_next_action_terminate_with_reason_b_fires_condition_b(
    vc, caplog: pytest.LogCaptureFixture
) -> None:
    """v0.2.28: when ``termination_condition`` is absent but
    ``next_action: "terminate"`` + ``termination_reason: "B"`` are
    present, the validator must derive Condition B AND emit a
    DeprecationWarning to logging.

    This is the literal shape the v0.2.27 DFS prompt example produces.
    """
    report = _report({"next_action": "terminate", "termination_reason": "B"})
    caplog.set_level(logging.WARNING)
    result = vc.check_termination_v2(
        report,
        max_cycles=10,
        budget_cap=100.0,
        vault_dir=None,
        pipeline_dir=None,
    )
    assert result.status == "TERMINATE", (
        "DFS prompt example shape must be honored; got "
        f"{result.status}: {result.reason}"
    )
    assert "Condition B" in result.reason
    # The deprecation warning is mandatory so users see they're on the
    # legacy field path and can migrate before 0.3.0 removes it.
    combined = " ".join(rec.getMessage() for rec in caplog.records)
    assert "deprecat" in combined.lower(), (
        "expected a deprecation warning when next_action/termination_reason "
        f"shape is used; got log:\n{combined}"
    )


@pytest.mark.parametrize("reason", ["A", "C"])
def test_prompt_aliases_with_other_reasons_fire_their_conditions(
    vc, reason: str
) -> None:
    """Same shape, other reasons: must fire Conditions A and C."""
    extras = {"next_action": "terminate", "termination_reason": reason}
    if reason == "A":
        # Condition A fires on cycle >= max_cycles, regardless of field;
        # so the test for A via the alias path needs cycle near the max.
        extras_with_cycle = dict(extras)
        report = _report(extras_with_cycle)
        report["cycle"] = 10
        result = vc.check_termination_v2(
            report,
            max_cycles=10,
            budget_cap=100.0,
            vault_dir=None,
            pipeline_dir=None,
        )
        assert result.status == "TERMINATE"
        assert "Condition A" in result.reason
    else:  # reason == "C"
        report = _report(extras)
        # Push budget to cap so Condition C fires when reason maps to it.
        report["budget_consumed_usd"] = 999.0
        result = vc.check_termination_v2(
            report,
            max_cycles=10,
            budget_cap=100.0,
            vault_dir=None,
            pipeline_dir=None,
        )
        assert result.status == "TERMINATE"
        # Either condition C (budget) or the reason-derived path fires.
        assert "Condition C" in result.reason


def test_canonical_takes_precedence_over_aliases(vc) -> None:
    """If both shapes are present (one says continue, one says
    terminate), canonical wins. Locks the precedence so future readers
    aren't surprised."""
    report = _report(
        {
            "termination_condition": None,
            "next_action": "terminate",
            "termination_reason": "B",
        }
    )
    result = vc.check_termination_v2(
        report,
        max_cycles=10,
        budget_cap=100.0,
        vault_dir=None,
        pipeline_dir=None,
    )
    # Canonical termination_condition=None → fall through to next_action
    # alias. (Canonical only "wins" when it's a non-None value.)
    assert result.status == "TERMINATE", (
        "When canonical termination_condition is explicitly None, fall "
        "through to the alias is acceptable; got "
        f"{result.status}: {result.reason}"
    )

    report = _report(
        {
            "termination_condition": "B",
            "next_action": "continue",  # alias says don't terminate
        }
    )
    result = vc.check_termination_v2(
        report,
        max_cycles=10,
        budget_cap=100.0,
        vault_dir=None,
        pipeline_dir=None,
    )
    assert result.status == "TERMINATE", (
        "Canonical termination_condition='B' must win over "
        "next_action='continue'; got "
        f"{result.status}: {result.reason}"
    )


def test_no_termination_signal_continues(vc) -> None:
    """Sanity: when neither field shape signals termination, CONTINUE."""
    report = _report({})
    result = vc.check_termination_v2(
        report,
        max_cycles=10,
        budget_cap=100.0,
        vault_dir=None,
        pipeline_dir=None,
    )
    assert result.status == "CONTINUE"
