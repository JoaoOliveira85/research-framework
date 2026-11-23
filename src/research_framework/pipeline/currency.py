"""Note currency in the pipeline (spec 087): the due-review sweep and the
scout's update rows.

At the start of a cycle, every note whose type declares ``review_after_days``,
whose standing is live and whose ``as_of`` is older than that interval gets an
open ``update`` entry with ``reason: review_due`` in the research backlog.

Deterministic and offline: it reads note frontmatter and the spec, calls no
model and no network, and writes the backlog in one transaction.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path
from typing import Any

from research_framework.vault.frontmatter import (
    FrontmatterParseError,
    parse_frontmatter,
)
from research_framework.vault.note_currency import effective, is_due

from ..spec.schema import SpecConfig
from . import backlog
from .research_plan import _exclusion_slug

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


def _corpus_notes(vault_dir: Path, spec: SpecConfig) -> dict[str, Path]:
    """Every note under the corpus, keyed by its normalised stem."""
    corpus = vault_dir / (spec.vault_corpus_dir or "data_vault")
    notes: dict[str, Path] = {}
    if not corpus.is_dir():
        return notes
    for path in sorted(corpus.rglob("*.md")):
        if path.name in _INDEX_FILES or "_templates" in path.relative_to(corpus).parts:
            continue
        notes.setdefault(_exclusion_slug(path.stem), path)
    return notes


def record_scout_updates(
    vault_dir: Path,
    spec: SpecConfig,
    scout_report: Path,
    dropped_new_rows: Iterable[dict[str, Any]] = (),
    cycle: int | None = None,
) -> int:
    """Queue ``new_material`` updates from a scout report; return how many notes.

    Two sources, one transaction as the ``scout`` writer:

    * each ``topics_found.updates`` row whose ``note`` resolves to an existing
      note (a row naming no existing note is ignored with a WARNING);
    * each ``topics_found.new`` row the plan merge dropped because it matches an
      existing note (``dropped_new_rows``, from ``merge_scout_topics_detailed``),
      carrying the row's ``source_urls``.
    """
    notes = _corpus_notes(vault_dir, spec)
    sightings: dict[str, list[str]] = {}

    def add(stem_path: Path, urls: Iterable[Any]) -> None:
        sightings.setdefault(stem_path.stem, [])
        for url in urls:
            text = str(url).strip()
            if text and text not in sightings[stem_path.stem]:
                sightings[stem_path.stem].append(text)

    try:
        doc = json.loads(scout_report.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    found = doc.get("topics_found") if isinstance(doc, dict) else None
    rows = found.get("updates") if isinstance(found, dict) else None
    for row in rows if isinstance(rows, list) else []:
        name = str(row.get("note") or "").strip() if isinstance(row, dict) else ""
        path = notes.get(_exclusion_slug(name)) if name else None
        if path is None:
            _LOG.warning(
                "[currency] scout update names no existing note, ignored: %r", row
            )
            continue
        urls = row.get("source_urls")
        add(path, urls if isinstance(urls, list) else [])
    for row in dropped_new_rows:
        path = notes.get(str(row.get("key") or ""))
        if path is not None:
            add(path, row.get("source_urls") or [])
    if not sightings:
        return 0
    by_stem = {p.stem: p for p in notes.values()}

    def observe(tx: backlog.Transaction) -> None:
        for stem, urls in sightings.items():
            try:
                fm, _body = parse_frontmatter(by_stem[stem])
            except (OSError, FrontmatterParseError):
                fm = {}
            as_of = effective(fm)[1]
            tx.observe_update(
                stem,
                "new_material",
                prompted_by=urls,
                cycle=cycle,
                as_of=as_of.isoformat() if as_of else None,
            )

    if not backlog.update(vault_dir, "scout", observe):
        return 0
    return len(sightings)


def _share(shares: object, name: str) -> int:
    value = (
        shares.get(name, 0) if isinstance(shares, Mapping) else getattr(shares, name)
    )
    return max(0, int(value))


def split_quota(
    quota: int,
    shares: object,
    *,
    mode: str,
    new_available: int,
    updates_available: int,
) -> tuple[int, int]:
    """Share a cycle's planned topic count between new topics and updates.

    ``shares`` is ``pipeline.cycle_split`` (``new``/``updates``/``discovery``,
    attributes or mapping keys). Spec 087 FR-015..FR-017:

    * Discovery has no work of its own yet, so its share always goes to new
      topics.
    * ``mode`` applies first: ``bootstrap`` gives updates 0, ``refresh`` gives
      new topics 0, ``expand`` (and anything else) uses the shares as written.
    * The two shares are rounded together (largest remainder) so they sum to
      ``quota``.
    * A share with no work falls to the other: with fewer open update entries
      than the update count the rest goes to new topics, and with fewer new
      topics than the new count the rest goes to updates. A mode's zero is
      never filled. The result may sum to less than ``quota`` when neither
      kind has enough work.
    """
    quota = max(0, int(quota))
    new_available = max(0, int(new_available))
    updates_available = max(0, int(updates_available))
    new_weight = _share(shares, "new") + _share(shares, "discovery")
    update_weight = _share(shares, "updates")
    if mode == "bootstrap":
        update_weight = 0
    elif mode == "refresh":
        new_weight = 0
    total = new_weight + update_weight
    if quota == 0 or total == 0:
        return 0, 0
    raw_updates = quota * update_weight / total
    update_n = int(raw_updates)
    new_n = int(quota * new_weight / total)
    leftover = quota - update_n - new_n
    if leftover:  # largest remainder, ties to new topics
        new_rem = quota * new_weight / total - new_n
        update_rem = raw_updates - update_n
        if update_rem > new_rem:
            update_n += 1
        else:
            new_n += 1
    if update_weight and update_n > updates_available:
        spare = update_n - updates_available
        update_n = updates_available
        new_n += spare if new_weight else 0
    if new_weight and new_n > new_available:
        spare = new_n - new_available
        new_n = new_available
        update_n += min(spare, updates_available - update_n) if update_weight else 0
    return new_n, update_n
