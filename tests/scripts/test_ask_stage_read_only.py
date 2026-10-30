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
import os
import shutil
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


#: What the opencode ask agent must not be able to do: run a shell (which
#: could start `./vault cycle`), fetch, spawn a sub-agent, or edit.
_OPENCODE_MUST_DENY = frozenset({"bash", "webfetch", "task", "edit"})


def _opencode_permission(executor: dict[str, Any]) -> dict[str, Any]:
    import json

    raw = (executor.get("env") or {}).get("OPENCODE_PERMISSION")
    assert raw, "stages.ask must set OPENCODE_PERMISSION for opencode"
    return json.loads(raw)


def _opencode_denied(executor: dict[str, Any]) -> set[str]:
    return {k for k, v in _opencode_permission(executor).items() if v == "deny"}


def test_stage_env_reaches_the_runtime_process(
    agent_call, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`stages.<stage>.env` is published to the spawned runtime's environment."""
    dump = tmp_path / "env.txt"
    stub = tmp_path / "claude"
    stub.write_text(
        f'#!/bin/sh\nprintf "%s" "$ASK_PROBE" > {dump}\ncat > /dev/null\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)
    monkeypatch.setenv("CLAUDE_BIN", str(stub))
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text(
        "default_executor:\n  runtime: claude\n  model: sonnet\n"
        "stages:\n  ask:\n    env:\n      ASK_PROBE: published\n",
        encoding="utf-8",
    )
    prompt = tmp_path / "p.md"
    prompt.write_text("hi", encoding="utf-8")

    assert agent_call.run(vault, "ask", prompt) == 0
    assert dump.read_text(encoding="utf-8") == "published"


def test_stage_env_must_map_strings_to_strings(agent_call) -> None:
    settings = {"stages": {"ask": {"env": {"X": 1}}}}
    with pytest.raises(ValueError, match="env"):
        agent_call._resolve_executor(settings, "ask")


_OPENCODE = shutil.which("opencode")


@pytest.mark.skipif(_OPENCODE is None, reason="opencode binary not installed")
def test_the_opencode_ask_agent_is_denied_shell_fetch_task_and_edit(
    agent_call, tmp_path: Path
) -> None:
    """The OUTCOME, read back from opencode itself — not just the flags.

    `opencode agent list` prints each agent's effective permission rules; it
    makes no model call. XDG dirs point at empty temp dirs so the operator's
    own opencode config cannot mask or supply the deny.
    """
    import json
    import re
    import subprocess

    executor = _ask_executor(agent_call, REPO_ROOT / "settings.opencode.yaml")
    env = {**os.environ, **(executor.get("env") or {})}
    for name in (
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_STATE_HOME",
        "XDG_CACHE_HOME",
    ):
        d = tmp_path / name
        d.mkdir()
        env[name] = str(d)
    project = tmp_path / "vault"
    project.mkdir()
    out = subprocess.run(
        [_OPENCODE, "agent", "list"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    ).stdout
    parts = re.split(r"^(\S+) \((?:primary|subagent|all)\)\s*$", out, flags=re.M)
    agents = {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}
    rules = json.loads(agents[executor["agent"]])

    def effective(permission: str) -> str:
        # opencode evaluates the LAST matching rule; `*` covers every tool.
        hits = [
            r["action"]
            for r in rules
            if r["permission"] in (permission, "*") and r["pattern"] == "*"
        ]
        return hits[-1]

    for permission in sorted(_OPENCODE_MUST_DENY):
        assert effective(permission) == "deny", (permission, rules)
    assert effective("read") == "allow"


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
        # `plan` alone only denies edits; the deny list rides in the env.
        assert _value_after(argv, "--agent") == "plan"
        assert _opencode_denied(executor) >= _OPENCODE_MUST_DENY
    else:  # pragma: no cover - a new runtime must add its own read-only rule
        pytest.fail(f"{profile.name}: no read-only rule for runtime {runtime!r}")
