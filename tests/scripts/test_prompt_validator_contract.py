"""Seam test: the cycle-report fields the prompt templates ask agents to
emit MUST satisfy the cycle-report fields the validator demands. v0.2.21 and
v0.2.24 both shipped with this contract silently broken — every real
research-phase cycle aborted with ``missing required v2 field:
budget_consumed_usd`` because the DFS prompt told agents to emit
``cumulative_cost_usd`` / ``cost_estimate_usd`` instead.

This test parses the actual prompt templates (Jinja → render → JSON spec
block) and the actual validator's required-field lists, then asserts the
seam holds. It is the prototype of the "schema-contract" layer from the
018 testing-strategy spec.

The test deliberately runs without spinning up a full pipeline so it stays
fast (< 100 ms) and is checked on every commit.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
PROMPTS_DIR = REPO_ROOT / "templates" / "prompts"
DFS_PROMPT = PROMPTS_DIR / "dfs-prompt.md.j2"
SCOUT_PROMPT = PROMPTS_DIR / "scout-prompt.md.j2"


def _load_validator_module():
    """Import ``scripts/validate_cycle.py`` without invoking its CLI.
    The script lives outside the ``research_framework`` package on purpose
    (it's bundled as a standalone tool), so we load it by path.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_vc", SCRIPTS_DIR / "validate_cycle.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_vc"] = module
    spec.loader.exec_module(module)
    return module


def _extract_json_field_names(template_text: str, marker: str) -> set[str]:
    """Extract the top-level JSON keys from the fenced ``json`` block in
    the template that CONTAINS ``marker``. Returns the set of keys the
    prompt instructs the agent to emit at the top level of its report.

    We deliberately use a regex on the template source rather than
    rendering the Jinja: the template uses ``{% for %}`` loops to build
    nested ``sources_consulted`` keys, but the top-level field list is
    static and immune to rendering context. The marker is matched
    against the block body so multiple blocks in the same file (e.g.
    scout-prompt has a v2 and a v1 block) can be disambiguated.
    """
    blocks = re.findall(r"```json\s*\n(.*?)\n```", template_text, re.DOTALL)
    matching = [b for b in blocks if marker in b]
    assert matching, f"marker {marker!r} not found in any of {len(blocks)} json blocks"
    assert len(matching) == 1, (
        f"marker {marker!r} is ambiguous (matches {len(matching)} json "
        "blocks); pick a more specific marker"
    )
    body = matching[0]
    # Top-level keys: lines like ``  "key":`` that are indented exactly two
    # spaces (the opening brace is at column 0 and the body is two-space
    # indented per our prompt convention). This avoids matching nested
    # keys inside ``sources_consulted`` (which are four-space indented).
    keys = set()
    for line in body.splitlines():
        m = re.match(r'^  "([A-Za-z_][A-Za-z0-9_]*)"\s*:', line)
        if m:
            keys.add(m.group(1))
    return keys


# ---------------------------------------------------------------------------
# Sanity: the helpers actually find fields
# ---------------------------------------------------------------------------


def test_helper_extracts_dfs_prompt_top_level_keys() -> None:
    text = DFS_PROMPT.read_text(encoding="utf-8")
    keys = _extract_json_field_names(text, '"phase": "research"')
    assert keys, "DFS prompt JSON block parsed as empty — helper broken"
    assert "cycle" in keys
    assert "phase" in keys
    assert "sources_consulted" in keys


def test_helper_extracts_scout_prompt_top_level_keys() -> None:
    text = SCOUT_PROMPT.read_text(encoding="utf-8")
    # The scout prompt has TWO scout-phase blocks: the v2/code-first
    # one (the only one we ship today) and a legacy v1 block. We pin to
    # the v2 block by a v2-only marker.
    keys = _extract_json_field_names(text, '"schema_version": "2.0"')
    assert "cycle" in keys
    assert "sources_consulted" in keys


# ---------------------------------------------------------------------------
# Contract: every required validator field IS in the prompt
# ---------------------------------------------------------------------------


def test_dfs_prompt_emits_every_validator_required_research_field() -> None:
    """Whatever ``REQUIRED_REPORT_FIELDS_V2_RESEARCH`` demands MUST appear
    in the DFS prompt's output spec, otherwise agents won't know to emit
    it and every real research cycle will abort. This is the test that
    would have caught the v0.2.21 / v0.2.24 ``budget_consumed_usd``
    crash before it shipped.
    """
    vc = _load_validator_module()
    prompt_keys = _extract_json_field_names(
        DFS_PROMPT.read_text(encoding="utf-8"), '"phase": "research"'
    )
    required = set(vc.REQUIRED_REPORT_FIELDS_V2_RESEARCH)
    missing = required - prompt_keys
    assert not missing, (
        "DFS prompt is missing required validator fields: "
        f"{sorted(missing)}. The validator will abort every research-phase "
        "cycle until the prompt teaches the agent to emit these. "
        "Update templates/prompts/dfs-prompt.md.j2."
    )


def test_dfs_prompt_emits_at_least_one_budget_field() -> None:
    """Research reports must report budget under one of the accepted
    aliases (``budget_consumed_usd`` / ``cumulative_cost_usd`` /
    ``cost_estimate_usd``). The validator accepts any of the three; the
    prompt MUST ask for at least one or the agent has no incentive to
    emit any cost data. v0.2.25 emits all three for forward-compat.
    """
    vc = _load_validator_module()
    prompt_keys = _extract_json_field_names(
        DFS_PROMPT.read_text(encoding="utf-8"), '"phase": "research"'
    )
    accepted = set(vc.BUDGET_FIELDS_V2_RESEARCH)
    present = prompt_keys & accepted
    assert present, (
        "DFS prompt does not ask the agent to emit ANY budget field. "
        f"Accepted: {sorted(accepted)}. Add at least one to "
        "templates/prompts/dfs-prompt.md.j2."
    )


def test_dfs_prompt_emits_canonical_budget_field_v0_2_25() -> None:
    """Beyond accepting any-of-three, v0.2.25 specifically asks the
    prompt to emit the canonical ``budget_consumed_usd`` alias so reports
    stay aligned with the published v2 schema. A prompt that emits only
    the legacy names still validates but defeats the cleanup effort.
    """
    prompt_keys = _extract_json_field_names(
        DFS_PROMPT.read_text(encoding="utf-8"), '"phase": "research"'
    )
    assert "budget_consumed_usd" in prompt_keys, (
        "DFS prompt should emit the canonical `budget_consumed_usd` "
        "field, not only the legacy `cumulative_cost_usd` / "
        "`cost_estimate_usd` aliases."
    )


def test_scout_prompt_emits_every_validator_required_scout_field() -> None:
    """Mirror of the DFS test for scout reports: the scout prompt MUST
    emit every field in ``REQUIRED_REPORT_FIELDS_V2`` (the superset that
    includes ``topics_from_code`` / ``intent_from_confluence`` /
    ``dimensions_covered``)."""
    vc = _load_validator_module()
    prompt_keys = _extract_json_field_names(
        SCOUT_PROMPT.read_text(encoding="utf-8"),
        '"schema_version": "2.0"',
    )
    required = set(vc.REQUIRED_REPORT_FIELDS_V2)
    missing = required - prompt_keys
    assert not missing, (
        "Scout prompt is missing required validator fields: "
        f"{sorted(missing)}. Update templates/prompts/scout-prompt.md.j2."
    )


# ---------------------------------------------------------------------------
# Contract: orchestrator budget reader and validator agree on field names
# ---------------------------------------------------------------------------


def test_orchestrator_budget_aliases_match_validator() -> None:
    """The orchestrator (``pipeline/orchestrator.py``) extracts budget
    info from research reports using ``cost_estimate_usd``,
    ``cumulative_cost_usd``, and ``budget_consumed_usd``. Those three
    names MUST equal ``BUDGET_FIELDS_V2_RESEARCH`` so the validator and
    the orchestrator can never disagree about what counts as a valid
    budget signal — that disagreement is the v0.2.21 bug class.
    """
    vc = _load_validator_module()
    orch_path = (
        REPO_ROOT / "src" / "research_framework" / "pipeline" / "orchestrator.py"
    )
    orch_text = orch_path.read_text(encoding="utf-8")
    for field in vc.BUDGET_FIELDS_V2_RESEARCH:
        assert field in orch_text, (
            f"validator accepts budget field {field!r} but the "
            "orchestrator never reads it — the contract is split. "
            f"Either drop it from BUDGET_FIELDS_V2_RESEARCH in "
            "scripts/validate_cycle.py or teach the orchestrator's "
            "budget reader about it."
        )


# ---------------------------------------------------------------------------
# Regression: the exact failure shape from the user's vault
# ---------------------------------------------------------------------------


@pytest.fixture
def realistic_cycle_005_report() -> dict:
    """A research-phase report shaped like the one the user's cycle 5
    actually produced (omits ``budget_consumed_usd``, uses
    ``cumulative_cost_usd`` instead). Pre-v0.2.25 this report aborts the
    cycle; post-fix it validates cleanly because the validator accepts
    ``cumulative_cost_usd`` as a budget signal.
    """
    return {
        "schema_version": "2.0",
        "cycle": 5,
        "phase": "research",
        "timestamp": "2026-05-17T17:05:00Z",
        "sources_consulted": {"open_web": {"searched": True, "results_count": 2}},
        "topics_found": {"new": [], "existing": ["JSON", "Protobuf"], "total": 2},
        "notes_created": ["data_vault/01 - Concepts/json.md"],
        "notes_updated": [],
        "cost_estimate_usd": 0.0,
        "cumulative_cost_usd": 0.0,
        "next_action": "continue",
        "termination_reason": None,
    }


def test_real_world_cycle_005_report_validates_after_fix(
    realistic_cycle_005_report: dict,
) -> None:
    """Lock the v0.2.21–v0.2.24 regression: a research report that
    reports budget via ``cumulative_cost_usd`` instead of
    ``budget_consumed_usd`` is acceptable after v0.2.25."""
    vc = _load_validator_module()
    errors = vc.validate_report_structure_v2(realistic_cycle_005_report)
    assert errors == [], f"expected no errors after fix, got: {errors}"


def test_research_report_with_no_budget_field_still_fails(
    realistic_cycle_005_report: dict,
) -> None:
    """We must NOT have over-relaxed: a research report with ZERO budget
    fields is still invalid. Reporting budget is a contract requirement,
    just not tied to a single field name."""
    vc = _load_validator_module()
    report = dict(realistic_cycle_005_report)
    for field in vc.BUDGET_FIELDS_V2_RESEARCH:
        report.pop(field, None)
    errors = vc.validate_report_structure_v2(report)
    assert any("budget" in e for e in errors), (
        f"removing all budget fields should fail validation; got {errors}"
    )


# ---------------------------------------------------------------------------
# The prompt must offer a `reason` field for the sources the validator will
# demand a reason from.
# ---------------------------------------------------------------------------


def _sources_consulted_line(template: Path) -> str:
    """The Jinja line that renders one `sources_consulted` entry."""
    for line in template.read_text(encoding="utf-8").splitlines():
        if '"searched": true|false' in line:
            return line
    raise AssertionError(f"no sources_consulted entry line in {template}")


@pytest.mark.parametrize("template", [DFS_PROMPT, SCOUT_PROMPT])
def test_reason_is_offered_for_required_sources_too(template: Path) -> None:
    """The seam that made every "no reason given" warning unanswerable.

    `validate_cycle.validate_sources` warns
    ``required source 'X' was not searched: <reason>`` — it demands a reason
    from REQUIRED sources. The prompts offered the `reason` field only
    ``if not ds.required``, so on a vault where every source is required the
    agent had **nowhere to put one**, and the validator dutifully printed "no
    reason given" for something it had never asked for.

    Observed on feeds-vault, all 7 sources required, 5 skipped, 5 identical
    unanswerable warnings every cycle. The scout template contradicted itself
    outright: its prose said required sources must be "explicitly skipped with
    a reason" while its JSON schema withheld the field.

    A skipped REQUIRED source is the one that most needs to explain itself.
    """
    line = _sources_consulted_line(template)
    assert "reason" in line, f"{template.name}: no reason field offered at all"
    assert "if not ds.required" not in line, (
        f"{template.name}: `reason` is still withheld from required sources — "
        "the validator demands one from exactly those"
    )


def test_scout_instruction_covers_required_sources() -> None:
    """The prose rule must match the schema it describes."""
    text = SCOUT_PROMPT.read_text(encoding="utf-8")
    assert "For each optional source skipped, provide a `reason`." not in text, (
        "the rule still scopes `reason` to optional sources only"
    )
    assert "skipped" in text and "reason" in text
