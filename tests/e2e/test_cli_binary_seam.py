"""Tier-5: a whole cycle on the CLI-binary seam (issue #270).

``tests/_helpers/test_fake_cli_binary.py`` proves one dispatch. This proves
the tier the issue actually names: ``run_cycle_steps`` end to end with the
vault's REAL ``scripts/agent_call.py``, only the leaf ``claude`` binary faked.
Every sidecar under ``agent-calls/`` here was written by production code.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.pipeline.cycle_runner import run_cycle_steps
from tests._helpers import fake_cli_binary
from tests._helpers.vault_factory import build_minimal_vault, install_bundled_skill

pytestmark = pytest.mark.e2e


def test_a_cycle_runs_with_only_the_leaf_binary_faked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    vault = build_minimal_vault(
        tmp_path,
        num_categories=1,
        num_targets_per_category=3,
        max_cycles=1,
        install_fake_agent=False,
    )
    install_bundled_skill(vault, "scout")
    fake_cli_binary.activate(monkeypatch, tmp_path / "bin")

    rc = run_cycle_steps(vault, cycle_num=1, budget_cap=50.0, max_cycles=1)

    assert rc in (0, 1)
    sidecars = sorted(
        (vault / "_pipeline" / "cycles" / "cycle-001" / "agent-calls").glob("*.json")
    )
    assert sidecars, "the real dispatcher must have written at least one sidecar"
    payloads = [json.loads(p.read_text(encoding="utf-8")) for p in sidecars]
    assert all(p["agent"] == "claude" for p in payloads), payloads
    assert all(p["agent_kind"] == "real" for p in payloads), (
        "with the real dispatcher in the vault the fake-shim marker is gone, so "
        "these are the production timestamp/cost branches — the point of #270"
    )
