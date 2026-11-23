"""Spec 084 FR-014: the loop's continuation trigger is this cycle's harvest
manifest, never the backlog store."""

from __future__ import annotations

import json
from pathlib import Path

from research_framework.pipeline import backlog
from research_framework.pipeline import state_layout as L
from research_framework.pipeline.coverage import save_targets
from research_framework.spec.schema import CoverageCategory, CoverageTargets

from .test_quarantine_ordering import _budget, _make_vault, _spec


def _open_entries(vault: Path) -> None:
    def _fill(tx: backlog.Transaction) -> None:
        for n in range(5):
            tx.observe_topic(
                cycle=1,
                title=f"Topic {n}",
                origin="harvest",
                citation_count=3,
                cited_from=["data_vault/a.md"],
            )

    assert backlog.update(vault, "harvest", _fill)


def test_continuation_reads_the_harvest_manifest_not_the_store(
    tmp_path: Path, monkeypatch
) -> None:
    from research_framework.pipeline import orchestrator as orch

    vault = _make_vault(tmp_path)
    save_targets(
        vault,
        CoverageTargets(
            categories=[
                CoverageCategory(
                    name="concepts", note_type="concept", target_count=1, met_count=1
                )
            ]
        ),
    )
    _open_entries(vault)
    cycles = vault / "_pipeline" / "cycles"
    cycles.mkdir(parents=True, exist_ok=True)
    ran: list[int] = []

    def fake_run_single_cycle(vault_dir, cycle_num, *args, **kwargs):
        ran.append(cycle_num)
        (cycles / f"cycle-{cycle_num:03d}-harvest.json").write_text(
            json.dumps({"cycle": cycle_num, "followups": [], "coverage_gaps": []}),
            encoding="utf-8",
        )
        return 0

    monkeypatch.setattr(orch, "run_single_cycle", fake_run_single_cycle)
    monkeypatch.setattr(orch, "merge_expected_filenames_from_scan", lambda _v: None)
    monkeypatch.setattr(orch, "_run_health_gate", lambda _v: [])
    monkeypatch.setattr(orch, "_scout_new_topics", lambda _v, _c: [])
    monkeypatch.setattr(orch, "scan_stubs", lambda _v, _s: [])

    rc = orch.run_cycles(_spec(vault), vault, budget=_budget(max_cycles=3))

    # Five open entries in the store, none in this cycle's manifest: no fuel,
    # coverage met, so the run completes after one cycle.
    assert rc == 0
    assert ran == [1]
    assert len(backlog.planner_topics(vault)) == 5
    assert L.research_backlog_path(vault).is_file()
