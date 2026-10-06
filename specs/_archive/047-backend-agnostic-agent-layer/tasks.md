# Tasks: 047 v1 — Ollama HTTP Executor

**Branch:** `047-ollama-http-executor` · **Target:** 1.0.0rc5 · Implemented 2026-06-08.

`Testing Requirements` blocks below were authored from `spec.md` (Clarifications
Session 2026-06-08, Q-v1.1…Q-v1.5) + `plan.md`. Run the Arm A verifier
(`scripts/foreman/verify_test_coverage.py`) after implementation.

[P] = parallelisable (different files, no incomplete-task dependency).

---

- [x] T001 Add the HTTP runtime constants + detection to `scripts/agent_call.py`: `_OLLAMA = "ollama"`, `_HTTP_RUNTIMES = frozenset({_OLLAMA})`, widen `_LLM_AGENT_NAMES` to include `_OLLAMA`; add `_is_http_executor(executor)` (true when `type: api` OR `runtime` ∈ `_HTTP_RUNTIMES`; false for `type: script` and for CLI runtimes). Ollama must NOT be in `_STREAMING_AGENTS` / `_FLAT_RATE_AGENTS`.

  ### Testing Requirements

  _Authored by test-design pass on 2026-06-08. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_agent_call_ollama.py::test_is_http_executor_detection`
    - Behavior: `{type:api,runtime:ollama}` and `{runtime:ollama}` → True; `{type:cli,runtime:claude}`, `{type:script,runtime:ollama}`, `{runtime:codex}` → False.
    - Tier: 2
  - **Test 2**: `tests/scripts/test_agent_call_ollama.py::test_ollama_in_llm_agent_names`
    - Behavior: `ollama` ∈ `_LLM_AGENT_NAMES` and `_HTTP_RUNTIMES`; ∉ `_STREAMING_AGENTS` and `_FLAT_RATE_AGENTS`.
    - Tier: 2

  **TDD discipline**: required — tests above MUST be added in the same commit as or earlier than the implementation commit for `scripts/agent_call.py`.

- [x] T002 Endpoint + transport + parser helpers in `scripts/agent_call.py`: `_http_endpoint(executor)` (`{base_url}{api_path}`, default `api_path` `/v1/chat/completions`, `OLLAMA_BASE_URL` env overrides `base_url` when set, single-slash join); `_http_post_json(url, payload, timeout)` (stdlib `urllib` POST + `OLLAMA_HTTP_FIXTURE` file seam, NO network); `_parse_http_response(obj)` → `(text, tokens_in, tokens_out)` for the OpenAI-compatible AND Ollama-native shapes.

  ### Testing Requirements

  - **Test 1**: `tests/scripts/test_agent_call_ollama.py::test_http_endpoint_default_and_overrides`
    - Behavior: default path appended; trailing-slash base + custom `api_path` joins to a single slash; `OLLAMA_BASE_URL` used when `base_url` absent.
    - Tier: 2
  - **Test 2**: `tests/scripts/test_agent_call_ollama.py::test_parse_http_response_openai_shape`
    - Behavior: `choices[0].message.content` + `usage.{prompt,completion}_tokens` → `(text, tin, tout)`.
    - Tier: 2
  - **Test 3**: `tests/scripts/test_agent_call_ollama.py::test_parse_http_response_ollama_native_shape`
    - Behavior: `message.content` + `prompt_eval_count`/`eval_count` → `(text, tin, tout)`.
    - Tier: 2
  - **Test 4**: `tests/scripts/test_agent_call_ollama.py::test_http_post_json_fixture_seam`
    - Behavior: `OLLAMA_HTTP_FIXTURE` returns the file verbatim with NO network call.
    - Tier: 2

  **TDD discipline**: required.

- [x] T003 Widen the executor enum where it hardcodes `{"claude","codex","cursor-agent"}`: `DefaultAgent` Literal + `_VALID_AGENTS` + `_parse_default_agent` message (`pipeline/settings.py`); `_DEFAULT_ESTIMATOR_CALIBRATION` (settings) + `DEFAULT_ESTIMATOR_CALIBRATION` (`cost_estimator.py`) gain `"ollama": 1.0`.

  ### Testing Requirements

  - **Test 1**: `tests/pipeline/test_settings_ollama.py::test_default_agent_accepts_ollama`
    - Behavior: `settings.yaml` with `default_agent: ollama` loads; `.default_agent == "ollama"`.
    - Tier: 2
  - **Test 2**: `tests/pipeline/test_settings_ollama.py::test_default_agent_error_lists_ollama`
    - Behavior: an unknown agent raises `SettingsError` whose message names `ollama` (negative control + message coverage).
    - Tier: 2

  **TDD discipline**: required — same-or-earlier commit as `src/research_framework/pipeline/settings.py`.

- [x] T004 `_dispatch_http(executor, prompt, timeout_s)` + integrate into `dispatch()` in `scripts/agent_call.py`: returns `(stdout, stderr, exit_code, tokens_in, tokens_out)`; on success `cost_usd: 0.0`, real tokens, `cost_source: "runtime"`, `status: ok`; on transport error exit 2 + `status: failed` + `$0`. The HTTP branch runs BEFORE the streaming/CLI branches and shares the existing sidecar tail.

  ### Testing Requirements

  - **Test 1**: `tests/scripts/test_agent_call_ollama.py::test_dispatch_ollama_returns_text_and_real_tokens`
    - Behavior: stubbed `_http_post_json` → exit 0, text in stdout, real `tokens_in/out`, `cost_usd == 0.0`.
    - Tier: 3
  - **Test 2**: `tests/scripts/test_agent_call_ollama.py::test_dispatch_ollama_sidecar_cost_source_runtime`
    - Behavior: sidecar has `agent: ollama`, `agent_kind: real`, `cost_source: runtime`, `cost_usd: 0.0`, real tokens, `status: ok`.
    - Tier: 3
  - **Test 3**: `tests/scripts/test_agent_call_ollama.py::test_dispatch_ollama_http_error_is_failed`
    - Behavior: `_http_post_json` raising `OSError` → exit 2, `failed` in stderr, sidecar `status: failed`, `cost_usd: 0.0`.
    - Tier: 3
  - **Test 4**: `tests/scripts/test_agent_call_ollama.py::test_dispatch_ollama_native_endpoint_shape`
    - Behavior: a native-shape response is parsed end-to-end through dispatch.
    - Tier: 3

  **TDD discipline**: required.

- [x] T005 `_run_http(...)` + integrate into the CLI `run()` path in `scripts/agent_call.py` so `run_cycle.sh`-style invocations route Ollama through HTTP (never `_build_command`), writing the output file + sidecar identically to the CLI path.

  ### Testing Requirements

  - **Test 1**: `tests/scripts/test_agent_call_ollama.py::test_run_ollama_writes_sidecar_and_output`
    - Behavior: `run()` writes the output file (response text) + a sidecar with `agent: ollama`, `cost_source: runtime`, `cost_usd: 0.0`, real tokens.
    - Tier: 3
  - **Test 2**: `tests/scripts/test_agent_call_ollama.py::test_run_ollama_never_builds_cli_command`
    - Behavior: with `_build_command` patched to raise, `run()` still returns 0 (proves the HTTP branch handles ollama before any CLI-command construction).
    - Tier: 3

  **TDD discipline**: required.

- [x] T006 Fix the sidecar-version footgun in `pipeline/budget_guard.py`: `list_sidecars_v11` accepted only `schema_version == "1.1"` while the writer emits `"1.2"`, silently dropping every modern sidecar from the dollar tally. Add `_is_talliable_sidecar_version` accepting the additive `1.x` line from 1.1 onward (legacy 1.0 excluded).

  ### Testing Requirements

  - **Test 1**: `tests/pipeline/test_budget_guard_ollama.py::test_v12_sidecar_is_now_tallied`
    - Behavior: a `1.2` sidecar is listed AND its dollar reaches `refresh_actuals` (regression — was a silent $0).
    - Tier: 2
  - **Test 2**: `tests/pipeline/test_budget_guard_ollama.py::test_v11_sidecar_still_tallied`
    - Behavior: a legacy `1.1` sidecar still counts (back-compat); codex tokens still metered.
    - Tier: 2
  - **Test 3**: `tests/pipeline/test_budget_guard_ollama.py::test_ollama_sidecar_zero_dollar_and_unmetered_tokens`
    - Behavior: an ollama `1.2` sidecar contributes `$0` and 0 metered tokens (local/unmetered).
    - Tier: 2

  **TDD discipline**: required — same-or-earlier commit as `src/research_framework/pipeline/budget_guard.py`.

- [x] T007 [P] Ship `settings.ollama.yaml` (peer profile): `communication.mode: http`, `default_executor.{type:api, runtime:ollama, base_url:http://localhost:11434, api_path:/v1/chat/completions}`, tier map basic→`qwen3:14b` / normal→`gemma3:27b` / flagship→`llama3.3:70b`, model-router upgrade to the flagship.

  ### Testing Requirements

  - **Test 1**: `tests/pipeline/test_settings_ollama.py::test_shipped_ollama_profile_loads`
    - Behavior: the committed `settings.ollama.yaml` copies into a vault and loads via `load_vault_settings` without error.
    - Tier: 2

  **TDD discipline**: not required (data file; validated by the loader test).
