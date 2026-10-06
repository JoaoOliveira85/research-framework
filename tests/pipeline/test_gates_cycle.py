"""Tests for per-cycle gates CG-001..CG-007 (T037, feature 017).

Per `spec.md` Story 9a — each gate is deterministic over vault/cycle inputs.
"""

from __future__ import annotations

from pathlib import Path

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from research_framework.pipeline.coverage import save_targets
from research_framework.spec.schema import (
    BudgetConfig,
    CoverageCategory,
    CoverageTargets,
    ScopeConfig,
    SpecConfig,
)


def _save_gap_vault(vault: Path, *, target: int, met: int) -> None:
    cat = CoverageCategory(
        name="concepts",
        note_type="concept",
        target_count=target,
        met_count=met,
    )
    save_targets(vault, CoverageTargets(categories=[cat]))


def _minimal_spec(
    *,
    forbidden: list[str],
) -> SpecConfig:
    return SpecConfig(
        name="vault",
        location=Path("."),
        owner="test",
        scope=ScopeConfig(domain="d", organization="o"),
        note_types=[],
        data_sources=[],
        search_dimensions=[],
        coverage_targets=CoverageTargets(categories=[]),
        budget=BudgetConfig(),
        forbidden_filename_prefixes=forbidden,
    )


class TestCG001MinCycleYield:
    """Notes created vs the spec-051 FR1 ``base × cadence × coverage`` target."""

    @settings(
        max_examples=80,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(
        total_unmet=st.integers(min_value=1, max_value=800),
        max_cycles=st.integers(min_value=1, max_value=30),
        cycle_number=st.integers(min_value=1, max_value=30),
    )
    def test_threshold_matches_model_and_never_below_floor(
        self,
        tmp_path: Path,
        total_unmet: int,
        max_cycles: int,
        cycle_number: int,
    ) -> None:
        # The gate's threshold IS the model's target (DRY — the model math is
        # unit-tested in test_cg001_yield_model.py) and never below floor (1).
        from research_framework.pipeline.coverage import compute_yield_target
        from research_framework.pipeline.gates_cycle import CG001_min_cycle_yield

        assume(cycle_number <= max_cycles)
        _save_gap_vault(tmp_path, target=total_unmet + 10, met=10)
        expected = compute_yield_target(tmp_path, cycle_number, max_cycles).target
        r = CG001_min_cycle_yield(
            tmp_path,
            {"notes_created": []},
            cycle_number=cycle_number,
            max_cycles=max_cycles,
        )
        assert r.gate_id == "CG-001"
        assert r.threshold == expected
        assert r.threshold >= 1

    def test_passes_when_at_or_above_target(self, tmp_path: Path) -> None:
        from research_framework.pipeline.coverage import compute_yield_target
        from research_framework.pipeline.gates_cycle import CG001_min_cycle_yield

        _save_gap_vault(tmp_path, target=100, met=0)
        need = compute_yield_target(tmp_path, cycle_number=1, max_cycles=4).target
        names = [f"n{i:03d}.md" for i in range(need)]
        r = CG001_min_cycle_yield(
            tmp_path,
            {"notes_created": names},
            cycle_number=1,
            max_cycles=4,
        )
        assert r.status == "PASS"

    def test_fails_when_zero_notes(self, tmp_path: Path) -> None:
        from research_framework.pipeline.gates_cycle import CG001_min_cycle_yield

        _save_gap_vault(tmp_path, target=50, met=0)
        r = CG001_min_cycle_yield(
            tmp_path,
            {"notes_created": []},
            cycle_number=1,
            max_cycles=5,
        )
        assert r.status == "FAIL"
        assert r.correction_hint

    def test_boundary_warn_band_near_half_expected(self, tmp_path: Path) -> None:
        from research_framework.pipeline.gates_cycle import CG001_min_cycle_yield

        _save_gap_vault(tmp_path, target=90, met=0)
        r = CG001_min_cycle_yield(
            tmp_path,
            {"notes_created": ["only-one.md"]},
            cycle_number=1,
            max_cycles=3,
        )
        assert r.status in ("WARN", "FAIL")


class TestCG002CategoryDiversity:
    """Spread of ``coverage_category`` across cycle notes."""

    def test_passes_when_enough_distinct_categories(self) -> None:
        from research_framework.pipeline.gates_cycle import CG002_category_diversity

        notes = [
            {"file": "a.md", "category": "c1"},
            {"file": "b.md", "category": "c2"},
            {"file": "c.md", "category": "c3"},
            {"file": "d.md", "category": "c4"},
            {"file": "e.md", "category": "c5"},
        ]
        r = CG002_category_diversity(notes, unfilled_categories=8)
        assert r.status == "PASS"

    def test_fails_single_category_cycle(self) -> None:
        from research_framework.pipeline.gates_cycle import CG002_category_diversity

        notes = [{"file": "a.md", "category": "only"} for _ in range(4)]
        r = CG002_category_diversity(notes, unfilled_categories=10)
        assert r.status == "FAIL"

    def test_boundary_warn_when_below_three_but_not_one(self) -> None:
        from research_framework.pipeline.gates_cycle import CG002_category_diversity

        notes = [
            {"file": "a.md", "category": "x"},
            {"file": "b.md", "category": "y"},
        ]
        r = CG002_category_diversity(notes, unfilled_categories=8)
        assert r.status == "WARN"


class TestCG003FilenameAbstractionCheck:
    """Prefixes from the spec, else the framework starter set (#296).

    ``NA`` used to mean "the spec left the key empty", which was every vault
    the generator produces. It now means one thing only: the vault switched the
    abstraction gates off in ``settings.yaml``.
    """

    def test_na_only_when_the_vault_switches_the_gate_off(self, tmp_path: Path) -> None:
        from research_framework.pipeline.gates_cycle import (
            CG003_filename_abstraction_check,
        )

        (tmp_path / "settings.yaml").write_text(
            "pipeline:\n  gates:\n    abstraction_enabled: false\n",
            encoding="utf-8",
        )
        spec = _minimal_spec(forbidden=[])
        r = CG003_filename_abstraction_check(spec, ["svc_foo.md"], tmp_path)
        assert r.status == "NA"

    def test_empty_spec_list_uses_the_framework_prefixes(self, tmp_path: Path) -> None:
        from research_framework.pipeline.gates_cycle import (
            CG003_filename_abstraction_check,
        )

        spec = _minimal_spec(forbidden=[])
        r = CG003_filename_abstraction_check(
            spec, ["svc_a.md", "svc_b.md", "svc_c.md", "ok.md"], tmp_path
        )
        assert r.status == "FAIL"

    def test_pass_when_ratio_low(self, tmp_path: Path) -> None:
        from research_framework.pipeline.gates_cycle import (
            CG003_filename_abstraction_check,
        )

        spec = _minimal_spec(forbidden=["oms_"])
        r = CG003_filename_abstraction_check(
            spec,
            ["alpha.md", "beta.md", "gamma.md", "oms_x.md"],
            tmp_path,
        )
        assert r.status == "PASS"

    def test_fail_when_ratio_above_sixty(self, tmp_path: Path) -> None:
        from research_framework.pipeline.gates_cycle import (
            CG003_filename_abstraction_check,
        )

        spec = _minimal_spec(forbidden=["oms_"])
        files = ["oms_a.md", "oms_b.md", "oms_c.md", "ok.md"]
        r = CG003_filename_abstraction_check(spec, files, tmp_path)
        assert r.status == "FAIL"

    def test_boundary_warn_between_thirty_and_sixty(self, tmp_path: Path) -> None:
        from research_framework.pipeline.gates_cycle import (
            CG003_filename_abstraction_check,
        )

        spec = _minimal_spec(forbidden=["x_"])
        r = CG003_filename_abstraction_check(
            spec,
            ["x_1.md", "x_2.md", "a.md", "b.md", "c.md"],
            tmp_path,
        )
        assert r.status == "WARN"


class TestCG004AvgWordCountVelocity:
    """Coverage velocity vs expected per-cycle progress (spec Story 9a)."""

    def test_pass_when_half_expected_met_categories_progress(self) -> None:
        from research_framework.pipeline.gates_cycle import CG004_avg_word_count

        before = {"concepts": {"met": 1}}
        after = {"concepts": {"met": 6}}
        r = CG004_avg_word_count(
            before,
            after,
            expected_per_cycle=10,
            categories=["concepts"],
        )
        assert r.status == "PASS"

    def test_fail_zero_progress_unfilled(self) -> None:
        from research_framework.pipeline.gates_cycle import CG004_avg_word_count

        before = {"concepts": {"met": 2}, "flows": {"met": 0}}
        after = {"concepts": {"met": 7}, "flows": {"met": 0}}
        r = CG004_avg_word_count(
            before,
            after,
            expected_per_cycle=5,
            categories=["concepts", "flows"],
        )
        assert r.status == "FAIL"

    def test_boundary_warn_below_half_velocity(self) -> None:
        from research_framework.pipeline.gates_cycle import CG004_avg_word_count

        before = {"concepts": {"met": 0}}
        after = {"concepts": {"met": 2}}
        r = CG004_avg_word_count(
            before,
            after,
            expected_per_cycle=10,
            categories=["concepts"],
        )
        assert r.status == "WARN"


class TestCG005CumulativeCoverageTrajectory:
    """Projected fill at max_cycles vs 70% bar."""

    def test_pass_high_projected_fill(self) -> None:
        from research_framework.pipeline.gates_cycle import (
            CG005_cumulative_coverage_trajectory,
        )

        snap = {"c": {"target": 10, "met": 8, "fill_pct": 0.8}}
        r = CG005_cumulative_coverage_trajectory(snap, max_cycles=5, current_cycle=2)
        assert r.status == "PASS"

    def test_warn_low_projected_fill(self) -> None:
        from research_framework.pipeline.gates_cycle import (
            CG005_cumulative_coverage_trajectory,
        )

        snap = {"c": {"target": 100, "met": 5, "fill_pct": 0.05}}
        r = CG005_cumulative_coverage_trajectory(snap, max_cycles=6, current_cycle=2)
        assert r.status == "WARN"

    def test_boundary_near_seventy_percent(self) -> None:
        from research_framework.pipeline.gates_cycle import (
            CG005_cumulative_coverage_trajectory,
        )

        snap = {"c": {"target": 10, "met": 6, "fill_pct": 0.6}}
        r = CG005_cumulative_coverage_trajectory(snap, max_cycles=8, current_cycle=4)
        assert r.status in ("PASS", "WARN")


class TestCG006WordCountCompliance:
    """Share of notes below per-type ``min_word_count``."""

    def test_pass_mostly_compliant(self) -> None:
        from research_framework.pipeline.gates_cycle import CG006_word_count_compliance

        r = CG006_word_count_compliance(
            [120, 300, 250, 400],
            min_floor=200,
        )
        assert r.status == "PASS"

    def test_fail_too_many_short(self) -> None:
        from research_framework.pipeline.gates_cycle import CG006_word_count_compliance

        r = CG006_word_count_compliance(
            [50, 40, 300, 20, 10],
            min_floor=200,
        )
        assert r.status == "FAIL"

    def test_boundary_warn_above_ten_pct(self) -> None:
        from research_framework.pipeline.gates_cycle import CG006_word_count_compliance

        r = CG006_word_count_compliance(
            [50, 210, 210, 210, 210, 210, 210, 210, 210, 210],
            min_floor=200,
        )
        assert r.status == "WARN"


class TestCG007OrphanLinkPct:
    """Dead wikilinks / total wikilinks."""

    def test_pass_low_orphan_ratio(self) -> None:
        from research_framework.pipeline.gates_cycle import CG007_orphan_link_pct

        r = CG007_orphan_link_pct(dead=2, total=50)
        assert r.status == "PASS"

    def test_fail_very_high_orphans(self) -> None:
        from research_framework.pipeline.gates_cycle import CG007_orphan_link_pct

        r = CG007_orphan_link_pct(dead=45, total=50)
        assert r.status == "FAIL"

    def test_boundary_warn_just_over_twenty(self) -> None:
        from research_framework.pipeline.gates_cycle import CG007_orphan_link_pct

        r = CG007_orphan_link_pct(dead=11, total=50)
        assert r.status == "WARN"
