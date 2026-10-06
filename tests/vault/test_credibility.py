"""Tests for vault/credibility.py (spec 055 US1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework.spec.schema import (
    BudgetConfig,
    CoverageCategory,
    CoverageTargets,
    DataSourceConfig,
    NoteTypeConfig,
    ScopeConfig,
    SpecConfig,
)
from research_framework.vault.credibility import (
    CredibilityContext,
    CredibilityUnresolved,
    Level,
    build_credibility_context,
    citation_url,
    downgrade_one_step,
    effective_level,
    min_rank,
    off_field,
    parse_level,
)
from research_framework.vault.credibility_catalog import is_malformed_url


def _spec(
    *,
    data_sources: list[DataSourceConfig] | None = None,
    note_types: list[NoteTypeConfig] | None = None,
) -> SpecConfig:
    return SpecConfig(
        name="cred-test",
        location=Path("/tmp/cred"),
        owner="test",
        scope=ScopeConfig(domain="d", organization="o"),
        note_types=note_types
        or [
            NoteTypeConfig(
                name="concept",
                description="d",
                folder="f",
                authoritative_role="domain",
            ),
            NoteTypeConfig(
                name="service",
                description="s",
                folder="s",
                authoritative_role="behaviour",
            ),
        ],
        data_sources=data_sources or [],
        search_dimensions=["domain"],
        coverage_targets=CoverageTargets(
            categories=[CoverageCategory(name="c", note_type="concept", target_count=1)]
        ),
        budget=BudgetConfig(),
    )


def _ctx(spec: SpecConfig, vault_dir: Path) -> CredibilityContext:
    return build_credibility_context(spec, vault_dir)


def test_level_enum_order() -> None:
    assert parse_level("primary") is Level.PRIMARY
    assert parse_level("corroborated") is Level.CORROBORATED
    assert parse_level("commentary") is Level.COMMENTARY
    assert parse_level("unvetted") is Level.UNVETTED

    assert Level.PRIMARY.rank == 3
    assert Level.CORROBORATED.rank == 2
    assert Level.COMMENTARY.rank == 1
    assert Level.UNVETTED.rank == 0

    assert min_rank(Level.PRIMARY, Level.COMMENTARY) is Level.COMMENTARY
    assert downgrade_one_step(Level.PRIMARY) is Level.CORROBORATED
    assert downgrade_one_step(Level.UNVETTED) is Level.UNVETTED


@pytest.mark.parametrize(
    ("declared", "coi", "off_field_flag", "expected"),
    [
        ("commentary", False, False, Level.COMMENTARY),
        ("unvetted", False, False, Level.UNVETTED),
        ("corroborated", True, False, Level.COMMENTARY),
        ("corroborated", False, True, Level.COMMENTARY),
        ("primary", True, True, Level.UNVETTED),
        ("primary", False, False, Level.PRIMARY),
    ],
    ids=[
        "hn-expert-in-field",
        "hn-random-opinion",
        "openai-paper-coi",
        "leader-off-field",
        "leader-coi-and-off-field",
        "first-party-docs",
    ],
)
def test_effective_level_matrix(
    tmp_path: Path,
    declared: str,
    coi: bool,
    off_field_flag: bool,
    expected: Level,
) -> None:
    spec = _spec(
        data_sources=[
            DataSourceConfig(name="src", type="external", role="domain", priority=2),
            DataSourceConfig(
                name="code", type="internal", role="behaviour", priority=1
            ),
        ]
    )
    ctx = _ctx(spec, tmp_path)
    note = {"type": "concept" if not off_field_flag else "service"}
    citation = {
        "url": "https://example.com/paper",
        "credibility": declared,
        "coi": coi,
    }
    if off_field_flag:
        # Force off_field via role mismatch: domain citation on behaviour note.
        ctx.role_index.exact["https://example.com/paper"] = "domain"
        note = {"type": "service"}
    else:
        ctx.role_index.exact["https://example.com/paper"] = "domain"
    assert effective_level(citation, note, ctx) is expected


def test_resolution_order(tmp_path: Path) -> None:
    spec = _spec(
        data_sources=[
            DataSourceConfig(
                name="HN",
                type="external",
                role="domain",
                priority=2,
                default_credibility="commentary",
            )
        ]
    )
    ctx = _ctx(spec, tmp_path)
    ctx.role_index.exact["https://news.ycombinator.com/item?id=1"] = "domain"
    note = {"type": "concept"}

    explicit = {
        "url": "https://news.ycombinator.com/item?id=1",
        "credibility": "primary",
    }
    assert effective_level(explicit, note, ctx) is Level.PRIMARY

    default_only = {"url": "https://news.ycombinator.com/item?id=1"}
    assert effective_level(default_only, note, ctx) is Level.COMMENTARY

    unresolved = {"url": "https://unknown.example/no-default"}
    with pytest.raises(CredibilityUnresolved):
        effective_level(unresolved, note, ctx)


def test_off_field_missing_role_is_not_off_field(tmp_path: Path) -> None:
    spec = _spec(
        data_sources=[
            DataSourceConfig(name="HN", type="external", role="domain", priority=2)
        ]
    )
    ctx = _ctx(spec, tmp_path)
    citation = {"url": "https://unknown.example/x", "credibility": "corroborated"}
    note = {"type": "service"}
    assert off_field(citation, note, ctx) is False
    assert effective_level(citation, note, ctx) is Level.CORROBORATED


def test_default_credibility_loaded(tmp_path: Path) -> None:
    spec = _spec(
        data_sources=[
            DataSourceConfig(
                name="Journal",
                type="external",
                role="domain",
                priority=2,
                default_credibility="corroborated",
            )
        ]
    )
    ctx = _ctx(spec, tmp_path)
    assert ctx.default_by_source_id.get("journal-feed") is None
    ctx.default_by_source_id["https://journal.example/feed"] = "corroborated"
    note = {"type": "concept"}
    citation = {"url": "https://journal.example/feed"}
    assert effective_level(citation, note, ctx) is Level.CORROBORATED


def test_invalid_default_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    spec = _spec(
        data_sources=[
            DataSourceConfig(
                name="Bad",
                type="external",
                role="domain",
                priority=2,
                default_credibility="tier-99",
            )
        ]
    )
    ctx = _ctx(spec, tmp_path)
    assert ctx.default_by_source_id == {}
    assert any("default_credibility" in r.message for r in caplog.records)


# --- citation_url: presentation is not part of the URL (2026-09-09 regression) ---
#
# A live vault lost 8 of 10 notes in one run because its note-writer applied the
# classification tag its own CLAUDE.md teaches ("[code]/[intent]/[domain]") inside
# the machine-read `source_urls` frontmatter. Every such citation graded as
# IX-citation-malformed. The instruction is now scoped to rendered citations, and
# the parser tolerates what the old instruction produced.


@pytest.mark.parametrize(
    "entry,expected",
    [
        ("https://example.com/a", "https://example.com/a"),
        ("  https://example.com/a  ", "https://example.com/a"),
        ("[domain] https://example.com/a", "https://example.com/a"),
        ("[DOMAIN] https://example.com/a", "https://example.com/a"),
        ("[code] https://example.com/a", "https://example.com/a"),
        ("[intent] https://example.com/a", "https://example.com/a"),
        (
            "[domain] https://example.com/a — Example, 'A Title', accessed 2026-09-09",
            "https://example.com/a",
        ),
        (
            "https://example.com/a — Example, accessed 2026-09-09",
            "https://example.com/a",
        ),
    ],
)
def test_citation_url_strips_tag_and_tail(entry: str, expected: str) -> None:
    assert citation_url(entry) == expected


def test_citation_url_leaves_mappings_untouched() -> None:
    assert citation_url({"url": " https://example.com/a "}) == "https://example.com/a"
    assert citation_url({"title": "no url here"}) is None


def test_citation_url_on_prose_still_grades_malformed() -> None:
    """A tail-only string keeps failing: the fix widens the parser, not the gate."""
    url = citation_url("Stanford HAI, The 2026 AI Index Report")
    assert url == "Stanford"
    assert is_malformed_url(url)


def test_tagged_citation_is_no_longer_malformed() -> None:
    assert not is_malformed_url(citation_url("[domain] https://example.com/a") or "")
