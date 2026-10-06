# Phase 1 Data Model: Vault Quality Fix

**Feature**: 017-vault-quality-fix
**Plan**: [plan.md](./plan.md) | **Research**: [research.md](./research.md)
**Date**: 2026-05-15

## Overview

This document enumerates every entity introduced or modified by this feature. Each entity has: **Purpose**, **Schema** (Python dataclass-style), **Validation rules**, **State transitions** (where applicable), and **Where it lives** (filesystem location or Python module).

All entities serialize to JSON or Markdown using the existing `to_dict()` / `from_dict()` round-trip pattern from `src/research_vault/spec/schema.py`. No external persistence (Principle V).

---

## E-001 — `SpecConfig` (MODIFIED)

**Purpose**: Vault spec dataclass; gains two fields used by the new gate machinery.

**Module**: `src/research_vault/spec/schema.py`

**New fields**:

```python
@dataclass
class SpecConfig:
    # ... existing fields preserved ...
    forbidden_filename_prefixes: list[str] = field(default_factory=list)
    """
    Vault-specific filename prefixes (e.g. ['oms_', 'wms_']) that mark notes
    named after internal artifacts rather than engineering concepts. Read by
    abstraction gates SG-003, CG-003, and success criterion SC-009. Default
    empty: those gates report N/A and never fail (R-007 backwards compat).
    """
```

```python
@dataclass
class CoverageCategory:
    # ... existing fields preserved ...
    priority: int = 0
    """
    Higher value = filled first when budget is constrained. Default 0
    (no preference, ordering follows spec definition order). Used by
    pipeline.research_plan to rank categories in the priority queue (FR-005).
    Range: 0..100, validated by spec/validator.py.
    """
```

**Validation rules** (`src/research_vault/spec/validator.py`):

- `forbidden_filename_prefixes`: each entry MUST be a non-empty string ending with `_` or `-`. Empty list is valid.
- `priority`: integer 0..100. Negative or > 100 → SpecValidationError.
- Backwards compat: missing field → default value (no warning).

**State transitions**: none (read-only at runtime).

---

## E-002 — `ResearchPlan`

**Purpose**: The hybrid research plan written before each cycle (FR-001/FR-002, clarification Q1). Single source of truth for "what the vault needs, what it has, what to do next, what to avoid."

**Module**: `src/research_vault/pipeline/research_plan.py`

**Schema**:

```python
@dataclass
class CategoryFillState:
    name: str
    target_count: int
    met_count: int
    fill_pct: float            # met_count / target_count, 0.0..1.0
    priority: int              # from CoverageCategory.priority
    unmet_topics: list[str]    # filenames the spec expects but vault lacks

@dataclass
class PrioritizedTopic:
    title: str                 # generalized topic title (NOT internal artifact name)
    category: str              # matches CoverageCategory.name
    priority_score: float      # 0.0..1.0; higher = more urgent
    source_hints: list[str]    # spec data sources / file paths likely to back this topic
    provenance: str            # "spec_gap" | "harvest_orphan" | "auto_promoted"
    citation_count: int = 0    # if provenance == "harvest_orphan"

@dataclass
class ResearchPlan:
    cycle_number: int          # the upcoming cycle this plan targets
    generated_at: str          # ISO-8601 UTC timestamp
    framework_version: str     # research_vault.__version__ at generation time
    coverage_state: list[CategoryFillState]
    priority_queue: list[PrioritizedTopic]   # full ranked queue
    cycle_focus: list[str]                    # category names this cycle should hit (≥ 70% of notes)
    cycle_quota: int                          # min notes this cycle, from ceil(remaining/remaining_cycles)
    exclusions: list[str]                     # filenames to NEVER propose (already covered + persistent rejects + out_of_scope)
    narrative_header: str = ""                # ≤ 200 words from research-plan-narrator skill; advisory only

    def to_markdown(self) -> str: ...
    def to_dict(self) -> dict[str, Any]: ...
    @classmethod
    def from_markdown(cls, text: str) -> "ResearchPlan": ...
```

**Validation rules**:

- `cycle_number ≥ 1`.
- `cycle_quota ≥ 1` (cannot plan a zero-yield cycle; if budget is exhausted, the orchestrator should ABORT, not generate a degenerate plan).
- `len(cycle_focus) ≥ 1`.
- `len(priority_queue) ≥ cycle_quota` (must have enough material to assign).
- `narrative_header` length ≤ 200 words after whitespace normalization. Longer narrative is truncated by the narrator step before this dataclass is constructed.
- All `category` names in `priority_queue` MUST exist in `coverage_state`.

**State transitions**: stateless. Each cycle writes a fresh plan; previous plans are preserved as `_pipeline/cycles/cycle-NNN-research-plan.md` for traceability.

**Filesystem**: `_pipeline/research-plan.md` (current cycle, always overwritten) + `_pipeline/cycles/cycle-NNN-research-plan.md` (historical, append-only).

---

## E-003 — `NoteWriterBatch`

**Purpose**: A single note-writer invocation scoped to 5–8 topics from `ResearchPlan.priority_queue` (Q2 sequential batches; FR-006).

**Module**: `src/research_vault/pipeline/batch.py`

**Schema**:

```python
@dataclass
class BatchAssignment:
    cycle_number: int
    batch_number: int          # 1-indexed within cycle
    topics: list[PrioritizedTopic]      # 3..10 topics, default 6 (R-004)
    correction_directive: str = ""      # injected from previous batch's gate FAIL (FR-018)

@dataclass
class BatchResult:
    cycle_number: int
    batch_number: int
    started_at: str            # ISO-8601 UTC
    finished_at: str
    notes_written: list[str]   # filenames committed to data_vault/
    skipped_topics: list[dict[str, str]]   # [{"topic": "...", "reason": "no_sources" | "exclusion_match" | ...}]
    sg_gate_results: list["GateResult"]    # gates that ran on this batch (SG-004, SG-005)
    accepted: bool             # True iff all SG gates returned PASS or WARN
```

**Validation rules**:

- `3 ≤ len(topics) ≤ 10`. Outside range → scheduler clamps and logs WARN (R-004).
- `1 ≤ batch_number ≤ ceil(cycle_quota / batch_size)`.
- `accepted` is computed deterministically from `sg_gate_results`: `True` iff no gate returned FAIL.
- `notes_written` filenames MUST match `proposed_filenames` from the cycle's scout report (Principle VI).

**State transitions**:

```text
PENDING ─(invoked)→ RUNNING ─(complete)→ ACCEPTED  (sg gates PASS/WARN; coverage state advances)
                              └(complete)→ REJECTED (any sg gate FAIL; notes discarded; retry directive built)
```

REJECTED batches discard their `notes_written` (the framework deletes them) before the retry. ACCEPTED batches are committed and **never** rolled back even if a later cycle-level gate FAILs (Q3 incremental retry rule).

**Filesystem**: `_pipeline/cycles/cycle-NNN-batch-MMM.json` (one per batch; M zero-padded 3 digits).

---

## E-004 — `GateResult`

**Purpose**: Common return type for every gate (SG-xxx and CG-xxx). Carries enough info for the orchestrator to decide control flow and for the cycle quality report to be human-readable.

**Module**: `src/research_vault/pipeline/gates.py`

**Schema**:

```python
GateStatus = Literal["PASS", "WARN", "FAIL", "NA"]

@dataclass
class GateResult:
    gate_id: str               # "CG-001" | "SG-003" | ...
    status: GateStatus
    metric_name: str           # e.g. "notes_created_this_cycle"
    metric_value: float | int | str
    threshold: float | int | str | None
    message: str               # human-readable explanation
    correction_hint: str = ""  # used by FR-018 to build the next-batch correction directive
```

**Validation rules**:

- `gate_id` MUST match `^[CS]G-\d{3}$`.
- `status == "NA"` only when the gate is structurally inapplicable (e.g., SG-003 when `forbidden_filename_prefixes` is empty per R-007).
- `correction_hint` MUST be non-empty when `status == "FAIL"`.

**State transitions**: immutable value type.

---

## E-005 — `CycleQualityReport`

**Purpose**: Per-cycle deterministic JSON summarizing all gate results, coverage snapshot, queryability score, and trajectory (FR-019). Machine-readable, no agent judgment.

**Module**: `src/research_vault/pipeline/quality_report.py`

**Schema**:

```python
@dataclass
class CycleQualityReport:
    cycle_number: int
    framework_version: str
    generated_at: str          # ISO-8601 UTC
    cycle_started_at: str
    cycle_finished_at: str
    gates: dict[str, GateResult]               # keyed by gate_id; includes both SG and CG
    coverage_snapshot: dict[str, dict]         # {category_name: {"target": int, "met": int, "fill_pct": float, "delta_this_cycle": int}}
    notes_written: int
    notes_accepted: int        # passed SG-004 + SG-005
    notes_rejected: int        # failed SG-004 or SG-005 → discarded
    batches: list[str]         # batch report filenames
    queryability_score: int    # 0..100 (see E-007)
    queryability_trajectory: Literal["improving", "stable", "regressing"]   # per R-002
    degraded_sources: list[str]                # source names degraded mid-cycle (R-003)
    retry_count: int           # 0..2; > 0 means a gate FAIL was retried
    aborted: bool              # True iff retry budget exhausted
    abort_reason: str = ""

    def to_dict(self) -> dict[str, Any]: ...
```

**Validation rules**:

- `cycle_number ≥ 1`.
- `notes_written == notes_accepted + notes_rejected`.
- `queryability_score ∈ [0, 100]`.
- `retry_count ∈ {0, 1, 2}`.
- `aborted == True` ⟹ `retry_count == 2` AND `abort_reason != ""`.
- `len(gates) ≥ 12` (5 SG gates run at least once + 7 CG gates always run; if the cycle had multiple batches, SG keys are suffixed `SG-004#1`, `SG-004#2` etc. and the count is higher).

**State transitions**: written once per cycle by the orchestrator after either ACCEPT-and-advance or ABORT. Never mutated after write.

**Filesystem**: `_pipeline/cycles/cycle-NNN-quality-report.json`.

---

## E-006 — `CorrectionDirective`

**Purpose**: Structured payload that turns a gate FAIL into prompt-injection text for the next batch / next cycle (FR-018).

**Module**: `src/research_vault/pipeline/correction.py`

**Schema**:

```python
@dataclass
class CorrectionDirective:
    cycle_number: int
    batch_number: int | None   # None when directive is cycle-wide (CG-xxx FAIL)
    failing_gate_ids: list[str]
    diagnosis: str             # human + LLM-readable, e.g. "Previous batch failed CG-002 (single-category cycle)"
    required_actions: list[str]   # e.g. ["produce notes in ≥ 5 categories", "include at least one note in: [java-jvm, security-practice]"]
    forbidden_actions: list[str]  # e.g. ["do NOT propose any topic with prefix in: [oms_, erp_]"]
    expires_after_cycle: int   # directive auto-clears after this cycle (default = current cycle + 1)

    def to_prompt_block(self) -> str: ...   # markdown injectable into agent prompts
```

**Validation rules**:

- `len(failing_gate_ids) ≥ 1`.
- `len(required_actions) ≥ 1`.
- Directives never persist beyond `expires_after_cycle` — pipeline.correction garbage-collects expired ones.

**State transitions**:

```text
CREATED (gate FAIL) → INJECTED (next prompt rendered) → EXPIRED (cycle > expires_after_cycle)
```

**Filesystem**: `_pipeline/corrections/cycle-NNN-batch-MMM.json` (or cycle-wide: `_pipeline/corrections/cycle-NNN.json`).

---

## E-007 — `QueryabilityProbe` and `ProbeResult`

**Purpose**: Deterministically generated questions the vault should be able to answer (FR-020), and the per-probe outcome of running them.

**Module**: `src/research_vault/pipeline/probes.py`

**Schema**:

```python
ProbeKind = Literal["coverage", "cross_reference", "findability"]

@dataclass
class QueryabilityProbe:
    probe_id: str              # stable hash of (kind, source_text, vault_id) for caching
    kind: ProbeKind
    question: str              # e.g. "What does Spring's ApplicationContext do under the hood?"
    keywords: list[str]        # extracted from question; used by deterministic scorer
    source_category: str       # category from spec.note_types this probe targets
    source_field: str          # "contextual_questions" | "boundaries" | "out_of_scope"

@dataclass
class CandidateNote:
    filename: str
    confidence: Literal["high", "medium", "low"]   # from agent collection step

@dataclass
class ProbeResult:
    probe_id: str
    candidates: list[CandidateNote]                # what agent retrieval returned
    scored_candidates: list[tuple[str, int]]       # (filename, rubric_score 0..3)
    answered: bool             # True iff any scored_candidate has score ≥ 2
    partial: bool              # True iff !answered AND any scored_candidate has score == 1
    reason: str                # explanation when !answered (e.g. "no candidate notes")
```

**Validation rules**:

- `probe_id` stable across cycles for unchanged vaults (cache key).
- Probes are generated deterministically from `SpecConfig` (`contextual_questions` per note type + `boundaries` keywords + `out_of_scope` negative probes).
- Scoring rubric (R-006) is pure Python; the agent step provides only `candidates`, never `scored_candidates`.

**State transitions**: probes are stateless template definitions; results are per-cycle artifacts.

**Filesystem**:

- Probe templates: derived at runtime from `SpecConfig`; not stored on disk.
- Probe results: `_pipeline/cycles/cycle-NNN-probe-results.json` (list of `ProbeResult`).

---

## E-008 — `PreflightResult`

**Purpose**: Pre-Phase-2 source connectivity check (FR-007).

**Module**: `src/research_vault/pipeline/preflight.py`

**Schema**:

```python
SourceStatus = Literal["ok", "degraded", "unreachable"]

@dataclass
class SourceCheck:
    name: str                  # matches SpecConfig.data_sources[].name
    role: str                  # "required" | "enrichment"
    type: str                  # "local_repo" | "github_pr" | "web" | "rss" | "oreilly" | ...
    status: SourceStatus
    detail: str                # human-readable error if degraded/unreachable
    checked_at: str            # ISO-8601 UTC
    elapsed_ms: int

@dataclass
class PreflightResult:
    generated_at: str
    framework_version: str
    sources: list[SourceCheck]
    required_unreachable_count: int
    enrichment_unreachable_count: int
    overall_status: Literal["pass", "warn", "fail"]
    # pass: all sources OK; warn: enrichment failures only; fail: ≥ 1 required unreachable
```

**Validation rules**:

- Mapped exit codes (per Principle "Script Exit Code Model"):
  - `pass` → exit 0
  - `warn` → exit 0 (still passes the precondition; logged)
  - `fail` → exit 1 (precondition unmet; cycle does not start)
- Mid-run degradation uses the same `SourceCheck` shape, written to `_pipeline/source-incidents.md` (R-003), but doesn't update `PreflightResult` (which is start-of-run only).

**State transitions**: snapshot value, immutable after write.

**Filesystem**: `_pipeline/preflight.json`. Also referenced by `pipeline/preconditions.py` (in-memory, no separate write).

---

## E-009 — `PersistentReject`

**Purpose**: Track topics the verifier rejected ≥ 2 times across cycles so the plan generator can exclude them (R-009).

**Module**: tracked by `pipeline/research_plan.py`; rebuilds from cycle reports on demand (no separate writer).

**Schema**:

```python
@dataclass
class PersistentReject:
    topic_title: str
    proposed_filename: str
    reject_count: int
    first_rejected_cycle: int
    last_rejected_cycle: int
    reasons: list[str]         # verifier reasons accumulated across rejections
```

**Validation rules**:

- `reject_count ≥ 2` is the threshold for inclusion in `ResearchPlan.exclusions`.
- A topic that later gets accepted (vault contains a note matching `proposed_filename`) is auto-removed from the rejects on next plan generation — no manual cleanup.

**State transitions**: rebuilt deterministically from `_pipeline/cycles/cycle-NNN-quality-report.json` history each plan cycle. Not persisted as a separate file (avoids drift).

**Filesystem**: derived. Not stored separately.

---

## Relationships

```text
SpecConfig
  ├─ uses → CoverageCategory.priority           (E-001 modifies coverage.py to read priority)
  ├─ feeds → ResearchPlan.coverage_state        (plan generator reads spec)
  └─ feeds → QueryabilityProbe                  (probes derive from contextual_questions/boundaries)

ResearchPlan
  ├─ produced by → research_plan.py + plan_narrator.py
  ├─ inputs ← coverage-targets.json, research-backlog.md (from topic_harvest.py), PersistentReject
  ├─ consumed by → scout skill, note-writer skill (via _render.py)
  └─ archived as → cycle-NNN-research-plan.md

NoteWriterBatch (BatchAssignment + BatchResult)
  ├─ produced by → batch.py scheduler (slices ResearchPlan.priority_queue)
  ├─ executed by → note-writer skill
  ├─ validated by → SG-004, SG-005 (gates_step.py)
  └─ persisted as → cycle-NNN-batch-MMM.json

CorrectionDirective
  ├─ produced by → correction.py on any gate FAIL
  ├─ consumed by → next BatchAssignment (or next cycle's ResearchPlan)
  └─ persisted as → cycle-NNN-batch-MMM.json (corrections subdirectory)

CycleQualityReport
  ├─ produced by → quality_report.py at cycle end (or abort)
  ├─ aggregates → all GateResults, all BatchResults, ProbeResults, PreflightResult deltas
  └─ persisted as → cycle-NNN-quality-report.json

QueryabilityProbe → ProbeResult
  ├─ generated by → probes.py from SpecConfig (deterministic)
  ├─ collected by → agent step (retrieval only, no scoring per R-006)
  ├─ scored by → probes.py scorer (3-rule rubric)
  └─ feeds → CycleQualityReport.queryability_score

PreflightResult
  ├─ produced by → preflight.py (called from preconditions.py + standalone CLI)
  └─ gates → Phase 2 entry (precondition #6)

PersistentReject
  ├─ derived from → CycleQualityReport history
  └─ feeds → ResearchPlan.exclusions
```

## Schema-extension summary

This feature adds 8 new dataclasses (E-002..E-009) and modifies 1 existing (E-001 `SpecConfig`). All new dataclasses live in `src/research_vault/pipeline/` modules; the spec dataclass change lives in `src/research_vault/spec/schema.py`. No existing dataclass is removed or has fields removed.

Every dataclass implements `to_dict()` / `from_dict()` (or `to_markdown()` / `from_markdown()` for the plan) following the existing schema.py convention. JSON contract files in `contracts/` give the on-disk shape independently of the Python dataclasses, so the framework can evolve internal types without breaking JSON-consuming tools.
