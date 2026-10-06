"""Issue #268 — the release gate must drive the cycle count it documents.

`docs/testing-strategy.md` advertises "3 fixture vaults x 3 cycles x 3 metric
families"; spec 022's plan caps a harness run at ``max_cycles: 3`` per fixture
and its data model reads ``Fixture (1) --< CycleOutput (N, one per cycle in the
harness run)``; ``tests/quality/conftest.run_fixture_cycles`` drives three. The
runner drove ONE, so `build.sh --quality` was a third of the documented gate.
"""

from __future__ import annotations

import re
from pathlib import Path

from research_framework.quality import runner as quality_runner
from research_framework.quality.determinism import canonical_json_write
from research_framework.quality.models import CurrentJSON
from research_framework.quality.runner import (
    HARNESS_BUDGET_CAP_USD,
    HARNESS_CYCLE_CEILING,
    HARNESS_MAX_CYCLES,
    resolve_fixture,
)
from tests.quality.conftest import _MAX_CYCLES

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _record_cycles(
    monkeypatch, exit_codes: dict[int, int] | None = None
) -> tuple[list[int], list[dict], object]:
    """Build the stand-in runner ``_invoke_cycles`` will be handed.

    The stub mirrors the real signature including the budget arguments: since
    issue #233 removed ``run_cycle_steps``' hardcoded ``10.0`` / ``5``, the
    harness passes its own pinned pair, and a stub that could not accept them
    would hide that.

    It is returned, not installed: the harness takes a ``cycle_runner=`` seam,
    so nothing here replaces a module global (issue #86).
    """
    seen: list[int] = []
    budgets: list[dict] = []
    codes = exit_codes or {}

    def _fake_run_cycle_steps(
        vault_dir: Path,
        cycle_num: int,
        budget_cap: float | None = None,
        max_cycles: int | None = None,
        scripts_dir: Path | None = None,
    ) -> int:
        seen.append(cycle_num)
        budgets.append({"budget_cap": budget_cap, "max_cycles": max_cycles})
        return codes.get(cycle_num, 0)

    monkeypatch.setattr(quality_runner, "get_last_cycle_results", lambda _n: {})
    return seen, budgets, _fake_run_cycle_steps


def test_the_harness_drives_three_cycles_per_fixture(monkeypatch) -> None:
    seen, _, runner = _record_cycles(monkeypatch)

    outputs, crashed = quality_runner._invoke_cycles(
        resolve_fixture("tech-lite"), cycle_runner=runner
    )

    assert crashed is False
    assert seen == [1, 2, 3]
    assert [o.cycle_number for o in outputs] == [1, 2, 3]


def test_the_harness_pins_its_own_budget_rather_than_resolving_settings(
    monkeypatch,
) -> None:
    """Issue #233: a baseline must not move when shipped settings change.

    Every other caller resolves the spec-061 ladder. A regression fixture is
    the one that must not — its numbers describe the pipeline, and a ceiling
    that came from today's ``settings.yaml`` would re-cut three baselines the
    next time someone edits one.
    """
    _, budgets, runner = _record_cycles(monkeypatch)

    quality_runner._invoke_cycles(resolve_fixture("tech-lite"), cycle_runner=runner)

    assert (
        budgets
        == [{"budget_cap": HARNESS_BUDGET_CAP_USD, "max_cycles": HARNESS_CYCLE_CEILING}]
        * HARNESS_MAX_CYCLES
    )


def test_a_cycle_aborted_by_a_gate_does_not_end_the_run(monkeypatch) -> None:
    """source-poor aborts at SG-002; its failure mode belongs on every cycle."""
    seen, _, runner = _record_cycles(monkeypatch, exit_codes={1: 2, 2: 2, 3: 2})

    outputs, crashed = quality_runner._invoke_cycles(
        resolve_fixture("source-poor"), cycle_runner=runner
    )

    assert crashed is False
    assert seen == [1, 2, 3]
    assert [o.exit_code for o in outputs] == [2, 2, 2]


def test_a_crash_stops_the_run_and_keeps_what_ran(monkeypatch) -> None:
    def _boom(vault_dir: Path, cycle_num: int, **_kwargs: object) -> int:
        if cycle_num == 2:
            raise RuntimeError("cycle runner exploded")
        return 0

    monkeypatch.setattr(quality_runner, "get_last_cycle_results", lambda _n: {})

    outputs, crashed = quality_runner._invoke_cycles(
        resolve_fixture("tech-lite"), cycle_runner=_boom
    )

    assert crashed is True
    assert [o.cycle_number for o in outputs] == [1], (
        "the cycle that did run must still reach the metrics"
    )


def _bless(current: CurrentJSON, baselines: Path) -> None:
    """Cut a throwaway baseline from *current*, as ``quality-baseline-update`` would."""
    payload = {
        "schema_version": current.schema_version,
        "fixture": current.fixture,
        "baseline_commit": "abc123",
        "last_updated": current.run_timestamp,
        "last_updated_by": "test",
        "last_updated_reason": "test baseline",
        "coverage_targets_hash": current.coverage_targets_hash,
        "metrics": current.metrics,
    }
    path = baselines / f"{current.fixture}.baseline.json"
    canonical_json_write(path, payload)


def test_a_crashed_fixture_fails_the_gate_even_when_another_fixture_ran(
    monkeypatch, tmp_path, capsys
) -> None:
    """A crash is not a measurement, so it must never be left to the metric diff.

    ``run`` exited 2 for a crashed cycle only when EVERY fixture crashed. A
    partial crash went to the diff, which books it as one failed cycle — and
    source-poor's baseline is three of them (SG-002 aborts every cycle), so a
    crash on its first cycle read as ``cycles_fail`` 3 → 1, an improvement:
    exit 0, "Verdict: PASS", and ``build.sh --quality`` built the bundle.
    """
    baselines = tmp_path / "baselines"
    out = tmp_path / "out"
    monkeypatch.setattr(quality_runner, "_BASELINES_DIR", baselines)
    monkeypatch.setattr(quality_runner, "_WORK_ROOT", tmp_path / "work")
    monkeypatch.setattr(quality_runner, "get_last_cycle_results", lambda _n: {})

    def _aborting(vault_dir: Path, cycle_num: int, **_kwargs: object) -> int:
        # What the committed fixtures do: source-poor aborts at a step gate on
        # every cycle (exit 2), the other fixture completes.
        return 2 if vault_dir.name == "source-poor" else 0

    def _crashing(vault_dir: Path, cycle_num: int, **_kwargs: object) -> int:
        if vault_dir.name == "source-poor":
            raise RuntimeError("cycle runner exploded")
        return 0

    names = ["source-poor", "tech-lite"]
    for name in names:
        current, crashed = quality_runner.collect_fixture_current(
            name, output_dir=out, cycle_runner=_aborting
        )
        assert crashed is False
        _bless(current, baselines)
    assert current.metrics["cycle_health"]["cycles_pass"] == 3
    control = quality_runner.run(
        fixtures=names, output_dir=out, color=False, cycle_runner=_aborting
    )
    assert control == 0, "the same runner that cut the baselines must pass them"
    capsys.readouterr()

    code = quality_runner.run(
        fixtures=names, output_dir=out, color=False, cycle_runner=_crashing
    )

    captured = capsys.readouterr()
    assert code == 2
    assert "HARNESS FAILED: cycle-runner-crash" in captured.err
    assert "--fixture source-poor" in captured.err
    assert "Verdict: PASS" not in captured.out


def test_the_pytest_wrapper_shares_the_runner_constant() -> None:
    """Two drivers, one number — they disagreed (3 vs 1) until #268."""
    assert _MAX_CYCLES == HARNESS_MAX_CYCLES


def test_the_testing_strategy_doc_states_the_cycle_count_the_runner_uses() -> None:
    """The doc claim and the code are the drift #268 is about; pin them together."""
    text = (_REPO_ROOT / "docs" / "testing-strategy.md").read_text(encoding="utf-8")
    match = re.search(r"\*\*(\d+) fixture vaults × (\d+) cycles", text)

    assert match is not None, "testing-strategy.md must state the harness shape"
    assert int(match.group(1)) == len(quality_runner.REGISTERED_FIXTURES)
    assert int(match.group(2)) == HARNESS_MAX_CYCLES
