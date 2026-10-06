# Specification Quality Checklist: Source Credibility Model

**Purpose**: Validate specification completeness and quality before planning/implementation
**Created**: 2026-06-03 · **Feature**: [spec.md](../spec.md)
**State**: post-clarify + plan + tasks + analyze. **IMPLEMENT-READY** (gated only
by the 053-ship sequencing gate — Wave 2).

## Content Quality
- [x] No implementation details leaking into the spec's requirements (the *what*,
      not the *how*; concrete shapes live in `contracts/`)
- [x] Focused on user/consumer value (030 metric, 048 v2 diagnosability, consistent
      authoring guidelines)
- [x] Written so a non-author can apply the model (FR-009 guidelines bar)
- [x] All mandatory sections completed (Problem, Scenarios, Requirements, Key
      Entities, Determinism guardrails, Dependencies, Out-of-scope, Success Criteria)

## Requirement Completeness
- [x] **No `[NEEDS CLARIFICATION]` markers remain** — CL-1..CL-6 resolved
      (Clarifications 2026-06-03):
  - CL-1 → 4-level ordinal enum
  - CL-2 → per-citation + per-source `default_credibility` (strict resolve, no silent default)
  - CL-3 → declared COI caps at `commentary`
  - CL-4 → 053 `note_type → role` off-field, one-step downgrade
  - CL-5 → declared by authoring agent
  - CL-6 → per-citation note frontmatter; note-writer writes, verifier shape-validates, gates read
- [x] Requirements are testable and unambiguous (every FR maps to ≥1 task + the
      contract's pure-function definition)
- [x] Success criteria are measurable (deterministic float; same-input-same-level;
      two-author agreement via guidelines)
- [x] Determinism boundary explicit (no LLM at gate/metric time — 053 #4/#5 + Principle IV)
- [x] Out-of-scope explicit (runtime judge, reputation scraping, spec rewrite, back-fill)
- [x] Dependencies explicit (053 ship gate; unblocks 030; reuses 020 `source_id`;
      enriches 048 v2)

## Cross-spec consistency (from /analyze)
- [x] Reuses (not forks) 053's `source_id → role` + `note_type → role` resolution
- [x] Reuses (not rewrites) the existing `source_urls` object form — no new
      top-level frontmatter key, no parser rewrite
- [x] 030 seam honoured: 055 delivers level + boundary; 030's other 3 metrics
      untouched; `tier2_source_ratio` references in 030 to be flipped at ship
- [x] 048 v2 annotation is read-only + degrade-never-error (matches 048 v2 ethos)
- [x] Principle V: stdlib + `pyyaml`, no new dependency
- [x] Spec 026 isolation honoured for new fixtures (`tmp_path`)

## Notes
- **HIGH-readiness**, with a single external gate: **053 must ship first** (the
  role resolution 055's `off_field` reuses). Captured as the tasks.md sequencing
  gate + plan.md Complexity risk. Not a spec defect — a sequencing fact.
- The author-facing guidelines doc (FR-009 / T023) is the load-bearing artifact
  for the "consistency" success criterion — flagged as the highest-value
  implementation deliverable.
- `/analyze` found no contradictions among spec ↔ contract ↔ plan ↔ tasks. One
  intentional decision recorded: 055 (not 030) owns the `tier2_source_ratio`
  calculator wiring end-to-end (plan Phase 2; tasks T018) — 030 remains the
  metric-family home and its contract is updated in the same task.
