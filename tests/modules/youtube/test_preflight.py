"""Subprocess-contract tests for the youtube module preflight (spec 051 FR4,
T033).

Mirrors the extractor test pattern (`tests/source_bridge/test_youtube_module.py
::_run_extractor`): the contract is exercised by spawning the preflight
subprocess (request JSON on stdin → PreflightResult JSON on stdout) and parsing
the result through the orchestrator-side `PreflightResult.from_json` (so the
cross-process payload is validated end-to-end).
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
    / "youtube"
)
PREFLIGHT = MODULE_DIR / "preflight.py"


@pytest.fixture(autouse=True)
def _default_youtube_fake_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Hermetic auth probe for tests that are not explicitly exercising missing keys."""
    auth_fixture = tmp_path / "youtube-fake-env.json"
    auth_fixture.write_text(
        json.dumps({"YOUTUBE_API_KEY": "test-key-preflight"}), encoding="utf-8"
    )
    monkeypatch.setenv("YOUTUBE_PREFLIGHT_FAKE_ENV", str(auth_fixture))


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


def test_clean_channel_and_video_is_success() -> None:
    r = _result(
        {
            "youtube_videos": [{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}],
            "youtube_channels": [{"url": "https://www.youtube.com/@SomeChannel"}],
        }
    )
    assert r.verdict == "success"
    assert r.corrections == []


def test_trailing_whitespace_is_corrected_and_applied() -> None:
    r = _result(
        {"youtube_videos": [{"url": "https://www.youtube.com/watch?v=abc123XYZ_-  "}]}
    )
    assert r.verdict == "warning"
    corr = next(c for c in r.corrections if c.reason.lower().find("whitespace") >= 0)
    assert corr.applied is True
    assert corr.suggested == "https://www.youtube.com/watch?v=abc123XYZ_-"


def test_plain_handle_without_at_is_suggested() -> None:
    r = _result({"youtube_channels": [{"url": "MyChannel"}]})
    assert r.verdict == "warning"
    corr = next(c for c in r.corrections if c.original == "MyChannel")
    assert corr.suggested == "@MyChannel"
    assert corr.applied is False  # suggestion only, not auto-applied


def test_at_handle_channel_is_success() -> None:
    r = _result({"youtube_channels": [{"url": "@MyChannel"}]})
    assert r.verdict == "success"


def test_channel_id_url_is_success() -> None:
    r = _result(
        {"youtube_channels": [{"url": "https://www.youtube.com/channel/UCabcdef12345"}]}
    )
    assert r.verdict == "success"


def test_empty_sources_is_fatal_fail() -> None:
    r = _result({})
    assert r.verdict == "fatal_fail"
    assert r.messages  # explains why


def test_unknown_command_is_fatal_fail() -> None:
    proc = _run_preflight({"youtube_videos": []}, command="extract")
    assert proc.returncode == 0, proc.stderr
    assert PreflightResult.from_json(json.loads(proc.stdout)).verdict == "fatal_fail"


def test_bare_string_entry_is_flagged_not_silently_accepted() -> None:
    # mix of a usable dict entry + a bare string → warning + a wrap correction
    # (the extractor's loader drops bare strings, so preflight must flag them).
    r = _result(
        {
            "youtube_videos": [
                {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
                "https://www.youtube.com/watch?v=abc123XYZ_",
            ]
        }
    )
    assert r.verdict == "warning"
    corr = next(c for c in r.corrections if "bare-string" in c.reason)
    assert corr.applied is False


def test_all_bare_string_entries_is_fatal_fail() -> None:
    r = _result({"youtube_videos": ["https://www.youtube.com/watch?v=abc123XYZ_"]})
    assert r.verdict == "fatal_fail"  # no usable dict sources for the extractor


def test_missing_youtube_api_key_fatal_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """FR-013: mandatory env var unset ⇒ fatal_fail naming module + var (spec 038)."""
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.delenv("YOUTUBE_PREFLIGHT_FAKE_ENV", raising=False)
    r = _result(
        {"youtube_videos": [{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}]},
    )
    assert r.verdict == "fatal_fail"
    joined = " ".join(r.messages).lower()
    assert "youtube" in joined
    assert "youtube_api_key" in joined


def test_youtube_preflight_fake_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hermetic env-presence probe via YOUTUBE_PREFLIGHT_FAKE_ENV (no real credentials)."""
    sources = {
        "youtube_videos": [{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}]
    }
    fixture = tmp_path / "fake-env.json"
    fixture.write_text(
        json.dumps({"YOUTUBE_API_KEY": "test-key-038"}), encoding="utf-8"
    )
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.delenv("YOUTUBE_PREFLIGHT_FAKE_ENV", raising=False)

    without_override = _result(sources)
    assert without_override.verdict == "fatal_fail"

    monkeypatch.setenv("YOUTUBE_PREFLIGHT_FAKE_ENV", str(fixture))
    r = _result(sources)
    assert r.verdict != "fatal_fail"
    joined = " ".join(r.messages).lower()
    assert "missing env var youtube_api_key" not in joined
