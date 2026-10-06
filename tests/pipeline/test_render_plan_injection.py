"""`_render.py` injects `_pipeline/research-plan.md` into agent prompts (T016).

After T021, scout + note-writer render paths MUST embed the priority queue,
cycle focus list, and exclusion list **verbatim** from the on-disk plan.

This module only imports `research_framework.agents._render` inside tests so
collection works while the new helpers are still missing (TDD RED).
"""

from __future__ import annotations

import textwrap
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


def _tiny_spec() -> SpecConfig:
    cat = CoverageCategory(
        name="alpha", note_type="concept", target_count=3, met_count=0
    )
    return SpecConfig(
        name="v",
        location=Path("."),
        owner="u",
        scope=ScopeConfig(domain="d", organization="o"),
        note_types=[NoteTypeConfig(name="concept", description="", folder="c/")],
        data_sources=[DataSourceConfig(name="s", type="external", priority=2)],
        search_dimensions=["q"],
        coverage_targets=CoverageTargets(categories=[cat]),
        budget=BudgetConfig(),
    )


class TestResearchPlanPromptInjection:
    def test_scout_and_note_writer_prompts_include_plan_excerpts(
        self, tmp_path: Path
    ) -> None:
        from research_framework.agents._render import (
            render_note_writer_prompt_for_cycle,
            render_scout_prompt_for_cycle,
        )

        spec = _tiny_spec()
        plan = textwrap.dedent("""\
            ---
            cycle_number: 1
            generated_at: "2026-05-15T09:10:00Z"
            framework_version: "0.2.17"
            cycle_quota: 12
            schema_version: "1"
            ---

            ## Focus rationale

            placeholder

            ## Coverage state

            | x | y |
            |-|-|

            ## Cycle focus

            This cycle MUST produce ≥ 70% of its notes in the following categories:

            - RV_MARKER_FOCUS_GAMMA (0% filled)

            ## Priority queue

            Each entry: `<title> · category · score · provenance · sources`.

            1. RV_MARKER_QUEUE_ALPHA · alpha · 0.71 · spec_gap · example

            ## Exclusions

            The note-writer MUST NOT propose any topic whose canonical filename matches:

            - out-of-scope: RV_MARKER_EXCLUSION_BETA
            """)
        pdir = tmp_path / "_pipeline"
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "research-plan.md").write_text(plan, encoding="utf-8")

        scout = render_scout_prompt_for_cycle(tmp_path, spec)
        dfs = render_note_writer_prompt_for_cycle(tmp_path, spec)
        for label, text in (("scout", scout), ("note_writer", dfs)):
            for needle in (
                "RV_MARKER_QUEUE_ALPHA",
                "RV_MARKER_FOCUS_GAMMA",
                "RV_MARKER_EXCLUSION_BETA",
            ):
                assert needle in text, f"{label} prompt missing {needle!r}"
