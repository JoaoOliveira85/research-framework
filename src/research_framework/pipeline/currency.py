"""The due-review sweep (spec 087 FR-010).

At the start of a cycle, every note whose type declares ``review_after_days``,
whose standing is live and whose ``as_of`` is older than that interval gets an
open ``update`` entry with ``reason: review_due`` in the research backlog.

Deterministic and offline: it reads note frontmatter and the spec, calls no
model and no network, and writes the backlog in one transaction.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from research_framework.vault.frontmatter import (
    FrontmatterParseError,
    parse_frontmatter,
)
from research_framework.vault.note_currency import effective, is_due

from ..spec.schema import SpecConfig
from . import backlog

_LOG = logging.getLogger(__name__)

_INDEX_FILES = ("_index.md", "_concepts.md", "_graph.md")


def due_notes(vault_dir: Path, spec: SpecConfig, today: date) -> list[tuple[str, str]]:
    """``(stem, as_of)`` for each note past its type's review interval.

    Sorted by path, so the result is the same for the same tree. Alias stubs
    and notes marked ``verifier_status: exempt`` are skipped, as coverage skips
    aliases; a note whose type declares no interval is never due.
    """
    intervals = {
        nt.name: nt.review_after_days
        for nt in spec.note_types
        if nt.review_after_days is not None
    }
    if not intervals:
        return []
    corpus = vault_dir / (spec.vault_corpus_dir or "data_vault")
    if not corpus.is_dir():
        return []
    due: list[tuple[str, str]] = []
    for path in sorted(corpus.rglob("*.md")):
        if path.name in _INDEX_FILES or "_templates" in path.relative_to(corpus).parts:
            continue
        try:
            fm, _body = parse_frontmatter(path)
        except (OSError, FrontmatterParseError):
            continue
        if not fm:
            continue
        if str(fm.get("note_type", "") or "").strip().lower() == "alias":
            continue
        if str(fm.get("verifier_status", "") or "").strip().lower() == "exempt":
            continue
        interval = intervals.get(str(fm.get("type", "") or "").strip())
        if interval is None or not is_due(fm, interval, today):
            continue
        as_of = effective(fm)[1]
        due.append((path.stem, as_of.isoformat() if as_of else ""))
    return due


def queue_due_reviews(vault_dir: Path, spec: SpecConfig, today: date) -> int:
    """Record a ``review_due`` update entry for every due note; return how many.

    One ``backlog.update`` transaction as the ``review`` writer, and none at all
    when nothing is due (a vault with no interval never gets a store created
    here). Returns 0 when the backlog could not be written.
    """
    due = due_notes(vault_dir, spec, today)
    if not due:
        return 0

    def observe(tx: backlog.Transaction) -> None:
        for stem, as_of in due:
            tx.observe_update(stem, "review_due", as_of=as_of or None)

    if not backlog.update(vault_dir, "review", observe):
        return 0
    _LOG.info("[currency] %d note(s) past their review interval queued", len(due))
    return len(due)
