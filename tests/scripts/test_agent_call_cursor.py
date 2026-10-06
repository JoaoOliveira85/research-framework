"""Spec 052 — cursor-agent third runtime.

Hermetic: we NEVER spawn the real ``cursor-agent`` binary. The non-stream helper
tests patch ``_run_in_session_with_timeout``; the streaming tests patch
``subprocess.Popen`` with a fake process whose stdout yields canned
``--output-format stream-json`` NDJSON (cursor's real shape, probed 2026-06-08:
camelCase ``usage.inputTokens/outputTokens`` + a terminal ``result`` event with
NO ``total_cost_usd`` because Cursor is flat-rate).

Tests are module-level functions (no classes) so the foreman Arm A verifier can
collect them by ``path::function`` node id (docs/foreman.md grammar).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "agent_call.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("agent_call", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["agent_call"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def agent_call():
    return _load_module()


def _make_vault(tmp_path: Path, runtime: str, model: str) -> Path:
    vault = tmp_path / f"vault-{runtime}"
    vault.mkdir()
    (vault / "settings.yaml").write_text(
        "pipeline:\n"
        "  max_cycles: 20\n"
        "  budget_usd: 50\n"
        "default_executor:\n"
        "  type: cli\n"
        f"  runtime: {runtime}\n"
        f"  model: {model}\n"
        "stages:\n"
        "  plan_narrator:\n"
        f"    model: {model}\n",
        encoding="utf-8",
    )
    return vault


@pytest.fixture
def cursor_vault(tmp_path: Path) -> Path:
    return _make_vault(tmp_path, "cursor-agent", "gpt-5.4-high")


@pytest.fixture
def codex_vault(tmp_path: Path) -> Path:
    return _make_vault(tmp_path, "codex", "gpt-5.4")


@pytest.fixture
def claude_vault(tmp_path: Path) -> Path:
    return _make_vault(tmp_path, "claude", "claude-sonnet-5")


def _cycle_dir(vault: Path, cycle: int = 2) -> Path:
    d = vault / "_pipeline" / "cycles" / f"cycle-{cycle:03d}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cursor_result_line(tin: int = 11, tout: int = 7) -> str:
    """One cursor stream-json terminal ``result`` event (camelCase usage, no $)."""
    return json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "duration_ms": 1234,
            "result": "done",
            "session_id": "sess-1",
            "usage": {
                "inputTokens": tin,
                "outputTokens": tout,
                "cacheReadTokens": 5,
                "cacheWriteTokens": 9,
            },
        }
    )


def _claude_result_line(cost: float = 0.5, tin: int = 11, tout: int = 7) -> str:
    return json.dumps(
        {
            "type": "result",
            "total_cost_usd": cost,
            "usage": {"input_tokens": tin, "output_tokens": tout},
        }
    )


def _fake_stream_proc(events: list[str]) -> MagicMock:
    fake = MagicMock()
    fake.stdin = MagicMock()
    fake.stdout = iter(line + "\n" for line in events)
    fake.stderr = MagicMock(read=MagicMock(return_value=""))
    fake.wait.return_value = 0
    return fake


# ---------------------------------------------------------------------------
# T001 — adapter argv + CURSOR_BIN + with-cost stream-json
# ---------------------------------------------------------------------------


def test_cursor_cmd_argv_shape(agent_call) -> None:
    cmd = agent_call._build_command(
        {"type": "cli", "runtime": "cursor-agent", "model": "gpt-5.4-high", "args": []}
    )
    assert cmd[0] == "cursor-agent"
    assert "-p" in cmd
    assert "--output-format" in cmd and "json" in cmd
    assert "--model" in cmd and "gpt-5.4-high" in cmd
    assert "--trust" in cmd


def test_cursor_bin_env_override(agent_call) -> None:
    with patch.dict("os.environ", {"CURSOR_BIN": "/x/y/cursor-agent"}):
        cmd = agent_call._cursor_cmd(
            {"type": "cli", "runtime": "cursor-agent", "model": "m", "args": []}
        )
    assert cmd[0] == "/x/y/cursor-agent"


def test_cursor_cmd_with_cost_uses_stream_json(agent_call) -> None:
    cmd = agent_call._cursor_cmd_with_cost(
        {"type": "cli", "runtime": "cursor-agent", "model": "m", "args": []}
    )
    assert "stream-json" in cmd
    # The base json output-format must have been swapped, not duplicated.
    assert "json" not in cmd
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"


def test_cursor_registered_in_runtime_adapters(agent_call) -> None:
    assert "cursor-agent" in agent_call._RUNTIME_ADAPTERS


def test_cursor_workspace_injected_for_vault(agent_call, tmp_path: Path) -> None:
    """Mirrors codex --cd: the vault is pinned as --workspace so the agent can
    write notes into a sibling-directory vault (write-confinement, not full-disk)."""
    cmd = agent_call._cursor_cmd(
        {"type": "cli", "runtime": "cursor-agent", "model": "m", "args": []},
        vault_dir=tmp_path,
    )
    assert "--workspace" in cmd
    assert str(tmp_path) in cmd
    # operator-supplied --workspace must win (no double flag)
    cmd2 = agent_call._cursor_cmd(
        {
            "type": "cli",
            "runtime": "cursor-agent",
            "model": "m",
            "args": ["--workspace", "/explicit"],
        },
        vault_dir=tmp_path,
    )
    assert cmd2.count("--workspace") == 1
    assert "/explicit" in cmd2


# ---------------------------------------------------------------------------
# T003 — token capture (camelCase) + claude regression
# ---------------------------------------------------------------------------


def test_cursor_tokens_from_json_object(agent_call) -> None:
    line = _cursor_result_line(tin=11, tout=7)
    parsed = agent_call._cursor_cost_from_output(f"noise\n{line}\nmore\n")
    assert parsed == (11, 7)


def test_cursor_cost_from_output_no_op_on_plain_text(agent_call) -> None:
    assert agent_call._cursor_cost_from_output("just words") is None
    assert agent_call._cursor_cost_from_output("") is None


def test_apply_stream_event_camelcase_usage(agent_call) -> None:
    result = agent_call.StreamCostResult()
    event = json.loads(_cursor_result_line(tin=20, tout=9))
    agent_call._apply_stream_event(event, result)
    assert result.tokens_in == 20
    assert result.tokens_out == 9
    assert result.cost_usd == pytest.approx(0.0)  # flat-rate: no total_cost_usd
    assert result.saw_result is True


def test_apply_stream_event_claude_snakecase_unchanged(agent_call) -> None:
    result = agent_call.StreamCostResult()
    event = json.loads(_claude_result_line(cost=0.5, tin=11, tout=7))
    agent_call._apply_stream_event(event, result)
    assert result.cost_usd == pytest.approx(0.5)
    assert result.tokens_in == 11
    assert result.tokens_out == 7


# ---------------------------------------------------------------------------
# T004 — honest cost: real tokens + estimated dollar + cost_source runtime_tokens
# ---------------------------------------------------------------------------


def test_cursor_sidecar_cost_source_runtime_tokens(agent_call, cursor_vault) -> None:
    cycle_dir = _cycle_dir(cursor_vault)
    fake = _fake_stream_proc([_cursor_result_line(tin=100, tout=40)])
    with (
        patch.object(agent_call.subprocess, "Popen", return_value=fake),
        patch.object(agent_call, "_fallback_estimate", return_value=(0.33, 222)),
    ):
        agent_call.dispatch(
            "plan_narrator", "hi", vault_dir=cursor_vault, cycle_dir=cycle_dir
        )
    data = json.loads((cycle_dir / "agent-calls" / "plan_narrator.json").read_text())
    assert data["agent"] == "cursor-agent"
    assert data["cost_source"] == "runtime_tokens"
    assert data["tokens_in"] == 100  # REAL tokens from the runtime
    assert data["tokens_out"] == 40
    assert data["cost_usd"] == pytest.approx(0.33)  # estimated dollar


def test_cursor_dollar_is_estimate_not_zero(agent_call, cursor_vault) -> None:
    cycle_dir = _cycle_dir(cursor_vault)
    fake = _fake_stream_proc([_cursor_result_line()])
    with (
        patch.object(agent_call.subprocess, "Popen", return_value=fake),
        patch.object(agent_call, "_fallback_estimate", return_value=(0.5, 10)),
    ):
        result = agent_call.dispatch(
            "plan_narrator", "hi", vault_dir=cursor_vault, cycle_dir=cycle_dir
        )
    assert result.cost_usd == pytest.approx(0.5)
    data = json.loads((cycle_dir / "agent-calls" / "plan_narrator.json").read_text())
    assert data["cost_source"] == "runtime_tokens"


def test_cursor_estimator_unavailable_degrades_without_crash(
    agent_call, cursor_vault
) -> None:
    cycle_dir = _cycle_dir(cursor_vault)
    fake = _fake_stream_proc([_cursor_result_line(tin=5, tout=2)])
    with (
        patch.object(agent_call.subprocess, "Popen", return_value=fake),
        patch.object(agent_call, "_fallback_estimate", return_value=None),
    ):
        agent_call.dispatch(
            "plan_narrator", "hi", vault_dir=cursor_vault, cycle_dir=cycle_dir
        )
    data = json.loads((cycle_dir / "agent-calls" / "plan_narrator.json").read_text())
    # tokens are still real; dollar is an honest flat-rate 0 (no crash).
    assert data["tokens_in"] == 5
    assert data["cost_source"] == "runtime_tokens"
    # When the estimator is unavailable the dollar must degrade to an explicit
    # 0.0 — never a silent non-zero figure that would mislead the budget guard.
    assert data["cost_usd"] == 0.0


def test_codex_and_claude_cost_source_unchanged(
    agent_call, codex_vault, claude_vault
) -> None:
    """Regression guard: codex stays runtime/estimated, claude stays runtime —
    the new flat-rate branch must NOT touch the metered runtimes."""
    # codex (non-stream): no parseable $, estimator stands ⇒ "estimated".
    codex_cycle = _cycle_dir(codex_vault)
    completed = subprocess.CompletedProcess(["codex"], 0, "no cost json here", "")
    with (
        patch.object(
            agent_call, "_run_in_session_with_timeout", return_value=completed
        ),
        patch.object(agent_call, "_fallback_estimate", return_value=(0.1, 50)),
    ):
        agent_call.dispatch(
            "plan_narrator", "hi", vault_dir=codex_vault, cycle_dir=codex_cycle
        )
    codex_data = json.loads(
        (codex_cycle / "agent-calls" / "plan_narrator.json").read_text()
    )
    assert codex_data["agent"] == "codex"
    assert codex_data["cost_source"] == "estimated"

    # claude (stream): real dollar in-stream ⇒ "runtime".
    claude_cycle = _cycle_dir(claude_vault)
    fake = _fake_stream_proc([_claude_result_line(cost=0.5, tin=11, tout=7)])
    with patch.object(agent_call.subprocess, "Popen", return_value=fake):
        agent_call.dispatch(
            "plan_narrator", "hi", vault_dir=claude_vault, cycle_dir=claude_cycle
        )
    claude_data = json.loads(
        (claude_cycle / "agent-calls" / "plan_narrator.json").read_text()
    )
    assert claude_data["agent"] == "claude"
    assert claude_data["cost_source"] == "runtime"
    assert claude_data["cost_usd"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# T007 — tier->model recommendation map + explicit model
# ---------------------------------------------------------------------------


def test_cursor_model_tiers_defaults(agent_call) -> None:
    assert agent_call._CURSOR_MODEL_TIERS == {
        "basic": "composer-2.5-fast",
        "normal": "gpt-5.4-high",
        "flagship": "claude-opus-4-8-thinking-high",
    }


def test_cursor_cmd_uses_explicit_model(agent_call) -> None:
    cmd = agent_call._cursor_cmd(
        {
            "type": "cli",
            "runtime": "cursor-agent",
            "model": "claude-opus-4-8-thinking-high",
            "args": [],
        }
    )
    assert "claude-opus-4-8-thinking-high" in cmd


# ---------------------------------------------------------------------------
# T008 — end-to-end through the CLI run() path writes a cursor sidecar
# ---------------------------------------------------------------------------


def test_cursor_full_fixture_cycle_writes_note(
    agent_call, cursor_vault, tmp_path: Path
) -> None:
    """The pipeline shells out to run()/main(); cursor must stream-cost there too."""
    cost_sidecar = _cycle_dir(cursor_vault) / "agent-calls" / "plan_narrator.json"
    prompt_file = tmp_path / "p.md"
    prompt_file.write_text("write a note", encoding="utf-8")
    fake = _fake_stream_proc([_cursor_result_line(tin=12, tout=3)])
    with (
        patch.object(agent_call.subprocess, "Popen", return_value=fake),
        patch.object(agent_call, "_fallback_estimate", return_value=(0.2, 15)),
    ):
        rc = agent_call.run(
            cursor_vault,
            "plan_narrator",
            prompt_file,
            cost_sidecar=cost_sidecar,
        )
    assert rc == 0
    data = json.loads(cost_sidecar.read_text(encoding="utf-8"))
    assert data["agent"] == "cursor-agent"
    assert data["cost_source"] == "runtime_tokens"
    assert data["tokens_in"] == 12
