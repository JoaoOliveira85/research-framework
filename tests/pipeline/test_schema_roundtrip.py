"""Round-trip tests for `SpecConfig` extension fields (T006, feature 017).

Per `contracts/spec-extension.schema.md` round-trip rules:

- Empty `forbidden_filename_prefixes` MUST be omitted from serialized output
  to keep specs readable for vaults that don't use the gate.
- `priority == 0` MUST be omitted from serialized `CoverageCategory` output
  (default value omission).
- Both fields MUST round-trip losslessly when present.
"""

from __future__ import annotations

from pathlib import Path

from research_framework.spec.schema import (
    BudgetConfig,
    CoverageCategory,
    CoverageTargets,
    DataSourceConfig,
    NoteTypeConfig,
    ScopeConfig,
    SpecConfig,
)


def _minimal_spec(
    *,
    forbidden_filename_prefixes: list[str] | None = None,
    priorities: list[int] | None = None,
) -> SpecConfig:
    """Build a SpecConfig with the field-permutation under test."""
    cats = []
    n_cats = max(1, len(priorities) if priorities is not None else 1)
    for i in range(n_cats):
        kw: dict = {
            "name": f"cat-{i}",
            "note_type": "concept",
            "target_count": 5,
        }
        if priorities is not None:
            kw["priority"] = priorities[i]
        cats.append(CoverageCategory(**kw))

    kw_spec: dict = {
        "name": "x",
        "location": Path("."),
        "owner": "u",
        "scope": ScopeConfig(domain="d", organization="o"),
        "note_types": [
            NoteTypeConfig(name="concept", description="", folder="concepts/")
        ],
        "data_sources": [DataSourceConfig(name="s", type="external", priority=2)],
        "search_dimensions": ["domain", "market"],
        "coverage_targets": CoverageTargets(categories=cats),
        "budget": BudgetConfig(),
    }
    if forbidden_filename_prefixes is not None:
        kw_spec["forbidden_filename_prefixes"] = forbidden_filename_prefixes
    return SpecConfig(**kw_spec)


# ---------------------------------------------------------------------------
# Omission rules (default values disappear from serialized output)
# ---------------------------------------------------------------------------


class TestForbiddenPrefixesOmission:
    """Empty `forbidden_filename_prefixes` MUST be omitted from to_dict()."""

    def test_default_empty_field_is_omitted(self) -> None:
        spec = _minimal_spec()  # field absent → defaults to []
        d = spec.to_dict()
        assert "forbidden_filename_prefixes" not in d, (
            "default-empty list MUST be omitted from to_dict() to keep "
            "spec frontmatter clean for vaults that don't use the gate "
            "(see contracts/spec-extension.schema.md round-trip rules)"
        )

    def test_explicit_empty_field_is_omitted(self) -> None:
        spec = _minimal_spec(forbidden_filename_prefixes=[])
        d = spec.to_dict()
        assert "forbidden_filename_prefixes" not in d

    def test_non_empty_field_is_present(self) -> None:
        spec = _minimal_spec(forbidden_filename_prefixes=["oms_", "erp_"])
        d = spec.to_dict()
        assert d["forbidden_filename_prefixes"] == ["oms_", "erp_"]


class TestPriorityOmission:
    """`priority == 0` (default) MUST be omitted from CoverageCategory.to_dict()."""

    def test_default_zero_priority_is_omitted(self) -> None:
        cat = CoverageCategory(name="x", note_type="concept", target_count=5)
        d = cat.to_dict()
        assert "priority" not in d, (
            "default-zero priority MUST be omitted from CoverageCategory.to_dict() "
            "(see contracts/spec-extension.schema.md round-trip rules)"
        )

    def test_explicit_zero_priority_is_omitted(self) -> None:
        cat = CoverageCategory(
            name="x", note_type="concept", target_count=5, priority=0
        )
        d = cat.to_dict()
        assert "priority" not in d

    def test_non_zero_priority_is_present(self) -> None:
        cat = CoverageCategory(
            name="x", note_type="concept", target_count=5, priority=85
        )
        d = cat.to_dict()
        assert d["priority"] == 85


# ---------------------------------------------------------------------------
# Lossless round-trip when present
# ---------------------------------------------------------------------------


class TestRoundTripLossless:
    """parse → serialize → parse produces same in-memory state when fields set."""

    def test_forbidden_prefixes_roundtrip(self) -> None:
        original = _minimal_spec(forbidden_filename_prefixes=["oms_", "legacy-"])
        d = original.to_dict()
        restored = SpecConfig.from_dict(d)
        assert restored.forbidden_filename_prefixes == ["oms_", "legacy-"]

    def test_priority_roundtrip(self) -> None:
        original = _minimal_spec(priorities=[90, 20, 0])
        d = original.to_dict()
        restored = SpecConfig.from_dict(d)
        priorities = [c.priority for c in restored.coverage_targets.categories]
        assert priorities == [90, 20, 0]

    def test_combined_roundtrip(self) -> None:
        original = _minimal_spec(
            forbidden_filename_prefixes=["oms_"], priorities=[80, 0]
        )
        d = original.to_dict()
        restored = SpecConfig.from_dict(d)
        assert restored.forbidden_filename_prefixes == ["oms_"]
        assert [c.priority for c in restored.coverage_targets.categories] == [80, 0]

    def test_absent_fields_default_correctly(self) -> None:
        d = _minimal_spec().to_dict()
        # Strip any vestige; ensure restored state matches construction defaults.
        restored = SpecConfig.from_dict(d)
        assert restored.forbidden_filename_prefixes == []
        assert restored.coverage_targets.categories[0].priority == 0
