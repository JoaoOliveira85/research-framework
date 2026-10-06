"""Orchestrator incremental retry behaviour (T040, feature 017).

Per clarifications Q3 / FR-018: on CG-001 FAIL the orchestrator retries up to
two times without deleting notes from accepted batches; on exhaustion,
``cycle-NNN-quality-report.json`` records ``aborted=true``, ``retry_count=2``,
and a non-empty ``abort_reason``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.pipeline.coverage import save_targets
from research_framework.spec.schema import CoverageCategory, CoverageTargets


def _write_accepted_batch(
    vault: Path, *, cycle: int, batch: int, notes: list[str]
) -> None:
    cyc = vault / "_pipeline" / "cycles"
    cyc.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema_version": "1",
        "cycle_number": cycle,
        "batch_number": batch,
        "started_at": "2026-05-15T10:00:00Z",
        "finished_at": "2026-05-15T10:05:00Z",
        "topics": [
            {
                "title": f"t{i}",
                "category": "concepts",
                "priority_score": 0.4,
                "provenance": "spec_gap",
            }
            for i in range(3)
        ],
        "notes_written": notes,
        "skipped_topics": [],
        "sg_gate_results": [],
        "accepted": True,
        "correction_directive_in": "",
    }
    name = f"cycle-{cycle:03d}-batch-{batch:03d}.json"
    (cyc / name).write_text(json.dumps(doc), encoding="utf-8")


def _write_note(vault: Path, rel: str, body: str = "hello world\n") -> Path:
    p = vault / "data_vault" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    fm = (
        "---\n"
        "coverage_category: concepts\n"
        "source_urls:\n  - https://e.test\n"
        "summary: ok\n"
        "---\n\n"
    )
    p.write_text(fm + body, encoding="utf-8")
    return p


class TestIncrementalRetryPreservesAcceptedBatches:
    """Earlier accepted notes survive failed CG-001 + retries (Q3)."""

    def test_three_failed_attempts_abort_with_invariants(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dv = tmp_path / "data_vault"
        dv.mkdir(parents=True, exist_ok=True)
        cat = CoverageCategory(
            name="concepts",
            note_type="concept",
            target_count=200,
            met_count=0,
        )
        save_targets(tmp_path, CoverageTargets(categories=[cat]))
        _write_accepted_batch(
            tmp_path,
            cycle=1,
            batch=1,
            notes=["kept_alpha.md", "kept_beta.md"],
        )
        _write_note(tmp_path, "kept_alpha.md")
        _write_note(tmp_path, "kept_beta.md")

        calls: list[int] = []

        def fake_cycle_steps(
            _vault: Path, cycle_num: int, _cap: float, _max_c: int
        ) -> int:
            calls.append(cycle_num)
            report = {
                "notes_created": [],
                "notes_updated": [],
            }
            rep_path = (
                _vault / "_pipeline" / "cycles" / f"cycle-{cycle_num:03d}-research.json"
            )
            rep_path.parent.mkdir(parents=True, exist_ok=True)
            rep_path.write_text(json.dumps(report), encoding="utf-8")
            return 0

        from research_framework.pipeline.orchestrator import run_single_cycle

        rc = run_single_cycle(
            tmp_path,
            cycle_num=1,
            budget_cap=10.0,
            max_cycles=5,
            spec=None,
            cycle_runner=fake_cycle_steps,
        )
        assert rc == 2
        qr = tmp_path / "_pipeline" / "cycles" / "cycle-001-quality-report.json"
        rep = json.loads(qr.read_text(encoding="utf-8"))
        assert rep["retry_count"] == 2
        assert rep["aborted"] is True
        assert str(rep.get("abort_reason", "")).strip()
        assert (tmp_path / "data_vault" / "kept_alpha.md").is_file()
        assert (tmp_path / "data_vault" / "kept_beta.md").is_file()
        assert len(calls) == 3

    def test_retry_succeeds_when_second_attempt_meets_minimum(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dv = tmp_path / "data_vault"
        dv.mkdir(parents=True, exist_ok=True)
        cat = CoverageCategory(
            name="concepts",
            note_type="concept",
            target_count=100,
            met_count=0,
        )
        save_targets(tmp_path, CoverageTargets(categories=[cat]))

        attempt = {"n": 0}

        def fake_cycle_steps(
            vault: Path, cycle_num: int, _cap: float, _max_c: int
        ) -> int:
            attempt["n"] += 1
            n = 40 if attempt["n"] >= 2 else 0
            names = [f"note_{i}.md" for i in range(n)]
            report = {"notes_created": names, "notes_updated": []}
            rep_path = (
                vault / "_pipeline" / "cycles" / f"cycle-{cycle_num:03d}-research.json"
            )
            rep_path.parent.mkdir(parents=True, exist_ok=True)
            rep_path.write_text(json.dumps(report), encoding="utf-8")
            return 0

        from research_framework.pipeline.orchestrator import run_single_cycle

        rc = run_single_cycle(
            tmp_path, 1, 10.0, 5, spec=None, cycle_runner=fake_cycle_steps
        )
        assert rc == 0
        qr = tmp_path / "_pipeline" / "cycles" / "cycle-001-quality-report.json"
        body = json.loads(qr.read_text(encoding="utf-8"))
        assert body["aborted"] is False
        assert body["retry_count"] == 1


class TestRetryHelperSurface:
    """T048 introduces ``_incremental_retry_after_cg_fail`` on the module."""

    def test_incremental_retry_hook_symbol_exists(self) -> None:
        import research_framework.pipeline.orchestrator as orch

        getattr(orch, "_incremental_retry_after_cg_fail")


class TestTerminateShortCircuitsYieldGate:
    """rc7 cycle-1 regression (issue #158).

    A scout-TERMINATE cycle (``run_cycle_steps`` returns ``1``) produces zero
    notes BY DESIGN — the agent decided "no DFS this cycle". The CG-001
    min-cycle-yield retry must NOT treat that as a low-yield failure: retrying
    re-ran Step 0 (vault_metrics) and aborted cycle 1 with a spurious
    "cycle_runner returned structural error". TERMINATE must short-circuit the
    retry loop and propagate ``rc==1`` unchanged.

    The cycle runner is injected (not monkeypatched) per ROADMAP QW-9.
    """

    def test_terminate_returns_immediately_without_retry(self, tmp_path: Path) -> None:
        # Coverage targets that the yield gate WOULD fail on (0 notes vs a real
        # target) — proving the short-circuit fires *before* the gate, not that
        # the gate happened to pass.
        cat = CoverageCategory(
            name="concepts",
            note_type="concept",
            target_count=200,
            met_count=0,
        )
        save_targets(tmp_path, CoverageTargets(categories=[cat]))

        from research_framework.pipeline.orchestrator import (
            _incremental_retry_after_cg_fail,
        )

        calls: list[int] = []

        def fake_cycle_runner(_v: Path, cyc: int, _cap: float, _mc: int) -> int:
            calls.append(cyc)
            return 1  # TERMINATE — no DFS this cycle

        returncode, retry_count, aborted, reason = _incremental_retry_after_cg_fail(
            tmp_path,
            cycle_num=1,
            budget_cap=10.0,
            max_cycles=5,
            spec=None,
            cycle_runner=fake_cycle_runner,
        )

        assert returncode == 1
        assert retry_count == 0
        assert aborted is False
        assert reason == ""
        assert calls == [1]  # exactly one attempt — no wasteful retry

    def test_structural_error_still_aborts(self, tmp_path: Path) -> None:
        """Guard against over-correction: rc==2 must still abort immediately."""
        from research_framework.pipeline.orchestrator import (
            _incremental_retry_after_cg_fail,
        )

        calls: list[int] = []

        def fake_cycle_runner(_v: Path, cyc: int, _cap: float, _mc: int) -> int:
            calls.append(cyc)
            return 2  # structural error

        returncode, _retry, aborted, reason = _incremental_retry_after_cg_fail(
            tmp_path,
            cycle_num=1,
            budget_cap=10.0,
            max_cycles=5,
            spec=None,
            cycle_runner=fake_cycle_runner,
        )

        assert returncode == 2
        assert aborted is True
        assert "structural error" in reason
        assert calls == [1]
