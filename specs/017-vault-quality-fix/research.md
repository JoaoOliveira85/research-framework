# Phase 0 Research: Vault Quality Fix

**Feature**: 017-vault-quality-fix
**Spec**: [spec.md](./spec.md)
**Plan**: [plan.md](./plan.md)
**Date**: 2026-05-15

## Purpose

Resolve every unknown left by the spec + clarifications before Phase 1 design begins. Each section follows the **Decision / Rationale / Alternatives considered** format.

The unknowns fall into three buckets:

1. **Deferred clarifications** — items the `/speckit.clarify` session marked Deferred (mid-cycle crash recovery, queryability monotonic tolerance, source-failure threshold during run).
2. **Integration patterns** — how the new modules wire into existing `pipeline/` code (orchestrator, cycle_runner, source_manager, topic_harvest).
3. **Best-practice calibrations** — magic numbers and approaches the spec leaves open (batch size 5–8, narrator token budget, probe scoring approach).

---

## R-001 — Mid-batch crash recovery (write-ahead vs. idempotent replay)

**Decision**: **Idempotent replay using filesystem state as the journal.** No write-ahead log file. The orchestrator on resume rebuilds in-flight cycle state by:

1. Reading `_pipeline/cycles/cycle-NNN-*.json` (research, harvest, quality, batch reports) — whichever exist.
2. Walking `data_vault/` for notes whose frontmatter `lifecycle.created_at_cycle == NNN` to determine which batches successfully wrote files.
3. Reading `_pipeline/coverage-targets.json` whose `last_updated_cycle` field tells us how far coverage state advanced.

The batch is the commit unit (per Q3 incremental retry). A batch's commit is "atomic" in the eventual-consistency sense: its notes hit disk, then `quality_report.py` writes `cycle-NNN-batch-NNN.json`. If the orchestrator dies between those two writes, on resume the batch is treated as **un-acknowledged** — `coverage-targets.json` won't have absorbed it yet, but the notes are already on disk. The next batch invocation deduplicates against existing filenames (existing dedup behavior, Principle VI), so the effect is "the next attempt sees the orphan notes, accepts them through SG-005, and writes the missing batch report."

**Rationale**:

- Adding a write-ahead log is a new failure mode (corrupt log → corrupt resume) and a new file format to maintain. The codebase already treats filesystem state as the source of truth (see `coverage.py:update_after_cycle`, `cycle_runner.py:_cycle_research_report_path`).
- The batch reports are small JSON files (≤ a few KB). Writing them after notes commit is a strictly safer order than writing them before — a missing batch report on resume is a recoverable signal, an orphan batch report pointing at non-existent notes is not.
- Constitution Principle V (offline-first, no external persistence) and existing patterns favor "filesystem is the database." A WAL would be the only piece of pipeline state that contradicts that.
- The orchestrator already does idempotent re-rendering of the scout prompt on `resume=True` (see `orchestrator.py:run_single_cycle`). Extending this pattern to batches is consistent.

**Alternatives considered**:

- **Write-ahead log (`_pipeline/cycles/cycle-NNN-wal.jsonl`)** — explicit per-event log written before each filesystem mutation. Rejected: introduces a new format, a new failure mode, and contradicts the existing "fs is the journal" pattern. The savings (no need to walk frontmatter for `created_at_cycle`) are not worth the cost; the walk is O(n_notes) and runs at resume time only.
- **SQLite transaction in `sources.db`** — wrap each batch's filesystem mutation in a SQLite tx. Rejected: SQLite cannot transact filesystem writes; the SQLite tx would lie about atomicity.
- **Lock files / `.in-progress` markers** — touch a marker before each batch, remove on success. Rejected: still a partial WAL; same failure modes (stale marker on crash); adds cleanup logic for no real gain over the frontmatter-walk approach.

---

## R-002 — Queryability score "monotonic increase" tolerance

**Decision**: **Allow regressions up to 5 percentage points without flagging; flag any regression > 5pp as a trajectory-warning (not a FAIL gate).** Specifically, the trajectory check in `cycle-NNN-quality-report.json` reports `trajectory: "improving" | "stable" | "regressing"` based on the rule:

- `improving` if `score(N) - score(N-1) >= 0`
- `stable` if `-0.05 <= score(N) - score(N-1) < 0` (within noise floor)
- `regressing` if `score(N) - score(N-1) < -0.05`

Only `regressing` triggers the WARN that FR-020 / SC-011 imply. `regressing` does NOT cause the orchestrator to abort or retry — it is logged for human review and surfaced in the cycle report and `vault_audit.py` summary.

**Rationale**:

- Probes are agent-collected evidence (which note matched which probe) scored by a deterministic Python rule (see R-006). The agent step introduces stochastic variance; observed variance for similar evidence-gathering tasks in the existing pipeline is ~3pp run-to-run. A 5pp band gives ~1.5x noise margin without being so wide it masks real regressions.
- The spec's SC-011 says "monotonically increases (each cycle ≥ previous cycle's score, **or flags a regression**)" — the "or flags" clause already permits a flag-don't-block semantics. Picking 5pp makes the rule executable.
- Treating regression as a hard FAIL would couple a *qualitative* signal (queryability is harder to compute crisply than counts) to a hard control-flow decision. Per Principle IV, scripts validate; this score is at the boundary of what counts as a clean validation. WARN preserves the signal without forcing the orchestrator to act on noisy data.
- Aborting on probe regression would also conflict with Principle II's "loop continuation is orchestrator-owned" — adding a third condition (probe regression) to the termination decision would muddy the existing three-condition logic.

**Alternatives considered**:

- **Strict monotonic (any drop = FAIL)**: rejected — couples noisy signal to hard control flow; would cause spurious aborts.
- **Wider band (e.g. 10pp)**: rejected — risks masking real plateaus that should trigger human attention.
- **Smoothed trajectory (3-cycle moving average)**: rejected for the v1 of this feature — adds complexity; revisit if 5pp band proves too noisy in practice. The cycle quality report keeps raw `score` history so a future smoother can be added without breaking the JSON contract.

---

## R-003 — Source-failure threshold during run (mid-cycle source unreachability)

**Decision**: **Two-tier threshold based on source role**, configurable via `settings.yaml` with sane defaults:

- **`required` sources** (those whose `role` field in `sources.db` is `required` or whose spec entry has `phases: [bootstrap]` and any of the spec's `source_of_truth_rules` references it): if even ONE becomes unreachable mid-run, log a structured WARN to `_pipeline/source-incidents.md`, mark the source as `degraded` in `sources.db`, and continue the current cycle. If 2+ required sources are degraded simultaneously, the orchestrator ABORTs the cycle (exit 2) with a "required-source quorum lost" diagnostic — `--resume` after fixing the source picks up cleanly.
- **`enrichment` sources** (everything else — RSS, market, secondary docs): unlimited mid-run failures are tolerated, each logged as INFO. The cycle continues. They appear in the cycle quality report's `degraded_sources` list so trajectory analysis can spot patterns.

Defaults live in `settings.yaml`:

```yaml
pipeline:
  source_failure_thresholds:
    required_quorum_loss: 2     # abort cycle if >= this many required sources fail
    enrichment_max_failures: 0  # 0 means unlimited; integer caps total enrichment failures per cycle
```

**Rationale**:

- The trial-run failure mode the spec describes is "burned 3 hours and tokens before anyone noticed source connectivity was degraded." Preflight (FR-007) catches this at start. Mid-run, the question is asymmetric: a required source going down means the cycle's output cannot be authoritative; an enrichment source going down means the cycle is just less rich. Treating them identically penalizes the second case unnecessarily.
- The 2-source quorum-loss threshold matches Principle VII (external sources mandatory): losing exactly one source is recoverable; losing two is structurally compromising.
- `sources.db` already carries a `role` column and a `consecutive_empty_cycles` counter (see `pipeline/source_manager.py:_CREATE_SOURCES`). Reusing this avoids new schema.
- Configurability satisfies the framework's portability principle: different vaults have different source criticality. `reference_vault_v3` would set `required_quorum_loss: 1` for code-derived vaults where every repo is treated as authoritative; the default of `2` suits typical mixed-source vaults.

**Alternatives considered**:

- **Single threshold `max_failed_sources: N`** without role distinction: rejected — flat threshold treats a failed Hyperskill (enrichment) the same as a failed canonical-repo source, which mismatches Principle VII's authority model.
- **Always abort on any source failure**: rejected — overshoots; many cycles run successfully with one transient enrichment failure.
- **Always continue, just log**: rejected — silently produces low-quality cycles when required sources are unreachable; this is the trial-run failure mode the feature exists to prevent.

---

## R-004 — Batch size (5–8 topics): exact default and override mechanism

**Decision**: **Default batch size = 6 topics, configurable via `settings.yaml` with hard bounds [3, 10].** The orchestrator's batch scheduler reads `pipeline.note_writer_batch_size` (default 6); if the spec or settings overrides outside [3, 10], the scheduler clamps and logs a WARN.

```yaml
pipeline:
  note_writer_batch_size: 6   # topics per note-writer invocation; clamped to [3, 10]
```

**Rationale**:

- Empirical signal from the trial run: the note-writer self-limited at ~10 notes per (single, large) invocation, even when handed more topics. That's a sign that ~10 topics is the upper bound of comfortable agent context for the existing `.agents/skills/note-writer/SKILL.md`. Batches must be **strictly smaller** than that ceiling so each batch completes its assignment without self-limiting.
- 6 leaves headroom: at 6 topics, the agent has token budget for type templates + research-plan injection + per-topic source citations + the actual prose. 5 is the floor for "this is a meaningful batch" (anything smaller is overhead-dominated). 8 is the ceiling above which observed self-limiting starts.
- Clamping at [3, 10] prevents two failure modes: tiny batches (1–2 topics) = orchestration overhead dwarfs work; batches > 10 = recreates the original problem.
- 25-note quota / 6 per batch = ~5 batches per cycle. Mid-cycle gates fire 4 times per cycle — frequent enough to catch drift early (FR's Story 9c "at 50% of assigned topics" check is triggered after batch 2 of ~5).

**Alternatives considered**:

- **Fixed 5**: rejected — bottom of the range; less efficient than 6, no observed downside to slightly larger batches.
- **Fixed 8**: rejected — top of the safe range; one slightly chatty topic could push the batch over the agent's self-limit threshold.
- **Adaptive (start at 8, shrink on partial completion)**: rejected for v1 — adds state machine complexity for marginal benefit; revisit in v2 if observed batches show consistent under-completion at 6.

---

## R-005 — Narrator token budget and failure mode

**Decision**: **Cap the narrator output at 200 words; the narrator skill's prompt enforces this. If the narrator step fails (LLM error, timeout, output > 400 words after retry), the orchestrator ships the deterministic plan body with a fixed canned header ("Cycle N priority: <top-3 categories from focus list>") and continues.** The narrator is advisory — its absence MUST NOT block a cycle.

Token cost estimate per cycle: ≤ 1,000 input tokens (deterministic body excerpt + spec scope summary) + ≤ 300 output tokens (narrative). At ~$3/M input + $15/M output: **≤ $0.008 per cycle** — well below noise threshold of typical cycle costs.

**Rationale**:

- Q1 (hybrid plan) chose to keep a narrator specifically because the user value of the plan is partly in *framing* — a deterministic priority queue is correct but illegible. The narrator's job is to translate the queue into "here's why we're focusing on Spring features and JVM internals this cycle: those are the largest gaps and have ample source material in `oms-service`."
- Capping output at 200 words bounds context impact downstream. The scout and note-writer prompts inject the narrative header verbatim; an unbounded narrator would hijack their context budgets.
- The fallback canned header guarantees the deterministic body always reaches downstream agents — no narrator outage can stop a cycle. This satisfies Principle IV (the "advisory" classification of the header is enforced architecturally, not just by convention).
- 200 words / 300 output tokens is large enough for nuance but small enough that the narrator can't smuggle control instructions into the body via verbose prose.

**Alternatives considered**:

- **No cap, trust the agent**: rejected — observed token-count discipline of agents on summary tasks is poor; uncapped narrative would crowd downstream prompts.
- **Skip narrator entirely (just deterministic body)**: rejected — Q1 explicitly chose hybrid (Option C). User wants the framing.
- **Narrator writes the entire plan**: rejected — Q1 explicitly rejected this (Option B). Would re-introduce the drift the deterministic body is supposed to prevent.

---

## R-006 — Probe scoring approach (deterministic vs. agent-judged)

**Decision**: **Two-step probe execution where evidence collection is agent-driven but scoring is pure Python.** For each probe:

1. **Collection (agent)**: a one-shot agent invocation reads the probe text and returns a JSON list of vault filenames it considers relevant (e.g., `[{"file": "spring-application-context.md", "confidence": "high"}]`). The agent does NOT score — it only retrieves candidate notes. This step uses the existing search/grep tooling and is cheap.
2. **Scoring (Python, deterministic)**: `pipeline/probes.py` opens each candidate file and applies a rubric:
   - `+1` if the probe's primary keyword (extracted from the probe text) appears ≥ 3 times in the note body.
   - `+1` if the note's `summary` frontmatter mentions any keyword from the probe.
   - `+1` if the note's `coverage_category` matches the probe's source category (e.g., a `spring-feature` probe answered by a `spring-feature` note).
   - The probe is `answered` if any candidate note scores ≥ 2; partially answered if any scores 1; unanswered if no candidates returned or all score 0.

Per-cycle queryability score = `answered_count / total_probes` × 100, integer 0–100.

**Rationale**:

- Principle IV (Agent-Script Separation) is the load-bearing constraint here. Letting the agent both find evidence AND grade it would let the agent self-validate — exactly what the constitution forbids.
- The split (agent finds, Python scores) keeps the agent's role as "report and gather" and Python's role as "compute and decide" — the same pattern `topic_harvest.py` uses (agent's research report supplies wikilinks; Python ranks them by citation count).
- Scoring rubric is intentionally crude (3 binary checks). Sophisticated NLP scoring would tempt new dependencies (sentence-transformers etc.); the constitution forbids those. The crude rubric is sufficient because the *trend across cycles* is what matters (R-002), not absolute precision.
- Caching is trivial: the probe set is deterministically generated from the spec, so the cache key is `(probe_id, vault_content_hash)`. Re-runs over an unchanged vault skip the agent step entirely.

**Alternatives considered**:

- **Pure agent scoring**: rejected — Principle IV violation.
- **Pure regex/keyword matching, no agent step**: rejected — would miss probes whose answer is in a note whose name doesn't match the probe text. The agent's retrieval step is cheap and recovers ~30% additional matches in pilot estimates.
- **Use vault-side FTS5 index for retrieval**: rejected for v1 — the FTS5 index is a Phase 2/3 concern per the constitution ("Not a Phase 2/3 system. ... FTS5 indexing ... are separate concerns"). Agent-driven retrieval avoids depending on infra that doesn't exist yet.

---

## R-007 — Backwards compatibility for `forbidden_filename_prefixes`

**Decision**: **Additive optional field on `SpecConfig` with default `field(default_factory=list)`; existing specs continue to validate without modification; gates SG-003 / CG-003 / SC-009 report `N/A` (not WARN, not FAIL) when the field is absent or empty.** The reference_vault_v3 spec receives a follow-up edit (tracked as a separate task in `/speckit.tasks`) to declare its eight known prefixes.

```python
@dataclass
class SpecConfig:
    ...
    forbidden_filename_prefixes: list[str] = field(default_factory=list)
```

`validator.py` does not warn on absence. `parser.py` round-trips the field (omits it from output if empty, preserving spec readability for specs that don't use it). The `vault_audit.py` summary surfaces `Abstraction gate: N/A (no forbidden_filename_prefixes declared)` when applicable so users know why the gate didn't run.

**Rationale**:

- Backwards compatibility is a non-negotiable: there are existing vaults (codebase-vault, feeds-vault per the audit baselines) that have specs predating this field. Forcing them to add it would conflict with the constitution's "vault spec file format" being out-of-scope for governance — i.e., spec evolution must be smooth.
- N/A (not WARN) is the right signal: WARN implies the user did something wrong; N/A implies the gate is inactive by design. The vault_audit.py rendering distinguishes them.
- Per-vault configurability is the explicit decision in clarification Q5. The gate code must read from spec, not constants, so no in-code prefix list ever ships.

**Alternatives considered**:

- **Mandatory field in all new specs**: rejected — would break spec backwards compat; would force vaults that don't need the gate to declare empty lists; conflicts with Q5's "default empty" explicit answer.
- **Gate WARN on missing field**: rejected — penalizes correct spec authors who chose not to use the field.
- **Heuristic detection (no spec field)**: rejected in Q5 (Option C); user explicitly chose A. Recording the alternative here for completeness.

---

## R-008 — Integration with existing `pipeline/preconditions.py` (preflight as 6th precondition)

**Decision**: **Add `preflight_sources` as the 6th Phase-2 entry precondition** in `pipeline/preconditions.py:check`. It runs after the existing 5 (pytest, validate_vault, vault_metrics baseline, settings, agent runtime) and exits non-zero (precondition unmet) if any required source is unreachable. The cycle does not start.

The standalone `scripts/preflight_sources.py` CLI is also created (FR-007 visible to users) but `preconditions.py` calls into the same `pipeline/preflight.py` module so there's exactly one implementation.

**Rationale**:

- The constitution's Phase Sequencing principle treats preconditions as the sole gate on Phase 2 entry. Adding source preflight as a precondition is the constitutionally correct slot for it — putting it inside the cycle loop would create a second entry gate and complicate Phase 2 semantics.
- Reusing the precondition infrastructure (already iterated, already tested) avoids duplicating gate-running machinery.
- A standalone CLI is still useful (the user wants to run preflight independently per User Story 5); it's a thin wrapper, not a parallel implementation.

**Alternatives considered**:

- **Run preflight inside `cycle_runner.py` at cycle 1 start**: rejected — couples preflight to cycle execution, makes "run preflight without committing to a cycle" awkward, splits the implementation across two call sites.
- **Run preflight only as a CLI, not in preconditions**: rejected — users would forget to run it, defeating the "30-second preflight would have caught this" benefit.

---

## R-009 — `topic_harvest.py` as upstream feeder (clarification Q4 mechanics)

**Decision**: **`topic_harvest.py` runs unchanged at every cycle's tail** (its existing position per `cycle_runner.py`). The new `pipeline/research_plan.py` reads its outputs (`_pipeline/cycles/cycle-NNN-harvest.json` and `_pipeline/research-backlog.md`) at the **start** of the next cycle, before the scout invocation, and merges them into the priority queue. Specifically:

- Harvested orphan wikilinks (with citation counts) → appended to the priority queue under category `concept` with priority = `0.3 + 0.1 × citation_count` (capped at 1.0). They sort below explicit spec-driven gaps (which start at 0.5+) but above pure speculation.
- Harvest-promoted coverage targets (the auto-promotion mechanism in the constitution's "Coverage Targets as Phase Completion Gate" section) are already absorbed into `coverage-targets.json` by the time the plan generator runs, so the plan picks them up naturally via its coverage-state input.
- Persistent rejects (notes the verifier rejected ≥ 2 times across cycles, tracked in a new `_pipeline/rejects.json`) → appended to the exclusion list so the plan doesn't re-propose them.

**Rationale**:

- Q4 explicitly chose Option A: keep harvester as upstream feeder. This R-item makes that wiring concrete.
- Reusing existing harvest outputs (rather than re-implementing orphan capture in the plan generator) honors Q4's "the plan is the single source of truth for *what to do next*; the backlog remains the source of truth for *harvested orphan wikilinks*" — distinct responsibilities, distinct files, single read direction (plan reads backlog; backlog never reads plan).
- Citation-count-weighted priority means high-demand orphan concepts surface in the next plan automatically (alignment with the constitution's Stub-as-Fuel principle).

**Alternatives considered**:

- **Plan generator re-implements orphan harvesting**: rejected (Q4 Option B).
- **Two parallel files (plan + backlog as independent inputs to agents)**: rejected (Q4 Option C) — splits the source of truth.
- **Inline harvest output as a section of `research-plan.md`**: rejected (Q4 Option D) — harvester would have to know about plan format; one-way dependency becomes two-way.

---

## R-010 — Existing scout / note-writer skill modifications (FR-003, FR-004, FR-006)

**Decision**: **Modify `.agents/skills/scout/SKILL.md` and `.agents/skills/note-writer/SKILL.md` in place** (they are the currently-used skills per `pipeline/cycle_runner.py` invocation paths). Specific edits:

**`.agents/skills/scout/SKILL.md`**:

- Add explicit Step 0: "Read `_pipeline/research-plan.md`. Treat its priority queue as the canonical to-do list for this cycle."
- Modify the topic extraction step (existing wording: "extract the service it describes, every ADR file, every Kafka topic, every domain term referenced in 2+ files"): replace with "for each code artifact you observe, name the engineering concept, pattern, or technique it exemplifies — that name goes into `topics_found.new`. Internal class/flow names go into `topics_from_code` as provenance only."
- Add explicit MUST: "Populate `topics_found.new` with generalizable topic titles. If `topics_found.new` is empty, the SG-001 gate will fail your output and the cycle will not proceed."
- Add Step 0.5: "If `_pipeline/research-plan.md` declares a per-cycle focus list, ≥ 70% of your `topics_found.new` entries MUST belong to those categories."

**`.agents/skills/note-writer/SKILL.md`**:

- Add Step 0: "Read `_pipeline/research-plan.md` for the cycle's narrative header and exclusion list."
- Add an explicit input schema: the orchestrator now passes a `batch_topics` argument (list of 5–8 topics) instead of expecting the agent to scan a full report. The skill MUST attempt every assigned topic before stopping.
- Add: "If you cannot write a topic in this batch (no sources, conflicts with exclusion list, etc.), report it explicitly in the batch report's `skipped_topics` field with a reason. Skipped-because-different-topic-was-easier is a quality-gate violation."

**`.agents/skills/research-plan-narrator/SKILL.md`** (NEW): the cap-at-200-words narrator skill from R-005.

**Rationale**:

- Skills live in `.agents/skills/` per existing convention. They are bundled into the wheel via `tool.hatch.build.targets.wheel.force-include`. Modifying them in place means generated vaults pick up the new behavior automatically on next `research-vault generate`.
- Step 0 placement (read the plan first) makes the plan structurally unmissable rather than relying on agent discipline.
- The MUST clause for `topics_found.new` plus the SG-001 gate together implement FR-021 (gate fails if scout produces empty `topics_found.new`).

**Alternatives considered**:

- **Create new skill files alongside the old ones**: rejected — splits maintenance, leaves dead code, confuses generated vaults.
- **Encode the rules in agent prompts at render time only**: rejected — bypasses the skill abstraction, makes the rules invisible to anyone reading the skill files directly.

---

## R-011 — Test strategy (TDD per Principle III)

**Decision**: **Each new module gets contract tests written before implementation**, in this order:

1. Schema/contract tests first (Phase 1 contracts/ files drive pydantic-style assertions in Python) — these fail until the dataclass exists.
2. Pure-function tests for each gate (CG-001..CG-007, SG-001..SG-005) using small fixture vaults.
3. Integration tests for orchestrator retry semantics (incremental retry per Q3) using `tmp_path` fixtures.
4. Property tests via `hypothesis` (already a dev dep) for the per-cycle minimum-yield arithmetic (`ceil(remaining/remaining_cycles)`) — invariants like "yield monotonically increases as cycles consume budget."
5. Mocked-LLM tests for the narrator skill (the test injects a fake claude CLI binary that returns a canned response).

Test file organization mirrors `src/research_vault/pipeline/` → `tests/pipeline/` (new directory; pyproject's `pythonpath = ["src"]` already supports this).

**Rationale**:

- TDD is constitutionally non-negotiable (Principle III). The Phase 1 contracts/ files are the contract test inputs.
- Hypothesis is already declared in `pyproject.toml`'s `[project.optional-dependencies] dev`. No new test deps.
- Mocking the LLM avoids network calls in tests (Principle V, Phase V offline-first) and keeps tests deterministic.

**Alternatives considered**:

- **Implementation-first then tests**: rejected — Principle III forbids.
- **Real LLM calls in tests via the `integration` marker**: kept available (the marker exists per `pyproject.toml`'s `markers = ["integration: marks tests that make real LLM calls"]`) but **opt-in only**, not the default test path.

---

## Summary

All 11 unknowns resolved. No remaining `NEEDS CLARIFICATION` markers in the plan or spec.

Decisions summary table:

| ID | Decision |
|---|---|
| R-001 | Idempotent replay using filesystem state — no WAL |
| R-002 | 5pp tolerance for queryability score; WARN-only on regression |
| R-003 | Two-tier source-failure threshold by role (required quorum vs enrichment unlimited), configurable in `settings.yaml` |
| R-004 | Default batch size = 6, clamped to [3, 10], configurable |
| R-005 | Narrator capped at 200 words, fallback canned header on failure |
| R-006 | Probe scoring: agent retrieves, Python scores via 3-rule rubric |
| R-007 | `forbidden_filename_prefixes` field is additive optional; gates report N/A when absent |
| R-008 | Preflight wired as the 6th Phase-2 precondition; standalone CLI is a thin wrapper |
| R-009 | `topic_harvest.py` unchanged; new plan generator reads its outputs at next cycle start |
| R-010 | Existing scout + note-writer skills modified in place; new narrator skill added |
| R-011 | TDD per Principle III: contracts → unit → integration → property; mocked LLM in tests |

Ready for Phase 1 (data-model, contracts, quickstart).
