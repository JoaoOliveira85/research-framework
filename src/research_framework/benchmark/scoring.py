"""Deterministic per-task quality scorers (spec 056, contract §4; Principle IV).

Every quality scalar is computed by a deterministic parser/metric — never an LLM
judge. Each scorer returns ``parse_ok`` so the runner can map an unusable output
(e.g. non-JSON scout report) to cell ``status: failed`` rather than a fake score.

Quality scalars (all in ``[0, 1]``):
  - scout       → ``min(1.0, topics_proposed / topics_expected)``
  - note-writer → spec-022 ``note_quality.template_compliance_pct`` (already a
                  0..1 ratio despite the ``_pct`` suffix — used as-is, NOT /100;
                  the contract's "/100" predates confirming the upstream scale).
  - verifier    → ``1.0`` if verdict ``accept`` else ``0.0``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from research_framework.pipeline.gates_step import normalise_topic_row
from research_framework.quality.metrics._helpers import split_frontmatter
from research_framework.quality.metrics.note_quality import compute_note_quality_metric
from research_framework.quality.models import CycleOutput, Fixture

SCORING_MODE = "deterministic"

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def _loads_tolerant(text: str) -> Any:
    """Parse JSON tolerating markdown fences / surrounding prose (ADR-0004).

    Tries the raw text, then a fenced block, then the span from the first ``{`` to
    the last ``}`` (a coarse slice — NOT brace-balanced; sufficient for the single
    top-level object the scorers expect). Raises ``ValueError`` if nothing parses.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("empty output")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fence = _FENCE_RE.search(text)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError("no JSON object found in output")


def _result(
    quality: float | None,
    detail: dict[str, Any],
    *,
    parse_ok: bool,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "quality": quality,
        "quality_detail": detail,
        "scoring_mode": SCORING_MODE,
        "parse_ok": parse_ok,
        "reason": reason,
    }


def score_scout(stdout: str, *, topics_expected: int) -> dict[str, Any]:
    """scout-report v2 → ``topics_proposed / topics_expected`` (capped at 1.0)."""
    try:
        doc = _loads_tolerant(stdout)
    except ValueError as exc:
        return _result(
            None,
            {
                "scout_report_valid": False,
                "topics_proposed": 0,
                "topics_expected": topics_expected,
            },
            parse_ok=False,
            reason=f"scout output not valid JSON ({exc})",
        )
    found = doc.get("topics_found") if isinstance(doc, dict) else None
    raw_new = found.get("new") if isinstance(found, dict) else None
    if not isinstance(raw_new, list):
        return _result(
            None,
            {
                "scout_report_valid": False,
                "topics_proposed": 0,
                "topics_expected": topics_expected,
            },
            parse_ok=False,
            reason="scout report missing topics_found.new array",
        )
    topics_proposed = sum(
        1
        for entry in raw_new
        if (row := normalise_topic_row(entry)) is not None
        and str(row.get("title") or "").strip()
    )
    denom = max(1, int(topics_expected))
    quality = min(1.0, topics_proposed / denom)
    return _result(
        round(quality, 4),
        {
            "scout_report_valid": True,
            "topics_proposed": topics_proposed,
            "topics_expected": int(topics_expected),
            # Effective divisor actually used (clamped to >= 1); makes the scalar
            # unambiguous when topics_expected is mis-configured to 0 / negative.
            "denominator": denom,
        },
        parse_ok=True,
    )


def score_note_writer(
    stdout: str, *, fixture_dir: Path, work_dir: Path
) -> dict[str, Any]:
    """Write the produced note and score it with the spec-022 note-quality metric.

    The benchmark prompt asks the agent to emit the FULL note (frontmatter + body)
    on stdout. Output with no parseable YAML frontmatter is not a note at all ⇒
    ``parse_ok=False`` (cell ``status: failed``) rather than a misleading ``ok``
    with ``quality 0.0`` — the latter would rank "ignored the prompt" the same as
    "wrote a note that missed every heading".
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    fm, _body = split_frontmatter(stdout)
    if fm is None:
        return _result(
            None,
            {"template_compliance_pct": 0.0, "note_frontmatter_present": False},
            parse_ok=False,
            reason="note-writer output has no YAML frontmatter (not a note)",
        )
    note_path = work_dir / "note.md"
    note_path.write_text(stdout, encoding="utf-8")
    fixture = Fixture(
        name="benchmark",
        vault_dir=fixture_dir,
        spec_path=fixture_dir / "research.spec.md",
        settings_path=fixture_dir / "settings.yaml",
        coverage_targets_path=fixture_dir / "_pipeline" / "coverage-targets.json",
        fake_agent_responses_dir=fixture_dir / "fake_agent_responses",
        note_count_target=0,
        failure_mode="none",
    )
    cycle = CycleOutput(
        fixture_name="benchmark",
        cycle_number=1,
        exit_code=0,
        quality_report_path=work_dir / "quality-report.json",
        research_report_path=work_dir / "research.json",
        notes_written=[note_path],
    )
    metric = compute_note_quality_metric(fixture, [cycle])
    # ``template_compliance_pct`` is a 0..1 ratio (see module docstring) → use directly.
    quality = max(0.0, min(1.0, float(metric.get("template_compliance_pct", 0.0))))
    return _result(round(quality, 4), dict(metric), parse_ok=True)


def score_verifier(stdout: str) -> dict[str, Any]:
    """Verifier verdict JSON → ``1.0`` accept / ``0.0`` reject (ADR-0004 tolerant)."""
    try:
        doc = _loads_tolerant(stdout)
    except ValueError as exc:
        return _result(
            None,
            {"verifier_pass": False, "verdict": None},
            parse_ok=False,
            reason=f"verifier output not valid JSON ({exc})",
        )
    verdict = ""
    if isinstance(doc, dict):
        verdict = str(doc.get("verdict") or doc.get("decision") or "").strip().lower()
    passed = verdict == "accept"
    return _result(
        1.0 if passed else 0.0,
        {"verifier_pass": passed, "verdict": verdict or None},
        parse_ok=True,
    )


def score_task(
    task: str,
    stdout: str,
    *,
    fixture_dir: Path,
    manifest: dict[str, Any],
    work_dir: Path,
) -> dict[str, Any]:
    """Dispatch to the per-task scorer; returns the score payload (contract §4)."""
    task_cfg = (manifest.get("tasks") or {}).get(task, {}) if manifest else {}
    if task == "scout":
        return score_scout(
            stdout, topics_expected=int(task_cfg.get("topics_expected", 1))
        )
    if task == "note-writer":
        return score_note_writer(stdout, fixture_dir=fixture_dir, work_dir=work_dir)
    if task == "verifier":
        return score_verifier(stdout)
    raise ValueError(f"no scorer for task {task!r}")


def write_scored_json(cell_dir: Path, scored: dict[str, Any]) -> Path:
    """Persist the deterministic score replay artifact (contract §1)."""
    cell_dir.mkdir(parents=True, exist_ok=True)
    path = cell_dir / "scored.json"
    path.write_text(json.dumps(scored, indent=2, sort_keys=True), encoding="utf-8")
    return path


def rescore_from_artifacts(
    cell_dir: Path, *, task: str, fixture_dir: Path, manifest: dict[str, Any]
) -> dict[str, Any]:
    """Replay the scorer against the cell's recorded ``stdout.txt`` (FR-014 / SC-002).

    Determinism guarantee: same stdout ⇒ same ``quality``. Used by the contract
    test to prove re-scoring reproduces the persisted scalar.
    """
    stdout = (cell_dir / "stdout.txt").read_text(encoding="utf-8")
    return score_task(
        task,
        stdout,
        fixture_dir=fixture_dir,
        manifest=manifest,
        work_dir=cell_dir / "_rescore",
    )
