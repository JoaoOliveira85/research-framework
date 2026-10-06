"""Tier-3: quality-report retry gets suffixed sidecar (spec 028 FR-012)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from tests._helpers import fake_cli_binary

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "agent_call.py"


def _load_agent_call():
    spec = importlib.util.spec_from_file_location("agent_call", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["agent_call"] = module
    spec.loader.exec_module(module)
    return module


def test_second_dispatch_after_sidecar_exists_uses_suffix_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ac = _load_agent_call()
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text(
        "default_executor:\n  type: cli\n  runtime: codex\n  model: gpt-5\n",
        encoding="utf-8",
    )
    cycle_dir = vault / "_pipeline" / "cycles" / "cycle-003"
    cycle_dir.mkdir(parents=True)
    calls = cycle_dir / "agent-calls"
    calls.mkdir(parents=True)
    (calls / "plan_narrator.json").write_text("{}", encoding="utf-8")

    # The leaf binary is the seam. ``dispatch()`` has not gone through
    # ``subprocess.run`` since spec 050, so patching that did nothing and the
    # real ``codex`` on the developer's PATH was run with this prompt.
    fake_cli_binary.activate(monkeypatch, tmp_path / "bin")
    ac.dispatch(
        "plan_narrator",
        "retry",
        vault_dir=vault,
        cycle_dir=cycle_dir,
    )
    assert (calls / "plan_narrator-2.json").is_file()
    payload = json.loads((calls / "plan_narrator-2.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.2"
