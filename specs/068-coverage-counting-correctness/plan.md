# Implementation Plan: Coverage counting correctness

**Branch**: `068-coverage-counting-correctness` | **Date**: 2026-06-15 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/068-coverage-counting-correctness/spec.md`
**Target ship**: **1.0.0rc8 / 1.0.0** (rc8-wave umbrella #152; issue #156)

## Summary

The rc7 run wrote ~107 notes; `./vault digest` reports `0% → 0% (+0%)` for every
category and flags each "stagnant". Phase-0 code audit pins the root cause precisely:
`pipeline/coverage.py::update_after_cycle` **increments `met_count` from each cycle's
`research_report['notes_created']` list and never reconciles with the on-disk
`data_vault/` tree**. The stored `met_count` sums to ~14 while ~107 notes exist; the
digest (`pipeline/digest/sections.py::build_coverage_delta` → `_load_coverage_targets`)
reads that stale file, and against huge targets (250) the survivors round to 0% with
~0 cross-cycle delta. Crucially the notes already carry `coverage_category: concepts`
matching the target slug exactly — so it is **not** a naming mismatch (candidate #1
ruled out); it is the stale incremental model (candidate #2).

068 makes coverage a **derived-from-disk** quantity (clarify Q1/Q3):

| FR | What | Primary code target (Phase-0 verified) |
| --- | --- | --- |
| **FR1** | Recompute coverage by scanning `data_vault/` + reading each note's `coverage_category` frontmatter (skip `note_type: alias`); reuse `classify_note_category` resolution | `pipeline/coverage.py` — new `recompute_from_disk(vault_dir)`; `update_after_cycle` becomes a thin wrapper (or is replaced by the recompute) |
| **FR2** | Cycle-end invariant: the on-disk recount MUST equal the written `met_count`; fail loudly on divergence | `pipeline/coverage.py` (`recompute_from_disk` is the source of truth) + cycle-end call site in `pipeline/orchestrator.py` / `pipeline/steps/` |
| **FR3** | Digest Coverage-Delta + Gaps "stagnant" reflect the recomputed count; delta is cycle-over-cycle, not absolute-zero | `pipeline/digest/sections.py` (`build_coverage_delta`, `_load_coverage_targets`) consume recomputed values |
| **FR4** | `./vault status` surfaces the same recomputed count (one source of truth) | `cli/status.py` (`build_status_json`) |
| **FR5** | Multi-category quality fixture: N notes × M categories ⇒ digest shows real %, not `0% → 0%`; caught at `build.sh --quality` | `tests/fixtures/quality/` + `tests/quality/` + baseline |

Frontmatter `coverage_category` wins on directory disagreement (Q2). Derive-on-read
means stale vaults self-heal — **no migration verb** (Q3). No new runtime dependency
(Principle V). No `schema_version` bump (`coverage-targets.json` shape unchanged;
`met_count` becomes a recomputed cache). No ADR. Standalone spec (Q4).

## Technical Context

**Language/Version**: Python 3.11+ (per `pyproject.toml::requires-python`).
**Primary Dependencies**: stdlib + existing only — `pyyaml ≥ 6.0` (frontmatter),
`pathlib` (tree walk). Reuses `vault/frontmatter.parse_frontmatter` and the existing
`classify_note_category`. **No new runtime dependency** (Principle V).
**Storage**: filesystem under vault root. `coverage-targets.json::met_count` becomes a
recomputed cache (same schema). No new `_pipeline/` artifact.
**Testing**: pytest, seven-tier pyramid (ADR-0008). New tier-1 unit suite for
`recompute_from_disk` (slug/display-name/`NN - Title` dirs; alias-skip;
frontmatter-wins-over-dir WARN), tier-3 cycle-end invariant test, tier-2 digest +
status consistency, + the FR5 quality fixture (gated by `build.sh --quality`).
**Target Platform**: macOS / Linux dev + CI.
**Project Type**: single-project Python CLI + Jinja2-templated vault scaffold.
**Performance Goals**: recompute is O(notes) one frontmatter parse each, once per
cycle-end + once per digest/status read. For ~2k-note vaults this is sub-second; cache
the result per `(vault, data_vault-mtime)` if a hot-path read shows up (data-model
Entity 3). No cycle-throughput regression.
**Constraints**: determinism (Principle IV) — pure filesystem scan, no LLM. FR2 must
fail **loudly** (not silently re-write) when a divergence is detected, so a future
regression surfaces. Must skip `note_type: alias` stubs (spec-062 FR3) — already done
in `update_after_cycle:290–293`.
**Scale/Scope**: ~3 source files touched (`coverage.py`, `digest/sections.py`,
`cli/status.py`) + 1 cycle-end call site + 1 quality fixture; ~0.5–1 day. Adds
~20–30 tests + 1 fixture/baseline.

### Resolved unknowns (full detail in research.md)

- **D1** — Root cause = stale incremental `met_count` (candidate #2), **not** a
  frontmatter↔target naming mismatch (candidate #1 ruled out: notes carry
  `coverage_category: concepts` == target slug). `NN - Title` dirs (candidate #3) are a
  *fix constraint* (the recompute must read frontmatter, not infer category from dir).
- **D2** — `classify_note_category` is reused unchanged; only the **driver** changes
  from "iterate `notes_created`" to "walk `data_vault/*.md`". Its existing resolution
  (explicit `coverage_category` → keyword overlap → largest-gap round-robin) already
  handles the slug match.
- **D3** — `met_count` stays in `coverage-targets.json` (no schema bump) but is now
  **authoritatively recomputed**; the file is a cache. Digest cross-cycle delta reads
  per-cycle snapshots, so historical stale cycles won't retro-fix, but every cycle
  from rc8 forward writes the correct recount → deltas become correct + absolute
  coverage is correct immediately (derive-on-read at digest/status time).
- **D4** — FR2 invariant lives at cycle-end (after the note-writer + verifier stages
  land notes) in the orchestrator's coverage-update call site; on divergence it logs a
  loud **WARN** (decided at /analyze, U1 — WARN-and-trust) and trusts the recount.
- **D5** — Directory-vs-frontmatter disagreement → frontmatter wins, WARN logged
  (Q2). The dir is never used to assign a category in the recompute.

## Constitution Check

*GATE: evaluated against constitution v1.4.0.*

| Principle | Verdict | Notes |
| --- | --- | --- |
| **I. Script-Validated Quality Gates** | ✅ PASS (reinforces) | Coverage becomes a deterministic disk recompute; FR5 adds a `build.sh --quality` regression fixture so `0% → 0%` can't regress silently. |
| **II. Phase Sequencing** | ✅ PASS | No cycle-phase reordering; the recompute runs at the existing cycle-end coverage-update point. |
| **III. Test-First (TDD)** | ✅ PASS | Each FR ships its test file with/before impl; foreman `Testing Requirements` at `/tasks`. |
| **IV. Agent-Script Separation** | ✅ PASS (reinforces) | Pure filesystem scan; no LLM. Dispatch allowlist stays empty. |
| **V. Offline-First, No External Persistence** | ✅ PASS | No new dep; reads local notes only. |
| **VI. No Duplicate Notes** | ✅ N/A | Counting only; no note creation. |
| **VII. External Sources Mandatory** | ✅ N/A | Untouched. |
| **VIII. No Placeholders / Stub-as-Fuel** | ✅ PASS (reinforces) | Alias stubs are excluded from counts (062 FR3), so coverage reflects only real notes. |
| **IX. Vault-First Citation** | ✅ N/A | Untouched. |
| **X. Vault History is Append-Only Git** | ✅ PASS | `coverage-targets.json` rewrites use the existing atomic-write `save_targets`; committed by the normal cycle commit. |

**Ask-First items (resolved at /analyze):**
1. **FR2 divergence severity — DECIDED (analyze U1): loud WARN-and-trust.** When the
   cycle-end recount disagrees with the incrementally-written value, log a **loud WARN**
   and **trust the recount** (now the authoritative source). A hard ERROR/block is
   rejected: the recount is correct by construction, so blocking a cycle would punish
   legitimate transition states (e.g. a stale vault self-healing on first read) for a
   condition the recompute already fixes. No operator confirmation needed.

**Gate result: PASS.** Complexity Tracking empty.

### Post-Design Re-check (after Phase 1)

No new dependency, no new principle, no `schema_version` bump (data-model
"Migration": derive-on-read, file is a cache). The reused `classify_note_category`
(D2) keeps the change small and behaviour-compatible. Verdict remains **PASS**.

## Project Structure

### Documentation (this feature)

```text
specs/068-coverage-counting-correctness/
├── plan.md          # This file
├── spec.md          # Feature spec (clarified 2026-06-15, 4/4; root cause confirmed)
├── research.md      # Phase 0 — decisions D1–D5 + rc7 count evidence
├── data-model.md    # Phase 1 — CoverageCategory (derived), recompute fn, invariant, cache
├── contracts/
│   └── coverage-recompute.contract.md  # recompute_from_disk + cycle-end invariant + frontmatter-wins
├── quickstart.md    # Phase 1 — reproduce 0%→0%; prove disk recompute fixes it
└── tasks.md         # Phase 2 (/speckit.tasks — NOT created here)
```

### Source Code (repository root) — files touched, by FR

```text
src/research_framework/
├── pipeline/
│   ├── coverage.py          # FR1/FR2 (NEW recompute_from_disk): walk data_vault/, read coverage_category,
│   │                        #   reuse classify_note_category, skip note_type: alias; update_after_cycle → wrapper;
│   │                        #   cycle-end invariant (recount == written)
│   ├── orchestrator.py      # FR2: call recompute_from_disk at cycle-end (replace/augment update_after_cycle call)
│   └── digest/sections.py   # FR3: build_coverage_delta + _load_coverage_targets read recomputed met_count
└── cli/
    └── status.py            # FR4: build_status_json surfaces the recomputed coverage (same source as digest)

tests/
├── pipeline/
│   ├── test_coverage_recompute.py   # FR1: NN - Title dirs; slug + display_name match; alias-skip; frontmatter wins over dir (WARN)
│   └── test_coverage_invariant.py   # FR2: cycle-end recount == written; divergence surfaces
├── cli/
│   └── test_status_coverage.py      # FR4: status coverage == digest coverage (one source of truth)
└── quality/ + tests/fixtures/quality/
    └── multi-category fixture + baseline # FR5: N notes × M categories ⇒ real %, not 0% → 0%
```

**Structure Decision**: single-project layout, in-place change to the existing
`pipeline/coverage.py` counter (the shared module 035 digest + 048 v1.1 status both
consume). No new module; the driver flips from incremental to disk-scan. Consumers
(`digest/sections.py`, `cli/status.py`) read the recomputed value.

## Phase Sequencing for implementation (dependency-ordered)

FR1 is the core (the recompute); FR2 wires the cycle-end invariant on top; FR3/FR4
are consumers; FR5 validates end-to-end. Recommended `/speckit.tasks` ordering:

1. **FR1** (≈0.3d) — `recompute_from_disk(vault_dir)`: walk `data_vault/*.md`, parse
   frontmatter, skip `note_type: alias`, reuse `classify_note_category` per the note's
   `type`, count into `CoverageCategory.met_count`; frontmatter-vs-dir WARN. Make
   `update_after_cycle` delegate to it (or replace its call site). Unit tests on a
   fixture with `NN - Title` dirs.
2. **FR2** (≈0.2d) — call `recompute_from_disk` at cycle-end in `orchestrator.py`;
   add the invariant (recount == written) with the Ask-First severity. Test: a cycle
   that writes N notes ends with `met_count == N` per category.
3. **FR3** (≈0.2d) — `digest/sections.py` reads the recomputed `met_count`; "stagnant"
   is cycle-over-cycle delta (already delta-based — confirm it consumes the corrected
   counts). Test: a vault with notes shows real % + non-stagnant.
4. **FR4** (≈0.1d) — `cli/status.py::build_status_json` surfaces the same coverage.
   Test: status coverage == digest coverage.
5. **FR5** (≈0.2d) — multi-category quality fixture (N notes × M categories, mixed
   slug/display-name/`NN - Title`) + committed baseline asserting non-zero coverage %;
   gated by `build.sh --quality`.

**Pre-`/speckit.implement`**: dispatch the test-design subagent (ADR-0010); implement;
foreman Arm A + Arm B before the PR.

## Complexity Tracking

> No Constitution Check violations require justification. Table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
