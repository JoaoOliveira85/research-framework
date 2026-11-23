"""Tier 1: ``pipeline.cycle_split`` is three non-negative integers summing to
100 (spec 087 FR-015)."""

from __future__ import annotations

import tempfile
import warnings
from pathlib import Path

import pytest

from research_framework.pipeline.settings import (
    CycleSplit,
    SettingsError,
    UnknownSettingsKeyWarning,
    load_vault_settings,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIPPED = sorted(REPO_ROOT.glob("settings*.yaml")) + [
    REPO_ROOT / "examples" / "settings.yml"
]


def _load(tmp_path: Path, split: str | None):
    vault = tmp_path / "vault"
    vault.mkdir(exist_ok=True)
    body = "pipeline:\n  max_cycles: 5\n  budget_usd: 10.0\n"
    if split is not None:
        body += f"  cycle_split:{split}\n"
    (vault / "settings.yaml").write_text(body, encoding="utf-8")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UnknownSettingsKeyWarning)
        return load_vault_settings(vault)


def test_absent_means_60_30_10(tmp_path: Path) -> None:
    assert _load(tmp_path, None).cycle_split == CycleSplit(60, 30, 10)


def test_a_valid_split_is_read(tmp_path: Path) -> None:
    got = _load(tmp_path, "\n    new: 50\n    updates: 50\n    discovery: 0")
    assert got.cycle_split == CycleSplit(new=50, updates=50, discovery=0)
    assert "cycle_split" not in got.extras.get("pipeline", {})


@pytest.mark.parametrize(
    "split",
    [
        "\n    new: 60\n    updates: 30\n    discovery: 11",  # sums to 101
        "\n    new: 60\n    updates: 30\n    discovery: 9",  # sums to 99
        "\n    new: 70\n    updates: 40\n    discovery: -10",  # negative
        '\n    new: "60"\n    updates: 30\n    discovery: 10',  # not an integer
        "\n    new: 60.5\n    updates: 29.5\n    discovery: 10",
        "\n    new: true\n    updates: 30\n    discovery: 10",  # a bool is no integer
        "\n    new: 60\n    updates: 40",  # discovery missing
        "\n    new: 60\n    update: 30\n    discovery: 10",  # a typo'd key
        "\n    new: 60\n    updates: 30\n    discovery: 10\n    extra: 0",
        " 100",  # not a mapping
    ],
)
def test_shares_must_be_three_non_negative_integers_summing_to_100(
    tmp_path: Path, split: str
) -> None:
    with pytest.raises(SettingsError) as exc:
        _load(tmp_path, split)
    assert "cycle_split" in str(exc.value)


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: p.name)
def test_every_shipped_profile_declares_the_default_and_no_research_modes(
    path: Path,
) -> None:
    text = path.read_text(encoding="utf-8")
    assert "research_modes:" not in text
    assert "auto-detected" not in text  # the promised auto-detection is gone
    block = "\n  cycle_split:\n    new: 60\n    updates: 30\n    discovery: 10"
    assert block in text
    if path.parent.name == "examples":
        return  # an illustration, not a loadable vault file (no max_cycles)
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "settings.yaml").write_text(text, encoding="utf-8")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            settings = load_vault_settings(Path(d))
    ours = [
        str(w.message)
        for w in caught
        if "cycle_split" in str(w.message) or "research_modes" in str(w.message)
    ]
    assert ours == []
    assert settings.cycle_split == CycleSplit(60, 30, 10)
