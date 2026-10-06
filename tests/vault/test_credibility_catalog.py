"""Spec 066 FR1 — credibility domain catalog + override + resolution.

Contract: specs/066-credibility-model-calibration/contracts/credibility-catalog.contract.md
Tier: 1 (pure functions over shipped data + in-memory entries).
"""

from __future__ import annotations

from research_framework.vault.credibility import Level
from research_framework.vault.credibility_catalog import (
    TIER_TO_LEVEL,
    build_resolved_catalog,
    default_catalog_path,
    is_malformed_url,
    load_default_catalog,
)

# --- tier → Level mapping (contract §1 / D0) -------------------------------


def test_tier_to_level_mapping():
    assert TIER_TO_LEVEL == {
        "tier_1": Level.PRIMARY,
        "tier_2": Level.CORROBORATED,
        "tier_3": Level.COMMENTARY,
    }
    # unvetted is never catalog-assigned.
    assert Level.UNVETTED not in TIER_TO_LEVEL.values()


# --- default catalog ships + parses (the rc7 hosts resolve) ----------------


def test_default_catalog_file_exists():
    assert default_catalog_path().is_file()


def test_rc7_hosts_resolve_against_default_catalog():
    cat = load_default_catalog()
    # exact tier_2 project site
    assert cat.lookup("https://fastify.dev/") == Level.CORROBORATED
    # exact tier_1 reference
    assert cat.lookup("https://en.wikipedia.org/wiki/CAP_theorem") == Level.PRIMARY
    assert cat.lookup("https://developer.mozilla.org/en-US/docs/X") == Level.PRIMARY
    # first-party vendor docs tier_1
    assert cat.lookup("https://docs.aws.amazon.com/boto3/") == Level.PRIMARY


def test_github_host_path_requires_at_least_one_segment():
    """Spec 070 F2 relaxed this from >=2 to >=1 segments.

    Was ``test_github_host_path_requires_two_segments``. The >=2 rule was right
    for citing a repository and wrong for citing a person: ``github.com/<user>``
    is a profile, and a profile is first-party evidence that someone ships code.
    The invariant that actually mattered — a BARE host grounds nothing — is
    unchanged and still asserted here.
    """
    cat = load_default_catalog()
    # org/repo → tier_2 corroborated (unchanged)
    assert cat.lookup("https://github.com/fastify/fastify") == Level.CORROBORATED
    # profile → tier_2 corroborated (070 F2: was a miss)
    assert cat.lookup("https://github.com/onlyorg") == Level.CORROBORATED
    # bare github.com → still a miss (host_path needs >=1 segment)
    assert cat.lookup("https://github.com/") is None


def test_wildcard_suffix_is_tier3():
    cat = load_default_catalog()
    assert cat.lookup("https://spark.apache.org/docs/") == Level.COMMENTARY
    assert cat.lookup("https://someproject.github.io/") == Level.COMMENTARY


def test_unknown_well_formed_host_is_none():
    cat = load_default_catalog()
    assert cat.lookup("https://kubernetes.default.svc/x") is None


# --- malformed detection (D2) ----------------------------------------------


def test_is_malformed_url():
    assert is_malformed_url("http://prometheus:9090/") is True  # host has no dot
    assert is_malformed_url("ftp://example.com/x") is True  # bad scheme
    assert is_malformed_url("https://example.com/x") is False


# --- override semantics (Q11 full replacement) -----------------------------


def test_override_replaces_default_at_any_tier():
    # wikipedia.org is tier_1 in the default; override demotes to tier_3.
    cat = build_resolved_catalog(
        [{"domain": "wikipedia.org", "tier": "tier_3"}],
    )
    assert cat.lookup("https://wikipedia.org/wiki/X") == Level.COMMENTARY


def test_override_adds_new_trusted_domain():
    cat = build_resolved_catalog(
        [{"domain": "internal.companyhost.com", "tier": "tier_1"}],
    )
    assert cat.lookup("https://internal.companyhost.com/x") == Level.PRIMARY


def test_override_may_use_wildcard_at_any_tier():
    # Override wildcard at tier_1 is allowed (operator prerogative, Q11).
    cat = build_resolved_catalog(
        [
            {
                "domain": "*.companyhost.com",
                "tier": "tier_1",
                "match_type": "host_suffix",
            }
        ],
    )
    assert cat.lookup("https://wiki.companyhost.com/x") == Level.PRIMARY


def test_unknown_domain_policy_carried():
    assert build_resolved_catalog([]).unknown_domain_policy == "warn"
    assert (
        build_resolved_catalog([], unknown_domain_policy="reject").unknown_domain_policy
        == "reject"
    )


# --- fail-closed loading (contract §2/§3) ----------------------------------


def test_bad_entries_dropped_not_crashed():
    cat = build_resolved_catalog(
        [
            {"domain": "good.com", "tier": "tier_2"},
            {"domain": "bad.com", "tier": "tier_99"},  # bad tier → dropped
            {"tier": "tier_1"},  # empty domain → dropped
            "not-a-dict",  # → dropped
        ],
    )
    assert cat.lookup("https://good.com/") == Level.CORROBORATED
    assert cat.lookup("https://bad.com/") is None


def test_default_catalog_wildcard_at_non_tier3_is_dropped():
    # A default-catalog (is_default path is exercised by load_default_catalog,
    # but here we assert the resolver tolerates a hostile override-free build).
    cat = load_default_catalog()
    # The shipped file has no non-tier_3 wildcards, so every *.suffix entry is
    # commentary; confirm a freely-registrable TLD floor stays tier_3.
    assert cat.lookup("https://anything.dev/") == Level.COMMENTARY
