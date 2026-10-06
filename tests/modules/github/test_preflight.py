"""Subprocess-contract tests for the github module preflight (spec 051 FR4).

Mirrors the oreilly/youtube preflight pattern: spawn the preflight subprocess
(request JSON on stdin → PreflightResult JSON on stdout) and parse via the
orchestrator-side ``PreflightResult.from_json``.

Rules under test:
- ``gh auth status`` failure ⇒ **fatal_fail** (fail-closed — every extraction
  depends on the session token);
- a valid ``github.com/<org>/<repo>`` source with auth OK ⇒ success;
- bare-string entries ⇒ flagged (the extractor's loader drops them);
- non-github URL ⇒ warning; no sources / not-a-mapping / unknown command ⇒
  fatal_fail.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from research_framework.pipeline.source_bridge.preflight_types import PreflightResult

MODULE_DIR = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "research_framework"
    / "modules"
    / "github"
)
PREFLIGHT = MODULE_DIR / "preflight.py"

GH_URL = "https://github.com/openai/openai-python/releases"


@pytest.fixture(autouse=True)
def _default_auth_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Default: gh is authenticated, so sources-validation tests isolate cleanly."""
    auth_fixture = tmp_path / "gh-auth-ok.json"
    auth_fixture.write_text(json.dumps({"ok": True}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_PREFLIGHT_AUTH_FIXTURE", str(auth_fixture))


def _run_preflight(
    sources: object,
    *,
    command: str = "preflight",
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if env_extra is not None:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(PREFLIGHT), command],
        input=json.dumps(
            {"schema_version": "1.0", "sources": sources, "watermarks": {}}
        ),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
        env=env,
    )


def _result(sources: object, **kw) -> PreflightResult:
    proc = _run_preflight(sources, **kw)
    assert proc.returncode == 0, proc.stderr
    return PreflightResult.from_json(json.loads(proc.stdout))


def test_authenticated_valid_source_is_success() -> None:
    r = _result({"github_sources": [{"url": GH_URL}]})
    assert r.verdict == "success"
    assert r.corrections == []


def test_unauthenticated_is_fatal_fail(tmp_path: Path) -> None:
    auth_fixture = tmp_path / "gh-auth-bad.json"
    auth_fixture.write_text(
        json.dumps({"ok": False, "error": "not logged in"}), encoding="utf-8"
    )
    r = _result(
        {"github_sources": [{"url": GH_URL}]},
        env_extra={"GITHUB_PREFLIGHT_AUTH_FIXTURE": str(auth_fixture)},
    )
    assert r.verdict == "fatal_fail"
    joined = " ".join(r.messages).lower()
    assert "github" in joined
    assert "logged in" in joined or "auth" in joined


def test_missing_gh_binary_is_fatal_fail(tmp_path: Path) -> None:
    missing = tmp_path / "definitely-not-gh"
    # Blank the auth fixture so the preflight falls through to the real `gh`
    # path, which then can't find the (missing) binary.
    r = _result(
        {"github_sources": [{"url": GH_URL}]},
        env_extra={"GITHUB_PREFLIGHT_AUTH_FIXTURE": "", "GH_BIN": str(missing)},
    )
    assert r.verdict == "fatal_fail"
    assert any("gh" in m.lower() for m in r.messages)


def test_trailing_whitespace_is_corrected() -> None:
    r = _result({"github_sources": [{"url": f"{GH_URL}  "}]})
    assert r.verdict == "warning"
    corr = next(c for c in r.corrections if "whitespace" in c.reason.lower())
    assert corr.applied is True
    assert corr.suggested == GH_URL


def test_bare_string_is_flagged_fatal_when_only_entry() -> None:
    r = _result({"github_sources": [GH_URL]})
    assert r.verdict == "fatal_fail"
    corr = next(c for c in r.corrections if c.original == GH_URL)
    assert corr.applied is False
    assert "wrap" in corr.reason.lower()


def test_mixed_bare_and_dict_is_warning() -> None:
    r = _result({"github_sources": [{"url": GH_URL}, "https://github.com/o/r/issues"]})
    assert r.verdict == "warning"
    assert any("bare" in m.lower() for m in r.messages)


def test_non_github_url_is_flagged() -> None:
    r = _result({"github_sources": [{"url": "https://example.com/o/r"}]})
    assert r.verdict == "warning"
    assert any("github.com" in m for m in r.messages)


def test_no_sources_is_fatal_fail() -> None:
    r = _result({"github_sources": []})
    assert r.verdict == "fatal_fail"
    assert r.messages


def test_sources_not_a_mapping_is_fatal_fail() -> None:
    r = _result(["not", "a", "mapping"])
    assert r.verdict == "fatal_fail"


def test_unknown_command_is_fatal_fail() -> None:
    proc = _run_preflight({"github_sources": []}, command="extract")
    assert proc.returncode == 0, proc.stderr
    assert PreflightResult.from_json(json.loads(proc.stdout)).verdict == "fatal_fail"
