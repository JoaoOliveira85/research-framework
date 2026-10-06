"""FR2 (spec 061): the per-cycle budget + dollar cap are gone from the spec schema.

A stray ``budget.max_cycles`` / ``budget.max_usd`` / top-level ``max_cycles`` in a
parsed spec must be dropped silently — *exactly* like any unknown key (the schema's
``from_dict`` is ``.get()``-based, so an arbitrary ``pizza:`` key is dropped the same
way) — and have ZERO effect on the effective budget, which is resolved from
settings/flag/default via ``cli._budget_resolve`` (data-model.md D2).
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from research_framework.cli._budget_resolve import (
    DEFAULT_MAX_CYCLES,
    BudgetResolution,
    resolve_cycle_budget,
)
from research_framework.spec.schema import BudgetConfig, SpecConfig


def _spec_with_stray_budget(**budget_extra: Any) -> SpecConfig:
    """Parse (``from_dict`` — the parse layer; validation is a separate stage) a
    spec dict carrying stray budget/cycle keys plus an arbitrary ``pizza`` control
    key. None of them may surface as honoured fields."""
    return SpecConfig.from_dict(
        {
            "name": "t",
            "location": "/tmp/x",
            "budget": {"warn_at_pct": 0.8, **budget_extra},
            "pizza": "pepperoni",  # the control: an arbitrary unknown key
        }
    )


def test_stray_budget_max_cycles_parses_with_zero_effect() -> None:
    spec = _spec_with_stray_budget(max_cycles=999)
    # Parse succeeded and the stray key is NOT an honoured field.
    assert not hasattr(spec.budget, "max_cycles")
    # The effective budget resolved elsewhere is NOT the stray 999.
    res = resolve_cycle_budget({}, flag_max_cycles=None, flag_max_usd=None)
    assert res.max_cycles == DEFAULT_MAX_CYCLES
    assert res.max_cycles != 999


def test_stray_budget_max_usd_parses_with_zero_effect() -> None:
    spec = _spec_with_stray_budget(max_usd=999.0)
    assert not hasattr(spec.budget, "max_usd")
    # No dollar cap is derived from the stray spec value.
    res = resolve_cycle_budget({}, flag_max_cycles=None, flag_max_usd=None)
    assert res.max_usd is None


def test_stray_top_level_max_cycles_silently_ignored() -> None:
    spec = SpecConfig.from_dict(
        {"name": "t", "location": "/tmp/x", "max_cycles": 12, "pizza": "x"}
    )
    # Dropped at from_dict with zero runtime effect — identical to ``pizza``.
    assert not hasattr(spec, "max_cycles")
    res = resolve_cycle_budget({}, flag_max_cycles=None, flag_max_usd=None)
    assert res.max_cycles == DEFAULT_MAX_CYCLES
    assert res.max_cycles != 12


def test_budget_config_schema_fields_removed() -> None:
    budget_field_names = {f.name for f in fields(BudgetConfig)}
    assert "max_cycles" not in budget_field_names
    assert "max_usd" not in budget_field_names
    # Top-level spec field also removed.
    spec_field_names = {f.name for f in fields(SpecConfig)}
    assert "max_cycles" not in spec_field_names


def test_generate_path_does_not_mutate_spec_max_cycles_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The generate budget-resolution entry path threads the resolver output into
    ``run_cycles`` and never mutates the spec (the rc1 root cause). The orchestrator
    receives the settings value (7), NOT any stray spec budget field."""
    import research_framework.cli.research_generate as rg

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text(
        "pipeline:\n  max_cycles: 7\n  budget_usd: 10.0\n", encoding="utf-8"
    )

    # A genuine parsed spec carrying stray budget fields (dropped by the schema).
    spec = _spec_with_stray_budget(max_cycles=999, max_usd=999.0)
    object.__setattr__(spec, "location", vault)

    captured: dict[str, Any] = {}

    def _fake_run_cycles(
        spec_arg: SpecConfig, vd: Path, *, budget: BudgetResolution, **_: Any
    ) -> int:
        captured["spec"] = spec_arg
        captured["budget"] = budget
        return 0

    monkeypatch.setattr(
        "research_framework.pipeline.orchestrator.run_cycles",
        _fake_run_cycles,
        raising=True,
    )
    monkeypatch.setattr(rg, "load_spec", lambda *a, **k: spec, raising=True)
    monkeypatch.setattr(rg, "validate", lambda *a, **k: None, raising=True)
    monkeypatch.setattr(rg, "scaffold", lambda *a, **k: None, raising=True)
    monkeypatch.setattr(rg, "render_all", lambda *a, **k: None, raising=True)
    monkeypatch.setattr(rg, "copy_scripts", lambda *a, **k: None, raising=True)
    monkeypatch.setattr(rg, "_run_phase3", lambda *a, **k: 0, raising=True)

    args = SimpleNamespace(
        regenerate_plan_only=False,
        legacy_cycle_runner=False,
        spec=vault / "research.spec.md",
        dry_run=False,
        resume=False,
        output=vault,
        settings=None,
        prepopulate=None,
        skip_gate=True,
        max_cycles=None,
        max_usd=None,
    )

    rc = rg._cmd_generate(args)

    assert rc == 0
    # The orchestrator got the settings value, not the stray spec 999.
    assert captured["budget"].max_cycles == 7
    assert captured["budget"].max_cycles_source == "settings"
    # The spec object was never given a max_cycles field (no in-place mutation).
    assert not hasattr(captured["spec"], "max_cycles")
    assert not hasattr(captured["spec"].budget, "max_cycles")
