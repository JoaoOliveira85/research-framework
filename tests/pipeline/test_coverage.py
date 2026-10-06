"""Tests for src/research_framework/pipeline/coverage.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.pipeline.coverage import (
    all_targets_met,
    classify_note_category,
    load_targets,
    save_targets,
    unmet_targets,
    update_after_cycle,
)
from research_framework.spec.schema import CoverageCategory, CoverageTargets


def test_load_targets_returns_parsed(tmp_vault_dir: Path) -> None:
    targets = load_targets(tmp_vault_dir)
    assert len(targets.categories) == 2
    assert targets.categories[0].name == "concepts"


def test_all_targets_met_false_when_gap(tmp_vault_dir: Path) -> None:
    assert not all_targets_met(tmp_vault_dir)


def test_unmet_targets_names_unmet_categories(tmp_vault_dir: Path) -> None:
    names = unmet_targets(tmp_vault_dir)
    assert "concepts" in names  # gap 2
    assert "services" not in names  # met


def test_all_targets_met_true_when_all_met(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    pipeline = vault / "_pipeline"
    pipeline.mkdir(parents=True)
    targets = CoverageTargets(
        categories=[
            CoverageCategory(name="c", note_type="concept", target_count=2, met_count=2)
        ]
    )
    save_targets(vault, targets)
    assert all_targets_met(vault)


def test_load_targets_malformed_raises(tmp_vault_dir: Path) -> None:
    (tmp_vault_dir / "_pipeline" / "coverage-targets.json").write_text("not json {{{")
    with pytest.raises(RuntimeError) as exc:
        load_targets(tmp_vault_dir)
    assert "malformed" in str(exc.value)


def test_load_targets_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_targets(tmp_path)


def test_update_after_cycle_increments(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    data = vault / "data_vault" / "01 - Concepts"
    data.mkdir(parents=True)
    pipeline = vault / "_pipeline"
    pipeline.mkdir()
    targets = CoverageTargets(
        categories=[
            CoverageCategory(name="c", note_type="concept", target_count=5, met_count=0)
        ]
    )
    save_targets(vault, targets)

    # Write a new concept note
    (data / "New Concept.md").write_text(
        "---\ntype: concept\ntitle: New Concept\n---\n\nBody.\n"
    )
    report = {"notes_created": ["New Concept.md"]}
    updated = update_after_cycle(vault, report, cycle_number=1)
    assert updated.categories[0].met_count == 1
    assert updated.cycle_number == 1


def test_save_is_atomic(tmp_path: Path) -> None:
    """save_targets uses temp-file + rename (no partial write observable)."""
    vault = tmp_path / "vault"
    (vault / "_pipeline").mkdir(parents=True)
    targets = CoverageTargets(
        categories=[CoverageCategory(name="c", note_type="x", target_count=1)]
    )
    save_targets(vault, targets)
    path = vault / "_pipeline" / "coverage-targets.json"
    assert path.exists()
    # File must be fully valid JSON (no partial writes visible)
    data = json.loads(path.read_text())
    assert data["categories"][0]["name"] == "c"


# --- Per-category classification (v0.2.12) ---


def _cats(*triples: tuple[str, str, int]) -> list[CoverageCategory]:
    """Shorthand: each triple is ``(name, display_name, target)``."""
    return [
        CoverageCategory(name=n, display_name=dn, note_type="concept", target_count=t)
        for n, dn, t in triples
    ]


def test_classify_uses_explicit_coverage_category() -> None:
    cats = _cats(
        ("recipes", "Batch-cook freezer recipes", 5),
        ("nutrition", "Macro and micronutrient coverage", 5),
    )
    fm = {
        "title": "Chicken rice bowl",
        "summary": "macro-heavy recipe with rice and chicken",
        "coverage_category": "nutrition",
    }
    chosen = classify_note_category(fm, "chicken_rice.md", cats)
    assert chosen is not None and chosen.name == "nutrition"


def test_classify_unknown_explicit_falls_back_to_keywords() -> None:
    cats = _cats(
        ("recipes", "Batch cooking freezer recipes portioning reheating", 5),
        ("nutrition", "Macro coverage micronutrient context", 5),
    )
    fm = {
        "title": "Chicken and rice freezer portions",
        "summary": "batch cooking and portioning a chicken rice meal",
        "tags": ["batch", "freezer"],
        "coverage_category": "made-up-slug",
    }
    chosen = classify_note_category(fm, "chicken_rice.md", cats)
    assert chosen is not None and chosen.name == "recipes"


def test_classify_keyword_overlap_picks_best_display_name_match() -> None:
    cats = _cats(
        ("recipes", "Batch cooking freezer recipes portioning reheating", 5),
        ("nutrition", "Macro coverage micronutrient context", 5),
    )
    fm = {
        "title": "Macro balance across a week",
        "summary": "Weekly micronutrient and macro context for meal planning",
        "tags": ["nutrition"],
    }
    chosen = classify_note_category(fm, "macro_balance.md", cats)
    assert chosen is not None and chosen.name == "nutrition"


def test_classify_round_robin_when_no_keyword_overlap() -> None:
    cats = _cats(
        ("alpha", "Alpha topic about xyzzy", 5),
        ("beta", "Beta topic about frobnicate", 5),
    )
    cats[0].met_count = 3  # smaller gap (2)
    cats[1].met_count = 0  # bigger gap (5) — should be chosen
    fm = {"title": "Unrelated thing", "summary": "nothing in common"}
    chosen = classify_note_category(fm, "unrelated.md", cats)
    assert chosen is not None and chosen.name == "beta"


def test_classify_returns_none_for_empty_category_list() -> None:
    assert classify_note_category({"title": "anything"}, "x.md", []) is None


def _write_concept(dir_: Path, filename: str, **fm) -> None:
    """Emit a minimal concept note with the given frontmatter keys."""
    lines = ["---", "type: concept"]
    for k, v in fm.items():
        if isinstance(v, list):
            lines.append(f"{k}:")
            for item in v:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{k}: {v}")
    lines += ["---", "", "Body.", ""]
    (dir_ / filename).write_text("\n".join(lines))


def test_update_after_cycle_increments_only_one_category(tmp_path: Path) -> None:
    """Regression: pre-v0.2.12 every concept note bumped every concept
    category, so 6 categories × target 5 were "met" after just 5 notes. The
    DFS-stamped ``coverage_category`` field MUST now direct the increment
    to exactly one bucket."""
    vault = tmp_path / "vault"
    data = vault / "data_vault" / "01 - Concepts"
    data.mkdir(parents=True)
    (vault / "_pipeline").mkdir()
    targets = CoverageTargets(
        categories=[
            CoverageCategory(
                name="recipes",
                display_name="Batch cooking freezer recipes",
                note_type="concept",
                target_count=5,
            ),
            CoverageCategory(
                name="nutrition",
                display_name="Macro coverage micronutrient context",
                note_type="concept",
                target_count=5,
            ),
        ]
    )
    save_targets(vault, targets)

    _write_concept(
        data, "recipe_one.md", title="Recipe one", coverage_category="recipes"
    )
    _write_concept(
        data, "macros_one.md", title="Macro primer", coverage_category="nutrition"
    )

    updated = update_after_cycle(
        vault, {"notes_created": ["recipe_one.md", "macros_one.md"]}, cycle_number=1
    )
    counts = {c.name: c.met_count for c in updated.categories}
    assert counts == {"recipes": 1, "nutrition": 1}


def test_update_after_cycle_restricts_classification_to_matching_note_type(
    tmp_path: Path,
) -> None:
    """A ``source`` note must not count against a ``concept`` category even
    if its title happens to keyword-match."""
    vault = tmp_path / "vault"
    data_c = vault / "data_vault" / "01 - Concepts"
    data_s = vault / "data_vault" / "02 - Sources"
    data_c.mkdir(parents=True)
    data_s.mkdir(parents=True)
    (vault / "_pipeline").mkdir()
    targets = CoverageTargets(
        categories=[
            CoverageCategory(
                name="recipes",
                display_name="Batch cooking freezer recipes",
                note_type="concept",
                target_count=5,
            ),
            CoverageCategory(
                name="source-articles",
                display_name="Primary-source articles",
                note_type="source",
                target_count=2,
            ),
        ]
    )
    save_targets(vault, targets)

    _write_concept(data_c, "recipe_a.md", title="Recipe A", coverage_category="recipes")
    # ``source`` note with no explicit coverage_category — should still land
    # in the source bucket via round-robin, NOT in the concept bucket.
    (data_s / "source_x.md").write_text(
        "---\ntype: source\ntitle: Source X\n---\n\nBody.\n"
    )

    updated = update_after_cycle(
        vault, {"notes_created": ["recipe_a.md", "source_x.md"]}, cycle_number=1
    )
    counts = {c.name: c.met_count for c in updated.categories}
    assert counts == {"recipes": 1, "source-articles": 1}
