"""Spec 025 US4 (A4): auto-detect --resume cycle from _pipeline/state.json."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from research_framework import cli


def _minimal_vault(tmp_path: Path) -> tuple[Path, Path]:
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    spec_path = vault_dir / "research.spec.md"
    spec_path.write_text(
        "---\nname: t\nlocation: /tmp/x\nbudget:\n  max_usd: 10\n"
        "  max_cycles: 1\n---\n# T\n",
        encoding="utf-8",
    )
    (vault_dir / "settings.yaml").write_text(
        "pipeline:\n  max_cycles: 1\n  budget_usd: 10.0\ncycles:\n  update_max: 1\n",
        encoding="utf-8",
    )
    (vault_dir / "_pipeline").mkdir(parents=True, exist_ok=True)
    return vault_dir, spec_path


def _resume_args(
    vault_dir: Path, spec_path: Path, *, cycle: int | None = None
) -> mock.Mock:
    args = mock.Mock()
    args.legacy_cycle_runner = False
    args.output = vault_dir
    args.vault_dir = vault_dir
    args.spec = spec_path
    args.cycle = cycle
    args.force_budget = False
    args.approve = None
    args.approve_all = False
    args.reject = None
    # Spec 061: resume resolves the budget from these flags (None ⇒ settings).
    # A real argparse Namespace always carries them; Mock would otherwise leak
    # a child Mock and trip the resolver's positive-int validation.
    args.max_cycles = None
    args.max_usd = None
    # Issue #239 added the two per-run spellings on the same ladder; a Mock
    # leaks a child Mock for each and trips the same validation.
    args.more_cycles = None
    args.max_usd_this_run = None
    return args


def _patch_resume_deps(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Patch _resume prerequisites; return list of start_cycle values passed to run_cycles."""
    start_cycles: list[int] = []

    def _fake_run_cycles(spec, vd, **kwargs):
        start_cycles.append(kwargs.get("start_cycle"))
        return 0

    monkeypatch.setattr(
        "research_framework.pipeline.orchestrator.run_cycles",
        _fake_run_cycles,
        raising=True,
    )
    monkeypatch.setattr(
        "research_framework.pipeline.preconditions.check",
        lambda vd, *, for_resume: (True, []),
        raising=True,
    )

    def _fake_load_spec(spec_arg, *, location):
        from types import SimpleNamespace

        return SimpleNamespace(
            name="t",
            budget=SimpleNamespace(max_usd=10, max_cycles=1),
            max_cycles=1,
        )

    monkeypatch.setattr(cli, "load_spec", _fake_load_spec, raising=True)
    monkeypatch.setattr(cli, "validate", lambda spec: None, raising=True)
    monkeypatch.setattr(cli, "_run_phase3", lambda *a, **k: 0, raising=True)
    return start_cycles


def test_resume_auto_detects_cycle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    vault_dir, spec_path = _minimal_vault(tmp_path)
    state_path = vault_dir / "_pipeline" / "state.json"
    state_path.write_text(json.dumps({"in_progress_cycle": 5}), encoding="utf-8")

    start_cycles = _patch_resume_deps(monkeypatch)
    args = _resume_args(vault_dir, spec_path, cycle=None)

    rc = cli._resume(args)
    assert rc == 0
    assert start_cycles == [5]


def test_explicit_cycle_overrides_auto(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    vault_dir, spec_path = _minimal_vault(tmp_path)
    state_path = vault_dir / "_pipeline" / "state.json"
    state_path.write_text(json.dumps({"in_progress_cycle": 5}), encoding="utf-8")

    start_cycles = _patch_resume_deps(monkeypatch)
    args = _resume_args(vault_dir, spec_path, cycle=3)

    rc = cli._resume(args)
    assert rc == 0
    assert start_cycles == [3]


def test_no_state_file_starts_at_cycle_one(tmp_path: Path) -> None:
    """Issue #150 — was ``test_no_state_file_errors_clearly``.

    A vault with no state.json and no cycles is a fresh scaffold, and
    ``--resume`` is the documented "safe to re-run" verb. Hard-erroring here
    made it hostile on the very first invocation; the rc7 validation script
    worked around it by injecting ``--cycle 1``. Cycle 1 IS the answer.
    """
    vault_dir, spec_path = _minimal_vault(tmp_path)
    args = _resume_args(vault_dir, spec_path, cycle=None)

    assert cli._resolve_resume_cycle(args) == 1


def test_corrupted_state_errors_clearly(tmp_path: Path) -> None:
    vault_dir, spec_path = _minimal_vault(tmp_path)
    state_path = vault_dir / "_pipeline" / "state.json"
    state_path.write_text("{not valid json", encoding="utf-8")
    args = _resume_args(vault_dir, spec_path, cycle=None)

    with pytest.raises(SystemExit) as exc_info:
        cli._resolve_resume_cycle(args)

    msg = str(exc_info.value)
    assert "state.json is corrupted" in msg
    assert "use --cycle <N>" in msg


def test_null_in_progress_and_no_cycles_starts_at_cycle_one(tmp_path: Path) -> None:
    """Issue #150 — was ``test_null_in_progress_errors_clearly``.

    A scaffold that wrote ``state.json`` but never ran a cycle is the same
    fresh-vault case as having no state file at all. The spec 025 A4 resolution
    ORDER is unchanged (in-progress → highest completed + 1 → …); only the final
    branch changed, from a hard error to the obvious answer. Corrupt state is
    still an error — see ``test_corrupted_state_errors_clearly``.
    """
    vault_dir, spec_path = _minimal_vault(tmp_path)
    state_path = vault_dir / "_pipeline" / "state.json"
    state_path.write_text(json.dumps({"in_progress_cycle": None}), encoding="utf-8")
    args = _resume_args(vault_dir, spec_path, cycle=None)

    assert cli._resolve_resume_cycle(args) == 1


# ---------------------------------------------------------------------------
# 0.6.1 — next-cycle fallback when state.json::in_progress_cycle is null
# but completed cycles are visible on disk. Discovered during the feeds-vault
# revival end-to-end test (post-mortem 2026-05-30): every "re-run after a
# clean cycle" tripped this because state is cleared on completion.
# ---------------------------------------------------------------------------


def _write_completed_cycle(vault_dir: Path, cycle_num: int) -> None:
    """Create the canonical "this cycle finished cleanly" artifact:
    ``cycle-NNN-quality-report.json``. Spec 023 / 0.6.2: only this
    specific file marks a cleanly-completed cycle — stray
    ``cycle-NNN/`` directories or partial state files do NOT (see
    ``test_sentinel_cycle_dirs_do_not_count``).
    """
    cycles = vault_dir / "_pipeline" / "cycles"
    cycles.mkdir(parents=True, exist_ok=True)
    (cycles / f"cycle-{cycle_num:03d}-quality-report.json").write_text(
        json.dumps({"cycle": cycle_num, "timestamp": "2026-05-31T00:00:00Z"}),
        encoding="utf-8",
    )


def test_null_in_progress_with_completed_cycles_advances_to_next(
    tmp_path: Path,
) -> None:
    """state.json::in_progress_cycle is null but cycles 1+2 are complete →
    --resume targets cycle 3 (highest completed + 1)."""
    vault_dir, spec_path = _minimal_vault(tmp_path)
    (vault_dir / "_pipeline" / "state.json").write_text(
        json.dumps({"in_progress_cycle": None}), encoding="utf-8"
    )
    _write_completed_cycle(vault_dir, 1)
    _write_completed_cycle(vault_dir, 2)

    args = _resume_args(vault_dir, spec_path, cycle=None)
    assert cli._resolve_resume_cycle(args) == 3


def test_missing_state_with_completed_cycles_advances_to_next(
    tmp_path: Path,
) -> None:
    """state.json absent but cycles on disk → still advances. Handles the
    case where a user nukes ``_pipeline/state.json`` between runs."""
    vault_dir, spec_path = _minimal_vault(tmp_path)
    _write_completed_cycle(vault_dir, 4)

    args = _resume_args(vault_dir, spec_path, cycle=None)
    assert cli._resolve_resume_cycle(args) == 5


def test_in_progress_set_takes_precedence_over_completed_cycles(
    tmp_path: Path,
) -> None:
    """If state.json points at an in-flight cycle, that wins regardless of
    what's on disk (matches spec 025 A4 contract)."""
    vault_dir, spec_path = _minimal_vault(tmp_path)
    (vault_dir / "_pipeline" / "state.json").write_text(
        json.dumps({"in_progress_cycle": 7}), encoding="utf-8"
    )
    _write_completed_cycle(vault_dir, 1)
    _write_completed_cycle(vault_dir, 2)

    args = _resume_args(vault_dir, spec_path, cycle=None)
    assert cli._resolve_resume_cycle(args) == 7


def test_highest_cycle_handles_non_contiguous_numbering(tmp_path: Path) -> None:
    """Gaps in cycle numbers (e.g. cycle 1, then cycle 5) advance from the
    highest, not the next-after-lowest."""
    vault_dir, spec_path = _minimal_vault(tmp_path)
    (vault_dir / "_pipeline" / "state.json").write_text(
        json.dumps({"in_progress_cycle": None}), encoding="utf-8"
    )
    _write_completed_cycle(vault_dir, 1)
    _write_completed_cycle(vault_dir, 5)

    args = _resume_args(vault_dir, spec_path, cycle=None)
    assert cli._resolve_resume_cycle(args) == 6


def test_sentinel_cycle_dirs_do_not_count(tmp_path: Path) -> None:
    """Stray ``cycle-NNN/`` directories without a ``cycle-NNN-quality-report.json``
    must NOT be treated as completed cycles.

    Real-world regression (post-mortem 2026-05-31 follow-up): the
    feeds-vault had a ``cycle-999/source-signals.json`` left over from a
    source_bridge sanity test. The old loose check picked up ``999`` as
    the highest cycle, resume tried to start cycle 1000, the orchestrator
    saw ``start_cycle > max_cycles`` and exited "constrained — max_cycles
    reached" without doing any work. Tightening the scan to require the
    canonical ``cycle-NNN-quality-report.json`` (atomic-written at clean
    cycle exit) fixes the trap.
    """
    vault_dir, spec_path = _minimal_vault(tmp_path)
    (vault_dir / "_pipeline" / "state.json").write_text(
        json.dumps({"in_progress_cycle": None}), encoding="utf-8"
    )
    # Real completed cycles 1-3 (canonical artifact).
    _write_completed_cycle(vault_dir, 1)
    _write_completed_cycle(vault_dir, 2)
    _write_completed_cycle(vault_dir, 3)

    # Sentinel/junk directory with a partial state file — must be
    # ignored. ``source-signals.json`` is what source_bridge writes
    # during early sanity testing; this is the exact artifact that
    # poisoned the feeds-vault.
    cycles_dir = vault_dir / "_pipeline" / "cycles"
    junk = cycles_dir / "cycle-999"
    junk.mkdir()
    (junk / "source-signals.json").write_text("{}", encoding="utf-8")

    # Other adjacent noise: a stray non-quality JSON at the cycles
    # root must also be ignored.
    (cycles_dir / "cycle-007-research.json").write_text("{}", encoding="utf-8")

    args = _resume_args(vault_dir, spec_path, cycle=None)
    assert cli._resolve_resume_cycle(args) == 4, (
        "_highest_completed_cycle picked up sentinel cycle-999/ or stray "
        "cycle-007-research.json — only cycle-NNN-quality-report.json files "
        "should count. Regression of the 2026-05-31 feeds-vault trap."
    )


def test_only_a_quality_report_marks_a_cycle_complete(tmp_path: Path) -> None:
    """A vault with a half-finished cycle (some state on disk, no
    quality report yet) should NOT advance past it on the next resume."""
    vault_dir, spec_path = _minimal_vault(tmp_path)
    (vault_dir / "_pipeline" / "state.json").write_text(
        json.dumps({"in_progress_cycle": None}), encoding="utf-8"
    )
    _write_completed_cycle(vault_dir, 1)
    _write_completed_cycle(vault_dir, 2)

    # Cycle 3 has scout + research artifacts on disk but never wrote
    # a quality report (cycle aborted mid-stream). We must NOT treat
    # it as completed.
    cycles_dir = vault_dir / "_pipeline" / "cycles"
    (cycles_dir / "cycle-003").mkdir()
    (cycles_dir / "cycle-003-scout.json").write_text("{}", encoding="utf-8")
    (cycles_dir / "cycle-003-research.json").write_text("{}", encoding="utf-8")

    args = _resume_args(vault_dir, spec_path, cycle=None)
    assert cli._resolve_resume_cycle(args) == 3, (
        "_highest_completed_cycle treated an aborted mid-stream cycle as "
        "completed — only a quality-report.json should count it."
    )
