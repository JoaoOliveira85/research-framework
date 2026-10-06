"""Tier-2 static guard: a test must not monkeypatch ``run_cycle_steps``.

Scan root (only paths scanned):
  ``tests/**/*.py``

Excluded from scan (never reported):
  this module — it names the symbol in order to guard it.

``CLAUDE.md`` § Testing has listed "never monkey-patch ``run_cycle_steps``" as
a hard anti-pattern since the 2026-05-30 audit found ten sites, and issue #86
asks for zero. The rule was prose only: nothing failed when a new site was
added, so the count went down by hand and back up by accident.

Why the rule exists. ``run_cycle_steps`` is where every cycle invariant is
enforced. Replacing the module global from outside means the code under test
still *believes* it called the runner — the substitution is invisible at the
call site, leaks to every other test that imports the same module in the same
process, and depends on import order to bind at all. A test that does it is
asserting about a pipeline that does not exist.

What replaces it: an **injectable seam**. ``orchestrator.run_single_cycle``
and the quality harness's ``run`` / ``collect_fixture_current`` /
``_invoke_cycles`` take a keyword-only ``cycle_runner``; ``None`` (production)
resolves the real runner at call time. The substitution is then declared in
the signature, typed, and scoped to the one call.

Both spellings are gated, because the sites used both::

    monkeypatch.setattr(orch, "run_cycle_steps", ...)              # attribute
    monkeypatch.setattr("research_framework...run_cycle_steps", ...)  # dotted

Related: ``tests/_helpers/test_llm_dispatch_guard.py`` (the sibling rule, for
LLM dispatch).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOT = _REPO_ROOT / "tests"

#: This module names ``run_cycle_steps`` in prose and in test data; it is the
#: guard, so it cannot be its own violation.
_SCAN_SKIP: frozenset[str] = frozenset({"_helpers/test_cycle_runner_seam_guard.py"})

#: The patch verbs a test reaches for. ``setattr`` covers pytest's
#: ``monkeypatch``; ``patch`` / ``object`` cover ``unittest.mock``.
_PATCH_ATTRS = frozenset({"setattr", "delattr", "patch", "object"})

_GUARDED_SYMBOL = "run_cycle_steps"


@dataclass(frozen=True)
class Violation:
    rel_path: str
    line: int
    snippet: str


def _targets_guarded_symbol(node: ast.Call) -> bool:
    """True when any argument names ``run_cycle_steps`` as a patch target.

    Covers the dotted form (``"pkg.mod.run_cycle_steps"``) and the two-arg
    attribute form (``mod, "run_cycle_steps"``).
    """
    for arg in list(node.args) + [kw.value for kw in node.keywords]:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            value = arg.value
            if value == _GUARDED_SYMBOL or value.endswith("." + _GUARDED_SYMBOL):
                return True
    return False


def _is_patch_call(node: ast.Call) -> bool:
    func = node.func
    return isinstance(func, ast.Attribute) and func.attr in _PATCH_ATTRS


def scan_file(path: Path) -> list[Violation]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []
    rel = path.relative_to(SCAN_ROOT).as_posix()
    out: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_patch_call(node):
            continue
        if not _targets_guarded_symbol(node):
            continue
        out.append(
            Violation(
                rel_path=rel,
                line=node.lineno,
                snippet=ast.unparse(node.func) + "(…)",
            )
        )
    return out


def scan_tests() -> list[Violation]:
    out: list[Violation] = []
    for path in sorted(SCAN_ROOT.rglob("*.py")):
        if path.relative_to(SCAN_ROOT).as_posix() in _SCAN_SKIP:
            continue
        out.extend(scan_file(path))
    return out


def test_no_test_monkeypatches_the_cycle_runner() -> None:
    violations = scan_tests()
    assert violations == [], (
        "a test must not monkeypatch `run_cycle_steps` (CLAUDE.md § Testing, "
        "issue #86) — pass the `cycle_runner=` seam instead:\n"
        + "\n".join(f"  {v.rel_path}:{v.line}  {v.snippet}" for v in violations)
    )


def test_the_guard_detects_both_spellings(tmp_path: Path) -> None:
    """A guard that reports zero because it looks for nothing is the failure
    mode this whole battery exists to avoid (#283)."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        "monkeypatch.setattr(mod, 'run_cycle_' + 'steps', f)\n"
        "monkeypatch.setattr(mod, 'run_cycle_steps', f)\n"
        "monkeypatch.setattr('a.b.run_cycle_steps', f)\n"
        "monkeypatch.setattr(mod, 'run_cycles', f)\n",
        encoding="utf-8",
    )
    # scan_file computes a path relative to SCAN_ROOT; call the AST half directly.
    tree = ast.parse(sample.read_text(encoding="utf-8"))
    hits = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and _is_patch_call(n) and _targets_guarded_symbol(n)
    ]
    assert hits == [2, 3], (
        "expected the literal and dotted spellings to be caught, and a "
        "different symbol to be left alone"
    )
