# Phase 0 Research — opencode Executor

**Date**: 2026-06-11 · **Probe**: `opencode` v1.16.2 installed at `/opt/homebrew/bin/opencode`; `opencode run --help` captured. Items marked **VERIFY@IMPL** need a live JSON-event capture (requires a configured model) but have a documented expected shape.

---

## R1 — Headless invocation + machine-readable output (FR-003)

**Decision**: Invoke `opencode run --format json --model <provider/model> --dir <vault> [--variant <effort>] [--agent <name>]`, feeding the prompt on the positional `message`/stdin. Parse the JSON event stream for the terminal completion event to recover assistant text + token usage.

**Rationale**: `opencode run` is the documented non-interactive entry point. `--format json` ("raw JSON events") is the machine-readable mode (the `default` format is human-formatted and unparseable). This mirrors the cursor adapter exactly (`-p --output-format json|stream-json`), so it slots into the existing dispatch/cost tail with minimal new code.

**Alternatives considered**:
- *`--attach` to a running opencode server + REST* — opencode can run a server (`--attach http://localhost:PORT`, basic-auth flags). Rejected for v1: reintroduces the long-lived-process / HTTP shape that the 047 primitive showed is awkward, and adds a server-lifecycle concern. The subprocess-per-call CLI shape is what every other adapter uses.
- *`default` format + scrape stdout* — rejected; brittle, no structured usage.

**VERIFIED 2026-06-11** (live run against the operator's ollama box, `ollama/qwen3-coder:30b-64k`, $0): `--format json` emits **NDJSON** (one JSON object per line, like cursor's stream-json — *not* a single JSON doc; parse line-by-line). The cost-bearing event is `type: "step_finish"`, shape:

```json
{"type":"step_finish","part":{"tokens":{"total":8566,"input":8523,"output":43,
  "reasoning":0,"cache":{"write":0,"read":0}},"cost":0}}
```

Parser rules: iterate lines, JSON-decode each, **accumulate over every `step_finish` event** (a multi-step agentic run emits one per step, each a real API call): `tokens_in += part.tokens.input`, `tokens_out += part.tokens.output`, `cost_usd += part.cost`. Be robust to a missing terminal event (the verification capture ended on a `step_start`) — use whatever `step_finish` events exist; zero of them ⇒ estimator fallback (R3). Tool actions surface as `type: "tool_use"` (`part.tool == "write"`, etc.).

---

## R2 — Vault-write containment (FR-010) — *primary risk, RESOLVED*

**Decision**: Pass `--dir <vault>` on every opencode invocation (auto-injected by an `opencode` branch in `_build_command`, exactly like codex `--cd` and cursor `--workspace`). An operator-supplied `--dir` in `args` wins (no double flag), reusing the `_has_workspace_flag` pattern.

**Rationale**: `opencode run --dir <path>` sets the directory the agent runs in — the working-root analogue of codex `--cd` / cursor `--workspace`. This is the write-confinement story (CHANGELOG `[1.0.0rc2]`): the orchestrator's cwd is not the vault, so the agent's writable root must be pinned to the vault. With `--dir`, opencode reads/edits within the vault and we never need a full-disk-access posture.

**Important distinction**: `--dangerously-skip-permissions` is an **approval** lever (auto-approve tool calls), NOT a sandbox/scope mechanism. It must never be used as the containment story (that would be the exact UNsandboxed pattern that tripped endpoint security pre-rc2). Containment = `--dir`; approval = the autonomy posture (R5).

**VERIFIED 2026-06-11**: with `--dir /tmp/oc-verify`, opencode's `write` tool resolved the relative path against `--dir` and wrote `/private/tmp/oc-verify/hello.txt` — inside the dir, nothing created outside it, exit 0. So `--dir` is the effective working root for file tools. **Residual VERIFY@IMPL**: whether `--dir` *hard-denies* an out-of-dir write when the model explicitly targets an absolute path elsewhere. SC-005 asserts zero out-of-vault writes; if `--dir` alone is only a root hint, back it with a generated `opencode.json` `permission` block scoping edits to the vault. The local run used `--dangerously-skip-permissions` to auto-approve the write headlessly (approval lever, R5) — orthogonal to `--dir` containment.

---

## R3 — Cost classification (FRs 006/007) — *the one genuinely new design decision*

**Problem**: cursor and ollama each have a *static* cost class — `_FLAT_RATE_AGENTS = {cursor-agent}` (real tokens + estimator dollar ⇒ `runtime_tokens`); `_HTTP_RUNTIMES = {ollama}` (local ⇒ measured `$0` ⇒ `runtime`). **opencode has no single static class** — its cost depends on the model it routes to: a local Ollama model is $0; a hosted model is metered.

**Decision**: Classify opencode cost **per call, by resolved provider**, not by static set membership:
1. If the resolved model is a **local** provider (provider prefix `ollama` / `local`, or a configured local-provider allowlist) → measured `cost_usd: 0.0` + **real** tokens from the usage event ⇒ `cost_source: "runtime"` (same as the ollama HTTP path). Tokens are NOT added to the metered-token cap (no external quota).
2. Else (**metered** hosted provider):
   - If the usage event includes a real per-call **dollar** → use it ⇒ `cost_source: "runtime"`.
   - Else (tokens but no dollar — the common case) → real tokens + spec-033 estimator dollar ⇒ `cost_source: "runtime_tokens"` (same as cursor); the dollar cap gates the estimate; metered tokens count toward the token cap.
   - Else (no usage at all) → estimator only ⇒ `cost_source: "estimated"`; never a silent `$0`.

**VERIFIED 2026-06-11**: opencode emits a real `part.cost` in each `step_finish` event (`0` for the local ollama run). For metered providers opencode derives this dollar from its built-in models.dev pricing catalog — so the **common metered case is rule (2): `cost_source: "runtime"` with a real measured dollar**, *richer* than cursor (which emits tokens but no dollar). The `runtime_tokens` estimator path (rule 3) is therefore the **fallback** for when `cost` is absent or unreliably `0` on a known-metered provider — not the primary path. Local stays rule (1): `cost == 0` + real tokens ⇒ measured `$0`, `cost_source: runtime`.

**Rationale**: Honors the existing `cost_source` literal set (`runtime` / `runtime_tokens` / `estimated` / `none`) with **no schema bump** — the rc3 sidecar schema 1.2 already carries `cost_source`. It keeps the "never bill blind / never silent $0" invariant (FR-007, the rc3 footgun lesson). Reuses the spec-033 estimator and the `_resolve_cost` tail verbatim; only the *classification* of opencode is new.

**Alternatives considered**:
- *Treat opencode as statically flat-rate like cursor* — wrong for local models (would estimate a dollar for a $0 run and fire the dollar cap spuriously).
- *Treat opencode as statically HTTP/local like ollama* — wrong for hosted models (would record a false `$0` for a billed call — the exact silent-$0 footgun FR-007 forbids).
- *A new `cost_source` literal* (`runtime_mixed`) — rejected; unnecessary schema churn. The per-call resolution already lands on the right existing literal.

**Implementation shape**: a small `_opencode_cost_class(model, usage) -> (cost_usd, tokens_in, tokens_out, cost_source)` helper consulted inside `_resolve_cost`. Local-provider detection is a prefix check on the `provider/model` string + an overridable allowlist in `settings.opencode.yaml`.

---

## R4 — Model selection + tier map (FR-004)

**Decision**: `settings.opencode.yaml` is cloned from `settings.cursor.yaml` with the model-tier map retargeted to opencode `provider/model` ids, and reasoning effort expressed via `--variant`:

| tier | example opencode model | how |
|---|---|---|
| basic | `ollama/qwen2.5:7b` (or a cheap hosted) | `--model ollama/qwen2.5:7b` |
| normal (default) | e.g. `anthropic/claude-sonnet-4-6` or `openai/gpt-…` | `--model <provider/model>` |
| flagship | e.g. `anthropic/claude-opus-4-8` + `--variant high` | `--model …` `--variant high` |

**Rationale**: opencode's `--model provider/model` is the provider-agnostic selector (FR-005 falls out for free). `--variant high|max|minimal` is opencode's reasoning-effort knob — the analogue of cursor baking `-high` into the model id and codex's `-c model_reasoning_effort`. The shipped profile picks sensible defaults but the operator edits one config value to repoint any stage at any provider. The default-shipped tier examples should bias to a **local** Ollama model for the basic tier (the cost pivot) with hosted models documented as drop-in.

**VERIFY@IMPL**: the operator's actual installed/authorized opencode providers (`opencode models` / the models.dev catalog) — the shipped defaults must reference models that exist; pick conservative, widely-available ids and document how to list/override.

---

## R5 — Autonomy posture (FR-013) + spec 042 relationship

**Decision**: For v1, `settings.opencode.yaml` ships the **unattended** posture in `default_executor.args` (the opencode analogue of cursor's `--force --approve-mcps`): auto-approve tool calls so a cron-driven cycle never blocks. The concrete mechanism is opencode's permission config (preferred — `opencode.json` `permission: { edit: allow, … }`) with `--dangerously-skip-permissions` as the blunt fallback. The full `autonomy_level: interactive|semi-auto|full-auto` → opencode mapping is a **forward integration**: spec 042 is still a *draft* (ROADMAP queue #19, not shipped), so 064 defines opencode's posture standalone and 042 will, when implemented, add opencode to its per-executor mapping table (042 Edge Case already anticipates "a future backend without `permissions.defaultMode` — the wrapper owns it").

**Rationale**: cursor's shipped profile already bakes the unattended posture into `args`; opencode parity keeps the "runs unattended out of the box" story. Gating 064 on the unshipped 042 would be a false dependency. FR-013's "defined posture per level" is satisfied at the executor level now; the settings→level wiring lands with 042.

**Alternatives considered**: blocking 064 on spec 042 — rejected (042 isn't ready; the dependency is soft). Defaulting to `--dangerously-skip-permissions` unconditionally — disfavored; prefer opencode's scoped permission config so "auto-approve" doesn't also mean "skip *denied* permissions". Use the blunt flag only if the permission config can't express the unattended-but-contained posture.

---

## R6 — Template vendor-neutrality (soft risk, not a gate)

**Decision**: No template rewrite in v1. Run the local-Ollama cycle; if a stage's prompt relies on a Claude-ism (e.g. `<thinking>` tags) that a given model ignores, the existing verifier/quality gates catch the degraded artifact (Constitution I) — that is signal about the *model*, not a framework defect. Document any observed vendor-specific template dependency; vendor-neutralize opportunistically later (this was 047's deferred Q1).

**Rationale**: Templates are already Jinja2 and largely vendor-neutral; a blanket audit is out of proportion to v1. The acceptance gates are the safety net. Keeps scope tight (the spec's Out-of-Scope already excludes the 047 template-audit work).

---

## R7 — Benchmark integration + custom label (FRs 018/019/020)

**Decision**:
- **FR-018/019 (free):** `benchmark/matrix.py::valid_runtimes()` loads `_RUNTIME_ADAPTERS ∪ _HTTP_RUNTIMES` from `agent_call.py` by path and caches it — so the moment opencode is registered in `_RUNTIME_ADAPTERS`, `{opencode × models × tasks}` cells validate and expand with **zero** benchmark code change. Add only a **guard test** asserting `"opencode" in valid_runtimes()` (mirrors the existing intent of picking up `ollama`/`cursor-agent` automatically).
- **FR-020 (small, SHOULD):** add an OPTIONAL `label: str | None` to `Executor` (`matrix.py`); when set, `Cell.key` and the reporter row use `label` in place of `executor`. Absent ⇒ `f"{task}__{executor}__{model}"` unchanged (byte-identical). One field + a 2-line `key` change + a reporter column tweak + a parse branch in `_parse_executors`.

**Rationale**: This is the "run all our tests through opencode, any model" capability — and it is almost free because 056 was deliberately built to discover runtimes from the registry. The label makes "same executor, different combos" (e.g. `opencode-local-qwen` vs `opencode-gpt5`) readable in reports without inventing fake runtime names. Capped at matrix/reporter per the user's "not worth much effort".

**Alternatives considered**: a separate per-model label list — rejected; the executor-block label is the smallest thing that satisfies the ask. Making `label` mandatory — rejected; would break the byte-identical default and every existing matrix YAML.

---

## R8 — 047 Ollama-HTTP branch disposition (FR-017)

**Decision**: **Leave `_dispatch_http` / `_HTTP_RUNTIMES = {ollama}` dormant** — do not delete in this spec. It is dead-but-harmless, remains a valid benchmark cell, and removing it is an orthogonal change with its own regression surface (sidecar tail, budget-guard schema-line matching, benchmark runtime union). 047's status header + ROADMAP already mark it superseded. Revisit deletion only if it starts to rot.

**Rationale**: smallest-blast-radius; the spec explicitly scoped retirement as a plan-time call, and "keep dormant" is the lower-risk call. The provider-agnostic opencode path is now the *recommended* way to reach Ollama; the raw HTTP path simply stops being recommended.
