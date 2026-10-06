"""Tests for scout step gates SG-001 and SG-002 (T026, feature 017).

Per spec.md Story 9b and tasks.md T026:

- **SG-001** — ``len(topics_found.new)``: FAIL when empty; PASS when count
  ≥ ``cycle_quota``; WARN when ``0 < count < cycle_quota``.
- **SG-002** — category diversity across ``topics_found.new``: FAIL when
  every topic shares one category; PASS when
  ``len(set(categories)) >= min(5, unfilled_categories)``.

Target implementation: ``research_framework.pipeline.gates_step`` —
``SG001_topics_new_nonempty``, ``SG002_topic_category_diversity``.
"""

from __future__ import annotations

import json
import re
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

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _gate_result_schema() -> dict:
    """Load the JSON schema for ``gate_result`` from the feature contracts."""
    contracts = (
        Path(__file__).resolve().parents[2]
        / "specs"
        / "017-vault-quality-fix"
        / "contracts"
        / "cycle-quality-report.schema.json"
    )
    schema = json.loads(contracts.read_text(encoding="utf-8"))
    return schema["$defs"]["gate_result"]


def _matches_schema(payload: dict, schema: dict) -> tuple[bool, str]:
    """Hand-rolled schema check (avoids adding ``jsonschema`` as a dep)."""
    for k in schema.get("required", []):
        if k not in payload:
            return False, f"missing required key: {k}"
    if schema.get("additionalProperties") is False:
        allowed = set(schema.get("properties", {}).keys())
        extras = set(payload.keys()) - allowed
        if extras:
            return False, f"unexpected keys: {sorted(extras)}"
    props = schema.get("properties", {})
    if "status" in payload and "enum" in props.get("status", {}):
        if payload["status"] not in props["status"]["enum"]:
            return False, f"invalid status: {payload['status']!r}"
    if "gate_id" in payload and "pattern" in props.get("gate_id", {}):
        if not re.match(props["gate_id"]["pattern"], payload["gate_id"]):
            return False, f"gate_id {payload['gate_id']!r} fails pattern"
    if payload.get("status") == "FAIL" and not payload.get("correction_hint"):
        return False, "status=FAIL requires non-empty correction_hint"
    return True, ""


def _minimal_spec(**kwargs) -> SpecConfig:
    """Build a minimal ``SpecConfig`` for gate unit tests."""
    base: dict = {
        "name": "gate-test",
        "location": Path("."),
        "owner": "tester",
        "scope": ScopeConfig(domain="d", organization="o"),
        "note_types": [
            NoteTypeConfig(name="concept", description="", folder="concepts/")
        ],
        "data_sources": [DataSourceConfig(name="s", type="external", priority=2)],
        "search_dimensions": ["domain", "market"],
        "coverage_targets": CoverageTargets(
            categories=[CoverageCategory(name="x", note_type="concept", target_count=1)]
        ),
        "budget": BudgetConfig(),
    }
    base.update(kwargs)
    return SpecConfig(**base)


def _topic_new(title: str, *, category: str | None = None) -> dict:
    row: dict = {"title": title}
    if category is not None:
        row["coverage_category"] = category
    return row


# ---------------------------------------------------------------------------
# SG-001
# ---------------------------------------------------------------------------


class TestSG001TopicsNewNonempty:
    """``topics_found.new`` must meet the per-cycle quota (with WARN band)."""

    def test_fails_when_topics_found_new_is_empty(self) -> None:
        from research_framework.pipeline.gates_step import SG001_topics_new_nonempty

        spec = _minimal_spec()
        report = {"topics_found": {"new": []}, "proposed_filenames": []}
        r = SG001_topics_new_nonempty(report, spec, cycle_quota=10)
        assert r.gate_id == "SG-001"
        assert r.status == "FAIL"
        ok, why = _matches_schema(r.to_dict(), _gate_result_schema())
        assert ok, why

    def test_passes_when_count_at_or_above_cycle_quota(self) -> None:
        from research_framework.pipeline.gates_step import SG001_topics_new_nonempty

        spec = _minimal_spec()
        new = [_topic_new(f"topic-{i}") for i in range(5)]
        report = {"topics_found": {"new": new}, "proposed_filenames": []}
        r = SG001_topics_new_nonempty(report, spec, cycle_quota=5)
        assert r.status == "PASS"

    def test_warns_when_count_positive_but_below_cycle_quota(self) -> None:
        from research_framework.pipeline.gates_step import SG001_topics_new_nonempty

        spec = _minimal_spec()
        new = [_topic_new(f"t-{i}") for i in range(3)]
        report = {"topics_found": {"new": new}, "proposed_filenames": []}
        r = SG001_topics_new_nonempty(report, spec, cycle_quota=10)
        assert r.status == "WARN"
        ok, why = _matches_schema(r.to_dict(), _gate_result_schema())
        assert ok, why


# ---------------------------------------------------------------------------
# SG-002
# ---------------------------------------------------------------------------


class TestSG002TopicCategoryDiversity:
    """Distinct ``coverage_category`` values in ``topics_found.new``."""

    def test_fails_when_all_topics_share_one_category(self) -> None:
        from research_framework.pipeline.gates_step import (
            SG002_topic_category_diversity,
        )

        spec = _minimal_spec()
        new = [
            _topic_new("Alpha", category="concepts"),
            _topic_new("Beta", category="concepts"),
            _topic_new("Gamma", category="concepts"),
        ]
        report = {"topics_found": {"new": new}}
        r = SG002_topic_category_diversity(report, spec, unfilled_categories=10)
        assert r.gate_id == "SG-002"
        assert r.status == "FAIL"
        ok, why = _matches_schema(r.to_dict(), _gate_result_schema())
        assert ok, why

    def test_passes_when_distinct_categories_meet_min_of_five_and_unfilled(
        self,
    ) -> None:
        from research_framework.pipeline.gates_step import (
            SG002_topic_category_diversity,
        )

        spec = _minimal_spec()
        cats = ["c1", "c2", "c3", "c4", "c5"]
        new = [_topic_new(f"topic-{c}", category=c) for c in cats]
        report = {"topics_found": {"new": new}}
        r = SG002_topic_category_diversity(report, spec, unfilled_categories=13)
        assert r.status == "PASS"
        assert r.metric_value >= 5

    def test_threshold_clamps_to_unfilled_when_below_five(self) -> None:
        from research_framework.pipeline.gates_step import (
            SG002_topic_category_diversity,
        )

        spec = _minimal_spec()
        new = [
            _topic_new("a", category="u1"),
            _topic_new("b", category="u2"),
            _topic_new("c", category="u3"),
        ]
        report = {"topics_found": {"new": new}}
        r = SG002_topic_category_diversity(report, spec, unfilled_categories=3)
        assert r.status == "PASS"


# ---------------------------------------------------------------------------
# Bare-string tolerance (regression suite for the codex/gpt scout output
# discovered during the feeds-vault revival, 2026-05-30 post-mortem).
# ---------------------------------------------------------------------------


class TestBareStringTopicTolerance:
    """``topics_found.new`` rows may be bare strings as well as dicts.

    Codex/GPT scouts emit ``["AlphaEvolve", "Mira Murati", ...]`` while
    claude scouts emit fully structured dicts. The framework must accept
    both shapes — every call site that reads ``topics_found.new`` MUST go
    through ``normalise_topic_row``.
    """

    def test_normalise_wraps_bare_string_as_title_dict(self) -> None:
        from research_framework.pipeline.gates_step import normalise_topic_row

        assert normalise_topic_row("AlphaEvolve") == {"title": "AlphaEvolve"}

    def test_normalise_passes_dict_with_title_through(self) -> None:
        from research_framework.pipeline.gates_step import normalise_topic_row

        row = {"title": "Foo", "coverage_category": "concepts"}
        assert normalise_topic_row(row) is row

    def test_normalise_returns_none_for_empty_string(self) -> None:
        from research_framework.pipeline.gates_step import normalise_topic_row

        assert normalise_topic_row("") is None
        assert normalise_topic_row("   ") is None

    def test_normalise_returns_none_for_dict_without_title(self) -> None:
        from research_framework.pipeline.gates_step import normalise_topic_row

        assert normalise_topic_row({"coverage_category": "x"}) is None

    def test_normalise_returns_none_for_other_types(self) -> None:
        from research_framework.pipeline.gates_step import normalise_topic_row

        assert normalise_topic_row(42) is None
        assert normalise_topic_row(["nested", "list"]) is None
        assert normalise_topic_row(None) is None

    def test_sg001_passes_with_bare_string_topics(self) -> None:
        """Regression: codex output of bare strings used to be dropped by
        the gate's row filter (returning 0 → FAIL). Now bare strings count
        toward the cycle quota."""
        from research_framework.pipeline.gates_step import SG001_topics_new_nonempty

        spec = _minimal_spec()
        report = {
            "topics_found": {
                "new": [
                    "AlphaEvolve",
                    "Content Credentials",
                    "Mira Murati",
                    "Thinking Machines Lab",
                    "Forward Deployed Engineering",
                ]
            }
        }
        r = SG001_topics_new_nonempty(report, spec, cycle_quota=5)
        assert r.status == "PASS"
        assert r.metric_value == 5

    def test_sg002_degrades_to_warn_when_all_topics_uncategorised(self) -> None:
        """Bare-string topics carry no ``coverage_category`` — the diversity
        signal is vacuous in that case, so the gate degrades to WARN
        (downstream classifier will enrich) instead of failing."""
        from research_framework.pipeline.gates_step import (
            SG002_topic_category_diversity,
        )

        spec = _minimal_spec()
        report = {
            "topics_found": {
                "new": ["AlphaEvolve", "Mira Murati", "Thinking Machines Lab"]
            }
        }
        r = SG002_topic_category_diversity(report, spec, unfilled_categories=10)
        assert r.status == "WARN"
        assert "uncategorised" in r.message

    def test_sg002_still_fails_when_some_categorised_topics_share_one_category(
        self,
    ) -> None:
        """Tolerance is bounded: if ANY topic carries a coverage_category,
        the gate evaluates diversity normally (FAIL when all share one)."""
        from research_framework.pipeline.gates_step import (
            SG002_topic_category_diversity,
        )

        spec = _minimal_spec()
        report = {
            "topics_found": {
                "new": [
                    {"title": "A", "coverage_category": "concepts"},
                    {"title": "B", "coverage_category": "concepts"},
                    "Bare String C",
                ]
            }
        }
        r = SG002_topic_category_diversity(report, spec, unfilled_categories=10)
        assert r.status == "FAIL"
