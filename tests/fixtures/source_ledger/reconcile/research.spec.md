---
name: source-ledger-fixture
owner: research-framework-tests
location: /tmp/source-ledger-fixture
scope:
  domain: Synthetic vault for source_ledger.py verdict tests
  organization: Tests
  boundaries:
    - Fixture-only
  out_of_scope: []
note_types:
  - name: concept
    description: Concept note
    folder: "03 - Concepts"
    required_sections: ["Overview", "Related"]
    min_word_count: 40
    template_version: "1.0.0"
data_sources:
  - name: GitHub Pull Requests
    type: code
    role: behaviour
    description: Primary code behaviour source
    priority: 1
    required: true
  - name: Product Confluence Space
    type: external
    role: intent
    description: Intent and roadmap documentation
    priority: 2
    required: true
  - name: Industry RSS Feed
    type: external
    role: domain
    description: Domain context feed
    priority: 3
    required: false
  - name: Optional Blog Archive
    type: external
    role: domain
    description: Optional supplementary domain source
    priority: 4
    required: false
search_dimensions: [technical]
coverage_targets:
  categories:
    - name: concepts
      note_type: concept
      target_count: 1
      met_count: 0
      priority: 90
---