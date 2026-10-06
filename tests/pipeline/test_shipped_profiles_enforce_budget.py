"""Every shipped settings profile must resolve to a LIVE budget cap (issue #230).

Spec 033 ships three ceilings — a per-cycle dollar cap, a per-cycle wall-clock
cap and (for metered runtimes) a token cap — and spec 061 ships a run-level
cumulative dollar cap on top. Every one of them is opt-in by absence:
``budget_guard`` skips a limit that is ``None``, and ``orchestrator``'s
``cumulative >= budget_cap > 0`` skips a cap of ``0.0``. The six profiles this
repo ships declared no ``limits:`` block at all and ``pipeline.budget_usd:
0.0``, so a headless ``generate`` / ``--resume`` run against a freshly
generated vault had no dollar, token or wall-clock ceiling whatsoever — on a
framework whose whole promise is running unattended.

These are guard tests over the committed profiles, not over a fixture: the
defect was in the shipped configuration, so only the shipped configuration can
pin it.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from research_framework.cli._budget_resolve import resolve_cycle_budget_from_path
from research_framework.pipeline.settings import load_vault_settings

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Every profile the repo ships. Collected by glob so a seventh profile added
#: later inherits the guarantee instead of quietly opting out of it.
SHIPPED_PROFILES: list[Path] = sorted(REPO_ROOT.glob("settings*.yaml"))


def _load(profile: Path, tmp_path: Path):
    shutil.copy(profile, tmp_path / "settings.yaml")
    return load_vault_settings(tmp_path)


def test_repo_ships_the_expected_profile_set() -> None:
    """Guard the guard: an empty glob would make every test below vacuous."""
    names = {p.name for p in SHIPPED_PROFILES}
    assert "settings.yaml" in names
    assert len(SHIPPED_PROFILES) >= 6


@pytest.mark.parametrize("profile", SHIPPED_PROFILES, ids=lambda p: p.name)
def test_profile_declares_a_live_cycle_dollar_cap(profile: Path, tmp_path: Path):
    settings = _load(profile, tmp_path)
    cap = settings.limits.cycle_budget_usd
    assert cap is not None, f"{profile.name}: limits.cycle_budget_usd is unset — "
    assert cap > 0, f"{profile.name}: limits.cycle_budget_usd must be > 0"


@pytest.mark.parametrize("profile", SHIPPED_PROFILES, ids=lambda p: p.name)
def test_profile_declares_a_live_wallclock_cap(profile: Path, tmp_path: Path):
    settings = _load(profile, tmp_path)
    wall = settings.limits.cycle_wallclock_budget_minutes
    assert wall is not None, f"{profile.name}: cycle_wallclock_budget_minutes unset"
    assert wall > 0


@pytest.mark.parametrize("profile", SHIPPED_PROFILES, ids=lambda p: p.name)
def test_profile_resolves_to_a_live_orchestrator_budget_cap(
    profile: Path, tmp_path: Path
) -> None:
    """``pipeline.budget_usd`` must survive spec 061's ladder as a live cap.

    ``orchestrator.run_cycles`` computes ``budget_cap = budget.max_usd or 0.0``
    and then guards on ``cumulative >= budget_cap > 0``: a resolved ``0.0`` is
    indistinguishable from "uncapped", which is what every profile shipped.
    """
    shutil.copy(profile, tmp_path / "settings.yaml")
    resolution = resolve_cycle_budget_from_path(tmp_path / "settings.yaml")
    assert resolution.max_usd is not None, f"{profile.name}: budget_usd unresolved"
    assert resolution.max_usd > 0, (
        f"{profile.name}: pipeline.budget_usd resolves to "
        f"{resolution.max_usd!r}, which disables the cumulative cap"
    )
    assert resolution.max_usd_source == "settings"


@pytest.mark.parametrize("profile", SHIPPED_PROFILES, ids=lambda p: p.name)
def test_profile_has_no_unparsed_budget_block(profile: Path, tmp_path: Path) -> None:
    """The old top-level ``budget:`` block was never read by the loader.

    It sat in ``VaultSettings.extras`` looking like configuration and enforcing
    nothing, next to a ``limits:`` block that does the same job for real. Two
    spellings of one fact is exactly how ``max_usd: null`` came to read as a
    deliberate choice.
    """
    settings = _load(profile, tmp_path)
    assert "budget" not in settings.extras, (
        f"{profile.name}: top-level `budget:` is not parsed by the settings "
        "loader — express caps under `limits:` instead"
    )
