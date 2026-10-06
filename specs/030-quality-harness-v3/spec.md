# Feature Specification: Quality Harness v3

**Feature Branch**: `030-quality-harness-v3`
**Created**: 2026-05-22
**Status**: planned — Clarified 2026-06-03 (Wave 1 / 0.9.0) — see Clarifications. Next: `/speckit.plan`.
**Input**: User description: "Spec 022 shipped v1+v2 with 3 fixtures × 3 metric families × fake-agent only. Three deliberate deferrals remain: (a) the 4th metric family `source_quality` (Shannon entropy, broken-source rate, spec-source utilization, tier-2-source ratio); (b) the deferred 3 fixtures (`embedded-firmware`, `childcare`, `gaming`); (c) the highest-value deferred signal — with-vault-vs-without-vault `/ask` comparison. The 022 v1/v2 cuts were deliberate. v3 closes them. Also folds in the audit's 022 v2 typed-step-result holes: ScoutResult.sg_trips, ResearchResult.notes_rejected, missing exit_code — the harness's typed-result hooks are currently hollow."

## Clarifications

### Session 2026-06-03

- **Q1 (FR-012 — ship `template_section_compliance` in v3 or defer?) → defer to v4.**
  Keep v3 focused on the `source_quality` family + fixtures + the with/without-vault
  comparison (the run-scoring signal); section-compliance overlaps spec 053 and is
  sequenced after.
- **Q2 (FR-014 — hotfix tracking as a harness metric or RELEASE.md checklist?) →
  `docs/RELEASE.md` retrospective checklist item.** It's a release-process signal,
  not a per-cycle vault-quality metric; keep it out of `build.sh --quality`.
- **Q3 (post-plan, 2026-06-03 — the 4th metric `tier2_source_ratio`) → DROPPED from
  v3; deferred to spec 055 (Wave 2).** Planning surfaced that "source tier" is
  modeled nowhere (only a prose Tier-1/Tier-2 list in ROADMAP) and that a static
  per-module label is conceptually wrong — source credibility is **contextual**
  (per-author: HN users vary), **conflict-of-interest-aware** (an OpenAI paper
  praising GPT is low-authority), and **topic-scoped** (an in-field authority is
  out of place off-topic). v3 ships the other **3** `source_quality` metrics;
  `tier2_source_ratio` waits for spec 055 to establish consistent credibility
  guidelines. (FR-001, US1, Key Entities, SC-001, Dependencies updated.)

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Source quality is a measurable harness signal (Priority: P1)

The harness's 022 v1 metrics catch coverage drift, note-quality regression, and cycle health. Source quality — the 4th deferred metric family — is the missing signal. Without it, the framework cannot detect: source diversity collapse (all notes from one source), broken-source rate creep, spec-declared sources going unused, tier-2 sources displacing tier-1 sources.

**Why this priority**: Source quality is the upstream signal for note quality. A vault with degraded source quality WILL eventually produce degraded notes — but the note-quality metric only catches it after the regression has shipped. Source quality is the leading indicator.

**Independent Test**: Run the harness on each fixture and verify **3** new metrics emit in the report: `source_diversity_shannon`, `broken_source_rate`, `spec_source_utilization`. Each has a baseline + a regression threshold. *(A 4th metric, `tier2_source_ratio`, was dropped from v3 — see Clarifications 2026-06-03; it needs a real source-credibility model, deferred to **spec 055** / Wave 2.)*

**Acceptance Scenarios**:

1. **Given** a fixture with N sources, M of which are unused this cycle, **When** the harness reports, **Then** `spec_source_utilization` = `(N-M)/N`.
2. **Given** a fixture where 3 of 10 sources fail preflight, **When** the harness reports, **Then** `broken_source_rate` = 0.3.
3. **Given** a baseline at `source_diversity_shannon`, **When** a cycle's source mix collapses (one source dominates), **Then** the harness fires a WARN (>5%) or FAIL (>15%) per the moderate regression gate.

---

### User Story 2 — Three deferred fixtures probe domain-specific failure modes (Priority: P2)

The 022 v1 cut shipped `tech-lite`, `source-poor`, `source-rich`. The 3 deferred fixtures (`embedded-firmware`, `childcare`, `gaming`) each probe a specific failure mode the existing fixtures don't catch:

- `embedded-firmware`: highly technical, dense domain vocab, tests note-density and citation-precision
- `childcare`: non-technical, narrative domain, tests prompt-vs-domain mismatch and Wikipedia-style source dominance
- `gaming`: edge-case domain with novel terminology that benefits hugely from vault, tests with-vs-without `/ask` delta

**Why this priority**: Each deferred fixture maps to a real-world vault the user wants to maintain. The harness without them passes for `tech-lite` and may not catch failures specific to non-technical domains.

**Acceptance Scenarios**:

1. **Given** 6 fixtures live in `tests/fixtures/quality/`, **When** `./build.sh --quality` runs, **Then** all 6 are exercised and their baselines committed.
2. **Given** the harness fails on a non-tech-lite fixture, **When** the report is generated, **Then** the failure clearly attributes which fixture's metric drifted.

---

> **Landed on `main` 2026-08-30** from the long-lived `030-quality-harness-v3` branch so the design work is not stranded on a branch. **Not implemented** — tracked by issue #47.

### User Story 3 — With-vault-vs-without-vault `/ask` comparison is the killer quality signal (Priority: P1)

If a feature shipped to the framework doesn't improve the with-vault-vs-without-vault `/ask` delta, it's NOT quality work — it's noise. This is the MOST IMPORTANT signal but it requires live LLM (the baseline run has zero vault context; the vault run uses Principle IX citations).

**Why this priority**: This is the quality framework's reason to exist. Without it, every other metric is a proxy.

**Acceptance Scenarios**:

1. **Given** a fixture with a canonical question set, **When** the harness runs each question against a baseline (no vault) and against `/ask` (with vault), **Then** the report includes 4 deltas: factual accuracy, specificity, citation density (Principle IX), hallucination rate.
2. **Given** a baseline shows `accuracy_delta = +0.4` (vault adds 40% accuracy), **When** a cycle regresses to `+0.2`, **Then** the harness fires WARN per moderate gate. Below +0.0 is FAIL.
3. **Given** the `live_llm` cost concern, **When** the comparison runs, **Then** it's gated by an opt-in marker (`live_llm` AND `quality_comparison`), NOT in the default `./build.sh --quality` invocation.

---

### User Story 4 — Typed step results populate fully (Priority: P1)

The audit found 022 v2's typed-step-result hooks are hollow: `ScoutResult.sg_trips` always `[]`, `ResearchResult.notes_rejected` always `[]`, `ResearchResult` has no `exit_code`. The harness falls back to filesystem scraping silently. Fix the typed results so the harness consumes the real signal.

**Why this priority**: Quality-blindness bug — the harness "works" but its inputs are degraded. Tightly coupled to spec 022 v2's intent; correct to fold here.

**Acceptance Scenarios**:

1. **Given** a cycle where SG-002 trips, **When** the cycle completes, **Then** `ScoutResult.sg_trips` contains the trip record.
2. **Given** a cycle where verifier rejects 3 notes, **When** the cycle completes, **Then** `ResearchResult.notes_rejected` lists those 3 notes.
3. **Given** a cycle where the research phase aborts early, **When** the cycle completes, **Then** `ResearchResult.exit_code` is non-zero.
4. **Given** the harness consumes `ResearchResult`, **When** it generates `cycle_health._sg002_trips_for_cycle`, **Then** it uses the typed `sg_trips` (no filesystem fallback).

---

### Edge Cases

- What happens when `live_llm` is unavailable (no `claude` CLI, no API key)? `/ask` comparison must skip gracefully, not fail.
- How does the harness handle a fixture where the canonical question set is empty (a fixture pre-question-set)?
- For `broken_source_rate`, what counts as "broken"? Preflight failure, 5xx response, timeout, returned-empty? Define each.
- For Shannon entropy of source diversity, what's the unit of measurement (notes per source vs citations per source vs facts per source)?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The harness MUST compute **3** new `source_quality` metrics per cycle: `source_diversity_shannon`, `broken_source_rate`, `spec_source_utilization`. *(`tier2_source_ratio` is DEFERRED to spec 055 / Wave 2 — Clarifications 2026-06-03; it requires a contextual source-credibility model the system does not yet have.)*
- **FR-002**: Each new metric MUST have a baseline committed under `tests/fixtures/quality/baselines/<fixture>.baseline.json` and respect the moderate regression gate (>15% fail, >5% warn).
- **FR-003**: Three new fixtures MUST be added to `tests/fixtures/quality/`: `embedded-firmware`, `childcare`, `gaming`. Each fixture follows the same shape as existing fixtures (vault root, spec, sources, canonical question set).
- **FR-004**: A new harness step MUST run with-vault-vs-without-vault `/ask` comparison, computing 4 deltas: `accuracy_delta`, `specificity_delta`, `citation_density_delta`, `hallucination_delta`.
- **FR-005**: The `/ask` comparison MUST be gated by an opt-in marker (e.g., `@pytest.mark.quality_comparison` + `live_llm`). The default `./build.sh --quality` invocation MUST NOT trigger live LLM calls.
- **FR-006**: A new CLI flag `./build.sh --quality-deep` (or `bash build.sh --quality --comparison`) MUST trigger the comparison when explicitly invoked. The release pipeline `.github/workflows/release.yml` SHOULD NOT use this flag (cost concern).
- **FR-007**: `pipeline/steps/scout.py::ScoutResult.sg_trips` MUST be populated with all SG-001/002/003 FAIL/WARN trips. Harness `cycle_health._sg002_trips_for_cycle` MUST read from `sg_trips`, not filesystem.
- **FR-008**: `pipeline/steps/research.py::ResearchResult.notes_rejected` MUST list all verifier-rejected notes per cycle.
- **FR-009**: `pipeline/steps/research.py::ResearchResult` MUST have an `exit_code` field assigned from the step's return value.
- **FR-010**: The harness MUST stop scraping the filesystem as a fallback for `sg_trips` / `notes_rejected` / research exit code once FR-007/008/009 are met.
- **FR-011**: The 022 v2 postprocess hook `postprocess.run_postprocess` MUST return non-empty `wikilink_fixes` / `CoverageDelta()` when wikilinks were fixed / coverage moved. Currently stubbed.
- **FR-012**: `template_section_compliance` (% notes per cycle including their note-type's required sections; 2026-05-20 triage item #26, `docs/TODO.md#restoration-notes`) is **deferred to v4** (Clarifications Q1). v3 stays focused on the `source_quality` family + the deferred fixtures + the with/without-vault comparison; section-compliance also overlaps spec 053's authority/section work, so it is better sequenced after.
- **FR-013**: Cost watch-item enhancement: record `total_cost_usd` + `budget_utilization` + `source_utilization` alongside quality metrics (2026-05-20 triage item #28). Record-only; gating is spec 033's domain.
- **FR-014**: Per-release-hotfix tracking (2026-05-20 triage item #8): "post-release seam-hotfix count within 7 days" is tracked as a **`docs/RELEASE.md` retrospective checklist item, NOT a harness metric** (Clarifications Q2) — it is a release-process signal, not a per-cycle vault-quality measure the harness computes from artifacts; folding it into `build.sh --quality` would conflate the two concerns.

### Key Entities

- **`source_quality` metric family**: 3 new metrics in the harness output (`tier2_source_ratio` deferred to spec 055).
- **Three new fixtures**: `embedded-firmware`, `childcare`, `gaming`. Each is a fully-shaped fixture vault per the 022 v1 contract.
- **Canonical question set**: Per-fixture file (e.g., `tests/fixtures/quality/<name>/canonical-questions.json`) listing 5-10 question+expected-shape pairs.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Running `./build.sh --quality` reports 3 source_quality metrics per fixture (9 new measurements per run for the 3 v1 fixtures; 18 once v3 fixtures land).
- **SC-002**: The 3 new fixtures land with baselines committed under `tests/fixtures/quality/baselines/`.
- **SC-003**: Running `bash build.sh --quality-deep` against a `tech-lite`-equivalent fixture reports the 4 deltas. Baseline accuracy_delta ≥ 0.2 (vault improves accuracy by ≥20% on canonical questions).
- **SC-004**: The hollow typed-step-result hooks (sg_trips, notes_rejected, exit_code) are populated. Filesystem-fallback code in `cycle_health.py` is removed; tests catch any reintroduction.
- **SC-005**: Total `./build.sh --quality` wall-clock time grows by no more than 50% with 6 fixtures vs 3 (current ~5 min → max ~7:30).

## Assumptions

- The harness architecture from 022 v1/v2 extends cleanly to a 4th metric family without rework. (Spot-check during planning.)
- The 3 new fixtures can be authored in ~1 day each (lean on the `tech-lite` template). Total ~3 days for fixture creation.
- The `/ask` comparison is opt-in and not part of the regular CI/release gate (cost-prohibitive).
- The 022 v2 typed-step-result holes are local bugs in `pipeline/steps/{scout,research,postprocess}.py`, not architectural — fixing them doesn't require harness changes beyond removing filesystem fallback.

## Dependencies

- Spec 028 (dispatch telemetry) — cost-watch-item enhancement in FR-013 depends on real `cost_usd` in sidecars.
- Spec 026 (fixture isolation) — 3 new fixtures need the tmp_path-isolation work or they'll pollute git status.
- **Spec 055 (source-credibility model, Wave 2)** — owns the deferred `tier2_source_ratio` metric. The "source tier" concept needs a contextual, conflict-of-interest-aware, topic-scoped credibility model (a static per-module Tier-1/Tier-2 label is wrong); 030 will consume it once 055 establishes the guidelines.

## Acceptance coverage

Draft — evidence cells will be populated by `/speckit.tasks` for
this spec. Listed for the ADR-0008 guard so the spec is accepted
into the queue (the guard refuses any G/W/T-bearing spec without
this section).

| User Story | Evidence |
|------------|----------|
| US1 — Source quality is a measurable harness signal | _(deferred to tasks.md — populated by `/speckit.tasks`)_ |
| US2 — Three deferred fixtures probe domain-specific failure modes | _(deferred to tasks.md — populated by `/speckit.tasks`)_ |
| US3 — With-vault-vs-without-vault `/ask` comparison is the killer quality signal | _(deferred to tasks.md — populated by `/speckit.tasks`)_ |
| US4 — Typed step results populate fully | _(deferred to tasks.md — populated by `/speckit.tasks`)_ |

## Out of Scope

- Cost-enforcement (hard cap with graceful pause). Spec 033 owns that.
- New metric families beyond the 4 listed (`security_quality`, `freshness_quality`, etc.). Future v4 or beyond.
- Fixtures beyond the 6 total. Vault Specialities (Horizon 3) may eventually add more.
- The 022 v1's deliberate "fake-agent only" cut for the gating loop. v3 adds an OPT-IN live-LLM mode (FR-005, FR-006); the gating loop stays fake-agent-only.
