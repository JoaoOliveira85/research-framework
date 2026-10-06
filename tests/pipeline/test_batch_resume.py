"""Resume + idempotent replay for batched note-writer (T054, US4 / R-001 / FR-014).

Targets :func:`research_framework.pipeline.orchestrator.run_single_cycle` with
``resume=True`` once orphan batch detection (T058) lands. Today the orchestrator
does not synthesize missing ``cycle-*-batch-*.json`` files — expect RED.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.pipeline.coverage import save_targets
from research_framework.spec.schema import (
    BudgetConfig,
    CoverageCategory,
    CoverageTargets,
    DataSourceConfig,
    NoteTypeConfig,
    ScopeConfig,
    SpecConfig,
)
from tests._helpers.cycle_runner_stub import no_op_cycle_runner


def _minimal_spec(tmp: Path, *, max_cycles: int = 10) -> SpecConfig:
    cats = [
        CoverageCategory(
            name="concepts",
            note_type="concept",
            target_count=40,
            met_count=0,
            priority=60,
        )
    ]
    scope = ScopeConfig(domain="d", organization="o")
    return SpecConfig(
        name="vault",
        location=tmp,
        owner="u",
        scope=scope,
        note_types=[NoteTypeConfig(name="concept", description="", folder="c/")],
        data_sources=[DataSourceConfig(name="s", type="external", priority=2)],
        search_dimensions=["domain"],
        coverage_targets=CoverageTargets(categories=cats),
        budget=BudgetConfig(),
    )


def _write_coverage(tmp: Path, spec: SpecConfig) -> None:
    save_targets(tmp, spec.coverage_targets)


def _note_body(name: str, cycle: int) -> str:
    return (
        "---\n"
        "type: concept\n"
        f"title: {name}\n"
        "coverage_category: concepts\n"
        "source_urls:\n  - https://ex.test\n"
        "summary: summary\n"
        "lifecycle:\n"
        f"  created_at_cycle: {cycle}\n"
        "---\n\n## {name}\ncontent\n"
    )


def _write_research_json(vault: Path, cycle: int, notes: list[str]) -> None:
    p = vault / "_pipeline" / "cycles" / f"cycle-{cycle:03d}-research.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {"notes_created": notes, "notes_updated": []},
            indent=2,
        ),
        encoding="utf-8",
    )


class TestR001OrphanNotesWithoutBatchReport:
    """R-001: notes on disk + missing batch JSON → resume synthesizes batch report."""

    def test_resume_reconciles_orphan_notes_into_batch_one(
        self, tmp_path: Path, monkeypatch
    ):
        vault = tmp_path / "v"
        dv = vault / "data_vault"
        dv.mkdir(parents=True)
        (vault / "_pipeline").mkdir(parents=True)
        (vault / "_pipeline" / "research-backlog.md").write_text(
            "# backlog\n", encoding="utf-8"
        )
        spec = _minimal_spec(vault)
        _write_coverage(vault, spec)
        names = ["a-alpha.md", "b-beta.md", "c-gamma.md", "d-delta.md"]
        for n in names:
            (dv / n).write_text(_note_body(n, 1), encoding="utf-8")

        _write_research_json(vault, 1, names)

        from research_framework.pipeline.orchestrator import run_single_cycle

        run_single_cycle(
            vault,
            cycle_num=1,
            budget_cap=10.0,
            max_cycles=10,
            spec=spec,
            resume=True,
            cycle_runner=no_op_cycle_runner(),
        )

        report = vault / "_pipeline" / "cycles" / "cycle-001-batch-001.json"
        assert report.is_file(), "orphan reconciliation must write missing batch report"
        doc = json.loads(report.read_text(encoding="utf-8"))
        assert sorted(doc.get("notes_written", [])) == sorted(names)
        assert doc.get("accepted") is True

        md_paths = [
            p
            for p in dv.glob("*.md")
            if p.name not in ("_index.md", "_concepts.md", "_graph.md")
        ]
        assert len(md_paths) == len(names)
        assert len({p.name for p in md_paths}) == len(names)


class TestFr014CrashMidBatch:
    """Crash after some notes from the batch hit ``data_vault/`` but before batch JSON."""

    def test_mid_batch_crash_no_duplicate_notes_on_resume(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        vault = tmp_path / "v"
        dv = vault / "data_vault"
        dv.mkdir(parents=True)
        (vault / "_pipeline").mkdir(parents=True)
        (vault / "_pipeline" / "research-backlog.md").write_text(
            "#b\n", encoding="utf-8"
        )
        spec = _minimal_spec(vault)
        _write_coverage(vault, spec)
        partial = ["mid-a.md", "mid-b.md"]
        for n in partial:
            (dv / n).write_text(_note_body(n, 1), encoding="utf-8")
        _write_research_json(vault, 1, partial)

        from research_framework.pipeline.orchestrator import run_single_cycle

        run_single_cycle(
            vault,
            1,
            budget_cap=10.0,
            max_cycles=10,
            spec=spec,
            resume=True,
            cycle_runner=no_op_cycle_runner(),
        )
        assert (vault / "_pipeline" / "cycles" / "cycle-001-batch-001.json").is_file()
        before = {p.name for p in dv.glob("*.md")}
        run_single_cycle(
            vault,
            1,
            budget_cap=10.0,
            max_cycles=10,
            spec=spec,
            resume=True,
            cycle_runner=no_op_cycle_runner(),
        )
        after = {p.name for p in dv.glob("*.md")}
        assert before == after


class TestFr014CrashBetweenBatches:
    """Crash after batch-001 accepted on disk but before batch-002 starts."""

    def test_between_batches_preserves_retry_count_and_accepted_batch_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        vault = tmp_path / "v"
        dv = vault / "data_vault"
        dv.mkdir(parents=True)
        cyc = vault / "_pipeline" / "cycles"
        cyc.mkdir(parents=True)
        (vault / "_pipeline" / "research-backlog.md").write_text(
            "#b\n", encoding="utf-8"
        )
        spec = _minimal_spec(vault)
        _write_coverage(vault, spec)

        for fn in ("keep-1.md", "keep-2.md"):
            (dv / fn).write_text(_note_body(fn, 1), encoding="utf-8")
        batch1 = {
            "schema_version": "1",
            "cycle_number": 1,
            "batch_number": 1,
            "started_at": "2026-05-15T10:00:00Z",
            "finished_at": "2026-05-15T10:05:00Z",
            "topics": [
                {
                    "title": f"t{i}",
                    "category": "concepts",
                    "priority_score": 0.5,
                    "provenance": "spec_gap",
                }
                for i in range(3)
            ],
            "notes_written": ["keep-1.md", "keep-2.md"],
            "skipped_topics": [],
            "sg_gate_results": [],
            "accepted": True,
            "correction_directive_in": "",
        }
        (cyc / "cycle-001-batch-001.json").write_text(
            json.dumps(batch1), encoding="utf-8"
        )
        _write_research_json(vault, 1, ["keep-1.md", "keep-2.md"])
        (cyc / "cycle-001-retry-state.json").write_text(
            json.dumps({"retry_count": 0, "aborted": False, "abort_reason": ""}),
            encoding="utf-8",
        )

        from research_framework.pipeline.orchestrator import run_single_cycle

        run_single_cycle(
            vault,
            1,
            budget_cap=10.0,
            max_cycles=10,
            spec=spec,
            resume=True,
            cycle_runner=no_op_cycle_runner(),
        )
        retry_path = cyc / "cycle-001-retry-state.json"
        st = json.loads(retry_path.read_text(encoding="utf-8"))
        assert int(st.get("retry_count", -1)) == 0
        b1 = json.loads((cyc / "cycle-001-batch-001.json").read_text(encoding="utf-8"))
        assert b1.get("accepted") is True


class TestFr014CrashAfterCgFailRetryOne:
    """Quality report already written mid-retry; resume must not reset gate memory."""

    def test_pre_crash_quality_report_preserved_when_resuming(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        vault = tmp_path / "v"
        (vault / "data_vault").mkdir(parents=True)
        cyc = vault / "_pipeline" / "cycles"
        cyc.mkdir(parents=True)
        (vault / "_pipeline" / "research-backlog.md").write_text(
            "#b\n", encoding="utf-8"
        )
        spec = _minimal_spec(vault)
        _write_coverage(vault, spec)
        _write_research_json(vault, 1, [])

        qr = {
            "schema_version": "1",
            "cycle_number": 1,
            "framework_version": "0.2.18",
            "generated_at": "2026-05-15T12:00:00Z",
            "cycle_started_at": "2026-05-15T11:00:00Z",
            "cycle_finished_at": "2026-05-15T11:30:00Z",
            "gates": {},
            "coverage_snapshot": {},
            "notes_written": 0,
            "notes_accepted": 0,
            "notes_rejected": 0,
            "batches": [],
            "queryability_score": 0,
            "queryability_trajectory": "stable",
            "degraded_sources": [],
            "retry_count": 1,
            "aborted": False,
        }
        (cyc / "cycle-001-quality-report.json").write_text(
            json.dumps(qr), encoding="utf-8"
        )
        (cyc / "cycle-001-retry-state.json").write_text(
            json.dumps({"retry_count": 1, "aborted": False, "abort_reason": ""}),
            encoding="utf-8",
        )

        from research_framework.pipeline.orchestrator import run_single_cycle

        run_single_cycle(
            vault,
            1,
            budget_cap=10.0,
            max_cycles=10,
            spec=spec,
            resume=True,
            cycle_runner=no_op_cycle_runner(),
        )
        loaded = json.loads(
            (cyc / "cycle-001-quality-report.json").read_text(encoding="utf-8")
        )
        assert int(loaded.get("retry_count", 0)) == 1
