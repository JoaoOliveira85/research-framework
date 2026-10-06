"""Deterministic per-task scoring contract (spec 056 §4; T012–T015).

Every quality scalar is parser-derived (Principle IV — no LLM judge). Re-scoring
the same recorded ``stdout`` MUST reproduce the scalar (FR-014 / SC-002).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.benchmark import scoring


def _scout_json(n: int) -> str:
    topics = [f"Topic {i}" for i in range(n)]
    return json.dumps(
        {"schema_version": "2.0", "phase": "scout", "topics_found": {"new": topics}}
    )


@pytest.mark.parametrize(
    ("stdout", "expected_quality", "expected_proposed", "parse_ok"),
    [
        (_scout_json(4), 1.0, 4, True),  # 4/4 capped
        (_scout_json(2), 0.5, 2, True),  # 2/4
        (_scout_json(8), 1.0, 8, True),  # 8/4 → capped at 1.0
        ("not json at all", None, 0, False),  # parse failure → failed
    ],
)
def test_scout_quality_scalar(stdout, expected_quality, expected_proposed, parse_ok):
    """scout JSON → topics_proposed / topics_expected, capped (contract §4)."""
    result = scoring.score_scout(stdout, topics_expected=4)
    assert result["parse_ok"] is parse_ok
    assert result["quality"] == expected_quality
    assert result["quality_detail"]["topics_proposed"] == expected_proposed
    assert result["quality_detail"]["topics_expected"] == 4
    if parse_ok:
        assert result["scoring_mode"] == "deterministic"


def test_scout_handles_fenced_json() -> None:
    """ADR-0004 tolerance: a ```json fenced block still parses."""
    fenced = f"```json\n{_scout_json(3)}\n```"
    result = scoring.score_scout(fenced, topics_expected=4)
    assert result["parse_ok"] is True
    assert result["quality_detail"]["topics_proposed"] == 3


def test_scout_records_effective_denominator_when_expected_zero() -> None:
    """topics_expected<=0 clamps to 1; the detail records the effective denominator
    so the scalar is unambiguous (Copilot re-review)."""
    result = scoring.score_scout(_scout_json(2), topics_expected=0)
    assert result["parse_ok"] is True
    assert result["quality_detail"]["topics_expected"] == 0
    assert result["quality_detail"]["denominator"] == 1
    assert result["quality"] == 1.0  # min(1.0, 2/1)


def test_note_writer_quality_scalar(tmp_path: Path, fixture_dir: Path) -> None:
    """Template-complete note → compliance 1.0; missing-heading note → 0.0 (FR-005/FR-017).

    Note: ``template_compliance_pct`` from spec-022 is a 0..1 ratio, so it is used
    directly as ``quality`` (the contract's historical ``/100`` predates confirming
    the upstream scale — see scoring.py docstring).
    """
    complete = (
        '---\ntype: concept\ntitle: "X"\n---\n\n'
        "## Summary\ns\n\n## Key Points\n- a\n\n## Details\nd\n\n## Sources\n- s\n"
    )
    res_full = scoring.score_note_writer(
        complete, fixture_dir=fixture_dir, work_dir=tmp_path / "full"
    )
    assert res_full["parse_ok"] is True
    assert res_full["quality"] == 1.0
    assert "template_compliance_pct" in res_full["quality_detail"]

    partial = '---\ntype: concept\ntitle: "X"\n---\n\n## Summary\nonly one heading\n'
    res_partial = scoring.score_note_writer(
        partial, fixture_dir=fixture_dir, work_dir=tmp_path / "partial"
    )
    assert res_partial["quality"] == 0.0


def test_note_writer_no_frontmatter_is_failed(
    tmp_path: Path, fixture_dir: Path
) -> None:
    """Output that isn't a note (no YAML frontmatter) ⇒ failed, not ok/0.0 (MINOR review)."""
    res = scoring.score_note_writer(
        "Here is the note you asked for: it covers HNSW thoroughly.",
        fixture_dir=fixture_dir,
        work_dir=tmp_path / "prose",
    )
    assert res["parse_ok"] is False
    assert res["quality"] is None
    assert "frontmatter" in (res["reason"] or "")


def test_verifier_quality_scalar() -> None:
    """accept → 1.0, reject → 0.0, garbage → failed (contract §4)."""
    accept = scoring.score_verifier('{"verdict": "accept", "reasons": []}')
    assert (
        accept["quality"] == 1.0 and accept["quality_detail"]["verifier_pass"] is True
    )

    reject = scoring.score_verifier('{"verdict": "reject"}')
    assert (
        reject["quality"] == 0.0 and reject["quality_detail"]["verifier_pass"] is False
    )

    bad = scoring.score_verifier("definitely not json")
    assert bad["parse_ok"] is False and bad["quality"] is None


_NOTE_STDOUT = (
    '---\ntype: concept\ntitle: "X"\n---\n\n'
    "## Summary\ns\n\n## Key Points\n- a\n\n## Details\nd\n\n## Sources\n- s\n"
)


@pytest.mark.parametrize(
    ("task", "stdout"),
    [
        ("scout", _scout_json(3)),
        ("note-writer", _NOTE_STDOUT),
        ("verifier", '{"verdict": "accept"}'),
    ],
)
def test_rescore_identical(
    task: str, stdout: str, tmp_path: Path, fixture_dir: Path, manifest: dict
) -> None:
    """Re-scoring a persisted cell's stdout reproduces the scalar for every task (FR-014, SC-002)."""
    cell_dir = tmp_path / "cells" / f"{task}__claude__sonnet"
    cell_dir.mkdir(parents=True)
    (cell_dir / "stdout.txt").write_text(stdout, encoding="utf-8")

    first = scoring.score_task(
        task, stdout, fixture_dir=fixture_dir, manifest=manifest, work_dir=cell_dir
    )
    scoring.write_scored_json(cell_dir, first)
    replay = scoring.rescore_from_artifacts(
        cell_dir, task=task, fixture_dir=fixture_dir, manifest=manifest
    )
    assert replay["quality"] == first["quality"]
    persisted = json.loads((cell_dir / "scored.json").read_text(encoding="utf-8"))
    assert persisted["quality"] == first["quality"]
