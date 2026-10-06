"""Spec 070 F1/FR1 — a declared source must be able to ground a citation to itself.

Before this: ``build_credibility_context`` indexed ``ds.repos[].url`` only. A
``kind: strategy_hint`` source has no ``repos`` — that is the entire point of the
069 concept — so its ``default_credibility`` never reached the index the verifier
consults. It was silently inert: no error, no warning, no grounding.

The sharpest case, from the live vault that surfaced this: notes about
``engineering.bravo.example`` and ``engineering.charlie.example`` were quarantined for
"no visible source default_credibility" while both domains were declared
``data_sources`` carrying ``default_credibility: primary``.

FR1's prerequisite, found during review: ``DataSourceConfig`` had no ``url``
field at all, so every ``url:`` in every vault spec was discarded at parse time.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework.spec.schema import (
    BudgetConfig,
    CoverageCategory,
    CoverageTargets,
    DataSourceConfig,
    NoteTypeConfig,
    RepoEnumeration,
    ScopeConfig,
    SpecConfig,
)
from research_framework.vault.credibility import (
    CredibilityUnresolved,
    Level,
    build_credibility_context,
    effective_level,
)


def _spec(vault_dir: Path, data_sources: list[DataSourceConfig]) -> SpecConfig:
    return SpecConfig(
        name="strategy-hint-test",
        location=vault_dir,
        owner="test",
        scope=ScopeConfig(domain="d", organization="o"),
        note_types=[
            NoteTypeConfig(
                name="publication",
                description="d",
                folder="04 - Publications",
                authoritative_role="domain",
            )
        ],
        data_sources=data_sources,
        search_dimensions=["domain"],
        coverage_targets=CoverageTargets(
            categories=[
                CoverageCategory(
                    name="publications", note_type="publication", target_count=1
                )
            ]
        ),
        budget=BudgetConfig(),
    )


def _level(spec: SpecConfig, vault_dir: Path, url: str) -> str:
    ctx = build_credibility_context(spec, vault_dir)
    try:
        return effective_level({"url": url}, {"type": "publication"}, ctx).value
    except CredibilityUnresolved:
        return "UNRESOLVED"


# --------------------------------------------------------------------------
# Prerequisite: the schema must actually carry `url`.
# --------------------------------------------------------------------------


def test_data_source_url_survives_round_trip() -> None:
    """`url:` was silently discarded at parse — every vault spec declared it."""
    ds = DataSourceConfig.from_dict(
        {
            "name": "Regional company engineering blogs",
            "type": "external",
            "url": "https://eng.alpha.example/",
            "default_credibility": "primary",
            "kind": "strategy_hint",
        }
    )
    assert ds.url == "https://eng.alpha.example/"
    assert ds.to_dict()["url"] == "https://eng.alpha.example/"
    assert DataSourceConfig.from_dict(ds.to_dict()).url == ds.url


def test_data_source_url_defaults_empty_and_is_omitted() -> None:
    """Additive + optional — a source without `url` round-trips unchanged."""
    ds = DataSourceConfig.from_dict({"name": "n", "type": "external"})
    assert ds.url == ""
    assert "url" not in ds.to_dict()


# --------------------------------------------------------------------------
# FR1: the strategy-hint source grounds citations to its own host.
# --------------------------------------------------------------------------


def test_strategy_hint_grounds_deep_path_citation(tmp_path: Path) -> None:
    """A bare origin must ground a citation carrying a full path."""
    spec = _spec(
        tmp_path,
        [
            DataSourceConfig(
                name="Regional company engineering blogs",
                type="external",
                url="https://engineering.bravo.example/",
                default_credibility="primary",
                kind="strategy_hint",
                role="domain",
            )
        ],
    )
    assert (
        _level(spec, tmp_path, "https://engineering.bravo.example/some-post")
        == Level.PRIMARY.value
    )


def test_strategy_hint_does_not_ground_a_different_host(tmp_path: Path) -> None:
    """Grounding is host-scoped — it must not leak to unrelated domains."""
    spec = _spec(
        tmp_path,
        [
            DataSourceConfig(
                name="Regional company engineering blogs",
                type="external",
                url="https://engineering.bravo.example/",
                default_credibility="primary",
                kind="strategy_hint",
                role="domain",
            )
        ],
    )
    # Not declared, not in the shipped catalog ⇒ still unresolved.
    assert _level(spec, tmp_path, "https://unrelated-blog.example/post") == "UNRESOLVED"


def test_strategy_hint_grounding_is_not_a_subdomain_wildcard(tmp_path: Path) -> None:
    """`engineering.bravo.example` must not silently ground all of `bravo.example`."""
    spec = _spec(
        tmp_path,
        [
            DataSourceConfig(
                name="Regional company engineering blogs",
                type="external",
                url="https://engineering.bravo.example/",
                default_credibility="primary",
                kind="strategy_hint",
                role="domain",
            )
        ],
    )
    assert _level(spec, tmp_path, "https://www.bravo.example/marketing") == "UNRESOLVED"


@pytest.mark.parametrize(
    "declared,citation",
    [
        (
            "https://eng.alpha.example/",
            "https://eng.alpha.example/a/deep/path?q=1#frag",
        ),
        ("https://eng.alpha.example", "https://eng.alpha.example/post"),
        ("eng.alpha.example", "https://eng.alpha.example/post"),
        ("https://ENG.ALPHA.EXAMPLE/", "https://eng.alpha.example/post"),
    ],
)
def test_declared_url_shapes_all_ground(
    tmp_path: Path, declared: str, citation: str
) -> None:
    """Operators write URLs inconsistently; grounding must not depend on that."""
    spec = _spec(
        tmp_path,
        [
            DataSourceConfig(
                name="Alpha engineering",
                type="external",
                url=declared,
                default_credibility="primary",
                kind="strategy_hint",
                role="domain",
            )
        ],
    )
    assert _level(spec, tmp_path, citation) == Level.PRIMARY.value


def test_source_without_default_credibility_grounds_nothing(tmp_path: Path) -> None:
    """A `url` alone is not a credibility claim."""
    spec = _spec(
        tmp_path,
        [
            DataSourceConfig(
                name="Some blog",
                type="external",
                url="https://no-default.example/",
                kind="strategy_hint",
                role="domain",
            )
        ],
    )
    assert _level(spec, tmp_path, "https://no-default.example/post") == "UNRESOLVED"


def test_declared_source_beats_shipped_catalog(tmp_path: Path) -> None:
    """A vault's own declaration is more specific than the global catalog.

    `docs/source-credibility.md` documents the order as
    "explicit citation → source default → FAIL", so the source default must be
    consulted before the 066 domain catalog.
    """
    spec = _spec(
        tmp_path,
        [
            DataSourceConfig(
                name="Wikipedia, for this vault",
                type="external",
                url="https://en.wikipedia.org/",
                default_credibility="unvetted",
                kind="strategy_hint",
                role="domain",
            )
        ],
    )
    assert (
        _level(spec, tmp_path, "https://en.wikipedia.org/wiki/Software_engineering")
        == Level.UNVETTED.value
    )


def test_explicit_citation_credibility_still_wins(tmp_path: Path) -> None:
    """Resolution order is unchanged at the top: the citation's own field wins."""
    spec = _spec(
        tmp_path,
        [
            DataSourceConfig(
                name="Alpha engineering",
                type="external",
                url="https://eng.alpha.example/",
                default_credibility="primary",
                kind="strategy_hint",
                role="domain",
            )
        ],
    )
    ctx = build_credibility_context(spec, tmp_path)
    entry = {"url": "https://eng.alpha.example/post", "credibility": "commentary"}
    assert (
        effective_level(entry, {"type": "publication"}, ctx).value
        == Level.COMMENTARY.value
    )


# --------------------------------------------------------------------------
# Regression: repos-backed sources are untouched (tasks.md T013).
# --------------------------------------------------------------------------


def test_repos_backed_source_behaviour_unchanged(tmp_path: Path) -> None:
    """The pre-070 exact-URL index must keep working exactly as before."""
    spec = _spec(
        tmp_path,
        [
            DataSourceConfig(
                name="Platform repos",
                type="internal",
                default_credibility="primary",
                # `domain` matches the note type's authoritative_role, so the
                # off-field downgrade stays out of this assertion.
                role="domain",
                repos=[
                    RepoEnumeration(
                        name="svc", url="https://github.com/acme/svc", local_path=""
                    )
                ],
            )
        ],
    )
    ctx = build_credibility_context(spec, tmp_path)
    assert ctx.default_by_source_id.get("https://github.com/acme/svc") == "primary"
    assert (
        effective_level(
            {"url": "https://github.com/acme/svc"}, {"type": "publication"}, ctx
        ).value
        == Level.PRIMARY.value
    )


def test_source_with_both_url_and_repos_keeps_repo_grounding(tmp_path: Path) -> None:
    """Declaring `url` must not displace an existing `repos` entry."""
    spec = _spec(
        tmp_path,
        [
            DataSourceConfig(
                name="Platform repos",
                type="internal",
                url="https://acme.example/",
                default_credibility="primary",
                role="behaviour",
                repos=[
                    RepoEnumeration(
                        name="svc", url="https://github.com/acme/svc", local_path=""
                    )
                ],
            )
        ],
    )
    ctx = build_credibility_context(spec, tmp_path)
    assert ctx.default_by_source_id.get("https://github.com/acme/svc") == "primary"
    assert (
        effective_level(
            {"url": "https://acme.example/x"}, {"type": "publication"}, ctx
        ).value
        == Level.PRIMARY.value
    )


def test_multi_domain_strategy_hint_grounds_every_declared_host(tmp_path: Path) -> None:
    """A strategy hint is routinely a SET of domains, not one.

    The live vault declared one source, "Regional company engineering blogs",
    spanning alpha / bravo / charlie / echo while `url:` could name only one of
    them. Grounding one host and quarantining the rest is not a fix.
    """
    spec = _spec(
        tmp_path,
        [
            DataSourceConfig(
                name="Regional company engineering blogs",
                type="external",
                url="https://eng.alpha.example/",
                urls=[
                    "https://engineering.bravo.example/",
                    "https://engineering.charlie.example/",
                ],
                default_credibility="primary",
                kind="strategy_hint",
                role="domain",
            )
        ],
    )
    for citation in (
        "https://eng.alpha.example/post",
        "https://engineering.bravo.example/some-post",
        "https://engineering.charlie.example/2024/xyz",
    ):
        assert _level(spec, tmp_path, citation) == Level.PRIMARY.value, citation


def test_urls_list_round_trips() -> None:
    ds = DataSourceConfig.from_dict(
        {
            "name": "blogs",
            "type": "external",
            "urls": ["https://a.example/", "https://b.example/"],
            "default_credibility": "primary",
        }
    )
    assert ds.urls == ["https://a.example/", "https://b.example/"]
    assert DataSourceConfig.from_dict(ds.to_dict()).urls == ds.urls
    assert (
        "urls" not in DataSourceConfig.from_dict({"name": "n", "type": "e"}).to_dict()
    )
