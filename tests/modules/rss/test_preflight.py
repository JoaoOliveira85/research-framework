"""Subprocess-contract tests for the rss module preflight (spec 051 FR4, T035).

Mirrors the youtube preflight test pattern
(`tests/modules/youtube/test_preflight.py::_run_preflight`): the contract is
exercised by spawning the preflight subprocess (request JSON on stdin →
PreflightResult JSON on stdout) and parsing the result through the
orchestrator-side `PreflightResult.from_json` (so the cross-process payload is
validated end-to-end).

rss is the only module performing a network HEAD probe. To stay hermetic /
offline (Principle V), EVERY test sets the `RSS_PREFLIGHT_HEAD_FIXTURE` env var
so the probe reads its content-type from a fixture file instead of the network.
The fixture is a JSON file; see the preflight module docstring for the format.
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
    / "rss"
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


def _write_head_fixture(tmp_path: Path, value) -> str:
    """Write a HEAD-probe fixture (a JSON object {url: ct} or a bare JSON string
    applied to all URLs) and return its path."""
    fixture = tmp_path / "head-fixture.json"
    fixture.write_text(json.dumps(value), encoding="utf-8")
    return str(fixture)


def _result(sources: dict, *, head_fixture: str | None = None, **kw) -> PreflightResult:
    env_extra = kw.pop("env_extra", None) or {}
    if head_fixture is not None:
        env_extra = {**env_extra, "RSS_PREFLIGHT_HEAD_FIXTURE": head_fixture}
    proc = _run_preflight(sources, env_extra=env_extra or None, **kw)
    assert proc.returncode == 0, proc.stderr
    return PreflightResult.from_json(json.loads(proc.stdout))


def test_clean_feed_with_xml_probe_is_success(tmp_path: Path) -> None:
    # Fixture reports an XML content-type for every probed URL.
    fixture = _write_head_fixture(tmp_path, "application/rss+xml; charset=utf-8")
    r = _result(
        {"rss_feeds": [{"url": "https://example.com/feed"}]},
        head_fixture=fixture,
    )
    assert r.verdict == "success"
    assert r.corrections == []


def test_doubled_feed_segment_is_deduped_and_applied(tmp_path: Path) -> None:
    fixture = _write_head_fixture(tmp_path, "application/atom+xml")
    r = _result(
        {"rss_feeds": [{"url": "https://example.com/feed/feed/"}]},
        head_fixture=fixture,
    )
    assert r.verdict == "warning"
    corr = next(c for c in r.corrections if "feed/feed" in c.original)
    assert corr.applied is True
    assert corr.suggested == "https://example.com/feed/"


def test_arxiv_list_url_is_suggested_not_applied(tmp_path: Path) -> None:
    fixture = _write_head_fixture(tmp_path, "text/xml")
    r = _result(
        {"rss_feeds": [{"url": "https://arxiv.org/list/cs.AI"}]},
        head_fixture=fixture,
    )
    assert r.verdict == "warning"
    corr = next(c for c in r.corrections if "arxiv.org/list" in c.original)
    assert corr.suggested == "https://rss.arxiv.org/rss/cs.AI"
    assert corr.applied is False  # suggestion only, not auto-applied


def test_arxiv_list_url_generalizes_category(tmp_path: Path) -> None:
    fixture = _write_head_fixture(tmp_path, "text/xml")
    r = _result(
        {"rss_feeds": [{"url": "https://arxiv.org/list/cs.LG"}]},
        head_fixture=fixture,
    )
    corr = next(c for c in r.corrections if "arxiv.org/list" in c.original)
    assert corr.suggested == "https://rss.arxiv.org/rss/cs.LG"


def test_non_xml_head_probe_emits_warning_message(tmp_path: Path) -> None:
    # Fixture maps the specific feed URL to a non-XML content-type → warning.
    fixture = _write_head_fixture(
        tmp_path,
        {"https://example.com/feed": "text/html; charset=utf-8"},
    )
    r = _result(
        {"rss_feeds": [{"url": "https://example.com/feed"}]},
        head_fixture=fixture,
    )
    assert r.verdict == "warning"
    assert any("xml" in m.lower() or "html" in m.lower() for m in r.messages)
    # A non-xml probe is a soft warning, not a correction.
    assert r.corrections == []


def test_bare_string_source_with_dict_entry_is_warning(tmp_path: Path) -> None:
    # A bare-string feed entry is dropped by the extractor's loader, so
    # preflight flags it with a wrap correction (not auto-applied). Because a
    # usable dict entry is also present, the verdict is a soft warning.
    fixture = _write_head_fixture(tmp_path, "application/rss+xml")
    r = _result(
        {
            "rss_feeds": [
                {"url": "https://example.com/feed"},
                "https://bare.example.com/rss",
            ]
        },
        head_fixture=fixture,
    )
    assert r.verdict == "warning"
    corr = next(
        c for c in r.corrections if c.original == "https://bare.example.com/rss"
    )
    assert corr.applied is False
    assert corr.suggested == '{"url": "https://bare.example.com/rss"}'
    assert "bare-string" in corr.reason
    assert any("bare-string" in m for m in r.messages)


def test_all_bare_string_sources_is_fatal_fail(tmp_path: Path) -> None:
    # No dict entries → the extractor's loader drops everything → fatal.
    fixture = _write_head_fixture(tmp_path, "application/rss+xml")
    r = _result(
        {
            "rss_feeds": [
                "https://bare-one.example.com/rss",
                "https://bare-two.example.com/feed",
            ]
        },
        head_fixture=fixture,
    )
    assert r.verdict == "fatal_fail"
    # Each bare string gets a wrap correction (not auto-applied).
    assert len(r.corrections) == 2
    assert all(c.applied is False for c in r.corrections)
    assert any("all source entries are bare strings" in m for m in r.messages)


def test_empty_sources_is_fatal_fail(tmp_path: Path) -> None:
    fixture = _write_head_fixture(tmp_path, "application/rss+xml")
    r = _result({}, head_fixture=fixture)
    assert r.verdict == "fatal_fail"
    assert r.messages  # explains why


def test_no_feeds_declared_is_fatal_fail(tmp_path: Path) -> None:
    fixture = _write_head_fixture(tmp_path, "application/rss+xml")
    r = _result({"rss_feeds": []}, head_fixture=fixture)
    assert r.verdict == "fatal_fail"
    assert r.messages


def test_unknown_command_is_fatal_fail(tmp_path: Path) -> None:
    fixture = _write_head_fixture(tmp_path, "application/rss+xml")
    proc = _run_preflight(
        {"rss_feeds": [{"url": "https://example.com/feed"}]},
        command="extract",
        env_extra={"RSS_PREFLIGHT_HEAD_FIXTURE": fixture},
    )
    assert proc.returncode == 0, proc.stderr
    assert PreflightResult.from_json(json.loads(proc.stdout)).verdict == "fatal_fail"


def test_connectivity_failure_warning_not_fatal_fail(tmp_path: Path) -> None:
    """HEAD probe failure ⇒ warning, NOT fatal_fail (external connectivity = WARN)."""
    feed_url = "https://example.com/feed"
    fixture = _write_head_fixture(
        tmp_path,
        {feed_url: {"error": "connection refused"}},
    )
    r = _result(
        {"rss_feeds": [{"url": feed_url}]},
        head_fixture=fixture,
    )
    assert r.verdict == "warning"
    assert r.verdict != "fatal_fail"
    joined = " ".join(r.messages).lower()
    assert "connect" in joined or "refused" in joined or "probe" in joined
