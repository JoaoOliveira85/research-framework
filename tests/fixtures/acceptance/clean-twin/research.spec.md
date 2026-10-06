---
name: rc1-codebase-snapshot
owner: research-framework-tests
location: /tmp/rc1-codebase-snapshot
scope:
  domain: Synthetic snapshot reproducing the codebase-vault rc1 off-script findings
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
    description: Primary code behaviour source (the derived trunk).
    priority: 1
    required: true
    repos:
      - org: acme-corp
        url: https://github.com/acme-corp/oebh-service
  - name: Product Confluence Space
    type: external
    role: intent
    description: Intent and roadmap documentation.
    priority: 2
    required: true
    url: https://confluence.example.com
search_dimensions: [technical]
coverage_targets:
  categories:
    - name: concepts
      note_type: concept
      target_count: 4
      met_count: 2
      priority: 90
---
