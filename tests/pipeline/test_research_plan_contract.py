"""Contract tests for `_pipeline/research-plan.md` (T012, feature 017).

Exercises `ResearchPlan.from_markdown` against the layout in
`specs/017-vault-quality-fix/contracts/research-plan.schema.md`:

- YAML frontmatter fields are required by the contract.
- Body sections appear in exact order and the parser rejects gaps
  in the last four sections.
- `## Focus rationale` may be empty (narrator-optional path, R-005).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


def _contract_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "specs"
        / "017-vault-quality-fix"
        / "contracts"
        / "research-plan.schema.md"
    )


def _valid_plan_markdown(*, empty_focus: bool = False) -> str:
    focus_body = "" if empty_focus else "We prioritise gaps in core learning folders.\n"
    return textwrap.dedent(f"""\
        ---
        cycle_number: 2
        generated_at: "2026-05-15T12:00:00Z"
        framework_version: "0.2.17"
        cycle_quota: 15
        schema_version: "1"
        ---

        ## Focus rationale

        {focus_body}
        ## Coverage state

        | Category | Target | Met | Fill % | Priority | Unmet topics |
        |----------|--------|-----|--------|----------|--------------|
        | alpha | 10 | 0 | 0% | 90 | topic_a |

        ## Cycle focus

        This cycle MUST produce ≥ 70% of its notes in the following categories:

        - alpha (0% filled)

        ## Priority queue

        Each entry: `<title> · category · score · provenance · sources`.

        1. Topic A · alpha · 0.9 · spec_gap · example.com

        ## Exclusions

        The note-writer MUST NOT propose any topic whose canonical filename matches:

        - already-covered: kept-note
        - out-of-scope: internal-only-rules
        """)


def _section_indices(md: str) -> dict[str, int]:
    keys = (
        "## Focus rationale",
        "## Coverage state",
        "## Cycle focus",
        "## Priority queue",
        "## Exclusions",
    )
    return {k: md.find(k) for k in keys}


class TestResearchPlanContractParsing:
    """`from_markdown` accepts conformant files and exposes parsed fields."""

    def test_parses_required_frontmatter_fields(self) -> None:
        from research_framework.pipeline.research_plan import ResearchPlan

        text = _valid_plan_markdown()
        plan = ResearchPlan.from_markdown(text)
        assert plan.cycle_number == 2
        assert plan.cycle_quota == 15
        assert "2026-05-15T12:00:00Z" in plan.generated_at
        assert plan.framework_version == "0.2.17"

    def test_focus_rationale_may_be_empty(self) -> None:
        from research_framework.pipeline.research_plan import ResearchPlan

        plan = ResearchPlan.from_markdown(_valid_plan_markdown(empty_focus=True))
        assert plan.narrative_header.strip() == ""

    def test_five_sections_are_enforced_in_order(self) -> None:
        from research_framework.pipeline.research_plan import ResearchPlan

        text = _valid_plan_markdown()
        ResearchPlan.from_markdown(text)
        idx = _section_indices(text)
        ordered = [
            idx["## Focus rationale"],
            idx["## Coverage state"],
            idx["## Cycle focus"],
            idx["## Priority queue"],
            idx["## Exclusions"],
        ]
        assert all(i >= 0 for i in ordered)
        assert ordered == sorted(ordered)


class TestResearchPlanContractRefusal:
    """Missing any of the last four sections is a hard parse error."""

    @pytest.mark.parametrize(
        "broken",
        [
            "coverage_state",  # drop ## Coverage state onward
            "cycle_focus",
            "priority_queue",
            "exclusions",
        ],
    )
    def test_refuses_when_latter_section_missing(self, broken: str) -> None:
        from research_framework.pipeline.research_plan import ResearchPlan

        text = _valid_plan_markdown()
        if broken == "coverage_state":
            text = text.split("## Coverage state", 1)[0] + "\n"
        elif broken == "cycle_focus":
            pre, _, _ = text.partition("## Cycle focus")
            text = pre
        elif broken == "priority_queue":
            pre, _, _ = text.partition("## Priority queue")
            text = pre
        else:
            pre, _, _ = text.partition("## Exclusions")
            text = pre

        with pytest.raises(ValueError, match="(?i)malformed|missing|section"):
            ResearchPlan.from_markdown(text)

    def test_refuses_wrong_section_order(self) -> None:
        from research_framework.pipeline.research_plan import ResearchPlan

        base = _valid_plan_markdown()
        parts = _section_indices(base)
        focus = base[parts["## Focus rationale"] : parts["## Coverage state"]]
        cov = base[parts["## Coverage state"] : parts["## Cycle focus"]]
        cf = base[parts["## Cycle focus"] : parts["## Priority queue"]]
        pq = base[parts["## Priority queue"] : parts["## Exclusions"]]
        ex = base[parts["## Exclusions"] :]
        wrong = focus + cf + cov + pq + ex
        with pytest.raises(ValueError):
            ResearchPlan.from_markdown(wrong)


class TestContractDocumentAnchor:
    """Sanity: on-disk contract doc exists (guards moved files)."""

    def test_schema_doc_present(self) -> None:
        assert _contract_path().is_file()
