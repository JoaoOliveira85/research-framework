"""Update outcomes and their gate (spec 087 FR-005, FR-011..FR-014).

An update batch asks the writer to revisit existing notes. The writer *proposes*
one outcome per assigned note in the research report's ``update_outcomes``; this
module decides, deterministically and against git ``HEAD``, whether each one
stands (gate ``UG-001``):

* ``confirmed``: the body is byte-identical to ``HEAD``, only ``as_of`` moved,
  and the sources consulted are recorded;
* ``revised``: the body changed and at least one ``source_urls`` entry is new;
* ``superseded``: ``currency: superseded``, the successor field names a note that
  exists (or one the batch reports as pending), and that successor's
  ``supersedes`` names this note;
* ``retracted``: ``currency: retracted`` with a reason recorded in the note.

Every outcome also needs ``as_of`` set to today. A note with no outcome, or one
that fails its check, is restored from ``HEAD`` and its backlog entry stays open;
a passing one closes the entry. ``notes_updated`` in the report is *derived*:
exactly the notes whose passing outcome is not ``confirmed``, and a ``confirmed``
note is counted nowhere as content (FR-014).

Whether a ``superseded`` or ``retracted`` outcome is *credible* (its evidence
source's credibility) is the verifier's call, not this gate's.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from research_framework.vault import note_currency as nc
from research_framework.vault.frontmatter import (
    FrontmatterParseError,
    parse_frontmatter_str,
)

from . import backlog, vault_git
from .atomic_write import write_json
from .gates import GateResult, run_gate
from .gates_step import UG001_update_outcomes
from .research_plan import UpdateTopic

_LOG = logging.getLogger(__name__)

_INDEX_FILES = ("_index.md", "_concepts.md", "_graph.md")


@dataclass(frozen=True)
class Verdict:
    """The gate's finding for one assigned note."""

    stem: str
    path: str
    outcome: str | None
    ok: bool
    reason: str = ""
    sources_consulted: tuple[str, ...] = ()
    evidence_url: str | None = None
    successor: str | None = None
    change: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "note": self.stem,
            "path": self.path,
            "outcome": self.outcome,
            "status": "passed" if self.ok else "failed",
            "reason": self.reason,
            "sources_consulted": list(self.sources_consulted),
            "evidence_url": self.evidence_url,
            nc.SUPERSEDED_BY_FIELD: self.successor,
            "change": self.change,
        }


@dataclass
class BatchOutcomes:
    gate: GateResult
    verdicts: list[Verdict] = field(default_factory=list)


_slug = nc.ref_slug
_refs = nc.refs


def _urls(fm: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    raw = fm.get("source_urls")
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, str):
            out.add(item.strip())
        elif isinstance(item, dict) and isinstance(item.get("url"), str):
            out.add(item["url"].strip())
    return {u for u in out if u}


def _strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, list):
        return tuple(str(v).strip() for v in value if str(v).strip())
    return ()


def _split(text: str) -> tuple[dict[str, Any], str]:
    try:
        return parse_frontmatter_str(text)
    except FrontmatterParseError:
        return {}, text


def _comparable(fm: dict[str, Any]) -> dict[str, Any]:
    """Frontmatter minus what a ``confirmed`` outcome is allowed to move."""
    out = {k: v for k, v in fm.items() if k != nc.AS_OF_FIELD}
    out[nc.CURRENCY_FIELD] = nc.effective(fm)[0]
    return out


_notes_by_slug = nc.corpus_notes_by_slug


def _row_for(stem: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    want = _slug(stem)
    for row in rows:
        if isinstance(row, dict) and _slug(str(row.get("note") or "")) == want:
            return row
    return None


def _check(
    vault_dir: Path,
    topic: UpdateTopic,
    row: dict[str, Any] | None,
    *,
    today: date,
    pending: set[str],
    notes: dict[str, Path],
) -> Verdict:
    sources = _strings(row.get("sources_consulted")) if row else ()
    evidence = (
        str(row["evidence_url"]).strip()
        if row and isinstance(row.get("evidence_url"), str)
        else ""
    )
    successor_raw = (
        str(row[nc.SUPERSEDED_BY_FIELD]).strip()
        if row and isinstance(row.get(nc.SUPERSEDED_BY_FIELD), str)
        else ""
    )
    outcome = str(row["outcome"]).strip() if row and row.get("outcome") else None
    base = {
        "stem": topic.stem,
        "path": topic.path,
        "outcome": outcome,
        "sources_consulted": sources,
        "evidence_url": evidence or None,
        "successor": successor_raw or None,
        "change": str(row.get("change") or "") if row else "",
    }

    def fail(reason: str) -> Verdict:
        return Verdict(ok=False, reason=reason, **base)

    if row is None:
        return fail("no outcome was reported for this note")
    if outcome not in backlog.OUTCOMES:
        return fail(f"outcome {outcome!r} is not one of {', '.join(backlog.OUTCOMES)}")
    note = vault_dir / topic.path if topic.path else None
    if note is None or not note.is_file():
        return fail("the assigned note is not on disk")
    head_text = vault_git.head_content(vault_dir, topic.path)
    if head_text is None:
        return fail("the note did not exist at HEAD, so there is nothing to compare")
    head_fm, head_body = _split(head_text)
    try:
        fm, body = parse_frontmatter_str(note.read_text(encoding="utf-8"))
    except (OSError, FrontmatterParseError) as exc:
        return fail(f"the note's frontmatter does not parse ({exc})")

    as_of = nc.effective(fm)[1]
    if as_of is None or abs((as_of - today).days) > 1:
        return fail(f"as_of is not today ({today.isoformat()}): {fm.get('as_of')!r}")

    if outcome == "confirmed":
        if not sources:
            return fail("a confirmed outcome must record the sources consulted")
        if body != head_body:
            return fail("confirmed, but the body differs from HEAD")
        if _comparable(fm) != _comparable(head_fm):
            return fail("confirmed, but frontmatter other than as_of changed")
    elif outcome == "revised":
        if body == head_body:
            return fail("revised, but the body is identical to HEAD")
        if not (_urls(fm) - _urls(head_fm)):
            return fail("revised, but no source_urls entry was added")
    elif outcome == "superseded":
        if nc.effective(fm)[0] != nc.SUPERSEDED:
            return fail(f"superseded, but {nc.CURRENCY_FIELD} is not superseded")
        refs = _refs(fm.get(nc.SUPERSEDED_BY_FIELD))
        if not refs:
            return fail(f"superseded, but {nc.SUPERSEDED_BY_FIELD} is empty")
        if successor_raw and _slug(successor_raw) not in refs:
            return fail("the report and the note name different successors")
        if not evidence:
            return fail("superseded needs the evidence_url that supports it")
        for ref in refs:
            successor = notes.get(ref)
            if successor is None:
                if ref in pending:
                    continue  # reported as pending; symmetry is the verifier's
                return fail(f"the successor {ref!r} does not exist")
            try:
                succ_fm, _ = parse_frontmatter_str(successor.read_text("utf-8"))
            except (OSError, FrontmatterParseError):
                return fail(f"the successor {ref!r} does not parse")
            if _slug(topic.stem) not in _refs(succ_fm.get(nc.SUPERSEDES_FIELD)):
                return fail(
                    f"the successor {ref!r} does not name this note in "
                    f"{nc.SUPERSEDES_FIELD}"
                )
    elif outcome == "retracted":
        if nc.effective(fm)[0] != nc.RETRACTED:
            return fail(f"retracted, but {nc.CURRENCY_FIELD} is not retracted")
        reason = fm.get(nc.RETRACTION_REASON_FIELD)
        if not (isinstance(reason, str) and reason.strip()):
            return fail(
                f"retracted, but no {nc.RETRACTION_REASON_FIELD} is recorded "
                "in the note"
            )
        if not evidence:
            return fail("retracted needs the evidence_url that supports it")
    return Verdict(ok=True, **base)


def evaluate(
    vault_dir: Path,
    assigned: list[UpdateTopic],
    rows: list[dict[str, Any]],
    *,
    today: date | None = None,
    pending: set[str] | None = None,
) -> list[Verdict]:
    """One :class:`Verdict` per assigned note (no filesystem or git writes)."""
    today = today or datetime.now(UTC).date()
    notes = _notes_by_slug(vault_dir)
    return [
        _check(
            vault_dir,
            topic,
            _row_for(topic.stem, rows),
            today=today,
            pending=pending or set(),
            notes=notes,
        )
        for topic in assigned
    ]


def restore_note(vault_dir: Path, rel_path: str) -> bool:
    """Put a note back to its content at ``HEAD``; ``False`` when it has none."""
    previous = vault_git.head_content(vault_dir, rel_path)
    if previous is None:
        return False
    try:
        (vault_dir / rel_path).write_text(previous, encoding="utf-8")
    except OSError as exc:
        _LOG.warning("[update_outcomes] could not restore %s: %s", rel_path, exc)
        return False
    return True


def _sidecar(cycles_dir: Path, cycle: int) -> Path:
    return cycles_dir / f"cycle-{cycle:03d}-update-outcomes.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def apply_batch(
    vault_dir: Path,
    cycles_dir: Path,
    research_report: Path,
    cycle: int,
    assigned: list[UpdateTopic],
    *,
    today: date | None = None,
) -> BatchOutcomes:
    """Judge one update batch, act on the verdicts and record the result.

    Failing notes are restored from ``HEAD`` and their entries left open;
    passing outcomes close their entries as the ``research`` writer. The
    research report's ``notes_updated`` is then derived from every update batch
    of the cycle so far, and the assigned notes are removed from
    ``notes_created`` (an outcome is not a new note).
    """
    report = _read_json(research_report)
    raw_rows = report.get("update_outcomes")
    rows = (
        [r for r in raw_rows if isinstance(r, dict)]
        if isinstance(raw_rows, list)
        else []
    )
    pending = {
        _slug(w)
        for key in ("new_wikilinks_discovered", "unresolved_wikilinks")
        for w in (report.get(key) or [])
        if isinstance(w, str)
    }
    verdicts = evaluate(vault_dir, assigned, rows, today=today, pending=pending)
    gate = run_gate(UG001_update_outcomes, verdicts)
    for verdict in verdicts:
        if verdict.ok:
            backlog.close_update(
                vault_dir, verdict.stem, verdict.outcome or "", cycle=cycle
            )
        elif verdict.path and restore_note(vault_dir, verdict.path):
            _LOG.warning(
                "[update_outcomes] %s: %s; restored from HEAD, entry left open",
                verdict.stem,
                verdict.reason,
            )
        else:
            _LOG.warning(
                "[update_outcomes] %s: %s; entry left open",
                verdict.stem,
                verdict.reason,
            )

    # accumulate across the cycle's update batches (the writer may rewrite the
    # report, so the record lives beside it)
    sidecar = _sidecar(cycles_dir, cycle)
    results = {
        r["note"]: r
        for r in _read_json(sidecar).get("results", [])
        if isinstance(r, dict) and "note" in r
    }
    for verdict in verdicts:
        entry = verdict.to_dict()
        entry["row"] = _row_for(verdict.stem, rows)
        results[verdict.stem] = entry
    write_json(sidecar, {"cycle": cycle, "results": list(results.values())})
    _patch_report(research_report, report, list(results.values()))
    return BatchOutcomes(gate=gate, verdicts=verdicts)


def recorded_result(
    vault_dir: Path, cycle: int, note_rel: str
) -> dict[str, Any] | None:
    """The cycle's recorded outcome for the note at ``note_rel``, if it had one."""
    sidecar = _sidecar(vault_dir / "_pipeline" / "cycles", cycle)
    for row in _read_json(sidecar).get("results", []):
        if isinstance(row, dict) and row.get("path") == note_rel:
            return row
    return None


def reject_outcome(vault_dir: Path, cycle: int, note_rel: str, reason: str) -> bool:
    """The verifier rejected an update outcome UG-001 had passed (FR-013).

    The note itself is put back from ``HEAD`` by the rejected-note sweep, the
    same path a rejected rewrite of a committed note takes. What this does is
    make the record say so: the result becomes ``failed`` with the reason, the
    report's ``notes_updated`` is re-derived without it, and the backlog entry
    that UG-001 closed is reopened, with the rejected outcome kept in its
    history. Returns ``False`` when the note had no passing outcome this cycle.
    """
    cycles_dir = vault_dir / "_pipeline" / "cycles"
    sidecar = _sidecar(cycles_dir, cycle)
    doc = _read_json(sidecar)
    results = [r for r in doc.get("results", []) if isinstance(r, dict)]
    target = next(
        (
            r
            for r in results
            if r.get("path") == note_rel and r.get("status") == "passed"
        ),
        None,
    )
    if target is None:
        return False
    target["status"] = "failed"
    target["reason"] = f"rejected by the verifier: {reason}"
    write_json(sidecar, {"cycle": cycle, "results": results})
    research_report = cycles_dir / f"cycle-{cycle:03d}-research.json"
    _patch_report(research_report, _read_json(research_report), results)
    backlog.reopen_update(
        vault_dir, str(target["note"]), f"verifier: {reason}", cycle=cycle
    )
    return True


def _patch_report(
    research_report: Path, report: dict[str, Any], results: list[dict[str, Any]]
) -> None:
    """Derive ``notes_updated`` and record the verdicts in the research report."""
    assigned_paths = {r["path"] for r in results if r.get("path")}
    report["update_outcomes"] = [r["row"] for r in results if r.get("row")]
    report["update_outcome_results"] = [
        {k: v for k, v in r.items() if k != "row"} for r in results
    ]
    report["notes_updated"] = [
        r["path"]
        for r in results
        if r.get("status") == "passed" and r.get("outcome") != "confirmed" and r["path"]
    ]
    report["notes_created"] = [
        n for n in (report.get("notes_created") or []) if n not in assigned_paths
    ]
    write_json(research_report, report)


__all__ = [
    "BatchOutcomes",
    "recorded_result",
    "reject_outcome",
    "Verdict",
    "apply_batch",
    "evaluate",
    "restore_note",
]
