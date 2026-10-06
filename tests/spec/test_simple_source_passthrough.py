"""Spec 070 F8 — the simple spec format silently dropped source annotations.

`simple.py::_data_sources` built each `DataSourceConfig` from a fixed subset of
keys. `kind`, `default_credibility`, `url`/`urls` and `local_path` were not
among them, so a simple-format vault could:

- never satisfy spec 069's fail-closed source-backing precondition, whose own
  error message instructs the operator to "annotate kind: strategy_hint" — an
  instruction the parser then discarded, leaving the vault permanently blocked
  with no legal way to comply;
- never supply a source `default_credibility`, so the credibility model's
  source-default rung did not exist for it;
- never ground a citation via spec 070 FR1.

Found by running the 070 build against `~/Documents/vaults/feeds-vault`, which is a
simple-format vault and was hard-blocked by exactly this.

The same function already sets `kind="strategy_hint"` on the injected default
`Web` source, so the field was known to matter — it just was not passed through
from user input.
"""

from __future__ import annotations

from research_framework.spec.simple import SimpleSpec, _data_sources


def _spec(sources: list[dict]) -> SimpleSpec:
    return SimpleSpec(
        name="t",
        owner="o",
        topic="t",
        goal="g",
        sources=sources,
    )


def test_kind_is_passed_through() -> None:
    """069's own remediation instruction must actually work."""
    (ds,) = _data_sources(_spec([{"name": "Hacker News", "kind": "strategy_hint"}]))
    assert ds.kind == "strategy_hint"


def test_default_credibility_is_passed_through() -> None:
    (ds,) = _data_sources(
        _spec([{"name": "AI lab blogs", "default_credibility": "primary"}])
    )
    assert ds.default_credibility == "primary"


def test_url_and_urls_are_passed_through() -> None:
    (ds,) = _data_sources(
        _spec(
            [
                {
                    "name": "AI lab blogs",
                    "url": "https://www.anthropic.com/",
                    "urls": ["https://openai.com/", "https://deepmind.google/"],
                }
            ]
        )
    )
    assert ds.url == "https://www.anthropic.com/"
    assert ds.urls == ["https://openai.com/", "https://deepmind.google/"]


def test_local_path_is_passed_through() -> None:
    (ds,) = _data_sources(_spec([{"name": "Seed", "local_path": "~/somewhere"}]))
    assert ds.local_path == "~/somewhere"


def test_absent_annotations_keep_their_defaults() -> None:
    """Regression: a source declaring none of these is unchanged."""
    (ds,) = _data_sources(_spec([{"name": "Plain", "description": "d"}]))
    assert (ds.kind, ds.default_credibility, ds.url, ds.urls, ds.local_path) == (
        "",
        "",
        "",
        [],
        "",
    )
    assert ds.name == "Plain"
    assert ds.type == "external"
    assert ds.required is True


def test_injected_default_web_source_still_annotated() -> None:
    """The empty-sources fallback keeps its own strategy_hint annotation."""
    (ds,) = _data_sources(_spec([]))
    assert ds.name == "Web"
    assert ds.kind == "strategy_hint"


def test_end_to_end_a_simple_spec_source_can_ground_a_citation(tmp_path) -> None:
    """The whole point: a simple-format vault can now use the 070 grounding."""
    from research_framework.vault.credibility import (
        build_credibility_context,
        source_host,
    )

    (ds,) = _data_sources(
        _spec(
            [
                {
                    "name": "AI lab official blogs",
                    "kind": "strategy_hint",
                    "default_credibility": "primary",
                    "url": "https://www.anthropic.com/",
                    "urls": ["https://openai.com/"],
                }
            ]
        )
    )

    class _Spec:
        data_sources = [ds]
        note_types: list = []

    ctx = build_credibility_context(_Spec(), tmp_path)
    assert ctx.default_by_source_host.get(source_host("https://openai.com/")) == (
        "primary"
    )
    assert ctx.default_by_source_host.get("www.anthropic.com") == "primary"
