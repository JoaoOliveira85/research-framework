# Feature Specification: Local-Model Agentic Fit (spike)

**Feature Branch**: `065-local-model-agentic-fit`
**Created**: 2026-06-13
**Status**: planned — 🔬 **DRAFT / SPIKE — design-space, not implementable.** Captures the empirical findings from the first live opencode + local-Ollama validation runs (2026-06-12/13, on the back of spec 064) and frames the spikes needed before local models are a *reliable* executor path for real research cycles. Gated: `/speckit.plan` only after a chosen spike direction is greenlit. The 064 executor itself is correct and shipped — this is about model/prompt FIT, not the dispatch layer.
**Builds on**: Spec 064 (opencode Executor — the dispatch surface) and spec 047's deferred Q1 (vendor-neutral templates).
**Tracking issue**: #147.

**Input**: opencode is a working, provider-agnostic executor (spec 064). But a real `./vault research` cycle on local Ollama models **does not complete the autonomous research stages** — even on capable, tool-optimized models. This spec records *why* (with evidence) and proposes spikes to close the gap, so local $0 cycles become real rather than aspirational.

## Context: what the validation runs actually showed (2026-06-12/13)

Hardware: RTX 5070 Ti (16 GB VRAM), i7-14700K, 64 GB DDR5. Operator's Ollama box, reached by opencode via its OpenAI-compatible provider.

Three distinct issues were diagnosed and separated:

1. **Infrastructure (RESOLVED — not the framework).** Early runs were crippled by **leaked VRAM** (only ~90 MiB free of 16 GiB after crash-heavy testing) and **IntelliJ's Ollama autocomplete contending the GPU**. After a clean restart + freeing the GPU, the box runs **~32.6 tok/s warm** and a scout-sized generation completes in ~17.5 s direct. Speed is fine.

2. **Framework / opencode plumbing (CLEAN).** opencode dispatched through the real `cycle_runner`, executed tools, and left **zero orphaned processes** (the spec-050 process-group reap works for opencode in the real pipeline; the orphan leak is benchmark-runner-only). Cost telemetry parses correctly. No 064 defect.

3. **THE BLOCKER — local models don't *complete* the autonomous structured stages.** The scout stage requires the agent to consult sources and **write a structured JSON report to a specific path** ("output ONLY the JSON file… do not print to stdout"). Observed behaviour:
   - `qwen3.6:27b` (dense): emitted a *bash command as plain text* (` ```bash cat CLAUDE.md``` `) instead of invoking the read tool, then stopped. No report.
   - `qwen3-coder:30b-64k` (MoE, tool-call-optimised): *did* invoke tools — `grep`, then `webfetch` of `sqlite.org/wal.html` (correctly!) — but improvised a **non-standard `<function=…>` tool-call syntax**, then **drifted into a conversational summary** ("…Is there a specific aspect you'd like to know more about?") and **stopped without writing the JSON report**. The research was done; the *task contract* was not.

The local models treat the stage like a **chat** (research → summarise for a human) instead of an **autonomous job** (produce structured output → write it to the given path). Claude / cursor-class agents honour the contract reliably; local 27–30B models do not.

## Root-cause hypotheses (to validate in the spike)

- **H1 — Vendor-skewed prompts (the spec-047 Q1 debt).** The framework's stage prompts + the operator's **global agent files** (`AGENTS.md`, `~/.config/opencode` skills — opencode loaded **37 skills / ~13.5k tokens of fixed context** for a trivial call) are tuned for commercial Claude-class agents. The "fluff" is noise a local model can't filter — it bloats context and dilutes the *one* instruction that matters ("write the JSON to this path"). *(Operator hypothesis, 2026-06-13.)*
- **H2 — opencode's default `build` agent is wrong for the job.** It is a coding agent with the full toolset and a chat-completion posture; nothing forces a single-shot, write-the-file-then-stop loop.
- **H3 — Tool-protocol mismatch.** The local model emits non-native tool-call syntax (`<function=…>`); opencode tolerates some of it, but the round-trip is fragile and the model loses the thread.

## Proposed spike directions (pick one+ to `/speckit.plan`)

1. **Lean / vendor-neutral prompt path for local executors (H1).** A reduced prompt + minimal agent context (opencode `--pure` strips plugins/skills; a tool-limited agent profile) so a local model sees only the task + the output contract. Measure: does a local model then write the scout JSON?
2. **Output-forcing agent profile (H2).** Constrain opencode to a single-shot, write-required posture (tool-limited agent defined in `opencode.json`, or a per-stage `--agent`), removing the conversational drift.
3. **Evaluate OpenHands as an alternative agentic frontend (operator candidate).** OpenHands (formerly OpenDevin) is a purpose-built autonomous agent runtime with stronger task-completion scaffolding; assess whether it drives local models to completion where opencode's chat-posture loop does not. Same 064 seam philosophy — another executor behind `_RUNTIME_ADAPTERS` if it proves out.
4. **Local-model capability sweep.** Use the spec-056 benchmark (once its harness fixes land) to score `{local model × stage}` task-completion rate, so model selection for the local path is evidence-based, not anecdotal.

## Out of scope

- Any change to the spec-064 opencode executor dispatch/cost/containment code — it is correct.
- Making local models a v1.0.0 gate. The v1.0.0 validation campaign runs on **cursor-agent**; local-model fit is explicitly deferred to post-1.0.0 work (operator decision, 2026-06-13).
- Re-plumbing the inference engine (ollama vs llama.cpp): the issue is model task-completion, not the engine — llama.cpp only helps VRAM-fit/speed, which is already adequate.

## Dependencies

- **Hard**: Spec 064 (opencode executor — the seam these spikes attach to).
- **Soft**: Spec 056 (benchmark harness — the measurement tool for direction 4, pending its orphan-reap/timeout fixes).
- **Absorbs**: spec 047's deferred Q1 (vendor-neutral templates) for the local-model case.

## Success criteria (for a future, post-spike implementation — not this draft)

- **SC-001**: A real `./vault research` cycle on a *local* model completes the scout stage — i.e. writes a schema-valid scout report — and produces ≥1 substantive note, unattended.
- **SC-002**: The chosen direction is evidence-backed: a measured task-completion rate per `{local model × stage}`, not a single anecdote.
