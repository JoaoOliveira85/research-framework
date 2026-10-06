"""FR2 (spec 068) — cycle-end coverage invariant: recount is authoritative.

Contract C2:
- C2-a: a cycle that writes N notes ends with ``sum(met_count) == N``.
- divergence between the incrementally-written value and the disk recount is
  surfaced with a loud WARN (WARN-and-trust, analyze U1) and the recount is trusted.
"""

from __future__ import annotations

import logging
from pathlib import Path

from research_framework.pipeline.coverage import (
    load_targets,
    save_targets,
    update_after_cycle,
)
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


def test_cycle_end_recount_equals_notes_written(tmp_path: Path) -> None:
    """C2-a: a fresh cycle that writes N notes ends with sum(met_count) == N."""
    vault = tmp_path / "vault"
    concepts = vault / "data_vault" / "01 - Concepts"
    _seed_targets(
        vault,
        CoverageCategory(name="concepts", note_type="concept", target_count=50),
    )
    created = []
    for i in range(7):
        name = f"C{i}.md"
        _write_note(concepts, name, type="concept", coverage_category="concepts")
        created.append(name)

    targets = update_after_cycle(vault, {"notes_created": created}, cycle_number=1)
    assert sum(c.met_count for c in targets.categories) == 7


def test_divergent_written_value_is_surfaced_and_recount_trusted(
    tmp_path: Path, caplog
) -> None:
    """A stale/diverging met_count is detected (WARN) and the recount is trusted.

    Reproduces the rc7 self-heal: coverage-targets.json carries a wrong met_count
    (99) while only 3 notes exist on disk. The invariant must log a loud WARN and
    write the true recount (3), never silently keep the wrong value.
    """
    vault = tmp_path / "vault"
    concepts = vault / "data_vault" / "01 - Concepts"
    _seed_targets(
        vault,
        CoverageCategory(
            name="concepts",
            note_type="concept",
            target_count=200,
            met_count=99,  # wrong / stale
        ),
    )
    for i in range(3):
        _write_note(concepts, f"C{i}.md", type="concept", coverage_category="concepts")

    with caplog.at_level(logging.WARNING):
        # No new notes reported this cycle, yet disk holds 3 — divergence.
        targets = update_after_cycle(vault, {"notes_created": []}, cycle_number=2)

    by = {c.name: c.met_count for c in targets.categories}
    assert by["concepts"] == 3  # recount trusted, stale 99 discarded
    assert load_targets(vault).categories[0].met_count == 3
    assert any(
        "invariant" in rec.message.lower() or "divergence" in rec.message.lower()
        for rec in caplog.records
    )


def test_clean_cycle_does_not_warn(tmp_path: Path, caplog) -> None:
    """Steady state: prior recount + new notes == disk recount → no spurious WARN."""
    vault = tmp_path / "vault"
    concepts = vault / "data_vault" / "01 - Concepts"
    _seed_targets(
        vault,
        CoverageCategory(name="concepts", note_type="concept", target_count=50),
    )
    # Cycle 1: write 4 notes.
    for i in range(4):
        _write_note(concepts, f"C{i}.md", type="concept", coverage_category="concepts")
    update_after_cycle(
        vault,
        {"notes_created": [f"C{i}.md" for i in range(4)]},
        cycle_number=1,
    )
    # Cycle 2: write 2 more, report them honestly.
    caplog.clear()
    new = []
    for i in range(4, 6):
        name = f"C{i}.md"
        _write_note(concepts, name, type="concept", coverage_category="concepts")
        new.append(name)
    with caplog.at_level(logging.WARNING):
        targets = update_after_cycle(vault, {"notes_created": new}, cycle_number=2)

    assert sum(c.met_count for c in targets.categories) == 6
    assert not any(
        "invariant" in rec.message.lower() or "divergence" in rec.message.lower()
        for rec in caplog.records
    )
