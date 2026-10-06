"""Cost efficiency quality metric tests (spec 033 US3/US4)."""

from __future__ import annotations

import json
from pathlib import Path

from research_framework.pipeline.steps._types import ResearchResult
from research_framework.quality.metrics import REGISTERED_METRIC_FAMILIES
from research_framework.quality.metrics.cost_efficiency import (
    compute_cost_per_substantive_note,
    compute_source_cache_hit_ratio,
    cost_per_substantive_note_regression_verdict,
)
from research_framework.quality.models import CycleOutput, Fixture

_FIXTURE_VAULT = (
    Path(__file__).resolve().parents[2] / "fixtures" / "cost_enforcement" / "vault"
)


def _fixture() -> Fixture:
    return Fixture(
        name="cost-fixture",
        vault_dir=_FIXTURE_VAULT,
        spec_path=_FIXTURE_VAULT / "research.spec.md",
        settings_path=_FIXTURE_VAULT / "settings.yaml",
        coverage_targets_path=_FIXTURE_VAULT / "coverage-targets.json",
        fake_agent_responses_dir=_FIXTURE_VAULT / "fake_agent_responses",
        note_count_target=1,
        failure_mode="test",
    )


def test_compute_cost_per_substantive_note_deterministic(tmp_path: Path) -> None:
    import shutil

    vault = tmp_path / "vault"
    shutil.copytree(_FIXTURE_VAULT, vault)
    outputs = [
        CycleOutput(
            fixture_name="cost-fixture",
            cycle_number=1,
            exit_code=0,
            quality_report_path=_FIXTURE_VAULT / "q.json",
            research_report_path=_FIXTURE_VAULT / "r.json",
            notes_written=[_FIXTURE_VAULT / "note.md"],
        )
    ]
    fixture = Fixture(
        name="cost-fixture",
        vault_dir=vault,
        spec_path=vault / "research.spec.md",
        settings_path=vault / "settings.yaml",
        coverage_targets_path=vault / "coverage-targets.json",
        fake_agent_responses_dir=vault / "fake_agent_responses",
        note_count_target=1,
        failure_mode="test",
    )
    result = compute_cost_per_substantive_note(fixture, outputs)
    assert result["cost_per_substantive_note"] > 0
    assert result["substantive_notes"] == 1


def _runner_shaped_output(
    notes: list[Path], *, cycle_number: int = 1, vault: Path
) -> CycleOutput:
    """A ``CycleOutput`` in the shape ``runner._invoke_cycles`` actually builds.

    ``notes_written`` is derived FROM ``research_result.notes_written`` there, so
    the two fields always name the same files. The old unit fixture populated
    only the former — the one shape the harness never produces.
    """
    return CycleOutput(
        fixture_name="cost-fixture",
        cycle_number=cycle_number,
        exit_code=0,
        quality_report_path=vault / "q.json",
        research_report_path=vault / "r.json",
        notes_written=list(notes),
        research_result=ResearchResult(
            notes_written=list(notes),
            notes_rejected=[],
            duration_ms=0,
            cost_usd=0.0,
            raw_json_path=vault / "r.json",
        ),
    )


def test_substantive_notes_counts_each_note_once_on_the_runner_shape(
    tmp_path: Path,
) -> None:
    """Issue #294: the two note lists are the same list — count them once.

    Three notes written in one cycle must read ``substantive_notes == 3``. The
    pre-fix code summed both fields and reported 6, halving the metric.
    """
    import shutil

    vault = tmp_path / "vault"
    shutil.copytree(_FIXTURE_VAULT, vault)
    notes = [vault / f"note-{i}.md" for i in range(1, 4)]
    fixture = Fixture(
        name="cost-fixture",
        vault_dir=vault,
        spec_path=vault / "research.spec.md",
        settings_path=vault / "settings.yaml",
        coverage_targets_path=vault / "coverage-targets.json",
        fake_agent_responses_dir=vault / "fake_agent_responses",
        note_count_target=3,
        failure_mode="test",
    )
    outputs = [_runner_shaped_output(notes, vault=vault)]

    result = compute_cost_per_substantive_note(fixture, outputs)

    assert result["substantive_notes"] == 3
    # Hand-computable: the fixture's cycle-1 sidecars sum to a known cost, and
    # the metric is that sum over exactly three notes.
    assert result["cost_per_substantive_note"] == round(result["cost_sum_usd"] / 3, 4)


def test_substantive_notes_dedupe_a_note_rewritten_in_a_later_cycle(
    tmp_path: Path,
) -> None:
    """A note re-written in cycle 2 is one substantive note, not two."""
    import shutil

    vault = tmp_path / "vault"
    shutil.copytree(_FIXTURE_VAULT, vault)
    shared = vault / "shared.md"
    fixture = Fixture(
        name="cost-fixture",
        vault_dir=vault,
        spec_path=vault / "research.spec.md",
        settings_path=vault / "settings.yaml",
        coverage_targets_path=vault / "coverage-targets.json",
        fake_agent_responses_dir=vault / "fake_agent_responses",
        note_count_target=2,
        failure_mode="test",
    )
    outputs = [
        _runner_shaped_output([shared, vault / "only-cycle-1.md"], vault=vault),
        _runner_shaped_output([shared], cycle_number=2, vault=vault),
    ]

    result = compute_cost_per_substantive_note(fixture, outputs)

    assert result["substantive_notes"] == 2


def test_cost_per_substantive_note_regression_gate_fails_over_15_percent() -> None:
    assert cost_per_substantive_note_regression_verdict(0.40, 0.65) == "fail"
    assert cost_per_substantive_note_regression_verdict(0.40, 0.42) == "pass"


def test_cost_efficiency_metric_registered_in_quality_runner() -> None:
    names = [f.name for f in REGISTERED_METRIC_FAMILIES]
    assert "cost_efficiency" in names


def test_source_cache_hit_ratio_returns_na_without_020_cache(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    fixture = Fixture(
        name="x",
        vault_dir=vault,
        spec_path=vault / "research.spec.md",
        settings_path=vault / "settings.yaml",
        coverage_targets_path=vault / "coverage-targets.json",
        fake_agent_responses_dir=vault / "fake",
        note_count_target=1,
        failure_mode="test",
    )
    out = compute_source_cache_hit_ratio(fixture, [])
    assert out == {"status": "na", "reason": "020_not_present"}


def test_source_cache_hit_ratio_warns_below_80_percent(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    mod = vault / "_pipeline/sources/youtube"
    mod.mkdir(parents=True)
    (mod / "stats.json").write_text(
        json.dumps({"cache_hits": 3, "cache_misses": 1}),
        encoding="utf-8",
    )
    fixture = Fixture(
        name="x",
        vault_dir=vault,
        spec_path=vault / "research.spec.md",
        settings_path=vault / "settings.yaml",
        coverage_targets_path=vault / "coverage-targets.json",
        fake_agent_responses_dir=vault / "fake",
        note_count_target=1,
        failure_mode="test",
    )
    out = compute_source_cache_hit_ratio(fixture, [])
    assert out.get("warning") == "cache_hit_ratio_below_80_percent"
    assert out.get("source_cache_hit_ratio") == out.get("cache_hit_ratio")
