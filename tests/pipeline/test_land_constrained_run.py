"""Spec 072 — a constrained run lands on main, and leaves you there.

Every run opened `research/<date>` and, on any non-zero exit, left the vault
sitting on it with "branch retained for review". But a **constrained** exit
(rc=1) is a *designed terminal state*, not a failure: budget-cap, max_cycles and
source-exhausted all mean "this run is over and its content is as valid as a
clean finish". `_constrained_exit` is where the orchestrator says so.

The operator was left holding a question the framework is better placed to
answer. Five vaults sat on research branches through the 2026-08-27 campaign,
and the operator merged one by hand:

    git checkout main && git merge research/2026-08-26-2054   # fast-forward

Correct — and not theirs to do.

rc=2 (abort) is deliberately excluded: it already rewinds its stub cycle-commit,
and a run that died mid-cycle is exactly the one a human should look at.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from research_framework.pipeline.vault_commit import (
    begin_run,
    commit_cycle,
    complete_run,
)


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(args), cwd=str(cwd), check=True, capture_output=True, text=True
    )


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    _run("git", "init", "-b", "main", cwd=vault)
    _run("git", "config", "user.email", "t@example.com", cwd=vault)
    _run("git", "config", "user.name", "T", cwd=vault)
    (vault / "README.md").write_text("# vault\n", encoding="utf-8")
    _run("git", "add", "-A", cwd=vault)
    _run("git", "commit", "-m", "initial", cwd=vault)
    return vault


def _current_branch(vault: Path) -> str:
    return _run("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=vault).stdout.strip()


def _branches(vault: Path) -> list[str]:
    return [
        ln.strip().lstrip("* ").strip()
        for ln in _run("git", "branch", cwd=vault).stdout.splitlines()
        if ln.strip()
    ]


def _note(vault: Path, name: str) -> None:
    (vault / "data_vault").mkdir(exist_ok=True)
    (vault / "data_vault" / name).write_text("body\n", encoding="utf-8")


def _one_cycle_run(vault: Path):
    ctx = begin_run(vault, kind="research", resume=False)
    _note(vault, "note.md")
    commit_cycle(vault, cycle=1, summary={}, ctx=ctx)
    return ctx


def test_constrained_run_lands_on_main(tmp_path: Path) -> None:
    """rc=1 with committed content is a completed run — land it."""
    vault = _make_vault(tmp_path)
    ctx = _one_cycle_run(vault)

    result = complete_run(
        vault, final_rc=1, final_reason="budget cap reached ($31 >= $31)", ctx=ctx
    )

    assert result.ok
    assert _current_branch(vault) == "main", "operator must end on main"
    assert (vault / "data_vault" / "note.md").is_file(), "content landed"


def test_the_branch_is_retained_for_recovery(tmp_path: Path) -> None:
    """FR5 — a bad landing must be recoverable, and per-cycle history survives."""
    vault = _make_vault(tmp_path)
    ctx = _one_cycle_run(vault)

    complete_run(vault, final_rc=1, final_reason="max_cycles reached", ctx=ctx)

    assert ctx.branch in _branches(vault)


def test_aborted_run_is_not_landed(tmp_path: Path) -> None:
    """rc=2 died mid-cycle — that is exactly what a human should look at."""
    vault = _make_vault(tmp_path)
    ctx = _one_cycle_run(vault)

    complete_run(vault, final_rc=2, final_reason="cycle 2 aborted (exit 2)", ctx=ctx)

    assert (vault / "data_vault" / "note.md").is_file() is False or _current_branch(
        vault
    ) == ctx.branch, "an aborted run must not silently land on main"


def test_a_run_with_nothing_committed_is_not_landed(tmp_path: Path) -> None:
    """Nothing to land, so don't touch main's content — but issue #250: a
    constrained exit that produced zero commits must not strand the empty
    `research/<ts>` branch it opened either. There is nothing on it to
    recover, so it is dropped and the operator ends up back on main. This
    is exactly the spec-070 F5 path: a `--resume` anchored past
    `--max-cycles` returns rc=1 before running a single cycle."""
    vault = _make_vault(tmp_path)
    ctx = begin_run(vault, kind="research", resume=False)

    result = complete_run(vault, final_rc=1, final_reason="budget cap", ctx=ctx)

    assert result.ok
    assert ctx.branch not in _branches(vault), "empty branch must be dropped"
    assert result.branch_retained is False
    assert _current_branch(vault) == "main"


def test_a_run_with_nothing_committed_and_auto_merge_off_is_still_dropped(
    tmp_path: Path,
) -> None:
    """The empty-branch cleanup is unconditional on `auto_merge` — that flag
    gates whether *content* auto-lands, and there is none here either way,
    so there is nothing for the review gate to hold open."""
    vault = _make_vault(tmp_path)
    (vault / "settings.yaml").write_text(
        "---\nvault_commit:\n  auto_merge: false\n---\n", encoding="utf-8"
    )
    _run("git", "add", "settings.yaml", cwd=vault)
    _run("git", "commit", "-m", "settings", cwd=vault)
    ctx = begin_run(vault, kind="research", resume=False)

    result = complete_run(vault, final_rc=1, final_reason="budget cap", ctx=ctx)

    assert result.ok
    assert ctx.branch not in _branches(vault)
    assert _current_branch(vault) == "main"


def test_auto_merge_false_still_retains(tmp_path: Path) -> None:
    """FR4 — the operator can keep the review gate."""
    vault = _make_vault(tmp_path)
    (vault / "settings.yaml").write_text(
        "---\nvault_commit:\n  auto_merge: false\n---\n", encoding="utf-8"
    )
    _run("git", "add", "settings.yaml", cwd=vault)
    _run("git", "commit", "-m", "settings", cwd=vault)
    ctx = _one_cycle_run(vault)

    complete_run(vault, final_rc=1, final_reason="budget cap", ctx=ctx)

    assert _current_branch(vault) == ctx.branch
    assert ctx.branch in _branches(vault)


def test_clean_exit_behaviour_is_unchanged(tmp_path: Path) -> None:
    """Regression: rc=0 still squash-merges and deletes its branch."""
    vault = _make_vault(tmp_path)
    ctx = _one_cycle_run(vault)

    complete_run(vault, final_rc=0, final_reason="vault complete", ctx=ctx)

    assert _current_branch(vault) == "main"
    assert ctx.branch not in _branches(vault), "rc=0 deletes its branch as before"


def test_landing_is_reported(tmp_path: Path) -> None:
    """The operator should be able to see what happened from the result."""
    vault = _make_vault(tmp_path)
    ctx = _one_cycle_run(vault)

    result = complete_run(vault, final_rc=1, final_reason="budget cap", ctx=ctx)

    assert result.ok
    assert result.branch_retained is True
