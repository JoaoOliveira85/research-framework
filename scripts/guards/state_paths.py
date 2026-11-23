#!/usr/bin/env python3
"""Guard: only ``state_layout`` spells a state artefact's name (spec 083 FR-005).

``src/research_framework/pipeline/state_layout.py`` is the one place a state
path is written down. A second spelling is how a file ends up half-moved: the
writer follows the layout module, a reader somewhere else still builds
``_pipeline/propose-rejects.md`` by hand. This guard fails when any other file
under ``src/`` or ``scripts/`` carries the name of a registry artefact
(``state_layout.STATE_ARTEFACTS``) in a string literal.

**How it detects.** An AST walk over string constants, not a regex over text:
a regex cannot tell code from the prose around it, and these names (``sources.db``,
``quarantine``) are exactly what comments and docstrings discuss. Docstrings
(the leading string of a module, class or function) are skipped, comments are
invisible to the AST, and f-strings are covered because their literal parts are
constants. A literal matches when a ``/``-separated segment of it IS an
artefact's name (``"coverage-targets.json"``, ``"_pipeline/sources.db"``,
``"_pipeline/quarantine/"``) and the literal has no whitespace. A sentence in a
log or help message that mentions a path is prose, not a path, and is not
flagged; a name joined as ``vault / "_pipeline" / "x.md"`` is, because the
segment is a constant of its own.

**What it does not do.** It cannot see a name assembled at run time
(``"coverage" + "-targets.json"``). Like ``parser_flag_consumers`` it closes the
cheap half of the class and says so.

**Fail-closed.** It reports how many files and artefact names it scanned and
fails when either is zero, so an empty scan root cannot pass vacuously.
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from research_framework.pipeline import state_layout  # noqa: E402

LAYOUT_MODULE = "src/research_framework/pipeline/state_layout.py"
# The guard itself names the artefacts it polices in its allowlists.
SELF = "scripts/guards/state_paths.py"
SCAN_ROOTS = ("src", "scripts")

# The Markdown backlog stays where it is until spec 084 converts it, so its
# legacy name may appear anywhere. Spec 084 adds the JSON store, its converter
# and the ``.pre-migration.md`` snapshot; only those modules may name them.
# Both lists are explicit so that widening one is a reviewed edit.
EXEMPT_EVERYWHERE = frozenset({"research-backlog.md"})
ALLOWED_IN_FILE: dict[str, frozenset[str]] = {
    "src/research_framework/pipeline/backlog.py": frozenset(
        {"research-backlog.json", "research-backlog.pre-migration.md"}
    ),
    "src/research_framework/pipeline/backlog_conversion.py": frozenset(
        {"research-backlog.json", "research-backlog.pre-migration.md"}
    ),
    # ``quarantine`` is also an everyday word. These two uses are not the state
    # directory: the source bridge's per-module raw-signal quarantine under
    # ``_pipeline/sources/<module>/``, and the ``quarantine/`` id prefix the
    # claims export gives notes it reads FROM ``state_layout.quarantine_dir``.
    "src/research_framework/pipeline/source_bridge/cache.py": frozenset({"quarantine"}),
    "src/research_framework/vault/claims_export.py": frozenset({"quarantine"}),
}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    literal: str
    name: str

    def render(self) -> str:
        return (
            f"{self.path}:{self.line}: {self.literal!r} spells state artefact "
            f"{self.name!r}; use state_layout instead"
        )


def artefact_names() -> set[str]:
    """Basename of every registry artefact (the directory name for a dir row)."""
    names: set[str] = set()
    for art in state_layout.STATE_ARTEFACTS:
        for rel in (art.new_rel, art.legacy_rel):
            if rel:
                names.add(rel.rstrip("/").rsplit("/", 1)[-1])
    return names - EXEMPT_EVERYWHERE


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def scan_source(
    text: str, rel: str, names: set[str], *, allowed: frozenset[str] = frozenset()
) -> list[Finding]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    skip = _docstring_nodes(tree)
    found: list[Finding] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in skip:
            continue
        if any(ch.isspace() for ch in node.value):
            continue  # prose, not a path
        segments = {seg for seg in node.value.split("/") if seg}
        for name in sorted(names & segments):
            if name not in allowed:
                found.append(Finding(rel, node.lineno, node.value, name))
    return found


def scan_tree(repo_root: Path) -> tuple[list[Finding], int]:
    names = artefact_names()
    findings: list[Finding] = []
    scanned = 0
    for root in SCAN_ROOTS:
        for path in sorted((repo_root / root).rglob("*.py")):
            rel = path.relative_to(repo_root).as_posix()
            if rel in (LAYOUT_MODULE, SELF):
                continue
            scanned += 1
            findings += scan_source(
                path.read_text(encoding="utf-8"),
                rel,
                names,
                allowed=ALLOWED_IN_FILE.get(rel, frozenset()),
            )
    return findings, scanned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=_REPO_ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    findings, scanned = scan_tree(args.root)
    names = artefact_names()
    if scanned == 0 or not names:
        print(
            "state-paths: scanned nothing; refusing to pass vacuously", file=sys.stderr
        )
        return 2
    for finding in findings:
        print(finding.render(), file=sys.stderr)
    print(
        f"state-paths: {scanned} files, {len(names)} artefact names, "
        f"{len(findings)} finding(s)"
    )
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
