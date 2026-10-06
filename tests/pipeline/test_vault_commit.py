"""Lifecycle tests for `pipeline.vault_commit` (spec 050).

Each test stands up a fresh `git init`'d temp directory and exercises one
slice of the auto-commit invariant. Hermetic — no real network, no real
remote (we use a second on-disk bare repo for the push tests).

The tests are grouped by the public surface of `vault_commit`:

  - begin_run          (branch lifecycle, dirty-main HARD STOP)
  - commit_cycle       (per-cycle commit shape + skip-on-empty)
  - complete_run       (squash-merge / branch retention / aborted-cycle rewind)
  - push behaviour     (auto / never / always policies)
  - commit_framework_change
  - commit_command_output
  - settings opt-out   (vault_commit.enabled: false)

A handful of helpers at the top keep each test fact-shaped and one-screen.
"""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from research_framework.pipeline.branch_retention import (
    is_branch_landed,
    list_research_branches,
    prune_research_branches,
)
from research_framework.pipeline.vault_commit import (
    CompleteResult,
    RunContext,
    VaultCommitDirtyError,
    _is_dirty,
    begin_run,
    commit_command_output,
    commit_cycle,
    commit_framework_change,
    complete_run,
    is_working_tree_dirty,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    """Convenience around `subprocess.run` with sensible defaults."""
    return subprocess.run(
        list(args), cwd=str(cwd), check=True, capture_output=True, text=True
    )


def _make_vault(tmp_path: Path) -> Path:
    """Return a brand-new git repo on `main` with one initial commit."""
    vault = tmp_path / "vault"
    vault.mkdir()
    _run("git", "init", "-b", "main", cwd=vault)
    _run("git", "config", "user.email", "test@example.com", cwd=vault)
    _run("git", "config", "user.name", "Test", cwd=vault)
    (vault / "README.md").write_text("# vault\n", encoding="utf-8")
    _run("git", "add", "-A", cwd=vault)
    _run("git", "commit", "-m", "initial", cwd=vault)
    return vault


def _write_settings(vault: Path, block: dict[str, object] | None) -> None:
    """Materialise a `settings.yaml` with the given `vault_commit:` block.

    Commits the file so it doesn't dirty `main` (the real generator
    writes settings.yaml as part of the bootstrap commit, so this
    matches reality).
    """
    if block is None:
        return
    lines = ["---", "vault_commit:"]
    for k, v in block.items():
        if isinstance(v, bool):
            v = "true" if v else "false"
        lines.append(f"  {k}: {v}")
    lines.append("---")
    (vault / "settings.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _run("git", "add", "settings.yaml", cwd=vault)
    _run("git", "commit", "-m", "test: write settings", cwd=vault)


def _write_note(vault: Path, name: str, text: str = "body\n") -> None:
    """Drop a note under data_vault/ to simulate a cycle's output."""
    notes = vault / "data_vault"
    notes.mkdir(exist_ok=True)
    (notes / name).write_text(text, encoding="utf-8")


def _head_sha(vault: Path) -> str:
    return _run("git", "rev-parse", "HEAD", cwd=vault).stdout.strip()


def _branches(vault: Path) -> list[str]:
    return [
        ln.strip().lstrip("* ").strip()
        for ln in _run("git", "branch", cwd=vault).stdout.splitlines()
        if ln.strip()
    ]


def _commit_log(vault: Path, ref: str = "HEAD", n: int = 10) -> list[str]:
    return _run(
        "git", "log", "--pretty=%s", f"-n{n}", ref, cwd=vault
    ).stdout.splitlines()


# ---------------------------------------------------------------------------
# begin_run
# ---------------------------------------------------------------------------


class TestBeginRun:
    def test_clean_main_creates_research_branch(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        ctx = begin_run(vault, kind="research")
        assert ctx is not None
        assert ctx.branch.startswith("research/")
        assert "research/" in _branches(vault)[0] or any(
            b.startswith("research/") for b in _branches(vault)
        )
        assert (
            vault / ".git" / "research-framework" / "vault-commit-state.json"
        ).exists()

    def test_dirty_main_raises_hard_stop(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        (vault / "README.md").write_text("dirty edit\n", encoding="utf-8")
        with pytest.raises(VaultCommitDirtyError):
            begin_run(vault, kind="research")

    def test_pipeline_sidecar_does_not_count_as_dirty(self, tmp_path: Path) -> None:
        """_pipeline/* mutations are expected — must not trigger HARD STOP."""
        vault = _make_vault(tmp_path)
        (vault / "_pipeline").mkdir()
        (vault / "_pipeline" / "state.json").write_text("{}\n", encoding="utf-8")
        ctx = begin_run(vault, kind="research")
        assert ctx is not None
        assert ctx.branch.startswith("research/")

    def test_resume_on_existing_research_branch_reuses_it(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        ctx1 = begin_run(vault, kind="research")
        assert ctx1 is not None
        # Simulate process exit + resume.
        ctx2 = begin_run(vault, kind="research", resume=True)
        assert ctx2 is not None
        assert ctx2.branch == ctx1.branch

    def test_non_resume_on_research_branch_raises(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        begin_run(vault, kind="research")
        with pytest.raises(VaultCommitDirtyError):
            begin_run(vault, kind="research", resume=False)

    def test_settings_disabled_short_circuits(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write_settings(vault, {"enabled": False})
        assert begin_run(vault, kind="research") is None
        # No branch created.
        assert not any(b.startswith("research/") for b in _branches(vault))

    def test_branch_name_collision_appends_suffix(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        fixed_now = datetime(2026, 6, 1, 12, 0, 0)
        # Create the first branch by hand to reserve the name.
        _run(
            "git",
            "branch",
            f"research/{fixed_now.strftime('%Y-%m-%d-%H%M')}",
            cwd=vault,
        )
        ctx = begin_run(vault, kind="research", now=fixed_now)
        assert ctx is not None
        assert ctx.branch.endswith("-02")


# ---------------------------------------------------------------------------
# commit_cycle
# ---------------------------------------------------------------------------


class TestCommitCycle:
    def test_per_cycle_commit_lands_on_branch(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        ctx = begin_run(vault, kind="research")
        _write_note(vault, "note-a.md")
        result = commit_cycle(
            vault, cycle=1, summary={"notes_added": 1, "short": "scout pass"}, ctx=ctx
        )
        assert result.ok is True
        assert result.sha is not None
        log = _commit_log(vault)
        assert any("research: cycle 1 — scout pass" in s for s in log)

    def test_no_changes_skips_silently(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        ctx = begin_run(vault, kind="research")
        before = _head_sha(vault)
        result = commit_cycle(vault, cycle=1, summary={"notes_added": 0}, ctx=ctx)
        assert result.ok is True
        assert result.skipped_reason == "no changes"
        assert _head_sha(vault) == before

    def test_commit_body_contains_coverage(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        ctx = begin_run(vault, kind="research")
        _write_note(vault, "note-cov.md")
        commit_cycle(
            vault,
            cycle=2,
            summary={
                "notes_added": 1,
                "coverage": [
                    {"category": "foo", "line": "3/10 (+1)"},
                ],
                "wall_time_human": "12s",
                "gate_verdict": "PASS",
                "cost_usd": 0.01,
            },
            ctx=ctx,
        )
        msg = _run("git", "log", "-1", "--pretty=%B", cwd=vault).stdout
        assert "**Coverage**" in msg
        assert "foo: 3/10 (+1)" in msg
        assert "PASS" in msg
        assert "$0.0100 spent" in msg

    def test_cycle_shas_recorded_in_context(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        ctx = begin_run(vault, kind="research")
        _write_note(vault, "n1.md")
        commit_cycle(vault, cycle=1, summary={"notes_added": 1}, ctx=ctx)
        _write_note(vault, "n2.md")
        commit_cycle(vault, cycle=2, summary={"notes_added": 1}, ctx=ctx)
        assert len(ctx.cycle_commit_shas) == 2


# ---------------------------------------------------------------------------
# complete_run
# ---------------------------------------------------------------------------


class TestCompleteRun:
    def test_rc0_squash_merges_and_deletes_branch(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        ctx = begin_run(vault, kind="research")
        _write_note(vault, "n1.md")
        commit_cycle(vault, cycle=1, summary={"notes_added": 1}, ctx=ctx)
        _write_note(vault, "n2.md")
        commit_cycle(vault, cycle=2, summary={"notes_added": 1}, ctx=ctx)
        result = complete_run(
            vault, final_rc=0, final_reason="all targets met", ctx=ctx
        )
        assert result.ok is True
        assert result.merged is True
        # Branch deleted; we land back on main.
        current = _run(
            "git", "rev-parse", "--abbrev-ref", "HEAD", cwd=vault
        ).stdout.strip()
        assert current == "main"
        assert ctx.branch not in _branches(vault)
        # Squashed: exactly one new commit on main beyond the initial commit.
        log = _commit_log(vault)
        assert len(log) == 2  # initial + squashed run
        assert log[0].startswith("research run:")

    def test_rc1_constrained_lands_on_main_and_retains_branch(
        self, tmp_path: Path
    ) -> None:
        """Spec 072 changed half of this: a constrained exit now LANDS.

        The branch is still retained (that part is unchanged, and is FR5 — the
        run left work undone, so its per-cycle history is worth keeping), but
        the content no longer sits on the branch waiting for the operator to
        decide. rc=1 is a designed terminal state, not a failure.
        """
        vault = _make_vault(tmp_path)
        ctx = begin_run(vault, kind="research")
        _write_note(vault, "n1.md")
        commit_cycle(vault, cycle=1, summary={"notes_added": 1}, ctx=ctx)
        result = complete_run(vault, final_rc=1, final_reason="constrained", ctx=ctx)
        assert result.ok is True
        assert result.branch_retained is True
        assert ctx.branch in _branches(vault)
        # New in spec 072: landed, and the operator is left on the base branch.
        current = _run(
            "git", "rev-parse", "--abbrev-ref", "HEAD", cwd=vault
        ).stdout.strip()
        assert current == "main"
        assert (vault / "data_vault" / "n1.md").is_file()

    def test_rc2_aborted_rewinds_last_cycle_commit(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        ctx = begin_run(vault, kind="research")
        _write_note(vault, "n1.md")
        commit_cycle(vault, cycle=1, summary={"notes_added": 1}, ctx=ctx)
        # Simulate one more partial cycle that gets aborted: write but
        # also commit (orchestrator may have done so before the abort).
        _write_note(vault, "n2.md")
        commit_cycle(vault, cycle=2, summary={"notes_added": 1}, ctx=ctx)
        result = complete_run(vault, final_rc=2, final_reason="aborted", ctx=ctx)
        assert result.ok is True
        # Cycle 2 commit rewound.
        log = _commit_log(vault, ref=ctx.branch)
        assert not any("cycle 2" in s for s in log)
        assert any("cycle 1" in s for s in log)

    def test_auto_merge_false_leaves_branch_and_drops_pointer(
        self, tmp_path: Path
    ) -> None:
        vault = _make_vault(tmp_path)
        _write_settings(vault, {"auto_merge": False})
        ctx = begin_run(vault, kind="research")
        _write_note(vault, "n1.md")
        commit_cycle(vault, cycle=1, summary={"notes_added": 1}, ctx=ctx)
        result = complete_run(vault, final_rc=0, final_reason="clean", ctx=ctx)
        assert result.ok is True
        assert result.merged is False
        assert result.branch_retained is True
        assert ctx.branch in _branches(vault)
        # Main carries the pointer commit (empty).
        log = _commit_log(vault, ref="main")
        assert any("research run:" in s for s in log)


# ---------------------------------------------------------------------------
# Push policy
# ---------------------------------------------------------------------------


class TestPushPolicy:
    def _make_remote(self, tmp_path: Path, vault: Path) -> Path:
        bare = tmp_path / "remote.git"
        _run("git", "init", "--bare", str(bare), cwd=tmp_path)
        _run("git", "remote", "add", "origin", str(bare), cwd=vault)
        # Seed the bare repo with main so non-fast-forward isn't an issue.
        _run("git", "push", "-u", "origin", "main", cwd=vault)
        return bare

    def test_auto_pushes_when_remote_present(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        bare = self._make_remote(tmp_path, vault)
        ctx = begin_run(vault, kind="research")
        _write_note(vault, "n.md")
        commit_cycle(vault, cycle=1, summary={"notes_added": 1}, ctx=ctx)
        result = complete_run(vault, final_rc=0, final_reason="ok", ctx=ctx)
        assert result.pushed is True
        # The squashed merge commit is now in the bare repo.
        remote_log = _run(
            "git", "log", "--pretty=%s", "-n", "5", "main", cwd=bare
        ).stdout
        assert "research run:" in remote_log

    def test_never_skips_push_even_with_remote(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        self._make_remote(tmp_path, vault)
        _write_settings(vault, {"push_on_complete": "never"})
        ctx = begin_run(vault, kind="research")
        _write_note(vault, "n.md")
        commit_cycle(vault, cycle=1, summary={"notes_added": 1}, ctx=ctx)
        result = complete_run(vault, final_rc=0, final_reason="ok", ctx=ctx)
        assert result.pushed is False

    def test_always_without_remote_warns_does_not_fail(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write_settings(vault, {"push_on_complete": "always"})
        ctx = begin_run(vault, kind="research")
        _write_note(vault, "n.md")
        commit_cycle(vault, cycle=1, summary={"notes_added": 1}, ctx=ctx)
        result = complete_run(vault, final_rc=0, final_reason="ok", ctx=ctx)
        assert result.ok is True
        assert result.pushed is False

    # -- values other than the three documented strings --------------------
    #
    # A push cannot be taken back, so the policy must not resolve to "push"
    # by default: only `never` used to suppress it, and every other value —
    # YAML's own spellings of "no" included — fell through to `auto`.

    def _run_with_policy(
        self, tmp_path: Path, yaml_value: str
    ) -> tuple[CompleteResult, str]:
        """Land one run under ``push_on_complete: <yaml_value>``; return the
        result and the subjects on the remote's ``main``."""
        vault = _make_vault(tmp_path)
        bare = self._make_remote(tmp_path, vault)
        _write_settings_text(
            vault, f"vault_commit:\n  push_on_complete: {yaml_value}\n"
        )
        ctx = begin_run(vault, kind="research")
        _write_note(vault, "n.md")
        commit_cycle(vault, cycle=1, summary={"notes_added": 1}, ctx=ctx)
        result = complete_run(vault, final_rc=0, final_reason="ok", ctx=ctx)
        remote_log = _run(
            "git", "log", "--pretty=%s", "-n", "5", "main", cwd=bare
        ).stdout
        return result, remote_log

    @pytest.mark.parametrize("yaml_value", ["false", "no", "off", "False", "NO"])
    def test_yaml_false_means_never(self, tmp_path: Path, yaml_value: str) -> None:
        result, remote_log = self._run_with_policy(tmp_path, yaml_value)
        assert result.ok is True
        assert result.pushed is False
        assert "research run:" not in remote_log

    @pytest.mark.parametrize(
        "yaml_value",
        ["nver", "'no'", "disabled", "", "0", "[never]"],
        ids=["typo", "quoted-no", "other-word", "empty", "integer", "list"],
    )
    def test_unrecognised_policy_does_not_push_and_warns(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture, yaml_value: str
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="research_framework"):
            result, remote_log = self._run_with_policy(tmp_path, yaml_value)
        assert result.ok is True
        assert result.pushed is False
        assert "research run:" not in remote_log
        warnings = [
            r.getMessage()
            for r in caplog.records
            if r.levelno == logging.WARNING and "push_on_complete" in r.getMessage()
        ]
        assert len(warnings) == 1, caplog.text
        assert "not pushing" in warnings[0]

    @pytest.mark.parametrize(
        "yaml_value", ["true", "yes", "on", "Auto", "ALWAYS", "' auto '"]
    )
    def test_yaml_true_and_case_variants_still_push(
        self, tmp_path: Path, yaml_value: str
    ) -> None:
        result, remote_log = self._run_with_policy(tmp_path, yaml_value)
        assert result.pushed is True
        assert "research run:" in remote_log

    @pytest.mark.parametrize("yaml_value", ["Never", "NEVER", "' never '"])
    def test_never_is_matched_case_insensitively(
        self, tmp_path: Path, yaml_value: str
    ) -> None:
        result, remote_log = self._run_with_policy(tmp_path, yaml_value)
        assert result.pushed is False
        assert "research run:" not in remote_log


# ---------------------------------------------------------------------------
# commit_framework_change
# ---------------------------------------------------------------------------


class TestCommitFrameworkChange:
    def test_records_upgrade_on_main(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        (vault / ".scaffold").write_text("scaffold v2\n", encoding="utf-8")
        result = commit_framework_change(
            vault, title="upgrade to 0.7.0", body="changelog excerpt..."
        )
        assert result.ok is True
        assert result.sha is not None
        assert _commit_log(vault)[0] == "framework: upgrade to 0.7.0"

    def test_no_changes_skips(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        result = commit_framework_change(vault, title="upgrade to 0.7.0")
        assert result.ok is True
        assert result.skipped_reason == "no changes"


# ---------------------------------------------------------------------------
# commit_command_output
# ---------------------------------------------------------------------------


class TestCommitCommandOutput:
    def test_ask_output_committed(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        out = vault / "_output"
        out.mkdir()
        (out / "answer-001.md").write_text("answer\n", encoding="utf-8")
        result = commit_command_output(
            vault,
            command="ask",
            output_paths=[out / "answer-001.md"],
            summary="What is X?",
        )
        assert result.ok is True
        msg = _run("git", "log", "-1", "--pretty=%B", cwd=vault).stdout
        assert msg.startswith("vault: ask — What is X?")
        assert "_output/answer-001.md" in msg

    def test_no_output_silent_skip(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        result = commit_command_output(
            vault, command="write", output_paths=[], summary="nothing happened"
        )
        assert result.ok is True
        assert result.skipped_reason == "no changes"


# ---------------------------------------------------------------------------
# Repo-edge cases
# ---------------------------------------------------------------------------


class TestNoRepo:
    def test_begin_run_on_non_repo_returns_none(self, tmp_path: Path) -> None:
        bare = tmp_path / "no_git"
        bare.mkdir()
        assert begin_run(bare, kind="research") is None

    def test_commit_cycle_on_non_repo_returns_ok_skipped(self, tmp_path: Path) -> None:
        bare = tmp_path / "no_git"
        bare.mkdir()
        result = commit_cycle(bare, cycle=1, summary={})
        assert result.ok is True
        assert result.skipped_reason == "not a git repo"


# ---------------------------------------------------------------------------
# Public dirty-tree wrapper (spec 027 FR-003)
# ---------------------------------------------------------------------------


def test_is_working_tree_dirty_is_public_export() -> None:
    assert callable(is_working_tree_dirty)
    assert is_working_tree_dirty.__name__ == "is_working_tree_dirty"


def test_is_working_tree_dirty_true_on_dirty_vault(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    (vault / "dirty.txt").write_text("x\n", encoding="utf-8")
    assert is_working_tree_dirty(vault) is True
    assert is_working_tree_dirty(vault) == _is_dirty(vault)


def test_is_working_tree_dirty_false_on_clean_vault(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    assert is_working_tree_dirty(vault) is False
    assert is_working_tree_dirty(vault) == _is_dirty(vault)


def test_is_working_tree_dirty_false_when_vault_is_not_a_repository(
    tmp_path: Path,
) -> None:
    """Spec 027: "non-git vaults degrade gracefully". `git status` fails
    outside a repository; the update verb read that failure — a traceback and
    a non-zero exit — as "Working tree is dirty. Commit or stash changes"."""
    plain = tmp_path / "plain-vault"
    plain.mkdir()
    (plain / "note.md").write_text("never versioned\n", encoding="utf-8")
    assert is_working_tree_dirty(plain) is False


def test_is_working_tree_dirty_ignores_the_enclosing_repository(
    tmp_path: Path,
) -> None:
    """A vault nested in someone else's repository is never committed to
    (`TestVaultInsideAnotherRepository`), so that repository's uncommitted
    files are not the vault's to "commit or stash"."""
    parent = _make_vault(tmp_path)
    (parent / "unrelated_wip.txt").write_text("wip\n", encoding="utf-8")
    vault = parent / "nested-vault"
    vault.mkdir()
    assert is_working_tree_dirty(vault) is False


# ---------------------------------------------------------------------------
# Issue #307 / owner decision D10 (2026-09-08): research-branch retention is
# evaluated when a session starts and after a run lands, and every completed
# run leaves the checkout on the base branch so an open research branch is
# only ever a record. These tests drive the REAL begin_run / commit_cycle /
# complete_run flow on a git-backed vault — no hand-rolled markers.
# ---------------------------------------------------------------------------


def _current_branch(vault: Path) -> str:
    return _run("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=vault).stdout.strip()


def _write_settings_text(vault: Path, text: str) -> None:
    (vault / "settings.yaml").write_text(text, encoding="utf-8")
    _run("git", "add", "settings.yaml", cwd=vault)
    _run("git", "commit", "-m", "test: write settings", cwd=vault)


def _land_one_run(vault: Path, note: str, *, final_rc: int = 1) -> str:
    """Run one real research session to completion; return its branch name."""
    ctx = begin_run(vault, kind="research")
    assert ctx is not None
    _write_note(vault, note)
    commit_cycle(vault, cycle=1, summary={"notes_added": 1}, ctx=ctx)
    result = complete_run(vault, final_rc=final_rc, final_reason="test", ctx=ctx)
    assert result.ok is True
    return ctx.branch


class TestEveryCompletedRunReturnsToMain:
    """D10's premise, pinned: after a run completes, the checkout is on main.

    rc=0 and rc=1 are the designed terminal states (spec 072 FR1); an empty
    rc=1 drops its branch (#250). rc=2 is an abort, not a completion, and is
    left on the branch on purpose. The `auto_merge: false` opt-out is the
    operator's own review gate: a clean rc=0 DOES return to main, with an
    empty pointer commit and the content only on the branch — so that branch
    must read as unlanded to retention, which is pinned here so a change is
    loud.
    """

    def test_rc0_lands_and_returns_to_main(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _land_one_run(vault, "n1.md", final_rc=0)
        assert _current_branch(vault) == "main"

    def test_rc1_with_commits_lands_returns_to_main_and_branch_is_landed(
        self, tmp_path: Path
    ) -> None:
        vault = _make_vault(tmp_path)
        branch = _land_one_run(vault, "n1.md", final_rc=1)
        assert _current_branch(vault) == "main"
        landed = {b.name: b.landed for b in list_research_branches(vault)}
        assert landed == {branch: True}

    def test_rc1_without_commits_drops_branch_and_returns_to_main(
        self, tmp_path: Path
    ) -> None:
        vault = _make_vault(tmp_path)
        ctx = begin_run(vault, kind="research")
        assert ctx is not None
        result = complete_run(vault, final_rc=1, final_reason="nothing", ctx=ctx)
        assert result.ok is True
        assert _current_branch(vault) == "main"
        assert ctx.branch not in _branches(vault)

    def test_rc2_abort_is_not_a_completion_and_stays_on_branch(
        self, tmp_path: Path
    ) -> None:
        vault = _make_vault(tmp_path)
        ctx = begin_run(vault, kind="research")
        assert ctx is not None
        _write_note(vault, "n1.md")
        commit_cycle(vault, cycle=1, summary={"notes_added": 1}, ctx=ctx)
        complete_run(vault, final_rc=2, final_reason="aborted", ctx=ctx)
        assert _current_branch(vault) == ctx.branch

    def test_rc0_auto_merge_off_returns_to_main_but_branch_is_unlanded(
        self, tmp_path: Path
    ) -> None:
        vault = _make_vault(tmp_path)
        _write_settings_text(vault, "vault_commit:\n  auto_merge: false\n")
        ctx = begin_run(vault, kind="research")
        assert ctx is not None
        _write_note(vault, "n1.md")
        commit_cycle(vault, cycle=1, summary={"notes_added": 1}, ctx=ctx)
        result = complete_run(vault, final_rc=0, final_reason="clean", ctx=ctx)
        assert result.ok is True
        assert _current_branch(vault) == "main"
        # Main carries the pointer (same `**Branch:**` line as a landing)
        # but not the content — the classifier must not be fooled by it.
        assert any("research run:" in s for s in _commit_log(vault, ref="main"))
        assert not (vault / "data_vault" / "n1.md").exists()
        landed = {b.name: b.landed for b in list_research_branches(vault)}
        assert landed == {ctx.branch: False}


class TestRetentionAtSessionStart:
    def test_begin_run_prunes_landed_branches_beyond_the_cap_and_reports(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        vault = _make_vault(tmp_path)
        first = _land_one_run(vault, "n1.md")
        second = _land_one_run(vault, "n2.md")
        # Both landed and retained under the default cap of 5. Tighten the
        # cap to 1 AFTER they landed, so the prune below can only be the
        # session-start check — not `complete_run`'s own (tested separately).
        assert first in _branches(vault) and second in _branches(vault)
        _write_settings_text(vault, "vault_commit:\n  retention:\n    keep_last: 1\n")

        with caplog.at_level(logging.INFO, logger="research_framework"):
            ctx = begin_run(vault, kind="research")
        assert ctx is not None
        assert first not in _branches(vault)
        assert second in _branches(vault)
        lines = [
            r.getMessage()
            for r in caplog.records
            if r.levelno == logging.INFO and "pruned" in r.getMessage()
        ]
        assert len(lines) == 1, caplog.text
        assert first in lines[0] and "(cap)" in lines[0]
        assert "\n" not in lines[0]

    def test_begin_run_never_deletes_an_unlanded_branch(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        _write_settings_text(
            vault,
            "vault_commit:\n  retention:\n    keep_last: 0\n    max_age_days: 1\n",
        )
        # An interrupted run: branch with a cycle commit, never landed.
        ctx = begin_run(vault, kind="research")
        assert ctx is not None
        _write_note(vault, "n1.md")
        commit_cycle(vault, cycle=1, summary={"notes_added": 1}, ctx=ctx)
        _run("git", "checkout", "main", cwd=vault)
        stranded = ctx.branch

        ctx2 = begin_run(vault, kind="research")
        assert ctx2 is not None
        assert stranded in _branches(vault)

    def test_begin_run_is_silent_when_nothing_is_pruned(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        vault = _make_vault(tmp_path)
        _land_one_run(vault, "n1.md")
        with caplog.at_level(logging.INFO, logger="research_framework"):
            begin_run(vault, kind="research")
        assert not any("pruned" in r.getMessage() for r in caplog.records)

    def test_disabled_policy_prunes_nothing_at_session_start(
        self, tmp_path: Path
    ) -> None:
        vault = _make_vault(tmp_path)
        _write_settings_text(
            vault,
            "vault_commit:\n  retention:\n    keep_last: null\n    max_age_days: null\n",
        )
        branches = [_land_one_run(vault, f"n{i}.md") for i in range(1, 8)]
        begin_run(vault, kind="research")
        assert all(b in _branches(vault) for b in branches)

    def test_dirty_main_refuses_before_pruning_anything(self, tmp_path: Path) -> None:
        """A refused session must have no side effects — not even a prune."""
        vault = _make_vault(tmp_path)
        landed = _land_one_run(vault, "n1.md")
        # Cap 0 = keep no landed record; set after landing so the record is
        # still there for the refused session to (not) prune.
        _write_settings_text(vault, "vault_commit:\n  retention:\n    keep_last: 0\n")
        assert landed in _branches(vault)
        (vault / "README.md").write_text("dirty\n", encoding="utf-8")
        with pytest.raises(VaultCommitDirtyError):
            begin_run(vault, kind="research")
        assert landed in _branches(vault)


class TestPrunedNamesAreNeverReused:
    def test_a_pruned_branch_name_is_not_reallocated_to_a_new_run(
        self, tmp_path: Path
    ) -> None:
        """Landedness is a marker on main; a reused name would inherit it.

        Land a run, prune its record, then start another run at the SAME
        minute: the new branch must get a fresh suffix, and must not read as
        landed before it has landed anything.
        """
        vault = _make_vault(tmp_path)
        moment = datetime(2026, 9, 8, 12, 0)
        ctx = begin_run(vault, kind="research", now=moment)
        assert ctx is not None
        _write_note(vault, "n1.md")
        commit_cycle(vault, cycle=1, summary={"notes_added": 1}, ctx=ctx)
        complete_run(vault, final_rc=1, final_reason="constrained", ctx=ctx)
        old_name = ctx.branch
        assert prune_research_branches(vault, keep_last=0, dry_run=False).deleted == [
            old_name
        ]

        ctx2 = begin_run(vault, kind="research", now=moment)
        assert ctx2 is not None
        assert ctx2.branch != old_name
        assert ctx2.branch.startswith(old_name)
        assert is_branch_landed(vault, ctx2.branch) is False


class TestRetentionAfterLanding:
    def test_complete_run_prunes_beyond_the_cap_once_back_on_main(
        self, tmp_path: Path
    ) -> None:
        vault = _make_vault(tmp_path)
        _write_settings_text(vault, "vault_commit:\n  retention:\n    keep_last: 1\n")
        first = _land_one_run(vault, "n1.md")
        assert first in _branches(vault)
        second = _land_one_run(vault, "n2.md")
        # Landing the second run returned to main and applied the cap: the
        # older landed record is gone, the just-landed one is the kept one.
        assert _current_branch(vault) == "main"
        assert first not in _branches(vault)
        assert second in _branches(vault)

    def test_auto_merge_off_leaves_review_branch_and_prunes_nothing(
        self, tmp_path: Path
    ) -> None:
        """With the opt-out the branch is a review gate, not a record."""
        vault = _make_vault(tmp_path)
        _write_settings_text(
            vault,
            "vault_commit:\n  auto_merge: false\n  retention:\n    keep_last: 0\n",
        )
        ctx = begin_run(vault, kind="research")
        assert ctx is not None
        _write_note(vault, "n1.md")
        commit_cycle(vault, cycle=1, summary={"notes_added": 1}, ctx=ctx)
        result = complete_run(vault, final_rc=1, final_reason="constrained", ctx=ctx)
        assert result.ok is True
        assert result.branch_retained is True
        assert _current_branch(vault) == ctx.branch
        assert ctx.branch in _branches(vault)

    def test_auto_merge_off_clean_run_returns_to_main_and_prunes_nothing(
        self, tmp_path: Path
    ) -> None:
        """rc=0 with the opt-out: back on main, so retention runs — and the

        pointer-only branch must survive even a `keep_last: 0` policy, on
        this pass and on the next session start.
        """
        vault = _make_vault(tmp_path)
        _write_settings_text(
            vault,
            "vault_commit:\n  auto_merge: false\n  retention:\n    keep_last: 0\n",
        )
        ctx = begin_run(vault, kind="research")
        assert ctx is not None
        _write_note(vault, "n1.md")
        commit_cycle(vault, cycle=1, summary={"notes_added": 1}, ctx=ctx)
        result = complete_run(vault, final_rc=0, final_reason="clean", ctx=ctx)
        assert result.ok is True
        assert result.branch_retained is True
        assert _current_branch(vault) == "main"
        assert ctx.branch in _branches(vault)
        # The next session's start-of-run pass sees the same pointer branch.
        nxt = begin_run(vault, kind="research")
        assert nxt is not None
        assert ctx.branch in _branches(vault)
        assert is_branch_landed(vault, ctx.branch) is False


# ---------------------------------------------------------------------------
# An abort (rc=2) undoes the aborted cycle's own commit and nothing else.
# Spec 050's lifecycle: "reset --hard HEAD~1 on branch (if last commit was an
# aborted-cycle stub)". The scaffold's .gitignore keeps most of `_pipeline/`
# out of git, so a cycle that aborts before it writes a note has no diff and
# makes no commit — the branch tip is then the previous, good cycle.
# ---------------------------------------------------------------------------


def _failing_commit_hook(tmp_path: Path, vault: Path) -> None:
    """Make every later `git commit` in *vault* fail (a pre-commit hook)."""
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    hook = hooks / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    _run("git", "config", "core.hooksPath", str(hooks), cwd=vault)


class TestAbortRewindsOnlyItsOwnCommit:
    def test_rc2_with_no_diff_keeps_the_previous_cycle_commit(
        self, tmp_path: Path
    ) -> None:
        vault = _make_vault(tmp_path)
        ctx = begin_run(vault, kind="research")
        assert ctx is not None
        _write_note(vault, "n1.md")
        commit_cycle(vault, cycle=1, summary={"notes_added": 1}, ctx=ctx)
        _write_note(vault, "n2.md")
        commit_cycle(vault, cycle=2, summary={"notes_added": 1}, ctx=ctx)
        good_tip = _head_sha(vault)

        # Cycle 3 aborts before it writes anything git tracks.
        aborted = commit_cycle(
            vault, cycle=3, summary={"exit_reason": "aborted"}, ctx=ctx
        )
        assert aborted.skipped_reason == "no changes"
        result = complete_run(vault, final_rc=2, final_reason="aborted", ctx=ctx)

        assert result.ok is True
        assert _head_sha(vault) == good_tip
        assert (vault / "data_vault" / "n2.md").is_file()
        assert any("cycle 2" in s for s in _commit_log(vault, ref=ctx.branch))

    def test_rc2_when_the_abort_commit_failed_keeps_earlier_work_and_the_tree(
        self, tmp_path: Path
    ) -> None:
        vault = _make_vault(tmp_path)
        ctx = begin_run(vault, kind="research")
        assert ctx is not None
        _write_note(vault, "n1.md")
        commit_cycle(vault, cycle=1, summary={"notes_added": 1}, ctx=ctx)
        good_tip = _head_sha(vault)

        _failing_commit_hook(tmp_path, vault)
        _write_note(vault, "partial.md")
        aborted = commit_cycle(
            vault, cycle=2, summary={"exit_reason": "aborted"}, ctx=ctx
        )
        assert aborted.ok is False
        complete_run(vault, final_rc=2, final_reason="aborted", ctx=ctx)

        assert _head_sha(vault) == good_tip
        assert (vault / "data_vault" / "n1.md").is_file()
        # The uncommitted partial work is the only copy; a hard reset to the
        # parent of a commit that was never made would have deleted it.
        assert (vault / "data_vault" / "partial.md").is_file()

    def test_rc2_after_a_same_cycle_reemit_restores_the_commit_it_amended(
        self, tmp_path: Path
    ) -> None:
        """Spec 062 FR2 folds a same-cycle re-emit into HEAD with `--amend`.

        When that re-emit is the aborted one, undoing it means going back to
        the commit it amended — `HEAD~1` is one commit too far and drops the
        cycle's earlier, good content with it.
        """
        vault = _make_vault(tmp_path)
        ctx = begin_run(vault, kind="research")
        assert ctx is not None
        _write_note(vault, "n1.md")
        commit_cycle(vault, cycle=1, summary={"notes_added": 1}, ctx=ctx)
        _write_note(vault, "n2.md")
        commit_cycle(vault, cycle=2, summary={"notes_added": 1}, ctx=ctx)
        good_tip = _head_sha(vault)
        good_shas = list(ctx.cycle_commit_shas)

        _write_note(vault, "partial.md")
        commit_cycle(vault, cycle=2, summary={"exit_reason": "aborted"}, ctx=ctx)
        assert _head_sha(vault) != good_tip  # amended in place
        complete_run(vault, final_rc=2, final_reason="aborted", ctx=ctx)

        assert _head_sha(vault) == good_tip
        assert (vault / "data_vault" / "n2.md").is_file()
        assert not (vault / "data_vault" / "partial.md").exists()
        assert ctx.cycle_commit_shas == good_shas

    def test_rc2_without_a_cycle_commit_in_this_process_rewinds_nothing(
        self, tmp_path: Path
    ) -> None:
        """`complete_run` falling back to the state file knows the run's
        commits, not which of them (if any) the aborted cycle made."""
        vault = _make_vault(tmp_path)
        ctx = begin_run(vault, kind="research")
        assert ctx is not None
        _write_note(vault, "n1.md")
        commit_cycle(vault, cycle=1, summary={"notes_added": 1}, ctx=ctx)
        good_tip = _head_sha(vault)

        complete_run(vault, final_rc=2, final_reason="aborted", ctx=None)

        assert _head_sha(vault) == good_tip
        assert (vault / "data_vault" / "n1.md").is_file()


# ---------------------------------------------------------------------------
# A branch is dropped only when it is empty. "Did this run commit anything?"
# is a question for git: the in-memory list is empty on every resume that
# follows an rc=2 abort (the abort clears the state file) and never counts a
# commit the operator made on the branch.
# ---------------------------------------------------------------------------


def _files_on(vault: Path, ref: str) -> list[str]:
    return _run(
        "git", "ls-tree", "-r", "--name-only", ref, cwd=vault
    ).stdout.splitlines()


def _abort_then_resume(vault: Path, notes: list[str]):
    """Commit one cycle per note, abort the next cycle, resume the branch.

    The aborted cycle does write something, so its own commit is made and
    rewound — the state this leaves is "a branch with ``len(notes)`` good
    cycle commits, and no state file".
    """
    ctx = begin_run(vault, kind="research")
    assert ctx is not None
    for cycle, name in enumerate(notes, start=1):
        _write_note(vault, name)
        commit_cycle(vault, cycle=cycle, summary={"notes_added": 1}, ctx=ctx)
    good_shas = list(ctx.cycle_commit_shas)
    _write_note(vault, "partial.md")
    commit_cycle(
        vault, cycle=len(notes) + 1, summary={"exit_reason": "aborted"}, ctx=ctx
    )
    complete_run(vault, final_rc=2, final_reason="aborted", ctx=ctx)
    assert _head_sha(vault) == good_shas[-1]

    resumed = begin_run(vault, kind="research", resume=True)
    assert resumed is not None
    assert resumed.branch == ctx.branch
    return resumed, good_shas


class TestUnlandedWorkIsNeverDropped:
    def test_resume_without_state_rebuilds_the_cycle_commits_from_git(
        self, tmp_path: Path
    ) -> None:
        vault = _make_vault(tmp_path)
        resumed, good_shas = _abort_then_resume(vault, ["n1.md", "n2.md"])
        assert resumed.cycle_commit_shas == good_shas

    def test_rc1_on_a_resumed_run_lands_the_earlier_cycles(
        self, tmp_path: Path
    ) -> None:
        """The resumed run hits its budget cap before committing anything
        new. Cycles 1 and 2 are still unlanded work on the branch."""
        vault = _make_vault(tmp_path)
        resumed, _ = _abort_then_resume(vault, ["n1.md", "n2.md"])

        commit_cycle(vault, cycle=3, summary={"notes_added": 0}, ctx=resumed)
        result = complete_run(
            vault, final_rc=1, final_reason="budget cap reached", ctx=resumed
        )

        assert result.ok is True
        assert _current_branch(vault) == "main"
        on_main = _files_on(vault, "main")
        assert "data_vault/n1.md" in on_main and "data_vault/n2.md" in on_main
        # Spec 072 FR5: a constrained landing keeps its branch.
        assert resumed.branch in _branches(vault)
        assert _commit_log(vault, ref="main")[0].endswith("2 cycle(s)")

    def test_rc1_with_the_review_gate_keeps_a_resumed_branch(
        self, tmp_path: Path
    ) -> None:
        """`auto_merge: false` never lands — and must not delete either."""
        vault = _make_vault(tmp_path)
        _write_settings_text(vault, "vault_commit:\n  auto_merge: false\n")
        resumed, good_shas = _abort_then_resume(vault, ["n1.md"])

        result = complete_run(
            vault, final_rc=1, final_reason="budget cap reached", ctx=resumed
        )

        assert result.ok is True
        assert result.branch_retained is True
        assert resumed.branch in _branches(vault)
        assert (
            _run("git", "rev-parse", resumed.branch, cwd=vault).stdout.strip()
            == good_shas[-1]
        )

    def test_rc1_keeps_a_commit_the_operator_made_on_the_run_branch(
        self, tmp_path: Path
    ) -> None:
        vault = _make_vault(tmp_path)
        ctx = begin_run(vault, kind="research")
        assert ctx is not None
        _write_note(vault, "by-hand.md")
        _run("git", "add", "-A", cwd=vault)
        _run("git", "commit", "-m", "notes: a hand-written note", cwd=vault)
        assert ctx.cycle_commit_shas == []

        result = complete_run(vault, final_rc=1, final_reason="nothing", ctx=ctx)

        assert result.ok is True
        assert "data_vault/by-hand.md" in _files_on(vault, "main")


# ---------------------------------------------------------------------------
# The invariant acts on the vault's OWN repository. Every commit stages with
# `git add -A`, which is repository-wide, and a research run branches, merges
# and pushes the whole repository — so a vault directory that merely sits
# inside someone else's work tree must not be treated as "a git repo".
# ---------------------------------------------------------------------------


def _status(repo: Path) -> list[str]:
    return _run(
        "git", "status", "--porcelain", "--untracked-files=all", cwd=repo
    ).stdout.splitlines()


class TestVaultInsideAnotherRepository:
    def _nested_vault(self, tmp_path: Path) -> tuple[Path, Path]:
        parent = _make_vault(tmp_path)  # stands in for the enclosing repo
        (parent / "unrelated-wip.txt").write_text("not the vault's\n", encoding="utf-8")
        vault = parent / "vaults" / "v"
        vault.mkdir(parents=True)
        _write_note(vault, "n1.md")
        return parent, vault

    def test_command_output_is_not_committed_to_the_enclosing_repo(
        self, tmp_path: Path
    ) -> None:
        parent, vault = self._nested_vault(tmp_path)
        head, status = _head_sha(parent), _status(parent)

        result = commit_command_output(vault, command="ask", summary="answer")

        assert result.ok is True
        assert result.skipped_reason == "not a git repo"
        assert _head_sha(parent) == head
        # Nothing staged either: the operator's index is theirs.
        assert _status(parent) == status

    def test_a_research_run_does_not_branch_or_commit_the_enclosing_repo(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        parent, vault = self._nested_vault(tmp_path)
        _run("git", "add", "-A", cwd=parent)
        _run("git", "commit", "-m", "parent: tracked state", cwd=parent)
        head = _head_sha(parent)

        with caplog.at_level(logging.WARNING, logger="research_framework"):
            ctx = begin_run(vault, kind="research")
        assert ctx is None
        assert str(parent.resolve()) in caplog.text or str(parent) in caplog.text

        _write_note(vault, "n2.md")
        assert (
            commit_cycle(vault, cycle=1, summary={}, ctx=ctx).skipped_reason
            == "not a git repo"
        )
        assert complete_run(vault, final_rc=0, final_reason="ok", ctx=ctx).ok is True
        assert (
            commit_framework_change(vault, title="upgrade").skipped_reason
            == "not a git repo"
        )
        assert _current_branch(parent) == "main"
        assert _branches(parent) == ["main"]
        assert _head_sha(parent) == head


class TestVaultIsALinkedWorktree:
    def test_a_run_starts_resumes_and_lands_when_dot_git_is_a_file(
        self, tmp_path: Path
    ) -> None:
        """In a linked worktree `.git` is a file, so the run state cannot
        live at `<vault>/.git/research-framework/` — it lives wherever git
        says that worktree's git dir is."""
        repo = _make_vault(tmp_path)
        _run("git", "checkout", "-b", "parked", cwd=repo)  # frees `main`
        vault = tmp_path / "vault-worktree"
        _run("git", "worktree", "add", str(vault), "main", cwd=repo)
        assert (vault / ".git").is_file()

        ctx = begin_run(vault, kind="research")
        assert ctx is not None
        assert _current_branch(vault) == ctx.branch
        _write_note(vault, "n1.md")
        assert commit_cycle(vault, cycle=1, summary={}, ctx=ctx).ok is True

        resumed = begin_run(vault, kind="research", resume=True)
        assert resumed is not None
        assert resumed.cycle_commit_shas == ctx.cycle_commit_shas
        assert resumed.started_at == ctx.started_at  # read back, not rebuilt

        result = complete_run(vault, final_rc=0, final_reason="ok", ctx=resumed)
        assert result.ok is True and result.merged is True
        assert _current_branch(vault) == "main"
        assert "data_vault/n1.md" in _files_on(vault, "main")


# ---------------------------------------------------------------------------
# Spec 072 FR3 — a landing that cannot apply stops and stays on the branch
# ---------------------------------------------------------------------------


def _run_that_conflicts_with_main(vault: Path) -> RunContext:
    """One committed cycle on a research branch, plus an operator commit on
    ``main`` that rewrites the same line — the squash-merge cannot apply."""
    note = vault / "note.md"
    note.write_text("# note\n\noriginal line\n", encoding="utf-8")
    _run("git", "add", "-A", cwd=vault)
    _run("git", "commit", "-m", "seed note", cwd=vault)

    ctx = begin_run(vault, kind="research")
    assert ctx is not None
    note.write_text("# note\n\nline from the run\n", encoding="utf-8")
    _write_note(vault, "new.md")
    assert commit_cycle(vault, cycle=1, summary={"notes_added": 1}, ctx=ctx).ok

    _run("git", "checkout", "main", cwd=vault)
    note.write_text("# note\n\nline from the operator\n", encoding="utf-8")
    _run("git", "commit", "-am", "operator edit on main", cwd=vault)
    _run("git", "checkout", ctx.branch, cwd=vault)
    return ctx


class TestLandingConflictStaysOnTheBranch:
    """ "If it is not [a fast-forward] (the operator committed to `main`
    mid-run), stop, stay on the branch, and say so — never auto-resolve a
    conflict in someone's notes." The squash-merge did stop, but it left
    `main` checked out with an unmerged index and conflict markers in the
    notes, where the next `git add -A` commits them."""

    @pytest.mark.parametrize("final_rc", [0, 1])
    def test_conflict_leaves_main_untouched_and_returns_to_the_branch(
        self, tmp_path: Path, final_rc: int
    ) -> None:
        vault = _make_vault(tmp_path)
        ctx = _run_that_conflicts_with_main(vault)
        main_before = _run("git", "rev-parse", "main", cwd=vault).stdout.strip()
        branch_before = _run("git", "rev-parse", ctx.branch, cwd=vault).stdout.strip()

        result = complete_run(vault, final_rc=final_rc, final_reason="done", ctx=ctx)

        assert result.ok is False
        assert result.branch_retained is True
        assert _current_branch(vault) == ctx.branch
        assert _status(vault) == []
        on_disk = (vault / "note.md").read_text(encoding="utf-8")
        assert "<<<<<<<" not in on_disk
        assert "line from the run" in on_disk
        assert _run("git", "rev-parse", "main", cwd=vault).stdout.strip() == main_before
        assert _head_sha(vault) == branch_before

    def test_next_vault_verb_cannot_commit_conflict_markers_to_main(
        self, tmp_path: Path
    ) -> None:
        vault = _make_vault(tmp_path)
        ctx = _run_that_conflicts_with_main(vault)
        complete_run(vault, final_rc=0, final_reason="done", ctx=ctx)

        # Every ad-hoc verb (`./vault ask`, `write`, `sync`) ends in this.
        (vault / "answer.md").write_text("an answer\n", encoding="utf-8")
        commit_command_output(vault, command="ask", summary="what is x")

        on_main = _run("git", "show", "main:note.md", cwd=vault).stdout
        assert "<<<<<<<" not in on_main
        assert on_main == "# note\n\nline from the operator\n"

    def test_unstaged_edit_outside_the_merge_survives(self, tmp_path: Path) -> None:
        """Backing out of the half-applied squash must not cost the operator
        an edit they had not committed yet."""
        vault = _make_vault(tmp_path)
        ctx = _run_that_conflicts_with_main(vault)
        (vault / "README.md").write_text("# vault\n\nunsaved edit\n", encoding="utf-8")

        result = complete_run(vault, final_rc=0, final_reason="done", ctx=ctx)

        assert result.ok is False
        assert _current_branch(vault) == ctx.branch
        assert _status(vault) == [" M README.md"]
        assert "unsaved edit" in (vault / "README.md").read_text(encoding="utf-8")

    def test_staged_work_is_not_reset_when_the_merge_refuses_to_start(
        self, tmp_path: Path
    ) -> None:
        """Git will not start a merge over a staged change, so nothing was
        half-applied — and the index is the operator's, not the merge's.
        Resetting it here would delete their staged edit."""
        vault = _make_vault(tmp_path)
        ctx = _run_that_conflicts_with_main(vault)
        (vault / "README.md").write_text("# vault\n\nstaged edit\n", encoding="utf-8")
        _run("git", "add", "README.md", cwd=vault)

        result = complete_run(vault, final_rc=0, final_reason="done", ctx=ctx)

        assert result.ok is False
        assert _current_branch(vault) == ctx.branch
        assert _status(vault) == ["M  README.md"]
        assert "staged edit" in (vault / "README.md").read_text(encoding="utf-8")

    def test_conflict_is_reported_with_what_to_do(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        vault = _make_vault(tmp_path)
        ctx = _run_that_conflicts_with_main(vault)
        with caplog.at_level(logging.WARNING, logger="research_framework"):
            complete_run(vault, final_rc=0, final_reason="done", ctx=ctx)
        warnings = [
            r.getMessage() for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert any(
            ctx.branch in m and "main" in m and "by hand" in m for m in warnings
        ), caplog.text
