# Implementation Plan: Observability v2 — Source-Consideration Ledger (MVP cut)

**Branch**: `048-v2-source-ledger` | **Date**: 2026-06-03 | **Spec**: [spec.md § v2 scope](./spec.md#v2-scope--source-consideration-ledger-added-2026-06-02--high-priority)
**Input**: Feature specification v2 scope from `/specs/048-observability-v1/spec.md` (the `## v2 scope — Source-Consideration Ledger` section + `### Clarifications — Session 2026-06-03`).

> **Scope (binding, per Clarifications 2026-06-03)**: This plan covers the **MVP cut only** — a **read-only** post-run script `scripts/source_ledger.py` implementing **FR-017** (per-source ledger artifact) + **FR-019** (fail-loud on a failure verdict, handled uniformly) by **joining existing artifacts**. **Zero pipeline change.** FR-018 (routing-derived MCP instrumentation), FR-020-as-pipeline-gate, and FR-021 (health-header surfacing) are deferred to a later promotion pass — see `## Out of scope for THIS plan`. FR-020's *verdict state machine* is implemented here (the script needs it); what's deferred is wiring that state machine *into the pipeline* and the MCP access-signal emission.

## Summary

Ship the **Source-Consideration Ledger**: a per-cycle JSON artifact + a per-run roll-up that answers, crisply and per declared source, *was it considered? did it contribute cited content? and if not, which of four causes applies* — `USED` / `SKIPPED_RELEVANCE` / `ACCESS_FAIL` / `QUALITY_REJECT` / `PIPELINE_DROP` / `NOT_REACHED`. Today those signals exist but are fragmented across 5–6 artifacts; reconstructing an (a-not-relevant / b-access-fail / c-pipeline-drop / d-quality-reject) verdict means hand-joining them, and a silent pipeline drop (c) is indistinguishable from a legitimate skip (a). That ambiguity is exactly what the three upcoming live evaluation runs (codebase-vault rebuild, new reference-vault, feeds-vault update) cannot afford to misread.

Concretely, the MVP is a single **read-only** script:

1. **`scripts/source_ledger.py`** — consumes the existing artifacts of one cycle (or a whole run), resolves each `spec.data_sources` entry through the deterministic FR-020 verdict state machine, and emits:
   - per-cycle `_pipeline/cycles/cycle-NNN-source-ledger.json` (the gate-consumable artifact — spec 053's trunk-inversion gate reads it), and
   - a run-level roll-up section printed to stdout and (optionally) written to `_pipeline/source-ledger-run.md` (read-only — the script writes its own roll-up block, it does not edit `run_report.py`'s writer).
2. **FR-019 fail-loud** — any *required* source that resolves to a failure verdict (`ACCESS_FAIL`, `PIPELINE_DROP`, `QUALITY_REJECT`) is surfaced **uniformly** (no special "unexplained silence" category — same path as a dead service or a wrong key, per Clarifications SL-Q2): a WARN line in the roll-up + a **non-zero exit code** from the script as the diagnostic signal in v1. Opt-in hard-fail (spec-033 `approval_gates` pattern) is a later promotion, not this MVP.

**Technical approach**: pure stdlib + the existing in-process readers. The script reuses `pipeline/source_manager.py` (sources.db `source_cycles.notes_generated` / `notes_referencing`), the scout report's `sources_consulted` `{name, searched, reason}` rows (`cycle-NNN-scout.json`), `cycle-NNN-source-incidents.json` + `_pipeline/source-incidents.md`, the capture-failure groups already aggregated by `cycle_summary._aggregate_capture_failures`, and the `cycle-NNN-quality-report.json` gates. It **adds no schema, no new pipeline write, no new dependency** — it is a documented *join + roll-up*, honouring `docs/observability-strategy.md`'s "don't fragment surfaces" anti-pattern.

## Technical Context

**Language/Version**: Python 3.11+ (per `pyproject.toml::requires-python` and constitution Technology Constraints).
**Primary Dependencies**: Standard library only — `json`, `sqlite3`, `pathlib`, `argparse`, `dataclasses`, `sys`, `re`. Reuses existing in-repo modules (`research_framework.pipeline.source_manager`, `research_framework.spec.schema`, `research_framework.pipeline.cycle_summary._aggregate_capture_failures`, `research_framework.vault.frontmatter`). Existing project dep `pyyaml ≥ 6.0` (already present) is used to load the spec. **No new runtime dependency** (Principle V upheld).
**Storage**: Filesystem under the vault root. New read artifact: `<vault>/_pipeline/cycles/cycle-NNN-source-ledger.json` (per-cycle, written by the script, never by the pipeline). Run-level roll-up printed to stdout and (optionally) written to `<vault>/_pipeline/source-ledger-run.md`. All *input* artifacts already exist and are only **read**.
**Testing**: `pytest` (existing). New tests under `tests/scripts/test_source_ledger.py` (Tier-2 unit/contract — the script is a `scripts/` deterministic tool, same tier as `tests/scripts/test_raw_capture.py` and `test_preflight_sources.py`). Fixtures: synthetic `_pipeline/` trees exercising each terminal verdict + the reconciliation invariant.
**Target Platform**: Linux + macOS (existing matrix). Windows out of scope.
**Project Type**: CLI tool (single project, `src/research_framework/` package + `scripts/` maintainer/per-vault tools).
**Performance Goals**: Ledger build for a typical run (≤ ~50 cycles, ≤ ~30 declared sources) completes in < 1 s. The frontmatter `notes_referencing` scan is the only O(notes) step and is already implemented + amortised in `source_manager._count_notes_referencing`; the script reuses sources.db's precomputed `source_cycles` rows rather than re-scanning where possible.
**Constraints**: **Zero pipeline change** (binding scope). The script must be runnable on a finished run with no re-execution of any cycle. Must degrade gracefully on a partial run (a cycle missing its scout/research/quality artifact resolves to `NOT_REACHED`, never crashes). `ruff check` + `ruff format --check` must stay at the zero baseline.
**Scale/Scope**: 1 new script (`scripts/source_ledger.py`, est. ≤ ~350 LOC) + 1 new test module + 1 contract + this plan/research/data-model/quickstart. The verdict state machine (FR-020) is a pure function (`resolve_verdict(...)`) — the deterministic heart, fully unit-tested. LOC budget: ≤ ~700 lines added net (incl. tests + fixtures).

## Constitution Check

*Gate run 2026-06-03 against constitution v1.4.0.*

| Principle | Status | Notes |
|---|---|---|
| I — Script-Validated Quality Gates (NON-NEGOTIABLE) | ✅ PASS | The ledger is a **diagnostic/observability** artifact, NOT a cycle gate in this MVP — it does not block a phase transition. FR-019's non-zero exit is an out-of-band diagnostic signal an operator/CI runs *after* a run, exactly the read-only-post-run posture the spec's MVP section mandates. Promoting it to an in-loop gate (opt-in hard-fail) is explicitly deferred. No existing exit-code semantics (0/1/2 in the orchestrator) are touched. The script's own exit codes are documented in its contract (0 = all required sources OK; non-zero = ≥1 required-source failure verdict). |
| II — Phase Sequencing (NON-NEGOTIABLE) | ✅ N/A | No phase work. The script runs post-run; it reads `_pipeline/` artifacts and never participates in the cycle loop or phase ordering. |
| III — Test-First (TDD — NON-NEGOTIABLE) | ✅ PASS | Work follows the foreman TDD pattern (ADR-0010). `resolve_verdict` and the join/reconciliation are pure-functional and get failing tests committed BEFORE the implementing code. No `pass`-body stubs ship. `--dry-run` is N/A — the script is read-only and writes only its own derived ledger artifact (it never modifies vault content or input artifacts); the contract documents this explicitly. |
| IV — Agent-Script Separation of Concerns | ✅ PASS | This is the principle the spec exists to serve. The script **validates/diagnoses**; it does NOT ask an agent for a verdict. The per-source `searched`/`reason` agent self-report is treated as an *input signal* (one of several joined), never as the authority — the deterministic state machine decides the verdict from the fused evidence. No `claude`/`codex` dispatch (LLM-dispatch guard stays green; allowlist stays empty). |
| V — Offline-First, No External Persistence (NON-NEGOTIABLE) | ✅ PASS | Pure stdlib. Reads only local `_pipeline/` artifacts + the local spec; writes only the local derived ledger. No telemetry, no cloud, no new dep. |
| VI — No Duplicate Notes | ✅ N/A | No note generation. |
| VII — External Sources Are Mandatory | ✅ PASS (reinforces) | The ledger is, in effect, the *measurement instrument* for VII — it makes "was every required external source consulted?" auditable per-source. It enforces nothing new but surfaces VII compliance. |
| VIII — No Placeholders in Deliverables | ✅ PASS | The one script ships as a working implementation with tests. FR-018/020-gate/021 are documented as deferred in the spec — they are NOT half-written stubs in this MVP's code. |
| IX — Vault-First Citation (NON-NEGOTIABLE) | ✅ N/A | No agent output / no generated prose. The ledger reports on citations (`notes_referencing`) but produces none. |
| X — Vault History is Append-Only Git (NON-NEGOTIABLE) | ✅ PASS / N/A | The script is a manual post-run diagnostic, not a framework verb that mutates the vault during a cycle. The ledger JSON it writes lands under `_pipeline/` and will be captured by whatever commits the run that produced it (or by the operator's next commit) — it does not introduce a new uncommitted-mutation path. Wiring the ledger emission *into* a committing pipeline verb is part of the deferred promotion, where Principle X re-applies. |

**ADR-0007 (mandatory smoke gate)**: The MVP is a standalone diagnostic script, not a release gate. Its test module (`tests/scripts/test_source_ledger.py`) runs in the default `pytest -m "not e2e"` collection. It is **not** added to `build.sh::SMOKE_TESTS` in this MVP (the script doesn't gate the build); a later promotion that turns FR-019 into an opt-in hard-fail would revisit smoke-gate membership. Compliant — no smoke-gate bypass introduced.

**ADR-0008 (seven-tier pyramid)**: The script's tests are Tier 2 (deterministic `scripts/` tool, like `raw_capture`/`preflight_sources`), the lowest tier that catches the bug per the decision tree. No e2e tier needed for a pure join.

**ADR-0010 (foreman verification pattern)**: `tasks.md` (produced by `/speckit.tasks`, NOT this command) will carry `### Testing Requirements` blocks; Arm A `verify_test_coverage.py` must pass before merge.

**Gate result**: ✅ PASS — no violations, no Complexity Tracking entries needed.

## Project Structure

### Documentation (this feature, v2 artifacts — suffixed `-v2` to avoid clobbering the shipped v1.0 plan)

```text
specs/048-observability-v1/
├── plan.md                              # v1.0 MVP plan (SHIPPED — untouched)
├── plan-v2.md                           # THIS FILE — v2 Source-Consideration Ledger MVP
├── spec.md                              # Feature spec (v2 scope + Clarifications 2026-06-03)
├── research-v2.md                       # Phase 0 — v2 join-source audit + decisions (this commit)
├── data-model-v2.md                     # Phase 1 — SourceLedgerEntry + verdict state machine (this commit)
├── quickstart-v2.md                     # Phase 1 — operator usage on the three live runs (this commit)
├── contracts/
│   ├── bridge-log-format.contract.md    # v1.0 (untouched)
│   ├── log-level-flag.contract.md       # v1.0 (untouched)
│   ├── logger-wiring.contract.md        # v1.0 (untouched)
│   └── source-ledger-v2.contract.md     # NEW — ledger JSON schema + verdict semantics + exit codes
└── tasks.md                             # v1.0 tasks (populated later for v2 by /speckit.tasks — NOT this command)
```

### Source Code (repository root)

```text
scripts/
└── source_ledger.py                     # NEW — read-only post-run ledger builder
                                         #   - resolve_verdict(...)  pure FR-020 state machine
                                         #   - build_cycle_ledger(...) per-cycle join
                                         #   - build_run_rollup(...) per-run aggregation + FR-019
                                         #   - main(argv) argparse CLI; exit code = FR-019 diagnostic

tests/scripts/
└── test_source_ledger.py                # NEW — Tier-2 unit/contract tests
                                         #   verdict-per-terminal-state, reconciliation invariant,
                                         #   FR-019 non-zero exit, partial-run NOT_REACHED, role roll-up
tests/fixtures/source_ledger/            # NEW — synthetic _pipeline/ trees per verdict (added by /speckit.tasks)
    ├── used/ skipped_relevance/ access_fail/ quality_reject/ pipeline_drop/ not_reached/
    └── reconcile/                        # declared-set == ledger-set invariant fixture
```

**Read-only inputs (NOT modified)** — the join sources, all pre-existing:

```text
<vault>/research.spec.md                                  # spec.data_sources (declared set, role, required, priority)
<vault>/_pipeline/sources.db                              # sources + source_cycles (notes_generated, notes_referencing)
<vault>/_pipeline/cycles/cycle-NNN-scout.json             # sources_consulted [{name, searched, reason}]  -> (a) signal
<vault>/_pipeline/cycles/cycle-NNN-research.json          # notes_created / discovered_sources
<vault>/_pipeline/cycles/cycle-NNN-source-incidents.json  # required-source degradation count  -> (b) signal
<vault>/_pipeline/source-incidents.md                     # append-only degradation log (host/reason)  -> (b) signal
<vault>/_pipeline/cycles/cycle-NNN-quality-report.json    # verifier/gate verdicts  -> (d) signal
   (capture failures: reused via cycle_summary._aggregate_capture_failures over the same inputs -> (b) host/reason)
```

**Structure Decision**: The MVP is a **`scripts/` tool, not a `pipeline/` module** — deliberately, to keep "zero pipeline change" structurally true (a `scripts/` file cannot be imported into the cycle loop by accident) and to match the established read-only diagnostic convention (`scripts/raw_capture.py`, `scripts/preflight_sources.py`, `scripts/agent_call.py`). The verdict state machine is the only logic with a future pipeline home; it is written as a **pure importable function** so a later promotion (FR-020 in-pipeline) can lift it into `pipeline/` without rewrite. Tests live under `tests/scripts/` (Tier 2), mirroring the existing `scripts/` test layout.

## Phase 0 — Research findings

*The hard decisions were resolved in `/speckit.clarify` (Session 2026-06-03). Phase 0 here audits the six join sources to confirm each signal is present + addressable, and pins the four open design micro-decisions.* See `research-v2.md` for the full notes.

| Topic | Decision | Rationale |
|---|---|---|
| Which artifact carries the (a) "not relevant" signal | Scout report `sources_consulted` rows `{name, searched: bool, reason: str}` at `cycle-NNN-scout.json` (verified: parsed by `validate_sources_v2`; prompt template at `_cycle_helpers.py:443`) | It is the *only* per-source agent self-report; a non-empty `reason` yields `SKIPPED_RELEVANCE` (trusted for this MVP — bad-faith trunk-skips → spec 053); unexplained silence (`PIPELINE_DROP`) is the state machine's loud (c) signal |
| Which artifacts carry contribution (USED) | `sources.db::source_cycles.notes_generated` + `notes_referencing` (verified: `source_manager.record_cycle` upserts both; `notes_referencing` = citations via frontmatter scan, `source_manager.py:138`) | Already computed per (source, cycle); the ledger reuses these rather than recomputing |
| Which artifacts carry (b) access-fail | `cycle-NNN-source-incidents.json` count (`_cycle_helpers.py:774`) + `source-incidents.md` (required sources) + capture-failure groups (`_aggregate_capture_failures`: host+reason incl. `JS_SHELL`/`THIN`/404, `cycle_summary.py:89`) | Two complementary surfaces; required-source degradation is the strong signal, capture-failure host/reason the supplementary one |
| Which artifact carries (d) quality-reject | `cycle-NNN-quality-report.json` gates (verified: read by `cycle_summary._gate_lines`, `:111`) | The verifier/gate verdict is the (d) authority |
| MCP-backed-ness for FR-018 | **DEFERRED** — routing-derived (module `managed:true` per spec 054), but spec 054 has not shipped and `managed` is not yet a manifest field (`discovery.ModuleManifest` has `triggers` + `preflight`, no `managed`) | Per Clarifications SL-Q3, MCP-backed is derived from the routing result; the routing input (`managed`) does not exist yet -> FR-018 cannot be implemented without a cross-spec dependency -> correctly out of MVP scope |
| Verdict precedence when signals conflict | Deterministic priority order in `resolve_verdict` (USED > QUALITY_REJECT > ACCESS_FAIL > SKIPPED_RELEVANCE > PIPELINE_DROP > NOT_REACHED), documented in the contract | A source can have multiple weak signals across cycles; one verdict per source per the spec's acceptance criterion requires a total order |

## Phase 1 — Design artifacts

**Generated files** (this commit, alongside `plan-v2.md`):

1. **`research-v2.md`** — the six-source join audit (each signal located + line-cited), the four micro-decisions above with alternatives rejected (e.g. *re-running cycles to recompute* rejected per zero-pipeline-change; *trusting the agent `searched` flag as authority* rejected per Principle IV + the 0.6.0 drift postmortem; *a new SQLite ledger table* rejected — it's a join, not a new store), and the explicit cross-spec dependency note for FR-018 (spec 054 `managed`).
2. **`data-model-v2.md`** — the entities:
   - **`SourceLedgerEntry`** (per source, per cycle and rolled up): `name`, `role`, `required`, `priority`, `declared`, `considered`, `fetch_attempted`, `fetch_outcome`, `notes_generated`, `notes_referencing`, `verdict`, `reason` (carried through from the agent self-report when `SKIPPED_RELEVANCE`), `evidence` (which input artifact(s) supplied each field).
   - **`VerdictStateMachine`** — the FR-020 table as a pure decision function + the documented precedence total-order; the single normative source the contract and tests both reference.
   - **`RunRollup`** — per-source roll-up across cycles + per-`role` aggregation (`behaviour`/`intent`/`domain`), the reconciliation invariant (declared-set ≡ ledger-set), and the FR-019 required-source-failure summary that drives the exit code.
3. **`quickstart-v2.md`** — operator-facing usage for the three live runs: run the script on a finished run, read the per-source table, interpret each verdict, use the non-zero exit as a CI signal, and how spec 053's trunk-inversion gate consumes `cycle-NNN-source-ledger.json`.
4. **`contracts/source-ledger-v2.contract.md`** — the normative JSON schema of `cycle-NNN-source-ledger.json` + the run roll-up block, the verdict enum + state-machine precedence, the reconciliation invariant, and the script's CLI surface + exit-code semantics (FR-019).

**Agent context update**: per the task constraints, `update-agent-context.sh` is **NOT** run and nothing outside `specs/048-observability-v1/` is edited. The new technologies (read-only ledger join, `source_ledger.py`) will be registered in `CLAUDE.md` Active Technologies at ship time, not at plan time.

**Constitution re-check post-design**: Same as Phase 0 — still ✅ PASS, no violations introduced. The design keeps the verdict logic a pure function (no agent self-assessment -> Principle IV holds) and adds no store/dep (Principle V holds).

## Complexity Tracking

No Constitution violations to justify. Section intentionally empty per template guidance.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| _(none)_ | — | — |

## Out of scope for THIS plan (deferred to a later promotion pass)

These are in the spec's v2 scope but **NOT** addressed by this MVP plan (per the spec's "MVP (if the full scope can't land before the live runs)" section + Clarifications 2026-06-03):

- **FR-018 — MCP access instrumentation (routing-derived).** Requires the module-routing result to expose `managed: true` (spec 054) so an empty managed source resolves to `ACCESS_FAIL` not `SKIPPED_RELEVANCE`. **Hard-blocked**: spec 054 has not shipped and `managed` is not yet a `manifest.yaml` field nor on `discovery.ModuleManifest`. Until then, an MCP-backed source with no other signal falls through to `SKIPPED_RELEVANCE` (its agent reason) or `PIPELINE_DROP` (no reason) — the known v1 blind spot, documented in the contract. No `[NEEDS CLARIFICATION]` is raised because the spec already routes this to spec 054 explicitly; it is a sequencing dependency, not an unresolved decision.
- **FR-020 as an in-pipeline gate.** The *state machine* ships here (the script needs it); wiring it into the cycle loop / orchestrator exit paths is the promotion. The function is written importable so the promotion is a lift, not a rewrite.
- **FR-021 — surface the roll-up in the cycle-summary health header / `vault status`.** Depends on FR-013 (one-line health header, itself v1.1-deferred) and the `vault status` verb (also v1.1-deferred). Lands when those ship.
- **Opt-in hard-fail (spec-033 `approval_gates` pattern).** v1 is WARN + non-zero diagnostic exit only (Clarifications SL-Q2). The opt-in in-loop hard-fail is a later promotion.

## Next command

`/speckit.implement` — tasks + analyze complete (`tasks-v2.md`). Implementation follows 3 task groups:

1. **Verdict state machine (pure core)** (3 tasks): `resolve_verdict` table + precedence total-order + per-terminal-state unit tests (TDD: tests first).
2. **Join + ledger build** (3–4 tasks): per-cycle join over the six inputs -> `SourceLedgerEntry`, reconciliation invariant (declared-set ≡ ledger-set), per-cycle JSON writer, partial-run `NOT_REACHED` degradation.
3. **Run roll-up + CLI + FR-019** (2–3 tasks): per-source/per-`role` roll-up to stdout + optional `_pipeline/source-ledger-run.md` (`--write-rollup`; does not edit `run_report.py`), `argparse` CLI, non-zero exit on required-source failure + its test.

Each task ships with a `### Testing Requirements` block per ADR-0010 (foreman pattern). Tests are Tier-2 (`tests/scripts/`). Estimated MVP wall-clock: ~1.5–2 days (a pure join + a state machine; no pipeline surgery).
