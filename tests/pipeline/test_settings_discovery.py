"""Tier 1: ``pipeline.discovery`` is two positive integers with defaults
(spec 088 FR-001, FR-012)."""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from research_framework.pipeline.settings import (
    DiscoverySettings,
    SettingsError,
    UnknownSettingsKeyWarning,
    load_vault_settings,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIPPED = sorted(REPO_ROOT.glob("settings*.yaml")) + [
    REPO_ROOT / "examples" / "settings.yml"
]


def _load(tmp_path: Path, block: str | None):
    vault = tmp_path / "vault"
    vault.mkdir(exist_ok=True)
    body = "pipeline:\n  max_cycles: 5\n  budget_usd: 10.0\n"
    if block is not None:
        body += f"  discovery:{block}\n"
    (vault / "settings.yaml").write_text(body, encoding="utf-8")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UnknownSettingsKeyWarning)
        return load_vault_settings(vault)


def test_defaults_and_validation(tmp_path: Path) -> None:
    # absent (a vault that predates the spec): the defaults, FR-012
    assert _load(tmp_path, None).discovery == DiscoverySettings(3, 180)
    got = _load(tmp_path, "\n    areas_per_cycle: 5\n    window_days: 90")
    assert got.discovery == DiscoverySettings(areas_per_cycle=5, window_days=90)
    assert "discovery" not in got.extras.get("pipeline", {})
    # one key left out keeps its default
    assert _load(tmp_path, "\n    window_days: 30").discovery == DiscoverySettings(
        3, 30
    )


@pytest.mark.parametrize(
    ("block", "fragment"),
    [
        ("\n    areas_per_cycle: 0", "pipeline.discovery.areas_per_cycle"),
        ("\n    areas_per_cycle: -1", "pipeline.discovery.areas_per_cycle"),
        ('\n    areas_per_cycle: "3"', "pipeline.discovery.areas_per_cycle"),
        ("\n    areas_per_cycle: 2.5", "pipeline.discovery.areas_per_cycle"),
        ("\n    areas_per_cycle: true", "pipeline.discovery.areas_per_cycle"),
        ("\n    window_days: 0", "pipeline.discovery.window_days"),
        ("\n    window_days: 1.5", "pipeline.discovery.window_days"),
        ("\n    area_per_cycle: 3", "area_per_cycle"),  # a typo'd key
        (" 3", "pipeline.discovery"),  # not a mapping
        (" [1, 2]", "pipeline.discovery"),
    ],
)
def test_bad_values_are_field_level_errors(
    tmp_path: Path, block: str, fragment: str
) -> None:
    with pytest.raises(SettingsError) as exc:
        _load(tmp_path, block)
    assert fragment in str(exc.value)


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: p.name)
def test_every_shipped_profile_declares_the_defaults(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "\n  discovery:\n    areas_per_cycle: 3\n    window_days: 180" in text
    if path.parent.name == "examples":
        return
    vault = path.parent / "unused"
    assert vault  # the file itself is loaded below
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "settings.yaml").write_text(text, encoding="utf-8")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            settings = load_vault_settings(Path(d))
    assert [str(w.message) for w in caught if "discovery" in str(w.message)] == []
    assert settings.discovery == DiscoverySettings(3, 180)


def test_the_pass_reads_its_settings(tmp_path: Path) -> None:
    from research_framework.pipeline import discovery

    assert discovery.discovery_settings(tmp_path) == DiscoverySettings(3, 180)
    assert discovery.discovery_share(tmp_path) == 10
    (tmp_path / "settings.yaml").write_text(
        "pipeline:\n  max_cycles: 5\n  budget_usd: 10.0\n"
        "  cycle_split: {new: 70, updates: 30, discovery: 0}\n"
        "  discovery: {areas_per_cycle: 2, window_days: 30}\n",
        encoding="utf-8",
    )
    assert discovery.discovery_settings(tmp_path) == DiscoverySettings(2, 30)
    assert discovery.discovery_share(tmp_path) == 0
