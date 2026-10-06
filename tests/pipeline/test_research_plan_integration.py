"""Integration: synthetic 13-category vault → plan file (T015, feature 017).

End-to-end through `generate_plan`, `to_markdown`, and contract re-parse.

Asserts:

- `cycle_focus` is a superset of the three highest-priority categories
  (ties broken by lowest fill — here all 0%).
- `len(priority_queue) >= cycle_quota`
- written markdown round-trips through `ResearchPlan.from_markdown`
"""

from __future__ import annotations

import json
from pathlib import Path

from research_framework.spec.schema import (
    BudgetConfig,
    CoverageCategory,
    CoverageTargets,
    DataSourceConfig,
    NoteTypeConfig,
    ScopeConfig,
    SpecConfig,
)


def _spec_thirteen_categories() -> SpecConfig:
    cats: list[CoverageCategory] = []
    for i in range(13):
        # Enumerate two expected_filenames per category so the pre-cycle
        # plan ships real `spec_gap` rows. v0.2.21 removed placeholder
        # synthesis (`_placeholder_titles`); a vault that wants the queue
        # filled before scout runs must declare its targets here.
        cats.append(
            CoverageCategory(
                name=f"c{i:02d}",
                note_type="concept",
                target_count=10,
                met_count=0,
                priority=100 - i,
                expected_filenames=[
                    f"c{i:02d}-target-a.md",
                    f"c{i:02d}-target-b.md",
                ],
            )
        )
    return SpecConfig(
        name="int-vault",
        location=Path("."),
        owner="u",
        scope=ScopeConfig(domain="d", organization="o"),
        note_types=[NoteTypeConfig(name="concept", description="", folder="c/")],
        data_sources=[DataSourceConfig(name="s", type="external", priority=2)],
        search_dimensions=["x"],
        coverage_targets=CoverageTargets(categories=cats),
        budget=BudgetConfig(),
    )


class TestResearchPlanGoldenPath:
    def test_plan_covers_top_priorities_quota_and_contract(
        self, tmp_path: Path
    ) -> None:
        from research_framework.pipeline.research_plan import (
            ResearchPlan,
            generate_plan,
        )

        spec = _spec_thirteen_categories()
        path = tmp_path / "_pipeline" / "coverage-targets.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(spec.coverage_targets.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )
        (tmp_path / "_pipeline" / "research-backlog.md").write_text(
            "# backlog\n", encoding="utf-8"
        )
        (tmp_path / "data_vault").mkdir(parents=True, exist_ok=True)

        plan = generate_plan(tmp_path, spec, cycle_number=1)
        top3 = {"c00", "c01", "c02"}
        assert top3 <= set(plan.cycle_focus)
        # 13 categories × 2 enumerated targets each = 26 spec_gap rows.
        # `cycle_quota` is `ceil(130 / 10) = 13`, so the queue clears it.
        assert len(plan.priority_queue) >= plan.cycle_quota

        md = plan.to_markdown()
        out = tmp_path / "_pipeline" / "research-plan.md"
        out.write_text(md, encoding="utf-8")
        roundtrip = ResearchPlan.from_markdown(out.read_text(encoding="utf-8"))
        assert roundtrip.cycle_number == plan.cycle_number
        assert roundtrip.cycle_quota == plan.cycle_quota
        assert len(roundtrip.cycle_focus) == len(plan.cycle_focus)
