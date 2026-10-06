"""Tier-3: multi-batch sidecar summation (spec 028 US3 / SC-004)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.pipeline.orchestrator import _sum_sidecar_costs


def _sidecar(cost: float, *, batch: int | None = None) -> dict:
    payload = {
        "schema_version": "1.1",
        "stage": "note_writer",
        "agent": "fake",
        "agent_kind": "fake",
        "tier": "standard",
        "status": "ok",
        "exit_code": 0,
        "cost_usd": cost,
        "tokens_in": 0,
        "tokens_out": 0,
        "latency_ms": 0,
        "started_at": "2000-01-01T00:00:00Z",
        "completed_at": "2000-01-01T00:00:01Z",
        "cycle": 1,
    }
    if batch is not None:
        payload["batch_index"] = batch
    return payload


def test_sum_includes_all_batch_sidecars(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    calls = vault / "_pipeline" / "cycles" / "cycle-001" / "agent-calls"
    calls.mkdir(parents=True)
    (calls / "note_writer-batch-1.json").write_text(
        json.dumps(_sidecar(0.4, batch=1)), encoding="utf-8"
    )
    (calls / "note_writer-batch-2.json").write_text(
        json.dumps(_sidecar(0.6, batch=2)), encoding="utf-8"
    )
    total = _sum_sidecar_costs(vault, 1)
    assert total == pytest.approx(1.0)
