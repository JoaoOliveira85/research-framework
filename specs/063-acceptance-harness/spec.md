---
spec_number: 063
title: Acceptance harness — framework-generic gates + shipped-ledger reconciliation + authority/credibility grading
status: SHIPPED 1.0.0rc3 (framework-side; US4/US5 in-vault pack authored per-vault)
target_version: 1.0.0rc3
created: 2026-06-05
source_input: |
  2026-06-05 codebase-vault rc1 acceptance evaluation, §4 (full). The probe pack
  (`codebase-vault-acceptance-probes.md`) was written against framework 0.7.x; we
  are on 1.0.0rc2 (specs →060). Defects 3.2–3.5 were caught only by going *off the
  pack*; a literal run would have passed structural Phase 0 and mis-fired Phase 2B.
  The evaluation recommends (and the operator approved, 2026-06-05) expanding the
  harness — FULL §4 in rc3 — and splitting framework-generic gates from domain probes.
---

**Status:** shipped(2026-06-06, PR #126) — SHIPPED **1.0.0rc3** (2026-06-06, PR #126, squash `2d217be`) — rc3 wave
(sibling specs 061, 062; amendments to 028 + 048 v2). Operator scope decision
2026-06-05: **full §4**. Framework-side delivered: `./vault acceptance` verb, six
generic gates (GA-001..006), ledger↔citation reconciliation, 053/055 authority +
credibility grading vs the vault's own derived trunk, in-vault domain-probe
discovery, clean-exit auto-run. US4/US5 in-vault probe packs are authored per-vault.

> **Note on code homes:** `/speckit.plan` Phase-0 reconciles the exact module homes
> (new `./vault acceptance` surface vs extending spec 006 `./vault audit`; the
> ledger reader; the indexer's duplicate/inbound-link helpers already touched by
> spec 051 FR3 + spec 062 FR2). Where this spec's guess is wrong, the plan wins.

# Feature Specification: Acceptance harness

**Feature Branch**: `063-acceptance-harness`
**Created**: 2026-06-05

## Clarifications (resolved 2026-06-05)

| Q | Decision | Notes |
| --- | --- | --- |
| **Q1 — surface** | **New `./vault acceptance` verb** (discoverable; distinct from `./vault audit` / health). | The generic gates (US1/US2) live in-framework behind this verb (US5). |
| **Q2 — gate severity** *(in-spec default taken)* | **FAIL** (non-zero exit): rejected-notes-remain, untracked-git, constrained-exit-reported-as-done, `$0`-telemetry. **WARN**: template-version drift. | A run/build can gate on the FAILs; drift is advisory. |
| **Q3 — domain-probe home** *(in-spec default taken)* | Generic gates ship **in the framework**; **domain probes live in-vault** under `_pipeline/acceptance/`. The per-domain pack shrinks to domain probes. | Framework owns generic; the vault owns domain. |
| **Q4 — auto-run** *(in-spec default taken)* | Runs **automatically at clean exit** (records the scorecard, FR-006) **and** on-demand via `./vault acceptance`. | Catches regressions without a human remembering to run it. |
| **Q5 — US3/US4 scope** | **In rc3** — operator chose full §4 (2026-06-05). | Authority/credibility grading (US3) + domain rebalance (US4) ship in rc3, not as a fast-follow. |

All five resolved; no remaining open questions. Shipped 1.0.0rc3 (PR #126).

## Why this spec exists

The acceptance harness is the instrument we use to judge a vault run — and the rc1
evaluation showed the instrument has blind spots that a *real* framework defect can
slip through. Two structural problems:

1. **Version drift.** The pack is a 0.7.x artifact run against a 1.0.0rc2 framework.
   It still treats the spec-048-v2 source-ledger as "future" and hand-joins
   artifacts; it checks for a duplicate *corpus tree* but not duplicate *notes* or
   *rejected* notes. Defects 3.2–3.5 were caught only because the evaluator went
   off-script. A literal run would have **passed** Phase 0 and **mis-fired** Phase 2B.
2. **Generic and domain checks are tangled.** The pack mixes framework-generic gates
   (Phase 0/2/2B — true of *any* vault) with business-specific GOLD probes
   (fingerprint / convergence). Splitting them lets the generic gates be **reused by
   the tech- and feeds-vaults** and, ideally, shipped *inside the framework* so every
   generated vault inherits them.

This matters now because two more live validation runs (reference-vault, feeds-vault) are
imminent. Without this, they get graded by the same blind harness. The generic gates
+ ledger reconciliation (US1, US2) are the load-bearing protection; the grading
deepening (US3, US4) and the pack restructure (US5) complete the picture.

## User Scenarios & Testing

### User Story 1 — Framework-generic acceptance gates, shipped in-framework (Priority: P1)

Every generated vault inherits a deterministic, LLM-call-free set of structural +
integrity gates that catch the defect classes 3.2–3.5 + 3.1's symptom, runnable on
demand (and, per Q4, at clean-exit). This is the MVP — it is reusable across *all*
vaults and turns "the evaluator noticed by going off-script" into "the harness fails
the build."

**Why this priority**: it directly protects the next two validation runs and is pure
deterministic checking over artifacts the framework already emits.

**Independent Test**: run the gates against the rc1 codebase-vault snapshot; they must
FAIL on the real defects (rejected notes, ` 2.md` dups, $0 telemetry, 6/12
truncation reported as not-complete) — i.e. reproduce the off-script findings
deterministically.

**Acceptance Scenarios** (the §4.1 gate set):

1. **No verifier-rejected notes remain** in the indexed corpus on a clean exit
   (catch 3.2; pairs with spec 062 FR1).
2. **No duplicate note files** — extends the old "one corpus tree" check to also flag
   `… N.md` siblings AND content-hash duplicates (catch 3.3; shares the detector with
   spec 062 FR2).
3. **Git integrity (spec 050 / Principle X)** — no untracked content under
   `data_vault/`, no duplicate per-cycle commits, research branch squash-merged on a
   clean exit (catch 3.3).
4. **Run-completion semantics** — parse the run report: a **constrained exit
   (max_cycles / budget) MUST NOT read as "done"**; surface *configured vs actual*
   cycles and per-category % of target. This is the gate that would have made the
   6/12 truncation the headline (consumes spec 061 FR4's recorded provenance).
5. **Cost / telemetry sanity** — `total_cost_usd > 0`, tokens recorded, within budget
   (catch 3.5; consumes the spec-028 amendment's codex telemetry).
6. **Template-version drift** — every note's `template_version` matches the shipped
   templates.

### User Story 2 — Phase-2B uses the shipped ledger and cross-checks it against citations (Priority: P1)

The harness stops hand-joining artifacts and instead reads the first-class
`cycle-NNN-source-ledger.json` / `scripts/source_ledger.py`, **and** cross-checks the
ledger's per-source verdicts against the notes' actual `source_urls`. **The
disagreement is the finding**: in rc1 the ledger asserted ACCESS_FAIL/PIPELINE_DROP on
every required source while the notes cited code/PR/Jira at 100%/71%/63% — a false
negative that would have produced multiple bogus SA-4 CRITICALs.

**Why this priority**: the ledger is the designated eval lens for all three validation
runs; a lens that false-fails on the dominant evidence path can't be trusted to grade
them. Pairs with the spec-048-v2 amendment (which makes the ledger itself reconcile).

**Independent Test**: on the rc1 snapshot, the reconciled Phase-2B reports the
ledger↔citation *mismatch* as the finding (not a wall of ACCESS_FAIL), and re-grades
SA-3/SA-4 against the reconciled view.

**Acceptance Scenarios**:

1. Phase-2B reads `cycle-NNN-source-ledger.json` directly (no hand-join instructions).
2. A source the ledger marks failed but the notes demonstrably cite → flagged as a
   **ledger/citation disagreement**, not a source failure.
3. SA-3 / SA-4 are graded against the reconciled view.

### User Story 3 — Citation grading understands spec 053 authority + spec 055 credibility (Priority: P2)

Notes now carry `role` / `priority` / derived-trunk (spec 053) and `credibility:
primary` / `coi: true` per source_url (spec 055). Extend the citation probes (the
pack's P10/P11) to grade **authority/trunk correctness** and **credibility tiers** —
not just two-tier presence. This makes the "code is the map; US→PR→code" model
machine-checkable.

**Why this priority**: high-signal but depends on US1's plumbing; not required to
*unblock* the next run, but completes the eval depth the operator asked for (full §4).

**Independent Test**: a fixture note whose citations invert the declared authority
(cites a low-priority role as trunk) is FLAGGED; a correctly-grounded note passes.

**Acceptance Scenarios**:

1. A note citing against its vault's derived-trunk authority is flagged (053).
2. Credibility tiers + `coi` are graded, not just presence (055).

### User Story 4 — Domain probes rebalanced for breadth (Priority: P2)

Keep the high-signal GOLD anchors (P1 fingerprint `variantId` trap, P12 convergence
confidence) but the GOLD set is over-indexed on one product sub-area. Add lighter breadth
probes across other declared products/flows so a vault that legitimately covers a
*different* slice isn't scored as a total miss on Goal 1/3.

**Why this priority**: improves fairness/signal of the domain grade; orthogonal to the
generic gates.

**Independent Test**: a vault that covers products B/C instead of the GOLD-anchored
product A scores partial-breadth credit rather than zero.

**Acceptance Scenarios**:

1. Breadth probes exist across ≥N declared products/flows beyond the GOLD anchors.
2. GOLD anchors P1 + P12 are retained verbatim.

### User Story 5 — Generic/domain split; generic gates live in the framework (Priority: P3)

Factor US1 + US2 into the **framework** (a `./vault acceptance` verb or shared probe
lib — Q1) so every generated vault inherits them; the per-domain pack shrinks to just
the domain probes (US3/US4). Ties into spec 006 (vault audit) and the spec 036 / 023
assistant-framework direction.

**Why this priority**: the structural payoff (reuse across tech-/feeds-vaults), but it
depends on US1/US2 existing first.

**Acceptance Scenarios**:

1. The generic gates are invokable via the framework on any vault (not copy-pasted per
   domain).
2. The domain pack is reduced to domain probes; generic checks are referenced from
   the framework surface.

### Edge Cases

- A vault with **no** code-first sources (journal-first, per spec 053) — the
  authority grade (US3) must use that vault's *derived* trunk, not assume code.
- A clean exit with **zero** cycles (nothing to research) — run-completion gate must
  distinguish "nothing to do" from "truncated".
- A runtime with genuinely-unparseable cost (pre-028-amendment codex) — the telemetry
  gate must FAIL-loud, not silently pass on `$0` (the whole point of catch 3.5).

## Requirements *(functional, condensed)*

- **FR-001**: Ship the §4.1 generic gate set (US1 scenarios 1–6) as deterministic,
  LLM-call-free checks over existing artifacts.
- **FR-002**: Phase-2B reads the shipped ledger and reports ledger↔citation
  disagreement as the finding (US2).
- **FR-003**: Citation grading covers spec-053 authority/trunk + spec-055 credibility
  (US3).
- **FR-004**: Domain probes rebalanced — GOLD anchors retained + breadth probes added
  (US4).
- **FR-005**: Generic gates are framework-resident and reusable across vaults; the
  domain pack shrinks to domain probes (US5).
- **FR-006**: A per-vault acceptance scorecard artifact is emitted
  (`_pipeline/acceptance/REPORT-<date>.md` per the probe-pack §5 template) summarising
  gate verdicts + the run-completion / cost / coverage headline.

## Success criteria

- **SC-001**: Run against the rc1 codebase-vault snapshot, the harness deterministically
  reproduces the off-script findings (rejected notes, dup files, $0 telemetry, 6/12
  truncation-not-complete, ledger/citation mismatch) — zero of them require a human to
  "go off the pack".
- **SC-002**: The generic gates run unchanged against the reference-vault and feeds-vault
  (proving reuse).
- **SC-003**: A constrained exit can never be graded "done"; a $0-cost run can never
  pass the telemetry gate.

## Relationship to existing specs (important — avoid overlap)

- **Spec 022 (E2E quality harness)** is *build-time regression* over synthetic
  fixtures (3 metric families × 3 fixtures, baseline diff in `build.sh --quality`).
  **063 is post-run acceptance** over a *real* generated vault. Complementary, not a
  replacement — 063 does not touch the 022 baselines.
- **Spec 006 (vault audit)** — `./vault audit` health report. US5's generic gates may
  *extend* 006 rather than add a new verb (Q1).
- **Spec 048 v2 (ledger)** — US2 *consumes* the ledger; the **048-v2 amendment**
  (sibling rc3 change) makes the ledger itself reconcile against citations. US2 is the
  harness-side cross-check; the amendment is the framework-side fix. They pair.
- **Spec 028 amendment** — US1 scenario 5 (telemetry gate) consumes codex cost
  capture from that amendment; without it the gate just FAILs on $0 (still correct).
- **Specs 053 / 055** — US3 grades the authority + credibility frontmatter those
  specs introduced.
- **Spec 062** — shares the duplicate-note detector (FR2) and the rejected-note
  invariant (FR1); 062 *prevents*, 063 *detects*.

## Open questions — RESOLVED 2026-06-05

All five resolved in the **Clarifications** block at the top of this spec; original
text retained below for provenance.

- **Q1 — Surface: new `./vault acceptance` verb vs extend spec 006 `./vault audit`?**
  A dedicated verb is discoverable; extending 006 avoids verb proliferation. Which?
- **Q2 — Generic gate severity model.** Which §4.1 gates are FAIL (block/non-zero
  exit) vs WARN? (proposed: rejected-notes / untracked-git / constrained-as-done /
  $0-telemetry = FAIL; template-drift = WARN.)
- **Q3 — Domain-probe home + split mechanism.** Do domain probes live in-vault
  (`_pipeline/acceptance/`), as a repo-side pack, or both? How is the generic/domain
  boundary expressed so the framework owns generic and the vault owns domain?
- **Q4 — Auto-run on clean exit?** Does `./vault acceptance` run automatically at the
  end of a clean run (and record the scorecard), or on-demand only?
- **Q5 — Scope confirmation for US3/US4.** Operator chose full §4; confirm US3
  (authority/credibility grading) + US4 (domain rebalance) ship in rc3 rather than as
  a fast-follow, given their P2 priority.

## Provenance

- **Primary source**: 2026-06-05 codebase-vault rc1 acceptance evaluation, §4 (full)
  + the appendix evidence index (`_pipeline/acceptance/REPORT-2026-06-05.md`,
  `scripts/source_ledger.py`, `cycle-002-source-ledger.json`).
- **Operator decision**: 2026-06-05 — grouped rc3 wave, **full §4 harness scope**.
- **Constitution**: no amendment (acceptance tooling, not a new principle).
- **Cross-references**: specs 006, 022, 028 (amendment), 048 v2 (amendment), 053, 055,
  062; assistant-framework direction (036 / 023).

Shipped 1.0.0rc3 (2026-06-06, PR #126).
