"""Tier-2 contract tests for agent-call sidecar v1.1/v1.2 (spec 028 + rc3).

The rc3 amendment bumped the canonical writer to ``schema_version: "1.2"`` with
an additive ``cost_source`` discriminator. The contract is back-compatible:
v1.1 (no ``cost_source``) and v1.2 sidecars both validate.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "agent_call.py"
SCHEMA_PATH = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "contracts"
    / "agent-call-sidecar-1.1.schema.json"
)


def _load_agent_call():
    spec = importlib.util.spec_from_file_location("agent_call", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["agent_call"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def ac():
    return _load_agent_call()


def _required_keys() -> frozenset[str]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return frozenset(schema["required"])


def _validate_required_fields(payload: dict) -> list[str]:
    missing = sorted(_required_keys() - set(payload.keys()))
    errors: list[str] = []
    if missing:
        errors.append(f"missing required: {missing}")
    if payload.get("schema_version") not in ("1.1", "1.2"):
        errors.append("schema_version must be 1.1 or 1.2")
    if payload.get("agent_kind") not in ("fake", "real"):
        errors.append("agent_kind must be fake or real")
    if payload.get("status") not in ("ok", "failed"):
        errors.append("status must be ok or failed")
    # cost_source is additive (v1.2); when present it must be one of the
    # canonical literals. "runtime_tokens" (spec 052) records a flat-rate
    # runtime that emits real token counts but no dollar figure (dollar is
    # estimated downstream).
    if "cost_source" in payload and payload["cost_source"] not in (
        "runtime",
        "runtime_tokens",
        "estimated",
        "none",
    ):
        errors.append("cost_source must be runtime, runtime_tokens, estimated, or none")
    return errors


@pytest.mark.parametrize(
    "payload",
    [
        {
            "schema_version": "1.1",
            "stage": "plan_narrator",
            "agent": "claude",
            "agent_kind": "real",
            "tier": "standard",
            "status": "ok",
            "exit_code": 0,
            "cost_usd": 0.0123,
            "tokens_in": 100,
            "tokens_out": 50,
            "latency_ms": 1200,
            "started_at": "2026-05-26T17:40:35.123Z",
            "completed_at": "2026-05-26T17:40:36.323Z",
            "cycle": 7,
        },
        {
            "schema_version": "1.1",
            "stage": "note_writer",
            "agent": "fake",
            "agent_kind": "fake",
            "tier": "standard",
            "status": "failed",
            "exit_code": 2,
            "cost_usd": 0.0,
            "tokens_in": 0,
            "tokens_out": 0,
            "latency_ms": 500,
            "started_at": "2000-01-01T00:00:00Z",
            "completed_at": "2000-01-01T00:00:01Z",
            "cycle": 1,
            "stderr_excerpt": "timed out",
        },
        {
            "schema_version": "1.2",
            "stage": "research",
            "agent": "codex",
            "agent_kind": "real",
            "tier": "standard",
            "status": "ok",
            "exit_code": 0,
            "cost_usd": 0.5,
            "cost_source": "estimated",
            "tokens_in": 2048,
            "tokens_out": 0,
            "latency_ms": 3000,
            "started_at": "2026-06-01T00:00:00.000Z",
            "completed_at": "2026-06-01T00:00:03.000Z",
            "cycle": 4,
        },
        {
            # spec 052: cursor-agent is a flat-rate runtime — real tokens,
            # estimated dollar, cost_source="runtime_tokens".
            "schema_version": "1.2",
            "stage": "research",
            "agent": "cursor-agent",
            "agent_kind": "real",
            "tier": "standard",
            "status": "ok",
            "exit_code": 0,
            "cost_usd": 0.31,
            "cost_source": "runtime_tokens",
            "tokens_in": 4096,
            "tokens_out": 512,
            "latency_ms": 4200,
            "started_at": "2026-06-08T00:00:00.000Z",
            "completed_at": "2026-06-08T00:00:04.200Z",
            "cycle": 1,
        },
    ],
)
def test_valid_sidecar_payloads(payload: dict) -> None:
    assert _validate_required_fields(payload) == []


def test_invalid_cost_source_rejected() -> None:
    payload = {
        "schema_version": "1.2",
        "stage": "scout",
        "agent": "codex",
        "agent_kind": "real",
        "tier": "standard",
        "status": "ok",
        "exit_code": 0,
        "cost_usd": 0.0,
        "cost_source": "codex",  # retired draft literal — must be rejected
        "tokens_in": 0,
        "tokens_out": 0,
        "latency_ms": 0,
        "started_at": "2026-06-01T00:00:00.000Z",
        "completed_at": "2026-06-01T00:00:01.000Z",
        "cycle": 1,
    }
    assert "cost_source must be runtime, runtime_tokens, estimated, or none" in (
        _validate_required_fields(payload)
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": "1.0", "stage": "scout"},
        {"schema_version": "1.1", "stage": "scout"},
    ],
)
def test_reject_incomplete_payloads(payload: dict) -> None:
    assert _validate_required_fields(payload)


# --- #295: validate a REAL sidecar (the actual production builder/writer,
# not a hand-typed literal) against the schema via jsonschema, not the
# hand-rolled `_validate_required_fields` above. jsonschema was not a
# dependency anywhere in the repo before this; every one of the 20 committed
# JSON Schemas was prose only.


def test_real_built_sidecar_payload_validates_against_schema(ac) -> None:
    """`_build_sidecar_v11_payload` is the actual production payload builder

    (used by every real dispatch, not a test fixture). Its output must
    satisfy the schema jsonschema-strict, not just the hand-rolled required-
    field check above.
    """
    import jsonschema

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    payload = ac._build_sidecar_v11_payload(
        stage="note_writer",
        agent="claude",
        agent_kind="real",
        tier="standard",
        status="ok",
        exit_code=0,
        cost_usd=0.042,
        tokens_in=321,
        tokens_out=64,
        latency_ms=1500,
        started_at="2026-09-07T00:00:00.000Z",
        completed_at="2026-09-07T00:00:01.500Z",
        cycle=3,
    )
    jsonschema.validate(payload, schema)


def test_real_written_sidecar_file_validates_against_schema(ac, tmp_path: Path) -> None:
    """`_emit_sidecar_v11` is the real write path (atomic temp-file +

    os.replace); read the file it actually produces back off disk and
    validate that, not an in-memory payload.
    """
    import jsonschema

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    sidecar_path = tmp_path / "agent-calls" / "note_writer.json"
    ac._emit_sidecar_v11(
        sidecar_path,
        stage="note_writer",
        agent="claude",
        agent_kind="real",
        tier="standard",
        status="ok",
        exit_code=0,
        cost_usd=0.042,
        tokens_in=321,
        tokens_out=64,
        latency_ms=1500,
        started_at="2026-09-07T00:00:00.000Z",
        completed_at="2026-09-07T00:00:01.500Z",
        cycle=3,
    )
    written = json.loads(sidecar_path.read_text(encoding="utf-8"))
    jsonschema.validate(written, schema)


class TestAllocateSidecarPath:
    def test_empty_dir_uses_stage_json(self, ac, tmp_path: Path) -> None:
        cycle_dir = tmp_path / "cycle-001"
        path = ac._allocate_sidecar_path(cycle_dir, "plan_narrator")
        assert path == cycle_dir / "agent-calls" / "plan_narrator.json"

    def test_existing_stage_gets_suffix_2(self, ac, tmp_path: Path) -> None:
        cycle_dir = tmp_path / "cycle-001"
        calls = cycle_dir / "agent-calls"
        calls.mkdir(parents=True)
        (calls / "plan_narrator.json").write_text("{}", encoding="utf-8")
        path = ac._allocate_sidecar_path(cycle_dir, "plan_narrator")
        assert path.name == "plan_narrator-2.json"

    def test_batch_files_do_not_advance_per_call_suffix(
        self, ac, tmp_path: Path
    ) -> None:
        cycle_dir = tmp_path / "cycle-001"
        calls = cycle_dir / "agent-calls"
        calls.mkdir(parents=True)
        (calls / "note_writer.json").write_text("{}", encoding="utf-8")
        (calls / "note_writer-batch-1.json").write_text("{}", encoding="utf-8")
        (calls / "note_writer-batch-2.json").write_text("{}", encoding="utf-8")
        path = ac._allocate_sidecar_path(cycle_dir, "note_writer")
        assert path.name == "note_writer-2.json"


class TestSidecarTimestamps:
    def test_fake_sentinel_bytes(self, ac) -> None:
        started, completed = ac._sidecar_timestamps(
            "fake", started_mono=0.0, completed_mono=1.0
        )
        assert started == "2000-01-01T00:00:00Z"
        assert completed == "2000-01-01T00:00:01Z"

    def test_real_uses_millisecond_precision(self, ac) -> None:
        started, completed = ac._sidecar_timestamps(
            "real", started_mono=0.0, completed_mono=0.5
        )
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", started)
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", completed)


class TestConsumeClaudeStream:
    def test_maps_result_event_to_cost_and_tokens(self, ac) -> None:
        lines = [
            json.dumps(
                {
                    "type": "result",
                    "result": "done",
                    "total_cost_usd": 0.042,
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                }
            ),
        ]
        stream = ac._consume_claude_stream(iter(lines))
        assert stream.cost_usd == pytest.approx(0.042)
        assert stream.tokens_in == 10
        assert stream.tokens_out == 5
