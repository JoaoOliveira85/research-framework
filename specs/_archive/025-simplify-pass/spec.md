# Feature Specification: Code Simplification Pass (Tier A + B Refactor)

**Feature Branch**: `025-simplify-pass`
**Created**: 2026-05-21
**Status**: shipped(2026-05-22, version 0.3.1) — **SHIPPED 0.3.1 (2026-05-22)** — Tier A landed in 0.3.0 (coordinated 022+024 release); Tier B (B3 step extraction, B4 frontmatter parser, B5 cli subpackage, B7 settings loader) + 022 v2 hook retargeting landed in 0.3.1. All 10 user stories complete. `cycle_runner.py` shrunk 2,350 → 232 LOC; 8 frontmatter migrations; 6 settings migrations; byte-identical `./vault --help`. `tests/_helpers/llm_dispatch_allowlist.yaml` remains empty (US10 / SC-003 preserved). Fast-loop tests green at ship time (1278 at v0.3.2; 1692 at 0.6.0 — growth is from subsequent specs, not regressions in this one); `./build.sh --quality` green across all three fixtures with unchanged baselines.
**Follow-up patch — 0.3.2 (2026-05-22)**: a latent Principle-IV violation in `plan_narrator._bootstrap_scripts_agent_call` (and the same bootstrap call from the probe-retrieval path in `_cycle_helpers`) — both A1/A2 surfaces touched in this spec — was caught by `tests/quality/test_fake_agent_interception.py::test_no_live_claude_or_codex_during_fixture_run` after ship. The bootstrap now prefers `<vault>/scripts/agent_call.py` over the repo root so the fake-agent shim intercepts in-process dispatch during fixture cycles. Closed in 0.3.2; tier-6 e2e went 22/23 → **23/23** with the suite wall-clock dropping 644s → 114s (5.6×). The associated **gate-gap was closed in `[Unreleased]`** (post-Foundation gate hardening): the interception test is now in `build.sh::SMOKE_TESTS` and the release workflow runs `bash build.sh --quality` before publishing, so no Principle-IV regression of this kind can land on `main` silently in the future. See CHANGELOG `[0.3.2]` + `[Unreleased]` for the full audit trail.
**Input**: `docs/SIMPLIFY-PASS.md` — architect plan commissioned 2026-05-21,
~245 lines covering goal / problem / scope tiers / alternatives / risks /
calendar / definition of done. This spec promotes the SIMPLIFY-PASS plan
to spec-kit format so each tier item gets prioritised user stories,
acceptance criteria, and traceability. The companion plan doc remains
as the implementation reference; this spec is the contract.

## Clarifications

### Session 2026-05-21 (interactive clarify with user)

Decisions locked during the interactive `/speckit.clarify` pass on
the `025-simplify-pass` worktree (`~/src/research-framework-025/`).
Two clarifications below (Q2, Q3) are net-new from the interactive
session and were not in the original draft's [PROPOSED] list; the
remaining seven (Q1, Q4a–e) lock the original [PROPOSED] starting
positions or refine them.

- **Q1 (Scope) — LOCKED 2026-05-21**: **Tier A + Tier B**
  (Alternative A from `docs/SIMPLIFY-PASS.md` § 5). Tier C
  explicitly deferred. **MVP fallback** if calendar slips before
  2026-06-01 = Tier A only (see Q3b).
- **Q2 (Ship gate / sequencing) — LOCKED 2026-05-21**: **Parallel-
  develop, sequenced-ship**. The strategic sequencing across the
  three foundation specs becomes `024 → 022 → 025 → Features`
  (UPDATES the prior `Foundation 024+025 → Quality 022` ordering
  in `docs/ROADMAP.md` and `CLAUDE.md`; doc sync ships with this
  commit). 025 work happens in parallel in this worktree NOW, but
  025 PRs **cannot MERGE** until spec 022 v1 has shipped and
  produced committed baselines (per 022 FR-016). Post-022-v1,
  every 025 PR must pass `./build.sh --quality` — the regression
  report shows `pass` or `warn` (fail blocks merge). 022's harness
  is the authoritative regression detector for 025; spec 024 ships
  ALONGSIDE 022 because 024's fake_agent extensions are 022's
  hard prerequisite (the 022 ↔ 024 dependency is not circular —
  they ship as a coordinated quality release).
- **Q3a (B3 rollback strategy) — LOCKED 2026-05-21**: Stage B3
  (cycle-runner step extraction) in a **long-lived sub-branch**
  `025-b3-step-extraction`. Develop all three step extractions
  (scout, research, postprocess) there; ship as **one big PR**
  after `./build.sh --quality` passes locally. Don't merge
  intermediate B3 PRs to main. *Trade-off accepted*: the architect
  warned against long-lived branches in `docs/SIMPLIFY-PASS.md`
  § 6; user accepted the merge-conflict / drift risk in exchange
  for revert simplicity. See **Risks & Mitigations** § R1 for the
  mitigation plan.
- **Q3b (MVP if calendar slips) — LOCKED 2026-05-21**: Pre-committed
  cut menu. If 2026-06-01 approaches with only PART of 025 shipped,
  MVP cut = **Tier A only** (A1, A2, A4, A5, A6). Tier B items
  (B3, B4, B5, B7) defer to follow-up specs (e.g.
  `026-cycle-runner-extraction`, `027-frontmatter-parser`). Cut
  activation decision happens at **2026-05-29** (48h before
  deadline review).
- **Q4a (Spec 024 overlap ownership) — LOCKED 2026-05-21**: **Spec
  024 owns** the four testing-infrastructure overlap items:
  - A3 (smoke meta-tests restoration) → spec 024 US3
  - B1 (fake_agent verifier scenarios) → spec 024 US2
  - B2 (tier-5 cycle e2e wiring) → spec 024 US6
  - B6 (retire `test_e2e_synthetic_vault.py` mock pattern) → spec 024 US7

  Spec 025 covers the *production-code* refactor only.
- **Q4b (Branch strategy) — LOCKED 2026-05-21**: One umbrella
  spec-kit branch `025-simplify-pass`. Sub-branches per merge
  unit: A1/A2/A4/A5/A6 each in its own PR; `025-b3-step-extraction`
  long-lived for B3 (per Q3a); B4/B5/B7 each in separate PRs.
- **Q4c (Top-level acceptance criterion) — LOCKED 2026-05-21**:
  **LLM dispatch guard allowlist contains ZERO entries** after
  this spec ships (see FR-013, US10, SC-003). Implies A1 + A2
  must both ship for the spec to be considered "done" against
  its primary acceptance gate; secondary gate is SC-014 (post-022
  `./build.sh --quality` pass).
- **Q4d (Tier B items as user stories) — LOCKED 2026-05-21**:
  Each Tier B item is its own user story (US6 = B3, US7 = B4,
  US8 = B5, US9 = B7). Pro: different files, different risk,
  different reviewer pool. Ship cadence: **B4/B5/B7 each ship
  as a separate PR**; **B3 is the exception per Q3a — ships as
  ONE big PR from the long-lived `025-b3-step-extraction`
  sub-branch**. So Tier B = 4 user stories but 4 PRs of which
  one is large (B3) and three are small (B4, B5, B7).
- **Q4e (Known-debt exception) — LOCKED 2026-05-21**:
  `processors/extract.py` cleanup explicitly out of scope per
  `docs/SIMPLIFY-PASS.md` § 8; documented in **Out of scope**
  section. Future contributor lifts via a new spec.

### Session 2026-05-21 (asynchronous draft — RESOLVED)

This block originally contained 7 `[PROPOSED]` starting positions
the agent drafted before interactive clarify. All resolved in the
interactive session above; pointers below for traceability.

- **[LOCKED 2026-05-21]** Q: Scope (Tier A + B vs Tier A only)?
  → Resolved Q1: **Tier A + Tier B** (MVP fallback Tier A only
  per Q3b).
- **[LOCKED 2026-05-21]** Q: Items overlapping with spec 024 — who
  owns? → Resolved Q4a: **Spec 024 owns** A3/B1/B2/B6.
- **[LOCKED 2026-05-21]** Q: Branch strategy — one vs two? →
  Resolved Q4b: **One umbrella + sub-branches per merge unit**.
- **[LOCKED 2026-05-21]** Q: Top-level acceptance criterion? →
  Resolved Q4c: **LLM dispatch guard allowlist = ZERO entries**.
- **[LOCKED 2026-05-21]** Q: Behaviour preservation — what counts
  as a regression? → Resolved Q2: pytest + smoke + tier-5 e2e
  (when 024 wires it) **PLUS** post-022 `./build.sh --quality`
  as a hard gate. 022's harness is the authoritative regression
  detector; the original "manual visual inspection of tech-lite
  cycle output" fallback is dropped in favour of the harness.
- **[LOCKED 2026-05-21]** Q: Tier B items as separate user stories
  or one bucket? → Resolved Q4d: **Separate US per item**.
- **[LOCKED 2026-05-21]** Q: Definition-of-done allows known-debt
  exceptions? → Resolved Q4e: **Yes** — `processors/extract.py`
  exempt.

### Background — why simplify before 022

`docs/SIMPLIFY-PASS.md` § 2 summarises the structural-debt signals:

- `cycle_runner.py` at **2,195 lines** — any 022 metric hook attaches
  here, blowing up the context every agent needs.
- **Dual code trees** (`src/research_framework/` + `scripts/`) — agents
  miss `scripts/agent_call.py` and validators.
- **2 LLM bypasses** (`plan_narrator`, probe cache) — cost not
  captured; fake_agent can't stub; codex vaults secretly call claude.
- **fake_agent covers scout + note_writer only** — spec 024 fixes this.
- **12+ frontmatter parsers** — note-quality metrics may disagree
  across gates.
- **Stale docs** (QW-2 "files missing", constitution mentions
  `run_cycle.sh`) — agents follow wrong instructions.

The strategic-sequencing block in `docs/ROADMAP.md` (lines 247–263)
puts spec 022 (quality harness) ahead of every feature spec. But
022 itself is hard to *implement* against a 2,195-line `cycle_runner.py`
with two LLM bypasses and stale docs. Spec 025 makes the code
ready for 022. Phase 2 of the testing strategy (spec 024) makes the
test infrastructure ready for 022. The three specs ship as a
coordinated foundation.

### Relationship to other specs

- **Spec 018** (Testing Strategy, SHIPPED 0.2.23 + partially
  superseded by ADR-0008): provides the LLM dispatch guard
  contract that spec 025 Tier A satisfies.
- **Spec 020** (Source-Module Architecture, DESIGN LOCKED, PAUSED
  pending 022): downstream of spec 025; expects clean LLM dispatch
  and cycle-step modules to plug into.
- **Spec 022** (E2E Quality Harness, DRAFT 2026-05-21): consumes
  the simplified codebase. 022's metric hooks attach at spec 025
  Tier B3 step boundaries.
- **Spec 024** (Testing Infrastructure v2, DRAFT 2026-05-21): owns
  the LLM dispatch *guard* (which catches violations); spec 025
  owns the production *code* that the guard validates. Spec 024
  also owns A3/B1/B2/B6 — see Clarifications.

### What this spec is NOT

- It is **NOT** new product features. Pure behaviour-preserving
  refactor + dead-code removal + doc sync.
- It is **NOT** the LLM dispatch guard. That's spec 024 US1.
  Spec 025 makes the guard's allowlist go to zero.
- It is **NOT** the quality harness. That's spec 022.
- It is **NOT** the fake_agent extensions. That's spec 024 US2.
- It is **NOT** the smoke meta-test restoration. That's spec 024
  US3 (was SIMPLIFY-PASS A3).
- It is **NOT** the source-module architecture or gap-pursuit.
  Those are specs 020 and 021.
- It is **NOT** `processors/extract.py` cleanup (known separate
  debt per SIMPLIFY-PASS § 8).
- It is **NOT** the Tier C items (C1–C7). Those are explicitly
  deferred until after 022 v1 ships.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — A1: plan_narrator routes through agent_call.py (Priority: P1)

A vault generator runs a cycle that needs the research-plan narrator.
Today the call goes through `subprocess.run(["claude", "-p", ...])`
in `pipeline/plan_narrator.py` (or wherever `prepend_narrative` lives).
After spec 025 A1, the same call routes through
`scripts/agent_call.py` with stage `plan_narrator`, captures cost,
respects the configured tier (basic/standard/expert), and lets
fake_agent stub it during tests. The LLM dispatch guard allowlist
row for `plan_narrator` is removed in the same commit.

**Why this priority**: One of the two known production bypasses. Each
day this stays in place is a day of wasted cost-capture data and
broken `codex`-default vaults (which secretly call `claude`). P1
because it's a constitutional violation (Principle IV).

**Independent Test**: Set `settings.yaml::stages.plan_narrator.tier:
expert`. Run a cycle with `RESEARCH_FRAMEWORK_DEFAULT_AGENT=codex`.
Confirm via `_pipeline/cycles/cycle-NNN/agent-calls/*.json` that the
narrator call recorded `agent: codex` (not `claude`) and a
non-zero `cost_usd`. Confirm the LLM dispatch guard passes with the
allowlist row for `plan_narrator` deleted.

**Acceptance Scenarios**:

1. **Given** `pipeline/plan_narrator.py` post-A1, **When** the
   narrator is invoked during a cycle, **Then** the call is routed
   through `scripts/agent_call.py` with the correct stage tag.
2. **Given** `RESEARCH_FRAMEWORK_DEFAULT_AGENT=codex`, **When** the
   narrator is invoked, **Then** the underlying subprocess is `codex`,
   not `claude`.
3. **Given** the cycle completes, **When** `_pipeline/cycles/cycle-NNN/
   agent-calls/` is inspected, **Then** a narrator-stage cost-sidecar
   JSON exists with valid cost data.
4. **Given** the LLM dispatch guard from spec 024, **When** A1 ships,
   **Then** the allowlist entry for `pipeline/plan_narrator.py` is
   removed in the same commit and the guard still passes.

---

### User Story 2 — A2: probe-retrieval routes through agent_call.py (Priority: P1)

Same as A1 but for the probe-cache retrieval call in
`pipeline/cycle_runner.py` (~lines 1137–1252 per SIMPLIFY-PASS).
After A2, the probe call routes through `agent_call.py` with stage
`probe_retrieval`, captures cost, and is stubbable by fake_agent.

**Why this priority**: The second of the two known production
bypasses. P1 for the same reasons as A1.

**Independent Test**: Run a cycle that requires probe retrieval
(e.g. `tech-lite` fixture with `probe_retrieval` enabled in settings).
Confirm via the agent-calls sidecar that the probe stage recorded
properly and the subprocess respected the configured default agent.
Confirm the LLM dispatch guard passes with the allowlist row for
`cycle_runner.py` probe-block deleted.

**Acceptance Scenarios**:

1. **Given** `pipeline/cycle_runner.py` post-A2, **When** the probe-
   retrieval stage runs, **Then** the call is routed through
   `scripts/agent_call.py` with stage `probe_retrieval`.
2. **Given** `RESEARCH_FRAMEWORK_DEFAULT_AGENT=codex`, **When** the
   probe stage runs, **Then** the underlying subprocess is `codex`.
3. **Given** the cycle completes, **When** the agent-calls dir is
   inspected, **Then** a probe-stage cost-sidecar JSON exists.
4. **Given** the LLM dispatch guard from spec 024, **When** A2 ships,
   **Then** the allowlist entry for the probe-retrieval line range
   is removed and the guard still passes with **zero allowlist entries**.

---

### User Story 3 — A6: quality-report context-manager guard (Priority: P1)

A cycle author runs `run_cycle_steps`. Today the function has
**32 scattered calls** to `_write_cycle_quality_report` — one at
each error/early-return path — and any new return path that forgets
to call it ships an incomplete cycle. After A6, a single
`try/finally` (or context manager) around the cycle ensures the
quality report is *always* written exactly once, regardless of how
the cycle exits.

**Why this priority**: This is the highest-yield safety refactor in
the spec. Touching `cycle_runner.py` is intrinsically risky; this
refactor eliminates a whole class of "I forgot to write the report"
bug from future edits. P1 because spec 022 will add many new exit
paths for metric capture, and we want exactly one place to wire that.

**Independent Test**: Trigger a cycle abort via every error path
known to `cycle_runner.py` (scout failure, research failure, note-
writer failure, verifier reject of every note, etc.). For each path,
assert `cycle-NNN-quality-report.json` exists and contains the
appropriate failure record. Then deliberately raise an exception
from the middle of cycle execution; assert the report still gets
written.

**Acceptance Scenarios**:

1. **Given** `run_cycle_steps` post-A6, **When** any code path (happy,
   sad, exception) exits the function, **Then**
   `cycle-NNN-quality-report.json` is written exactly once.
2. **Given** a deliberate `KeyboardInterrupt` mid-cycle, **When**
   the cycle exits, **Then** the quality report is written and
   records the interrupt.
3. **Given** the refactored code, **When** `_write_cycle_quality_report`
   is grepped, **Then** there are at most **2** call sites
   (the context-manager entry + a deliberate "log progress" mid-cycle
   call, if one is kept).
4. **Given** the existing cycle-runner tests, **When** they run,
   **Then** all pass unchanged (behaviour-preserving).

---

### User Story 4 — A4: auto-detect resume cycle (Priority: P2)

A vault researcher runs `./vault research --resume` after a cycle
crashed mid-execution. Today they have to pass `--cycle 7` explicitly.
After A4, the CLI auto-detects the in-progress cycle by reading
`_pipeline/state.json` (or equivalent) and resumes without the
extra flag.

**Why this priority**: Quality-of-life. P2 because it doesn't unblock
anything else, but it's a frequent papercut during 022 e2e runs
(per ROADMAP line 146) and easy to fix (~10 lines).

**Independent Test**: Run a cycle, simulate a crash mid-research,
then run `./vault research --resume` (no `--cycle` flag). Confirm
it picks up the in-progress cycle automatically. Run again with
no in-progress cycle and confirm it errors clearly: "no in-progress
cycle found; use `--cycle <N>` to specify".

**Acceptance Scenarios**:

1. **Given** an in-progress cycle (state file present), **When**
   `./vault research --resume` runs without `--cycle`, **Then** it
   resumes the in-progress cycle.
2. **Given** no in-progress cycle, **When** `./vault research --resume`
   runs without `--cycle`, **Then** it errors with a clear message.
3. **Given** an in-progress cycle, **When** `./vault research
   --resume --cycle 5` runs (explicit override), **Then** it
   resumes cycle 5 (explicit flag wins).
4. **Given** multiple in-progress cycles (edge case), **When**
   auto-detect runs, **Then** it errors: "multiple in-progress
   cycles found; specify with `--cycle <N>`".

---

### User Story 5 — A5: doc sync (constitution, ROADMAP, build.sh) (Priority: P2)

A new contributor reads `.specify/memory/constitution.md` and finds
references to `run_cycle.sh` — a script that no longer exists.
They read `docs/ROADMAP.md` QW-2 and find a description claiming
the two smoke meta-tests don't exist on disk — but they do. They
read `build.sh` comments and find stale references to the old smoke
gate contract. After A5, all three docs match reality.

**Why this priority**: Stale docs send agents down wrong paths and
burn tokens. P2 because no code change blocks on it, but the cost
compounds with every session.

**Independent Test**: `rg "run_cycle\.sh" .specify/ docs/ src/` →
expect zero hits after A5. `rg "files never committed" docs/ROADMAP.md`
→ expect zero hits. Comments in `build.sh` reference the current
`SMOKE_TESTS` manifest format.

**Acceptance Scenarios**:

1. **Given** `.specify/memory/constitution.md` post-A5, **When**
   grepped for `run_cycle.sh`, **Then** zero matches.
2. **Given** `docs/ROADMAP.md` QW-2 entry, **When** read, **Then**
   it correctly states "uncomment lines in build.sh", not "restore
   missing files".
3. **Given** `build.sh` post-A5, **When** the file is read, **Then**
   comments accurately describe the smoke-gate enforcement mechanism.

---

### User Story 6 — B3: extract cycle-runner steps into pipeline/steps/ (Priority: P2)

A contributor reading `pipeline/cycle_runner.py` today opens a
2,195-line file. After B3 (partial), top-level steps (scout,
research, postprocess) are extracted into `pipeline/steps/<step>.py`
modules with stable public APIs. `cycle_runner.py` orchestrates by
calling into the step modules; the `run_cycle_steps` signature is
unchanged (drop-in replaceable).

**Why this priority**: P2. Big refactor surface; doesn't unblock
anything immediately but pays down the structural debt that costs
every future agent. Architect plan calls it "B3 step modules are
where metric injection attaches" — making 022's metric hooks
possible without further surgery.

**Independent Test**: After B3, line-count of `pipeline/cycle_runner.py`
is < 1,500 lines (down from 2,195) and the three new modules
(`steps/scout.py`, `steps/research.py`, `steps/postprocess.py`)
exist with ~200–400 LOC each. Full pytest sweep passes unchanged.
Tier-5 cycle e2e (spec 024 US6) passes unchanged.

**Acceptance Scenarios**:

1. **Given** `pipeline/cycle_runner.py` post-B3, **When** `wc -l`,
   **Then** less than 1,500 lines.
2. **Given** the new `pipeline/steps/` package, **When** scout
   logic is needed, **Then** it lives in `pipeline/steps/scout.py`
   with a documented public function (e.g. `run_scout(...)`).
3. **Given** the refactor, **When** `run_cycle_steps` is called,
   **Then** its signature and externally-observable behaviour is
   unchanged.
4. **Given** the full pytest sweep, **When** it runs post-B3,
   **Then** all tests pass without modification.

---

### User Story 7 — B4: shared frontmatter parser (Priority: P3)

A note-quality metric author needs to read a note's frontmatter.
Today they pick one of 12+ frontmatter parsers scattered across
`src/research_framework/`. After B4, one canonical parser lives at
`vault/frontmatter.py` (or `processors/_common.py`); at least 8 of
the 12+ call sites migrate to it.

**Why this priority**: P3 because the duplication doesn't cause bugs
*today* (the parsers happen to agree). But spec 022's metric layer
will read frontmatter from many places; having one parser makes
metric-disagreement impossible.

**Independent Test**: After B4, `rg "yaml.safe_load.*frontmatter|---.*\n.*---"`
returns the canonical parser and at most 4 holdout sites (with
clear comments explaining why they can't migrate). Edge-case tests
cover empty frontmatter, malformed YAML, multi-document YAML, and
nested keys.

**Acceptance Scenarios**:

1. **Given** the canonical parser exists, **When** ≥8 call sites
   are grepped, **Then** they import from the canonical location.
2. **Given** an edge-case note (empty frontmatter, malformed YAML,
   multi-doc, nested keys), **When** parsed via the canonical
   function, **Then** each case is handled with a documented
   contract (parse success or specific failure mode).
3. **Given** the holdout sites that can't migrate, **When** read,
   **Then** each has a comment explaining the constraint (e.g.
   "this site must accept malformed YAML and return partial data").

---

### User Story 8 — B5: split `cli.py` into a subpackage (Priority: P3)

A contributor adds a new `./vault` subcommand. Today they open a
1.1k-line `cli.py` and try to find the right argparse hook. After
B5, `cli.py` is a thin entry point that imports from a `cli/`
subpackage organised by command group (research, audit, vault,
quality, etc.). `build_parser()` is re-exported unchanged so external
callers (and the `./vault` shell wrapper) see no difference.

**Why this priority**: P3. Big surface area; touches many tests;
doesn't unblock anything directly. But every CLI change touches
this file and the size makes agents miss conventions.

**Independent Test**: After B5, `wc -l cli.py` < 200 lines.
`cli/__init__.py` re-exports `build_parser`. `cli/research.py`,
`cli/audit.py`, etc., each handle one command group. The full
pytest sweep passes; `./vault --help` output is byte-identical
before/after.

**Acceptance Scenarios**:

1. **Given** the refactored `cli.py`, **When** `wc -l`, **Then**
   less than 200 lines.
2. **Given** the new `cli/` subpackage, **When** `cli/__init__.py`
   is read, **Then** `build_parser` is re-exported unchanged.
3. **Given** the refactor, **When** `./vault --help` runs both
   before and after, **Then** stdout is byte-identical.
4. **Given** the full pytest sweep, **When** it runs, **Then** all
   tests pass without modification.

---

### User Story 9 — B7: shared settings loader (Priority: P3)

A new pipeline stage needs to read `settings.yaml`. Today multiple
modules implement their own `load_settings` flavour with subtle
differences. After B7, one `load_vault_settings(vault_dir)` lives
at `pipeline/settings.py` and is the only path. Other modules import
it.

**Why this priority**: P3. Same rationale as B4 — duplication doesn't
bite today but spec 022 will read settings from many places.

**Independent Test**: After B7, `rg "yaml.safe_load.*settings\.yaml"`
returns the canonical loader and at most 2 holdout sites with
documented constraints. Settings loading is now consistent across
the codebase.

**Acceptance Scenarios**:

1. **Given** the canonical loader exists, **When** ≥6 call sites
   are grepped, **Then** they import from `pipeline/settings.py`.
2. **Given** an invalid settings file (missing required key,
   malformed YAML), **When** loaded via the canonical function,
   **Then** the error message is consistent across all call sites.

---

### User Story 10 — LLM dispatch guard allowlist reaches zero (Priority: P1, meta)

After this spec ships in full (at minimum A1 + A2), the LLM dispatch
guard from spec 024 has **zero entries** in its allowlist. This is
the top-level success criterion for Tier A.

**Why this priority**: P1 meta-story — it doesn't add code, it
verifies the code that A1 and A2 add achieves the constitutional
goal (Principle IV: Agent-Script Separation of Concerns). Without
this, A1 and A2 might "work" but leave the guard non-empty (defeating
the point).

**Independent Test**: After A1 + A2 ship,
`cat tests/_helpers/llm_dispatch_allowlist.yaml` shows zero entries
(or only an empty list with a comment "no current bypasses"). Run
the LLM dispatch guard and confirm it passes with zero exceptions.

**Acceptance Scenarios**:

1. **Given** A1 and A2 shipped, **When** the LLM dispatch guard
   runs, **Then** the allowlist contains zero file/line entries.
2. **Given** the allowlist is empty, **When** the guard runs against
   the full codebase, **Then** it finds zero direct claude/codex
   subprocess invocations (excluding `scripts/agent_call.py`
   itself, which is the dispatcher).
3. **Given** a future contributor accidentally re-adds a bypass,
   **When** the guard runs, **Then** it fails — no allowlist
   exception is granted without a new spec-level decision.

### Edge Cases

- A1: settings.yaml schema lacks `stages.plan_narrator.tier` (older
  vault) → loader uses a default; doc the default.
- A2: probe-retrieval is disabled in settings → no agent_call.py
  invocation expected; cycle proceeds without the stage.
- A6: a malicious test deliberately catches `BaseException` and
  swallows the context-manager's `__exit__` → unlikely; document
  the assumption that test code respects context manager semantics.
- A4: `_pipeline/state.json` is corrupted → auto-detect fails
  gracefully with a clear error rather than silently selecting the
  wrong cycle.
- B3: cycle-runner step extraction introduces a circular import →
  catch via import-time tests; lazy-import within the step modules
  if needed.
- B4: a holdout frontmatter parser depends on a side-effect (e.g.
  schema-drift detection) → keep that parser; document why; count
  in the "≥8 of 12+ migrated" success criterion.
- B5: a downstream tool (CI script, install.sh) imports `cli.py`
  internals directly → audit and migrate or stabilize the public
  API before B5.
- B7: settings file is generated by `vault-spec` skill and has a
  schema mismatch → catch at `load_vault_settings` time, surface
  validator output.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001** (A1): `pipeline/plan_narrator.py` MUST invoke the
  narrator via `scripts/agent_call.py` with stage tag `plan_narrator`.
  Direct `subprocess.run([...])` to `claude`/`codex` MUST be removed.
- **FR-002** (A2): `pipeline/cycle_runner.py` probe-retrieval block
  (~lines 1137–1252 at v0.2.33) MUST invoke probes via
  `scripts/agent_call.py` with stage tag `probe_retrieval`.
- **FR-003** (A1, A2): Each routed call MUST produce a cost-sidecar
  JSON under `_pipeline/cycles/cycle-NNN/agent-calls/<stage>.json`.
- **FR-004** (A4): `./vault research --resume` without `--cycle`
  MUST auto-detect the in-progress cycle from `_pipeline/state.json`
  (or equivalent). MUST error clearly if no in-progress cycle exists
  or if multiple in-progress cycles exist.
- **FR-005** (A5): `.specify/memory/constitution.md` MUST NOT
  reference `run_cycle.sh` (deleted long ago). `docs/ROADMAP.md`
  QW-2 entry MUST accurately describe the work (uncomment, not
  restore). `build.sh` comments MUST match current contract.
- **FR-006** (A6): `run_cycle_steps` MUST guarantee
  `_write_cycle_quality_report` runs exactly once on every exit
  path (success, failure, exception, interrupt) via a single
  context manager or `try/finally` block.
- **FR-007** (A6): The codebase MUST have at most 2 call sites of
  `_write_cycle_quality_report` after the refactor (entry/exit of
  the context manager + at most one progress-log site).
- **FR-008** (B3): `pipeline/cycle_runner.py` MUST be reduced to
  < 1,500 lines by extracting scout, research, and postprocess
  steps into `pipeline/steps/<step>.py` modules with stable
  public functions.
- **FR-009** (B3): `run_cycle_steps` public signature MUST be
  unchanged. Externally-observable cycle behaviour MUST be
  unchanged (full pytest sweep + tier-5 e2e green without test
  modifications).
- **FR-010** (B4): A canonical frontmatter parser MUST live at
  `vault/frontmatter.py` (or `processors/_common.py`). ≥8 of the
  ≥12 existing call sites MUST migrate to it.
- **FR-011** (B5): `cli.py` MUST be reduced to < 200 lines.
  Subcommand handlers MUST live in `cli/<group>.py`.
  `build_parser()` MUST remain a re-exported public function with
  unchanged signature.
- **FR-012** (B7): A canonical settings loader MUST live at
  `pipeline/settings.py` as `load_vault_settings(vault_dir)`.
  ≥6 of the existing call sites MUST migrate.
- **FR-013** (US10): The LLM dispatch guard (from spec 024)
  allowlist MUST contain **zero entries** after this spec ships.
- **FR-014** (cross-cutting): No new runtime dependencies
  (Constitution Principle V). Pure stdlib + existing deps.
- **FR-015** (cross-cutting): Behaviour-preserving — `./vault --help`,
  `build_parser()` export, `run_cycle_steps` signature, settings
  YAML keys all unchanged. **Regression gate** depends on tier
  (per FR-016 + SC-014 + R3 carve-out):
  - Tier A PRs (any time): pytest sweep + `./build.sh` smoke.
  - Tier B PRs (post-022-v1 only): pytest sweep + `./build.sh
    --quality` (which transitively runs smoke).
- **FR-016** (ship sequencing, locked Q2 2026-05-21, amended for
  R3 carve-out):
  **Tier B** 025 PRs (US6 B3, US7 B4, US8 B5, US9 B7) MUST NOT
  merge to `main` until spec 022 v1 has shipped AND committed
  baselines exist under `tests/fixtures/quality/baselines/
  *.baseline.json` (per 022 FR-016). Pre-022-v1, Tier B 025 PRs
  may be opened for review but block on the merge gate until
  that prerequisite lands.
  **Tier A** 025 PRs (US1 A1, US2 A2, US3 A6, US4 A4, US5 A5)
  are **EXEMPT** from the post-022-v1 gate — they ship pre-022-v1
  with pytest + smoke as the gate. *Rationale*: Tier A items
  (especially A1/A2) fix LLM-bypass debt that 022 itself
  depends on for cost capture and fake_agent stubbability;
  they CANNOT gate on the thing they enable. The architect
  characterised them as "mandatory pre-022".
  Coordination signal for Tier B unlock: the release commit
  that bumps `pyproject.toml` to 022's ship version + adds the
  baselines = Tier B merge-gate unlocked. The
  `024-testing-infrastructure-v2` branch is 022's hard
  prerequisite and ships in the same coordinated release window
  as 022 v1.

### Key Entities

- **agent-calls sidecar JSON** — written by `agent_call.py` for each
  routed call. Schema includes `stage`, `agent`, `tier`, `cost_usd`,
  `tokens_in`, `tokens_out`, `latency_ms`. Spec 022 will read these.
- **LLM dispatch allowlist** — owned by spec 024; spec 025 deletes
  the two entries that exist at the start.
- **pipeline/steps/ package** (B3) — three new modules: `scout.py`,
  `research.py`, `postprocess.py`. Each exports a single public
  function that `cycle_runner.py` calls.
- **vault/frontmatter.py** (B4) — single parser; signature
  `parse_frontmatter(path: Path) -> tuple[dict, str]` returning
  (frontmatter dict, body markdown).
- **cli/ subpackage** (B5) — one module per command group with
  consistent `register(parser)` and `handle(args)` shape.
- **pipeline/settings.py** (B7) — single `load_vault_settings(vault_dir:
  Path) -> VaultSettings` function returning a typed dict / dataclass.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Full sweep (`pytest`) green at ship — every tier.
- **SC-002**: `./build.sh` smoke green at ship.
- **SC-003**: LLM dispatch guard (spec 024) allowlist contains
  **zero entries** after this spec ships.
- **SC-004**: `pipeline/cycle_runner.py` line count is **< 1,500**
  lines (post-B3).
- **SC-005**: `cli.py` line count is **< 200** lines (post-B5).
- **SC-006**: `_write_cycle_quality_report` has **≤ 2** call sites
  (post-A6).
- **SC-007**: ≥ **8** frontmatter parser call sites migrated to
  the canonical parser (post-B4).
- **SC-008**: ≥ **6** settings loader call sites migrated
  (post-B7).
- **SC-009**: `./vault --help` output byte-identical pre/post
  (regression check for B5).
- **SC-010**: `./vault research --resume` without `--cycle`
  auto-detects (post-A4).
- **SC-011**: Each agent-calls sidecar produced by A1 and A2 has
  valid cost data (`cost_usd` > 0 when LLM was actually called).
- **SC-012**: Zero references to `run_cycle.sh` in
  `.specify/memory/` or `docs/` (post-A5).
- **SC-013**: Spec 022 implementation can attach metric hooks at
  the new step-module boundaries without further refactoring of
  `cycle_runner.py` (validated when spec 022 v2 retargets its
  metric hooks to the new step modules — see FR-016 ship
  sequencing, which puts 022 v1 BEFORE 025 ship and 022 v2 AFTER).
- **SC-014** (post-022-v1 Tier B regression gate, locked Q2
  2026-05-21, amended for R3 carve-out): Every **Tier B** 025
  PR (US6 B3, US7 B4, US8 B5, US9 B7) merged AFTER 022 v1 ships
  MUST produce `./build.sh --quality` exit code 0 (or exit code
  0 with warn-band per 022 FR-009; warn-band requires reviewer
  acknowledgement in the PR description). Tier A PRs (US1 A1,
  US2 A2, US3 A6, US4 A4, US5 A5) are exempt from SC-014 per
  R3 mitigation 1 — they ship pre-022-v1 with pytest + smoke
  only. Verification: CI workflow `.github/workflows/quality.yml`
  (defined in spec 022) gates every tag-pushed release; manual
  local invocation recommended pre-PR per 022 FR-015.
- **SC-015** (B3 long-lived sub-branch hygiene, Q3a 2026-05-21):
  `025-b3-step-extraction` MUST rebase against `main` at least
  weekly until its single ship PR opens; target ship within 5
  calendar days of branch creation. If the branch exceeds 7
  calendar days unmerged, escalate (re-evaluate B3 scope or
  split the step extraction into smaller PRs per `pipeline/steps/
  <step>.py` module).

## Assumptions

- **Sequencing (locked Q2 2026-05-21)**: Spec 024 ships ALONGSIDE
  spec 022 v1 as the coordinated quality release (024's
  fake_agent extensions are 022's hard prerequisite — see Q2 in
  Clarifications). Spec 025 ships AFTER that coordinated release.
  Concretely: `024 + 022 v1` (single release window) → `025`
  → `022 v2` (retargets metric hooks to new step modules).
- 025 development happens NOW in parallel (worktree at
  `~/src/research-framework-025/`) regardless
  of ship gate; PRs may open early but merge only post-022-v1
  (FR-016).
- `scripts/agent_call.py`'s dispatch surface is stable; no
  schema changes required for A1/A2.
- `_pipeline/state.json` (or equivalent in-progress-cycle marker)
  exists or is added during this spec — A4 may need to add it.
- Cycle-runner has stable input/output contracts at scout, research,
  and postprocess boundaries (the architect's review implies this;
  verify at `/speckit.plan` time).
- No new runtime dependencies (Principle V).
- `processors/extract.py` cleanup is **out of scope** even though
  it has similar LLM-bypass debt (SIMPLIFY-PASS § 8 explicit
  exception). Future spec.
- Tier C (C1–C7) is explicitly deferred and will not be tackled
  in this spec.
- **Calendar / MVP fallback (locked Q3b 2026-05-21)**: If by
  2026-05-29 the sequenced release window suggests 025 cannot
  ship full scope by 2026-06-01, the pre-committed cut is
  **Tier A only** (A1, A2, A4, A5, A6). Tier B (B3/B4/B5/B7)
  spins out as follow-up specs (e.g. `026-cycle-runner-extraction`,
  `027-frontmatter-parser`). Cut activation decision is the
  spec-author's call at 2026-05-29 review.

## Risks & Mitigations

Captured here because the locked clarifications surface novel
ship-risk that the original draft did not enumerate.

- **R1 — B3 long-lived sub-branch drift (Q3a trade-off)**.
  *Risk*: `025-b3-step-extraction` is a single-big-PR branch
  per Q3a. The architect (`docs/SIMPLIFY-PASS.md` § 6) flagged
  long-lived branches as merge-conflict-prone, particularly
  given concurrent 022 implementation may also touch
  `pipeline/cycle_runner.py`.
  *Mitigations*:
  1. **Cycle-runner edit lock during B3 window**: no other PR
     may modify `pipeline/cycle_runner.py` while
     `025-b3-step-extraction` is open. 022's metric-hook
     attachment work coordinates with 025 via the
     `025-b3-step-extraction` branch (022 v1 attaches to
     pre-B3 seams; 022 v2 attaches to post-B3 step modules).
  2. **Weekly rebase cadence** (SC-015): rebase against `main`
     every Monday until ship. Maintainer enforces.
  3. **5-day ship target, 7-day hard escalation** (SC-015): if
     the branch hasn't merged by day 7, escalate to "split into
     per-step-module PRs" — abandon the single-PR plan.
  4. **PR description by step**: when the ship PR opens, the
     description splits the diff by step module (scout,
     research, postprocess) with before/after cycle output
     diffs from the `tech-lite` fixture to aid review.

- **R2 — B4/B5/B7 behaviour-preservation gap pre-022-v1**.
  *Risk*: Tier B items (frontmatter parser unification, cli.py
  split, settings loader unification) are claimed
  "behaviour-preserving" but the only objective gate pre-022-v1
  is the pytest sweep + smoke gate, which has known coverage
  gaps in cycle-runner integration paths.
  *Mitigations*:
  1. **Sequence Tier B AFTER 022 v1**: Tier B PRs target the
     post-022-v1 window (FR-016) so each one passes
     `./build.sh --quality` before merge.
  2. **Per-item migration tests**: each US (US7/US8/US9) ships
     with explicit edge-case tests (US7 covers malformed YAML
     / multi-doc / nested keys; US8 covers `./vault --help`
     byte-identical golden file; US9 covers invalid-settings
     error consistency).
  3. **Holdout-site documentation**: B4/B7 acceptance scenarios
     require each non-migrated call site to carry an inline
     comment explaining the constraint — auditable trail of
     why uniformity broke.

- **R3 — 022 v1 ship slips, blocking 025 merge (Q2 sequencing)**.
  *Risk*: 025's merge gate is `022 v1 ships + baselines committed`
  (FR-016). If 022 implementation slips past 2026-06-01, 025
  Tier A items (which the architect calls "mandatory pre-022")
  are blocked behind 022 — inverting their "pre-022" semantics.
  *Mitigations*:
  1. **Tier A exemption from FR-016**: Tier A items (US1/US2/US4/
     US5/US3 = A1/A2/A4/A5/A6) ship pre-022-v1 with the
     pytest + smoke gate only. Only Tier B items (US6–US9 =
     B3/B4/B5/B7) wait for the post-022-v1 quality gate.
     *Rationale*: A1/A2 fix LLM-bypass debt that 022 itself
     depends on (cost capture, fake_agent stubbability). They
     CANNOT gate on the thing they enable.
  2. **MVP fallback** (Q3b / SC-fallback): if 2026-05-29
     suggests slip, ship only Tier A; defer Tier B to
     follow-up specs.
  3. **Tag-trigger CI**: spec 022's tag-push GitHub Action
     (per 022's Q4 = Option B) catches harness regressions
     post-022-v1, decoupling 025's merge cadence from PR-level
     CI friction.

  **Implication**: FR-016 as written gates ALL 025 PRs on
  022 v1; R3 mitigation 1 *carves out Tier A*. Tasks.md must
  encode the carve-out explicitly. Spec text amended to
  reflect this — see FR-016 amendment below.

## Acceptance coverage

Per ADR-0008 § Spec acceptance coverage convention. Tier A (US1–US5 +
US10) ships in 0.3.0 with tests on disk; Tier B (US6–US9) is deferred
to tasks.md and ships in 0.3.1. Implementing-task references retained
as `T### in Phase N` for traceability.

| User Story | Evidence |
|------------|----------|
| US1 — A1: plan_narrator routes through agent_call.py | `tests/pipeline/test_plan_narrator.py::test_dispatch_through_agent_call` + `tests/pipeline/test_plan_narrator.py::test_codex_default_respected` (T010–T017 in Phase 3) |
| US2 — A2: probe-retrieval routes through agent_call.py | `tests/pipeline/test_cycle_runner_probe.py::test_dispatch_through_agent_call` + `tests/pipeline/test_cycle_runner_probe.py::test_probe_disabled_short_circuits` (T018–T025 in Phase 4) |
| US3 — A6: quality-report context-manager guard | `tests/pipeline/test_cycle_runner_quality_report.py::test_happy_path_writes_once` + `tests/pipeline/test_cycle_runner_quality_report.py::test_keyboard_interrupt_writes_once` (T026–T031 in Phase 5) |
| US4 — A4: auto-detect resume cycle | `tests/cli/test_research_resume.py::test_resume_auto_detects_cycle` + `tests/cli/test_research_resume.py::test_explicit_cycle_overrides_auto` (T032–T037 in Phase 6) |
| US5 — A5: doc sync (constitution, ROADMAP, build.sh) | `tests/docs/test_doc_sync.py::test_no_run_cycle_sh_references` (T038–T042 in Phase 7); the QW-2 wording clause this row also cited (`test_qw2_text_accurate`) was retired post-0.3.0 when QW-2 was pruned from ROADMAP — see the module docstring in `tests/docs/test_doc_sync.py` |
| US6 — B3: extract cycle-runner steps | _(deferred to tasks.md Phase 11, T054–T056 + T058a)_ |
| US7 — B4: shared frontmatter parser | _(deferred to tasks.md Phase 12, T068)_ |
| US8 — B5: split cli.py | _(deferred to tasks.md Phase 13, T076–T077)_ |
| US9 — B7: shared settings loader | _(deferred to tasks.md Phase 14, T086)_ |
| US10 — LLM dispatch guard allowlist reaches zero | `tests/_helpers/test_llm_dispatch_guard.py` + `tests/_helpers/llm_dispatch_allowlist.yaml` (allowlist file MUST contain `[]` or header comment only; LLM dispatch guard owned by spec 024 US1, ships with US10 satisfied) |

## Out of scope (covered elsewhere or explicitly deferred)

- **A3** (smoke meta-test restoration) → owned by **spec 024 US3**.
- **B1** (fake_agent verifier scenarios) → owned by **spec 024 US2**.
- **B2** (tier-5 cycle e2e wiring) → owned by **spec 024 US6**.
- **B6** (retire `test_e2e_synthetic_vault.py` mock pattern) →
  owned by **spec 024 US7**.
- LLM dispatch guard itself → owned by **spec 024 US1**.
- Quality-regression harness → owned by **spec 022**.
- `processors/extract.py` cleanup → known separate debt; future
  spec (SIMPLIFY-PASS § 8 explicit exception).
- **Tier C items (C1–C7)** — explicitly deferred until after 022
  v1 ships:
  - C1: Import `scripts/` into package (touches vault bundle).
  - C2: Remove legacy single-shot note-writer path (breaking).
  - C3: Unify spec/simple + detailed parsers (product decision).
  - C4: Decompose `orchestrator.py` (021 gap-pursuit pending).
  - C5: Split `research_plan.py` (021 extends).
  - C6: Full `./vault update` hardening (separate 2–3 day effort).
  - C7: ADR on 014/015 vs 020 (doc-only; blocks modules not simplify).
