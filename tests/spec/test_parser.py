"""Tests for src/research_framework/spec/parser.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework.spec.parser import parse
from research_framework.spec.schema import SpecConfig, SpecValidationError


def test_parse_valid_spec(sample_spec_path: Path) -> None:
    spec = parse(sample_spec_path)
    assert isinstance(spec, SpecConfig)
    assert spec.name == "Test Vault"
    assert spec.owner == "Test Author"
    assert len(spec.note_types) == 1
    assert spec.note_types[0].name == "concept"
    assert len(spec.data_sources) == 2
    assert "domain" in spec.search_dimensions
    assert "market" in spec.search_dimensions


def test_parse_missing_file() -> None:
    with pytest.raises(SpecValidationError) as exc:
        parse(Path("/tmp/research_framework-nonexistent-spec.md"))
    assert "spec file not found" in "\n".join(exc.value.messages)


def test_parse_no_frontmatter(tmp_path: Path) -> None:
    bad = tmp_path / "no-fm.md"
    bad.write_text("# Just a Markdown file, no frontmatter\n")
    with pytest.raises(SpecValidationError):
        parse(bad)


def test_parse_malformed_yaml(tmp_path: Path) -> None:
    bad = tmp_path / "bad-yaml.md"
    bad.write_text("---\nname: [unclosed\n---\nbody\n")
    with pytest.raises(SpecValidationError) as exc:
        parse(bad)
    assert "YAML parse error" in "\n".join(exc.value.messages)


def test_parse_malformed_yaml_names_the_line(tmp_path: Path) -> None:
    """The reported line is unchanged by how the frontmatter is split."""
    bad = tmp_path / "bad-yaml.md"
    bad.write_text("---\nname: ok\nowner: [unclosed\n---\nbody\n")
    with pytest.raises(SpecValidationError) as exc:
        parse(bad)
    assert "(line 3)" in "\n".join(exc.value.messages)


def test_dashes_inside_a_frontmatter_line_do_not_end_the_spec(
    tmp_path: Path, sample_spec_path: Path
) -> None:
    """Only a `---` LINE closes the frontmatter.

    The split was on the first `---` substring, so a `# -------` comment rule
    ended the spec there and every field below it was dropped without a word.
    """
    text = sample_spec_path.read_text(encoding="utf-8")
    assert text.startswith("---\nname:")
    ruled = tmp_path / "ruled.md"
    ruled.write_text(
        text.replace("---\nname:", "---\n# ---------- identity ----------\nname:", 1),
        encoding="utf-8",
    )

    assert parse(ruled) == parse(sample_spec_path)


def test_the_shipped_example_spec_loads_whole() -> None:
    """`examples/research.spec.md` separates its sections with comment rules."""
    example = Path(__file__).resolve().parents[2] / "examples" / "research.spec.md"

    spec = parse(example)

    assert spec.name == "Macro Photography on Analog Film"
    assert spec.note_types
    assert spec.data_sources
    assert spec.coverage_targets.categories


# Code-first (feature 002) parser round-trip — inline spec, no file dep on
# the code-first spec fixture.


def test_parses_code_first_fields_inline(tmp_path: Path) -> None:
    spec_file = tmp_path / "code-first.md"
    spec_file.write_text("""---
name: Sample Code-First
location: /tmp/sample
owner: Owner
scope:
  domain: d
  organization: o
  source_of_truth_rules:
    - "Code wins on questions of behaviour."
note_types:
  - name: service
    description: Service profile
    folder: "02 - Services"
    source_policy: hard
  - name: market
    description: Market context
    folder: "09 - Market"
    source_policy: soft
data_sources:
  - name: GitHub repos
    type: internal
    priority: 1
    role: behaviour
    required: true
    access_method: GitHub MCP + local clones
    repos:
      - name: OEHK
        url: https://github.com/acme-corp/oehk-service
        priority_paths: ["README.md", "docs/"]
        ignore_paths: ["target/"]
        owning_team: Platform
        access_method: both
  - name: Confluence
    type: external
    priority: 2
    role: intent
    required: true
    access_method: Atlassian MCP
search_dimensions: [technical, organizational, domain, market, temporal]
coverage_targets:
  categories:
    - name: services
      note_type: service
      target_count: 1
      required: true
budget:
  max_usd: 10.0
  max_cycles: 2
---

# Body
""")
    spec = parse(spec_file)
    # Priority/role round-trip
    assert spec.data_sources[0].priority == 1
    assert spec.data_sources[0].role == "behaviour"
    assert spec.data_sources[1].role == "intent"
    # Repo enumeration parsed
    assert len(spec.data_sources[0].repos) == 1
    assert spec.data_sources[0].repos[0].name == "OEHK"
    assert spec.data_sources[0].repos[0].owning_team == "Platform"
    assert spec.data_sources[0].repos[0].priority_paths == ["README.md", "docs/"]
    # source_policy round-trip
    assert spec.note_types[0].source_policy == "hard"
    assert spec.note_types[1].source_policy == "soft"
    # source_of_truth_rules parsed
    assert len(spec.scope.source_of_truth_rules) == 1
    assert "Code wins" in spec.scope.source_of_truth_rules[0]


def test_parses_authority_and_domain_role_fields_inline(tmp_path: Path) -> None:
    """spec 053 FR-001: note_type authority fields + the `domain` source role
    survive the full markdown-frontmatter → SpecConfig parse path."""
    spec_file = tmp_path / "authority.md"
    spec_file.write_text("""---
name: Journal-First
location: /tmp/journal
owner: Owner
scope:
  domain: d
  organization: o
note_types:
  - name: finding
    description: A domain finding
    folder: "01 - Findings"
    authoritative_role: domain
    authority_section: "## Evidence"
    complementary_section: "## Commentary"
data_sources:
  - name: Journals
    type: external
    priority: 1
    role: domain
    required: true
  - name: Reddit
    type: external
    priority: 3
    role: domain
search_dimensions: [domain, temporal]
coverage_targets:
  categories:
    - name: findings
      note_type: finding
      target_count: 1
budget:
  max_usd: 10.0
  max_cycles: 2
---

# Body
""")
    spec = parse(spec_file)
    # `domain` role parses on every data_source (no behaviour source at all)
    assert [ds.role for ds in spec.data_sources] == ["domain", "domain"]
    assert spec.data_sources[0].priority == 1
    # note_type authority fields parse through the markdown path
    nt = spec.note_types[0]
    assert nt.authoritative_role == "domain"
    assert nt.authority_section == "## Evidence"
    assert nt.complementary_section == "## Commentary"


def test_parses_authored_codebase_vault_spec() -> None:
    """Integration test: load the real codebase-vault-spec.md and check invariants."""
    from research_framework.spec.validator import validate

    # Path resolves relative to the repo root (pytest rootdir).
    spec_path = (
        Path(__file__).parent.parent.parent
        / "tests"
        / "fixtures"
        / "specs"
        / "code-first-vault-spec.md"
    )
    spec = parse(spec_path)
    validate(spec)
    assert spec.name == "Codebase Vault (Code-First)"
    # Primary behaviour source must be first by priority
    assert spec.data_sources[0].name == "GitHub repos"
    assert spec.data_sources[0].priority == 1
    assert spec.data_sources[0].role == "behaviour"
    # Exactly 9 repos enumerated
    assert len(spec.data_sources[0].repos) == 9
    repo_names = {r.name for r in spec.data_sources[0].repos}
    assert repo_names == {
        "CAT",
        "LDG",
        "BAL",
        "CLR",
        "SET",
        "CFG",
        "RPT",
        "ONB",
        "REF",
    }
    # Hard types present with source_policy
    service_type = next(nt for nt in spec.note_types if nt.name == "service")
    assert service_type.resolved_source_policy() == "hard"
    assert "Current Behaviour" in service_type.required_sections
    assert "Stated Intent" in service_type.required_sections
    # Spec 061: a stray `budget.max_usd: 200` in the authored spec parses fine
    # but is NOT honoured (the dollar cap moved to settings.yaml) — exactly like
    # any unknown frontmatter key.
    assert not hasattr(spec.budget, "max_usd")
