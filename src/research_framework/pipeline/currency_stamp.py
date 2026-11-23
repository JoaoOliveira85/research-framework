"""Stamp ``as_of`` and ``currency`` onto the notes a pre-087 vault already has
(spec 087 FR-021, FR-022).

A note written before spec 087 carries neither field. :func:`plan_stamps` finds
the corpus notes that lack one (alias and exempt notes are not notes in this
sense, and a note with no frontmatter block, or frontmatter that does not
parse, is skipped and counted); :func:`apply_stamps` adds the missing line(s)
with :func:`~research_framework.vault.frontmatter.append_frontmatter_keys`, so
every line already in the file stays byte for byte.

``as_of`` is the best evidence the note itself gives of when it was last
checked: the newest ``source_urls`` ``accessed`` date, else ``updated``, else
``created``, else the date of the file's first git commit, else today.
``currency`` is ``current``.

Nothing here queues review work. A missing field already reads as ``current``
and never due, so the stamp only makes an old note *able* to come due: the
cycle's due sweep queues what is past its interval, and the cycle split bounds
how many are worked per cycle.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from research_framework.vault import note_currency as nc
from research_framework.vault.corpus import corpus_dir
from research_framework.vault.frontmatter import (
    FrontmatterParseError,
    append_frontmatter_keys,
    parse_frontmatter_str,
)

_LOG = logging.getLogger(__name__)

_INDEX_FILES = ("_index.md", "_concepts.md", "_graph.md")
_ACCESSED_RE = re.compile(r"accessed[ :]+(\d{4}-\d{2}-\d{2})")


@dataclass(frozen=True)
class Stamp:
    """One note to stamp: what to add and where ``as_of`` came from."""

    rel: str
    as_of: str
    add_as_of: bool
    add_currency: bool
    basis: str  # accessed | updated | created | git | today


@dataclass
class StampPlan:
    stamps: list[Stamp] = field(default_factory=list)
    skipped: int = 0
    skipped_notes: list[str] = field(default_factory=list)

    @property
    def oldest(self) -> str | None:
        dates = [s.as_of for s in self.stamps if s.add_as_of]
        return min(dates) if dates else None

    @property
    def newest(self) -> str | None:
        dates = [s.as_of for s in self.stamps if s.add_as_of]
        return max(dates) if dates else None


def _to_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def _accessed(fm: dict[str, Any]) -> date | None:
    """The newest ``accessed`` date among ``source_urls`` (dict or tagged string)."""
    found: list[date] = []
    entries = fm.get("source_urls")
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, dict):
            parsed = _to_date(entry.get("accessed"))
        elif isinstance(entry, str):
            match = _ACCESSED_RE.search(entry)
            parsed = _to_date(match.group(1)) if match else None
        else:
            parsed = None
        if parsed is not None:
            found.append(parsed)
    return max(found) if found else None


def _first_commit_date(vault: Path, rel: str) -> date | None:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(vault),
                "log",
                "--diff-filter=A",
                "--follow",
                "--format=%as",
                "--",
                rel,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    return _to_date(lines[-1]) if result.returncode == 0 and lines else None


def derive_as_of(
    fm: dict[str, Any], vault: Path, rel: str, today: date
) -> tuple[date, str]:
    """``(as_of, basis)`` for a note, from the best evidence it carries."""
    accessed = _accessed(fm)
    if accessed is not None:
        return accessed, "accessed"
    for key in ("updated", "created"):
        parsed = _to_date(fm.get(key))
        if parsed is not None:
            return parsed, key
    committed = _first_commit_date(vault, rel)
    if committed is not None:
        return committed, "git"
    return today, "today"


def _missing(fm: dict[str, Any], key: str) -> bool:
    return fm.get(key) in (None, "")


def _read(path: Path) -> str | None:
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _patch(text: str, additions: dict[str, Any], empty: list[str]) -> str | None:
    """``text`` with the missing keys added, every other byte untouched; ``None``
    when that cannot be done simply (the note is then skipped).

    ``empty`` names keys present with an empty value (``as_of: ""``): that one
    line is replaced instead of a second one being added. CRLF files are patched
    with CRLF line ends, only when every line end is CRLF.
    """
    bom = text.startswith("﻿")
    body = text[1:] if bom else text
    crlf = "\r\n" in body
    if crlf:
        if body.count("\n") != body.count("\r\n"):
            return None
        body = body.replace("\r\n", "\n")
    for key in empty:
        replaced, count = re.subn(
            rf"(?m)^{re.escape(key)}:[ \t]*(?:\"\"|'')?[ \t]*$",
            f"{key}: {additions[key]}",
            body,
            count=1,
        )
        if count != 1:
            return None
        body = replaced
    fresh = {k: v for k, v in additions.items() if k not in empty}
    if fresh:
        patched = append_frontmatter_keys(body, fresh)
        if patched is None:
            return None
        body = patched
    if crlf:
        body = body.replace("\n", "\r\n")
    return ("﻿" if bom else "") + body


def plan_stamps(vault: Path, *, today: date | None = None) -> StampPlan:
    """Read-only: the notes to stamp, with the date each would get."""
    today = today or datetime.now(UTC).date()
    plan = StampPlan()
    root = corpus_dir(vault)
    if not root.is_dir():
        return plan
    for path in sorted(root.rglob("*.md")):
        if path.name in _INDEX_FILES or "_templates" in path.relative_to(root).parts:
            continue
        rel = path.relative_to(vault).as_posix()
        text = _read(path)
        try:
            fm, _body = parse_frontmatter_str(
                (text or "").removeprefix("﻿").replace("\r\n", "\n")
            )
        except FrontmatterParseError:
            fm = None
        if text is None or not fm:
            plan.skipped += 1  # no frontmatter block, or one that does not parse
            plan.skipped_notes.append(rel)
            continue
        if str(fm.get("note_type", "")).strip().lower() == "alias":
            continue
        if str(fm.get("verifier_status", "")).strip().lower() == "exempt":
            continue
        need_as_of = _missing(fm, nc.AS_OF_FIELD)
        need_currency = _missing(fm, nc.CURRENCY_FIELD)
        if not (need_as_of or need_currency):
            continue
        as_of, basis = derive_as_of(fm, vault, rel, today)
        additions: dict[str, Any] = {}
        if need_as_of:
            additions[nc.AS_OF_FIELD] = as_of
        if need_currency:
            additions[nc.CURRENCY_FIELD] = nc.CURRENT
        empty = [k for k in additions if k in fm]
        if _patch(text, additions, empty) is None:
            plan.skipped += 1
            plan.skipped_notes.append(rel)
            continue
        plan.stamps.append(
            Stamp(
                rel=rel,
                as_of=as_of.isoformat(),
                add_as_of=need_as_of,
                add_currency=need_currency,
                basis=basis,
            )
        )
    return plan


def apply_stamps(vault: Path, plan: StampPlan) -> int:
    """Write the planned stamps; return how many notes changed."""
    written = 0
    for stamp in plan.stamps:
        path = vault / stamp.rel
        text = _read(path)
        if text is None:
            continue
        try:
            fm, _ = parse_frontmatter_str(text.removeprefix("﻿").replace("\r\n", "\n"))
        except FrontmatterParseError:
            continue
        additions: dict[str, Any] = {}
        if stamp.add_as_of:
            additions[nc.AS_OF_FIELD] = date.fromisoformat(stamp.as_of)
        if stamp.add_currency:
            additions[nc.CURRENCY_FIELD] = nc.CURRENT
        patched = _patch(text, additions, [k for k in additions if k in fm])
        if patched is None or patched == text:
            continue
        path.write_bytes(patched.encode("utf-8"))
        written += 1
    return written
