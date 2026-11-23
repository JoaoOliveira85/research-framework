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

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

from . import state_layout
from .atomic_write import write_text

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


class BacklogUnavailable(Exception):
    """Internal: the store cannot be used (malformed, read-only or unconverted)."""


class TitleRef(NamedTuple):
    """One entry's normalised key and display title (any status)."""

    key: str
    title: str


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

    # -- observations -----------------------------------------------------


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
    return True


# ---------------------------------------------------------------------------
# Queries (immutable results)
# ---------------------------------------------------------------------------


def all_titles(vault_dir: Path) -> list[TitleRef]:
    """Every entry's key and display title, whatever its status (FR-013)."""
    return [
        TitleRef(title_key(e["title"]), e["title"]) for e in _read_for_query(vault_dir)
    ]


# ---------------------------------------------------------------------------
# The view (contracts/backlog-view.contract.md)
# ---------------------------------------------------------------------------


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
