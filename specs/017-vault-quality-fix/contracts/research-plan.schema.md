# Contract: `_pipeline/research-plan.md`

**Owner**: `pipeline/research_plan.py` (deterministic body) + `pipeline/plan_narrator.py` (advisory header). **Q1 hybrid**.
**Consumers**: scout skill, note-writer skill, plan_narrator skill (reads the deterministic body to write its header).
**Lifetime**: written before each cycle; overwritten next cycle. Historical copy at `_pipeline/cycles/cycle-NNN-research-plan.md`.

## File structure

The file is Markdown with YAML frontmatter. The Markdown body has a strict section ordering. Anything outside the documented sections MUST be ignored by parsers (forward compatibility).

```markdown
---
cycle_number: 4
generated_at: "2026-05-15T22:30:00Z"
framework_version: "0.2.17"
cycle_quota: 30                # ceil(remaining_targets / remaining_cycles)
schema_version: "1"            # bump on breaking layout changes
---

## Focus rationale

<≤ 200-word narrative from research-plan-narrator skill — ADVISORY ONLY.
Downstream code MUST NOT parse this section for control flow. If absent or
empty, downstream agents fall back to the deterministic sections below.>

## Coverage state

| Category         | Target | Met | Fill % | Priority | Unmet topics                          |
|------------------|--------|-----|--------|----------|---------------------------------------|
| spring-feature   | 36     | 8   | 22%    | 90       | application_context, dependency_inj…  |
| concept          | 40     | 12  | 30%    | 80       | hexagonal_architecture, …             |
| ...

## Cycle focus

This cycle MUST produce ≥ 70% of its notes in the following categories:

- spring-feature (22% filled)
- java-jvm (0% filled)
- learning-module (0% filled)

## Priority queue

Each entry: `<title> · category · score · provenance · sources`.

1. Spring ApplicationContext lifecycle · spring-feature · 0.92 · spec_gap · oms-service/.../AppContext.java, docs.spring.io/...
2. JVM garbage collection algorithms · java-jvm · 0.88 · spec_gap · Hyperskill module 12, docs.oracle.com/...
3. Hexagonal architecture / ports and adapters · architecture-pattern · 0.81 · harvest_orphan(7) · wms-service/.../OutboundPort.java
4. ...

## Exclusions

The note-writer MUST NOT propose any topic whose canonical filename matches:

- already-covered: spring-bean-registration, kafka-consumer-groups, …  (already in vault)
- persistent-rejects: oreilly-deep-learning-book-summary, …  (verifier rejected ≥ 2x)
- out-of-scope: order-management-business-rules, …  (per spec.scope.out_of_scope)
```

## YAML frontmatter contract

| Field | Type | Required | Notes |
|---|---|---|---|
| `cycle_number` | int ≥ 1 | yes | the upcoming cycle this plan targets |
| `generated_at` | ISO-8601 UTC string | yes | |
| `framework_version` | string | yes | matches `research_vault.__version__` at gen time |
| `cycle_quota` | int ≥ 1 | yes | per-cycle minimum yield (FR-017) |
| `schema_version` | string | yes | currently `"1"`; bump on breaking layout changes |

## Section contract

Sections appear in exact order: `## Focus rationale` → `## Coverage state` → `## Cycle focus` → `## Priority queue` → `## Exclusions`. A parser missing any of the latter four MUST treat the file as malformed and refuse to render the next cycle's prompts.

`## Focus rationale` MAY be empty (narrator failure path per R-005).

## Read direction

```text
research_plan.py (deterministic) → writes everything except `## Focus rationale`
plan_narrator.py (agent step)    → reads everything; writes ONLY `## Focus rationale`
agents (scout, note-writer)      → read entire file via _render.py prompt injection
```

The narrator MUST NOT modify any section other than `## Focus rationale`. Parsers MUST tolerate (but log) any deviation by treating the deterministic body as canonical.

## Forward compatibility

- New frontmatter fields MAY be added without bumping `schema_version`. Consumers MUST ignore unknown fields.
- New body sections MAY be appended after `## Exclusions`. Consumers MUST ignore unknown sections.
- Removing or renaming any of the 5 sections, or any required frontmatter field, requires `schema_version` bump.
