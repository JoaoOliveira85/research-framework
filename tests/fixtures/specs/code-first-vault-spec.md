---
name: Codebase Vault (Code-First)
location: ~/Documents/codebase-vault-v2
owner: João Pedro Oliveira

scope:
  domain: "Acme Corp Platform team — business logic, services, flows, decisions, risks, org context, products, market"
  organization: "Acme Corp — Platform team"
  source_of_truth_rules:
    - "Code wins on questions of current behaviour (authoritative source is the repository)."
    - "Confluence wins on questions of stated intent and original motivation."
    - "When code and intent disagree, the note records both and flags the drift via `intent_implementation_drift: true`."
  boundaries:
    - "Platform-owned services (CAT, LDG, BAL, CLR, SET, CFG, RPT, ONB, plus reference-lookup-tool)"
    - "Upstream producers and downstream consumers of those services (as referenced in code)"
    - "Domain concepts referenced 2+ times across Platform repos"
  out_of_scope:
    - "Programming languages, frameworks, libraries (reference-vault territory)"
    - "Tutorials or how-to walkthroughs"
    - "Confluence pages with no matching code topic"
    - "Personal opinions / industry editorial"
  contextual_questions:
    - "What does the code actually do? (current behaviour)"
    - "Why does this exist? (stated intent, decision context)"
    - "Who owns it? Who uses it? Who changed it last?"
    - "Does current behaviour match stated intent? If not, where do they diverge?"

data_sources:
  - name: "GitHub repos"
    type: internal
    priority: 1
    role: behaviour
    description: "Platform-owned and adjacent repos. Primary source of truth for services, flows, events, DTOs, configs, ADRs."
    required: true
    access_method: "GitHub MCP + local clones at ~/acme-corp/backend/"
    repos:
      - name: CAT
        url: https://github.com/acme-corp/catalogue-service
        priority_paths: ["README.md", "docs/", "src/main/resources/application.yml", "src/main/java/**/config/"]
        ignore_paths: ["target/", "build/", "generated/", ".gradle/"]
        owning_team: Platform
        access_method: both
        local_path: ~/acme-corp/backend/catalogue-service
      - name: LDG
        url: https://github.com/acme-corp/ledger-service
        priority_paths: ["README.md", "docs/", "src/main/resources/application.yml", "src/main/java/**/config/"]
        ignore_paths: ["target/", "build/", "generated/", ".gradle/"]
        owning_team: Platform
        access_method: both
        local_path: ~/acme-corp/backend/ledger-service
      - name: BAL
        url: https://github.com/acme-corp/balance-service
        priority_paths: ["README.md", "docs/", "src/main/resources/application.yml", "src/main/java/**/config/"]
        ignore_paths: ["target/", "build/", "generated/", ".gradle/"]
        owning_team: Platform
        access_method: both
        local_path: ~/acme-corp/backend/balance-service
      - name: CLR
        url: https://github.com/acme-corp/clearing-service
        priority_paths: ["README.md", "docs/", "src/main/resources/application.yml", "src/main/java/**/config/"]
        ignore_paths: ["target/", "build/", "generated/", ".gradle/"]
        owning_team: Platform
        access_method: both
        local_path: ~/acme-corp/backend/clearing-service
      - name: SET
        url: https://github.com/acme-corp/settlement-service
        priority_paths: ["README.md", "docs/", "src/main/resources/application.yml", "src/main/java/**/config/"]
        ignore_paths: ["target/", "build/", "generated/", ".gradle/"]
        owning_team: Platform
        access_method: both
        local_path: ~/acme-corp/backend/settlement-service
      - name: CFG
        url: https://github.com/acme-corp/config-service
        priority_paths: ["README.md", "docs/", "src/main/resources/application.yml", "src/main/java/**/config/"]
        ignore_paths: ["target/", "build/", "generated/", ".gradle/"]
        owning_team: Platform
        access_method: both
        local_path: ~/acme-corp/backend/config-service
      - name: RPT
        url: https://github.com/acme-corp/reporting-service
        priority_paths: ["README.md", "docs/", "src/main/resources/application.yml", "src/main/java/**/config/"]
        ignore_paths: ["target/", "build/", "generated/", ".gradle/"]
        owning_team: Platform
        access_method: both
        local_path: ~/acme-corp/backend/reporting-service
      - name: ONB
        url: https://github.com/acme-corp/onboarding-service
        priority_paths: ["README.md", "docs/", "src/main/resources/application.yml", "src/main/java/**/config/"]
        ignore_paths: ["target/", "build/", "generated/", ".gradle/"]
        owning_team: Platform
        access_method: both
        local_path: ~/acme-corp/backend/onboarding-service
      - name: REF
        url: https://github.com/acme-corp/reference-lookup-tool
        priority_paths: ["README.md", "docs/"]
        ignore_paths: ["target/", "build/", "generated/", ".gradle/"]
        owning_team: Platform
        access_method: both
        local_path: ~/acme-corp/backend/reference-lookup-tool

  - name: "Confluence"
    type: external
    priority: 2
    role: intent
    description: "Used ONLY to answer 'why does this exist' for code topics already surfaced. Never used to discover new topics."
    required: true
    access_method: "Atlassian MCP"

  - name: "Jira (PLAT project)"
    type: external
    priority: 2
    role: intent
    description: "Active-work dimension. Epics and stories show what the team is currently building — concepts referenced here must have notes."
    required: true
    access_method: "Atlassian MCP"

  - name: "Slack"
    type: external
    priority: 3
    role: intent
    description: "Channel archives and pinned messages for discussion context."
    required: false
    access_method: "Slack MCP"

  - name: "Microsoft 365"
    type: external
    priority: 3
    role: intent
    description: "SharePoint + email context."
    required: false
    access_method: "M365 MCP"

  - name: "Web"
    type: external
    priority: 3
    role: domain
    description: "Market and competitor context. Only for note types market, product, process, risk."
    required: true
    access_method: "web fetch"

search_dimensions: [technical, organizational, domain, market, temporal]

note_types:
  - name: service
    description: "Platform-owned or adjacent backend service with an enumerated repo."
    folder: "02 - Services"
    required_sections:
      - "Overview"
      - "Current Behaviour"
      - "Stated Intent"
      - "Dependencies"
      - "Risks"
      - "Why It Matters"
    contextual_questions:
      - "What does this service DO today (from code)?"
      - "What was it ORIGINALLY intended to do (from Confluence/ADRs)?"
      - "Where do current behaviour and stated intent disagree?"
      - "Who owns it? What upstream services call it? What downstream consumers?"
    min_word_count: 200
    source_policy: hard

  - name: flow
    description: "End-to-end data or business flow, usually a chain of services + events."
    folder: "03 - Flows"
    required_sections:
      - "Overview"
      - "Current Behaviour"
      - "Stated Intent"
      - "Trigger"
      - "Outcome"
      - "Failure Modes"
    contextual_questions:
      - "What triggers this flow and what is the outcome?"
      - "Which services participate and in what order?"
      - "What breaks if this flow fails?"
    min_word_count: 200
    source_policy: hard

  - name: concept
    description: "Business or domain term referenced 2+ times in Platform code (class names, package components, shared DTOs, enums)."
    folder: "01 - Concepts"
    required_sections:
      - "Overview"
      - "Where Referenced"
      - "Usage Context"
      - "Related"
    contextual_questions:
      - "Where in the code is this concept defined?"
      - "Which services reference it and how?"
      - "What business question does it answer?"
    min_word_count: 200
    source_policy: hard

  - name: decision
    description: "ADR captured under docs/adr or docs/decisions in any enumerated repo, plus Confluence-recorded decisions with a code parent."
    folder: "06 - Decisions"
    required_sections:
      - "Context"
      - "Decision"
      - "Consequences"
      - "Alternatives"
      - "Status"
    contextual_questions:
      - "What problem triggered this decision?"
      - "What alternatives were considered?"
      - "What are the consequences (positive and negative)?"
    min_word_count: 200
    source_policy: hard

  - name: product
    description: "Customer-facing product or feature."
    folder: "04 - Products"
    required_sections:
      - "Overview"
      - "Customer Usage"
      - "Business Risk"
      - "Related Services"
    contextual_questions:
      - "How do customers actually use this?"
      - "Which services handle it?"
    min_word_count: 200
    source_policy: soft

  - name: team
    description: "Internal team, capability, or pillar relevant to the Platform team."
    folder: "05 - Teams"
    required_sections:
      - "Overview"
      - "Ownership"
      - "Key Contacts"
      - "Interaction Points"
    contextual_questions:
      - "What do they own?"
      - "How do we interact with them?"
      - "What roadmap items affect us?"
    min_word_count: 200
    source_policy: soft

  - name: risk
    description: "A specific risk (security, operational, regulatory, business) relevant to the Platform team."
    folder: "07 - Risks"
    required_sections:
      - "Description"
      - "Likelihood"
      - "Impact"
      - "Mitigation Status"
    contextual_questions:
      - "What caused this risk?"
      - "What's the worst case?"
      - "What mitigation is in place?"
    min_word_count: 200
    source_policy: soft

  - name: process
    description: "Business or engineering process (incident mgmt, deployment, on-call, releases)."
    folder: "08 - Processes"
    required_sections:
      - "Overview"
      - "Steps"
      - "Owners"
      - "Tooling"
    contextual_questions:
      - "Why was this process created?"
      - "Who runs it?"
      - "What breaks if skipped?"
    min_word_count: 200
    source_policy: soft

  - name: market
    description: "Competitor, market segment, or industry context relevant to the Platform team."
    folder: "09 - Market"
    required_sections:
      - "Overview"
      - "Key Players"
      - "Why It Matters"
    contextual_questions:
      - "Who are the players?"
      - "How does this affect our product?"
    min_word_count: 200
    source_policy: soft

  - name: source
    description: "Raw source reference (Confluence page snapshot, Jira epic, doc link) captured verbatim."
    folder: "10 - Sources"
    required_sections:
      - "Source Metadata"
      - "Extracted Content"
    contextual_questions: []
    min_word_count: 0
    source_policy: soft

  - name: moc
    description: "Map of Content — index notes that route into each major area."
    folder: "00 - MOC"
    required_sections:
      - "Overview"
      - "Index"
    contextual_questions: []
    min_word_count: 0
    source_policy: soft

coverage_targets:
  categories:
    - name: services
      note_type: service
      target_count: 9
      required: true
    - name: concepts
      note_type: concept
      target_count: 150
      required: true
    - name: flows
      note_type: flow
      target_count: 30
      required: true
    - name: decisions
      note_type: decision
      target_count: 25
      required: true
    - name: products
      note_type: product
      target_count: 15
      required: true
    - name: teams
      note_type: team
      target_count: 20
      required: true
    - name: risks
      note_type: risk
      target_count: 20
      required: true
    - name: processes
      note_type: process
      target_count: 15
      required: true
    - name: market
      note_type: market
      target_count: 10
      required: true
    - name: mocs
      note_type: moc
      target_count: 12
      required: false

budget:
  max_usd: 200.0
  max_cycles: 5
  warn_at_pct: 0.8

max_cycles: 5
naming_convention: full_name
jira_project: PLAT
access_modes: [claude-code, obsidian]
---

# Codebase Vault — Code-First Specification

## What this vault is

A business knowledge base for the Acme Corp Platform team, grown outward from the team's GitHub
repositories. Code is the authoritative source for how the system behaves; Confluence is
consulted for original intent. Every service, flow, concept, and decision note carries at
least one code citation.

## Build strategy

Cycle 1 walks the 9 enumerated repos (all at `~/acme-corp/backend/`), extracts code
topics (services, ADRs, Kafka topics, REST endpoints, domain terms with ref_count ≥ 2),
then consults Confluence/Jira to attach intent to each surfaced topic.

Coverage targets (`target_count` above) are placeholders; `repo_scan.py` derives the
final expected filename list at Phase 1.

## Budget

Initial run: $200 USD soft cap. Resume runs expected — top up `budget.max_usd` before
each `--resume` invocation. Total projected spend to full coverage: $500–$1,000 across
3–5 runs.

## Termination conditions

Standard speckit — Condition A (max cycles), Condition B (no new topics AND all
dimensions covered AND all required sources consulted), Condition C (budget). TERMINATE
alone does not unlock Phase 3 — coverage targets must also be met.
