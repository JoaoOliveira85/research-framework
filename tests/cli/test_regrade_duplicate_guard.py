"""Spec 070 F9 — re-grade must not reinstate a collision-renamed duplicate.

`_quarantine_rejected_notes` renames on collision: a second rejection of
`foo.md` lands in quarantine as `foo-3.md`. Re-grade then reinstated BOTH under
their quarantine names, so a vault that quarantined the same note twice came
back with `foo.md` and `foo-3.md` side by side — byte-identical duplicates
polluting the graph and the coverage count.

Observed live on `community-vault`, which gained 9 such duplicates in a
single run while validating the 070 build.
"""

from __future__ import annotations

from pathlib import Path

from research_framework.cli.regrade import duplicate_of_live_note

_NOTE = """---
title: {title}
type: practitioner
coverage_category: practitioners
---

{body}
"""


def _live(vault: Path, name: str, body: str = "Shared body.") -> Path:
    p = vault / "data_vault" / "01 - Practitioners" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_NOTE.format(title=Path(name).stem, body=body), encoding="utf-8")
    return p


def _quarantined(vault: Path, name: str) -> Path:
    p = vault / "_pipeline" / "quarantine" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_NOTE.format(title=Path(name).stem, body="Shared body."), "utf-8")
    return p


def test_identical_collision_copy_is_detected(tmp_path: Path) -> None:
    live = _live(tmp_path, "person_c.md")
    q = _quarantined(tmp_path, "person_c-0.md")
    assert duplicate_of_live_note(tmp_path, q, "Shared body.") == live


def test_differing_body_is_not_a_duplicate(tmp_path: Path) -> None:
    """A genuine variant must never be silently dropped."""
    _live(tmp_path, "person_c.md", body="Original body.")
    q = _quarantined(tmp_path, "person_c-0.md")
    assert duplicate_of_live_note(tmp_path, q, "Shared body.") is None


def test_legitimate_numeric_suffix_is_not_a_collision(tmp_path: Path) -> None:
    """`http-2.md` is a real title; with no live `http.md` it must pass through."""
    q = _quarantined(tmp_path, "http-2.md")
    assert duplicate_of_live_note(tmp_path, q, "Shared body.") is None


def test_note_without_numeric_suffix_is_never_a_duplicate(tmp_path: Path) -> None:
    _live(tmp_path, "person_c.md")
    q = _quarantined(tmp_path, "person_c.md")
    assert duplicate_of_live_note(tmp_path, q, "Shared body.") is None


def test_missing_corpus_is_handled(tmp_path: Path) -> None:
    q = _quarantined(tmp_path, "foo-1.md")
    assert duplicate_of_live_note(tmp_path, q, "b") is None


def test_end_to_end_regrade_leaves_the_duplicate_in_quarantine(tmp_path: Path) -> None:
    """The duplicate stays quarantined; dropping content is the operator's call."""
    import json

    from research_framework.cli.regrade import run_regrade

    _live(tmp_path, "person_c.md")
    dupe = tmp_path / "_pipeline" / "quarantine" / "person_c-0.md"
    dupe.parent.mkdir(parents=True, exist_ok=True)
    dupe.write_text(
        "---\ntitle: person_c-0\ntype: practitioner\n"
        "coverage_category: practitioners\nverifier_status: rejected\n"
        "verifier_notes:\n  - 'citation lacks credibility'\n"
        "source_urls:\n  - url: https://github.com/person-d\n---\n\nShared body.\n",
        encoding="utf-8",
    )

    run_regrade(tmp_path, dry_run=False)

    assert dupe.exists(), "the duplicate must remain quarantined, not be deleted"
    assert not (
        tmp_path / "data_vault" / "01 - Practitioners" / "person_c-0.md"
    ).exists(), "F9: the duplicate must not be reinstated alongside the live note"
    assert json is not None


def test_reinstate_never_overwrites_a_live_note_of_the_same_name(
    tmp_path: Path,
) -> None:
    """The "rewrite quarantined note" backlog flow puts a fresh `foo.md` in
    `data_vault/` while the old rejected `foo.md` is still quarantined. The
    bodies differ, so the duplicate guard does not fire, and `_reinstate`
    atomically replaced the live rewrite with the stale quarantined copy."""
    from research_framework.cli.regrade import run_regrade

    live = _live(tmp_path, "person_c.md", body="NEW REWRITTEN body.")
    stale = tmp_path / "_pipeline" / "quarantine" / "person_c.md"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text(
        "---\ntitle: person_c\ntype: practitioner\n"
        "coverage_category: practitioners\nverifier_status: rejected\n"
        "verifier_notes:\n  - 'citation lacks credibility'\n"
        "source_urls:\n  - url: https://github.com/person-d\n---\n\n"
        "OLD QUARANTINED body.\n",
        encoding="utf-8",
    )

    run_regrade(tmp_path, dry_run=False)

    assert "NEW REWRITTEN body." in live.read_text(encoding="utf-8")
    assert stale.exists(), "the stale copy stays quarantined for the operator"
