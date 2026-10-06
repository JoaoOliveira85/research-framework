"""Cycle state persistence, quality-report state helpers, and note lifecycle."""

from __future__ import annotations

import dataclasses
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from ._io import (  # noqa: F401
    _discover_new_markdown_files,
    _state_write,
    _vault_notes_content_sha1,
)

_LOG = logging.getLogger(__name__)


@dataclasses.dataclass
class QualityReportState:
    """Mutable per-cycle state consumed by ``_quality_report_guard`` (spec 025 A6)."""

    cycle_dir: Path
    vault_dir: Path | None = None
    cycle_num: int | None = None
    exit_status: str | None = None
    exit_code: int | None = None
    exception: str | None = None


def _cycle_num_from_dir(cycle_dir: Path) -> int:
    return int(cycle_dir.name.removeprefix("cycle-"))


def _vault_dir_from_state(state: QualityReportState) -> Path:
    if state.vault_dir is not None:
        return state.vault_dir
    return state.cycle_dir.parent.parent.parent


def _cycle_num_from_state(state: QualityReportState) -> int:
    if state.cycle_num is not None:
        return state.cycle_num
    return _cycle_num_from_dir(state.cycle_dir)


def _apply_exit_metadata(report_path: Path, state: QualityReportState) -> None:
    """Merge A6 exit fields into the written quality report (additive)."""
    if state.exit_status is None:
        return
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _LOG.warning("_apply_exit_metadata: could not read %s: %s", report_path, exc)
        return
    data["exit_status"] = state.exit_status
    if state.exception:
        data["exception"] = state.exception
    elif "exception" in data:
        del data["exception"]
    try:
        from ..atomic_write import write_json as _write_json

        _write_json(report_path, data)
    except OSError as exc:
        _LOG.warning("_apply_exit_metadata: could not write %s: %s", report_path, exc)


def _read_skipped_topics_from_research(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    st = doc.get("skipped_topics")
    if not isinstance(st, list):
        st = doc.get("last_batch_skipped_topics")
    if not isinstance(st, list):
        return []
    out: list[dict[str, str]] = []
    for row in st:
        if isinstance(row, dict):
            out.append({str(k): str(v) for k, v in row.items()})
    return out


def _merge_research_notes(research_path: Path, new_names: list[str]) -> None:
    research_path.parent.mkdir(parents=True, exist_ok=True)
    doc: dict = {"notes_created": [], "notes_updated": []}
    if research_path.is_file():
        try:
            doc = json.loads(research_path.read_text(encoding="utf-8")) or doc
        except (OSError, json.JSONDecodeError):
            pass
    prev = list(doc.get("notes_created") or [])
    seen = set(prev)
    for n in new_names:
        if n not in seen:
            prev.append(n)
            seen.add(n)
    doc["notes_created"] = prev
    from ..atomic_write import write_json as _write_json

    _write_json(research_path, doc)


def _stamp_lifecycle_cycle(note_paths: list[Path], cycle_num: int) -> int:
    """Stamp ``lifecycle.created_at_cycle`` on every freshly-written note.

    Note-writer agents (claude / codex) author the body and most of the
    frontmatter, but `lifecycle.created_at_cycle` is *framework-owned*
    metadata: it is read by ``orchestrator._parse_note_created_at_cycle``
    to answer "which notes did this cycle produce?", which in turn drives
    coverage updates, deferred-work lists, and the cycle-summary writer.

    Pre-0.7.0 nothing wrote the field — the agent's skill template never
    mentioned it — so every "what's new this cycle?" query returned an
    empty set and the orchestrator's cycle-attribution logic silently
    underweighted. This helper backfills the field right after the
    note_writer batch returns, before any consumer can read it.

    Idempotent: notes that already declare ``lifecycle.created_at_cycle``
    are left alone (don't overwrite a value the agent set on purpose).

    Returns the number of notes actually stamped (callers may log it).
    """
    stamped = 0
    for path in note_paths:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if not text.startswith("---\n"):
            continue
        end = text.find("\n---\n", 4)
        if end < 0:
            continue
        front = text[4:end]
        body = text[end + 5 :]
        # Already has the field — respect agent intent.
        if re.search(
            r"^lifecycle:\s*\n(?:\s+[^\n]+\n)*\s+created_at_cycle:\s*\d+",
            front,
            re.MULTILINE,
        ) or re.search(r"^lifecycle:\s*\{[^}]*created_at_cycle", front, re.MULTILINE):
            continue
        # Patch: append a `lifecycle:` block in YAML-block form. We avoid
        # mutating an existing `lifecycle:` block of any other shape —
        # detect-and-skip above handles the with-field case, and a
        # without-field lifecycle block is an unusual enough shape that
        # we fall through and append a sibling block; PyYAML and most
        # frontmatter readers tolerate the duplicate key by taking the
        # last one (which is the desired effect).
        addition = f"lifecycle:\n  created_at_cycle: {cycle_num}\n"
        new_front = front.rstrip() + "\n" + addition
        try:
            path.write_text(f"---\n{new_front}---\n{body}", encoding="utf-8")
            stamped += 1
        except OSError:
            continue
    return stamped


def _empty_batch_result_for_pace(cycle: int, batch_number: int):
    from ..batch import BatchResult

    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return BatchResult(
        cycle_number=cycle,
        batch_number=batch_number,
        started_at=ts,
        finished_at=ts,
        notes_written=[],
        skipped_topics=[],
        sg_gate_results=[],
        topics=None,
    )
