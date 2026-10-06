"""FR-024 per-call audit records for bridge-initiated agent subprocesses.

Writes full prompt/response records without modifying ``scripts/agent_call.py``.
Spec 028 sidecar v1.1 may coexist in the same ``agent-calls/`` directory.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .cache import atomic_write_json


@dataclass
class AgentCallRecord:
    stage: str
    call_id: str
    timestamp: str
    model: str
    prompt: str
    response: str
    latency_ms: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    tier: str | None = None
    error: str | None = None
    retry_attempt: int | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "stage": self.stage,
            "call_id": self.call_id,
            "timestamp": self.timestamp,
            "model": self.model,
            "prompt": self.prompt,
            "response": self.response,
            "latency_ms": self.latency_ms,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": self.cost_usd,
            "tier": self.tier,
            "error": self.error,
        }
        if self.retry_attempt is not None:
            data["retry_attempt"] = self.retry_attempt
        return data


def agent_calls_dir(vault_dir: Path, cycle: int) -> Path:
    cycle_3 = f"{cycle:03d}"
    path = vault_dir / "_pipeline" / "cycles" / f"cycle-{cycle_3}" / "agent-calls"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_agent_call_record(
    vault_dir: Path,
    cycle: int,
    record: AgentCallRecord,
) -> Path:
    """Write ``AgentCallRecord`` under ``agent-calls/<ts>-<stage>-<call-id>.json``."""
    ts = record.timestamp.replace(":", "").replace("-", "")[:15]
    safe_stage = record.stage.replace("/", "-")
    filename = f"{ts}-{safe_stage}-{record.call_id}.json"
    path = agent_calls_dir(vault_dir, cycle) / filename
    atomic_write_json(path, record.to_dict())
    return path


def record_from_dispatch(
    *,
    stage: str,
    prompt: str,
    response: str,
    model: str,
    tier: str | None,
    latency_ms: int,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: float = 0.0,
    error: str | None = None,
    retry_attempt: int | None = None,
) -> AgentCallRecord:
    return AgentCallRecord(
        stage=stage,
        call_id=str(uuid.uuid4()),
        timestamp=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        model=model,
        tier=tier,
        prompt=prompt,
        response=response,
        latency_ms=latency_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
        error=error,
        retry_attempt=retry_attempt,
    )


def list_agent_call_records(vault_dir: Path, cycle: int) -> list[Path]:
    return sorted(agent_calls_dir(vault_dir, cycle).glob("*.json"))


def load_record(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
