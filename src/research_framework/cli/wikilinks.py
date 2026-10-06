"""``vault wikilinks`` sweep verb (spec 067 FR4/FR5).

A deterministic, zero-LLM, idempotent repair pass over ``data_vault/``:

1. Build the acronym map (``ambiguous`` set authoritative).
2. **Body links** — any all-caps ``[[TOKEN]]`` whose acronym is ambiguous, or that
   renames the containing note's own title (C2/C3), → plain text.
3. **Alias stubs** (``note_type: alias``):
   - exactly one valid expansion → re-point ``redirect_to``.
   - no inbound ``[[...]]`` reference AND (ambiguous OR no valid expansion) → delete.
   - else no-op.

Without ``--fix`` it reports only (dry-run); with ``--fix`` it applies repairs via
atomic writes / file deletes. ``--json`` emits ``SweepActionRecord[]``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..pipeline.wikilinks import (
    _WIKILINK_RE,
    _parse_frontmatter,
    _rewrite_acronym_body,
    _serialize_note,
    build_acronym_map,
    title_self_acronyms,
)
from ..vault.corpus import corpus_dir


def _iter_notes(data: Path):
    for note in sorted(data.rglob("*.md")):
        if note.name.startswith("_"):
            continue
        yield note


def _inbound_referenced(data: Path, stem: str) -> bool:
    """True if any note body contains a ``[[<stem>]]`` (case-insensitive stem)."""
    needle = stem.lower()
    for note in _iter_notes(data):
        try:
            text = note.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in _WIKILINK_RE.finditer(text):
            if m.group(1).strip().lower() == needle:
                return True
    return False


def _sweep(vault_dir: Path, *, apply: bool) -> list[dict[str, str]]:
    """Compute (and optionally apply) the sweep actions for ``vault_dir``."""
    from ..pipeline.atomic_write import write_text as _aw_text

    data = corpus_dir(vault_dir)
    actions: list[dict[str, str]] = []
    if not data.is_dir():
        return actions

    acronym_map, ambiguous = build_acronym_map(vault_dir)
    ambiguous_set = frozenset(a.upper() for a in ambiguous)

    # 1. Body links — plain-text ambiguous / self-title-renaming all-caps links.
    for note in _iter_notes(data):
        try:
            text = note.read_text(encoding="utf-8")
        except OSError:
            continue
        fm, body = _parse_frontmatter(text)
        self_stem = note.stem.lower()
        if fm is None:
            title = note.stem.replace("-", " ")
            self_acronyms = title_self_acronyms(title)
            new_body, fixes = _rewrite_acronym_body(
                text,
                acronym_map,
                self_stem=self_stem,
                self_acronyms=self_acronyms,
                ambiguous=ambiguous_set,
            )
            if fixes:
                actions.append(
                    {
                        "action": "plaintext_body_link",
                        "path": str(note.relative_to(vault_dir)),
                        "detail": f"{fixes} link(s) plain-texted",
                    }
                )
                if apply:
                    _aw_text(note, new_body)
            continue
        if str(fm.get("note_type", "")).strip().lower() == "alias":
            continue  # stubs handled in pass 2
        title = str(fm.get("title") or note.stem.replace("-", " "))
        self_acronyms = title_self_acronyms(title)
        new_body, fixes = _rewrite_acronym_body(
            body,
            acronym_map,
            self_stem=self_stem,
            self_acronyms=self_acronyms,
            ambiguous=ambiguous_set,
        )
        if fixes:
            actions.append(
                {
                    "action": "plaintext_body_link",
                    "path": str(note.relative_to(vault_dir)),
                    "detail": f"{fixes} link(s) plain-texted",
                }
            )
            if apply:
                _aw_text(note, _serialize_note(fm, new_body))

    # 2. Alias stubs — re-point fixable, delete orphan/unfixable.
    for note in _iter_notes(data):
        try:
            text = note.read_text(encoding="utf-8")
        except OSError:
            continue
        fm, _body = _parse_frontmatter(text)
        if not fm or str(fm.get("note_type", "")).strip().lower() != "alias":
            continue
        acro = note.stem.upper()
        rel = str(note.relative_to(vault_dir))
        valid_stem = acronym_map.get(acro)
        if valid_stem is not None:
            current = str(fm.get("redirect_to") or "").strip().lower()
            if current != valid_stem:
                actions.append(
                    {
                        "action": "repoint_stub",
                        "path": rel,
                        "detail": f"redirect_to: {current or '∅'} → {valid_stem}",
                    }
                )
                if apply:
                    fm["redirect_to"] = valid_stem
                    _aw_text(note, _serialize_note(fm, f"See [[{valid_stem}]].\n"))
            continue
        # No single valid expansion (ambiguous or vanished target).
        if acro in ambiguous_set or not _inbound_referenced(data, note.stem):
            actions.append(
                {
                    "action": "delete_stub",
                    "path": rel,
                    "detail": "ambiguous or orphaned alias stub",
                }
            )
            if apply:
                try:
                    note.unlink()
                except OSError:
                    pass

    return actions


def cmd_wikilinks(args: argparse.Namespace) -> int:
    vault = getattr(args, "vault", None)
    if vault is None:
        print("error: --vault is required", file=sys.stderr)
        return 2
    vault_dir = Path(vault).expanduser().resolve()
    if not vault_dir.is_dir():
        print(f"error: vault not found: {vault_dir}", file=sys.stderr)
        return 2

    apply = bool(getattr(args, "fix", False))
    actions = _sweep(vault_dir, apply=apply)

    if getattr(args, "json", False):
        print(json.dumps(actions, indent=2, sort_keys=True))
        return 0

    mode = "applied" if apply else "dry-run (use --fix to apply)"
    if not actions:
        print(f"wikilinks: no actions needed ({mode})")
        return 0
    print(f"wikilinks: {len(actions)} action(s) [{mode}]")
    for a in actions:
        print(f"  {a['action']:<22} {a['path']}  — {a['detail']}")
    return 0


__all__ = ["cmd_wikilinks"]
