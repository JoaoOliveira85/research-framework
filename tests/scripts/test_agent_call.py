"""Tests for `scripts/agent_call.py` — the runtime dispatcher.

These tests pin down the three properties the dispatcher must hold for
`--settings claude|codex` to actually mean something end-to-end:

1. It reads the vault's `settings.yaml` (no hardcoded runtime).
2. Per-stage overrides win over `default_executor`.
3. The resolved runtime / model / args get built into the right CLI
   invocation for each supported runtime, so when the shell script
   pipes a prompt in, the right binary receives it.

We don't actually spawn `claude` or `codex` — subprocess is mocked so
the tests verify command construction only. Real end-to-end behaviour
is covered by the manual E2E checklist.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "agent_call.py"


def _load_module():
    """Load agent_call.py as a module without executing its argparse main.

    Registered in sys.modules so any @dataclass or introspection done
    during import can find the module by name.
    """
    spec = importlib.util.spec_from_file_location("agent_call", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["agent_call"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def agent_call():
    return _load_module()


@pytest.fixture
def codex_vault(tmp_path: Path) -> Path:
    """A vault whose settings.yaml pins every stage to Codex."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text(
        "default_executor:\n"
        "  type: cli\n"
        "  runtime: codex\n"
        "  model: gpt-5.4\n"
        "stages:\n"
        "  scout:\n"
        "    model: gpt-5.4\n"
        "    args: ['-c', 'model_reasoning_effort=low']\n"
        "  note_writer:\n"
        "    model: gpt-5.5\n",
        encoding="utf-8",
    )
    return vault


@pytest.fixture
def claude_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text(
        "default_executor:\n"
        "  type: cli\n"
        "  runtime: claude\n"
        "  model: sonnet\n"
        "stages:\n"
        "  note_writer:\n"
        "    model: opus\n",
        encoding="utf-8",
    )
    return vault


# ---------------------------------------------------------------------------
# Settings loading + stage resolution
# ---------------------------------------------------------------------------


class TestDispatchAgentCallResult:
    def test_dispatch_populates_result_from_stream_mock(
        self, agent_call, claude_vault, tmp_path
    ) -> None:
        vault = claude_vault
        cycle_dir = tmp_path / "_pipeline" / "cycles" / "cycle-002"
        cycle_dir.mkdir(parents=True)
        events = [
            '{"type":"result","total_cost_usd":0.5,'
            '"usage":{"input_tokens":11,"output_tokens":7}}',
        ]
        fake_proc = MagicMock()
        fake_proc.stdin = MagicMock()
        fake_proc.stdout = iter(line + "\n" for line in events)
        fake_proc.stderr = MagicMock(read=MagicMock(return_value=""))
        fake_proc.wait.return_value = 0
        with patch.object(agent_call.subprocess, "Popen", return_value=fake_proc):
            result = agent_call.dispatch(
                "plan_narrator",
                "hi",
                vault_dir=vault,
                cycle_dir=cycle_dir,
            )
        assert result.exit_code == 0
        assert result.cost_usd == pytest.approx(0.5)
        assert result.tokens_in == 11
        assert result.tokens_out == 7
        assert result.latency_ms >= 0

    def test_dispatch_returns_the_answer_once(
        self, agent_call, claude_vault, tmp_path
    ) -> None:
        """claude says its answer twice in stream-json: in the assistant event
        and again as the terminal event's ``result``. Both were appended to
        ``stdout``, so a caller that parses it (the probe-retrieval stage does,
        with a strict ``json.loads``) got two JSON documents and kept nothing,
        and the plan narrator wrote its rationale into the plan twice."""
        answer = '{"probes": {"p1": [{"filename": "a.md", "confidence": "high"}]}}'
        events = [
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": answer}]},
                }
            ),
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "result": answer,
                    "total_cost_usd": 0.01,
                }
            ),
        ]
        fake_proc = MagicMock()
        fake_proc.stdin = MagicMock()
        fake_proc.stdout = iter(line + "\n" for line in events)
        fake_proc.stderr = MagicMock(read=MagicMock(return_value=""))
        fake_proc.wait.return_value = 0
        with patch.object(agent_call.subprocess, "Popen", return_value=fake_proc):
            result = agent_call.dispatch(
                "probe_retrieval", "hi", agent="claude", vault_dir=claude_vault
            )

        assert result.exit_code == 0
        assert json.loads(result.stdout) == json.loads(answer)


class TestResolveExecutor:
    def test_default_is_applied_when_stage_missing(self, agent_call, codex_vault):
        settings = agent_call._load_settings(codex_vault)
        executor = agent_call._resolve_executor(settings, "unknown_stage")
        assert executor["runtime"] == "codex"
        assert executor["model"] == "gpt-5.4"
        assert executor["args"] == []

    def test_stage_override_wins_over_default(self, agent_call, codex_vault):
        settings = agent_call._load_settings(codex_vault)
        executor = agent_call._resolve_executor(settings, "note_writer")
        # Default runtime survives, but the stage-level model override wins.
        assert executor["runtime"] == "codex"
        assert executor["model"] == "gpt-5.5"

    def test_stage_args_propagate(self, agent_call, codex_vault):
        """Codex reasoning-effort overrides live in stages.<stage>.args."""
        settings = agent_call._load_settings(codex_vault)
        executor = agent_call._resolve_executor(settings, "scout")
        assert executor["args"] == ["-c", "model_reasoning_effort=low"]

    def test_default_and_stage_args_merge_additively(
        self, agent_call, tmp_path: Path
    ) -> None:
        """Runtime-level flags in default_executor.args must survive even
        when a stage adds its own args. This is the regression guard for
        v0.2.5 → v0.2.6: sandbox flags in default_executor must still be
        present when a stage overrides reasoning effort."""
        vault = tmp_path / "v"
        vault.mkdir()
        (vault / "settings.yaml").write_text(
            "default_executor:\n"
            "  runtime: codex\n"
            "  model: gpt-5.4\n"
            "  args:\n"
            "    - --skip-git-repo-check\n"
            "    - --sandbox\n"
            "    - workspace-write\n"
            "stages:\n"
            "  source_relevance:\n"
            "    args: ['-c', 'model_reasoning_effort=low']\n",
            encoding="utf-8",
        )
        executor = agent_call._resolve_executor(
            agent_call._load_settings(vault), "source_relevance"
        )
        # Both sets of flags present, default first so they stay at the
        # front of argv (Codex needs sandbox flags before subcommand args).
        assert executor["args"] == [
            "--skip-git-repo-check",
            "--sandbox",
            "workspace-write",
            "-c",
            "model_reasoning_effort=low",
        ]

    def test_non_list_args_raises_actionable_error(
        self, agent_call, tmp_path: Path
    ) -> None:
        vault = tmp_path / "v"
        vault.mkdir()
        (vault / "settings.yaml").write_text(
            "default_executor:\n  runtime: codex\n  model: x\n  args: not-a-list\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError) as exc:
            agent_call._resolve_executor(agent_call._load_settings(vault), "any_stage")
        # Error must point at the actual offending source (default vs stage).
        assert "default_executor.args" in str(exc.value)

    def test_missing_settings_file_raises(self, agent_call, tmp_path):
        with pytest.raises(FileNotFoundError):
            agent_call._load_settings(tmp_path)


# ---------------------------------------------------------------------------
# Per-runtime command construction
# ---------------------------------------------------------------------------


class TestBuildCommand:
    def test_codex_cmd_uses_exec_subcommand(self, agent_call):
        """Codex non-interactive runs go through `codex exec`."""
        cmd = agent_call._build_command(
            {"type": "cli", "runtime": "codex", "model": "gpt-5.4", "args": []}
        )
        assert cmd[0] == "codex"
        assert cmd[1] == "exec"
        assert "--model" in cmd and "gpt-5.4" in cmd

    def test_codex_cmd_threads_args_before_model(self, agent_call):
        """Config overrides must land before --model so they actually apply."""
        cmd = agent_call._build_command(
            {
                "type": "cli",
                "runtime": "codex",
                "model": "gpt-5.4",
                "args": ["-c", "model_reasoning_effort=low"],
            }
        )
        # Layout: [codex, exec, -c, model_reasoning_effort=low, --model, gpt-5.4]
        assert cmd == [
            "codex",
            "exec",
            "-c",
            "model_reasoning_effort=low",
            "--model",
            "gpt-5.4",
        ]

    def test_claude_cmd_uses_print_flag(self, agent_call):
        cmd = agent_call._build_command(
            {"type": "cli", "runtime": "claude", "model": "sonnet", "args": []}
        )
        assert cmd[0] == "claude"
        assert "--print" in cmd
        assert "sonnet" in cmd

    def test_unknown_runtime_raises_actionable_error(self, agent_call):
        with pytest.raises(ValueError) as exc:
            agent_call._build_command(
                {"type": "cli", "runtime": "gemini", "model": "x", "args": []}
            )
        msg = str(exc.value)
        assert "gemini" in msg
        # Error must tell the user how to recover.
        assert "claude" in msg and "codex" in msg

    def test_bin_env_override_is_honoured(self, agent_call, monkeypatch):
        monkeypatch.setenv("CODEX_BIN", "/opt/custom/codex")
        cmd = agent_call._build_command(
            {"type": "cli", "runtime": "codex", "model": "gpt-5.4", "args": []}
        )
        assert cmd[0] == "/opt/custom/codex"


class TestCodexWorkingRoot:
    """``--cd <vault>`` pins codex's sandbox working root to the vault.

    Without this, codex inherits the orchestrator's cwd (typically
    ``~``/``~/Documents``) and ``--sandbox workspace-write`` can't write a
    vault in a *sibling* directory — the reason operators were forced onto
    ``danger-full-access`` (which runs UNsandboxed and was the behavioural
    trigger for the 2026-06-05 endpoint-security script quarantine; see
    CHANGELOG [1.0.0rc2]). Pinning the working root lets the contained
    ``workspace-write`` default work, so the agent stays inside the vault.
    """

    def _codex(self, args=None):
        return {
            "type": "cli",
            "runtime": "codex",
            "model": "gpt-5.4",
            "args": args or [],
        }

    def test_cd_injected_when_vault_dir_given(self, agent_call, tmp_path):
        """A vault_dir injects ``--cd <vault>`` right after ``exec``."""
        cmd = agent_call._build_command(self._codex(), tmp_path)
        assert cmd[:4] == ["codex", "exec", "--cd", str(tmp_path)]
        assert "--model" in cmd and "gpt-5.4" in cmd

    def test_cd_precedes_user_args_and_model(self, agent_call, tmp_path):
        """Working root, then the profile's sandbox flags, then the model —
        mirrors the real ``settings.codex.yaml`` workspace-write profile."""
        cmd = agent_call._build_command(
            self._codex(
                [
                    "--skip-git-repo-check",
                    "--sandbox",
                    "workspace-write",
                    "-c",
                    "sandbox_workspace_write.network_access=true",
                ]
            ),
            tmp_path,
        )
        assert cmd == [
            "codex",
            "exec",
            "--cd",
            str(tmp_path),
            "--skip-git-repo-check",
            "--sandbox",
            "workspace-write",
            "-c",
            "sandbox_workspace_write.network_access=true",
            "--model",
            "gpt-5.4",
        ]

    def test_no_cd_when_vault_dir_omitted(self, agent_call):
        """Back-compat: single-arg ``_build_command`` (registry / older
        callers) must NOT inject a working root — no vault path is known."""
        cmd = agent_call._build_command(self._codex(["--sandbox", "workspace-write"]))
        assert "--cd" not in cmd and "-C" not in cmd

    def test_explicit_cd_in_args_is_not_doubled(self, agent_call, tmp_path):
        """An operator who already set ``--cd`` keeps full control — we
        never inject a second, conflicting working-root flag."""
        cmd = agent_call._build_command(
            self._codex(["--cd", "/operator/chosen/root"]), tmp_path
        )
        assert cmd.count("--cd") == 1
        assert "/operator/chosen/root" in cmd
        assert str(tmp_path) not in cmd

    def test_explicit_short_c_flag_is_respected(self, agent_call, tmp_path):
        """The short form ``-C`` also suppresses auto-injection."""
        cmd = agent_call._build_command(self._codex(["-C", "/operator/root"]), tmp_path)
        assert "--cd" not in cmd
        assert cmd.count("-C") == 1

    def test_vault_dir_ignored_for_non_codex_runtimes(self, agent_call, tmp_path):
        """``--cd`` is codex-only; passing a vault_dir to claude/python is a
        harmless no-op (those adapters are vault-agnostic)."""
        cmd = agent_call._build_command(
            {"type": "cli", "runtime": "claude", "model": "sonnet", "args": []},
            tmp_path,
        )
        assert "--cd" not in cmd
        assert cmd[0] == "claude"

    def test_has_cd_flag_detects_all_forms(self, agent_call):
        assert agent_call._has_cd_flag(["--cd", "/x"]) is True
        assert agent_call._has_cd_flag(["-C", "/x"]) is True
        assert agent_call._has_cd_flag(["--cd=/x"]) is True
        assert agent_call._has_cd_flag(["--sandbox", "workspace-write"]) is False
        assert agent_call._has_cd_flag([]) is False


# ---------------------------------------------------------------------------
# End-to-end dispatch (subprocess mocked)
# ---------------------------------------------------------------------------


class TestRunDispatch:
    # ``run()`` no longer uses ``subprocess.run`` directly — it goes
    # through ``_run_in_session_with_timeout`` so a timeout actually kills
    # the whole process tree (post-mortem 2026-05-30). These tests patch
    # the wrapper to verify command construction without spawning real
    # binaries.
    def test_codex_vault_spawns_codex_binary(self, agent_call, codex_vault, tmp_path):
        """The regression test for v0.2.4 → v0.2.5: a vault with
        `runtime: codex` in its settings.yaml must produce a `codex`
        invocation, not `claude`."""
        prompt = tmp_path / "p.md"
        prompt.write_text("say hi", encoding="utf-8")

        with patch.object(agent_call, "_run_in_session_with_timeout") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            rc = agent_call.run(codex_vault, "scout", prompt)

        assert rc == 0
        called_cmd = mock_run.call_args.args[0]
        assert called_cmd[0] == "codex"
        assert "--model" in called_cmd
        # Prompt is piped on stdin, not argv — keeps argv short and safe.
        assert mock_run.call_args.kwargs["input"] == "say hi"

    def test_claude_vault_spawns_claude_binary(
        self, agent_call, claude_vault, tmp_path
    ):
        prompt = tmp_path / "p.md"
        prompt.write_text("say hi", encoding="utf-8")
        with patch.object(agent_call, "_run_in_session_with_timeout") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            rc = agent_call.run(claude_vault, "note_writer", prompt)

        assert rc == 0
        called_cmd = mock_run.call_args.args[0]
        assert called_cmd[0] == "claude"
        # note_writer stage override bumped model to opus.
        assert "opus" in called_cmd

    def test_codex_vault_writes_sentinel_cost_sidecar(
        self, agent_call, codex_vault, tmp_path
    ):
        """Codex CLI doesn't expose cost. The wrapper must still drop a
        sentinel sidecar so the orchestrator's per-cycle summing logic
        finds one file per stage and can distinguish "0 because no data"
        from "0 because no run happened"."""
        prompt = tmp_path / "p.md"
        prompt.write_text("hi", encoding="utf-8")
        sidecar = (
            tmp_path
            / "_pipeline"
            / "cycles"
            / "cycle-001"
            / "agent-calls"
            / "scout.json"
        )
        with patch.object(agent_call, "_run_in_session_with_timeout") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            rc = agent_call.run(codex_vault, "scout", prompt, sidecar)

        assert rc == 0
        assert sidecar.exists()
        import json as _json

        payload = _json.loads(sidecar.read_text())
        assert payload["schema_version"] == "1.2"
        assert payload["agent"] == "codex"
        assert payload["tokens_in"] == 0
        assert payload["tokens_out"] == 0
        assert payload["cost_usd"] == 0.0
        # Spec 028 rc3: this vault declares no pipeline.max_cycles, so the
        # estimator can't load — the sidecar fails loud as cost_source=none
        # (never a silent runtime $0).
        assert payload["cost_source"] == "none"
        # The legacy text-streaming path is what was invoked — no
        # stream-json flags should have been added for codex.
        cmd = mock_run.call_args.args[0]
        assert "stream-json" not in cmd

    def test_claude_with_sidecar_uses_stream_json(
        self, agent_call, claude_vault, tmp_path
    ):
        """When --cost-sidecar is set on a claude vault, the wrapper
        switches to stream-json so it can read the final result event."""
        prompt = tmp_path / "p.md"
        prompt.write_text("hi", encoding="utf-8")
        sidecar = (
            tmp_path
            / "_pipeline"
            / "cycles"
            / "cycle-003"
            / "agent-calls"
            / "scout.json"
        )

        # Simulate a stream-json run: one assistant text event, then a
        # terminal `result` envelope carrying total_cost_usd.
        events = [
            '{"type":"assistant","message":{"content":[{"type":"text","text":"working"}]}}',
            '{"type":"result","subtype":"success","total_cost_usd":0.1234,'
            '"duration_ms":42,"is_error":false,'
            '"usage":{"input_tokens":100,"output_tokens":50}}',
        ]
        fake_proc = MagicMock()
        fake_proc.stdin = MagicMock()
        fake_proc.stdout = iter(line + "\n" for line in events)
        fake_proc.wait.return_value = 0
        with patch.object(
            agent_call.subprocess, "Popen", return_value=fake_proc
        ) as mock_popen:
            rc = agent_call.run(claude_vault, "note_writer", prompt, sidecar)

        assert rc == 0
        cmd = mock_popen.call_args.args[0]
        assert "stream-json" in cmd
        assert "--verbose" in cmd
        import json as _json

        payload = _json.loads(sidecar.read_text())
        assert payload["schema_version"] == "1.2"
        assert payload["agent"] == "claude"
        assert payload["cost_usd"] == pytest.approx(0.1234)
        assert payload["cost_source"] == "runtime"
        assert payload["tokens_in"] == 100
        assert payload["tokens_out"] == 50

    def test_missing_binary_returns_exit_2_with_clear_error(
        self, agent_call, codex_vault, tmp_path, capsys
    ):
        prompt = tmp_path / "p.md"
        prompt.write_text("hi", encoding="utf-8")
        with patch.object(agent_call, "_run_in_session_with_timeout") as mock_run:
            mock_run.side_effect = FileNotFoundError("no such binary")
            rc = agent_call.run(codex_vault, "scout", prompt)

        assert rc == 2
        err = capsys.readouterr().err
        assert "codex" in err
        # Error must mention the env escape hatch so the user can fix it.
        assert "CODEX_BIN" in err or "CLAUDE_BIN" in err

    def test_output_file_flag_writes_result(self, agent_call, codex_vault, tmp_path):
        """When --output-file is passed, the agent's stdout text is written
        to that path after a successful run. This is the interface verifier.py
        depends on to read structured JSON back from agent_call.py."""
        prompt = tmp_path / "p.md"
        prompt.write_text("summarise this", encoding="utf-8")
        output_file = tmp_path / "result.json"

        agent_output = '{"status": "ok", "summary": "all good"}'
        with patch.object(agent_call, "_run_in_session_with_timeout") as mock_run:
            proc = MagicMock()
            proc.returncode = 0
            proc.stdout = agent_output
            proc.stderr = ""
            mock_run.return_value = proc
            rc = agent_call.run(codex_vault, "scout", prompt, output_file=output_file)

        assert rc == 0
        assert output_file.exists(), "output file was not created"
        assert output_file.read_text(encoding="utf-8") == agent_output

    @staticmethod
    def _run_stream_json(agent_call, vault, tmp_path, events, *, exit_code=0):
        """``run()`` with BOTH ``--cost-sidecar`` and ``--output-file``.

        That pair is what ``verifier.py`` and the benchmark runner pass, and on
        claude / cursor-agent the sidecar switches the call to stream-json.
        """
        prompt = tmp_path / "p.md"
        prompt.write_text("verify this note", encoding="utf-8")
        sidecar = tmp_path / "cycle-003" / "agent-calls" / "verifier-1.json"
        output_file = tmp_path / "verdict.json"
        fake_proc = MagicMock()
        fake_proc.stdin = MagicMock()
        fake_proc.stdout = iter(line + "\n" for line in events)
        fake_proc.wait.return_value = exit_code
        with patch.object(agent_call.subprocess, "Popen", return_value=fake_proc):
            rc = agent_call.run(
                vault, "verifier", prompt, sidecar, output_file=output_file
            )
        return rc, output_file

    def test_output_file_is_written_on_the_stream_json_path(
        self, agent_call, claude_vault, tmp_path
    ):
        """The answer must reach ``--output-file`` when a sidecar is requested too.

        ``run()`` returned straight out of the streaming branch, before the
        write, so the verifier read back the empty file it had created and
        stamped every note ``pending``. What ``claude --print`` writes to
        stdout in plain mode is the terminal event's ``result`` in stream-json.
        """
        verdict = '{"verdict": "accept", "violations": []}'
        events = [
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": verdict}]},
                }
            ),
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "result": verdict,
                    "total_cost_usd": 0.01,
                    "usage": {"input_tokens": 3, "output_tokens": 4},
                }
            ),
        ]

        rc, output_file = self._run_stream_json(
            agent_call, claude_vault, tmp_path, events
        )

        assert rc == 0
        assert output_file.exists(), "output file was not created"
        assert output_file.read_text(encoding="utf-8") == verdict

    def test_output_file_gets_the_assistant_text_when_the_result_has_none(
        self, agent_call, claude_vault, tmp_path
    ):
        """A terminal event without a ``result`` string must not empty the file."""
        verdict = '{"verdict": "reject", "violations": ["no sources"]}'
        events = [
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": verdict}]},
                }
            ),
            '{"type":"result","subtype":"success","result":"","total_cost_usd":0.0}',
        ]

        rc, output_file = self._run_stream_json(
            agent_call, claude_vault, tmp_path, events
        )

        assert rc == 0
        assert output_file.read_text(encoding="utf-8").strip() == verdict

    def test_output_file_is_not_written_when_the_stream_json_agent_fails(
        self, agent_call, claude_vault, tmp_path
    ):
        """Same contract as every other runtime: written after exit 0 only."""
        events = ['{"type":"result","subtype":"success","result":"partial"}']

        rc, output_file = self._run_stream_json(
            agent_call, claude_vault, tmp_path, events, exit_code=1
        )

        assert rc == 1
        assert not output_file.exists()


# ===========================================================================
# Spec 064 — opencode executor (Phase 1+2: command builder + registry)
# ===========================================================================


def test_opencode_cmd_basic_shape(agent_call, tmp_path):
    """Minimal executor + vault_dir → exact opencode run shape (FR-003)."""
    cmd = agent_call._opencode_cmd({"model": "ollama/qwen2.5"}, tmp_path)
    assert cmd == [
        "opencode",
        "run",
        "--format",
        "json",
        "--model",
        "ollama/qwen2.5",
        "--dir",
        str(tmp_path),
    ]


def test_opencode_cmd_dir_auto_injected(agent_call, tmp_path):
    """``--dir`` is auto-injected from vault_dir exactly once (FR-010)."""
    cmd = agent_call._opencode_cmd({"model": "ollama/m", "args": []}, tmp_path)
    assert cmd.count("--dir") == 1
    assert cmd[cmd.index("--dir") + 1] == str(tmp_path)


def test_opencode_cmd_operator_dir_wins(agent_call, tmp_path):
    """An operator ``--dir`` in args wins — no double flag (FR-010)."""
    cmd = agent_call._opencode_cmd(
        {"model": "ollama/m", "args": ["--dir", "/operator/path"]}, tmp_path
    )
    assert cmd.count("--dir") == 1
    assert cmd[cmd.index("--dir") + 1] == "/operator/path"
    assert str(tmp_path) not in cmd


def test_opencode_cmd_bin_env_override(agent_call, tmp_path, monkeypatch):
    """``OPENCODE_BIN`` overrides the binary token."""
    monkeypatch.setenv("OPENCODE_BIN", "/custom/opencode")
    cmd = agent_call._opencode_cmd({"model": "ollama/m"}, tmp_path)
    assert cmd[0] == "/custom/opencode"


def test_opencode_cmd_variant_and_agent_flags(agent_call):
    """Optional ``--variant`` / ``--agent`` appear only when set."""
    cmd = agent_call._opencode_cmd(
        {"model": "ollama/m", "variant": "high", "agent": "researcher"}
    )
    assert cmd[cmd.index("--variant") + 1] == "high"
    assert cmd[cmd.index("--agent") + 1] == "researcher"
    bare = agent_call._opencode_cmd({"model": "ollama/m"})
    assert "--variant" not in bare
    assert "--agent" not in bare


def test_build_command_opencode_routes_with_vault_dir(agent_call, tmp_path):
    """``_build_command`` routes the ``opencode`` runtime through _opencode_cmd
    with vault_dir (FR-002 single dispatch surface)."""
    executor = {"type": "cli", "runtime": "opencode", "model": "ollama/qwen"}
    cmd = agent_call._build_command(executor, tmp_path)
    assert cmd[0] == "opencode"
    assert cmd[1] == "run"
    assert cmd.count("--dir") == 1
    assert cmd[cmd.index("--dir") + 1] == str(tmp_path)


def test_unknown_runtime_error_lists_opencode(agent_call):
    """The unknown-runtime ValueError now lists ``opencode`` as supported."""
    with pytest.raises(ValueError) as exc:
        agent_call._build_command({"type": "cli", "runtime": "bogus", "model": "m"})
    assert "opencode" in str(exc.value)


def test_existing_executor_commands_unchanged(agent_call, tmp_path):
    """FR-014: adding opencode did not change claude/codex/cursor commands.

    Baselines frozen from the adapters as of spec 064; if a future change
    mutates an existing executor's command, this snapshot catches it.
    """
    claude = agent_call._build_command(
        {"type": "cli", "runtime": "claude", "model": "sonnet", "args": []}
    )
    assert claude == ["claude", "--model", "sonnet", "--print"]

    codex = agent_call._build_command(
        {"type": "cli", "runtime": "codex", "model": "gpt-5.4", "args": []}, tmp_path
    )
    assert codex == ["codex", "exec", "--cd", str(tmp_path), "--model", "gpt-5.4"]

    cursor = agent_call._build_command(
        {"type": "cli", "runtime": "cursor-agent", "model": "gpt-5.4-high", "args": []},
        tmp_path,
    )
    assert cursor == [
        "cursor-agent",
        "-p",
        "--output-format",
        "json",
        "--model",
        "gpt-5.4-high",
        "--trust",
        "--workspace",
        str(tmp_path),
    ]


# --- Phase 3: opencode preflight (FR-015 fail-closed) ----------------------


def test_opencode_preflight_binary_missing_fails_closed(agent_call, monkeypatch):
    monkeypatch.delenv("OPENCODE_BIN", raising=False)
    monkeypatch.setattr(agent_call.shutil, "which", lambda _name: None)
    ok, reason = agent_call._opencode_preflight({"model": "ollama/qwen"})
    assert ok is False
    assert "opencode" in reason and "PATH" in reason


def test_opencode_preflight_local_provider_unreachable(agent_call, monkeypatch):
    monkeypatch.setattr(agent_call.shutil, "which", lambda _name: "/usr/bin/opencode")
    monkeypatch.setattr(
        agent_call, "_opencode_provider_reachable", lambda *a, **k: False
    )
    ok, reason = agent_call._opencode_preflight(
        {"model": "ollama/qwen", "base_url": "http://localhost:11434"}
    )
    assert ok is False
    assert "unreachable" in reason.lower()


def test_opencode_preflight_passes_when_reachable(agent_call, monkeypatch):
    monkeypatch.setattr(agent_call.shutil, "which", lambda _name: "/usr/bin/opencode")
    monkeypatch.setattr(
        agent_call, "_opencode_provider_reachable", lambda *a, **k: True
    )
    ok, reason = agent_call._opencode_preflight({"model": "ollama/qwen"})
    assert ok is True
    assert reason is None


def test_opencode_preflight_hosted_creds_absent_fails(agent_call, monkeypatch):
    monkeypatch.setattr(agent_call.shutil, "which", lambda _name: "/usr/bin/opencode")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(agent_call, "_opencode_has_auth", lambda _provider: False)
    ok, reason = agent_call._opencode_preflight({"model": "openai/gpt-4o"})
    assert ok is False
    assert "openai" in reason.lower()
    assert "credential" in reason.lower() or "auth" in reason.lower()


# --- Phase 4 (US1): NDJSON step_finish parsing + local cost class -----------

_STEP_FINISH = (
    '{"type":"step_finish","part":{"tokens":{"total":8566,"input":8523,'
    '"output":43,"reasoning":0,"cache":{"write":0,"read":0}},"cost":0}}'
)


def test_parse_opencode_ndjson_accumulates_step_finish(agent_call):
    """A single step_finish line → real tokens + cost (verified shape, R1)."""
    stream = (
        '{"type":"step_start","part":{}}\n'
        '{"type":"tool_use","part":{"tool":"write"}}\n' + _STEP_FINISH + "\n"
    )
    usage = agent_call._parse_opencode_ndjson(stream)
    assert usage == {
        "tokens_in": 8523,
        "tokens_out": 43,
        "cost_usd": 0.0,
        "n_steps": 1,
    }


def test_parse_opencode_ndjson_multi_step_accumulates(agent_call):
    """Multi-step agentic run: tokens + cost SUM across step_finish events."""
    step2 = (
        '{"type":"step_finish","part":{"tokens":{"input":100,"output":20},'
        '"cost":0.0123}}'
    )
    usage = agent_call._parse_opencode_ndjson(_STEP_FINISH + "\n" + step2 + "\n")
    assert usage["tokens_in"] == 8523 + 100
    assert usage["tokens_out"] == 43 + 20
    assert usage["cost_usd"] == pytest.approx(0.0123)
    assert usage["n_steps"] == 2


def test_parse_opencode_ndjson_no_step_finish_returns_none(agent_call):
    """No step_finish event (incl. malformed lines) → None → estimator path."""
    stream = '{"type":"step_start","part":{}}\nnot json\n{"type":"tool_use"}\n'
    assert agent_call._parse_opencode_ndjson(stream) is None


def test_extract_opencode_text_concatenates_text_events(agent_call):
    """opencode's answer is the concatenated `text` events, not the raw NDJSON."""
    ndjson = (
        '{"type":"step_start","part":{}}\n'
        '{"type":"text","part":{"text":"{\\"verdict\\": \\"accept\\"}"}}\n'
        '{"type":"step_finish","part":{"tokens":{"input":10,"output":3},"cost":0}}\n'
    )
    assert agent_call._extract_opencode_text(ndjson) == '{"verdict": "accept"}'
    # multi-part text concatenates in order
    multi = (
        '{"type":"text","part":{"text":"Hello "}}\n'
        '{"type":"text","part":{"text":"world"}}\n'
    )
    assert agent_call._extract_opencode_text(multi) == "Hello world"
    # pure tool-write turn (no text events) → empty, not raw NDJSON
    assert agent_call._extract_opencode_text('{"type":"step_start","part":{}}\n') == ""


def test_opencode_cost_class_local_ollama_returns_zero_dollar_runtime(agent_call):
    """Local ollama → measured $0 + real tokens, cost_source 'runtime' (FR-006)."""
    usage = {"tokens_in": 100, "tokens_out": 20, "cost_usd": 0.0, "n_steps": 1}
    cost, tin, tout, source = agent_call._opencode_cost_class("ollama/qwen", usage)
    assert (cost, tin, tout) == (0.0, 100, 20)
    assert source == agent_call._COST_SOURCE_RUNTIME


def test_opencode_cost_class_local_provider_prefix_recognized(agent_call):
    """A non-ollama LOCAL provider prefix (e.g. local/) is also $0/runtime."""
    usage = {"tokens_in": 5, "tokens_out": 7, "cost_usd": 0.0, "n_steps": 1}
    _, _, _, source = agent_call._opencode_cost_class("local/my-model", usage)
    assert source == agent_call._COST_SOURCE_RUNTIME


def test_resolve_cost_opencode_local_sidecar_fields(agent_call):
    """Integration: a local opencode runtime_cost resolves to measured $0 +
    real tokens + cost_source 'runtime' (SC-003)."""
    cost, tin, tout, source = agent_call._resolve_cost(
        stream=None,
        runtime_cost=(0.0, 8523, 43),
        estimate=None,
        agent_name="opencode",
        stage="scout",
        exit_code=0,
        timed_out=False,
        warn=False,
    )
    assert (cost, tin, tout) == (0.0, 8523, 43)
    assert source == agent_call._COST_SOURCE_RUNTIME


# --- US3: metered cost arms -------------------------------------------------


def test_opencode_cost_class_metered_real_dollar_is_runtime(agent_call):
    """Metered + a real per-call dollar (opencode pricing catalog) → 'runtime'."""
    usage = {"tokens_in": 100, "tokens_out": 50, "cost_usd": 0.05, "n_steps": 1}
    cost, tin, tout, source = agent_call._opencode_cost_class("openai/gpt-4o", usage)
    assert cost == pytest.approx(0.05)
    assert (tin, tout) == (100, 50)
    assert source == agent_call._COST_SOURCE_RUNTIME


def test_opencode_cost_class_metered_tokens_only_is_runtime_tokens(agent_call):
    """Metered + tokens but no dollar → real tokens kept, 'runtime_tokens'
    (the estimator supplies the dollar downstream)."""
    usage = {"tokens_in": 100, "tokens_out": 50, "cost_usd": 0.0, "n_steps": 1}
    _, tin, tout, source = agent_call._opencode_cost_class("openai/gpt-4o", usage)
    assert (tin, tout) == (100, 50)
    assert source == agent_call._COST_SOURCE_RUNTIME_TOKENS


def test_opencode_cost_class_no_usage_never_silent_zero_runtime(agent_call):
    """No parseable usage → NEVER a silent (0,..,'runtime'); cost_source 'none'."""
    cost, tin, tout, source = agent_call._opencode_cost_class("openai/gpt-4o", None)
    assert source != agent_call._COST_SOURCE_RUNTIME
    assert source == agent_call._COST_SOURCE_NONE


# --- US5: non-regression + Principle IV -------------------------------------


def test_existing_executor_sidecars_unchanged_after_opencode(agent_call):
    """FR-014: the opencode `resolved_cost` path is gated to opencode — the
    existing cost resolution for codex/claude is byte-identical."""
    codex = agent_call._resolve_cost(
        stream=None,
        runtime_cost=(0.12, 100, 50),
        estimate=None,
        agent_name="codex",
        stage="scout",
        exit_code=0,
        timed_out=False,
        warn=False,
    )
    assert codex == (0.12, 100, 50, agent_call._COST_SOURCE_RUNTIME)
    none = agent_call._resolve_cost(
        stream=None,
        runtime_cost=None,
        estimate=None,
        agent_name="codex",
        stage="scout",
        exit_code=0,
        timed_out=False,
        warn=False,
    )
    assert none[3] == agent_call._COST_SOURCE_NONE


def test_llm_dispatch_allowlist_is_empty():
    """Principle IV: the LLM-dispatch guard allowlist MUST stay empty — opencode
    is reached only via agent_call.py, never a direct claude/codex subprocess."""
    import yaml

    allowlist = (
        Path(__file__).resolve().parents[1] / "_helpers" / "llm_dispatch_allowlist.yaml"
    )
    data = yaml.safe_load(allowlist.read_text(encoding="utf-8"))
    assert not data, "the LLM-dispatch allowlist must stay EMPTY"


def test_run_cli_opencode_records_runtime_cost(agent_call, tmp_path, monkeypatch):
    """The CLI run() path (used by the benchmark) classifies opencode cost from
    its NDJSON — honest $0/runtime, not the codex/estimator fallback."""
    import subprocess as _sp

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text(
        "schema_version: 1\n"
        "default_executor:\n"
        "  type: cli\n"
        "  runtime: opencode\n"
        "  model: ollama/qwen\n",
        encoding="utf-8",
    )
    prompt = tmp_path / "p.txt"
    prompt.write_text("hi", encoding="utf-8")
    sidecar = (
        vault / "_pipeline" / "cycles" / "cycle-001" / "agent-calls" / "scout.json"
    )
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        agent_call,
        "_opencode_preflight_cached",
        lambda _e, **_kw: (True, None),
    )
    ndjson = (
        '{"type":"step_finish","part":{"tokens":{"input":500,"output":20},"cost":0}}\n'
    )
    monkeypatch.setattr(
        agent_call,
        "_run_in_session_with_timeout",
        lambda cmd, *a, **k: _sp.CompletedProcess(cmd, 0, ndjson, ""),
    )

    rc = agent_call.run(
        vault, "scout", prompt, cost_sidecar=sidecar, output_file=tmp_path / "o.txt"
    )

    assert rc == 0
    import json as _json

    sc = _json.loads(sidecar.read_text(encoding="utf-8"))
    assert sc["agent"] == "opencode"
    assert sc["cost_source"] == "runtime"
    assert sc["cost_usd"] == 0.0
    assert sc["tokens_in"] == 500


def test_run_cli_opencode_output_file_is_extracted_text_not_ndjson(
    agent_call, tmp_path, monkeypatch
):
    """The CLI run() must write opencode's ANSWER (text events) to --output-file,
    not the raw NDJSON event stream (the benchmark/verifier scores this)."""
    import json as _json
    import subprocess as _sp

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text(
        "schema_version: 1\n"
        "default_executor:\n"
        "  type: cli\n"
        "  runtime: opencode\n"
        "  model: ollama/qwen3-coder:30b-64k\n",
        encoding="utf-8",
    )
    prompt = tmp_path / "p.txt"
    prompt.write_text("verify this", encoding="utf-8")
    out = tmp_path / "verdict.json"
    monkeypatch.setattr(
        agent_call,
        "_opencode_preflight_cached",
        lambda _e, **_kw: (True, None),
    )
    # opencode emits the real answer inside a `text` event amid control events.
    ndjson = (
        '{"type":"step_start","part":{}}\n'
        '{"type":"text","part":{"text":'
        '"{\\"verdict\\": \\"reject\\", \\"reasons\\": [\\"no source\\"]}"}}\n'
        '{"type":"step_finish","part":{"tokens":{"input":900,"output":40},'
        '"cost":0}}\n'
    )
    monkeypatch.setattr(
        agent_call,
        "_run_in_session_with_timeout",
        lambda cmd, *a, **k: _sp.CompletedProcess(cmd, 0, ndjson, ""),
    )

    rc = agent_call.run(vault, "verifier", prompt, output_file=out)
    assert rc == 0
    content = out.read_text(encoding="utf-8")
    # the ANSWER, parseable as the expected JSON — NOT the raw event stream
    assert _json.loads(content) == {"verdict": "reject", "reasons": ["no source"]}
    assert "step_finish" not in content and "step_start" not in content


def _fake_binary(tmp_path: Path, name: str, body: str) -> Path:
    """An executable stand-in for a runtime CLI that runs the Python ``body``."""
    impl = tmp_path / f"fake_{name}.py"
    impl.write_text(body, encoding="utf-8")
    stub = tmp_path / name
    stub.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{impl}" "$@"\n', encoding="utf-8"
    )
    stub.chmod(0o755)
    return stub


def test_run_cli_parses_the_runtime_cost_without_an_output_file(
    agent_call, tmp_path, monkeypatch, capfd
):
    """The pipeline runner asks for a sidecar and, deliberately, no
    ``--output-file``. Stdout was captured only when a file was wanted, so the
    cost the runtime reported on it was never seen: the sidecar recorded an
    estimate, or ``cost_source: none`` and $0, for a call that had a price."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text(
        "schema_version: 1\n"
        "default_executor:\n"
        "  type: cli\n"
        "  runtime: opencode\n"
        "  model: anthropic/claude-sonnet-5\n",
        encoding="utf-8",
    )
    prompt = tmp_path / "p.txt"
    prompt.write_text("hi", encoding="utf-8")
    sidecar = tmp_path / "cycle-001" / "agent-calls" / "scout.json"
    monkeypatch.setattr(
        agent_call, "_opencode_preflight_cached", lambda _e, **_kw: (True, None)
    )
    monkeypatch.setenv(
        "OPENCODE_BIN",
        str(
            _fake_binary(
                tmp_path,
                "opencode",
                "import sys\n"
                "sys.stdin.read()\n"
                'print(\'{"type":"text","part":{"text":"the answer"}}\')\n'
                'print(\'{"type":"step_finish","part":{"tokens":'
                '{"input":500,"output":20},"cost":0.0123}}\')\n',
            )
        ),
    )

    rc = agent_call.run(vault, "scout", prompt, cost_sidecar=sidecar)

    assert rc == 0
    recorded = json.loads(sidecar.read_text(encoding="utf-8"))
    assert recorded["cost_source"] == "runtime"
    assert recorded["cost_usd"] == pytest.approx(0.0123)
    assert recorded["tokens_in"] == 500
    # ... and the runtime's output still streams through to our stdout, which
    # is the only record of it the runner's stage log has.
    assert "step_finish" in capfd.readouterr().out


def test_run_cli_records_a_timeout_on_the_non_stream_path(
    agent_call, tmp_path, monkeypatch
):
    """A timed-out codex / opencode / script call left no sidecar at all.

    Exit 2 with no sidecar is this script's "runtime unavailable" signal: the
    benchmark reports such a cell as skipped, and the pipeline has no record
    that a call was made and killed. The streaming runtimes already write one.
    """
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text(
        "default_executor:\n"
        "  type: cli\n"
        "  runtime: codex\n"
        "  model: gpt-5.4\n"
        "  timeout_s: 1\n",
        encoding="utf-8",
    )
    prompt = tmp_path / "p.txt"
    prompt.write_text("hi", encoding="utf-8")
    sidecar = tmp_path / "cycle-004" / "agent-calls" / "note_writer-batch-2.json"
    monkeypatch.setenv(
        "CODEX_BIN",
        str(
            _fake_binary(
                tmp_path,
                "codex",
                "import sys, time\nsys.stdin.read()\ntime.sleep(20)\n",
            )
        ),
    )

    rc = agent_call.run(vault, "note_writer", prompt, cost_sidecar=sidecar)

    assert rc == 2
    assert sidecar.is_file(), "a timeout must not look like an unavailable runtime"
    recorded = json.loads(sidecar.read_text(encoding="utf-8"))
    assert recorded["status"] == "failed"
    assert recorded["exit_code"] == 2
    assert recorded["timed_out"] is True
    assert recorded["agent"] == "codex"
    assert recorded["cycle"] == 4
    assert recorded["batch_index"] == 2
    assert recorded["cost_source"] == "none"  # nothing was measured
