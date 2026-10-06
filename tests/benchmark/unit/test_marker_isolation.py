"""Guard: no hermetic benchmark test performs live dispatch (spec 056 SC-007/SC-010; T034).

Any test module under ``tests/benchmark/`` whose *code* (not docstrings/comments)
touches a live-dispatch surface — an ``import subprocess`` or a call to
``…live_dispatch(…)`` — MUST carry the ``@pytest.mark.live_llm`` marker so it is
skipped by default. AST-based so prose mentioning the seam doesn't trip the guard.
"""

from __future__ import annotations

import ast
from pathlib import Path

_BENCHMARK_TESTS = Path(__file__).resolve().parents[1]
_SELF = Path(__file__).name


def _uses_live_dispatch(tree: ast.AST) -> str | None:
    """Return the offending construct name, or None — AST only (ignores strings)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "subprocess":
                    return "import subprocess"
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "subprocess":
                return "from subprocess import …"
        elif isinstance(node, ast.Attribute) and node.attr == "live_dispatch":
            return "live_dispatch(…)"
        elif isinstance(node, ast.Name) and node.id == "live_dispatch":
            return "live_dispatch(…)"
    return None


def _has_live_llm_marker(tree: ast.AST) -> bool:
    """True if the module carries a real ``live_llm`` marker — AST, not substring.

    Matches both ``@pytest.mark.live_llm`` decorators and a module-level
    ``pytestmark = pytest.mark.live_llm`` (or a list thereof): any ``ast.Attribute``
    whose ``attr == "live_llm"`` is a code reference to the marker, so a mention in a
    docstring/comment can neither satisfy nor trip the guard.
    """
    return any(
        isinstance(node, ast.Attribute) and node.attr == "live_llm"
        for node in ast.walk(tree)
    )


def test_no_unmarked_live_dispatch_in_benchmark_tests() -> None:
    offenders: list[str] = []
    for path in _BENCHMARK_TESTS.rglob("test_*.py"):
        if path.name == _SELF:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        hit = _uses_live_dispatch(tree)
        if hit and not _has_live_llm_marker(tree):
            offenders.append(f"{path.name} uses {hit} without @pytest.mark.live_llm")
    assert not offenders, (
        "Unmarked live-dispatch in hermetic benchmark tests:\n" + "\n".join(offenders)
    )


def test_benchmark_tests_scan_is_not_vacuous() -> None:
    """Fail closed (#278): a moved/renamed `tests/benchmark/` would make the
    guard above iterate zero files and report zero offenders — passing for
    having checked nothing rather than for having checked and found it clean."""
    scanned = [p for p in _BENCHMARK_TESTS.rglob("test_*.py") if p.name != _SELF]
    assert len(scanned) >= 3, (
        f"only {len(scanned)} module(s) found under {_BENCHMARK_TESTS} — "
        "expected at least 3. A scan that finds nothing to check is not "
        "the same thing as a scan that found nothing wrong."
    )


def test_detection_logic_flags_an_unmarked_live_dispatch_call() -> None:
    """Issue #288: the two guards above assert on the real `tests/benchmark/`
    tree and on the scan not going vacuous — neither exercises the detection
    primitives (`_uses_live_dispatch` / `_has_live_llm_marker`) against a
    known violation. Parse a synthetic module that calls `live_dispatch()`
    with no `live_llm` marker and confirm the same functions
    `test_no_unmarked_live_dispatch_in_benchmark_tests` calls actually flag
    it — and are silent once the marker is present."""
    unmarked = ast.parse("def test_x():\n    live_dispatch()\n")
    assert _uses_live_dispatch(unmarked) == "live_dispatch(…)"
    assert not _has_live_llm_marker(unmarked)

    marked = ast.parse(
        "import pytest\n\npytestmark = pytest.mark.live_llm\n\n"
        "def test_x():\n    live_dispatch()\n"
    )
    assert _has_live_llm_marker(marked)
