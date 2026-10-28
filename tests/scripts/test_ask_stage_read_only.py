"""Issue #15 — the headless ``ask`` stage answers from the vault and runs nothing.

``ask --escalate`` dispatches the ``/ask`` command through ``agent_call.py``
with ``--stage ask``. With no ``stages.ask`` block it inherited
``default_executor`` — ``bypassPermissions`` (claude), ``--sandbox
workspace-write`` (codex), ``--force`` (cursor), ``--dangerously-skip-
permissions`` (opencode) — so a one-shot question could run commands and
write files, and could start the very research run the operator did not
ask for.

``default_executor.args`` and ``stages.<stage>.args`` are ADDITIVE, and codex
refuses a second ``--sandbox`` ("cannot be used multiple times"), so a
read-only ask cannot be had by appending. ``stages.<stage>.inherit_args:
false`` makes the stage's ``args`` the whole list; every shipped profile's
``stages.ask`` uses it. These tests build the real argv through the real
adapters.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "agent_call.py"

PROFILES = sorted(REPO_ROOT.glob("settings*.yaml"))

#: Flags that let a headless agent run commands or write unasked.
_WRITE_OR_RUN_FLAGS = (
    "bypassPermissions",
    "workspace-write",
    "danger-full-access",
    "--force",
    "--yolo",
    "--dangerously-skip-permissions",
    "--dangerously-bypass-approvals-and-sandbox",
    "--approve-mcps",
)


@pytest.fixture(scope="module")
def agent_call() -> Any:
    spec = importlib.util.spec_from_file_location("agent_call", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["agent_call"] = module
    spec.loader.exec_module(module)
    return module


def _ask_executor(agent_call: Any, profile: Path) -> dict[str, Any]:
    settings = yaml.safe_load(profile.read_text(encoding="utf-8"))
    return agent_call._resolve_executor(settings, "ask")


def test_every_shipped_profile_is_checked() -> None:
    names = {p.name for p in PROFILES}
    assert {
        "settings.yaml",
        "settings.codex.yaml",
        "settings.cursor.yaml",
        "settings.cursor-claude.yaml",
        "settings.opencode.yaml",
        "settings.ollama.yaml",
    } <= names


def test_inherit_args_false_makes_the_stage_args_the_whole_list(agent_call) -> None:
    settings = {
        "default_executor": {"runtime": "claude", "args": ["--a", "1"]},
        "stages": {
            "kept": {"args": ["--b"]},
            "alone": {"args": ["--b"], "inherit_args": False},
        },
    }
    assert agent_call._resolve_executor(settings, "kept")["args"] == ["--a", "1", "--b"]
    assert agent_call._resolve_executor(settings, "alone")["args"] == ["--b"]


def test_inherit_args_must_be_a_boolean(agent_call) -> None:
    settings = {"stages": {"ask": {"inherit_args": "no"}}}
    with pytest.raises(ValueError, match="inherit_args"):
        agent_call._resolve_executor(settings, "ask")


@pytest.mark.parametrize("profile", PROFILES, ids=[p.name for p in PROFILES])
def test_the_ask_stage_does_not_retry(agent_call, profile: Path) -> None:
    """A failed ask is reported, not re-sent: a retry is a second paid call."""
    assert _ask_executor(agent_call, profile)["retry"] == 0


@pytest.mark.parametrize("profile", PROFILES, ids=[p.name for p in PROFILES])
def test_the_ask_stage_argv_carries_no_write_or_run_flag(
    agent_call, profile: Path, tmp_path: Path
) -> None:
    executor = _ask_executor(agent_call, profile)
    if agent_call._is_http_executor(executor):
        # HTTP runtimes (ollama) receive the prompt and return text; they have
        # no tools, so there is nothing to run and nothing to restrict.
        assert executor.get("args") in (None, [])
        return
    argv = agent_call._build_command(executor, tmp_path)
    bad = [flag for flag in _WRITE_OR_RUN_FLAGS if flag in argv]
    assert not bad, f"{profile.name}: stages.ask argv carries {bad}: {argv}"


def _value_after(argv: list[str], flag: str) -> str:
    assert flag in argv, argv
    return argv[argv.index(flag) + 1]


@pytest.mark.parametrize("profile", PROFILES, ids=[p.name for p in PROFILES])
def test_the_ask_stage_argv_is_read_only_for_its_runtime(
    agent_call, profile: Path, tmp_path: Path
) -> None:
    executor = _ask_executor(agent_call, profile)
    runtime = executor.get("runtime")
    if agent_call._is_http_executor(executor):
        pytest.skip("HTTP runtime: no tools (see the test above)")
    argv = agent_call._build_command(executor, tmp_path)
    if runtime == "claude":
        assert _value_after(argv, "--tools") == "Read,Grep,Glob"
        assert "--strict-mcp-config" in argv
    elif runtime == "codex":
        assert _value_after(argv, "--sandbox") == "read-only"
        assert argv.count("--sandbox") == 1
    elif runtime == "cursor-agent":
        assert _value_after(argv, "--mode") == "ask"
    elif runtime == "opencode":
        assert _value_after(argv, "--agent") == "plan"
    else:  # pragma: no cover - a new runtime must add its own read-only rule
        pytest.fail(f"{profile.name}: no read-only rule for runtime {runtime!r}")
