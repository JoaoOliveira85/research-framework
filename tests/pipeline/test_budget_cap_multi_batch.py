"""028-SC-005: multi-batch sidecar totals feed budget-cap math (spec.budget.max_usd)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from research_framework.pipeline.orchestrator import _cumulative_sidecar_cost


def _batch_sidecar(cost: float, batch: int) -> dict:
    return {
        "schema_version": "1.1",
        "stage": "note_writer",
        "agent": "fake",
        "agent_kind": "fake",
        "tier": "standard",
        "status": "ok",
        "exit_code": 0,
        "cost_usd": cost,
        "tokens_in": 0,
        "tokens_out": 0,
        "latency_ms": 0,
        "started_at": "2000-01-01T00:00:00Z",
        "completed_at": "2000-01-01T00:00:01Z",
        "cycle": 1,
        "batch_index": batch,
    }


def test_cumulative_includes_all_batches_for_cap_check(tmp_path: Path) -> None:
    """Uses ``spec.budget.max_usd`` path (pre-033); sidecars must sum both batches."""
    vault = tmp_path / "vault"
    calls = vault / "_pipeline" / "cycles" / "cycle-001" / "agent-calls"
    calls.mkdir(parents=True)
    (calls / "note_writer-batch-1.json").write_text(
        json.dumps(_batch_sidecar(0.55, 1)), encoding="utf-8"
    )
    (calls / "note_writer-batch-2.json").write_text(
        json.dumps(_batch_sidecar(0.55, 2)), encoding="utf-8"
    )
    cumulative = _cumulative_sidecar_cost(vault, up_to=1)
    budget_cap = 1.0
    assert cumulative >= budget_cap


# ---------------------------------------------------------------------------
# The totals are only right if every dispatch's sidecar is still on disk.
# The cycle steps name the sidecar themselves — ``scout.json``,
# ``note_writer-batch-N.json`` — and every re-dispatch named the same file.
# ---------------------------------------------------------------------------


def _dispatch_recorder(vault: Path, costs: dict[str, list[float]], *, fail_first: bool):
    """A ``subprocess`` stand-in whose agent writes its cost where it is told.

    ``costs`` maps a stage to what each successive dispatch of it costs.
    ``fail_first`` makes the first scout validation a structural failure, which
    is what sends the scout round a second time inside one attempt.
    """
    from tests.pipeline.test_cycle_runner_scout_correction import (
        _write_sidecar_with_errors,
    )

    scout_report = vault / "_pipeline" / "cycles" / "cycle-001-scout.json"
    seen: dict[str, int] = {}
    validations: list[int] = []

    def _fake_run(cmd, **kwargs):
        script = Path(cmd[1]).name
        mock = MagicMock()
        mock.stdout = b""
        mock.returncode = 0
        if script == "agent_call.py":
            stage = cmd[cmd.index("--stage") + 1]
            cost = costs[stage][seen.get(stage, 0)]
            seen[stage] = seen.get(stage, 0) + 1
            sidecar = Path(cmd[cmd.index("--cost-sidecar") + 1])
            sidecar.parent.mkdir(parents=True, exist_ok=True)
            sidecar.write_text(
                json.dumps({**_batch_sidecar(cost, 1), "stage": stage}),
                encoding="utf-8",
            )
        elif script == "validate_cycle.py" and Path(cmd[2]) == scout_report:
            validations.append(1)
            if fail_first and len(validations) == 1:
                _write_sidecar_with_errors(
                    scout_report, ["required source 'x' not in sources_consulted"]
                )
                mock.returncode = 2
        return mock

    return _fake_run


def _vault_ready_for_a_cycle(tmp_path: Path) -> Path:
    from tests.pipeline.test_cycle_runner import _make_vault

    vault = _make_vault(tmp_path)
    cycles = vault / "_pipeline" / "cycles"
    (cycles / "cycle-001-scout.json").write_text('{"schema_version": "2.0"}')
    (cycles / "cycle-001-research.json").write_text("{}")
    (vault / "_pipeline" / "vault-metrics.json").write_text("{}")
    return vault


@pytest.mark.regression
def test_a_scout_retry_does_not_overwrite_the_first_dispatchs_cost(
    tmp_path: Path,
) -> None:
    """$2 scout + $3 corrected scout + $4 note-writer is $9, not $7."""
    from research_framework.pipeline.budget_guard import sum_sidecar_actuals_usd
    from research_framework.pipeline.cycle_runner import run_cycle_steps
    from tests.pipeline.test_cycle_runner import _patch_cycle_runner_subprocess

    vault = _vault_ready_for_a_cycle(tmp_path)
    fake = _dispatch_recorder(
        vault, {"scout": [2.0, 3.0], "note_writer": [4.0]}, fail_first=True
    )
    with _patch_cycle_runner_subprocess(fake):
        assert run_cycle_steps(vault, 1) == 0

    assert sum_sidecar_actuals_usd(vault, 1) == pytest.approx(9.0)
    assert _cumulative_sidecar_cost(vault, up_to=1) == pytest.approx(9.0)


@pytest.mark.regression
def test_a_second_attempt_at_a_cycle_adds_to_its_spend(tmp_path: Path) -> None:
    """A CG-001 retry, or a resumed cycle, dispatches every stage again."""
    from research_framework.pipeline.cycle_runner import run_cycle_steps
    from tests.pipeline.test_cycle_runner import _patch_cycle_runner_subprocess

    vault = _vault_ready_for_a_cycle(tmp_path)
    fake = _dispatch_recorder(
        vault, {"scout": [1.0, 1.0], "note_writer": [1.0, 1.0]}, fail_first=False
    )
    with _patch_cycle_runner_subprocess(fake):
        assert run_cycle_steps(vault, 1) == 0
        assert run_cycle_steps(vault, 1) == 0

    calls = vault / "_pipeline" / "cycles" / "cycle-001" / "agent-calls"
    assert sorted(p.name for p in calls.glob("*.json")) == [
        # The suffix goes on the stage, so a batch sidecar still ends in
        # ``-batch-N.json`` and agent_call.py still reads its batch index.
        "note_writer-2-batch-1.json",
        "note_writer-batch-1.json",
        "scout-2.json",
        "scout.json",
    ]
    assert _cumulative_sidecar_cost(vault, up_to=1) == pytest.approx(4.0)
