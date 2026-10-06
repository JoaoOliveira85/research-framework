"""Unit tests for deterministic `generate_plan` (T013, feature 017).

Covers ranking math from `research.md` R-009 / `data-model.md` E-002:

- queue score uses category `priority * fill_gap` (fill_gap = unfilled fraction)
- harvest orphans weighted `0.3 + 0.1 * citation_count`, capped `1.0`
- `cycle_focus` picks the three lowest-fill categories among high-priority
  (priority ≥ 50) rows
- `exclusions` dedupes overlaps across vault filenames, rejects, and
  `scope.out_of_scope`
- `cycle_quota` matches `ceil(remaining_targets / remaining_cycles)`
- degenerate queue shorter than quota → `ValueError`

Imports `research_framework.pipeline.research_plan` **inside** tests so collection
succeeds before the module exists (TDD RED).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from research_framework.spec.schema import (
    BudgetConfig,
    CoverageCategory,
    CoverageTargets,
    DataSourceConfig,
    NoteTypeConfig,
    ScopeConfig,
    SpecConfig,
)


def _write_coverage(
    tmp_path: Path,
    *,
    categories: list[CoverageCategory],
    cycle_number: int = 0,
) -> None:
    p = tmp_path / "_pipeline" / "coverage-targets.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    targets = CoverageTargets(categories=categories, cycle_number=cycle_number)
    p.write_text(json.dumps(targets.to_dict(), indent=2) + "\n", encoding="utf-8")


def _write_settings_max_cycles(vault: Path, max_cycles: int) -> None:
    """Spec 061: the cycle horizon the yield model reads now lives in
    ``settings.yaml`` (``pipeline.max_cycles``), not the spec. ``budget_usd`` is
    required by the loader, so we include it; absence would make
    ``effective_max_cycles`` fall back to the built-in default."""
    (vault / "settings.yaml").write_text(
        f"pipeline:\n  max_cycles: {max_cycles}\n  budget_usd: 10.0\n",
        encoding="utf-8",
    )


def _minimal_spec(
    *,
    categories: list[CoverageCategory],
    out_of_scope: list[str] | None = None,
    max_cycles: int = 10,
) -> SpecConfig:
    scope = ScopeConfig(
        domain="d",
        organization="o",
        out_of_scope=list(out_of_scope or []),
    )
    return SpecConfig(
        name="vault",
        location=Path("."),
        owner="u",
        scope=scope,
        note_types=[NoteTypeConfig(name="concept", description="", folder="c/")],
        data_sources=[DataSourceConfig(name="s", type="external", priority=2)],
        search_dimensions=["domain"],
        coverage_targets=CoverageTargets(categories=categories),
        budget=BudgetConfig(),
    )


def _backlog_block(cycle: int, lines: list[str]) -> str:
    start = f"<!-- topic-harvest:cycle={cycle:03d} -->"
    end = f"<!-- /topic-harvest:cycle={cycle:03d} -->"
    body = "\n".join(lines)
    return f"{start}\n{body}\n{end}\n"


class TestPriorityQueueOrdering:
    """Higher `priority * fill_gap` ranks earlier (descending sort)."""

    def test_orders_by_priority_times_fill_gap(self, tmp_path: Path) -> None:
        from research_framework.pipeline.research_plan import generate_plan

        # Enumerate expected_filenames so the queue gets real spec_gap
        # rows (v0.2.21 no longer synthesises placeholders for empty
        # `expected_filenames`).
        cats = [
            CoverageCategory(
                name="prefer",
                note_type="concept",
                target_count=10,
                met_count=0,
                priority=60,  # 60 * 1.0 = 60
                expected_filenames=["prefer-one.md", "prefer-two.md"],
            ),
            CoverageCategory(
                name="after",
                note_type="concept",
                target_count=10,
                met_count=5,
                priority=100,  # 100 * 0.5 = 50
                expected_filenames=["after-one.md", "after-two.md"],
            ),
        ]
        _write_coverage(tmp_path, categories=cats)
        (tmp_path / "_pipeline" / "research-backlog.md").write_text(
            "# backlog\n", encoding="utf-8"
        )
        spec = _minimal_spec(categories=cats)
        plan = generate_plan(tmp_path, spec, cycle_number=1)
        assert plan.priority_queue[0].category == "prefer"


class TestHarvestOrphanWeighting:
    """Orphan scores follow `0.3 + 0.1 * citation_count` capped at `1.0`."""

    @pytest.mark.parametrize(
        "citations, expected",
        [
            (0, 0.3),
            (3, 0.6),
            (7, 1.0),
            (99, 1.0),
        ],
    )
    def test_citation_weighting_and_cap(
        self, tmp_path: Path, citations: int, expected: float
    ) -> None:
        from research_framework.pipeline.research_plan import generate_plan

        cats = [
            CoverageCategory(
                name="concept",
                note_type="concept",
                target_count=5,
                met_count=0,
                priority=10,
            ),
        ]
        _write_coverage(tmp_path, categories=cats)
        body = _backlog_block(
            1,
            [
                "## Harvest — cycle 001 (2026-05-15)",
                "",
                "Follow-on topics (wikilink targets with no note yet, "
                "ranked by citation count):",
                "",
                f"- **Orphan Title** — cited by {citations} note(s): `n/a`",
                "",
            ],
        )
        (tmp_path / "_pipeline" / "research-backlog.md").write_text(
            f"# Backlog\n\n{body}", encoding="utf-8"
        )
        spec = _minimal_spec(categories=cats)
        plan = generate_plan(tmp_path, spec, cycle_number=2)
        orch = [
            t
            for t in plan.priority_queue
            if "harvest_orphan" in t.provenance or "orphan" in t.provenance
        ]
        assert orch, plan.priority_queue
        got = orch[0].priority_score
        assert math.isclose(got, expected, rel_tol=0.0, abs_tol=1e-6)


class TestCycleFocusSelection:
    """Three lowest-fill categories among priority ≥ 50."""

    def test_three_lowest_fill_among_high_priority(self, tmp_path: Path) -> None:
        from research_framework.pipeline.research_plan import generate_plan

        cats = [
            CoverageCategory(
                name="p90_fill50",
                note_type="concept",
                target_count=10,
                met_count=5,
                priority=90,
            ),
            CoverageCategory(
                name="p90_fill40",
                note_type="concept",
                target_count=10,
                met_count=6,
                priority=90,
            ),
            CoverageCategory(
                name="p90_fill30",
                note_type="concept",
                target_count=10,
                met_count=7,
                priority=90,
            ),
            CoverageCategory(
                name="p90_fill20",
                note_type="concept",
                target_count=10,
                met_count=8,
                priority=90,
            ),
            CoverageCategory(
                name="p10_fill0",
                note_type="concept",
                target_count=10,
                met_count=0,
                priority=10,
            ),
        ]
        _write_coverage(tmp_path, categories=cats)
        (tmp_path / "_pipeline" / "research-backlog.md").write_text(
            "# x\n", encoding="utf-8"
        )
        spec = _minimal_spec(categories=cats)
        plan = generate_plan(tmp_path, spec, cycle_number=1)
        assert set(plan.cycle_focus) >= {
            "p90_fill50",
            "p90_fill40",
            "p90_fill30",
        }
        assert "p10_fill0" not in set(plan.cycle_focus)


class TestExclusionsDedup:
    """Overlapping exclusion sources collapse to unique strings."""

    def test_deduplicates_out_of_scope_and_vault_and_rejects(
        self, tmp_path: Path
    ) -> None:
        from research_framework.pipeline.research_plan import generate_plan

        cats = [
            CoverageCategory(
                name="c1",
                note_type="concept",
                target_count=3,
                met_count=0,
                priority=80,
            ),
        ]
        _write_coverage(tmp_path, categories=cats)
        dv = tmp_path / "data_vault"
        dv.mkdir(parents=True, exist_ok=True)
        (dv / "already.md").write_text(
            "---\ntitle: x\ntype: concept\n---\n", encoding="utf-8"
        )
        rej = tmp_path / "_pipeline" / "rejects.json"
        rej.write_text(
            json.dumps(
                {
                    "rejects": [
                        {"proposed_filename": "dup-slug.md", "reject_count": 2},
                        {"proposed_filename": "dup-slug.md", "reject_count": 3},
                    ]
                }
            ),
            encoding="utf-8",
        )
        spec = _minimal_spec(
            categories=cats,
            out_of_scope=["dup-slug", "dup-slug", "other-scope"],
        )
        (tmp_path / "_pipeline" / "research-backlog.md").write_text(
            "# x\n", encoding="utf-8"
        )
        plan = generate_plan(tmp_path, spec, cycle_number=1)
        assert len(plan.exclusions) == len(set(plan.exclusions))
        joined = "\n".join(plan.exclusions)
        assert "other-scope" in joined
        assert joined.lower().count("dup-slug") <= 1


class TestCycleQuota:
    """Matches ceil(remaining_targets / remaining_cycles)."""

    def test_quota_arithmetic(self, tmp_path: Path) -> None:
        from research_framework.pipeline.research_plan import generate_plan

        cats = [
            CoverageCategory(
                name="a", note_type="concept", target_count=40, met_count=10
            ),
            CoverageCategory(
                name="b", note_type="concept", target_count=60, met_count=20
            ),
        ]
        _write_coverage(tmp_path, categories=cats)
        (tmp_path / "_pipeline" / "research-backlog.md").write_text(
            "# x\n", encoding="utf-8"
        )
        spec = _minimal_spec(categories=cats, max_cycles=10)
        _write_settings_max_cycles(tmp_path, 10)
        plan = generate_plan(tmp_path, spec, cycle_number=3)
        remaining = sum(c.target_count - c.met_count for c in cats)
        remaining_cycles = max(1, 10 - (3 - 1))
        expect = math.ceil(remaining / remaining_cycles)
        assert plan.cycle_quota == expect


class TestInsufficientQueue:
    """``require_nonempty_queue=True`` callers still get the v0.2.20 raise."""

    def test_raises_when_queue_shorter_than_quota_opt_in(self, tmp_path: Path) -> None:
        from research_framework.pipeline.research_plan import generate_plan

        cats = [
            CoverageCategory(
                name="solo",
                note_type="concept",
                target_count=500,
                met_count=0,
                priority=99,
            ),
        ]
        _write_coverage(tmp_path, categories=cats)
        (tmp_path / "_pipeline" / "research-backlog.md").write_text(
            "# empty\n", encoding="utf-8"
        )
        spec = _minimal_spec(categories=cats, max_cycles=1)
        with pytest.raises(ValueError, match="(?i)quota|queue|topic"):
            generate_plan(tmp_path, spec, cycle_number=1, require_nonempty_queue=True)

    def test_default_allows_empty_queue_post_v021(self, tmp_path: Path) -> None:
        """Default ``generate_plan`` no longer raises on empty queues.

        v0.2.21 removed placeholder generation in favour of post-scout
        merging (`merge_scout_topics`). Pre-cycle plans for vaults whose
        coverage categories don't enumerate ``expected_filenames`` are
        expected to ship an empty queue, which the cycle runner fills
        once scout has run.
        """
        from research_framework.pipeline.research_plan import generate_plan

        cats = [
            CoverageCategory(
                name="solo",
                note_type="concept",
                target_count=500,
                met_count=0,
                priority=99,
            ),
        ]
        _write_coverage(tmp_path, categories=cats)
        (tmp_path / "_pipeline" / "research-backlog.md").write_text(
            "# empty\n", encoding="utf-8"
        )
        spec = _minimal_spec(categories=cats, max_cycles=1)
        plan = generate_plan(tmp_path, spec, cycle_number=1)
        assert plan.priority_queue == []
        assert plan.cycle_quota >= 1
