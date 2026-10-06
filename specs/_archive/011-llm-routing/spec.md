# Spec 011 — Per-Flow LLM Routing

**Status**: superseded(by spec 025, spec 028, spec 033)

> **🗄️ ABSORBED INTO foundation arc (2026-05-22).** The per-stage
> routing problem this spec described has been partly absorbed by
> shipped work and partly retargeted into future specs:
>
> - The single LLM dispatch surface (`scripts/agent_call.py`) +
>   per-stage configuration plumbing landed in **spec 025 Tier A**
>   (SHIPPED 0.3.0). `pipeline/settings.py::VaultSettings.stage()`
>   gives every research stage a typed override surface
>   (spec 025 US7, SHIPPED 0.3.1).
> - The honest cost telemetry that per-flow routing decisions need
>   to be cost-aware is now **spec 028 — Dispatch Telemetry**
>   (drafted 2026-05-22, awaiting `/speckit.clarify`).
> - The cost-aware routing decision itself (haiku for audits,
>   sonnet for queries, opus for research) is now **spec 033 — Cost
>   Enforcement** (drafted 2026-05-22, URGENT under the codex
>   2026-06-01 cap).
> - The `vault-config.yaml` `flows` block this spec proposed has
>   NOT been implemented as-described; the as-shipped surface uses
>   `settings.yaml` per-stage overrides instead. If a future spec
>   revives the `flows` block, it should rebase on the shipped
>   `VaultSettings` API.
>
> Treat 011 as design-history. Do NOT plan against 011 directly —
> use 025 (shipped), 028 (drafted), and 033 (drafted) instead.
>
> **Vision spec.** This is a design-intent document, not an implementation
> plan. Do not start implementation until a tasks.md is written with full detail.

## Problem Statement

`settings.yaml` has per-stage model overrides for research stages (scout,
note-writer, verifier, topic-propose), but the query and maintenance flows
inherit whatever model the Claude Code session happens to use. There is no
way to say "use haiku for audit checks and opus for query answers" without
manually switching models in the session.

This matters because:
- Research benefits from deep reasoning (Opus) but runs in batch — cost
  is amortised over many cycles
- Query answers need to be fast and responsive (Sonnet) — latency matters
- Audit/maintenance checks are structural (Haiku) — cost matters
- A user might want a local LLM for research and a commercial model for queries

The gap: command templates (`ask.md`, `write.md`) and the new maintenance
script (`vault_maintain.py`) have no mechanism to select a model.

## Proposed Solution

Extend `vault-config.yaml` with a `flows` section that declares the preferred
model/runtime for each flow. At generation time, this config is rendered into
the vault. Command templates read it at invocation; scripts read it at runtime.

```yaml
# vault-config.yaml (generated into each vault)
flows:
  research:
    model: opus
    runtime: claude
  query:
    model: sonnet
    runtime: claude
  maintenance:
    model: haiku
    runtime: claude
  audit:
    model: haiku
    runtime: claude
  document:
    model: sonnet
    runtime: claude
```

## Non-Goals

- Building a model router from scratch — `agent_call.py` already handles
  runtime dispatch; this spec just exposes the per-flow config
- Supporting multiple runtimes within a single flow — one model per flow
  is sufficient for v1
- Hot-swapping models mid-session — config is read at invocation time

## Technical Design (high-level)

### `vault-config.yaml.j2` extension

Add the `flows:` block rendered from `spec.settings.flows` (or from
a default table in `SimpleSpecConfig` if not overridden).

### Command template changes (`ask.md.j2`, `write.md.j2`, `research.md.j2`)

Add a preamble that reads `vault-config.yaml` and selects the appropriate
model:

```markdown
<!-- Generated from vault-config.yaml — do not edit directly -->
Model: {{ flows.query.model }} ({{ flows.query.runtime }})
```

This renders at generation time into the static command file, so the model
is baked in. Users who want to change it edit `vault-config.yaml` and
re-render with `./vault reindex` (or a new `./vault reconfigure` command).

### `agent_call.py` pass-through

`agent_call.py` already accepts `--stage` and resolves model from
`settings.yaml`. The change is that `vault-config.yaml` values feed into
`settings.yaml` under a `flows:` key that `agent_call.py` reads.

### Per-spec defaults

The `SimpleSpecConfig` expansion (in `spec/simple.py`) maps `growth_mode`
to default flow models:

| Growth mode | Research | Query | Maintenance |
|-------------|----------|-------|-------------|
| throwaway | haiku | haiku | haiku |
| incremental | sonnet | sonnet | haiku |
| big-bang | opus | sonnet | haiku |

Users who want to override declare `settings.flows.*` in their spec.

## Constraints to Preserve Until This Ships

- `agent_call.py` must remain the single LLM dispatch point — don't let
  command templates hardcode `claude --model sonnet` directly
- `vault-config.yaml` must be writable by the vault's automation — it's
  a generated file that the pipeline updates; don't make it user-editable
  by convention if it will be overwritten
- The `flows:` section in `settings.yaml` must be additive — existing
  per-stage overrides continue to work and take priority over flow-level
  defaults

## Provisional Acceptance Criteria

1. A vault generated with `growth_mode: throwaway` uses haiku for all flows
2. A vault with `settings.flows.query.model: opus` uses opus for `/ask`
3. `vault-config.yaml` contains a `flows:` section after generation
4. `agent_call.py --stage ask` resolves model from `vault-config.yaml`
   if `settings.yaml` has no stage-specific override
5. Changing `vault-config.yaml` and running `./vault reindex` takes effect
   in the next query without vault regeneration
