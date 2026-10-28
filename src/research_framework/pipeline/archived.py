"""The ``settings.yaml::archived`` flag — one rule, one message (spec 071, issue #26).

Everything that decides "is this vault frozen?" or says so to a human or an
agent lives here, so the CLI verbs, the orchestrator, the pipeline runner,
``./vault status`` and the rendered agent instructions cannot drift apart.

This module is a leaf on purpose: it imports nothing from the pipeline, so the
read-only ``status`` verb and the template renderer can use it without pulling
in the orchestrator.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ARCHIVED_EXIT = 2


def is_archived(vault_dir: Path) -> bool:
    """True when ``settings.yaml::archived`` is set (spec 071).

    Reads the key directly rather than through ``load_vault_settings``. The
    typed loader validates the WHOLE file, so a vault with, say, no
    ``pipeline.max_cycles`` raises before ``archived`` is ever reached — and an
    archived vault is exactly the one whose pipeline config nobody has kept
    current. The real codebase-vault is in that state: settings predating spec
    061, where routing this through the typed loader made the flag silently
    inert. ``archived`` must hold under every circumstance, including a
    settings file that is otherwise invalid.

    Only a literal YAML ``true`` archives. A missing file, unreadable file,
    unparseable YAML or a typo all read as NOT archived — those are different
    failures, surfaced on their own terms; defaulting to "archived" would
    strand a working vault. The typed loader still rejects a non-boolean value
    outright (``_parse_archived``), so a typo is not silently tolerated
    wherever settings do load.
    """
    settings_path = vault_dir / "settings.yaml"
    try:
        import yaml

        raw = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return False
    return isinstance(raw, dict) and raw.get("archived") is True


def archived_refusal_message(vault_dir: Path) -> str | None:
    """The spec-071 refusal text, or ``None`` when the vault is not archived.

    Names the vault, what still works, and the one-line change that reverses
    it. Every refusal — CLI or library — uses this string.
    """
    if not is_archived(vault_dir):
        return None
    return (
        f"{vault_dir} is archived — no research cycle may write to it.\n"
        "It stays fully queryable (`./vault ask`, `status`, `digest`, "
        "`re-grade`) and still takes framework upgrades (`./vault update`).\n"
        f"To resume research, set `archived: false` in {vault_dir}/settings.yaml."
    )


def refuse_if_archived(vault_dir: Path) -> int | None:
    """CLI guard: print the refusal to stderr and return exit 2, else ``None``.

    Call it before any side effect from a verb that writes research content.
    """
    message = archived_refusal_message(vault_dir)
    if message is None:
        return None
    print(f"error: {message}", file=sys.stderr)
    return ARCHIVED_EXIT


# --------------------------------------------------------------------------
# Rendered agent instructions (issue #26)
# --------------------------------------------------------------------------

_NOTICE_BEGIN = "<!-- archived-notice:begin -->"
_NOTICE_END = "<!-- archived-notice:end -->"

_NOTICE_BODY = (
    "> **Vault archived — do not write research.** This vault is frozen "
    "(`archived: true` in `settings.yaml`). You must not create, edit, move or "
    "delete research notes, or run research cycles, in it; read and answer from "
    "the existing notes only. To lift the freeze, set `archived: false` in "
    "`settings.yaml`, then run `research-framework regenerate-agents "
    "<vault> --force` to drop this notice."
)

_NOTICE_RE = re.compile(
    rf"\n?{re.escape(_NOTICE_BEGIN)}.*?{re.escape(_NOTICE_END)}\n", re.DOTALL
)
_H1_RE = re.compile(r"^# .*\n", re.MULTILINE)
_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)


def apply_archived_notice(text: str, archived: bool) -> str:
    """Return ``text`` with the archived notice present iff ``archived``.

    Idempotent and reversible: any existing notice block is removed first, so
    a repeat run never stacks notices and ``archived=False`` restores the
    original text byte for byte. The notice goes straight after the file's
    ``# `` title (else after front matter, else the top) so it is the first
    thing an agent reads. Nothing outside the marked block is touched, which is
    what lets this run over hand-edited ``CLAUDE.md`` / ``AGENTS.md``.
    """
    text = _NOTICE_RE.sub("", text)
    if not archived:
        return text
    block = f"\n{_NOTICE_BEGIN}\n{_NOTICE_BODY}\n{_NOTICE_END}\n"
    heading = _H1_RE.search(text)
    if heading is not None:
        at = heading.end()
    else:
        frontmatter = _FRONTMATTER_RE.match(text)
        at = frontmatter.end() if frontmatter is not None else 0
    return text[:at] + block + text[at:]


def sync_archived_notice(vault_dir: Path) -> list[Path]:
    """Bring ``CLAUDE.md`` / ``AGENTS.md`` in line with the vault's flag.

    Returns the files rewritten. A file that is absent or already correct is
    skipped, so this is safe to call on every render.
    """
    archived = is_archived(vault_dir)
    changed: list[Path] = []
    for name in ("CLAUDE.md", "AGENTS.md"):
        path = vault_dir / name
        try:
            before = path.read_text(encoding="utf-8")
        except OSError:
            continue
        after = apply_archived_notice(before, archived)
        if after != before:
            path.write_text(after, encoding="utf-8")
            changed.append(path)
    return changed
