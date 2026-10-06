---
description: "Task list — Spec 064 opencode Executor"
---

# Tasks: opencode Executor (provider-agnostic agentic runtime)

> **Ledger** — this spec shipped; the boxes below are a historical record, not a live gate (CONTRIBUTING.md § 2). The Status header in `spec.md` is the source of truth for what shipped.

**Input**: Design documents from `specs/064-opencode-executor/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: INCLUDED — TDD is non-negotiable (Constitution Principle III). Every
code task is preceded by the test that must fail first (config-asset tasks
included — see Phase 4). The LLM-dispatch guard allowlist stays EMPTY; opencode
is only ever reached via `agent_call.py`; real `opencode`/`ollama` calls are
confined to `live_llm`-marked tests.

**Organization**: grouped by user story (spec.md priorities). MVP = Phase 2 +
Phase 3 (preflight) + Phase 4 (US1).

> **Revision 2026-06-11 (post-`/speckit.analyze` remediation)**: added the
> Phase 3 preflight gate (FR-015, was uncovered); reordered the US1 settings
> tasks to test-first; made the `default_agent: opencode` validity (FR-001) and
> the sidecar `model` field (FR-008) explicit; pinned the fake-agent parity task.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: parallelizable (different file, no incomplete dependency)
- Tasks touching `scripts/agent_call.py` are NOT mutually `[P]` (same file).

## Path conventions

Single-project framework. Implementation in `scripts/agent_call.py`,
`settings.opencode.yaml` (+ `src/research_framework/_data/` copy),
`src/research_framework/benchmark/`, `src/research_framework/_assets.py`,
`build.sh`, `dist-templates/install.sh`. Tests under `tests/`.

> **Foreman note (ADR-0010)**: before `/speckit.implement`, run the blind
> test-design subagent to enrich the test tasks below with strict
> `### Testing Requirements` blocks (exact filenames + function names + TDD flag).
> The task IDs/paths here are the inputs to that step.

---

## Phase 1: Setup (shared scaffolding)

**Purpose**: identifiers + helpers the adapter and cost classifier share. Additive to an existing module — no project init.

- T001 Add opencode identifiers to `scripts/agent_call.py`: `_OPENCODE = "opencode"` constant, an `OPENCODE_BIN` env lookup, and a `_has_dir_flag(args)` guard (mirrors `_has_workspace_flag`). No dispatch behavior yet — just the symbols later tasks consume.

**Checkpoint**: module still imports; existing tests unaffected.

---

## Phase 2: Foundational (BLOCKING — every story depends on this)

**Purpose**: make `opencode` a dispatchable CLI runtime through the single seam. Until this lands, no user story can run.

- T002 [P] Write failing unit tests for `_opencode_cmd` in `tests/scripts/test_agent_call.py` (class `TestOpencodeCommand`): asserts the command shape `opencode run --format json --model <m> --dir <vault> [--variant ..][--agent ..] <args>`; `--dir` auto-injected from `vault_dir`; operator `--dir` in `args` wins (no double flag); `OPENCODE_BIN` override; prompt fed on stdin. Per `contracts/opencode-adapter.contract.md`.

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-11. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_agent_call.py::test_opencode_cmd_basic_shape`
    - Behavior: Call `_opencode_cmd` with a minimal executor dict (model set, no variant/agent) and a `vault_dir`; assert the resulting list is exactly `["opencode", "run", "--format", "json", "--model", "<model>", "--dir", "<vault_dir>"]`. No real opencode binary; assert on the list return value only.
    - Tier: 2
    - Notes: adapter contract §Command builder MUST produce shape; FR-003 headless mode
  - **Test 2**: `tests/scripts/test_agent_call.py::test_opencode_cmd_dir_auto_injected`
    - Behavior: Call `_opencode_cmd` with a `vault_dir` and no `--dir` in `args`; assert `"--dir"` appears exactly once in the output and its value equals `str(vault_dir)`.
    - Tier: 2
    - Notes: adapter contract `_has_dir_flag` guard; FR-010 containment
  - **Test 3**: `tests/scripts/test_agent_call.py::test_opencode_cmd_operator_dir_wins`
    - Behavior: Call `_opencode_cmd` with a `vault_dir` AND `--dir /operator/path` already in `args`; assert `--dir` appears exactly once (the operator value, not `vault_dir`). The auto-inject MUST NOT fire when `_has_dir_flag(args)` is true.
    - Tier: 2
    - Notes: adapter contract "operator `--dir` override wins"; FR-010 no double flag
  - **Test 4**: `tests/scripts/test_agent_call.py::test_opencode_cmd_bin_env_override`
    - Behavior: Set `OPENCODE_BIN=/custom/opencode` in the environment; assert the first token of the returned command is `/custom/opencode`. Do not call a real binary — inspect the list.
    - Tier: 2
    - Notes: adapter contract `OPENCODE_BIN` env lookup

  **TDD discipline**: required
- T003 [P] Write failing regression test in `tests/scripts/test_agent_call.py` (class `TestExecutorNonRegression`) asserting `_claude_cmd` / `_codex_cmd` / `_cursor_cmd` outputs are byte-identical to a captured baseline (FR-014 guard).

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-11. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_agent_call.py::test_existing_executor_commands_unchanged`
    - Behavior: For each of `claude`, `codex`, and `cursor-agent`, call their command-builder with a fixed executor dict and `vault_dir`; assert the returned list exactly matches a frozen baseline captured before any 064 changes. The test file itself IS the snapshot — embed baseline lists as module-level constants. This test MUST exist before any 064 implementation so it can catch silent regressions.
    - Tier: 2
    - Notes: FR-014 byte-identical requirement; adapter contract MUST NOT section

  **TDD discipline**: required
- T004 Implement `_opencode_cmd(executor, vault_dir=None)` in `scripts/agent_call.py` per the contract (consumes T001 helpers). Makes T002 pass.

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-11. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_agent_call.py::test_opencode_cmd_variant_and_agent_flags`
    - Behavior: Call `_opencode_cmd` with `executor = {"model": "ollama/m", "variant": "high", "agent": "researcher"}`; assert `["--variant", "high"]` and `["--agent", "researcher"]` both appear in the output. Call again with neither key set; assert neither `--variant` nor `--agent` appears.
    - Tier: 2
    - Notes: adapter contract optional `--variant`/`--agent` flags; FR-003 headless

  **TDD discipline**: required
- T005 Add the `opencode` branch to `_build_command` in `scripts/agent_call.py` (route to `_opencode_cmd` with `vault_dir`, like the `codex`/`cursor-agent` branches); register `opencode` in `_RUNTIME_ADAPTERS` + `_LLM_AGENT_NAMES`; **and add `opencode` to the allowed `default_agent` set / agent-name allowlist** (wherever `default_agent: ollama|cursor-agent` is validated — FR-001, G2). Do NOT add it to `_HTTP_RUNTIMES` / `_FLAT_RATE_AGENTS` / `_STREAMING_AGENTS` (cost is per-call — Phase 6). Makes T002/T003 pass; unknown-runtime error now lists `opencode`.

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-11. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_agent_call.py::test_build_command_opencode_routes_with_vault_dir`
    - Behavior: Call `_build_command("opencode", executor_dict, vault_dir=some_path)`; assert the returned command contains `"--dir"` with `str(some_path)` and begins with the opencode binary token. This ensures the `_build_command` branch passes `vault_dir` through to `_opencode_cmd` (mirrors the codex/cursor-agent branches).
    - Tier: 2
    - Notes: adapter contract `_build_command` MUST gain an `opencode` branch; FR-002 single dispatch surface
  - **Test 2**: `tests/scripts/test_agent_call.py::test_unknown_runtime_error_lists_opencode`
    - Behavior: Call `_build_command("nonexistent_runtime", …)`; catch the `ValueError`; assert the error message contains the string `"opencode"` (it is now a supported runtime and must appear in the error listing). Assert `opencode` is NOT in `_HTTP_RUNTIMES`, `_FLAT_RATE_AGENTS`, or `_STREAMING_AGENTS`.
    - Tier: 2
    - Notes: adapter contract MUST raise existing unknown-runtime ValueError listing `opencode`; FR-001 valid executor; no static cost class

  **TDD discipline**: required

**Checkpoint**: `opencode` is dispatchable; `_build_command("opencode", …)` yields a `--dir`-scoped command; the other three executors are provably unchanged.

---

## Phase 3: Preflight fail-closed gate (FR-015) — cross-cutting guardrail

**Purpose**: a cycle must fail closed with an actionable message BEFORE dispatch when opencode can't run (binary missing / provider unreachable / creds absent). Depends only on Phase 2. Not on the US1 happy path, but hardens every story (US1 local, US2 hosted creds). *(No story label — cross-cutting, like Foundational/Polish.)*

- T006 [P] Write failing tests in `tests/scripts/test_agent_call.py` (or the executor-preflight test module, mirroring the codex/cursor preflight tests) class `TestOpencodePreflight`: (a) `opencode` binary not on PATH → fail closed, message names the binary + install hint; (b) a derivable local provider endpoint unreachable (ollama box down) → fail closed, per-cause message; (c) a hosted provider with absent credentials → fail closed, per-cause message; (d) reachable/authed → passes. Per spec FR-015 + Edge Cases §1–2.

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-11. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_agent_call.py::test_opencode_preflight_binary_missing_fails_closed`
    - Behavior: Mock PATH / `OPENCODE_BIN` so the opencode binary is absent; invoke the preflight check; assert it raises or returns a failure result whose message contains both the binary name (`"opencode"`) and an install hint. Must not start a subprocess that exits non-zero — the check is a pre-dispatch guard.
    - Tier: 2
    - Notes: FR-015 fail-closed; Edge Cases §1 "opencode not installed"
  - **Test 2**: `tests/scripts/test_agent_call.py::test_opencode_preflight_local_provider_unreachable`
    - Behavior: Binary present (mock shutil.which or OPENCODE_BIN to a dummy path); derivable local provider (ollama) endpoint unreachable (mock the connectivity probe to fail); assert preflight fails with a per-cause message that names the provider/endpoint. Must not proceed to dispatch.
    - Tier: 2
    - Notes: FR-015; Edge Cases §2 "Configured model/provider unavailable"
  - **Test 3**: `tests/scripts/test_agent_call.py::test_opencode_preflight_passes_when_reachable`
    - Behavior: Binary present, provider reachable (mock probes to succeed); assert preflight returns success/passes without raising. Ensures the fail-closed path does not over-fire.
    - Tier: 2
    - Notes: FR-015 happy path; Edge Cases §2

  **TDD discipline**: required
- T007 Implement the opencode preflight check (binary-on-PATH via `OPENCODE_BIN`/PATH; derivable provider-reachability + credential presence where determinable ahead of dispatch) in the executor-preflight path used before a cycle starts, mirroring the existing codex/cursor preflight. Make T006 pass.

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-11. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_agent_call.py::test_opencode_preflight_hosted_creds_absent_fails`
    - Behavior: Binary present; hosted provider configured (non-local model, e.g. `anthropic/claude-*`); relevant credential env var absent; assert preflight fails with a per-cause message that names the credential or provider. Tests the third preflight scenario (T006 sub-case c) not covered in T006's own block.
    - Tier: 2
    - Notes: FR-015; Edge Cases §2 "hosted API key missing/invalid"

  **TDD discipline**: required

**Checkpoint**: misconfigured opencode aborts before burning a stage, with a per-cause message.

---

## Phase 4: User Story 1 — Full vault cycle on opencode + local Ollama ($0) (P1) 🎯 MVP

**Goal**: a real research cycle runs end-to-end on opencode driving a local Ollama model, writing every stage artifact, committing, at $0.
**Independent test**: fake-agent cycle on a minimal vault with `default_agent: opencode` writes all stage files + commits; sidecar shows `executor: opencode`, the resolved `model`, `cost_usd: 0.0`, real tokens, `cost_source: runtime`; (opt-in) a live local-ollama cycle completes.

### Cost classification — local arm (so the $0 sidecar is honest)

- T008 [P] [US1] Write failing unit tests in `tests/scripts/test_agent_call.py` (class `TestOpencodeUsageParse`) for an NDJSON parser that accumulates `step_finish` events → `(tokens_in, tokens_out, cost_usd, n_steps)`; robust to a missing terminal event (use the verified shape in `research.md` R1). Include the captured local-run line as a fixture.

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-11. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_agent_call.py::test_parse_opencode_ndjson_accumulates_step_finish`
    - Behavior: Feed the NDJSON fixture from research.md R1 (the live-verified `step_finish` line with `tokens.input=8523, tokens.output=43, cost=0`) through the parser; assert `tokens_in == 8523`, `tokens_out == 43`, `cost_usd == 0.0`, `n_steps == 1`. The fixture MUST be an inline string constant, not a file read — keeps the test hermetic.
    - Tier: 2
    - Notes: cost contract §Usage extraction VERIFIED shape; R1 exact token values
  - **Test 2**: `tests/scripts/test_agent_call.py::test_parse_opencode_ndjson_multi_step_accumulates`
    - Behavior: Feed two `step_finish` lines (distinct `tokens` and `cost` values each); assert totals are the sum across both events, `n_steps == 2`. Non-`step_finish` lines (e.g. `step_start`, `tool_use`) MUST be ignored and not raise.
    - Tier: 2
    - Notes: cost contract "accumulate over every `step_finish` event"; R1 multi-step agentic run
  - **Test 3**: `tests/scripts/test_agent_call.py::test_parse_opencode_ndjson_no_step_finish_returns_none`
    - Behavior: Feed only non-`step_finish` lines (simulate a run that ended before a `step_finish`); assert the parser returns `None` (or an empty/zero sentinel that the caller can distinguish from a real zero-cost result). Must NOT raise.
    - Tier: 2
    - Notes: cost contract "robust to a missing terminal event"; R1 "verification capture ended on a `step_start`"

  **TDD discipline**: required
- T009 [P] [US1] Write failing unit tests (class `TestOpencodeCostClassLocal`) for `_opencode_cost_class`: local provider (`ollama/…`) → `(0.0, t_in>0, t_out>0, "runtime")`; tokens NOT added to the metered-token cap. Per `contracts/opencode-cost.contract.md` rule 1.

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-11. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_agent_call.py::test_opencode_cost_class_local_ollama_returns_zero_dollar_runtime`
    - Behavior: Call `_opencode_cost_class("ollama/qwen2.5:7b", {"tokens_in": 8523, "tokens_out": 43, "cost_usd": 0.0, "n_steps": 1})`; assert return is `(0.0, 8523, 43, "runtime")`. The `cost_usd` must be exactly `0.0` (float) and `cost_source` must be the string `"runtime"`, not `"estimated"` or `"none"`.
    - Tier: 2
    - Notes: cost contract rule 1 local provider; FR-006 true $0 with real tokens; SC-003
  - **Test 2**: `tests/scripts/test_agent_call.py::test_opencode_cost_class_local_provider_prefix_recognized`
    - Behavior: Call `_opencode_cost_class` with `model="local/my-model"` and real usage; assert `cost_source == "runtime"` and `cost_usd == 0.0`. Verifies the `local` prefix is recognized alongside `ollama`. Also call with a non-local prefix (e.g. `"anthropic/claude-sonnet-4-6"`) and real usage with `cost_usd > 0`; assert `cost_source != "none"` (the metered path applies).
    - Tier: 2
    - Notes: cost contract rule 1 `local_providers` set; settings.opencode.contract `local_providers: [ollama, local]`

  **TDD discipline**: required
- T010 [US1] Implement the `step_finish` NDJSON usage accumulator + `_opencode_cost_class` (local arm) and wire it into `_resolve_cost` for the `opencode` runtime in `scripts/agent_call.py`. Makes T008/T009 pass. (Metered arms land in US3 — keep the function structured for them.)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-11. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_agent_call.py::test_resolve_cost_opencode_local_sidecar_fields`
    - Behavior: Call `_resolve_cost` (or the sidecar-production function) with `executor="opencode"`, a local model, and an NDJSON stdout fixture containing one `step_finish` event; assert the sidecar dict has `executor == "opencode"`, `model` populated, `cost_usd == 0.0`, `cost_source == "runtime"`, and non-zero `tokens_in`/`tokens_out`. Uses inline string fixtures only — no real opencode binary. This tests the wiring from parser → cost classifier → sidecar, not just the classifier in isolation.
    - Tier: 2
    - Notes: FR-008 resolved model recorded; FR-011 sidecar fields; cost contract invariants; SC-003

  **TDD discipline**: required

### Settings profile (test-first — O1 fix)

- T011 [P] [US1] Write failing tests for the bundled profile: `tests/test_assets.py` asserts `settings.opencode.yaml` is wheel-bundled + in the bundle (mirror the cursor assertion); `tests/test_cli.py` asserts `rv generate --settings settings.opencode.yaml` resolves; a `pipeline/settings.py` load test asserts `default_executor.runtime == "opencode"` **and that `default_agent: opencode` validates** (FR-001, G2).

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-11. Do not edit during implementation._

  - **Test 1**: `tests/test_assets.py::test_settings_opencode_yaml_bundled_in_wheel_data`
    - Behavior: Use `importlib.resources` (or the project's `_assets` helper) to assert that `settings.opencode.yaml` is present in the wheel's `_data/` directory — mirroring the existing cursor bundling assertion. This test MUST fail before T013 creates the file.
    - Tier: 2
    - Notes: settings.opencode.contract MUST be bundled; FR-004
  - **Test 2**: `tests/test_cli.py::test_generate_settings_opencode_yaml_resolves`
    - Behavior: Run the `rv generate --settings settings.opencode.yaml` CLI command against a temp output dir; assert exit code 0 and that the output `settings.yaml` file contains `runtime: opencode`. Uses a subprocess or the CLI test harness — no real vault cycle.
    - Tier: 2
    - Notes: settings.opencode.contract; FR-004 generate command
  - **Test 3**: `tests/pipeline/test_opencode_executor_cycle.py::test_settings_opencode_loads_runtime_and_default_agent`
    - Behavior: Load the bundled `settings.opencode.yaml` via `pipeline/settings.py`; assert `settings.default_executor.runtime == "opencode"` and that `default_agent: opencode` passes validation without raising. Use `vault_factory.build_minimal_vault` to supply a vault root — no real opencode dispatch.
    - Tier: 3
    - Notes: settings.opencode.contract; FR-001 `default_agent: opencode` valid; G2

  **TDD discipline**: required
- T012 [US1] Create `settings.opencode.yaml` at repo root, cloned from `settings.cursor.yaml` and retargeted per `contracts/settings.opencode.contract.md`: `runtime: opencode`, a local-Ollama basic-tier default, `--variant` effort map documented, `local_providers: [ollama, local]`, the unattended approval posture in `default_executor.args`, and a header comment documenting `--model provider/model` / `--dir` / per-call cost behavior.
- T013 [US1] Register `settings.opencode.yaml` as a bundled asset: add it to `src/research_framework/_assets.py`, copy root→`src/research_framework/_data/settings.opencode.yaml` in the wheel force-include, and add it to the bundle copy lists in `build.sh` + `dist-templates/install.sh` (parity with `settings.cursor.yaml`). Makes T011 pass.

### Cycle integration

- T014 [US1] Write a failing fake-agent cycle test `tests/pipeline/test_opencode_executor_cycle.py` using `vault_factory.build_minimal_vault` + `tests/_helpers/fake_agent.py`: a cycle with the opencode profile writes every expected stage output file and produces a clean commit (FR-009); assert the sidecar has `executor: "opencode"`, **the resolved `model` field populated** (FR-008, G3), `cost_usd: 0.0`, `cost_source: "runtime"`, and non-zero real tokens.

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-11. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_opencode_executor_cycle.py::test_opencode_cycle_writes_stage_files_and_commits`
    - Behavior: Build a minimal vault (`vault_factory.build_minimal_vault`) configured with `default_agent: opencode` and a local model; run one cycle using `tests/_helpers/fake_agent.py` as the executor shim (MUST NOT call real opencode or any LLM); assert every expected stage output file exists after the cycle and that the vault git repo has a new commit. The LLM dispatch guard allowlist MUST stay EMPTY.
    - Tier: 3
    - Notes: FR-009 stage-output-file contract; SC-001; CLAUDE.md fake_agent usage mandate
  - **Test 2**: `tests/pipeline/test_opencode_executor_cycle.py::test_opencode_cycle_sidecar_honest_local_cost`
    - Behavior: Same fake-agent cycle; read the sidecar produced under `_pipeline/cycles/cycle-NNN/agent-calls/`; assert `executor == "opencode"`, `model` is non-empty (the resolved `provider/model`), `cost_usd == 0.0`, `cost_source == "runtime"`, and both `tokens_in` and `tokens_out` are positive integers. A sidecar with `cost_source == "none"` or a missing `model` field MUST fail the assertion.
    - Tier: 3
    - Notes: FR-008 resolved model; FR-011 sidecar fields; FR-006 real tokens; SC-003

  **TDD discipline**: required
- T015 [US1] Add an `opencode` handler to `tests/_helpers/fake_agent.py` that emits an NDJSON `step_finish`-shaped response (tokens + `cost: 0`) and performs the stage file-write, so T014 runs hermetically (no real opencode). If the existing generic handler already satisfies this, replace this task with a one-line assertion that documents why none is needed. Make T014 pass.

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-11. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_opencode_executor_cycle.py::test_fake_agent_opencode_handler_emits_valid_ndjson`
    - Behavior: Invoke the fake-agent opencode handler directly (not through a full cycle); assert its stdout contains at least one line that is valid JSON with `type == "step_finish"` and `part.tokens.input > 0`. This is a unit-level check on the fake handler itself, so T014's cycle assertion is not the only verification.
    - Tier: 3
    - Notes: CLAUDE.md fake_agent pattern; cost contract verified NDJSON shape; ensures the shim feeds the parser correctly

  **TDD discipline**: required
- T016 [P] [US1] Add a `@pytest.mark.live_llm` test (e.g. `tests/live/test_opencode_ollama_cycle.py`) that runs one real cycle against a local Ollama model via opencode and asserts stage files + `$0`/`runtime` sidecar (SC-001). Skipped by default; never in CI/fast loop.

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-11. Do not edit during implementation._

  - **Test 1**: `tests/live/test_opencode_ollama_cycle.py::test_live_opencode_ollama_cycle_completes`
    - Behavior: MUST be decorated `@pytest.mark.live_llm`. Runs one real cycle via opencode against the operator's local Ollama box; asserts every expected stage file exists, the cycle commits, and the sidecar has `cost_usd == 0.0`, `cost_source == "runtime"`, and positive `tokens_in`/`tokens_out`. This test is NEVER collected by `pytest -m "not e2e"` or in CI; it is the operator's manual acceptance gate per SC-001. The test MUST use a temporary vault created by `vault_factory.build_minimal_vault` so it leaves no permanent side-effects.
    - Tier: 5
    - Notes: SC-001; spec clarification "live_llm opt-in not a CI gate"; CLAUDE.md live_llm pattern; FR-009 stage output file contract

  **TDD discipline**: required

**Checkpoint**: MVP — a vault runs on opencode+Ollama at $0 with honest telemetry, failing closed when misconfigured (Phase 3).

---

## Phase 5: User Story 2 — Swap the model provider by config only (P1)

**Goal**: change opencode's model (local→hosted) with zero framework code change.
**Independent test**: same fixture cycle with two model configs (local + hosted) — only config differs; both dispatch with `executor: opencode`, differing recorded model.

- T017 [P] [US2] Write a failing structural test in `tests/pipeline/test_opencode_executor_cycle.py` (or a sibling) that runs the fake-agent dispatch twice with two `default_executor.model` values (one `ollama/…`, one hosted `provider/…`), asserting: same code path, `executor: opencode` both, recorded `model` differs, no source change between runs (SC-002 gate).

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-11. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_opencode_executor_cycle.py::test_opencode_provider_swap_config_only`
    - Behavior: Build two minimal vault configs differing only in `default_executor.model` (one `ollama/qwen2.5:7b`, one `anthropic/claude-sonnet-4-6`); run a fake-agent dispatch for each; assert both sidecars have `executor == "opencode"`, that `sidecar_a["model"] != sidecar_b["model"]`, and that no `scripts/agent_call.py` source modification was needed (checked by asserting the dispatch function name is the same object for both calls). Uses `tests/_helpers/fake_agent.py` — no real opencode or LLM.
    - Tier: 3
    - Notes: SC-002 provider-swap zero-source-change; FR-005 provider as config; US2

  **TDD discipline**: required
- T018 [US2] Make T017 pass (expected: no new code — the adapter is already model-agnostic; if a model-string assumption leaks, fix it in `scripts/agent_call.py`). Refresh the provider-swap steps in `quickstart.md` if they drifted from the live findings.

**Checkpoint**: provider-agnosticism proven structurally; live hosted run remains `live_llm` opt-in (not gated).

---

## Phase 6: User Story 3 — Cost & telemetry guardrails survive (metered + budget) (P1)

**Goal**: metered opencode runs are honest and capped; no silent $0; budget tally includes opencode.
**Independent test**: per-arm cost-class tests + a budget-guard fixture where cumulative opencode dollar crosses the cap → `BUDGET_PAUSED`.

- T019 [P] [US3] Write failing tests (class `TestOpencodeCostClassMetered`, `tests/scripts/test_agent_call.py`) for the metered arms per `contracts/opencode-cost.contract.md` rules 2–4: real `cost`>0 → `"runtime"`; tokens but no/zero dollar → `"runtime_tokens"` (estimator); no usage → estimator/`"none"`, NEVER a silent `(0.0,…,"runtime")`.

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-11. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_agent_call.py::test_opencode_cost_class_metered_real_dollar_is_runtime`
    - Behavior: Call `_opencode_cost_class("anthropic/claude-sonnet-4-6", {"tokens_in": 100, "tokens_out": 50, "cost_usd": 0.003, "n_steps": 1})`; assert `cost_source == "runtime"` and `cost_usd == pytest.approx(0.003)` and `tokens_in == 100`, `tokens_out == 50`. This is rule 2: metered + real dollar from opencode's pricing catalog.
    - Tier: 2
    - Notes: cost contract rule 2; R3 "common metered case is rule 2"; FR-007
  - **Test 2**: `tests/scripts/test_agent_call.py::test_opencode_cost_class_metered_tokens_only_is_runtime_tokens`
    - Behavior: Call `_opencode_cost_class("openai/gpt-4o", {"tokens_in": 200, "tokens_out": 80, "cost_usd": 0.0, "n_steps": 1})`; assert `cost_source == "runtime_tokens"` and `cost_usd > 0` (the estimator produced a dollar). The result MUST NOT be `(0.0, …, "runtime")` — that would be a silent silent-$0 violation.
    - Tier: 2
    - Notes: cost contract rule 3 estimator fallback; FR-007 never silent $0
  - **Test 3**: `tests/scripts/test_agent_call.py::test_opencode_cost_class_no_usage_never_silent_zero_runtime`
    - Behavior: Call `_opencode_cost_class("openai/gpt-4o", None)` (no usage — the missing-terminal-event case for a metered provider); assert `cost_source` is either `"estimated"` or `"none"` and is NEVER `"runtime"`. The triple `(0.0, 0, 0, "runtime")` MUST raise `AssertionError` in this test. This is the anti-footgun invariant from cost contract rule 4.
    - Tier: 2
    - Notes: cost contract rule 4 "NEVER a silent `(0.0,…,'runtime')`"; FR-007; the rc3 $0 footgun lesson

  **TDD discipline**: required
- T020 [US3] Implement the metered arms of `_opencode_cost_class` in `scripts/agent_call.py` (extends T010): metered-token-cap accounting + estimator fallback. Make T019 pass.
- T021 [P] [US3] Write failing budget tests `tests/pipeline/test_budget_guard_opencode.py` + `tests/pipeline/test_cost_estimator_opencode.py` (mirror the `_cursor` equivalents): opencode sidecars sum into the dollar tally (regression of the rc3 `schema_version` line-match footgun — `1.x` accepted); `BUDGET_PAUSED` fires on the dollar cap (metered) AND the wall-clock cap (zero-cost local, FR-012).

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-11. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_budget_guard_opencode.py::test_opencode_sidecars_sum_into_budget_tally`
    - Behavior: Write two synthetic sidecar JSON files with `executor: "opencode"`, valid `schema_version: "1.2"`, and `cost_usd` values; feed them through the budget guard's tally function; assert the cumulative total equals the sum of both sidecars' `cost_usd`. Also write a sidecar with `schema_version: "1.1"` (a `1.x` version); assert it is also accepted (regression of the rc3 schema-line-match footgun where only exact version strings were matched). Uses file fixtures in a temp dir — no real cycle.
    - Tier: 3
    - Notes: FR-012 budget participation; rc3 `1.x` schema footgun regression (cost contract invariants); US3
  - **Test 2**: `tests/pipeline/test_budget_guard_opencode.py::test_budget_paused_fires_on_dollar_cap_metered`
    - Behavior: Configure the budget guard with a dollar cap of `$0.01`; feed it opencode sidecars (metered, `cost_source: "runtime"`) that cumulatively exceed the cap; assert a `BUDGET_PAUSED` marker is written or the cycle is aborted. Uses `vault_factory.build_minimal_vault` + `tests/_helpers/fake_agent.py` to run inside a real vault structure.
    - Tier: 3
    - Notes: FR-012 dollar cap fires; SC-004; spec 033 BUDGET_PAUSED
  - **Test 3**: `tests/pipeline/test_budget_guard_opencode.py::test_budget_paused_fires_on_wall_clock_cap_local`
    - Behavior: Configure the budget guard with a short wall-clock cap; run a fake-agent opencode cycle with `cost_usd == 0.0` (local model, zero dollar); simulate wall-clock expiry; assert `BUDGET_PAUSED` fires even though the dollar cost never moved. Proves the wall-clock cap is not accidentally gated on `cost_usd > 0`.
    - Tier: 3
    - Notes: FR-012 wall-clock cap fires on zero-cost local run; US1 Acceptance Scenario 3; SC-003

  **TDD discipline**: required
- T022 [US3] Make T021 pass (wire opencode sidecars through the spec-033 budget guard; verify no schema bump needed).

**Checkpoint**: cost is honest and enforced across local and metered opencode runs.

---

## Phase 7: User Story 4 — Writes contained to the vault (P1)

**Goal**: opencode writes stay inside the vault; no full-disk mode.
**Independent test**: a cycle creates/modifies nothing outside the vault root; the invocation carries `--dir` and never a full-access flag.

- T023 [P] [US4] Write a failing test in `tests/pipeline/test_opencode_executor_cycle.py` asserting (a) the built opencode command for a cycle contains `--dir <vault>` (the containment mechanism — always injected regardless of approval posture), and (b) after a fake-agent cycle, no file outside the vault root was created/modified (SC-005).

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-11. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_opencode_executor_cycle.py::test_opencode_command_contains_dir_and_no_full_disk_flag`
    - Behavior: Build the opencode command for a cycle (`_build_command("opencode", executor, vault_dir=tmp_vault)`) using the shipped unattended profile's `args`; assert `"--dir"` is present exactly once and its value equals `str(tmp_vault)` — `--dir` is the containment mechanism and MUST always be injected regardless of approval posture. Do NOT assert the absence of `--dangerously-skip-permissions`: it is a legitimate *approval* lever in the settings `args` (verified working in the 2026-06-11 live run) and is orthogonal to write-containment, which `--dir` enforces. Do not run the command — assert on the list.
    - Tier: 2
    - Notes: FR-010 containment = `--dir` (positive assertion); R2 live-verified `--dir` write-scoping; approval posture (R5) is orthogonal; SC-005
  - **Test 2**: `tests/pipeline/test_opencode_executor_cycle.py::test_opencode_cycle_no_writes_outside_vault`
    - Behavior: Record all files in a temp directory tree before and after a fake-agent opencode cycle (`vault_factory.build_minimal_vault` + `tests/_helpers/fake_agent.py`); assert no new or modified files exist outside the vault root after the cycle. Use `os.walk` or `pathlib` to collect the before/after snapshot. This is the observable containment assertion — a regression of the rc2 containment fix.
    - Tier: 3
    - Notes: SC-005 zero out-of-vault writes; FR-010; US4 acceptance scenario 1

  **TDD discipline**: required
- T024 [US4] Make T023 pass. If a residual out-of-`--dir` absolute-write path is reachable (the `research.md` R2 residual), ship a generated `opencode.json` `permission` block scoping edits to the vault alongside the settings profile; otherwise document that `--dir` is sufficient.

**Checkpoint**: containment matches the codex/cursor invariant (no danger-full-access regression).

---

## Phase 8: User Story 5 — Existing executors + autonomy unchanged (P2)

**Goal**: claude/codex/cursor untouched; opencode has a defined autonomy posture.
**Independent test**: full fast-loop unchanged + byte-identical sidecars for the other three; each autonomy level resolves to a defined opencode posture.

- T025 [P] [US5] Extend the regression coverage (`tests/scripts/test_agent_call.py`) to assert claude/codex/cursor **sidecars** (not just commands) are byte-identical before/after opencode, and confirm `tests/_helpers/llm_dispatch_allowlist.yaml` is still EMPTY (Principle IV).

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-11. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_agent_call.py::test_existing_executor_sidecars_unchanged_after_opencode`
    - Behavior: For each of `claude`, `codex`, and `cursor-agent`: produce a sidecar dict via the cost-resolution path with a fixed NDJSON/stdout fixture; assert the dict is byte-identical (field-by-field, not just `==`) to a frozen baseline captured before any 064 changes. The frozen baselines MUST be module-level constants so drift is immediately obvious on diff.
    - Tier: 2
    - Notes: FR-014 sidecars byte-identical; US5; SC-006
  - **Test 2**: `tests/scripts/test_agent_call.py::test_llm_dispatch_allowlist_is_empty`
    - Behavior: Open `tests/_helpers/llm_dispatch_allowlist.yaml`, parse it, and assert it contains zero entries (or an empty list). This is a declarative invariant: adding opencode to the dispatch must not require any entry in the allowlist (opencode is reached via `agent_call.py`, never a direct subprocess in `src/`). The test MUST be in the fast loop.
    - Tier: 2
    - Notes: Constitution Principle IV; CLAUDE.md "allowlist MUST stay EMPTY"; FR-002 single dispatch surface

  **TDD discipline**: required
- T026 [US5] Document + test opencode's autonomy posture (FR-013): the `settings.opencode.yaml` unattended `args` (opencode permission config / `--dangerously-skip-permissions` as the blunt fallback) is the `full-auto`/`semi-auto` posture; add a test asserting the posture is present. Note in the spec/`research.md` R5 that the full `autonomy_level`→opencode mapping lands with spec 042 (still draft) — 064 defines the executor-level posture only.

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-11. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_opencode_executor_cycle.py::test_settings_opencode_unattended_posture_present`
    - Behavior: Load `settings.opencode.yaml` via `pipeline/settings.py`; assert `default_executor.args` is non-empty and contains at least one token that represents the unattended approval posture (either an opencode permission-config flag or `"--dangerously-skip-permissions"`). This verifies FR-013 at the settings level without running a real cycle.
    - Tier: 2
    - Notes: FR-013 defined unattended autonomy posture; R5; settings.opencode.contract "unattended approval posture in args"

  **TDD discipline**: required

**Checkpoint**: zero regression to shipped executors; opencode runs unattended out of the box.

---

## Phase 9: User Story 6 — Benchmark cell + sweep + optional label (P2)

**Goal**: sweep any model through opencode in the spec-056 benchmark; optional readable labels.
**Independent test**: `opencode ∈ valid_runtimes()`; an opencode block × N models → N cells; optional `label` replaces the runtime token in the cell key/report.

- T027 [P] [US6] Write a failing guard test in `tests/benchmark/unit/test_matrix.py` asserting `"opencode" in valid_runtimes()` (FR-018) — passes for free once Phase 2 registered opencode; this pins it against future regression.

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-11. Do not edit during implementation._

  - **Test 1**: `tests/benchmark/unit/test_matrix.py::test_opencode_in_valid_runtimes`
    - Behavior: Call `valid_runtimes()` from `benchmark/matrix.py`; assert `"opencode" in valid_runtimes()`. This test MUST fail before Phase 2 registers opencode (it is the forward-regression pin). Must not mock the registry — call the real function so it reads from the live `_RUNTIME_ADAPTERS` union.
    - Tier: 2
    - Notes: FR-018 guard test MUST; benchmark-label contract §FR-018/019; SC-007

  **TDD discipline**: required
- T028 [P] [US6] Write failing tests for the optional `label` (FR-020): `_parse_executors` accepts `label: str?`; an `{opencode, label, models:[m1,m2]}` block → 2 cells whose key uses the label; absent `label` → key byte-identical to `task__executor__model` (SC-008). Per `contracts/benchmark-label.contract.md`.

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-11. Do not edit during implementation._

  - **Test 1**: `tests/benchmark/unit/test_matrix.py::test_executor_label_replaces_runtime_in_cell_key`
    - Behavior: Parse an executor block `{runtime: opencode, label: "opencode-local-qwen", models: ["ollama/qwen2.5:7b", "ollama/llama3"]}` with a single task; assert `cells()` returns 2 cells and both cell keys match the pattern `"<task>__opencode-local-qwen__<model>"` (label replaces the runtime token). Assert neither key contains the literal string `"opencode"` as the runtime portion.
    - Tier: 2
    - Notes: FR-020; benchmark-label contract §FR-020 label set → key uses label; SC-008
  - **Test 2**: `tests/benchmark/unit/test_matrix.py::test_executor_absent_label_key_byte_identical`
    - Behavior: Parse an identical executor block WITHOUT `label`; assert the cell keys are exactly `"<task>__opencode__<model>"` — byte-identical to the pre-064 `task__executor__model` format. Adding opencode must not change the default keying for any unlabeled executor (including the existing non-opencode ones).
    - Tier: 2
    - Notes: FR-020 absent label → byte-identical; benchmark-label contract MUST NOT make label required; SC-008
  - **Test 3**: `tests/benchmark/unit/test_matrix.py::test_two_opencode_blocks_distinct_labels_produce_distinct_cells`
    - Behavior: Parse two executor blocks both with `runtime: opencode` but different `label` values (`opencode-local` and `opencode-gpt5`) and overlapping models; assert all resulting cells have distinct keys and neither key is ambiguous (no two cells share the same key). Regression of the "same runtime, two configs" readability use-case.
    - Tier: 2
    - Notes: benchmark-label contract "two opencode blocks with distinct labels → two distinct cells"; FR-020 use case

  **TDD discipline**: required
- T029 [US6] Implement the optional `label` in `src/research_framework/benchmark/matrix.py` (`Executor.label`, carry to `Cell`, `Cell.key` uses label when set) and surface it in `src/research_framework/benchmark/reporter.py`. Make T027/T028 pass. No change to runner/scoring/gating.

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-11. Do not edit during implementation._

  - **Test 1**: `tests/benchmark/unit/test_matrix.py::test_executor_label_surfaces_in_reporter_row`
    - Behavior: Build a single cell with `Executor(runtime="opencode", models=("ollama/m",), label="opencode-local")`; pass it through the reporter; assert the reporter row contains the string `"opencode-local"` and NOT the bare `"opencode"` runtime string in the label position. This verifies the label flows from `matrix.py` into `reporter.py`.
    - Tier: 2
    - Notes: FR-020 reporter surfaces label; benchmark-label contract §reporter; data-model E4

  **TDD discipline**: required

**Checkpoint**: the benchmark can compare any model through opencode (uniform `cost_source: runtime` cost basis); same-runtime combos are readable.

---

## Phase 10: Polish & cross-cutting

- T030 [P] Add a `CHANGELOG.md [Unreleased]` entry (new `opencode` executor + `settings.opencode.yaml` + opencode preflight + benchmark opencode cells/label) and refresh `quickstart.md` against the verified flow.
- T031 [P] Confirm the 047 disposition (R8): leave `_dispatch_http`/`_HTTP_RUNTIMES = {ollama}` dormant; add a one-line code comment in `scripts/agent_call.py` pointing `ollama`-HTTP users to the opencode path (no behavior change).
- T032 Run `ruff check .` + `ruff format --check .` (both gates) and `bash build.sh --quality` (3 fixtures, regression diff); fix any fallout. Update `docs/ROADMAP.md` #29 → implemented once the impl PR is ready.

---

## Dependencies & order

- **Phase 1 → Phase 2**: setup constants before the adapter.
- **Phase 2 (foundational) blocks ALL later phases** — opencode must be dispatchable first.
- **Phase 3 (preflight)** depends only on Phase 2; independent of the user stories (hardening), but on the MVP ship list.
- **Phase 4 (US1) = functional MVP**; it introduces the cost classifier (local arm) + settings profile that **US2/US3/US4 build on**.
- **US3 metered arms (Phase 6) extend US1's `_opencode_cost_class`** — sequential on `scripts/agent_call.py`.
- **US2, US4** depend on US1's profile + cycle test scaffold.
- **US5, US6 are independent** of US2–US4 (US6 only needs Phase 2's registration; US5 only needs the regression baseline) — can proceed in parallel once Phase 2 lands.
- **Phase 10** last.

## Parallel opportunities

- Within Phase 2: T002 ∥ T003 (different test classes/baseline), then T004 → T005 (same file, sequential).
- Phase 3: T006 (test) → T007 (impl); T006 ∥ the Phase 4 `[P]` tests (different files) once Phase 2 lands.
- Phase 4: T008 ∥ T009 ∥ T011 ∥ T016 (different files); T010 (agent_call.py) sequential after T008/T009; T012/T013/T014/T015 follow their tests.
- US5 (T025/T026) ∥ US6 (T027–T029) once Phase 2 is done — different files.

## Implementation strategy

1. **MVP**: Phase 2 + Phase 3 (preflight) + Phase 4 (US1) → a vault runs on opencode+Ollama at $0 with honest telemetry and fails closed when misconfigured. Ship-worthy on its own.
2. **Harden**: US3 (metered cost + budget) + US4 (containment) → safe for unattended + metered use.
3. **Prove & leverage**: US2 (provider-swap gate) + US6 (benchmark) → the "any model, measured cost" story.
4. **Guardrail**: US5 non-regression throughout; Phase 10 polish + the `build.sh --quality` gate before PR.

**Total: 32 tasks** (T001–T032) across 10 phases. Tests-first per Constitution III; foreman test-design enrichment is the recommended pre-`/speckit.implement` step.
