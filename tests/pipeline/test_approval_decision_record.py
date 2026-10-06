"""The persisted approval-decision record (issue #235).

``approval_gates_fired`` is the one clause of approval-marker.contract.md §6
that no production caller ever populated: the operator's verdict is taken in
the CLI process (``cli/budget_resume.py``) and the cycle cost report is written
much later, deep inside ``pipeline/cycle_runner.py``, from a budget session
that knows nothing about it. The two halves are joined by a small decision
artifact under ``_pipeline/`` — schema'd and atomically written like every
other ``_pipeline`` JSON (issue #314) — and these tests pin the artifact
itself. The end-to-end path (CLI writes it, cost report reads it) is pinned in
``tests/cli/test_research_resume_approval_decisions.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.pipeline.budget_guard import (
    ApprovalDecision,
    approval_decisions_path,
    read_approval_decisions,
    record_approval_decision,
    validate_approval_decision_log,
)


def _decision(**overrides: object) -> ApprovalDecision:
    kwargs: dict = {
        "stage_name": "note_writer",
        "cycle_number": 1,
        "approved": True,
        "decided_by_mode": "tty",
    }
    kwargs.update(overrides)
    return ApprovalDecision(**kwargs)  # type: ignore[arg-type]


def test_recording_a_decision_creates_a_schema_versioned_log(tmp_path: Path) -> None:
    assert record_approval_decision(tmp_path, _decision()) is True
    doc = json.loads(approval_decisions_path(tmp_path).read_text(encoding="utf-8"))
    assert doc["schema_version"] == "1.0"
    assert len(doc["decisions"]) == 1
    row = doc["decisions"][0]
    assert row["stage"] == "note_writer"
    assert row["cycle_number"] == 1
    assert row["approved"] is True
    assert row["decided_by_mode"] == "tty"
    assert row["decided_at"].endswith("Z")


def test_decisions_append_rather_than_overwrite(tmp_path: Path) -> None:
    record_approval_decision(tmp_path, _decision(stage_name="scout"))
    record_approval_decision(tmp_path, _decision(stage_name="note_writer"))
    doc = json.loads(approval_decisions_path(tmp_path).read_text(encoding="utf-8"))
    assert [row["stage"] for row in doc["decisions"]] == ["scout", "note_writer"]


def test_read_returns_contract_section_6_rows_for_one_cycle(tmp_path: Path) -> None:
    """§6's row shape exactly: stage / approved / decided_at / decided_by_mode."""
    record_approval_decision(tmp_path, _decision(cycle_number=1, stage_name="scout"))
    record_approval_decision(
        tmp_path,
        _decision(cycle_number=2, stage_name="note_writer", approved=False),
    )
    rows = read_approval_decisions(tmp_path, 2)
    assert len(rows) == 1
    assert set(rows[0]) == {"stage", "approved", "decided_at", "decided_by_mode"}
    assert rows[0]["stage"] == "note_writer"
    assert rows[0]["approved"] is False


def test_read_is_empty_when_no_log_exists(tmp_path: Path) -> None:
    assert read_approval_decisions(tmp_path, 1) == []


def test_rejection_is_recorded_as_a_decision(tmp_path: Path) -> None:
    """§5.4: a rejection must reach the report as ``approved: false``.

    A gate the operator refused is telemetry the report owes just as much as
    one they let through — "nothing fired" and "I said no" are different facts.
    """
    record_approval_decision(tmp_path, _decision(approved=False))
    assert read_approval_decisions(tmp_path, 1)[0]["approved"] is False


def test_an_unreadable_log_is_never_clobbered(tmp_path: Path) -> None:
    """Refuse to append over something this build cannot parse.

    Truncating it would destroy the operator's record of every earlier
    verdict to make room for one new row. The write declines (returning
    ``False``, so the caller can WARN) and the bytes on disk stand.
    """
    path = approval_decisions_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert record_approval_decision(tmp_path, _decision()) is False
    assert path.read_text(encoding="utf-8") == "{not json"
    assert read_approval_decisions(tmp_path, 1) == []


def test_a_future_schema_version_is_never_clobbered(tmp_path: Path) -> None:
    """Same rule for a log written by a newer build: read-only, never rewritten."""
    path = approval_decisions_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"schema_version": "9.9", "decisions": []})
    path.write_text(body, encoding="utf-8")
    assert record_approval_decision(tmp_path, _decision()) is False
    assert path.read_text(encoding="utf-8") == body


def test_validate_rejects_a_bad_schema_version() -> None:
    with pytest.raises(ValueError):
        validate_approval_decision_log({"schema_version": "2.0", "decisions": []})


def test_validate_rejects_a_non_list_decisions_field() -> None:
    with pytest.raises(ValueError):
        validate_approval_decision_log({"schema_version": "1.0", "decisions": {}})


def test_decision_mode_must_be_tty_or_headless(tmp_path: Path) -> None:
    """§6's ``decided_by_mode`` is a closed set; a typo must not reach the report."""
    with pytest.raises(ValueError):
        record_approval_decision(tmp_path, _decision(decided_by_mode="interactive"))


def test_log_is_written_atomically(tmp_path: Path, monkeypatch) -> None:
    """Issue #314: every ``_pipeline`` JSON goes through ``atomic_write``.

    Pinned by observing the helper rather than by racing a reader: the point
    is that no caller reintroduces a bare ``write_text``.
    """
    seen: list[Path] = []
    import research_framework.pipeline.budget_guard as bg

    original = bg.atomic_write.write_text

    def _spy(path: Path, body: str, **kwargs: object) -> None:
        seen.append(Path(path))
        original(path, body, **kwargs)

    monkeypatch.setattr(bg.atomic_write, "write_text", _spy)
    record_approval_decision(tmp_path, _decision())
    assert approval_decisions_path(tmp_path) in seen
