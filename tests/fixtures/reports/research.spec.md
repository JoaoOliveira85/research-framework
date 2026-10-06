---
name: digest-fixture-vault
owner: research-framework-tests
scope:
  domain: Minimal vault for spec-035 cross-cycle digest harness.
note_types:
  - name: concept
    folder: "03 - Concepts"
  - name: service
    folder: "01 - Services"
  - name: flow
    folder: "02 - Flows"
data_sources:
  - name: youtube-rss
    type: rss
    priority: 2
  - name: payment-repo
    type: code
    priority: 1
coverage_targets:
  categories:
    - name: concepts
      note_type: concept
      target_count: 5
    - name: services
      note_type: service
      target_count: 4
    - name: flows
      note_type: flow
      target_count: 3
---
