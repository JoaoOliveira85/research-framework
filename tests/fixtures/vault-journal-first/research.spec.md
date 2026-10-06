---
name: Journal-First Authority Fixture
location: /tmp/vault-journal-first
owner: Fixture Author
scope:
  domain: machine learning research
  organization: independent
note_types:
  - name: finding
    description: A research finding grounded in the literature
    folder: "01 - Findings"
    source_policy: hard
    authoritative_role: domain
data_sources:
  - name: Journals
    type: external
    priority: 1
    role: domain
    required: true
    access_method: RSS + arXiv feeds
  - name: Reddit
    type: external
    priority: 3
    role: domain
    access_method: subreddit RSS
search_dimensions: [technical, organizational, domain, market, temporal]
coverage_targets:
  categories:
    - name: findings
      note_type: finding
      target_count: 1
      required: true
budget:
  max_usd: 10.0
  max_cycles: 2
---

# Journal-First Authority Fixture

Fixture spec for spec 053 US2 — the plasticity proof. There is **no behaviour
source**: the derived trunk is `Journals` (minimum `priority` 1, `role: domain`),
`Reddit` is a lower-priority domain branch. The same three gates that enforce a
code-first vault must enforce here — grounding demands the authoritative
**domain** role, and the trunk-seed gate must NOT require code/behaviour (the
pure-domain `if signatures:` guard). No per-topic config; authority is declared.
