---
name: Reference Vault
location: ~/Documents/reference-vault
owner: João Pedro Oliveira

scope:
  domain: "computer science and software engineering — concepts, algorithms, data structures, languages, frameworks, architectures, databases, infrastructure, tools, and practices"
  organization: "Personal technical reference (maintained by João Pedro Oliveira)"
  boundaries:
    - "Technology-agnostic CS/SWE concepts (CAP, ACID, concurrency models, consistency, etc.)"
    - "Algorithms and data structures with canonical complexity characteristics"
    - "Design patterns (GoF, enterprise, concurrency, integration, security)"
    - "Programming languages — type systems, paradigms, ecosystems, trade-offs"
    - "Frameworks, libraries, and packages — what they are, when to use, alternatives"
    - "Architectural styles — microservices, event-driven, hexagonal, CQRS, monolith, serverless, etc."
    - "Database technologies — RDBMS, NoSQL families, search engines, caches, time-series"
    - "Protocols and standards — HTTP, gRPC, WebSocket, AMQP, TCP, TLS, RFCs"
    - "Infrastructure and cloud primitives — K8s objects, AWS services, observability"
    - "Developer tools — build systems, package managers, CI/CD, version control, editors"
    - "Engineering practices — TDD, CI/CD, code review, pair programming, agile"
  out_of_scope:
    - "Internal service implementation details (codebase-vault territory)"
    - "Tutorials, how-to guides, or step-by-step walkthroughs (this vault is reference, not pedagogy)"
    - "Personal opinions, hot takes, industry editorial"
    - "Time-sensitive news, release announcements, conference reports"
    - "Company-confidential information from any source"
  contextual_questions:
    - "What is this thing precisely? (Definition, not analogy.)"
    - "What problem does it solve and under what assumptions?"
    - "What are the canonical alternatives and when is each preferred?"
    - "What are the known trade-offs, failure modes, and edge cases?"
    - "What do engineers actually need to know to evaluate whether to use it?"
    - "Where is the authoritative source of truth (spec, paper, official docs)?"

note_types:
  - name: concept
    description: "Abstract CS/SWE ideas and principles — theoretical underpinnings independent of any specific tech"
    folder: "01 - Concepts"
    required_sections: ["Overview", "Key Properties", "Trade-offs", "Examples", "Related"]
    contextual_questions:
      - "What is this concept precisely?"
      - "What problem does it address?"
      - "What are its invariants or defining properties?"
      - "Where does it appear in practice?"
    min_word_count: 200

  - name: algorithm
    description: "Specific algorithms with complexity characteristics and canonical implementations"
    folder: "02 - Algorithms"
    required_sections: ["Overview", "Complexity", "How It Works", "Use Cases", "Variants", "Trade-offs"]
    contextual_questions:
      - "What does this algorithm compute?"
      - "What is the time/space complexity (best, average, worst)?"
      - "What are its preconditions and invariants?"
      - "When is this the right choice vs. alternatives?"
    min_word_count: 200

  - name: data-structure
    description: "Specific data structures — arrays, trees, graphs, bloom filters, skip lists, etc."
    folder: "03 - Data Structures"
    required_sections: ["Overview", "Operations & Complexity", "Implementation Notes", "Use Cases", "Trade-offs"]
    contextual_questions:
      - "What does this data structure represent?"
      - "What operations does it support and at what cost?"
      - "When is its cost profile preferable to alternatives?"
      - "What are common implementation pitfalls?"
    min_word_count: 200

  - name: pattern
    description: "Design patterns — GoF, enterprise, concurrency, integration, security"
    folder: "04 - Patterns"
    required_sections: ["Intent", "Problem", "Solution", "Structure", "Consequences", "Known Uses", "Related Patterns"]
    contextual_questions:
      - "What problem does this pattern solve?"
      - "What is the structure (participants, relationships, responsibilities)?"
      - "What are the consequences (positive and negative)?"
      - "Where is it used in real systems/libraries?"
    min_word_count: 200

  - name: language
    description: "Programming languages — paradigm, type system, ecosystem, trade-offs"
    folder: "05 - Languages"
    required_sections: ["Overview", "Paradigm & Type System", "Key Features", "Ecosystem", "Typical Use Cases", "Trade-offs"]
    contextual_questions:
      - "What paradigm(s) does this language support?"
      - "What is its type system (static/dynamic, strong/weak, structural/nominal)?"
      - "What problems is it designed for?"
      - "What are the main ecosystems, package managers, and build tools?"
    min_word_count: 200

  - name: framework
    description: "Frameworks — Spring, Django, React, Rails, Kafka Streams, etc."
    folder: "06 - Frameworks"
    required_sections: ["Overview", "Core Concepts", "Typical Stack", "Use Cases", "Alternatives", "Trade-offs"]
    contextual_questions:
      - "What problem is this framework designed to solve?"
      - "What are its core abstractions?"
      - "What's the typical application structure?"
      - "What are the main alternatives and when would you choose each?"
    min_word_count: 200

  - name: library
    description: "Libraries and packages — specific dependencies, not frameworks (e.g., Jackson, requests, lodash, pytest)"
    folder: "07 - Libraries"
    required_sections: ["Overview", "API Surface", "Installation", "Common Use Cases", "Alternatives"]
    contextual_questions:
      - "What does this library do?"
      - "What problem does it address that the stdlib doesn't?"
      - "What's its API surface (what are the main entry points)?"
      - "What are the main alternatives?"
    min_word_count: 200

  - name: architecture
    description: "Architectural styles and macro-patterns — microservices, event-driven, hexagonal, CQRS, monolith, serverless, etc."
    folder: "08 - Architectures"
    required_sections: ["Overview", "Motivation", "Structure", "Communication Patterns", "Trade-offs", "When to Use"]
    contextual_questions:
      - "What organizational or technical constraints motivate this style?"
      - "How are components structured and how do they communicate?"
      - "What does it optimize for and what does it sacrifice?"
      - "In what contexts is it a poor fit?"
    min_word_count: 200

  - name: database
    description: "Specific database technologies — PostgreSQL, MySQL, Redis, Cassandra, DynamoDB, Elasticsearch, ClickHouse, etc."
    folder: "09 - Databases"
    required_sections: ["Overview", "Data Model", "Consistency Model", "Indexing", "Use Cases", "Trade-offs"]
    contextual_questions:
      - "What data model does it expose (relational, key-value, document, columnar, graph, time-series)?"
      - "What consistency and availability guarantees does it offer?"
      - "What are its strengths and weaknesses for common workloads?"
      - "What are the main operational concerns?"
    min_word_count: 200

  - name: protocol
    description: "Network, wire, and application protocols — HTTP, gRPC, WebSocket, AMQP, TCP, TLS, OAuth, etc."
    folder: "10 - Protocols"
    required_sections: ["Overview", "Layer", "Message Format", "Security", "Use Cases", "Alternatives"]
    contextual_questions:
      - "What layer does it sit at (OSI-ish)?"
      - "What is its message/frame structure?"
      - "What security properties does it provide (or not)?"
      - "When is it preferred over alternatives?"
    min_word_count: 200

  - name: tool
    description: "Developer tools — Maven, Gradle, Docker, Git, Vim, IntelliJ, pytest, Terraform, etc."
    folder: "11 - Tools"
    required_sections: ["Overview", "Purpose", "Typical Workflow", "Configuration", "Alternatives"]
    contextual_questions:
      - "What problem does this tool solve in a developer's workflow?"
      - "How is it typically invoked and configured?"
      - "What are the main alternatives?"
      - "What does it integrate with?"
    min_word_count: 200

  - name: practice
    description: "Engineering practices and methodologies — TDD, CI/CD, code review, pair programming, agile, DDD, etc."
    folder: "12 - Practices"
    required_sections: ["Overview", "Motivation", "How to Apply", "Common Pitfalls", "Tooling"]
    contextual_questions:
      - "What engineering problem does this practice address?"
      - "What does it actually look like in day-to-day work?"
      - "What are the common failure modes?"
      - "What tooling supports it?"
    min_word_count: 200

  - name: infrastructure
    description: "Infrastructure and cloud primitives — K8s objects, AWS/GCP/Azure services, service meshes, observability stacks"
    folder: "13 - Infrastructure"
    required_sections: ["Overview", "Purpose", "Configuration Surface", "Typical Deployment", "Alternatives"]
    contextual_questions:
      - "What infrastructure role does this play?"
      - "What's its configuration model (declarative/imperative)?"
      - "How does it compose with adjacent infra primitives?"
      - "What are the main alternatives?"
    min_word_count: 200

  - name: moc
    description: "Map of Content — index notes that route into each major area of the vault"
    folder: "00 - MOC"
    required_sections: ["Overview", "Index"]
    contextual_questions:
      - "What does this map cover?"
      - "What are the key entry points into this area?"
    min_word_count: 0

data_sources:
  - name: "Codebase Vault Seed"
    type: internal
    description: "Harvest the starting tech stack from ~/Documents/codebase-vault (scripts, configs, CLAUDE.md, service notes). Used only in Cycle 1 to seed the backlog with technologies the team actually uses. Do NOT copy codebase-vault content into this vault."
    required: true
    access_method: "local filesystem"

  - name: "GitHub"
    type: external
    description: "Public GitHub repositories — official project repos, their READMEs, ADRs, and design docs. Expand outward to the projects behind the frameworks/libraries/tools discovered."
    required: true
    access_method: "GitHub MCP"

  - name: "Official Documentation"
    type: external
    description: "Canonical vendor documentation for the technologies being documented (e.g., docs.oracle.com/java, spring.io/projects, kafka.apache.org, postgresql.org/docs). Authoritative source of truth for each note's citations."
    required: true
    access_method: "web fetch"

  - name: "Web"
    type: external
    description: "General web — reference material from reputable sources (Wikipedia for CS fundamentals, academic papers, RFCs, canonical books, well-cited engineering blogs). Always prefer primary sources; use blog posts only for practical context, never as the sole citation."
    required: true
    access_method: "web fetch"

search_dimensions: ["technical", "organizational", "domain", "market", "temporal"]

coverage_targets:
  categories:
    - name: concepts
      note_type: concept
      target_count: 250
      met_count: 0
      required: true
    - name: algorithms
      note_type: algorithm
      target_count: 150
      met_count: 0
      required: true
    - name: data-structures
      note_type: data-structure
      target_count: 100
      met_count: 0
      required: true
    - name: patterns
      note_type: pattern
      target_count: 200
      met_count: 0
      required: true
    - name: languages
      note_type: language
      target_count: 80
      met_count: 0
      required: true
    - name: frameworks
      note_type: framework
      target_count: 200
      met_count: 0
      required: true
    - name: libraries
      note_type: library
      target_count: 250
      met_count: 0
      required: true
    - name: architectures
      note_type: architecture
      target_count: 100
      met_count: 0
      required: true
    - name: databases
      note_type: database
      target_count: 100
      met_count: 0
      required: true
    - name: protocols
      note_type: protocol
      target_count: 80
      met_count: 0
      required: true
    - name: tools
      note_type: tool
      target_count: 150
      met_count: 0
      required: true
    - name: practices
      note_type: practice
      target_count: 100
      met_count: 0
      required: true
    - name: infrastructure
      note_type: infrastructure
      target_count: 100
      met_count: 0
      required: true
    - name: mocs
      note_type: moc
      target_count: 40
      met_count: 0
      required: false

# Target total: ~1,900 notes — book-scale coverage across all categories.
# At typical per-note cost (~$0.10 for research+write), full population is ~$200+.
# The $150 cap below WILL trip Condition C (budget) before Condition B (no new topics).
# This is intentional: the vault grows across multiple `research-vault generate --resume` passes,
# each topping up the budget. Use `research-vault coverage` between runs to see gaps.

budget:
  max_usd: 10.0
  max_cycles: 20
  warn_at_pct: 0.8

max_cycles: 20
naming_convention: full_name
jira_project: null
access_modes: ["claude-code", "obsidian"]
---

# Reference Vault — Specification

## What this vault is

A personal technical reference covering computer science and software engineering concepts
— from fundamentals (algorithms, data structures, patterns) through to the specific
technologies (languages, frameworks, libraries, databases, protocols, tools, infrastructure)
used in practice. Reference material, not tutorial material. Self-contained notes that a
reader can consult without additional context.

**Scope ambition**: book-scale. Target total is ~1,900 notes — enough combined depth to
support writing multiple technical books drawn from the vault (e.g., one on distributed
systems, one on language theory, one on SRE practices). Each note is a reference entry of
200–500 words; they compose into book-length treatments via the MOC and wikilink graph.

## Seeding strategy

Cycle 1 harvests the starting set of technologies from `~/Documents/codebase-vault`:
- `scripts/` — Python deps, test frameworks, linters
- `vault-config.yaml` — declared stack
- `CLAUDE.md` — build/test commands, standards
- Service notes in `data_vault/02 - Services/` — tech stacks listed in frontmatter
  (`tech_stack` field) for each internal service

From that seed, the scout identifies:
1. Canonical projects behind each technology (e.g., "Spring" → spring-projects/spring-framework)
2. The language ecosystem behind each (Java → JVM, JDK, Maven, Gradle, JUnit, …)
3. Peer technologies commonly compared (PostgreSQL → MySQL, MariaDB; Kafka → Pulsar, RabbitMQ)
4. Fundamental concepts referenced in the docs (pub-sub → event-driven → CQRS → eventual consistency)

Cycle 2+ expands breadth-first from those seeds via GitHub, official docs, and general web.

## Strict separation from codebase-vault

This vault must NEVER contain:
- Team structure, ownership, or organizational context
- Any content that identifies how the team specifically uses a given technology

If a tech note needs an example, use canonical public examples (Netflix using Cassandra,
Discord using Elixir, etc.) — never internal ones.

## Quality bar for this vault

Beyond the generic quality bar in CLAUDE.md, notes in this vault must also satisfy:

- **Primary source in citations**: At least one `source_urls` entry MUST be from the
  official project documentation, spec, or canonical paper/book. Blog posts and
  engineering-blog links may supplement but never stand alone.
- **Version-specific claims marked as such**: If a claim depends on a specific version
  (e.g., "Java records were added in Java 14"), state the version explicitly.
- **No opinion language**: "best", "worst", "always use X" are prohibited. Use "preferred
  when", "typical trade-off", "canonical alternative" instead.
- **Named alternatives**: Every note (except `moc`) must name at least one alternative or
  related technology in the "Trade-offs" or "Alternatives" section.

## Termination conditions

The vault is considered complete when ALL of:

- Every coverage target in `coverage_targets.categories` is met
- `validate_vault.py` exits 0
- `check_template_compliance.py` exits 0
- `check_acronym_links.py` exits 0
- Every note has at least one primary-source citation
- Cycle scout reports 0 new topics not already covered

## Budget

- Hard cap per run: **$250 USD**
- Max cycles per run: **20**
- Warn at 80% consumed

### Budget vs. scope — intentional reality check

Book-scale coverage (~1,900 notes) at typical per-note cost is ~$200+ of model spend.
**$150 will not hit all coverage targets in a single run.** The design handles this:

1. Cycle 1–N runs until `cumulative_cost_usd ≥ $150` → `validate_cycle.py` exits 1
   (Condition C: budget cap).
2. `research-vault coverage` reports which categories are unmet and by how much.
3. You top up: edit `budget.max_usd` in the spec, then
   `research-vault generate --spec reference-vault-spec.md --resume` re-enters Phase 2 targeting
   the unmet categories.
4. Repeat until `research-vault coverage` shows all targets met. Phase 3 (index rebuild +
   git init + report) runs only after coverage is complete.

Expected total spend across all runs: **$300–$500** to fully populate to the targets
above. Up to you whether to commit to that up front or grow the vault over time.

## Generation command

```bash
# First run
research-vault generate --spec reference-vault-spec.md --output ~/Documents/reference-vault

# Check progress
research-vault coverage --vault ~/Documents/reference-vault

# Resume after budget top-up (edit spec's budget.max_usd, then:)
research-vault generate --spec reference-vault-spec.md --output ~/Documents/reference-vault --resume
```
