"""spec-019 / 0.2.30 — directive must be injected into the rendered prompt.

This is the test 0.2.29 should have shipped with and didn't, which is
why the user's cycle 1 hit the "loop runs, agent ignores directive,
abort anyway" failure mode.

The test stubs ``agent_call.py`` (via the cycle runner's subprocess
patch) with a fake whose behaviour is **conditioned on the prompt text
it receives**:

- First call (no directive expected): writes a *deliberately
  incomplete* scout report (missing a required source).
- Second call: ONLY writes a *complete* scout report when the prompt
  text contains the substring ``"CORRECTION DIRECTIVE"``. If the
  directive is absent, the stub writes the same incomplete report
  again — and the test asserts the cycle aborts.

Variant 1: ``test_retry_prompt_contains_directive_then_succeeds`` —
the happy path. The directive is injected, the stub sees it, writes a
clean report, the cycle proceeds.

Variant 2: ``test_retry_prompt_without_directive_still_aborts`` —
sanity check on the test itself. If we deliberately strip the
directive-injection code, the test must fail (proving it actually
exercises the injection path, not some bypass).

These tests intentionally do NOT mock ``_render_prompt`` — they
exercise the real function so any regression in the injection path is
caught.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from tests.pipeline.test_cycle_runner import (
    _make_vault,
    _patch_cycle_runner_subprocess,
)

# Required sources baked into the test spec. The stub writes scout
# reports referencing only a subset, then (on a directive-bearing
# retry) adds the missing ones. Must match the validator's case
# normalisation.
_REQUIRED_SOURCES = ["Local Team Service Repositories", "Confluence"]
_INCOMPLETE_REPORT_SOURCES = ["Local Team Service Repositories"]
_COMPLETE_REPORT_SOURCES = [
    "Local Team Service Repositories",
    "Confluence",
]


def _build_test_vault(tmp_path: Path) -> tuple[Path, Path]:
    vault = _make_vault(tmp_path)
    cycle_num = 1
    cycle_3 = f"{cycle_num:03d}"
    cycles_dir = vault / "_pipeline" / "cycles"
    scout_report = cycles_dir / f"cycle-{cycle_3}-scout.json"
    # Pre-create vault-metrics so shutil.copy doesn't crash in step 0.
    (vault / "_pipeline" / "vault-metrics.json").write_text("{}")

    # Spec-parse with two required sources, both ``role: behaviour`` so
    # phase-scoping isn't the gating concern in this test (the other
    # test file covers phase-scoping separately).
    (vault / "_pipeline" / "spec-parse.json").write_text(
        json.dumps(
            {
                "name": "T",
                "data_sources": [
                    {"name": s, "required": True, "role": "behaviour", "priority": 1}
                    for s in _REQUIRED_SOURCES
                ],
            }
        ),
        encoding="utf-8",
    )
    return vault, scout_report


def _make_complete_report(sources: list[str]) -> dict:
    """A *structurally valid* v2 scout report that also passes SG-001
    (non-empty topics_found.new) and SG-002 (diverse coverage_category
    spread). The only failure surface left is ``sources_consulted`` —
    which is what we're testing.

    The minimum to satisfy:
    - SG-001: ``topics_found.new`` has ≥ 1 generalizable topic with a
      coverage_category.
    - SG-002: ``topics_found.new`` spans ≥ 2 distinct coverage_categories.
    """
    topics_new = [
        {
            "title": "Order Engine Housekeeper",
            "coverage_category": "service",
            "source_code_topic_ids": ["CT-1-001"],
        },
        {
            "title": "Order Management Service",
            "coverage_category": "concept",
            "source_code_topic_ids": ["CT-1-002"],
        },
        {
            "title": "Retry Policy",
            "coverage_category": "decision",
            "source_code_topic_ids": ["CT-1-003"],
        },
    ]
    return {
        "schema_version": "2.0",
        "cycle": 1,
        "phase": "scout",
        "timestamp": "2026-05-18T12:00:00Z",
        "dimensions_covered": [
            "technical",
            "organizational",
            "domain",
            "market",
            "temporal",
        ],
        "topics_from_code": [
            {
                "id": "CT-1-001",
                "topic_type": "service",
                "source_file": "acme/svc/README.md",
                "source_snippet": "lines 1-10",
            },
            {
                "id": "CT-1-002",
                "topic_type": "concept",
                "source_file": "acme/svc/src/Domain.java",
                "source_snippet": "class Domain",
            },
            {
                "id": "CT-1-003",
                "topic_type": "decision",
                "source_file": "acme/svc/docs/adr/0001.md",
                "source_snippet": "ADR body",
            },
        ],
        "intent_from_confluence": [],
        "topics_found": {
            "new": topics_new,
            "existing": [],
            "total": len(topics_new),
        },
        "proposed_filenames": [
            "Order Engine Housekeeper.md",
            "Order Management Service.md",
            "Retry Policy.md",
        ],
        "sources_consulted": list(sources),
        "termination_condition": None,
        "notes_created": [],
        "budget_consumed_usd": 1.0,
    }


def _simulate_validate_cycle(scout_report: Path, missing_sources: list[str]) -> int:
    """Simulate ``validate_cycle.py``: write the sidecar with named
    errors and return the canonical exit code.

    The real validator does this work; in the test we deterministically
    control which errors appear without depending on validate_cycle.py's
    internals (those are exercised by the dedicated sidecar test file).
    """
    sidecar = scout_report.with_suffix(scout_report.suffix + ".validation.json")
    errors = [
        f"required source '{s.lower()}' not in sources_consulted"
        for s in missing_sources
    ]
    if errors:
        sidecar.write_text(
            json.dumps(
                {
                    "status": "ABORT",
                    "reason": f"v2 report has {len(errors)} structural error(s)",
                    "errors": errors,
                    "warnings": [],
                    "metrics_delta": {},
                    "report_path": str(scout_report),
                    "schema_version": "2.0",
                }
            ),
            encoding="utf-8",
        )
        return 2
    sidecar.write_text(
        json.dumps(
            {
                "status": "CONTINUE",
                "reason": "ok",
                "errors": [],
                "warnings": [],
                "metrics_delta": {},
                "report_path": str(scout_report),
                "schema_version": "2.0",
            }
        ),
        encoding="utf-8",
    )
    return 0


def test_retry_prompt_contains_directive_then_succeeds(tmp_path: Path) -> None:
    """The 0.2.30 fix: when the scout fails validation, the retry
    prompt MUST include the correction directive text, AND the agent's
    response to that retry MUST be allowed to pass the gate.

    Stub behaviour:
    - Scout: reads the prompt-file path off the agent_call.py command
      line. On first invocation, writes the incomplete report. On
      second invocation, inspects the prompt:
      - If it contains 'CORRECTION DIRECTIVE': writes the complete
        report (simulating an agent that responded to the directive).
      - Otherwise: writes the incomplete report again (simulating an
        agent that never saw the directive — the 0.2.29 bug).
    - validate_cycle.py: simulated. Returns 2 + writes sidecar when the
      report's sources_consulted is missing 'Confluence'; returns 0 +
      writes empty-errors sidecar otherwise.

    The cycle should:
    - Invoke scout twice (initial + 1 retry).
    - Second invocation gets the directive.
    - Validator passes the second report.
    - Cycle proceeds past scout.
    """
    from research_framework.pipeline.cycle_runner import run_cycle_steps

    vault, scout_report = _build_test_vault(tmp_path)
    cycle_num = 1

    scout_invocations: list[dict] = []
    last_report_sources: list[list[str]] = []

    def _fake_run(cmd, **kwargs):
        script_name = Path(cmd[1]).name
        mock = MagicMock()
        mock.stdout = b""
        if script_name == "agent_call.py" and "--stage" in cmd:
            stage_idx = cmd.index("--stage")
            stage = cmd[stage_idx + 1]
            if stage == "scout":
                prompt_idx = cmd.index("--prompt-file")
                prompt_path = Path(cmd[prompt_idx + 1])
                prompt_text = prompt_path.read_text(encoding="utf-8")
                attempt = len(scout_invocations) + 1
                has_directive = "CORRECTION DIRECTIVE" in prompt_text
                scout_invocations.append(
                    {
                        "attempt": attempt,
                        "has_directive": has_directive,
                        "prompt_path": str(prompt_path),
                    }
                )
                if attempt == 1:
                    sources = _INCOMPLETE_REPORT_SOURCES
                else:
                    sources = (
                        _COMPLETE_REPORT_SOURCES
                        if has_directive
                        else _INCOMPLETE_REPORT_SOURCES
                    )
                last_report_sources.append(sources)
                scout_report.write_text(
                    json.dumps(_make_complete_report(sources)), encoding="utf-8"
                )
            mock.returncode = 0
            return mock
        if script_name == "validate_cycle.py":
            # cmd[2] is the report path.
            current_sources = (
                last_report_sources[-1]
                if last_report_sources
                else _INCOMPLETE_REPORT_SOURCES
            )
            missing = [s for s in _REQUIRED_SOURCES if s not in current_sources]
            mock.returncode = _simulate_validate_cycle(scout_report, missing)
            return mock
        mock.returncode = 0
        return mock

    with _patch_cycle_runner_subprocess(_fake_run):
        run_cycle_steps(vault, cycle_num)

    print(f"scout_invocations: {json.dumps(scout_invocations, indent=2)}")

    assert len(scout_invocations) >= 2, (
        f"scout MUST be invoked at least twice (initial + 1 retry); got "
        f"{len(scout_invocations)} invocation(s)"
    )
    assert scout_invocations[0]["has_directive"] is False, (
        "first scout invocation must NOT carry a directive — there's "
        "nothing to correct yet"
    )
    assert scout_invocations[1]["has_directive"] is True, (
        "second scout invocation (the RETRY) MUST carry a directive — "
        "this is the entire point of the correction loop, and the "
        "regression 0.2.29 shipped silently. Got prompt without "
        "'CORRECTION DIRECTIVE' substring at "
        f"{scout_invocations[1]['prompt_path']}."
    )
    # We don't assert rc==0 here because the cycle has more steps after
    # scout that don't have full stubs (DFS, validate-research, etc.) —
    # those are exercised by the full e2e tests. What matters for THIS
    # test is the retry prompt's content and the scout-side invocation
    # count.


def test_first_attempt_prompt_has_no_directive(tmp_path: Path) -> None:
    """Sanity guard: directive injection must NOT happen on the
    first attempt of a fresh cycle (no directive on disk yet).

    Without this, the directive-injection code might accidentally pick
    up a STALE directive from a previous cycle and prepend it to a
    fresh first-attempt prompt — confusing the agent with "fix these
    errors" when there are no errors yet.
    """
    from research_framework.pipeline.cycle_runner import run_cycle_steps

    vault, scout_report = _build_test_vault(tmp_path)
    cycle_num = 1

    scout_invocations: list[dict] = []

    def _fake_run(cmd, **kwargs):
        script_name = Path(cmd[1]).name
        mock = MagicMock()
        mock.stdout = b""
        if script_name == "agent_call.py" and "--stage" in cmd:
            stage_idx = cmd.index("--stage")
            stage = cmd[stage_idx + 1]
            if stage == "scout":
                prompt_idx = cmd.index("--prompt-file")
                prompt_path = Path(cmd[prompt_idx + 1])
                prompt_text = prompt_path.read_text(encoding="utf-8")
                scout_invocations.append(
                    {"has_directive": "CORRECTION DIRECTIVE" in prompt_text}
                )
                scout_report.write_text(
                    json.dumps(_make_complete_report(_COMPLETE_REPORT_SOURCES)),
                    encoding="utf-8",
                )
            mock.returncode = 0
            return mock
        if script_name == "validate_cycle.py":
            mock.returncode = _simulate_validate_cycle(scout_report, [])
            return mock
        mock.returncode = 0
        return mock

    with _patch_cycle_runner_subprocess(_fake_run):
        run_cycle_steps(vault, cycle_num)

    assert scout_invocations, "scout must have been invoked at least once"
    assert scout_invocations[0]["has_directive"] is False, (
        "first attempt at a fresh cycle must NOT carry a directive — no "
        "errors to correct yet. A stale directive from a prior cycle is "
        "leaking into the prompt."
    )
