"""Tests for the foreman verifier (Arm A) — scripts/foreman/verify_test_coverage.

These tests cover three layers:

1. Parser — given a tasks.md body, does it extract the right tasks +
   Testing Requirements?
2. Primitives — file existence, AST function detection, TDD timeline
   check via git.
3. End-to-end ``verify()`` — spinning a tiny temp git repo with a real
   tasks.md + real python test files + real pytest subprocess.

The end-to-end tests are slower (each spawns one or two pytest
subprocesses) but are necessary because the verifier's contract is
"pytest exit code determines pass/fail" — mocking would defeat the
purpose.

Spec 057 (tolerant retro matching) insertion points (FR-001 baseline):
  * parser  — ``parse_tasks_md(content, matching_mode="strict"|"tolerant")``;
              tolerant accepts file-only ``- **Test N**: `path.py``` lines.
  * primitive — ``check_file_has_passing_test(workdir, path)`` → ≥1 PASSED.
  * verify  — ``verify(..., matching_mode=...)`` stamps ``summary.matching_mode``
              and routes file-only reqs through ``_verify_file_requirement``.
  * CLI     — ``--tolerant`` flag on ``_build_parser()`` / ``main()``.
  * report  — ``_render_text`` MODE banner (``MODE: tolerant`` / ``MODE: strict``).
"""

from __future__ import annotations

import json as _json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts.foreman.verify_test_coverage import (
    ParseError,
    RequiredTest,
    _branch_commits_in_order,
    _first_commit_for,
    _render_text,
    check_file_exists,
    check_file_has_passing_test,
    check_function_defined,
    parse_tasks_md,
    verify,
)

# When tests run, the project repo is the cwd. The verifier module lives
# under ``scripts/foreman``; pytest can import it because pytest adds the
# project root to sys.path via the rootdir.

# -----------------------------------------------------------------------------
# Parser tests
# -----------------------------------------------------------------------------


class TestParser:
    def test_empty_input_returns_empty_list(self) -> None:
        assert parse_tasks_md("") == []

    def test_task_header_without_requirements(self) -> None:
        tasks = parse_tasks_md("- [ ] T001 Confirm Phase 1 scope\n")
        assert len(tasks) == 1
        assert tasks[0].task_id == "T001"
        assert tasks[0].required_tests == []
        assert tasks[0].tdd_required is False
        assert tasks[0].impl_files == []

    def test_task_with_single_impl_file_in_prose(self) -> None:
        md = "- [ ] T003 Implement `src/research_framework/pipeline/atomic_write.py`\n"
        tasks = parse_tasks_md(md)
        assert tasks[0].impl_files == [
            "src/research_framework/pipeline/atomic_write.py"
        ]

    def test_task_with_two_impl_files_in_prose(self) -> None:
        md = (
            "- [ ] T005 Extract from `src/research_framework/generator/"
            "scaffold.py` to `scripts/agent_call.py`\n"
        )
        tasks = parse_tasks_md(md)
        assert "src/research_framework/generator/scaffold.py" in tasks[0].impl_files
        assert "scripts/agent_call.py" in tasks[0].impl_files

    def test_testing_requirements_block_with_tdd_required(self) -> None:
        md = """- [ ] T003 Implement `src/x.py`

  ### Testing Requirements

  - **Test 1**: `tests/test_x.py::test_alpha`
    - Behavior: alpha
  - **Test 2**: `tests/test_x.py::test_beta`

  **TDD discipline**: required
"""
        tasks = parse_tasks_md(md)
        assert len(tasks) == 1
        t = tasks[0]
        assert len(t.required_tests) == 2
        assert t.required_tests[0] == RequiredTest(
            test_id="tests/test_x.py::test_alpha",
            path="tests/test_x.py",
            function="test_alpha",
        )
        assert t.required_tests[1].function == "test_beta"
        assert t.tdd_required is True
        assert t.impl_files == ["src/x.py"]

    def test_tdd_not_required_flag_is_respected(self) -> None:
        md = """- [ ] T003 Implement `src/x.py`

  ### Testing Requirements

  - **Test 1**: `tests/x.py::test_a`

  **TDD discipline**: not required
"""
        tasks = parse_tasks_md(md)
        assert tasks[0].tdd_required is False

    def test_multiple_tasks_separated_by_section_break(self) -> None:
        md = """- [ ] T001 First task

  ### Testing Requirements

  - **Test 1**: `tests/a.py::test_a`

---

- [ ] T002 Second task

  ### Testing Requirements

  - **Test 1**: `tests/b.py::test_b`
"""
        tasks = parse_tasks_md(md)
        assert [t.task_id for t in tasks] == ["T001", "T002"]
        assert tasks[0].required_tests[0].test_id == "tests/a.py::test_a"
        assert tasks[1].required_tests[0].test_id == "tests/b.py::test_b"

    def test_completed_task_with_lowercase_x_parses(self) -> None:
        assert parse_tasks_md("- [x] T001 Done\n")[0].task_id == "T001"

    def test_completed_task_with_uppercase_X_parses(self) -> None:
        assert parse_tasks_md("- [X] T001 Done\n")[0].task_id == "T001"

    def test_non_test_list_items_are_skipped(self) -> None:
        """Sub-bullets like ``- Behavior:`` and ``- random text`` are NOT
        Test lines and remain silently skipped. ``- **TestX**:`` (no word
        boundary after ``Test``) is also not a Test line — it could be a
        class reference. Strict-grammar enforcement only fires on lines
        that match the ``- **Test\\b`` weak pattern."""
        md = """- [ ] T001 First `src/x.py`

  ### Testing Requirements

  - **Test 1**: `tests/a.py::test_a`
  - not a real requirement line
  - **TestX**: `bad-format-no-backticks`
  - Behavior: this is a sub-bullet
  - **Test 2**: `tests/b.py::test_b`
"""
        tasks = parse_tasks_md(md)
        assert len(tasks[0].required_tests) == 2

    def test_raises_parse_error_on_malformed_strict_test_line(self) -> None:
        """A line that *looks* like a Test line (matches ``- **Test\\b``)
        but fails the strict grammar must raise ParseError. The verifier
        is the enforcement point — silently dropping such lines would
        produce false-clean verdicts (Copilot review on PR #29)."""
        md = """- [ ] T001 First `src/x.py`

  ### Testing Requirements

  - **Test 1**: bad-without-backticks
"""
        with pytest.raises(ParseError, match="malformed Testing Requirements"):
            parse_tasks_md(md)

    def test_raises_parse_error_on_absolute_test_path(self) -> None:
        """Absolute paths (``/...``) escape the worktree and must be rejected."""
        md = """- [ ] T001 First `src/x.py`

  ### Testing Requirements

  - **Test 1**: `/etc/passwd_test.py::test_pwn`
"""
        with pytest.raises(ParseError, match="absolute"):
            parse_tasks_md(md)

    def test_raises_parse_error_on_parent_traversal(self) -> None:
        """``..`` segments could navigate outside the worktree — reject."""
        md = """- [ ] T001 First `src/x.py`

  ### Testing Requirements

  - **Test 1**: `../escape/test_x.py::test_pwn`
"""
        with pytest.raises(ParseError, match=r"\.\."):
            parse_tasks_md(md)

    def test_raises_parse_error_on_home_dir_path(self) -> None:
        """``~`` could be expanded by some tools — reject defensively."""
        md = """- [ ] T001 First `src/x.py`

  ### Testing Requirements

  - **Test 1**: `~/test_x.py::test_pwn`
"""
        with pytest.raises(ParseError, match="~"):
            parse_tasks_md(md)

    def test_raises_parse_error_on_windows_absolute_path(self) -> None:
        """Defensive: Windows-style absolute paths must also be rejected
        (the verifier may run on macOS / Linux but the parser shouldn't
        accept them anywhere)."""
        md = """- [ ] T001 First `src/x.py`

  ### Testing Requirements

  - **Test 1**: `C:/Windows/test_x.py::test_pwn`
"""
        with pytest.raises(ParseError, match="Windows absolute"):
            parse_tasks_md(md)

    def test_requirements_block_outside_a_parsed_task_is_an_error(self) -> None:
        """Seven shipped specs write task headers without a checkbox
        (``- T002 [P] …``). None of them matched ``_TASK_HEADER_RE``, every
        requirements block was skipped, and the verifier printed "All declared
        Testing Requirements satisfied" having checked nothing."""
        md = """- T002 [P] Verify the allowlist

  ### Testing Requirements

  - **Test 1**: `tests/a.py::test_a`
"""
        with pytest.raises(ParseError, match="not inside a parsed task"):
            parse_tasks_md(md)

    def test_subsequent_heading_ends_requirements_block(self) -> None:
        md = """- [ ] T001 thing `src/x.py`

  ### Testing Requirements

  - **Test 1**: `tests/a.py::test_a`

  ### Notes

  - **Test 2**: `tests/should_be_ignored.py::test_z`
"""
        tasks = parse_tasks_md(md)
        # The second "Test 2" line is after a different ### heading, so it
        # should NOT be parsed as a requirement.
        assert len(tasks[0].required_tests) == 1
        assert tasks[0].required_tests[0].test_id == "tests/a.py::test_a"


# -----------------------------------------------------------------------------
# Primitive tests
# -----------------------------------------------------------------------------


class TestPrimitives:
    def test_check_file_exists_true(self, tmp_path: Path) -> None:
        (tmp_path / "x.py").write_text("def foo(): ...\n")
        assert check_file_exists(tmp_path, "x.py") is True

    def test_check_file_exists_false(self, tmp_path: Path) -> None:
        assert check_file_exists(tmp_path, "nope.py") is False

    def test_check_function_defined_true(self, tmp_path: Path) -> None:
        (tmp_path / "x.py").write_text("def my_test():\n    pass\n")
        assert check_function_defined(tmp_path, "x.py", "my_test") is True

    def test_check_function_defined_handles_async_def(self, tmp_path: Path) -> None:
        (tmp_path / "x.py").write_text("async def my_test():\n    pass\n")
        assert check_function_defined(tmp_path, "x.py", "my_test") is True

    def test_check_function_defined_false_when_missing(self, tmp_path: Path) -> None:
        (tmp_path / "x.py").write_text("def other():\n    pass\n")
        assert check_function_defined(tmp_path, "x.py", "my_test") is False

    def test_check_function_defined_false_on_syntax_error(self, tmp_path: Path) -> None:
        (tmp_path / "broken.py").write_text("def broken(:\n")
        assert check_function_defined(tmp_path, "broken.py", "broken") is False

    def test_check_function_defined_false_when_file_missing(
        self, tmp_path: Path
    ) -> None:
        assert check_function_defined(tmp_path, "absent.py", "anything") is False


# -----------------------------------------------------------------------------
# End-to-end tests with real git + pytest subprocesses
# -----------------------------------------------------------------------------


def _init_git_repo(workdir: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=workdir, check=True)
    subprocess.run(
        ["git", "config", "user.email", "foreman-test@example.com"],
        cwd=workdir,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Foreman Test"], cwd=workdir, check=True
    )
    subprocess.run(
        ["git", "config", "commit.gpgsign", "false"], cwd=workdir, check=True
    )


def _git_commit(workdir: Path, msg: str) -> str:
    subprocess.run(["git", "add", "-A"], cwd=workdir, check=True)
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", msg], cwd=workdir, check=True
    )
    res = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workdir,
        check=True,
        capture_output=True,
        text=True,
    )
    return res.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _init_git_repo(tmp_path)
    return tmp_path


@pytest.fixture
def fresh_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure pytest subprocesses in the temp repo don't inherit the
    parent ``PYTEST_*`` / coverage env vars (they'd otherwise confuse the
    inner pytest into re-running the parent test session)."""
    for var in list(os.environ):
        if var.startswith(("PYTEST_", "COV_", "COVERAGE_")):
            monkeypatch.delenv(var, raising=False)


class TestVerify:
    def test_no_requirements_yields_no_requirements_status(
        self, repo: Path, fresh_env: None
    ) -> None:
        (repo / "tasks.md").write_text("- [ ] T001 Pure-prose task\n")
        _git_commit(repo, "init")

        report = verify(repo, repo / "tasks.md", base_ref="HEAD")
        assert report["summary"]["tasks_total"] == 1
        assert report["summary"]["tasks_without_requirements"] == 1
        assert report["summary"]["requirements_total"] == 0
        assert report["tasks"][0]["status"] == "NO_REQUIREMENTS"

    def test_passing_requirement_end_to_end(self, repo: Path, fresh_env: None) -> None:
        (repo / "tests").mkdir()
        (repo / "tests" / "test_sample.py").write_text(
            "def test_passes():\n    assert 1 + 1 == 2\n"
        )
        (repo / "tasks.md").write_text(
            "- [ ] T001 implement thing\n\n"
            "  ### Testing Requirements\n\n"
            "  - **Test 1**: `tests/test_sample.py::test_passes`\n"
        )
        _git_commit(repo, "init")

        report = verify(repo, repo / "tasks.md", base_ref="HEAD")
        assert report["summary"]["tasks_passing"] == 1
        assert report["tasks"][0]["status"] == "PASS"
        req_report = report["tasks"][0]["requirements"][0]
        assert req_report["file_exists"] is True
        assert req_report["function_defined"] is True
        assert req_report["collected_by_pytest"] is True
        assert req_report["test_passes"] is True

    def test_missing_function_fails(self, repo: Path, fresh_env: None) -> None:
        (repo / "tests").mkdir()
        (repo / "tests" / "test_sample.py").write_text(
            "def test_other():\n    assert True\n"
        )
        (repo / "tasks.md").write_text(
            "- [ ] T001 do thing\n\n"
            "  ### Testing Requirements\n\n"
            "  - **Test 1**: `tests/test_sample.py::test_required_but_missing`\n"
        )
        _git_commit(repo, "init")

        report = verify(repo, repo / "tasks.md", base_ref="HEAD")
        assert report["summary"]["tasks_failing"] == 1
        req_report = report["tasks"][0]["requirements"][0]
        assert req_report["status"] == "FAIL"
        assert req_report["file_exists"] is True
        assert req_report["function_defined"] is False
        assert "not defined" in (req_report["reason"] or "")

    def test_failing_test_fails(self, repo: Path, fresh_env: None) -> None:
        (repo / "tests").mkdir()
        (repo / "tests" / "test_sample.py").write_text(
            "def test_fails():\n    assert False, 'intentional'\n"
        )
        (repo / "tasks.md").write_text(
            "- [ ] T001 thing\n\n"
            "  ### Testing Requirements\n\n"
            "  - **Test 1**: `tests/test_sample.py::test_fails`\n"
        )
        _git_commit(repo, "init")

        report = verify(repo, repo / "tasks.md", base_ref="HEAD")
        req_report = report["tasks"][0]["requirements"][0]
        assert req_report["status"] == "FAIL"
        assert req_report["test_passes"] is False
        assert "test failed" in (req_report["reason"] or "").lower()

    def test_tdd_timeline_pass_test_before_impl(
        self, repo: Path, fresh_env: None
    ) -> None:
        # Base commit
        (repo / "README.md").write_text("init\n")
        _git_commit(repo, "init")
        subprocess.run(["git", "branch", "base"], cwd=repo, check=True)

        # Commit 1: failing test
        (repo / "tests").mkdir()
        (repo / "tests" / "test_x.py").write_text(
            "import sys; sys.path.insert(0, '.')\n"
            "from src import x\n"
            "def test_x_does_thing():\n"
            "    assert x.do() == 1\n"
        )
        (repo / "src").mkdir()
        (repo / "src" / "__init__.py").write_text("")
        _git_commit(repo, "test: failing test for x")

        time.sleep(1.1)

        # Commit 2: impl makes it pass
        (repo / "src" / "x.py").write_text("def do():\n    return 1\n")
        _git_commit(repo, "impl: x does the thing")

        (repo / "tasks.md").write_text(
            "- [ ] T001 implement `src/x.py`\n\n"
            "  ### Testing Requirements\n\n"
            "  - **Test 1**: `tests/test_x.py::test_x_does_thing`\n\n"
            "  **TDD discipline**: required\n"
        )
        _git_commit(repo, "docs: add testing requirements")

        report = verify(repo, repo / "tasks.md", base_ref="base")
        req_report = report["tasks"][0]["requirements"][0]
        assert req_report["status"] == "PASS", req_report
        assert req_report["tdd_timeline_ok"] is True

    def test_tdd_timeline_violation_impl_before_test(
        self, repo: Path, fresh_env: None
    ) -> None:
        (repo / "README.md").write_text("init\n")
        _git_commit(repo, "init")
        subprocess.run(["git", "branch", "base"], cwd=repo, check=True)

        # Commit 1: impl first (WRONG order)
        (repo / "src").mkdir()
        (repo / "src" / "__init__.py").write_text("")
        (repo / "src" / "x.py").write_text("def do():\n    return 1\n")
        _git_commit(repo, "impl: x does the thing (TDD-violating order)")

        time.sleep(1.1)

        # Commit 2: test second
        (repo / "tests").mkdir()
        (repo / "tests" / "test_x.py").write_text(
            "import sys; sys.path.insert(0, '.')\n"
            "from src import x\n"
            "def test_x_does_thing():\n"
            "    assert x.do() == 1\n"
        )
        _git_commit(repo, "test: belated test for x")

        (repo / "tasks.md").write_text(
            "- [ ] T001 implement `src/x.py`\n\n"
            "  ### Testing Requirements\n\n"
            "  - **Test 1**: `tests/test_x.py::test_x_does_thing`\n\n"
            "  **TDD discipline**: required\n"
        )
        _git_commit(repo, "docs: add testing requirements")

        report = verify(repo, repo / "tasks.md", base_ref="base")
        req_report = report["tasks"][0]["requirements"][0]
        assert req_report["status"] == "FAIL", req_report
        assert req_report["tdd_timeline_ok"] is False
        assert "TDD violation" in (req_report["reason"] or "")

    def test_first_commit_for_falls_back_to_modify(
        self, repo: Path, fresh_env: None
    ) -> None:
        """When the impl file already existed in ``base_ref`` and is only
        modified on the branch, ``_first_commit_for`` must still return
        a commit (the first MODIFY commit). Copilot review on PR #29
        flagged the original add-only behavior as a false negative for
        legitimate extend/refactor tasks."""
        (repo / "src").mkdir()
        (repo / "src" / "x.py").write_text("def existing():\n    return 1\n")
        (repo / "README.md").write_text("init\n")
        _git_commit(repo, "init with existing impl")
        subprocess.run(["git", "branch", "base"], cwd=repo, check=True)

        (repo / "src" / "x.py").write_text(
            "def existing():\n    return 1\ndef new_function():\n    return 2\n"
        )
        modify_sha = _git_commit(repo, "feat: add new_function to existing x.py")

        sha = _first_commit_for(repo, "src/x.py", base_ref="base")
        assert sha == modify_sha

    def test_branch_commits_in_topological_order(
        self, repo: Path, fresh_env: None
    ) -> None:
        """``_branch_commits_in_order`` returns commits oldest-ancestor
        first regardless of wall-clock timestamps."""
        (repo / "README.md").write_text("init\n")
        _git_commit(repo, "init")
        subprocess.run(["git", "branch", "base"], cwd=repo, check=True)

        sha_a = _git_commit(repo, "feat: a")
        sha_b = _git_commit(repo, "feat: b")
        sha_c = _git_commit(repo, "feat: c")

        order = _branch_commits_in_order(repo, base_ref="base")
        assert order == [sha_a, sha_b, sha_c]

    def test_tdd_timeline_uses_commit_order_not_timestamps(
        self, repo: Path, fresh_env: None
    ) -> None:
        """Same-second commits (no ``time.sleep`` between them) must be
        ordered correctly by commit ancestry, not by identical
        timestamps. This is the Copilot-flagged failure mode on PR #29
        where two commits with ``%ct`` values equal made ``test_ts <=
        impl_ts`` falsely pass an impl-first ordering."""
        (repo / "README.md").write_text("init\n")
        _git_commit(repo, "init")
        subprocess.run(["git", "branch", "base"], cwd=repo, check=True)

        # NOTE: no time.sleep — these commits will land in the same second.
        # The old timestamp-based check would have called this a tie and
        # passed; the new topological check correctly identifies the impl-
        # first ordering as a TDD violation.
        (repo / "src").mkdir()
        (repo / "src" / "__init__.py").write_text("")
        (repo / "src" / "x.py").write_text("def do():\n    return 1\n")
        _git_commit(repo, "impl: x first (TDD violation)")

        (repo / "tests").mkdir()
        (repo / "tests" / "test_x.py").write_text(
            "import sys; sys.path.insert(0, '.')\n"
            "from src import x\n"
            "def test_x():\n    assert x.do() == 1\n"
        )
        _git_commit(repo, "test: x second")

        (repo / "tasks.md").write_text(
            "- [ ] T001 implement `src/x.py`\n\n"
            "  ### Testing Requirements\n\n"
            "  - **Test 1**: `tests/test_x.py::test_x`\n\n"
            "  **TDD discipline**: required\n"
        )
        _git_commit(repo, "docs: add testing requirements")

        report = verify(repo, repo / "tasks.md", base_ref="base")
        req_report = report["tasks"][0]["requirements"][0]
        assert req_report["status"] == "FAIL", req_report
        assert req_report["tdd_timeline_ok"] is False
        assert "TDD violation" in (req_report["reason"] or "")

    def test_tdd_works_for_existing_file_modifications(
        self, repo: Path, fresh_env: None
    ) -> None:
        """When TDD is required for a task that MODIFIES an existing
        framework file (adds a function rather than the whole file), the
        verifier should still be able to assess timeline using the first
        modification commit. Copilot called out the original add-only
        check as a false negative."""
        (repo / "src").mkdir()
        (repo / "src" / "__init__.py").write_text("")
        (repo / "src" / "x.py").write_text("def existing():\n    return 1\n")
        (repo / "README.md").write_text("init\n")
        _git_commit(repo, "init with existing x.py")
        subprocess.run(["git", "branch", "base"], cwd=repo, check=True)

        # Commit 1: add the test (test-first)
        (repo / "tests").mkdir()
        (repo / "tests" / "test_x.py").write_text(
            "import sys; sys.path.insert(0, '.')\n"
            "from src import x\n"
            "def test_new_function():\n    assert x.new_function() == 2\n"
        )
        _git_commit(repo, "test: add new_function test")

        # Commit 2: extend x.py with new_function
        (repo / "src" / "x.py").write_text(
            "def existing():\n    return 1\ndef new_function():\n    return 2\n"
        )
        _git_commit(repo, "feat: add new_function to x.py")

        (repo / "tasks.md").write_text(
            "- [ ] T001 add new_function to `src/x.py`\n\n"
            "  ### Testing Requirements\n\n"
            "  - **Test 1**: `tests/test_x.py::test_new_function`\n\n"
            "  **TDD discipline**: required\n"
        )
        _git_commit(repo, "docs: add testing requirements")

        report = verify(repo, repo / "tasks.md", base_ref="base")
        req_report = report["tasks"][0]["requirements"][0]
        assert req_report["status"] == "PASS", req_report
        assert req_report["tdd_timeline_ok"] is True

    def test_skipped_test_does_not_count_as_pass(
        self, repo: Path, fresh_env: None
    ) -> None:
        """Pytest exits 0 on ``@pytest.mark.skip`` — without an explicit
        PASSED check, the verifier would mark a skipped test as passing.
        Copilot called this out specifically for ``live_llm`` tests
        which are skipped by default. The verifier must look at the
        per-test status line, not just the exit code."""
        (repo / "tests").mkdir()
        (repo / "tests" / "test_sample.py").write_text(
            "import pytest\n"
            "@pytest.mark.skip(reason='intentional skip for foreman test')\n"
            "def test_skipped():\n    assert True\n"
        )
        (repo / "tasks.md").write_text(
            "- [ ] T001 thing\n\n"
            "  ### Testing Requirements\n\n"
            "  - **Test 1**: `tests/test_sample.py::test_skipped`\n"
        )
        _git_commit(repo, "init")

        report = verify(repo, repo / "tasks.md", base_ref="HEAD")
        req_report = report["tasks"][0]["requirements"][0]
        assert req_report["status"] == "FAIL", req_report
        assert req_report["test_passes"] is False

    def test_xfail_test_does_not_count_as_pass(
        self, repo: Path, fresh_env: None
    ) -> None:
        """``@pytest.mark.xfail`` tests also exit 0 but print ``XFAIL``,
        not ``PASSED``. They must not count as passing."""
        (repo / "tests").mkdir()
        (repo / "tests" / "test_sample.py").write_text(
            "import pytest\n"
            "@pytest.mark.xfail(reason='intentional')\n"
            "def test_xfails():\n    assert False\n"
        )
        (repo / "tasks.md").write_text(
            "- [ ] T001 thing\n\n"
            "  ### Testing Requirements\n\n"
            "  - **Test 1**: `tests/test_sample.py::test_xfails`\n"
        )
        _git_commit(repo, "init")

        report = verify(repo, repo / "tasks.md", base_ref="HEAD")
        req_report = report["tasks"][0]["requirements"][0]
        assert req_report["status"] == "FAIL", req_report
        assert req_report["test_passes"] is False

    def test_tdd_same_commit_squash_is_clean(self, repo: Path, fresh_env: None) -> None:
        (repo / "README.md").write_text("init\n")
        _git_commit(repo, "init")
        subprocess.run(["git", "branch", "base"], cwd=repo, check=True)

        # Squashed: test + impl in the same commit (test-first squash is
        # indistinguishable from impl-first squash; both are accepted).
        (repo / "tests").mkdir()
        (repo / "src").mkdir()
        (repo / "src" / "__init__.py").write_text("")
        (repo / "src" / "x.py").write_text("def do():\n    return 1\n")
        (repo / "tests" / "test_x.py").write_text(
            "import sys; sys.path.insert(0, '.')\n"
            "from src import x\n"
            "def test_x():\n"
            "    assert x.do() == 1\n"
        )
        _git_commit(repo, "feat: x with squashed TDD")

        (repo / "tasks.md").write_text(
            "- [ ] T001 implement `src/x.py`\n\n"
            "  ### Testing Requirements\n\n"
            "  - **Test 1**: `tests/test_x.py::test_x`\n\n"
            "  **TDD discipline**: required\n"
        )
        _git_commit(repo, "docs: add testing requirements")

        report = verify(repo, repo / "tasks.md", base_ref="base")
        req_report = report["tasks"][0]["requirements"][0]
        assert req_report["status"] == "PASS"
        assert req_report["tdd_timeline_ok"] is True


# -----------------------------------------------------------------------------
# CLI smoke test
# -----------------------------------------------------------------------------


class TestCLI:
    def test_cli_returns_exit_2_when_tasks_file_missing(self, tmp_path: Path) -> None:
        _init_git_repo(tmp_path)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.foreman.verify_test_coverage",
                "--tasks",
                str(tmp_path / "nonexistent.md"),
                "--workdir",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "not found" in (result.stdout + result.stderr).lower()

    def test_cli_returns_exit_2_on_parser_error(
        self, tmp_path: Path, fresh_env: None
    ) -> None:
        """A malformed Testing Requirements line surfaces as exit 2,
        not silently as exit 0 / 1. Copilot review on PR #29."""
        _init_git_repo(tmp_path)
        (tmp_path / "tasks.md").write_text(
            "- [ ] T001 thing\n\n"
            "  ### Testing Requirements\n\n"
            "  - **Test 1**: this-is-malformed-no-backticks\n"
        )
        _git_commit(tmp_path, "init")

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.foreman.verify_test_coverage",
                "--tasks",
                str(tmp_path / "tasks.md"),
                "--workdir",
                str(tmp_path),
                "--base-ref",
                "HEAD",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "parser error" in (result.stdout + result.stderr).lower()

    def test_cli_returns_exit_1_on_failure(
        self, tmp_path: Path, fresh_env: None
    ) -> None:
        _init_git_repo(tmp_path)
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_x.py").write_text("def test_other():\n    pass\n")
        (tmp_path / "tasks.md").write_text(
            "- [ ] T001 thing\n\n"
            "  ### Testing Requirements\n\n"
            "  - **Test 1**: `tests/test_x.py::test_missing`\n"
        )
        _git_commit(tmp_path, "init")

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.foreman.verify_test_coverage",
                "--tasks",
                str(tmp_path / "tasks.md"),
                "--workdir",
                str(tmp_path),
                "--base-ref",
                "HEAD",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1


# -----------------------------------------------------------------------------
# Spec 057 — tolerant retro matching mode
# -----------------------------------------------------------------------------


class TestTolerantParser:
    """T002 — parser accepts file-only lines in tolerant mode only."""

    _FILE_ONLY = (
        "- [ ] T001 thing\n\n"
        "  ### Testing Requirements\n\n"
        "  - **Test 1**: `tests/foo/test_bar.py`\n"
    )

    def test_file_only_line_parsed_in_tolerant_mode(self) -> None:
        tasks = parse_tasks_md(self._FILE_ONLY, matching_mode="tolerant")
        assert len(tasks) == 1
        assert len(tasks[0].required_tests) == 1
        req = tasks[0].required_tests[0]
        assert req.path == "tests/foo/test_bar.py"
        assert req.function == ""
        assert req.test_id == "tests/foo/test_bar.py"

    def test_file_only_line_rejected_in_strict_mode(self) -> None:
        with pytest.raises(ParseError):
            parse_tasks_md(self._FILE_ONLY, matching_mode="strict")

    def test_strict_shaped_line_still_parsed_in_tolerant_mode(self) -> None:
        md = (
            "- [ ] T001 thing\n\n"
            "  ### Testing Requirements\n\n"
            "  - **Test 1**: `tests/foo/test_bar.py::test_baz`\n"
        )
        tasks = parse_tasks_md(md, matching_mode="tolerant")
        req = tasks[0].required_tests[0]
        assert req.test_id == "tests/foo/test_bar.py::test_baz"
        assert req.function == "test_baz"

    def test_tdd_discipline_line_ignored_in_tolerant_parse(self) -> None:
        md = (
            "- [ ] T001 thing\n\n"
            "  ### Testing Requirements\n\n"
            "  - **Test 1**: `tests/foo/test_bar.py`\n\n"
            "  **TDD discipline**: required\n"
        )
        tasks = parse_tasks_md(md, matching_mode="tolerant")
        assert tasks[0].tdd_required is False

    def test_default_mode_is_strict(self) -> None:
        with pytest.raises(ParseError):
            parse_tasks_md(self._FILE_ONLY)


class TestFilePassingPrimitive:
    """T005 — ``check_file_has_passing_test`` file-level primitive."""

    def test_file_with_one_passing_test(self, tmp_path: Path, fresh_env: None) -> None:
        (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n")
        assert check_file_has_passing_test(tmp_path, "test_ok.py") is True

    def test_file_all_skipped_not_passing(
        self, tmp_path: Path, fresh_env: None
    ) -> None:
        (tmp_path / "test_skip.py").write_text(
            "import pytest\n"
            "pytestmark = pytest.mark.skip(reason='all skipped')\n"
            "def test_a():\n    assert True\n"
            "def test_b():\n    assert True\n"
        )
        assert check_file_has_passing_test(tmp_path, "test_skip.py") is False

    def test_missing_file_not_passing(self, tmp_path: Path) -> None:
        assert check_file_has_passing_test(tmp_path, "nope.py") is False


class TestVerifyTolerantE2E:
    """T006 — end-to-end tolerant verdicts on a temp git worktree."""

    def test_tolerant_all_files_pass(self, repo: Path, fresh_env: None) -> None:
        (repo / "tests").mkdir()
        (repo / "tests" / "test_a.py").write_text("def test_a():\n    assert True\n")
        (repo / "tests" / "test_b.py").write_text("def test_b():\n    assert True\n")
        (repo / "tasks.md").write_text(
            "- [ ] T001 thing\n\n"
            "  ### Testing Requirements\n\n"
            "  - **Test 1**: `tests/test_a.py`\n"
            "  - **Test 2**: `tests/test_b.py`\n"
        )
        _git_commit(repo, "init")
        report = verify(
            repo, repo / "tasks.md", base_ref="HEAD", matching_mode="tolerant"
        )
        assert report["summary"]["matching_mode"] == "tolerant"
        assert report["summary"]["tasks_failing"] == 0
        assert report["tasks"][0]["status"] == "PASS"
        req = report["tasks"][0]["requirements"][0]
        assert req["file_exists"] is True
        assert req["function_defined"] is None
        assert req["collected_by_pytest"] is None
        assert req["test_passes"] is True
        assert req["tdd_timeline_ok"] is None

    def test_tolerant_missing_file_fails(self, repo: Path, fresh_env: None) -> None:
        (repo / "tasks.md").write_text(
            "- [ ] T001 thing\n\n"
            "  ### Testing Requirements\n\n"
            "  - **Test 1**: `tests/missing/test_none.py`\n"
        )
        _git_commit(repo, "init")
        report = verify(
            repo, repo / "tasks.md", base_ref="HEAD", matching_mode="tolerant"
        )
        assert report["summary"]["tasks_failing"] == 1
        req = report["tasks"][0]["requirements"][0]
        assert req["status"] == "FAIL"
        assert req["file_exists"] is False
        assert "tests/missing/test_none.py" in (req["reason"] or "")

    def test_tolerant_empty_file_fails(self, repo: Path, fresh_env: None) -> None:
        (repo / "tests").mkdir()
        (repo / "tests" / "test_empty.py").write_text(
            "import pytest\n"
            "pytestmark = pytest.mark.skip(reason='all skipped')\n"
            "def test_x():\n    assert True\n"
        )
        (repo / "tasks.md").write_text(
            "- [ ] T001 thing\n\n"
            "  ### Testing Requirements\n\n"
            "  - **Test 1**: `tests/test_empty.py`\n"
        )
        _git_commit(repo, "init")
        report = verify(
            repo, repo / "tasks.md", base_ref="HEAD", matching_mode="tolerant"
        )
        req = report["tasks"][0]["requirements"][0]
        assert req["status"] == "FAIL"
        assert req["file_exists"] is True
        assert req["test_passes"] is False

    def test_no_requirements_still_skipped(self, repo: Path, fresh_env: None) -> None:
        (repo / "tasks.md").write_text("- [ ] T001 pure prose\n")
        _git_commit(repo, "init")
        report = verify(
            repo, repo / "tasks.md", base_ref="HEAD", matching_mode="tolerant"
        )
        assert report["tasks"][0]["status"] == "NO_REQUIREMENTS"


class TestModeTaggedReport:
    """T011 — verdict report is mode-tagged and never claims TDD in tolerant."""

    def test_json_strict_mode_field(self, repo: Path, fresh_env: None) -> None:
        (repo / "tasks.md").write_text("- [ ] T001 prose\n")
        _git_commit(repo, "init")
        report = verify(repo, repo / "tasks.md", base_ref="HEAD")
        assert report["summary"]["matching_mode"] == "strict"

    def test_json_tolerant_never_sets_tdd_timeline_true(
        self, repo: Path, fresh_env: None
    ) -> None:
        (repo / "tests").mkdir()
        (repo / "tests" / "test_a.py").write_text("def test_a():\n    assert True\n")
        (repo / "tasks.md").write_text(
            "- [ ] T001 thing\n\n"
            "  ### Testing Requirements\n\n"
            "  - **Test 1**: `tests/test_a.py`\n"
        )
        _git_commit(repo, "init")
        report = verify(
            repo, repo / "tasks.md", base_ref="HEAD", matching_mode="tolerant"
        )
        for task in report["tasks"]:
            assert task["tdd_required"] is False
            for req in task["requirements"]:
                assert req["tdd_timeline_ok"] is None

    def _empty_report(self, mode: str) -> dict:
        return {
            "summary": {
                "matching_mode": mode,
                "tasks_total": 0,
                "tasks_with_requirements": 0,
                "tasks_without_requirements": 0,
                "tasks_passing": 0,
                "tasks_failing": 0,
                "requirements_total": 0,
                "requirements_passing": 0,
                "requirements_failing": 0,
            },
            "tasks": [],
        }

    def test_human_banner_tolerant(self) -> None:
        text = _render_text(self._empty_report("tolerant"))
        assert "MODE: tolerant" in text

    def test_human_banner_strict(self) -> None:
        text = _render_text(self._empty_report("strict"))
        assert "MODE: strict" in text


class TestFileOnlyBlockEndToEnd:
    """T016 — minimal file-only tasks.md gets a tolerant PASS (US3 acceptance)."""

    def test_file_only_block_end_to_end(self, repo: Path, fresh_env: None) -> None:
        (repo / "tests").mkdir()
        (repo / "tests" / "test_a.py").write_text("def test_a():\n    assert True\n")
        (repo / "tests" / "test_b.py").write_text("def test_b():\n    assert True\n")
        (repo / "tasks.md").write_text(
            "- [ ] T001 first thing\n\n"
            "  ### Testing Requirements\n\n"
            "  - **Test 1**: `tests/test_a.py`\n"
            "  - **Test 2**: `tests/test_b.py`\n"
        )
        _git_commit(repo, "init")
        report = verify(
            repo, repo / "tasks.md", base_ref="HEAD", matching_mode="tolerant"
        )
        assert report["tasks"][0]["status"] == "PASS"
        assert report["summary"]["tasks_failing"] == 0


class TestStrictModeUnchanged:
    """T017 / T020 — strict mode (default) behaves exactly as before 057."""

    def test_strict_passing_requirement_unchanged(
        self, repo: Path, fresh_env: None
    ) -> None:
        (repo / "tests").mkdir()
        (repo / "tests" / "test_sample.py").write_text(
            "def test_passes():\n    assert 1 + 1 == 2\n"
        )
        (repo / "tasks.md").write_text(
            "- [ ] T001 implement thing\n\n"
            "  ### Testing Requirements\n\n"
            "  - **Test 1**: `tests/test_sample.py::test_passes`\n"
        )
        _git_commit(repo, "init")
        report = verify(repo, repo / "tasks.md", base_ref="HEAD")
        assert report["summary"]["matching_mode"] == "strict"
        req = report["tasks"][0]["requirements"][0]
        assert req["status"] == "PASS"
        assert req["function_defined"] is True
        assert req["collected_by_pytest"] is True

    def test_strict_file_only_line_is_parse_error(self) -> None:
        md = (
            "- [ ] T001 thing\n\n"
            "  ### Testing Requirements\n\n"
            "  - **Test 1**: `tests/test_sample.py`\n"
        )
        with pytest.raises(ParseError):
            parse_tasks_md(md)

    def test_strict_tdd_path_still_runs(self, repo: Path, fresh_env: None) -> None:
        (repo / "README.md").write_text("init\n")
        _git_commit(repo, "init")
        subprocess.run(["git", "branch", "base"], cwd=repo, check=True)
        (repo / "tests").mkdir()
        (repo / "src").mkdir()
        (repo / "src" / "__init__.py").write_text("")
        (repo / "tests" / "test_x.py").write_text(
            "import sys; sys.path.insert(0, '.')\n"
            "from src import x\n"
            "def test_x():\n    assert x.do() == 1\n"
        )
        _git_commit(repo, "test: failing test for x")
        (repo / "src" / "x.py").write_text("def do():\n    return 1\n")
        _git_commit(repo, "impl: x")
        (repo / "tasks.md").write_text(
            "- [ ] T001 implement `src/x.py`\n\n"
            "  ### Testing Requirements\n\n"
            "  - **Test 1**: `tests/test_x.py::test_x`\n\n"
            "  **TDD discipline**: required\n"
        )
        _git_commit(repo, "docs: testing requirements")
        report = verify(repo, repo / "tasks.md", base_ref="base")
        req = report["tasks"][0]["requirements"][0]
        assert req["status"] == "PASS", req
        assert req["tdd_timeline_ok"] is True


class TestRelaxationDeterminism:
    """T018 / T019 — strict PASS ⇒ tolerant PASS; tolerant verdict deterministic."""

    def test_strict_pass_implies_tolerant_pass(
        self, repo: Path, fresh_env: None
    ) -> None:
        (repo / "tests").mkdir()
        (repo / "tests" / "test_sample.py").write_text(
            "def test_passes():\n    assert True\n"
        )
        (repo / "tasks.md").write_text(
            "- [ ] T001 implement thing\n\n"
            "  ### Testing Requirements\n\n"
            "  - **Test 1**: `tests/test_sample.py::test_passes`\n"
        )
        _git_commit(repo, "init")
        strict = verify(repo, repo / "tasks.md", base_ref="HEAD")
        tolerant = verify(
            repo, repo / "tasks.md", base_ref="HEAD", matching_mode="tolerant"
        )
        assert strict["tasks"][0]["status"] == "PASS"
        assert tolerant["tasks"][0]["status"] == "PASS"

    def test_deterministic_tolerant_verdict(self, repo: Path, fresh_env: None) -> None:
        (repo / "tests").mkdir()
        (repo / "tests" / "test_a.py").write_text("def test_a():\n    assert True\n")
        (repo / "tasks.md").write_text(
            "- [ ] T001 thing\n\n"
            "  ### Testing Requirements\n\n"
            "  - **Test 1**: `tests/test_a.py`\n"
        )
        _git_commit(repo, "init")
        r1 = verify(repo, repo / "tasks.md", base_ref="HEAD", matching_mode="tolerant")
        r2 = verify(repo, repo / "tasks.md", base_ref="HEAD", matching_mode="tolerant")
        assert _json.dumps(r1, sort_keys=True) == _json.dumps(r2, sort_keys=True)


# Module marker — keep the unused import noise away from ruff in some setups.
__all__ = [
    "TestParser",
    "TestPrimitives",
    "TestVerify",
    "TestCLI",
    "TestTolerantParser",
    "TestFilePassingPrimitive",
    "TestVerifyTolerantE2E",
    "TestModeTaggedReport",
    "TestFileOnlyBlockEndToEnd",
    "TestStrictModeUnchanged",
    "TestRelaxationDeterminism",
]
