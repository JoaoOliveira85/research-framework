# Feature Specification: Vault Quality Fix

**Feature Branch**: `017-vault-quality-fix`
**Created**: 2026-05-15
**Status**: **SHIPPED 0.2.30 (2026-05-15) — partial.** The quality-fix
slice that motivated the spec landed in 0.2.30: phase-scoped
`sources_consulted` validation (ADR-0002), correction directives
injected into prompts (ADR-0003), and the carry-over of ten ruff
errors that were finally retired in 0.2.33's baseline reset. The
spec's broader "quality" framing was effectively superseded by spec
022 (E2E Quality Harness, SHIPPED 0.3.0) — the measurement
infrastructure 022 brought is the durable answer to "is the reference
vault any good?". Treat 017's "what's still pending" sections as
historical: anything still relevant has been absorbed into 022 or
queued under spec 030 (Quality Harness v3).
**Input**: Post-mortem of the reference_vault_v3 trial run; vault quality audit results; lessons from 016 spec; agent feedback from install assistant session

## Context

The reference_vault_v3 trial run (2026-05-15) consumed ~3 hours of generation time and produced a vault that fails the quality audit on 5 of 7 gates. Of 292 target notes across 13 categories, only 52 were generated — and those 52 are concentrated in business-specific folders (Flows: 17, Concepts: 15, Services: 8, Decisions: 7) while the core learning folders the user explicitly prioritized are completely empty (Learning Modules: 0, Java/JVM: 0, APIs/Protocols: 0, Architecture Patterns: 0, Testing Practices: 0, Security Practices: 0, Tools: 0).

The vault is unusable in its current state. This spec defines what must change in the framework, the pipeline, and the vault spec to produce a result that passes the quality audit and actually serves the user's stated goals.

### Forensic Analysis of the Trial Run

The trial ran 6 cycles (5 complete). The budget log shows:

| Cycle | Notes Created | Cumulative |
|-------|--------------|------------|
| 1     | 18           | 18         |
| 2     | 6            | 24         |
| 3     | 6            | 30         |
| 4     | 12           | 42         |
| 5     | 9            | 51         |
| 6     | (incomplete) | 52         |

**~10 notes/cycle average.** With 292 targets, the vault would need ~30 cycles at this rate — far beyond the 10-cycle budget. But the low yield isn't the real problem. The real problem is *what* the pipeline chose to write about.

### Root Cause 1: The Scout Extracts Internal Names Instead of Generalizable Knowledge

This **was** a code-derived vault — the spec explicitly listed 8 local repositories as primary sources alongside Hyperskill, official docs, and O'Reilly. The repos are full of Spring Boot patterns, Cassandra modeling, hexagonal architecture, Testcontainers setups, Kafka consumer patterns, and repository-port abstractions. A competent human scanning those same repos would produce notes titled "Repository Port Pattern", "Hexagonal Architecture in Spring", "Cassandra Partition Key Design", "Kafka Consumer Group Management", "Component Testing with Testcontainers" — reusable engineering knowledge extracted from concrete implementations.

Instead, the scout extracted **internal class and flow names verbatim**: `oms_cassandra_component_test_harness`, `erp_general_settings_kafka_topic_bundle`, `oehk_customer_order_eviction_producer_toggle`, `pim_composite_key_find_all_by_id_downside`. Every single one of the 52 notes is named after a service-specific internal artifact. Not one note generalizes the pattern behind the implementation.

The scout prompt's Step 1 says "extract the service it describes, every ADR file, every Kafka topic, every domain term referenced in 2+ files." This instruction produces an inventory of *what exists in the code* — not an extraction of *what engineering knowledge the code represents*. The prompt never asks "what general concept, pattern, or technique does this code exemplify?" It never says "for each Spring feature you observe in the code, create a note about the feature, not the specific usage."

The scout also has no step that consults the spec's coverage targets, the Hyperskill curriculum, or any external documentation. Topics are derived exclusively from code artifact names. The output's `topics_found.new` field was **empty in all 6 cycles** because the prompt doesn't populate it — only `topics_from_code` gets filled. The note-writer then reads `topics_found.new` (empty) and falls back to `topics_from_code`, producing only internal-name notes.

**Result:** All 52 notes are internal service documentation, not reusable engineering knowledge. 7/13 categories are empty because the scout has no mechanism to derive topics at the right abstraction level — neither from code analysis nor from external sources. The repos contained all the raw material for hundreds of generalizable notes, but the pipeline could only see class names.

### Root Cause 2: No Shared Research Plan Connects Agents Across Cycles

Each cycle is structurally independent: scout → note-writer → harvest → repeat. There is no persistent document that says "here is what the vault should look like when complete, here is what we have, here is what to do next." The closest thing is `research-backlog.md` (populated by topic_harvest.py from orphan wikilinks), but this is reactive — it only captures wikilinks to notes that *already exist*, not topics that *should exist* but don't.

The coverage targets in `coverage-targets.json` are checked by the orchestrator for loop termination, but they are **never injected into the scout or note-writer prompts**. The agents don't know what the coverage gaps are. They don't know what priority the user assigned to each category. They just walk repos and write about what they find.

**Result:** No convergence toward the stated goal. The pipeline does work, but it's rudderless work. Each cycle rediscovers similar code topics because the scout's input doesn't change between cycles (same repos, same prompt structure). The topic harvester adds orphan wikilinks to the backlog, but these are all code-derived orphans ("customer_bet_risk_service", "customer_order_calculator_service") — never learning-oriented topics.

### Root Cause 3: Low Notes-Per-Cycle Throughput

10 notes per cycle is low for a vault with 292 targets. The note-writer agent gets one invocation per cycle and writes until it decides to stop. There is no mechanism to tell it "you have budget for 30 notes this cycle" or "continue until you've filled these categories." The agent self-limits based on the scout report's topic list, which contains ~15-20 code-derived topics per cycle. After writing 10, it stops — likely hitting context limits or the agent's own completion heuristics.

**Result:** Even if topic selection were correct, 10 notes/cycle × 10 max_cycles = 100 notes maximum — only 34% of the 292 target. The pipeline structurally cannot reach its own targets at current throughput.

### Root Cause 4: No Scope Guard Against Out-of-Scope Content

The spec's `out_of_scope` says "Product-specific business rules, confidential operational details." But a significant portion of the 52 generated notes are highly business-specific: `erp_bet_overlay_processor_impl.md`, `oms_cumulative_stakes_eviction_by_event_flow.md`, `oehk_customer_order_eviction_producer_toggle.md`. These are internal service implementation details, not reusable engineering knowledge. The note-writer is told to "generalize" but in practice, the notes are tightly coupled to specific service internals.

**Result:** Notes that the user describes as "electronic trash" — they don't accelerate learning and they're not reusable as onboarding material.

### Root Cause 5: Missing Infrastructure (Index Files, Templates, MOCs)

Index files (`_index.md`, `_concepts.md`, `_graph.md`) are scaffolded at vault root (should be inside `data_vault/`) and never populated. The `data_vault/_templates/` directory is missing. No MOC (Map of Content) notes are generated. These are all symptoms of the pipeline having no post-generation finalization step.

### Summary of Structural Failures

| Failure | Layer | Impact |
|---------|-------|--------|
| Scout only pulls from code repos | Prompt template | 7/13 categories permanently empty |
| No research plan shared between agents | Architecture | No convergence toward coverage targets |
| Coverage targets not injected into agent prompts | Orchestrator → Prompt gap | Agents unaware of what's needed |
| Low throughput (~10 notes/cycle) | Agent invocation | Cannot reach targets within budget |
| No scope-guard on generated content | Note-writer prompt | Out-of-scope notes consume budget |
| No post-generation finalization | Pipeline lifecycle | Empty indexes, missing templates, no MOCs |
| No source preflight | Pipeline lifecycle | Wasted hours on unreachable sources |
| O'Reilly collector tool-name mismatch | Collector code | Silent zero-result failures |

## Clarifications

### Session 2026-05-15

- Q: Who generates `_pipeline/research-plan.md` — deterministic Python, an LLM/agent step, or a hybrid? → A: Hybrid — Python computes the prioritized queue and exclusions deterministically; an agent writes only a short narrative "focus rationale" header on top.
- Q: How does the pipeline reach ≥ 25 notes per cycle? → A: Multiple sequential note-writer invocations per cycle, each given a small batch (5–8 topics) from the cycle's assigned list; orchestrator enforces the quota and runs mid-cycle gates between batches.
- Q: What survives a cycle that FAILs and is retried? → A: Incremental retry — keep notes already accepted by per-step gates (SG-004, SG-005); the retry only re-runs the remaining batches with a correction directive, never rewriting accepted notes. The batch is the commit boundary.
- Q: How does the new research plan relate to the existing `topic_harvest.py` / `research-backlog.md`? → A: Keep `topic_harvest.py` as an upstream input feeder. The research-plan generator consumes `research-backlog.md` (orphan wikilinks) as one input alongside coverage gaps, spec scope, and persistent rejects, then merges them into a single prioritized queue with the exclusion list applied. The plan is the single source of truth for "what to do next"; the backlog remains the source of truth for "harvested orphan wikilinks."
- Q: Is the service-prefix list (`oms_`, `wms_`, `pim_`, `erp_`, `oebh_`, `oecdh_`, `oehk_`, `cms_`) hardcoded into the abstraction gate, or configurable per vault? → A: Configurable per vault. The spec gains a `forbidden_filename_prefixes` field that the abstraction gates (SG-003, CG-003, SC-009) read at runtime. Default is empty for new vaults; the reference_vault_v3 spec MUST be updated to declare the eight known prefixes.

## User Scenarios & Testing

### User Story 1 - A persistent research plan drives all agents toward the same goal (Priority: P0)

The pipeline must maintain a **research plan** — a living document that captures what the vault should contain, what it currently has, what to do next, and in what order. This plan is updated after each cycle and injected into both the scout and note-writer prompts. It replaces the current approach where agents are structurally disconnected and have no shared context.

The research plan should contain:
- The spec's coverage targets with current fill rates (e.g., "spring-feature: 1/36")
- A prioritized topic queue derived from coverage gaps, the spec's scope, and harvested followups
- An explicit "this cycle, focus on these N topics" instruction
- A "do NOT write about" list (already-covered topics, out-of-scope items, persistent rejects)

**Why this priority**: This is the root structural failure. Without a shared plan, the scout walks repos, the note-writer writes about whatever it finds, and coverage targets are never consulted. No other fix matters if agents don't know what they're supposed to produce.

**Independent Test**: After 3 cycles, notes are distributed across ≥ 8 categories (not concentrated in 4–5).

**Acceptance Scenarios**:

1. **Given** a fresh vault with 13 categories, **When** the research plan is generated before cycle 1, **Then** it lists coverage gaps for all 13 categories with priority ordering.
2. **Given** the plan says "this cycle: spring-feature, java-jvm, concept", **When** the note-writer runs, **Then** ≥ 70% of notes created belong to those 3 categories.
3. **Given** cycle 1 produced 18 notes, **When** cycle 2's plan is generated, **Then** it reflects the 18 notes as covered and adjusts priorities for remaining gaps.
4. **Given** the plan lists "out of scope: product-specific business rules", **When** the note-writer creates a note, **Then** the note does not describe internal service implementation details that are not generalizable.

---

### User Story 2 - The scout extracts generalizable knowledge, not internal artifact names (Priority: P0)

The scout must operate at the right abstraction level. When it walks a codebase and finds `CassandraTestContainersLauncherExtension`, the topic should be "Component Testing with Testcontainers" (a testing-practice note), not `oms_cassandra_component_test_harness` (an internal class reference). When it finds a `DualWritingRepositoryAdapter`, the topic should be "Dual-Write Pattern for Storage Migration" (an architecture-pattern note), not `oms_primary_database_resolver` (a toggle name).

The scout should:
1. **Start from coverage gaps**: Read `coverage-targets.json` and identify which categories are most under-filled.
2. **Derive generalizable topics from code**: For each code artifact, ask "what engineering concept, pattern, or technique does this exemplify?" and emit a topic at that abstraction level. A Kafka consumer class → "Kafka Consumer Patterns"; a hexagonal port interface → "Hexagonal Architecture / Ports and Adapters"; a `@Bean` vs `@Component` choice → "Spring Bean Registration Strategies."
3. **Derive topics from external sources**: For under-filled categories without code exemplars (e.g., Learning Modules, Security Practices), consult the spec's scope, Hyperskill curriculum, and official docs.
4. **Populate `topics_found.new`**: The scout's output MUST populate `topics_found.new` with generalized topic titles — this is the field the note-writer reads. `topics_from_code` remains as a supplementary provenance field linking generalized topics back to their source artifacts.

The spec's `source_of_truth_rules` already say "code in the local repositories is the authoritative source of truth" for *behaviour*, while official documentation is authoritative for *semantics*. The scout should use code to discover *what patterns are in play* and then write notes about those patterns citing both code examples and official docs.

**Why this priority**: The repos contain the raw material for hundreds of generalizable notes across all 13 categories. The problem isn't source availability — it's that the scout can only see class names, not the concepts they implement. A `KafkaParallelConsumerAdapter` class should produce notes about "Parallel Consumers in Kafka", "Consumer Group Rebalancing", "Backpressure Handling" — not a note called `kafka_parallel_consumer_adapter`.

**Independent Test**: After cycle 1's scout runs (scout-output stage, before any notes are written), fewer than 20% of `topics_found.new` entries match any prefix in the spec's `forbidden_filename_prefixes` field (for reference_vault_v3 this is the set `oms_, wms_, pim_, erp_, oebh_, oecdh_, oehk_, cms_`; for vaults that do not declare the field, this gate is reported as N/A and does not fail). Equivalently, ≥ 80% of scout-proposed topics are named after engineering concepts.

**Acceptance Scenarios**:

1. **Given** the scout walks `oms-service` and finds `CassandraTestContainersLauncherExtension`, **When** it emits a topic, **Then** the topic is titled "Component Testing with Testcontainers" (type: testing-practice), not `oms_cassandra_component_test_harness`.
2. **Given** the scout walks repos and finds hexagonal port interfaces, **When** it emits topics, **Then** at least one topic is "Hexagonal Architecture / Ports and Adapters" (type: architecture-pattern) with `source_file` pointing to the concrete port class.
3. **Given** the spec has coverage targets for 13 categories, **When** the scout runs cycle 1, **Then** `topics_found.new` contains at least 20 topics spanning at least 8 categories.
4. **Given** the spec lists "Hyperskill Java Backend Developer (Spring Boot)" as a data source and "Learning Modules" has 0 notes, **When** the scout runs, **Then** it proposes at least 5 learning-module topics derived from the curriculum outline in the spec.

---

### User Story 3 - Regenerate a usable reference vault from the existing spec (Priority: P1)

The user wants to regenerate the reference vault so that it primarily contains Spring Boot, Java/JVM, SQL/JPA, testing, security, architecture, and API notes from the Hyperskill curriculum and official documentation — not business-specific service internals. Business-specific content (services, flows, decisions derived from team repos) should be a secondary enrichment pass, not the primary output.

**Why this priority**: The entire point of the vault is to accelerate learning; an empty vault with only business-specific notes defeats the purpose.

**Independent Test**: Run the vault quality audit protocol (all 7 gates) against the regenerated vault.

**Acceptance Scenarios**:

1. **Given** a regenerated vault, **When** `vault_metrics.py` runs, **Then** at least 10 of 13 categories contain notes, and no required category has 0 notes.
2. **Given** a regenerated vault, **When** `validate_vault.py` runs, **Then** it exits 0 with zero violations.
3. **Given** a regenerated vault, **When** the wikilink audit runs, **Then** average wikilinks/note ≥ 4.0 and dead wikilinks ≤ 10%.
4. **Given** a regenerated vault, **When** index files are inspected, **Then** `_index.md`, `_concepts.md`, and `_graph.md` list all notes with summaries.

---

### User Story 4 - Notes-per-cycle throughput reaches 25+ (Priority: P1)

The pipeline should produce at least 25 notes per cycle, not the current ~10. This requires either: (a) the note-writer being given a larger explicit topic list per cycle, (b) multiple note-writer invocations per cycle, or (c) the note-writer being told its per-cycle quota. At 25 notes/cycle, the vault reaches 250 notes in 10 cycles — covering 85% of the 292 target.

**Why this priority**: At ~10 notes/cycle, the pipeline structurally cannot reach its targets within the 10-cycle budget. This makes the budget and coverage targets meaningless.

**Independent Test**: Run 3 cycles and confirm ≥ 75 total notes created.

**Acceptance Scenarios**:

1. **Given** a fresh vault with 292 coverage targets, **When** cycle 1 completes, **Then** at least 25 notes are created.
2. **Given** the research plan assigns 30 topics to a cycle, **When** the note-writer runs, **Then** it attempts all 30 (some may be deferred if quality can't be met, but it doesn't stop at 10).

---

### User Story 5 - Source preflight prevents wasted runs (Priority: P2)

Before the pipeline starts generating notes, it should validate that all required sources are accessible: local repository paths exist, `gh auth status` succeeds, web-fetch URLs are reachable, and the O'Reilly collector's MCP tool name is correct.

**Why this priority**: The trial run burned 3 hours and tokens before anyone noticed that source connectivity was degraded. A 30-second preflight would have caught this.

**Independent Test**: Run the preflight check with a deliberately broken source (e.g., non-existent repo path) and confirm it fails with a clear error before any generation starts.

**Acceptance Scenarios**:

1. **Given** a spec with a local repo path that doesn't exist, **When** preflight runs, **Then** it exits non-zero and names the missing path.
2. **Given** a spec with GitHub PR sources, **When** `gh auth status` fails, **Then** preflight warns (non-fatal) and notes that PR-derived content will be skipped.
3. **Given** a spec with O'Reilly sources, **When** the collector is tested with a dry-run query, **Then** preflight confirms the MCP tool name resolves correctly.

---

### User Story 6 - Post-generation reindex populates index files (Priority: P2)

After note generation completes, the pipeline should automatically run a reindex step that populates `_index.md`, `_concepts.md`, and `_graph.md` with actual vault content.

**Why this priority**: Empty index files make the vault un-navigable in Obsidian and fail the Gate 6 quality audit.

**Independent Test**: Generate a vault with 10+ notes and confirm all three index files contain entries referencing those notes.

**Acceptance Scenarios**:

1. **Given** a vault with 50+ notes, **When** reindex runs, **Then** `_index.md` lists every note grouped by folder with title and summary.
2. **Given** a vault with 50+ notes, **When** reindex runs, **Then** `_concepts.md` contains quick-lookup definitions for the most important terms.
3. **Given** a vault with 50+ notes, **When** reindex runs, **Then** `_graph.md` maps relationships between notes in meaningful groups.

---

### User Story 7 - Index files live inside data_vault (Priority: P3)

The `_index.md`, `_concepts.md`, and `_graph.md` files should be generated inside `data_vault/` (or whatever the corpus directory is named), not at the vault root. This keeps the corpus self-contained and navigable as a single Obsidian vault.

**Why this priority**: Currently these files sit at the vault root, separate from the corpus. This breaks Obsidian navigation and the user's expectation that the data vault is the complete knowledge base.

**Independent Test**: After generation, confirm index files are inside `data_vault/` and not at the vault root.

**Acceptance Scenarios**:

1. **Given** a freshly generated vault, **When** the user opens `data_vault/` in Obsidian, **Then** `_index.md`, `_concepts.md`, and `_graph.md` appear at the top of the file list.

---

### User Story 8 - Template directory is generated for compliance checking (Priority: P3)

The vault scaffold should include `data_vault/_templates/` with the note-type templates defined in the spec, so that `check_template_compliance.py` can validate notes against them.

**Why this priority**: Without the templates directory, compliance checking is impossible and Gate 1 of the quality audit always fails.

**Independent Test**: Run `check_template_compliance.py data_vault/` and confirm it exits 0 (or reports only content violations, not missing templates).

**Acceptance Scenarios**:

1. **Given** a scaffolded vault, **When** `check_template_compliance.py data_vault/` is run, **Then** it does not error with "template directory not found".

### User Story 9 - Deterministic quality gates enforce minimum standards between steps and cycles (Priority: P0)

The pipeline must have **code-enforced, deterministic guardrails** that run between every pipeline step and between every cycle. These are not agent judgments — they are Python scripts that read the vault state, compute quantitative metrics, and either PASS (continue), WARN (continue but log), or FAIL (halt and demand correction before proceeding).

The purpose is to make it **structurally impossible** for the pipeline to produce the trial run's outcome: 6 cycles of drift with no correction, 7 empty categories, 100% internal-artifact content, and zero convergence toward targets.

#### 9a. Per-Cycle Quantitative Gates (deterministic, code-enforced)

These run after each cycle's note-writer completes, before the orchestrator decides whether to continue:

| Gate ID | Metric | Computation | Threshold | Action on Fail |
|---------|--------|-------------|-----------|----------------|
| CG-001 | **Notes created this cycle** | `len(report.notes_created)` | ≥ `ceil(remaining_targets / remaining_cycles)` | WARN if < 50% of expected; FAIL if 0 |
| CG-002 | **Category spread** | `len(set(note.coverage_category for note in cycle_notes))` | ≥ `min(5, unfilled_categories)` | WARN if < 3; FAIL if 1 (single-category cycle) |
| CG-003 | **Abstraction check** | `count(notes whose filename matches any prefix in spec.forbidden_filename_prefixes) / total_notes` (reported as N/A if the spec does not declare the field) | ≤ 30% of cycle's notes match a forbidden prefix | WARN if > 30%; FAIL if > 60% (skipped when N/A) |
| CG-004 | **Coverage velocity** | `(met_count_after - met_count_before) / expected_per_cycle` | ≥ 0.5 (at least half of expected progress) | WARN if < 0.5; FAIL if 0 (zero progress on any target category) |
| CG-005 | **Cumulative coverage trajectory** | project `met_count / target_count` at current rate to `max_cycles` | projected final fill ≥ 70% | WARN if projected < 70%; accelerate (increase per-cycle quota) |
| CG-006 | **Word count compliance** | `count(notes below min_word_count) / total_notes` | ≤ 10% below minimum | WARN if > 10%; FAIL if > 30% |
| CG-007 | **Orphan wikilink ratio** | `dead_wikilinks / total_wikilinks` | ≤ 20% | WARN if > 20%; logged for next-cycle correction |

**How "expected per cycle" works (CG-001):** Before cycle N, compute `remaining = total_target - met_count` and `remaining_cycles = max_cycles - (N - 1)`. The minimum expected yield is `ceil(remaining / remaining_cycles)`. If the vault has 292 targets, 0 met, and 10 max_cycles, cycle 1's minimum is `ceil(292/10) = 30`. If after cycle 3 only 60 are met, cycle 4's minimum is `ceil(232/7) = 34`. The system becomes more aggressive as it falls behind — exactly as requested.

**What happens on FAIL:** The orchestrator does NOT proceed to the next cycle. Instead, it:
1. Logs the failing gate(s) with specific numbers.
2. Re-renders the scout and note-writer prompts with a **correction directive**: "Previous cycle failed gate CG-002 (single-category cycle). This cycle MUST produce notes in at least 5 categories. Categories with 0 notes: [list]."
3. Re-runs the cycle (up to 2 retries per cycle, then ABORT with a full diagnostic report).

#### 9b. Per-Step Gates (between scout and note-writer within a cycle)

| Gate ID | When | Metric | Threshold | Action |
|---------|------|--------|-----------|--------|
| SG-001 | After scout | `len(topics_found.new)` | ≥ per-cycle quota | FAIL if 0; WARN if < quota (scout didn't find enough) |
| SG-002 | After scout | Category diversity of `topics_found.new` | ≥ `min(5, unfilled_categories)` | FAIL if all topics are same category |
| SG-003 | After scout | Abstraction check on topic titles against `spec.forbidden_filename_prefixes` (reported as N/A if the spec does not declare the field) | ≤ 20% titles match a forbidden prefix | WARN if > 20%; re-prompt scout with correction (skipped when N/A) |
| SG-004 | After note-writer | `validate_vault.py` findings | 0 | **FAIL** on a `duplicate` violation (constitutional Principle VI); WARN on any other non-zero exit and log violations for next cycle — *amended 2026-09-06, issue #293; see note below* |
| SG-005 | After note-writer | Frontmatter completeness | 100% of notes have all required fields | FAIL if any note missing `coverage_category`, `source_urls`, or `summary` |

> **SG-004 amendment (2026-09-06, issue #293).** The original row mapped *every*
> non-zero `validate_vault.py` exit to WARN. Only a FAIL drives the correction
> loop, so a **duplicate note** — a violation of constitutional Principle VI,
> which is non-negotiable and whose only other enforcement is a pre-write check
> on an optional scout field — was detected, logged, and written anyway. SG-004
> now separates "the vault has duplicate notes" (FAIL, with a correction hint)
> from "validate_vault reported something" (WARN, unchanged). The deliberate
> soft default this row records still governs the style/hygiene findings it was
> written for; it never covered a constitutional violation. Spec 019's FR-013 /
> FR-014 (`settings.yaml::gates.sg004.mode`, a *settings-driven* hard mode for
> all findings) remain **deferred** — this amendment is narrower and needs no
> new setting.

#### 9c. Mid-Cycle Progress Tracking (for long cycles)

For the note-writer specifically, if the orchestrator supports progress checkpoints:
- At 50% of the assigned topic list: check how many notes are actually written. If < 40% of assigned topics, inject a "you're behind pace — prioritize breadth over depth for remaining topics" correction.
- Track which assigned topics were skipped and why. "Skipped: couldn't find sources" is acceptable; "skipped: decided to write a different topic instead" is a gate violation.

#### 9d. Queryability Probes (qualitative, agent-assisted but structured)

After each cycle, run a set of **probe queries** against the vault — questions the vault should be able to answer given its current content. These are not free-form; they are deterministically generated from the spec:

1. **Coverage probes**: For each note type with ≥ 5 notes, generate a question from that type's `contextual_questions`. Example: the spec says spring-feature notes should answer "What is Spring doing under the hood here?" → probe: "What does Spring's ApplicationContext do under the hood?" If the vault can't answer it (no note matches), that's a coverage gap signal.

2. **Cross-reference probes**: Pick 3 random notes and check: "Can I navigate from this note to a related concept using wikilinks?" If the link graph is disconnected (islands of notes with no cross-links), that's a structure quality signal.

3. **Findability probes**: Pick a topic from the spec's `boundaries` list and search the vault by keyword. If zero hits, the vault has a findability gap. Example: spec says "Cassandra concepts and migration concerns" is in scope → search vault for "Cassandra" → if 0 notes mention it, flag.

These probes produce a **queryability score** (0–100%) per cycle: `(probes_answered / total_probes) * 100`. The score is logged and tracked across cycles — it should monotonically increase. If it plateaus or drops, the research plan is failing.

#### 9e. Trajectory Dashboard (per-cycle summary)

After each cycle, the pipeline writes `_pipeline/cycles/cycle-NNN-quality-report.json`:

```json
{
  "cycle": 3,
  "gates": {
    "CG-001": {"status": "PASS", "value": 28, "threshold": 26, "note": "exceeded minimum"},
    "CG-002": {"status": "PASS", "value": 7, "threshold": 5},
    "CG-003": {"status": "WARN", "value": 0.35, "threshold": 0.30, "note": "slightly over abstraction limit"},
    "CG-004": {"status": "PASS", "value": 0.8, "threshold": 0.5},
    "CG-005": {"status": "PASS", "projected_fill": 0.85, "threshold": 0.70},
    "CG-006": {"status": "PASS", "value": 0.04, "threshold": 0.10},
    "CG-007": {"status": "WARN", "value": 0.22, "threshold": 0.20}
  },
  "coverage_snapshot": {
    "concepts": {"target": 40, "met": 12, "fill_pct": 0.30},
    "spring-features": {"target": 36, "met": 8, "fill_pct": 0.22}
  },
  "queryability_score": 0.65,
  "trajectory": "on-track"
}
```

This file is **deterministic** — no agent judgment, just computed metrics. A human or CI system can read it and know exactly where the vault stands.

**Why this priority**: Without deterministic gates, the pipeline is a hope-driven system. The trial run proved that agents left unsupervised will produce 6 cycles of drift without self-correcting. Code-enforced gates make bad outcomes structurally impossible — if the scout produces zero topics_found.new, the pipeline stops and demands a fix instead of blindly continuing for 3 hours.

**Independent Test**: Artificially create a cycle that produces 0 notes (mock the note-writer). Confirm the CG-001 gate catches it, logs the failure, and prevents the orchestrator from moving to the next cycle.

**Acceptance Scenarios**:

1. **Given** a cycle that produces notes in only 1 category, **When** gate CG-002 runs, **Then** it returns FAIL and the orchestrator re-runs the cycle with a correction directive.
2. **Given** after cycle 3 the cumulative notes are 30 (vs expected 90), **When** gate CG-005 runs, **Then** it computes projected fill < 70%, returns WARN, and increases the per-cycle quota for cycle 4.
3. **Given** the scout produces `topics_found.new` with 0 entries, **When** gate SG-001 runs, **Then** it returns FAIL and the cycle does not proceed to the note-writer.
4. **Given** 5 queryability probes, **When** the vault answers 3/5, **Then** the queryability score is 60%, logged, and compared to previous cycles.
5. **Given** cycle N-1 had queryability score 40% and cycle N has score 38%, **When** trajectory analysis runs, **Then** it flags a plateau/regression and recommends specific coverage gaps to address.

---

### Edge Cases

- What happens when the budget runs out mid-category? The pipeline should checkpoint and report which categories are under-filled so the user can `--resume` with a top-up budget.
- What happens when a source is unreachable during generation (not just preflight)? The pipeline should log the failure, skip that source, and continue with remaining sources — not silently produce empty results.
- What happens when the spec has more coverage targets than the budget can fill in one pass? The pipeline should prioritize by the spec's category ordering and fill the most important categories first.
- What happens when a code artifact doesn't map cleanly to a general concept? The scout should still attempt generalization (e.g., `erp_general_settings_kafka_topic_bundle` → "Kafka Topic Configuration Patterns") and tag ambiguous mappings for the note-writer to refine. It should never emit the internal class name as the topic title.
- What happens when the same general concept appears in multiple repos? The scout should deduplicate — one topic "Repository Port Pattern" backed by source references from multiple repos, not 8 service-specific copies.

## Requirements

### Functional Requirements

- **FR-001**: The pipeline MUST generate and maintain a **research plan** (`_pipeline/research-plan.md`) that contains: (a) coverage targets with current fill rates, (b) a prioritized topic queue for the next cycle, (c) an explicit per-cycle focus list, and (d) an exclusion list of already-covered and out-of-scope items. This plan MUST be updated after every cycle. Plan generation is **hybrid**: a deterministic Python step computes (a)–(d) from coverage state, the spec, the existing `research-backlog.md` (produced by `topic_harvest.py`), and persistent rejects; an agent step then prepends only a short narrative "focus rationale" header explaining the cycle's priorities. The deterministic body is the source of truth for downstream agents — the narrative header is advisory and MUST NOT alter the priority queue, focus list, or exclusion list. The existing `topic_harvest.py` stage is **kept** as an upstream input feeder: it continues to write `research-backlog.md` (orphan-wikilink capture), and the research-plan generator consumes that file rather than re-implementing orphan harvesting. The research plan is the single source of truth for "what to do next"; `research-backlog.md` remains the source of truth for "harvested orphan wikilinks."
- **FR-002**: The research plan MUST be injected into both the scout and note-writer prompts so that every agent invocation has full context of what the vault needs, what it has, and what to do next.
- **FR-003**: The scout prompt MUST extract topics at the **generalizable engineering concept** level, not at the internal artifact name level. When code contains `CassandraTestContainersLauncherExtension`, the topic is "Component Testing with Testcontainers", not the class name. The scout prompt MUST include a step that asks "what pattern, concept, or technique does this code exemplify?" for each code artifact.
- **FR-004**: The scout's output MUST populate `topics_found.new` with generalized topic titles as its primary topic list. `topics_from_code` remains as a provenance/traceability field. The note-writer reads `topics_found.new` — if it's empty, the note-writer has nothing to work on. For categories without code exemplars, the scout MUST derive topics from the spec's scope, curriculum references, and external documentation sources.
- **FR-005**: The pipeline MUST support a `priority` field on coverage target categories. Categories with higher priority MUST be filled before lower-priority categories when budget is constrained.
- **FR-006**: The pipeline MUST reach a per-cycle quota of ≥ 25 notes by issuing **multiple sequential note-writer invocations per cycle**, each given a small batch of 5–8 topics by default (configurable per vault via `pipeline.note_writer_batch_size` in `settings.yaml`, clamped to [3, 10] hard bounds) drawn in priority order from the cycle's assigned topic list. The orchestrator (not the agent) is responsible for enforcing the cycle quota: it continues invoking the note-writer until the quota is met or the assigned list is exhausted. Mid-cycle quality gates (Story 9c) MUST run between batches, and a correction directive from a between-batch gate MUST be injected into the next batch's prompt without aborting the cycle.
- **FR-007**: The pipeline MUST run a source preflight check before starting generation, validating local paths exist, GitHub auth works (if PR sources are configured), and collector tool names resolve.
- **FR-008**: The pipeline MUST run a reindex step after note generation that populates `_index.md`, `_concepts.md`, and `_graph.md` with content from all generated notes.
- **FR-009**: The vault scaffold MUST generate `data_vault/_templates/` containing templates for each note type defined in the spec.
- **FR-010**: Index files (`_index.md`, `_concepts.md`, `_graph.md`) MUST be placed inside the corpus directory (`data_vault/`), not at the vault root.
- **FR-011**: The pipeline MUST NOT generate notes for topics explicitly listed in the spec's `out_of_scope` section. The note-writer prompt MUST contain the out-of-scope list.
- **FR-012**: Every wikilink in a generated note MUST either resolve to an existing note OR be captured by `topic_harvest.py` at cycle tail (per the constitution's Stub-as-Fuel mechanism, Principle VIII) and surfaced in `_pipeline/research-backlog.md` as orphan fuel for the next cycle. The note-writer MUST NOT silently emit dangling wikilinks; the cycle-tail harvest is the authoritative capture path. (No new active "stub-creation during note-writing" code path is required — the existing harvester is the constitutionally-endorsed mechanism.)
- **FR-013**: The pipeline MUST produce notes that meet the `min_word_count` specified per note type in the spec. Vaults that want a higher floor for `source_policy: hard` note types (e.g., 500+ words for concept/decision/service/flow) MUST encode that floor by setting `min_word_count` in the spec for those note types. The framework does not impose a separate aspirational threshold — `min_word_count` is the single source of truth and is enforced by gate CG-006.
- **FR-014**: The pipeline MUST checkpoint progress after each cycle so that `--resume` can continue from where it left off without regenerating existing notes.
- **FR-015**: The O'Reilly collector MUST use the correct MCP tool name (`search_oreilly_content`) and fail loudly with a non-zero exit code if the tool is not found.
- **FR-016**: The pipeline MUST run **deterministic quality gates** (Python scripts, no agent judgment) after every scout output and after every note-writer cycle. Gate results are PASS/WARN/FAIL with numeric values and thresholds.
- **FR-017**: The orchestrator MUST compute a **per-cycle minimum yield** as `ceil(remaining_targets / remaining_cycles)` and use it as the CG-001 threshold. This value increases as the pipeline falls behind, making the system progressively more aggressive.
- **FR-018**: On gate FAIL, the orchestrator MUST NOT proceed to the next cycle. It MUST re-render prompts with a correction directive citing the specific failing gate(s) and re-run the cycle **incrementally** (up to 2 retries, then ABORT). Incremental retry rules:
    - Notes already written this cycle that passed per-step gates SG-004 and SG-005 are **kept on disk** and **count toward `met_count`** — they are not rewritten or discarded.
    - The retry re-runs only the **remaining batches** of the cycle's topic assignment, with the correction directive injected into the next batch's prompt.
    - The retry MAY append additional topics to the remaining batch list (drawn from the research plan's priority queue) if the original assignment is exhausted but the cycle quota / failing gate still requires more notes.
    - Harvest backlog updates and `coverage-targets.json` updates from accepted batches are **not rolled back**; subsequent batches build on the updated state.
    - The batch is the cycle's commit boundary: a batch is either fully accepted (notes kept, state advanced) or fully rejected by SG-004/SG-005 (notes discarded, state untouched). Cycle-level gates (CG-xxx) never roll back accepted batches.
    - On ABORT (after 2 retries), all accepted notes from the cycle remain on disk and `--resume` (FR-014) MUST treat them as completed work.
- **FR-019**: After each cycle, the pipeline MUST write a `cycle-NNN-quality-report.json` containing all gate results, coverage snapshot, queryability score, and trajectory assessment. This file is deterministic and machine-readable.
- **FR-020**: The pipeline MUST run **queryability probes** after each cycle — structured questions derived from the spec's `contextual_questions` and `boundaries` — and compute a queryability score (0–100%). This score MUST be logged and MUST monotonically increase (or flag a regression).
- **FR-021**: The scout gate SG-001 MUST FAIL the cycle if `topics_found.new` is empty. Zero topics means zero useful output — the pipeline must not proceed to note-writing with no topics.
- **FR-022**: The per-step gate SG-003 MUST check that ≤ 20% of scout-proposed topic titles match any prefix declared in the spec's `forbidden_filename_prefixes` field. If > 20%, the scout MUST be re-prompted with a correction directive before proceeding to note-writing. The gate MUST be reported as N/A (and not block the cycle) when the spec does not declare `forbidden_filename_prefixes` or declares it empty. The same prefix list MUST also drive the cycle gate CG-003 and the success criterion SC-009 — gates and criteria MUST NOT hardcode prefixes in code.
- **FR-023**: Coverage velocity (CG-004) MUST track per-category progress, not just aggregate. A cycle that produces 30 notes all in one category scores 0 on unfilled categories — the gate catches this even if total throughput is high.

### Key Entities

- **Research Plan**: A living document (`_pipeline/research-plan.md`) generated before each cycle that tells agents what the vault needs, what it has, what to do next, and what to avoid. It is the connective tissue between the orchestrator, the scout, and the note-writer — the "string connecting every action." Authored as a hybrid: the prioritized queue, focus list, and exclusion list are produced deterministically by Python; an agent contributes only a short narrative "focus rationale" header that frames the cycle's priorities for downstream agents but cannot change the deterministic body. Inputs to the deterministic step include coverage state, the spec, **`research-backlog.md` (produced by the existing `topic_harvest.py` stage as an upstream feeder)**, and persistent rejects.
- **Quality Gate**: A deterministic Python check (no agent involvement) that runs between pipeline steps or cycles. Each gate has an ID (CG-xxx for cycle gates, SG-xxx for step gates), a numeric metric, a threshold, and a PASS/WARN/FAIL result. Gates are the "immune system" of the pipeline — they catch drift before it compounds.
- **Per-Cycle Minimum Yield**: Computed as `ceil(remaining_targets / remaining_cycles)`. Starts at ~30 for a 292-target, 10-cycle vault. Increases automatically when the pipeline falls behind, forcing progressively more aggressive catch-up.
- **Cycle Quality Report**: A JSON file (`cycle-NNN-quality-report.json`) containing all gate results, coverage snapshot, queryability score, and trajectory assessment. Deterministic, machine-readable, no agent judgment.
- **Queryability Probe**: A structured question derived from the spec's `contextual_questions` and `boundaries` that tests whether the vault can answer it. Probes produce a 0–100% score per cycle. The score must monotonically increase.
- **Correction Directive**: When a gate FAILs, the orchestrator injects specific instructions into the next cycle's prompts: "Previous cycle failed gate CG-002. This cycle MUST produce notes in at least 5 categories. Categories with 0 notes: [list]."
- **Coverage Target**: A category from the spec with a `target_count`, `met_count`, `priority`, and fill rate that determines what the research plan prioritizes.
- **Source Preflight Result**: A pass/fail/warn status for each configured data source, checked before the pipeline starts generating notes.
- **Reindex Output**: The three index files populated from vault content, generated as the final pipeline step.
- **Forbidden Filename Prefixes**: A vault-specific list of filename prefixes (declared in the vault's `research.spec.md` as `forbidden_filename_prefixes`) that the abstraction gates SG-003, CG-003, and the success criterion SC-009 use to detect notes named after internal artifacts rather than engineering concepts. Default is empty (gate reports N/A and does not fail). The reference_vault_v3 spec declares `[oms_, wms_, pim_, erp_, oebh_, oecdh_, oehk_, cms_]`. Gate implementations MUST read this list from the spec at runtime and MUST NOT hardcode prefixes in framework code.
- **Per-Cycle Topic Assignment**: A list of 25+ topics assigned to the note-writer for a single cycle, derived from the research plan's priority queue. Consumed in **batches of 5–8 topics per note-writer invocation**, with the orchestrator issuing successive invocations until the cycle quota is met or the list is exhausted.
- **Note-Writer Batch**: A single note-writer invocation scoped to 5–8 topics from the per-cycle assignment. Batches are the unit at which mid-cycle quality gates (Story 9c) run and at which correction directives can be injected without restarting the cycle. The batch is also the **commit boundary** for incremental retries (FR-018): a batch's notes are either fully accepted (kept on disk, counted toward `met_count`) or fully rejected by per-step gates (discarded, state untouched). Cycle-level gate FAILs never roll back already-accepted batches.

## Success Criteria

### Measurable Outcomes

- **SC-001**: The regenerated vault passes Gates 1–4 of the vault quality audit protocol (structural integrity, coverage, frontmatter quality, wikilink network) with zero blocking failures.
- **SC-002**: At least 10 of 13 note-type categories contain notes after the first full pipeline run.
- **SC-003**: Average content depth across a 10-note sample scores ≥ 9.0 on the Gate 5 rubric of `vault_audit.py` (precision + depth + cross-referencing + source authority + self-containedness). This is a Phase 3 (post-finalization) human-judgment criterion verified by the user against the audit output, not an automated per-cycle gate; the framework's role is to make this achievable (via the abstraction gates, batched note-writer, and quality reports), not to automate the rubric scoring.
- **SC-004**: The pipeline produces ≥ 25 notes per cycle (up from ~10).
- **SC-005**: The top 5 priority categories (spring-feature, concept, java-jvm, data-store, learning-module) each reach ≥ 50% of their target count in the first pipeline pass.
- **SC-006**: Zero notes are generated for topics listed in the spec's `out_of_scope` section.
- **SC-007**: The vault can answer at least 4 of 5 queryability questions from the Gate 7 audit using only vault content.
- **SC-008**: After every cycle, the research plan (`_pipeline/research-plan.md`) accurately reflects current coverage state and assigns next-cycle topics accordingly.
- **SC-009**: Fewer than 20% of generated notes (post-generation, by vault filename) have filenames matching any prefix declared in the spec's `forbidden_filename_prefixes` field (for reference_vault_v3 this set is `oms_, wms_, pim_, erp_, oebh_, oecdh_, oehk_, cms_`; vaults that do not declare the field treat this criterion as N/A). Equivalently, ≥ 80% of generated note filenames are named after engineering concepts, patterns, or techniques rather than internal artifact names.
- **SC-010**: Every cycle produces a `cycle-NNN-quality-report.json` with all gate results. No cycle completes with a FAIL-status gate unresolved (either the gate was retried and passed, or the pipeline ABORTed with diagnostics).
- **SC-011**: The queryability score monotonically increases across cycles (each cycle ≥ previous cycle's score, or flags a regression). Final score after all cycles ≥ 70%.
- **SC-012**: The per-cycle minimum yield (`ceil(remaining / remaining_cycles)`) is computed and enforced — no cycle produces fewer notes than 50% of this value without triggering a correction cycle.
- **SC-013**: Gate SG-001 catches and prevents any cycle where the scout produces 0 entries in `topics_found.new` — the trial run's 6 cycles of zero-topics-found is structurally impossible under the new gates.

## Acceptance coverage

Backfilled per spec 024 FR-013 (ADR-0008). Maps each user story to shipped
tests where a dedicated file exists; end-to-end vault regeneration rows
use historical references.

| User Story | Evidence |
|------------|----------|
| US1 — A persistent research plan drives all agents toward the same goal | `tests/pipeline/test_research_plan.py` + `tests/pipeline/test_research_plan_contract.py` + `tests/pipeline/test_research_plan_integration.py` |
| US2 — The scout extracts generalizable knowledge, not internal artifact names | `tests/scripts/test_check_abstraction.py` + `tests/pipeline/test_gates_step_sg003.py` + `tests/pipeline/test_merge_scout_topics.py` |
| US3 — Regenerate a usable reference vault from the existing spec | `tests/scripts/test_validate_vault.py` + `tests/scripts/test_vault_audit.py` |
| US4 — Notes-per-cycle throughput reaches 25+ | `tests/pipeline/test_batch.py` + `tests/pipeline/test_batch_orchestration.py` |
| US5 — Source preflight prevents wasted runs | `tests/scripts/test_preflight_sources.py` + `tests/pipeline/test_preflight.py` |
| US6 — Post-generation reindex populates index files | `tests/pipeline/test_reindex_at_cycle_end.py` |
| US7 — Index files live inside data_vault | _(historical — see CHANGELOG.md [0.2.27] scaffold/index placement; covered by generator + `tests/pipeline/test_reindex_at_cycle_end.py`)_ |
| US8 — Template directory is generated for compliance checking | `tests/scripts/test_check_template_compliance.py` + `tests/scripts/test_check_template_compliance_with_dir.py` |
| US9 — Deterministic quality gates enforce minimum standards between steps and cycles | `tests/scripts/test_quality_report.py` + `tests/pipeline/test_gates.py` + `tests/pipeline/test_gates_cycle.py` + `tests/pipeline/test_quality_report.py` |

## Assumptions

- The existing research.spec.md in reference_vault_v3 is structurally valid and its note-type taxonomy, coverage targets, and source configuration are sound — the problem is pipeline execution, not spec authoring.
- The framework bundle at `~/Documents/research-vault-0.2.17` is the baseline for fixes; changes will be applied there or in the framework source at `~/src/research-framework`.
- The user is willing to run a second generation pass after fixes are applied; the vault will be regenerated, not manually repaired note-by-note.
- The O'Reilly collector fix (tool name mismatch) has already been applied in the trial session and should be carried forward.
- The `collect_oreilly.py` script fix from the trial session (changing `search-oreilly-content` to `search_oreilly_content`) is already committed or will be committed as part of this spec's implementation.
- The 015a–d pre-requisites are not blocking this work — this spec addresses pipeline-level quality issues that exist regardless of the framework consolidation effort.
- The vault spec schema (`research.spec.md`) is extended in this feature to support a new `forbidden_filename_prefixes` field; the reference_vault_v3 spec MUST be updated to declare the eight known service prefixes so the abstraction gates produce meaningful results for that vault. Vaults that do not declare the field continue to work — the abstraction gates report N/A and never fail.
















