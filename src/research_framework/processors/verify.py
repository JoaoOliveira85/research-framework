"""Vault structural verification processor (Tier 0 — pure Python, no AI).

Checks vault health: frontmatter completeness, broken wikilinks, orphan notes,
MOC consistency. Outputs a structured report and optionally auto-fixes trivial
issues (missing ``related``, missing ``status``).

Ported faithfully from feeds-vault/scripts/verify.py with two adaptations:
  1. ``python-frontmatter`` dependency removed — notes are read and written
     through the canonical codec in ``research_framework.vault.frontmatter``
     (``parse_frontmatter_str`` / ``dump_frontmatter``, spec 025 B4), which is
     real YAML. The line-scalar parser in ``_common`` is NOT usable here: it
     is scoped to ``_pipeline`` raw items and flattens lists, nested mappings
     and quoted scalars, so auto-fix used to destroy note frontmatter.
  2. Path conventions use vault root argument instead of hard-coded DEFAULT_VAULT.

The ``fail_threshold`` spec field (fraction of flagged notes that constitutes a
FAIL verdict) is honoured when spec_processors config is supplied.

Python API:
    from research_framework.processors.verify import verify, VerifyResult
    result = verify(vault_path, auto_fix=True)

CLI:
    python -m research_framework.processors.verify <vault> [options]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..vault.frontmatter import (
    FrontmatterParseError,
    append_frontmatter_keys,
    dump_frontmatter,
    parse_frontmatter_str,
)
from ._common import processor_config

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerifyResult:
    files_processed: int
    notes_checked: int
    auto_fixes_applied: int
    structural_flags: int
    malformed_count: int
    verdict: str  # "PASS" | "WARN" | "FAIL"
    report: dict[str, Any]
    errors: tuple[str, ...]
    # The threshold this run was actually graded against, after the
    # explicit-argument > spec-config > default precedence in :func:`verify`.
    # A caller cannot report "over threshold" honestly without it, and the
    # value it would otherwise have to guess is the one thing spec config can
    # move out from under it.  Defaulted so the field is additive for the
    # existing keyword constructions in the test suite.
    fail_threshold: float = 0.20
    # The verdict-bearing half of ``structural_flags``, and the rest.  A
    # ``content`` flag is something only the vault's author can fix; a
    # ``tooling`` flag is the framework's own graph bookkeeping — an orphan,
    # a MOC gap, a key verify itself can write.  Only content flags are
    # measured against ``fail_threshold`` (issue #225).  The two partition
    # ``structural_flags``.
    content_flags: int = 0
    tooling_flags: int = 0


# ---------------------------------------------------------------------------
# Constants (ported verbatim from feeds-vault/scripts/verify.py)
# ---------------------------------------------------------------------------

# Directories that never hold notes.  Every dot-directory is excluded too
# (``.claude/commands/*.md``, ``.venv/**`` site-package READMEs, ``.git``),
# which is what kept the 2026-09-01 run from grading its own tooling as notes.
EXCLUDE_DIRS = {
    "_templates",
    "_pipeline",
    ".obsidian",
    "node_modules",
    "scripts",
    "venv",
}

# Markdown files that are vault CONFIG or documentation, never notes.  A real
# note is never named any of these, at any depth.
EXCLUDE_FILES = {
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "Home.md",
    "README.md",
}

# Suffixes that mark a config document (``research.spec.md`` and friends).
EXCLUDE_SUFFIXES = (".spec.md",)

# Framework-GENERATED corpus index files (see ``vault.indexer._is_note_path``,
# which uses the same three names).  They live inside the corpus but are not
# notes: they carry no frontmatter and exist to link OUT to every note.  So
# they are scanned for wikilinks — dropping them would report every note they
# index as an orphan — but never graded, counted or auto-fixed.
GENERATED_INDEX_FILES = {"_index.md", "_concepts.md", "_graph.md"}

WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")

MOC_TO_FOLDERS: dict[str, list[str]] = {
    "Companies MOC": ["02 - Companies"],
    "People MOC": ["03 - People"],
    "Concepts MOC": ["04 - Concepts"],
    "Issues & Risks MOC": ["05 - Issues & Risks"],
    "Opportunities MOC": ["06 - Opportunities"],
    "AI Tools MOC": ["13 - AI Tools"],
    "Sources MOC": ["01 - Sources"],
    "Society Culture Technology MOC": [
        "07 - Trends",
        "09 - Society",
        "10 - Technology Deep Dives",
        "11 - Future",
    ],
}

ARTIFACT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^Note Name$"),
    re.compile(r"\)$"),
    re.compile(r"^wikilinks$"),
]

# ---------------------------------------------------------------------------
# Flag classes (issue #225 / #227)
# ---------------------------------------------------------------------------

CONTENT = "content"
TOOLING = "tooling"

# Checks the FRAMEWORK owns, not the vault's author.  The rule is mechanical:
# a check verify can satisfy on its own (``missing_related`` and
# ``missing_status`` are exactly the two it auto-fixes) or that says something
# about the shape of the graph rather than the content of a note is tooling.
# Tooling flags are reported and counted; they never drive the FAIL verdict.
# Before this split, 14 orphan flags over 18 notes were enough on their own to
# fail a committed fixture.
TOOLING_CHECKS = frozenset({"missing_related", "missing_status", "orphan", "moc_gap"})

# ``verifier_status`` values that take a note out of grading entirely.  The
# verifier stage writes ``verified`` / ``pending`` / ``rejected``; ``exempt`` is
# the vault format's own opt-out and is what ``pipeline.wikilinks`` stamps on
# every acronym redirect stub it generates.
EXEMPT_VERIFIER_STATUSES = frozenset({"exempt"})

# Note types that exist to redirect, not to say anything.  An alias stub is a
# legitimate link target with no body of its own; grading it produces a flag
# for every alias the framework generated for the vault.
ALIAS_NOTE_TYPES = frozenset({"alias"})


# ---------------------------------------------------------------------------
# Helpers (ported from feeds-vault/scripts/verify.py)
# ---------------------------------------------------------------------------


def _is_markdown_content(name: str) -> bool:
    """True when *name* is vault markdown — a note or a generated index."""
    if not name.endswith(".md"):
        return False
    if name in EXCLUDE_FILES:
        return False
    return not name.endswith(EXCLUDE_SUFFIXES)


def _is_note_filename(name: str) -> bool:
    """True when *name* is a gradeable note."""
    return _is_markdown_content(name) and name not in GENERATED_INDEX_FILES


def _iter_markdown(vault: Path):
    """Yield every markdown file that participates in the wikilink graph.

    Dot-directories are skipped wholesale: ``.claude/``, ``.venv/``, ``.git/``
    hold markdown that is tooling, not corpus, and grading it both produced
    bogus orphan/missing-summary flags and — with auto-fix on — rewrote it.
    """
    for root, dirs, files in os.walk(vault):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".")]
        for f in files:
            if _is_markdown_content(f):
                yield Path(root) / f


def _iter_notes(vault: Path):
    """Yield the gradeable notes — :func:`_iter_markdown` minus generated indexes."""
    for path in _iter_markdown(vault):
        if path.name not in GENERATED_INDEX_FILES:
            yield path


def _note_name(path: Path) -> str:
    return path.stem


def _relative_path(path: Path, vault: Path) -> str:
    try:
        return str(path.relative_to(vault))
    except ValueError:
        return str(path)


def _resolve_wikilink(raw_link: str) -> str:
    name = raw_link.split("#", 1)[0].strip()
    if not name:
        return ""
    if "/" in name:
        name = name.rsplit("/", 1)[-1]
    return name.strip()


def _strip_code_for_link_scan(text: str) -> str:
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]*`", "", text)
    return text


def _is_artifact(name: str) -> bool:
    return any(pat.search(name) for pat in ARTIFACT_PATTERNS)


def _link_key(name: str) -> str:
    """The identity a wikilink and a filename are compared under.

    ADR-0005 decided that ``[[Cassandra]]`` and ``cassandra.md`` are one node
    and that the drift is repaired at cycle time. Verify never got the memo and
    compared the two case-sensitively, so on a vault mid-normalisation every
    case variant was simultaneously a broken link and an orphan — two flags for
    one node that the framework's own normaliser was about to fix.
    """
    return name.casefold()


def _is_exempt(metadata: dict[str, Any] | None) -> bool:
    """True when the vault format itself says "do not grade this note".

    Two markers, both already written by the framework:
    ``verifier_status: exempt`` (the format's opt-out) and
    ``note_type: alias`` (the redirect stubs ``pipeline.wikilinks`` generates
    for every title-derived acronym — bodies of one line whose entire job is to
    be a link target).
    """
    if not metadata:
        return False
    status = str(metadata.get("verifier_status", "") or "").strip().lower()
    if status in EXEMPT_VERIFIER_STATUSES:
        return True
    note_type = str(metadata.get("note_type", "") or "").strip().lower()
    return note_type in ALIAS_NOTE_TYPES


def _flag_class(check: str) -> str:
    """Which side of the verdict a check falls on. See :data:`TOOLING_CHECKS`."""
    return TOOLING if check in TOOLING_CHECKS else CONTENT


# ---------------------------------------------------------------------------
# Frontmatter read + write (no python-frontmatter dep)
# ---------------------------------------------------------------------------


def _load_note(path: Path) -> tuple[dict[str, Any] | None, str | None, str]:
    """Read note frontmatter through the canonical codec.

    Returns (metadata_dict | None, error_msg | None, body).  The body is
    returned verbatim — everything after the closing ``---`` line — so that a
    subsequent :func:`_write_frontmatter` round-trips it byte-for-byte.
    """
    # ``utf-8-sig`` strips a BOM that would otherwise hide the frontmatter (and
    # make auto-fix prepend a second block); strict decoding reports a
    # non-UTF-8 note as malformed instead of writing U+FFFD over its bytes.
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        return None, str(exc), ""
    try:
        fm, body = parse_frontmatter_str(text)
    except FrontmatterParseError as exc:
        return None, str(exc), ""
    except Exception as exc:  # pragma: no cover — defensive
        return None, str(exc), ""
    return fm, None, body


def _write_frontmatter(path: Path, metadata: dict[str, Any], body: str) -> None:
    """Write updated frontmatter back to a note file.

    Delegates to the canonical :func:`dump_frontmatter`, which emits real YAML.
    Key order is preserved, the body is written verbatim, and lists / nested
    mappings / quoted scalars survive intact.
    """
    path.write_text(dump_frontmatter(metadata, body), encoding="utf-8")


def _add_frontmatter_key(
    path: Path, metadata: dict[str, Any], body: str, key: str, value: Any
) -> None:
    """Add ``key: value`` to *metadata* and to the note on disk.

    The key is appended to the frontmatter as the note has it, so the lines
    this fix has no business with stay as their author wrote them — a YAML
    load/dump round trip drops comments and rewrites ``0123`` as ``83`` and
    ``no`` as ``false``. Only where a line cannot simply be appended (no
    frontmatter block yet, a flow-style mapping) is the block re-emitted from
    *metadata*, as before.
    """
    metadata[key] = value
    try:
        # ``utf-8-sig`` for the same reason as in ``_load_note``.
        patched = append_frontmatter_keys(
            path.read_text(encoding="utf-8-sig"), {key: value}
        )
    except (OSError, UnicodeDecodeError):
        patched = None
    if patched is None:
        _write_frontmatter(path, metadata, body)
    else:
        path.write_text(patched, encoding="utf-8")


# ---------------------------------------------------------------------------
# Check functions (ported verbatim)
# ---------------------------------------------------------------------------


def _flag(
    check: str,
    file: str,
    detail: str,
    severity: str = "low",
    *,
    flag_class: str | None = None,
) -> dict[str, Any]:
    """One structural flag, always labelled with the class it is graded under.

    Callers may override the class (an artifact wikilink is the framework's
    own template residue, not a claim the author made), but never omit it: a
    flag with no class is a flag nobody can decide the verdict from.
    """
    return {
        "type": "structural_flag",
        "check": check,
        "file": file,
        "detail": detail,
        "severity": severity,
        "class": flag_class or _flag_class(check),
    }


def _check_missing_related(
    metadata: dict[str, Any], path: Path, body: str, vault: Path, auto_fix: bool
) -> list[dict[str, Any]]:
    fixes = []
    if "related" not in metadata:
        if auto_fix:
            _add_frontmatter_key(path, metadata, body, "related", [])
            fixes.append(
                {
                    "type": "auto_fix",
                    "check": "missing_related",
                    "file": _relative_path(path, vault),
                    "detail": "Added missing `related: []`",
                    "severity": "low",
                }
            )
        else:
            fixes.append(
                _flag(
                    "missing_related",
                    _relative_path(path, vault),
                    "Missing `related` frontmatter field",
                )
            )
    return fixes


def _check_missing_status(
    metadata: dict[str, Any], path: Path, body: str, vault: Path, auto_fix: bool
) -> list[dict[str, Any]]:
    fixes = []
    if "status" not in metadata:
        if auto_fix:
            _add_frontmatter_key(path, metadata, body, "status", "draft")
            fixes.append(
                {
                    "type": "auto_fix",
                    "check": "missing_status",
                    "file": _relative_path(path, vault),
                    "detail": "Added missing `status: draft`",
                    "severity": "low",
                }
            )
        else:
            fixes.append(
                _flag(
                    "missing_status",
                    _relative_path(path, vault),
                    "Missing `status` frontmatter field",
                )
            )
    return fixes


def _check_required_frontmatter(
    metadata: dict[str, Any],
    path: Path,
    vault: Path,
    required: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Flag every declared frontmatter key the note does not carry.

    ``required`` is resolved per run — see :func:`_resolve_required_frontmatter`
    — rather than hardcoded, because a hardcoded key set is how the shipped
    note template came to be unable to satisfy the framework's own checker
    (issue #226).
    """
    rel = _relative_path(path, vault)
    return [
        _flag(
            f"missing_{key}",
            rel,
            f"Missing `{key}` frontmatter field",
        )
        for key in required
        if not metadata.get(key)
    ]


def _find_broken_wikilinks(
    all_note_names: set[str],
    wikilinks_by_file: dict[str, list[str]],
    incoming_links: dict[str, int],
) -> list[dict[str, Any]]:
    """Flag wikilinks whose target does not exist, case-folded (ADR-0005)."""
    flags = []
    known = {_link_key(name) for name in all_note_names}
    for file_rel, links in wikilinks_by_file.items():
        for link in links:
            key = _link_key(link)
            if key in known:
                continue
            ref_count = incoming_links.get(key, 0)
            flag_class = None
            if _is_artifact(link):
                # ``[[Note Name]]``, ``[[wikilinks]]``: template residue the
                # framework emitted. Reported, but not the author's failure.
                severity = "low"
                flag_class = TOOLING
            elif ref_count >= 4:
                severity = "critical"
            elif ref_count >= 2:
                severity = "high"
            else:
                severity = "low"
            flags.append(
                _flag(
                    "broken_wikilink",
                    file_rel,
                    f"[[{link}]] — no matching file found",
                    severity,
                    flag_class=flag_class,
                )
            )
    return flags


def _find_orphans(
    incoming_links: dict[str, int],
    note_paths: dict[str, str],
    exempt: frozenset[str] | set[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Flag notes with zero incoming wikilinks.

    Driven off ``note_paths``, not the caller's ``all_note_names``: the latter
    also holds generated index files, which are link SOURCES — they must stay
    resolvable as link targets but must never themselves be flagged.

    ``exempt`` holds the case-folded names of notes the vault format took out
    of grading — ``verifier_status: exempt`` and the alias redirect stubs. An
    alias stub has, by construction, nothing pointing at it; flagging it as an
    orphan reports the framework's own generated file back to its author.
    """
    flags = []
    for name in sorted(note_paths):
        key = _link_key(name)
        if key in exempt:
            continue
        if incoming_links.get(key, 0) == 0:
            rel = note_paths.get(name, name)
            if any(skip in rel for skip in ["00 - MOC/", "Home.md", "AGENTS.md"]):
                continue
            flags.append(_flag("orphan", rel, "Zero incoming wikilinks"))
    return flags


def _check_moc_consistency(
    vault: Path,
    note_paths: dict[str, str],
    moc_to_folders: dict[str, list[str]],
    exempt: frozenset[str] | set[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Flag notes in a MOC's folders that the MOC does not list.

    ``moc_to_folders`` is resolved per run from the vault's own declared
    note-type folders — see :func:`_resolve_moc_map`. It used to be the module
    constant, which named one specific vault's folders, so this check was inert
    or misdirected for every vault the framework itself generated (#226).
    """
    flags = []
    moc_dir = vault / "00 - MOC"
    for moc_stem, folder_prefixes in moc_to_folders.items():
        moc_path = moc_dir / f"{moc_stem}.md"
        if not moc_path.exists():
            continue
        moc_text = moc_path.read_text(encoding="utf-8", errors="replace")
        raw_moc_links = WIKILINK_RE.findall(moc_text)
        moc_links = {_link_key(_resolve_wikilink(lnk)) for lnk in raw_moc_links}
        moc_links.discard("")
        moc_lower = moc_text.lower()
        for name, rel_path in note_paths.items():
            if _link_key(name) in exempt:
                continue
            in_folder = any(rel_path.startswith(prefix) for prefix in folder_prefixes)
            if not in_folder:
                continue
            if _link_key(name) in moc_links or name.lower() in moc_lower:
                continue
            flags.append(_flag("moc_gap", rel_path, f"Not listed in {moc_stem}.md"))
    return flags


# ---------------------------------------------------------------------------
# The note format this run grades against (issue #226)
# ---------------------------------------------------------------------------

# What verify required before it could ask. ``summary`` is the one key of the
# three that the framework's own step gate SG-005 also requires and that verify
# cannot write for the author, so it is the only one that survived into the
# content class; ``status`` and ``related`` are still checked, still auto-fixed
# and now classed as tooling.
DEFAULT_REQUIRED_FRONTMATTER: tuple[str, ...] = ("summary",)

# Files under a vault's ``_templates/`` that are not note templates.
_NON_TEMPLATE_FILES = {"CHANGELOG.md", "README.md"}


def _declared_note_format(templates_dir: Path) -> tuple[str, ...]:
    """The frontmatter keys a vault's own note templates leave for the writer.

    The framework renders one ``_templates/<note-type>.md`` per declared note
    type from ``templates/note-type.md.j2``. Keys the template STAMPS (``type``,
    ``template_version``) are the template's own business; keys it declares
    EMPTY (``summary: ""``, ``source_urls: []``, ``coverage_category: ""``) are
    the slots a note is expected to fill — which is precisely the contract
    ``pipeline.gates_step.SG005_frontmatter_completeness`` already enforces at
    note-write time.

    Reading the requirement off the template is what makes it impossible for
    the shipped template and the checker to disagree — the disagreement that
    made every framework-generated note flag ``missing_summary`` on sight.
    Returns ``()`` when there is nothing to read, so the caller can fall back.
    """
    if not templates_dir.is_dir():
        return ()
    keys: set[str] = set()
    for path in sorted(templates_dir.glob("*.md")):
        if path.name in _NON_TEMPLATE_FILES:
            continue
        fm, error, _body = _load_note(path)
        if error is not None or not fm:
            continue
        keys.update(key for key, value in fm.items() if not value)
    return tuple(sorted(keys))


def _resolve_required_frontmatter(
    *,
    required_frontmatter: list[str] | tuple[str, ...] | None,
    cfg: dict[str, Any],
    template_dirs: tuple[Path, ...],
) -> tuple[str, ...]:
    """Explicit argument > spec config > the vault's templates > the default.

    ``template_dirs`` is searched in order and the FIRST directory that
    declares anything wins. A generated vault has two ``_templates/``
    directories — the corpus one holds section skeletons with no frontmatter at
    all, the vault-root one holds the frontmatter-bearing note-type templates —
    so "the first directory that exists" is the wrong rule and "the first that
    says something" is the right one.
    """
    if required_frontmatter is not None:
        return tuple(str(k) for k in required_frontmatter)
    declared = cfg.get("required_frontmatter")
    if declared:
        return tuple(str(k) for k in declared)
    for templates_dir in template_dirs:
        from_templates = _declared_note_format(templates_dir)
        if from_templates:
            return from_templates
    return DEFAULT_REQUIRED_FRONTMATTER


def _resolve_moc_map(
    spec_note_types: list[dict[str, Any]] | None,
) -> dict[str, list[str]]:
    """Map ``00 - MOC/<stem>.md`` → the folders it is expected to cover.

    Derived from the vault's declared ``note_types`` when it declares any: a
    note type named ``company`` living in ``02 - Companies`` is covered by
    ``Companies MOC.md`` / ``Company MOC.md``, whichever the vault actually
    wrote. With nothing declared, the legacy :data:`MOC_TO_FOLDERS` stands in —
    it is one real vault's taxonomy, and that vault is the only one it has ever
    described correctly.
    """
    if not spec_note_types:
        return MOC_TO_FOLDERS
    derived: dict[str, list[str]] = {}
    for note_type in spec_note_types:
        if not isinstance(note_type, dict):
            continue
        folder = str(note_type.get("folder", "") or "").strip()
        name = str(note_type.get("name", "") or "").strip()
        if not folder or not name:
            continue
        # ``02 - Companies`` → the MOC is named for the label, not the number.
        label = folder.split(" - ", 1)[-1].strip() or name
        for stem in {f"{label} MOC", f"{name.title()} MOC"}:
            derived.setdefault(stem, [])
            if folder not in derived[stem]:
                derived[stem].append(folder)
    return derived or MOC_TO_FOLDERS


# ---------------------------------------------------------------------------
# Failure reasons (issue #218)
# ---------------------------------------------------------------------------

# A FAIL used to be a verdict with no reason attached: ``errors`` was declared
# at the top of :func:`verify` and never written to, so ``VerifyResult.errors``
# was ``()`` for every FAIL the framework has ever produced.  On 2026-09-01
# seven of eight real vaults failed verify and the recorded reason was, in each
# case, the empty list.
#
# The reasons below are deliberately BOUNDED.  They are persisted into
# ``pipeline-state.json`` by the pipeline runner, so "one line per malformed
# note" would put 840 strings into the state file of a vault whose real problem
# is one bad template.  The full per-note detail lives in ``report['results']``,
# which the runner now writes to ``_pipeline/logs/verify-<ts>.json``.
_MAX_REPORTED_MALFORMED = 5
_MAX_REPORTED_FLAG_FAMILIES = 5


def _first_line(text: str) -> str:
    """The headline of a multi-line loader message, collapsed to one line.

    PyYAML's errors are five-line caret diagrams.  The first line names the
    construct that failed, which is what fits in a state file; the rest is in
    the verify report.
    """
    return text.strip().splitlines()[0].strip() if text.strip() else text.strip()


def _flags_by_check(results: list[dict[str, Any]]) -> dict[str, int]:
    """Structural-flag counts keyed by check name, densest first."""
    counts: dict[str, int] = {}
    for r in results:
        if r.get("type") != "structural_flag":
            continue
        check = str(r.get("check", "unknown"))
        counts[check] = counts.get(check, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _failure_reasons(
    *,
    results: list[dict[str, Any]],
    flags_by_check: dict[str, int],
    notes_checked: int,
    structural_flags: int,
    content_flags: int,
    tooling_flags: int,
    malformed_count: int,
    fail_threshold: float,
) -> list[str]:
    """Why this vault failed, in the form an operator can act on."""
    reasons: list[str] = []

    if malformed_count > 0:
        reasons.append(
            f"FAIL: {malformed_count} note(s) have malformed frontmatter — a "
            f"single malformed note fails the vault, independently of "
            f"fail_threshold."
        )
        malformed = [r for r in results if r.get("check") == "malformed_frontmatter"]
        for flag in malformed[:_MAX_REPORTED_MALFORMED]:
            detail = _first_line(str(flag.get("detail", "")))
            reasons.append(f"  {flag.get('file')}: malformed frontmatter — {detail}")
        remaining = len(malformed) - _MAX_REPORTED_MALFORMED
        if remaining > 0:
            reasons.append(
                f"  ... and {remaining} more; every one is in the verify report."
            )

    ratio = (content_flags / notes_checked) if notes_checked else 0.0
    if notes_checked > 0 and ratio > fail_threshold:
        reasons.append(
            f"FAIL: {content_flags} content flag(s) across "
            f"{notes_checked} note(s) = {ratio:.1%}, over the "
            f"{fail_threshold:.0%} fail_threshold "
            f"({structural_flags} structural flag(s) in total; "
            f"{tooling_flags} tooling flag(s) did not count toward the verdict)."
        )

    if flags_by_check:
        families = list(flags_by_check.items())[:_MAX_REPORTED_FLAG_FAMILIES]
        rendered = ", ".join(f"{check} x{count}" for check, count in families)
        reasons.append(f"  top flags: {rendered}")

    return reasons


def _get_recent_notes(vault: Path, limit: int = 5) -> list[dict[str, Any]]:
    skip_stems = {"Home", "AGENTS"}
    notes = []
    for path in _iter_notes(vault):
        rel = _relative_path(path, vault)
        if rel.startswith("00 - MOC"):
            continue
        if path.stem in skip_stems:
            continue
        mtime = path.stat().st_mtime
        notes.append({"path": str(path), "mtime": mtime})
    notes.sort(key=lambda n: n["mtime"], reverse=True)
    return notes[:limit]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def verify(
    vault: Path,
    *,
    auto_fix: bool | None = None,
    fail_threshold: float | None = None,
    spec_processors: dict[str, Any] | None = None,
    required_frontmatter: list[str] | tuple[str, ...] | None = None,
    note_templates_dir: Path | None = None,
    spec_note_types: list[dict[str, Any]] | None = None,
) -> VerifyResult:
    """Run all structural checks on the vault.

    Args:
        vault: Directory to check — the vault's CORPUS directory, not the vault
               root, when the caller can resolve it.  System directories
               (``_pipeline``, ``_templates``, ``scripts``, every
               dot-directory) and config markdown are excluded regardless.
        auto_fix: Apply trivial auto-fixes (missing ``related``, ``status``).
                  ``None`` defers to spec config, then to the ``True`` default.
        fail_threshold: Fraction of checked notes flagged before verdict=FAIL.
                        ``None`` defers to spec config, then to ``0.20``.
        spec_processors: Optional processors section from SpecConfig.
        required_frontmatter: Frontmatter keys every note must carry.  ``None``
                              defers to spec config, then to the note templates
                              in ``note_templates_dir``, then to
                              :data:`DEFAULT_REQUIRED_FRONTMATTER`.
        note_templates_dir: The vault's ``_templates/`` directory — the note
                            format this vault actually declares (issue #226).
                            Defaults to a ``_templates`` sibling of *vault*
                            when one exists, so the corpus-scoped call the
                            pipeline makes can still find it.
        spec_note_types: The vault's declared ``note_types`` (from
                         ``_pipeline/spec-parse.json``), which give the
                         MOC-consistency check its folders.

    Precedence for every option is **explicit argument > spec config >
    what the vault declares > default**.  Before this was fixed,
    ``cfg.get(key, param)`` always found the key in ``PROCESSOR_DEFAULTS``, so
    an explicit argument — including the CLI's ``--no-fix`` and
    ``--fail-threshold`` — was silently discarded.

    Returns:
        VerifyResult with summary counts, verdict, and full report dict.
    """
    cfg = processor_config(spec_processors, "verify")
    if auto_fix is None:
        auto_fix = bool(cfg.get("auto_fix", True))
    if fail_threshold is None:
        fail_threshold = float(cfg.get("fail_threshold", 0.20))
    # ``vault`` is normally the corpus directory; the frontmatter-bearing
    # note-type templates the generator renders live one level up, beside it.
    template_dirs = (
        (note_templates_dir,)
        if note_templates_dir is not None
        else (vault / "_templates", vault.parent / "_templates")
    )
    required = _resolve_required_frontmatter(
        required_frontmatter=required_frontmatter,
        cfg=cfg,
        template_dirs=template_dirs,
    )
    moc_to_folders = _resolve_moc_map(spec_note_types)

    results: list[dict[str, Any]] = []
    all_note_names: set[str] = set()
    note_paths: dict[str, str] = {}
    exempt_names: set[str] = set()
    wikilinks_by_file: dict[str, list[str]] = {}
    incoming_links: dict[str, int] = {}
    notes_checked = 0
    auto_fixes_applied = 0
    malformed_count = 0
    errors: list[str] = []
    files_processed = 0

    # First pass: collect note names and wikilinks.  Generated index files are
    # scanned for their outgoing links (so the notes they index are not
    # reported as orphans) and are resolvable link TARGETS, but they never
    # enter ``note_paths`` — nothing downstream grades or flags them.
    for path in _iter_markdown(vault):
        files_processed += 1
        name = _note_name(path)
        rel = _relative_path(path, vault)
        all_note_names.add(name)
        if path.name not in GENERATED_INDEX_FILES:
            note_paths[name] = rel
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        scan_text = _strip_code_for_link_scan(text)
        raw_links = WIKILINK_RE.findall(scan_text)
        resolved = [_resolve_wikilink(lnk) for lnk in raw_links]
        resolved = [lnk for lnk in resolved if lnk]
        # Issue #287: dedupe within THIS note, case-folded (ADR-0005's own
        # identity for a link). A note mentioning [[X]] four times cites one
        # note, not four — left un-deduped, `incoming_links` counted raw
        # occurrences, so a single citing note could alone push a target past
        # the broken-wikilink "critical" threshold (>=4) or the hub threshold
        # (>=3), and `_find_broken_wikilinks` below emitted one flag per
        # occurrence, inflating `structural_flags` toward the FAIL threshold
        # for a single author habit, not four separate corroborating notes.
        distinct_by_key: dict[str, str] = {}
        for lnk in resolved:
            distinct_by_key.setdefault(_link_key(lnk), lnk)
        distinct_links = list(distinct_by_key.values())
        wikilinks_by_file[rel] = distinct_links
        for link in distinct_links:
            key = _link_key(link)
            incoming_links[key] = incoming_links.get(key, 0) + 1

    # Second pass: per-note checks.
    for path in _iter_notes(vault):
        notes_checked += 1
        rel = _relative_path(path, vault)
        metadata, error, body = _load_note(path)
        if error is not None:
            results.append(
                _flag(
                    "malformed_frontmatter",
                    rel,
                    f"Parse error: {error}",
                    "critical",
                )
            )
            malformed_count += 1
            continue
        if metadata is None:
            continue

        # The vault format's own opt-out.  An exempt note is still counted, is
        # still a link source and a link target, and is never graded, flagged
        # or rewritten (issue #227).
        if _is_exempt(metadata):
            exempt_names.add(_link_key(_note_name(path)))
            continue

        for fix in _check_missing_related(metadata, path, body, vault, auto_fix):
            results.append(fix)
            if fix["type"] == "auto_fix":
                auto_fixes_applied += 1

        for fix in _check_missing_status(metadata, path, body, vault, auto_fix):
            results.append(fix)
            if fix["type"] == "auto_fix":
                auto_fixes_applied += 1

        results.extend(_check_required_frontmatter(metadata, path, vault, required))

    # Cross-note checks.
    results.extend(
        _find_broken_wikilinks(all_note_names, wikilinks_by_file, incoming_links)
    )
    results.extend(_find_orphans(incoming_links, note_paths, exempt_names))
    results.extend(
        _check_moc_consistency(vault, note_paths, moc_to_folders, exempt_names)
    )

    structural_flags = sum(1 for r in results if r["type"] == "structural_flag")
    content_flags = sum(
        1
        for r in results
        if r["type"] == "structural_flag" and r.get("class") == CONTENT
    )
    tooling_flags = structural_flags - content_flags

    recent = _get_recent_notes(vault, limit=5)
    known_by_key = {_link_key(name): name for name in sorted(all_note_names)}
    hub_notes = {
        known_by_key[key]: count
        for key, count in incoming_links.items()
        if count >= 3 and key in known_by_key
    }

    # Verdict logic (honours fail_threshold).  Only CONTENT flags are measured
    # against the threshold: an orphan is a fact about the graph, not a defect
    # in a note, and counting orphans equally is what failed seven of eight
    # live vaults at once on 2026-09-01 (issue #225).
    if malformed_count > 0:
        verdict = "FAIL"
    elif notes_checked > 0 and (content_flags / notes_checked) > fail_threshold:
        verdict = "FAIL"
    elif structural_flags > 5:
        verdict = "WARN"
    else:
        verdict = "PASS"

    flags_by_check = _flags_by_check(results)

    # The verdict alone is not a reason.  Anything that made this vault FAIL
    # is stated here, bounded, so a caller that persists only ``errors`` still
    # records something actionable (issue #218).
    if verdict == "FAIL":
        errors.extend(
            _failure_reasons(
                results=results,
                flags_by_check=flags_by_check,
                notes_checked=notes_checked,
                structural_flags=structural_flags,
                content_flags=content_flags,
                tooling_flags=tooling_flags,
                malformed_count=malformed_count,
                fail_threshold=fail_threshold,
            )
        )

    report = {
        "timestamp": datetime.now().isoformat(),
        "vault": str(vault),
        "notes_checked": notes_checked,
        "auto_fixes_applied": auto_fixes_applied,
        "structural_flags": structural_flags,
        "content_flags": content_flags,
        "tooling_flags": tooling_flags,
        "malformed_count": malformed_count,
        "fail_threshold": fail_threshold,
        "required_frontmatter": list(required),
        "flags_by_check": flags_by_check,
        "verdict": verdict,
        "results": results,
        "recent_notes": recent,
        "hub_notes": hub_notes,
    }

    return VerifyResult(
        files_processed=files_processed,
        notes_checked=notes_checked,
        auto_fixes_applied=auto_fixes_applied,
        structural_flags=structural_flags,
        malformed_count=malformed_count,
        verdict=verdict,
        report=report,
        errors=tuple(errors),
        fail_threshold=fail_threshold,
        content_flags=content_flags,
        tooling_flags=tooling_flags,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli_main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Vault structural verification (Tier 0)")
    ap.add_argument("vault", type=Path, help="Vault root directory")
    ap.add_argument("--no-fix", action="store_true", help="Report only; no auto-fixes")
    ap.add_argument(
        "--fail-threshold",
        type=float,
        default=None,
        help="Fraction of flagged notes that triggers FAIL verdict (default: 0.20)",
    )
    ap.add_argument(
        "--json", action="store_true", help="Output full JSON report to stdout"
    )
    args = ap.parse_args(argv)

    if not args.vault.is_dir():
        print(f"Error: vault path does not exist: {args.vault}", file=sys.stderr)
        return 1

    result = verify(
        args.vault,
        auto_fix=False if args.no_fix else None,
        fail_threshold=args.fail_threshold,
    )

    if args.json:
        json.dump(result.report, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"Vault:           {args.vault}")
        print(f"Notes checked:   {result.notes_checked}")
        print(f"Structural flags:{result.structural_flags}")
        print(f"  content:       {result.content_flags} (these decide the verdict)")
        print(f"  tooling:       {result.tooling_flags}")
        print(f"Malformed:       {result.malformed_count}")
        print(f"Auto-fixes:      {result.auto_fixes_applied}")
        print(f"Verdict:         {result.verdict}")

    if result.errors:
        for e in result.errors:
            print(f"  {e}", file=sys.stderr)

    return 0 if result.verdict in ("PASS", "WARN") else 1


if __name__ == "__main__":
    sys.exit(_cli_main())
