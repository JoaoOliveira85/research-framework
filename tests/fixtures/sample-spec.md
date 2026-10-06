---
name: Test Vault
location: /tmp/research_framework-test-vault
owner: Test Author
scope:
  domain: "testing, fixture data"
  organization: "Speckit test suite"
  boundaries:
    - "Test-only content"
  out_of_scope:
    - "Production data"
  contextual_questions:
    - "Why does this fixture exist?"
    - "Who maintains it?"
note_types:
  - name: concept
    description: "Abstract concepts and terminology"
    folder: "01 - Concepts"
    required_sections: ["Overview", "Key Details", "Relationships"]
    contextual_questions:
      - "What is this concept?"
      - "How does it relate to others?"
    min_word_count: 200
data_sources:
  - name: "Internal Wiki"
    type: internal
    description: "Company documentation"
    required: true
    access_method: "web"
  - name: "External Web"
    type: external
    description: "Public web content"
    required: true
    access_method: "web"
search_dimensions: ["technical", "organizational", "domain", "market", "temporal"]
coverage_targets:
  categories:
    - name: concepts
      note_type: concept
      target_count: 5
      met_count: 0
      required: true
    - name: secondary-concepts
      note_type: concept
      target_count: 3
      met_count: 0
      required: true
budget:
  max_usd: 5.0
  max_cycles: 2
  warn_at_pct: 0.8
max_cycles: 2
naming_convention: full_name
access_modes: ["claude-code"]
---

# Test Vault Specification

This is a minimal valid vault spec used for end-to-end generator tests. It defines one
note type (concept), two data sources (one internal, one external, both required), all
five search dimensions, two coverage categories, and a small budget.
