---
name: Code-First Authority Fixture
location: /tmp/vault-code-first
owner: Fixture Author
scope:
  domain: backend services
  organization: acme-corp
  source_of_truth_rules:
    - "Code wins on questions of behaviour."
    - "Confluence wins on intent."
note_types:
  - name: service
    description: Service behaviour profile
    folder: "02 - Services"
    source_policy: hard
    authoritative_role: behaviour
    authority_section: "## Current Behaviour"
    complementary_section: "## Stated Intent"
data_sources:
  - name: GitHub repos
    type: internal
    priority: 1
    role: behaviour
    required: true
    access_method: GitHub MCP + local clones
    repos:
      - name: oehk-service
        url: https://github.com/acme-corp/oehk-service
        local_path: /repo/oehk-service
      - name: shared-lib
        url: https://github.com/acme-corp/shared-lib
        local_path: /repo/shared-lib
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

# Code-First Authority Fixture

Fixture spec for spec 053 US1 regression lock (`vault-code-first`). The single
derived trunk is `GitHub repos` (minimum `priority` 1, `role: behaviour`);
`Confluence` is the `intent` branch. `note_type` `service` declares
`authoritative_role: behaviour` + the authority/complementary sections so the
generalized grounding and drift gates resolve identically to the pre-053
hardcoded gates.
