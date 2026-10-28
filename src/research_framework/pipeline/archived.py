"""The ``settings.yaml::archived`` flag — one rule, one message (spec 071, issue #26).

Everything that decides "is this vault frozen?" or says so to a human or an
agent lives here, so the CLI verbs, the orchestrator, the pipeline runner,
``./vault status`` and the rendered agent instructions cannot drift apart.

This module is a leaf on purpose: it imports nothing from the pipeline, so the
read-only ``status`` verb and the template renderer can use it without pulling
in the orchestrator.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

_LOG = logging.getLogger(__name__)

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

# Says only what the agent needs: it is frozen, and how a human reverses that.
# No command and no placeholder — an agent would run it or print it literally.
_NOTICE_BODY = (
    "> **Vault archived — do not write research.** This vault is frozen "
    "(`archived: true` in `settings.yaml`). You must not create, edit, move or "
    "delete research notes, or run research cycles, in it; read and answer from "
    "the existing notes only. A human lifts the freeze by setting "
    "`archived: false` in `settings.yaml`."
)

# A complete block: BEGIN, anything that is not itself a BEGIN, END, and at
# most the one line terminator the insertion added. `(?!BEGIN)` is what stops
# an orphan BEGIN from swallowing everything up to a later, complete block.
_BLOCK_RE = re.compile(
    rf"{re.escape(_NOTICE_BEGIN)}(?:(?!{re.escape(_NOTICE_BEGIN)}).)*?"
    rf"{re.escape(_NOTICE_END)}(?:\r\n|\n)?",
    re.DOTALL,
)
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_FRONTMATTER_RE = re.compile(r"\A---\r?\n.*?\r?\n---(?:\r?\n|\Z)", re.DOTALL)


def _title_end(text: str, start: int) -> int | None:
    """Offset just past the first ``# `` title line at or after ``start``.

    Skips fenced code blocks, so a ``# comment`` in a shell snippet is never
    mistaken for the document title.
    """
    fence: str | None = None
    offset = start
    pieces = text[start:].split("\n")
    for index, piece in enumerate(pieces):
        end = offset + len(piece) + (1 if index < len(pieces) - 1 else 0)
        stripped = piece.rstrip("\r")
        marker = _FENCE_RE.match(stripped)
        if fence is None:
            if marker is not None:
                fence = marker.group(1)[0]
            elif stripped.startswith("# "):
                return end
        elif marker is not None and marker.group(1)[0] == fence:
            fence = None
        offset = end
    return None


def apply_archived_notice(text: str, archived: bool) -> str:
    """Return ``text`` with the archived notice present iff ``archived``.

    Idempotent and reversible: any complete notice block is removed first (with
    the one line terminator the insertion added, and nothing before it), so a
    repeat run never stacks notices and ``archived=False`` restores the
    original text byte for byte. The notice goes straight after the file's
    ``# `` title — found after any front matter and outside code fences — else
    after the front matter, else at the top, so it is the first thing an agent
    reads. New lines use the file's own line ending. Nothing outside the marked
    block is touched, which is what lets this run over hand-edited files; an
    orphan marker (a begin without its end, or the reverse) is left in place
    and reported rather than guessed at.
    """
    text = _BLOCK_RE.sub("", text)
    if _NOTICE_BEGIN in text or _NOTICE_END in text:
        _LOG.warning(
            "archived notice: orphan marker left in place (a begin or end "
            "marker without its partner); edit or remove it by hand"
        )
    if not archived:
        return text
    nl = "\r\n" if "\r\n" in text else "\n"
    block = f"{_NOTICE_BEGIN}{nl}{_NOTICE_BODY}{nl}{_NOTICE_END}{nl}"
    frontmatter = _FRONTMATTER_RE.match(text)
    body_start = frontmatter.end() if frontmatter is not None else 0
    at = _title_end(text, body_start)
    if at is None:
        at = body_start
    if at > 0 and text[at - 1] not in "\r\n":
        # The anchor line is the file's last and has no terminator.
        block = nl + block
    return text[:at] + block + text[at:]


def _research_command_stem(vault_dir: Path) -> str:
    """Destination stem of the ``/research`` command (``commands.research``).

    Read from ``_pipeline/spec-parse.json`` when it exists; the notice-only
    path must not require it, so any problem falls back to the default.
    """
    try:
        parsed = json.loads(
            (vault_dir / "_pipeline" / "spec-parse.json").read_text(encoding="utf-8")
        )
        stem = parsed["settings"]["commands"]["research"]
    except (OSError, ValueError, KeyError, TypeError):
        return "research"
    return stem if isinstance(stem, str) and stem else "research"


def sync_archived_notice(vault_dir: Path) -> list[Path]:
    """Bring the archived notice in line with the vault's flag.

    Touches ``CLAUDE.md``, ``AGENTS.md`` and the ``/research`` command — and
    inside them only the marked block. Everything else, including customised
    commands, is left byte for byte as it was, and no spec is needed. Returns
    the files rewritten; one that is absent or already correct is skipped, so
    this is safe to call on every render and every update.
    """
    archived = is_archived(vault_dir)
    targets = [
        vault_dir / "CLAUDE.md",
        vault_dir / "AGENTS.md",
        vault_dir / ".claude" / "commands" / f"{_research_command_stem(vault_dir)}.md",
    ]
    changed: list[Path] = []
    for path in targets:
        try:
            before = path.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        after = apply_archived_notice(before, archived)
        if after != before:
            path.write_bytes(after.encode("utf-8"))
            changed.append(path)
    return changed
