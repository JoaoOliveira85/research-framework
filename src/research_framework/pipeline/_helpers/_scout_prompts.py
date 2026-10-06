"""Scout prompt rendering sub-leaf (SC-001 escape hatch under scout_correction concern)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..gates import GateResult


def _read_correction_directive_block(vault_dir: Path, cycle_num: int) -> str | None:
    """Render any active correction directive for ``cycle_num`` as a
    markdown block to be prepended to the next prompt invocation.

    Returns ``None`` when no directive exists (the common first-attempt
    path) or when the on-disk directive is unreadable / empty (so
    callers fall through to the legacy untouched prompt).

    This is the spec-019 / 0.2.30 fix for the bug 0.2.29 shipped: the
    correction loop wrote ``_pipeline/corrections/cycle-NNN.json`` but
    nothing ever read it back into a retry prompt. The retry prompt
    was therefore byte-identical to the first attempt, and the agent
    received no feedback. Tests in
    ``tests/pipeline/test_cycle_runner_directive_injection.py`` lock
    this contract.
    """
    cycle_3 = f"{cycle_num:03d}"
    path = vault_dir / "_pipeline" / "corrections" / f"cycle-{cycle_3}.json"
    if not path.exists():
        return None
    try:
        directive = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    diagnosis = (directive.get("diagnosis") or "").strip()
    required_actions = directive.get("required_actions") or []
    forbidden_actions = directive.get("forbidden_actions") or []
    failing_ids = directive.get("failing_gate_ids") or []
    if not diagnosis and not required_actions:
        return None
    parts: list[str] = [
        "## CORRECTION DIRECTIVE — your previous attempt failed",
        "",
        "The pipeline validator rejected your previous output for this cycle.",
        "You MUST address every issue below before re-emitting the report.",
        "Preserve all valid content from your previous attempt; modify only",
        "the fields named in the diagnosis. Do not delete unaffected rows.",
        "",
    ]
    if failing_ids:
        parts.append(f"**Failing gates**: {', '.join(failing_ids)}")
        parts.append("")
    parts.extend(["### Diagnosis", "", diagnosis, ""])
    if required_actions:
        parts.append("### Required actions")
        parts.append("")
        for action in required_actions:
            parts.append(f"- {action}")
        parts.append("")
    if forbidden_actions:
        parts.append("### Forbidden")
        parts.append("")
        for action in forbidden_actions:
            parts.append(f"- {action}")
        parts.append("")
    parts.append("---")
    parts.append("")
    return "\n".join(parts)


def _render_prompt(
    src: Path,
    dest: Path,
    replacements: dict[str, str],
    *,
    vault_dir: Path | None = None,
    cycle_num: int | None = None,
) -> None:
    """Render a prompt template by substituting all placeholder keys with values.

    When ``vault_dir`` and ``cycle_num`` are provided AND an active
    correction directive exists at
    ``<vault>/_pipeline/corrections/cycle-NNN.json``, the directive is
    rendered as a markdown block and **prepended** to the rendered
    prompt. This is how the SG-003 / SG-006 correction loops feed the
    validator's errors back to the agent — without this prepend the
    retry prompt is identical to the first attempt and the loop is a
    no-op (the 0.2.29 bug).

    Callers that don't pass ``vault_dir`` / ``cycle_num`` (e.g. tests
    that exercise the substitution logic in isolation) get the old
    behaviour unchanged.
    """
    text = src.read_text(encoding="utf-8")
    for key, value in replacements.items():
        text = text.replace(key, value)
    if vault_dir is not None and cycle_num is not None:
        directive_block = _read_correction_directive_block(vault_dir, cycle_num)
        if directive_block:
            text = directive_block + "\n" + text
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")


def _parse_priority_queue_from_plan_md(text: str) -> list:
    """Rebuild priority-queue topics from ``## Priority queue`` (``to_markdown`` shape)."""
    from ..research_plan import PrioritizedTopic

    sec = "## Priority queue"
    i = text.find(sec)
    if i < 0:
        return []
    rest = text[i + len(sec) :]
    next_h = re.search(r"\n##\s+", rest)
    block = rest if next_h is None else rest[: next_h.start()]
    out: list[PrioritizedTopic] = []
    for line in block.splitlines():
        line = line.strip()
        m = re.match(r"^\d+\.\s+(.+)$", line)
        if not m:
            continue
        body = m.group(1)
        parts = [p.strip() for p in body.split(" · ")]
        if len(parts) < 3:
            continue
        title, category, score_s = parts[0], parts[1], parts[2]
        provenance = parts[3] if len(parts) > 3 else "spec_gap"
        sources_raw = parts[4] if len(parts) > 4 else "—"
        citation_count = 0
        if provenance.endswith(")") and "(" in provenance:
            pv, _, inner = provenance.rpartition("(")
            if inner.endswith(")"):
                try:
                    citation_count = int(inner[:-1])
                    provenance = pv.rstrip()
                except ValueError:
                    provenance = parts[3] if len(parts) > 3 else "spec_gap"
        hints: list[str] = []
        if sources_raw and sources_raw != "—":
            hints = [s.strip() for s in sources_raw.split(",") if s.strip()]
        try:
            score = float(score_s)
        except ValueError:
            score = 0.0
        out.append(
            PrioritizedTopic(
                title=title,
                category=category,
                priority_score=score,
                source_hints=hints,
                provenance=provenance or "spec_gap",
                citation_count=citation_count,
            )
        )
    return out


def _render_batch_note_writer_prompt(
    *,
    dfs_prompt_src: Path,
    dest: Path,
    cycle_num: int,
    scout_report: Path,
    research_report: Path,
    batch_topics,
    correction_directive: str,
) -> None:
    topics_payload = json.dumps([t.to_dict() for t in batch_topics], indent=2)
    parts = [
        dfs_prompt_src.read_text(encoding="utf-8")
        .replace("{CYCLE_NUM}", str(cycle_num))
        .replace("{SCOUT_REPORT}", str(scout_report))
        .replace("{RESEARCH_REPORT}", str(research_report)),
        "",
        "## Batch topics (JSON)",
        "",
        "```json",
        topics_payload,
        "```",
        "",
    ]
    if correction_directive.strip():
        parts.extend(["## Correction directive", "", correction_directive.strip(), ""])
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(parts).strip() + "\n", encoding="utf-8")


def _correction_prompt_text(
    vault_dir: Path, failing_gates: list[GateResult], *, cycle: int, batch: int | None
) -> str:
    from research_framework.pipeline.correction import (
        CorrectionDirective,
        build_directive,
    )

    path = build_directive(
        vault_dir, failing_gates=failing_gates, cycle=cycle, batch=batch
    )
    directive = CorrectionDirective.from_dict(
        json.loads(path.read_text(encoding="utf-8"))
    )
    block = directive.to_prompt_block()
    if any(g.gate_id == "SG-005" for g in failing_gates):
        # Use the gate's own correction hint as the prelude rather than the
        # legacy "restore frontmatter completeness" string. Many SG-005
        # failures (batch_yield_empty, batch_topic_adherence) have nothing
        # to do with frontmatter — see ``_synthetic_mid_batch_empty_sg005``.
        first_sg005 = next(g for g in failing_gates if g.gate_id == "SG-005")
        hint = (first_sg005.correction_hint or "").strip()
        prelude = hint or (
            "SG-005 correction: write notes for the assigned topics "
            "(do not edit existing notes to inflate the count)."
        )
        block = prelude + "\n\n" + block
    return block
