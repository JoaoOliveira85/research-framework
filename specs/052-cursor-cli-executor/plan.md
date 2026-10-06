# Implementation Plan: Cursor CLI Executor (spec 052)

**Status:** Ready for `/speckit.implement` (2026-06-08)
**Target:** 1.0.0rc4
**Branch:** `052-cursor-cli-executor`

## Summary

Add `cursor-agent` as a third **first-class** LLM runtime in the single dispatch
surface (`scripts/agent_call.py`), with honest cost telemetry (real tokens from
the runtime + estimated dollars, flagged `cost_source: runtime_tokens`), a
stream-json live-output + token-capture path, estimator + budget-guard parity,
and a tier→model map — all without changing claude/codex behaviour byte-for-byte.

This is a CLI-only addition that extends the existing `_RUNTIME_ADAPTERS`
registry; it deliberately does NOT build the spec-047 vendor abstraction.

## Empirical contract (resolved 2026-06-08, see spec.md Clarifications)

- `cursor-agent -p --output-format json` → one result object with
  `usage:{inputTokens,outputTokens,cacheReadTokens,cacheWriteTokens}`,
  `duration_ms`, `result`, `session_id`. No dollar figure (flat-rate).
- `--output-format stream-json` → NDJSON: `system/init`, `user`, `assistant`
  (`message.content[].text`, same shape claude uses), terminal `result` (with
  `usage` camelCase, no `total_cost_usd`).
- Models via `--list-models`; headless via `-p --trust --force`.

## Seam map (exact sites)

- **Command construction** (pluggable): `_RUNTIME_ADAPTERS` registry,
  `scripts/agent_call.py:450`. → add `_cursor_cmd` (+ `_cursor_cmd_with_cost`
  for stream-json), `CURSOR_BIN` override.
- **Executor enum / validation** (hardcoded dual):
  - `pipeline/settings.py:16` `DefaultAgent` Literal, `:19` `_VALID_AGENTS`,
    `:889` `_parse_default_agent` error text.
  - `scripts/agent_call.py:493` `_LLM_AGENT_NAMES`.
  - `tests/_helpers/test_llm_dispatch_guard.py:30` `_LLM_BINARIES`.
- **Stream/cost capture** (claude-specific):
  - `agent_call.py:1064` `use_stream = agent_name == "claude" and …` → also true
    for `cursor-agent`.
  - `agent_call.py:789` `_apply_stream_event` reads `usage.input_tokens` /
    `total_cost_usd` → also read camelCase `inputTokens/outputTokens`
    (additive; claude unaffected). `_extract_text_from_event` (`:1320`) already
    handles cursor's text shape — no change.
  - `_resolve_cost` (`:921`) → for a flat-rate runtime with a stream, return the
    **estimated** dollar + the **real** stream tokens + `cost_source:
    runtime_tokens`.
  - `run()` CLI path (`:1488`/`:1504`) → route cursor through the stream-cost
    helper too.
- **Cost estimation** (inline `if agent ==`):
  - `pipeline/cost_estimator.py:21` `DEFAULT_ESTIMATOR_CALIBRATION` +
    `settings.py` `_DEFAULT_ESTIMATOR_CALIBRATION` → add `"cursor-agent": 1.0`.
  - `cost_estimator.py:156/171` tiktoken branch → add a `cursor-agent` branch
    (o200k_base, `_OUTPUT_RATE_CODEX`, returns real `codex_tokens` estimate so
    the metered-token cap has a number).
- **Budget enforcement** (codex-specific):
  - `budget_guard.py:254` `refresh_actuals` tallies tokens for `agent ==
    "codex"` → tally for a `_METERED_TOKEN_AGENTS = {"codex","cursor-agent"}`
    set.
  - `budget_guard.py:362` `check_pre_dispatch` token cap fires for `agent ==
    "codex"` → fire for `agent in _METERED_TOKEN_AGENTS`. Dollar cap already
    covers cursor (`dollar_increment` excludes only local/fake).
- **Fake-agent shim**: binary-agnostic (shim replacement) — no new handler
  needed; tests use a `CURSOR_BIN` stub.

## Cost-source design (the crux)

`cursor-agent` gives REAL tokens but NO dollar. To keep spec-033 honest:

```
cost_source value      tokens     dollars     used by
---------------------  ---------  ----------  ----------------------
runtime                measured   measured    claude stream, codex-with-$
runtime_tokens (NEW)   measured   estimated   cursor-agent (flat-rate)
estimated              estimated  estimated   codex no-$ fallback
none                   0          0           estimator also failed
```

`_resolve_cost` and the stream path special-case the flat-rate runtime: real
stream tokens are kept, the dollar comes from `_fallback_estimate`, and the
source is `runtime_tokens`. The dollar still flows into the dollar cap; the
tokens flow into the metered-token cap.

## Tier→model map

`_CURSOR_MODEL_TIERS = {"basic": "composer-2.5-fast", "standard":
"gpt-5.4-high", "expert": "claude-opus-4-8-thinking-high"}`, overridable via
`settings.yaml::tiers`. Resolution mirrors the existing claude/codex tier logic.

## Invariants / non-goals

- Existing claude/codex sidecars byte-identical; their tests unmodified.
- LLM-dispatch guard rejects a stray `cursor-agent` subprocess outside
  `agent_call.py`.
- No spec-047 abstraction; no Ollama/HTTP; no new runtime deps (Principle V —
  stdlib + the already-present tiktoken optional extra).

## Test strategy

Hermetic `CURSOR_BIN` stub (a tiny python script emitting canned
json/stream-json), mirroring the youtube `_BIN` env-override pattern. Contract
tests for: argv shape, token capture (json + stream-json), `cost_source:
runtime_tokens`, dollar+token cap firing, enum/guard widening, tier→model. No
real `cursor-agent` calls in the suite (Principle IV).
