---
spec_number: 053
title: Plastic-but-Enforceable Source Authority
status: SHIPPED (PR #95) — Foundational + US1 (MVP) + US2 + US3 gate shipped; US3 ledger wire-in + Polish T020/T021/T022 remain follow-ups.
priority: high
priority_reason: |
  Gates BOTH upcoming vault runs (user decision 2026-06-02). The reference-vault has
  topic-dependent authority ("general semantics → official docs; team-specific →
  code/PR/ADR") that the current hardcoded code=trunk model cannot enforce
  correctly. Sequenced after spec 048 v2 (source-ledger), before the runs.
created: 2026-06-02
source_input: |
  docs/handoff-source-strategy.md — standalone design brief authored by the user
  2026-06-02. This spec is authored FROM that brief; the brief's locked design
  decisions are carried verbatim and its two open questions were confirmed with
  the user 2026-06-02 (see Clarifications).
---

**Status:** SHIPPED (PR #95) — `role`+`priority` schema, derived trunk, three
strategy-driven gates + trunk-inversion gate (`scripts/check_trunk_inversion.py`).
US3 ledger wire-in + Polish T020–T022 remain follow-ups. **Subsumes spec 046**
(vault-specialities plugin model).

# Feature Specification: Plastic-but-Enforceable Source Authority

**Feature Branch**: `053-source-authority-strategy`

## Problem

The framework hardcodes one source-authority model: **code = behaviour (the
trunk), Confluence = intent (a branch)**. The *same* pipeline must support
different per-vault source-of-truth strategies (journal-first, docs-first,
code-first, …) **without weakening enforcement**. The model must be **plastic**
(declarable per vault, adaptive per topic) yet **enforceable** (deterministic
gates, no reliance on LLM judgement).

The two-axis model is **already implemented end-to-end** — it is merely frozen
to the code/Confluence pair. **This feature generalizes existing code; it does
not add a new subsystem** (this is also why it *subsumes* spec 046's plugin
approach — specialities become *declared*, not *plugged in*).

## Locked design decisions (from the brief — do not re-litigate)

1. **Two axes, kept separate.** *Discovery order* = trunk (scout seed) +
   branches. *Authority* = per-source `role` + `priority`. **trunk ⊥ authority** —
   load-bearing decoupling (a later trunk change does not invalidate existing
   notes).
2. **Authority is claim-type-scoped, NOT a global ranking.** A claim's type
   selects the authoritative `role` (behaviour→code, intent→ADR/wiki,
   domain→journal/web); `priority` only breaks ties **within** a role. A global
   "highest priority wins" is rejected (it would let code override a wiki on a
   pure-*intent* question).
3. **Per-topic plasticity emerges for free** from `claim-type × source-availability`
   — no per-topic config. A vault with no behaviour source makes its domain
   source the effective trunk for those topics.
4. **"Immutability" is an authoring heuristic, not a runtime computation.** The
   user/agent assigns role/priority **at spec time**; runtime only reads the
   frozen declaration. The runtime agent NEVER judges authority.
5. **Enforcement = deterministic outcome gates on artifacts**, never LLM
   judgement. Every gate is a script with exit codes and its own unit tests.

## Clarifications

### Resolved 2026-06-02 (the brief's open questions, confirmed with the user)

- **Q1 — Does this subsume spec 046 (vault-specialities plugin model)?** **YES —
  subsume / close 046.** 053 delivers per-vault-type behaviour via *declared*
  `role`/`priority`, making 046's plugin subsystem unnecessary. 046 is tombstoned
  "superseded by 053 (generalize, don't pluginize)".
- **Q2 — v1 / v1.1 / v1.2 cut + trunk-derived-from-priority (no `trunk:` flag)?**
  **CONFIRMED.** v1 = populate `role`+`priority` on all `data_sources`, derive
  the trunk from highest priority (no explicit `trunk:` flag), generalize the 3
  gates + add the trunk-inversion gate + the 3 fixtures. Charter → v1.1; HOME.md +
  reconciliation → v1.2.
- **Q3 — Sequencing (added 2026-06-02).** **053 before BOTH vault runs.** The
  runs are gated behind `048 v2 → 053`. Both vaults use the generalized pipeline.

### Session 2026-06-02

- Q: How is a claim's type (behaviour/intent/domain) determined for the Grounding gate? → A: Per-note via `note_type` — each `note_type` declares its authoritative `role`; the gate resolves `note → note_type → authoritative role` (deterministic, spec-time, no runtime judgement).
- Q: How is the derived trunk resolved when the highest `priority` is shared by multiple sources? → A: Require a unique top priority — spec validation FAILs if ≥2 sources share the highest priority (no global role ranking; author disambiguates).
- Q: Must `authority_section`/`complementary_section` be declared on every `note_type`, or only drift-checked ones? → A: Opt-in — only note_types declaring BOTH sections are drift-checked; others are skipped (no drift dimension).

## User Scenarios & Testing *(mandatory)* — the fixtures ARE the outcome gates (write first, TDD)

### User Story 1 — Code-first vault still enforces (Priority: P1, regression)

Extend the existing `tests/fixtures/vault-code-first/`. Trunk = code; behaviour
notes cite code; intent↔implementation drift is flagged; the source-ledger shows
code `USED`. **Why P1**: the generalization must not regress the one model that
ships today.

**Independent Test**: run the 3 generalized gates against the code-first fixture
→ identical pass/fail to the pre-053 hardcoded gates.

### User Story 2 — Journal-first vault enforces with NO behaviour source (Priority: P1, the abstraction proof)

**NEW fixture** `vault-journal-first`: the derived trunk is a **domain** source
(peer-reviewed journals, `priority: 1`), **no behaviour source at all**; reddit
is a complementary domain source (`priority: 3`).

**Independent Test**: the Trunk-seed/attach gate demands `topics_from_trunk` =
journal (not code) and **does NOT error on a missing behaviour source**; the
Grounding gate requires the authoritative role for each claim type; the ledger
shows journal `USED`. This proves the model is plastic without per-topic config.

### User Story 3 — Bad-faith seeding FAILs deterministically (Priority: P1)

**NEW fixture** `vault-bad-faith`: the spec's derived trunk is code, but the
scout report seeds topics only from Confluence (path of least resistance).

**Independent Test**: the **trunk-inversion gate FAILs** — the ledger shows code
(trunk) `NOT_REACHED` while intent (branch) is `USED`. This is the deterministic
"bad-faith / path-of-least-resistance" detector.

## Requirements *(mandatory)*

### Schema (`research.spec.md`) — FR-001..003
- **FR-001**: Populate `role: behaviour|intent|domain` + `priority: int` on
  **every** `data_sources[]` entry (today only code-first entries carry them).
  Each `note_type` declares its **authoritative `role`** (the claim-type it
  anchors) — this is how a note's claim-type is resolved at gate time
  (`note → note_type → authoritative role`), keeping authority declared at spec
  time and never runtime-judged (per Clarifications Q1).
- **FR-002**: **Trunk is derived** = the highest-priority source; its `role`
  scopes which claim-types it anchors. **No new `trunk:` flag in v1.**
  **"Highest priority" ≡ the minimum `priority` value (per Analyze F3)** — NOT
  the existing hardcoded `priority == 1` sentinel (`validate_cycle.py:556`),
  which this generalizes. The minimum value MUST be held by **exactly one**
  source — spec validation FAILs if ≥2 sources share it (per Clarifications Q2),
  so the derived trunk is unambiguous. **If no unique minimum exists** (a tie, or
  no `priority` signal at all) **⇒ no derivable trunk** → the trunk-seed gate
  no-ops via the pure-domain guard (FR-006). No global role ranking is introduced
  (decision #2); the author disambiguates. (Lower-priority ties *within* a role
  remain fine — they only affect within-role authority tie-breaking, not trunk
  derivation.)
- **FR-003**: **No new `identity:` field.** Citation→source attribution reuses
  spec-020 `source_id` (`url`/`path`/`name` via `manifest.source_id_from`).
  Access/connection config stays in `settings.yaml`/`vault-config.yaml`/module
  `manifest.yaml` — out of scope.

### Generalize three existing gates (code-hardcoded → strategy-driven) — FR-004..006
- **FR-004 — Grounding gate** (`scripts/check_code_source_coverage.py`): a claim
  of type T must cite ≥1 source whose `role` is authoritative for T. **The
  claim-type T is the authoritative `role` declared on the note's `note_type`
  (per Clarifications Q1)** — the gate resolves `note → note_type →
  authoritative role T`, then verifies the note cites ≥1 source whose `role` is
  T via `citation → source_id → owning data_source → role` resolution (reuse
  `sources_loader.py`, replacing `classify_url` regex-guessing). "needs a code
  source" → "needs the authoritative role for this claim type"; code-first is
  the T=behaviour case.
- **FR-005 — Drift gate** (`scripts/check_intent_drift.py`): compare the note's
  `authority_section` vs `complementary_section` (declared on its `note_type`)
  instead of the hardcoded `## Current Behaviour` / `## Stated Intent`. Rename
  the frontmatter flag `intent_implementation_drift → authority_drift`. **The
  gate is opt-in per `note_type` (per Clarifications Q3)**: only note_types that
  declare BOTH `authority_section` and `complementary_section` are drift-checked;
  note_types without both (e.g. pure-domain reference types) are skipped — no
  artificial authority/complementary split is forced on them.
- **FR-006 — Trunk-seed/attach gate** (`scripts/validate_cycle.py::check_termination_v2`):
  `topics_from_code → topics_from_trunk`; `parent_code_topic_id →
  parent_trunk_topic_id`; generalize `_spec_primary_repos` +
  `_repo_match_signatures` / `_source_file_matches_repo` to resolve via
  `source_id` across module kinds. **Critical conditional**: only enforce
  trunk-seeding when a trunk is *derivable* — a pure-domain vault must NOT trip
  "trunk empty" (mirror the existing `if signatures:` guard, ~line 773). The
  scout-report contract change (`topics_from_code → topics_from_trunk`) is
  v2→v3; ride the existing `_warn_deprecated_termination_shape_once` path for
  old-shape reports.

### Trunk-inversion gate — FR-007 (on the Source-Consideration Ledger, spec 048 v2)
- **FR-007**: The derived trunk source MUST resolve to ledger verdict `USED` (or
  an *explained* `ACCESS_FAIL`). If the trunk is `NOT_REACHED` / `SKIPPED_RELEVANCE`
  while branches are `USED` → **FAIL** (the bad-faith detector). **Hard-depends
  on spec 048 v2 FR-017..021.**

## Dependencies & relationships

- **Hard dependency: spec 048 v2** (Source-Consideration Ledger) — FR-007 builds
  on it. 053 cannot ship before 048 v2.
- **Generalizes** specs 002 (codebase-vault code-first — the model being
  generalized), 019 (roles behaviour/intent/domain), 020 (`source_id`,
  `source_id_from`, `sources_loader.py`).
- **Subsumes spec 046** (vault-specialities plugin model) — tombstoned.
- **Sequenced before both vault runs** (reference-vault + codebase-vault).
- Deferred phases touch spec 027 (git snapshot/rollback) and spec 035
  (cross-cycle-digest migration report).

## Deferred — sequenced follow-ons; do NOT build in v1

- **v1.1 — Charter**: `scope.audience` + `expertise_level` (enum) + `depth_band`
  (advisory floor/ceiling) + top-level `success_metrics`. Relevance gating:
  below-floor / above-ceiling candidates → ledger `SKIPPED_RELEVANCE` citing the
  charter clause. Spec-time authoring in `.agents/skills/vault-spec/SKILL.md`:
  the spec agent infers role/priority **with per-source rationale**, flags
  low-confidence items, freezes; spec validation FAILs if any source lacks
  role+priority(+rationale). Test artifact completeness + that escalation fires —
  never the LLM's judgement.
- **v1.2 — HOME.md + reconciliation**: human-facing `HOME.md` (render
  `scripts/vault_metrics.py` stats + recent notes + a quick-ref Charter
  projection) with machine/human ownership markers. Steering checkboxes feed the
  **fast frontier only** (never charter/strategy) as deterministic, thresholded,
  provenance-tagged signals. Convergent reconciliation for spec/trunk changes:
  `strategy_hash` change detection → LLM-free re-grounding pass (re-runs the 3
  gates) → migration report extending **spec 035** → non-destructive supersession
  reusing `migration/superseded_paths.py` + git snapshot/rollback from **spec
  027**. Add the `vault-trunk-flip` fixture here (trunk=code → flip to
  trunk=Confluence → re-run; behaviour notes survive, frontier re-seeds,
  migration report records the delta, nothing deleted).

## Guardrails (non-negotiable, per constitution)

- TDD: write the failing fixtures/tests before implementation.
- Gates are deterministic, LLM-free, with their own unit tests (pattern:
  `tests/scripts/test_check_intent_drift.py`).
- No silent drops: every source not used carries a ledger verdict (048 v2 FR-019).
- `research.spec.md` is user-owned — read it, never rewrite it.

## Out of scope (v1)

- Source access/connection config (stays in settings/vault-config/manifest).
- A new `trunk:` flag or `identity:` field.
- LLM-judged authority at runtime.
- The Charter (v1.1) and HOME.md/reconciliation (v1.2).

## Success Criteria

- The `vault-journal-first` fixture parses + runs with **no behaviour source** and
  its gates enforce journal-as-trunk without erroring on missing behaviour.
- The `vault-code-first` regression fixture's gate verdicts are unchanged from
  the pre-053 hardcoded behaviour.
- The `vault-bad-faith` fixture FAILs the trunk-inversion gate (trunk `NOT_REACHED`,
  branch `USED`).
- All 4 gates are deterministic + unit-tested; `research.spec.md` is never rewritten.
