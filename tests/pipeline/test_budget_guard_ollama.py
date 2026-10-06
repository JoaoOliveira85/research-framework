"""Spec 047 v1 — budget-guard parity for the ollama runtime + the v1.2 sidecar fix.

Two things under test:

1. **Footgun regression**: ``list_sidecars_v11`` used to hard-match
   ``schema_version == "1.1"`` while the writer emits ``"1.2"`` (spec 028 rc3
   added ``cost_source``). That silently DROPPED every modern sidecar from the
   budget tally (``actual_usd`` stuck at 0). The consumer now accepts the whole
   additive ``1.x`` line.
2. **Ollama is local/unmetered**: its $0 sidecars contribute nothing to the
   dollar tally and its tokens are NOT counted toward the metered-token cap
   (unlike codex/cursor).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.pipeline.budget_guard import (
    CycleSpendTally,
    list_sidecars_v11,
    refresh_actuals,
)


def _write_sidecar(
    vault: Path,
    cycle: int,
    stage: str,
    agent: str,
    *,
    version: str,
    cost: float,
    tin: int,
    tout: int,
) -> None:
    d = vault / "_pipeline" / "cycles" / f"cycle-{cycle:03d}" / "agent-calls"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stage}.json").write_text(
        json.dumps(
            {
                "schema_version": version,
                "stage": stage,
                "agent": agent,
                "agent_kind": "real",
                "tier": "normal",
                "status": "ok",
                "exit_code": 0,
                "cost_usd": cost,
                "cost_source": "runtime",
                "tokens_in": tin,
                "tokens_out": tout,
                "latency_ms": 0,
                "started_at": "2026-01-01T00:00:00Z",
                "completed_at": "2026-01-01T00:00:01Z",
                "cycle": cycle,
            }
        ),
        encoding="utf-8",
    )


def test_v12_sidecar_is_now_tallied(tmp_path: Path) -> None:
    """Regression: a 1.2 sidecar (what the writer emits today) must be counted.

    Before the fix, ``list_sidecars_v11`` returned [] for 1.2 files and the
    dollar tally was a silent $0 for every runtime.
    """
    vault = tmp_path / "vault"
    _write_sidecar(
        vault, 1, "note_writer", "claude", version="1.2", cost=0.42, tin=10, tout=5
    )
    assert len(list_sidecars_v11(vault, 1)) == 1
    tally = CycleSpendTally(cycle_num=1)
    refresh_actuals(vault, 1, tally)
    assert tally.actual_usd == pytest.approx(0.42)


def test_v11_sidecar_still_tallied(tmp_path: Path) -> None:
    """Back-compat: legacy 1.1 sidecars keep counting after the fix."""
    vault = tmp_path / "vault"
    _write_sidecar(vault, 1, "scout", "codex", version="1.1", cost=0.10, tin=4, tout=2)
    tally = CycleSpendTally(cycle_num=1)
    refresh_actuals(vault, 1, tally)
    assert tally.actual_usd == pytest.approx(0.10)
    assert tally.actual_codex_tokens == 6  # codex stays a metered-token agent


def test_v10_sidecar_is_excluded(tmp_path: Path) -> None:
    """Boundary lock: the fix widens 1.1→1.x but must STILL drop legacy 1.0
    (spec 025, pre the required agent_kind/status/cycle fields). Without this
    pin, a future ``startswith('1.')`` regression would silently re-admit 1.0."""
    vault = tmp_path / "vault"
    _write_sidecar(
        vault, 1, "note_writer", "claude", version="1.0", cost=0.99, tin=10, tout=5
    )
    assert list_sidecars_v11(vault, 1) == []
    tally = CycleSpendTally(cycle_num=1)
    refresh_actuals(vault, 1, tally)
    assert tally.actual_usd == 0.0


def test_ollama_sidecar_zero_dollar_and_unmetered_tokens(tmp_path: Path) -> None:
    """Ollama is local: $0 contributes nothing, and its tokens are NOT metered
    (it has no external token cap, unlike codex/cursor)."""
    vault = tmp_path / "vault"
    _write_sidecar(
        vault, 1, "scout", "ollama", version="1.2", cost=0.0, tin=500, tout=300
    )
    tally = CycleSpendTally(cycle_num=1)
    refresh_actuals(vault, 1, tally)
    assert tally.actual_usd == 0.0
    assert tally.actual_codex_tokens == 0
