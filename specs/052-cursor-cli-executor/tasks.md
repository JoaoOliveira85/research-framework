# Tasks: Cursor CLI Executor (spec 052)

> **Ledger** — this spec shipped; the boxes below are a historical record, not a live gate (CONTRIBUTING.md § 2). The Status header in `spec.md` is the source of truth for what shipped.

**Branch:** `052-cursor-cli-executor` · **Target:** 1.0.0rc4 · Ready for `/speckit.implement`.

`Testing Requirements` blocks below were authored 2026-06-08 from spec.md
(FR-001…FR-009) + plan.md. Run the Arm A verifier
(`scripts/foreman/verify_test_coverage.py`) after implementation.

[P] = parallelisable (different files, no incomplete-task dependency).

---

- T001 Add `_cursor_cmd(executor)` + `_cursor_cmd_with_cost(executor)` to `scripts/agent_call.py` and register `"cursor-agent"` in `_RUNTIME_ADAPTERS`; resolve the binary via `CURSOR_BIN` (default `cursor-agent`). argv: `-p --output-format json` (base) / `--output-format stream-json` (with-cost) `--model <m> --trust` then `executor["args"]`. Prompt stays on stdin.

  ### Testing Requirements

  _Authored by test-design pass on 2026-06-08. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_agent_call_cursor.py::test_cursor_cmd_argv_shape`
    - Behavior: `_cursor_cmd` yields `[bin, -p, --output-format, json, --model, <m>, --trust, *args]`; `_build_command` routes `runtime: cursor-agent` to it.
    - Tier: 2
  - **Test 2**: `tests/scripts/test_agent_call_cursor.py::test_cursor_bin_env_override`
    - Behavior: `CURSOR_BIN=/x/y` makes the argv[0] `/x/y`; default is `cursor-agent`.
    - Tier: 2
  - **Test 3**: `tests/scripts/test_agent_call_cursor.py::test_cursor_cmd_with_cost_uses_stream_json`
    - Behavior: `_cursor_cmd_with_cost` sets `--output-format stream-json`.
    - Tier: 2

  **TDD discipline**: required — tests above MUST be added in the same commit as or earlier than the implementation commit for `scripts/agent_call.py`.

- T002 Widen the executor enum everywhere it hardcodes `{"claude","codex"}`: `DefaultAgent` Literal + `_VALID_AGENTS` + `_parse_default_agent` message (`pipeline/settings.py`), `_LLM_AGENT_NAMES` (`agent_call.py`), `_LLM_BINARIES` (`tests/_helpers/test_llm_dispatch_guard.py`).

  ### Testing Requirements

  - **Test 1**: `tests/pipeline/test_settings_cursor.py::test_default_agent_accepts_cursor_agent`
    - Behavior: `settings.yaml` with `default_agent: cursor-agent` loads; `.default_agent == "cursor-agent"`.
    - Tier: 2
  - **Test 2**: `tests/pipeline/test_settings_cursor.py::test_default_agent_rejects_unknown`
    - Behavior: an unknown agent still raises `SettingsError` (negative control).
    - Tier: 2
  - **Test 3**: `tests/_helpers/test_llm_dispatch_guard.py::test_cursor_agent_is_a_guarded_binary`
    - Behavior: a `subprocess.run(["cursor-agent", ...])` in production code is flagged by the guard (`cursor-agent` in `_LLM_BINARIES`).
    - Tier: 2

  **TDD discipline**: required — tests above MUST be added in the same commit as or earlier than the implementation commit for `src/research_framework/pipeline/settings.py`.

- T003 Cursor token capture: add `_cursor_cost_from_output(stdout)` reading the cursor `result` object/last-line `usage.{inputTokens,outputTokens}` (camelCase, no dollar) → `(tokens_in, tokens_out)`. Generalise `_apply_stream_event` to also read camelCase usage keys (claude snake_case path unchanged).

  ### Testing Requirements

  - **Test 1**: `tests/scripts/test_agent_call_cursor.py::test_cursor_tokens_from_json_object`
    - Behavior: given a one-line cursor `{"type":"result",...,"usage":{"inputTokens":11,"outputTokens":7}}`, returns `(11, 7)`.
    - Tier: 2
  - **Test 2**: `tests/scripts/test_agent_call_cursor.py::test_apply_stream_event_camelcase_usage`
    - Behavior: `_apply_stream_event` on a cursor `result` event sets `tokens_in/out` from camelCase keys and leaves `cost_usd == 0.0`.
    - Tier: 2
  - **Test 3**: `tests/scripts/test_agent_call_cursor.py::test_apply_stream_event_claude_snakecase_unchanged`
    - Behavior: a claude `result` event with `input_tokens`/`output_tokens` + `total_cost_usd` still parses exactly as before (regression guard).
    - Tier: 2

  **TDD discipline**: required — tests above MUST be added in the same commit as or earlier than the implementation commit for `scripts/agent_call.py`.

- T004 Honest cost resolution for cursor: introduce `_COST_SOURCE_RUNTIME_TOKENS = "runtime_tokens"`; make `_resolve_cost` (and the `dispatch()`/`run()` flows) record, for `cursor-agent`, REAL stream/parsed tokens + the spec-033 ESTIMATOR dollar + `cost_source: runtime_tokens`. Route cursor through the stream-json path (`use_stream` true for claude OR cursor).

  ### Testing Requirements

  - **Test 1**: `tests/scripts/test_agent_call_cursor.py::test_cursor_sidecar_cost_source_runtime_tokens`
    - Behavior: a stubbed cursor dispatch writes a sidecar with `cost_source == "runtime_tokens"`, real `tokens_in/out`, and a non-null estimated `cost_usd`.
    - Tier: 3
  - **Test 2**: `tests/scripts/test_agent_call_cursor.py::test_cursor_dollar_is_estimate_not_zero`
    - Behavior: with the estimator available, cursor `cost_usd > 0` (never a silent $0). The estimator-unavailable path degrades to an honest `cost_usd == 0.0` with `cost_source` still `runtime_tokens` (covered by the dedicated degrade-without-crash test).
    - Tier: 3
  - **Test 3**: `tests/scripts/test_agent_call_cursor.py::test_codex_and_claude_cost_source_unchanged`
    - Behavior: codex stays `estimated` (no-$ fallback) and claude stays `runtime` (real in-stream $) — the new flat-rate branch must not touch the metered runtimes (regression guard).
    - Tier: 3

  **TDD discipline**: required — tests above MUST be added in the same commit as or earlier than the implementation commit for `scripts/agent_call.py`.

- T005 [P] Estimator parity: add `"cursor-agent": 1.0` to `DEFAULT_ESTIMATOR_CALIBRATION` (`cost_estimator.py`) and `_DEFAULT_ESTIMATOR_CALIBRATION` (`settings.py`); add a `cursor-agent` tiktoken branch (`o200k_base`, `_OUTPUT_RATE_CODEX`) returning a real `codex_tokens` estimate so the metered-token cap has a number.

  ### Testing Requirements

  - **Test 1**: `tests/pipeline/test_cost_estimator_cursor.py::test_cursor_tiktoken_branch_returns_tokens`
    - Behavior: `estimate_dispatch(agent="cursor-agent", ...)` returns `cost_usd > 0` and `codex_tokens > 0` with `vendor == "cursor-agent"`.
    - Tier: 2
  - **Test 2**: `tests/pipeline/test_cost_estimator_cursor.py::test_cursor_calibration_default_present`
    - Behavior: `DEFAULT_ESTIMATOR_CALIBRATION["cursor-agent"] == 1.0` and a `settings.yaml` override is honoured.
    - Tier: 2

  **TDD discipline**: required — tests above MUST be added in the same commit as or earlier than the implementation commit for `src/research_framework/pipeline/cost_estimator.py`.

- T006 [P] Budget-guard parity: define `_METERED_TOKEN_AGENTS = {"codex","cursor-agent"}`; `refresh_actuals` tallies tokens for that set; `check_pre_dispatch` fires the (renamed-in-doc) metered-token cap for `agent in _METERED_TOKEN_AGENTS`. Dollar cap already covers cursor.

  ### Testing Requirements

  - **Test 1**: `tests/pipeline/test_budget_guard_cursor.py::test_cursor_tokens_tallied`
    - Behavior: `refresh_actuals` sums `tokens_in+out` for a `cursor-agent` sidecar row into the tally.
    - Tier: 2
  - **Test 2**: `tests/pipeline/test_budget_guard_cursor.py::test_cursor_token_cap_fires`
    - Behavior: with `codex_token_budget` set and a cursor projection over it, `check_pre_dispatch(agent="cursor-agent")` returns a `codex_token_cap_exceeded` pause.
    - Tier: 2
  - **Test 3**: `tests/pipeline/test_budget_guard_cursor.py::test_cursor_dollar_cap_fires_on_estimate`
    - Behavior: cursor's estimated dollar counts toward `cycle_budget_usd` (dollar cap fires identically to codex).
    - Tier: 2
  - **Test 4**: `tests/pipeline/test_budget_guard_cursor.py::test_codex_token_cap_unchanged`
    - Behavior: existing codex token-cap behavior is byte-identical and claude is still NOT token-capped (regression guard).
    - Tier: 2

  **TDD discipline**: required — tests above MUST be added in the same commit as or earlier than the implementation commit for `src/research_framework/pipeline/budget_guard.py`.

- T007 [P] Tier→model map: add `_CURSOR_MODEL_TIERS = {basic: composer-2.5-fast, normal: gpt-5.4-high, flagship: claude-opus-4-8-thinking-high}` (the `basic`/`normal`/`flagship` keys match the repo's `settings.yaml::tiers` vocabulary and the test); wire cursor into the same tier-resolution the claude/codex adapters use; `settings.yaml::tiers` overrides win.

  ### Testing Requirements

  - **Test 1**: `tests/scripts/test_agent_call_cursor.py::test_cursor_model_tiers_defaults`
    - Behavior: `_CURSOR_MODEL_TIERS == {basic: composer-2.5-fast, normal: gpt-5.4-high, flagship: claude-opus-4-8-thinking-high}` (recommended map; tiers are resolved upstream into an explicit model, exactly like the codex profile).
    - Tier: 2
  - **Test 2**: `tests/scripts/test_agent_call_cursor.py::test_cursor_cmd_uses_explicit_model`
    - Behavior: `_cursor_cmd` emits `--model <explicit>` from the resolved executor.
    - Tier: 2

  **TDD discipline**: required — tests above MUST be added in the same commit as or earlier than the implementation commit for `scripts/agent_call.py`.

- T008 Scaffold/docs: a settings example documenting `default_executor.runtime: cursor-agent` (model, `--trust/--force/--sandbox/--approve-mcps`, tier map); note the `--workspace`/sandbox write-confinement story (cross-ref spec 042); confirm the generator needs no runtime-specific scaffolding branch (or add one).

  ### Testing Requirements

  - **Test 1**: `tests/scripts/test_agent_call_cursor.py::test_cursor_full_fixture_cycle_writes_note`
    - Behavior: a Popen-stubbed cursor stream-json drives the load-bearing `run()` CLI path end-to-end; the sidecar carries `agent == "cursor-agent"`, `cost_source == "runtime_tokens"`, and the real tokens.
    - Tier: 3

  _Coverage/integration task — the `run()`-path behaviour it exercises is
  introduced under T004 (no new module here), so this is not a TDD-first task._

- T009 Polish: `ruff check` + `ruff format --check`; full `pytest -m "not e2e"` green; confirm existing claude/codex agent_call + budget + estimator tests pass unmodified.

  ### Testing Requirements

  _No net-new tests — this task runs the existing suite as the regression gate._

---

## Notes

- Principle IV: no real `cursor-agent` calls in any test — a hermetic `CURSOR_BIN`
  python stub emits canned json/stream-json (mirrors the youtube `_BIN` pattern).
- Principle V: no new runtime deps; tiktoken stays the optional `[budget]` extra.
- Doc-sync (CHANGELOG/ROADMAP/spec-status/`Closes #N`/version bump to 1.0.0rc4)
  is a ship-time activity per CLAUDE.md — handled in the `ship_052` step, not here.
