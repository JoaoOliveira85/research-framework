"""Subprocess-contract tests for the reddit module preflight (spec 051 FR4,
T034).

Mirrors the youtube preflight test pattern
(`tests/modules/youtube/test_preflight.py`): the contract is exercised by
spawning the preflight subprocess (request JSON on stdin → PreflightResult JSON
on stdout) and parsing the result through the orchestrator-side
`PreflightResult.from_json` (so the cross-process payload is validated
end-to-end).

Canonical form: the reddit extractor (`_SUBREDDIT_RX` / `_rss_url_for_source`)
consumes a *full* Reddit URL and resolves it to
`https://www.reddit.com/r/<name>/.rss`. So a bare `<name>` or `/r/<name>`
*mapping value* (`{url: ...}`) is auto-normalized to that canonical `.rss` URL
(applied=true).

Bare-STRING entries (a YAML scalar, not a `{url: ...}` mapping) are dropped by
the extractor's loader (`load_module_sources` keeps dict records only), so
preflight flags them as NOT usable with a wrap correction (applied=false) —
mirroring `tests/modules/youtube/test_preflight.py`.
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
    / "reddit"
)
PREFLIGHT = MODULE_DIR / "preflight.py"


@pytest.fixture(autouse=True)
def _default_reddit_head_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = tmp_path / "reddit-head-ok.json"
    fixture.write_text(json.dumps("application/rss+xml"), encoding="utf-8")
    monkeypatch.setenv("REDDIT_PREFLIGHT_HEAD_FIXTURE", str(fixture))


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


def test_clean_full_rss_urls_is_success() -> None:
    r = _result(
        {
            "reddit_subreddits": [
                {"url": "https://www.reddit.com/r/MachineLearning/.rss"},
                {"url": "https://www.reddit.com/r/LocalLLaMA/.rss"},
            ]
        }
    )
    assert r.verdict == "success"
    assert r.corrections == []


def test_bare_name_is_normalized_and_applied() -> None:
    r = _result({"reddit_subreddits": [{"url": "LocalLLaMA"}]})
    assert r.verdict == "warning"
    corr = next(c for c in r.corrections if c.original == "LocalLLaMA")
    assert corr.suggested == "https://www.reddit.com/r/LocalLLaMA/.rss"
    assert corr.applied is True


def test_slash_r_prefix_is_normalized_and_applied() -> None:
    r = _result({"reddit_subreddits": [{"url": "/r/ClaudeAI"}]})
    assert r.verdict == "warning"
    corr = next(c for c in r.corrections if c.original == "/r/ClaudeAI")
    assert corr.suggested == "https://www.reddit.com/r/ClaudeAI/.rss"
    assert corr.applied is True


def test_bare_string_entry_is_flagged_not_normalized() -> None:
    # A bare STRING (not a {url: ...} mapping) is dropped by the extractor's
    # loader, so preflight must flag it (applied=false) — NOT normalize it.
    # One usable dict entry keeps the verdict at warning (not fatal).
    r = _result(
        {
            "reddit_subreddits": [
                "OpenAI",
                {"url": "https://www.reddit.com/r/MachineLearning/.rss"},
            ]
        }
    )
    assert r.verdict == "warning"
    corr = next(c for c in r.corrections if c.original == "OpenAI")
    assert corr.suggested == '{"url": "OpenAI"}'
    assert corr.applied is False
    assert r.messages  # explains the bare-string is ignored


def test_all_bare_string_entries_is_fatal_fail() -> None:
    # No usable dict entries at all → nothing the extractor can consume.
    r = _result({"reddit_subreddits": ["OpenAI", "LocalLLaMA"]})
    assert r.verdict == "fatal_fail"
    # Each bare string still gets a wrap correction (applied=false).
    assert {c.original for c in r.corrections} == {"OpenAI", "LocalLLaMA"}
    assert all(c.applied is False for c in r.corrections)
    assert any("wrap each as {url: ...}" in m for m in r.messages)


def test_obvious_typo_with_space_is_rejected() -> None:
    r = _result({"reddit_subreddits": [{"url": "/r/Machine Learning"}]})
    corr = next(c for c in r.corrections if c.original == "/r/Machine Learning")
    assert corr.applied is False  # ambiguous typo — suggestion only, not used
    assert r.messages  # explains the rejection


def test_only_typos_is_fatal_fail() -> None:
    # if no entry yields a usable subreddit, there is nothing to extract.
    r = _result({"reddit_subreddits": [{"url": ""}, {"url": "   "}]})
    assert r.verdict == "fatal_fail"
    assert r.messages


def test_empty_sources_is_fatal_fail() -> None:
    r = _result({})
    assert r.verdict == "fatal_fail"
    assert r.messages  # explains why


def test_unknown_command_is_fatal_fail() -> None:
    proc = _run_preflight({"reddit_subreddits": []}, command="extract")
    assert proc.returncode == 0, proc.stderr
    assert PreflightResult.from_json(json.loads(proc.stdout)).verdict == "fatal_fail"


def test_reddit_env_var_and_connectivity_probes(tmp_path: Path) -> None:
    """Env-var presence + connectivity probe via fixture overrides (spec 038)."""
    import os

    rss_url = "https://www.reddit.com/r/MachineLearning/.rss"
    head_fixture = tmp_path / "head-fixture.json"
    head_fixture.write_text(
        json.dumps({rss_url: {"error": "connection refused"}}),
        encoding="utf-8",
    )
    env = {k: v for k, v in os.environ.items()}
    env["REDDIT_PREFLIGHT_HEAD_FIXTURE"] = str(head_fixture)
    env.pop("REDDIT_PREFLIGHT_FAKE_ENV", None)

    r = _result(
        {"reddit_subreddits": [{"url": rss_url}]},
        env_extra=env,
    )
    assert r.verdict == "warning"
    assert r.verdict != "fatal_fail"
    joined = " ".join(r.messages).lower()
    assert "connect" in joined or "refused" in joined or "probe" in joined
