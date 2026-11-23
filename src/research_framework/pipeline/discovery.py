"""Outside-in discovery: scope areas, their rotation and the ledger (spec 088).

Each cycle the scout is handed a few of the spec's scope areas, least recently
checked first, and asked what is new in them without starting from the vault's
own note titles. This module holds the deterministic pieces: which lines of the
spec are areas, which areas a cycle gets, and the ledger that remembers what was
checked. A scope area that was checked and had nothing new is recorded as such,
so "checked, nothing found" differs from "never checked".

The ledger lives at :func:`state_layout.discovery_ledger_path`. Per-cycle records
are the source of truth: the per-area figures are recomputed from them on every
write, so recording the same cycle twice replaces its record and nothing is
counted twice.

The ledger also carries the discovery share's fractional credit (spec 088
Q1): a 10% share of a small quota rounds to zero topics, so each cycle adds
``share x quota / 100`` and a whole unit buys one dispatch slot. The credit is
keyed by cycle number (see :func:`accrue_credit`), so planning twice in one
cycle adds it once.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from ..spec.schema import SpecConfig
from . import backlog, rejects, state_layout
from .atomic_write import write_json
from .settings import (
    CycleSplit,
    DiscoverySettings,
    SettingsError,
    load_vault_settings,
)

_LOG = logging.getLogger(__name__)

SCHEMA_VERSION = 1

#: Provenance of a discovery topic in the research plan's priority queue.
DISCOVERY_PROVENANCE = "discovery"

Ledger = dict[str, Any]


class DiscoveryLedgerError(RuntimeError):
    """The ledger file exists and cannot be read as a ledger."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"discovery ledger {path} is unreadable: {reason}")


def discovery_settings(vault_dir: Path) -> DiscoverySettings:
    """``pipeline.discovery`` of the vault; the defaults when unreadable."""
    try:
        return load_vault_settings(vault_dir).discovery
    except SettingsError:
        return DiscoverySettings()


def discovery_share(vault_dir: Path) -> int:
    """The ``pipeline.cycle_split`` discovery share (0 switches the pass off)."""
    try:
        return load_vault_settings(vault_dir).cycle_split.discovery
    except SettingsError:
        return CycleSplit().discovery


def scope_areas(spec: SpecConfig) -> list[str]:
    """The spec's scope lines: stripped, in spec order, first duplicate kept.

    A simple-format spec's ``scope.include`` is expanded into
    ``scope.boundaries``, so one source serves both formats.
    """
    return _clean_areas(spec.scope.boundaries)


def _clean_areas(lines: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    areas: list[str] = []
    for line in lines:
        text = str(line).strip()
        if text and text not in seen:
            seen.add(text)
            areas.append(text)
    return areas


def empty_ledger() -> Ledger:
    return {"schema_version": SCHEMA_VERSION, "areas": {}, "cycles": []}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def load_ledger(vault_dir: Path) -> Ledger:
    """Read the ledger; a missing file is an empty one, a broken one raises."""
    path = state_layout.discovery_ledger_path(vault_dir)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return empty_ledger()
    except OSError as exc:
        raise DiscoveryLedgerError(path, str(exc)) from exc
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DiscoveryLedgerError(path, f"not valid JSON ({exc})") from exc
    if not isinstance(doc, dict) or doc.get("schema_version") != SCHEMA_VERSION:
        raise DiscoveryLedgerError(path, f"expected schema_version {SCHEMA_VERSION}")
    areas, cycles = doc.get("areas"), doc.get("cycles")
    if not isinstance(areas, dict) or not all(
        isinstance(row, dict) for row in areas.values()
    ):
        raise DiscoveryLedgerError(path, "'areas' is not an object of objects")
    if not isinstance(cycles, list) or not all(
        isinstance(rec, dict) and _is_int(rec.get("cycle")) for rec in cycles
    ):
        raise DiscoveryLedgerError(path, "'cycles' is not a list of cycle records")
    credit = doc.get("credit")
    if credit is not None and not (
        isinstance(credit, dict)
        and _is_int(credit.get("cycle"))
        and isinstance(credit.get("accrued"), int | float)
        and not isinstance(credit.get("accrued"), bool)
        and _is_int(credit.get("spent"))
    ):
        raise DiscoveryLedgerError(path, "'credit' is not {cycle, accrued, spent}")
    return doc


def _area_rows(cycles: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Recompute every area's figures from the per-cycle records."""
    rows: dict[str, dict[str, Any]] = {}
    for record in sorted(cycles, key=lambda rec: rec["cycle"]):
        reported: dict[str, int] = {}
        for item in record.get("reported") or []:
            area = item.get("area")
            if isinstance(area, str):
                found = item.get("found")
                reported[area] = reported.get(area, 0) + (
                    found if _is_int(found) and found > 0 else 0
                )
        for area in record.get("assigned") or []:
            row = rows.setdefault(
                area,
                {
                    "last_checked_cycle": None,
                    "times_checked": 0,
                    "found_total": 0,
                    "last_found_cycle": None,
                    "times_assigned_not_reported": 0,
                },
            )
            if area not in reported:
                row["times_assigned_not_reported"] += 1
                continue
            row["last_checked_cycle"] = record["cycle"]
            row["times_checked"] += 1
            row["found_total"] += reported[area]
            if reported[area] > 0:
                row["last_found_cycle"] = record["cycle"]
    return rows


def record_cycle(
    vault_dir: Path,
    *,
    cycle: int,
    assigned: list[str],
    reported: list[dict[str, Any]],
    kept: int,
    rerouted: int,
    dropped: list[dict[str, str]],
    topics: list[dict[str, str]] | None = None,
) -> Ledger:
    """Record what ``cycle`` assigned and what the scout reported; atomic.

    Recording the same cycle again replaces that cycle's record. An assigned
    area absent from ``reported`` counts as assigned-not-reported and is not
    marked checked; one reported with ``found: 0`` is checked.
    """
    ledger = load_ledger(vault_dir)
    record = {
        "cycle": cycle,
        "assigned": list(assigned),
        "reported": [dict(item) for item in reported],
        "kept": kept,
        "rerouted": rerouted,
        "dropped": [dict(item) for item in dropped],
    }
    if topics is not None:
        # Optional: which scope area each kept topic came from (spec 088 US1).
        record["topics"] = [dict(item) for item in topics]
    cycles = [rec for rec in ledger["cycles"] if rec["cycle"] != cycle]
    cycles.append(record)
    cycles.sort(key=lambda rec: rec["cycle"])
    # Rows for areas no cycle assigned cannot exist; rows that earlier cycles
    # created are recomputed from those cycles, so none is ever dropped.
    doc: Ledger = {
        "schema_version": SCHEMA_VERSION,
        "areas": _area_rows(cycles),
        "cycles": cycles,
    }
    if "credit" in ledger:
        doc["credit"] = ledger["credit"]
    write_json(state_layout.discovery_ledger_path(vault_dir), doc)
    return doc


def _write_credit(vault_dir: Path, ledger: Ledger, credit: dict[str, Any]) -> None:
    doc = {**ledger, "credit": credit}
    write_json(state_layout.discovery_ledger_path(vault_dir), doc)


def accrue_credit(vault_dir: Path, *, cycle: int, quota: int, share: int) -> float:
    """The discovery credit available to ``cycle``, accrued once per cycle.

    The ledger holds ``credit: {cycle, accrued, spent}``: the balance this
    cycle started with plus its accrual (``accrued``), and what the cycle has
    spent of it (``spent``). The first call for a ``cycle`` adds
    ``share x quota / 100`` to the previous cycle's unspent balance, caps the
    sum at one cycle's ``quota`` so credit cannot pile up, and writes it; any
    later call for the same ``cycle`` (planning may run more than once) returns
    the unspent balance as stored and adds nothing.
    """
    ledger = load_ledger(vault_dir)
    credit = ledger.get("credit")
    if credit is not None and credit["cycle"] == cycle:
        return max(float(credit["accrued"]) - credit["spent"], 0.0)
    carried = (
        max(float(credit["accrued"]) - credit["spent"], 0.0)
        if credit is not None and credit["cycle"] < cycle
        else 0.0
    )
    accrued = min(carried + max(quota, 0) * max(share, 0) / 100, float(max(quota, 0)))
    _write_credit(vault_dir, ledger, {"cycle": cycle, "accrued": accrued, "spent": 0})
    return accrued


def spend_credit(vault_dir: Path, *, cycle: int, spent: int) -> None:
    """Record that ``cycle`` dispatched ``spent`` discovery topics.

    Absolute, not additive: calling it twice for the same cycle with the same
    count leaves the same ledger. A no-op when ``cycle`` has not accrued.
    """
    ledger = load_ledger(vault_dir)
    credit = ledger.get("credit")
    if credit is None or credit["cycle"] != cycle:
        return
    _write_credit(vault_dir, ledger, {**credit, "spent": max(int(spent), 0)})


def choose_areas(ledger: Ledger, areas: list[str], n: int) -> list[str]:
    """Up to ``n`` of ``areas``: never checked first, then oldest check.

    Ties keep spec order. An area the spec no longer lists is not offered (its
    ledger row stays).
    """
    rows = ledger.get("areas", {})

    def last_checked(area: str) -> int | None:
        value = rows.get(area, {}).get("last_checked_cycle")
        return value if _is_int(value) else None

    ranked = sorted(
        enumerate(areas),
        key=lambda pair: (
            last_checked(pair[1]) is not None,
            last_checked(pair[1]) or 0,
            pair[0],
        ),
    )
    return [area for _, area in ranked[: max(n, 0)]]


# ---------------------------------------------------------------------------
# The cycle's assignment, the DG-001 checks and the routing (spec 088 FR-004,
# FR-005). Scratch, not state: the assignment lives with the cycle's files.
# ---------------------------------------------------------------------------


def assignment_path(vault_dir: Path, cycle: int) -> Path:
    return (
        vault_dir
        / "_pipeline"
        / "cycles"
        / f"cycle-{cycle:03d}-discovery-assigned.json"
    )


def window_start(today: date, window_days: int) -> date:
    return today - timedelta(days=max(window_days, 0))


def write_assignment(
    vault_dir: Path, cycle: int, areas: Sequence[str], start: date
) -> None:
    """Remember which areas ``cycle``'s scout was asked about, and the window."""
    write_json(
        assignment_path(vault_dir, cycle),
        {"cycle": cycle, "areas": list(areas), "window_start": start.isoformat()},
    )


def read_assignment(vault_dir: Path, cycle: int) -> dict[str, Any] | None:
    """The cycle's assignment, or ``None`` (no pass this cycle, or unreadable)."""
    try:
        doc = json.loads(assignment_path(vault_dir, cycle).read_text(encoding="utf-8"))
        areas = doc["areas"]
        date.fromisoformat(doc["window_start"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not (isinstance(areas, list) and all(isinstance(a, str) for a in areas)):
        return None
    return {"areas": areas, "window_start": doc["window_start"]}


_ISO_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[T ].*)?$")


@dataclass(frozen=True)
class RowVerdict:
    """DG-001's verdict on one ``topics_found.discovery`` row."""

    row: Any
    ok: bool
    reason: str = ""

    @property
    def title(self) -> str:
        title = self.row.get("title") if isinstance(self.row, dict) else None
        return title.strip() if isinstance(title, str) and title.strip() else "?"


def _check_row(row: Any, assigned: Sequence[str], start: date, today: date) -> str:
    """``""`` when the row passes, else the reason it does not."""
    if not isinstance(row, dict):
        return "row is not an object"
    title = row.get("title")
    if not (isinstance(title, str) and title.strip()):
        return "empty title"
    if row.get("area") not in assigned:
        return "area was not assigned to this cycle"
    urls = row.get("source_urls")
    if not (
        isinstance(urls, list) and any(isinstance(u, str) and u.strip() for u in urls)
    ):
        return "no source"
    published = row.get("published")
    if not isinstance(published, str):
        return "no publication date"
    match = _ISO_DATE.match(published.strip())
    try:
        when = date.fromisoformat(match.group(1)) if match else None
    except ValueError:
        when = None
    if when is None:
        return f"malformed publication date {published!r}"
    if when < start:
        return (
            f"published {when.isoformat()}, before the window opens {start.isoformat()}"
        )
    if when > today:
        return f"published {when.isoformat()}, after today"
    return ""


def evaluate_rows(
    rows: Iterable[Any], assigned: Sequence[str], start: date, today: date
) -> list[RowVerdict]:
    """DG-001: ``area`` assigned (exact text), a source, an ISO ``published``
    date inside ``[start, today]``, a non-empty ``title``. Whether the page
    really carries that date is not something a script can know (spec 088 D2).
    """
    verdicts = []
    for row in rows:
        reason = _check_row(row, assigned, start, today)
        verdicts.append(RowVerdict(row, not reason, reason))
    return verdicts


def _exclusion_keys(exclusions: Iterable[str], prefix: str) -> set[str]:
    from .research_plan import _exclusion_slug

    return {
        _exclusion_slug(e.split(": ", 1)[-1])
        for e in exclusions
        if e.startswith(f"{prefix}:")
    }


@dataclass
class Routing:
    """What :func:`route_rows` did with the rows that passed DG-001."""

    topics: list[dict[str, str]] = dataclasses.field(default_factory=list)
    """``{title, area}`` of each row that is (or stays) a discovery topic."""
    observed: list[str] = dataclasses.field(default_factory=list)
    """Titles of open non-discovery backlog topics observed again."""
    rerouted: int = 0
    """Rows sent to ``new_material`` update entries of existing notes."""
    dropped: list[dict[str, str]] = dataclasses.field(default_factory=list)

    @property
    def kept(self) -> int:
        return len(self.topics) + len(self.observed)


def route_rows(
    vault_dir: Path,
    spec: SpecConfig,
    rows: Iterable[dict[str, Any]],
    *,
    cycle: int,
    exclusions: Sequence[str] = (),
    planned_titles: Iterable[str] = (),
    mode: str = "expand",
) -> Routing:
    """Route each row that passed DG-001 by its normalised filename / title.

    * a note the vault already has -> a ``new_material`` update entry (writer
      ``scout``), counted as re-routed; never a second note;
    * a persistent reject (or an out-of-scope phrase) -> dropped;
    * a topic already in this cycle's plan or this report -> dropped;
    * an open backlog topic that is not a discovery topic -> observed again, no
      duplicate and no discovery slot (the planner already offers it);
    * otherwise a discovery topic: recorded in the backlog (origin
      ``discovery``) and offered to the plan by :func:`plan_discovery_topics`.
      Under ``research_mode: refresh`` such a row is dropped instead.

    The match key is the row's proposed filename, else its title, as the scout
    merge uses; the title is tried too, so a differently-named file for a
    covered title still routes to its note.
    """
    from . import currency
    from .research_plan import _exclusion_slug

    notes = currency._corpus_notes(vault_dir, spec)
    rejected = _exclusion_keys(exclusions, "persistent-rejects")
    out_of_scope = _exclusion_keys(exclusions, "out-of-scope")
    rejected |= {
        _exclusion_slug(t) for t in rejects.persistent_reject_titles(vault_dir)
    }
    planned = {t.strip().casefold() for t in planned_titles}
    seen: set[str] = set()
    routing = Routing()
    rerouted_rows: list[dict[str, Any]] = []
    observe: list[tuple[dict[str, Any], str]] = []  # (row, "topic" | "again")

    for row in rows:
        title = " ".join(str(row["title"]).split())
        keys = [
            k
            for k in (
                _exclusion_slug(str(row.get("proposed_filename") or "")),
                _exclusion_slug(title),
            )
            if k
        ]
        urls = [str(u).strip() for u in row["source_urls"] if str(u).strip()]
        note_key = next((k for k in keys if k in notes), None)
        if note_key is not None:
            rerouted_rows.append({"key": note_key, "source_urls": urls})
            routing.rerouted += 1
            continue
        reason = ""
        if any(k in rejected for k in keys):
            reason = "persistent reject"
        elif any(k in out_of_scope for k in keys):
            reason = "out of scope"
        elif title.casefold() in planned:
            reason = "already in this cycle's plan"
        elif keys[-1] in seen:
            reason = "duplicate of another row in this report"
        elif mode == "refresh":
            reason = "research_mode refresh: a discovery row may only update a note"
        else:
            state = backlog.topic_state(vault_dir, title)
            if state is not None and state[1] == "dropped":
                reason = "dropped from the backlog by the operator"
        if reason:
            routing.dropped.append({"title": title, "reason": reason})
            continue
        seen.update(keys)
        state = backlog.topic_state(vault_dir, title)
        if state is not None and state[0] != "discovery" and state[1] == "open":
            observe.append((row, "again"))
            routing.observed.append(title)
        else:
            observe.append((row, "topic"))
            routing.topics.append({"title": title, "area": str(row["area"])})

    if rerouted_rows:
        currency.record_new_material(vault_dir, spec, rerouted_rows, cycle=cycle)
    if observe:

        def write(tx: backlog.Transaction) -> None:
            for row, kind in observe:
                title = " ".join(str(row["title"]).split())
                if kind == "again":
                    tx.observe_topic(cycle=cycle, title=title, origin="discovery")
                    continue
                category = row.get("coverage_category")
                filename = row.get("proposed_filename")
                why = row.get("why_new")
                tx.observe_topic(
                    cycle=cycle,
                    title=title,
                    origin="discovery",
                    detail=why.strip()
                    if isinstance(why, str) and why.strip()
                    else None,
                    scope_area=str(row["area"]),
                    source_urls=[
                        str(u).strip() for u in row["source_urls"] if str(u).strip()
                    ],
                    category=category
                    if isinstance(category, str) and category
                    else None,
                    proposed_filename=(
                        filename if isinstance(filename, str) and filename else None
                    ),
                )

        if not backlog.update(vault_dir, "scout", write):
            _LOG.warning("[discovery] the backlog could not be written")
    return routing


def plan_discovery_topics(
    vault_dir: Path, spec: SpecConfig, plan: Any, *, cycle: int
) -> tuple[Any, int]:
    """Merge up to the discovery share's worth of open discovery topics into the
    plan's queue, ahead of every other topic (spec 088 FR-007).

    Candidates are the backlog's open discovery topics, oldest first, so the
    ones an earlier cycle could not hold come before fresh rows. How many fit is
    ``split_quota``'s ``discovery_n`` over the carried credit; the credit is
    accrued once per ``cycle`` and the count dispatched is recorded as spent
    (absolute, so a re-run adds nothing). Topics a note now covers, or that are
    already in the queue, are skipped. Returns ``(plan, merged_count)``.
    """
    from . import currency
    from .research_plan import (
        PrioritizedTopic,
        _exclusion_slug,
        _pick_orphan_category,
        is_placeholder_topic,
    )

    already = [t for t in plan.priority_queue if t.provenance == DISCOVERY_PROVENANCE]
    queued = {t.title.strip().casefold() for t in plan.priority_queue}
    notes = currency._corpus_notes(vault_dir, spec)
    refs = [
        r
        for r in backlog.discovery_topics(vault_dir)
        if r.title.strip().casefold() not in queued
        and not any(
            k in notes
            for k in (_exclusion_slug(r.proposed_filename), _exclusion_slug(r.title))
            if k
        )
    ]
    # The credit accrues every cycle the pass runs, whether or not a topic waits.
    credit = accrue_credit(
        vault_dir,
        cycle=cycle,
        quota=int(plan.cycle_quota),
        share=discovery_share(vault_dir),
    )
    if not refs and not already:
        return plan, 0
    _new, _upd, count = currency.split_quota(
        int(plan.cycle_quota),
        currency.cycle_split_shares(vault_dir),
        mode=currency.cycle_mode(vault_dir, spec),
        new_available=sum(
            1
            for t in plan.priority_queue
            if not is_placeholder_topic(t) and t.provenance != DISCOVERY_PROVENANCE
        ),
        updates_available=len(plan.update_queue),
        discovery_available=len(refs),
        discovery_credit=credit,
    )
    spend_credit(vault_dir, cycle=cycle, spent=len(already) + count)
    if count <= 0:
        return plan, 0
    categories = {c.name for c in plan.coverage_state}
    merged = []
    for ref in refs[:count]:
        category = (
            ref.category
            if ref.category in categories
            else _pick_orphan_category(plan.coverage_state)
        )
        merged.append(
            PrioritizedTopic(
                title=ref.title,
                category=category,
                priority_score=1.0,
                source_hints=list(ref.source_urls),
                provenance=DISCOVERY_PROVENANCE,
            )
        )
    return (
        dataclasses.replace(plan, priority_queue=merged + list(plan.priority_queue)),
        len(merged),
    )


# ---------------------------------------------------------------------------
# What the reader sees (spec 088 FR-010): the last cycle's line, and health.
# ---------------------------------------------------------------------------


def cycle_summary(vault_dir: Path, cycle: int) -> dict[str, Any] | None:
    """What ``cycle``'s pass did, from the ledger; ``None`` when it ran no pass
    (or the ledger is unreadable: a reader never fails on it).

    ``checked`` are the assigned areas the scout reported on (found or not),
    ``not_reported`` the assigned ones it did not; ``kept``, ``rerouted`` and
    ``dropped`` count rows.
    """
    try:
        ledger = load_ledger(vault_dir)
    except DiscoveryLedgerError:
        return None
    record = next((r for r in ledger["cycles"] if r["cycle"] == cycle), None)
    if record is None:
        return None
    assigned = [a for a in record.get("assigned") or [] if isinstance(a, str)]
    reported = {
        r.get("area") for r in record.get("reported") or [] if isinstance(r, dict)
    }
    return {
        "cycle": cycle,
        "checked": [a for a in assigned if a in reported],
        "not_reported": [a for a in assigned if a not in reported],
        "kept": int(record.get("kept") or 0),
        "rerouted": int(record.get("rerouted") or 0),
        "dropped": len(record.get("dropped") or []),
    }


def summary_line(info: dict[str, Any]) -> str:
    """One line for the cycle summary and ``./vault status``."""
    checked = info["checked"]
    line = (
        f"discovery (cycle {info['cycle']}): checked {len(checked)} scope area(s)"
        + (f" [{'; '.join(checked)}]" if checked else "")
        + f", kept {info['kept']}, re-routed to updates {info['rerouted']}, "
        f"dropped {info['dropped']}"
    )
    if info["not_reported"]:
        line += f"; not reported: {'; '.join(info['not_reported'])}"
    return line


@dataclass(frozen=True)
class DiscoveryHealth:
    """Scope areas the pass has not looked at (read-only; spec 088 FR-010)."""

    cycle: int
    never_checked: tuple[str, ...]
    stale: tuple[tuple[str, int], ...]
    """``(area, cycles since it was last checked)``."""
    threshold: int
    """``2 x ceil(areas / areas_per_cycle)``: more cycles than this is stale."""
    areas: int


def health(vault_dir: Path) -> DiscoveryHealth | None:
    """Areas never checked, and areas not checked for more than
    ``2 x ceil(areas / areas_per_cycle)`` cycles.

    ``None`` (nothing to show) when the pass is off, the spec has no scope
    areas, no cycle has run, or the ledger cannot be read.
    """
    import math

    from ..spec.parsed import ParsedSpecError, load_parsed_spec
    from . import cycle_ledger

    if discovery_share(vault_dir) <= 0:
        return None
    try:
        scope = load_parsed_spec(vault_dir).get("scope") or {}
        areas = _clean_areas(scope.get("boundaries") or [])
        ledger = load_ledger(vault_dir)
    except (ParsedSpecError, DiscoveryLedgerError, AttributeError):
        return None
    known = [r["cycle"] for r in ledger["cycles"]]
    latest = max(
        [*known, cycle_ledger.highest_completed_cycle(vault_dir) or 0], default=0
    )
    if not areas or latest < 1:
        return None
    threshold = 2 * math.ceil(
        areas.__len__() / discovery_settings(vault_dir).areas_per_cycle
    )
    never: list[str] = []
    stale: list[tuple[str, int]] = []
    for area in areas:
        last = ledger["areas"].get(area, {}).get("last_checked_cycle")
        if not _is_int(last):
            never.append(area)
        elif latest - last > threshold:
            stale.append((area, latest - last))
    return DiscoveryHealth(latest, tuple(never), tuple(stale), threshold, len(areas))
