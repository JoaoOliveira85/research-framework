"""Tier-5 budget pause + resume e2e (spec 033 SC-002).

Runs on the CLI-binary seam (issue #270): the vault keeps its REAL
``scripts/agent_call.py`` and only the leaf ``claude`` binary is faked, so the
pause this test provokes happens around a genuine dispatch — argv, stdin
prompt, stream-json parse, sidecar write — rather than around a stub that had
replaced the dispatcher wholesale.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework.pipeline.budget_guard import budget_marker_path
from research_framework.pipeline.cycle_runner import run_cycle_steps
from tests._helpers import fake_cli_binary
from tests._helpers.vault_factory import build_minimal_vault, install_bundled_skill

pytestmark = pytest.mark.e2e

_EXECUTOR = """
default_executor:
  runtime: claude
  model: sonnet
  timeout_s: 60
"""


def test_mid_cycle_budget_pause_resume_completes_cycle(
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
    (vault / "settings.yaml").write_text(
        """
pipeline:
  max_cycles: 1
  budget_usd: 10.0
limits:
  cycle_budget_usd: 0.05
"""
        + _EXECUTOR,
        encoding="utf-8",
    )
    with pytest.raises(SystemExit):
        run_cycle_steps(vault, cycle_num=1, budget_cap=10.0, max_cycles=1)
    assert budget_marker_path(vault).is_file()

    (vault / "settings.yaml").write_text(
        """
pipeline:
  max_cycles: 1
  budget_usd: 10.0
limits:
  cycle_budget_usd: 50.0
"""
        + _EXECUTOR,
        encoding="utf-8",
    )
    budget_marker_path(vault).unlink()
    rc = run_cycle_steps(vault, cycle_num=1, budget_cap=50.0, max_cycles=1)
    assert rc in (0, 1)
