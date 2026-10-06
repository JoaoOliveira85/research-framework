"""Tier-2 unit tests for the shared cycle-budget precedence resolver (spec 061 FR3/D3).

The resolver is the single home for the ladder ``flag > pipeline.max_cycles >
built-in default`` (with the deprecated ``cycles.*`` block warn-and-honoured only
when the canonical key is absent). These tests pin every rung so FR1/FR3/FR4 can
consume it without re-deriving precedence.
"""

from __future__ import annotations

import logging

import pytest

from research_framework.cli._budget_resolve import (
    DEFAULT_MAX_CYCLES,
    BudgetError,
    BudgetResolution,
    resolve_cycle_budget,
)


def test_flag_beats_pipeline_max_cycles_and_default() -> None:
    """Ladder top tier: the flag wins over a present canonical settings key."""
    res = resolve_cycle_budget(
        {"pipeline": {"max_cycles": 12}},
        flag_max_cycles=8,
        flag_max_usd=None,
    )
    assert isinstance(res, BudgetResolution)
    assert res.max_cycles == 8
    assert res.max_cycles_source == "flag"


def test_pipeline_max_cycles_beats_builtin_default() -> None:
    """Middle tier: with no flag, the canonical settings key wins over the default."""
    res = resolve_cycle_budget(
        {"pipeline": {"max_cycles": 12}},
        flag_max_cycles=None,
        flag_max_usd=None,
    )
    assert res.max_cycles == 12
    assert res.max_cycles_source == "settings"
    # Sanity: the default differs from the configured value, so "settings" is meaningful.
    assert res.max_cycles != DEFAULT_MAX_CYCLES


def test_deprecated_initial_max_warn_and_honour_only_when_canonical_absent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """FR1 grace: only ``cycles.initial_max`` present (no canonical) ⇒ honoured + WARNING.

    MUST NOT silently drop the deprecated value when the canonical key is absent —
    that regresses to the pre-grace behaviour.
    """
    with caplog.at_level(logging.WARNING):
        res = resolve_cycle_budget(
            {"cycles": {"initial_max": 6}},
            flag_max_cycles=None,
            flag_max_usd=None,
        )
    assert res.max_cycles == 6
    assert res.max_cycles_source == "settings"
    assert "cycles.initial_max" in res.deprecated_keys_seen
    # A single loud WARNING that names the canonical key.
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "deprecated key must emit a logging.WARNING"
    assert any("pipeline.max_cycles" in r.getMessage() for r in warnings)


def test_both_present_canonical_wins_deprecated_not_honoured(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """rc1 bug inversion: canonical present AND deprecated present ⇒ canonical wins + WARNING.

    The deprecated value (6) is recorded as *seen* but is NOT applied; the canonical
    12 wins. This is the exact scenario that silently truncated the codebase-vault run.
    """
    with caplog.at_level(logging.WARNING):
        res = resolve_cycle_budget(
            {"pipeline": {"max_cycles": 12}, "cycles": {"initial_max": 6}},
            flag_max_cycles=None,
            flag_max_usd=None,
        )
    assert res.max_cycles == 12  # NOT 6
    assert res.max_cycles_source == "settings"
    assert "cycles.initial_max" in res.deprecated_keys_seen
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "a shadowed deprecated key must still WARN"


def test_neither_present_falls_through_to_builtin_default() -> None:
    """Bottom tier: empty settings ⇒ the generous built-in default, source ``default``."""
    res = resolve_cycle_budget({}, flag_max_cycles=None, flag_max_usd=None)
    assert res.max_cycles == DEFAULT_MAX_CYCLES
    assert res.max_cycles_source == "default"
    assert res.deprecated_keys_seen == []


def test_max_usd_resolves_same_precedence_ladder() -> None:
    """Q3/FR3: ``max_usd`` resolves flag > settings(pipeline.budget_usd) > default(None)."""
    # settings tier
    settings = {"pipeline": {"max_cycles": 12, "budget_usd": 25.0}}
    res = resolve_cycle_budget(settings, flag_max_cycles=None, flag_max_usd=None)
    assert res.max_usd == 25.0
    assert res.max_usd_source == "settings"
    # flag tier beats settings
    res = resolve_cycle_budget(settings, flag_max_cycles=None, flag_max_usd=10.0)
    assert res.max_usd == 10.0
    assert res.max_usd_source == "flag"
    # default tier: no flag, no settings cap ⇒ uncapped (None)
    res = resolve_cycle_budget(
        {"pipeline": {"max_cycles": 12}}, flag_max_cycles=None, flag_max_usd=None
    )
    assert res.max_usd is None
    assert res.max_usd_source == "default"


def test_max_cycles_zero_or_negative_raises_usage_error() -> None:
    """Invalid ``max_cycles`` from ANY source is a usage error (caller maps to exit 2).

    MUST NOT coerce to a positive value or silently fall through to the default.
    """
    # via flag
    for bad in (0, -1):
        with pytest.raises(BudgetError):
            resolve_cycle_budget(
                {"pipeline": {"max_cycles": 12}},
                flag_max_cycles=bad,
                flag_max_usd=None,
            )
    # via settings canonical key (present-but-invalid must raise, not fall through)
    for bad in (0, -1):
        with pytest.raises(BudgetError):
            resolve_cycle_budget(
                {"pipeline": {"max_cycles": bad}},
                flag_max_cycles=None,
                flag_max_usd=None,
            )


@pytest.mark.parametrize("flag", ["flag_max_usd", "flag_max_usd_this_run"])
@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_non_finite_dollar_flag_is_a_usage_error(flag: str, value: float) -> None:
    """``--max-usd nan`` passed both the ``< 0`` check and the zero-means-
    unlimited check, so the cap was NaN — and ``spent >= nan`` is always False,
    so a cap the operator set could never trip."""
    with pytest.raises(BudgetError):
        resolve_cycle_budget({}, **{flag: value})
