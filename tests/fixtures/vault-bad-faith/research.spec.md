---
name: Bad-Faith Seeding Fixture
location: /tmp/vault-bad-faith
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
    repos:
      - name: oehk-service
        url: https://github.com/acme-corp/oehk-service
        local_path: /repo/oehk-service
  - name: Confluence
    type: external
    priority: 2
    role: intent
    required: true
---

# Bad-Faith Seeding Fixture

spec 053 US3 (FR-007). The derived trunk is the **code** source `GitHub repos`
(priority 1, behaviour). A bad-faith cycle seeds only from the easier-to-reach
intent source (Confluence) and never reaches the trunk — the accompanying
`cycle-NNN-source-ledger.json` records the trunk `NOT_REACHED` while the intent
branch is `USED`. The trunk-inversion gate must FAIL this.
