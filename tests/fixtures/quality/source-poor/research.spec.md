---
name: source-poor-quality-fixture
owner: research-framework-tests
location: /Users/dev/src/research-framework-022-us3/tests/fixtures/quality/source-poor
scope:
  domain: >-
    Deliberately under-resourced research spec to exercise gap-pursuit and
    SG-002 diversity gate behaviour (FR-011 gap-pursuit-substitution).
  organization: Synthetic fixture
  boundaries:
    - One reachable wiki source
    - Many ambitious coverage categories
  out_of_scope:
    - Paid corpora without credentials
note_types:
  - name: concept
    description: Concept note
    folder: "01 - Concepts"
    required_sections: ["Overview", "Mechanism", "Trade-offs", "Related"]
    min_word_count: 60
    template_version: "1.0.0"
  - name: service
    description: Service note
    folder: "02 - Services"
    required_sections: ["Overview", "API Surface", "Dependencies", "Related"]
    min_word_count: 60
    template_version: "1.0.0"
  - name: flow
    description: Flow note
    folder: "03 - Flows"
    required_sections: ["Overview", "Trigger", "Steps", "Failure Modes", "Related"]
    min_word_count: 60
    template_version: "1.0.0"
  - name: decision
    description: Decision note
    folder: "04 - Decisions"
    required_sections: ["Context", "Decision", "Consequences", "Related"]
    min_word_count: 60
    template_version: "1.0.0"
data_sources:
  - name: only-wiki
    type: external
    description: Single weak wiki source
    priority: 1
    required: true
search_dimensions: [technical]
coverage_targets:
  categories:
    - name: concepts
      note_type: concept
      target_count: 12
      met_count: 0
      priority: 95
    - name: services
      note_type: service
      target_count: 10
      met_count: 0
      priority: 90
    - name: flows
      note_type: flow
      target_count: 8
      met_count: 0
      priority: 85
    - name: decisions
      note_type: decision
      target_count: 6
      met_count: 0
      priority: 80
    - name: integrations
      note_type: service
      target_count: 5
      met_count: 0
      priority: 75
budget:
  max_usd: 10.0
  max_cycles: 3
max_cycles: 3
---

# source-poor quality fixture
