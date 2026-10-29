"""Issue #33: an unlimited lifetime ceiling and a per-run cycle cap in settings.

``pipeline.max_cycles`` is a LIFETIME ceiling (an absolute cycle number). A
long-lived vault always ran into it, and the only per-run reading was the CLI
flag ``--more-cycles N`` (#239). Two settings change that:

* ``pipeline.max_cycles: 0`` means no lifetime ceiling — the same reading of
  zero ``pipeline.budget_usd: 0`` already has (spec 061 amendment).
* ``pipeline.cycles_per_run: N`` is the settings spelling of ``--more-cycles
  N``: a run starting at cycle k stops after cycle k+N-1. When a finite
  lifetime ceiling also applies, the lower of the two wins. The CLI flags
  still win over both (the spec-061 ladder).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework.cli._budget_resolve import (
    DEFAULT_MAX_CYCLES,
    BudgetError,
    fill_missing_run_budget,
    require_bounded_run,
    resolve_cycle_budget,
    resolve_cycle_budget_from_path,
)
from research_framework.pipeline.settings import (
    UNLIMITED_MAX_CYCLES,
    SettingsError,
    effective_max_cycles,
    format_cycle_ceiling,
    load_vault_settings,
    planning_horizon,
)

# --- max_cycles: 0 is no lifetime ceiling ----------------------------------


def test_unlimited_sentinel_is_zero() -> None:
    assert UNLIMITED_MAX_CYCLES == 0


def test_settings_max_cycles_zero_resolves_to_unlimited() -> None:
    res = resolve_cycle_budget({"pipeline": {"max_cycles": 0}}, start_cycle=26)
    assert res.max_cycles == UNLIMITED_MAX_CYCLES
    assert res.max_cycles_source == "settings"


@pytest.mark.parametrize("bad", [-1, 1.5, True, "5", "0"])
def test_settings_max_cycles_negative_or_non_integer_is_refused(bad: object) -> None:
    with pytest.raises(BudgetError) as exc:
        resolve_cycle_budget({"pipeline": {"max_cycles": bad}})
    assert "pipeline.max_cycles" in str(exc.value)


def test_max_cycles_flag_zero_is_still_refused() -> None:
    """The flag rung is unchanged: ``--max-cycles 0`` stays a usage error."""
    with pytest.raises(BudgetError):
        resolve_cycle_budget({"pipeline": {"max_cycles": 0}}, flag_max_cycles=0)


def test_flags_still_beat_an_unlimited_setting() -> None:
    assert (
        resolve_cycle_budget(
            {"pipeline": {"max_cycles": 0}}, flag_max_cycles=12
        ).max_cycles
        == 12
    )
    assert (
        resolve_cycle_budget(
            {"pipeline": {"max_cycles": 0}}, flag_more_cycles=2, start_cycle=30
        ).max_cycles
        == 31
    )


# --- cycles_per_run --------------------------------------------------------


def test_cycles_per_run_caps_a_run_under_an_unlimited_lifetime() -> None:
    res = resolve_cycle_budget(
        {"pipeline": {"max_cycles": 0, "cycles_per_run": 3}}, start_cycle=26
    )
    assert res.max_cycles == 28, "cycles 26, 27, 28 — three this run"
    assert res.max_cycles_source == "settings"


def test_cycles_per_run_is_the_settings_spelling_of_more_cycles() -> None:
    by_setting = resolve_cycle_budget(
        {"pipeline": {"max_cycles": 0, "cycles_per_run": 4}}, start_cycle=7
    )
    by_flag = resolve_cycle_budget(
        {"pipeline": {"max_cycles": 0}}, flag_more_cycles=4, start_cycle=7
    )
    assert by_setting.max_cycles == by_flag.max_cycles == 10


def test_the_lower_of_per_run_and_lifetime_wins() -> None:
    lifetime_lower = resolve_cycle_budget(
        {"pipeline": {"max_cycles": 10, "cycles_per_run": 3}}, start_cycle=9
    )
    assert lifetime_lower.max_cycles == 10
    per_run_lower = resolve_cycle_budget(
        {"pipeline": {"max_cycles": 10, "cycles_per_run": 3}}, start_cycle=2
    )
    assert per_run_lower.max_cycles == 4


def test_cycles_per_run_against_the_default_lifetime_rung() -> None:
    """An absent ``max_cycles`` still means the built-in finite default."""
    res = resolve_cycle_budget({"pipeline": {"cycles_per_run": 3}}, start_cycle=19)
    assert res.max_cycles == DEFAULT_MAX_CYCLES


def test_a_vault_past_its_finite_ceiling_is_not_rescued_by_cycles_per_run() -> None:
    """The lifetime ceiling still binds; spec 070 F5 then reports it."""
    res = resolve_cycle_budget(
        {"pipeline": {"max_cycles": 10, "cycles_per_run": 3}}, start_cycle=12
    )
    assert res.max_cycles == 10


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        ({"flag_more_cycles": 5}, 11),
        ({"flag_max_cycles": 30}, 30),
    ],
)
def test_cli_flags_win_over_cycles_per_run(flags: dict, expected: int) -> None:
    res = resolve_cycle_budget(
        {"pipeline": {"max_cycles": 0, "cycles_per_run": 2}}, start_cycle=7, **flags
    )
    assert res.max_cycles == expected
    assert res.max_cycles_source == "flag"


def test_absent_cycles_per_run_leaves_behaviour_unchanged() -> None:
    res = resolve_cycle_budget({"pipeline": {"max_cycles": 12}}, start_cycle=5)
    assert res.max_cycles == 12


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "3"])
def test_invalid_cycles_per_run_is_refused(bad: object) -> None:
    with pytest.raises(BudgetError) as exc:
        resolve_cycle_budget({"pipeline": {"max_cycles": 0, "cycles_per_run": bad}})
    assert "pipeline.cycles_per_run" in str(exc.value)


def test_null_cycles_per_run_is_absent() -> None:
    res = resolve_cycle_budget(
        {"pipeline": {"max_cycles": 12, "cycles_per_run": None}}, start_cycle=5
    )
    assert res.max_cycles == 12


def test_cycles_per_run_leaves_no_second_copy_of_the_ceiling() -> None:
    """Folded into ``max_cycles`` like ``--more-cycles``, not a field beside it."""
    res = resolve_cycle_budget(
        {"pipeline": {"max_cycles": 0, "cycles_per_run": 2}}, start_cycle=3
    )
    assert not hasattr(res, "cycles_per_run")


# --- the in-process backfill (issue #233) anchors at the cycle it runs -----


def _vault(tmp_path: Path, pipeline: str) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text(
        f"pipeline:\n  budget_usd: 0\n{pipeline}", encoding="utf-8"
    )
    return vault


def test_fill_missing_run_budget_passes_unlimited_through(tmp_path: Path) -> None:
    vault = _vault(tmp_path, "  max_cycles: 0\n")
    assert fill_missing_run_budget(vault, None, None, start_cycle=40) == (0.0, 0)


def test_fill_missing_run_budget_anchors_cycles_per_run(tmp_path: Path) -> None:
    vault = _vault(tmp_path, "  max_cycles: 0\n  cycles_per_run: 3\n")
    _, ceiling = fill_missing_run_budget(vault, None, None, start_cycle=7)
    assert ceiling == 9


def test_resolve_from_path_reads_both_keys(tmp_path: Path) -> None:
    vault = _vault(tmp_path, "  max_cycles: 0\n  cycles_per_run: 2\n")
    res = resolve_cycle_budget_from_path(vault / "settings.yaml", start_cycle=50)
    assert res.max_cycles == 51


# --- the typed loader accepts both keys -------------------------------------


def test_loader_accepts_max_cycles_zero(tmp_path: Path) -> None:
    vault = _vault(tmp_path, "  max_cycles: 0\n")
    settings = load_vault_settings(vault)
    assert settings.max_cycles == 0
    assert settings.cycles_per_run is None
    assert effective_max_cycles(vault) == 0


def test_loader_types_cycles_per_run(tmp_path: Path) -> None:
    vault = _vault(tmp_path, "  max_cycles: 0\n  cycles_per_run: 4\n")
    settings = load_vault_settings(vault)
    assert settings.cycles_per_run == 4
    assert "cycles_per_run" not in settings.extras.get("pipeline", {})


@pytest.mark.parametrize("bad", ["-1", "1.5", "true", "'5'"])
def test_loader_refuses_bad_max_cycles(tmp_path: Path, bad: str) -> None:
    vault = _vault(tmp_path, f"  max_cycles: {bad}\n")
    with pytest.raises(SettingsError) as exc:
        load_vault_settings(vault)
    assert exc.value.key == "max_cycles"


@pytest.mark.parametrize("bad", ["0", "-2", "1.5", "true", "'3'"])
def test_loader_refuses_bad_cycles_per_run(tmp_path: Path, bad: str) -> None:
    vault = _vault(tmp_path, f"  max_cycles: 0\n  cycles_per_run: {bad}\n")
    with pytest.raises(SettingsError) as exc:
        load_vault_settings(vault)
    assert exc.value.key == "pipeline.cycles_per_run"


# --- display and planning helpers -------------------------------------------


def test_format_cycle_ceiling() -> None:
    assert format_cycle_ceiling(0) == "unlimited"
    assert format_cycle_ceiling(12) == "12"


def test_planning_horizon_is_the_ceiling_when_finite() -> None:
    assert planning_horizon(12, 3) == 12


def test_planning_horizon_rolls_forward_when_unlimited() -> None:
    """No end point ⇒ plan as if the default horizon started at this cycle."""
    assert planning_horizon(0, 1) == DEFAULT_MAX_CYCLES
    assert planning_horizon(0, 30) == 30 + DEFAULT_MAX_CYCLES - 1


# --- a multi-cycle run must have SOME bound (review of #33) -----------------
#
# `max_cycles: 0` with no per-run cap and no dollar cap leaves a run with fuel
# nothing to stop it: Condition B/C TERMINATE comes back as rc 1 and the loop
# continues, and the `limits.*` caps are per cycle. Run resolution refuses that
# combination; `load_vault_settings` does not, so status and digest still load.


def _unbounded_settings(**pipeline: object) -> dict:
    return {"pipeline": {"max_cycles": 0, "budget_usd": 0, **pipeline}}


def test_an_unbounded_multi_cycle_run_is_refused() -> None:
    res = resolve_cycle_budget(_unbounded_settings(), start_cycle=86)
    with pytest.raises(BudgetError) as exc:
        require_bounded_run(res)
    message = str(exc.value)
    for remedy in (
        "pipeline.cycles_per_run",
        "pipeline.max_cycles",
        "pipeline.budget_usd",
        "--more-cycles",
        "--max-cycles",
        "--max-usd",
        "--max-usd-this-run",
    ):
        assert remedy in message, f"the refusal must name {remedy}"


def test_a_zero_dollar_flag_is_no_escape_hatch() -> None:
    """``--max-usd 0`` / ``--max-usd-this-run 0`` mean unlimited, not a bound."""
    res = resolve_cycle_budget(
        _unbounded_settings(), flag_max_usd=0.0, flag_max_usd_this_run=0.0
    )
    with pytest.raises(BudgetError):
        require_bounded_run(res)


@pytest.mark.parametrize(
    ("settings", "flags"),
    [
        (_unbounded_settings(cycles_per_run=3), {}),
        ({"pipeline": {"max_cycles": 40, "budget_usd": 0}}, {}),
        (_unbounded_settings(budget_usd=25.0), {}),
        (_unbounded_settings(), {"flag_more_cycles": 2}),
        (_unbounded_settings(), {"flag_max_cycles": 100}),
        (_unbounded_settings(), {"flag_max_usd": 5.0}),
        (_unbounded_settings(), {"flag_max_usd_this_run": 2.0}),
    ],
    ids=[
        "cycles_per_run",
        "finite-max_cycles",
        "budget_usd",
        "--more-cycles",
        "--max-cycles",
        "--max-usd",
        "--max-usd-this-run",
    ],
)
def test_each_escape_hatch_bounds_the_run(settings: dict, flags: dict) -> None:
    require_bounded_run(resolve_cycle_budget(settings, start_cycle=86, **flags))


def test_the_typed_loader_still_loads_an_unbounded_vault(tmp_path: Path) -> None:
    """Refusal lives in run resolution, so `status` / `digest` keep working."""
    vault = _vault(tmp_path, "  max_cycles: 0\n")
    assert load_vault_settings(vault).max_cycles == 0


# --- the multi-cycle CLI verbs refuse before any cycle runs ------------------


def _resume_args(vault_dir: Path, **over: object):
    from unittest import mock

    args = mock.Mock()
    args.legacy_cycle_runner = False
    args.output = vault_dir
    args.spec = vault_dir / "research.spec.md"
    args.cycle = 86
    args.max_cycles = None
    args.max_usd = None
    args.more_cycles = None
    args.max_usd_this_run = None
    for key, value in over.items():
        setattr(args, key, value)
    return args


def _stub_resume(monkeypatch: pytest.MonkeyPatch, vault_dir: Path) -> list[dict]:
    from types import SimpleNamespace

    from research_framework import cli

    calls: list[dict] = []
    (vault_dir / "research.spec.md").write_text("---\nname: t\n---\n", "utf-8")
    monkeypatch.setattr(cli, "load_spec", lambda *_a, **_k: SimpleNamespace(name="t"))
    monkeypatch.setattr(cli, "validate", lambda _spec: None)
    monkeypatch.setattr(cli, "_run_phase3", lambda *_a: 0)
    monkeypatch.setattr(
        "research_framework.pipeline.preconditions.check",
        lambda _vd, *, for_resume: (True, []),
    )
    monkeypatch.setattr(
        "research_framework.pipeline.orchestrator.run_cycles",
        lambda _spec, _vd, **kw: calls.append(kw) or 0,
    )
    return calls


def test_resume_refuses_an_unbounded_run_with_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    from research_framework import cli

    vault = _vault(tmp_path, "  max_cycles: 0\n")
    calls = _stub_resume(monkeypatch, vault)

    rc = cli._resume(_resume_args(vault))

    assert rc == 2
    assert calls == [], "no cycle may run"
    assert "pipeline.cycles_per_run" in capsys.readouterr().err


def test_resume_with_more_cycles_is_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from research_framework import cli

    vault = _vault(tmp_path, "  max_cycles: 0\n")
    calls = _stub_resume(monkeypatch, vault)

    rc = cli._resume(_resume_args(vault, more_cycles=2))

    assert rc == 0
    assert calls and calls[0]["budget"].max_cycles == 87
