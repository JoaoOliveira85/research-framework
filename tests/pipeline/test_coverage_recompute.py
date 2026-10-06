"""FR1 (spec 068) — recompute_from_disk counts on-disk notes, not a stale increment.

Contract: specs/068-coverage-counting-correctness/contracts/coverage-recompute.contract.md
- C1-a: 20 concept notes in ``01 - Concepts/`` recompute ``met_count == 20``.
- C1-b: ``note_type: alias`` stubs are excluded.
- C1-c: a note whose ``coverage_category`` disagrees with its dir is counted by
  frontmatter + a WARN is logged.
"""

from __future__ import annotations

import logging
from pathlib import Path

from research_framework.pipeline.coverage import recompute_from_disk, save_targets
from research_framework.spec.schema import CoverageCategory, CoverageTargets


def _write_note(dir_: Path, filename: str, **fm: object) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    lines = ["---"]
    for key, value in fm.items():
        lines.append(f"{key}: {value}")
    lines += ["---", "", "Body text.", ""]
    (dir_ / filename).write_text("\n".join(lines), encoding="utf-8")


def _seed_targets(vault: Path, *cats: CoverageCategory) -> None:
    (vault / "_pipeline").mkdir(parents=True, exist_ok=True)
    save_targets(vault, CoverageTargets(categories=list(cats)))


def test_recompute_counts_all_on_disk_concepts(tmp_path: Path) -> None:
    """C1-a: 20 concept notes on disk → met_count == 20 (not a stale 2)."""
    vault = tmp_path / "vault"
    concepts = vault / "data_vault" / "01 - Concepts"
    _seed_targets(
        vault,
        CoverageCategory(
            name="concepts",
            note_type="concept",
            target_count=200,
            met_count=2,  # deliberately stale (the rc7 shape)
        ),
    )
    for i in range(20):
        _write_note(
            concepts,
            f"Concept {i:02d}.md",
            type="concept",
            title=f"Concept {i:02d}",
            coverage_category="concepts",
        )

    targets = recompute_from_disk(vault)
    by = {c.name: c.met_count for c in targets.categories}
    assert by["concepts"] == 20


def test_recompute_excludes_alias_stubs(tmp_path: Path) -> None:
    """C1-b: alias/redirect stubs never count toward coverage."""
    vault = tmp_path / "vault"
    concepts = vault / "data_vault" / "01 - Concepts"
    _seed_targets(
        vault,
        CoverageCategory(name="concepts", note_type="concept", target_count=50),
    )
    _write_note(
        concepts,
        "Real.md",
        type="concept",
        title="Real",
        coverage_category="concepts",
    )
    _write_note(
        concepts,
        "ACID alias.md",
        type="concept",
        note_type="alias",
        title="ACID",
        coverage_category="concepts",
    )

    targets = recompute_from_disk(vault)
    by = {c.name: c.met_count for c in targets.categories}
    assert by["concepts"] == 1  # the alias stub is excluded


def test_recompute_frontmatter_wins_over_dir_with_warn(tmp_path: Path, caplog) -> None:
    """C1-c: frontmatter coverage_category wins over the directory; WARN logged."""
    vault = tmp_path / "vault"
    concepts_dir = vault / "data_vault" / "01 - Concepts"
    _seed_targets(
        vault,
        CoverageCategory(
            name="concepts",
            display_name="Concepts",
            note_type="concept",
            target_count=50,
        ),
        CoverageCategory(
            name="algorithms",
            display_name="Algorithms",
            note_type="concept",
            target_count=50,
        ),
    )
    # Note lives under "01 - Concepts/" but declares coverage_category: algorithms.
    _write_note(
        concepts_dir,
        "Dijkstra.md",
        type="concept",
        title="Dijkstra",
        coverage_category="algorithms",
    )

    with caplog.at_level(logging.WARNING):
        targets = recompute_from_disk(vault)

    by = {c.name: c.met_count for c in targets.categories}
    assert by["algorithms"] == 1  # frontmatter wins
    assert by["concepts"] == 0
    assert any(
        "coverage_category" in rec.message.lower() or "disagree" in rec.message.lower()
        for rec in caplog.records
    )


def test_recompute_is_idempotent(tmp_path: Path) -> None:
    """Running twice yields identical counts (pure + idempotent)."""
    vault = tmp_path / "vault"
    concepts = vault / "data_vault" / "01 - Concepts"
    _seed_targets(
        vault,
        CoverageCategory(name="concepts", note_type="concept", target_count=50),
    )
    for i in range(5):
        _write_note(
            concepts,
            f"C{i}.md",
            type="concept",
            coverage_category="concepts",
        )

    first = {c.name: c.met_count for c in recompute_from_disk(vault).categories}
    second = {c.name: c.met_count for c in recompute_from_disk(vault).categories}
    assert first == second == {"concepts": 5}


def test_recompute_persists_to_targets_file(tmp_path: Path) -> None:
    """The recount is written back to coverage-targets.json (cache write)."""
    from research_framework.pipeline.coverage import load_targets

    vault = tmp_path / "vault"
    concepts = vault / "data_vault" / "01 - Concepts"
    _seed_targets(
        vault,
        CoverageCategory(name="concepts", note_type="concept", target_count=50),
    )
    for i in range(3):
        _write_note(concepts, f"C{i}.md", type="concept", coverage_category="concepts")

    recompute_from_disk(vault)
    reloaded = load_targets(vault)
    assert {c.name: c.met_count for c in reloaded.categories} == {"concepts": 3}
