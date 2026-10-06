"""FR-024 agent call logging via source_bridge (no agent_call.py edits)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from research_framework.pipeline.source_bridge.agent_logging import (
    record_from_dispatch,
    write_agent_call_record,
)


def test_agent_call_record_shape_matches_schema(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    record = record_from_dispatch(
        stage="schema_gen",
        prompt="p",
        response="r",
        model="claude-sonnet-5",
        tier="basic",
        latency_ms=10,
        tokens_in=1,
        tokens_out=2,
        cost_usd=0.01,
    )
    path = write_agent_call_record(vault, 1, record)
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in (
        "stage",
        "call_id",
        "timestamp",
        "model",
        "prompt",
        "response",
        "latency_ms",
        "tokens_in",
        "tokens_out",
        "cost_usd",
    ):
        assert key in data
    uuid.UUID(data["call_id"])


def test_prompt_and_response_not_truncated(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    long = "x" * 50_000
    record = record_from_dispatch(
        stage="test",
        prompt=long,
        response=long,
        model="m",
        tier=None,
        latency_ms=1,
    )
    path = write_agent_call_record(vault, 1, record)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["prompt"]) == 50_000
    assert len(data["response"]) == 50_000


def test_agent_call_captures_full_prompt_and_response(tmp_path: Path) -> None:
    test_prompt_and_response_not_truncated(tmp_path)


def test_agent_call_writes_under_agent_calls_directory(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    record = record_from_dispatch(
        stage="scout",
        prompt="a",
        response="b",
        model="m",
        tier="basic",
        latency_ms=0,
    )
    path = write_agent_call_record(vault, 3, record)
    assert "agent-calls" in str(path)
    assert "cycle-003" in str(path)


def test_agent_call_records_tier_and_resolved_model(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    record = record_from_dispatch(
        stage="source_extraction",
        prompt="p",
        response="r",
        model="claude-haiku-4-5",
        tier="basic",
        latency_ms=0,
    )
    path = write_agent_call_record(vault, 1, record)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["tier"] == "basic"
    assert data["model"] == "claude-haiku-4-5"


def test_sc009_record_count_matches_invocation_tally(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    for i in range(3):
        write_agent_call_record(
            vault,
            1,
            record_from_dispatch(
                stage=f"stage_{i}",
                prompt="p",
                response="r",
                model="m",
                tier=None,
                latency_ms=0,
            ),
        )
    calls_dir = vault / "_pipeline" / "cycles" / "cycle-001" / "agent-calls"
    assert len(list(calls_dir.glob("*.json"))) == 3
