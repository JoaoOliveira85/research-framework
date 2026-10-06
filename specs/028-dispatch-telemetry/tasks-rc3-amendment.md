# Tasks (rc3 amendment): codex-runtime cost telemetry

**Input**: `specs/028-dispatch-telemetry/plan-rc3-amendment.md` + the spec's "rc3 amendment" section.
**Scope**: the amendment only — the shipped 028 `tasks.md`/behaviour is untouched.

**Tests**: INCLUDED (Principle III). (Foreman test-design subagent enriches before
`/speckit.implement`, ADR-0010.)

**Organization**: grouped by amendment requirement (A1–A3). Order per plan: A3 → A2 → A1.

**Requirement map (→ spec FR ids)**: **A1** (best-effort first-class parse) + **A2**
(estimator fallback) together satisfy **FR-028A** (codex cost capture) and **FR-028B**
(no silent `$0`); **A3** (`cost_source` + schema 1.2) = **FR-028C**.

**`cost_source` literal (canonical, per spec FR-028C + H1 reconciliation)**:
`"runtime"` (measured from the runtime's own signal — generic, also fits cursor-agent
/052) | `"estimated"` (spec-033 estimator fallback) | `"none"` (estimator also failed —
emits a WARNING). The earlier `"codex"`/`"estimate"` draft literals are retired.

## Format: `[ID] [P?] [Ax] Description`

---

## Phase 1: Setup

- [x] T001 Confirm green baseline: `pytest tests/scripts/test_agent_call.py -q` + `ruff check .` pass.

---

## Phase 2: A3 — `cost_source` discriminator + sidecar schema 1.1 → 1.2

**Goal**: the sidecar carries `cost_source ∈ {"runtime","estimated","none"}`; schema bumps to `1.2` (additive).
**Independent Test**: a written sidecar has `schema_version: "1.2"` + a `cost_source` field; existing consumers tolerate it.

- [x] T002 [P] [A3] Write `tests/scripts/test_agent_call_codex_cost.py` (RED, shape half): a codex dispatch sidecar has `schema_version: "1.2"` and a `cost_source` field.
- [x] T003 [A3] In `scripts/agent_call.py`: bump `_SIDECAR_SCHEMA_VERSION` to `"1.2"` and add `cost_source` to `_build_sidecar_v11_payload` (rename/extend to v12); keep all existing fields. Make T002 (shape) GREEN.
- [x] T004 [P] [A3] Confirm `pipeline/cost_estimator.py` + any sidecar reader (`_historical_sidecar_costs`, dispatch-telemetry sums) tolerate the new field (`.get()`-based) — add a regression assertion if not.

---

## Phase 3: A2 — Estimator fallback for runtimes with no parsed cost

**Goal**: when a non-claude dispatch yields no parsed cost, fall back to the spec-033 `cost_estimator` value with `cost_source: "estimated"` (never silent `$0`).
**Independent Test**: a codex dispatch with no cost signal writes the estimator's `cost_usd`/tokens + `cost_source: "estimated"`; `total_cost_usd` is non-zero.

- [x] T005 [A2] Extend `tests/scripts/test_agent_call_codex_cost.py` (RED): codex + no parsed cost ⇒ sidecar `cost_usd == estimator value`, `cost_source == "estimated"`; total run cost reflects it.
- [x] T006 [A2] In `scripts/agent_call.py` `_write_dispatch_sidecar_for_result` (and the CLI path): for non-claude runtimes with no parsed `cost_usd`, call `pipeline.cost_estimator` for the stage and write its `cost_usd`/`codex_tokens` with `cost_source: "estimated"`. Make T005 GREEN.
- [x] T007 [P] [A2] Add `tests/pipeline/test_dispatch_telemetry_cost_source.py`: `total_cost_usd` in the run summary reflects estimated codex spend (not `$0`).

---

## Phase 4: A1 — Best-effort first-class codex cost parse

**Goal**: if codex emits a parseable per-call cost/token signal, use it (`cost_source: "runtime"`); otherwise the A2 estimate stands.
**Independent Test**: a codex output carrying a cost signal ⇒ `cost_source: "runtime"` with the parsed value; output with none ⇒ falls back to estimate (A2).

- [x] T008 [A1] Investigate + document codex's actual cost/token output shape (residual unknown F4); record the finding in the amendment's research note (parseable or not).
- [x] T009 [A1] Add `_codex_cost_from_output(...)` to `scripts/agent_call.py` (sibling to `_apply_stream_event`); on a successful parse, overwrite the sidecar cost with `cost_source: "runtime"`; on no signal, no-op cleanly (A2 estimate stands).
- [x] T010 [A1] Extend `tests/scripts/test_agent_call_codex_cost.py`: parsed-codex branch ⇒ `cost_source: "runtime"` + parsed value; no-signal branch ⇒ `"estimated"`; total-failure-to-estimate ⇒ `"none"` + a WARNING. Make GREEN.

---

## Phase 5: Polish

- [x] T011 [P] Update the 028 sidecar schema reference / contract note to `schema_version: "1.2"` (additive `cost_source`).
- [x] T012 [P] `ruff check .` + `ruff format --check .`; `pytest tests/scripts/test_agent_call_codex_cost.py tests/pipeline/test_dispatch_telemetry_cost_source.py`.
- [x] T013 CHANGELOG `[1.0.0rc3]`: codex cost telemetry (try-parse-else-estimate, `cost_source`, schema 1.2).

---

## Dependencies & Execution Order

- A3 (T002–T004) first — the shape everything writes. Then A2 (T005–T007, the always-on
  fallback). Then A1 (T008–T010, best-effort first-class) layered on top.
- This amendment is a prerequisite for the clean signal of spec 063 GA-005 (cost gate),
  which FAILs loud on `$0` even without it.
