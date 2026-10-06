"""Canonical YAML frontmatter parser for vault markdown notes (spec 025 US7 B4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_OPENING = "---\n"


class FrontmatterParseError(Exception):
    """Raised when YAML frontmatter is malformed."""

    def __init__(
        self,
        message: str,
        *,
        path: Path | None = None,
        line_no: int | None = None,
    ) -> None:
        self.path = path
        self.line_no = line_no
        super().__init__(message)


def parse_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from a markdown file at *path*.

    Issue #287: this used to read the file in binary mode and compare the
    first 4 bytes against the literal ``b"---\\n"``. A note saved with CRLF
    line endings (``b"---\\r\\n"``) or a leading UTF-8 BOM (``b"\\xef\\xbb\\xbf-"``)
    never matched, so the file was silently treated as having NO frontmatter
    — ``related``/``coverage_category`` lost, SG-005 failing with no parse
    error to explain why. Every other reader in this codebase reads notes
    with ``Path.read_text()``, which already normalizes ``\\r\\n``/``\\r`` to
    ``\\n`` (universal newlines) — ``open(..., "rb")`` was the one path that
    opted out of that. Reading in text mode with ``utf-8-sig`` gets both for
    free: universal-newline translation, and BOM stripping when a BOM is
    present (a no-op otherwise).
    """
    try:
        content = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise FrontmatterParseError(str(exc), path=path) from exc
    if not content.startswith(_OPENING):
        return {}, content
    try:
        return parse_frontmatter_str(content)
    except FrontmatterParseError as exc:
        if exc.path is None:
            exc.path = path
        raise


def parse_frontmatter_str(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from in-memory markdown *content*."""
    if not content.startswith(_OPENING):
        return {}, content

    pos = len(_OPENING)
    while True:
        newline = content.find("\n", pos)
        if newline == -1:
            line = content[pos:]
            if line == "---":
                yaml_text = content[len(_OPENING) : pos]
                body = ""
                return _load_frontmatter_dict(yaml_text, path=None), body
            raise FrontmatterParseError("missing closing --- delimiter")
        line = content[pos:newline]
        if line == "---":
            yaml_text = content[len(_OPENING) : pos]
            body = content[newline + 1 :]
            return _load_frontmatter_dict(yaml_text, path=None), body
        pos = newline + 1


def split_frontmatter(content: str) -> tuple[str, str] | None:
    """Split *content* into ``(yaml_text, body)`` without parsing the YAML.

    For the readers that cannot use :func:`parse_frontmatter_str` because they
    must not raise on malformed YAML: stub detection still counts the body's
    words, the spec loaders and the SKILL.md preflight report the YAML error in
    their own terms. Returns ``None`` when *content* does not open with a
    ``---`` line or that block is never closed.

    A delimiter is a whole LINE reading ``---``. Trailing whitespace on it is
    tolerated, because the ``text.split("---", 2)`` these readers used before
    tolerated it. A ``---`` inside a line is not a delimiter — a slug URL such
    as ``kafka---a-guide``, a ``# -------`` comment rule — and that split ended
    the frontmatter there.
    """
    lines = content.split("\n")
    if lines[0].rstrip() != "---":
        return None
    for index in range(1, len(lines)):
        if lines[index].rstrip() == "---":
            yaml_text = "".join(line + "\n" for line in lines[1:index])
            return yaml_text, "\n".join(lines[index + 1 :])
    return None


def dump_frontmatter(
    frontmatter: dict[str, Any],
    body: str,
    *,
    sort_keys: bool = False,
) -> str:
    """Build a markdown string with YAML frontmatter and *body*."""
    if not frontmatter:
        return body
    fm_text = yaml.dump(
        frontmatter,
        sort_keys=sort_keys,
        allow_unicode=True,
        default_flow_style=False,
    ).rstrip()
    return f"---\n{fm_text}\n---\n{body}"


def append_frontmatter_keys(content: str, additions: dict[str, Any]) -> str | None:
    """Return *content* with *additions* appended to its frontmatter block.

    Every line already there is kept byte for byte. A load/dump round trip
    (:func:`dump_frontmatter`) cannot promise that: it drops comments and
    re-types plain scalars the YAML 1.1 way — ``0123`` comes back as ``83``,
    ``no`` as ``false``, ``1.10`` as ``1.1``, ``1:30`` as ``90``.

    Returns ``None`` when the keys cannot simply be added as new lines: there
    is no frontmatter block, a key is already present, or the block with the
    new lines does not parse back to the same mapping plus *additions* (a
    flow-style ``{...}`` mapping, for one). The caller then falls back to the
    round trip.
    """
    if not additions or not content.startswith(_OPENING):
        return None
    try:
        frontmatter, body = parse_frontmatter_str(content)
    except FrontmatterParseError:
        return None
    if any(key in frontmatter for key in additions):
        return None
    # ``body`` is everything after the closing delimiter line, so that line is
    # the tail of what precedes it (without a newline when it ends the file).
    head = content[: len(content) - len(body)]
    closing = "---\n" if head.endswith("---\n") else "---"
    insert_at = len(head) - len(closing)
    added = yaml.dump(
        additions,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    patched = content[:insert_at] + added + content[insert_at:]
    try:
        if parse_frontmatter_str(patched) != ({**frontmatter, **additions}, body):
            return None
    except FrontmatterParseError:
        return None
    return patched


def _load_frontmatter_dict(
    yaml_text: str,
    *,
    path: Path | None,
) -> dict[str, Any]:
    if not yaml_text.strip():
        return {}
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        line_no = _yaml_error_line_no(exc)
        if _is_unsafe_yaml_error(exc):
            raise FrontmatterParseError(
                "unsafe YAML construct", path=path, line_no=line_no
            ) from exc
        raise FrontmatterParseError(
            f"YAML parse error: {exc}", path=path, line_no=line_no
        ) from exc
    if data is None:
        return {}
    if isinstance(data, list):
        raise FrontmatterParseError(
            "frontmatter must be a mapping, got list", path=path
        )
    if not isinstance(data, dict):
        type_name = type(data).__name__
        raise FrontmatterParseError(
            f"frontmatter must be a mapping, got {type_name}", path=path
        )
    return data


def _yaml_error_line_no(exc: yaml.YAMLError) -> int | None:
    mark = getattr(exc, "problem_mark", None)
    if mark is None:
        return None
    return int(mark.line) + 1 + 1


def _is_unsafe_yaml_error(exc: yaml.YAMLError) -> bool:
    msg = str(exc).lower()
    return "could not determine a constructor" in msg or "!!" in msg
