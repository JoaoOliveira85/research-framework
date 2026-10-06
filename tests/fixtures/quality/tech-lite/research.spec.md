---
name: tech-lite-quality-fixture
owner: research-framework-tests
location: /Users/dev/src/research-framework-022-us3/tests/fixtures/quality/tech-lite
scope:
  domain: >-
    Small Java payment-gateway microservice domain for the spec-022 quality
    harness. Exercises code-derived topic discovery (FR-011).
  organization: Synthetic fixture — not a production vault
  boundaries:
    - Spring Boot services under synthetic/acme/* repos
    - Kafka flows and ADR decisions
    - Shared platform concepts (idempotency, sagas, circuit breakers)
  out_of_scope:
    - Production credentials or real customer data
    - Non-Java stacks
note_types:
  - name: service
    description: Microservice boundary and responsibilities
    folder: "01 - Services"
    required_sections: ["Overview", "API Surface", "Dependencies", "Related"]
    min_word_count: 80
    template_version: "1.0.0"
  - name: flow
    description: End-to-end messaging or HTTP flow
    folder: "02 - Flows"
    required_sections: ["Overview", "Trigger", "Steps", "Failure Modes", "Related"]
    min_word_count: 80
    template_version: "1.0.0"
  - name: concept
    description: Reusable engineering concept
    folder: "03 - Concepts"
    required_sections: ["Overview", "Mechanism", "Trade-offs", "Related"]
    min_word_count: 80
    template_version: "1.0.0"
  - name: decision
    description: Architecture decision record
    folder: "04 - Decisions"
    required_sections: ["Context", "Decision", "Consequences", "Related"]
    min_word_count: 80
    template_version: "1.0.0"
data_sources:
  - name: payment-repo
    type: code
    description: Synthetic payment service repository
    priority: 1
    required: true
  - name: order-repo
    type: code
    description: Synthetic order service repository
    priority: 1
    required: true
search_dimensions: [technical, organizational]
coverage_targets:
  categories:
    - name: services
      note_type: service
      target_count: 6
      met_count: 0
      priority: 95
    - name: flows
      note_type: flow
      target_count: 4
      met_count: 0
      priority: 90
    - name: concepts
      note_type: concept
      target_count: 5
      met_count: 0
      priority: 85
    - name: decisions
      note_type: decision
      target_count: 3
      met_count: 0
      priority: 80
budget:
  max_usd: 25.0
  max_cycles: 3
max_cycles: 3
---

# tech-lite quality fixture

Synthetic Java microservice domain for harness regression tests.
