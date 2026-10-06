"""Tests for `pipeline.branch_retention` (issue #307, spec 072 FR5 follow-up).

Two fixture strategies, deliberately both used:

  - a hand-built git repo with synthetic commit messages, for fast
    unit-level coverage of the classification/prune logic in isolation;
  - the REAL `vault_commit.begin_run` / `commit_cycle` / `complete_run`
    flow, to prove the landed-branch marker this module greps for actually
    matches what production code writes — a hand-rolled fixture could
    quietly drift from the real format and this module would still report
    green while being wrong about what "landed" means.

The one invariant every prune test checks somewhere: an unlanded branch is
never a deletion candidate, at any age or count.
"""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from research_framework.pipeline.branch_retention import (
    DEFAULT_KEEP_LAST,
    DEFAULT_MAX_AGE_DAYS,
    POINTER_RETAINED_MARKER,
    RetentionPolicy,
    apply_retention_policy,
    format_prune_report,
    is_branch_landed,
    list_research_branches,
    load_retention_policy,
    prune_research_branches,
)
from research_framework.pipeline.vault_commit import (
    begin_run,
    commit_cycle,
    complete_run,
)


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(args), cwd=str(cwd), check=True, capture_output=True, text=True
    )


def _make_repo(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    _run("git", "init", "-b", "main", cwd=vault)
    _run("git", "config", "user.email", "test@example.com", cwd=vault)
    _run("git", "config", "user.name", "Test", cwd=vault)
    (vault / "README.md").write_text("# vault\n", encoding="utf-8")
    _run("git", "add", "-A", cwd=vault)
    _run("git", "commit", "-m", "initial", cwd=vault)
    return vault


def _add_landed_branch(vault: Path, name: str, *, commit_offset: int) -> None:
    """Fabricate a branch + a matching landing commit on main, hand-rolled.

    Mirrors `vault_commit._format_run_body`'s exact marker line
    (`**Branch:** <name>`) without going through the real landing code —
    used only for the fast unit tests; the "real format" claim is verified
    separately in TestAgainstRealVaultCommit below.
    """
    _run("git", "branch", name, cwd=vault)
    (vault / f"file-{commit_offset}.txt").write_text("x\n", encoding="utf-8")
    _run("git", "add", "-A", cwd=vault)
    message = f"research run: landed {commit_offset}\n\n**Branch:** {name}\n"
    _run("git", "commit", "-m", message, cwd=vault)


def _add_unlanded_branch(vault: Path, name: str) -> None:
    """A branch with no landing commit anywhere on main — never touch it."""
    _run("git", "branch", name, cwd=vault)


def _add_pointer_branch(vault: Path, name: str) -> None:
    """A branch whose content is ONLY on the branch, plus an empty pointer

    commit on main that carries the same `**Branch:**` line a landing would
    — what `vault_commit._emit_pointer_commit` writes for a clean run under
    `auto_merge: false`. Hand-rolled here; the real path is driven in
    TestAgainstRealVaultCommit.
    """
    _run("git", "checkout", "-b", name, cwd=vault)
    (vault / f"only-on-{name.replace('/', '-')}.txt").write_text(
        "z\n", encoding="utf-8"
    )
    _run("git", "add", "-A", cwd=vault)
    _run("git", "commit", "-m", "cycle 1", cwd=vault)
    _run("git", "checkout", "main", cwd=vault)
    message = (
        f"research run: pointer\n\n**Branch:** {name}\n\n{POINTER_RETAINED_MARKER}\n"
    )
    _run("git", "commit", "--allow-empty", "-m", message, cwd=vault)


def _branch_names(vault: Path) -> set[str]:
    out = _run("git", "branch", "--format=%(refname:short)", cwd=vault).stdout
    return {line.strip() for line in out.splitlines() if line.strip()}


class TestListAndClassify:
    def test_no_research_branches_returns_empty(self, tmp_path: Path) -> None:
        vault = _make_repo(tmp_path)
        assert list_research_branches(vault) == []

    def test_landed_branch_is_classified_landed(self, tmp_path: Path) -> None:
        vault = _make_repo(tmp_path)
        _add_landed_branch(vault, "research/2026-01-01-0000", commit_offset=1)
        assert is_branch_landed(vault, "research/2026-01-01-0000") is True
        branches = list_research_branches(vault)
        assert len(branches) == 1
        assert branches[0].name == "research/2026-01-01-0000"
        assert branches[0].landed is True

    def test_unlanded_branch_is_classified_unlanded(self, tmp_path: Path) -> None:
        vault = _make_repo(tmp_path)
        _add_unlanded_branch(vault, "research/2026-01-01-0000")
        assert is_branch_landed(vault, "research/2026-01-01-0000") is False
        branches = list_research_branches(vault)
        assert len(branches) == 1
        assert branches[0].landed is False

    def test_similar_branch_names_do_not_cross_match(self, tmp_path: Path) -> None:
        """A landing marker for one branch must not "land" a same-prefix sibling."""
        vault = _make_repo(tmp_path)
        _add_landed_branch(vault, "research/2026-01-01-0000", commit_offset=1)
        _add_unlanded_branch(vault, "research/2026-01-01-0000-02")
        branches = {b.name: b.landed for b in list_research_branches(vault)}
        assert branches["research/2026-01-01-0000"] is True
        assert branches["research/2026-01-01-0000-02"] is False

    def test_a_landed_suffixed_sibling_does_not_land_its_prefix(
        self, tmp_path: Path
    ) -> None:
        """The reverse direction: ``**Branch:** research/<ts>`` is a substring of
        ``**Branch:** research/<ts>-02``. A stranded ``<ts>`` run whose same-minute
        rerun landed as ``-02`` must stay unlanded, or prune deletes its commits."""
        vault = _make_repo(tmp_path)
        _add_unlanded_branch(vault, "research/2026-01-01-0000")
        _add_landed_branch(vault, "research/2026-01-01-0000-02", commit_offset=1)
        branches = {b.name: b.landed for b in list_research_branches(vault)}
        assert branches["research/2026-01-01-0000"] is False
        assert branches["research/2026-01-01-0000-02"] is True
        result = prune_research_branches(
            vault, keep_last=0, max_age_days=None, dry_run=False
        )
        assert "research/2026-01-01-0000" in _branch_names(vault)
        assert "research/2026-01-01-0000" not in result.deleted

    def test_pointer_only_branch_is_unlanded_and_never_a_candidate(
        self, tmp_path: Path
    ) -> None:
        """The pointer commit carries the marker but none of the content."""
        vault = _make_repo(tmp_path)
        _add_pointer_branch(vault, "research/2026-01-01-0000")
        assert is_branch_landed(vault, "research/2026-01-01-0000") is False
        result = prune_research_branches(
            vault, keep_last=0, max_age_days=None, dry_run=False
        )
        assert result.deleted == []
        assert result.kept_unlanded == ["research/2026-01-01-0000"]
        assert "research/2026-01-01-0000" in _branch_names(vault)

    def test_pointer_followed_by_a_real_landing_counts_as_landed(
        self, tmp_path: Path
    ) -> None:
        """An operator merging the reviewed branch later must not be masked

        by the older pointer: every matching commit is read, not the newest.
        """
        vault = _make_repo(tmp_path)
        _add_pointer_branch(vault, "research/2026-01-01-0000")
        (vault / "landed.txt").write_text("x\n", encoding="utf-8")
        _run("git", "add", "-A", cwd=vault)
        message = "research run: landed\n\n**Branch:** research/2026-01-01-0000\n"
        _run("git", "commit", "-m", message, cwd=vault)
        assert is_branch_landed(vault, "research/2026-01-01-0000") is True

    def test_list_is_sorted_oldest_first(self, tmp_path: Path) -> None:
        vault = _make_repo(tmp_path)
        _add_landed_branch(vault, "research/2026-03-01-0000", commit_offset=1)
        _add_landed_branch(vault, "research/2026-01-01-0000", commit_offset=2)
        _add_landed_branch(vault, "research/2026-02-01-0000", commit_offset=3)
        names = [b.name for b in list_research_branches(vault)]
        assert names == [
            "research/2026-01-01-0000",
            "research/2026-02-01-0000",
            "research/2026-03-01-0000",
        ]


class TestPrune:
    def test_dry_run_deletes_nothing(self, tmp_path: Path) -> None:
        vault = _make_repo(tmp_path)
        _add_landed_branch(vault, "research/2026-01-01-0000", commit_offset=1)
        result = prune_research_branches(vault, keep_last=0, dry_run=True)
        assert result.dry_run is True
        assert result.deleted == ["research/2026-01-01-0000"]
        # Still there — dry-run must not touch the repo.
        assert "research/2026-01-01-0000" in {
            b.name for b in list_research_branches(vault)
        }

    def test_keeps_newest_n_landed_branches(self, tmp_path: Path) -> None:
        vault = _make_repo(tmp_path)
        for i in range(1, 6):
            _add_landed_branch(vault, f"research/2026-01-0{i}-0000", commit_offset=i)
        result = prune_research_branches(vault, keep_last=2, dry_run=False)
        assert result.deleted == [
            "research/2026-01-01-0000",
            "research/2026-01-02-0000",
            "research/2026-01-03-0000",
        ]
        assert result.kept_landed == [
            "research/2026-01-04-0000",
            "research/2026-01-05-0000",
        ]
        remaining = {b.name for b in list_research_branches(vault)}
        assert remaining == {"research/2026-01-04-0000", "research/2026-01-05-0000"}

    def test_unlanded_branch_is_never_deleted_regardless_of_keep_last(
        self, tmp_path: Path
    ) -> None:
        """The one hard invariant: keep_last=0 still spares every unlanded branch."""
        vault = _make_repo(tmp_path)
        _add_landed_branch(vault, "research/2026-01-01-0000", commit_offset=1)
        _add_unlanded_branch(vault, "research/2026-01-02-0000")
        result = prune_research_branches(vault, keep_last=0, dry_run=False)
        assert result.deleted == ["research/2026-01-01-0000"]
        assert result.kept_unlanded == ["research/2026-01-02-0000"]
        remaining = {b.name for b in list_research_branches(vault)}
        assert remaining == {"research/2026-01-02-0000"}

    def test_fewer_landed_branches_than_keep_last_deletes_nothing(
        self, tmp_path: Path
    ) -> None:
        vault = _make_repo(tmp_path)
        _add_landed_branch(vault, "research/2026-01-01-0000", commit_offset=1)
        result = prune_research_branches(vault, keep_last=5, dry_run=False)
        assert result.deleted == []
        assert result.kept_landed == ["research/2026-01-01-0000"]

    def test_a_branch_git_refuses_to_delete_is_not_reported_deleted(
        self, tmp_path: Path
    ) -> None:
        """git refuses to delete a branch that a linked worktree has checked
        out (or whose ref is locked). The exit code was ignored, so the
        result — and the one-line retention report built from it — named a
        branch as pruned while it still existed."""
        vault = _make_repo(tmp_path)
        _add_landed_branch(vault, "research/2026-01-01-0000", commit_offset=1)
        _add_landed_branch(vault, "research/2026-01-02-0000", commit_offset=2)
        _run(
            "git",
            "worktree",
            "add",
            str(tmp_path / "elsewhere"),
            "research/2026-01-01-0000",
            cwd=vault,
        )

        result = prune_research_branches(vault, keep_last=0, dry_run=False)

        remaining = {b.name for b in list_research_branches(vault)}
        assert remaining == {"research/2026-01-01-0000"}
        assert result.deleted == ["research/2026-01-02-0000"]
        assert result.kept_landed == ["research/2026-01-01-0000"]
        assert result.reasons == {"research/2026-01-02-0000": "cap"}

    def test_negative_keep_last_rejected(self, tmp_path: Path) -> None:
        vault = _make_repo(tmp_path)
        try:
            prune_research_branches(vault, keep_last=-1, dry_run=True)
        except ValueError:
            return
        raise AssertionError("expected ValueError for a negative keep_last")


class TestAgainstRealVaultCommit:
    """Proves the landing-marker grep matches what vault_commit actually writes.

    Uses the real begin_run / commit_cycle / complete_run flow (spec 072's
    rc=1 constrained-exit path — same one test_vault_commit.py's
    test_rc1_constrained_lands_on_main_and_retains_branch drives) rather
    than a hand-rolled commit message.
    """

    def _make_vault(self, tmp_path: Path) -> Path:
        return _make_repo(tmp_path)

    def _write_note(self, vault: Path, name: str) -> None:
        notes = vault / "data_vault"
        notes.mkdir(exist_ok=True)
        (notes / name).write_text("body\n", encoding="utf-8")

    def test_real_constrained_landing_is_recognised_as_landed(
        self, tmp_path: Path
    ) -> None:
        vault = self._make_vault(tmp_path)
        ctx = begin_run(vault, kind="research")
        self._write_note(vault, "n1.md")
        commit_cycle(vault, cycle=1, summary={"notes_added": 1}, ctx=ctx)
        result = complete_run(vault, final_rc=1, final_reason="constrained", ctx=ctx)
        assert result.ok is True
        assert result.branch_retained is True

        assert is_branch_landed(vault, ctx.branch) is True
        branches = {b.name: b.landed for b in list_research_branches(vault)}
        assert branches[ctx.branch] is True

    def test_prune_deletes_a_real_landed_branch_beyond_keep_last(
        self, tmp_path: Path
    ) -> None:
        vault = self._make_vault(tmp_path)
        ctx = begin_run(vault, kind="research")
        self._write_note(vault, "n1.md")
        commit_cycle(vault, cycle=1, summary={"notes_added": 1}, ctx=ctx)
        complete_run(vault, final_rc=1, final_reason="constrained", ctx=ctx)

        result = prune_research_branches(vault, keep_last=0, dry_run=False)
        assert result.deleted == [ctx.branch]
        assert ctx.branch not in {b.name for b in list_research_branches(vault)}
        # The content that landed on main is untouched by the branch delete.
        assert (vault / "data_vault" / "n1.md").is_file()

    def test_real_auto_merge_off_clean_run_is_never_a_candidate(
        self, tmp_path: Path
    ) -> None:
        """rc=0 under `auto_merge: false`: main gets an EMPTY pointer commit

        carrying the same `**Branch:**` line and the checkout returns to
        main — the content exists only on the branch. Pruning it would be
        data loss, so the classifier must call it unlanded at any policy.
        """
        vault = self._make_vault(tmp_path)
        _write_settings(vault, "vault_commit:\n  auto_merge: false\n")
        ctx = begin_run(vault, kind="research")
        self._write_note(vault, "n1.md")
        commit_cycle(vault, cycle=1, summary={"notes_added": 1}, ctx=ctx)
        result = complete_run(vault, final_rc=0, final_reason="clean", ctx=ctx)
        assert result.ok is True
        assert result.merged is False
        assert result.branch_retained is True
        # The premise the hazard rests on: back on main, content not there.
        head = _run("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=vault).stdout
        assert head.strip() == "main"
        assert not (vault / "data_vault" / "n1.md").exists()

        assert is_branch_landed(vault, ctx.branch) is False
        result = prune_research_branches(
            vault,
            keep_last=0,
            max_age_days=1,
            dry_run=False,
            now=datetime.now(UTC) + timedelta(days=400),
        )
        assert result.deleted == []
        assert result.kept_unlanded == [ctx.branch]
        assert ctx.branch in _branch_names(vault)


# ---------------------------------------------------------------------------
# Issue #307, owner decision D10 (2026-09-08): the policy is cap-N AND max
# age, both configurable, applied automatically at session start and after
# a run lands, with the manual verb kept. Everything below pins that policy.
# ---------------------------------------------------------------------------


def _add_landed_branch_with_tip_date(
    vault: Path, name: str, *, commit_offset: int, tip_date: str
) -> None:
    """A landed branch whose TIP commit carries an explicit committer date.

    `_add_landed_branch` points the branch at whatever `main` is at, so its
    tip is dated "now". The age rule reads the tip's committer date, so age
    tests need a branch commit with a date of their own choosing.
    """
    _run("git", "checkout", "-b", name, cwd=vault)
    (vault / f"branch-{commit_offset}.txt").write_text("y\n", encoding="utf-8")
    _run("git", "add", "-A", cwd=vault)
    env = {
        **os.environ,
        "GIT_COMMITTER_DATE": tip_date,
        "GIT_AUTHOR_DATE": tip_date,
    }
    subprocess.run(
        ["git", "commit", "-m", f"cycle {commit_offset}"],
        cwd=str(vault),
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    _run("git", "checkout", "main", cwd=vault)
    (vault / f"file-{commit_offset}.txt").write_text("x\n", encoding="utf-8")
    _run("git", "add", "-A", cwd=vault)
    message = f"research run: landed {commit_offset}\n\n**Branch:** {name}\n"
    _run("git", "commit", "-m", message, cwd=vault)


def _write_settings(vault: Path, text: str) -> None:
    (vault / "settings.yaml").write_text(text, encoding="utf-8")
    _run("git", "add", "settings.yaml", cwd=vault)
    _run("git", "commit", "-m", "test: settings", cwd=vault)


class TestRetentionPolicyLoading:
    def test_defaults_are_cap_five_and_ninety_days(self, tmp_path: Path) -> None:
        vault = _make_repo(tmp_path)
        policy = load_retention_policy(vault)
        assert policy == RetentionPolicy(keep_last=5, max_age_days=90)
        assert DEFAULT_KEEP_LAST == 5
        assert DEFAULT_MAX_AGE_DAYS == 90

    def test_reads_vault_commit_retention_block(self, tmp_path: Path) -> None:
        vault = _make_repo(tmp_path)
        _write_settings(
            vault,
            "vault_commit:\n  retention:\n    keep_last: 2\n    max_age_days: 30\n",
        )
        assert load_retention_policy(vault) == RetentionPolicy(
            keep_last=2, max_age_days=30
        )

    def test_null_disables_a_rule(self, tmp_path: Path) -> None:
        vault = _make_repo(tmp_path)
        _write_settings(
            vault,
            "vault_commit:\n  retention:\n    keep_last: null\n    max_age_days: null\n",
        )
        policy = load_retention_policy(vault)
        assert policy == RetentionPolicy(keep_last=None, max_age_days=None)
        assert policy.active is False

    def test_frontmatter_wrapped_settings_are_read(self, tmp_path: Path) -> None:
        """`vault_commit._load_settings` tolerates a `---` wrapper; so must this."""
        vault = _make_repo(tmp_path)
        _write_settings(
            vault, "---\nvault_commit:\n  retention:\n    keep_last: 1\n---\n"
        )
        assert load_retention_policy(vault).keep_last == 1

    @pytest.mark.parametrize(
        "block",
        [
            "keep_last: -1",
            "keep_last: true",
            "keep_last: five",
            "max_age_days: 0",
            "max_age_days: -3",
            "max_age_days: 1.5",
        ],
    )
    def test_invalid_values_fall_back_to_the_default_and_warn(
        self, tmp_path: Path, block: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        vault = _make_repo(tmp_path)
        _write_settings(vault, f"vault_commit:\n  retention:\n    {block}\n")
        with caplog.at_level("WARNING"):
            policy = load_retention_policy(vault)
        assert policy == RetentionPolicy()
        assert any("retention" in rec.getMessage() for rec in caplog.records)

    def test_non_mapping_block_falls_back(self, tmp_path: Path) -> None:
        vault = _make_repo(tmp_path)
        _write_settings(vault, "vault_commit:\n  retention: 5\n")
        assert load_retention_policy(vault) == RetentionPolicy()


class TestAgeRule:
    def test_landed_branch_older_than_max_age_is_pruned(self, tmp_path: Path) -> None:
        vault = _make_repo(tmp_path)
        _add_landed_branch_with_tip_date(
            vault,
            "research/2026-01-01-0000",
            commit_offset=1,
            tip_date="2026-01-01T00:00:00+00:00",
        )
        _add_landed_branch_with_tip_date(
            vault,
            "research/2026-06-01-0000",
            commit_offset=2,
            tip_date="2026-06-01T00:00:00+00:00",
        )
        now = datetime(2026, 6, 15, tzinfo=UTC)
        result = prune_research_branches(
            vault, keep_last=None, max_age_days=90, dry_run=False, now=now
        )
        assert result.deleted == ["research/2026-01-01-0000"]
        assert result.reasons == {"research/2026-01-01-0000": "age"}
        assert result.kept_landed == ["research/2026-06-01-0000"]

    def test_age_rule_never_touches_an_unlanded_branch(self, tmp_path: Path) -> None:
        vault = _make_repo(tmp_path)
        _add_unlanded_branch(vault, "research/2020-01-01-0000")
        now = datetime.now(UTC) + timedelta(days=3650)
        result = prune_research_branches(
            vault, keep_last=None, max_age_days=1, dry_run=False, now=now
        )
        assert result.deleted == []
        assert result.kept_unlanded == ["research/2020-01-01-0000"]

    def test_age_within_window_is_kept(self, tmp_path: Path) -> None:
        vault = _make_repo(tmp_path)
        _add_landed_branch(vault, "research/2026-01-01-0000", commit_offset=1)
        result = prune_research_branches(
            vault, keep_last=None, max_age_days=90, dry_run=False
        )
        assert result.deleted == []
        assert result.kept_landed == ["research/2026-01-01-0000"]

    def test_invalid_max_age_rejected(self, tmp_path: Path) -> None:
        vault = _make_repo(tmp_path)
        with pytest.raises(ValueError):
            prune_research_branches(vault, max_age_days=0, dry_run=True)


class TestCombinedPolicy:
    def test_cap_or_age_each_prunes_on_its_own(self, tmp_path: Path) -> None:
        """D10 reads as two ceilings — count AND age — each of which is enforced.

        A landed branch goes when it is beyond the newest-N window OR older
        than the age ceiling; it stays only while it satisfies both. Six
        branches, cap 5, and the newest one dated a year back: the oldest goes
        for count, the newest for age, and the reason column says which.
        """
        vault = _make_repo(tmp_path)
        for i in range(1, 6):
            _add_landed_branch(vault, f"research/2026-06-0{i}-0000", commit_offset=i)
        _add_landed_branch_with_tip_date(
            vault,
            "research/2026-06-09-0000",
            commit_offset=9,
            tip_date="2025-01-01T00:00:00+00:00",
        )
        result = prune_research_branches(
            vault, keep_last=5, max_age_days=90, dry_run=False
        )
        assert result.deleted == [
            "research/2026-06-01-0000",
            "research/2026-06-09-0000",
        ]
        assert result.reasons == {
            "research/2026-06-01-0000": "cap",
            "research/2026-06-09-0000": "age",
        }

    def test_branch_failing_both_rules_reports_both(self, tmp_path: Path) -> None:
        vault = _make_repo(tmp_path)
        _add_landed_branch_with_tip_date(
            vault,
            "research/2025-01-01-0000",
            commit_offset=1,
            tip_date="2025-01-01T00:00:00+00:00",
        )
        _add_landed_branch(vault, "research/2026-06-02-0000", commit_offset=2)
        result = prune_research_branches(
            vault, keep_last=1, max_age_days=90, dry_run=False
        )
        assert result.deleted == ["research/2025-01-01-0000"]
        assert result.reasons["research/2025-01-01-0000"] == "cap+age"

    def test_no_cap_and_no_age_prunes_nothing(self, tmp_path: Path) -> None:
        vault = _make_repo(tmp_path)
        _add_landed_branch_with_tip_date(
            vault,
            "research/2020-01-01-0000",
            commit_offset=1,
            tip_date="2020-01-01T00:00:00+00:00",
        )
        result = prune_research_branches(
            vault, keep_last=None, max_age_days=None, dry_run=False
        )
        assert result.deleted == []

    def test_checked_out_branch_is_never_a_candidate(self, tmp_path: Path) -> None:
        """git refuses to delete HEAD's branch; the policy must not even try."""
        vault = _make_repo(tmp_path)
        _add_landed_branch(vault, "research/2026-01-01-0000", commit_offset=1)
        _run("git", "checkout", "research/2026-01-01-0000", cwd=vault)
        result = prune_research_branches(vault, keep_last=0, dry_run=False)
        assert result.deleted == []
        assert result.kept_landed == ["research/2026-01-01-0000"]
        _run("git", "checkout", "main", cwd=vault)


class TestApplyRetentionPolicy:
    def test_uses_the_vault_settings_when_no_policy_is_given(
        self, tmp_path: Path
    ) -> None:
        vault = _make_repo(tmp_path)
        _write_settings(vault, "vault_commit:\n  retention:\n    keep_last: 1\n")
        _add_landed_branch(vault, "research/2026-01-01-0000", commit_offset=1)
        _add_landed_branch(vault, "research/2026-01-02-0000", commit_offset=2)
        result = apply_retention_policy(vault)
        assert result.dry_run is False
        assert result.deleted == ["research/2026-01-01-0000"]
        assert "research/2026-01-01-0000" not in {
            b.name for b in list_research_branches(vault)
        }

    def test_inactive_policy_is_a_no_op(self, tmp_path: Path) -> None:
        vault = _make_repo(tmp_path)
        _add_landed_branch(vault, "research/2026-01-01-0000", commit_offset=1)
        result = apply_retention_policy(
            vault, RetentionPolicy(keep_last=None, max_age_days=None)
        )
        assert result.deleted == []
        assert result.kept_landed == []  # never even listed
        assert "research/2026-01-01-0000" in {
            b.name for b in list_research_branches(vault)
        }

    def test_report_is_one_line_and_names_each_branch_with_its_reason(
        self, tmp_path: Path
    ) -> None:
        vault = _make_repo(tmp_path)
        _add_landed_branch(vault, "research/2026-01-01-0000", commit_offset=1)
        _add_landed_branch(vault, "research/2026-01-02-0000", commit_offset=2)
        _add_unlanded_branch(vault, "research/2026-01-03-0000")
        policy = RetentionPolicy(keep_last=1, max_age_days=90)
        result = apply_retention_policy(vault, policy)
        line = format_prune_report(result, policy)
        assert "\n" not in line
        assert "research/2026-01-01-0000 (cap)" in line
        assert "keep_last=1" in line and "max_age_days=90" in line
        assert "1 landed kept" in line and "1 unlanded kept" in line

    def test_dry_run_report_says_would(self, tmp_path: Path) -> None:
        vault = _make_repo(tmp_path)
        _add_landed_branch(vault, "research/2026-01-01-0000", commit_offset=1)
        policy = RetentionPolicy(keep_last=0, max_age_days=None)
        result = apply_retention_policy(vault, policy, dry_run=True)
        assert "would prune" in format_prune_report(result, policy)
        assert "research/2026-01-01-0000" in {
            b.name for b in list_research_branches(vault)
        }
