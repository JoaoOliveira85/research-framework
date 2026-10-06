"""Spec 069 FR1 — declared-source backing resolution (contract C1)."""

from __future__ import annotations

from pathlib import Path

from research_framework.spec.schema import DataSourceConfig, RepoEnumeration
from research_framework.spec.source_backing import (
    build_available_registry,
    source_is_backed,
    source_locator,
)


def _src(name: str, **kw) -> DataSourceConfig:
    return DataSourceConfig(name=name, type=kw.pop("type", "external"), **kw)


def test_repo_url_matches_module_trigger_is_backed() -> None:
    """C1-a: a source whose repos[].url matches a module url_pattern → backed."""
    registry = build_available_registry()
    src = _src(
        "GitHub",
        repos=[RepoEnumeration(name="r", url="https://github.com/foo/bar")],
    )
    assert source_is_backed(src, registry) == "backed"


def test_no_locator_source_is_unbacked() -> None:
    """C1-a: a description-only source (no locator) with no kind → unbacked."""
    registry = build_available_registry()
    src = _src("Web", description="general web search")
    assert source_locator(src) is None
    assert source_is_backed(src, registry) == "unbacked"


def test_strategy_hint_short_circuits() -> None:
    """C1-b: kind: strategy_hint → strategy_hint (no module required)."""
    registry = build_available_registry()
    src = _src("Official Documentation", kind="strategy_hint")
    assert source_is_backed(src, registry) == "strategy_hint"


def test_rc7_four_sources_resolution(tmp_path: Path) -> None:
    """C3-b: rc7's 4 sources — GitHub backed (repo URL); the other 3 require
    strategy_hint (description-only) else unbacked."""
    registry = build_available_registry(tmp_path)
    github = _src(
        "GitHub", repos=[RepoEnumeration(name="r", url="https://github.com/o/p")]
    )
    web = _src("Web")
    docs = _src("Official Documentation")
    seed = _src("Codebase Vault Seed")
    assert source_is_backed(github, registry) == "backed"
    assert source_is_backed(web, registry) == "unbacked"
    assert source_is_backed(docs, registry) == "unbacked"
    assert source_is_backed(seed, registry) == "unbacked"
    # Annotating the three description-only sources flips them to valid.
    for s in (web, docs, seed):
        s.kind = "strategy_hint"
        assert source_is_backed(s, registry) == "strategy_hint"


def test_non_canonical_access_string_is_unbacked() -> None:
    """The rc7 trap: a free-text access string with no real handler ("web fetch",
    "GitHub MCP", "local filesystem") and no module/kind → unbacked."""
    registry = build_available_registry()
    for access in ("web fetch", "GitHub MCP", "local filesystem"):
        src = _src("Trap", access_method=access)
        assert source_is_backed(src, registry) == "unbacked", access


def test_canonical_access_method_is_backed() -> None:
    """A canonical access_method has a real preflight/extraction handler → backed
    even without a module-trigger-matching locator."""
    registry = build_available_registry()
    for access in ("local", "github_pr", "web", "rss", "oreilly"):
        src = _src("Handler", access_method=access)
        assert source_is_backed(src, registry) == "backed", access


def test_local_path_locator_resolution() -> None:
    """The D2 locator falls back to repos[].local_path then source-level
    local_path when no url is present."""
    src = _src(
        "Checkout",
        repos=[RepoEnumeration(name="r", url="", local_path="/srv/code")],
    )
    assert source_locator(src) == "/srv/code"
    src2 = _src("Bare", local_path="/srv/other")
    assert source_locator(src2) == "/srv/other"
