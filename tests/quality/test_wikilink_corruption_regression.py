"""T029 (spec 067) — quality-gated guard against the rc7 acronym corruption.

A ``CAP Theorem`` note whose first body wikilink renames its own title to a
sibling ``cache-aside pattern`` expansion MUST be flagged by the deterministic
verifier rule (``deterministic_wikilink_violations``), and a clean note (first
link a genuinely different concept) MUST stay silent.

Wired into ``build.sh``'s SMOKE_TESTS so a regression that re-introduces the rc7
``[[cache-aside pattern]] Theorem`` corruption (or breaks the title-corruption
gate) hard-fails the release gate. Fast tier-2 guard (<1s), not an e2e harness
test.
"""

from __future__ import annotations

from pathlib import Path

from research_framework.pipeline.verifier import deterministic_wikilink_violations


def _cap_vault(root: Path) -> Path:
    """A vault where ``cache-aside pattern`` claims acronym ``CAP`` and a sibling
    ``CAP Theorem`` note exists — the rc7 corruption shape."""
    vault = root / "wikilink-corruption"
    data = vault / "data_vault"
    data.mkdir(parents=True)
    (data / "cache-aside-pattern.md").write_text(
        "---\ntitle: Cache-Aside Pattern\ntype: concept\n---\nBody.\n",
        encoding="utf-8",
    )
    return vault


def test_self_title_corruption_is_flagged(tmp_path: Path) -> None:
    vault = _cap_vault(tmp_path)
    note_rel = "data_vault/cap-theorem.md"
    note_text = (
        "---\ntitle: CAP Theorem\ntype: concept\n---\n"
        "The [[CAP]] Theorem is about distributed systems.\n"
    )
    (vault / note_rel).write_text(note_text, encoding="utf-8")
    violations = deterministic_wikilink_violations(vault, note_rel, note_text)
    assert len(violations) == 1
    assert violations[0]["rule_id"] == "IX-wikilink-title-corruption"


def test_clean_note_is_silent(tmp_path: Path) -> None:
    vault = _cap_vault(tmp_path)
    note_rel = "data_vault/cap-theorem.md"
    note_text = (
        "---\ntitle: CAP Theorem\ntype: concept\n---\n"
        "It constrains [[consistency]] under network partitions.\n"
    )
    (vault / note_rel).write_text(note_text, encoding="utf-8")
    assert deterministic_wikilink_violations(vault, note_rel, note_text) == []
