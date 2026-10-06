"""Tier-2 guard: harness e2e tests carry e2e + slow markers (T067 / US5)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_QUALITY_DIR = Path(__file__).resolve().parents[1]
# Tier-2 guards at tests/quality/*.py are not harness e2e tests.
_EXEMPT_MODULES = frozenset(
    {
        "test_baseline_update_isolation.py",
        # Spec 026: a regression-lock module (git-status pristine, machine-agnostic
        # shims, bootstrap --force). Its fast guards are SUPPOSED to run in the
        # fast loop; its one heavy runner-subprocess check is explicitly e2e+slow.
        "test_fixture_isolation.py",
        # Spec 068 (FR5): a fast (<1s) deterministic guard that a multi-category
        # vault with the rc7 stale-count shape recomputes to non-zero coverage.
        # It builds a tmp vault (no real run_cycle_steps / LLM), so it is a tier-2
        # guard meant to run in the fast loop + build.sh SMOKE_TESTS, not a
        # harness e2e test.
        "test_coverage_recompute_regression.py",
        # Spec 067 (T029): a fast (<1s) deterministic guard that a CAP-Theorem-shaped
        # note whose first body wikilink renames its own title is flagged by
        # ``deterministic_wikilink_violations`` (and a clean note is silent). No
        # real run / LLM — a tier-2 guard for the fast loop + build.sh SMOKE_TESTS.
        "test_wikilink_corruption_regression.py",
    }
)


def _pytest_mark_name(deco: ast.AST) -> str | None:
    target = deco.func if isinstance(deco, ast.Call) else deco
    if isinstance(target, ast.Attribute):
        inner = target.value
        if (
            isinstance(inner, ast.Attribute)
            and inner.attr == "mark"
            and isinstance(inner.value, ast.Name)
            and inner.value.id == "pytest"
        ):
            return target.attr
    return None


def _marker_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for deco in getattr(node, "decorator_list", ()):
        mark = _pytest_mark_name(deco)
        if mark:
            names.add(mark)
    return names


def _module_markers(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "pytestmark":
                value = node.value if isinstance(node, ast.Assign) else node.value
                if isinstance(value, ast.List):
                    for elt in value.elts:
                        mark = _pytest_mark_name(elt)
                        if mark:
                            names.add(mark)
                else:
                    mark = _pytest_mark_name(value)
                    if mark:
                        names.add(mark)
    return names


def test_every_harness_e2e_test_has_e2e_and_slow_markers() -> None:
    """US5 scenarios 1+2: top-level tests/quality/*.py e2e tests are tier-6 marked."""
    failures: list[str] = []
    for path in sorted(_QUALITY_DIR.glob("test_*.py")):
        if path.name in _EXEMPT_MODULES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        mod_markers = _module_markers(tree)
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or not node.name.startswith(
                "test_"
            ):
                continue
            fn_markers = _marker_names(node) | mod_markers
            if "e2e" not in fn_markers:
                failures.append(f"{path.name}::{node.name} missing @pytest.mark.e2e")
            if "slow" not in fn_markers:
                failures.append(f"{path.name}::{node.name} missing @pytest.mark.slow")
    if failures:
        pytest.fail(
            "Harness marker isolation:\n" + "\n".join(f"  {line}" for line in failures)
        )


def test_quality_dir_scan_is_not_vacuous() -> None:
    """Fail closed (#278): the guard above loops `_QUALITY_DIR.glob(...)` and
    only ever reports what it iterates — a moved/renamed `_QUALITY_DIR`, or
    every module becoming exempt, makes `failures` empty for the wrong
    reason and the guard passes having checked nothing."""
    scanned = [
        p for p in _QUALITY_DIR.glob("test_*.py") if p.name not in _EXEMPT_MODULES
    ]
    assert len(scanned) >= 5, (
        f"only {len(scanned)} non-exempt module(s) under {_QUALITY_DIR} — "
        "expected at least 8. A scan that finds nothing to check is not "
        "the same thing as a scan that found nothing wrong."
    )


def test_detection_logic_flags_a_missing_marker() -> None:
    """Issue #288: the two guards above assert on the real `_QUALITY_DIR`
    tree and on the scan not going vacuous — neither exercises the marker
    DETECTION primitives (`_module_markers` / `_marker_names`) against a
    known violation. Parse a synthetic module with one marker present and
    one missing and confirm the same functions
    `test_every_harness_e2e_test_has_e2e_and_slow_markers` calls actually
    report the missing one missing and the present one present."""
    source = "import pytest\n\n@pytest.mark.slow\ndef test_missing_e2e():\n    pass\n"
    tree = ast.parse(source)
    mod_markers = _module_markers(tree)
    (fn,) = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    fn_markers = _marker_names(fn) | mod_markers

    assert "slow" in fn_markers
    assert "e2e" not in fn_markers
