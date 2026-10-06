"""Regression tests for spec 025 US5 (A5 doc sync).

Walks ``.specify/`` and ``docs/`` with the standard library (no external
``rg`` binary — the PR-CI runners don't ship ripgrep, spec 009) so stale
references fail CI without importing doc parsers.

Historical: this module used to also check QW-2 wording in
``docs/ROADMAP.md``. QW-2 shipped as part of 0.3.0 (spec 024 US3 —
smoke meta-tests restored) and was pruned from ROADMAP during the
post-Wave-1 doc restructure (2026-05-27) per the doc-discipline rule
"shipped items belong in CHANGELOG, not ROADMAP." The wording-regression
guard is no longer load-bearing; the historical entry survives in
``CHANGELOG.md [0.3.0]``.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _offenders(paths: list[Path], pattern: re.Pattern[str]) -> list[str]:
    """``path:lineno: line`` for every scanned line matching ``pattern``."""
    hits: list[str] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary / unreadable — not a doc reference
        for lineno, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                hits.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    return hits


def _files_under(*bases: str) -> list[Path]:
    found: list[Path] = []
    for base in bases:
        root = REPO_ROOT / base
        if not root.is_dir():
            continue
        found += [p for p in sorted(root.rglob("*")) if p.is_file()]
    return found


def test_no_run_cycle_sh_references() -> None:
    """``.specify/`` and ``docs/`` must not mention the deleted bash driver.

    The rule was written when spec 004 replaced ``run_cycle.sh`` — but the file
    was not deleted then, only undocumented: ``copy_scripts`` kept shipping it
    into every generated vault, executable, until #298. So for years this guard
    was green about a file that existed, while ``tests/generator/`` asserted its
    presence and the constitution (which lives under ``.specify/``) was
    structurally unable to describe a file the framework shipped. The file is
    gone now and the assertion finally means what it says.
    """
    offenders = _offenders(
        _files_under("docs", ".specify"), re.compile(r"run_cycle\.sh")
    )
    assert not offenders, "Found stale run_cycle.sh references:\n" + "\n".join(
        offenders
    )


# Root docs are the project's historical record: ARCHITECTURE.md names
# `run_cycle.sh` as the thing spec 004 replaced, and deleting that sentence
# would lose the reason `cycle_runner.py` exists. What they must not do is send
# a reader to run it — a command line, or a repo path that implies the file is
# still there. Scanning them at all closes the #278 fail-open shape the old
# guard had: it was green partly because of where it chose not to look.
_ROOT_DOCS = ("README.md", "ARCHITECTURE.md", "CONTRIBUTING.md", "CLAUDE.md")
_RUN_CYCLE_INVOCATION = re.compile(r"(?:bash |sh |\./|scripts/)run_cycle\.sh")


def test_root_docs_do_not_point_at_run_cycle_sh() -> None:
    """Root docs may record the history; they may not send you to the file."""
    paths = [REPO_ROOT / name for name in _ROOT_DOCS if (REPO_ROOT / name).is_file()]
    offenders = _offenders(paths, _RUN_CYCLE_INVOCATION)
    assert not offenders, (
        "Root docs point at a bash driver deleted in #298:\n" + "\n".join(offenders)
    )
