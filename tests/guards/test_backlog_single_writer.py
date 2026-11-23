"""Spec 084 FR-006 / acceptance 7: only the backlog module writes the backlog.

A static scan of ``src/`` and ``scripts/`` (an AST walk, not a regex over text).
It is a guard, not a proof: it catches the shapes a writer takes in this
codebase -- a write call whose receiver or arguments reach one of the module's
path accessors, a name assigned from one, or a literal path string.

Owners may write: ``pipeline/backlog.py`` (the store, the view and the
overwritten copy) and, through ``backlog.install_store`` only,
``pipeline/backlog_conversion.py`` (whose own ``write_bytes`` targets the
archive). Files that merely *name* a backlog path (a registry row, a manifest
pattern, a legacy ``.gitignore`` stanza) are listed with the reason.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

OWNER = "src/research_framework/pipeline/backlog.py"
# Never writes either path itself; it hands entries to ``backlog.install_store``.
CONVERTER = "src/research_framework/pipeline/backlog_conversion.py"
# Name a backlog path without opening it.
NAMES_ONLY = {
    "src/research_framework/pipeline/state_layout.py": "the registry rows",
    "scripts/build_scaffold_manifest.py": "the manifest's exclusions and patterns",
}

_ACCESSORS = {
    "research_backlog_path",
    "store_path",
    "view_path",
    "overwritten_path",
}
_WRITE_CALLS = {
    "write_text",
    "write_bytes",
    "write_json",
    "open",
    "replace",
    "rename",
    "unlink",
    "copy",
    "copy2",
    "copyfile",
    "move",
    "remove",
    "install_store",
    "touch",
}
_PATH_LITERALS = ("research-backlog.md", "research-backlog.json")


def _name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


_NAME_ONLY_ATTRS = {"name", "stem", "suffix", "parent"}


def _reaches_a_backlog_path(node: ast.AST, tainted: set[str]) -> bool:
    """True if ``node`` evaluates to (or is built from) a backlog path.

    ``accessor(v).name`` is only a string drawn from the path, so the walk
    does not descend through ``.name`` / ``.stem`` / ``.suffix`` / ``.parent``.
    """
    if isinstance(node, ast.Attribute) and node.attr in _NAME_ONLY_ATTRS:
        return False
    if isinstance(node, ast.Call) and _name(node.func) in _ACCESSORS:
        return True
    if isinstance(node, ast.Name) and node.id in tainted:
        return True
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return any(lit in node.value for lit in _PATH_LITERALS)
    return any(
        _reaches_a_backlog_path(child, tainted) for child in ast.iter_child_nodes(node)
    )


def writes_a_backlog_path(source: str) -> list[int]:
    """Line numbers of write calls that reach a backlog path in ``source``."""
    tree = ast.parse(source)
    tainted: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _reaches_a_backlog_path(
            node.value, tainted
        ):
            tainted.update(t.id for t in node.targets if isinstance(t, ast.Name))
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _name(node.func) not in _WRITE_CALLS:
            continue
        reachable = [*node.args, *(k.value for k in node.keywords)]
        if isinstance(node.func, ast.Attribute):
            reachable.append(node.func.value)
        if any(_reaches_a_backlog_path(part, tainted) for part in reachable):
            lines.append(node.lineno)
    return sorted(lines)


def _sources(root: Path) -> list[tuple[str, str]]:
    found = []
    for base in ("src", "scripts"):
        for path in sorted((root / base).rglob("*.py")):
            found.append((path.relative_to(root).as_posix(), path.read_text("utf-8")))
    return found


def offenders(sources: list[tuple[str, str]]) -> dict[str, list[int]]:
    """Files other than the owner whose code writes a backlog path."""
    bad: dict[str, list[int]] = {}
    for rel, text in sources:
        if rel == OWNER:
            continue
        lines = writes_a_backlog_path(text)
        if lines:
            bad[rel] = lines
    return bad


def test_only_the_module_writes_either_backlog_path() -> None:
    sources = _sources(ROOT)
    bad = offenders(sources)
    # The converter hands its entries to ``backlog.install_store``: that call
    # is its only write that reaches a backlog path (its other write is the
    # archive's, which is not one).
    converter = dict(sources)[CONVERTER]
    install_lines = [
        n.lineno
        for n in ast.walk(ast.parse(converter))
        if isinstance(n, ast.Call) and _name(n.func) == "install_store"
    ]
    assert install_lines, "the converter should install through the module"
    assert set(bad.pop(CONVERTER, [])) <= set(install_lines)
    assert not bad, f"only {OWNER} may write the backlog; found writers: {bad}"


def test_names_only_files_do_not_write() -> None:
    sources = dict(_sources(ROOT))
    for rel in NAMES_ONLY:
        assert rel in sources, rel
        assert writes_a_backlog_path(sources[rel]) == [], rel


def test_a_planted_writer_fails_the_guard(tmp_path: Path) -> None:
    planted = {
        "direct store write": (
            "from research_framework.pipeline import state_layout\n"
            "def f(v):\n"
            "    state_layout.research_backlog_path(v).write_text('{}')\n"
        ),
        "write through a name": (
            "from research_framework.pipeline import backlog\n"
            "def f(v):\n"
            "    p = backlog.view_path(v)\n"
            "    p.write_text('x')\n"
        ),
        "literal path": (
            "def f(v):\n"
            "    open(v / '_pipeline' / 'research-backlog.md', 'w').write('x')\n"
        ),
        "unlink": (
            "from research_framework.pipeline import backlog\n"
            "def f(v):\n    backlog.store_path(v).unlink()\n"
        ),
    }
    for label, source in planted.items():
        assert writes_a_backlog_path(source), label
    bad = offenders([("scripts/evil.py", planted["direct store write"])])
    assert bad == {"scripts/evil.py": [3]}
    # Reading is fine.
    assert not writes_a_backlog_path(
        "from research_framework.pipeline import backlog\n"
        "def f(v):\n    return backlog.store_path(v).read_text()\n"
    )
