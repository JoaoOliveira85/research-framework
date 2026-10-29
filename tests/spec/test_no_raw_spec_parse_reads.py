"""Static guard: nothing under ``src/`` or ``scripts/`` reads ``spec-parse.json``
directly (issue #9).

The parsed spec is read through ``spec.parsed.load_parsed_spec`` so that its
freshness is decided in one place. A path built from the ``spec-parse.json``
literal (``vault / "_pipeline" / "spec-parse.json"``, ``Path("...")``) is the
signature of a raw read, so this test fails on any such path that is not on the
allow-list below. Prose, error messages and manifest entries are not paths and
are not flagged.

If a new reader needs the *file itself* (not the parsed spec), add it to
``ALLOWED`` with the reason; otherwise route it through the loader.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LITERAL = "spec-parse.json"

#: (repo-relative file, enclosing function or "<module>") -> why a path may be built.
ALLOWED: dict[tuple[str, str], str] = {
    ("src/research_framework/spec/parsed.py", "<module>"): "the loader's own path",
    (
        "src/research_framework/cli_inventory.py",
        "_build_pipeline_state",
    ): "reports the file's own presence, validity and framework_version",
    (
        "src/research_framework/pipeline/scaffold_baseline.py",
        "_read_framework_version",
    ): "reads the cache's framework_version metadata, not the parsed spec",
}
#: ImportError fallbacks in the standalone per-vault scripts.
for _script in (
    "validate_cycle",
    "check_intent_drift",
    "check_code_source_coverage",
    "topic_propose",
    "repo_scan",
    "check_trunk_inversion",
):
    ALLOWED[(f"scripts/{_script}.py", "_parsed_spec")] = (
        "stdlib-only fallback when research_framework is not importable"
    )


def _path_builds(tree: ast.AST) -> list[tuple[int, str]]:
    """``(line, enclosing function)`` for every path built from the literal."""
    hits: list[tuple[int, str]] = []

    def visit(node: ast.AST, scope: str) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scope = node.name
        for child in ast.iter_child_nodes(node):
            if _is_literal(child) and _is_path_operand(node, child):
                hits.append((child.lineno, scope))
            visit(child, scope)

    visit(tree, "<module>")
    return hits


def _is_literal(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and LITERAL in node.value
    )


def _is_path_operand(parent: ast.AST, child: ast.AST) -> bool:
    if isinstance(parent, ast.BinOp) and isinstance(parent.op, ast.Div):
        return True
    if isinstance(parent, ast.Call):
        func = parent.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        return name in {"Path", "joinpath", "open"}
    return False


def _violations() -> list[str]:
    found: list[str] = []
    for root in ("src", "scripts"):
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for line, scope in _path_builds(tree):
                if (rel, scope) not in ALLOWED:
                    found.append(f"{rel}:{line} in {scope}()")
    return found


def test_no_raw_reads_of_spec_parse_json() -> None:
    assert _violations() == [], (
        "these build a path to spec-parse.json directly; read the parsed spec "
        "with research_framework.spec.parsed.load_parsed_spec instead, or add "
        "the site to ALLOWED in this test with a reason"
    )


def test_the_allow_list_has_no_stale_entries() -> None:
    live = set()
    for root in ("src", "scripts"):
        for path in (REPO_ROOT / root).rglob("*.py"):
            rel = path.relative_to(REPO_ROOT).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"))
            live.update((rel, scope) for _, scope in _path_builds(tree))
    assert set(ALLOWED) <= live, sorted(set(ALLOWED) - live)


def test_the_guard_flags_a_raw_read() -> None:
    tree = ast.parse(
        "def f(vault):\n"
        "    return (vault / '_pipeline' / 'spec-parse.json').read_text()\n"
    )
    assert _path_builds(tree) == [(2, "f")]


def test_the_guard_ignores_messages_and_manifest_entries() -> None:
    tree = ast.parse(
        'MSG = "spec-parse.json not found"\nPATHS = ["_pipeline/spec-parse.json"]\n'
    )
    assert _path_builds(tree) == []
