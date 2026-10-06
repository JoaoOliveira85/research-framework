"""Deterministic test-coverage verifier (Foreman Arm A).

Parses ``Testing Requirements`` blocks in a ``tasks.md`` file and checks
that the named tests exist, are registered with pytest, pass, and (when
flagged) were added in same-or-earlier commits than their implementation
files.

See ``docs/foreman.md`` for the parser contract and CLI surface, and
``docs/adr/0010-foreman-verification-pattern.md`` for rationale.

This module is stdlib-only (Principle V — no new runtime dependencies).
It is dev tooling, not runtime code, and lives under ``scripts/`` per the
project's script conventions (``CLAUDE.md``).
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

# -----------------------------------------------------------------------------
# Parser
# -----------------------------------------------------------------------------

# Task header: "- [ ] T123 ..." or "- [X] T123 ..." (case-insensitive X).
_TASK_HEADER_RE = re.compile(r"^\s*-\s+\[[ xX]\]\s+(T\d+)\b(.*)$")

# Testing Requirements section header. Exact heading expected.
_TESTING_REQS_RE = re.compile(r"^\s*###\s+Testing\s+Requirements\s*$")

# Required-test line: "- **Test N**: `path::function`"
_REQUIRED_TEST_RE = re.compile(
    r"^\s*-\s+\*\*Test\s+\d+\*\*\s*:\s+`([^`]+?\.py)::([a-z_][a-z0-9_]*)`"
)

# File-only required-test line (spec 057, tolerant mode only):
# "- **Test N**: `path.py`" with NO `::function`. Anchored at end so a
# strict-shaped line never matches this (it is handled by _REQUIRED_TEST_RE).
_FILE_ONLY_TEST_RE = re.compile(r"^\s*-\s+\*\*Test\s+\d+\*\*\s*:\s+`([^`]+?\.py)`\s*$")

# Looks-like-a-Test line (weak match). When this matches but _REQUIRED_TEST_RE
# does not, the line is malformed and the parser raises ParseError. This
# closes the silent-skip loophole Copilot flagged on PR #29 (a typo'd test
# line would otherwise yield NO_REQUIREMENTS or under-counted checks).
_TEST_LIKE_RE = re.compile(r"^\s*-\s+\*\*Test\b", re.IGNORECASE)

# TDD discipline flag line (exact wording, case-sensitive).
_TDD_REQUIRED_RE = re.compile(r"^\s*\*\*TDD\s+discipline\*\*\s*:\s*required\b")
_TDD_NOT_REQUIRED_RE = re.compile(
    r"^\s*\*\*TDD\s+discipline\*\*\s*:\s*not\s+required\b"
)

# Implementation file paths quoted in task prose (only src/ and scripts/ are
# considered impl files; tests/ paths inside the task header are ignored — the
# requirements block is the authoritative source for test paths).
_IMPL_FILE_RE = re.compile(r"`(src/[^`]+\.py|scripts/[^`]+\.py)`")

# Section break — ends the current task block even without another task header.
_SECTION_BREAK_RE = re.compile(r"^\s*(---|##\s)")

# Any other ### heading (not the Testing Requirements one). Used to close a
# requirements block when the agent uses a sibling subsection.
_OTHER_HEADING_RE = re.compile(r"^\s*###\s+")


class ParseError(ValueError):
    """Raised when ``tasks.md`` contains a malformed Testing Requirements block.

    The verifier is the enforcement point for the foreman pattern, so we
    fail loudly rather than silently skipping invalid input (Copilot
    review feedback on PR #29). Caught by the CLI ``main()`` and surfaced
    as exit code 2 (parser error).
    """


def _validate_test_path(path: str, *, line_for_error: str | None = None) -> None:
    """Reject absolute paths, parent-traversal, and obviously-not-repo-relative
    paths. Required-test paths must stay inside the worktree (Copilot security
    feedback on PR #29: the grammar previously accepted any string ending in
    ``.py``, which would let a requirement reach outside the repo when the
    workdir join + pytest invocation followed).
    """
    if not path:
        raise ParseError(f"empty test path in requirement line: {line_for_error!r}")
    # POSIX-style absolute path
    if path.startswith("/"):
        raise ParseError(
            f"required test path must be repo-relative, not absolute: "
            f"{path!r} (line: {line_for_error!r})"
        )
    # Windows-style absolute (defensive)
    if len(path) >= 2 and path[1] == ":":
        raise ParseError(
            f"required test path looks like a Windows absolute path: {path!r}"
        )
    # Parent traversal — block any '..' segment to keep paths inside the repo.
    parts = path.replace("\\", "/").split("/")
    if any(part == ".." for part in parts):
        raise ParseError(
            f"required test path may not contain '..': {path!r} "
            f"(line: {line_for_error!r})"
        )
    # ``~`` expansion — block since the verifier never expands tilde, but a
    # malicious or careless input could escape via shell-style notation.
    if parts and parts[0].startswith("~"):
        raise ParseError(f"required test path may not start with '~': {path!r}")


@dataclass(frozen=True)
class RequiredTest:
    """A single test the task declared must exist.

    In strict mode ``function`` is always a non-empty test-function name and
    ``test_id`` is ``"path::function"``. In tolerant mode (spec 057) a
    *file-only* requirement carries ``function == ""`` and ``test_id == path``;
    the verifier checks file existence + ≥1 PASSED rather than a single node.
    """

    test_id: str  # "path::function" (strict) or "path" (tolerant file-only)
    path: str
    function: str


@dataclass
class TaskRequirements:
    """Requirements parsed from a single task block in tasks.md."""

    task_id: str
    impl_files: list[str] = field(default_factory=list)
    required_tests: list[RequiredTest] = field(default_factory=list)
    tdd_required: bool = False


def parse_tasks_md(
    content: str,
    matching_mode: Literal["strict", "tolerant"] = "strict",
) -> list[TaskRequirements]:
    """Parse a ``tasks.md`` body into a list of task requirements.

    Tasks without a ``### Testing Requirements`` block are still emitted
    with empty ``required_tests`` so callers can report
    ``NO_REQUIREMENTS`` status. Lines inside a requirements block that
    *look* like Test lines but fail the grammar (typo, wrong path shape,
    absolute path, parent-traversal, etc.) raise :class:`ParseError` —
    the verifier is the enforcement point for the foreman pattern, so we
    fail loudly. Non-test list items (sub-bullets like ``- Behavior:``)
    are still ignored as expected.

    ``matching_mode`` (spec 057):

    * ``"strict"`` (default) — grammar unchanged: ``- **Test N**: `p::f```
      required; a file-only line (no ``::function``) is a :class:`ParseError`.
    * ``"tolerant"`` — file-only lines ``- **Test N**: `p.py``` are accepted
      and yield a ``RequiredTest`` with ``function == ""``. Strict-shaped
      lines are still accepted (FR-008 superset). ``**TDD discipline**``
      lines are ignored — ``tdd_required`` stays ``False`` (tolerant verdicts
      are never TDD-verified).
    """
    tasks: list[TaskRequirements] = []
    current: TaskRequirements | None = None
    in_requirements = False
    current_task_id_for_error: str | None = None

    for line_no, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.rstrip()

        m_task = _TASK_HEADER_RE.match(line)
        if m_task:
            # finalize previous
            if current is not None:
                tasks.append(current)
            task_id = m_task.group(1)
            prose = m_task.group(2)
            impl_files = _IMPL_FILE_RE.findall(prose)
            current = TaskRequirements(task_id=task_id, impl_files=list(impl_files))
            current_task_id_for_error = task_id
            in_requirements = False
            continue

        # Anything below requires us to be inside a task block.
        if current is None:
            # A requirements block no task header claimed would otherwise be
            # skipped, and a tasks.md whose headers all miss the grammar
            # (e.g. "- T002 [P] ..." with no checkbox) verified as clean.
            if _TESTING_REQS_RE.match(line):
                raise ParseError(
                    f"Testing Requirements block at line {line_no} is not "
                    f"inside a parsed task — task headers must read "
                    f"`- [ ] T<NNN> …` or `- [x] T<NNN> …`"
                )
            continue

        # Section break ends the current task (even mid-requirements).
        if _SECTION_BREAK_RE.match(line):
            tasks.append(current)
            current = None
            in_requirements = False
            continue

        # Enter requirements section.
        if _TESTING_REQS_RE.match(line):
            in_requirements = True
            continue

        # A different ### heading ends the requirements section but stays in
        # the task block (so we can collect more impl_files from prose below).
        # Uses a regex to handle indented headings (markdown nested lists).
        if _OTHER_HEADING_RE.match(line):
            in_requirements = False
            continue

        # Collect impl-file references from prose lines too (not just header).
        for impl in _IMPL_FILE_RE.findall(line):
            if impl not in current.impl_files:
                current.impl_files.append(impl)

        if in_requirements:
            m_req = _REQUIRED_TEST_RE.match(line)
            if m_req:
                path, function = m_req.group(1), m_req.group(2)
                _validate_test_path(path, line_for_error=line)
                current.required_tests.append(
                    RequiredTest(
                        test_id=f"{path}::{function}", path=path, function=function
                    )
                )
                continue
            # Tolerant mode (spec 057): a file-only line — `path.py` with no
            # `::function` — is accepted as a file-level requirement. Strict
            # mode falls through to the malformed-line ParseError below.
            if matching_mode == "tolerant":
                m_file = _FILE_ONLY_TEST_RE.match(line)
                if m_file:
                    path = m_file.group(1)
                    _validate_test_path(path, line_for_error=line)
                    current.required_tests.append(
                        RequiredTest(test_id=path, path=path, function="")
                    )
                    continue
            # Strict-grammar enforcement: a line that *looks* like a Test
            # line (matches the weak ``_TEST_LIKE_RE``) but fails the active
            # grammar is a typo / malformed entry — raise ParseError so the
            # foreman surfaces it as exit-2 instead of silently dropping it.
            # In strict mode this also fires for file-only lines (FR-005).
            if _TEST_LIKE_RE.match(line):
                expected = (
                    "`- **Test <N>**: \\`<path>::<function_name>\\`` (or "
                    "`- **Test <N>**: \\`<path.py>\\`` in --tolerant mode)"
                    if matching_mode == "tolerant"
                    else "`- **Test <N>**: \\`<path>::<function_name>\\``"
                )
                raise ParseError(
                    f"malformed Testing Requirements line at line {line_no} "
                    f"of task {current_task_id_for_error}: {line!r} — "
                    f"expected grammar: {expected}"
                )
            # TDD discipline lines drive strict-mode timeline checks. In
            # tolerant mode they are ignored entirely (tdd_required stays
            # False) — tolerant verdicts are never TDD-verified (contract §4).
            if matching_mode == "strict":
                if _TDD_REQUIRED_RE.match(line):
                    current.tdd_required = True
                    continue
                if _TDD_NOT_REQUIRED_RE.match(line):
                    current.tdd_required = False
                    continue

    if current is not None:
        tasks.append(current)

    return tasks


# -----------------------------------------------------------------------------
# Verification primitives
# -----------------------------------------------------------------------------


def check_file_exists(workdir: Path, path: str) -> bool:
    return (workdir / path).is_file()


def check_function_defined(workdir: Path, path: str, function: str) -> bool:
    file_path = workdir / path
    if not file_path.is_file():
        return False
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    except SyntaxError:
        return False
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function
        for node in ast.walk(tree)
    )


def _run(
    workdir: Path, args: list[str], *, timeout: float = 120.0
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with stdout+stderr captured, no shell."""
    return subprocess.run(
        args,
        cwd=str(workdir),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def check_pytest_collect(workdir: Path, test_id: str) -> bool:
    """Return True iff pytest can collect the node id (file::function)."""
    result = _run(workdir, ["pytest", "--collect-only", "-q", test_id])
    # pytest exits 0 on successful collect (even if no tests run); 5 = no tests
    # collected. Anything else (1, 2, 3, 4) indicates a real error.
    if result.returncode != 0:
        return False
    # Even with exit 0, pytest may report "no tests ran" — guard against that.
    return "no tests ran" not in (result.stdout + result.stderr).lower()


def check_pytest_run(workdir: Path, test_id: str) -> tuple[bool, str]:
    """Return ``(passes, output)`` for running the single node id.

    A test passes ONLY when pytest both exits 0 AND prints an explicit
    ``PASSED`` status for the requested node. Skipped tests (``SKIPPED``,
    ``XFAIL``, ``XPASS``), errored tests, and runs where the requested
    node never appears all count as NOT passing — fixing a Copilot
    review bug on PR #29 where ``return_code == 0`` was treated as a
    pass even though pytest exits 0 on skip (notably for ``live_llm``
    tests which are skipped by default per ``CLAUDE.md``).
    """
    result = _run(
        workdir,
        [
            "pytest",
            "-v",
            "--tb=short",
            "--no-header",
            "-p",
            "no:cacheprovider",
            test_id,
        ],
        timeout=300.0,
    )
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        return False, output
    # Pytest -v writes one line per test: "<file>::<test> PASSED|FAILED|
    # SKIPPED|XFAIL|XPASS|ERROR". We look for explicit PASSED on the test
    # node line; anything else is treated as not-passing.
    pass_pattern = re.compile(rf"{re.escape(test_id)}\s+PASSED\b")
    if pass_pattern.search(output):
        return True, output
    # Also accept the case where pytest prints the relative path (some
    # pytest versions strip workdir prefixes). Try matching on the
    # function name alone in a ::function PASSED context as a backup.
    function = test_id.rsplit("::", 1)[-1] if "::" in test_id else test_id
    backup = re.compile(rf"::{re.escape(function)}\s+PASSED\b")
    if backup.search(output):
        return True, output
    return False, output


def check_file_has_passing_test(workdir: Path, path: str) -> bool:
    """Return True iff the test *file* has at least one PASSED test (spec 057).

    Tolerant retro mode verifies coverage at file granularity: a file
    "passes" when ``pytest -v <path>`` prints at least one ``PASSED`` line.
    A missing file, a file with zero tests, or a file whose tests are all
    SKIPPED / XFAIL / ERROR (no ``PASSED``) → ``False``. The return-code is
    intentionally *not* the gate (pytest exits 0 on all-skipped), mirroring
    the per-node ``check_pytest_run`` PASSED-line discipline (PR #29).
    """
    if not (workdir / path).is_file():
        return False
    result = _run(
        workdir,
        ["pytest", "-v", "--tb=short", "--no-header", "-p", "no:cacheprovider", path],
        timeout=300.0,
    )
    output = result.stdout + result.stderr
    return re.search(r"\bPASSED\b", output) is not None


def _first_commit_for(workdir: Path, path: str, base_ref: str) -> str | None:
    """Return the SHA of the first commit on the branch that touched ``path``.

    Strategy: look for ADD commits first (``--diff-filter=A``); if none,
    fall back to MODIFY commits (``--diff-filter=M``). The fallback lets
    TDD discipline checks work for tasks that modify *existing*
    framework files — Copilot flagged the prior add-only behavior on
    PR #29 as a false negative for legitimate refactor/extend tasks.

    Returns ``None`` if the file was never touched in ``base_ref..HEAD``.
    """
    for diff_filter in ("A", "M"):
        result = _run(
            workdir,
            [
                "git",
                "log",
                f"{base_ref}..HEAD",
                f"--diff-filter={diff_filter}",
                "--follow",
                "--reverse",
                "--format=%H",
                "--",
                path,
            ],
        )
        if result.returncode != 0:
            continue
        shas = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if shas:
            return shas[0]
    return None


def _branch_commits_in_order(workdir: Path, base_ref: str) -> list[str]:
    """Return commit SHAs in ``base_ref..HEAD`` in topological order
    (oldest-ancestor first).

    Uses ``git log --reverse --topo-order`` so the position of a commit
    in the resulting list reflects branch ancestry, NOT wall-clock
    timestamps. This sidesteps two Copilot-flagged failure modes on
    PR #29: (a) same-second commits whose `%ct` values are equal, and
    (b) commits whose author/committer timestamps have been skewed
    (e.g. by rebase or by deliberate manipulation).
    """
    result = _run(
        workdir,
        [
            "git",
            "log",
            f"{base_ref}..HEAD",
            "--reverse",
            "--topo-order",
            "--format=%H",
        ],
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def check_tdd_timeline(
    workdir: Path, test_path: str, impl_path: str, base_ref: str
) -> tuple[bool, str]:
    """Verify the test file was added in same-or-earlier commit than impl.

    Uses **commit topological order** (``git log --reverse --topo-order``)
    rather than wall-clock timestamps. Two commits made in the same
    second, or commits whose author/committer timestamps have been
    rewritten by rebase, would otherwise yield false positives /
    negatives — see the Copilot review comment on PR #29 (the original
    implementation compared ``%ct`` values, which is unreliable).

    Returns ``(ok, reason)``. If either file cannot be located in
    ``base_ref..HEAD``, returns ``(False, <reason>)`` — TDD discipline
    cannot be verified for files that don't appear in the branch's diff.
    """
    test_sha = _first_commit_for(workdir, test_path, base_ref)
    impl_sha = _first_commit_for(workdir, impl_path, base_ref)
    if test_sha is None:
        return False, f"test file {test_path} not touched on this branch"
    if impl_sha is None:
        return False, f"impl file {impl_path} not touched on this branch"
    if test_sha == impl_sha:
        return True, "test and impl in the same commit (TDD-clean squash)"

    order = _branch_commits_in_order(workdir, base_ref)
    if test_sha not in order:
        return (
            False,
            f"test commit {test_sha[:8]} not in {base_ref}..HEAD topology",
        )
    if impl_sha not in order:
        return (
            False,
            f"impl commit {impl_sha[:8]} not in {base_ref}..HEAD topology",
        )
    test_pos = order.index(test_sha)
    impl_pos = order.index(impl_sha)
    if test_pos <= impl_pos:
        return (
            True,
            f"test at commit position {test_pos} ≤ impl at position {impl_pos}",
        )
    return (
        False,
        f"test at commit position {test_pos} AFTER impl at position "
        f"{impl_pos} — TDD violation",
    )


# -----------------------------------------------------------------------------
# Top-level verification
# -----------------------------------------------------------------------------

# Type alias kept loose so tests can introspect dict shape.
TaskStatus = Literal["PASS", "FAIL", "NO_REQUIREMENTS"]
RequirementStatus = Literal["PASS", "FAIL"]


def _verify_requirement(
    workdir: Path,
    req: RequiredTest,
    tdd_required: bool,
    impl_files: list[str],
    base_ref: str,
) -> dict:
    """Verify a single required test against the workdir."""
    result: dict = {
        "test_id": req.test_id,
        "file_exists": False,
        "function_defined": False,
        "collected_by_pytest": False,
        "test_passes": None,
        "tdd_timeline_ok": None,
        "status": "FAIL",
        "reason": None,
    }

    if not check_file_exists(workdir, req.path):
        result["reason"] = f"file {req.path} not present in workdir"
        return result
    result["file_exists"] = True

    if not check_function_defined(workdir, req.path, req.function):
        result["reason"] = f"function {req.function!r} not defined in {req.path}"
        return result
    result["function_defined"] = True

    if not check_pytest_collect(workdir, req.test_id):
        result["reason"] = "pytest could not collect this node id"
        return result
    result["collected_by_pytest"] = True

    passes, output = check_pytest_run(workdir, req.test_id)
    result["test_passes"] = passes
    if not passes:
        # Truncate output to keep the JSON manageable.
        snippet = output[-800:] if len(output) > 800 else output
        result["reason"] = f"test failed; pytest tail: {snippet}"
        return result

    if tdd_required:
        if not impl_files:
            result["tdd_timeline_ok"] = False
            result["reason"] = (
                "TDD required but task prose declares no `src/...` or "
                "`scripts/...` impl file to check timeline against"
            )
            return result
        timeline_failures: list[str] = []
        for impl in impl_files:
            ok, reason = check_tdd_timeline(workdir, req.path, impl, base_ref)
            if not ok:
                timeline_failures.append(f"{impl}: {reason}")
        if timeline_failures:
            result["tdd_timeline_ok"] = False
            result["reason"] = "TDD timeline violation — " + "; ".join(
                timeline_failures
            )
            return result
        result["tdd_timeline_ok"] = True

    result["status"] = "PASS"
    return result


def _verify_file_requirement(workdir: Path, req: RequiredTest) -> dict:
    """Verify a tolerant *file-only* requirement (spec 057).

    Checks file existence + ≥1 PASSED test in the file. ``function_defined``,
    ``collected_by_pytest`` and ``tdd_timeline_ok`` are always ``None`` — they
    are node-level / TDD concepts that do not apply at file granularity
    (verdict-report contract §3). ``tdd_timeline_ok`` MUST NOT be ``True`` in
    tolerant mode.
    """
    result: dict = {
        "test_id": req.path,
        "file_exists": False,
        "function_defined": None,
        "collected_by_pytest": None,
        "test_passes": False,
        "tdd_timeline_ok": None,
        "status": "FAIL",
        "reason": None,
    }

    if not check_file_exists(workdir, req.path):
        result["reason"] = f"file {req.path} not present in workdir"
        return result
    result["file_exists"] = True

    if not check_file_has_passing_test(workdir, req.path):
        result["reason"] = f"no passing test found in {req.path}"
        return result
    result["test_passes"] = True

    result["status"] = "PASS"
    return result


def verify(
    workdir: Path,
    tasks_file: Path,
    base_ref: str = "origin/main",
    matching_mode: Literal["strict", "tolerant"] = "strict",
) -> dict:
    """Run end-to-end verification, return JSON-ready report dict.

    The report has shape::

        {
          "summary": {...},
          "tasks": [
            {"id": "T003", "status": "PASS"|"FAIL"|"NO_REQUIREMENTS",
             "tdd_required": bool, "requirements": [...]},
            ...
          ]
        }
    """
    if not tasks_file.is_file():
        raise FileNotFoundError(f"tasks file not found: {tasks_file}")
    if not workdir.is_dir():
        raise FileNotFoundError(f"workdir not a directory: {workdir}")

    parsed = parse_tasks_md(
        tasks_file.read_text(encoding="utf-8"), matching_mode=matching_mode
    )

    task_reports: list[dict] = []
    summary = {
        "matching_mode": matching_mode,
        "tasks_total": len(parsed),
        "tasks_with_requirements": 0,
        "tasks_without_requirements": 0,
        "tasks_passing": 0,
        "tasks_failing": 0,
        "requirements_total": 0,
        "requirements_passing": 0,
        "requirements_failing": 0,
    }

    for task in parsed:
        task_report: dict = {
            "id": task.task_id,
            "tdd_required": task.tdd_required,
            "impl_files": list(task.impl_files),
            "requirements": [],
            "status": "NO_REQUIREMENTS",
        }

        if not task.required_tests:
            summary["tasks_without_requirements"] += 1
            task_reports.append(task_report)
            continue

        summary["tasks_with_requirements"] += 1
        all_pass = True
        for req in task.required_tests:
            # File-only requirements (function == "") only occur in tolerant
            # mode and use the file-level verifier. Strict-shaped requirements
            # use the per-node path; in tolerant mode ``tdd_required`` is
            # always False so the TDD-timeline branch is skipped (FR-008).
            if req.function == "":
                req_report = _verify_file_requirement(workdir, req)
            else:
                req_report = _verify_requirement(
                    workdir, req, task.tdd_required, task.impl_files, base_ref
                )
            task_report["requirements"].append(req_report)
            summary["requirements_total"] += 1
            if req_report["status"] == "PASS":
                summary["requirements_passing"] += 1
            else:
                summary["requirements_failing"] += 1
                all_pass = False

        task_report["status"] = "PASS" if all_pass else "FAIL"
        if all_pass:
            summary["tasks_passing"] += 1
        else:
            summary["tasks_failing"] += 1
        task_reports.append(task_report)

    return {"summary": summary, "tasks": task_reports}


# -----------------------------------------------------------------------------
# Human-readable rendering
# -----------------------------------------------------------------------------


def _render_text(report: dict) -> str:
    lines: list[str] = []
    s = report["summary"]
    lines.append("=" * 72)
    lines.append("Foreman Arm A — deterministic test-coverage verifier")
    lines.append("=" * 72)
    # Spec 057: mode banner so a tolerant (file-level, not TDD-verified)
    # verdict can never be mistaken for a strict / TDD foreman sign-off.
    if s.get("matching_mode") == "tolerant":
        lines.append("MODE: tolerant — file-level coverage only (not TDD-verified)")
    else:
        lines.append("MODE: strict")
    lines.append(
        f"Tasks: {s['tasks_total']} total | "
        f"{s['tasks_with_requirements']} with requirements | "
        f"{s['tasks_without_requirements']} without"
    )
    lines.append(
        f"Requirements: {s['requirements_total']} total | "
        f"{s['requirements_passing']} pass | {s['requirements_failing']} fail"
    )
    lines.append(
        f"Task verdicts: {s['tasks_passing']} PASS | "
        f"{s['tasks_failing']} FAIL | {s['tasks_without_requirements']} N/A"
    )
    lines.append("")

    failing_tasks = [t for t in report["tasks"] if t["status"] == "FAIL"]
    if not failing_tasks:
        lines.append("✓ All declared Testing Requirements satisfied.")
    else:
        lines.append(f"✗ {len(failing_tasks)} task(s) failed verification:")
        lines.append("")
        for task in failing_tasks:
            lines.append(f"  {task['id']}  (tdd_required={task['tdd_required']})")
            for req in task["requirements"]:
                if req["status"] == "PASS":
                    continue
                lines.append(f"    ✗ {req['test_id']}")
                lines.append(f"        reason: {req['reason']}")
            lines.append("")
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m scripts.foreman.verify_test_coverage",
        description=(
            "Deterministic test-coverage verifier (Foreman Arm A). "
            "Parses ### Testing Requirements blocks in a tasks.md file "
            "and checks that the named tests exist, pass, and obey TDD "
            "timeline when flagged. See docs/foreman.md."
        ),
    )
    p.add_argument(
        "--tasks", required=True, type=Path, help="Path to the tasks.md to verify."
    )
    p.add_argument(
        "--workdir",
        required=True,
        type=Path,
        help="Git worktree to verify against (must be a valid git repo).",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON report to stdout instead of human-readable text.",
    )
    p.add_argument(
        "--base-ref",
        default="origin/main",
        help="Base ref for TDD-timeline checks (default: origin/main).",
    )
    p.add_argument(
        "--tolerant",
        action="store_true",
        help=(
            "Tolerant retro mode (spec 057): verify Testing Requirements at "
            "FILE granularity (file exists + >=1 PASSED test). Accepts file-only "
            "`- **Test N**: `path.py`` lines and ignores TDD-discipline flags. "
            "A tolerant PASS is NOT a TDD / strict foreman sign-off."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    matching_mode = "tolerant" if args.tolerant else "strict"
    try:
        report = verify(
            args.workdir, args.tasks, args.base_ref, matching_mode=matching_mode
        )
    except FileNotFoundError as exc:
        sys.stderr.write(f"foreman: {exc}\n")
        return 2
    except ParseError as exc:
        sys.stderr.write(f"foreman: parser error — {exc}\n")
        return 2

    if args.json:
        sys.stdout.write(json.dumps(report, indent=2, default=_json_default))
        sys.stdout.write("\n")
    else:
        sys.stdout.write(_render_text(report))
        sys.stdout.write("\n")

    if report["summary"]["tasks_failing"] > 0:
        return 1
    return 0


def _json_default(obj: object) -> object:
    # dataclass passthrough kept for symmetry; current report is already pure
    # dict, but this protects future shape evolutions.
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)  # type: ignore[arg-type]
    raise TypeError(f"Object of type {type(obj)!r} is not JSON serializable")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
