"""Tests for `plan_narrator.prepend_narrative` (feature 017 + spec 025 A1).

Dispatcher signature (T007): ``scripts.agent_call.dispatch(stage, prompt, *,
tier=..., agent=None, vault_dir=..., cycle_dir=..., timeout_s=...)``
→ ``AgentCallResult`` per ``contracts/llm-dispatch.contract.md`` § 1.

Legacy tests use a fake ``claude`` on ``PATH`` via settings ``runtime: claude``.
A1 tests assert routing through ``dispatch`` and contract sidecars.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import stat
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
FAKE_CODEX = REPO_ROOT / "tests" / "_helpers" / "fake_codex_binary.sh"

REQUIRED_SIDECAR_KEYS = frozenset(
    {
        "schema_version",
        "stage",
        "agent",
        "agent_kind",
        "status",
        "cycle",
        "tier",
        "cost_usd",
        "tokens_in",
        "tokens_out",
        "latency_ms",
        "started_at",
        "completed_at",
        "exit_code",
    }
)


def _ensure_scripts_agent_call():
    name = "scripts.agent_call"
    if name in sys.modules:
        return sys.modules[name]
    script_path = REPO_ROOT / "scripts" / "agent_call.py"
    spec = importlib.util.spec_from_file_location(name, script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _write_minimal_settings(vault_dir: Path, *, runtime: str = "claude") -> None:
    vault_dir.joinpath("settings.yaml").write_text(
        textwrap.dedent(
            f"""\
            default_executor:
              type: cli
              runtime: {runtime}
              model: sonnet
            stages:
              plan_narrator:
                tier: standard
            """
        ),
        encoding="utf-8",
    )


def _deterministic_plan_tail() -> str:
    return textwrap.dedent("""\
        ## Coverage state

        | Category | Target | Met | Fill % | Priority | Unmet topics |
        |----------|--------|-----|--------|----------|--------------|
        | aa | 3 | 0 | 0% | 80 | x |

        ## Cycle focus

        This cycle MUST produce ≥ 70% of its notes in the following categories:

        - bb (0% filled)
        - cc (0% filled)
        - dd (0% filled)

        ## Priority queue

        Each entry: `<title> · category · score · provenance · sources`.

        1. T1 · aa · 0.5 · spec_gap · src

        ## Exclusions

        The note-writer MUST NOT propose any topic whose canonical filename matches:

        - out-of-scope: zz
        """)


def _plan_with_empty_focus(front_yaml: str) -> str:
    head = textwrap.dedent(f"""\
        {front_yaml}
        ## Focus rationale

        """)
    return head + _deterministic_plan_tail()


def _tail_from_coverage(text: str) -> str:
    idx = text.find("## Coverage state")
    assert idx >= 0
    return text[idx:]


def _install_claude_stub(
    bindir: Path, *, mode: str, rationale: str | None = None
) -> None:
    """Install a fake ``claude`` binary into ``bindir``.

    The stub mimics real claude's two output formats based on its argv:
    when invoked with ``--output-format stream-json`` (the cost-capture
    path used by ``_run_claude_with_cost`` and ``dispatch()``), it emits
    an ``assistant`` text event followed by a terminal ``result``
    envelope so that downstream parsers populate ``saw_result=True`` and
    record a sidecar with ``status: "ok"``. Without stream-json, it just
    prints the body text the way ``claude --print`` does.

    Previously the stub only printed plain text regardless of args, which
    relied on the wrapper accepting "exit 0 + no result envelope" as
    success. That behaviour was tightened in PR #28 / Copilot fix #6.
    """
    bindir.mkdir(parents=True, exist_ok=True)
    stub = bindir / "claude"
    if mode == "ok":
        body = rationale or (
            "We emphasise category bb first because it is a hard gate for "
            "the vault quality bar."
        )
        # 512 single-line payload avoids shell/heredoc quoting issues.
        result_env = (
            '{"type":"result","subtype":"success","total_cost_usd":0.0,'
            '"duration_ms":1,"is_error":false,'
            '"usage":{"input_tokens":1,"output_tokens":1}}'
        )
        assistant_env = (
            '{"type":"assistant","message":{"content":'
            f'[{{"type":"text","text":"{body}"}}]}}'
        )
        script = (
            "#!/bin/sh\n"
            'case "$*" in\n'
            f"  *stream-json*) printf '%s\\n%s\\n' '{assistant_env}' '{result_env}' ;;\n"
            f"  *) printf '%s\\n' '{body}' ;;\n"
            "esac\n"
        )
    else:
        script = "#!/bin/sh\nexit 1\n"
    stub.write_text(script, encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class TestPlanNarratorDispatchRouting:
    """Spec 025 A1 — T010–T012."""

    def test_dispatch_through_agent_call(self, tmp_path: Path) -> None:
        from research_framework.pipeline.plan_narrator import prepend_narrative

        _write_minimal_settings(tmp_path)
        front = textwrap.dedent("""\
            ---
            cycle_number: 3
            generated_at: "2026-05-15T00:00:00Z"
            framework_version: "0.2.17"
            cycle_quota: 5
            schema_version: "1"
            ---

            """)
        plan_path = tmp_path / "_pipeline" / "research-plan.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(_plan_with_empty_focus(front), encoding="utf-8")

        agent_call = _ensure_scripts_agent_call()
        result = agent_call.AgentCallResult(
            stdout="Synthetic focus rationale for cycle three.",
            stderr="",
            exit_code=0,
        )

        with patch.object(agent_call, "dispatch", return_value=result) as mock_dispatch:
            prepend_narrative(tmp_path, cycle_number=3)

        mock_dispatch.assert_called_once()
        call_kwargs = mock_dispatch.call_args.kwargs
        assert call_kwargs["stage"] == "plan_narrator"
        assert call_kwargs["tier"] == "standard"
        assert call_kwargs["prompt"].strip()
        assert call_kwargs["vault_dir"] == tmp_path
        assert (
            call_kwargs["cycle_dir"] == tmp_path / "_pipeline" / "cycles" / "cycle-003"
        )

    def test_codex_default_respected(self, tmp_path: Path, monkeypatch) -> None:
        from research_framework.pipeline.plan_narrator import prepend_narrative

        _write_minimal_settings(tmp_path, runtime="claude")
        monkeypatch.setenv("RESEARCH_FRAMEWORK_DEFAULT_AGENT", "codex")
        monkeypatch.setenv("CODEX_BIN", str(FAKE_CODEX))
        front = textwrap.dedent("""\
            ---
            cycle_number: 5
            generated_at: "2026-05-15T00:00:00Z"
            framework_version: "0.2.17"
            cycle_quota: 5
            schema_version: "1"
            ---

            """)
        plan_path = tmp_path / "_pipeline" / "research-plan.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(_plan_with_empty_focus(front), encoding="utf-8")

        prepend_narrative(tmp_path, cycle_number=5)

        sidecar_path = (
            tmp_path
            / "_pipeline"
            / "cycles"
            / "cycle-005"
            / "agent-calls"
            / "plan_narrator.json"
        )
        assert sidecar_path.is_file()
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
        assert payload["agent"] == "codex"

    def test_sidecar_written(self, tmp_path: Path, monkeypatch) -> None:
        from research_framework.pipeline.plan_narrator import prepend_narrative

        _write_minimal_settings(tmp_path)
        monkeypatch.setenv(
            "PATH",
            str(tmp_path / "bin") + os.pathsep + os.environ.get("PATH", ""),
        )
        _install_claude_stub(
            tmp_path / "bin",
            mode="ok",
            rationale="Sidecar test narrative for the focus section.",
        )
        front = textwrap.dedent("""\
            ---
            cycle_number: 7
            generated_at: "2026-05-15T00:00:00Z"
            framework_version: "0.2.17"
            cycle_quota: 5
            schema_version: "1"
            ---

            """)
        plan_path = tmp_path / "_pipeline" / "research-plan.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(_plan_with_empty_focus(front), encoding="utf-8")

        prepend_narrative(tmp_path, cycle_number=7)

        sidecar_path = (
            tmp_path
            / "_pipeline"
            / "cycles"
            / "cycle-007"
            / "agent-calls"
            / "plan_narrator.json"
        )
        assert sidecar_path.is_file()
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
        assert REQUIRED_SIDECAR_KEYS <= set(payload.keys())
        assert payload["schema_version"] == "1.2"
        assert payload["stage"] == "plan_narrator"
        assert payload["agent_kind"] in ("fake", "real")
        assert payload["status"] == "ok"
        assert payload["cycle"] == 7
        assert payload["exit_code"] == 0


class TestPrependNarrativeSuccess:
    def test_header_respects_word_budget(self, tmp_path: Path, monkeypatch) -> None:
        from research_framework.pipeline.plan_narrator import prepend_narrative

        _write_minimal_settings(tmp_path)
        monkeypatch.setenv(
            "PATH",
            str(tmp_path / "bin") + os.pathsep + os.environ.get("PATH", ""),
        )
        words = ["word"] * 199
        _install_claude_stub(
            tmp_path / "bin",
            mode="ok",
            rationale=" ".join(words),
        )
        front = textwrap.dedent("""\
            ---
            cycle_number: 4
            generated_at: "2026-05-15T00:00:00Z"
            framework_version: "0.2.17"
            cycle_quota: 5
            schema_version: "1"
            ---

            """)
        plan_path = tmp_path / "_pipeline" / "research-plan.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        before = _plan_with_empty_focus(front)
        plan_path.write_text(before, encoding="utf-8")
        tail_before = _tail_from_coverage(before)

        prepend_narrative(tmp_path, cycle_number=4)

        after = plan_path.read_text(encoding="utf-8")
        m = re.search(
            r"(?ms)^## Focus rationale\s+(.*?)^## Coverage state",
            after,
        )
        assert m, "missing Focus rationale / Coverage state boundary"
        header = m.group(1).strip()
        assert len(header.split()) <= 200
        assert _tail_from_coverage(after) == tail_before


class TestPrependNarrativeFailure:
    def test_falls_back_to_canned_cycle_priority_header(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from research_framework.pipeline.plan_narrator import prepend_narrative

        _write_minimal_settings(tmp_path)
        monkeypatch.setenv(
            "PATH",
            str(tmp_path / "bin") + os.pathsep + os.environ.get("PATH", ""),
        )
        _install_claude_stub(tmp_path / "bin", mode="fail")
        front = textwrap.dedent("""\
            ---
            cycle_number: 2
            generated_at: "2026-05-15T00:00:00Z"
            framework_version: "0.2.17"
            cycle_quota: 3
            schema_version: "1"
            ---

            """)
        plan_path = tmp_path / "_pipeline" / "research-plan.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        before = _plan_with_empty_focus(front)
        plan_path.write_text(before, encoding="utf-8")
        tail_before = _tail_from_coverage(before)

        prepend_narrative(tmp_path, cycle_number=2)

        after = plan_path.read_text(encoding="utf-8")
        assert "Cycle 2 priority:" in after
        for name in ("bb", "cc", "dd"):
            assert name in after
        assert _tail_from_coverage(after) == tail_before


class TestPrependNarrativeIsolation:
    def test_only_focus_section_content_changes(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from research_framework.pipeline.plan_narrator import prepend_narrative

        _write_minimal_settings(tmp_path)
        monkeypatch.setenv(
            "PATH",
            str(tmp_path / "bin") + os.pathsep + os.environ.get("PATH", ""),
        )
        _install_claude_stub(tmp_path / "bin", mode="ok", rationale="Narrative only.")
        front = textwrap.dedent("""\
            ---
            cycle_number: 1
            generated_at: "2026-05-15T00:00:00Z"
            framework_version: "0.2.17"
            cycle_quota: 1
            schema_version: "1"
            ---

            """)
        plan_path = tmp_path / "_pipeline" / "research-plan.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        before = _plan_with_empty_focus(front)
        plan_path.write_text(before, encoding="utf-8")
        want_tail = _tail_from_coverage(before)

        prepend_narrative(tmp_path, cycle_number=1)

        after = plan_path.read_text(encoding="utf-8")
        assert _tail_from_coverage(after) == want_tail
