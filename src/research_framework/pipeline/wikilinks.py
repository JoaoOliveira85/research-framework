"""Wikilink normalization \u2014 cycle-time auto-fix for case-mismatch links.

Why this lives separately from ``scripts/vault_health.py``:

``vault_health.py`` is the heavy graph-repair tool. It can CREATE stub
notes, PRUNE orphan ``related`` entries, and rewrite case mismatches \u2014
all of which require human judgement. It's run on-demand
(``--apply``).

This module is the LIGHT auto-fix that runs at the end of every cycle.
It does ONE thing: rewrites case-mismatched body and ``related``
wikilinks to match the existing filename stem. It does NOT create
notes, NOT delete orphan entries, and NOT touch wikilinks inside code
fences (which often demonstrate the WRONG form as a counter-example).

Why this is needed (user audit 2026-05-18):

The note-writer agent emits natural-language wikilinks
(``[[Cassandra]]``, ``[[OMS]]``, ``[[Kafka]]``) but the framework's
filename convention is lowercase-snake. Obsidian and the framework's
wikilink resolver treat ``[[Cassandra]]`` and ``cassandra.md`` as
distinct references, fragmenting the vault graph. The
reference-vault-0.2.30 audit found 207 such broken links. Wiring this
helper into the cycle ensures each cycle leaves the graph clean
instead of accumulating drift.

Contract:

- :func:`auto_fix_moved_wikilinks` is idempotent: re-running on a clean
  vault is a no-op and returns ``0``.
- It returns the count of FILES modified (not the count of individual
  link fixes), suitable for a one-line log entry.
- It is safe to call on an empty vault or before ``data_vault/`` exists.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from research_framework.vault.corpus import corpus_dir
from research_framework.vault.frontmatter import (
    FrontmatterParseError,
    parse_frontmatter_str,
)

_LOG = logging.getLogger(__name__)

# Matches inline wikilinks like ``[[Target]]`` or ``[[Target|alias text]]``.
# The ``([^\]\|]+?)`` captures the target (no ``]`` or ``|``); the optional
# ``(\|[^\]]*)?`` captures any alias including the leading pipe.
_WIKILINK_RE = re.compile(r"\[\[([^\]\|]+?)(\|[^\]]*)?\]\]")

# Matches a fenced code block delimiter. Used to skip content INSIDE fences
# during normalization \u2014 wikilinks in code fences are typically
# counter-examples ("don't do this") or actual code that uses double-bracket
# syntax. Rewriting them would corrupt documentation.
_FENCE_RE = re.compile(r"^```")


def _vault_note_stems(vault: Path) -> set[str]:
    """Return the lowercase stems of every markdown note under ``data_vault/``.

    Used as the lookup table for case-mismatch detection.
    """
    data = corpus_dir(vault)
    if not data.exists():
        return set()
    return {p.stem for p in data.rglob("*.md") if not p.name.startswith("_")}


def _parse_frontmatter(text: str) -> tuple[dict[str, Any] | None, str]:
    """Split a note into ``(frontmatter, body)``. Returns ``(None, text)``
    when no YAML frontmatter is present.
    """
    try:
        fm, body = parse_frontmatter_str(text)
    except FrontmatterParseError:
        return None, text
    if not fm:
        return None, body
    return fm, body


def _serialize_note(fm: dict[str, Any], body: str) -> str:
    """Re-emit a note from its parsed frontmatter + body. Preserves the
    ``---``-delimited YAML block format used by the rest of the framework.
    """
    fm_text = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).rstrip()
    return f"---\n{fm_text}\n---\n{body}"


def _resolve_titlecase_stem(target: str, stems: set[str]) -> str | None:
    """Resolve a wikilink ``target`` to an existing note stem.

    Tolerates two natural-language-vs-filename mismatches:

    - **case** — ``Cassandra`` → ``cassandra`` (the original 0.2.31 fix);
    - **space↔separator** — ``Outcome Matrix Order Vector Calculation`` →
      ``outcome_matrix_order_vector_calculation`` (rc5 reference-vault finding:
      title-style ``related``/body links never resolved to snake_case files,
      producing bulk "file not found" violations and note quarantines).

    Only variants that ACTUALLY exist in ``stems`` are returned, so a link to a
    genuinely missing note is left untouched (returns ``None``). Hyphen-case
    vaults are supported alongside snake_case.
    """
    lower = target.lower()
    for cand in (lower, lower.replace(" ", "_"), lower.replace(" ", "-")):
        if cand in stems:
            return cand
    return None


def _normalize_body_wikilinks(body: str, stems: set[str]) -> tuple[str, int]:
    """Rewrite case-mismatched wikilinks in note BODY text.

    Walks the body line-by-line so we can track code-fence state and
    skip ``[[...]]`` tokens inside fenced blocks (per contract).

    Returns ``(new_body, fixes_made)``.
    """
    if not body or not stems:
        return body, 0

    out_lines: list[str] = []
    fixes = 0
    in_fence = False

    for line in body.splitlines(keepends=True):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out_lines.append(line)
            continue
        if in_fence:
            out_lines.append(line)
            continue

        def _maybe_rewrite(match: re.Match[str]) -> str:
            nonlocal fixes
            target = match.group(1).strip()
            alias = match.group(2) or ""
            resolved = _resolve_titlecase_stem(target, stems)
            if resolved is not None and resolved != target:
                fixes += 1
                # Preserve the human-readable rendering when collapsing a
                # multi-word title to a snake_case stem (no existing alias):
                # [[Outcome Matrix …]] → [[outcome_matrix_…|Outcome Matrix …]].
                # Pure case fixes keep the bare form (per 0.2.31 contract).
                if not alias and " " in target:
                    return f"[[{resolved}|{target}]]"
                return f"[[{resolved}{alias}]]"
            return match.group(0)

        out_lines.append(_WIKILINK_RE.sub(_maybe_rewrite, line))

    return "".join(out_lines), fixes


def _normalize_related_entries(related: Any, stems: set[str]) -> tuple[list[Any], int]:
    """Rewrite case-mismatched entries in the frontmatter ``related`` list.

    Tolerates entries written as either bare strings (``Foo``) or
    wikilink-wrapped strings (``[[Foo]]``). Returns the rewritten list
    along with the number of entries changed.
    """
    if not isinstance(related, list) or not stems:
        return related if isinstance(related, list) else [], 0

    fixes = 0
    new_related: list[Any] = []
    for entry in related:
        if not isinstance(entry, str):
            new_related.append(entry)
            continue
        stripped = entry.strip()
        # Preserve original wrapping style: [[X]] or bare X.
        wrapped = stripped.startswith("[[") and stripped.endswith("]]")
        target = stripped.strip("[]").strip()
        resolved = _resolve_titlecase_stem(target, stems)
        if resolved is not None and resolved != target:
            new_related.append(f"[[{resolved}]]" if wrapped else resolved)
            fixes += 1
        else:
            new_related.append(entry)
    return new_related, fixes


# Title words too generic to contribute an acronym initial. Mirrors the
# self-contained copy in ``scripts/validate_vault.py`` (scripts can't import
# from ``src/``); keep the two in sync.
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


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*")


def _derive_acronym(title: str) -> str | None:
    """Initials of the significant words of ``title`` (e.g. "Order Engine
    Customer Data Handler" → "OECDH"). Returns ``None`` if < 2 initials.

    Only the head of the title (before the first ``(``/``—``/``–``/``:``) is
    used so trailing descriptors don't pollute the acronym.
    """
    head = re.split(r"[(\u2014\u2013:]", title, maxsplit=1)[0]
    initials = [
        w[0].upper()
        for w in _WORD_RE.findall(head)
        if w.lower() not in _ACRONYM_STOPWORDS
    ]
    if len(initials) < 2:
        return None
    acronym = "".join(initials)
    if acronym.lower() in _ACRONYM_FUNCTION_WORDS:
        return None
    return acronym


def _derive_acronym_or_upper(token: str) -> str:
    """The acronym a ``[[TOKEN]]`` refers to: derived initials if multi-word,
    else the bare token upper-cased (so ``"CAP"`` → ``"CAP"``)."""
    return _derive_acronym(token) or token.strip().upper()


def title_self_acronyms(title: str) -> set[str]:
    """Acronyms that refer to a note's OWN title (067 FR2/FR3).

    Returns the title's derived initials (``"Cache-Aside Pattern" → "CAP"``)
    **plus** any all-caps word in the title head (``"CAP Theorem" → {"CAP",
    "CT"}``). The all-caps-word case is the one that bit rc7: ``CAP Theorem``'s
    initials are ``CT``, but the note's own subject acronym is the literal
    leading word ``CAP`` — which the sibling ``cache-aside pattern`` (also
    ``CAP``) was wrongly rewriting it to.
    """
    head = re.split(r"[(\u2014\u2013:]", title, maxsplit=1)[0]
    out: set[str] = set()
    derived = _derive_acronym(title)
    if derived:
        out.add(derived)
    for w in _WORD_RE.findall(head):
        if len(w) >= 2 and w.isupper():
            out.add(w)
    return out


def first_body_wikilink(body: str) -> str | None:
    """The first ``[[TOKEN]]`` target in ``body`` outside code fences (067 FR3)."""
    if not body:
        return None
    in_fence = False
    for line in body.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _WIKILINK_RE.search(line)
        if m:
            return m.group(1).strip()
    return None


def build_acronym_map(vault: Path) -> tuple[dict[str, str], list[str]]:
    """Return ``(acronym_map, ambiguous)`` for the vault (spec 062 FR3, D4).

    Deterministic: derived from note titles (∪ explicit note ``aliases:``), not
    from LLM whim. ``acronym_map`` maps an UPPER-CASE acronym to its canonical
    note stem. An acronym claimed by two distinct notes is **dropped** (added to
    ``ambiguous``) so we never produce a wrong link.
    """
    data = corpus_dir(vault)
    if not data.is_dir():
        return {}, []

    claims: dict[str, set[str]] = {}
    real_stems: set[str] = set()
    for note in sorted(data.rglob("*.md")):
        if note.name.startswith("_"):
            continue
        try:
            text = note.read_text(encoding="utf-8")
        except OSError:
            continue
        fm, _body = _parse_frontmatter(text)
        stem = note.stem.lower()
        candidates: set[str] = set()
        title = ""
        if fm:
            if str(fm.get("note_type", "")).strip().lower() == "alias":
                continue  # redirect stubs don't seed the map
            title = str(fm.get("title") or "")
            aliases = fm.get("aliases")
            if isinstance(aliases, list):
                for a in aliases:
                    if isinstance(a, str) and a.strip():
                        candidates.add(a.strip().upper())
        real_stems.add(stem)
        derived = _derive_acronym(title or stem.replace("-", " "))
        if derived:
            candidates.add(derived)
        for acro in candidates:
            claims.setdefault(acro, set()).add(stem)

    acronym_map: dict[str, str] = {}
    ambiguous: list[str] = []
    for acro, stems in claims.items():
        if acro.lower() in real_stems:
            # The acronym already IS a note's stem — ``[[CAP]]`` resolves to
            # ``cap.md`` directly. Any real note counts, not only the ones
            # claiming the acronym: checking the claimants alone let a sibling
            # ("Cache-Aside Pattern") capture every link to ``cap.md``. The
            # acronym's own redirect stub is not a real note.
            continue
        if len(stems) == 1:
            acronym_map[acro] = next(iter(stems))
        else:
            ambiguous.append(acro)
    return acronym_map, sorted(ambiguous)


def _rewrite_acronym_body(
    body: str,
    acronym_map: dict[str, str],
    *,
    self_stem: str | None = None,
    self_acronyms: frozenset[str] | set[str] = frozenset(),
    ambiguous: frozenset[str] | set[str] = frozenset(),
) -> tuple[str, int]:
    """Rewrite unresolved all-caps ``[[TOKEN]]`` to the mapped canonical stem.

    Skips fenced code blocks (same contract as case normalisation).

    067 FR2 — **self-title protection**: a ``[[TOKEN]]`` whose acronym is the
    containing note's OWN title-acronym (``self_acronyms``) is NEVER rewritten to
    a sibling expansion (``mapping[A] != self_stem``). Instead the link is reduced
    to plain text (the acronym kept, the brackets dropped) so the note can't have
    its own subject renamed — the exact rc7 ``[[cache-aside pattern]] Theorem``
    corruption. This is idempotent: once plain-texted there is no token to match.

    067 FR2 (stale re-evaluation) — an all-caps ``[[TOKEN]]`` whose acronym is now
    ``ambiguous`` (≥2 title claims) is likewise reduced to plain text: a once-valid
    auto-link must not survive as a wrong/dead link after a sibling note made the
    acronym ambiguous.
    """
    if not body or (not acronym_map and not ambiguous):
        return body, 0
    ambiguous_upper = {a.upper() for a in ambiguous}
    out_lines: list[str] = []
    fixes = 0
    in_fence = False
    for line in body.splitlines(keepends=True):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out_lines.append(line)
            continue
        if in_fence:
            out_lines.append(line)
            continue

        def _maybe(match: re.Match[str]) -> str:
            nonlocal fixes
            target = match.group(1).strip()
            alias = match.group(2) or ""
            upper = target.upper()
            if target != upper:
                # 067 FR2 (retroactive heal): the corruption that actually shipped
                # in rc7 was the acronym already *expanded in full* —
                # ``The CAP Theorem`` rewritten to ``The [[cache-aside pattern]]
                # Theorem``. The all-caps branch below never sees it (the link text
                # is the sibling's multi-word title, not ``CAP``). Detect it by the
                # link's *derived* acronym: a bare ``[[phrase]]`` whose initials are
                # one of THIS note's own title-acronyms but resolve to a different
                # note is the note renaming its own subject → restore the plain
                # acronym. Only bare links — an explicit ``|alias`` is an author
                # display choice we never second-guess. Idempotent: once plain-texted
                # there is no ``[[...]]`` left to match.
                if alias or not self_acronyms or self_stem is None:
                    return match.group(0)
                derived = _derive_acronym(target)
                if derived and derived in self_acronyms and target.lower() != self_stem:
                    fixes += 1
                    return derived
                return match.group(0)
            if upper in ambiguous_upper:
                # FR2 re-eval: now-ambiguous acronym — keep plain text.
                fixes += 1
                return target
            mapped = acronym_map.get(upper)
            if mapped:
                if upper in self_acronyms and mapped != self_stem:
                    # FR2: would rename this note's own title — keep plain text.
                    fixes += 1
                    return target
                fixes += 1
                return f"[[{mapped}{alias}]]"
            return match.group(0)

        out_lines.append(_WIKILINK_RE.sub(_maybe, line))
    return "".join(out_lines), fixes


def _write_redirect_stub(
    vault: Path,
    acronym: str,
    stem: str,
    *,
    ambiguous: frozenset[str] | set[str] = frozenset(),
) -> bool:
    """Idempotently write ``data_vault/<folder>/<acronym>.md`` as an alias node.

    Placed in the target note's folder. Returns True if it created/changed the
    stub, False if already content-stable.

    067 FR1 — single-expansion-only: a no-op when ``acronym`` is currently
    ambiguous (≥2 title claims), so an ambiguous acronym never gets a redirect
    stub (the caller already excludes ambiguous acronyms from ``acronym_map``;
    this guard makes the invariant explicit + defensible in isolation).
    """
    if acronym.upper() in {a.upper() for a in ambiguous}:
        return False
    data = corpus_dir(vault)
    target = None
    for p in data.rglob(f"{stem}.md"):
        target = p
        break
    folder = target.parent if target else data
    stub_path = folder / f"{acronym.lower()}.md"
    # An alias is free frontmatter text: `CI/CD` or `../x` would name a path
    # outside the folder. Refuse rather than write there.
    if stub_path.parent != folder:
        _LOG.warning(
            "acronym %r is not a plain file name; no redirect stub written", acronym
        )
        return False
    content = (
        "---\n"
        f"title: {acronym}\n"
        "note_type: alias\n"
        f"redirect_to: {stem}\n"
        "verifier_status: exempt\n"
        "---\n"
        f"See [[{stem}]].\n"
    )
    try:
        if stub_path.exists():
            existing = stub_path.read_text(encoding="utf-8")
            if existing == content:
                return False
            # A stub may replace a stub; it must never replace a real note
            # (`aliases: [Kubernetes]` elsewhere vs. an existing kubernetes.md).
            existing_fm, _ = _parse_frontmatter(existing)
            if str((existing_fm or {}).get("note_type", "")).strip().lower() != (
                "alias"
            ):
                _LOG.warning(
                    "acronym %r would overwrite the note %s; no redirect stub written",
                    acronym,
                    stub_path,
                )
                return False
    except OSError:
        pass
    from .atomic_write import write_text as _aw_text

    _aw_text(stub_path, content)
    return True


def resolve_acronym_links(vault: Path) -> int:
    """Spec 062 FR3: make every title-derived acronym resolvable.

    Builds the deterministic acronym map, rewrites unresolved all-caps
    ``[[TOKEN]]`` references to the canonical stem, and generates an idempotent
    redirect stub per acronym. Returns the count of files written (body rewrites
    + new/changed stubs). Idempotent on a clean vault (returns 0).
    """
    data = corpus_dir(vault)
    if not data.is_dir():
        return 0
    acronym_map, ambiguous = build_acronym_map(vault)
    ambiguous_set = frozenset(a.upper() for a in ambiguous)
    if not acronym_map and not ambiguous_set:
        return 0

    files_written = 0
    for note in sorted(data.rglob("*.md")):
        if note.name.startswith("_"):
            continue
        try:
            text = note.read_text(encoding="utf-8")
        except OSError:
            continue
        fm, body = _parse_frontmatter(text)
        self_stem = note.stem.lower()
        if fm is None:
            self_acronyms = title_self_acronyms(note.stem.replace("-", " "))
            new_body, fixes = _rewrite_acronym_body(
                text,
                acronym_map,
                self_stem=self_stem,
                self_acronyms=self_acronyms,
                ambiguous=ambiguous_set,
            )
            if fixes:
                from .atomic_write import write_text as _aw_text

                _aw_text(note, new_body)
                files_written += 1
            continue
        if str(fm.get("note_type", "")).strip().lower() == "alias":
            # Redirect stubs carry an auto-generated ``See [[<expansion>]].`` body
            # whose link initials trivially match the stub's own acronym title —
            # the reverse-map heal must never fire there (it would rewrite the
            # redirect target back to the bare acronym). Stub re-point / orphan is
            # handled by ``_write_redirect_stub`` / ``_orphan_ambiguous_stubs``.
            continue
        title = str(fm.get("title") or note.stem.replace("-", " "))
        self_acronyms = title_self_acronyms(title)
        new_body, body_fixes = _rewrite_acronym_body(
            body,
            acronym_map,
            self_stem=self_stem,
            self_acronyms=self_acronyms,
            ambiguous=ambiguous_set,
        )
        new_related, rel_fixes = _normalize_acronym_related(
            fm.get("related"), acronym_map
        )
        if body_fixes == 0 and rel_fixes == 0:
            continue
        if rel_fixes:
            fm["related"] = new_related
        from .atomic_write import write_text as _aw_text

        _aw_text(note, _serialize_note(fm, new_body))
        files_written += 1

    for acro, stem in acronym_map.items():
        if _write_redirect_stub(vault, acro, stem, ambiguous=ambiguous_set):
            files_written += 1

    # FR2 re-eval: orphan stale alias stubs whose acronym is now ambiguous.
    files_written += _orphan_ambiguous_stubs(vault, ambiguous_set)
    return files_written


def _orphan_ambiguous_stubs(vault: Path, ambiguous: frozenset[str] | set[str]) -> int:
    """Delete ``note_type: alias`` stubs whose acronym is now ambiguous (067 FR2).

    A redirect stub is detritus once its acronym resolves to ≥2 titles — it can
    only point at one of them. Deleting it (rather than re-pointing) is the safe
    default; the operator-facing ``vault wikilinks`` sweep handles re-point vs
    delete with the full inbound-reference analysis.
    """
    if not ambiguous:
        return 0
    data = corpus_dir(vault)
    removed = 0
    for stub in sorted(data.rglob("*.md")):
        if stub.name.startswith("_"):
            continue
        if stub.stem.upper() not in ambiguous:
            continue
        try:
            fm, _body = _parse_frontmatter(stub.read_text(encoding="utf-8"))
        except OSError:
            continue
        if fm and str(fm.get("note_type", "")).strip().lower() == "alias":
            try:
                stub.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def _normalize_acronym_related(
    related: Any, acronym_map: dict[str, str]
) -> tuple[list[Any], int]:
    """Rewrite all-caps acronym entries in the ``related`` list to canonical stems."""
    if not isinstance(related, list) or not acronym_map:
        return related if isinstance(related, list) else [], 0
    fixes = 0
    new_related: list[Any] = []
    for entry in related:
        if not isinstance(entry, str):
            new_related.append(entry)
            continue
        stripped = entry.strip()
        wrapped = stripped.startswith("[[") and stripped.endswith("]]")
        target = stripped.strip("[]").strip()
        mapped = acronym_map.get(target.upper())
        if mapped and target == target.upper():
            new_related.append(f"[[{mapped}]]" if wrapped else mapped)
            fixes += 1
        else:
            new_related.append(entry)
    return new_related, fixes


def auto_fix_moved_wikilinks(vault: Path) -> int:
    """Normalize case-mismatched wikilinks across the vault. Returns the
    count of FILES modified.

    This is the cycle-time auto-fix described in the module docstring.
    Idempotent: re-running on a clean vault returns ``0``.

    See :mod:`tests.pipeline.test_wikilink_normalization` for the full
    behavioural contract.
    """
    data = corpus_dir(vault)
    if not data.exists():
        return 0

    stems = _vault_note_stems(vault)
    if not stems:
        return 0

    files_modified = 0
    for note in sorted(data.rglob("*.md")):
        if note.name.startswith("_"):
            continue
        try:
            text = note.read_text(encoding="utf-8")
        except OSError:
            continue

        fm, body = _parse_frontmatter(text)
        if fm is None:
            # No frontmatter \u2014 still normalize body wikilinks defensively.
            new_body, body_fixes = _normalize_body_wikilinks(text, stems)
            if body_fixes > 0:
                from .atomic_write import write_text as _aw_text

                _aw_text(note, new_body)
                files_modified += 1
            continue

        new_body, body_fixes = _normalize_body_wikilinks(body, stems)
        new_related, related_fixes = _normalize_related_entries(
            fm.get("related"), stems
        )

        if body_fixes == 0 and related_fixes == 0:
            continue

        if related_fixes > 0:
            fm["related"] = new_related

        from .atomic_write import write_text as _aw_text

        _aw_text(note, _serialize_note(fm, new_body))
        files_modified += 1

    return files_modified
