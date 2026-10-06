"""RED tests for pipeline/preflight.py (T066 / US5) — T070 implementation turns these green."""

from __future__ import annotations

import io
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from research_framework.spec.schema import (
    BudgetConfig,
    CoverageTargets,
    DataSourceConfig,
    NoteTypeConfig,
    RepoEnumeration,
    ScopeConfig,
    SpecConfig,
)


def _import_preflight():
    try:
        from research_framework.pipeline.preflight import (
            PreflightResult,
            SourceCheck,
            check_all,
            check_source,
        )
    except ImportError as exc:
        pytest.fail(f"T070: research_framework.pipeline.preflight must exist: {exc}")
    return SourceCheck, PreflightResult, check_all, check_source


def _minimal_scope() -> ScopeConfig:
    return ScopeConfig(domain="d", organization="o")


def _base_spec(data_sources: list[DataSourceConfig]) -> SpecConfig:
    return SpecConfig(
        name="t",
        location=Path("/tmp/t"),
        owner="o",
        scope=_minimal_scope(),
        note_types=[
            NoteTypeConfig(name="concept", description="", folder="01 - Concepts"),
        ],
        data_sources=data_sources,
        search_dimensions=[],
        coverage_targets=CoverageTargets(),
        budget=BudgetConfig(),
    )


def test_local_repo_missing_path_is_unreachable(tmp_path: Path) -> None:
    _, _, _, check_source = _import_preflight()
    ds = DataSourceConfig(
        name="repo-a",
        type="internal",
        role="behaviour",
        required=True,
        repos=[
            RepoEnumeration(
                name="r1",
                url="https://example.com/x",
                local_path=str(tmp_path / "does-not-exist"),
            ),
        ],
        access_method="local",
    )
    out = check_source(ds, tmp_path)
    assert out.status == "unreachable"
    assert out.name == "repo-a"
    assert (
        "path" in out.detail.lower()
        or "missing" in out.detail.lower()
        or "exist" in out.detail.lower()
    )


def test_local_repo_existing_directory_is_ok(tmp_path: Path) -> None:
    _, _, _, check_source = _import_preflight()
    repo = tmp_path / "clone"
    repo.mkdir()
    ds = DataSourceConfig(
        name="repo-b",
        type="internal",
        role="behaviour",
        required=True,
        repos=[RepoEnumeration(name="r1", url="", local_path=str(repo))],
        access_method="local",
    )
    out = check_source(ds, tmp_path)
    assert out.status == "ok"
    assert out.type == "local_repo"


def test_github_pr_no_auth_is_degraded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, _, _, check_source = _import_preflight()

    def boom(*_a, **_kw):
        raise OSError("missing token")

    monkeypatch.setattr("subprocess.run", boom)
    ds = DataSourceConfig(
        name="gh-pr",
        type="external",
        role="behaviour",
        required=True,
        access_method="github_pr",
        description="PR metadata",
    )
    out = check_source(ds, tmp_path)
    assert out.status == "degraded"
    assert out.type == "github_pr"


def test_github_pr_auth_ok_is_ok(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, _, _, check_source = _import_preflight()
    mock = MagicMock(
        return_value=MagicMock(returncode=0, stdout=b"logged in", stderr=b"")
    )
    monkeypatch.setattr("subprocess.run", mock)
    ds = DataSourceConfig(
        name="gh-ok",
        type="external",
        role="behaviour",
        required=True,
        repos=[
            RepoEnumeration(name="org/r", url="https://github.com/org/r", local_path="")
        ],
        access_method="github_pr",
    )
    out = check_source(ds, tmp_path)
    assert out.status == "ok"
    assert out.type == "github_pr"


def test_web_http_200_is_ok(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _, _, _, check_source = _import_preflight()

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_kw: _Resp())
    ds = DataSourceConfig(
        name="docs",
        type="external",
        role="intent",
        required=True,
        repos=[
            RepoEnumeration(name="u", url="https://docs.example.com/", local_path="")
        ],
        access_method="web",
    )
    out = check_source(ds, tmp_path)
    assert out.status == "ok"
    assert out.type == "web"


def test_web_http_4xx_is_unreachable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, _, _, check_source = _import_preflight()

    def open403(*_a, **_kw):
        raise urllib.error.HTTPError(
            "url", 403, "forbidden", hdrs=None, fp=io.BytesIO(b"")
        )

    monkeypatch.setattr("urllib.request.urlopen", open403)
    ds = DataSourceConfig(
        name="blog",
        type="external",
        role="intent",
        required=False,
        repos=[
            RepoEnumeration(name="u", url="https://blocked.example.com/", local_path="")
        ],
        access_method="web",
    )
    out = check_source(ds, tmp_path)
    assert out.status == "unreachable"


def test_web_connection_error_is_unreachable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, _, _, check_source = _import_preflight()

    def bust(*_a, **_kw):
        raise urllib.error.URLError("no route")

    monkeypatch.setattr("urllib.request.urlopen", bust)
    ds = DataSourceConfig(
        name="rss-home",
        type="external",
        role="domain",
        required=False,
        repos=[
            RepoEnumeration(
                name="u", url="https://down.example.com/feed", local_path=""
            )
        ],
        access_method="web",
    )
    out = check_source(ds, tmp_path)
    assert out.status == "unreachable"


def test_rss_feed_reachable_is_ok(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, _, _, check_source = _import_preflight()

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_kw: _Resp())
    ds = DataSourceConfig(
        name="feed",
        type="external",
        role="intent",
        required=False,
        repos=[
            RepoEnumeration(name="u", url="https://example.com/news.xml", local_path="")
        ],
        access_method="rss",
    )
    out = check_source(ds, tmp_path)
    assert out.status == "ok"
    assert out.type == "rss"


def test_rss_404_is_unreachable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, _, _, check_source = _import_preflight()

    def open404(*_a, **_kw):
        raise urllib.error.HTTPError("url", 404, "nope", hdrs=None, fp=io.BytesIO(b""))

    monkeypatch.setattr("urllib.request.urlopen", open404)
    ds = DataSourceConfig(
        name="dead-feed",
        type="external",
        role="domain",
        required=False,
        repos=[
            RepoEnumeration(
                name="u", url="https://example.com/missing.xml", local_path=""
            )
        ],
        access_method="rss",
    )
    out = check_source(ds, tmp_path)
    assert out.status == "unreachable"


def test_oreilly_mcp_tool_absent_is_unreachable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, _, _, check_source = _import_preflight()
    monkeypatch.setattr(
        "research_framework.pipeline.preflight.oreilly_mcp_tool_available",
        lambda: False,
        raising=False,
    )
    ds = DataSourceConfig(
        name="books",
        type="external",
        role="domain",
        required=False,
        access_method="oreilly",
    )
    out = check_source(ds, tmp_path)
    assert out.status == "unreachable"
    assert out.type == "oreilly"


def test_oreilly_mcp_tool_present_is_ok(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, _, _, check_source = _import_preflight()
    monkeypatch.setattr(
        "research_framework.pipeline.preflight.oreilly_mcp_tool_available",
        lambda: True,
        raising=False,
    )
    ds = DataSourceConfig(
        name="books",
        type="external",
        role="domain",
        required=False,
        access_method="oreilly",
    )
    out = check_source(ds, tmp_path)
    assert out.status == "ok"
    assert out.type == "oreilly"


def test_overall_status_fail_when_required_unreachable(tmp_path: Path) -> None:
    _, PreflightResult, check_all, _ = _import_preflight()
    missing = tmp_path / "nope"
    assert not missing.is_dir()
    spec = _base_spec(
        [
            DataSourceConfig(
                name="must-clone",
                type="internal",
                role="behaviour",
                required=True,
                repos=[RepoEnumeration(name="r", url="", local_path=str(missing))],
                access_method="local",
            ),
        ]
    )
    result = check_all(spec, tmp_path)
    assert isinstance(result, PreflightResult)
    assert result.overall_status == "fail"
    assert result.required_unreachable_count >= 1
    assert any(
        s.name == "must-clone" and s.status == "unreachable" for s in result.sources
    )


def test_overall_status_warn_when_only_enrichment_unreachable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, _, check_all, _ = _import_preflight()

    def open404(*_a, **_kw):
        raise urllib.error.HTTPError("url", 404, "nope", hdrs=None, fp=io.BytesIO(b""))

    monkeypatch.setattr("urllib.request.urlopen", open404)
    repo = tmp_path / "clone"
    repo.mkdir()
    spec = _base_spec(
        [
            DataSourceConfig(
                name="primary",
                type="internal",
                role="behaviour",
                required=True,
                repos=[RepoEnumeration(name="r", url="", local_path=str(repo))],
                access_method="local",
            ),
            DataSourceConfig(
                name="extra-feed",
                type="external",
                role="domain",
                required=False,
                repos=[
                    RepoEnumeration(
                        name="u", url="https://example.com/missing.xml", local_path=""
                    )
                ],
                access_method="rss",
            ),
        ]
    )
    result = check_all(spec, tmp_path)
    assert result.overall_status == "warn"
    assert result.required_unreachable_count == 0
    assert result.enrichment_unreachable_count >= 1


def test_overall_status_pass_all_ok(tmp_path: Path) -> None:
    _, _, check_all, _ = _import_preflight()
    repo = tmp_path / "clone"
    repo.mkdir()
    spec = _base_spec(
        [
            DataSourceConfig(
                name="primary",
                type="internal",
                role="behaviour",
                required=True,
                repos=[RepoEnumeration(name="r", url="", local_path=str(repo))],
                access_method="local",
            ),
        ]
    )
    result = check_all(spec, tmp_path)
    assert result.overall_status == "pass"
    assert result.required_unreachable_count == 0
    assert result.enrichment_unreachable_count == 0


# ---------------------------------------------------------------------------
# A probe that fails in a way urllib / subprocess do not wrap is still a
# verdict on the source, not a traceback out of `--resume`.
# ---------------------------------------------------------------------------


def _url_source(access_method: str, url: str) -> DataSourceConfig:
    return DataSourceConfig(
        name="src",
        type="external",
        role="domain",
        required=False,
        repos=[RepoEnumeration(name="u", url=url, local_path="")],
        access_method=access_method,
    )


@pytest.mark.regression
def test_github_pr_probe_that_times_out_is_degraded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``TimeoutExpired`` is not an ``OSError``; it used to escape."""
    import subprocess

    _, _, _, check_source = _import_preflight()

    def hang(cmd, **_kw):
        raise subprocess.TimeoutExpired(cmd, 30)

    monkeypatch.setattr("subprocess.run", hang)
    out = check_source(_url_source("github_pr", "o/r"), tmp_path)
    assert out.status == "degraded"
    assert "timed out" in out.detail


@pytest.mark.regression
@pytest.mark.parametrize("access_method", ["web", "rss"])
def test_a_read_that_stalls_after_connecting_is_unreachable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, access_method: str
) -> None:
    """A stall after the connection is a bare ``TimeoutError``, not a ``URLError``."""
    _, _, _, check_source = _import_preflight()

    def stall(*_a, **_kw):
        raise TimeoutError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", stall)
    out = check_source(_url_source(access_method, "https://example.com/x"), tmp_path)
    assert out.status == "unreachable"
    assert "timed out" in out.detail


@pytest.mark.regression
@pytest.mark.parametrize("access_method", ["web", "rss"])
@pytest.mark.parametrize(
    "url",
    ["example.com/feed", "http://example.com:port/feed"],
    ids=["no-scheme", "bad-port"],
)
def test_a_url_urllib_refuses_is_unreachable(
    tmp_path: Path, access_method: str, url: str
) -> None:
    """No network: ``ValueError`` / ``http.client.InvalidURL`` before any I/O."""
    _, _, _, check_source = _import_preflight()

    out = check_source(_url_source(access_method, url), tmp_path)
    assert out.status == "unreachable"
    assert out.detail


@pytest.mark.regression
def test_rss_body_in_an_encoding_expat_rejects_is_unreachable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``ET.fromstring`` raises ``LookupError``, not ``ParseError``, for these."""
    _, _, _, check_source = _import_preflight()

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, _n: int) -> bytes:
            return b'<?xml version="1.0" encoding="x-nope"?><rss/>'

    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_kw: _Resp())
    out = check_source(_url_source("rss", "https://example.com/feed.xml"), tmp_path)
    assert out.status == "unreachable"
    assert out.detail == "response is not valid XML"
