#!/usr/bin/env python3
"""Validate vault notes against the quality bar.

Exit codes:
  0 — all checks passed
  1 — violations found (structural, reportable)
  2 — abort (vault directory missing, no data_vault/ in it, malformed frontmatter)

Checks performed:
  - frontmatter completeness (title, type, summary, tags, source_urls, related, created, updated)
  - summary ≤ 120 characters
  - source_urls non-empty
  - related wikilinks resolve to existing notes
  - word count ≥ 200 for non-MOC note types
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

REQUIRED_FIELDS = [
    "title",
    "type",
    "summary",
    "tags",
    "source_urls",
    "related",
    "created",
    "updated",
]
SUMMARY_MAX = 120
MIN_WORD_COUNT_DEFAULT = 200
MOC_TYPES = {"moc", "index"}


@dataclass
class Violation:
    file: Path
    field: str
    message: str


@dataclass
class Warning:
    file: Path
    field: str
    message: str


@dataclass
class DuplicateFinding:
    """A duplicate-note finding (spec 062 FR2). ``kind`` is ``"os_sibling"``
    (an OS-style ` N.md` fork of a canonical note) or ``"content_hash"``
    (byte-identical files). ``paths`` are the offending files."""

    kind: str
    paths: list[Path]
    message: str


# The ``Violation.field`` a duplicate note is reported under. This is a
# CONTRACT, not an implementation detail: the SG-004 gate wrapper
# (``pipeline/gates_step.py``) reads it out of this script's stdout to tell a
# constitutional Principle-VI violation (a FAIL — duplicate notes) apart from
# the style and hygiene findings that share the same non-zero exit code (a
# WARN). Renaming it silently downgrades Principle VI; the coupling is pinned
# by ``tests/pipeline/test_gates_step_sg004_duplicates.py``.
DUPLICATE_FIELD = "duplicate"


# Matches an OS-style numbered sibling stem: "Foo Bar 2" → base "Foo Bar".
_OS_SIBLING_RE = re.compile(r"^(?P<base>.+) (?P<n>\d+)$")

# Acronym derivation — self-contained copy of pipeline/wikilinks.py's algorithm
# (this script must run standalone, including vault-side copies that can't
# import from the package). Keep the two in sync.
_ACRONYM_STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "nor",
    "but",
    "of",
    "for",
    "to",
    "in",
    "on",
    "with",
    "by",
    "from",
    "at",
    "as",
    "per",
    "via",
    "into",
    "over",
}
_ACRONYM_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*")


# Spec 067 follow-up (2026-08-29): a derived acronym that is an English FUNCTION
# word must not become an alias. `_derive_acronym` accepted any >= 2 initials, so
# "Nemotron Omni" derived "NO" and a `no.md` alias note appeared in feeds-vault.
#
# The test is matchability, not spelling: `resolve_acronym_links` rewrites
# unresolved all-caps `[[TOKEN]]` references, and a function-word acronym is far
# more likely to be hit by accident than on purpose — `[[IT]]` is more plausibly
# the pronoun than Information Technology. That alias is knowingly sacrificed;
# the note itself is unaffected.
#
# Deliberately the CLOSED class only (pronouns, articles, prepositions,
# conjunctions, auxiliaries). Content words are NOT blocked, so "AI", "ML",
# "OS", "RAG" and friends keep working — none of them is an English word.
_ACRONYM_FUNCTION_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "nor",
        "but",
        "so",
        "yet",
        "for",
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "up",
        "as",
        "if",
        "no",
        "not",
        "is",
        "am",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "do",
        "does",
        "did",
        "done",
        "has",
        "have",
        "had",
        "he",
        "him",
        "his",
        "she",
        "her",
        "hers",
        "it",
        "its",
        "me",
        "my",
        "we",
        "us",
        "our",
        "you",
        "your",
        "they",
        "them",
        "this",
        "that",
        "these",
        "those",
        "who",
        "whom",
        "which",
        "what",
        "all",
        "any",
        "each",
        "both",
        "few",
        "more",
        "most",
        "some",
        "such",
        "can",
        "may",
        "might",
        "must",
        "shall",
        "will",
        "would",
        "could",
        "with",
        "from",
        "into",
        "over",
        "than",
        "then",
        "when",
        "where",
        "why",
        "how",
        "out",
        "off",
        "own",
        "too",
        "very",
        "one",
        "go",
    }
)


def _derive_acronym(title: str) -> str | None:
    head = re.split(r"[(\u2014\u2013:]", title, maxsplit=1)[0]
    initials = [
        w[0].upper()
        for w in _ACRONYM_WORD_RE.findall(head)
        if w.lower() not in _ACRONYM_STOPWORDS
    ]
    if len(initials) < 2:
        return None
    acronym = "".join(initials)
    if acronym.lower() in _ACRONYM_FUNCTION_WORDS:
        return None
    return acronym


def find_duplicate_notes(data_vault: Path) -> list[DuplicateFinding]:
    """Detect duplicate notes under ``data_vault`` (spec 062 FR2 / 063 GA-002).

    Two classes:
      - ``os_sibling`` — a ` N.md` fork (e.g. ``Risk 2.md``) whose base
        (``Risk.md``) also exists in the same folder.
      - ``content_hash`` — two or more notes with byte-identical content.

    Returns structured findings (empty when the vault is clean).
    """
    if not data_vault.is_dir():
        return []
    findings: list[DuplicateFinding] = []

    def _is_note(p: Path) -> bool:
        if p.name.startswith("_"):
            return False
        try:
            parts = p.relative_to(data_vault).parts
        except ValueError:
            return True
        # Skip generator-owned template placeholders (byte-identical by design).
        return "_templates" not in parts

    notes = [p for p in sorted(data_vault.rglob("*.md")) if _is_note(p)]

    # OS-style numbered siblings.
    for p in notes:
        m = _OS_SIBLING_RE.match(p.stem)
        if not m:
            continue
        base = p.with_name(f"{m.group('base')}.md")
        if base.exists():
            findings.append(
                DuplicateFinding(
                    kind="os_sibling",
                    paths=[base, p],
                    message=f"OS-style duplicate '{p.name}' of '{base.name}'",
                )
            )

    # Byte-identical content duplicates.
    by_hash: dict[str, list[Path]] = {}
    for p in notes:
        try:
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
        except OSError:
            continue
        by_hash.setdefault(digest, []).append(p)
    for digest, paths in by_hash.items():
        if len(paths) > 1:
            findings.append(
                DuplicateFinding(
                    kind="content_hash",
                    paths=sorted(paths),
                    message=(
                        "byte-identical content: "
                        + ", ".join(p.name for p in sorted(paths))
                    ),
                )
            )
    return findings


def _build_acronym_map(vault: Path) -> tuple[dict[str, str], list[str]]:
    """``(acronym_map, ambiguous)`` derived from note titles (FR3 / wikilinks.py).

    Mirrors ``pipeline/wikilinks.build_acronym_map`` (kept self-contained for the
    standalone script). An acronym claimed by two notes is dropped (ambiguous).
    """
    data = vault / "data_vault"
    if not data.is_dir():
        return {}, []
    claims: dict[str, set[str]] = {}
    real_stems: set[str] = set()
    for note in sorted(data.rglob("*.md")):
        if note.name.startswith("_"):
            continue
        fm, _body, err = _parse_frontmatter(note)
        if err or fm is None:
            # Not a claimant, but still a real note a link can point at.
            real_stems.add(note.stem.lower())
            continue
        if str(fm.get("note_type", "")).strip().lower() == "alias":
            continue
        stem = note.stem.lower()
        real_stems.add(stem)
        candidates: set[str] = set()
        aliases = fm.get("aliases")
        if isinstance(aliases, list):
            for a in aliases:
                if isinstance(a, str) and a.strip():
                    candidates.add(a.strip().upper())
        derived = _derive_acronym(str(fm.get("title") or stem.replace("-", " ")))
        if derived:
            candidates.add(derived)
        for acro in candidates:
            claims.setdefault(acro, set()).add(stem)
    acronym_map: dict[str, str] = {}
    ambiguous: list[str] = []
    for acro, stems in claims.items():
        if acro.lower() in real_stems:
            # The acronym IS a real note's stem (any note, not only a claimant):
            # ``[[CAP]]`` resolves to ``cap.md`` directly. Redirect stubs excluded.
            continue
        if len(stems) == 1:
            acronym_map[acro] = next(iter(stems))
        else:
            ambiguous.append(acro)
    return acronym_map, sorted(ambiguous)


def _parse_frontmatter(path: Path) -> tuple[dict | None, str, str | None]:
    """Return (frontmatter_dict, body, error_message_or_None)."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None, text, "missing YAML frontmatter"
    # The closing delimiter is a `---` LINE, as the framework's canonical parser
    # (``vault/frontmatter.py``, not importable from this standalone script)
    # reads it. A `---` inside a value (a slug URL such as `kafka---a-guide`)
    # is not one: splitting on the first substring cut the frontmatter there.
    lines = text.split("\n")
    close = next((i for i in range(1, len(lines)) if lines[i].rstrip() == "---"), None)
    if close is None:
        return None, text, "frontmatter delimiters malformed"
    try:
        fm = yaml.safe_load("\n".join(lines[1:close])) or {}
    except yaml.YAMLError as e:
        return None, text, f"YAML parse error: {e}"
    if not isinstance(fm, dict):
        return None, text, "frontmatter is not a mapping"
    # The body starts right after the closing `---`, its newline included.
    return fm, "".join("\n" + line for line in lines[close + 1 :]), None


def _vault_note_stems(vault: Path) -> set[str]:
    """All resolvable wikilink targets in `data_vault/`.

    For each note file we register *both* the bare filename stem and
    every relative-path variant (`Folder/Note`, `01 - Foo/Bar`, etc.)
    so wikilinks of the form `[[Folder/Note]]` resolve correctly.

    B.4 (post-mortem 2026-05-30): pre-0.7.0 this returned only bare
    stems. On a vault that uses the recommended folder structure this
    flagged thousands of perfectly valid path-prefixed wikilinks as
    "file not found" — every cycle reported 2k+ SG-004 WARNs that
    were entirely a validator artefact. Comparison is case-insensitive
    because Obsidian-style wikilinks tolerate case differences.
    """
    data = vault / "data_vault"
    if not data.exists():
        return set()
    out: set[str] = set()
    for p in data.rglob("*.md"):
        # Bare stem (matches `[[Note]]`).
        out.add(p.stem.lower())
        try:
            rel = p.relative_to(data).with_suffix("")
        except ValueError:
            continue
        rel_posix = rel.as_posix().lower()
        if rel_posix:
            out.add(rel_posix)
    return out


def _lifecycle_created_at_cycle_warnings(path: Path, fm: dict) -> list[Warning]:
    """R-001 / 017: optional field — warn only, never fail."""
    warnings: list[Warning] = []
    life = fm.get("lifecycle")
    if life is None:
        warnings.append(
            Warning(
                path,
                "lifecycle.created_at_cycle",
                "missing (legacy vaults may omit this field)",
            )
        )
        return warnings
    if not isinstance(life, dict):
        warnings.append(
            Warning(
                path,
                "lifecycle.created_at_cycle",
                "lifecycle must be a mapping when present",
            )
        )
        return warnings
    val = life.get("created_at_cycle")
    if val is None:
        warnings.append(
            Warning(
                path,
                "lifecycle.created_at_cycle",
                "missing (legacy vaults may omit this field)",
            )
        )
        return warnings
    ok_int = isinstance(val, int) and not isinstance(val, bool)
    if not ok_int or val < 1:
        warnings.append(
            Warning(
                path,
                "lifecycle.created_at_cycle",
                f"expected integer ≥ 1, got {val!r}",
            )
        )
    return warnings


def _related_target_resolves(
    target: str,
    known_stems: set[str],
    acronym_map: dict[str, str] | None = None,
) -> bool:
    """Whether a `related` wikilink target resolves to a note.

    Shared with ``fix_wikilinks.py`` so the fixer removes exactly what this
    validator reports, and nothing it accepts.
    """
    # B.4: try bare stem AND full relative path AND last path
    # segment — `[[Folder/Note]]` should resolve when `Note.md`
    # exists under any folder, not just the declared one. Case
    # is normalised at lookup time.
    lookup_keys = {target.lower()}
    if "/" in target:
        lookup_keys.add(target.rsplit("/", 1)[-1].lower())
    # Natural-language wikilinks use spaces ([[Outcome Matrix Order
    # Vector Calculation]]) while filenames are snake_case (or hyphen-
    # case). Try space->_ and space->- variants so a title-style
    # related link resolves to its on-disk stem instead of reporting a
    # spurious "file not found" (rc5 reference-vault finding — these made up
    # the bulk of the non-alias violations and drove note quarantines).
    for key in list(lookup_keys):
        if " " in key:
            lookup_keys.add(key.replace(" ", "_"))
            lookup_keys.add(key.replace(" ", "-"))
    # FR3: an all-caps token that maps to a known stem via the
    # title-derived acronym map is resolvable (a redirect stub
    # resolves it), so it is NOT a dead link.
    if acronym_map and target.upper() in acronym_map:
        return True
    return any(k in known_stems for k in lookup_keys)


def _check_note(
    path: Path,
    vault: Path,
    known_stems: set[str],
    acronym_map: dict[str, str] | None = None,
) -> tuple[list[Violation], list[Warning]]:
    violations: list[Violation] = []
    warnings: list[Warning] = []
    fm, body, err = _parse_frontmatter(path)
    if err or fm is None:
        violations.append(Violation(path, "frontmatter", err or "unknown"))
        return violations, warnings

    warnings.extend(_lifecycle_created_at_cycle_warnings(path, fm))

    # Alias/redirect stubs are intentionally minimal and MUST be exempt from
    # the full-note schema. ``pipeline/wikilinks.resolve_acronym_links`` writes
    # one per title-derived acronym (``note_type: alias`` + ``redirect_to`` +
    # ``verifier_status: exempt``), and ``_build_acronym_map`` already skips
    # them here. Without this matching skip the validator applied the 8-field +
    # 200-word schema to every generated stub and reported ~8 spurious
    # violations apiece — the dominant driver of the rc5 reference-vault 113→246
    # violation growth (the framework was failing notes it generates itself).
    if str(fm.get("note_type", "")).strip().lower() == "alias":
        return violations, warnings

    for field in REQUIRED_FIELDS:
        if field not in fm:
            violations.append(Violation(path, field, "required field missing"))

    summary = fm.get("summary", "")
    if isinstance(summary, str) and len(summary) > SUMMARY_MAX:
        violations.append(
            Violation(
                path,
                "summary",
                f"{len(summary)} chars (limit: {SUMMARY_MAX})",
            )
        )

    sources = fm.get("source_urls")
    if sources is not None and (not isinstance(sources, list) or len(sources) == 0):
        violations.append(
            Violation(path, "source_urls", "empty (at least one required)")
        )

    related = fm.get("related") or []
    if isinstance(related, list):
        for link in related:
            target = str(link).strip("[]").strip()
            if not target:
                continue
            if not _related_target_resolves(target, known_stems, acronym_map):
                violations.append(
                    Violation(
                        path,
                        "related",
                        f"[[{target}]] — file not found",
                    )
                )

    note_type = str(fm.get("type", "")).lower()
    if note_type not in MOC_TYPES:
        words = len(body.split())
        if words < MIN_WORD_COUNT_DEFAULT:
            violations.append(
                Violation(
                    path,
                    "word_count",
                    f"{words} words (min: {MIN_WORD_COUNT_DEFAULT})",
                )
            )

    return violations, warnings


def validate(vault: Path) -> tuple[list[Violation], list[Warning]]:
    """Return (violations, warnings) for all notes under data_vault/."""
    if not vault.exists() or not vault.is_dir():
        raise FileNotFoundError(f"vault directory not found: {vault}")
    data = vault / "data_vault"
    if not data.is_dir():
        # A folder with no corpus is a wrong path, not a vault with nothing to
        # check: answering "all checks passed" for it is a pass over zero notes.
        raise FileNotFoundError(f"data_vault directory not found: {data}")

    known_stems = _vault_note_stems(vault)
    acronym_map, ambiguous = _build_acronym_map(vault)
    violations: list[Violation] = []
    warnings: list[Warning] = []
    for note in sorted(data.rglob("*.md")):
        if _is_scaffold_path(note, data):
            continue
        v, w = _check_note(note, vault, known_stems, acronym_map)
        violations.extend(v)
        warnings.extend(w)

    # FR2: OS-style ` N.md` siblings + byte-identical content duplicates.
    for finding in find_duplicate_notes(data):
        violations.append(
            Violation(finding.paths[-1], DUPLICATE_FIELD, finding.message)
        )

    # FR3: ambiguous acronyms are never auto-linked — surface them as WARNs.
    for acro in ambiguous:
        warnings.append(
            Warning(data, "acronym", f"acronym '{acro}' is ambiguous — not linked")
        )
    return violations, warnings


def _is_scaffold_path(note: Path, data_root: Path) -> bool:
    """Skip generator-owned files that don't carry note frontmatter.

    Excluded:

    - ``_index.md`` / ``_concepts.md`` / ``_graph.md`` and any other
      underscore-prefixed file directly under ``data_vault/`` (these are
      re-built each cycle by ``research_framework.vault.indexer``).
    - Anything under ``data_vault/_templates/`` (Jinja-style note-type
      templates with placeholder tokens, not real notes).

    These files were silently producing 16+ "missing YAML frontmatter"
    FAILs per cycle in v0.2.20, which Step 4 reported but the cycle
    runner correctly ignored — making the report a noise source that
    masked real violations on agent-written notes. Filtering at the
    walk level keeps the report focused on note quality.
    """
    try:
        rel = note.relative_to(data_root)
    except ValueError:
        return False
    if "_templates" in rel.parts:
        return True
    # Underscore-prefixed files at the data-vault root are scaffold artefacts
    # (`_index.md`, `_concepts.md`, `_graph.md`). Deeper-nested files starting
    # with `_` (e.g. a category's `_overview.md`) are still validated — only
    # the root-level generator-owned set is skipped.
    if len(rel.parts) == 1 and rel.parts[0].startswith("_"):
        return True
    return False


def format_warnings(warnings: list[Warning], vault: Path) -> str:
    lines: list[str] = []
    for w in warnings:
        try:
            rel = w.file.relative_to(vault)
        except ValueError:
            rel = w.file
        lines.append(f"WARN  {rel}")
        lines.append(f"      {w.field}: {w.message}")
        lines.append("")
    return "\n".join(lines)


def format_violations(violations: list[Violation], vault: Path) -> str:
    """Human-readable report."""
    lines: list[str] = []
    for v in violations:
        try:
            rel = v.file.relative_to(vault)
        except ValueError:
            rel = v.file
        lines.append(f"FAIL  {rel}")
        lines.append(f"      {v.field}: {v.message}")
        lines.append("")
    if violations:
        lines.append(
            f"{len(violations)} violation(s) found. Fix before proceeding to Phase 3."
        )
    else:
        lines.append("all checks passed")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate vault notes against the quality bar."
    )
    parser.add_argument("vault", type=Path, help="Path to vault root directory")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="No-op for validator (kept for script-suite uniformity)",
    )
    args = parser.parse_args()

    try:
        violations, warnings = validate(args.vault)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    print(format_violations(violations, args.vault))
    if warnings:
        print()
        print(format_warnings(warnings, args.vault).rstrip())
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
