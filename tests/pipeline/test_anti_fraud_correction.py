"""Anti-fraud guard for correction batches.

Reproduces the v0.2.19 cycle-6 fraud signature: SG-005 forces a correction
batch, the agent edits frontmatter on existing notes ("renames the title"),
writes zero new files, and the cycle records the batch as successful. The
guard fires SG-006 whenever a correction batch produces no new notes AND
leaves every existing note's *body* untouched.
"""

from __future__ import annotations

from pathlib import Path

from research_framework.pipeline.cycle_runner import (
    _detect_cosmetic_only_correction,
    _snapshot_note_bodies,
    _split_note_frontmatter,
)


def _seed_note(vault_dir: Path, rel: str, frontmatter: str, body: str) -> Path:
    p = vault_dir / "data_vault" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\n{frontmatter}---\n{body}", encoding="utf-8")
    return p


def test_split_note_frontmatter_handles_present_and_absent() -> None:
    fm, body = _split_note_frontmatter("---\ntitle: x\n---\nhello\n")
    assert fm.strip() == "title: x"
    assert body == "\nhello\n"

    fm, body = _split_note_frontmatter("no fm here\n")
    assert fm == ""
    assert body == "no fm here\n"


def test_no_changes_at_all_still_fires_on_correction_batch(tmp_path: Path) -> None:
    """Correction batch with literally zero modifications is itself fraud
    (the agent claimed completion without writing anything)."""
    _seed_note(tmp_path, "01 - Concepts/Example.md", "title: Old\n", "Body content\n")
    before = _snapshot_note_bodies(tmp_path / "data_vault")
    fraud = _detect_cosmetic_only_correction(
        tmp_path / "data_vault", before, new_note_paths=[]
    )
    assert fraud is not None
    assert fraud.gate_id == "SG-006"
    assert "cosmetic" in fraud.message.lower()


def test_frontmatter_only_edit_is_flagged(tmp_path: Path) -> None:
    """The cycle-6 signature: title rename without touching the body."""
    path = _seed_note(
        tmp_path, "01 - Concepts/Example.md", "title: Old\n", "Body content\n"
    )
    before = _snapshot_note_bodies(tmp_path / "data_vault")
    # Simulate the agent "renaming the title" to satisfy the directive.
    path.write_text(
        "---\ntitle: New Pretty Title\n---\nBody content\n", encoding="utf-8"
    )
    fraud = _detect_cosmetic_only_correction(
        tmp_path / "data_vault", before, new_note_paths=[]
    )
    assert fraud is not None
    assert fraud.gate_id == "SG-006"


def test_body_change_clears_the_guard(tmp_path: Path) -> None:
    """Real deepening (body changes) is legitimate even with zero new notes."""
    path = _seed_note(
        tmp_path, "01 - Concepts/Example.md", "title: Old\n", "Body content\n"
    )
    before = _snapshot_note_bodies(tmp_path / "data_vault")
    path.write_text(
        "---\ntitle: Old\n---\nBody content\n\nNew paragraph adding context.\n",
        encoding="utf-8",
    )
    fraud = _detect_cosmetic_only_correction(
        tmp_path / "data_vault", before, new_note_paths=[]
    )
    assert fraud is None


def test_new_note_clears_the_guard(tmp_path: Path) -> None:
    """When the agent writes a new file the correction is by definition not
    cosmetic, even if it ALSO renamed an existing title."""
    _seed_note(tmp_path, "01 - Concepts/Existing.md", "title: Existing\n", "Body.\n")
    before = _snapshot_note_bodies(tmp_path / "data_vault")
    new_note = _seed_note(
        tmp_path, "01 - Concepts/Newly Researched.md", "title: New\n", "Body.\n"
    )
    fraud = _detect_cosmetic_only_correction(
        tmp_path / "data_vault", before, new_note_paths=[new_note]
    )
    assert fraud is None
