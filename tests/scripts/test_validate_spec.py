"""Tests for scripts/validate_spec.py — the spec quality gate.

These assertions back the commitment in the ``vault-spec`` SKILL:

- A spec missing only soft fields (``owner``, budget, etc.) passes the gate
  with warnings so the skill can surface them.
- A structurally broken spec (missing ``topic``, bad growth_mode, invalid
  YAML) exits non-zero and emits a JSON payload the skill can iterate on.
- The exact failure modes the first E2E pass hit (plain-string sources,
  missing owner) now round-trip cleanly with warnings.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


@pytest.fixture
def validate_spec_module():
    """Load validate_spec.py as a module without shelling out."""
    script = Path(__file__).resolve().parents[2] / "scripts" / "validate_spec.py"
    spec = importlib.util.spec_from_file_location("validate_spec_script", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["validate_spec_script"] = module
    spec.loader.exec_module(module)
    return module


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "research.spec.md"
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# The exact user-hit scenario: non-technical user, agent-authored spec.
# ---------------------------------------------------------------------------


SKILL_AUTHORED_SPEC = """---
name: portugal-family-freezer-meal-prep
topic: Portuguese family freezer meal prep vault.
goal: Plan weekly meals from real freezer-friendly recipes.
problem: Hard to assemble a trusted base of tested recipes.
growth_mode: incremental
size: large
scope:
  include:
    - Real recipes from real cooks.
    - Lunch and dinner meals for families.
sources:
  - Portuguese-language family cooking sites.
  - Portugal-accessible recipe publishers.
acceptance:
  - Enough variety to plan a month without repeating.
budget_usd: null
---
"""


class TestUserHitScenario:
    """Every failure the first E2E test surfaced must now pass with warnings."""

    def test_skill_authored_spec_passes_gate(
        self,
        tmp_path: Path,
        validate_spec_module,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The actual file the agent handed the user must exit ``0`` now."""
        monkeypatch.setenv("USER", "tester")
        path = _write(tmp_path, SKILL_AUTHORED_SPEC)
        errors, warnings = validate_spec_module.validate_spec(path)
        assert errors == [], f"should have no hard errors, got {errors}"
        # The three issues the skill silently defaulted on — owner, string
        # sources, missing budget — must all surface as warnings so the skill
        # can read them back to the user before kicking off a run.
        joined = "\n".join(warnings)
        assert "owner" in joined
        assert "plain string" in joined or "plain strings" in joined
        assert "budget" in joined

    def test_cli_exit_0_for_skill_authored_spec(
        self,
        tmp_path: Path,
        validate_spec_module,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        path = _write(tmp_path, SKILL_AUTHORED_SPEC)
        rc = validate_spec_module.main([str(path)])
        assert rc == 0
        captured = capsys.readouterr()
        assert "SPEC OK" in captured.out
        # Warnings printed to stderr so pipelines can split signals.
        assert "Warnings" in captured.err

    def test_strict_mode_flips_warnings_to_failure(
        self,
        tmp_path: Path,
        validate_spec_module,
    ) -> None:
        """CI pipelines can opt into ``--strict`` to force every default to
        be explicit."""
        path = _write(tmp_path, SKILL_AUTHORED_SPEC)
        rc = validate_spec_module.main([str(path), "--strict"])
        assert rc == 1  # warnings present → strict mode treats as failure


# ---------------------------------------------------------------------------
# Hard-error paths — the gate must reject these, non-zero exit.
# ---------------------------------------------------------------------------


class TestHardErrors:
    def test_missing_topic_is_an_error(
        self, tmp_path: Path, validate_spec_module
    ) -> None:
        path = _write(tmp_path, "---\nname: n\n---\n")
        errors, _ = validate_spec_module.validate_spec(path)
        assert any("'topic'" in e for e in errors)

    def test_bad_growth_mode_is_an_error(
        self, tmp_path: Path, validate_spec_module
    ) -> None:
        path = _write(tmp_path, "---\nname: n\ntopic: t\ngrowth_mode: huge\n---\n")
        errors, _ = validate_spec_module.validate_spec(path)
        assert any("growth_mode" in e for e in errors)

    def test_nonexistent_file_is_an_error(
        self, tmp_path: Path, validate_spec_module
    ) -> None:
        errors, _ = validate_spec_module.validate_spec(tmp_path / "nope.md")
        assert any("not found" in e for e in errors)

    def test_json_mode_reports_errors_structurally(
        self,
        tmp_path: Path,
        validate_spec_module,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Agents parse JSON — the schema must be stable."""
        path = _write(tmp_path, "---\nname: n\n---\n")
        rc = validate_spec_module.main([str(path), "--json"])
        assert rc == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is False
        assert payload["errors"], "errors list must be populated"
        assert "warnings" in payload  # key always present

    def test_cli_exit_1_on_errors(
        self,
        tmp_path: Path,
        validate_spec_module,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        path = _write(tmp_path, "---\nname: n\n---\n")
        rc = validate_spec_module.main([str(path)])
        assert rc == 1
        assert "SPEC INVALID" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Summary payload — the skill reads these 3 lines back to the user.
# ---------------------------------------------------------------------------


class TestStrictModeHardensSkillOutput:
    """Regression: the skill now runs in --strict mode so every silent
    default surfaces as an error. These tests prove --strict actually fails
    the cases the user complained about (hidden owner/budget, plain-string
    sources, description-only sources, implicit model)."""

    COMPLETE_SPEC = """---
name: complete-example
location: /tmp/complete-example
owner: jdoe

scope:
  domain: "Complete spec domain"
  organization: "Test org"
  boundaries:
    - One bullet.
  out_of_scope:
    - commercial kitchen operations
  contextual_questions:
    - "What is this?"

note_types:
  - name: concept
    description: "Standalone concept note."
    folder: "01 - Concepts"
    required_sections: ["Overview"]
    min_word_count: 200

data_sources:
  - name: Example Recipes
    type: external
    description: "Example recipe source"
    required: true
    access_method: "web fetch"
    kind: strategy_hint
    role: domain

search_dimensions: ["technical", "domain", "market", "temporal"]

coverage_targets:
  categories:
    - name: concepts
      note_type: concept
      target_count: 5
      met_count: 0
      required: true

budget:
  max_usd: 5.0
  max_cycles: 3
  warn_at_pct: 0.8

max_cycles: 3
naming_convention: full_name
access_modes: ["claude-code", "obsidian"]
---
"""

    def test_strict_accepts_a_fully_explicit_spec(
        self, tmp_path: Path, validate_spec_module
    ) -> None:
        """A spec with every field spelled out MUST pass --strict cleanly.
        If this ever fails it means the skill now has no valid output shape."""
        path = _write(tmp_path, self.COMPLETE_SPEC)
        rc = validate_spec_module.main([str(path), "--strict"])
        assert rc == 0

    def test_warns_when_scope_out_of_scope_missing(
        self, tmp_path: Path, validate_spec_module
    ) -> None:
        """Phase 2 prerequisite — missing scope.out_of_scope surfaces as a warning
        (not an error). Phase 1 stays unaffected."""
        body = (
            "---\nname: n\nowner: o\ntopic: t\nacceptance: [a]\n"
            "budget_usd: 5\nmodel: sonnet\n"
            "sources:\n  - name: S\n    url: https://example.com\n    role: r\n"
            "---\n"
        )
        errors, warnings = validate_spec_module.validate_spec(_write(tmp_path, body))
        assert errors == []
        assert any("out_of_scope" in w for w in warnings)

    def test_no_warning_when_out_of_scope_present(
        self, tmp_path: Path, validate_spec_module
    ) -> None:
        body = (
            "---\nname: n\nowner: o\ntopic: t\nacceptance: [a]\n"
            "budget_usd: 5\nmodel: sonnet\n"
            "scope:\n  out_of_scope:\n    - some excluded term\n"
            "sources:\n  - name: S\n    url: https://example.com\n    role: r\n"
            "---\n"
        )
        _, warnings = validate_spec_module.validate_spec(_write(tmp_path, body))
        assert not any("out_of_scope" in w for w in warnings)

    def test_strict_flags_plain_string_sources(
        self, tmp_path: Path, validate_spec_module
    ) -> None:
        body = (
            "---\nname: n\nowner: o\ntopic: t\nacceptance: [a]\n"
            "budget_usd: 5\nmodel: sonnet\n"
            "sources:\n  - Just a description\n---\n"
        )
        _, warnings = validate_spec_module.validate_spec(_write(tmp_path, body))
        assert any("plain strings" in w for w in warnings)
        rc = validate_spec_module.main([str(_write(tmp_path, body)), "--strict"])
        assert rc == 1

    def test_strict_flags_description_only_mapping_sources(
        self, tmp_path: Path, validate_spec_module
    ) -> None:
        """Even when the source IS a mapping, if it carries no URL the
        scout can't act on it. The skill has to replace the entry or delete."""
        body = (
            "---\nname: n\nowner: o\ntopic: t\nacceptance: [a]\n"
            "budget_usd: 5\nmodel: sonnet\n"
            "sources:\n  - name: Portuguese recipe blogs\n    role: recipes\n"
            "---\n"
        )
        _, warnings = validate_spec_module.validate_spec(_write(tmp_path, body))
        assert any("description-only" in w for w in warnings)

    def test_strict_flags_missing_model(
        self, tmp_path: Path, validate_spec_module
    ) -> None:
        body = (
            "---\nname: n\nowner: o\ntopic: t\nacceptance: [a]\nbudget_usd: 5\n"
            "sources:\n  - name: s\n    url: https://example.com\n    role: x\n"
            "---\n"
        )
        _, warnings = validate_spec_module.validate_spec(_write(tmp_path, body))
        assert any("'model'" in w for w in warnings)

    def test_model_via_settings_default_executor_satisfies_check(
        self, tmp_path: Path, validate_spec_module
    ) -> None:
        """Power users who set ``settings.default_executor.model`` should
        NOT be nagged about top-level ``model:``."""
        body = (
            "---\nname: n\nowner: o\ntopic: t\nacceptance: [a]\nbudget_usd: 5\n"
            "sources:\n  - name: s\n    url: https://example.com\n    role: x\n"
            "settings:\n  default_executor:\n    model: opus\n"
            "---\n"
        )
        _, warnings = validate_spec_module.validate_spec(_write(tmp_path, body))
        assert not any("'model'" in w for w in warnings)


class TestSummary:
    def test_json_summary_shape_is_stable(
        self,
        tmp_path: Path,
        validate_spec_module,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        path = _write(tmp_path, SKILL_AUTHORED_SPEC)
        rc = validate_spec_module.main([str(path), "--json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
        summary = payload["summary"]
        assert len(summary) == 3  # name/mode/size, primary acceptance, budget
        assert "portugal-family-freezer-meal-prep" in summary[0]
        assert "incremental" in summary[0]


# ===========================================================================
# Feature 017 — SpecConfig extension fields (T005)
# Direct library-level tests for `forbidden_filename_prefixes` and
# `CoverageCategory.priority`. The high-level CLI is exercised in the
# pre-existing tests above; these focus on the new validator helpers in
# isolation so a regression points at exactly the field that broke.
# ===========================================================================


class TestSpecExtension017:
    """Validation rules for `forbidden_filename_prefixes` and `priority`.

    Per `contracts/spec-extension.schema.md` (R-007):
    - Both fields are additive optional with safe defaults.
    - `forbidden_filename_prefixes` entries MUST be non-empty strings ending
      in `_` or `-`. Empty list valid; absent → empty list.
    - `priority` MUST be int in [0, 100]; absent → 0.
    """

    def _make_spec(
        self,
        forbidden_filename_prefixes: list[str] | None = None,
        category_priority: int | None = None,
    ) -> SpecConfig:  # noqa: F821 — SpecConfig imported lazily below
        from research_framework.spec.schema import (
            BudgetConfig,
            CoverageCategory,
            CoverageTargets,
            DataSourceConfig,
            NoteTypeConfig,
            ScopeConfig,
            SpecConfig,
        )

        cat_kwargs: dict = {
            "name": "spring-feature",
            "note_type": "concept",
            "target_count": 5,
        }
        if category_priority is not None:
            cat_kwargs["priority"] = category_priority

        kwargs: dict = {
            "name": "x",
            "location": Path("."),
            "owner": "u",
            "scope": ScopeConfig(domain="d", organization="o"),
            "note_types": [
                NoteTypeConfig(name="concept", description="", folder="concepts/")
            ],
            "data_sources": [DataSourceConfig(name="s", type="external", priority=2)],
            "search_dimensions": ["domain", "market"],
            "coverage_targets": CoverageTargets(
                categories=[CoverageCategory(**cat_kwargs)]
            ),
            "budget": BudgetConfig(),
        }
        if forbidden_filename_prefixes is not None:
            kwargs["forbidden_filename_prefixes"] = forbidden_filename_prefixes
        return SpecConfig(**kwargs)

    # --- forbidden_filename_prefixes ---------------------------------------

    def test_forbidden_prefixes_default_is_empty_list(self) -> None:
        spec = self._make_spec()
        assert spec.forbidden_filename_prefixes == []

    def test_forbidden_prefixes_accepts_underscore_suffix(self) -> None:
        from research_framework.spec.validator import validate

        spec = self._make_spec(forbidden_filename_prefixes=["oms_", "erp_"])
        validate(spec)  # MUST NOT raise

    def test_forbidden_prefixes_accepts_dash_suffix(self) -> None:
        from research_framework.spec.validator import validate

        spec = self._make_spec(forbidden_filename_prefixes=["legacy-", "deprecated-"])
        validate(spec)

    def test_forbidden_prefixes_rejects_bare_strings(self) -> None:
        from research_framework.spec.schema import SpecValidationError
        from research_framework.spec.validator import validate

        spec = self._make_spec(forbidden_filename_prefixes=["nosuffix"])
        with pytest.raises(SpecValidationError) as exc:
            validate(spec)
        assert any("forbidden_filename_prefixes" in m for m in exc.value.messages)

    def test_forbidden_prefixes_rejects_empty_string_entry(self) -> None:
        from research_framework.spec.schema import SpecValidationError
        from research_framework.spec.validator import validate

        spec = self._make_spec(forbidden_filename_prefixes=[""])
        with pytest.raises(SpecValidationError) as exc:
            validate(spec)
        assert any("forbidden_filename_prefixes" in m for m in exc.value.messages)

    def test_forbidden_prefixes_rejects_non_string_entry(self) -> None:
        from research_framework.spec.schema import SpecValidationError
        from research_framework.spec.validator import validate

        spec = self._make_spec(forbidden_filename_prefixes=[123])  # type: ignore[list-item]
        with pytest.raises(SpecValidationError) as exc:
            validate(spec)
        assert any("forbidden_filename_prefixes" in m for m in exc.value.messages)

    def test_empty_forbidden_prefixes_passes_validation(self) -> None:
        from research_framework.spec.validator import validate

        spec = self._make_spec(forbidden_filename_prefixes=[])
        validate(spec)

    # --- CoverageCategory.priority -----------------------------------------

    def test_priority_default_is_zero(self) -> None:
        from research_framework.spec.schema import CoverageCategory

        cat = CoverageCategory(name="x", note_type="concept", target_count=1)
        assert cat.priority == 0

    def test_priority_accepts_zero(self) -> None:
        from research_framework.spec.validator import validate

        spec = self._make_spec(category_priority=0)
        validate(spec)

    def test_priority_accepts_one_hundred(self) -> None:
        from research_framework.spec.validator import validate

        spec = self._make_spec(category_priority=100)
        validate(spec)

    def test_priority_rejects_negative(self) -> None:
        from research_framework.spec.schema import SpecValidationError
        from research_framework.spec.validator import validate

        spec = self._make_spec(category_priority=-1)
        with pytest.raises(SpecValidationError) as exc:
            validate(spec)
        assert any("priority" in m for m in exc.value.messages)

    def test_priority_rejects_above_100(self) -> None:
        from research_framework.spec.schema import SpecValidationError
        from research_framework.spec.validator import validate

        spec = self._make_spec(category_priority=101)
        with pytest.raises(SpecValidationError) as exc:
            validate(spec)
        assert any("priority" in m for m in exc.value.messages)
