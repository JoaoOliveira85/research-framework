# Feature Specification: Pipeline Orchestrator as a Framework Command

> **🗄️ SUBSUMED BY ADR-0009 + spec 020 + spec 023 (2026-05-26).** The
> `/pipeline` slash-command + 7-phase orchestrator framing this spec
> proposed is superseded. The canonical entry point becomes
> `./vault refresh-sources` (spec 023 minimum subset) for source
> ingestion + the existing `pipeline.orchestrator.run_cycles` for
> the scout/research flow. The legacy `pipeline/runner.py` 7-phase
> orchestrator stays in place during the revival sprint (no
> deprecation banner per ADR-0009 clarify Q2) and is retired in a
> batched cleanup post-sprint as 020 modules port.
> Do NOT plan against 015g directly; open
> `docs/adr/0009-collectors-vs-modules-reconciliation.md`,
> `specs/020-code-bridge/spec.md`, and `specs/023-flow-separation/spec.md`
> instead. This file is kept as design-history.

**Feature Branch**: `015g-pipeline-orchestrator-command` *(proposal — not branched; subsumed)*
**Parent**: [015 — Pipeline Consolidation](../015-pipeline-consolidation/spec.md), Stage 4 (umbrella also partially subsumed)
**Created**: 2026-05-13
**Status**: superseded(by ADR-0009, spec 020, spec 023) — 🗄️ SUBSUMED BY ADR-0009 + spec 020 + spec 023 (2026-05-26)

## Problem

The feeds-vault's `/pipeline` slash command (~410 lines of orchestration
prose in `.claude/commands/pipeline.md`) sequences:

```
collect → extract → scout → triage → research → verify → report
```

It reads/writes `_pipeline/pipeline-state.json` to track progress,
handles partial completions, surfaces summaries, and tells the user
what command to run next. It works well — but it's per-vault and
will drift.

The framework already has a partial orchestrator (`research_vault
cycle <vault>` driven by `pipeline/orchestrator.py` +
`cycle_runner.py`) that runs scout + DFS + topic-harvest. That's a
subset of the feeds-vault's pipeline (no collect, extract, verify,
report phases).

This spec proposes the framework extend its orchestrator to cover
the full pipeline shape, making `/pipeline` a thin shim over the
framework command.

## Goals

1. **One framework command runs the full pipeline.** Subcommands
   match the user's mental model:
   ```bash
   research_vault pipeline <vault> full
   research_vault pipeline <vault> collect
   research_vault pipeline <vault> extract
   research_vault pipeline <vault> scout
   research_vault pipeline <vault> resume
   research_vault pipeline <vault> finish
   research_vault pipeline <vault> status
   ```
2. **Pipeline state lives in `<vault>/_pipeline/pipeline-state.json`
   with a stable framework-owned schema.** Today feeds-vault's shape is
   ad-hoc; we formalise it.
3. **Phase composition.** Each phase delegates to (015f) processors
   or to Claude Code (for LLM phases). The orchestrator handles
   sequencing, state, summaries, and pause-points.
4. **The vault's `/pipeline` slash command becomes a 5-line shim** —
   "shell out to `research_vault pipeline <vault> $1`".

## Non-goals

- **Not** a new LLM driver. The orchestrator continues to use
  Claude Code (for `/scout`, `/research`, `/verify`, `/report`)
  or `scripts/agent_call.py` for headless runs.
- **Not** a replacement for the existing `research_vault cycle`
  command. `cycle` becomes a synonym for `pipeline scout` +
  `pipeline resume` (the framework's current narrow loop).
- **Not** human-triage UI. The orchestrator stops at the triage
  point and tells the human to use Obsidian (or whatever) to
  triage; resumes on `research_vault pipeline <vault> resume`.

## User scenarios

### Story 1 — Full pipeline run

```bash
$ research_vault pipeline ~/Documents/feeds-vault full

[1/6] collect …
  → collect_rss: 12 new items
  → collect_youtube: 3 new items
  → collect_reddit: 8 new items
  Total: 23 new items in _pipeline/raw/

[2/6] extract …
  → 23 items processed; context tree at _pipeline/extracted/context-tree.md

[3/6] scout …
  → Topic Radar updated: <corpus>/00 - MOC/Topic Radar - May 2026.md
  → 7 new topics; 4 in Recommended Research Queue

HUMAN TRIAGE REQUIRED
Open the radar, approve/defer queue items, then:
  research_vault pipeline ~/Documents/feeds-vault resume
```

User triages, then:

```bash
$ research_vault pipeline ~/Documents/feeds-vault resume

[4/6] research …
  → 4 notes created, 1 updated; queue clear
[5/6] verify …
  → 5 notes spot-checked; 0 fails
[6/6] report …
  → Weekly report at _pipeline/exports/weekly-2026-05-13.md

Run complete.
```

### Story 2 — Status

```bash
$ research_vault pipeline ~/Documents/feeds-vault status

Pipeline status (run started 2026-05-13 14:00):
  collect    ✓ done   (12 + 3 + 8 = 23 items)
  extract    ✓ done   (23 processed)
  scout      ✓ done   (7 topics)
  triage     ⏸ waiting (4 unchecked queue items)
  research   – pending
  verify     – pending
  report     – pending
```

### Story 3 — Vault slash command is a shim

`research_vault generate` writes `.claude/commands/pipeline.md` as
a ~10-line agent-definition file that delegates to the framework
command. The vault's `/pipeline` in Claude Code shells out to
`research_vault pipeline <vault>` for each subcommand.

The 410-line feeds-vault `pipeline.md` becomes a vault-local override
(`pipeline.local.md`) for vaults that want the rich orchestrator
prose inline; new vaults get the slim shim.

## Design

### State schema

```json
{
  "$schema": "https://research-framework.local/schemas/pipeline-state-v1.json",
  "run_id": "2026-05-13-1400",
  "started_at": "2026-05-13T14:00:00Z",
  "framework_version": 1,
  "phases": {
    "collect": {
      "status": "done",
      "started_at": "...",
      "finished_at": "...",
      "summary": {"items_new": 23, "by_source": {"rss": 12, "youtube": 3, "reddit": 8}},
      "errors": []
    },
    "extract": {...},
    "scout":   {...},
    "triage":  {"status": "waiting", "started_at": "...", "queue_remaining": 4},
    "research":{"status": "pending"},
    "verify":  {"status": "pending"},
    "report":  {"status": "pending"}
  }
}
```

Phase status: `pending | in_progress | waiting | done | skipped | failed`.

Schema committed at `specs/075-pipeline-runner/contracts/pipeline-state.schema.json` (authored here; moved when this folder was archived, because a tracked file outside `specs/` opens it — #295).

### Phase composition

```python
# research_vault/pipeline/runner.py
PHASE_DRIVERS = {
    "collect":  _drive_collect,    # uses 014 collectors
    "extract":  _drive_extract,    # uses 015f processors
    "scout":    _drive_scout,      # uses 015e scout template + agent_call.py
    "research": _drive_research,   # uses 015e research template + agent_call.py
    "verify":   _drive_verify,     # uses 015f verify processor
    "report":   _drive_report,     # uses 015e report template + agent_call.py
}
```

Each driver:

1. Reads the phase's input contracts from disk.
2. Sequences sub-steps (e.g. `collect` runs each opted-in collector).
3. Writes its outputs to the documented paths.
4. Updates `pipeline-state.json` atomically.

### CLI

```bash
research_vault pipeline <vault> {full|collect|extract|scout|resume|finish|status} [--budget-cap USD] [--quiet]
```

`resume` runs research → verify → report (post-triage). `finish`
is an alias for `verify → report` only (skip research if queue is
empty).

### Backward compat

The current `research_vault cycle <vault>` command:

- v1: keep both. `cycle` = legacy narrow loop. `pipeline` = the new
  full one. Document `cycle` as deprecated in favour of `pipeline
  scout` + `pipeline resume`.
- v2 (later): `cycle` becomes an alias for `pipeline scout +
  resume`. Eventually retired.

## Acceptance

- [ ] `research_vault pipeline <vault> {full|...|status}` works
      end-to-end against a fixture vault.
- [ ] `pipeline-state.json` schema validated by tests.
- [ ] feeds-vault and codebase-vault can run `research_vault pipeline
      … full` after opting into 014 collectors + 015e agents + 015f
      processors. Their pre-existing `_pipeline/pipeline-state.json`
      shapes are migrated to the new schema (one-time auto-migration
      detected by the orchestrator on first run).
- [ ] The vault-local `pipeline.md` slash command is replaced by a
      thin shim (rendered from a framework template per 015e).
- [ ] Existing `research_vault cycle` command continues to work
      unchanged.

## Out of scope

- Parallel phase execution (collectors run sequentially in v1).
- Distributed runs across multiple machines.
- LLM provider abstraction.
- Web UI / dashboard.

## Open questions

- **Where does the cost-budget enforcement live?** Each phase
  driver currently writes a `.cost.json` sidecar via
  `agent_call.py`. The orchestrator can sum them and stop the
  pipeline when the per-run budget is exceeded. Tentative: yes,
  enforce at phase boundaries.
- **How is "triage" represented?** It's a phase but the
  orchestrator never runs it. Tentative: keep it in the state
  schema with status `waiting`, and `resume` flips it to `done`.
- **What happens on phase failure?** Today feeds-vault's
  `pipeline.md` says "continue with the next script" on collect
  failure. Should the framework be stricter? Tentative: per-phase
  failure policy declared in the spec (`processors.collect.on_error:
  continue | abort`).
