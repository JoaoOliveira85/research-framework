"""Subprocess-contract tests for the atlassian module preflight (spec 051 FR4).

Mirrors the oreilly preflight pattern. Rules under test:
- both mandatory env vars present + connectivity OK + valid URLs ⇒ success;
- a missing mandatory env var ⇒ **fatal_fail** (fail-closed);
- connectivity failure under block_cycle ⇒ fatal_fail;
- bare-string entries ⇒ flagged; non-atlassian URL ⇒ warning;
- no sources / not-a-mapping / unknown command ⇒ fatal_fail;
- credentials never leak into the preflight output.
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
    / "atlassian"
)
PREFLIGHT = MODULE_DIR / "preflight.py"

JIRA_URL = "https://example.atlassian.net/jira/projects/PROJ"
CONFLUENCE_URL = "https://example.atlassian.net/wiki/spaces/ENG"
SENTINEL_EMAIL = "leak-email@example.com"
SENTINEL_TOKEN = "sentinel-token-do-not-leak-98765"


@pytest.fixture(autouse=True)
def _default_probe_fixtures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_fixture = tmp_path / "atlassian-fake-env.json"
    env_fixture.write_text(
        json.dumps(
            {"ATLASSIAN_EMAIL": "you@example.com", "ATLASSIAN_API_TOKEN": "tok"}
        ),
        encoding="utf-8",
    )
    conn_fixture = tmp_path / "atlassian-conn-ok.json"
    conn_fixture.write_text(json.dumps({"ok": True}), encoding="utf-8")
    monkeypatch.setenv("ATLASSIAN_PREFLIGHT_FAKE_ENV", str(env_fixture))
    monkeypatch.setenv("ATLASSIAN_PREFLIGHT_CONNECTIVITY_FIXTURE", str(conn_fixture))


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


def test_valid_sources_is_success() -> None:
    r = _result(
        {
            "jira_projects": [{"url": JIRA_URL}],
            "confluence_spaces": [{"url": CONFLUENCE_URL}],
        }
    )
    assert r.verdict == "success"
    assert r.corrections == []


def test_missing_token_is_fatal_fail(tmp_path: Path) -> None:
    env_fixture = tmp_path / "only-email.json"
    env_fixture.write_text(
        json.dumps({"ATLASSIAN_EMAIL": "you@example.com"}), encoding="utf-8"
    )
    r = _result(
        {"jira_projects": [{"url": JIRA_URL}]},
        env_extra={"ATLASSIAN_PREFLIGHT_FAKE_ENV": str(env_fixture)},
    )
    assert r.verdict == "fatal_fail"
    joined = " ".join(r.messages).lower()
    assert "atlassian" in joined
    assert "atlassian_api_token" in joined


def test_missing_email_is_fatal_fail(tmp_path: Path) -> None:
    """Spec 051 FR4 requires BOTH mandatory vars fail-closed — pin the email half
    symmetrically to the token half."""
    env_fixture = tmp_path / "only-token.json"
    env_fixture.write_text(json.dumps({"ATLASSIAN_API_TOKEN": "tok"}), encoding="utf-8")
    r = _result(
        {"jira_projects": [{"url": JIRA_URL}]},
        env_extra={"ATLASSIAN_PREFLIGHT_FAKE_ENV": str(env_fixture)},
    )
    assert r.verdict == "fatal_fail"
    assert "atlassian_email" in " ".join(r.messages).lower()


def test_connectivity_failure_is_fatal_fail(tmp_path: Path) -> None:
    conn = tmp_path / "conn-bad.json"
    conn.write_text(
        json.dumps({"ok": False, "error": "HTTP 401 Unauthorized"}), encoding="utf-8"
    )
    r = _result(
        {"jira_projects": [{"url": JIRA_URL}]},
        env_extra={"ATLASSIAN_PREFLIGHT_CONNECTIVITY_FIXTURE": str(conn)},
    )
    assert r.verdict == "fatal_fail"
    joined = " ".join(r.messages).lower()
    assert "401" in joined or "connectivity" in joined


def test_trailing_whitespace_corrected() -> None:
    r = _result({"jira_projects": [{"url": f"{JIRA_URL}  "}]})
    assert r.verdict == "warning"
    corr = next(c for c in r.corrections if "whitespace" in c.reason.lower())
    assert corr.applied is True
    assert corr.suggested == JIRA_URL


def test_all_bare_strings_is_fatal_fail() -> None:
    r = _result({"jira_projects": [JIRA_URL, CONFLUENCE_URL]})
    assert r.verdict == "fatal_fail"
    assert any("bare" in m.lower() for m in r.messages)


def test_mixed_bare_and_dict_is_warning() -> None:
    r = _result({"jira_projects": [{"url": JIRA_URL}, "bare-one"]})
    assert r.verdict == "warning"
    assert any("bare" in m.lower() for m in r.messages)


def test_non_atlassian_url_is_flagged() -> None:
    r = _result({"jira_projects": [{"url": "https://example.com/jira/projects/PROJ"}]})
    assert r.verdict == "warning"
    assert any("atlassian.net" in m for m in r.messages)


def test_non_atlassian_url_without_conn_fixture_is_warning() -> None:
    """A bad URL shape must degrade to a warning even on the REAL probe path.

    Without this guard the missing site made ``_connectivity_probe`` return
    "no atlassian.net site URL to probe" → a misleading connectivity FATAL under
    block_cycle. Disabling the ok-fixture forces the real code path so the
    warning-not-fatal contract is actually exercised (the default fixture would
    otherwise short-circuit it to ok=True before the site check).
    """
    r = _result(
        {"jira_projects": [{"url": "https://example.com/jira/projects/PROJ"}]},
        env_extra={"ATLASSIAN_PREFLIGHT_CONNECTIVITY_FIXTURE": ""},
    )
    assert r.verdict == "warning"
    assert any("atlassian.net" in m for m in r.messages)


def test_no_sources_is_fatal_fail() -> None:
    r = _result({})
    assert r.verdict == "fatal_fail"
    assert r.messages


def test_sources_not_a_mapping_is_fatal_fail() -> None:
    r = _result(["nope"])
    assert r.verdict == "fatal_fail"


def test_unknown_command_is_fatal_fail() -> None:
    proc = _run_preflight({"jira_projects": []}, command="extract")
    assert proc.returncode == 0, proc.stderr
    assert PreflightResult.from_json(json.loads(proc.stdout)).verdict == "fatal_fail"


def test_credentials_never_leak_in_preflight_output(tmp_path: Path) -> None:
    import base64

    env_fixture = tmp_path / "sentinel-env.json"
    env_fixture.write_text(
        json.dumps(
            {
                "ATLASSIAN_EMAIL": SENTINEL_EMAIL,
                "ATLASSIAN_API_TOKEN": SENTINEL_TOKEN,
            }
        ),
        encoding="utf-8",
    )
    proc = _run_preflight(
        {"jira_projects": [{"url": JIRA_URL}]},
        env_extra={"ATLASSIAN_PREFLIGHT_FAKE_ENV": str(env_fixture)},
    )
    b64 = base64.b64encode(f"{SENTINEL_EMAIL}:{SENTINEL_TOKEN}".encode()).decode()
    for blob in (proc.stdout, proc.stderr):
        assert SENTINEL_TOKEN not in blob
        assert SENTINEL_EMAIL not in blob
        assert b64 not in blob
