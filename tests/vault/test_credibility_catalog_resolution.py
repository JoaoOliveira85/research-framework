"""Spec 066 FR1/FR2 — catalog wired into ``effective_level`` + severity split.

Contract: specs/066-credibility-model-calibration/contracts/credibility-catalog.contract.md §5-§7
Tier: 1/2 (pure resolution over the shipped catalog + an in-memory context).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework.pipeline.source_authority import build_source_role_index
from research_framework.spec.schema import (
    BudgetConfig,
    CoverageCategory,
    CoverageTargets,
    NoteTypeConfig,
    ScopeConfig,
    SpecConfig,
)
from research_framework.vault.credibility import (
    CredibilityContext,
    CredibilityUnresolved,
    Level,
    effective_level,
    validate_credibility_shape,
)
from research_framework.vault.credibility_catalog import (
    build_resolved_catalog,
)


def _spec() -> SpecConfig:
    return SpecConfig(
        name="cred-cat",
        location=Path("/tmp/credcat"),
        owner="t",
        scope=ScopeConfig(domain="d", organization="o"),
        note_types=[NoteTypeConfig(name="concept", description="d", folder="f")],
        data_sources=[],
        search_dimensions=["domain"],
        coverage_targets=CoverageTargets(
            categories=[CoverageCategory(name="c", note_type="concept", target_count=1)]
        ),
        budget=BudgetConfig(),
    )


def _ctx(
    *, policy: str = "warn", override=None, tmp_path: Path | None = None
) -> CredibilityContext:
    role_index = build_source_role_index(_spec(), tmp_path or Path("/tmp/credcat"))
    return CredibilityContext(
        role_index=role_index,
        catalog=build_resolved_catalog(override or [], unknown_domain_policy=policy),
    )


def _cite(url: str, **extra) -> dict:
    return {"url": url, **extra}


def _note() -> dict:
    return {"type": "concept", "source_urls": []}


# --- catalog supplies the declared level (the rc7 fix) ---------------------


def test_fastify_dev_resolves_corroborated():
    ctx = _ctx()
    assert (
        effective_level(_cite("https://fastify.dev/"), _note(), ctx)
        == Level.CORROBORATED
    )


def test_wikipedia_resolves_primary():
    ctx = _ctx()
    assert (
        effective_level(_cite("https://en.wikipedia.org/wiki/CAP"), _note(), ctx)
        == Level.PRIMARY
    )


def test_github_orgrepo_resolves_corroborated():
    ctx = _ctx()
    assert (
        effective_level(_cite("https://github.com/fastify/fastify"), _note(), ctx)
        == Level.CORROBORATED
    )


def test_apache_wildcard_resolves_commentary():
    ctx = _ctx()
    assert (
        effective_level(_cite("https://spark.apache.org/docs/"), _note(), ctx)
        == Level.COMMENTARY
    )


def test_catalog_miss_still_unresolved():
    ctx = _ctx()
    with pytest.raises(CredibilityUnresolved):
        effective_level(_cite("https://kubernetes.default.svc/x"), _note(), ctx)


# --- COI cap + off-field still apply on top of catalog declared ------------


def test_coi_caps_catalog_primary_to_commentary():
    ctx = _ctx()
    # wikipedia → primary, but coi caps to commentary (055 §4 unchanged).
    cite = _cite("https://en.wikipedia.org/wiki/CAP", coi=True)
    assert effective_level(cite, _note(), ctx) == Level.COMMENTARY


# --- override semantics (FR3/Q11) ------------------------------------------


def test_override_promotes_internal_domain():
    ctx = _ctx(override=[{"domain": "internal.companyhost.com", "tier": "tier_1"}])
    assert (
        effective_level(_cite("https://internal.companyhost.com/x"), _note(), ctx)
        == Level.PRIMARY
    )


def test_override_replaces_default_tier():
    ctx = _ctx(override=[{"domain": "wikipedia.org", "tier": "tier_3"}])
    assert (
        effective_level(_cite("https://wikipedia.org/wiki/X"), _note(), ctx)
        == Level.COMMENTARY
    )


# --- FR2 severity split in validate_credibility_shape ----------------------


def test_unresolved_is_warn_under_default_policy():
    ctx = _ctx(policy="warn")
    fm = {"type": "concept", "source_urls": [_cite("https://kubernetes.default.svc/x")]}
    violations = validate_credibility_shape(fm, ctx, location="note:n.md")
    assert len(violations) == 1
    assert violations[0]["rule_id"] == "IX-credibility-unresolved"
    assert violations[0]["severity"] == "warn"


def test_unresolved_is_fail_under_reject_policy():
    ctx = _ctx(policy="reject")
    fm = {"type": "concept", "source_urls": [_cite("https://kubernetes.default.svc/x")]}
    violations = validate_credibility_shape(fm, ctx, location="note:n.md")
    assert violations[0]["rule_id"] == "IX-credibility-unresolved"
    assert violations[0]["severity"] == "fail"


def test_malformed_url_is_citation_malformed_fail():
    ctx = _ctx(policy="warn")
    fm = {"type": "concept", "source_urls": [_cite("http://prometheus:9090/")]}
    violations = validate_credibility_shape(fm, ctx, location="note:n.md")
    assert violations[0]["rule_id"] == "IX-citation-malformed"
    assert violations[0]["severity"] == "fail"


def test_catalog_hit_has_no_violation():
    ctx = _ctx(policy="reject")  # even strict policy: a hit is clean
    fm = {"type": "concept", "source_urls": [_cite("https://fastify.dev/")]}
    assert validate_credibility_shape(fm, ctx, location="note:n.md") == []


def test_no_catalog_context_defaults_warn_policy():
    # A context without a catalog must not crash and defaults to warn.
    ctx = CredibilityContext(
        role_index=build_source_role_index(_spec(), Path("/tmp/x"))
    )
    assert ctx.unknown_domain_policy == "warn"
    fm = {"type": "concept", "source_urls": [_cite("https://kubernetes.default.svc/x")]}
    violations = validate_credibility_shape(fm, ctx, location="note:n.md")
    assert violations[0]["severity"] == "warn"
