"""Spec 062 FR1 — verifier-rejected notes are quarantined on any exit.

A constrained exit must never leave a ``verifier_status: rejected`` note in the
indexed/citable corpus. The orchestrator's finalise sweep moves each into
``_pipeline/quarantine/`` (uncited, unindexed) with a research-backlog pointer,
and the run report headlines the count. Clean exits are unchanged (the rewrite
loop clears rejections first, so the sweep finds zero).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from research_framework.pipeline.orchestrator import (
    _quarantine_out_of_scope_notes,
    _quarantine_rejected_notes,
)
from research_framework.pipeline.run_report import write_run_report


def _note(vault: Path, name: str, status: str, *, notes: str = "") -> Path:
    data = vault / "data_vault"
    data.mkdir(parents=True, exist_ok=True)
    fm = [f"title: {name}", "type: concept", f"verifier_status: {status}"]
    if notes:
        fm.append(f"verifier_notes: {notes}")
    p = data / f"{name}.md"
    p.write_text("---\n" + "\n".join(fm) + "\n---\nBody text.\n", encoding="utf-8")
    return p


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
    )


def _git_vault_with_committed_note(tmp_path: Path, name: str, body: str) -> Path:
    """A git-initialised vault whose ``data_vault/<name>.md`` is already committed
    at HEAD — simulating an existing note from a prior cycle's clean commit
    (the auto-commit invariant guarantees HEAD is clean at cycle start)."""
    vault = tmp_path / "v"
    (vault / "data_vault").mkdir(parents=True)
    _git("init", "-b", "main", cwd=vault)
    _git("config", "user.email", "t@e.com", cwd=vault)
    _git("config", "user.name", "T", cwd=vault)
    (vault / "data_vault" / f"{name}.md").write_text(body, encoding="utf-8")
    _git("add", "-A", cwd=vault)
    _git("commit", "-m", "initial", cwd=vault)
    return vault


def test_constrained_exit_quarantines_all_rejected(tmp_path: Path) -> None:
    """K rejected notes ⇒ 0 left in data_vault/, K in _pipeline/quarantine/."""
    vault = tmp_path / "v"
    _note(vault, "good-one", "accepted")
    _note(vault, "bad-one", "rejected", notes="presents a planned feature as shipped")
    _note(vault, "bad-two", "rejected")
    _note(vault, "bad-three", "rejected")

    count = _quarantine_rejected_notes(vault)

    assert count == 3
    data = vault / "data_vault"
    remaining = {p.stem for p in data.rglob("*.md")}
    assert remaining == {"good-one"}, "no rejected note may remain in the corpus"
    quarantined = {p.stem for p in (vault / "_pipeline" / "quarantine").glob("*.md")}
    assert quarantined == {"bad-one", "bad-two", "bad-three"}


def test_backlog_pointer_appended_with_reason(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    _note(vault, "bad-one", "rejected", notes="missing intent_implementation_drift")
    _quarantine_rejected_notes(vault)
    backlog = (vault / "_pipeline" / "research-backlog.md").read_text(encoding="utf-8")
    assert "rewrite quarantined note: bad-one" in backlog
    assert "missing intent_implementation_drift" in backlog


def test_quarantined_note_not_under_data_vault_scan(tmp_path: Path) -> None:
    """The indexer scans only data_vault/, so a quarantined note is uncitable."""
    vault = tmp_path / "v"
    _note(vault, "bad-one", "rejected")
    _quarantine_rejected_notes(vault)
    scanned = list((vault / "data_vault").rglob("*.md"))
    assert all("bad-one" not in p.stem for p in scanned)


def test_clean_exit_no_rejected_quarantines_zero(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    _note(vault, "good-one", "accepted")
    _note(vault, "good-two", "accepted")
    assert _quarantine_rejected_notes(vault) == 0
    assert not (vault / "_pipeline" / "quarantine").exists()


def test_a_quarantine_move_never_overwrites_an_earlier_quarantined_note(
    tmp_path: Path,
) -> None:
    """Quarantine is the only copy of a brand-new rejected note. The collision
    name was ``<stem>-<count>``, never checked: a second sweep's ``overview``
    landed on the first sweep's ``overview-0.md`` and replaced it."""
    vault = tmp_path / "v"
    quarantine = vault / "_pipeline" / "quarantine"
    quarantine.mkdir(parents=True)
    (quarantine / "overview.md").write_text("first sweep\n", encoding="utf-8")
    (quarantine / "overview-0.md").write_text("second sweep\n", encoding="utf-8")
    _note(vault, "overview", "rejected")

    assert _quarantine_rejected_notes(vault) == 1

    bodies = sorted(p.read_text(encoding="utf-8") for p in quarantine.glob("*.md"))
    assert len(bodies) == 3
    assert "first sweep\n" in bodies and "second sweep\n" in bodies


def test_out_of_scope_quarantine_keeps_same_named_notes_apart(tmp_path: Path) -> None:
    """Two categories may each hold an ``overview.md``. ``rename`` onto the same
    quarantine path silently replaced the first with the second."""
    from types import SimpleNamespace

    vault = tmp_path / "v"
    for folder in ("alpha", "beta"):
        note = vault / "data_vault" / folder / "overview.md"
        note.parent.mkdir(parents=True)
        note.write_text(f"{folder}: crypto mining\n", encoding="utf-8")
    spec = SimpleNamespace(scope=SimpleNamespace(out_of_scope=["crypto"]))

    moved = _quarantine_out_of_scope_notes(vault, spec)

    assert len(moved) == 2
    quarantine = vault / "_pipeline" / "quarantine"
    bodies = sorted(p.read_text(encoding="utf-8") for p in quarantine.glob("*.md"))
    assert bodies == ["alpha: crypto mining\n", "beta: crypto mining\n"]


def test_alias_exempt_note_is_never_quarantined(tmp_path: Path) -> None:
    """``verifier_status: exempt`` (alias/redirect stubs) is left in place."""
    vault = tmp_path / "v"
    _note(vault, "oecdh", "exempt")
    assert _quarantine_rejected_notes(vault) == 0
    assert (vault / "data_vault" / "oecdh.md").exists()


def test_rejected_refresh_of_committed_note_is_restored_not_lost(
    tmp_path: Path,
) -> None:
    """A rejected REWRITE of an already-committed note must not delete the
    original — only the rejected draft goes to quarantine (see the feeds-vault
    cycle-6 incident this regression-tests: SSI/Thinking Machines Lab/Concepts
    MOC were permanently deleted by exactly this bug)."""
    original_body = (
        "---\ntitle: Existing-Note\ntype: concept\nverifier_status: accepted\n"
        "---\nOriginal, previously-accepted body.\n"
    )
    vault = _git_vault_with_committed_note(tmp_path, "Existing-Note", original_body)

    # Simulate the note-writer overwriting the live file in place with a
    # rewrite that the verifier then rejects.
    note = vault / "data_vault" / "Existing-Note.md"
    note.write_text(
        "---\ntitle: Existing-Note\ntype: concept\nverifier_status: rejected\n"
        "verifier_notes: fabricated claim\n---\nRejected rewrite body.\n",
        encoding="utf-8",
    )

    count = _quarantine_rejected_notes(vault)

    assert count == 1
    # The live note must be back to its last-known-good (committed) content —
    # NOT deleted, NOT left holding the rejected draft.
    assert note.read_text(encoding="utf-8") == original_body
    # The rejected draft is preserved for review, not silently discarded.
    quarantined = (vault / "_pipeline" / "quarantine" / "Existing-Note.md").read_text(
        encoding="utf-8"
    )
    assert "Rejected rewrite body." in quarantined
    assert "verifier_status: rejected" in quarantined
    backlog = (vault / "_pipeline" / "research-backlog.md").read_text(encoding="utf-8")
    assert "retry refresh of Existing-Note" in backlog
    assert "previous content restored" in backlog


def test_rejected_brand_new_note_in_git_vault_still_quarantined_as_before(
    tmp_path: Path,
) -> None:
    """A rejected note with NO prior commit (created fresh this cycle) keeps the
    original behaviour: nothing to restore, so it's quarantined as-is."""
    vault = tmp_path / "v"
    (vault / "data_vault").mkdir(parents=True)
    _git("init", "-b", "main", cwd=vault)
    _git("config", "user.email", "t@e.com", cwd=vault)
    _git("config", "user.name", "T", cwd=vault)
    (vault / "README.md").write_text("# v\n", encoding="utf-8")
    _git("add", "-A", cwd=vault)
    _git("commit", "-m", "initial (no note yet)", cwd=vault)

    _note(vault, "Brand-New", "rejected", notes="unverifiable claim")

    count = _quarantine_rejected_notes(vault)

    assert count == 1
    assert not (vault / "data_vault" / "Brand-New.md").exists()
    assert (vault / "_pipeline" / "quarantine" / "Brand-New.md").exists()


class TestQuarantineBacklogReconciliation:
    """#257 — quarantine pointers must live inside a managed block that the
    next cycle reconciles against what's actually still in
    ``_pipeline/quarantine/``, and clear once nothing is left there. Plain
    appends outside any block meant a fixed note's pointer never went away.
    """

    def test_pointer_lives_inside_a_managed_quarantine_block(
        self, tmp_path: Path
    ) -> None:
        vault = tmp_path / "v"
        _note(vault, "bad-one", "rejected", notes="missing citation")
        _quarantine_rejected_notes(vault)
        backlog = (vault / "_pipeline" / "research-backlog.md").read_text(
            encoding="utf-8"
        )
        assert "<!-- quarantine -->" in backlog
        assert "<!-- /quarantine -->" in backlog
        start = backlog.index("<!-- quarantine -->")
        end = backlog.index("<!-- /quarantine -->")
        assert start < backlog.index("rewrite quarantined note: bad-one") < end

    def test_pointer_clears_once_the_quarantine_file_is_gone(
        self, tmp_path: Path
    ) -> None:
        """Simulates the note being fixed and its quarantine copy removed
        (e.g. by ``./vault re-grade`` or a manual rewrite) — the NEXT
        reconciliation sweep must drop the stale pointer, not carry it
        forever."""
        vault = tmp_path / "v"
        _note(vault, "bad-one", "rejected", notes="missing citation")
        _quarantine_rejected_notes(vault)
        assert "rewrite quarantined note: bad-one" in (
            vault / "_pipeline" / "research-backlog.md"
        ).read_text(encoding="utf-8")

        # The note was fixed and its quarantine copy removed; nothing else
        # is rejected this sweep.
        (vault / "_pipeline" / "quarantine" / "bad-one.md").unlink()
        count = _quarantine_rejected_notes(vault)

        assert count == 0
        backlog = (vault / "_pipeline" / "research-backlog.md").read_text(
            encoding="utf-8"
        )
        assert "bad-one" not in backlog
        # The block itself clears too — nothing left to reconcile.
        assert "<!-- quarantine -->" not in backlog

    def test_reconciliation_keeps_still_quarantined_entries_and_adds_new_ones(
        self, tmp_path: Path
    ) -> None:
        vault = tmp_path / "v"
        _note(vault, "bad-one", "rejected", notes="reason one")
        _quarantine_rejected_notes(vault)

        _note(vault, "bad-two", "rejected", notes="reason two")
        _quarantine_rejected_notes(vault)

        backlog = (vault / "_pipeline" / "research-backlog.md").read_text(
            encoding="utf-8"
        )
        assert "rewrite quarantined note: bad-one" in backlog
        assert "rewrite quarantined note: bad-two" in backlog
        # Exactly one managed block, not one per sweep.
        assert backlog.count("<!-- quarantine -->") == 1

    def test_manual_backlog_entries_outside_the_block_are_preserved(
        self, tmp_path: Path
    ) -> None:
        vault = tmp_path / "v"
        backlog = vault / "_pipeline" / "research-backlog.md"
        backlog.parent.mkdir(parents=True)
        backlog.write_text("- [ ] operator's own manual TODO\n", encoding="utf-8")

        _note(vault, "bad-one", "rejected")
        _quarantine_rejected_notes(vault)

        text = backlog.read_text(encoding="utf-8")
        assert "operator's own manual TODO" in text
        assert "rewrite quarantined note: bad-one" in text


def test_run_report_records_rejected_unresolved(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    (vault / "_pipeline").mkdir(parents=True)
    write_run_report(
        vault,
        final_exit_code=1,
        final_exit_reason="max_cycles (6) reached",
        rejected_unresolved=14,
    )
    payload = json.loads(
        (vault / "_pipeline" / "run-report.json").read_text(encoding="utf-8")
    )
    assert payload["rejected_unresolved"] == 14
    md = (vault / "_pipeline" / "run-report.md").read_text(encoding="utf-8")
    assert "14 note(s) ended the run rejected and were quarantined" in md
