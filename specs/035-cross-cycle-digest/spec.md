# Feature Specification: Cross-Cycle Digest

**Feature Branch**: `035-cross-cycle-digest`
**Created**: 2026-05-27 (promoted from `docs/TODO.md` during the post-Wave-1 doc restructure).
**Status**: shipped(2026-06-04, PR #117) — SHIPPED 1.0.0rc1 (PR #117, 2026-06-04) — deterministic, LLM-call-free `./vault digest` verb (7 sections) over local cycle artifacts; new `pipeline/digest/` package. **Hard dep on spec 050** (append-only git) reconciled below; soft deps on 030/055 (richer signals) are optional enrichments, not gates.

**Input**: A `./vault digest --since <date>` verb that produces a weekly markdown roll-up of cycle changes (new notes, source-quality drift, coverage delta, cost summary, "Strongest Signals" + "Gaps"). Mirrors the legacy feeds-vault Phase-7 report style that users actually read. Today, `./vault research` cycles already commit structured git history per-cycle, but there's no human-digestible weekly summary; users running unattended cycles fall back to `git log --since="1 week ago"` which works as an interim workaround but doesn't render coverage delta, source value drift, or surface the "strongest signals" the way the old feeds-vault Phase-7 report did.

## Clarifications

### Session 2026-06-03 (Q1-Q5 locked)

Q1-Q3 are the spec's original open questions; **Q4-Q5 were surfaced by a
2026-06-03 code audit** reconciling this 2026-05-27 draft against artifacts that
shipped since (050 append-only git; 030/055 source signals).

- **Q1 (FR-002) — Cadence.** **BOTH**: `--since <date>` (ISO8601) is the
  primitive; `--last-week` / `--last-month` / `--last-quarter` are convenience
  flags resolving to date ranges.
- **Q2 (FR-007) — "Strongest Signals" ranking (no LLM).** **Deterministic top-5
  by composite score** = inbound-citation/link count + source-quality delta +
  freshness (days-since-write). Pure heuristic over frontmatter + the graph; no
  agent call. *(055 credibility folding was offered and declined — keep v1 free
  of a 055 dependency.)*
- **Q3 (FR-013) — Scheduling.** **No auto-run.** Explicit `./vault digest` only;
  the README documents a cron/launchd one-liner.
- **Q4 (FR-006, audit) — "Source Quality Drift" signal.** `sources.db` has **no
  quality-score column**. v1 derives drift from **real shipped sources.db data**:
  per-source `notes_generated` / `notes_referencing` deltas across the range,
  `degraded`-state transitions (the `source-incidents` log), and
  `consecutive_empty_cycles` crossings. (Spec 030's `source_quality` metrics are
  a *future optional enrichment*, NOT a v1 gate.)
- **Q5 (FR-010/FR-011, audit) — per-cycle source of truth post-050.** Spec 050
  **squash-merges per-cycle commits into one run-level commit on `main`**, so
  per-cycle SHAs are not in main's `git log`. The **filesystem is authoritative**:
  enumerate cycles from `_pipeline/cycles/cycle-NNN/` + `cycle-<N>-report.md`; use
  git only for the run-level commit range + dates; "ship SHA" = the run squash
  commit (or the retained `research/<ts>` branch SHA on a constrained exit).

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Weekly digest replaces manual `git log` spelunking (Priority: P1)

The operator runs `./vault digest --since 2026-06-01` (or `./vault digest --last-week`). Within 5 seconds, `_pipeline/digests/digest-2026-06-01--2026-06-08.md` exists with 7 sections: Strongest Signals, Gaps, New Notes by Category, Source Quality Drift, Coverage Delta, Cost Summary, Cycle Index. The operator reads it in <5 minutes and decides whether to intervene.

**Why this priority**: Users running unattended cycles need a sub-5-minute weekly briefing. Without it, the cycles run but the operator doesn't engage; engagement is what catches regressions. The 2026-05-15 feeds-vault trial run produced 2 weeks of unattended cycles before the operator noticed a regression — a weekly digest would have caught it on day 2.

**Independent Test**: Set up a fixture vault with 3 cycles' worth of commits across a 1-week window. Run `./vault digest --since <start-date>`. Verify: a markdown file is produced at the expected path; it contains all 7 sections; each section has content (not "no data" placeholders) for the cycles in scope.

**Acceptance Scenarios**:

1. **Given** a vault with 3 cycles run over the last 7 days, **When** the operator runs `./vault digest --since 2026-06-01`, **Then** `_pipeline/digests/digest-2026-06-01--2026-06-08.md` exists and is readable.
2. **Given** the digest output, **When** the operator opens it, **Then** the 7 sections are present and populated (Strongest Signals, Gaps, New Notes by Category, Source Quality Drift, Coverage Delta, Cost Summary, Cycle Index).
3. **Given** a fresh vault with NO cycles in scope, **When** the operator runs `./vault digest --since <date>`, **Then** the command exits 0 with a "No cycles in scope" message; no empty digest file is created.

---

### User Story 2 — Digest is deterministic + idempotent (Priority: P2)

Running `./vault digest --since 2026-06-01` twice produces byte-identical output (modulo timestamps in the header). The digest's content is purely a function of (a) git history in the commit range, (b) `_pipeline/cycles/cycle-N-report.md` files, (c) `_pipeline/sources.db` snapshot, (d) `_pipeline/coverage-targets.json` snapshot. No LLM call. No external API call.

**Why this priority**: Idempotency makes the digest a reliable artifact to attach to PRs, share with collaborators, or feed into spec 040's delivery layer. LLM-call-free keeps it cheap + reproducible.

**Acceptance Scenarios**:

1. **Given** the same input commit range and unchanged underlying state, **When** the operator runs `./vault digest` twice, **Then** the two output files are byte-identical (excluding the rendered-at timestamp in the header).
2. **Given** the digest implementation, **When** running on a vault with no internet access, **Then** the digest still completes successfully (no external dependencies).
3. **Given** the digest is purely deterministic, **When** the operator wants to regenerate one from history, **Then** the same `--since` produces the same digest months later (modulo software version changes).

---

### User Story 3 — "Strongest Signals" surface the high-value notes (Priority: P2)

A digest's "Strongest Signals" section lists the top 5 notes by composite score (per Q2). For each, it shows: the note's wikilink, why it ranked (e.g. "+0.85 source-quality delta, 3 inbound citations, fresh"), and a 1-line summary from the note's frontmatter or first paragraph.

**Why this priority**: Users with limited time read the digest's first section and decide whether to drill deeper. "Strongest Signals" is the killer feature — without it, the digest is just a structured `git log`. With it, users can spot the genuinely interesting cycles in seconds.

**Independent Test**: Fixture vault where 1 note has high source-quality + 3 citations and 4 other notes are average. Verify: that note appears in "Strongest Signals" with its ranking rationale.

**Acceptance Scenarios**:

1. **Given** a vault where some notes are clearly more important than others, **When** the digest runs, **Then** "Strongest Signals" contains the top 5 (or fewer if vault has <5 notes in range) with ranking rationale.
2. **Given** the deterministic ranking (per Q2 default), **When** the same vault state is digested twice, **Then** "Strongest Signals" lists the same notes in the same order.

---

### User Story 4 — "Gaps" surface what's not covered (Priority: P2)

A digest's "Gaps" section lists `coverage_targets` that stagnated or regressed in the range. For each, it shows: the target identifier, the gap delta (e.g. "regressed: 47% → 39%"), and a pointer to the most recent cycle that touched it.

**Why this priority**: Complement to "Strongest Signals" — what should I prioritize next cycle? Without explicit gap-surfacing, users miss regressions and never close coverage targets.

**Acceptance Scenarios**:

1. **Given** a vault with `coverage-targets.json` and 3 cycles in range, **When** the digest renders "Gaps", **Then** any regressed or stagnant target appears with its delta + last-cycle-touched.
2. **Given** all targets advanced healthily, **When** the digest renders, **Then** "Gaps" reads "No regressions or stagnations in scope" — not an empty section.

---

### Edge Cases

- What if the commit range spans cycles where the spec was retroactively changed (e.g. `coverage-targets.json` schema migrated)? → Digest uses the SCHEMA AT THE TIME of the most recent commit in scope; older entries are best-effort-parsed with `[schema-migrated]` annotation.
- What if a cycle's commit message is malformed (missing the cycle-report sidecar)? → Skip that cycle, log a warning in the digest's footer; don't fail the run.
- What if `_pipeline/sources.db` is locked (concurrent cycle running)? → Wait up to 5 seconds; if still locked, render digest WITHOUT source-quality drift section + log warning.
- What if the operator passes `--since <future_date>`? → Exit non-zero with "no cycles in scope".
- What if the operator passes `--since <date>` for a date BEFORE the vault existed? → Treat as "since the vault was created" silently.
- What if two cycles ran on the same day with conflicting source-quality assessments? → Aggregate by last-write-wins per source per day.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A new `./vault digest` CLI verb MUST be added. The verb accepts `--since <date>` (ISO8601) and outputs a markdown digest.
- **FR-002** *(Q1)*: The verb MUST support `--last-week` / `--last-month` /
  `--last-quarter` as convenience flags that resolve to date ranges; `--since` is
  the primitive they desugar to.
- **FR-003**: The verb MUST output to `_pipeline/digests/digest-<start>--<end>.md` by default. An `--output <path>` flag MAY override the location.
- **FR-004**: The digest MUST contain a **Header** block (rendered-at, commit
  range, vault identity) followed by **exactly 7 content sections** in this order:
  Strongest Signals, Gaps, New Notes by Category, Source Quality Drift, Coverage
  Delta, Cost Summary, Cycle Index. Sections with no data render an explicit "No
  data in scope" line rather than being absent. *(Earlier drafts said "7
  sections" while listing the Header as an 8th item — the Header is a header, not
  a content section.)*
- **FR-005**: "New Notes by Category" MUST group new notes by their `note_types` value (per the vault's `research.spec.md`), with counts + sample wikilinks.
- **FR-006** *(reconciled per Q4)*: "Source Quality Drift" MUST report per-source
  drift derived from **real `sources.db` data** (no quality-score column exists):
  (a) `notes_generated` / `notes_referencing` deltas across the range (from
  `source_cycles`), (b) `degraded`-state transitions in scope (from the
  `source-incidents` log), and (c) `consecutive_empty_cycles` crossing a
  threshold. Each reported source shows name + the drift signal(s) + most-recent
  cycle touched. A source whose signals are flat is omitted. *(Spec 030's
  `source_quality` metrics are a future optional enrichment, not a v1 input.)*
- **FR-007** *(Q2)*: "Strongest Signals" MUST rank notes by a **deterministic
  composite score** = inbound-citation/link count + source-quality delta +
  freshness (days-since-write). Top 5 (or fewer if <5 notes in scope). Each entry
  includes its ranking rationale. No LLM call. The score weights/formula are fixed
  in `contracts/digest-format.contract.md`.
- **FR-008** *(path reconciled per audit)*: "Gaps" MUST list coverage categories
  that regressed or stagnated in scope. Targets (goals) come from
  **`<vault>/coverage-targets.json`** (vault root — NOT `_pipeline/`); per-cycle
  coverage *progress* is read from the first vs last `cycle-NNN-quality-report.json`
  in range (the 0.6.3 completion-marker artifact). Regressed = progress dropped;
  stagnant = flat AND still below the category target.
- **FR-009**: "Cost Summary" MUST report cumulative cost in scope (per spec 028 telemetry), per-stage breakdown, per-cycle costs as a sparkline-style ASCII chart.
- **FR-010** *(reconciled per Q5)*: "Cycle Index" MUST list every cycle in scope,
  **enumerated from the filesystem** (`_pipeline/cycles/cycle-NNN/` dirs +
  `cycle-<N>-report.md`), with: cycle number, ship date, 1-line summary (parsed
  from `cycle-<N>-report.md` H1), and a **ship SHA = the run-level squash commit**
  that merged the cycle to `main` (per spec 050), or the retained
  `research/<ts>` branch SHA on a constrained exit. The digest MUST NOT assume a
  distinct per-cycle commit exists in `main`'s `git log` (050 squashes them).
- **FR-011** *(reconciled per Q5)*: The digest MUST be deterministic — same
  inputs produce byte-identical output (modulo the rendered-at header timestamp).
  Inputs are: the **filesystem** cycle artifacts (`cycle-NNN/`, `cycle-<N>-report.md`),
  `_pipeline/sources.db`, `_pipeline/coverage-targets.json`, the 028 cost
  sidecars (`cycle-NNN/agent-calls/`), and git **only** for the run-level commit
  range + commit dates that bound the `--since` window.
- **FR-012**: The digest MUST be LLM-call-free. No agent dispatch; pure template rendering over structured cycle data.
- **FR-013** *(Q3)*: The digest does NOT auto-run. The README documents a
  cron/launchd one-liner for users who want scheduled digests.
- **FR-014**: Digest generation MUST complete in <5 seconds for a 1-week range on the feeds-vault fixture (3-5 cycles, ~50 notes new).
- **FR-015**: If a cycle's `cycle-N-report.md` is missing or malformed, the digest MUST skip that cycle with a warning in the footer, NEVER fail the run.

### Key Entities

- **`./vault digest` CLI verb**: New CLI surface; argparse-driven; flags per FR-001/002/003.
- **Digest output**: A markdown file at `_pipeline/digests/digest-<start>--<end>.md`. Structured 7-section layout.
- **Strongest Signals ranker**: A deterministic per-note score function (per Q2). Inputs: citation count, source-quality delta, freshness (days-since-write). Outputs: composite score per note.
- **Gap detector**: A diff between `coverage-targets.json` snapshots at start vs end of range. Detects regression + stagnation.
- **Cycle-report parser**: Reads each `_pipeline/cycles/cycle-N-report.md` in scope. Extracts H1 + cost summary + verifier outcomes.
- **Jinja2 digest template**: Lives at `dist-templates/digest.md.j2` or `src/research_framework/templates/`. Single template; one render-pass; no LLM in the loop.
- **Cron-friendly invocation**: Documented one-liner like `(cd ~/Documents/feeds-vault && ./vault digest --last-week)` for users who want scheduled digests.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A digest of 1 week (5 cycles, ~50 new notes) renders in <5 seconds on the feeds-vault fixture.
- **SC-002**: Repeated invocations of the same `--since` produce byte-identical output (excluding the rendered-at timestamp).
- **SC-003**: After this spec ships, operator engagement with cycle output (measured as: did the operator read the digest within 7 days of cycle completion) is ≥80% on the feeds-vault fixture (vs the 2026-05-15 trial-run baseline of ~30%).
- **SC-004**: 0 LLM calls per digest invocation (verified by spec 028's telemetry showing no `agent_call.py` invocations in the time window).
- **SC-005**: Across the 5 Tier-1 source modules (Wave 2), the digest correctly attributes source-quality drift to each module without misattribution.

## Assumptions

- The per-cycle artifacts exist on disk: `_pipeline/cycles/cycle-NNN/` (created by
  the orchestrator) and, when the `cycle-report` skill ran, `cycle-<N>-report.md`.
  The digest degrades gracefully when the latter is missing (FR-015).
- Spec 028 (telemetry sidecars) is shipped (0.4.0) — the Cost Summary has honest
  cost data under `cycle-NNN/agent-calls/`.
- Spec 050 (append-only git) is shipped (0.7.0) — the run/cycle commit topology is
  as FR-010/FR-011 describe.
- `sources.db` carries the `source_cycles` (`notes_generated`/`notes_referencing`)
  + `consecutive_empty_cycles` data the drift section reads (verified 2026-06-03).
- The 7-section layout mirrors the legacy feeds-vault Phase-7 report. If real
  operators want a different structure post-revival, this spec may rev to v2.

## Dependencies

- **Hard — Spec 050 (append-only vault git)** *(added by 2026-06-03 audit)*: 050's
  squash-merge topology defines how cycles map to commits; FR-010/FR-011 are
  written against it (filesystem-authoritative, run-level squash SHA). **All
  shipped on `main` (0.7.0).**
- **Hard — Spec 028 (dispatch telemetry sidecars)**: the Cost Summary reads the
  `cycle-NNN/agent-calls/` sidecars. **Shipped (0.4.0).**
- **Soft — per-cycle `cycle-<N>-report.md`** (the `cycle-report` skill artifact):
  the Cycle Index 1-line summaries + narrative come from it; FR-015 makes its
  absence non-fatal (skip + footer warning). It is LLM-skill-produced, so not
  every cycle has one.
- **Soft — Spec 030 (`source_quality` metrics)**: a *future optional* enrichment
  of "Source Quality Drift" (Q4 chose the sources.db-derived signal for v1, so
  030 is NOT a gate).
- **Soft — Spec 055 (credibility)**: a *future optional* enrichment of "Strongest
  Signals" (Q2 declined folding it into v1).
- **Soft — Spec 040 (vault reports + delivery)**: the digest output is a candidate
  artifact for 040's PDF/mirroring delivery layer.

## Acceptance coverage

Draft — evidence cells will be populated by `/speckit.tasks` for
this spec. Listed for the ADR-0008 guard so the spec is accepted
into the queue (the guard refuses any G/W/T-bearing spec without
this section).

| User Story | Evidence |
|------------|----------|
| US1 — Weekly digest replaces manual `git log` spelunking | _(deferred to tasks.md — design-only spec; digest verb and section coverage lands with implementation)_ |
| US2 — Digest is deterministic + idempotent | _(deferred to tasks.md — design-only spec; determinism and offline coverage lands with implementation)_ |
| US3 — "Strongest Signals" surface the high-value notes | _(deferred to tasks.md — design-only spec; strongest-signals ranking coverage lands with implementation)_ |
| US4 — "Gaps" surface what's not covered | _(deferred to tasks.md — design-only spec; gaps detection coverage lands with implementation)_ |

## Out of Scope

- Replacing per-cycle reports (`_pipeline/cycles/cycle-N-report.md`). Digest is a roll-up, not a replacement.
- LLM-driven summarization of the digest itself. v1 is deterministic template rendering only.
- Email / PDF delivery (deferred to spec 040 — vault reports + delivery).
- Cross-vault digests (one digest spanning multiple vaults). Per-vault only in v1.
- Time-series visualization (charts beyond ASCII sparklines). Defer to spec 043 (Obsidian Canvas autogen).
- Auto-publishing to GitHub Gists / blogs / external surfaces.

---

*IMPLEMENT-READY (2026-06-03): Q1-Q5 locked; plan + research + contract + tasks +
analyze complete (siblings in this dir). Wave 3 / rc1. No external sequencing gate
— all hard deps (028, 050) are shipped on `main`; 030/055 are optional future
enrichments, not blockers.*
