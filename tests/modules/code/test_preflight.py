"""Subprocess-contract tests for the code module preflight (spec 051 FR4, spec 038).

Mirrors the youtube preflight test pattern: spawn preflight subprocess, parse
PreflightResult via orchestrator-side ``from_json``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from research_framework.pipeline.source_bridge.preflight_types import PreflightResult

MODULE_DIR = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "research_framework"
    / "modules"
    / "code"
)
PREFLIGHT = MODULE_DIR / "preflight.py"


def _run_preflight(
    sources: dict,
    *,
    watermarks: dict | None = None,
    command: str = "preflight",
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = None
    if env_extra is not None:
        import os

        env = {**os.environ, **env_extra}
    return subprocess.run(
        [sys.executable, str(PREFLIGHT), command],
        input=json.dumps(
            {
                "schema_version": "1.0",
                "sources": sources,
                "watermarks": watermarks or {},
            }
        ),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
        env=env,
    )


def _result(sources: dict, **kw) -> PreflightResult:
    env_extra = kw.pop("env_extra", None)
    proc = _run_preflight(sources, env_extra=env_extra, **kw)
    assert proc.returncode == 0, proc.stderr
    return PreflightResult.from_json(json.loads(proc.stdout))


def test_declared_sources_is_success(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    r = _result({"github_repos": [{"path": str(repo)}]})
    assert r.verdict == "success"


def test_empty_sources_is_fatal_fail() -> None:
    r = _result({})
    assert r.verdict == "fatal_fail"
    assert r.messages


def test_code_env_var_and_local_repo_sanity(tmp_path: Path) -> None:
    """Missing local repo path surfaces warning (spec 038 local-path sanity)."""
    missing = str(tmp_path / "does-not-exist")
    r = _result({"github_repos": [{"path": missing}]})
    assert r.verdict == "warning"
    assert r.verdict != "fatal_fail"
    joined = " ".join(r.messages).lower()
    assert "path" in joined or "missing" in joined or "exist" in joined


def test_remote_only_entry_steers_to_github_module(tmp_path: Path) -> None:
    """A github_repos entry with a remote url but no local path is local-only
    in `code` — preflight warns and points at the `github` module (spec-020
    amendment 2026-06-08)."""
    r = _result({"github_repos": [{"url": "https://github.com/openai/openai-python"}]})
    assert r.verdict == "warning"
    joined = " ".join(r.messages).lower()
    assert "github" in joined
    assert "local" in joined or "remote" in joined
