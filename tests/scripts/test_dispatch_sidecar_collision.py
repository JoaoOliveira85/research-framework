"""Tier-3: dispatch sidecar path collision (spec 028 US2)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "agent_call.py"


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


@pytest.fixture
def vault_and_cycle(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text(
        "default_executor:\n  type: cli\n  runtime: codex\n  model: gpt-5\n",
        encoding="utf-8",
    )
    cycle_dir = vault / "_pipeline" / "cycles" / "cycle-001"
    cycle_dir.mkdir(parents=True)
    return vault, cycle_dir


def test_two_dispatches_produce_distinct_sidecars(ac, vault_and_cycle) -> None:
    vault, cycle_dir = vault_and_cycle
    mock_result = MagicMock(stdout="ok", stderr="", returncode=0)
    # dispatch() executes via _run_in_session_with_timeout (Popen-based, spec
    # 050 process-tree work) — NOT subprocess.run. Patching subprocess.run is a
    # no-op and lets a real codex executor spawn (Principle IV breach + hang).
    with patch.object(ac, "_run_in_session_with_timeout", return_value=mock_result):
        ac.dispatch(
            "plan_narrator",
            "prompt",
            vault_dir=vault,
            cycle_dir=cycle_dir,
        )
        ac.dispatch(
            "plan_narrator",
            "prompt2",
            vault_dir=vault,
            cycle_dir=cycle_dir,
        )
    first = cycle_dir / "agent-calls" / "plan_narrator.json"
    second = cycle_dir / "agent-calls" / "plan_narrator-2.json"
    assert first.is_file()
    assert second.is_file()
    p1 = json.loads(first.read_text(encoding="utf-8"))
    p2 = json.loads(second.read_text(encoding="utf-8"))
    assert p1["stage"] == p2["stage"] == "plan_narrator"


def test_single_dispatch_leaves_only_stage_json(ac, vault_and_cycle) -> None:
    vault, cycle_dir = vault_and_cycle
    mock_result = MagicMock(stdout="ok", stderr="", returncode=0)
    # See note above: patch the real exec fn, not subprocess.run.
    with patch.object(ac, "_run_in_session_with_timeout", return_value=mock_result):
        ac.dispatch("plan_narrator", "prompt", vault_dir=vault, cycle_dir=cycle_dir)
    calls = cycle_dir / "agent-calls"
    assert list(calls.glob("plan_narrator*.json")) == [calls / "plan_narrator.json"]
