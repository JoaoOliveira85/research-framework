"""Stub-note scanner — Principle VIII "Stub-Free Exit" enforcement.

A research run (bootstrap, refresh, or expand) MUST NOT terminate while any
note in `data_vault/` qualifies as a stub. A note is a stub when ANY of:

  - `word_count < note_type.min_word_count` (too short to be useful), OR
  - frontmatter `source_urls` is empty (zero Tier-2 citations — also a
    Principle IX violation), OR
  - verifier `status` is `pending` or `rejected`, OR
  - frontmatter lifecycle `status` is still `draft`.

This module does not *fix* stubs; it only detects them. The orchestrator
decides whether to wind-down (spend remaining budget) or abort with a report.
Keeping detection in its own module lets `research-framework validate`, resume
runs, and the final-report agent all consult the same predicate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

from ..spec.schema import NoteTypeConfig, SpecConfig
from ..vault.frontmatter import split_frontmatter

# Lifecycle status values that still count as "in progress" for exit purposes.
# `draft` is the conventional initial state; `in-review` is sometimes used.
# Anything else (e.g. `published`, `final`, `ready`) counts as complete.
_UNFINISHED_STATUSES = {"draft", "in-review", "in_review"}


def _failing_verifier_statuses(settings: dict | None = None) -> frozenset[str]:
    """Verifier status values that block exit.

    When stages.verifier.enabled is True (default once verifier is wired), an
    absent/empty verifier_status means the note was written but the verifier
    stage didn't stamp it — treat as unverified stub.

    When stages.verifier.enabled is False, absent status is neutral (back-compat
    with pre-004 vaults that predate the verifier stage).

    "rejected" is always a failing status regardless of the setting.
    """
    base = frozenset({"pending", "rejected"})
    verifier_on = (
        (settings or {}).get("stages", {}).get("verifier", {}).get("enabled", True)
    )
    if verifier_on:
        return base | frozenset({"", "missing"})  # empty string and absent key
    return base


_WORD_RE = re.compile(r"\S+")


@dataclass
class Stub:
    """A single stub note and the reasons it qualifies.

    `reasons` is a list (not a set) so the CLI/report can render them in a
    deterministic order: short-body first, then missing-sources, then
    verifier, then lifecycle. Callers rely on that ordering for diffs.
    """

    path: Path
    note_type: str
    reasons: list[str] = field(default_factory=list)
    word_count: int = 0

    def describe(self, vault_dir: Path | None = None) -> str:
        """One-line human-readable summary, path relativised when possible."""
        shown: str | Path
        if vault_dir is not None:
            try:
                shown = self.path.relative_to(vault_dir)
            except ValueError:
                shown = self.path
        else:
            shown = self.path
        reason_str = "; ".join(self.reasons)
        return f"{shown} [{self.note_type}]: {reason_str}"


StubClass = Literal["not-a-stub", "anchor-stub", "deletable-stub"]


@dataclass(frozen=True)
class StubClassificationContext:
    """Inputs for the inbound-link-aware stub lens (spec 051 FR3).

    ``body_len`` and ``inbound_links_count`` are supplied by the caller — the
    latter from :func:`research_framework.vault.indexer.inbound_link_counts`,
    built once per scan over the whole link graph.
    """

    path: Path
    inbound_links_count: int
    body_len: int


def classify_stub(
    ctx: StubClassificationContext,
    *,
    body_len_threshold: int,
    anchor_link_threshold: int,
) -> StubClass:
    """Classify a note as not-a-stub, anchor-stub, or deletable-stub.

    A *pure* additional lens over :func:`scan_stubs` — it does not re-run the
    word_count / source_urls / verifier / lifecycle detection criteria, and it
    has no side effects. State machine (data-model.md FR3):

    1. ``body_len > body_len_threshold`` → ``"not-a-stub"`` (substantial note).
    2. else ``inbound_links_count >= anchor_link_threshold`` → ``"anchor-stub"``
       — a heavily-linked graph anchor. Callers MUST flag it ``status:
       needs-research`` and surface it in the research-backlog as deferred
       work; it must **never** be deleted.
    3. else → ``"deletable-stub"`` — a short, orphaned note that is a normal
       stub-removal candidate.
    """
    if ctx.body_len > body_len_threshold:
        return "not-a-stub"
    if ctx.inbound_links_count >= anchor_link_threshold:
        return "anchor-stub"
    return "deletable-stub"


def scan_stubs(
    vault_dir: Path, spec: SpecConfig, settings: dict | None = None
) -> list[Stub]:
    """Return every stub note under the vault's corpus folder.

    That folder is the one the spec names (``vault.corpus_dir``, default
    ``data_vault``).

    Walks the subfolder for each note_type in the spec (so notes in folders
    the spec doesn't declare are ignored — that's how we stay quiet about
    `.obsidian/`, `_templates/`, etc.). The returned list is sorted by path
    so output is reproducible across runs — critical for diff-based CI
    checks of the stubs report.
    """
    data_vault = vault_dir / spec.vault_corpus_dir
    stubs: list[Stub] = []
    if not data_vault.exists():
        return stubs

    for nt in spec.note_types:
        folder = data_vault / nt.folder
        if not folder.exists():
            continue
        for note_path in sorted(folder.rglob("*.md")):
            # Ignore auto-generated index files that live in note-type folders
            # (some vaults keep an `_index.md` per folder). They're not notes
            # in the Quality-Bar sense, so they never count as stubs.
            if note_path.name.startswith("_"):
                continue
            stub = _check_note(note_path, nt, settings=settings)
            if stub is not None:
                stubs.append(stub)

    return stubs


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _is_alias_node(frontmatter: dict) -> bool:
    """True for spec-062 redirect stubs (``note_type: alias`` / ``type: alias``)."""
    for key in ("note_type", "type"):
        if str(frontmatter.get(key, "") or "").strip().lower() == "alias":
            return True
    return False


def _check_note(
    note_path: Path, note_type: NoteTypeConfig, settings: dict | None = None
) -> Stub | None:
    """Return a Stub if the note fails any exit criterion, else None."""
    reasons: list[str] = []

    try:
        text = note_path.read_text(encoding="utf-8")
    except OSError as e:
        # Unreadable file counts as a stub by definition — we can't prove it
        # meets the quality bar, so we refuse to exit over it. The reason
        # string is explicit so the user can fix permissions quickly.
        return Stub(
            path=note_path, note_type=note_type.name, reasons=[f"unreadable: {e}"]
        )

    frontmatter, body = _split_frontmatter(text)

    # Spec 062 FR3 / data-model Entity 4: alias/redirect stubs are graph-
    # resolution nodes, not research stubs. They are short by design and carry
    # no claims — never count them as fuel (would loop the orchestrator).
    if _is_alias_node(frontmatter):
        return None

    word_count = _count_words(body)

    if word_count < note_type.min_word_count:
        reasons.append(f"word_count {word_count} < min {note_type.min_word_count}")

    sources = frontmatter.get("source_urls") or []
    if not sources:
        reasons.append("source_urls empty (Principle IX Tier-2 violation)")

    verifier_status = str(frontmatter.get("verifier_status", "") or "").strip().lower()
    if verifier_status in _failing_verifier_statuses(settings):
        reasons.append(f"verifier_status={verifier_status}")

    lifecycle_status = str(frontmatter.get("status", "") or "").strip().lower()
    if lifecycle_status in _UNFINISHED_STATUSES:
        reasons.append(f"status={lifecycle_status}")

    if not reasons:
        return None
    return Stub(
        path=note_path,
        note_type=note_type.name,
        reasons=reasons,
        word_count=word_count,
    )


def _split_frontmatter(text: str) -> tuple[dict, str]:
    # Holdout from spec 025 B4 canonical parser migration.
    # Reason: stub detection must soft-fail on malformed YAML and still count
    # body words; ``vault.frontmatter`` raises ``FrontmatterParseError``.
    """Split a Markdown file into (frontmatter_dict, body_str).

    Tolerant: a note without frontmatter returns ({}, text). Malformed YAML
    returns ({}, body_after_delimiters) so we still count its words correctly
    rather than erroring out — a note with broken frontmatter is *definitely*
    a stub but we want to compute word_count too for the report.
    """
    if not text.startswith("---"):
        return {}, text
    # Split at the delimiter LINES. ``text.split("---", 2)`` ended the
    # frontmatter at the first `---` inside a value (a slug URL such as
    # `kafka---a-guide`), which hid ``verifier_status`` and ``status`` below it.
    split = split_frontmatter(text)
    if split is None:
        return {}, text
    yaml_text, body = split
    try:
        data = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return data, body


def _count_words(body: str) -> int:
    """Count non-whitespace tokens in the note body.

    Uses a simple regex rather than `len(body.split())` so callers see the
    same behaviour regardless of locale / whitespace variants. Good enough
    for Principle VIII (we only need approx parity with `min_word_count`).
    """
    return len(_WORD_RE.findall(body))
