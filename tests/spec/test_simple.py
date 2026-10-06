"""Tests for src/research_framework/spec/simple.py — the friendly spec format."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework.spec.schema import SpecConfig, SpecValidationError
from research_framework.spec.simple import (
    GROWTH_DEFAULTS,
    GROWTH_MODES,
    SimpleSpec,
    expand,
    is_simple,
    load,
    parse_simple,
)
from research_framework.spec.validator import validate

MINIMAL_FRONTMATTER = """---
name: "Test Vault"
owner: "tester"
topic: "A small topic for expansion tests"
---

Freeform body.
"""


def _write(tmp_path: Path, body: str, name: str = "research.spec.md") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# parse_simple — happy paths & validation
# ---------------------------------------------------------------------------


class TestParseSimpleHappyPath:
    def test_minimal_fields_parse(self, tmp_path: Path) -> None:
        path = _write(tmp_path, MINIMAL_FRONTMATTER)
        simple = parse_simple(path)
        assert simple.name == "Test Vault"
        assert simple.owner == "tester"
        assert simple.topic == "A small topic for expansion tests"

    def test_dashes_inside_a_value_do_not_end_the_frontmatter(
        self, tmp_path: Path
    ) -> None:
        """Only a `---` LINE closes the frontmatter.

        The split was on the first `---` substring: the topic below was cut
        to "Kafka" and `goal` was dropped, with no error.
        """
        path = _write(
            tmp_path,
            "---\n"
            "name: Kafka Vault\n"
            "owner: tester\n"
            "topic: Kafka --- the definitive guide\n"
            "goal: Run it in production\n"
            "---\n"
            "\n"
            "Freeform body.\n",
        )
        simple = parse_simple(path)
        assert simple.topic == "Kafka --- the definitive guide"
        assert simple.goal == "Run it in production"

    def test_defaults_applied_when_absent(self, tmp_path: Path) -> None:
        """Unspecified fields get safe defaults — user can write 3 lines."""
        path = _write(tmp_path, MINIMAL_FRONTMATTER)
        simple = parse_simple(path)
        assert simple.growth_mode == "incremental"
        assert simple.research_mode == "bootstrap"
        assert simple.scope_include == []
        assert simple.scope_exclude == []
        assert simple.sources == []

    def test_full_spec_round_trips_through_to_dict(self, tmp_path: Path) -> None:
        body = """---
name: "Macro Film"
owner: "jdoe"
topic: "Macro on film"
goal: "Learn it"
problem: "Most guides are digital-only"
scope:
  include: ["bellows", "reciprocity"]
  exclude: ["digital"]
growth_mode: big-bang
research_mode: expand
sources:
  - name: "Wikipedia"
    type: external
    phases: [bootstrap]
acceptance: ["coverage met", "no stubs"]
settings:
  budget:
    max_usd: 7.5
---
"""
        simple = parse_simple(_write(tmp_path, body))
        d = simple.to_dict()
        assert d["scope"] == {
            "include": ["bellows", "reciprocity"],
            "exclude": ["digital"],
        }
        assert d["growth_mode"] == "big-bang"
        assert d["research_mode"] == "expand"
        assert d["sources"][0]["phases"] == ["bootstrap"]


class TestParseSimpleRejections:
    def test_missing_name_is_rejected(self, tmp_path: Path) -> None:
        body = "---\nowner: o\ntopic: t\n---\n"
        with pytest.raises(SpecValidationError) as exc:
            parse_simple(_write(tmp_path, body))
        assert any("'name'" in m for m in exc.value.messages)

    def test_missing_topic_is_rejected(self, tmp_path: Path) -> None:
        body = "---\nname: n\nowner: o\n---\n"
        with pytest.raises(SpecValidationError) as exc:
            parse_simple(_write(tmp_path, body))
        assert any("'topic'" in m for m in exc.value.messages)

    def test_invalid_growth_mode_is_rejected(self, tmp_path: Path) -> None:
        body = "---\nname: n\nowner: o\ntopic: t\ngrowth_mode: huge\n---\n"
        with pytest.raises(SpecValidationError) as exc:
            parse_simple(_write(tmp_path, body))
        assert any("growth_mode" in m and "huge" in m for m in exc.value.messages)

    def test_invalid_research_mode_is_rejected(self, tmp_path: Path) -> None:
        body = "---\nname: n\nowner: o\ntopic: t\nresearch_mode: turbo\n---\n"
        with pytest.raises(SpecValidationError) as exc:
            parse_simple(_write(tmp_path, body))
        assert any("research_mode" in m for m in exc.value.messages)

    def test_source_without_name_is_rejected(self, tmp_path: Path) -> None:
        body = "---\nname: n\nowner: o\ntopic: t\nsources:\n  - type: external\n---\n"
        with pytest.raises(SpecValidationError) as exc:
            parse_simple(_write(tmp_path, body))
        assert any("sources[0]" in m for m in exc.value.messages)

    def test_missing_frontmatter_is_rejected(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "# No frontmatter here\n")
        with pytest.raises(SpecValidationError):
            parse_simple(path)

    def test_missing_file_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(SpecValidationError):
            parse_simple(tmp_path / "nope.md")


class TestParseSimpleUserFriendlyShortcuts:
    """Regression coverage for the exact failure modes a non-technical user hit
    in the first round of E2E testing: owner omitted, plain-string sources,
    and top-level ``budget_usd`` / ``model`` shortcuts."""

    def test_missing_owner_defaults_to_user_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``vault-spec`` skill rarely surfaces ``owner`` to users, so the
        parser has to be forgiving or every auto-drafted spec gets rejected."""
        monkeypatch.setenv("USER", "anon")
        body = "---\nname: n\ntopic: t\n---\n"
        simple = parse_simple(_write(tmp_path, body))
        assert simple.owner == "anon"

    def test_plain_string_sources_are_coerced(self, tmp_path: Path) -> None:
        """The skill template and examples advertise string sources; the
        parser has to accept them without forcing users to learn the mapping
        syntax."""
        body = (
            "---\nname: n\ntopic: t\n"
            "sources:\n"
            "  - Portuguese family cooking sites\n"
            "  - https://nutrition.gov/\n"
            "---\n"
        )
        simple = parse_simple(_write(tmp_path, body))
        assert len(simple.sources) == 2
        assert simple.sources[0]["name"] == "Portuguese family cooking sites"
        # URL strings ALSO populate ``description`` so downstream routing can
        # treat them as linkable artefacts.
        assert simple.sources[1]["name"] == "https://nutrition.gov/"
        assert simple.sources[1]["description"] == "https://nutrition.gov/"

    def test_plain_string_sources_expand_to_data_source_config(
        self, tmp_path: Path
    ) -> None:
        """Round-trip: a string source survives parse → expand into a valid
        DataSourceConfig and passes the detailed validator."""
        body = "---\nname: n\ntopic: t\nsources:\n  - ExampleSrc\n---\n"
        simple = parse_simple(_write(tmp_path, body))
        spec = expand(simple, location=tmp_path / "vault")
        assert len(spec.data_sources) == 1
        assert spec.data_sources[0].name == "ExampleSrc"
        validate(spec)

    def test_empty_string_source_is_rejected(self, tmp_path: Path) -> None:
        """Empty string sources indicate user typo, not intent — hard error."""
        body = '---\nname: n\ntopic: t\nsources:\n  - ""\n  - "  "\n---\n'
        with pytest.raises(SpecValidationError) as exc:
            parse_simple(_write(tmp_path, body))
        assert any("sources[0]" in m for m in exc.value.messages)

    def test_top_level_budget_usd_folds_into_settings(self, tmp_path: Path) -> None:
        """``budget_usd: 5`` at the top level is the template default; the
        parser maps it into ``settings.budget.max_usd``. Spec 061 keeps the
        dollar cap OFF the expanded spec (it seeds the vault settings.yaml at
        install time), so the parser layer is the one place it lives now."""
        body = "---\nname: n\ntopic: t\nbudget_usd: 5\n---\n"
        simple = parse_simple(_write(tmp_path, body))
        assert simple.settings["budget"]["max_usd"] == 5.0
        spec = expand(simple, location=tmp_path / "vault")
        validate(spec)
        assert not hasattr(spec.budget, "max_usd")

    def test_top_level_model_folds_into_default_executor(self, tmp_path: Path) -> None:
        body = "---\nname: n\ntopic: t\nmodel: haiku\n---\n"
        simple = parse_simple(_write(tmp_path, body))
        assert simple.settings["default_executor"]["model"] == "haiku"

    def test_top_level_shortcut_does_not_clobber_explicit_settings(
        self, tmp_path: Path
    ) -> None:
        """If a power user already set ``settings.budget.max_usd`` explicitly
        we MUST respect it — the top-level shortcut is only a convenience for
        the chat path, never an override."""
        body = (
            "---\nname: n\ntopic: t\nbudget_usd: 1\n"
            "settings:\n  budget:\n    max_usd: 99\n---\n"
        )
        simple = parse_simple(_write(tmp_path, body))
        assert simple.settings["budget"]["max_usd"] == 99

    def test_budget_usd_non_numeric_is_rejected(self, tmp_path: Path) -> None:
        body = '---\nname: n\ntopic: t\nbudget_usd: "five bucks"\n---\n'
        with pytest.raises(SpecValidationError) as exc:
            parse_simple(_write(tmp_path, body))
        assert any("budget_usd" in m for m in exc.value.messages)


# ---------------------------------------------------------------------------
# expand — structural invariants
# ---------------------------------------------------------------------------


def _simple(**overrides) -> SimpleSpec:
    base = dict(
        name="Test",
        owner="t",
        topic="topic",
        scope_include=["alpha", "beta"],
    )
    base.update(overrides)
    return SimpleSpec(**base)


class TestExpandCoreShape:
    def test_expand_produces_valid_spec(self, tmp_path: Path) -> None:
        spec = expand(_simple(), location=tmp_path / "vault")
        validate(spec)  # should NOT raise

    def test_expand_carries_research_mode_through(self, tmp_path: Path) -> None:
        spec = expand(_simple(research_mode="refresh"), location=tmp_path / "vault")
        assert spec.research_mode == "refresh"

    def test_expand_always_includes_concept_note_type(self, tmp_path: Path) -> None:
        spec = expand(_simple(), location=tmp_path / "vault")
        names = [nt.name for nt in spec.note_types]
        assert "concept" in names

    def test_simple_non_code_first_spec_gives_concept_soft_policy(
        self, tmp_path: Path
    ) -> None:
        """Recipe/photography/etc vaults have no repo to cite — forcing
        `source_policy: hard` produces a flood of MISSING CODE SOURCE
        violations on every concept note (v0.2.5/0.2.6 regression)."""
        spec = expand(
            _simple(
                sources=[
                    {"name": "Food From Portugal", "role": "recipes"},
                    {"name": "Teleculinaria", "role": "recipes"},
                ]
            ),
            location=tmp_path / "vault",
        )
        concept = next(nt for nt in spec.note_types if nt.name == "concept")
        assert concept.source_policy == "soft"

    def test_simple_code_first_spec_keeps_concept_hard_policy(
        self, tmp_path: Path
    ) -> None:
        """When the spec IS code-first (priority=1 source, intent role, or
        a repos list), concept retains `hard` so the verifier gate fires."""
        spec = expand(
            _simple(
                sources=[
                    {
                        "name": "Primary repo",
                        "role": "behaviour",
                        "priority": 1,
                        "repos": ["https://github.com/example/app"],
                    }
                ]
            ),
            location=tmp_path / "vault",
        )
        concept = next(nt for nt in spec.note_types if nt.name == "concept")
        assert concept.source_policy == "hard"

    def test_simple_spec_maps_include_to_boundaries_and_exclude_to_out_of_scope(
        self, tmp_path: Path
    ) -> None:
        """v0.2.5/0.2.6 bug: CLAUDE.md rendered every exclude item as
        'In scope' because the expander mapped scope_exclude onto
        ScopeConfig.boundaries and dropped scope_include entirely."""
        spec = expand(
            _simple(
                scope_include=["recipes that freeze well"],
                scope_exclude=["deep-frying recipes"],
            ),
            location=tmp_path / "vault",
        )
        assert spec.scope.boundaries == ["recipes that freeze well"]
        assert spec.scope.out_of_scope == ["deep-frying recipes"]

    def test_default_web_source_is_strategy_hint_not_unbacked(
        self, tmp_path: Path
    ) -> None:
        """Regression (spec 069): a sources-less simple spec injects a default
        ``Web`` source. Spec 069's source-backing validation must NOT classify
        it as ``unbacked`` (the rc7 trap that broke every simple-spec scaffold);
        open web search is honest LLM-fetch guidance ⇒ a ``strategy_hint``."""
        from research_framework.spec.source_backing import (
            build_available_registry,
            source_is_backed,
        )

        spec = expand(_simple(sources=[]), location=tmp_path / "vault")
        web = next(s for s in spec.data_sources if s.name == "Web")
        assert web.kind == "strategy_hint"
        registry = build_available_registry()
        assert source_is_backed(web, registry) == "strategy_hint"

    def test_throwaway_growth_mode_only_has_concept(self, tmp_path: Path) -> None:
        spec = expand(_simple(growth_mode="throwaway"), location=tmp_path / "vault")
        names = [nt.name for nt in spec.note_types]
        assert names == ["concept"]
        validate(spec)

    def test_incremental_growth_mode_adds_source_note_type(
        self, tmp_path: Path
    ) -> None:
        spec = expand(_simple(growth_mode="incremental"), location=tmp_path / "vault")
        names = [nt.name for nt in spec.note_types]
        assert names == ["concept", "source"]
        src = next(nt for nt in spec.note_types if nt.name == "source")
        assert src.folder == "02 - Sources"
        assert src.source_policy == "soft"
        validate(spec)

    def test_big_bang_growth_mode_adds_moc_and_source(self, tmp_path: Path) -> None:
        spec = expand(_simple(growth_mode="big-bang"), location=tmp_path / "vault")
        names = [nt.name for nt in spec.note_types]
        assert names == ["moc", "concept", "source"]
        folders = {nt.name: nt.folder for nt in spec.note_types}
        assert folders["moc"] == "00 - MOC"
        assert folders["concept"] == "01 - Concepts"
        assert folders["source"] == "02 - Sources"
        validate(spec)

    def test_note_type_folders_are_unique(self, tmp_path: Path) -> None:
        """Folder collision would break scaffold; guard explicitly."""
        for mode in GROWTH_MODES:
            spec = expand(_simple(growth_mode=mode), location=tmp_path / f"v-{mode}")
            folders = [nt.folder for nt in spec.note_types]
            assert len(folders) == len(set(folders)), (
                f"{mode}: duplicate folders {folders}"
            )

    def test_expand_includes_required_search_dimensions(self, tmp_path: Path) -> None:
        spec = expand(_simple(), location=tmp_path / "vault")
        assert {"domain", "market"}.issubset(set(spec.search_dimensions))

    def test_expand_seeds_two_tier_source_of_truth_rule(self, tmp_path: Path) -> None:
        spec = expand(_simple(), location=tmp_path / "vault")
        joined = "\n".join(spec.scope.source_of_truth_rules).lower()
        assert "tier-1" in joined or "principle ix" in joined
        assert "tier-2" in joined


class TestExpandCoverageTargets:
    def test_one_category_per_include(self, tmp_path: Path) -> None:
        spec = expand(
            _simple(scope_include=["alpha", "beta", "gamma"]),
            location=tmp_path / "v",
        )
        names = [c.name for c in spec.coverage_targets.categories]
        assert names == ["alpha", "beta", "gamma"]

    def test_catch_all_when_include_is_empty(self, tmp_path: Path) -> None:
        spec = expand(
            _simple(scope_include=[], topic="macro-film"),
            location=tmp_path / "v",
        )
        categories = spec.coverage_targets.categories
        assert len(categories) == 1
        assert categories[0].note_type == "concept"

    def test_target_count_follows_growth_mode(self, tmp_path: Path) -> None:
        spec = expand(
            _simple(growth_mode="throwaway", scope_include=["x", "y"]),
            location=tmp_path / "v",
        )
        target = GROWTH_DEFAULTS["throwaway"].coverage_target_per_include
        assert all(c.target_count == target for c in spec.coverage_targets.categories)


class TestExpandGrowthModeBudget:
    @pytest.mark.parametrize("mode", GROWTH_MODES)
    def test_all_modes_yield_valid_spec(self, tmp_path: Path, mode: str) -> None:
        spec = expand(_simple(growth_mode=mode), location=tmp_path / "v")
        validate(spec)

    def test_growth_defaults_scale_budget(self) -> None:
        """Sanity: big-bang should cost more than throwaway by default.

        Spec 061 moved the cycle/dollar caps off the spec, so the scaling
        invariant is now asserted on ``GROWTH_DEFAULTS`` directly — those
        values seed the vault ``settings.yaml`` at install time, not the spec.
        """
        assert (
            GROWTH_DEFAULTS["big-bang"].budget_usd
            > GROWTH_DEFAULTS["throwaway"].budget_usd
        )
        assert (
            GROWTH_DEFAULTS["big-bang"].max_cycles
            > GROWTH_DEFAULTS["throwaway"].max_cycles
        )

    def test_expand_does_not_bake_budget_onto_spec(self, tmp_path: Path) -> None:
        """The expanded spec's ``BudgetConfig`` carries only the warn threshold;
        the cycle/dollar caps live in ``settings.yaml`` (spec 061 / ADR-0011)."""
        spec = expand(_simple(growth_mode="incremental"), location=tmp_path / "v")
        validate(spec)
        assert not hasattr(spec.budget, "max_usd")
        assert not hasattr(spec.budget, "max_cycles")
        assert not hasattr(spec, "max_cycles")


class TestExpandDataSources:
    def test_default_source_injected_when_empty(self, tmp_path: Path) -> None:
        spec = expand(_simple(sources=[]), location=tmp_path / "v")
        assert len(spec.data_sources) == 1
        assert spec.data_sources[0].type == "external"

    def test_user_sources_carry_phases_through(self, tmp_path: Path) -> None:
        simple = _simple(
            sources=[
                {
                    "name": "Photrio",
                    "type": "external",
                    "role": "domain",
                    "phases": ["refresh", "expand"],
                }
            ]
        )
        spec = expand(simple, location=tmp_path / "v")
        assert spec.data_sources[0].phases == ["refresh", "expand"]

    def test_user_sources_default_phase_list_is_empty(self, tmp_path: Path) -> None:
        simple = _simple(sources=[{"name": "X", "type": "external", "role": "domain"}])
        spec = expand(simple, location=tmp_path / "v")
        assert spec.data_sources[0].phases == []


# ---------------------------------------------------------------------------
# is_simple + load — auto-detection
# ---------------------------------------------------------------------------


class TestIsSimple:
    def test_simple_recognised_by_topic_key(self) -> None:
        assert is_simple({"topic": "x", "name": "n"})

    def test_simple_recognised_by_growth_mode_key(self) -> None:
        assert is_simple({"growth_mode": "incremental", "name": "n"})

    def test_detailed_recognised_by_data_sources(self) -> None:
        assert not is_simple({"data_sources": [{"name": "x"}], "topic": "t"})

    def test_note_types_alone_does_not_trigger_detailed_parser(self) -> None:
        # Since 015d, `note_types` is also valid in the simple spec.
        # A spec with only `note_types` (no `data_sources` / `coverage_targets`)
        # routes to the simple parser which now understands the richer taxonomy.
        assert is_simple({"note_types": [{"name": "concept"}]})

    def test_empty_dict_routes_to_simple_parser(self) -> None:
        """An empty or minimally-populated dict routes to the simple parser
        so the user gets a clear "missing required field 'topic'" error
        rather than the detailed parser's stack of structural complaints
        about fields the user never tried to write."""
        assert is_simple({})
        assert is_simple({"name": "foo"})


class TestLoadAutoDetect:
    def test_load_routes_simple_through_expand(self, tmp_path: Path) -> None:
        body = MINIMAL_FRONTMATTER
        spec = load(_write(tmp_path, body))
        assert isinstance(spec, SpecConfig)
        assert spec.research_mode == "bootstrap"
        validate(spec)

    def test_load_uses_explicit_location_when_given(self, tmp_path: Path) -> None:
        body = MINIMAL_FRONTMATTER
        override = tmp_path / "elsewhere"
        spec = load(_write(tmp_path, body), location=override)
        assert spec.location == override


# ---------------------------------------------------------------------------
# vault.corpus_dir — 015a spec field
# ---------------------------------------------------------------------------


class TestVaultCorpusDir:
    """SimpleSpec round-trip and validation for vault.corpus_dir (015a)."""

    def test_default_is_data_vault_when_absent(self, tmp_path: Path) -> None:
        simple = parse_simple(_write(tmp_path, MINIMAL_FRONTMATTER))
        assert simple.vault_corpus_dir == "data_vault"

    def test_custom_corpus_dir_is_parsed(self, tmp_path: Path) -> None:
        body = (
            "---\n"
            "name: Legal Research\n"
            "owner: alice\n"
            "topic: Legal case law\n"
            "vault:\n"
            "  corpus_dir: cases\n"
            "---\n"
        )
        simple = parse_simple(_write(tmp_path, body))
        assert simple.vault_corpus_dir == "cases"

    def test_corpus_dir_round_trips_via_to_dict(self, tmp_path: Path) -> None:
        body = (
            "---\n"
            "name: Legal Research\n"
            "owner: alice\n"
            "topic: Legal case law\n"
            "vault:\n"
            "  corpus_dir: cases\n"
            "---\n"
        )
        simple = parse_simple(_write(tmp_path, body))
        d = simple.to_dict()
        assert d["vault"]["corpus_dir"] == "cases"

    def test_corpus_dir_threads_into_spec_config(self, tmp_path: Path) -> None:
        body = (
            "---\n"
            "name: Legal Research\n"
            "owner: alice\n"
            "topic: Legal case law\n"
            "vault:\n"
            "  corpus_dir: cases\n"
            "---\n"
        )
        simple = parse_simple(_write(tmp_path, body))
        spec = expand(simple, location=tmp_path / "vault")
        assert spec.vault_corpus_dir == "cases"

    def test_spec_config_round_trips_vault_corpus_dir(self, tmp_path: Path) -> None:
        """to_dict / from_dict preserves vault_corpus_dir."""
        body = (
            "---\n"
            "name: Legal Research\n"
            "owner: alice\n"
            "topic: Legal case law\n"
            "vault:\n"
            "  corpus_dir: cases\n"
            "---\n"
        )
        simple = parse_simple(_write(tmp_path, body))
        spec = expand(simple, location=tmp_path / "vault")
        assert spec.vault_corpus_dir == "cases"

        from research_framework.spec.schema import SpecConfig

        spec2 = SpecConfig.from_dict(spec.to_dict())
        assert spec2.vault_corpus_dir == "cases"

    def test_default_preserved_in_from_dict_when_absent(self) -> None:
        """Old spec-parse.json files without vault_corpus_dir still default."""
        from research_framework.spec.schema import SpecConfig

        spec = SpecConfig.from_dict(
            {
                "name": "feeds-vault",
                "location": "/tmp/feeds-vault",
                "owner": "someone",
                # vault_corpus_dir deliberately absent
            }
        )
        assert spec.vault_corpus_dir == "data_vault"


class TestVaultCorpusDirValidation:
    """Invalid vault.corpus_dir values must raise SpecValidationError."""

    def _spec(self, corpus_dir: str) -> str:
        return (
            "---\n"
            "name: n\n"
            "owner: o\n"
            "topic: t\n"
            f"vault:\n"
            f"  corpus_dir: {corpus_dir!r}\n"
            "---\n"
        )

    def test_empty_string_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(SpecValidationError) as exc:
            parse_simple(_write(tmp_path, self._spec("")))
        assert any("corpus_dir" in m for m in exc.value.messages)

    def test_dotdot_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(SpecValidationError) as exc:
            parse_simple(_write(tmp_path, self._spec("..")))
        assert any("corpus_dir" in m for m in exc.value.messages)

    def test_absolute_path_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(SpecValidationError) as exc:
            parse_simple(_write(tmp_path, self._spec("/abs/path")))
        assert any("corpus_dir" in m for m in exc.value.messages)

    def test_pipeline_dir_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(SpecValidationError) as exc:
            parse_simple(_write(tmp_path, self._spec("_pipeline")))
        assert any("corpus_dir" in m for m in exc.value.messages)

    def test_templates_dir_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(SpecValidationError) as exc:
            parse_simple(_write(tmp_path, self._spec("_templates")))
        assert any("corpus_dir" in m for m in exc.value.messages)

    def test_raw_data_dir_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(SpecValidationError) as exc:
            parse_simple(_write(tmp_path, self._spec("raw_data")))
        assert any("corpus_dir" in m for m in exc.value.messages)

    def test_spaces_in_name_are_allowed(self, tmp_path: Path) -> None:
        """Codebase Vault precedent: corpus dirs with spaces are valid."""
        body = (
            "---\n"
            "name: n\n"
            "owner: o\n"
            "topic: t\n"
            "vault:\n"
            "  corpus_dir: Codebase Vault\n"
            "---\n"
        )
        simple = parse_simple(_write(tmp_path, body))
        assert simple.vault_corpus_dir == "Codebase Vault"
