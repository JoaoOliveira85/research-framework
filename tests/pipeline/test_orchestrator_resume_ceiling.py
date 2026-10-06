"""Spec 070 F5 — resuming past the cycle ceiling must say so, loudly.

Root cause of the silent `exit 1`: ``_resolve_resume_cycle`` anchors resume at
``highest_completed + 1`` (cycle 7 on a 6-cycle vault) while ``--max-cycles`` is
an **absolute ceiling**, not a count of additional cycles. ``range(7, 3 + 1)`` is
empty, so the loop body never runs and control falls straight through to
``_constrained_exit`` — which narrates entirely at ``INFO``, invisible under the
non-TTY ``WARNING`` default (``_log_level`` FR-005).

The fix does not change the exit code or the control flow: it adds an
``ERROR``-level diagnostic that survives the default log level and names the
conflict.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

import pytest

from research_framework.pipeline.coverage import save_targets
from research_framework.spec.schema import (
    BudgetConfig,
    CoverageCategory,
    CoverageTargets,
    NoteTypeConfig,
    ScopeConfig,
    SpecConfig,
)


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(args), cwd=str(cwd), check=True, capture_output=True, text=True
    )


def _current_branch(vault: Path) -> str:
    return _run("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=vault).stdout.strip()


def _branches(vault: Path) -> list[str]:
    return [
        ln.strip().lstrip("* ").strip()
        for ln in _run("git", "branch", cwd=vault).stdout.splitlines()
        if ln.strip()
    ]


def _budget(max_cycles: int):
    from research_framework.cli._budget_resolve import BudgetResolution

    return BudgetResolution(
        max_cycles=max_cycles,
        max_cycles_source="--max-cycles",
        max_usd=12.0,
        max_usd_source="--max-usd",
    )


def _spec(vault_dir: Path) -> SpecConfig:
    return SpecConfig(
        name="ceiling-test",
        location=vault_dir,
        owner="test",
        scope=ScopeConfig(domain="d", organization="o"),
        note_types=[
            NoteTypeConfig(
                name="service",
                description="d",
                folder="01 - Services",
                authoritative_role="behaviour",
            )
        ],
        data_sources=[],
        search_dimensions=["domain"],
        coverage_targets=CoverageTargets(
            categories=[
                CoverageCategory(name="services", note_type="service", target_count=3)
            ]
        ),
        budget=BudgetConfig(),
    )


def _vault_with_completed_cycles(tmp_path: Path, completed: int) -> Path:
    vault = tmp_path / "vault"
    cycles = vault / "_pipeline" / "cycles"
    cycles.mkdir(parents=True)
    for n in range(1, completed + 1):
        (cycles / f"cycle-{n:03d}-quality-report.json").write_text(json.dumps({}))
    save_targets(
        vault,
        CoverageTargets(
            categories=[
                CoverageCategory(
                    name="services", note_type="service", target_count=3, met_count=1
                )
            ]
        ),
    )
    return vault


def _git_vault_with_completed_cycles(tmp_path: Path, completed: int) -> Path:
    """Same fixture as :func:`_vault_with_completed_cycles`, but a real git
    repo — needed to exercise ``vault_commit`` (issue #250), which the
    plain fixture above skips entirely (``_ensure_repo`` is False)."""
    vault = _vault_with_completed_cycles(tmp_path, completed=completed)
    _run("git", "init", "-b", "main", cwd=vault)
    _run("git", "config", "user.email", "t@example.com", cwd=vault)
    _run("git", "config", "user.name", "T", cwd=vault)
    (vault / "README.md").write_text("# vault\n", encoding="utf-8")
    _run("git", "add", "-A", cwd=vault)
    _run("git", "commit", "-m", "initial", cwd=vault)
    return vault


def test_resume_past_ceiling_with_zero_commits_drops_the_empty_branch(
    tmp_path: Path, monkeypatch
) -> None:
    """Issue #250: this IS the spec-070 F5 path the issue names as the
    routine reproduction — a `--resume` anchored past `--max-cycles`
    returns rc=1 having run zero cycles, so `vault_commit` opened a
    `research/<ts>` branch for a run that committed nothing on it. Fixing
    only `vault_commit.complete_run` in isolation wouldn't prove the
    orchestrator actually reaches that path with an empty
    `cycle_commit_shas`; this test drives the real `run_cycles` entry
    point end to end against a real git-backed vault.
    """
    from research_framework.pipeline import orchestrator as orch

    vault = _git_vault_with_completed_cycles(tmp_path, completed=6)

    def _must_not_run(*args, **kwargs):
        raise AssertionError("range(7, 4) is empty; the loop body must not run")

    monkeypatch.setattr(orch, "run_single_cycle", _must_not_run)
    monkeypatch.setattr(orch, "merge_expected_filenames_from_scan", lambda _v: None)
    monkeypatch.setattr(orch, "_run_health_gate", lambda _v: [])

    rc = orch.run_cycles(
        _spec(vault), vault, start_cycle=7, resume=True, budget=_budget(3)
    )

    assert rc == 1, "exit code is unchanged by the branch-cleanup fix"
    assert _current_branch(vault) == "main", "operator must not be left on a branch"
    stray = [b for b in _branches(vault) if b.startswith("research/")]
    assert stray == [], f"empty research branch(es) not cleaned up: {stray}"


def test_resume_past_ceiling_logs_above_info(
    tmp_path: Path, monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The conflict must be reported at >= WARNING so a redirected run sees it."""
    from research_framework.pipeline import orchestrator as orch

    vault = _vault_with_completed_cycles(tmp_path, completed=6)

    called: list[int] = []

    def _never(*args, **kwargs):
        called.append(1)
        return 0

    monkeypatch.setattr(orch, "run_single_cycle", _never)
    monkeypatch.setattr(orch, "merge_expected_filenames_from_scan", lambda _v: None)
    monkeypatch.setattr(orch, "_run_health_gate", lambda _v: [])

    with caplog.at_level(logging.WARNING):
        rc = orch.run_cycles(
            _spec(vault), vault, start_cycle=7, resume=True, budget=_budget(3)
        )

    assert rc == 1, "exit code is unchanged — this fix is about visibility"
    assert not called, "the loop body must not run; range(7, 4) is empty"

    loud = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert loud, "F5: the empty-range fall-through emitted nothing above INFO"

    joined = " ".join(r.getMessage() for r in loud)
    assert "7" in joined and "3" in joined, (
        "the diagnostic must name both the resume anchor and the ceiling"
    )


def test_normal_resume_within_ceiling_is_not_flagged(
    tmp_path: Path, monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Regression: a resume that CAN run must not gain a spurious error."""
    from research_framework.pipeline import orchestrator as orch

    vault = _vault_with_completed_cycles(tmp_path, completed=2)
    cycles = vault / "_pipeline" / "cycles"

    def _one_cycle(
        vault_dir, cycle_num, budget_cap, max_cycles, spec=None, resume=False
    ):
        (cycles / f"cycle-{cycle_num:03d}-research.json").write_text(
            json.dumps({"notes_created": []})
        )
        (cycles / f"cycle-{cycle_num:03d}-scout.json").write_text(
            json.dumps({"topics_found": {"new": []}})
        )
        return 0

    monkeypatch.setattr(orch, "run_single_cycle", _one_cycle)
    monkeypatch.setattr(orch, "merge_expected_filenames_from_scan", lambda _v: None)
    monkeypatch.setattr(orch, "_run_health_gate", lambda _v: [])
    monkeypatch.setattr(orch, "scan_stubs", lambda _v, _s: [])

    with caplog.at_level(logging.WARNING):
        orch.run_cycles(
            _spec(vault), vault, start_cycle=3, resume=True, budget=_budget(5)
        )

    ceiling_errors = [
        r
        for r in caplog.records
        if r.levelno >= logging.ERROR and "ceiling" in r.getMessage()
    ]
    assert not ceiling_errors
