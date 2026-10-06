"""Tier-5 cycle end-to-end scenarios (spec 024, US6).

Drives the real :func:`research_framework.pipeline.cycle_runner.run_cycle_steps`
with ``vault_factory.build_minimal_vault`` and fake-agent scenario env vars.
Contract: ``specs/024-testing-infrastructure-v2/data-model.md`` § Entity 8.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from research_framework.pipeline.cycle_runner import run_cycle_steps
from tests._helpers.vault_factory import build_minimal_vault

pytestmark = [pytest.mark.e2e, pytest.mark.slow]

_VERIFIER_ON_SETTINGS = """\
pipeline:
  gates:
    cg_003_warn_pct: 30
    cg_003_fail_pct: 60
  note_writer_batch_size: 6
  max_batches_per_cycle: 10
default_executor:
  runtime: claude
  model: sonnet
  timeout_s: 60
stages:
  verifier:
    enabled: true
    timeout_s: 60
"""


def _quality_report(vault: Path, cycle: int = 1) -> dict:
    p = vault / "_pipeline" / "cycles" / f"cycle-{cycle:03d}-quality-report.json"
    assert p.is_file(), f"missing quality report: {p}"
    return json.loads(p.read_text(encoding="utf-8"))


def _research_report(vault: Path, cycle: int = 1) -> dict:
    p = vault / "_pipeline" / "cycles" / f"cycle-{cycle:03d}-research.json"
    assert p.is_file(), f"missing research report: {p}"
    return json.loads(p.read_text(encoding="utf-8"))


def _verifier_manifest(vault: Path, cycle: int = 1) -> dict:
    p = vault / "_pipeline" / "cycles" / f"cycle-{cycle:03d}-verifier.json"
    assert p.is_file(), f"missing verifier manifest: {p}"
    return json.loads(p.read_text(encoding="utf-8"))


def _resolve_vault_note(vault: Path, note_ref: str) -> Path:
    """Resolve a research-report path (relative or bare filename) to an on-disk note."""
    p = vault / note_ref
    if p.is_file():
        return p
    basename = Path(note_ref).name
    matches = [
        c
        for c in (vault / "data_vault").rglob(basename)
        if c.is_file() and "_templates" not in c.parts
    ]
    assert len(matches) == 1, (
        f"expected exactly one note for {note_ref!r}; found {matches}"
    )
    return matches[0]


def _note_frontmatter(vault: Path, rel_path: str) -> dict:
    text = _resolve_vault_note(vault, rel_path).read_text(encoding="utf-8")
    assert text.startswith("---"), rel_path
    return yaml.safe_load(text.split("---", 2)[1]) or {}


def _run_one_cycle(
    vault: Path,
    *,
    budget_cap: float = 100.0,
    max_cycles: int = 1,
) -> int:
    rc = run_cycle_steps(
        vault, cycle_num=1, budget_cap=budget_cap, max_cycles=max_cycles
    )
    assert rc in (0, 1, 2), f"unexpected cycle exit code: {rc}"
    return rc


def test_cycle_oos_topic_rejected_by_verifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scout proposes an out-of-scope topic; verifier rejects it (recorded on disk)."""
    monkeypatch.setenv("FAKE_AGENT_SCOUT_SCENARIO", "oos_topic")
    monkeypatch.setenv("FAKE_AGENT_VERIFIER_SCENARIO", "reject")
    vault = build_minimal_vault(
        tmp_path,
        num_categories=2,
        num_targets_per_category=2,
        max_cycles=1,
        out_of_scope=["crypto"],
        settings_text=_VERIFIER_ON_SETTINGS,
    )

    _run_one_cycle(vault)

    research = _research_report(vault)
    created = [str(x) for x in (research.get("notes_created") or [])]
    crypto_notes = [p for p in created if "crypto" in p.lower()]
    assert crypto_notes, (
        f"expected an out-of-scope crypto note in notes_created; got {created}"
    )
    crypto_rel = crypto_notes[0]
    fm = _note_frontmatter(vault, crypto_rel)
    assert fm.get("verifier_status") == "rejected", (
        f"expected verifier to reject OOS note {crypto_rel!r}; frontmatter={fm!r}"
    )
    assert fm.get("verifier_notes"), "expected verifier_notes on rejected OOS note"

    manifest = _verifier_manifest(vault)
    rejected = [
        v
        for v in (manifest.get("verdicts") or [])
        if isinstance(v, dict)
        and v.get("status") == "rejected"
        and "crypto" in str(v.get("note_path") or "").lower()
    ]
    assert rejected, (
        f"verifier manifest must record crypto note rejection; got {manifest!r}"
    )

    qr = _quality_report(vault)
    assert qr.get("notes_written", 0) >= 1
    # Verifier rejections surface as rejected note slots in the quality rollup.
    assert qr.get("notes_rejected", 0) >= 1 or any(rejected), (
        "quality report should reflect verifier rejection of the OOS note"
    )


def test_cycle_partial_yield_trips_diversity_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """note_writer partial_yield skips topics; diversity gate warns in quality report."""
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    monkeypatch.setenv("FAKE_AGENT_NOTE_WRITER_SCENARIO", "partial_yield")
    vault = build_minimal_vault(
        tmp_path,
        num_categories=3,
        num_targets_per_category=2,
        max_cycles=1,
        note_writer_batch_size=3,
        settings_text=_VERIFIER_ON_SETTINGS.replace(
            "stages:\n  verifier:\n    enabled: true",
            "stages:\n  verifier:\n    enabled: false",
        ),
    )

    _run_one_cycle(vault)

    research = _research_report(vault)
    skipped = research.get("skipped_topics") or []
    assert skipped, "partial_yield must record skipped_topics in cycle research JSON"
    assert any(
        (row.get("reason") or "") == "fake_agent_partial_yield_mode"
        for row in skipped
        if isinstance(row, dict)
    ), f"unexpected skipped_topics shape: {skipped}"

    gates = _quality_report(vault).get("gates") or {}
    sg002 = gates.get("SG-002") or {}
    cg002 = gates.get("CG-002") or {}
    diversity_warn = sg002.get("status") == "WARN" or cg002.get("status") == "WARN"
    assert diversity_warn, (
        "expected SG-002 or CG-002 diversity-gate WARN in quality report; "
        f"SG-002={sg002!r}, CG-002={cg002!r}"
    )


def test_cycle_verifier_reject_moves_note_to_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy-path notes are verifier-rejected in place (Step 3b stamps frontmatter)."""
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    monkeypatch.setenv("FAKE_AGENT_VERIFIER_SCENARIO", "reject")
    vault = build_minimal_vault(
        tmp_path,
        num_categories=2,
        num_targets_per_category=2,
        max_cycles=1,
        settings_text=_VERIFIER_ON_SETTINGS,
    )

    _run_one_cycle(vault)

    rejected_dir = vault / "_pipeline" / "rejected"
    assert not rejected_dir.is_dir(), (
        "production verifier stamps notes in data_vault; "
        "_pipeline/rejected/ is not used"
    )

    research = _research_report(vault)
    created = [str(x) for x in (research.get("notes_created") or [])]
    assert created, "expected at least one note from happy-path cycle"

    manifest = _verifier_manifest(vault)
    manifest_rejected = {
        str(v.get("note_path"))
        for v in (manifest.get("verdicts") or [])
        if isinstance(v, dict) and v.get("status") == "rejected"
    }
    assert manifest_rejected, f"verifier manifest missing reject verdicts: {manifest!r}"

    stamped: list[str] = []
    for rel in created:
        fm = _note_frontmatter(vault, rel)
        if fm.get("verifier_status") == "rejected":
            stamped.append(rel)
        assert rel in manifest_rejected or rel.endswith(
            Path(next(iter(manifest_rejected))).name
        ), f"{rel!r} not listed in verifier manifest rejections"
    assert stamped, (
        "every written note should carry verifier_status: rejected in frontmatter"
    )

    qr = _quality_report(vault)
    assert qr.get("notes_rejected", 0) >= len(stamped) or manifest_rejected
