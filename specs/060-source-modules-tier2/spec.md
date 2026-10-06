# Feature Specification: Source-Module Tier 2+ Port Wave (governance umbrella)

**Feature Branch**: `060-source-modules-tier2`
**Created**: 2026-06-03
**Status**: ✅ **Batch-1 SHIPPED [Unreleased] / 1.0.0rc5** — `github` (PR #136, squash `a8d5240`) + `atlassian` (PR #137, squash `642ead5`), per the demand-driven **MCP-free** batch-1 reprioritization (Session 2026-06-08, PR #135). Umbrella otherwise IMPLEMENT-READY (2026-06-03; clarify Q1–Q5 + plan + research + contracts + tasks + analyze complete). Governs the ROADMAP tier ladder; **no `src/` runtime module**.
**Input**: User description: "Run /speckit.specify for the un-specced Tier 2+ source-module ports on docs/ROADMAP.md's 'Source Modules roadmap'."

> **Origin**: `docs/ROADMAP.md` → "Source Modules roadmap (tiered)". This spec is the
> governing umbrella for that ladder; the ROADMAP section is annotated `(governed by spec
> 060)`.

> **What this spec is — and is NOT.** It is a **sequencing + governance** spec for the
> *wave* of Tier 2+ source-module ports. It does **NOT** re-specify the spec-020 module
> architecture (amend 020 directly if that's needed), and it does **NOT** create a separate
> speckit spec per module — individual ports follow the spec-020 five-file module template.
> Its job is the things that template doesn't decide: *which* modules to port, *in what
> order*, against *what fixed acceptance bar*, and *how* to decide when a module can't fit
> 020's contracts.

## Clarifications

### Session 2026-06-03 (Q1–Q5 locked)

- **Q1 (first Tier-2 batch + criteria weighting)** — **Ranked order** (highest → lowest):
  `hackernews` → `wikipedia` → `newsletters` → `blog_posts` → `conference_talks` →
  `github_extras`. **Weights**: real vault demand **40%**, 020 contract fit **25%**, porting
  effort (lower is better) **20%**, dependency cost (lower is better) **15%**. **Batch-1
  kickoff**: `hackernews` only; `wikipedia` is batch-1 #2 and starts after the acceptance
  bar is validated on the first port (no parallel Tier-2 ports until one green ship).
- **Q2 (dependency-exception policy)** — **Tier 2 = stdlib-only, no exceptions.** **Tier 3+**
  default **defer** until a stdlib-only path exists; an optional-extra (à la `[budget]` /
  `[reports]`) is allowed only via the **020-amendment gate** with explicit maintainer
  approval (`pyproject.toml` extra + port PR rationale). **Never** an unconditional new
  core runtime dependency (Principle V).
- **Q3 (umbrella scope)** — **Governance + ladder only.** This spec authors the
  prioritization rubric, the fixed acceptance-bar contract, the 020-amendment procedure,
  and the authoritative tier ladder. It does **not** enumerate per-module implementation
  tasks or speckit sub-specs — ports use the spec-020 five-file template under
  `<vault>/modules/<name>/`.
- **Q4 (Tier 4 / Parked)** — **On the ladder, out of active scope.** `social_bookmarklet`
  (Tier 4) and the Parked set stay on the ladder with status `future` / `parked`; un-parking
  or Tier-4 activation is a future decision under this spec's gate, not part of batch-1 work.
- **Q5 (relationship to spec 038)** — **060 owns which/when/acceptance; 038 owns resilience
  polish.** The 060 acceptance bar is the **port ship gate** (020 template, hermetic contract
  tests, 022 hold-or-improve, mandatory 051 `preflight()`, dependency policy). Spec 038
  (EMPTY vs FAILED, rate limits, raw capture, install probes) is **not** duplicated in 060;
  it sequences **after** the first Tier-2 port validates the bar end-to-end, or opportunistically
  per module when a port's network surface needs it — never a substitute for the 060 bar.

### Session 2026-06-08 — demand-driven batch-1 reprioritization (Jira/Confluence/GitHub)

Real-vault demand (the dominant 40% selection weight, Q1) overrides the original
`hackernews`-first batch ordering. The two upcoming live runs (codebase-vault rebuild +
reference-vault) consume Jira, Confluence, and GitHub as primary sources, and the project is
deliberately moving **MCP-free** (so any runtime — claude / codex / cursor-agent / ollama —
can drive a vault regardless of MCP support). Three governance changes follow:

- **batch-1 is now `{github, atlassian}`** (was `hackernews`). `hackernews` drops to a later
  batch — it has no live-run demand pulling it forward.
- **`notion/confluence` is un-parked.** The earlier "park Notion/Confluence behind MCP"
  stance assumed MCP would cover them; the MCP-free pivot makes that false. Confluence is
  promoted into Tier-2 active **as part of a combined `atlassian` module** (Jira + Confluence
  on one REST v3 surface, one auth, one module) rather than a standalone Confluence port —
  the two share Atlassian Cloud auth and site, so a single module is the correct grain.
- **`github_extras` is pulled forward as `github`.** A first-class `github` module (PRs /
  issues / releases via the `gh` CLI) ships now. It is **deliberately distinct from `code`**:
  `code` owns *local working copies* (filesystem path triggers, `git rev-parse HEAD`);
  `github` owns *remote GitHub surfaces* (URL triggers, `gh api`). The boundary is recorded
  as a spec-020 amendment (see that spec's Clarifications, Session 2026-06-08).

This batch intentionally overrides the 060 "land one green Tier-2 ship before parallel ports"
kickoff guidance: `github` and `atlassian` are ported in parallel (worktrees, as the
reddit/rss Wave-2 ports were) because both are on the live-run critical path. Both still meet
the full 060 ship bar (020 five-file template, hermetic `_BIN`/`_FIXTURE` contract tests,
022 hold-or-improve, mandatory 051 `preflight()`, zero new runtime deps). The Ollama runtime
that makes "MCP-free on any vendor" real is tracked separately under spec 047 (promoted v1).

## Overview

Spec 020 shipped the source-module architecture (subprocess-isolated modules under
`<vault>/modules/<name>/`), and Wave 2 ported the five Tier-1 modules (`youtube`, `reddit`,
`rss`, `oreilly`; `arxiv` subsumed by `rss`) — released as 0.6.0. The ROADMAP then lists a
long tail of further modules across tiers:

- **Tier 2** *(active scope)*: newsletters, hackernews, wikipedia, blog_posts,
  conference_talks, github_extras
- **Tier 3** *(ladder only; defer-by-default)*: pdfs, podcasts, epub (tricky), twitter,
  mastodon/bluesky
- **Tier 4** *(ladder only; future)*: social_bookmarklet (user-initiated CSV import)
- **Parked** *(ladder only)*: slack/discord exports, email, notion/confluence, goodreads

Today those are tracked only as a roadmap table with "post-revival, gated by the 022
harness." There is no spec that fixes the **selection criteria**, the **per-module
acceptance bar**, or the **contract-amendment decision gate** — so each port risks
re-litigating the bar or quietly working around 020's contracts. This umbrella spec
formalizes the port wave so every Tier 2+ module lands at consistent quality and the 020
architecture stays intact.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Criteria-based prioritization of the next modules (Priority: P1)

As a maintainer planning the next source-coverage wave, I want the Tier 2+ modules
prioritized by documented criteria (real vault demand, porting effort, fit with 020's
contracts, dependency cost), so effort goes where it pays off instead of being picked
ad-hoc.

**Why this priority**: Without an ordering rule, ports happen by whim and the highest-value
sources may wait behind low-value ones. This is the umbrella's core value.

**Independent Test**: Apply the documented criteria to the Tier 2 list and produce a ranked
order with a one-line rationale per module; confirm the ranking is reproducible from the
criteria.

**Acceptance Scenarios**:

1. **Given** the Tier 2+ ladder, **When** the prioritization criteria are applied, **Then**
   each module has a position and a one-line rationale tying it to the criteria.
2. **Given** new real-world vault demand signal, **When** priorities are revisited, **Then**
   the ladder can be re-ordered by the same criteria without changing the acceptance bar.

---

### User Story 2 - One fixed acceptance bar for every port (Priority: P1)

As a maintainer porting a Tier 2+ module, I want a single, fixed acceptance bar so every
port lands at consistent quality without re-arguing the standard each time.

**Why this priority**: Consistency is what keeps a dozen+ ports from drifting in quality.
Co-P1 with prioritization — together they make the wave repeatable.

**Independent Test**: Take one module port and check it against the fixed bar (020 template,
hermetic contract tests, 022 non-regression, mandatory preflight, dependency policy);
confirm the bar is unambiguous enough to pass/fail the port.

**Acceptance Scenarios**:

1. **Given** a completed module port, **When** it is checked against the acceptance bar,
   **Then** every bar item is objectively pass/fail (020 template present; hermetic contract
   tests present; 022 harness holds-or-improves; mandatory `preflight()` per spec 051; zero
   new runtime deps unless explicitly approved).
2. **Given** a port that regresses the 022 harness, **When** it is evaluated, **Then** it is
   blocked from shipping until metrics hold or improve.

---

### User Story 3 - A clear gate when a module doesn't fit 020 (Priority: P2)

As a maintainer hitting a module that can't satisfy 020's contracts, I want a defined
decision gate — amend spec 020 (a deliberate spec-amendment) vs defer the module — so we
never accumulate per-module workarounds that erode the architecture.

**Why this priority**: Architecture erosion is slow and expensive; an explicit gate
prevents it. Important once ports are underway.

**Independent Test**: Present a module whose source shape violates an 020 contract; confirm
the spec routes it to an 020 amendment or an explicit deferral, not a local hack.

**Acceptance Scenarios**:

1. **Given** a module that needs to break an 020 contract, **When** the gate is applied,
   **Then** the outcome is either a recorded 020 spec-amendment or an explicit deferral —
   never a per-module workaround.

---

### User Story 4 - The tier ladder is the coverage source of truth (Priority: P3)

As a maintainer/operator, I want the tier ladder to be the single tracked source of truth
for source-surface coverage (shipped / next / parked), so coverage status is always legible
and not duplicated in divergent lists.

**Why this priority**: Prevents the doc-drift the project explicitly fights. Lowest priority
because it's hygiene around the substantive US1–US3.

**Independent Test**: Confirm there is exactly one authoritative module-coverage list and it
reflects current ship status.

**Acceptance Scenarios**:

1. **Given** a module ships or is parked, **When** the ladder is consulted, **Then** its
   status is current and no competing coverage list contradicts it.

---

### Edge Cases

- **Module needs a new runtime dependency** (e.g. a PDF/epub parser) → Tier 3 default defer;
  optional-extra only via the 020-amendment gate with explicit approval — never an
  unconditional new core dep (Principle V).
- **Module needs auth/credentials** (e.g. `github_extras`, `twitter`) → reuse the oreilly
  auth-gated pattern + key-leak-safety test; part of the acceptance bar (FR-004).
- **Module can't be made hermetically testable** → fails the acceptance bar; deferred until
  a hermetic contract-test approach exists.
- **Module overlaps an existing one** (à la `arxiv` ⊂ `rss`) → subsume, don't duplicate.
- **Module regresses the 022 harness** → blocked from shipping (US2 / FR-007).
- **A whole tier's demand never materializes** → stays on the ladder as `not_prioritized`;
  not half-built.
- **Resilience gaps (EMPTY vs FAILED, rate limits)** → tracked under spec 038; not a reason
  to weaken the 060 acceptance bar.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The spec MUST define **prioritization criteria** for selecting which Tier 2+
  modules to port and in what order (real vault demand 40%, 020 fit 25%, porting effort 20%,
  dependency cost 15%) with a **locked Tier-2 ranking** in `research.md`.
- **FR-002**: The spec MUST define a **single fixed acceptance bar** every Tier 2+ port
  satisfies — normative in `contracts/module-port-acceptance-bar.contract.md`: (a) spec-020
  five-file template; (b) hermetic contract tests; (c) spec-022 hold-or-improve; (d) mandatory
  `preflight()` per spec 051; (e) dependency policy per FR-004.
- **FR-003**: The spec MUST define the **contract-amendment gate** in
  `contracts/020-amendment-gate.contract.md`: a module that cannot fit 020 triggers an
  explicit **spec-020 amendment** or an explicit **deferral** — never a per-module workaround.
- **FR-004**: The spec MUST define how a module requiring a **new dependency**
  (optional-extra, Tier 3+ only) or **credentials** (auth-gated pattern, Tier 2 allowed) is
  handled or deferred — see `research.md` dependency table.
- **FR-005**: The **tier ladder** MUST be maintained as the single tracked source of truth in
  `contracts/tier-ladder.contract.md`, each module carrying status
  (`shipped` / `next` / `in_progress` / `future` / `parked` / `not_prioritized`).
- **FR-006**: The spec MUST NOT re-specify the spec-020 architecture nor replace per-module
  porting work — it **sequences and governs** the wave; individual ports follow the 020
  template (no speckit sub-spec per module).
- **FR-007**: A port that **regresses the spec-022 harness** MUST be blocked from shipping
  until metrics hold or improve (`build.sh --quality` gate).
- **FR-008**: The spec MUST sequence **spec 038** as resilience polish **after** the 060
  acceptance bar is validated on at least one Tier-2 port — 038 MUST NOT be folded into the
  060 bar (no duplication).

### Key Entities *(include if feature involves data)*

- **Tier ladder**: tiered candidate modules + per-module status — authoritative in
  `contracts/tier-ladder.contract.md`.
- **Module port**: a single source module under the spec-020 five-file template at
  `<vault>/modules/<name>/` (reference: shipped Tier-1 modules under
  `src/research_framework/modules/<name>/`).
- **Acceptance bar**: pass/fail conditions in `contracts/module-port-acceptance-bar.contract.md`.
- **020 contract-amendment gate**: decision procedure in `contracts/020-amendment-gate.contract.md`.
- **Prioritization rubric**: weighted criteria in `research.md`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every Tier 2+ module on the ladder has a recorded status and a one-line
  priority rationale derived from the criteria (Tier 2 fully ranked; Tier 3+ status only).
- **SC-002**: 100% of Tier 2+ ports that ship satisfy the fixed acceptance bar (checklist in
  contract; objectively verifiable per port).
- **SC-003**: Zero shipped ports contain a per-module workaround that violates an 020
  contract — every mismatch resolved by 020 amendment or explicit deferral.
- **SC-004**: Zero Tier 2+ ports that regress the spec-022 harness ship.
- **SC-005**: Exactly one authoritative module-coverage list exists (`tier-ladder.contract.md`);
  ROADMAP mirrors it at doc-sync time only.

## Assumptions

- Builds on **spec 020** (module architecture, SHIPPED 0.4.0), **Wave-2 Tier-1 ports**
  (0.6.0), **spec 022** (quality harness — Principle I gate per port), and **spec 051**
  (mandatory `preflight()`). **Spec 038** is a follow-on resilience pass, not a 060 bar item.
- **Governance-only deliverables** under `specs/060-source-modules-tier2/`; implementation
  work for ports lands in `src/research_framework/modules/<name>/` + vault `modules/` copies
  per existing Tier-1 precedent — not in this spec dir.
- **Gated post-revival**: Milestone A/B/C vault signal informs demand scores; rubric is
  re-runnable without changing the bar.
- **Principle V**: Tier 2 = stdlib-only; Tier 3+ optional-extra only via amendment gate.
- **Principle IV** unaffected — extractors remain subprocess-isolated; 022 harness is the
  deterministic quality gate (Principle I).
- **Principle VII** upheld — every shipped module must produce consultable external signals;
  ports that cannot log skip reasons fail the bar.

## Out of Scope

- Re-specifying the spec-020 architecture (amend spec 020 directly).
- Writing per-module speckit specs or per-module task breakdowns (020 template only).
- Tier 1 (shipped 0.6.0).
- **Active port work** for Tier 3+, Tier 4, or Parked modules (ladder tracking only).
- Spec 038 resilience implementation (sequenced separately; see FR-008).
- New `src/` umbrella runtime code — this spec produces docs/contracts + one kickoff port PR.

## Acceptance coverage

| User Story | Evidence |
|------------|----------|
| US1 — Criteria-based prioritization of the next modules | _(deferred to tasks.md — implement-ready 2026-06-03; tests land with /speckit.implement)_ |
| US2 — One fixed acceptance bar for every port | _(deferred to tasks.md — implement-ready 2026-06-03; tests land with /speckit.implement)_ |
| US3 — A clear gate when a module doesn't fit 020 | _(deferred to tasks.md — implement-ready 2026-06-03; tests land with /speckit.implement)_ |
| US4 — The tier ladder is the coverage source of truth | _(deferred to tasks.md — implement-ready 2026-06-03; tests land with /speckit.implement)_ |
