# Tasks: Observability **v1.1** (Spec 048 — `vault status` + health header + print allowlist)

**Input**: [spec.md](./spec.md) (FR-009/010/011/013/014) · [plan-v1.1.md](./plan-v1.1.md) · [research-v1.1.md](./research-v1.1.md) · [contracts/vault-status-v1.1.contract.md](./contracts/vault-status-v1.1.contract.md)
**Status**: ready for `/speckit.implement`. No external gate — base (v1.0) is on `main`.
**Tests**: TDD. `[P]` = parallelizable (distinct files, no ordering dep). No LLM dispatch anywhere (Principle IV).

## Sequencing (READ FIRST)

> FR-013 (Phase 1) and the live-status backing (Phase 2) are **inputs** the
> `vault status` verb (Phase 3) consumes — do them first. The print allowlist
> (Phase 4) is orthogonal and fully `[P]`. Everything is stdlib-only; if any task
> wants a new dependency, STOP — Principle V.

---

## Phase 1 — One-line cycle-health header (FR-013) 🎯 US4

- [ ] **T001** `pipeline/cycle_summary.py::health_header(cycle_n, *, exit_code, notes_drafted, verifier_passed, spent, budget, elapsed_s, errors, warnings) -> str` — pure function emitting the contract §4 line. **Test first**: `tests/observability/test_health_header.py` — exact format for a known input; the STATUS truth table (FAIL on exit 2 / any gate FAIL / errors>0; WARN on warnings>0; PASS otherwise); `budget=None ⇒ "n/a"`; missing field ⇒ `?` (never raises).
- [ ] **T002** Wire `health_header()` as **line 1** of `write_summary()` (before `# Cycle N summary`). Source the fields deterministically per contract §4 (notes/verifier/spent from research+quality, elapsed from `timings.cycle_started_at`, errors/warnings from gate counts + incidents). **Test**: extend `test_health_header.py` — render a `tmp_path` cycle fixture, assert line 1 matches; `write_summary` still never raises on partial inputs.

**Checkpoint**: every `cycle-NNN-summary.md` opens with the scannable header; `health_header()` is now reusable by Phase 3 (FR-011) + spec 035.

---

## Phase 2 — Live-status backing: extended `state.json` + `cycle.log` (D1/D2)

- [ ] **T003** `pipeline/cycle_state.py` — typed `read(vault)->CycleState|None` / `write(vault, **fields)` for the contract §1 schema (`in_progress_cycle, cycles_budgeted, stage, cycle_started_at, budget_snapshot, updated_at`), atomic-write (reuse `pipeline/atomic_write`). **Test first**: `tests/observability/test_cycle_state.py` — round-trip; absent file ⇒ `None`; corrupt JSON ⇒ `None` + no raise; nullable budget fields.
- [ ] **T004** `observability/cycle_log.py::cycle_log_handler(vault, cycle_n)` context manager — attach a `FileHandler(cycle-NNN/cycle.log)` (v1.0 formatter) to the framework logger; detach + close on `__exit__` for ALL paths. **Test first**: `tests/observability/test_cycle_log.py` — `logger.info` inside the ctx lands in `cycle.log`; **no handler leak** across two sequential ctxs in one process (asserts handler count returns to baseline); open-failure ⇒ warning, no raise (fail-open).
- [ ] **T005** Wire `cycle_state.write` into `cycle_runner` at **each stage transition** (extend the `_state_write(... "state.json" ...)` seam, ~:263) with `stage` + `cycle_started_at` + a `budget_snapshot` read from the 033 budget guard. **Test**: `test_cycle_state.py` integration — drive a fake cycle through 2 stages; `state.json` reflects the current stage + a monotonic `updated_at`.
- [ ] **T006** Wire `cycle_log_handler` around the cycle body in `cycle_runner` — opens on start, closes on clean/constrained/abort/**kill** exit. **Test**: `test_cycle_log.py` integration — a cycle that raises mid-stage still closes the handler (no leak) and `cycle.log` holds the pre-failure lines.

**Checkpoint**: `state.json` answers "which stage, how long, how much budget left?"; `cycle.log` is the tail source for FR-010.

---

## Phase 3 — `vault status` verb (FR-009/010/011) 🎯 US1 (the polished half)

- [ ] **T007** `cli/status.py::render_active(state, last_log_line) -> str` — the ACTIVE 5-point plain block (contract §3): cycle N of M + stage, elapsed, wall+dollar budget remaining, last log line. **Test first**: `tests/observability/test_vault_status.py::test_active` — `tmp_path` vault with an active `state.json` + a `cycle.log` tail ⇒ all 5 points present; `(starting)` when `state.json` absent in cycle 1.
- [ ] **T008** `render_inactive(vault) -> str` — `(no active cycle)` + last cycle's **verbatim** FR-013 header (reuse `health_header()` via the last summary) + days-since-last-success + deferred warnings. **Test**: `test_vault_status.py::test_inactive` — no `state.json` ⇒ header line matches the last `cycle-NNN-summary.md` line 1; `(no cycles yet)` when `_pipeline/` empty.
- [ ] **T009** `--json` path — the stable object (contract §3) for both active + inactive. **Test**: `test_vault_status.py::test_json` — keys/types per contract; `active` toggles the null-field set.
- [ ] **T010** Register `status` in `cli/_parser.py` (`add_parser("status", …)` + `set_defaults`) reusing `--log-level`; add the `status)` case to the `./vault` shim template; `--vault` **required** (exit 2 + clear error if absent). **Test**: `test_vault_status.py::test_cli_wiring` — `status` is a distinct verb from `pipeline status`; missing `--vault` ⇒ exit 2 + message.
- [ ] **T011** `[P]` Edge cases + perf — invalid `--vault`, corrupt `state.json` ⇒ inactive + warning (no traceback); **<1s on a 1000-cycle history** (SC-003) by reading only state.json + last summary + bounded `cycle.log` tail. **Test**: `test_vault_status.py::test_edges` + `test_perf` (synthesize 1000 empty cycle dirs in `tmp_path`; assert wall-clock < 1s).

**Checkpoint**: `vault status --vault <path> [--json]` answers "is a cycle alive, and how's it doing?" in <1s.

---

## Phase 4 — Print-allowlist convention (FR-014) `[P]` 🎯 US5 expansion

- [ ] **T012** `[P]` Classify the ~13 `pipeline/` `print()` sites (`verifier` 3, `_cycle_helpers` 4, `research_plan` 3, `budget_guard` 2, `timings` 1): **progress-noise → migrate to `logger.info/warning`**; **genuinely-raw → keep + annotate** `# noqa: T201 — keep raw print: <reason>` (reason ∈ the contract §5 set). Create `tests/observability/print_allowlist.txt` listing only the kept ones.
- [ ] **T013** `[P]` Extend `tests/observability/test_log_surfaces.py` — re-count `^\s*print\(` across **all** of `src/research_framework/pipeline/`; assert the set ⊆ `print_allowlist.txt` (no NET-NEW unlisted print) AND each listed site's inline `# noqa` reason matches the file. **No ruff change** (CL-4).

**Checkpoint**: a future stray `print()` in `pipeline/` fails the smoke gate with a "use `logger` or allowlist with a reason" message.

---

## Phase 5 — Polish & cross-cutting

- [ ] **T014** `[P]` `docs/observability-strategy.md` — flip Tier-4 (`vault status`) and Tier-5 (`cycle.log`) from "planned" to real; document the verb + the cycle.log/bridge.log distinction; note FR-013 header consumers (vault status + spec 035).
- [ ] **T015** `[P]` `CHANGELOG.md [Unreleased]` (vault status verb, health header, cycle.log, print allowlist) + spec.md status header → SHIPPED on merge; ROADMAP `048 v1.1` row → implement/merged (per CLAUDE.md doc-sync).
- [ ] **T016** FR-016 gate: the new `test_vault_status.py` + `test_health_header.py` join the default `pytest -m "not e2e"` collection **and** `build.sh` smoke set (matching the shipped FR-015 test). `ruff check .` + `ruff format --check .` clean; full fast-loop green.

---

## Dependencies & ordering

- **No external gate** — v1.0 base is on `main`.
- **Within v1.1**: Phase 1 (header) + Phase 2 (state/log) → Phase 3 (status verb
  consumes both). Phase 4 (allowlist) is fully `[P]` from day 1. Phase 5 closes.
- FR-013's `health_header()` is the shared seam: Phase 1 produces it, Phase 3
  (FR-011) + spec 035 consume it — implement once.

## Acceptance coverage

| User Story | Tasks |
|---|---|
| US1 — Watch a cycle live (`vault status` half) | T007, T008, T009, T010, T011 |
| US4 — One-line cycle health header | T001, T002 |
| US5 — Regression guard (allowlist expansion) | T012, T013 |

## Implementation strategy

**Smallest-first**: ship FR-013 (header) alone (immediately useful + unblocks
035's soft consumer), then the state/log backing, then the `vault status` verb on
top. The print allowlist rides in parallel. Every surface fails **open** —
observability never fails a research cycle (SC-001 posture inherited from v1.0).
