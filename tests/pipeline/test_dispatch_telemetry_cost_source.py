"""Spec 028 rc3 amendment (A2 / FR-028B) — run-report total reflects estimated
codex spend.

A codex cycle whose sidecars carry ``cost_source: "estimated"`` (the spec-033
fallback, never a silent ``$0``) must still roll up into the run report's
``Total cost`` headline. This is the lens spec 063 GA-005 (cost gate) consumes:
a $0 total on a real codex run is a FAIL, so the estimate has to land here.
"""

from __future__ import annotations

import json
from pathlib import Path

from research_framework.pipeline.run_report import write_run_report


def _write_estimated_sidecar(
    vault: Path, cycle: int, stage: str, cost_usd: float
) -> None:
    c3 = f"{cycle:03d}"
    cycles = vault / "_pipeline" / "cycles"
    # Mark the cycle as "ran" so _discover_cycles includes it.
    (cycles).mkdir(parents=True, exist_ok=True)
    (cycles / f"cycle-{c3}-timings.json").write_text(
        json.dumps({"stages": []}), encoding="utf-8"
    )
    agent_calls = cycles / f"cycle-{c3}" / "agent-calls"
    agent_calls.mkdir(parents=True, exist_ok=True)
    (agent_calls / f"{stage}.json").write_text(
        json.dumps(
            {
                "schema_version": "1.2",
                "stage": stage,
                "agent": "codex",
                "agent_kind": "real",
                "tier": "standard",
                "status": "ok",
                "exit_code": 0,
                "cost_usd": cost_usd,
                "cost_source": "estimated",
                "tokens_in": 2048,
                "tokens_out": 0,
                "latency_ms": 1000,
                "started_at": "2026-06-01T00:00:00.000Z",
                "completed_at": "2026-06-01T00:00:01.000Z",
                "cycle": cycle,
            }
        ),
        encoding="utf-8",
    )


def test_total_cost_reflects_estimated_codex_spend(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write_estimated_sidecar(vault, cycle=2, stage="scout", cost_usd=0.42)
    _write_estimated_sidecar(vault, cycle=2, stage="research", cost_usd=1.08)

    report = write_run_report(vault, final_exit_code=0, final_exit_reason="done")
    text = report.read_text(encoding="utf-8")

    # The two estimated sidecars sum to $1.50 — the headline must not show $0.
    assert "Total cost: **$1.50**" in text
    assert "$0.00" not in text.split("## Per-cycle", 1)[0]


def test_estimated_sidecar_does_not_break_json_companion(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write_estimated_sidecar(vault, cycle=1, stage="scout", cost_usd=0.25)

    write_run_report(
        vault,
        final_exit_code=0,
        final_exit_reason="done",
        cycle_budget_configured=20,
        cycle_budget_source="settings",
    )
    payload = json.loads(
        (vault / "_pipeline" / "run-report.json").read_text(encoding="utf-8")
    )
    # The new cost_source field must not perturb the additive JSON companion.
    assert payload["final_exit_code"] == 0
    assert payload["cycle_budget"]["configured"] == 20
