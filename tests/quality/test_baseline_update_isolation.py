"""Tier-2 guard: only baseline_update.py may write committed baselines (T062 / FR-012)."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCAN_ROOTS = (
    _REPO_ROOT / "src",
    _REPO_ROOT / "tests",
    _REPO_ROOT / "scripts",
)
_ALLOWLIST = frozenset(
    {
        "src/research_framework/quality/baseline_update.py",
    }
)
_BASELINE_PATH_RE = re.compile(
    r"tests/fixtures/quality/baselines|\.baseline\.json|baselines/.*\.json"
)
_WRITE_MODES = frozenset({"w", "w+", "a", "a+", "x", "x+"})


@dataclass(frozen=True)
class WriteViolation:
    rel_path: str
    line: int
    snippet: str


def _rel(path: Path) -> str:
    return path.relative_to(_REPO_ROOT).as_posix()


def _line_targets_committed_baseline(lines: list[str], lineno: int) -> bool:
    if lineno < 1 or lineno > len(lines):
        return False
    return _BASELINE_PATH_RE.search(lines[lineno - 1]) is not None


def _scan_file(path: Path) -> list[WriteViolation]:
    rel = _rel(path)
    if rel in _ALLOWLIST:
        return []
    text = path.read_text(encoding="utf-8")
    if not _BASELINE_PATH_RE.search(text):
        return []
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return []

    lines = text.splitlines()
    violations: list[WriteViolation] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_baseline_write_call(node):
            if _line_targets_committed_baseline(lines, node.lineno):
                snippet = lines[node.lineno - 1].strip() if node.lineno else ""
                violations.append(WriteViolation(rel, node.lineno, snippet))
        if isinstance(node, ast.With):
            for item in node.items:
                if isinstance(item.context_expr, ast.Call):
                    call = item.context_expr
                    if _is_open_write(call) and _line_targets_committed_baseline(
                        lines, call.lineno
                    ):
                        snippet = lines[call.lineno - 1].strip()
                        violations.append(WriteViolation(rel, call.lineno, snippet))

    return violations


def _is_open_write(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name) and func.id == "open":
        return _write_mode_arg(node)
    if isinstance(func, ast.Attribute) and func.attr == "open":
        return _write_mode_arg(node)
    return False


def _write_mode_arg(node: ast.Call) -> bool:
    mode: str | None = None
    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
        mode = node.args[1].value if isinstance(node.args[1].value, str) else None
    for kw in node.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            mode = kw.value.value if isinstance(kw.value.value, str) else None
    return mode in _WRITE_MODES if mode else False


def _is_baseline_write_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Attribute):
        if func.attr in {"write_text", "write_bytes"}:
            return True
        if func.attr == "replace" and isinstance(func.value, ast.Name):
            if func.value.id in {"Path", "os"}:
                return True
    if isinstance(func, ast.Name) and func.id == "canonical_json_write":
        return True
    return _is_open_write(node)


def test_only_baseline_update_writes_committed_baselines() -> None:
    """US4 scenario 4: no non-allowlisted codepath writes baseline JSON files."""
    violations: list[WriteViolation] = []
    for root in _SCAN_ROOTS:
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if path.name.startswith("."):
                continue
            violations.extend(_scan_file(path))

    offenders = [v for v in violations if v.rel_path not in _ALLOWLIST]
    if offenders:
        lines = "\n".join(
            f"  {v.rel_path}:{v.line}: {v.snippet}"
            for v in sorted(offenders, key=lambda x: (x.rel_path, x.line))
        )
        pytest.fail(
            "Baseline write isolation violated (FR-012). Only "
            "src/research_framework/quality/baseline_update.py may write "
            f"tests/fixtures/quality/baselines/*.baseline.json:\n{lines}"
        )


def test_scan_roots_are_not_vacuous() -> None:
    """Fail closed (#278): each root above is skipped outright when it
    doesn't exist (`if not root.is_dir(): continue`), so a moved `src/` or
    `scripts/` silently shrinks what's scanned instead of erroring — and an
    empty `violations` list is indistinguishable from "scanned everything,
    found nothing"."""
    scanned = sum(
        len(list(root.rglob("*.py"))) for root in _SCAN_ROOTS if root.is_dir()
    )
    assert scanned >= 200, (
        f"only {scanned} .py file(s) found across {_SCAN_ROOTS} — expected "
        "at least 200. A scan that finds nothing to check is not the same "
        "thing as a scan that found nothing wrong."
    )


def test_detection_helpers_flag_a_disallowed_baseline_write() -> None:
    """Issue #288: the two tests above assert on the real repo tree and on
    the scan surface not going vacuous — neither exercises the detection
    helpers (`_is_baseline_write_call` / `_line_targets_committed_baseline`)
    against a KNOWN violation. Parse a synthetic write call targeting a
    committed baseline path and confirm the same helpers `_scan_file` calls
    actually flag it, and are silent on an unrelated write."""
    source = (
        "from pathlib import Path\n\n"
        "def sneaky() -> None:\n"
        '    Path("tests/fixtures/quality/baselines/x.baseline.json"'
        ').write_text("{}")\n'
    )
    tree = ast.parse(source)
    (call,) = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    lines = source.splitlines()

    assert _is_baseline_write_call(call)
    assert _line_targets_committed_baseline(lines, call.lineno)

    innocuous_lines = (
        "def fine() -> None:\n    print('no baseline here')\n".splitlines()
    )
    assert not _line_targets_committed_baseline(innocuous_lines, 2)
