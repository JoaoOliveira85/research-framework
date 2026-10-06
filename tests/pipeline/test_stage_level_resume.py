"""Stage-level resume after a budget pause (issue #235).

``paused_stage`` was written into every ``BUDGET_PAUSED`` marker and read by
nobody, so budget-marker.contract.md §4.5's "continue cycle from
``paused_stage``" was a promise with no implementation: a cycle that paused at
the note-writer re-ran scout on resume and paid for it a second time — the
exact spend the caps exist to prevent.

These tests pin the two halves: the stage → phase mapping, and the runner
actually skipping the phases that already ran.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from research_framework.pipeline.cycle_runner import (
    arm_stage_resume,
    run_cycle_steps,
)
from tests.pipeline.test_cycle_runner import (
    _make_vault,
    _patch_cycle_runner_subprocess,
)


@pytest.fixture(autouse=True)
def _no_leaked_arming() -> object:
    """A plan armed by one test must never reach another (or another cycle)."""
    from research_framework.pipeline import cycle_runner

    cycle_runner._pending_stage_resume.clear()
    yield
    cycle_runner._pending_stage_resume.clear()


def _prepare(vault: Path, cycle: int = 1) -> Path:
    """Seed the on-disk artifacts an already-started cycle would have left."""
    pipeline = vault / "_pipeline"
    (pipeline / "vault-metrics.json").write_text("{}", encoding="utf-8")
    cycles = pipeline / "cycles"
    (cycles / f"cycle-{cycle:03d}-scout.json").write_text(
        '{"topics_found": {"new": [{"title": "Already scouted"}], '
        '"existing": []}, "cost_estimate_usd": 1.25}',
        encoding="utf-8",
    )
    (cycles / f"cycle-{cycle:03d}-research.json").write_text(
        '{"notes_created": []}', encoding="utf-8"
    )
    return cycles


def _run_recording_stages(vault: Path, cycle: int = 1) -> tuple[list[str], int]:
    """Run one cycle, returning every ``agent_call.py --stage`` dispatched."""
    stages: list[str] = []
    pipeline = vault / "_pipeline"
    cycles = pipeline / "cycles"

    def _fake_run(cmd, **kwargs):
        script = Path(cmd[1]).name if len(cmd) > 1 else ""
        if script == "vault_metrics.py":
            (pipeline / "vault-metrics.json").write_text("{}", encoding="utf-8")
        if script == "agent_call.py" and "--stage" in cmd:
            stage = cmd[cmd.index("--stage") + 1]
            stages.append(stage)
            if stage == "scout":
                (cycles / f"cycle-{cycle:03d}-scout.json").write_text(
                    '{"topics_found": {"new": [], "existing": []}, '
                    '"cost_estimate_usd": 0}',
                    encoding="utf-8",
                )
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b"{}"
        return mock

    with _patch_cycle_runner_subprocess(_fake_run):
        rc = run_cycle_steps(vault, cycle)
    return stages, rc


def test_unarmed_cycle_dispatches_scout_as_before(tmp_path: Path) -> None:
    """The baseline this fix must not disturb: no marker ⇒ the full cycle."""
    vault = _make_vault(tmp_path)
    _prepare(vault)
    stages, rc = _run_recording_stages(vault)
    assert rc == 0
    assert "scout" in stages


def test_resume_armed_at_note_writer_does_not_re_dispatch_scout(
    tmp_path: Path,
) -> None:
    """§4.5: the paid-for scout is not paid for twice."""
    vault = _make_vault(tmp_path)
    _prepare(vault)
    assert arm_stage_resume(1, "note_writer") == "research"
    stages, rc = _run_recording_stages(vault)
    assert rc == 0
    assert "scout" not in stages
    assert "note_writer" in stages


def test_resume_armed_at_verifier_also_starts_at_the_research_phase(
    tmp_path: Path,
) -> None:
    """``verifier`` dispatches from inside the research phase (step 3b)."""
    vault = _make_vault(tmp_path)
    _prepare(vault)
    assert arm_stage_resume(1, "verifier") == "research"
    stages, _ = _run_recording_stages(vault)
    assert "scout" not in stages


def test_resume_armed_at_scout_still_runs_scout(tmp_path: Path) -> None:
    """A pause BEFORE the scout dispatch means nothing was paid for yet."""
    vault = _make_vault(tmp_path)
    _prepare(vault)
    assert arm_stage_resume(1, "scout") == "scout"
    stages, _ = _run_recording_stages(vault)
    assert "scout" in stages


def test_an_unmapped_stage_falls_back_to_the_full_cycle(tmp_path: Path) -> None:
    """Fail safe, not cheap: an unknown stage re-runs rather than skipping blind.

    Skipping a phase on a stage name this build does not recognise would
    silently drop work; re-running it only costs money, and says so.
    """
    vault = _make_vault(tmp_path)
    _prepare(vault)
    assert arm_stage_resume(1, "some_future_stage") is None
    stages, _ = _run_recording_stages(vault)
    assert "scout" in stages


def test_a_skipped_scout_still_yields_the_cycles_scouted_topics(
    tmp_path: Path,
) -> None:
    """The skipped phase's result is rebuilt from its own on-disk report.

    ``run_research``/``run_postprocess`` ignore the value, but the harness and
    the cycle results stash read it, and a resumed cycle must not look like one
    that scouted nothing.
    """
    from research_framework.pipeline.cycle_runner import get_last_cycle_results

    vault = _make_vault(tmp_path)
    _prepare(vault)
    arm_stage_resume(1, "note_writer")
    _run_recording_stages(vault)
    scout_result = get_last_cycle_results(1)["scout"]
    assert [t.title for t in scout_result.topics_found] == ["Already scouted"]
    assert scout_result.exit_code == 0


def test_arming_is_single_shot(tmp_path: Path) -> None:
    """A CG-001 retry re-runs the WHOLE cycle — the skip must not repeat.

    ``_incremental_retry_after_cg_fail`` calls the runner up to three times for
    one cycle. A retry exists precisely because the cycle produced too little,
    so the second attempt must be free to scout again.
    """
    vault = _make_vault(tmp_path)
    _prepare(vault)
    arm_stage_resume(1, "note_writer")
    first, _ = _run_recording_stages(vault)
    second, _ = _run_recording_stages(vault)
    assert "scout" not in first
    assert "scout" in second


def test_arming_one_cycle_does_not_skip_another(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    _prepare(vault, cycle=2)
    arm_stage_resume(1, "note_writer")
    stages, _ = _run_recording_stages(vault, cycle=2)
    assert "scout" in stages


def test_source_extraction_is_not_re_run_when_resuming_past_it(
    tmp_path: Path,
) -> None:
    """Every phase before the paused one is already paid for, extraction too."""
    vault = _make_vault(tmp_path)
    (vault / "settings.yaml").write_text(
        "stages:\n  source_extraction:\n    enabled: true\n",
        encoding="utf-8",
    )
    (vault / "scripts" / "source_bridge.py").write_text("# stub\n")
    _prepare(vault)
    scripts: list[str] = []
    pipeline = vault / "_pipeline"

    def _fake_run(cmd, **kwargs):
        script = Path(cmd[1]).name if len(cmd) > 1 else ""
        scripts.append(script)
        if script == "vault_metrics.py":
            (pipeline / "vault-metrics.json").write_text("{}", encoding="utf-8")
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b"{}"
        return mock

    arm_stage_resume(1, "note_writer")
    with _patch_cycle_runner_subprocess(_fake_run):
        run_cycle_steps(vault, 1)
    assert "source_bridge.py" not in scripts
