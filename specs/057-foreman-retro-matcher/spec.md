# Feature Specification: Foreman Retro Coverage — Tolerant Matching Mode

**Feature Branch**: `057-foreman-retro-matcher`
**Created**: 2026-06-03
**Status**: SHIPPED [Unreleased] (mechanism only — PR #183, squash `c24cd22`,
2026-07-01). `--tolerant` file-level matching mode is implemented and tested
(T001–T020, T026–T027). **Remaining**: the SC-001 retro-rollout tasks
(T021–T025 — back-filling tolerant `### Testing Requirements` blocks onto
specs 018/022/025/028) are not done; tracked as a low-priority follow-up.
**Input**: User description: "Run /speckit.specify for the un-specced 'Foreman retro pass on already-shipped specs' idea in docs/TODO.md."

> **Origin**: `docs/TODO.md` → "Open ideas (un-triaged)" → *Foreman retro pass on
> already-shipped specs (LOW priority)*. This spec is the live home; the TODO entry
> is annotated `(now spec 057)`.

## Clarifications

### Session 2026-06-03

- **Q1 (mode surface)** → **A**: Opt-in CLI flag `--tolerant` on the existing verifier; default remains strict. The flag stamps `matching_mode: "tolerant"` on the JSON `summary` and human header (not a separate tool or subcommand).
- **Q2 ("covered" bar)** → **A**: File exists **and** `pytest <file>` reports ≥1 `PASSED` test in that file (same PASSED-only rule as strict node runs — skipped/xfail/empty do not count). No AST import-of-UUT check (that stays Arm B per `docs/foreman.md`).
- **Q3 (retro targets + sequencing)** → **A**: Canonical set **018, 022, 025, 028** (listed below). Recommended rollout order **028 → 018 → 022 → 025** (028 has the reference `tasks.md` enrichment at `fc24a43`). Authoring file-only blocks is follow-up work tracked in `tasks.md` Phase 7; this spec ships the matcher only.
- **Q4 (durability)** → **A**: Verdict is **stdout only** — human text + `--json` report. No new ledger file, DB, or committed artifact surface.

## Retro targets (canonical)

| Order | Spec | Rationale |
|-------|------|-----------|
| 1 | **028** dispatch-telemetry | Reference retro `tasks.md` enrichment exists (`test-design/028-retro` @ `fc24a43`); highest foreman-signal density. |
| 2 | **018** `018-testing-strategy` | Foundation spec; many tests, no `Testing Requirements` blocks today. |
| 3 | **022** `022-e2e-quality-harness` | Quality metrics; fixture tests are the insurance surface. |
| 4 | **025** `025-simplify-pass` | Large refactor; file-level retro is enough for insurance. |

## Overview

The foreman verification pattern (ADR-0010, `docs/foreman.md`) gates a spec's PR with
two arms: a deterministic Arm-A coverage verifier
(`scripts/foreman/verify_test_coverage.py`) and an Arm-B semantic review subagent.
Arm-A relies on **strict naming** — each task's `### Testing Requirements` block must
name exact test filenames *and* function names, with an optional TDD commit-timeline
flag.

That strict-naming policy is correct for **new** work but makes the foreman useless for
**retroactive** validation of specs that shipped *before* the pattern existed (e.g.
018 / 022 / 025 / 028). Those specs have no `Testing Requirements` blocks and were not
authored to the strict-naming policy, so Arm-A reports `NO_REQUIREMENTS` and skips them.
We therefore have no foreman-grade signal that the pre-pattern specs are actually
covered by tests — only that they passed the `build.sh` smoke gate (ADR-0007).

This feature adds an **opt-in tolerant matching mode** to the Arm-A verifier: a
requirement is satisfied when the named test **file exists** and has **at least one
passing test**, ignoring exact function names and the TDD commit-timeline. That makes it
cheap to author a *file-only* retro requirements list for a legacy spec and get a
coverage verdict — insurance that legacy test coverage is real, without rewriting each
old `tasks.md` to the strict policy. Strict mode stays the default and is unchanged.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Retroactively verify a pre-pattern spec's coverage (Priority: P1)

As a maintainer, I want to run the Arm-A verifier in a tolerant mode against a
pre-pattern spec that lists only the test **files** it expects, and get a coverage
verdict based on file-existence plus at-least-one-passing-test-per-file, so I can
confirm a legacy spec has real test coverage without rewriting its `tasks.md` to the
strict naming policy.

**Why this priority**: This is the entire point — turning the foreman's
`NO_REQUIREMENTS` skip on legacy specs into an actual coverage verdict. With just this,
the pre-pattern coverage gap is closeable. It is the MVP.

**Independent Test**: Author a file-only `Testing Requirements` list for one legacy spec,
run the verifier in tolerant mode, and confirm it returns a per-file PASS/FAIL verdict
(not `NO_REQUIREMENTS`).

**Acceptance Scenarios**:

1. **Given** a legacy spec whose `tasks.md` lists test files (no function names) under a
   tolerant requirements block, **When** the verifier runs in tolerant mode, **Then** it
   emits a PASS only if every named file exists and has ≥1 passing test.
2. **Given** the same spec, **When** one named file is missing or has zero passing tests,
   **Then** the verdict is FAIL and identifies the offending file.
3. **Given** a spec authored to the strict policy, **When** it is run in tolerant mode,
   **Then** it still PASSes (tolerant is a relaxation, never stricter).

---

### User Story 2 - Never confuse a tolerant PASS with a strict PASS (Priority: P2)

As a maintainer, I want a tolerant-mode verdict to be clearly labelled as tolerant in the
report, so a relaxed PASS (file-existence only) is never mistaken for a strict,
TDD-verified PASS.

**Why this priority**: A tolerant PASS is weaker evidence than a strict PASS; conflating
them would erode the foreman's credibility. Important, but only meaningful once tolerant
mode exists.

**Independent Test**: Run both modes on the same spec and confirm the report distinguishes
the verdict tiers unambiguously.

**Acceptance Scenarios**:

1. **Given** a tolerant-mode run, **When** the verdict is produced, **Then** the report
   marks it as tolerant (distinct from a strict verdict) in both human-readable and
   machine-readable output.
2. **Given** a tolerant PASS, **When** it is consumed by any downstream gate, **Then** it
   cannot be recorded as a strict/TDD-verified PASS.

---

### User Story 3 - Cheap retro authoring (file-only requirements) (Priority: P3)

As a maintainer, I want to express a legacy spec's expected coverage as a plain list of
test files (no exact function names, no TDD flag), so writing a retro requirements block
costs minutes, not hours.

**Why this priority**: Retro is explicitly *insurance, not diagnosis* (the specs already
passed the smoke gate). If retro authoring is expensive, it won't happen. Lowest priority
because it's a convenience on top of US1.

**Independent Test**: Author a file-only list for a legacy spec and confirm the verifier
accepts it without requiring function names or a TDD flag.

**Acceptance Scenarios**:

1. **Given** a file-only requirements list, **When** the verifier runs in tolerant mode,
   **Then** it does not require function names or a TDD-timeline flag.

---

### Edge Cases

- **Named file exists but has zero passing tests** → tolerant FAIL for that file.
- **Named file is missing** → tolerant FAIL (missing coverage), file identified.
- **Spec has no requirements block at all** → still `NO_REQUIREMENTS` (tolerant mode needs
  at least a file list; it does not invent one).
- **A strict-authored spec run in tolerant mode** → PASS (relaxation must never flip a
  strict PASS to FAIL).
- **A file with only skipped/xfail tests** → treated as zero passing tests → FAIL.
- **A tolerant verdict consumed by a strict gate** → must surface as "tolerant", never be
  silently upgraded.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The Arm-A coverage verifier MUST offer a **tolerant matching mode** that is
  **opt-in** and never the default.
- **FR-002**: In tolerant mode a requirement is satisfied iff the named test **file
  exists** AND it has **at least one passing test**, **ignoring** exact function names and
  the TDD commit-timeline.
- **FR-003**: A tolerant verdict MUST be **visibly labelled as tolerant** via
  `summary.matching_mode: "tolerant"` (JSON) and a `MODE: tolerant` banner (human text).
  Tolerant runs MUST NOT emit `tdd_timeline_ok: true` or imply TDD verification; strict
  runs MUST emit `matching_mode: "strict"` (JSON) for downstream consumers.
- **FR-004**: Tolerant mode MUST accept a **file-only** requirements shape (filenames
  without function names and without a TDD flag).
- **FR-005**: **Strict mode MUST remain the default and behave identically** to today for
  all existing specs (no regression).
- **FR-006**: A named file that is **missing** or has **zero passing tests** MUST yield a
  tolerant **FAIL** that identifies the offending file (no false PASS).
- **FR-007**: The tolerant verdict MUST be **deterministic** — same tree + same
  requirements ⇒ same verdict (Principle IV; it is a script, not an LLM judge).
- **FR-008**: Tolerant mode MUST be a **relaxation** of strict mode: any spec that PASSes
  strict MUST also PASS tolerant.

### Key Entities *(include if feature involves data)*

- **Tolerant requirements block**: a legacy spec's `### Testing Requirements` expressed as
  a list of test files (no function names, no TDD flag).
- **Per-file coverage result**: file path → {exists?, has ≥1 passing test?} → PASS/FAIL.
- **Mode-tagged verdict**: the spec-level verdict plus the mode (strict | tolerant) that
  produced it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Each retro target (018, 022, 025, 028) can be run through tolerant mode
  and receive a per-file coverage verdict instead of `NO_REQUIREMENTS`, once a
  file-only `### Testing Requirements` block is authored for that spec's `tasks.md`
  (rollout sequenced 028 → 018 → 022 → 025 per Clarifications).
- **SC-002**: 100% of tolerant verdicts are distinguishable from strict verdicts in the
  output.
- **SC-003**: Tolerant mode returns 0 false PASSes — every PASS has all named files present
  with ≥1 passing test each (verified by injecting a missing/empty file and observing FAIL).
- **SC-004**: Strict-mode verdicts are unchanged for 100% of existing specs (no regression).
- **SC-005**: Re-running tolerant verification on an unchanged tree yields an identical
  verdict every time (determinism).

## Assumptions

- This is a **relaxation of the existing** Arm-A verifier
  (`scripts/foreman/verify_test_coverage.py`) under ADR-0010 / `docs/foreman.md`, not a new
  tool or a change to the Arm-B semantic-review subagent.
- **LOW priority — insurance, not diagnosis**: the pre-pattern specs already passed the
  `build.sh` smoke gate (ADR-0007); retro coverage is added confidence, not a fix for a
  known gap.
- A reference sketch exists at the unmerged branch `test-design/028-retro` (commit
  `fc24a43`); it can seed the design but is not authoritative.
- Retro requirements lists are authored by a human or a subagent per spec; tolerant mode
  does not generate them. The canonical retro target set and sequencing live in this
  spec (Clarifications + Retro targets table); block authoring is Phase 7 in `tasks.md`.
- Tolerant mode is selected only via `--tolerant`; output is ephemeral (stdout / `--json`),
  not persisted to a coverage ledger.
- **No new runtime dependency** (Principle V); the verdict is **deterministic** (Principle
  IV — no LLM grading).
- Strict + TDD remains the policy for **new** specs; tolerant mode exists only for retro.

## Out of Scope

- Auto-generating `Testing Requirements` blocks for legacy specs (a human/subagent still
  writes the file list).
- Any change to the Arm-B semantic-review subagent or its verdict.
- Relaxing strict mode or the TDD-timeline check for **new** specs.
- Backfilling tolerant requirements blocks for every historical spec in this spec's scope
  (this spec delivers the *mechanism*; which legacy specs to retro and when is a follow-up).

## Acceptance coverage

| User Story | Evidence |
|------------|----------|
| US1 — Retroactively verify a pre-pattern spec's coverage | _(deferred to tasks.md — implement-ready 2026-06-03; tests land with /speckit.implement)_ |
| US2 — Never confuse a tolerant PASS with a strict PASS | _(deferred to tasks.md — implement-ready 2026-06-03; tests land with /speckit.implement)_ |
| US3 — Cheap retro authoring (file-only requirements) | _(deferred to tasks.md — implement-ready 2026-06-03; tests land with /speckit.implement)_ |
