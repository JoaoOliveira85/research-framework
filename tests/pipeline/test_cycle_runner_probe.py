"""Tests for `_run_probe_retrieval_and_cache` (spec 025 A2).

Dispatcher signature: ``scripts.agent_call.dispatch(stage, prompt, *,
tier=..., vault_dir=..., cycle_dir=..., timeout_s=...)`` → ``AgentCallResult``
per ``contracts/llm-dispatch.contract.md`` § 1.
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from unittest.mock import patch

from research_framework.spec.schema import (
    BudgetConfig,
    CoverageTargets,
    DataSourceConfig,
    NoteTypeConfig,
    ScopeConfig,
    SpecConfig,
)

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


def _minimal_probe_spec(vault_dir: Path) -> SpecConfig:
    from research_framework.spec.schema import CoverageCategory

    scope = ScopeConfig(
        domain="d",
        organization="o",
        boundaries=["edge-auth"],
        contextual_questions=["What runs first?"],
    )
    return SpecConfig(
        name="probe-vault",
        location=vault_dir,
        owner="t",
        scope=scope,
        note_types=[
            NoteTypeConfig(
                name="concept",
                description="c",
                folder="c/",
                required_sections=["Overview"],
                contextual_questions=["How does caching work?"],
            ),
        ],
        data_sources=[DataSourceConfig(name="s", type="external", priority=2)],
        search_dimensions=["x"],
        coverage_targets=CoverageTargets(
            categories=[
                CoverageCategory(
                    name="n", note_type="concept", target_count=1, met_count=0
                )
            ]
        ),
        budget=BudgetConfig(),
    )


def _write_minimal_settings(
    vault_dir: Path,
    *,
    runtime: str = "claude",
    probe_enabled: bool | None = None,
) -> None:
    lines = [
        "default_executor:",
        "  type: cli",
        f"  runtime: {runtime}",
        "  model: sonnet",
        "stages:",
        "  probe_retrieval:",
    ]
    if probe_enabled is False:
        lines.append("    enabled: false")
    lines.append("    tier: standard")
    vault_dir.joinpath("settings.yaml").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def _synthetic_probe_json() -> str:
    return json.dumps(
        {
            "probes": {
                "coverage-edge-auth": [
                    {"filename": "edge-auth.md", "confidence": "high"}
                ]
            }
        }
    )


def _install_claude_probe_stub(bindir: Path, *, payload: str | None = None) -> None:
    bindir.mkdir(parents=True, exist_ok=True)
    stub = bindir / "claude"
    body = payload or _synthetic_probe_json()
    script = f"#!/bin/sh\nprintf '%s\\n' '{body}'\n"
    stub.write_text(script, encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class TestCycleRunnerProbeDispatchRouting:
    """Spec 025 A2 — T018–T020a."""

    def test_dispatch_through_agent_call(self, tmp_path: Path) -> None:
        from research_framework.pipeline.cycle_runner import (
            _run_probe_retrieval_and_cache,
        )

        _write_minimal_settings(tmp_path)
        spec = _minimal_probe_spec(tmp_path)
        agent_call = _ensure_scripts_agent_call()
        result = agent_call.AgentCallResult(
            stdout=_synthetic_probe_json(),
            stderr="",
            exit_code=0,
        )

        with patch.object(agent_call, "dispatch", return_value=result) as mock_dispatch:
            with patch(
                "research_framework.pipeline.probes.run_cycle_probes",
            ):
                _run_probe_retrieval_and_cache(tmp_path, spec, cycle_num=3)

        mock_dispatch.assert_called_once()
        call_kwargs = mock_dispatch.call_args.kwargs
        assert call_kwargs["stage"] == "probe_retrieval"
        assert call_kwargs["tier"] == "standard"
        assert "Probes:" in call_kwargs["prompt"]
        assert call_kwargs["vault_dir"] == tmp_path
        assert call_kwargs["cycle_dir"] == (
            tmp_path / "_pipeline" / "cycles" / "cycle-003"
        )
        assert call_kwargs["timeout_s"] == 120

    def test_codex_default_respected(self, tmp_path: Path, monkeypatch) -> None:
        from research_framework.pipeline.cycle_runner import (
            _run_probe_retrieval_and_cache,
        )

        _write_minimal_settings(tmp_path, runtime="claude")
        monkeypatch.setenv("RESEARCH_FRAMEWORK_DEFAULT_AGENT", "codex")
        monkeypatch.setenv("CODEX_BIN", str(FAKE_CODEX))
        spec = _minimal_probe_spec(tmp_path)

        codex_payload = f"#!/bin/sh\nprintf '%s\\n' '{_synthetic_probe_json()}'\n"
        fake = tmp_path / "bin" / "codex"
        fake.parent.mkdir(parents=True, exist_ok=True)
        fake.write_text(codex_payload, encoding="utf-8")
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        monkeypatch.setenv(
            "PATH",
            str(tmp_path / "bin") + os.pathsep + os.environ.get("PATH", ""),
        )

        with patch(
            "research_framework.pipeline.probes.run_cycle_probes",
        ):
            _run_probe_retrieval_and_cache(tmp_path, spec, cycle_num=5)

        sidecar_path = (
            tmp_path
            / "_pipeline"
            / "cycles"
            / "cycle-005"
            / "agent-calls"
            / "probe_retrieval.json"
        )
        assert sidecar_path.is_file()
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
        assert payload["agent"] == "codex"

    def test_sidecar_written(self, tmp_path: Path, monkeypatch) -> None:
        from research_framework.pipeline.cycle_runner import (
            _run_probe_retrieval_and_cache,
        )

        _write_minimal_settings(tmp_path)
        monkeypatch.setenv(
            "PATH",
            str(tmp_path / "bin") + os.pathsep + os.environ.get("PATH", ""),
        )
        _install_claude_probe_stub(tmp_path / "bin")
        spec = _minimal_probe_spec(tmp_path)

        with patch(
            "research_framework.pipeline.probes.run_cycle_probes",
        ):
            _run_probe_retrieval_and_cache(tmp_path, spec, cycle_num=7)

        sidecar_path = (
            tmp_path
            / "_pipeline"
            / "cycles"
            / "cycle-007"
            / "agent-calls"
            / "probe_retrieval.json"
        )
        assert sidecar_path.is_file()
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
        assert REQUIRED_SIDECAR_KEYS <= set(payload.keys())
        assert payload["stage"] == "probe_retrieval"
        assert payload["exit_code"] == 0

    def test_probe_disabled_short_circuits(self, tmp_path: Path) -> None:
        from research_framework.pipeline.cycle_runner import (
            _run_probe_retrieval_and_cache,
        )

        _write_minimal_settings(tmp_path, probe_enabled=False)
        spec = _minimal_probe_spec(tmp_path)
        agent_call = _ensure_scripts_agent_call()

        with patch.object(agent_call, "dispatch") as mock_dispatch:
            with patch(
                "research_framework.pipeline.probes.run_cycle_probes",
            ):
                _run_probe_retrieval_and_cache(tmp_path, spec, cycle_num=2)

        mock_dispatch.assert_not_called()
        sidecar_path = (
            tmp_path
            / "_pipeline"
            / "cycles"
            / "cycle-002"
            / "agent-calls"
            / "probe_retrieval.json"
        )
        assert not sidecar_path.exists()
