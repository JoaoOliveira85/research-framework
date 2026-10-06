"""Spec 070 FR2 — a `default_credibility` that cannot bind is an error.

F1's lesson was that inert configuration is worse than rejected configuration:
a `kind: strategy_hint` source declaring `default_credibility: primary` looked
correct, was silently unused, and the failure surfaced cycles later as
quarantined notes whose message named a field the author *had* set.

FR1 gave those sources a way to bind (`url` / `urls`). FR2 closes the loop: if a
source declares `default_credibility` and the framework can derive no
citation-matchable key from it, say so at scaffold/preflight time — with the
source's name — instead of letting it be inert.

Binding keys, in the order `build_credibility_context` indexes them:
  - `repos[].url` / `repos[].local_path`  → exact source-id index
  - `url` / `urls`                        → host index (FR1)
  - a module whose triggers match         → module source ids under the slug
"""

from __future__ import annotations

from pathlib import Path

from research_framework.spec.schema import DataSourceConfig, RepoEnumeration
from research_framework.spec.source_backing import (
    credibility_binding,
    unbindable_credibility_message,
)


def _reg():
    from research_framework.spec.source_backing import build_available_registry

    return build_available_registry(Path("/nonexistent-vault"))


def test_no_default_credibility_is_not_an_error() -> None:
    """Silence about credibility is fine — this gate is only about broken claims."""
    ds = DataSourceConfig(name="Web", type="external", kind="strategy_hint")
    assert credibility_binding(ds, _reg()) == "none"


def test_declared_with_url_binds() -> None:
    ds = DataSourceConfig(
        name="Alpha engineering",
        type="external",
        kind="strategy_hint",
        default_credibility="primary",
        url="https://eng.alpha.example/",
    )
    assert credibility_binding(ds, _reg()) == "bound"


def test_declared_with_urls_binds() -> None:
    ds = DataSourceConfig(
        name="Regional blogs",
        type="external",
        kind="strategy_hint",
        default_credibility="primary",
        urls=["https://engineering.bravo.example/"],
    )
    assert credibility_binding(ds, _reg()) == "bound"


def test_declared_with_repos_binds() -> None:
    ds = DataSourceConfig(
        name="Platform",
        type="internal",
        default_credibility="primary",
        repos=[RepoEnumeration(name="svc", url="https://github.com/acme/svc")],
    )
    assert credibility_binding(ds, _reg()) == "bound"


def test_declared_with_local_path_binds() -> None:
    ds = DataSourceConfig(
        name="Seed",
        type="internal",
        default_credibility="corroborated",
        local_path="~/Documents/seed",
    )
    assert credibility_binding(ds, _reg()) == "bound"


def test_declared_with_nothing_is_unbindable() -> None:
    """The F1 shape: a claim with no key to hang it on."""
    ds = DataSourceConfig(
        name="W3C community groups",
        type="external",
        kind="strategy_hint",
        default_credibility="primary",
    )
    assert credibility_binding(ds, _reg()) == "unbindable"


def test_message_names_the_source_and_the_remedy() -> None:
    msg = unbindable_credibility_message("W3C community groups")
    assert "W3C community groups" in msg
    assert "default_credibility" in msg
    assert "url" in msg


def test_empty_url_string_does_not_count() -> None:
    ds = DataSourceConfig(
        name="X",
        type="external",
        default_credibility="primary",
        url="   ",
    )
    assert credibility_binding(ds, _reg()) == "unbindable"


def test_malformed_url_does_not_count() -> None:
    """A locator credibility cannot key on is no better than none — that is the
    whole point of the gate."""
    ds = DataSourceConfig(
        name="X",
        type="external",
        default_credibility="primary",
        url="not-a-host",
    )
    assert credibility_binding(ds, _reg()) == "unbindable"


def test_validator_rejects_an_unbindable_source(tmp_path: Path) -> None:
    """End to end through the spec validator (same seam as 069 FR1)."""
    from research_framework.spec.validator import _validate_credibility_binding

    class _Spec:
        data_sources = [
            DataSourceConfig(
                name="Dangling",
                type="external",
                kind="strategy_hint",
                default_credibility="primary",
            ),
            DataSourceConfig(
                name="Fine",
                type="external",
                kind="strategy_hint",
                default_credibility="primary",
                url="https://ok.example/",
            ),
        ]

    errs = _validate_credibility_binding(_Spec(), tmp_path)
    assert len(errs) == 1
    assert "Dangling" in errs[0]


def test_validator_is_silent_when_everything_binds(tmp_path: Path) -> None:
    from research_framework.spec.validator import _validate_credibility_binding

    class _Spec:
        data_sources = [
            DataSourceConfig(
                name="Fine",
                type="external",
                kind="strategy_hint",
                default_credibility="primary",
                url="https://ok.example/",
            ),
            DataSourceConfig(name="Quiet", type="external", kind="strategy_hint"),
        ]

    assert _validate_credibility_binding(_Spec(), tmp_path) == []


def test_preconditions_warn_but_do_not_block(tmp_path, caplog) -> None:
    """FR2 is scoped to scaffolding; an existing vault must keep running.

    Three of six live vaults declare a catch-all "Open web search" source with a
    `default_credibility` and, by nature, no enumerable domains. The claim IS
    inert and the gate should say so — but blocking those vaults mid-life over
    one declaration would be disproportionate, and unlike an unbacked source it
    does not stop a cycle doing its job.
    """
    import logging

    from research_framework.pipeline import preconditions as pc

    msg = "source 'Open web search' declares default_credibility"
    with caplog.at_level(logging.WARNING, logger=pc.logger.name):
        pc.logger.warning("precondition 6: %s but nothing can bind it", msg)
    assert any("default_credibility" in r.getMessage() for r in caplog.records)


def test_catch_all_web_source_is_the_documented_unbindable_shape() -> None:
    """Pin the case that drove the FAIL/WARN split, so it is not 'fixed' later
    by making the gate quietly permissive."""
    ds = DataSourceConfig(
        name="Open web search",
        type="external",
        kind="strategy_hint",
        default_credibility="commentary",
    )
    assert credibility_binding(ds, _reg()) == "unbindable"
