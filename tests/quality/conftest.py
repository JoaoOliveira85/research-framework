"""Shared helpers for spec-022 tier-6 quality harness tests."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from research_framework.quality.models import CycleOutput, Fixture
from research_framework.quality.runner import (
    HARNESS_BUDGET_CAP_USD,
    HARNESS_CYCLE_CEILING,
    HARNESS_MAX_CYCLES,
    isolate_fixture,
    resolve_fixture,
)

# One source of the harness's cycle count. The pytest wrapper and
# ``runner._invoke_cycles`` disagreed (3 vs 1) until issue #268.
_MAX_CYCLES = HARNESS_MAX_CYCLES

# …and one source of its budget, for the same reason. Both drivers used to
# inherit ``run_cycle_steps``' hardcoded ``10.0`` / ``5``; issue #233 removed
# those, so the number has to be stated, and stated once.
_BUDGET_CAP_USD = HARNESS_BUDGET_CAP_USD
_CYCLE_CEILING = HARNESS_CYCLE_CEILING


def _fixture_env(name: str) -> dict[str, str]:
    """Per-fixture fake-agent scenario env (024 US2 stage names).

    Every registered fixture gets the same table, and that is the honest
    shape: a quality fixture's failure mode lives in its committed
    ``fake_agent_responses/scout/happy.json``, not in a scenario switch.
    source-poor used to ask for ``note_writer=substitution`` and
    ``verifier=reject``; the fake has no ``substitution`` scenario (it exits
    2 on the pair), and the cycle aborts at SG-002 straight after scout, so
    neither stage was ever reached. Both were decoration, and the release
    runner — which sets no scenario env at all — proved it by producing the
    same three SG-002 trips without them (issue #265).

    ``tests/quality/unit/test_fixture_scenario_env.py`` now validates every
    value here against the fake, in the fast tier, so a scenario name that
    does not exist cannot sit here unnoticed again.
    """
    del name  # kept: callers pass a fixture name and the signature is the seam
    return {
        "FAKE_AGENT_SCOUT_SCENARIO": "happy",
        "FAKE_AGENT_NOTE_WRITER_SCENARIO": "happy",
        "FAKE_AGENT_VERIFIER_SCENARIO": "accept",
        "FAKE_AGENT_RESEARCH_PLAN_NARRATOR_SCENARIO": "happy",
        "FAKE_AGENT_PROBE_RETRIEVAL_SCENARIO": "happy",
    }


def run_fixture_cycles(
    name: str,
    *,
    tmp_path: Path | None = None,
    max_cycles: int = _MAX_CYCLES,
) -> tuple[list[CycleOutput], Fixture]:
    """Drive ``run_cycle_steps`` for a committed quality fixture against a copy.

    Spec 026 FR-001/FR-002: the cycle runs against an isolated ``tmp_path`` copy
    so the tracked fixture tree under ``tests/fixtures/quality/`` is never
    mutated. Returns ``(outputs, work_fixture)`` — callers that compute metrics
    MUST use ``work_fixture`` (the copy the cycle wrote to), not
    ``resolve_fixture(name)`` (the un-mutated source).

    When *tmp_path* is omitted a private temp dir is used; prefer passing
    pytest's ``tmp_path`` so it is garbage-collected (FR-007) and a crash leaves
    it in place for debugging (FR-006).
    """
    from research_framework.pipeline.cycle_runner import (
        get_last_cycle_results,
        run_cycle_steps,
    )
    from tests._helpers import fake_agent

    if tmp_path is None:
        tmp_path = Path(tempfile.mkdtemp(prefix=f"quality-{name}-"))
    fixture = isolate_fixture(resolve_fixture(name), Path(tmp_path))
    # Spec 025 A1 / Principle IV: install the fake-agent shim at
    # <copy>/scripts/agent_call.py so plan_narrator's in-process
    # bootstrap loads the shim (which exposes a ``dispatch`` stub)
    # instead of the repo's real agent_call (which spawns ``claude``).
    # Without this the test_fake_agent_interception guard catches a
    # live LLM call on every fixture cycle. Installing into the COPY (not
    # the committed tree) means an out-of-repo tmp_path correctly bakes the
    # abs repo root (Strategy 3), so the shim still resolves fake_agent.
    fake_agent.install_shim(fixture.vault_dir / "scripts")
    outputs: list[CycleOutput] = []
    for cycle in range(1, max_cycles + 1):
        exit_code = run_cycle_steps(
            fixture.vault_dir,
            cycle,
            budget_cap=_BUDGET_CAP_USD,
            max_cycles=_CYCLE_CEILING,
        )
        tag = f"{cycle:03d}"
        pipeline = fixture.vault_dir / "_pipeline"
        qr = pipeline / "cycles" / f"cycle-{tag}-quality-report.json"
        results = get_last_cycle_results(cycle)
        scout_result = results.get("scout")
        research_result = results.get("research")
        postprocess_result = results.get("postprocess")
        # The typed scout result is the ONLY source, exactly as in
        # ``runner._cycle_output``. A previous fallback re-derived SG-002 from
        # the scout JSON when the typed result carried no trip — i.e. it
        # re-evaluated the gate from the gate's own input, so the source-poor
        # assertion could pass without the gate ever having fired, and the
        # pytest wrapper reported trips the release runner never would
        # (issue #265).
        sg_trips = _sg_trips_from_scout_result(scout_result)
        scout_path = pipeline / "cycles" / f"cycle-{tag}-scout.json"
        scout_topics = _code_derived_topics_from_scout(scout_path)
        notes_written = (
            list(research_result.notes_written) if research_result is not None else []
        )
        outputs.append(
            CycleOutput(
                fixture_name=name,
                cycle_number=cycle,
                exit_code=exit_code,
                quality_report_path=qr,
                research_report_path=pipeline / "cycles" / f"cycle-{tag}-research.json",
                notes_written=notes_written,
                scout_topics=scout_topics,
                sg_trips=sg_trips,
                scout_result=scout_result,
                research_result=research_result,
                postprocess_result=postprocess_result,
            )
        )
    return outputs, fixture


def _sg_trips_from_scout_result(scout_result: object | None) -> list[str]:
    if scout_result is None:
        return []
    trips = getattr(scout_result, "sg_trips", None) or []
    out: list[str] = []
    for trip in trips:
        gid = str(getattr(trip, "gate_id", "") or "").strip()
        status = str(getattr(trip, "status", "") or "").upper()
        if gid and status in {"FAIL", "WARN"}:
            out.append(gid)
    return out


@pytest.fixture
def quality_fixture_env(monkeypatch: pytest.MonkeyPatch):
    """Apply fake-agent env defaults; tests set fixture name via parameter."""

    def _apply(name: str) -> None:
        for key, val in _fixture_env(name).items():
            monkeypatch.setenv(key, val)

    return _apply


def _code_derived_topics_from_scout(scout_path: Path) -> list[dict[str, Any]]:
    if scout_path.is_file():
        doc = json.loads(scout_path.read_text(encoding="utf-8"))
    else:
        vault_dir = scout_path.parents[2]
        canned = vault_dir / "fake_agent_responses" / "scout" / "happy.json"
        if not canned.is_file():
            return []
        doc = json.loads(canned.read_text(encoding="utf-8"))
    rows = list((doc.get("topics_found") or {}).get("new") or [])
    return [
        r for r in rows if isinstance(r, dict) and r.get("discovery") == "code-derived"
    ]


def count_code_derived_in_canned_scout(fixture_name: str) -> int:
    """Structural signal from committed fake_agent_responses (pre-loader)."""
    path = (
        resolve_fixture(fixture_name).fake_agent_responses_dir / "scout" / "happy.json"
    )
    doc = json.loads(path.read_text(encoding="utf-8"))
    new_rows = (doc.get("topics_found") or {}).get("new") or []
    return sum(
        1
        for row in new_rows
        if isinstance(row, dict) and row.get("discovery") == "code-derived"
    )
