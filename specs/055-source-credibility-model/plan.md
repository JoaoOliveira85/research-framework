# Implementation Plan: Source Credibility Model (Spec 055)

**Branch**: `055-source-credibility-model` · **Date**: 2026-06-03
**Spec**: [spec.md](./spec.md) · **Contract**: [contracts/credibility-model.contract.md](./contracts/credibility-model.contract.md) · **Research**: [research.md](./research.md)
**Status**: planned (post-clarify). Wave 2 / 0.10.0.

## Summary

Add a **contextual source-credibility axis** on top of spec 053's role/priority
authority axis: a 4-level ordinal enum (`primary > corroborated > commentary >
unvetted`), declared **per-citation** in note frontmatter (extending the existing
`source_urls` object form), modified by a COI cap and a 053-role topic-scope
downgrade, resolved by **one shared deterministic function** that the verifier and
spec-030's `tier2_source_ratio` calculator both consume. Authoring-time
declaration, gate-time read-only — preserving 053's determinism rule and
Principle IV. The author-facing guidelines doc (FR-009) is the durable "draw the
line consistently" artifact.

## Technical Context

- **Language**: Python 3.11+ (constitution). **Deps**: stdlib + `pyyaml` (already
  a dep). **No new runtime dependency** (Principle V).
- **Surfaces touched**:
  - NEW `src/research_framework/vault/credibility.py` — the enum + `effective_level`
    resolver + `off_field` + COI cap + the tier-2 boundary. Single source of truth
    imported by both the verifier path and 030's calculator (DRY — research.md
    open item resolved here in favour of a `vault/` helper, beside
    `vault/frontmatter.py`).
  - `src/research_framework/pipeline/settings.py` / sources loader — surface
    `default_credibility` off `data_sources[]` / module `sources.yaml`.
  - Verifier deterministic checks (`tests/pipeline/test_verifier.py` shape;
    the rule emitter) — add `IX-credibility-*` shape rules (FR-007).
  - `.agents/skills/note-writer` + `.agents/skills/source-relevance` +
    `.agents/skills/verifier` — authoring-time guidance (apply the guidelines;
    emit the fields).
  - Spec 030 calculator (`quality/metrics/source_quality.py`) — **wires** the
    4th metric using `vault/credibility.py`; ships as a 055 task OR a 030
    follow-up (see Phase 2).
  - NEW `docs/source-credibility.md` — the FR-009 guidelines (mirrors
    `docs/observability-strategy.md`).
- **Storage**: note frontmatter `source_urls[]` object entries (`credibility`,
  `coi`, `credibility_rationale`); optional `default_credibility` on sources. No
  DB column, no new sidecar (CL-6).
- **Testing**: deterministic unit tests for the resolver (table-driven over the
  contract's worked-examples matrix); verifier shape tests; a quality-harness
  fixture path for the 030 metric. Tier-2 (deterministic gate) per ADR-0008.

## Constitution Check

| Principle | Status | Note |
|-----------|--------|------|
| IV — No LLM self-assessment / deterministic gates | ✅ PASS | Resolver is a pure function; verifier shape-only; no agent at gate/metric time. |
| V — No new runtime dependency | ✅ PASS | stdlib + `pyyaml`. |
| VIII — Vault content is delivered, fixtures are test data | ✅ PASS | New fixtures are test data only. |
| IX — Vault-first / two-tier citation | ✅ REINFORCED | Credibility rides the existing Tier-2 `source_urls`; strengthens, never weakens, the citation contract. |
| 053 decisions #4/#5 (declared, deterministic) | ✅ PASS | Inherited verbatim (CL-5/CL-6). |
| TDD (ADR-0010 / constitution) | ✅ PLANNED | Resolver + verifier tests written first; foreman test-design eligible at implement. |

No violations; no Complexity-Tracking entries required.

## Project Structure (artifacts this spec produces)

```
specs/055-source-credibility-model/
├── spec.md                                  # CLARIFIED
├── plan.md                                  # this file
├── research.md                              # decisions D1–D6
├── contracts/
│   └── credibility-model.contract.md        # datum schema + resolution fn + validator/calculator contracts
├── checklists/requirements.md               # spec-quality checklist
└── tasks.md                                 # TDD task breakdown
```

Implementation (Wave 2) lands in `src/research_framework/vault/credibility.py`
(+ tests), verifier rule wiring, the three skill docs, `docs/source-credibility.md`,
and the 030 calculator entry.

## Phase 0 — Research ✅
See [research.md](./research.md). All six CL questions locked; alternatives
recorded; cross-spec seams (053 resolution reuse, 030 calculator seam, 048 v2
read-only join, `source_urls` object form) verified against the code.

## Phase 1 — Design ✅
See [contracts/credibility-model.contract.md](./contracts/credibility-model.contract.md):
the enum + definitions table, the frontmatter/source-default schema, the
`off_field` predicate, the `effective_level` resolution function (COI-cap before
topic-downgrade), the worked-example truth matrix, and the verifier / 030 /
048 v2 consumer contracts.

## Phase 2 — Task strategy (for `/speckit.tasks`)

- **TDD order**: contract worked-example matrix → failing resolver unit tests →
  `vault/credibility.py` → verifier shape rules (+ tests) → guidelines doc →
  note-writer/source-relevance/verifier skill updates → 030 calculator wiring (+
  baseline bless).
- **030 boundary decision**: 055 ships the resolver + a unit-tested tier-2
  boundary helper and a *ready-to-call* calculator function; the actual
  registration into 030's `source_quality` family + baseline re-bless is tagged so
  it can land in 055's tasks OR be handed to 030 — **recommend 055 owns it** end-
  to-end (it's the spec that unblocks the metric) and references 030's contract.
- **Fixture**: a small credibility fixture (notes with known levels/COI/off-field)
  drives both the resolver tests and the 030 metric baseline; reuse the 022/030
  fixture shape; honour spec 026's `tmp_path` isolation (no git-status pollution).

## Complexity & Risks

- **053 dependency timing** — 055's `off_field` reuses 053's `source_id → role`
  resolution. If 053 hasn't merged when 055 implements, the resolver's role lookup
  has no backing. *Mitigation*: gate 055 implementation behind 053 ship (Dependencies);
  the resolver treats unresolved role as "not off_field" (graceful, per contract §3).
- **Author burden** — per-citation fields add authoring work. *Mitigation*: per-
  source `default_credibility` covers uniform sources; only heterogeneous sources
  (HN/Reddit) need per-instance values; rationale is optional.
- **Boundary bikeshed** — where "tier-2" sits (below `corroborated`). *Mitigation*:
  fixed in the contract (§1) with 030 confirming; it's one constant, unit-tested.
- **Scope creep toward reputation scoring** — explicitly Out-of-scope; the model
  is declarative, not scraped.
