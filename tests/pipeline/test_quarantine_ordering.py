"""Issue #155 — quarantine MUST run before the per-cycle commit.

When the verifier rewrite loop fails to clear a rejected note, the orchestrator's
quarantine sweep moves the file to ``_pipeline/quarantine/``. If that sweep runs
AFTER ``vault_commit.commit_cycle`` (the rc7 reference-vault bug), the cycle commit
captures the rejected note as ADDED while the quarantine MOVE leaves a
post-commit ` D ` entry — flunking spec 062 FR2 / ``./vault acceptance`` GA-003.

The invariant under test: after a cycle whose ``run_single_cycle`` produces a
``verifier_status: rejected`` note, ``git status`` MUST be clean (no untracked,
no uncommitted deletes), because the quarantine MOVE has been folded into the
cycle commit atom.

Surfaced live on 2026-06-13 by ``~/Documents/reference-vault-rc7/`` (umbrella #152,
sub-issue #155). The fix is a small reorder inside the orchestrator's per-cycle
commit hook: call ``_quarantine_rejected_notes`` BEFORE ``commit_cycle`` so the
git-add sweep picks up the relocation.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from research_framework.cli._budget_resolve import BudgetResolution
from research_framework.pipeline.coverage import save_targets
from research_framework.spec.schema import (
    BudgetConfig,
    CoverageCategory,
    CoverageTargets,
    DataSourceConfig,
    NoteTypeConfig,
    RepoEnumeration,
    ScopeConfig,
    SpecConfig,
)


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _git_status_porcelain(vault: Path) -> str:
    return subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(vault),
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _data_vault_dirty_entries(vault: Path) -> list[str]:
    """Return porcelain entries scoped to ``data_vault/`` (the spec 062 FR2 scope).

    GA-003's gate is data_vault/-specific. Post-finalise writes under
    ``_pipeline/`` (run-report, acceptance scorecard) are intentionally
    untracked and are NOT part of this bug — keep the assertion focused.
    """
    raw = _git_status_porcelain(vault)
    return [line for line in raw.splitlines() if line and "data_vault/" in line]


def _make_vault(tmp_path: Path) -> Path:
    """Initialise a vault as a git repo on a clean ``main``."""
    vault = tmp_path / "vault"
    vault.mkdir()
    _git("init", "-b", "main", cwd=vault)
    _git("config", "user.email", "t@e.com", cwd=vault)
    _git("config", "user.name", "T", cwd=vault)
    (vault / "README.md").write_text("# v\n", encoding="utf-8")
    (vault / "data_vault").mkdir()
    (vault / "_pipeline").mkdir()
    (vault / "data_vault" / ".gitkeep").write_text("", encoding="utf-8")
    _git("add", "-A", cwd=vault)
    _git("commit", "-m", "initial", cwd=vault)
    return vault


def _rejected_note(data_vault: Path, name: str) -> Path:
    p = data_vault / f"{name}.md"
    p.write_text(
        "---\n"
        f"title: {name}\n"
        "type: concept\n"
        "verifier_status: rejected\n"
        "verifier_notes: surfaced by issue #155 regression test\n"
        "---\n"
        "Body.\n",
        encoding="utf-8",
    )
    return p


def _accepted_note(data_vault: Path, name: str) -> Path:
    p = data_vault / f"{name}.md"
    p.write_text(
        f"---\ntitle: {name}\ntype: concept\nverifier_status: accepted\n---\nBody.\n",
        encoding="utf-8",
    )
    return p


def _spec(vault_dir: Path) -> SpecConfig:
    return SpecConfig(
        name="Test 155",
        location=vault_dir,
        owner="T",
        scope=ScopeConfig(
            domain="d",
            organization="o",
            source_of_truth_rules=["Code wins on behaviour."],
        ),
        note_types=[
            NoteTypeConfig(name="concept", description="c", folder="01 - Concepts"),
        ],
        data_sources=[
            DataSourceConfig(
                name="GH",
                type="internal",
                priority=1,
                role="behaviour",
                repos=[RepoEnumeration(name="x", url="https://github.com/x/y")],
            ),
        ],
        search_dimensions=["technical"],
        coverage_targets=CoverageTargets(
            categories=[
                CoverageCategory(
                    name="concepts",
                    note_type="concept",
                    target_count=1,
                )
            ]
        ),
        budget=BudgetConfig(),
    )


def _budget(max_cycles: int = 1) -> BudgetResolution:
    return BudgetResolution(
        max_cycles=max_cycles,
        max_cycles_source="settings",
        max_usd=10.0,
        max_usd_source="settings",
    )


def _write_cycle_artifacts_minimal(cycles_dir: Path, cycle_num: int) -> None:
    """Mirror the bits of cycle output that orchestrator continuation reads."""
    cdir = cycles_dir / f"cycle-{cycle_num:03d}"
    cdir.mkdir(parents=True, exist_ok=True)
    # Minimum the orchestrator needs to call _commit_this_cycle's summary.
    (cycles_dir / f"cycle-{cycle_num}-research.json").write_text(
        '{"notes_created": [], "expected_notes": []}\n', encoding="utf-8"
    )
    (cycles_dir / f"cycle-{cycle_num}-research-report.json").write_text(
        '{"notes_created": [], "expected_notes": []}\n', encoding="utf-8"
    )
    (cycles_dir / f"cycle-{cycle_num:03d}-summary.md").write_text(
        f"# Cycle {cycle_num}\n", encoding="utf-8"
    )


def test_rejected_note_quarantine_lands_in_cycle_commit(
    tmp_path: Path, monkeypatch
) -> None:
    """Regression for issue #155: a verifier-rejected note must be quarantined
    BEFORE the per-cycle commit so the delete is captured atomically.

    Acceptance criteria (from the issue):
      - After a cycle with verifier-rejected notes, ``git status`` shows no
        uncommitted deletes under ``data_vault/``.
      - The cycle commit includes both the new note ADDs and the quarantine
        DELETEs atomically.
    """
    from research_framework.pipeline import orchestrator as orch

    vault = _make_vault(tmp_path)
    save_targets(
        vault,
        CoverageTargets(
            categories=[
                CoverageCategory(
                    name="concepts",
                    note_type="concept",
                    target_count=1,
                    met_count=1,  # already met → loop exits after cycle 1
                )
            ]
        ),
    )
    spec = _spec(vault)
    budget = _budget(max_cycles=1)
    cycles = vault / "_pipeline" / "cycles"
    cycles.mkdir(parents=True, exist_ok=True)

    def fake_run_single_cycle(
        vault_dir,
        cycle_num,
        budget_cap,
        max_cycles,
        spec=None,
        resume=False,
    ):
        # Simulate the cycle's note-writer leaving one accepted + one rejected
        # note in data_vault/. The rejected one is exactly the rc7 symptom.
        data = vault_dir / "data_vault"
        _accepted_note(data, "Good-Note")
        _rejected_note(data, "Bad-Note")
        _write_cycle_artifacts_minimal(cycles, cycle_num)
        return 0

    monkeypatch.setattr(orch, "run_single_cycle", fake_run_single_cycle)
    monkeypatch.setattr(orch, "merge_expected_filenames_from_scan", lambda _v: None)
    monkeypatch.setattr(orch, "_run_health_gate", lambda _v: [])
    # Empty fuel so the orchestrator exits cleanly after cycle 1 instead of
    # looping (no scout/harvest seeds in this fixture).
    monkeypatch.setattr(orch, "_scout_new_topics", lambda _v, _c: [])
    monkeypatch.setattr(orch, "_harvest_followups", lambda _v, _c: [])
    monkeypatch.setattr(orch, "scan_stubs", lambda _v, _s: [])

    rc = orch.run_cycles(spec, vault, budget=budget)

    # Spec 062 FR2: no entries under ``data_vault/`` may be left dirty after
    # a cycle. Without the fix, the post-cycle quarantine MOVE leaves a
    # ` D data_vault/Bad-Note.md` (constrained / aborted exits) or — when a
    # squash-merge auto-restores the rejected note — silently leaks it into
    # ``main`` while the quarantine copy sits untracked.
    dirty_data_vault = _data_vault_dirty_entries(vault)
    assert dirty_data_vault == [], (
        f"working tree has dirty data_vault/ entries after cycle (rc={rc}): "
        f"{dirty_data_vault!r} — quarantine MOVE must run BEFORE commit_cycle"
    )

    # The HEAD tree must NOT contain the rejected note under ``data_vault/`` —
    # ``main`` may not silently end up with verifier-rejected content. The
    # quarantine copy under ``_pipeline/quarantine/`` IS allowed (we want
    # to remember what was rejected so the next cycle can rewrite it).
    tree = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "HEAD"],
        cwd=str(vault),
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "data_vault/Good-Note.md" in tree, tree
    assert "data_vault/Bad-Note.md" not in tree, (
        f"rejected note must NOT remain in indexed corpus after cycle commit: {tree}"
    )
    assert "_pipeline/quarantine/Bad-Note.md" in tree, (
        f"rejected note must be committed under quarantine/: {tree}"
    )
