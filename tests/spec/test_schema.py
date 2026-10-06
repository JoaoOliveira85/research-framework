"""Tests for src/research_framework/spec/schema.py — code-first extensions (feature 002)."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework.spec.schema import (
    RESEARCH_MODES,
    BudgetConfig,
    CommandsConfig,
    CoverageCategory,
    CoverageTargets,
    DataSourceConfig,
    ExecutorConfig,
    NoteTypeConfig,
    RepoEnumeration,
    ScopeConfig,
    SpecConfig,
    SpecSettings,
    SpecValidationError,
    derive_trunk,
    intent_sources,
    primary_source,
)


def _minimal_spec(data_sources: list[DataSourceConfig]) -> SpecConfig:
    return SpecConfig(
        name="s",
        location=Path("/tmp/s"),
        owner="o",
        scope=ScopeConfig(domain="d", organization="o"),
        note_types=[NoteTypeConfig(name="concept", description="d", folder="f")],
        data_sources=data_sources,
        search_dimensions=["domain", "market"],
        coverage_targets=CoverageTargets(
            categories=[CoverageCategory(name="c", note_type="concept", target_count=1)]
        ),
        budget=BudgetConfig(),
    )


class TestDataSourceConfigPriorityRole:
    def test_priority_and_role_round_trip(self) -> None:
        ds = DataSourceConfig(
            name="GitHub", type="internal", priority=1, role="behaviour"
        )
        restored = DataSourceConfig.from_dict(ds.to_dict())
        assert restored.priority == 1
        assert restored.role == "behaviour"

    def test_defaults_are_v0_1_compatible(self) -> None:
        ds = DataSourceConfig(name="X", type="internal")
        assert ds.priority == 2
        assert ds.role == "behaviour"
        assert ds.repos == []


class TestRepoEnumeration:
    def test_round_trip(self) -> None:
        repo = RepoEnumeration(
            name="OEHK",
            url="https://github.com/acme-corp/oehk-service",
            priority_paths=["README.md", "docs/"],
            ignore_paths=["target/"],
            owning_team="Platform",
            access_method="local",
            local_path="/Users/me/src/oehk-service",
        )
        restored = RepoEnumeration.from_dict(repo.to_dict())
        assert restored == repo

    def test_defaults(self) -> None:
        repo = RepoEnumeration(name="X", url="https://github.com/acme-corp/x")
        assert repo.priority_paths == []
        assert repo.ignore_paths == []
        assert repo.access_method == "both"


class TestNoteTypeSourcePolicy:
    def test_hard_types_default_to_hard(self) -> None:
        for name in ("service", "flow", "concept", "decision"):
            nt = NoteTypeConfig(name=name, description="d", folder="f")
            assert nt.resolved_source_policy() == "hard"

    def test_soft_types_default_to_soft(self) -> None:
        for name in ("market", "team", "process", "risk", "moc"):
            nt = NoteTypeConfig(name=name, description="d", folder="f")
            assert nt.resolved_source_policy() == "soft"

    def test_explicit_override_wins(self) -> None:
        nt = NoteTypeConfig(
            name="concept", description="d", folder="f", source_policy="soft"
        )
        assert nt.resolved_source_policy() == "soft"


class TestNoteTypeAuthority:
    """spec 053 FR-001/D1 — note_type declares its authoritative role + the
    (opt-in) authority/complementary sections for the drift gate."""

    def test_authority_fields_parse_and_roundtrip(self) -> None:
        nt = NoteTypeConfig.from_dict(
            {
                "name": "behaviour-note",
                "description": "d",
                "folder": "f",
                "authoritative_role": "behaviour",
                "authority_section": "## Current Behaviour",
                "complementary_section": "## Stated Intent",
            }
        )
        assert nt.authoritative_role == "behaviour"
        assert nt.authority_section == "## Current Behaviour"
        assert nt.complementary_section == "## Stated Intent"
        assert NoteTypeConfig.from_dict(nt.to_dict()) == nt

    def test_authority_fields_default_empty(self) -> None:
        nt = NoteTypeConfig(name="concept", description="d", folder="f")
        assert nt.authoritative_role == ""
        assert nt.authority_section == ""
        assert nt.complementary_section == ""


class TestDeriveTrunk:
    """spec 053 FR-002 / D2 / Analyze F3 — the trunk is the source with the
    unique minimum `priority` value; no unique minimum ⇒ no derivable trunk."""

    def test_returns_unique_minimum_priority_source(self) -> None:
        spec = _minimal_spec(
            [
                DataSourceConfig(
                    name="GitHub", type="internal", priority=1, role="behaviour"
                ),
                DataSourceConfig(
                    name="Confluence", type="external", priority=2, role="intent"
                ),
            ]
        )
        trunk = derive_trunk(spec)
        assert trunk is not None
        assert trunk.name == "GitHub"

    def test_trunk_can_be_a_domain_source_journal_first(self) -> None:
        """Plasticity proof: no behaviour source at all — trunk = the domain
        journal source at the minimum priority."""
        spec = _minimal_spec(
            [
                DataSourceConfig(
                    name="Journals", type="external", priority=1, role="domain"
                ),
                DataSourceConfig(
                    name="Reddit", type="external", priority=3, role="domain"
                ),
            ]
        )
        trunk = derive_trunk(spec)
        assert trunk is not None
        assert trunk.name == "Journals"
        assert trunk.role == "domain"

    def test_tie_on_minimum_priority_has_no_derivable_trunk(self) -> None:
        spec = _minimal_spec(
            [
                DataSourceConfig(
                    name="A", type="internal", priority=1, role="behaviour"
                ),
                DataSourceConfig(name="B", type="external", priority=1, role="intent"),
                DataSourceConfig(name="C", type="external", priority=3, role="domain"),
            ]
        )
        assert derive_trunk(spec) is None

    def test_all_equal_priority_has_no_derivable_trunk(self) -> None:
        """Pure-domain vault with no priority signal (all default) ⇒ no trunk."""
        spec = _minimal_spec(
            [
                DataSourceConfig(name="A", type="external", role="domain"),
                DataSourceConfig(name="B", type="external", role="domain"),
            ]
        )
        assert derive_trunk(spec) is None

    def test_no_data_sources_has_no_derivable_trunk(self) -> None:
        spec = _minimal_spec([])
        assert derive_trunk(spec) is None


class TestPrimarySource:
    def test_returns_unique_primary(self) -> None:
        spec = _minimal_spec(
            [
                DataSourceConfig(
                    name="GitHub",
                    type="internal",
                    priority=1,
                    role="behaviour",
                    repos=[
                        RepoEnumeration(name="X", url="https://github.com/acme-corp/x")
                    ],
                ),
                DataSourceConfig(
                    name="Confluence", type="external", priority=2, role="intent"
                ),
            ]
        )
        primary = primary_source(spec)
        assert primary.name == "GitHub"

    def test_raises_when_no_primary(self) -> None:
        spec = _minimal_spec(
            [DataSourceConfig(name="X", type="external", priority=2, role="intent")]
        )
        with pytest.raises(SpecValidationError):
            primary_source(spec)

    def test_raises_on_multiple_primaries(self) -> None:
        spec = _minimal_spec(
            [
                DataSourceConfig(
                    name="A", type="internal", priority=1, role="behaviour"
                ),
                DataSourceConfig(
                    name="B", type="internal", priority=1, role="behaviour"
                ),
            ]
        )
        with pytest.raises(SpecValidationError):
            primary_source(spec)


class TestIntentSources:
    def test_returns_intents_sorted(self) -> None:
        spec = _minimal_spec(
            [
                DataSourceConfig(
                    name="GitHub", type="internal", priority=1, role="behaviour"
                ),
                DataSourceConfig(
                    name="Slack", type="external", priority=3, role="intent"
                ),
                DataSourceConfig(
                    name="Confluence", type="external", priority=2, role="intent"
                ),
                DataSourceConfig(
                    name="Jira", type="external", priority=2, role="intent"
                ),
            ]
        )
        intents = intent_sources(spec)
        assert [ds.name for ds in intents] == ["Confluence", "Jira", "Slack"]

    def test_empty_when_no_intents(self) -> None:
        spec = _minimal_spec(
            [DataSourceConfig(name="X", type="internal", priority=1, role="behaviour")]
        )
        assert intent_sources(spec) == []


class TestScopeSourceOfTruthRules:
    def test_round_trip_preserves_rules(self) -> None:
        scope = ScopeConfig(
            domain="d",
            organization="o",
            source_of_truth_rules=[
                "Code wins on behaviour.",
                "Confluence wins on intent.",
            ],
        )
        restored = ScopeConfig.from_dict(scope.to_dict())
        assert restored.source_of_truth_rules == scope.source_of_truth_rules


class TestCoverageCategoryExpectedFilenames:
    def test_round_trip(self) -> None:
        cat = CoverageCategory(
            name="services",
            note_type="service",
            target_count=3,
            expected_filenames=["A.md", "B.md", "C.md"],
        )
        restored = CoverageCategory.from_dict(cat.to_dict())
        assert restored.expected_filenames == ["A.md", "B.md", "C.md"]

    def test_empty_by_default(self) -> None:
        cat = CoverageCategory(name="x", note_type="concept", target_count=1)
        assert cat.expected_filenames == []


class TestExecutorConfig:
    def test_defaults(self) -> None:
        ex = ExecutorConfig()
        assert ex.type == "cli"
        assert ex.runtime == "claude"
        assert ex.model == "sonnet"
        assert ex.timeout_s == 3600
        assert ex.retry == 1
        assert ex.on_fail == "abort"

    def test_round_trip(self) -> None:
        ex = ExecutorConfig(
            type="script",
            runtime="python",
            model="n/a",
            skill=None,
            script_path="scripts/repo_scan.py",
            args=["--spec", "spec.md"],
            timeout_s=600,
            retry=0,
            on_fail="skip",
        )
        restored = ExecutorConfig.from_dict(ex.to_dict())
        assert restored == ex


class TestCommandsConfig:
    def test_defaults(self) -> None:
        cmds = CommandsConfig()
        assert cmds.ask == "ask"
        assert cmds.research == "research"
        assert cmds.write == "write"

    def test_custom_names_round_trip(self) -> None:
        cmds = CommandsConfig(ask="myteam", research="myteam-add", write="doc")
        restored = CommandsConfig.from_dict(cmds.to_dict())
        assert restored == cmds


class TestSpecSettings:
    def test_empty_by_default(self) -> None:
        s = SpecSettings()
        assert s.default_executor is None
        assert s.stages == {}
        assert s.commands == CommandsConfig()

    def test_partial_override_round_trip(self) -> None:
        s = SpecSettings(
            default_executor=ExecutorConfig(model="opus"),
            stages={"scout": ExecutorConfig(model="sonnet", skill="custom-scout")},
            commands=CommandsConfig(ask="myteam"),
        )
        restored = SpecSettings.from_dict(s.to_dict())
        assert restored.default_executor is not None
        assert restored.default_executor.model == "opus"
        assert restored.stages["scout"].skill == "custom-scout"
        assert restored.commands.ask == "myteam"


class TestSpecConfigSettingsAndUrlPatterns:
    def test_spec_config_carries_settings_and_patterns(self) -> None:
        base = _minimal_spec(
            [DataSourceConfig(name="ds", type="internal", priority=1, role="behaviour")]
        )
        base.settings = SpecSettings(commands=CommandsConfig(ask="myteam"))
        base.code_source_url_patterns = [r"^https?://github\.com/acme/.+"]
        restored = SpecConfig.from_dict(base.to_dict())
        assert restored.settings.commands.ask == "myteam"
        assert restored.code_source_url_patterns == [r"^https?://github\.com/acme/.+"]

    def test_spec_config_defaults_when_settings_missing(self) -> None:
        base = _minimal_spec(
            [DataSourceConfig(name="ds", type="internal", priority=1, role="behaviour")]
        )
        restored = SpecConfig.from_dict(base.to_dict())
        assert restored.settings.default_executor is None
        assert restored.code_source_url_patterns == []


class TestResearchModeAndPhases:
    def test_research_modes_constant(self) -> None:
        assert RESEARCH_MODES == ("bootstrap", "refresh", "expand")

    def test_spec_defaults_to_bootstrap(self) -> None:
        spec = _minimal_spec(
            [DataSourceConfig(name="ds", type="internal", priority=1, role="behaviour")]
        )
        assert spec.research_mode == "bootstrap"

    def test_spec_research_mode_round_trips(self) -> None:
        spec = _minimal_spec(
            [DataSourceConfig(name="ds", type="internal", priority=1, role="behaviour")]
        )
        spec.research_mode = "refresh"
        restored = SpecConfig.from_dict(spec.to_dict())
        assert restored.research_mode == "refresh"

    def test_datasource_phases_default_empty(self) -> None:
        ds = DataSourceConfig(name="x", type="internal")
        assert ds.phases == []

    def test_datasource_phases_round_trip(self) -> None:
        ds = DataSourceConfig(
            name="news-feed",
            type="external",
            phases=["refresh", "expand"],
        )
        restored = DataSourceConfig.from_dict(ds.to_dict())
        assert restored.phases == ["refresh", "expand"]

    def test_applies_to_empty_phases_means_all(self) -> None:
        """Empty phases list = universal source, applies to every mode."""
        ds = DataSourceConfig(name="wikipedia", type="external")
        for mode in RESEARCH_MODES:
            assert ds.applies_to(mode)

    def test_applies_to_respects_phase_list(self) -> None:
        ds = DataSourceConfig(
            name="hackernews", type="external", phases=["refresh", "expand"]
        )
        assert not ds.applies_to("bootstrap")
        assert ds.applies_to("refresh")
        assert ds.applies_to("expand")


class TestIntFieldCoercionErrors:
    """A non-integer numeric field must raise SpecValidationError naming the
    field, the offending value and the expected type — not a bare ValueError
    from int() (#255). `priority: high` in particular reads like valid YAML;
    an author would not suspect it's a typo without a field-level message.
    """

    def test_datasource_priority_non_integer_is_field_error(self) -> None:
        with pytest.raises(SpecValidationError) as exc_info:
            DataSourceConfig.from_dict(
                {"name": "reddit", "type": "external", "priority": "high"}
            )
        message = str(exc_info.value)
        assert "reddit" in message
        assert "priority" in message
        assert "'high'" in message
        assert "integer" in message

    def test_note_type_min_word_count_non_integer_is_field_error(self) -> None:
        with pytest.raises(SpecValidationError) as exc_info:
            NoteTypeConfig.from_dict(
                {"name": "concept", "min_word_count": "five hundred"}
            )
        message = str(exc_info.value)
        assert "concept" in message
        assert "min_word_count" in message
        assert "'five hundred'" in message

    def test_coverage_category_target_count_non_integer_is_field_error(self) -> None:
        with pytest.raises(SpecValidationError) as exc_info:
            CoverageCategory.from_dict(
                {"name": "sdk-flows", "note_type": "flow", "target_count": "five"}
            )
        message = str(exc_info.value)
        assert "sdk-flows" in message
        assert "target_count" in message
        assert "'five'" in message

    def test_coverage_category_met_count_non_integer_is_field_error(self) -> None:
        with pytest.raises(SpecValidationError) as exc_info:
            CoverageCategory.from_dict(
                {
                    "name": "sdk-flows",
                    "note_type": "flow",
                    "target_count": 3,
                    "met_count": "two",
                }
            )
        assert "met_count" in str(exc_info.value)

    def test_coverage_targets_cycle_number_non_integer_is_field_error(self) -> None:
        with pytest.raises(SpecValidationError) as exc_info:
            CoverageTargets.from_dict({"cycle_number": "one"})
        assert "cycle_number" in str(exc_info.value)

    def test_executor_timeout_s_non_integer_is_field_error(self) -> None:
        with pytest.raises(SpecValidationError) as exc_info:
            ExecutorConfig.from_dict({"runtime": "claude", "timeout_s": "forever"})
        message = str(exc_info.value)
        assert "timeout_s" in message
        assert "'forever'" in message

    def test_executor_retry_non_integer_is_field_error(self) -> None:
        with pytest.raises(SpecValidationError) as exc_info:
            ExecutorConfig.from_dict({"retry": "twice"})
        assert "retry" in str(exc_info.value)

    def test_valid_integers_still_parse(self) -> None:
        ds = DataSourceConfig.from_dict(
            {"name": "x", "type": "internal", "priority": 1}
        )
        assert ds.priority == 1

    def test_numeric_string_still_coerces(self) -> None:
        ds = DataSourceConfig.from_dict(
            {"name": "x", "type": "internal", "priority": "3"}
        )
        assert ds.priority == 3

    def test_missing_field_still_defaults(self) -> None:
        ds = DataSourceConfig.from_dict({"name": "x", "type": "internal"})
        assert ds.priority == 2
