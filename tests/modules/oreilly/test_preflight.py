"""Subprocess-contract tests for the oreilly module preflight (spec 051 FR4,
T036).

Mirrors the youtube preflight test pattern
(`tests/modules/youtube/test_preflight.py::_run_preflight`): the contract is
exercised by spawning the preflight subprocess (request JSON on stdin →
PreflightResult JSON on stdout) and parsing the result through the
orchestrator-side `PreflightResult.from_json` (so the cross-process payload is
validated end-to-end).

URL-shape rules under test:
- a valid `learning.oreilly.com/search/?q=…` query → success;
- the legacy `oreilly.com/api/v2/search` form → correction toward the
  search-URL shape (auto-applied when a query param can be mechanically
  lifted, suggestion-only otherwise);
- bare-string entries → flagged (the extractor's loader drops them, so they are
  NOT usable): a suggestion-only wrap correction, plus `fatal_fail` if every
  entry is bare and `warning` when mixed with usable dict entries;
- sources not a mapping / no oreilly sources / unknown command → fatal_fail.
"""

from __future__ import annotations

import json
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
    / "oreilly"
)
PREFLIGHT = MODULE_DIR / "preflight.py"


@pytest.fixture(autouse=True)
def _default_oreilly_probe_fixtures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth_fixture = tmp_path / "oreilly-fake-env.json"
    auth_fixture.write_text(
        json.dumps({"OREILLY_API_KEY": "test-key-preflight"}), encoding="utf-8"
    )
    conn_fixture = tmp_path / "oreilly-connectivity-ok.json"
    conn_fixture.write_text(json.dumps({"ok": True}), encoding="utf-8")
    monkeypatch.setenv("OREILLY_PREFLIGHT_FAKE_ENV", str(auth_fixture))
    monkeypatch.setenv("OREILLY_PREFLIGHT_CONNECTIVITY_FIXTURE", str(conn_fixture))


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


def test_clean_search_url_is_success() -> None:
    r = _result(
        {
            "oreilly_queries": [
                {"url": "https://learning.oreilly.com/search/?q=LLM+agents"},
                {"url": "https://learning.oreilly.com/search/?q=AI+safety"},
            ]
        }
    )
    assert r.verdict == "success"
    assert r.corrections == []


def test_legacy_api_url_with_query_is_corrected_and_applied() -> None:
    legacy = "https://www.oreilly.com/api/v2/search?query=kubernetes+operators"
    r = _result({"oreilly_queries": [{"url": legacy}]})
    assert r.verdict == "warning"
    corr = next(c for c in r.corrections if c.original == legacy)
    assert corr.applied is True  # query lifted mechanically → auto-rewrite
    assert corr.suggested == (
        "https://learning.oreilly.com/search/?q=kubernetes+operators"
    )
    assert "oreilly.com/api/v2/search" in corr.reason


def test_legacy_api_url_without_query_is_suggestion_only() -> None:
    legacy = "https://www.oreilly.com/api/v2/search"
    r = _result({"oreilly_queries": [{"url": legacy}]})
    assert r.verdict == "warning"
    corr = next(c for c in r.corrections if c.original == legacy)
    assert corr.applied is False  # no query to lift → cannot rewrite, suggest only
    assert corr.suggested.startswith("https://learning.oreilly.com/search/?q=")


def test_trailing_whitespace_is_corrected_and_applied() -> None:
    r = _result(
        {"oreilly_queries": [{"url": "https://learning.oreilly.com/search/?q=rust  "}]}
    )
    assert r.verdict == "warning"
    corr = next(c for c in r.corrections if "whitespace" in c.reason.lower())
    assert corr.applied is True
    assert corr.suggested == "https://learning.oreilly.com/search/?q=rust"


def test_bare_string_is_flagged_for_wrapping() -> None:
    # The extractor's loader drops bare strings, so even a well-shaped search URL
    # written as a bare string is NOT usable — preflight must flag it (not report
    # success) so the two components agree on what's usable.
    bare = "https://learning.oreilly.com/search/?q=system+design"
    r = _result({"oreilly_queries": [bare]})
    assert r.verdict == "fatal_fail"  # the only entry is bare → nothing usable
    corr = next(c for c in r.corrections if c.original == bare)
    assert corr.applied is False
    assert corr.suggested == f'{{"url": "{bare}"}}'
    assert "wrap" in corr.reason.lower()


def test_mixed_dict_and_bare_is_warning_with_wrap_correction() -> None:
    bare = "https://learning.oreilly.com/search/?q=bare+entry"
    r = _result(
        {
            "oreilly_queries": [
                {"url": "https://learning.oreilly.com/search/?q=dict+entry"},
                bare,
            ]
        }
    )
    # The dict entry is usable, so this isn't fatal — but the bare entry is
    # silently dropped by the extractor, so it must still be flagged.
    assert r.verdict == "warning"
    corr = next(c for c in r.corrections if c.original == bare)
    assert corr.applied is False
    assert corr.suggested == f'{{"url": "{bare}"}}'


def test_all_bare_strings_is_fatal_fail() -> None:
    r = _result(
        {
            "oreilly_queries": [
                "https://learning.oreilly.com/search/?q=one",
                "https://learning.oreilly.com/search/?q=two",
            ]
        }
    )
    assert r.verdict == "fatal_fail"
    assert any("bare string" in m.lower() for m in r.messages)
    assert len([c for c in r.corrections if "wrap" in c.reason.lower()]) == 2


def test_non_oreilly_url_is_flagged() -> None:
    r = _result({"oreilly_queries": [{"url": "https://example.com/search?q=foo"}]})
    assert r.verdict == "warning"
    assert any("learning.oreilly.com/search" in m for m in r.messages)


def test_sources_not_a_mapping_is_fatal_fail() -> None:
    r = _result(["not", "a", "mapping"])
    assert r.verdict == "fatal_fail"
    assert r.messages


def test_empty_sources_is_fatal_fail() -> None:
    r = _result({})
    assert r.verdict == "fatal_fail"
    assert r.messages  # explains why


def test_unknown_command_is_fatal_fail() -> None:
    proc = _run_preflight({"oreilly_queries": []}, command="extract")
    assert proc.returncode == 0, proc.stderr
    assert PreflightResult.from_json(json.loads(proc.stdout)).verdict == "fatal_fail"


def test_missing_oreilly_api_key_fatal_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """FR-013: mandatory env var unset ⇒ fatal_fail naming module + var (spec 038)."""
    monkeypatch.delenv("OREILLY_API_KEY", raising=False)
    monkeypatch.delenv("OREILLY_PREFLIGHT_FAKE_ENV", raising=False)
    monkeypatch.delenv("OREILLY_PREFLIGHT_CONNECTIVITY_FIXTURE", raising=False)
    r = _result(
        {
            "oreilly_queries": [
                {"url": "https://learning.oreilly.com/search/?q=LLM+agents"}
            ]
        },
    )
    assert r.verdict == "fatal_fail"
    joined = " ".join(r.messages).lower()
    assert "oreilly" in joined
    assert "oreilly_api_key" in joined


def test_unreachable_api_with_block_cycle_fatal_fail(tmp_path: Path) -> None:
    """FR-010: unreachable API + failure_policy block_cycle ⇒ loud fatal_fail."""
    import os

    auth_fixture = tmp_path / "fake-env.json"
    auth_fixture.write_text(
        json.dumps({"OREILLY_API_KEY": "test-key-038"}), encoding="utf-8"
    )
    connectivity_fixture = tmp_path / "connectivity-fixture.json"
    connectivity_fixture.write_text(
        json.dumps({"ok": False, "error": "HTTP 503 Service Unavailable"}),
        encoding="utf-8",
    )
    env = {k: v for k, v in os.environ.items() if k != "OREILLY_API_KEY"}
    env["OREILLY_PREFLIGHT_FAKE_ENV"] = str(auth_fixture)
    env["OREILLY_PREFLIGHT_CONNECTIVITY_FIXTURE"] = str(connectivity_fixture)
    r = _result(
        {
            "oreilly_queries": [
                {"url": "https://learning.oreilly.com/search/?q=LLM+agents"}
            ]
        },
        env_extra=env,
    )
    assert r.verdict == "fatal_fail"
    joined = " ".join(r.messages).lower()
    assert "oreilly" in joined
    assert "503" in joined or "unavailable" in joined or "connectivity" in joined
