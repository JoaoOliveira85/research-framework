"""Opt-in SC-001: dispatch vs CLI cost parity (@pytest.mark.live_llm)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "agent_call.py"


@pytest.mark.live_llm
def test_dispatch_cost_within_five_percent_of_cli(tmp_path: Path) -> None:
    """Requires real ``claude`` on PATH — skipped in CI fast loop."""
    spec = importlib.util.spec_from_file_location("agent_call", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    ac = importlib.util.module_from_spec(spec)
    sys.modules["agent_call"] = ac
    spec.loader.exec_module(ac)

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text(
        "default_executor:\n  type: cli\n  runtime: claude\n  model: sonnet\n",
        encoding="utf-8",
    )
    cycle_dir = vault / "_pipeline" / "cycles" / "cycle-001"
    cycle_dir.mkdir(parents=True)
    prompt = "Reply with exactly: ok"
    cli_sidecar = cycle_dir / "agent-calls" / "cli.json"

    rc_cli = ac.run(vault, "scout", None, cli_sidecar)
    assert rc_cli == 0
    cli_cost = float(
        __import__("json").loads(cli_sidecar.read_text(encoding="utf-8"))["cost_usd"]
    )

    result = ac.dispatch("scout", prompt, vault_dir=vault, cycle_dir=cycle_dir)
    assert result.exit_code == 0
    dispatch_path = cycle_dir / "agent-calls" / "scout.json"
    dispatch_cost = float(
        __import__("json").loads(dispatch_path.read_text(encoding="utf-8"))["cost_usd"]
    )
    if cli_cost > 0:
        assert abs(dispatch_cost - cli_cost) / cli_cost <= 0.05
