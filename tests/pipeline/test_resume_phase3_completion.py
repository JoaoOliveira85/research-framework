"""H4 regression: ``cli._resume`` MUST run Phase 3 (coverage gate,
code-first gate, reindex, generate-report) when the resume run
terminates the cycle stream.

Background (spec-019 / 0.2.28):

``src/research_framework/cli.py::_cmd_generate`` (line 168-201) runs
``run_cycles`` and then a 30-line Phase 3 block: coverage gate,
``_phase3_code_first_gate``, reindex, git init, ``generate_report``.

``_resume`` (line 204-248) ONLY calls ``run_cycles`` and exits. So a
user who runs ``./generate.sh --resume`` to completion never gets:
- the coverage gate check
- the code-first gate
- index rebuild
- a final ``run-report.md`` for the resume run

This was discovered during the spec-019 code review and is the cause
of resume runs "completing" without producing the artifacts a fresh
generate would.

v0.2.28 factors a ``_run_phase3(spec, vault_dir)`` helper from
``_cmd_generate`` and calls it from ``_resume`` when the run reached
terminal state.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest import mock

import pytest


def _import_cli_helpers():
    """Import ``cli._run_phase3`` if it exists in this version of the
    codebase. v0.2.28 introduces this helper; if missing, the test
    fails RED (which is the point — TDD)."""
    cli = importlib.import_module("research_framework.cli")
    return cli


def test_run_phase3_helper_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    """v0.2.28 introduces ``_run_phase3``. Pre-v0.2.28 this fails
    AttributeError, which is the RED signal."""
    cli = _import_cli_helpers()
    assert hasattr(cli, "_run_phase3"), (
        "cli._run_phase3 helper missing — needed to share Phase 3 logic "
        "between _cmd_generate and _resume (H4 fix in spec-019)."
    )


def test_resume_invokes_phase3_when_run_cycles_returns_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When ``run_cycles`` returns 0 (success / terminated cleanly),
    ``_resume`` must invoke ``_run_phase3``. Pre-v0.2.28 it never did."""
    cli = _import_cli_helpers()
    if not hasattr(cli, "_run_phase3"):
        pytest.fail("RED: _run_phase3 helper not yet implemented (H4).")

    # Stage a minimal vault dir with the artifacts ``_resume`` reads.
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    spec_path = vault_dir / "research.spec.md"
    spec_path.write_text(
        "---\nname: t\nlocation: /tmp/x\nbudget:\n  max_usd: 10\n"
        "  max_cycles: 1\n---\n# T\n",
        encoding="utf-8",
    )
    settings_path = vault_dir / "settings.yaml"
    settings_path.write_text("cycles:\n  update_max: 1\n", encoding="utf-8")

    phase3_calls: list[tuple[object, Path]] = []

    def _fake_phase3(spec, vd):
        phase3_calls.append((spec, vd))
        return 0

    # Patch dependencies.
    monkeypatch.setattr(cli, "_run_phase3", _fake_phase3, raising=True)

    def _fake_run_cycles(spec, vd, **kwargs):
        # Simulate a terminating cycle stream — return 0 so resume
        # proceeds to Phase 3.
        return 0

    monkeypatch.setattr(
        "research_framework.pipeline.orchestrator.run_cycles",
        _fake_run_cycles,
        raising=True,
    )

    def _fake_check(vd, *, for_resume):
        return True, []

    monkeypatch.setattr(
        "research_framework.pipeline.preconditions.check",
        _fake_check,
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

    args = mock.Mock()
    args.legacy_cycle_runner = False
    args.output = vault_dir
    args.spec = spec_path
    args.cycle = 1
    args.max_cycles = None  # spec 061: None ⇒ resolve from settings
    args.max_usd = None
    args.more_cycles = None  # issue #239: same ladder, same Mock-leak trap
    args.max_usd_this_run = None

    rc = cli._resume(args)
    assert rc == 0, f"_resume should return 0 on successful terminal run; got {rc}"
    assert len(phase3_calls) == 1, (
        "_resume must call _run_phase3 exactly once after run_cycles "
        f"returns 0; got {len(phase3_calls)} calls"
    )


def test_resume_skips_phase3_when_run_cycles_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When ``run_cycles`` returns non-zero (e.g., abort mid-cycle),
    ``_resume`` must NOT run Phase 3 — the cycle stream isn't terminal.
    This preserves current safety behaviour: only finalize a clean run."""
    cli = _import_cli_helpers()
    if not hasattr(cli, "_run_phase3"):
        pytest.fail("RED: _run_phase3 helper not yet implemented (H4).")

    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    (vault_dir / "research.spec.md").write_text("# T", encoding="utf-8")
    (vault_dir / "settings.yaml").write_text(
        "cycles:\n  update_max: 1\n", encoding="utf-8"
    )

    phase3_calls: list[object] = []
    monkeypatch.setattr(
        cli, "_run_phase3", lambda *a, **k: phase3_calls.append(a) or 0, raising=True
    )
    monkeypatch.setattr(
        "research_framework.pipeline.orchestrator.run_cycles",
        lambda *a, **k: 2,  # non-zero = abort
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

    args = mock.Mock()
    args.legacy_cycle_runner = False
    args.output = vault_dir
    args.spec = vault_dir / "research.spec.md"
    args.cycle = 1
    args.max_cycles = None  # spec 061: None ⇒ resolve from settings
    args.max_usd = None
    args.more_cycles = None  # issue #239: same ladder, same Mock-leak trap
    args.max_usd_this_run = None

    rc = cli._resume(args)
    assert rc == 2, f"failed run_cycles should bubble its non-zero rc; got {rc}"
    assert phase3_calls == [], (
        f"_run_phase3 must NOT run when run_cycles failed; got {len(phase3_calls)} calls"
    )
