---
name: source-rich-quality-fixture
owner: research-framework-tests
location: /Users/dev/src/research-framework-022-us3/tests/fixtures/quality/source-rich
scope:
  domain: >-
    Curated high-quality sources with comfortable coverage targets for
    source-quality-pruning regression (FR-011).
  organization: Synthetic fixture
  boundaries:
    - Official docs, papers, and org repos
  out_of_scope:
    - Low-signal scraper feeds
note_types:
  - name: service
    description: Service note
    folder: "01 - Services"
    required_sections: ["Overview", "API Surface", "Dependencies", "Related"]
    min_word_count: 60
    template_version: "1.0.0"
  - name: flow
    description: Flow note
    folder: "02 - Flows"
    required_sections: ["Overview", "Trigger", "Steps", "Failure Modes", "Related"]
    min_word_count: 60
    template_version: "1.0.0"
  - name: concept
    description: Concept note
    folder: "03 - Concepts"
    required_sections: ["Overview", "Mechanism", "Trade-offs", "Related"]
    min_word_count: 60
    template_version: "1.0.0"
  - name: decision
    description: Decision note
    folder: "04 - Decisions"
    required_sections: ["Context", "Decision", "Consequences", "Related"]
    min_word_count: 60
    template_version: "1.0.0"
data_sources:
  - name: official-docs
    type: external
    description: Curated official documentation
    priority: 1
    required: true
  - name: oreilly-shelf
    type: external
    description: Curated O'Reilly excerpts
    priority: 1
    required: true
  - name: arxiv-feed
    type: external
    description: Curated arXiv feed
    priority: 2
    required: true
  - name: github-org
    type: code
    description: Curated GitHub organization
    priority: 1
    required: true
  - name: confluence-space
    type: external
    description: Curated Confluence space
    priority: 2
    required: true
search_dimensions: [technical, organizational, domain]
coverage_targets:
  categories:
    - name: services
      note_type: service
      target_count: 4
      met_count: 0
      priority: 95
    - name: flows
      note_type: flow
      target_count: 3
      met_count: 0
      priority: 90
    - name: concepts
      note_type: concept
      target_count: 3
      met_count: 0
      priority: 85
    - name: decisions
      note_type: decision
      target_count: 2
      met_count: 0
      priority: 80
    - name: integrations
      note_type: service
      target_count: 2
      met_count: 0
      priority: 75
budget:
  max_usd: 40.0
  max_cycles: 3
max_cycles: 3
---

# source-rich quality fixture
