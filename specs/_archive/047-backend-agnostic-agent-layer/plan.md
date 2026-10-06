# Implementation Plan: 047 v1 — Ollama HTTP Executor

**Status:** Implemented (2026-06-08) — see Clarifications Session 2026-06-08 in `spec.md`.
**Target:** 1.0.0rc5
**Branch:** `047-ollama-http-executor`

## Summary

Add a **local Ollama HTTP server** as the first *non-CLI* LLM runtime, wired
into the single dispatch surface (`scripts/agent_call.py`) as ONE guarded
`http`/`api` branch — NOT a parallel script (FR-008/009 honored). Cost
telemetry for a local runtime is honest and free: `cost_usd: 0.0` with REAL
token counts from the API `usage` block, flagged `cost_source: "runtime"`.

This is an **incremental** step toward the full spec-047 vendor abstraction:
v1 adds the second backend (User Story 2 — "second backend validates the
seam"); it deliberately does NOT refactor the existing `claude`/`codex`/
`cursor-agent` CLI adapters behind an interface (User Story 1, FR-001..006 —
deferred to later 047 stages).

## Empirical contract (Ollama, resolved 2026-06-08)

- Ollama exposes an **OpenAI-compatible** endpoint at
  `POST {base_url}/v1/chat/completions` →
  `{"choices":[{"message":{"content": "..."}}], "usage":{"prompt_tokens":N,"completion_tokens":M}}`.
- It also exposes a **native** endpoint at `POST {base_url}/api/chat` →
  `{"message":{"content":"..."}, "prompt_eval_count":N, "eval_count":M}`.
- v1 defaults to the OpenAI-compatible path; both response shapes are parsed so
  `api_path: /api/chat` works too.
- Local ⇒ genuinely $0 per call; the `usage`/`*_count` numbers are REAL tokens.

## Seam map (exact sites)

- **Dispatch trigger** (previously parsed-but-unused): `communication.mode:
  http` + `default_executor.type: api` → new `_is_http_executor(executor)`.
- **HTTP dispatch** (new, single branch): `_dispatch_http()` in
  `scripts/agent_call.py`, placed BEFORE the streaming/CLI branches in both
  `dispatch()` (programmatic) and `run()` (CLI) — it never reaches
  `_build_command` (Ollama has no CLI adapter).
  - `_http_endpoint(executor)` — `{base_url}{api_path}`; `OLLAMA_BASE_URL` env
    overrides `base_url` when set (run-time override without editing the
    profile); default `api_path` `/v1/chat/completions`.
  - `_http_post_json(url, payload, timeout)` — stdlib `urllib` POST; honors the
    `OLLAMA_HTTP_FIXTURE` file seam for hermetic tests (NO network).
  - `_parse_http_response(obj)` — `(text, tokens_in, tokens_out)` for BOTH the
    OpenAI-compatible and Ollama-native shapes.
- **Executor enum** (hardcoded dual): `DefaultAgent` Literal + `_VALID_AGENTS`
  + `_parse_default_agent` message (`pipeline/settings.py`); `_LLM_AGENT_NAMES`
  + new `_HTTP_RUNTIMES = {"ollama"}` (`agent_call.py`).
- **Cost** (local/unmetered): reuse the existing `local`/$0 semantics —
  `cost_usd: 0.0`, real tokens, `cost_source: "runtime"`. Ollama is NOT a
  metered-token agent (no external token cap, unlike codex/cursor).
- **Estimator parity**: `"ollama": 1.0` in both
  `pipeline/cost_estimator.DEFAULT_ESTIMATOR_CALIBRATION` and
  `pipeline/settings._DEFAULT_ESTIMATOR_CALIBRATION` (for completeness — the
  dollar can never fire at $0).
- **Sidecar footgun fix**: `budget_guard.list_sidecars_v11` accepted only
  `schema_version == "1.1"` while the writer emits `"1.2"`, silently dropping
  every modern sidecar from the dollar tally. Now accepts the additive `1.x`
  line from 1.1 onward via `_is_talliable_sidecar_version` (1.0 stays excluded).

## New profile

- `settings.ollama.yaml` (peer of `settings.cursor.yaml` / `settings.codex.yaml`):
  `communication.mode: http`, `default_executor.{type: api, runtime: ollama,
  base_url: http://localhost:11434, api_path: /v1/chat/completions}`, and the
  tier→model map: basic→`qwen3:14b`, normal→`gemma3:27b`, flagship→`llama3.3:70b`.

## Out of scope (deferred to later 047 stages)

- Refactoring `claude`/`codex`/`cursor-agent` behind a backend interface
  (FR-001..006 / User Story 1).
- Other HTTP vendors (OpenAI, Gemini), multi-vendor consensus (Q3), per-stage
  `backend` key (Q4), vendor-native cost passthrough (Q2), template
  vendor-neutralization (Q1).

## Verification

- Hermetic: no test makes a real network call (`_http_post_json` patched or the
  `OLLAMA_HTTP_FIXTURE` seam).
- `tests/scripts/test_agent_call_ollama.py` (detection, endpoint, both parsers,
  dispatch sidecar provenance, error path, run() path, no-CLI-build guard).
- `tests/pipeline/test_budget_guard_ollama.py` (1.2-now-tallied regression +
  1.1 back-compat + ollama $0/unmetered).
- `tests/pipeline/test_settings_ollama.py` (default_agent accepts ollama;
  shipped profile loads).
- Foreman Arm A (`scripts/foreman/verify_test_coverage.py`) + Arm B before PR.
