"""Tier 3: a superseded or retracted note stops counting toward coverage (spec
087 FR-018, SC-004 first half; T010)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from research_framework.pipeline.coverage import (
    currency_counts,
    recompute_from_disk,
    save_targets,
)
from research_framework.spec.schema import CoverageCategory, CoverageTargets


def _note(folder: Path, name: str, **fm: object) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    lines = ["---", "type: concept", "coverage_category: concepts"]
    lines += [f"{k}: {v}" for k, v in fm.items()]
    lines += ["---", "", "Body.", ""]
    path = folder / f"{name}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "_pipeline").mkdir(parents=True)
    save_targets(
        vault,
        CoverageTargets(
            categories=[
                CoverageCategory(name="concepts", note_type="concept", target_count=10)
            ]
        ),
    )
    return vault


def _met(vault: Path) -> int:
    (cat,) = recompute_from_disk(vault, persist=False).categories
    return cat.met_count


def test_a_superseded_note_stops_counting(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    folder = vault / "data_vault" / "01 - Concepts"
    _note(folder, "unstamped")  # no fields: reads as current
    _note(folder, "current", as_of="2026-01-01", currency="current")
    _note(folder, "emerging", currency="emerging")
    _note(folder, "declining", currency="declining")
    old = _note(folder, "old", as_of="2020-01-01", currency="current")
    gone = _note(folder, "gone", as_of="2020-01-01", currency="current")
    assert _met(vault) == 6

    old.write_text(old.read_text().replace("currency: current", "currency: superseded"))
    assert _met(vault) == 5  # SC-004: the superseded note no longer counts

    gone.write_text(
        gone.read_text().replace("currency: current", "currency: retracted")
    )
    assert _met(vault) == 4

    # persisted, the recount agrees; and the file was only written when asked to
    (cat,) = recompute_from_disk(vault).categories
    assert cat.met_count == 4


def test_currency_counts_per_category(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    folder = vault / "data_vault" / "01 - Concepts"
    _note(folder, "fresh", as_of="2026-11-20", currency="current")
    _note(folder, "stale", as_of="2020-01-01", currency="current")
    _note(folder, "stale-declining", as_of="2020-01-01", currency="declining")
    _note(folder, "never-stamped")
    _note(folder, "super", as_of="2020-01-01", currency="superseded")
    _note(folder, "retr", as_of="2020-01-01", currency="retracted")

    counts = currency_counts(vault, intervals={"concept": 90}, today=date(2026, 11, 23))

    assert counts["concepts"].past_review == 2  # superseded notes are not "due"
    assert counts["concepts"].uncountable == 2
    # no interval declared: nothing is past review, the uncountable still show
    bare = currency_counts(vault, intervals={}, today=date(2026, 11, 23))
    assert (bare["concepts"].past_review, bare["concepts"].uncountable) == (0, 2)
