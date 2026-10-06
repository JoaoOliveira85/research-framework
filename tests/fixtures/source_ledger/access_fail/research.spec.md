---
name: source-ledger-fixture
owner: research-framework-tests
location: /tmp/source-ledger-fixture
scope:
  domain: Synthetic source ledger fixture
  organization: Tests
  boundaries: []
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
    description: Primary code source
    priority: 1
    required: true
    repos:
      - org: example
        url: https://github.com/example/repo
search_dimensions: [technical]
coverage_targets:
  categories:
    - name: concepts
      note_type: concept
      target_count: 1
      met_count: 0
      priority: 90
---
