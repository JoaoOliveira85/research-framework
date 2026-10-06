"""Tests for src/research_framework/pipeline/orchestrator.py — feature-002 additions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.cli._budget_resolve import BudgetResolution
from research_framework.pipeline.coverage import save_targets
from research_framework.pipeline.orchestrator import _append_budget_log
from research_framework.spec.schema import (
    BudgetConfig,
    CoverageCategory,
    CoverageTargets,
    DataSourceConfig,
    NoteTypeConfig,
    RepoEnumeration,
    ScopeConfig,
    SpecConfig,
)
from tests._helpers.cycle_runner_stub import no_op_cycle_runner


def _budget(max_cycles: int, max_usd: float | None = 10.0) -> BudgetResolution:
    """Spec 061: the per-run budget now flows in via ``run_cycles(budget=...)``
    instead of mutating ``spec.budget.max_cycles`` (which no longer exists)."""
    return BudgetResolution(
        max_cycles=max_cycles,
        max_cycles_source="settings",
        max_usd=max_usd,
        max_usd_source="settings",
    )


def _cf_spec(vault_dir: Path) -> SpecConfig:
    return SpecConfig(
        name="Test CF",
        location=vault_dir,
        owner="Test",
        scope=ScopeConfig(
            domain="d",
            organization="o",
            source_of_truth_rules=["Code wins on behaviour."],
        ),
        note_types=[
            NoteTypeConfig(name="service", description="s", folder="02 - Services"),
        ],
        data_sources=[
            DataSourceConfig(
                name="GitHub repos",
                type="internal",
                priority=1,
                role="behaviour",
                repos=[
                    RepoEnumeration(
                        name="OEHK", url="https://github.com/acme-corp/oehk-service"
                    )
                ],
            ),
            DataSourceConfig(
                name="Confluence",
                type="external",
                priority=2,
                role="intent",
                required=True,
            ),
        ],
        search_dimensions=[
            "technical",
            "organizational",
            "domain",
            "market",
            "temporal",
        ],
        coverage_targets=CoverageTargets(
            categories=[
                CoverageCategory(
                    name="services",
                    note_type="service",
                    target_count=1,
                )
            ]
        ),
        budget=BudgetConfig(),
    )


def test_budget_log_appends_across_resumes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "_pipeline").mkdir(parents=True)
    _append_budget_log(
        vault,
        1,
        {
            "cost_estimate_usd": 15.0,
            "cumulative_cost_usd": 15.0,
            "notes_created": ["A.md"],
        },
    )
    _append_budget_log(
        vault,
        2,
        {
            "cost_estimate_usd": 10.0,
            "cumulative_cost_usd": 25.0,
            "notes_created": ["B.md", "C.md"],
        },
    )
    log = (vault / "_pipeline" / "budget-log.md").read_text()
    # Both cycles appear; second append didn't overwrite the first
    assert "| 1 |" in log
    assert "| 2 |" in log
    assert "15.0000" in log
    assert "25.0000" in log
    # Exactly 2 data rows
    data_rows = [
        line
        for line in log.splitlines()
        if line.startswith("| 2026") or line.startswith("| 2027")
    ]
    # Each data row starts with an ISO timestamp like "| 2026-04-17T..."
    import re as _re

    data_rows = [
        line
        for line in log.splitlines()
        if _re.match(r"^\|\s*\d{4}-\d{2}-\d{2}T", line)
    ]
    assert len(data_rows) == 2


def test_budget_log_header_matches_after_scaffold(tmp_path: Path) -> None:
    """Regression: scaffold-written header must match orchestrator row format.

    Before the fix, scaffold wrote a 4-col header (`Cycle | Phase | Cost | Total`)
    and the orchestrator appended 5-field rows under it, producing a malformed
    table that survived across resume runs.
    """
    from research_framework.generator.scaffold import scaffold

    vault = tmp_path / "vault"
    scaffold(_cf_spec(vault), vault)
    _append_budget_log(
        vault,
        1,
        {
            "cost_estimate_usd": 1.5,
            "cumulative_cost_usd": 1.5,
            "notes_created": ["A.md"],
        },
    )
    log = (vault / "_pipeline" / "budget-log.md").read_text()
    table_rows = [ln for ln in log.splitlines() if ln.startswith("|")]
    col_counts = {ln.count("|") for ln in table_rows}
    assert len(col_counts) == 1, (
        f"header and rows disagree on column count: {col_counts}\n{log}"
    )


def test_budget_log_handles_v2_report_fields(tmp_path: Path) -> None:
    """v2 reports use `budget_consumed_usd` — must still populate the log."""
    vault = tmp_path / "vault"
    (vault / "_pipeline").mkdir(parents=True)
    _append_budget_log(
        vault,
        1,
        {"budget_consumed_usd": 42.5, "notes_created": ["X.md"]},
    )
    log = (vault / "_pipeline" / "budget-log.md").read_text()
    assert "42.5000" in log


def test_budget_log_prefers_cost_sidecars(tmp_path: Path) -> None:
    """When per-stage cost sidecars exist, they win over the agent's
    self-reported `cost_estimate_usd` (which is often 0 because the
    skill doesn't know its own cost). Fix for the always-$0 budget log
    seen across test-vault-0.2.5..0.2.13.
    """
    vault = tmp_path / "vault"
    cycles = vault / "_pipeline" / "cycles"
    cycles.mkdir(parents=True)
    calls = cycles / "cycle-001" / "agent-calls"
    calls.mkdir(parents=True)
    (calls / "scout.json").write_text(
        '{"schema_version": "1.1", "cost_usd": 0.7}', encoding="utf-8"
    )
    (calls / "note_writer-batch-1.json").write_text(
        '{"schema_version": "1.1", "cost_usd": 1.3}', encoding="utf-8"
    )
    _append_budget_log(
        vault,
        1,
        {"cost_estimate_usd": 0.0, "notes_created": ["A.md"]},
    )
    log = (vault / "_pipeline" / "budget-log.md").read_text()
    assert "2.0000" in log, log


def test_budget_log_cumulative_sums_prior_cycle_sidecars(tmp_path: Path) -> None:
    """Cumulative cost is the sum of every cycle's sidecar totals up to
    and including the current cycle — so a resume run starting at cycle
    3 still picks up cycles 1+2 from disk."""
    vault = tmp_path / "vault"
    cycles = vault / "_pipeline" / "cycles"
    cycles.mkdir(parents=True)
    for n, cost in [(1, 0.5), (2, 0.5), (3, 1.0)]:
        calls = cycles / f"cycle-{n:03d}" / "agent-calls"
        calls.mkdir(parents=True)
        (calls / "scout.json").write_text(
            f'{{"schema_version": "1.1", "cost_usd": {cost}}}',
            encoding="utf-8",
        )
    _append_budget_log(vault, 3, {"notes_created": []})
    log = (vault / "_pipeline" / "budget-log.md").read_text()
    # Cycle cost (cycle 3 only) = 1.0; cumulative across 1+2+3 = 2.0
    last_row = [ln for ln in log.splitlines() if ln.startswith("| 20")][-1]
    assert "1.0000" in last_row
    assert "2.0000" in last_row


def test_cycle_made_progress_reads_report(tmp_path: Path) -> None:
    """_cycle_made_progress → True when report shows created/updated notes."""
    from research_framework.pipeline.orchestrator import _cycle_made_progress

    vault = tmp_path / "vault"
    cycles = vault / "_pipeline" / "cycles"
    cycles.mkdir(parents=True)

    assert _cycle_made_progress(vault, 1) is False

    (cycles / "cycle-001-research.json").write_text(
        json.dumps({"notes_created": [], "notes_updated": []})
    )
    assert _cycle_made_progress(vault, 1) is False

    (cycles / "cycle-002-research.json").write_text(
        json.dumps({"notes_created": ["A.md"], "notes_updated": []})
    )
    assert _cycle_made_progress(vault, 2) is True

    (cycles / "cycle-003-research.json").write_text(
        json.dumps({"notes_created": [], "notes_updated": ["B.md"]})
    )
    assert _cycle_made_progress(vault, 3) is True

    (cycles / "cycle-010-research.json").write_text(
        json.dumps({"notes_created": ["C.md"], "notes_updated": []})
    )
    assert _cycle_made_progress(vault, 10) is True


# ---------------------------------------------------------------------------
# Loop continuation (constitution v1.3.0 § Principle II)
#
# The orchestrator runs another cycle whenever ANY of:
#   - latest scout's topics_found.new is non-empty
#   - cycle's harvest manifest has unresolved followups
#   - vault has stubs (Principle VIII criteria) or unresolved body wikilinks
# Successful exit only when ALL three are clear AND coverage met. Hitting
# budget/max_cycles with fuel still firing is a "constrained" exit (rc=1)
# with a punch list. No fuel + coverage unmet is "source-exhausted" (rc=1)
# with a different message.
# ---------------------------------------------------------------------------


def _write_cycle_artifacts(
    cycles_dir: Path,
    cycle: int,
    *,
    notes_created: list[str] | None = None,
    new_topics: list[str] | None = None,
    followups: list[dict] | None = None,
) -> None:
    """Helper: seed the per-cycle JSON files the new orchestrator reads to
    decide continuation. Each fake_run_single_cycle calls this so the test
    sets up exactly the fuel state the assertion needs."""
    (cycles_dir / f"cycle-{cycle:03d}-research.json").write_text(
        json.dumps({"notes_created": notes_created or [], "notes_updated": []})
    )
    (cycles_dir / f"cycle-{cycle:03d}-scout.json").write_text(
        json.dumps({"topics_found": {"new": new_topics or []}})
    )
    if followups is not None:
        (cycles_dir / f"cycle-{cycle:03d}-harvest.json").write_text(
            json.dumps({"followups": followups})
        )


def test_run_cycles_continues_while_scout_finds_new_topics(
    tmp_path: Path, monkeypatch
) -> None:
    """Each cycle's scout flags 1+ new topic — orchestrator keeps looping
    until max_cycles trips. Constrained exit, not source-exhausted."""
    from research_framework.pipeline import orchestrator as orch

    vault = tmp_path / "vault"
    cycles = vault / "_pipeline" / "cycles"
    cycles.mkdir(parents=True)

    save_targets(
        vault,
        CoverageTargets(
            categories=[
                CoverageCategory(
                    name="services",
                    note_type="service",
                    target_count=3,
                    met_count=1,
                )
            ]
        ),
    )

    spec = _cf_spec(vault)
    budget = _budget(3)

    calls: list[int] = []

    def fake_run_single_cycle(
        vault_dir,
        cycle_num,
        budget_cap,
        max_cycles,
        spec=None,
        resume=False,
    ):
        calls.append(cycle_num)
        _write_cycle_artifacts(
            cycles,
            cycle_num,
            notes_created=[f"Note{cycle_num}.md"],
            new_topics=[f"NewTopic{cycle_num}"],
        )
        return 0

    monkeypatch.setattr(orch, "run_single_cycle", fake_run_single_cycle)
    monkeypatch.setattr(orch, "merge_expected_filenames_from_scan", lambda _v: None)
    monkeypatch.setattr(orch, "_run_health_gate", lambda _v: [])

    rc = orch.run_cycles(spec, vault, budget=budget)
    assert rc == 1  # constrained exit (max_cycles trip with fuel left)
    assert calls == [1, 2, 3]


def test_run_cycles_continues_while_harvest_has_followups(
    tmp_path: Path, monkeypatch
) -> None:
    """Scout finds nothing new but topic_harvest left followups → continue.
    Stubs/orphans being fuel even when scout went quiet is the core of the
    v1.3.0 reframe."""
    from research_framework.pipeline import orchestrator as orch

    vault = tmp_path / "vault"
    cycles = vault / "_pipeline" / "cycles"
    cycles.mkdir(parents=True)

    save_targets(
        vault,
        CoverageTargets(
            categories=[
                CoverageCategory(
                    name="services",
                    note_type="service",
                    target_count=1,
                    met_count=1,
                )
            ]
        ),
    )

    spec = _cf_spec(vault)
    budget = _budget(2)

    calls: list[int] = []

    def fake_run_single_cycle(
        vault_dir,
        cycle_num,
        budget_cap,
        max_cycles,
        spec=None,
        resume=False,
    ):
        calls.append(cycle_num)
        # No new scout topics; coverage is already met. Only the followup
        # entry should keep the loop alive.
        _write_cycle_artifacts(
            cycles,
            cycle_num,
            notes_created=[],
            new_topics=[],
            # Single-citation followup so it doesn't auto-promote into a
            # new coverage target — we want to verify the followup itself
            # keeps the loop going.
            followups=[{"title": f"Orphan-{cycle_num}", "citation_count": 1}],
        )
        return 0

    monkeypatch.setattr(orch, "run_single_cycle", fake_run_single_cycle)
    monkeypatch.setattr(orch, "merge_expected_filenames_from_scan", lambda _v: None)
    monkeypatch.setattr(orch, "_run_health_gate", lambda _v: [])

    rc = orch.run_cycles(spec, vault, budget=budget)
    assert rc == 1  # constrained: max_cycles tripped with backlog left
    assert calls == [1, 2]


def test_run_cycles_succeeds_when_no_fuel_and_coverage_met(
    tmp_path: Path, monkeypatch
) -> None:
    """All three triggers clear AND coverage met → rc=0 (Phase 3 unlocked)."""
    from research_framework.pipeline import orchestrator as orch

    vault = tmp_path / "vault"
    cycles = vault / "_pipeline" / "cycles"
    cycles.mkdir(parents=True)
    (vault / "data_vault").mkdir()  # empty → no stubs

    save_targets(
        vault,
        CoverageTargets(
            categories=[
                CoverageCategory(
                    name="services",
                    note_type="service",
                    target_count=1,
                    met_count=1,
                )
            ]
        ),
    )

    spec = _cf_spec(vault)
    budget = _budget(5)

    calls: list[int] = []

    def fake_run_single_cycle(
        vault_dir,
        cycle_num,
        budget_cap,
        max_cycles,
        spec=None,
        resume=False,
    ):
        calls.append(cycle_num)
        _write_cycle_artifacts(
            cycles,
            cycle_num,
            notes_created=[],
            new_topics=[],
            followups=[],
        )
        return 0

    monkeypatch.setattr(orch, "run_single_cycle", fake_run_single_cycle)
    monkeypatch.setattr(orch, "merge_expected_filenames_from_scan", lambda _v: None)
    monkeypatch.setattr(orch, "_run_health_gate", lambda _v: [])

    rc = orch.run_cycles(spec, vault, budget=budget)
    assert rc == 0
    assert calls == [1]


def test_run_cycles_source_exhausted_when_no_fuel_and_coverage_unmet(
    tmp_path: Path, monkeypatch
) -> None:
    """No fuel + coverage unmet → rc=1 with a "narrow scope or add sources"
    message. Distinct from constrained exit (which fires on max_cycles)."""
    from research_framework.pipeline import orchestrator as orch

    vault = tmp_path / "vault"
    cycles = vault / "_pipeline" / "cycles"
    cycles.mkdir(parents=True)
    (vault / "data_vault").mkdir()

    save_targets(
        vault,
        CoverageTargets(
            categories=[
                CoverageCategory(
                    name="services",
                    note_type="service",
                    target_count=3,
                    met_count=0,
                )
            ]
        ),
    )

    spec = _cf_spec(vault)
    budget = _budget(5)

    calls: list[int] = []

    def fake_run_single_cycle(
        vault_dir,
        cycle_num,
        budget_cap,
        max_cycles,
        spec=None,
        resume=False,
    ):
        calls.append(cycle_num)
        _write_cycle_artifacts(
            cycles,
            cycle_num,
            notes_created=[],
            new_topics=[],
            followups=[],
        )
        return 0

    monkeypatch.setattr(orch, "run_single_cycle", fake_run_single_cycle)
    monkeypatch.setattr(orch, "merge_expected_filenames_from_scan", lambda _v: None)
    monkeypatch.setattr(orch, "_run_health_gate", lambda _v: [])

    rc = orch.run_cycles(spec, vault, budget=budget)
    assert rc == 1
    assert calls == [1]


# Auto-promotion of high-citation orphans into coverage-targets.json now
# lives in `scripts/topic_harvest.py` (called as Step 7 of the cycle runner,
# before control returns to the orchestrator). The promotion contract is
# covered by `tests/scripts/test_topic_harvest.py`.


def test_cycle_research_report_path_is_zero_padded(tmp_path: Path) -> None:
    """Regression: the orchestrator used to look up ``cycle-{n}-research.json``
    while the cycle runner writes ``cycle-{n:03d}-research.json``. The
    mismatch silently disabled coverage updates + budget logging for any
    single-digit cycle number. Lock the convention in one place."""
    from research_framework.pipeline.orchestrator import _cycle_research_report_path

    vault = tmp_path / "vault"
    assert _cycle_research_report_path(vault, 1).name == "cycle-001-research.json"
    assert _cycle_research_report_path(vault, 12).name == "cycle-012-research.json"
    assert _cycle_research_report_path(vault, 123).name == "cycle-123-research.json"


def test_render_cycle_scout_prompt_focuses_on_unmet(tmp_path: Path) -> None:
    """_render_cycle_scout_prompt pulls unmet expected_filenames into target_topics."""
    from research_framework.pipeline.orchestrator import _render_cycle_scout_prompt

    vault = tmp_path / "vault"
    (vault / "data_vault").mkdir(parents=True)
    (vault / "_pipeline" / "prompts").mkdir(parents=True)
    # Existing note — should be in exclude_topics
    (vault / "data_vault" / "ExistingNote.md").write_text("---\n---\n")
    # Coverage targets with expected_filenames (one unmet)
    save_targets(
        vault,
        CoverageTargets(
            categories=[
                CoverageCategory(
                    name="services",
                    note_type="service",
                    target_count=2,
                    met_count=0,
                    expected_filenames=["ExistingNote.md", "MissingNote.md"],
                )
            ]
        ),
    )
    _render_cycle_scout_prompt(_cf_spec(vault), vault, cycle_num=2)
    prompt = (vault / "_pipeline" / "prompts" / "scout-prompt.md").read_text()
    assert "MissingNote.md" in prompt
    # Exclude block lists the already-covered note
    assert "## Already covered" in prompt
    assert "ExistingNote.md" in prompt


def test_phase2_promoted_titles_merge_into_target_topics(tmp_path: Path) -> None:
    """Phase 2: accepted proposals from cycle N-1 should appear as target_topics
    in cycle N's scout prompt, and scope-rejected titles should appear as
    exclude_topics."""
    from research_framework.pipeline.orchestrator import _render_cycle_scout_prompt

    vault = tmp_path / "vault"
    (vault / "data_vault").mkdir(parents=True)
    (vault / "_pipeline" / "prompts").mkdir(parents=True)
    (vault / "_pipeline" / "cycles").mkdir(parents=True)
    # Cycle 1's propose manifest: one accepted proposal, one scope reject.
    (vault / "_pipeline" / "cycles" / "cycle-001-propose.json").write_text(
        '{"proposals": [{"title": "Gas Oven", "relation_type": "variant",'
        ' "parent_note": "data_vault/Oven.md", "justification": "x",'
        ' "degree": 1, "scope_check": "in_scope"}],'
        ' "rejected": [{"title": "Thermodynamics", "rejected_by": "scope_check"}]}'
    )
    # Persistent rejects file (simulates topic_propose.py's output).
    (vault / "_pipeline" / "propose-rejects.md").write_text(
        "# Persistent tangent rejections\n\n- **Thermodynamics** — cycle 001\n"
    )
    _render_cycle_scout_prompt(_cf_spec(vault), vault, cycle_num=2)
    prompt = (vault / "_pipeline" / "prompts" / "scout-prompt.md").read_text()
    assert "Gas Oven" in prompt, "auto-promoted proposal should be a target topic"
    assert "Thermodynamics" in prompt, "persistent reject should be an exclude"


def test_phase2_older_cycles_not_re_injected(tmp_path: Path) -> None:
    """Only the most recent cycle's propose manifest feeds target_topics."""
    from research_framework.pipeline.orchestrator import _phase2_promoted_titles

    vault = tmp_path / "vault"
    (vault / "_pipeline" / "cycles").mkdir(parents=True)
    (vault / "_pipeline" / "cycles" / "cycle-001-propose.json").write_text(
        '{"proposals": [{"title": "Old"}]}'
    )
    (vault / "_pipeline" / "cycles" / "cycle-002-propose.json").write_text(
        '{"proposals": [{"title": "Newer"}]}'
    )
    titles = _phase2_promoted_titles(vault, before_cycle=3)
    assert titles == ["Newer"]
    assert "Old" not in titles


def test_run_single_cycle_rerenders_on_cycle_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cycle >= 2 must trigger the scout prompt re-render even without --resume,
    so Phase 2 auto-promote can take effect in a normal (non-resume) run."""
    from research_framework.pipeline import orchestrator as orch

    vault = tmp_path / "vault"
    (vault / "scripts").mkdir(parents=True)

    calls: list[int] = []

    def _spy(spec, vault_dir, cycle_num, **kwargs):
        calls.append(cycle_num)

    monkeypatch.setattr(orch, "_render_cycle_scout_prompt", _spy)
    # The cycle itself is not under test here — only whether the scout prompt
    # is re-rendered — so it is injected, not monkeypatched (issue #86).
    no_op_cycle = no_op_cycle_runner()

    orch.run_single_cycle(
        vault,
        cycle_num=1,
        spec=_cf_spec(vault),
        resume=False,
        cycle_runner=no_op_cycle,
    )
    assert calls == []  # cycle 1 uses generate-time prompt

    orch.run_single_cycle(
        vault,
        cycle_num=2,
        spec=_cf_spec(vault),
        resume=False,
        cycle_runner=no_op_cycle,
    )
    assert calls == [2]
