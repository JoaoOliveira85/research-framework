"""Unit tests for pipeline.steps.scout.run_scout (spec 025 US6 T054)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from research_framework.pipeline.cycle_runner import _load_yaml_settings
from research_framework.pipeline.steps import CycleContext, run_scout
from tests.pipeline.test_cycle_runner import _make_vault, _patch_cycle_runner_subprocess


def _ctx(vault: Path, *, cycle_num: int = 1) -> CycleContext:
    pipeline = vault / "_pipeline"
    cycles = pipeline / "cycles"
    cycle_3 = f"{cycle_num:03d}"
    return CycleContext(
        vault_dir=vault,
        cycle_num=cycle_num,
        cycle_dir=cycles / f"cycle-{cycle_3}",
        settings=_load_yaml_settings(vault / "settings.yaml"),
        scripts_dir=vault / "scripts",
        pipeline_dir=pipeline,
        cycles_dir=cycles,
        prompts_dir=pipeline / "prompts",
        python_bin="python3",
        env={"RV_PYTHON": "python3"},
    )


def test_run_scout_happy_path(tmp_path: Path) -> None:
    """Scout step completes when agent and validator succeed."""
    vault = _make_vault(tmp_path)
    scout_path = vault / "_pipeline" / "cycles" / "cycle-001-scout.json"
    scout_doc = {
        "topics_found": {"new": ["Alpha"], "existing": [], "total": 1},
        "cost_estimate_usd": 0.05,
    }

    def _fake_run(cmd, **kwargs):
        script = Path(cmd[1]).name if len(cmd) > 1 else ""
        if (
            script == "agent_call.py"
            and "--stage" in cmd
            and cmd[cmd.index("--stage") + 1] == "scout"
        ):
            scout_path.write_text(json.dumps(scout_doc), encoding="utf-8")
        mock = MagicMock()
        mock.stdout = b""
        mock.returncode = 0 if script != "validate_cycle.py" else 0
        if script == "validate_cycle.py":
            mock.returncode = 0
        return mock

    with _patch_cycle_runner_subprocess(_fake_run):
        result = run_scout(_ctx(vault))

    assert result.exit_code == 0
    assert len(result.topics_found) == 1
    assert result.topics_found[0].title == "Alpha"
    assert result.raw_json_path.is_file()


def test_run_scout_missing_prompt_aborts(tmp_path: Path) -> None:
    """Missing scout-prompt.md yields exit code 2 (failure path)."""
    vault = _make_vault(tmp_path, scout_prompt=False)

    def _fake_run(cmd, **kwargs):
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b""
        return mock

    with _patch_cycle_runner_subprocess(_fake_run):
        result = run_scout(_ctx(vault))

    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# Step-gate recording (issue #269)
# ---------------------------------------------------------------------------


def _minimal_spec():
    """A ``SpecConfig`` the step gates accept; SG-001/SG-002 do not read it."""
    from research_framework.spec.schema import (
        BudgetConfig,
        CoverageCategory,
        CoverageTargets,
        DataSourceConfig,
        NoteTypeConfig,
        ScopeConfig,
        SpecConfig,
    )

    return SpecConfig(
        name="scout-gate-test",
        location=Path("."),
        owner="tester",
        scope=ScopeConfig(domain="d", organization="o"),
        note_types=[NoteTypeConfig(name="concept", description="", folder="concepts/")],
        data_sources=[DataSourceConfig(name="s", type="external", priority=2)],
        search_dimensions=["domain"],
        coverage_targets=CoverageTargets(
            categories=[CoverageCategory(name="x", note_type="concept", target_count=1)]
        ),
        budget=BudgetConfig(),
    )


def _scout_run_with_gates(
    vault: Path, scout_doc: dict, monkeypatch, *, unfilled: int = 5
):
    """Drive ``run_scout`` with the step gates active over *scout_doc*."""
    from research_framework.pipeline._helpers import source_signals as ss

    monkeypatch.setattr(
        ss, "_load_spec_for_scout_gates", lambda _vault: _minimal_spec()
    )
    monkeypatch.setattr(ss, "_unfilled_categories_for_gates", lambda _vault: unfilled)
    monkeypatch.setattr(ss, "_cycle_quota_for_gates", lambda _pipeline: 1)
    scout_path = vault / "_pipeline" / "cycles" / "cycle-001-scout.json"

    def _fake_run(cmd, **kwargs):
        script = Path(cmd[1]).name if len(cmd) > 1 else ""
        if (
            script == "agent_call.py"
            and "--stage" in cmd
            and cmd[cmd.index("--stage") + 1] == "scout"
        ):
            scout_path.write_text(json.dumps(scout_doc), encoding="utf-8")
        mock = MagicMock()
        mock.stdout = b""
        mock.returncode = 0
        return mock

    with _patch_cycle_runner_subprocess(_fake_run):
        return run_scout(_ctx(vault))


def test_a_gate_that_aborts_the_cycle_records_itself_as_the_failure(
    tmp_path: Path, monkeypatch
) -> None:
    """Issue #269: SG-002 FAIL aborts the cycle — and now says so.

    Before the fix ``ScoutResult.sg_trips`` was hard-coded ``[]``, so the one
    gate that stopped the cycle left no trace but an INFO log line.
    """
    from research_framework.pipeline.step_gate_log import read_step_gates

    vault = _make_vault(tmp_path)
    # Every topic in one category: SG-001 PASSes, SG-002 FAILs.
    scout_doc = {
        "topics_found": {
            "new": [
                {"title": "Alpha", "coverage_category": "services"},
                {"title": "Beta", "coverage_category": "services"},
            ],
            "existing": [],
            "total": 2,
        }
    }

    result = _scout_run_with_gates(vault, scout_doc, monkeypatch)

    assert result.exit_code == 2, "SG-002 FAIL must abort the cycle"
    trips = {t.gate_id: t.status for t in result.sg_trips}
    assert trips == {"SG-002": "FAIL"}, (
        f"the aborting gate must record itself; got {result.sg_trips}"
    )
    recorded = {
        g.gate_id: g.status for g in read_step_gates(vault / "_pipeline" / "cycles", 1)
    }
    assert recorded["SG-001"] == "PASS", "gates that ran before the abort are recorded"
    assert recorded["SG-002"] == "FAIL"
    assert "SG-003" not in recorded, "a gate the abort pre-empted is not invented"


def test_a_clean_cycle_records_its_passing_gates_and_trips_nothing(
    tmp_path: Path, monkeypatch
) -> None:
    from research_framework.pipeline.step_gate_log import read_step_gates

    vault = _make_vault(tmp_path)
    scout_doc = {
        "topics_found": {
            "new": [
                {"title": "Alpha", "coverage_category": "services"},
                {"title": "Beta", "coverage_category": "flows"},
            ],
            "existing": [],
            "total": 2,
        }
    }

    result = _scout_run_with_gates(vault, scout_doc, monkeypatch, unfilled=2)

    assert result.exit_code == 0
    assert result.sg_trips == [], "a PASS is not a trip"
    recorded = {
        g.gate_id: g.status for g in read_step_gates(vault / "_pipeline" / "cycles", 1)
    }
    assert recorded["SG-001"] == "PASS"
    assert recorded["SG-002"] == "PASS"
