"""Spec 069 US3 (FR3) — ``./vault status`` surfaces the stagnant WARN (C3-a).

The WARN must be read from the cycle quality report's ``degraded_sources`` so
status and the quality report agree.
"""

from __future__ import annotations

import json
from pathlib import Path

from research_framework.cli.status import build_status_json
from research_framework.pipeline.stagnant_sources import STAGNANT_PREFIX


def _write_passed_cycle(vault_dir: Path, cycle: int, degraded: list[str]) -> None:
    cycles = vault_dir / "_pipeline" / "cycles"
    cycles.mkdir(parents=True, exist_ok=True)
    (cycles / f"cycle-{cycle:03d}-summary.md").write_text(
        f"Cycle {cycle}: PASS\n", encoding="utf-8"
    )
    (cycles / f"cycle-{cycle:03d}-quality-report.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "cycle_number": cycle,
                "degraded_sources": degraded,
            }
        ),
        encoding="utf-8",
    )


def test_status_surfaces_stagnant_warn(tmp_path):
    vault = tmp_path / "vault"
    line = f"{STAGNANT_PREFIX} `Web`: cold 2 consecutive cycles (role=domain)"
    _write_passed_cycle(vault, 3, degraded=[line])

    status = build_status_json(vault)
    assert line in status["deferred_warnings"]


def test_status_omits_non_stagnant_degraded_entries(tmp_path):
    vault = tmp_path / "vault"
    stagnant = f"{STAGNANT_PREFIX} `Web`: cold 2 consecutive cycles (role=domain)"
    other = "- 2026-06-03 — `GitHub` degraded: auth failed"
    _write_passed_cycle(vault, 3, degraded=[stagnant, other])

    status = build_status_json(vault)
    deferred = status["deferred_warnings"]
    assert stagnant in deferred
    assert other not in deferred


def test_status_no_stagnant_when_clean(tmp_path):
    vault = tmp_path / "vault"
    _write_passed_cycle(vault, 3, degraded=[])

    status = build_status_json(vault)
    assert not any(
        str(w).startswith(STAGNANT_PREFIX) for w in status["deferred_warnings"]
    )
