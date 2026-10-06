# Specification Quality Checklist: Observability **v1.1**

**Purpose**: Validate the v1.1 FR set (FR-009/010/011/013/014) before implementation
**Created**: 2026-06-03 · **Feature**: [spec.md](../spec.md) (v1.1 subset) · **Artifacts**: `*-v1.1.*`
**State**: post-clarify (CL-1..CL-4) + plan + research + contract + tasks + analyze.
**IMPLEMENT-READY** — no external gate (v1.0 base shipped 0.5.0 on `main`).

## Content Quality
- [x] No implementation detail leaks into the FRs (the *what*; schemas/formats live in `contracts/vault-status-v1.1.contract.md`)
- [x] Operator value clear (live "is the cycle alive + how's it doing?" + a scannable per-cycle one-liner)
- [x] Maps to existing user stories (US1 `vault status` half, US4 health header, US5 allowlist expansion) with the v1.0 acceptance scenarios still valid
- [x] All mandatory sections present (v1.1 reuses the shipped spec.md; adds a localized "v1.1 clarified" subsection + the planning artifacts)

## Requirement Completeness
- [x] **No `[NEEDS CLARIFICATION]` markers remain** — CL-1..CL-4 resolved (2026-06-03):
  - CL-1 → extend `_pipeline/state.json` (stage + `cycle_started_at` + `budget_snapshot` + `cycles_budgeted`)
  - CL-2 → per-cycle `cycle.log` `FileHandler` as the FR-010 tail source
  - CL-3 → new first-class `status` verb, distinct from `pipeline status`
  - CL-4 → count-based allowlist test over all `pipeline/` + `# noqa: T201` reasons (no ruff change)
- [x] Requirements testable + unambiguous (every v1.1 FR → ≥1 task + a contract rule)
- [x] Success criteria measurable (SC-003 `vault status` <1s on 1000-cycle history; FR-013 line-1 format; no NET-NEW unlisted print)
- [x] Determinism explicit (status/header/test are pure deterministic reads; STATUS truth table is total; LLM-free)
- [x] Out-of-scope respected (no metrics push / tracing / alerting — those stay v2; the v2 Source-Ledger FR-017..021 is a SEPARATE line, untouched here)

## Cross-spec / cross-artifact consistency (from /analyze + 2026-06-03 audit)
- [x] **Stale-count reconciled** — spec's "~45 non-hot-path prints" corrected to the real **~13** in `pipeline/`; FR-014 scope + the allowlist test are sized to reality
- [x] **FR-010 data plumbing reconciled** — `state.json` (was `{in_progress_cycle}` only) extended; a real `cycle.log` created to satisfy "tail of the cycle log" (v1.0 logged to stderr, no file)
- [x] **Verb-placement reconciled** — new `status` verb kept distinct from the shipped phase-level `pipeline status` (`research_cycles.py:61`)
- [x] **`cycles_budgeted` reconciled** — the contract's "N of M" / JSON `cycles_budgeted` is now in the §1 `state.json` schema + T003 (single-read invariant preserved)
- [x] **FR ↔ task mapping complete** — FR-009→T007-T011, FR-010→T003/004/005/006/007, FR-011→T008, FR-013→T001/002, FR-014→T012/013; acceptance table US1/US4/US5 verified against `tasks-v1.1.md`
- [x] **No contradiction with v1.0** (extends, doesn't replace: logger, `bridge.log`, FR-015 test, `--log-level`) **nor v2** (FR-017..021 untouched; spec.md edits are mid-document, away from the v2 section)
- [x] Principle IV (deterministic, no LLM dispatch), V (stdlib `logging`/`argparse`/`json` — no new dep), X (`vault status` read-only; `cycle.log`/`state.json` under `_pipeline/`)
- [x] Test isolation (spec 026) — status/header/cycle.log/perf tests use `tmp_path` vaults; the 1000-cycle perf fixture is synthesized in `tmp_path`

## Notes
- **No blocker** — v1.0 base is on `main`, so v1.1 is implementable immediately; the three FR groups are independent (header → state/log → status verb; allowlist `[P]`).
- **Soft cross-ref**: FR-013's `health_header()` is consumed by spec 035's digest (implement-ready, unmerged) and by FR-011 — implemented once, no hard ordering (035 falls back to its own artifacts).
- `/analyze`: after the `cycles_budgeted` fix, **no contradictions** among spec ↔ contract ↔ plan ↔ tasks.
- Two implement-time validations flagged in plan Complexity: (1) the live wall/dollar `budget_snapshot` is readable mid-cycle from the 033 guard (else graceful `n/a`); (2) the `cycle.log` handler detaches on EVERY exit path (reusing v1.0's leak-fix) — a no-leak regression test pins it (T004/T006).
- **Isolation choice**: v1.1 ships as `*-v1.1.*` files (not edits to the shipped v1.0 artifacts) precisely to avoid a merge clash with the parallel `048-v2-source-ledger` branch on the same spec dir.
