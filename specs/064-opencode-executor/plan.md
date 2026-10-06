# Implementation Plan: opencode Executor (provider-agnostic agentic runtime)

**Branch**: `064-opencode-executor` | **Date**: 2026-06-11 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/064-opencode-executor/spec.md`

## Summary

Wire `opencode` (the open-source agentic CLI, v1.16.2 probed locally) as the **4th first-class executor** through the single `scripts/agent_call.py` / `_RUNTIME_ADAPTERS` dispatch surface, exactly mirroring how spec 052 added `cursor-agent`. opencode's distinguishing property is that the **model provider is a free-floating `--model provider/model` config value** (Ollama local, OpenAI, Anthropic, Google, OpenRouter…), so the framework gains N providers for the cost of integrating one executor — and it is *agentic* (writes files), which closes the dead-end that 047's non-agentic Ollama-HTTP primitive hit.

The technical approach is deliberately small and pattern-faithful: a `_opencode_cmd` adapter + an `opencode` branch in `_build_command` (for the `--dir` vault-scoping flag, the codex-`--cd` / cursor-`--workspace` analogue), a per-call cost classifier (local ⇒ measured `$0` `cost_source: runtime`; metered ⇒ real tokens + estimator `cost_source: runtime_tokens`), a `settings.opencode.yaml` peer profile (cloned from `settings.cursor.yaml`), and a one-line benchmark guard test (opencode is already a valid benchmark runtime once it is in `_RUNTIME_ADAPTERS`). The optional `label` field on the benchmark matrix executor block is the only net-new data shape.

## Technical Context

**Language/Version**: Python 3.11+ (`requires-python = ">=3.11"`); stdlib + `jinja2 ≥ 3.1` + `pyyaml ≥ 6.0` only — **no new runtime dependency** (Principle V). `opencode` itself is an external binary the operator installs out-of-band (like `cursor-agent` / `gh`), not a Python dep.
**Primary Dependencies**: `scripts/agent_call.py` (`_RUNTIME_ADAPTERS`, `_build_command`, cost-resolution + sidecar tail); `pipeline/settings.py` (typed settings loader); spec-028 sidecar writer; spec-033 budget guard/estimator; `src/research_framework/benchmark/` (matrix/runner/reporter); the wheel force-include + bundle copy list for `settings.*.yaml`.
**Storage**: Filesystem. New/changed artifacts: `settings.opencode.yaml` (repo root + wheel `_data/` + bundle); per-call sidecars under `<vault>/_pipeline/cycles/cycle-NNN/agent-calls/*.json` (schema unchanged — `executor: opencode`, `cost_source` reused literals). No schema bump expected (the `cost_source` literal set already includes `runtime` / `runtime_tokens` / `estimated` / `none`).
**Testing**: pytest seven-tier pyramid (ADR-0008). Fake-agent harness (`tests/_helpers/fake_agent.py`) for hermetic cycle tests; LLM-dispatch guard (allowlist stays EMPTY); `live_llm` opt-in for the real local-Ollama-through-opencode cycle and the opt-in hosted run. `build.sh --quality` (spec-022, 3 fixtures) for non-regression.
**Target Platform**: macOS + Linux (CI portability guard, spec 009). opencode ships for both.
**Project Type**: Single project — CLI research-pipeline framework. (No web/mobile split.)
**Performance Goals**: No new perf target. SC-001 = a local-Ollama cycle completes; latency is recorded (spec 028) but not gated (the wall-clock cap, spec 033, is the operative bound for unattended local runs).
**Constraints**: Offline-capable (Principle V) — opencode-on-local-Ollama is the offline-first story. Vault-write containment (FR-010) via `opencode run --dir <vault>` — NEVER `--dangerously-skip-permissions` as a write-scope mechanism (it is an approval lever, not a sandbox; writes are scoped by `--dir`). Single dispatch surface (FR-002) — no second dispatch script.
**Scale/Scope**: ~1 new adapter fn + 1 dispatch branch + 1 cost-classifier helper + 1 settings profile + benchmark `label` field + guard test + tests. Estimated small-to-medium, single PR.

### Resolved unknowns (see `research.md`)

The spec carried three plan-time risks; all are resolved — by the `opencode --help` probe (v1.16.2) AND a **live run against the operator's ollama box** (2026-06-11; `research.md` R1/R2/R3 VERIFIED sections):

- **FR-010 vault containment** → `opencode run --dir <vault>`. **VERIFIED** — a real run wrote its file inside `--dir`, nothing outside.
- **FR-003 headless + parseable** → `opencode run --format json` emits **NDJSON**; cost/tokens come from `step_finish` events (`part.tokens.*` + `part.cost`). **VERIFIED** against a live $0 ollama run.
- **FR-009 agentic stage-write** → the live run used opencode's `write` tool to produce the requested file (exit 0) — the thing the 047 HTTP primitive could not do. **VERIFIED**.
- **Model-tier map (FR-004)** → `--model provider/model` + `--variant high|max|minimal`. **Resolved** (probe).
- **Cost (FR-006/007)** → local ⇒ real `cost: 0` + real tokens (`runtime`); metered ⇒ real per-call dollar from opencode's pricing catalog (`runtime`), estimator only as fallback. **VERIFIED** (local arm).

No remaining `NEEDS CLARIFICATION`. The only residual VERIFY@IMPL is whether `--dir` *hard-denies* an explicit out-of-dir absolute-path write (SC-005's implementation target) — non-blocking for tasks.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution v1.3.4 (`.specify/memory/constitution.md`). Relevant gates:

| Principle | Status | Notes |
|---|---|---|
| **I. Script-Validated Quality Gates** | ✅ PASS | opencode is a dispatch mechanism; gates (`validate_*.py`, verifier) are runtime-agnostic and unchanged. A weaker local model that writes malformed artifacts is caught by the *same* gates — this spec must NOT weaken them (Edge Cases). |
| **III. Test-First (TDD)** | ✅ PASS | New adapter/classifier/profile land test-first (tier-2 unit for `_opencode_cmd` + cost classifier; tier-3/4 for cycle wiring; `live_llm` for the real run). Foreman `### Testing Requirements` to be authored at `/speckit.tasks`. |
| **IV. Agent-Script Separation** | ✅ PASS | No agent self-assessment added. The LLM-dispatch guard allowlist stays EMPTY; opencode is reached only via `agent_call.py`, never a direct subprocess in `src/`. |
| **V. Offline-First, No New Deps** | ✅ PASS — *strengthened* | opencode-on-local-Ollama is a purer offline story than today. **Zero new Python runtime deps** — opencode is an external binary (operator-installed, like `cursor-agent`). |
| **IX. Vault-First Citation** | ✅ PASS | Citation policy is runtime-agnostic prompt/template behavior; opencode honors the same Jinja2-rendered prompts. (Template vendor-neutrality is a soft risk tracked in `research.md`, not a gate.) |
| **X. Vault History Append-Only Git** | ✅ PASS | Cycle commit/append behavior is orchestrator-owned, not executor-owned; FR-009 requires opencode to satisfy the *same* stage-output + commit contract. |

**No violations.** Complexity Tracking table left empty.

## Project Structure

### Documentation (this feature)

```text
specs/064-opencode-executor/
├── plan.md              # This file
├── research.md          # Phase 0 — opencode CLI surface, cost model, autonomy, benchmark
├── data-model.md        # Phase 1 — adapter/profile/sidecar/benchmark-label entities
├── quickstart.md        # Phase 1 — how to run a vault + benchmark on opencode
├── contracts/
│   ├── opencode-adapter.contract.md     # _opencode_cmd command shape + dispatch branch
│   ├── settings.opencode.contract.md    # the peer settings profile contract
│   └── benchmark-label.contract.md      # optional matrix `label` field
├── spec.md
└── tasks.md             # /speckit.tasks output (NOT created here)
```

### Source Code (repository root)

```text
scripts/
└── agent_call.py                # + _opencode_cmd adapter, opencode branch in _build_command
                                 #   (--dir), opencode cost classification in _resolve_cost,
                                 #   register opencode in _RUNTIME_ADAPTERS + _LLM_AGENT_NAMES

settings.opencode.yaml           # NEW — peer of settings.cursor.yaml (root copy)

src/research_framework/
├── _data/settings.opencode.yaml # NEW — wheel force-include (build copies root → here)
└── benchmark/
    ├── matrix.py                # + optional Executor.label; Cell key uses label when present
    └── reporter.py              # label surfaces in the report rows

dist-templates/                  # bundle copy list gains settings.opencode.yaml (build.sh)

tests/
├── scripts/test_agent_call.py           # + TestOpencode (cmd shape, --dir, cost classify)
├── pipeline/…                            # + opencode cycle wiring (fake-agent) tests
├── benchmark/test_matrix.py             # + opencode-in-valid_runtimes guard; label cells
└── _helpers/fake_agent.py               # opencode handler parity (if any new shape needed)
```

**Structure Decision**: Single-project CLI framework. opencode plugs into the **existing** dispatch seam (`scripts/agent_call.py`) — no new package, no new top-level dir. The only net-new files are the `settings.opencode.yaml` profile (+ its `_data/` wheel copy) and this spec's docs. Everything else is additive edits to four existing files (`agent_call.py`, `matrix.py`, `reporter.py`, `build.sh` copy list) plus tests, which is what keeps FR-014 (zero change to the other three executors) cheap to guarantee.

## Complexity Tracking

> No Constitution Check violations — table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |

## Phase notes

- **Phase 0 (`research.md`)** — DONE: opencode CLI surface (probed), cost-classification model (the one genuinely new design decision — opencode is *not* statically flat-rate/HTTP like cursor/ollama; its cost class is per-call, model-dependent), autonomy posture (opencode permissions vs `--dangerously-skip-permissions`), template vendor-neutrality risk, benchmark integration + label.
- **Phase 1 (`data-model.md` + `contracts/` + `quickstart.md`)** — DONE: entities and the three contracts below.
- **Phase 2 (`/speckit.tasks`)** — NOT in this command. Will decompose into TDD tasks with foreman `### Testing Requirements`.

### Open decision deferred to tasks (recorded, not blocking)

- **047 HTTP-branch retirement** (FR-017 / Out of Scope): leave the shipped `_dispatch_http` / `_HTTP_RUNTIMES = {ollama}` branch **dormant** (do not delete) in this spec. Rationale: it is dead-but-harmless, still a valid benchmark cell, and deleting it is an orthogonal change with its own regression surface. Revisit only if it starts to rot. This is the plan-time call FR-017 asked for.
