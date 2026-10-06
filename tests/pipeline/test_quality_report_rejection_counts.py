"""Spec 070 F3 — a cycle must not report notes it destroyed as notes it kept.

``notes_rejected`` was derived purely from a batch's ``accepted`` flag. The
per-note verifier stamps ``verifier_status: rejected`` on individual notes
inside an otherwise-accepted batch, and the orchestrator then sweeps those into
``_pipeline/quarantine/``. So a cycle could record
``notes_written: 4, notes_accepted: 4, notes_rejected: 0`` while destroying
three of the four — which is exactly what the live vault recorded for three
consecutive cycles.
"""

from __future__ import annotations

import json
from pathlib import Path

from research_framework.pipeline.quality_report import (
    _merge_sg_gates,
    _notes_rejected_on_disk,
)

_FM = """---
title: {title}
type: practitioner
verifier_status: {status}
---

Body.
"""


def _write_note(vault: Path, rel: str, status: str) -> None:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_FM.format(title=Path(rel).stem, status=status), encoding="utf-8")


def _write_batch(vault: Path, cycle: int, notes: list[str], *, accepted: bool) -> None:
    cycles = vault / "_pipeline" / "cycles"
    cycles.mkdir(parents=True, exist_ok=True)
    (cycles / f"cycle-{cycle:03d}-batch-001.json").write_text(
        json.dumps(
            {
                "batch_number": 1,
                "accepted": accepted,
                "notes_written": notes,
                "topics": [{"category": "practitioners"} for _ in notes],
            }
        ),
        encoding="utf-8",
    )


def test_rejected_notes_inside_an_accepted_batch_are_counted(tmp_path: Path) -> None:
    """The regression that lost 9 notes in silence."""
    vault = tmp_path / "vault"
    notes = [
        "data_vault/01 - Practitioners/person_c.md",
        "data_vault/01 - Practitioners/person_a.md",
        "data_vault/01 - Practitioners/tuuli_tiilikainen.md",
        "data_vault/03 - Events/conf_four.md",
    ]
    for rel in notes:
        _write_note(vault, rel, "rejected" if "tuuli" not in rel else "verified")
    _write_batch(vault, 6, notes, accepted=True)

    (_g, _b, accepted, rejected, written, *_rest) = _merge_sg_gates(vault, 6)

    assert written == 4
    assert rejected == 3, "3 notes carry verifier_status: rejected"
    assert accepted == 1
    assert accepted + rejected == written, "the accounting must close"


def test_all_accepted_batch_with_clean_notes_reports_zero_rejected(
    tmp_path: Path,
) -> None:
    """Regression: the happy path must be unchanged."""
    vault = tmp_path / "vault"
    notes = ["data_vault/01 - Practitioners/a.md", "data_vault/01 - Practitioners/b.md"]
    for rel in notes:
        _write_note(vault, rel, "verified")
    _write_batch(vault, 1, notes, accepted=True)

    (_g, _b, accepted, rejected, written, *_rest) = _merge_sg_gates(vault, 1)

    assert (written, accepted, rejected) == (2, 2, 0)


def test_rejected_batch_still_counts_all_its_notes(tmp_path: Path) -> None:
    """Regression: batch-level rejection is still honoured on its own."""
    vault = tmp_path / "vault"
    notes = ["data_vault/01 - Practitioners/a.md", "data_vault/01 - Practitioners/b.md"]
    for rel in notes:
        _write_note(vault, rel, "verified")
    _write_batch(vault, 1, notes, accepted=False)

    (_g, _b, accepted, rejected, written, *_rest) = _merge_sg_gates(vault, 1)

    assert (written, accepted, rejected) == (2, 0, 2)


def test_a_note_counted_once_when_both_signals_fire(tmp_path: Path) -> None:
    """Batch rejected AND note stamped rejected must not double-count."""
    vault = tmp_path / "vault"
    notes = ["data_vault/01 - Practitioners/a.md"]
    _write_note(vault, notes[0], "rejected")
    _write_batch(vault, 1, notes, accepted=False)

    (_g, _b, accepted, rejected, written, *_rest) = _merge_sg_gates(vault, 1)

    assert (written, accepted, rejected) == (1, 0, 1)


def test_disk_scan_finds_notes_already_swept_to_quarantine(tmp_path: Path) -> None:
    """A prior sweep must not make the rejection invisible again."""
    vault = tmp_path / "vault"
    rel = "data_vault/01 - Practitioners/person_c.md"
    _write_note(vault, "_pipeline/quarantine/person_c.md", "rejected")

    assert _notes_rejected_on_disk(vault, [rel]) == {rel}


def test_missing_note_is_not_counted_as_rejected(tmp_path: Path) -> None:
    """Absence of evidence is not evidence of rejection."""
    vault = tmp_path / "vault"
    assert _notes_rejected_on_disk(vault, ["data_vault/gone.md"]) == set()
