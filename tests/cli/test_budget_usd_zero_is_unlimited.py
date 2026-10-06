"""``pipeline.budget_usd: 0`` means UNLIMITED (owner's decision, 2026-09-07).

Spec 061's ladder resolved a settings ``0`` to a literal ``0.0`` cap, leaving
its meaning to whoever read it next: ``orchestrator.run_cycles`` happened to
guard on ``cumulative >= budget_cap > 0`` and so treated it as uncapped, but
nothing said so and any other reader was free to read it as "spend nothing".
Every shipped profile said ``0.0`` for months (issue #230) and every one of
them ran, which makes "uncapped" the meaning the corpus already carries.

This amends the resolver so the value says what it means at the one place it
is decided, rather than depending on a ``> 0`` comparison three layers away.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework.cli._budget_resolve import (
    BudgetError,
    resolve_cycle_budget,
    resolve_cycle_budget_from_path,
)


def _resolve(budget_usd: object, **kwargs: object):
    data = {"pipeline": {"max_cycles": 3, "budget_usd": budget_usd}}
    return resolve_cycle_budget(data, flag_max_cycles=None, **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [0, 0.0, -0.0, "0"])
def test_zero_budget_usd_resolves_to_uncapped(value: object) -> None:
    res = _resolve(value, flag_max_usd=None)
    assert res.max_usd is None, f"{value!r} must mean uncapped, not a zero cap"


def test_zero_from_settings_keeps_its_provenance() -> None:
    """FR4 provenance survives: the operator DID configure this, explicitly."""
    res = _resolve(0.0, flag_max_usd=None)
    assert res.max_usd is None
    assert res.max_usd_source == "settings"


def test_absent_budget_usd_is_uncapped_from_the_default_rung() -> None:
    res = resolve_cycle_budget(
        {"pipeline": {"max_cycles": 3}}, flag_max_cycles=None, flag_max_usd=None
    )
    assert res.max_usd is None
    assert res.max_usd_source == "default"


def test_explicit_null_budget_usd_is_uncapped() -> None:
    res = _resolve(None, flag_max_usd=None)
    assert res.max_usd is None


def test_a_positive_budget_usd_still_caps(tmp_path: Path) -> None:
    """The seeded profiles must keep the ceiling #317 gave them."""
    res = _resolve(25.0, flag_max_usd=None)
    assert res.max_usd == 25.0
    assert res.max_usd_source == "settings"


def test_zero_on_the_flag_rung_is_uncapped_too() -> None:
    """One ladder, one meaning of zero.

    ``--max-usd 0`` reading as a zero-dollar cap while ``budget_usd: 0`` read
    as uncapped would be a silent disagreement between two rungs of the same
    ladder — the class of bug spec 061 exists to remove.
    """
    res = _resolve(25.0, flag_max_usd=0.0)
    assert res.max_usd is None
    assert res.max_usd_source == "flag"


def test_a_negative_flag_is_still_a_usage_error() -> None:
    with pytest.raises(BudgetError):
        _resolve(None, flag_max_usd=-1.0)


def test_a_negative_settings_value_is_still_ignored() -> None:
    """Unchanged: a negative cap is nonsense, so the ladder falls through."""
    res = _resolve(-5.0, flag_max_usd=None)
    assert res.max_usd is None
    assert res.max_usd_source == "default"


def test_a_zero_budget_vault_runs_without_a_budget_pause(tmp_path: Path) -> None:
    """The end the decision is about: a vault configured ``0.0`` is not stopped.

    ``run_cycles`` turns ``max_usd is None`` into ``budget_cap = 0.0`` and its
    cumulative guard skips a cap of zero, so the run proceeds past spend that
    a literal zero-dollar cap would have refused.
    """
    settings = tmp_path / "settings.yaml"
    settings.write_text(
        "pipeline:\n  max_cycles: 2\n  budget_usd: 0.0\n", encoding="utf-8"
    )
    resolution = resolve_cycle_budget_from_path(settings)
    assert resolution.max_usd is None
    budget_cap = resolution.max_usd if resolution.max_usd is not None else 0.0
    cumulative = 999.0
    assert not (cumulative >= budget_cap > 0)
