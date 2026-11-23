"""The research backlog as structured state (spec 084).

One module owns ``state_layout.research_backlog_path`` (the JSON store) and the
Markdown view rendered from it (``_pipeline/research-backlog.md``). Writers
never hold a mutable entry: they pass *observations* and the module applies
them under the field-ownership rule (FR-007). Readers get immutable query
results. Nothing here parses the view back.

Failure policy (spec § Edge Cases): a malformed store, or one whose
``schema_version`` has a newer major than this build knows, is never written.
Writers skip and log ``ERROR`` naming the file; readers return nothing (or, for
a newer major, what they can validate) and log ``WARNING``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

from . import state_layout
from .atomic_write import write_bytes, write_text

_LOG = logging.getLogger(__name__)

SCHEMA_MAJOR = 1
SCHEMA_MINOR = 0
SCHEMA_VERSION = f"{SCHEMA_MAJOR}.{SCHEMA_MINOR}"

WRITERS = ("harvest", "propose", "quarantine", "regrade", "migration")
ORIGINS = ("harvest", "researcher", "proposal", "quarantine", "operator", "migrated")
STATUSES = ("open", "resolved", "dropped")
KINDS = ("rewrite", "retry")

# The view and its overwritten copy are not state (083 does not register
# them), so this module spells them.
_VIEW_REL = "_pipeline/research-backlog.md"
_OVERWRITTEN_REL = "_pipeline/research-backlog.md.overwritten"
_FOOTER_PREFIX = "<!-- research-backlog-view sha256="
_FOOTER_RE = re.compile(r"<!-- research-backlog-view sha256=([0-9a-f]{64}) -->\n")

_ID_RE = re.compile(r"^(topic|quarantine|migrated):.+$")
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)$")
_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")

# Fields each writer may set on an entry (FR-007), besides ``updated``.
_OWNED_TOPIC_FIELDS: dict[str, frozenset[str]] = {
    "harvest": frozenset({"citation_count", "cited_from", "detail"}),
    "propose": frozenset({"detail", "relation", "parent_note", "scope_warn"}),
}
_TOPIC_ORIGINS: dict[str, frozenset[str]] = {
    "harvest": frozenset({"harvest", "researcher"}),
    "propose": frozenset({"proposal"}),
}


class BacklogUnavailable(Exception):
    """Internal: the store cannot be used (malformed, read-only or unconverted)."""


class TitleRef(NamedTuple):
    """One entry's normalised key and display title (any status)."""

    key: str
    title: str


@dataclass(frozen=True)
class TopicRef:
    """An immutable view of one queued topic for the planner."""

    id: str
    key: str
    title: str
    origin: str
    citation_count: int
    cited_from: tuple[str, ...]
    first_seen_cycle: int | None
    last_seen_cycle: int | None
    seen_cycles: int
    detail: str


# ---------------------------------------------------------------------------
# Paths and identity
# ---------------------------------------------------------------------------


def store_path(vault_dir: Path) -> Path:
    return state_layout.research_backlog_path(vault_dir)


def view_path(vault_dir: Path) -> Path:
    return vault_dir / _VIEW_REL


def overwritten_path(vault_dir: Path) -> Path:
    return vault_dir / _OVERWRITTEN_REL


def title_key(title: str) -> str:
    """Whitespace collapsed, stripped, case-folded (research R6)."""
    return " ".join(title.split()).casefold()


def topic_id(title: str) -> str:
    return f"topic:{title_key(title)}"


def quarantine_id(stem: str) -> str:
    return f"quarantine:{stem}"


def migrated_id(number: int) -> str:
    return f"migrated:{number:04d}"


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def is_unconverted(vault_dir: Path) -> bool:
    """Store absent while a Markdown backlog without the view footer exists."""
    if store_path(vault_dir).exists():
        return False
    view = view_path(vault_dir)
    if not view.is_file():
        return False
    try:
        return _split_footer(view.read_bytes()) is None
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Validation (hand-rolled mirror of contracts/research-backlog.schema.json)
# ---------------------------------------------------------------------------


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_version(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, str):
        return None
    match = _VERSION_RE.match(value)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def _validate_entry(entry: Any, index: int, *, lenient_enums: bool) -> str | None:
    where = f"entries[{index}]"
    if not isinstance(entry, dict):
        return f"{where} is not an object"
    for name in ("title", "origin", "status"):
        if name not in entry:
            return f"{where} is missing required field {name!r}"
    title = entry["title"]
    if not isinstance(title, str) or not title:
        return f"{where}.title must be a non-empty string"
    if "id" in entry:
        ident = entry["id"]
        if not isinstance(ident, str) or not _ID_RE.match(ident):
            return f"{where}.id {ident!r} does not match topic:|quarantine:|migrated:"
    if entry["origin"] not in ORIGINS and not lenient_enums:
        return f"{where}.origin {entry['origin']!r} is not a known origin"
    if not isinstance(entry["origin"], str):
        return f"{where}.origin must be a string"
    if entry["status"] not in STATUSES:
        return f"{where}.status {entry['status']!r} is not open|resolved|dropped"
    if "status_written" in entry and entry["status_written"] not in STATUSES:
        return f"{where}.status_written {entry['status_written']!r} is invalid"
    if "status_by" in entry and not isinstance(entry["status_by"], str):
        return f"{where}.status_by must be a string"
    for name in ("added", "updated"):
        if name in entry and not (
            isinstance(entry[name], str) and _DATE_RE.match(entry[name])
        ):
            return f"{where}.{name} must be YYYY-MM-DD"
    for name in ("first_seen_cycle", "last_seen_cycle"):
        if name in entry:
            value = entry[name]
            if value is not None and not (_is_int(value) and value >= 1):
                return f"{where}.{name} must be an integer >= 1 or null"
    for name in ("seen_cycles", "citation_count"):
        if name in entry and not (_is_int(entry[name]) and entry[name] >= 0):
            return f"{where}.{name} must be an integer >= 0"
    if "cited_from" in entry and not (
        isinstance(entry["cited_from"], list)
        and all(isinstance(p, str) for p in entry["cited_from"])
    ):
        return f"{where}.cited_from must be an array of strings"
    for name in ("detail", "relation", "parent_note", "stem"):
        if name in entry and not isinstance(entry[name], str):
            return f"{where}.{name} must be a string"
    if "scope_warn" in entry and not isinstance(entry["scope_warn"], bool):
        return f"{where}.scope_warn must be a boolean"
    if "kind" in entry and entry["kind"] not in KINDS:
        return f"{where}.kind {entry['kind']!r} is not rewrite|retry"
    if entry["origin"] == "quarantine":
        for name in ("stem", "kind"):
            if name not in entry:
                return f"{where} (quarantine) is missing required field {name!r}"
    return None


def _assign_missing_ids(entries: list[dict[str, Any]]) -> bool:
    """Give an operator-added entry without ``id`` one (spec § Edge Cases)."""
    changed = False
    used = {e["id"] for e in entries if "id" in e}
    next_number = 1 + max(
        (int(i.split(":", 1)[1]) for i in used if re.fullmatch(r"migrated:\d+", i)),
        default=0,
    )
    for entry in entries:
        if "id" in entry:
            continue
        if entry["origin"] == "quarantine":
            entry["id"] = quarantine_id(entry["stem"])
        elif entry["origin"] == "migrated":
            entry["id"] = migrated_id(next_number)
            next_number += 1
        else:
            entry["id"] = topic_id(entry["title"])
        changed = True
    return changed


def _validate_store(data: Any) -> tuple[str | None, bool]:
    """Return (error, read_only). ``read_only`` means a newer major version."""
    if not isinstance(data, dict):
        return "top level is not an object", False
    if "schema_version" not in data or "entries" not in data:
        return "missing required field 'schema_version' or 'entries'", False
    parsed = _parse_version(data["schema_version"])
    if parsed is None:
        return f"schema_version {data['schema_version']!r} is not MAJOR.MINOR", False
    major, minor = parsed
    if major < SCHEMA_MAJOR:
        return f"schema_version {data['schema_version']!r} is not supported", False
    read_only = major > SCHEMA_MAJOR
    entries = data["entries"]
    if not isinstance(entries, list):
        return "entries is not an array", read_only
    lenient = read_only or minor > SCHEMA_MINOR
    for index, entry in enumerate(entries):
        error = _validate_entry(entry, index, lenient_enums=lenient)
        if error:
            return error, read_only
    # Ids unique, counting ids the module would assign.
    probe = [dict(e) for e in entries]
    _assign_missing_ids(probe)
    seen: set[str] = set()
    for entry in probe:
        if entry["id"] in seen:
            return f"duplicate id {entry['id']!r}", read_only
        seen.add(entry["id"])
    return None, read_only


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------


@dataclass
class _Loaded:
    path: Path
    data: dict[str, Any]
    read_only: bool

    @property
    def entries(self) -> list[dict[str, Any]]:
        return self.data["entries"]


def _empty_data() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "entries": []}


def _load(vault_dir: Path) -> _Loaded:
    """Read and validate the store; an absent store is an empty one.

    Raises ``BacklogUnavailable`` with a human reason when it cannot be used.
    """
    path = store_path(vault_dir)
    if not path.exists():
        if is_unconverted(vault_dir):
            raise BacklogUnavailable(
                f"{path} is absent while a legacy Markdown backlog exists "
                "(unconverted vault; run the layout migration)"
            )
        return _Loaded(path, _empty_data(), False)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BacklogUnavailable(f"{path} is not valid JSON: {exc}") from exc
    error, read_only = _validate_store(data)
    if error:
        raise BacklogUnavailable(f"{path} is malformed: {error}")
    return _Loaded(path, data, read_only)


def _normalize(entries: list[dict[str, Any]]) -> None:
    """Assign missing ids and record operator status changes (research R5)."""
    _assign_missing_ids(entries)
    for entry in entries:
        if entry.get("status") != entry.get("status_written"):
            entry["status_by"] = "operator"
            entry["status_written"] = entry["status"]


def _dumps(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _read_for_query(vault_dir: Path) -> list[dict[str, Any]]:
    """Normalised entries for a reader; ``[]`` plus a WARNING when unusable."""
    try:
        loaded = _load(vault_dir)
    except BacklogUnavailable as exc:
        _LOG.warning("research backlog unreadable, returning no entries: %s", exc)
        return []
    _normalize(loaded.entries)
    return loaded.entries


# ---------------------------------------------------------------------------
# The transaction
# ---------------------------------------------------------------------------


def _check_writer(writer: str) -> None:
    if writer not in WRITERS:
        raise ValueError(
            f"unknown backlog writer {writer!r}; expected one of {WRITERS}"
        )


class Transaction:
    """Observations applied inside ``update``. Holds no public entry access."""

    def __init__(self, writer: str, entries: list[dict[str, Any]]) -> None:
        _check_writer(writer)
        self._writer = writer
        self._entries = entries
        self._today = _today()

    # -- helpers ----------------------------------------------------------

    def _find(self, entry_id: str) -> dict[str, Any] | None:
        for entry in self._entries:
            if entry["id"] == entry_id:
                return entry
        return None

    def _stamp_seen(self, entry: dict[str, Any], cycle: int | None) -> None:
        if cycle is None:
            return
        last = entry.get("last_seen_cycle")
        if last != cycle:
            entry["seen_cycles"] = entry.get("seen_cycles", 0) + 1
        if last is None or cycle > last:
            entry["last_seen_cycle"] = cycle

    def _set(self, entry: dict[str, Any], name: str, value: Any) -> None:
        if value is not None:
            entry[name] = value

    def _resolve(self, entry: dict[str, Any]) -> bool:
        if entry["status"] != "open" or entry.get("status_by") == "operator":
            return False
        entry["status"] = "resolved"
        entry["status_by"] = self._writer
        entry["status_written"] = "resolved"
        entry["updated"] = self._today
        return True

    def _reopen(self, entry: dict[str, Any]) -> bool:
        """Reopen an entry a writer resolved, because it was observed again.

        A note quarantined a second time, or a topic whose note was removed,
        must come back (spec 084 FR-007). An operator's status is never
        touched, and ``dropped`` is an operator's word by definition.
        """
        if entry["status"] != "resolved" or entry.get("status_by") == "operator":
            return False
        entry["status"] = "open"
        entry["status_by"] = self._writer
        entry["status_written"] = "open"
        return True

    # -- observations -----------------------------------------------------

    def observe_topic(
        self,
        *,
        cycle: int,
        title: str,
        origin: str,
        citation_count: int | None = None,
        cited_from: Iterable[str] | None = None,
        detail: str | None = None,
        relation: str | None = None,
        parent_note: str | None = None,
        scope_warn: bool | None = None,
    ) -> None:
        """Upsert one ``topic:`` entry. Existing entries get observation fields only."""
        if self._writer not in _TOPIC_ORIGINS:
            raise ValueError(f"writer {self._writer!r} does not observe topics")
        if origin not in _TOPIC_ORIGINS[self._writer]:
            raise ValueError(f"writer {self._writer!r} cannot create origin {origin!r}")
        if not isinstance(cycle, int) or isinstance(cycle, bool) or cycle < 1:
            raise ValueError(f"cycle must be an integer >= 1, got {cycle!r}")
        display = " ".join(title.split())
        if not display:
            raise ValueError("topic title is empty")
        fields: dict[str, Any] = {
            "citation_count": citation_count,
            "cited_from": None if cited_from is None else list(cited_from),
            "detail": detail,
            "relation": relation,
            "parent_note": parent_note,
            "scope_warn": scope_warn,
        }
        owned = _OWNED_TOPIC_FIELDS[self._writer]
        foreign = sorted(
            k for k, v in fields.items() if v is not None and k not in owned
        )
        if foreign:
            raise ValueError(
                f"writer {self._writer!r} does not own field(s) {', '.join(foreign)}"
            )
        entry = self._find(topic_id(display))
        if entry is None:
            entry = {
                "id": topic_id(display),
                "title": display,
                "origin": origin,
                "status": "open",
                "status_by": self._writer,
                "status_written": "open",
                "added": self._today,
                "updated": self._today,
                "first_seen_cycle": cycle,
                "last_seen_cycle": cycle,
                "seen_cycles": 1,
            }
            self._entries.append(entry)
        else:
            self._stamp_seen(entry, cycle)
            self._reopen(entry)
            entry["updated"] = self._today
        for name, value in fields.items():
            if value is None:
                continue
            # An operator's own description is not replaced by a writer's.
            if name == "detail" and entry["origin"] == "operator" and entry.get(name):
                continue
            entry[name] = value

    def observe_quarantine(
        self,
        *,
        stem: str,
        kind: str,
        detail: str | None = None,
        cycle: int | None = None,
    ) -> None:
        """Upsert one ``quarantine:<stem>`` entry (kind and detail are the latest)."""
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
        if not stem:
            raise ValueError("quarantine stem is empty")
        entry = self._find(quarantine_id(stem))
        if entry is None:
            entry = {
                "id": quarantine_id(stem),
                "title": stem,
                "origin": "quarantine",
                "status": "open",
                "status_by": self._writer,
                "status_written": "open",
                "added": self._today,
                "updated": self._today,
                "first_seen_cycle": cycle,
                "last_seen_cycle": cycle,
                "seen_cycles": 0 if cycle is None else 1,
                "stem": stem,
                "kind": kind,
            }
            self._entries.append(entry)
        else:
            self._stamp_seen(entry, cycle)
            self._reopen(entry)
            entry["updated"] = self._today
            entry["stem"] = stem
            entry["kind"] = kind
        self._set(entry, "detail", detail)

    def resolve_covered(self, existing_stems: Iterable[str]) -> int:
        """Resolve open harvest/researcher topics whose note now exists."""
        stems = {title_key(s) for s in existing_stems}
        count = 0
        for entry in self._entries:
            if entry["origin"] not in ("harvest", "researcher"):
                continue
            if not entry["id"].startswith("topic:"):
                continue
            if title_key(entry["title"]) in stems and self._resolve(entry):
                count += 1
        return count

    def resolve_quarantine(self, live_stems: Iterable[str]) -> int:
        """Resolve open quarantine entries whose quarantine file is gone."""
        live = set(live_stems)
        count = 0
        for entry in self._entries:
            if entry["origin"] != "quarantine":
                continue
            if entry.get("stem") not in live and self._resolve(entry):
                count += 1
        return count

    def resolve_quarantine_stem(self, stem: str) -> int:
        """Resolve exactly the open quarantine entries whose ``stem`` is ``stem``."""
        count = 0
        for entry in self._entries:
            if entry["origin"] == "quarantine" and entry.get("stem") == stem:
                if self._resolve(entry):
                    count += 1
        return count


def update(vault_dir: Path, writer: str, fn: Callable[[Transaction], None]) -> bool:
    """Read-modify-write the store under one writer's field ownership.

    ``fn`` receives a ``Transaction``; if it raises, nothing is written. The
    store is saved atomically only when it changed, then the view is rendered.
    Returns ``True`` when the update applied (even if nothing changed) and
    ``False`` when it was skipped because the store is unusable, with an
    ``ERROR`` logged naming the file.
    """
    _check_writer(writer)
    try:
        loaded = _load(vault_dir)
        if loaded.read_only:
            raise BacklogUnavailable(
                f"{loaded.path} has a newer major schema_version "
                f"{loaded.data['schema_version']!r}; read-only for this build"
            )
    except BacklogUnavailable as exc:
        _LOG.error("research backlog not written: %s", exc)
        return False
    before = _dumps(loaded.data) if loaded.path.exists() else None
    _normalize(loaded.entries)
    fn(Transaction(writer, loaded.entries))
    after = _dumps(loaded.data)
    if after != before:
        write_text(loaded.path, after)
    _render_view(vault_dir, loaded.entries)
    return True


def install_store(
    vault_dir: Path, entries: list[dict[str, Any]], *, archive: Path
) -> None:
    """Write a converted store and render its view (the conversion step only).

    Unlike :func:`update` this accepts an *unconverted* vault: it is how one
    becomes converted. It refuses to overwrite a store, validates the entries
    against the same rules as a load, and requires ``archive`` to hold the
    legacy Markdown byte for byte before that file is replaced by the view.

    Raises ``FileExistsError`` (store present), ``ValueError`` (invalid
    entries) or ``FileNotFoundError``/``ValueError`` (archive missing or not
    equal to the legacy file).
    """
    path = store_path(vault_dir)
    if path.exists():
        raise FileExistsError(f"{path} already exists; nothing to convert")
    data = {"schema_version": SCHEMA_VERSION, "entries": entries}
    error, _ = _validate_store(data)
    if error:
        raise ValueError(f"converted backlog is invalid: {error}")
    view = view_path(vault_dir)
    if view.is_file() and _split_footer(view.read_bytes()) is None:
        if not archive.is_file() or archive.read_bytes() != view.read_bytes():
            raise ValueError(
                f"{archive} must hold the legacy backlog byte for byte before "
                f"{view} is replaced by the view"
            )
        view.unlink()
    _normalize(entries)
    write_text(path, _dumps(data))
    _render_view(vault_dir, entries)


# ---------------------------------------------------------------------------
# Module-level observations (one transaction each)
# ---------------------------------------------------------------------------


def create_empty(vault_dir: Path) -> bool:
    """Seed an empty store and its view; a no-op when the store exists."""
    if store_path(vault_dir).exists():
        return False
    return update(vault_dir, "migration", lambda tx: None)


def observe_topic(
    vault_dir: Path,
    writer: str,
    *,
    cycle: int,
    title: str,
    origin: str,
    citation_count: int | None = None,
    cited_from: Iterable[str] | None = None,
    detail: str | None = None,
    relation: str | None = None,
    parent_note: str | None = None,
    scope_warn: bool | None = None,
) -> bool:
    return update(
        vault_dir,
        writer,
        lambda tx: tx.observe_topic(
            cycle=cycle,
            title=title,
            origin=origin,
            citation_count=citation_count,
            cited_from=cited_from,
            detail=detail,
            relation=relation,
            parent_note=parent_note,
            scope_warn=scope_warn,
        ),
    )


def observe_quarantine(
    vault_dir: Path,
    *,
    stem: str,
    kind: str,
    detail: str | None = None,
    cycle: int | None = None,
) -> bool:
    return update(
        vault_dir,
        "quarantine",
        lambda tx: tx.observe_quarantine(
            stem=stem, kind=kind, detail=detail, cycle=cycle
        ),
    )


def resolve_covered(vault_dir: Path, existing_stems: Iterable[str]) -> bool:
    stems = list(existing_stems)
    return update(vault_dir, "harvest", lambda tx: tx.resolve_covered(stems))


def resolve_quarantine(vault_dir: Path, live_stems: Iterable[str]) -> bool:
    stems = list(live_stems)
    return update(vault_dir, "quarantine", lambda tx: tx.resolve_quarantine(stems))


def resolve_quarantine_stem(vault_dir: Path, stem: str) -> bool:
    return update(vault_dir, "regrade", lambda tx: tx.resolve_quarantine_stem(stem))


# ---------------------------------------------------------------------------
# Queries (immutable results)
# ---------------------------------------------------------------------------


def _first_seen_sort_key(item: tuple[int, dict[str, Any]]) -> tuple[int, int, int]:
    index, entry = item
    first = entry.get("first_seen_cycle")
    return (1 if first is None else 0, first or 0, index)


def planner_topics(vault_dir: Path) -> list[TopicRef]:
    """Open topics worth queueing: operator-owned or cited (research R7)."""
    queued = []
    for index, entry in enumerate(_read_for_query(vault_dir)):
        if entry["status"] != "open":
            continue
        if entry["origin"] in ("quarantine", "migrated"):
            continue
        if not entry["id"].startswith("topic:"):
            continue
        cited = entry.get("citation_count", 0) >= 1
        owned = entry["origin"] == "operator" or entry.get("status_by") == "operator"
        if owned or cited:
            queued.append((index, entry))
    queued.sort(key=_first_seen_sort_key)
    return [
        TopicRef(
            id=e["id"],
            key=title_key(e["title"]),
            title=e["title"],
            origin=e["origin"],
            citation_count=e.get("citation_count", 0),
            cited_from=tuple(e.get("cited_from", ())),
            first_seen_cycle=e.get("first_seen_cycle"),
            last_seen_cycle=e.get("last_seen_cycle"),
            seen_cycles=e.get("seen_cycles", 0),
            detail=e.get("detail", ""),
        )
        for _, e in queued
    ]


def all_titles(vault_dir: Path) -> list[TitleRef]:
    """Every entry's key and display title, whatever its status (FR-013)."""
    return [
        TitleRef(title_key(e["title"]), e["title"]) for e in _read_for_query(vault_dir)
    ]


# ---------------------------------------------------------------------------
# The view (contracts/backlog-view.contract.md)
# ---------------------------------------------------------------------------


def _one_line(text: str) -> str:
    return " ".join(str(text).split())


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _topic_line_harvest(entry: dict[str, Any]) -> str:
    count = entry.get("citation_count", 0)
    line = f"- **{_one_line(entry['title'])}** — cited by {count} note(s)"
    paths = list(entry.get("cited_from", []))
    if paths:
        shown = ", ".join(f"`{p}`" for p in paths[:3])
        line += f": {shown}"
        if len(paths) > 3:
            line += f" (+{len(paths) - 3} more)"
    first = entry.get("first_seen_cycle")
    if first is not None:
        last = entry.get("last_seen_cycle", first)
        seen = entry.get("seen_cycles", 1)
        line += (
            f" · first seen cycle {first}, last seen cycle {last}"
            f" ({_plural(seen, 'cycle')})"
        )
    return line


def _topic_line_researcher(entry: dict[str, Any]) -> str:
    detail = _one_line(entry.get("detail", "")) or "flagged by the researcher"
    line = f"- **{_one_line(entry['title'])}** — {detail}"
    first = entry.get("first_seen_cycle")
    if first is not None:
        line += f" · first seen cycle {first}"
    return line


def _quarantine_line(entry: dict[str, Any]) -> str:
    action = (
        "retry the refresh; previous content restored"
        if entry.get("kind") == "retry"
        else "rewrite the quarantined note"
    )
    line = f"- **{_one_line(entry.get('stem', entry['title']))}** — {action}"
    detail = _one_line(entry.get("detail", ""))
    return f"{line} ({detail})" if detail else line


def _operator_line(entry: dict[str, Any]) -> str:
    line = f"- **{_one_line(entry['title'])}**"
    detail = _one_line(entry.get("detail", ""))
    return f"{line} — {detail}" if detail else line


def _proposal_line(entry: dict[str, Any]) -> str:
    line = f"- **{_one_line(entry['title'])}**"
    if entry.get("scope_warn"):
        line += " ⚠️"
    relation = _one_line(entry.get("relation", ""))
    parent = _one_line(entry.get("parent_note", ""))
    if relation and parent:
        line += f" ({relation} of [[{parent}]])"
    elif parent:
        line += f" (of [[{parent}]])"
    detail = _one_line(entry.get("detail", ""))
    return f"{line} — {detail}" if detail else line


def _migrated_line(entry: dict[str, Any]) -> str:
    return f"- {entry.get('detail', entry['title']).replace(chr(10), ' ')}"


def _coverage_lines(vault_dir: Path) -> list[str]:
    # Local import: coverage pulls in the spec and vault packages.
    from .coverage import load_targets

    try:
        targets = load_targets(vault_dir)
    except Exception:  # noqa: BLE001 - missing/unreadable file omits the section
        return []
    lines = []
    for category in targets.categories:
        if category.is_met:
            continue
        flag = "required" if category.required else "optional"
        lines.append(
            f"- `{category.name}` [{category.note_type}] — "
            f"{category.met_count}/{category.target_count} ({flag})"
        )
    return lines


def _render_text(vault_dir: Path, entries: list[dict[str, Any]]) -> str:
    open_entries = [(i, e) for i, e in enumerate(entries) if e["status"] == "open"]
    open_entries.sort(key=_first_seen_sort_key)
    sections: dict[str, list[str]] = {
        "harvest": [],
        "researcher": [],
        "quarantine": [],
        "operator": [],
        "proposal": [],
        "migrated": [],
    }
    for _, entry in open_entries:
        origin = entry["origin"]
        topic = entry["id"].startswith("topic:")
        if topic and entry.get("citation_count", 0) >= 1:
            sections["harvest"].append(_topic_line_harvest(entry))
        elif origin == "harvest":
            sections["harvest"].append(_topic_line_harvest(entry))
        elif origin == "researcher":
            sections["researcher"].append(_topic_line_researcher(entry))
        elif origin == "quarantine":
            sections["quarantine"].append(_quarantine_line(entry))
        elif origin == "operator":
            sections["operator"].append(_operator_line(entry))
        elif origin == "proposal":
            sections["proposal"].append(_proposal_line(entry))
        elif origin == "migrated":
            sections["migrated"].append(_migrated_line(entry))
    headings = (
        ("harvest", "Follow-on topics (harvest)"),
        ("researcher", "Flagged by the researcher"),
        ("quarantine", "Quarantined notes"),
        ("operator", "Added by the operator"),
        ("proposal", "Proposed tangents (advisory)"),
        ("migrated", "Carried over from the old backlog"),
    )
    store_rel = state_layout.research_backlog_path(Path()).as_posix()
    blocks = [
        "# Research Backlog\n\n"
        f"> Generated from `{store_rel}` — edit that file,\n"
        "> not this one. A change made here is overwritten on the next write; the\n"
        f"> overwritten text is kept once at `{_OVERWRITTEN_REL}`.\n"
    ]
    for key, heading in headings:
        if sections[key]:
            blocks.append(f"## {heading}\n\n" + "\n".join(sections[key]) + "\n")
    coverage = _coverage_lines(vault_dir)
    if coverage:
        blocks.append("## Unmet coverage categories\n\n" + "\n".join(coverage) + "\n")
    resolved = sum(1 for e in entries if e["status"] == "resolved")
    dropped = sum(1 for e in entries if e["status"] == "dropped")
    blocks.append(
        f"_{resolved} resolved and {dropped} dropped entries are kept in the JSON file._\n"
    )
    body = "\n".join(blocks) + "\n"
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return f"{body}{_FOOTER_PREFIX}{digest} -->\n"


def _split_footer(raw: bytes) -> tuple[bytes, str] | None:
    """Return (bytes above the footer, recorded digest) or ``None`` if absent."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    at = text.rfind(_FOOTER_PREFIX)
    if at < 0 or (at > 0 and text[at - 1] != "\n"):
        return None
    match = _FOOTER_RE.fullmatch(text[at:])
    if match is None:
        return None
    return text[:at].encode("utf-8"), match.group(1)


def _view_was_hand_edited(raw: bytes) -> bool:
    split = _split_footer(raw)
    if split is None:
        return True
    above, recorded = split
    return hashlib.sha256(above).hexdigest() != recorded


def _render_view(vault_dir: Path, entries: list[dict[str, Any]]) -> None:
    path = view_path(vault_dir)
    new_text = _render_text(vault_dir, entries)
    current: bytes | None = None
    if path.is_file():
        try:
            current = path.read_bytes()
        except OSError:
            current = None
    if current == new_text.encode("utf-8"):
        return
    if current is not None and _view_was_hand_edited(current):
        copy = overwritten_path(vault_dir)
        write_bytes(copy, current)
        _LOG.warning(
            "research backlog view %s was changed outside the module and is "
            "being overwritten; make changes in %s instead. The overwritten "
            "text is kept at %s",
            path,
            store_path(vault_dir),
            copy,
        )
    write_text(path, new_text)


def ensure_view(vault_dir: Path) -> Path | None:
    """Render the view from the store before a reader (the scout prompt) uses it.

    Idempotent: an up-to-date view is left untouched. Does nothing, returning
    ``None``, when the store is unusable or the vault is unconverted.
    """
    try:
        loaded = _load(vault_dir)
    except BacklogUnavailable as exc:
        _LOG.warning("research backlog view not rendered: %s", exc)
        return None
    if loaded.read_only:
        _LOG.warning(
            "research backlog view not rendered: %s is read-only (newer schema)",
            loaded.path,
        )
        return None
    if not loaded.path.exists():
        return None
    _normalize(loaded.entries)
    _render_view(vault_dir, loaded.entries)
    return view_path(vault_dir)
