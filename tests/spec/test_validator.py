"""Tests for src/research_framework/spec/validator.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework.spec.parser import parse
from research_framework.spec.schema import (
    BudgetConfig,
    CoverageCategory,
    CoverageTargets,
    DataSourceConfig,
    NoteTypeConfig,
    RepoEnumeration,
    ScopeConfig,
    SpecConfig,
    SpecValidationError,
)
from research_framework.spec.validator import validate


def _valid_spec() -> SpecConfig:
    return SpecConfig(
        name="Sample",
        location=Path("/tmp/sample"),
        owner="Owner",
        scope=ScopeConfig(domain="d", organization="o"),
        note_types=[
            NoteTypeConfig(name="concept", description="d", folder="01 - Concepts")
        ],
        data_sources=[DataSourceConfig(name="Internal", type="internal")],
        search_dimensions=[
            "technical",
            "organizational",
            "domain",
            "market",
            "temporal",
        ],
        coverage_targets=CoverageTargets(
            categories=[CoverageCategory(name="c", note_type="concept", target_count=5)]
        ),
        budget=BudgetConfig(),
    )


def test_valid_spec_passes() -> None:
    validate(_valid_spec())


class TestSourceAuthorityValidation:
    """spec 053 FR-001/FR-002 — unique-minimum-priority trunk derivation +
    note_type authoritative_role validation (uses the shared derive_trunk)."""

    def test_fails_when_minimum_priority_tied_with_differentiation(self) -> None:
        spec = _valid_spec()
        spec.data_sources = [
            DataSourceConfig(name="A", type="internal", priority=1, role="behaviour"),
            DataSourceConfig(name="B", type="external", priority=1, role="intent"),
            DataSourceConfig(name="C", type="external", priority=3, role="domain"),
        ]
        with pytest.raises(SpecValidationError) as exc:
            validate(spec)
        assert any("trunk" in m.lower() for m in exc.value.messages)

    def test_passes_when_all_priorities_equal_pure_domain(self) -> None:
        spec = _valid_spec()
        spec.data_sources = [
            DataSourceConfig(name="A", type="external", priority=2, role="domain"),
            DataSourceConfig(name="B", type="external", priority=2, role="domain"),
        ]
        validate(spec)  # no derivable trunk is valid for a pure-domain vault

    def test_passes_when_minimum_priority_unique(self) -> None:
        # Journal-first shape: unique minimum, not code-first (avoids the
        # behaviour-primary repo/code-wins invariants — those are US1's job).
        spec = _valid_spec()
        spec.data_sources = [
            DataSourceConfig(name="A", type="external", priority=2, role="domain"),
            DataSourceConfig(name="B", type="external", priority=3, role="domain"),
        ]
        validate(spec)

    def test_fails_on_invalid_authoritative_role(self) -> None:
        spec = _valid_spec()
        spec.note_types = [
            NoteTypeConfig(
                name="concept",
                description="d",
                folder="f",
                authoritative_role="code",  # not in the enum
            )
        ]
        with pytest.raises(SpecValidationError) as exc:
            validate(spec)
        assert any("authoritative_role" in m for m in exc.value.messages)

    def test_fails_when_authoritative_role_declared_inconsistently(self) -> None:
        spec = _valid_spec()
        spec.note_types = [
            NoteTypeConfig(
                name="concept",
                description="d",
                folder="f1",
                authoritative_role="behaviour",
            ),
            NoteTypeConfig(name="extra", description="d", folder="f2"),  # lacks it
        ]
        with pytest.raises(SpecValidationError) as exc:
            validate(spec)
        assert any("authoritative_role" in m for m in exc.value.messages)

    def test_passes_when_no_note_type_declares_authoritative_role(self) -> None:
        # Fully-legacy spec: authority model not adopted → exempt (non-breaking).
        validate(_valid_spec())


def test_missing_name() -> None:
    spec = _valid_spec()
    spec.name = ""
    with pytest.raises(SpecValidationError) as exc:
        validate(spec)
    assert any("name" in m for m in exc.value.messages)


def test_missing_owner() -> None:
    spec = _valid_spec()
    spec.owner = ""
    with pytest.raises(SpecValidationError) as exc:
        validate(spec)
    assert any("owner" in m for m in exc.value.messages)


def test_missing_domain_dimension() -> None:
    spec = _valid_spec()
    spec.search_dimensions = ["technical", "organizational", "market", "temporal"]
    with pytest.raises(SpecValidationError) as exc:
        validate(spec)
    assert any("domain" in m for m in exc.value.messages)


def test_missing_market_dimension() -> None:
    spec = _valid_spec()
    spec.search_dimensions = ["technical", "organizational", "domain", "temporal"]
    with pytest.raises(SpecValidationError) as exc:
        validate(spec)
    assert any("market" in m for m in exc.value.messages)


def test_empty_note_types() -> None:
    spec = _valid_spec()
    spec.note_types = []
    with pytest.raises(SpecValidationError):
        validate(spec)


def test_empty_data_sources() -> None:
    spec = _valid_spec()
    spec.data_sources = []
    with pytest.raises(SpecValidationError):
        validate(spec)


def test_empty_coverage_categories() -> None:
    spec = _valid_spec()
    spec.coverage_targets = CoverageTargets(categories=[])
    with pytest.raises(SpecValidationError):
        validate(spec)


def test_default_research_mode_is_valid() -> None:
    """Default research_mode ('bootstrap') is always accepted."""
    spec = _valid_spec()
    assert spec.research_mode == "bootstrap"
    validate(spec)


@pytest.mark.parametrize("mode", ["bootstrap", "refresh", "expand"])
def test_all_documented_research_modes_accepted(mode: str) -> None:
    spec = _valid_spec()
    spec.research_mode = mode
    validate(spec)


def test_invalid_research_mode_rejected() -> None:
    spec = _valid_spec()
    spec.research_mode = "turbocharged"
    with pytest.raises(SpecValidationError) as exc:
        validate(spec)
    assert any("research_mode" in m for m in exc.value.messages)


def test_source_empty_phases_accepted() -> None:
    """Empty phases list (universal) is the happy path."""
    spec = _valid_spec()
    spec.data_sources[0].phases = []
    validate(spec)


def test_source_valid_phases_accepted() -> None:
    spec = _valid_spec()
    spec.data_sources[0].phases = ["refresh", "expand"]
    validate(spec)


def test_source_invalid_phase_rejected() -> None:
    spec = _valid_spec()
    spec.data_sources[0].phases = ["bootstrap", "daily"]
    with pytest.raises(SpecValidationError) as exc:
        validate(spec)
    messages = exc.value.messages
    assert any("phase" in m and "daily" in m for m in messages)


def test_coverage_references_unknown_type() -> None:
    spec = _valid_spec()
    spec.coverage_targets.categories = [
        CoverageCategory(name="x", note_type="service", target_count=1)
    ]
    with pytest.raises(SpecValidationError) as exc:
        validate(spec)
    assert any("service" in m for m in exc.value.messages)


def test_invalid_data_source_type() -> None:
    spec = _valid_spec()
    spec.data_sources = [DataSourceConfig(name="X", type="confluence")]
    with pytest.raises(SpecValidationError) as exc:
        validate(spec)
    assert any("invalid type" in m for m in exc.value.messages)


def test_sample_spec_passes(sample_spec_path: Path) -> None:
    """The tests/fixtures/sample-spec.md must validate."""
    spec = parse(sample_spec_path)
    validate(spec)


# Code-first (feature 002) validator rules. These trigger only when the spec
# uses any non-default priority/role/repos — so v0.1 tests above keep passing.


def _code_first_spec() -> SpecConfig:
    spec = _valid_spec()
    spec.scope = ScopeConfig(
        domain="d",
        organization="o",
        source_of_truth_rules=[
            "Code wins on questions of current behaviour.",
            "Confluence wins on questions of stated intent.",
        ],
    )
    spec.data_sources = [
        DataSourceConfig(
            name="GitHub repos",
            type="internal",
            priority=1,
            role="behaviour",
            repos=[
                RepoEnumeration(
                    name="OEHK",
                    url="https://github.com/acme-corp/oehk-service",
                    owning_team="Platform",
                )
            ],
        ),
        DataSourceConfig(
            name="Confluence",
            type="external",
            priority=2,
            role="intent",
            required=True,
        ),
    ]
    return spec


def test_code_first_spec_passes() -> None:
    validate(_code_first_spec())


def test_code_first_missing_primary_fails() -> None:
    spec = _code_first_spec()
    # Downgrade the only priority=1 source to priority=2
    spec.data_sources[0].priority = 2
    # But keep `repos` populated so code-first detection still fires
    with pytest.raises(SpecValidationError) as exc:
        validate(spec)
    assert any("priority=1 and role=behaviour" in m for m in exc.value.messages)


def test_code_first_multiple_primaries_fails() -> None:
    spec = _code_first_spec()
    spec.data_sources.append(
        DataSourceConfig(
            name="Another",
            type="internal",
            priority=1,
            role="behaviour",
            repos=[RepoEnumeration(name="X", url="https://github.com/acme-corp/x")],
        )
    )
    with pytest.raises(SpecValidationError) as exc:
        validate(spec)
    assert any("multiple" in m.lower() for m in exc.value.messages)


def test_code_first_primary_missing_repos_fails() -> None:
    spec = _code_first_spec()
    spec.data_sources[0].repos = []
    with pytest.raises(SpecValidationError) as exc:
        validate(spec)
    assert any("at least one repo" in m for m in exc.value.messages)


def test_code_first_repo_url_must_match_spec_patterns_when_set() -> None:
    """When `code_source_url_patterns` is declared, repo URLs must match one.

    The default (no pattern set) allows any github/gitlab/bitbucket org plus
    file://, so the framework can ship without being bound to a specific
    company. Vault authors narrow the whitelist by setting the pattern list
    on their spec.
    """
    spec = _code_first_spec()
    spec.code_source_url_patterns = [r"^https?://github\.com/acme/"]
    spec.data_sources[0].repos[0].url = "https://github.com/some-other-org/project"
    with pytest.raises(SpecValidationError) as exc:
        validate(spec)
    assert any("does not match any allowed pattern" in m for m in exc.value.messages)


def test_code_first_repo_url_default_accepts_any_github_org() -> None:
    """Without a custom pattern list the defaults accept any github org —
    the framework must not privilege any specific company by default."""
    spec = _code_first_spec()
    spec.data_sources[0].repos[0].url = "https://github.com/some-other-org/project"
    validate(spec)  # should NOT raise


def test_code_first_repo_url_rejects_non_code_url_by_default() -> None:
    """The default pattern list still rejects obviously non-code URLs."""
    spec = _code_first_spec()
    spec.data_sources[0].repos[0].url = "https://example.com/not-a-repo"
    with pytest.raises(SpecValidationError) as exc:
        validate(spec)
    assert any("does not match any allowed pattern" in m for m in exc.value.messages)


def test_code_first_missing_code_wins_rule_fails() -> None:
    spec = _code_first_spec()
    spec.scope.source_of_truth_rules = ["Some unrelated rule"]
    with pytest.raises(SpecValidationError) as exc:
        validate(spec)
    assert any("code-wins" in m for m in exc.value.messages)


def test_code_first_missing_required_intent_fails() -> None:
    spec = _code_first_spec()
    spec.data_sources[1].required = False
    with pytest.raises(SpecValidationError) as exc:
        validate(spec)
    assert any("role=intent" in m for m in exc.value.messages)


def test_invalid_role_fails() -> None:
    """Code-first specs reject roles outside behaviour|intent|domain."""
    spec = _code_first_spec()
    spec.data_sources[1].role = "bogus"
    with pytest.raises(SpecValidationError) as exc:
        validate(spec)
    assert any("invalid role" in m for m in exc.value.messages)


class TestNonCodeFirstRoleVocabulary:
    """Simple user-facing specs use `role` as a free-form semantic tag.

    A recipe vault, a photography vault, a history vault — none of these
    have anything to do with the behaviour/intent/domain axes used by
    code-first vaults, and their skill-generated specs will carry
    human-friendly role tags like `recipes`, `nutrition`, `reference`.
    The validator must accept any non-empty role string in that mode and
    only enforce the strict vocabulary when the spec is actually
    code-first (regression for the v0.2.2 recipe-vault bug).
    """

    def test_recipe_vault_role_tags_are_accepted(self) -> None:
        spec = _valid_spec()
        spec.data_sources = [
            DataSourceConfig(name="Teleculinaria", type="external", role="recipes"),
            DataSourceConfig(name="PortFIR", type="external", role="nutrition"),
            DataSourceConfig(name="DGS", type="external", role="reference"),
        ]
        validate(spec)

    def test_empty_role_still_rejected_in_simple_spec(self) -> None:
        spec = _valid_spec()
        spec.data_sources = [DataSourceConfig(name="Bad", type="external", role="")]
        with pytest.raises(SpecValidationError) as exc:
            validate(spec)
        assert any("role" in m and "non-empty string" in m for m in exc.value.messages)

    def test_code_first_spec_still_rejects_recipes_role(self) -> None:
        """The strict vocabulary remains in force for code-first specs."""
        spec = _code_first_spec()
        spec.data_sources[1].role = "recipes"
        with pytest.raises(SpecValidationError) as exc:
            validate(spec)
        messages = " ".join(exc.value.messages)
        assert "invalid role" in messages
        assert "code-first specs" in messages


def test_invalid_source_policy_fails() -> None:
    spec = _code_first_spec()
    spec.note_types[0].source_policy = "medium"
    with pytest.raises(SpecValidationError) as exc:
        validate(spec)
    assert any("source_policy" in m for m in exc.value.messages)
