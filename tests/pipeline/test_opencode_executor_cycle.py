"""Spec 064 — opencode executor: settings profile + cycle integration.

Tier 2/3 tests. The settings-load tests are pure unit checks on the bundled
`settings.opencode.yaml`; the cycle/containment tests (added with US1/US4) drive
a fake-agent cycle via `tests/_helpers/fake_agent.py` — never a real opencode.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from research_framework._assets import asset_path
from research_framework.pipeline import settings as settings_mod
from tests._helpers import fake_agent

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "agent_call.py"


def _load_agent_call():
    # Use a per-call unique module name (digest of the script path) so the
    # loader never clobbers any pre-existing ``sys.modules["agent_call"]``
    # entry — under pytest reordering / xdist that bare name has bitten other
    # tests in this file before. Matches benchmark/matrix.py::valid_runtimes.
    digest = hashlib.sha1(str(_SCRIPT).encode("utf-8")).hexdigest()[:12]
    mod_name = f"_agent_call_under_test_{digest}"
    spec = importlib.util.spec_from_file_location(mod_name, _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(mod_name, None)
        raise
    return module


@pytest.fixture
def agent_call():
    return _load_agent_call()


def _opencode_vault(tmp_path: Path, *, model: str = "ollama/qwen3.6:27b") -> Path:
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "settings.yaml").write_text(
        "schema_version: 1\n"
        "default_executor:\n"
        "  type: cli\n"
        "  runtime: opencode\n"
        f"  model: {model}\n",
        encoding="utf-8",
    )
    return vault


def _mock_opencode_run(stage_file: Path, ndjson: str, *, returncode: int = 0):
    """Return a fake ``_run_in_session_with_timeout`` that simulates opencode:
    it writes a stage output file (its agentic write) and prints NDJSON."""

    def _run(cmd, *args, **kwargs):
        _run.cmd = cmd
        stage_file.parent.mkdir(parents=True, exist_ok=True)
        stage_file.write_text('{"ok": true}\n', encoding="utf-8")
        return subprocess.CompletedProcess(cmd, returncode, ndjson, "")

    return _run


def test_settings_opencode_loads_runtime_and_default_agent(tmp_path: Path) -> None:
    """The bundled opencode profile declares `runtime: opencode`, and
    `default_agent: opencode` validates (FR-001 / FR-004; analyze G2)."""
    profile = yaml.safe_load(asset_path("settings.opencode.yaml").read_text())
    assert profile["default_executor"]["runtime"] == "opencode"
    # `default_agent: opencode` must be an accepted value, not rejected.
    assert (
        settings_mod._parse_default_agent("opencode", vault_dir=tmp_path) == "opencode"
    )


def test_fake_agent_opencode_handler_emits_valid_ndjson(agent_call) -> None:
    """The fake-agent NDJSON emitter produces a step_finish event that
    `_parse_opencode_ndjson` accepts (T015 — keeps hermetic tests honest)."""
    line = fake_agent.opencode_step_finish_ndjson(tokens_in=120, tokens_out=8)
    usage = agent_call._parse_opencode_ndjson(line)
    assert usage == {
        "tokens_in": 120,
        "tokens_out": 8,
        "cost_usd": 0.0,
        "n_steps": 1,
    }


def test_opencode_cycle_writes_stage_files_and_commits(
    agent_call, tmp_path, monkeypatch
) -> None:
    """A real opencode dispatch runs `opencode run … --dir <vault>` and the
    agent's stage-output file lands inside the vault (FR-009 file contract).

    (The git commit is the cycle-runner's job, orchestrator-level; this exercises
    the dispatch → vault-scoped stage-write contract that makes it possible.)
    """
    vault = _opencode_vault(tmp_path)
    cycle_dir = vault / "_pipeline" / "cycles" / "cycle-001"
    stage_file = cycle_dir / "cycle-001-scout.json"
    monkeypatch.setattr(
        agent_call,
        "_opencode_preflight_cached",
        lambda _e, **_kw: (True, None),
    )
    ndjson = fake_agent.opencode_step_finish_ndjson(tokens_in=8523, tokens_out=43)
    runner = _mock_opencode_run(stage_file, ndjson)
    monkeypatch.setattr(agent_call, "_run_in_session_with_timeout", runner)

    result = agent_call.dispatch("scout", "hi", vault_dir=vault, cycle_dir=cycle_dir)

    assert result.exit_code == 0
    assert stage_file.exists(), "opencode did not produce the stage output file"
    # The agent was pinned to the vault via --dir (containment, FR-010).
    assert "--dir" in runner.cmd and str(vault) in runner.cmd
    assert runner.cmd[0] == "opencode"


def test_opencode_cycle_sidecar_honest_local_cost(
    agent_call, tmp_path, monkeypatch
) -> None:
    """The spec-028 sidecar for a local opencode call records executor=opencode,
    the resolved model, measured $0, real tokens, cost_source=runtime (SC-003)."""
    vault = _opencode_vault(tmp_path, model="ollama/qwen3-coder:30b-64k")
    cycle_dir = vault / "_pipeline" / "cycles" / "cycle-001"
    stage_file = cycle_dir / "cycle-001-scout.json"
    monkeypatch.setattr(
        agent_call,
        "_opencode_preflight_cached",
        lambda _e, **_kw: (True, None),
    )
    ndjson = fake_agent.opencode_step_finish_ndjson(tokens_in=8523, tokens_out=43)
    monkeypatch.setattr(
        agent_call,
        "_run_in_session_with_timeout",
        _mock_opencode_run(stage_file, ndjson),
    )

    agent_call.dispatch("scout", "hi", vault_dir=vault, cycle_dir=cycle_dir)

    sidecars = list((cycle_dir / "agent-calls").glob("*.json"))
    assert len(sidecars) == 1, "expected exactly one telemetry sidecar"
    sc = json.loads(sidecars[0].read_text(encoding="utf-8"))
    assert sc["agent"] == "opencode"
    assert sc["cost_usd"] == 0.0
    assert sc["cost_source"] == "runtime"
    assert sc["tokens_in"] == 8523 and sc["tokens_out"] == 43


def test_opencode_provider_swap_config_only(agent_call, tmp_path, monkeypatch) -> None:
    """US2/SC-002: switching the model (local → hosted) is config-only — the
    same code path dispatches `opencode` with a different recorded model."""
    monkeypatch.setattr(
        agent_call,
        "_opencode_preflight_cached",
        lambda _e, **_kw: (True, None),
    )
    ndjson = fake_agent.opencode_step_finish_ndjson(tokens_in=10, tokens_out=5)
    seen = []

    for model in ("ollama/qwen3.6:27b", "openai/gpt-4o"):
        vault = _opencode_vault(tmp_path / model.replace("/", "_"), model=model)
        cycle_dir = vault / "_pipeline" / "cycles" / "cycle-001"
        stage_file = cycle_dir / "cycle-001-scout.json"
        runner = _mock_opencode_run(stage_file, ndjson)
        monkeypatch.setattr(agent_call, "_run_in_session_with_timeout", runner)
        agent_call.dispatch("scout", "hi", vault_dir=vault, cycle_dir=cycle_dir)
        seen.append((runner.cmd[0], runner.cmd[runner.cmd.index("--model") + 1]))

    # Same executor (opencode), different model — no framework change between runs.
    assert seen[0][0] == seen[1][0] == "opencode"
    assert seen[0][1] != seen[1][1]


def test_opencode_command_contains_dir_and_no_full_disk_flag(agent_call, tmp_path):
    """US4/FR-010: the cycle command pins --dir as containment; the approval
    flag (if present in args) is orthogonal and never the containment story."""
    cmd = agent_call._build_command(
        {"type": "cli", "runtime": "opencode", "model": "ollama/m"}, tmp_path
    )
    assert "--dir" in cmd
    assert cmd[cmd.index("--dir") + 1] == str(tmp_path)
    # No codex-style full-disk-access escape hatch is used for opencode.
    assert "--dangerous-bypass" not in cmd
    assert "danger-full-access" not in cmd


def test_opencode_cycle_no_writes_outside_vault(
    agent_call, tmp_path, monkeypatch
) -> None:
    """US4/SC-005: after an opencode dispatch, nothing is created outside the
    vault root (the agent is pinned to --dir)."""
    vault = _opencode_vault(tmp_path)
    cycle_dir = vault / "_pipeline" / "cycles" / "cycle-001"
    stage_file = cycle_dir / "cycle-001-scout.json"
    outside = tmp_path / "outside"
    outside.mkdir()
    before = {p for p in outside.rglob("*")}
    monkeypatch.setattr(
        agent_call,
        "_opencode_preflight_cached",
        lambda _e, **_kw: (True, None),
    )
    ndjson = fake_agent.opencode_step_finish_ndjson(tokens_in=10, tokens_out=2)
    monkeypatch.setattr(
        agent_call,
        "_run_in_session_with_timeout",
        _mock_opencode_run(stage_file, ndjson),
    )

    agent_call.dispatch("scout", "hi", vault_dir=vault, cycle_dir=cycle_dir)

    assert {p for p in outside.rglob("*")} == before, "writes escaped the vault root"


def test_settings_opencode_unattended_posture_present() -> None:
    """US5/FR-013: the bundled profile carries opencode's unattended autonomy
    posture (the approval lever), contained by --dir."""
    profile = yaml.safe_load(asset_path("settings.opencode.yaml").read_text())
    args = profile["default_executor"]["args"]
    assert "--dangerously-skip-permissions" in args


@pytest.mark.live_llm
def test_live_opencode_ollama_cycle_completes(agent_call, tmp_path) -> None:
    """SC-001 (opt-in, real money/compute): a real opencode run against a local
    Ollama model writes a file inside --dir and reports a $0/runtime sidecar.
    Skipped unless --live-llm / LIVE_LLM=1 (never in CI)."""
    vault = _opencode_vault(tmp_path, model="ollama/qwen3-coder:30b-64k")
    cycle_dir = vault / "_pipeline" / "cycles" / "cycle-001"
    target = vault / "hello.txt"
    result = agent_call.dispatch(
        "scout",
        "Create a file named hello.txt in the current directory whose entire "
        "contents are exactly: HELLO_OPENCODE",
        vault_dir=vault,
        cycle_dir=cycle_dir,
    )
    assert result.exit_code == 0
    assert target.exists()
    sidecars = list((cycle_dir / "agent-calls").glob("*.json"))
    assert sidecars and json.loads(sidecars[0].read_text())["cost_source"] == "runtime"
