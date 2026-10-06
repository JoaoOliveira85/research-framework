"""Tier-4 single-cycle end-to-end tests (feature 018, US2).

Drives the real ``research_framework.pipeline.cycle_runner.run_cycle_steps``
against a vault built by ``tests/_helpers/vault_factory.build_minimal_vault``
with a fake ``agent_call.py`` shim installed in place of the real one.
No monkeypatching of cycle_runner internals — the only test-only
customization is the fake agent at the subprocess boundary.

Every scenario in this file is a regression test for a specific seam bug
that previously shipped to production. See spec.md § US2 for the mapping.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.pipeline.cycle_runner import run_cycle_steps
from tests._helpers.vault_factory import build_minimal_vault, install_bundled_skill

pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _list_batch_files(vault: Path, cycle: int) -> list[Path]:
    """Return cycle-NNN-batch-*.json files sorted by batch number."""
    cdir = vault / "_pipeline" / "cycles"
    return sorted(cdir.glob(f"cycle-{cycle:03d}-batch-*.json"))


def _batch_topic_counts(vault: Path, cycle: int) -> list[int]:
    return [
        len((json.loads(p.read_text(encoding="utf-8")) or {}).get("topics") or [])
        for p in _list_batch_files(vault, cycle)
    ]


def _quality_report(vault: Path, cycle: int) -> dict:
    p = vault / "_pipeline" / "cycles" / f"cycle-{cycle:03d}-quality-report.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def _list_data_vault_notes(vault: Path) -> list[Path]:
    dv = vault / "data_vault"
    if not dv.is_dir():
        return []
    return sorted(
        p
        for p in dv.rglob("*.md")
        if p.name not in ("_index.md", "_concepts.md", "_graph.md")
        and "_templates" not in p.parts
    )


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


def test_happy_path_single_cycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """15 spec targets, end-to-end clean cycle — every gate green."""
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    vault = build_minimal_vault(
        tmp_path,
        num_categories=3,
        num_targets_per_category=5,
        max_cycles=1,
    )

    rc = run_cycle_steps(vault, cycle_num=1, budget_cap=100.0, max_cycles=1)
    assert rc in (0, 1), f"expected CONTINUE/TERMINATE, got {rc}"

    cdir = vault / "_pipeline" / "cycles"
    assert (cdir / "cycle-001-scout.json").is_file()
    assert (cdir / "cycle-001-research.json").is_file()
    assert (cdir / "cycle-001-quality-report.json").is_file()

    batches = _list_batch_files(vault, 1)
    assert batches, "expected at least one batch file"

    notes = _list_data_vault_notes(vault)
    assert notes, "expected at least one note written under data_vault/"

    qr = _quality_report(vault, 1)
    gates = qr.get("gates") or {}
    for gate_id in ("SG-001", "SG-002"):
        g = gates.get(gate_id)
        if g is not None:
            assert g.get("status") != "FAIL", f"{gate_id} unexpectedly failed: {g}"


def test_asymmetric_tail_batch_serializes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for 0.2.22 — 8 topics @ batch_size=3 must serialize a 2-topic tail."""
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    vault = build_minimal_vault(
        tmp_path,
        num_categories=2,
        num_targets_per_category=4,
        max_cycles=1,
        note_writer_batch_size=3,
    )

    rc = run_cycle_steps(vault, cycle_num=1, budget_cap=100.0, max_cycles=1)
    assert rc in (0, 1), f"expected CONTINUE/TERMINATE, got {rc}"

    batches = _list_batch_files(vault, 1)
    assert len(batches) == 3, (
        f"expected 3 batches (8 topics / batch_size 3 → [3, 3, 2]); got "
        f"{[b.name for b in batches]}"
    )
    counts = _batch_topic_counts(vault, 1)
    assert counts == [3, 3, 2], (
        f"expected asymmetric tail [3, 3, 2]; got {counts}"
        " — 0.2.22 regression: BatchResult.to_dict rejected the 2-topic tail batch."
    )

    for path in batches:
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(doc, dict)
        assert "schema_version" in doc and "topics" in doc and "notes_written" in doc
        assert isinstance(doc["topics"], list) and 1 <= len(doc["topics"]) <= 10


def test_empty_scout_queue_aborts_via_sg001(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for 0.2.20 — empty scout MUST abort before any notes are written."""
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "empty_scout")
    vault = build_minimal_vault(
        tmp_path,
        num_categories=2,
        num_targets_per_category=3,
        max_cycles=1,
    )

    rc = run_cycle_steps(vault, cycle_num=1, budget_cap=100.0, max_cycles=1)
    assert rc == 2, (
        f"expected ABORT (2) on empty scout; got {rc}. "
        "0.2.20 regression: scout topics not reaching dispatcher → silent empty cycle."
    )

    cdir = vault / "_pipeline" / "cycles"
    assert (cdir / "cycle-001-scout.json").is_file(), (
        "scout report must still be written so the abort has a forensic trail"
    )

    batches = _list_batch_files(vault, 1)
    assert not batches, f"unexpected batch files after empty-scout abort: {batches}"

    notes = _list_data_vault_notes(vault)
    assert not notes, f"no notes should be written after empty-scout abort, got {notes}"


def test_corrupted_skill_file_self_repairs_in_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Skill preflight must restore a corrupted SKILL.md from bundled assets."""
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    vault = build_minimal_vault(
        tmp_path,
        num_categories=2,
        num_targets_per_category=2,
        max_cycles=1,
    )
    skill_path = install_bundled_skill(vault, "scout")

    skill_path.write_text(
        "not: valid: yaml:\n\tweird tabs and: colons:\n# missing description\n",
        encoding="utf-8",
    )

    rc = run_cycle_steps(vault, cycle_num=1, budget_cap=100.0, max_cycles=1)
    assert rc in (0, 1), (
        f"expected cycle to recover after skill auto-repair; got {rc}. "
        "If this asserts, skill_check.validate_and_repair_skills did not restore "
        "from the bundled copy."
    )

    restored = skill_path.read_text(encoding="utf-8")
    assert "name: scout" in restored, (
        "expected restored skill to contain bundled frontmatter (name: scout)"
    )

    sidecar = vault / "_pipeline" / "cycle-001-skill-check.json"
    assert sidecar.is_file()
    doc = json.loads(sidecar.read_text(encoding="utf-8"))
    repaired = doc.get("repaired") or []
    assert repaired, f"expected at least one repair record; got {doc!r}"


def test_sg005_failure_triggers_correction_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First batch fails SG-005 (missing source_urls) — correction directive in second batch."""
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    monkeypatch.setenv("FAKE_AGENT_NOTE_WRITER_SCENARIO", "fail_frontmatter")
    vault = build_minimal_vault(
        tmp_path,
        num_categories=2,
        num_targets_per_category=2,
        max_cycles=1,
        note_writer_batch_size=3,
    )

    rc = run_cycle_steps(vault, cycle_num=1, budget_cap=100.0, max_cycles=1)
    assert rc in (0, 1, 2), f"unexpected exit {rc}"

    batches = _list_batch_files(vault, 1)
    assert batches, "expected at least one batch report"
    first_batch = json.loads(batches[0].read_text(encoding="utf-8"))
    sg_results = first_batch.get("sg_gate_results") or []
    sg005_first = next((g for g in sg_results if g.get("gate_id") == "SG-005"), None)
    assert sg005_first is not None, (
        f"expected first batch to record an SG-005 result; got {sg_results}"
    )
    assert sg005_first.get("status") == "FAIL", (
        f"expected first batch SG-005 FAIL with fail_frontmatter scenario; got "
        f"{sg005_first}"
    )

    if len(batches) >= 2:
        second_batch = json.loads(batches[1].read_text(encoding="utf-8"))
        assert (second_batch.get("correction_directive_in") or "").strip(), (
            "expected second batch prompt to carry a correction directive"
        )
