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
import math
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
from .research_plan import UpdateTopic, _exclusion_slug
from .settings import CycleSplit, SettingsError, load_vault_settings

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
    rows: list[dict[str, Any]] = []
    try:
        doc = json.loads(scout_report.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    found = doc.get("topics_found") if isinstance(doc, dict) else None
    updates = found.get("updates") if isinstance(found, dict) else None
    for row in updates if isinstance(updates, list) else []:
        name = str(row.get("note") or "").strip() if isinstance(row, dict) else ""
        key = _exclusion_slug(name) if name else ""
        if not key or key not in notes:
            _LOG.warning(
                "[currency] scout update names no existing note, ignored: %r", row
            )
            continue
        urls = row.get("source_urls")
        rows.append({"key": key, "source_urls": urls if isinstance(urls, list) else []})
    rows.extend(dropped_new_rows)
    return record_new_material(vault_dir, spec, rows, cycle=cycle)


def record_new_material(
    vault_dir: Path,
    spec: SpecConfig,
    rows: Iterable[Mapping[str, Any]],
    cycle: int | None = None,
) -> int:
    """Queue a ``new_material`` update per existing note the rows point at.

    Each row is ``{"key": <normalised note slug>, "source_urls": [...]}``; a row
    whose key names no existing note is skipped. Sightings of one note merge
    (urls deduplicated, in order). One transaction as the ``scout`` writer;
    returns how many notes were queued. Used by the scout step (its ``updates``
    rows and the ``new`` rows the plan merge dropped) and by the discovery
    routing (a finding about a note the vault holds, spec 088).
    """
    notes = _corpus_notes(vault_dir, spec)
    sightings: dict[str, list[str]] = {}
    for row in rows:
        path = notes.get(str(row.get("key") or ""))
        if path is None:
            continue
        known = sightings.setdefault(path.stem, [])
        for url in row.get("source_urls") or []:
            text = str(url).strip()
            if text and text not in known:
                known.append(text)
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
    discovery_available: int = 0,
    discovery_credit: float | None = None,
) -> tuple[int, int, int]:
    """Share a cycle's planned topic count: ``(new_n, update_n, discovery_n)``.

    ``shares`` is ``pipeline.cycle_split`` (``new``/``updates``/``discovery``,
    attributes or mapping keys). Spec 087 FR-015..FR-017 and spec 088 FR-007:

    * ``discovery_n`` is the cap on discovery topics dispatched. It is
      ``min(floor(credit), discovery_available, quota)``, where ``credit`` is
      ``discovery_credit`` (the ledger's carried fractional credit,
      :func:`.discovery.accrue_credit`) or, when none is given, this cycle's
      share of the quota. It is 0 when no discovery topic is waiting, when the
      discovery share is 0, and under ``refresh``; the share then goes to new
      topics, exactly as it did before discovery had work of its own.
    * The rest of the quota is shared between new topics and updates: ``mode``
      applies first (``bootstrap`` gives updates 0, ``refresh`` gives new
      topics 0, ``expand`` and anything else uses the shares as written), and
      the two are rounded together (largest remainder) so they sum to the rest.
      A discovery share that did not dispatch anything counts as a new-topic
      share; one that did does not.
    * A share with no work falls to the other: with fewer open update entries
      than the update count the rest goes to new topics, and with fewer new
      topics than the new count the rest goes to updates. A mode's zero is
      never filled. The result may sum to less than ``quota`` when neither
      kind has enough work.
    """
    quota = max(0, int(quota))
    new_available = max(0, int(new_available))
    updates_available = max(0, int(updates_available))
    discovery_available = max(0, int(discovery_available))
    discovery_share = _share(shares, "discovery")
    discovery_n = 0
    if mode != "refresh" and discovery_share and discovery_available and quota:
        credit = (
            quota * discovery_share / 100
            if discovery_credit is None
            else float(discovery_credit)
        )
        discovery_n = min(math.floor(credit + 1e-9), discovery_available, quota)
        discovery_n = max(discovery_n, 0)
    quota -= discovery_n
    new_weight = _share(shares, "new") + (0 if discovery_n else discovery_share)
    update_weight = _share(shares, "updates")
    if mode == "bootstrap":
        update_weight = 0
    elif mode == "refresh":
        new_weight = 0
    total = new_weight + update_weight
    if quota == 0 or total == 0:
        return 0, 0, discovery_n
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
    return new_n, update_n, discovery_n


def note_path(vault_dir: Path, spec: SpecConfig, stem: str) -> Path | None:
    """The corpus note whose stem matches ``stem`` (normalised), if any."""
    return _corpus_notes(vault_dir, spec).get(_exclusion_slug(stem))


def cycle_split_shares(vault_dir: Path) -> CycleSplit:
    """``pipeline.cycle_split`` of the vault; the default when unreadable."""
    try:
        return load_vault_settings(vault_dir).cycle_split
    except SettingsError:
        return CycleSplit()


def cycle_mode(vault_dir: Path, spec: SpecConfig | None = None) -> str:
    """The vault's ``research_mode`` (``expand`` when it cannot be read)."""
    if spec is not None:
        return spec.research_mode or "expand"
    from research_framework.spec.parsed import ParsedSpecError, load_parsed_spec

    try:
        return str(load_parsed_spec(vault_dir).get("research_mode") or "expand")
    except ParsedSpecError:
        return "expand"


UPDATES_NEED_GIT = (
    "update batches need the vault's git history: enable vault_commit "
    "(`vault_commit.enabled: true` in settings.yaml) and initialise the "
    "repository with at least one commit"
)


def updates_supported(vault_dir: Path) -> tuple[bool, str]:
    """Whether update batches can run in this vault, and if not, why.

    UG-001 and the verifier's currency rules compare a note with its content at
    git ``HEAD`` and restore it from there, so a vault that is not a git
    repository with a first commit, or whose ``vault_commit.enabled`` is false
    (nothing would keep ``HEAD`` current), cannot have an update judged or
    undone. The due sweep and the scout still queue entries there: they need no
    git, and the work is picked up once the vault has history.
    """
    from . import vault_commit, vault_git

    if not vault_git.is_git_repo(vault_dir):
        return False, f"{vault_dir} is not a git repository; {UPDATES_NEED_GIT}"
    if not vault_commit._load_settings(vault_dir)["enabled"]:
        return False, f"vault_commit.enabled is false; {UPDATES_NEED_GIT}"
    if vault_git._run(["git", "rev-parse", "--verify", "HEAD"], vault_dir).returncode:
        return False, f"the repository has no commits yet; {UPDATES_NEED_GIT}"
    return True, ""


def warn_if_updates_unsupported(vault_dir: Path, cycle: int) -> None:
    """One WARNING per cycle when open update entries cannot be dispatched."""
    supported, why = updates_supported(vault_dir)
    if supported or not backlog.update_topics(vault_dir):
        return
    _LOG.warning("[currency] cycle %d: no update work is planned: %s", cycle, why)


def plan_updates(
    vault_dir: Path, spec: SpecConfig, quota: int, new_available: int
) -> tuple[list[UpdateTopic], int | None, int]:
    """The update queue and the ``(new, update)`` split of a cycle's quota.

    Returns ``([], None, 0)`` when no update work is planned (share 0, the
    ``bootstrap`` mode, or no open update entries), so the plan is exactly what
    it was before spec 087. At planning time scouted topics are not yet merged
    into the queue, so new topics are treated as plentiful
    (``max(new_available, quota)``); the batch loop re-splits against the
    merged queue.
    """
    refs = backlog.update_topics(vault_dir)
    if not updates_supported(vault_dir)[0]:
        refs = []  # the share falls to new topics, as for any empty share
    new_n, update_n, _discovery_n = split_quota(
        quota,
        cycle_split_shares(vault_dir),
        mode=cycle_mode(vault_dir, spec),
        new_available=max(new_available, quota),
        updates_available=len(refs),
    )
    if update_n <= 0:
        return [], None, 0
    from . import vault_git

    notes = _corpus_notes(vault_dir, spec)
    queue = []
    limit = max(quota, update_n)
    for ref in refs:
        if len(queue) >= limit:
            break
        found = notes.get(_exclusion_slug(ref.stem))
        rel = found.relative_to(vault_dir).as_posix() if found else ""
        if not rel or vault_git.head_content(vault_dir, rel) is None:
            # Never committed (or not on disk): it can be neither compared nor
            # restored, so it waits for a commit instead of failing.
            continue
        queue.append(
            UpdateTopic(
                stem=ref.stem,
                path=rel,
                reason=ref.reason,
                as_of=ref.as_of,
                prompted_by=ref.prompted_by,
            )
        )
    new_n, update_n, _discovery_n = split_quota(
        quota,
        cycle_split_shares(vault_dir),
        mode=cycle_mode(vault_dir, spec),
        new_available=max(new_available, quota),
        updates_available=len(queue),
    )
    if update_n <= 0:
        return [], None, 0
    return queue, new_n, update_n


def cycle_expectations(
    vault_dir: Path,
    spec: SpecConfig,
    quota: int,
    scout_updates: int = 0,
    discovery_available: int = 0,
) -> tuple[int, int]:
    """``(new topics wanted, other work planned)`` for a cycle, for the scout gates.

    The same split the plan makes (:func:`split_quota`), but computed when the
    scout has just reported: ``scout_updates`` is the number of
    ``topics_found.updates`` rows it returned, which add to the open entries.
    New topics are treated as plentiful (the scout is the one finding them), so
    ``new wanted`` is 0 only when the mode (``refresh``) or the shares ask for
    none, and the second count is 0 when the vault cannot run update batches.

    Spec 088: ``discovery_available`` is how many discovery topics could be
    dispatched this cycle (open backlog topics plus the rows in this report).
    Discovery topics are not ``topics_found.new`` rows, so the slots they take
    are taken OFF ``new wanted`` (SG-001 must not expect rows in
    ``topics_found.new`` for work the discovery share will do) and ADDED to the
    second count, which is "work the cycle will do besides new topics": updates
    plus discovery topics. With none available this is exactly the spec-087
    ``(new wanted, updates planned)``.
    """
    supported = updates_supported(vault_dir)[0]
    available = 0
    if supported:
        available = len(backlog.update_topics(vault_dir)) + max(0, scout_updates)
    new_n, update_n, discovery_n = split_quota(
        max(1, quota),
        cycle_split_shares(vault_dir),
        mode=cycle_mode(vault_dir, spec),
        new_available=max(1, quota),
        updates_available=available,
        discovery_available=discovery_available,
    )
    return new_n, update_n + discovery_n


def update_work_continues(report: Mapping[str, Any]) -> bool:
    """Whether a research report shows update work worth another cycle.

    ``update_work`` is stamped by the research step when the cycle ran update
    batches: ``worked`` counts outcomes that passed (``confirmed`` included),
    ``failed`` those that did not, ``open_after`` the entries still queued.
    A cycle that worked at least one update and left some made progress and may
    continue; one whose update batches all failed did not, so it cannot loop
    (the attempts limit then sets the stuck entries aside).
    """
    work = report.get("update_work")
    if not isinstance(work, Mapping):
        return False
    return (
        int(work.get("worked", 0) or 0) > 0 and int(work.get("open_after", 0) or 0) > 0
    )


def update_work_made_progress(report: Mapping[str, Any]) -> bool:
    """Whether a research report records at least one update outcome that held."""
    rows = report.get("update_outcome_results")
    return isinstance(rows, list) and any(
        isinstance(r, Mapping) and r.get("status") == "passed" for r in rows
    )


def stamp_update_work(vault_dir: Path, cycle: int, report_path: Path) -> None:
    """Record in the cycle's research report how its update batches went."""
    from .atomic_write import write_json
    from .update_outcomes import _read_json, _sidecar

    results = _read_json(_sidecar(vault_dir / "_pipeline" / "cycles", cycle)).get(
        "results"
    )
    if not isinstance(results, list) or not results:
        return
    report = _read_json(report_path)
    if not report:
        return
    worked = sum(
        1 for r in results if isinstance(r, dict) and r.get("status") == "passed"
    )
    report["update_work"] = {
        "worked": worked,
        "failed": len(results) - worked,
        "open_after": len(backlog.update_topics(vault_dir))
        if updates_supported(vault_dir)[0]
        else 0,
    }
    write_json(report_path, report)
