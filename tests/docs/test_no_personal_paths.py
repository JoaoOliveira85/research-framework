"""Guard: no personal absolute paths in the public docs/spec corpus (#272).

19 tracked files under ``specs/`` and ``docs/`` were found carrying absolute
``/Users/<real-username>/...`` paths — accumulated because
``scripts/check_portability.py``'s hardcoded-path rule (spec 009) exempts
``*.md`` outright, so nothing ever caught them. This is a **narrower**,
docs-corpus-scoped guard: it does not replace that portability rule (which
stays scoped to shipped shell/code and a fixed macOS-path token list); it
closes the specific gap that let a stale personal username accumulate across
the doc/spec corpus that will eventually ship standalone (docs-readiness
epic #217).

Scope mirrors the grep the corpus was audited with: ``docs/``, ``specs/``,
``.specify/`` (recursively) plus top-level ``*.md`` files. ``tests/`` is
deliberately excluded — fixture files there intentionally bake absolute
paths for the quality harness and are tracked separately (see
specs/026-fixture-isolation).

A handful of illustrative placeholders are allowed (``/Users/me``,
``/Users/you``, ``/Users/dev``, ``/Users/jdoe``, ``/Users/...``,
``/Users/<name>``) — none of them resolve to a real account.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Directories walked recursively.
_SCAN_DIRS: tuple[str, ...] = ("docs", "specs", ".specify")

# A real (or real-looking) username after /Users/. Deliberately excludes the
# handful of illustrative placeholders already used throughout the corpus:
# /Users/me, /Users/you, /Users/dev, /Users/jdoe, /Users/..., /Users/<name>.
_PERSONAL_PATH_RE = re.compile(
    r"/Users/(?!me\b|you\b|dev\b|jdoe\b|\.\.\.|<)[A-Za-z0-9_.-]+"
)


def _iter_scan_files() -> list[Path]:
    files: list[Path] = []
    for base in _SCAN_DIRS:
        root = REPO_ROOT / base
        if root.is_dir():
            files.extend(sorted(p for p in root.rglob("*") if p.is_file()))
    # Top-level *.md files (README.md, CLAUDE.md, CONTRIBUTING.md,
    # CHANGELOG.md, ARCHITECTURE.md, ...) — non-recursive, mirrors a shell
    # `*.md` glob.
    files.extend(sorted(REPO_ROOT.glob("*.md")))
    return files


def test_no_personal_paths_in_docs_corpus() -> None:
    """``docs/`` + ``specs/`` + ``.specify/`` + root ``*.md`` must not carry
    a real absolute ``/Users/<username>/...`` path (#272)."""
    offenders: list[str] = []
    for path in _iter_scan_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary / unreadable — not a doc reference
        for lineno, line in enumerate(text.splitlines(), 1):
            match = _PERSONAL_PATH_RE.search(line)
            if match:
                rel = path.relative_to(REPO_ROOT)
                offenders.append(f"{rel}:{lineno}: {match.group(0)} — {line.strip()}")
    assert not offenders, (
        "Found personal absolute path(s) in the docs/spec corpus — replace "
        "with ~/, $VAULT_DIR, or a placeholder (/Users/me, /Users/you, "
        "/Users/dev, /Users/...):\n" + "\n".join(offenders)
    )
