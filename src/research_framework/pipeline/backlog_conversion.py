"""Convert a legacy Markdown backlog into the structured store (spec 084 FR-021).

``convert_legacy`` is pure: text in, entries and a report out. It follows the
grammar table of ``research.md`` R8. ``write_converted`` installs the result
(store, byte-for-byte archive, rendered view) without going through
``backlog.update``, which refuses an unconverted vault. Neither is wired into a
migration step here; that step imports this module.

Every non-blank input line ends up in exactly one bucket: a typed entry, a
``migrated`` entry (carried verbatim) or a dropped line (seed boilerplate,
block markers, block headings and their fixed prose, coverage-gap snapshot
lines). :attr:`ConversionResult.accounted_lines` equals
:attr:`ConversionResult.nonblank_lines` by construction.

Decisions the table leaves open:

* One topic, several sightings (ids fold case and whitespace): the entry is
  created by the first sighting in file order and keeps its title. Its origin
  is that sighting's, except that a sighting *outside* any block (the
  operator-shaped bullet) makes the origin ``operator`` -- a person or an
  unmarked legacy writer owns the line, and operator ownership is the
  conservative choice: no writer auto-resolves, reopens or re-describes it.
  A researcher flag never overrides ``harvest``; a block sighting after a
  flag only adds citations (the entry stays queued on evidence, FR-012).
* Observation fields come from block sightings: ``first_seen_cycle`` /
  ``last_seen_cycle`` are the min / max block cycle, ``seen_cycles`` the
  number of distinct block cycles, citations from the *latest* block. An entry
  with no block sighting keeps its own bullet's citation count and no cycles.
* A shape that is only valid in one block kind (propose bullets, researcher
  flags) is typed by shape alone, except proposals, which need a propose
  block; outside one the line is carried as ``migrated``.
* ``status_written`` equals ``status`` so the module does not mistake the
  converted entries for operator edits.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import backlog, state_layout
from .atomic_write import write_bytes

_LOG = logging.getLogger(__name__)

# A legacy Markdown backlog cannot hold a note update (spec 087).
_LEGACY_ORIGINS = tuple(o for o in backlog.ORIGINS if o not in ("update", "discovery"))

_MARKER_RE = re.compile(
    r"^<!-- (/?)(?:topic-(harvest|propose):cycle=(\d+)|(quarantine)) -->$"
)
_HEADING_RE = re.compile(r"^## (?:Harvest|Proposed tangents) — cycle \d+\b")
_FIXED_LINES = frozenset(
    {
        "# Research Backlog",
        "Topics deferred from scout passes.",
        "Follow-on topics (wikilink targets with no note yet, "
        "ranked by citation count):",
        "Unmet coverage categories:",
        "Scope-bounded tangents the agent identified. Lower priority than "
        "the Phase 1 Harvest block; the scout can still consult them.",
    }
)
_VERSION_LINE_RE = re.compile(r"^_template_version: \d+$")
_GAP_RE = re.compile(r"^- `[^`]+` \[[^\]]+\] — \d+/\d+(?: \(required\))?$")

_ORPHAN_RE = re.compile(
    r"^\s*-\s+\*\*(?P<title>[^*]+?)\*\*\s+—\s+cited by\s+(?P<n>\d+)\s+note\(s\)"
    r"(?P<rest>.*)$"
)
_FLAG_RE = re.compile(
    r"^\s*-\s+\*\*(?P<title>[^*]+?)\*\*\s+—\s+flagged by researcher\s*$"
)
_PROPOSAL_RE = re.compile(
    r"^\s*-\s+\*\*(?P<title>[^*]+?)\*\*(?P<warn>\s+⚠️)?"
    r"\s+\((?P<relation>\w+) of \[\[(?P<parent>[^\]]+)\]\]\)\s+—\s+(?P<detail>.*)$"
)
_REWRITE_RE = re.compile(
    r"^\s*-\s+\[[ xX]\]\s+rewrite quarantined note:\s+(?P<stem>\S+)\s+"
    r"\((?P<reason>.*?)\)(?P<tag>\s+<!-- stem:\S+ -->)?\s*$"
)
_RETRY_RE = re.compile(
    r"^\s*-\s+\[[ xX]\]\s+retry refresh of\s+(?P<stem>\S+)\s+—\s+(?P<reason>.*?)"
    r"(?P<tag>\s+<!-- stem:\S+ -->)?\s*$"
)
_TAG_RE = re.compile(r"<!-- stem:(\S+) -->")
_VERIFIER_RE = re.compile(r"verifier_status: rejected — (.*)$")
_BACKTICK_RE = re.compile(r"`([^`]+)`")

_MAX_JOIN = 3
_TITLE_PREFIX = 80


@dataclass
class ConversionResult:
    """Store entries ready to save plus what the INFO line (FR-023) reports."""

    entries: list[dict[str, Any]]
    entries_by_origin: dict[str, int]
    nonblank_lines: int = 0
    typed_lines: int = 0
    migrated_lines: int = 0
    boilerplate_lines_dropped: int = 0
    derived_lines_dropped: int = 0  # coverage-gap snapshot lines (derivable)
    duplicates_collapsed: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def accounted_lines(self) -> int:
        return (
            self.typed_lines
            + self.migrated_lines
            + self.boilerplate_lines_dropped
            + self.derived_lines_dropped
        )

    def info_line(self, archive: Path | str) -> str:
        counts = " ".join(
            f"{origin}={self.entries_by_origin.get(origin, 0)}"
            for origin in _LEGACY_ORIGINS
        )
        return (
            f"research backlog converted: {counts}; "
            f"{self.derived_lines_dropped} coverage-gap line(s) not carried "
            f"(derivable); original kept at {archive}"
        )


def _join_wrapped(lines: list[str], i: int) -> tuple[str, int]:
    """The logical line starting at ``i`` and how many physical lines it spans.

    A bullet opened with ``- **`` and no closing ``**`` is joined with up to
    three following lines until the closing ``**`` appears (a title wrapped by
    an agent). Without a closing within the limit the line stands alone.
    """
    line = lines[i]
    if not re.match(r"^\s*-\s+\*\*", line) or line.count("**") >= 2:
        return line, 1
    parts = [line.rstrip()]
    for extra in range(1, _MAX_JOIN + 1):
        if i + extra >= len(lines):
            break
        following = lines[i + extra]
        if not following.strip():
            break  # a blank line ends the paragraph; never swallow it
        parts.append(following.strip())
        if "**" in following:
            return " ".join(parts), extra + 1
    return line, 1


class _Builder:
    def __init__(self, today: str) -> None:
        self.today = today
        self.entries: list[dict[str, Any]] = []
        self.by_id: dict[str, dict[str, Any]] = {}
        self.cycles: dict[str, set[int]] = {}
        self.migrated = 0
        self.duplicates = 0

    def _new(self, ident: str, title: str, origin: str) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "id": ident,
            "title": title,
            "origin": origin,
            "status": "open",
            "status_by": "migration",
            "status_written": "open",
            "added": self.today,
            "updated": self.today,
            "first_seen_cycle": None,
            "last_seen_cycle": None,
            "seen_cycles": 0,
        }
        self.entries.append(entry)
        self.by_id[ident] = entry
        return entry

    def topic(self, title: str, origin: str) -> dict[str, Any]:
        display = " ".join(title.split())
        ident = backlog.topic_id(display)
        entry = self.by_id.get(ident)
        if entry is None:
            entry = self._new(ident, display, origin)
        else:
            self.duplicates += 1
            if origin == "operator" and entry["origin"] != "operator":
                entry["origin"] = "operator"
        return entry

    def sight(self, entry: dict[str, Any], cycle: int | None) -> None:
        if cycle is None:
            return
        seen = self.cycles.setdefault(entry["id"], set())
        seen.add(cycle)
        entry["first_seen_cycle"] = min(seen)
        entry["last_seen_cycle"] = max(seen)
        entry["seen_cycles"] = len(seen)

    def cite(
        self, entry: dict[str, Any], cycle: int | None, n: int, paths: list[str]
    ) -> None:
        """Record citations; a later block (or a block over a bare bullet) wins."""
        previous = entry.get("_cite_cycle")
        if cycle is None:
            if previous is not None:
                return  # a block already supplied the latest figures
        elif previous is not None and cycle < previous:
            return
        entry["_cite_cycle"] = cycle
        entry["citation_count"] = n
        entry["cited_from"] = paths

    def migrated_line(self, line: str) -> None:
        self.migrated += 1
        entry = self._new(
            backlog.migrated_id(self.migrated),
            line.strip()[:_TITLE_PREFIX],
            "migrated",
        )
        entry["detail"] = line


def convert_legacy(markdown: str, *, today: str) -> ConversionResult:
    """Turn the text of a legacy Markdown backlog into store entries."""
    lines = markdown.splitlines()
    builder = _Builder(today)
    result = ConversionResult(entries=builder.entries, entries_by_origin={})
    block: tuple[str, int | None] | None = None
    in_frontmatter = False
    seen_frontmatter_open = False

    def typed(count: int) -> None:
        result.typed_lines += count

    result.nonblank_lines = sum(1 for line in lines if line.strip())
    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        if not stripped:
            i += 1
            continue

        # Seed frontmatter: only the delimiters and the template version.
        if not seen_frontmatter_open and stripped == "---":
            seen_frontmatter_open = in_frontmatter = True
            result.boilerplate_lines_dropped += 1
            i += 1
            continue
        seen_frontmatter_open = True
        if in_frontmatter:
            if stripped == "---":
                in_frontmatter = False
                result.boilerplate_lines_dropped += 1
                i += 1
                continue
            if _VERSION_LINE_RE.match(stripped):
                result.boilerplate_lines_dropped += 1
                i += 1
                continue
            in_frontmatter = False  # not frontmatter after all; carry the line

        marker = _MARKER_RE.match(stripped)
        if marker:
            closing, kind, cycle, quarantine = marker.groups()
            if closing:
                block = None
            elif quarantine:
                block = ("quarantine", None)
            else:
                block = (kind, int(cycle))
            result.boilerplate_lines_dropped += 1
            i += 1
            continue
        if _HEADING_RE.match(stripped) or stripped in _FIXED_LINES:
            result.boilerplate_lines_dropped += 1
            i += 1
            continue
        if _GAP_RE.match(stripped):
            result.derived_lines_dropped += 1
            i += 1
            continue

        logical, span = _join_wrapped(lines, i)
        kind = block[0] if block else None
        cycle = block[1] if block else None

        rewrite = _REWRITE_RE.match(logical)
        retry = None if rewrite else _RETRY_RE.match(logical)
        if rewrite or retry:
            m = rewrite or retry
            assert m is not None
            tag = _TAG_RE.search(logical)
            stem = tag.group(1) if tag else m.group("stem")
            reason = m.group("reason").strip()
            verifier = _VERIFIER_RE.search(reason)
            detail = verifier.group(1).strip() if verifier else reason
            if retry and verifier and detail.endswith(")"):
                detail = detail[:-1].rstrip()  # the retry text wraps it in parens
            ident = backlog.quarantine_id(stem)
            entry = builder.by_id.get(ident)
            if entry is None:
                entry = builder._new(ident, stem, "quarantine")
                entry["stem"] = stem
            else:
                builder.duplicates += 1
            entry["kind"] = "rewrite" if rewrite else "retry"
            entry["detail"] = detail
            typed(span)
            i += span
            continue

        flag = _FLAG_RE.match(logical)
        if flag:
            entry = builder.topic(flag.group("title"), "researcher")
            builder.sight(entry, cycle if kind == "harvest" else None)
            typed(span)
            i += span
            continue

        orphan = _ORPHAN_RE.match(logical)
        if orphan:
            in_harvest = kind == "harvest"
            entry = builder.topic(
                orphan.group("title"), "harvest" if in_harvest else "operator"
            )
            builder.sight(entry, cycle if in_harvest else None)
            builder.cite(
                entry,
                cycle if in_harvest else None,
                int(orphan.group("n")),
                _BACKTICK_RE.findall(orphan.group("rest")),
            )
            typed(span)
            i += span
            continue

        proposal = _PROPOSAL_RE.match(logical) if kind == "propose" else None
        if proposal:
            entry = builder.topic(proposal.group("title"), "proposal")
            builder.sight(entry, cycle)
            if entry["origin"] == "proposal":
                entry["relation"] = proposal.group("relation")
                entry["parent_note"] = proposal.group("parent").strip()
                entry["scope_warn"] = bool(proposal.group("warn"))
                entry["detail"] = proposal.group("detail").strip()
            typed(span)
            i += span
            continue

        builder.migrated_line(raw)
        i += 1

    for entry in builder.entries:
        entry.pop("_cite_cycle", None)
    result.migrated_lines = builder.migrated
    result.duplicates_collapsed = builder.duplicates
    counts = {origin: 0 for origin in _LEGACY_ORIGINS}
    for entry in builder.entries:
        counts[entry["origin"]] += 1
    result.entries_by_origin = counts
    return result


def write_converted(
    vault_dir: Path, result: ConversionResult, *, original: bytes
) -> bool:
    """Install a converted backlog: archive, store, view. ``False`` if converted.

    The archive (``state_layout.research_backlog_archive_path``) receives
    ``original`` byte for byte first; the store is written only once the
    archive exists, so an interrupted run never loses the only copy of the
    operator's lines. A store that already exists makes this a no-op, which
    makes a second run harmless. Logs the FR-023 INFO line.
    """
    store = backlog.store_path(vault_dir)
    if store.exists():
        return False
    archive = state_layout.research_backlog_archive_path(vault_dir)
    if archive.exists() and archive.read_bytes() != original:
        raise FileExistsError(f"{archive} exists and differs from the legacy backlog")
    if not archive.exists():
        write_bytes(archive, original)
    backlog.install_store(vault_dir, result.entries, archive=archive)
    _LOG.info(result.info_line(archive.relative_to(vault_dir).as_posix()))
    return True
