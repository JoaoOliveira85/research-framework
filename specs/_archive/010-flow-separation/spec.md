# Spec 010 — Flow Separation & Active Maintenance

**Status**: superseded(by spec 023)

> **🗄️ SUBSUMED BY spec 023 (2026-05-22).** Spec 023 (Flow Separation
> + ./vault refactor + local module integration) is the active home
> for this scope — it folds 010 + 012 + four 2026-05-20 triage items
> (#4/#5/#24/#25, captured at `docs/TODO.md#restoration-notes`). Do
> NOT plan against 010 directly; open `specs/023-flow-separation/spec.md`
> instead. This file is kept as a design-history reference (the
> earlier framing of "flow separation" is still useful context for
> 023's design decisions).
>
> **Vision spec.** This is a design-intent document, not an implementation
> plan. Acceptance criteria are provisional. Do not start implementation
> until a tasks.md is written with full detail.

## Problem Statement

The three vault flows — research, maintenance, and querying — are currently
co-located and coupled:

- Research logic lives in `cycle_runner.py` / `orchestrator.py`, but
  validation scripts (a maintenance concern) are called inside the cycle
- Maintenance is passive: validators report problems but fix nothing
- Querying is just command templates — there is no structured query flow,
  no escalation wiring, no three-mode dispatch

As the system grows, this coupling will make it harder to:
- Run maintenance independently (without triggering research)
- Deploy different flows on different schedules or hardware
- Replace one flow's LLM without touching the others

Additionally, the maintenance flow is under-powered. It should close the
loop: detect problems → fix what's fixable → queue the rest for research.

## Proposed Solution

### Research flow (clarification, not a rewrite)

Already well-defined via `cycle_runner.py`. The change here is extraction:
research logic should not call maintenance scripts as a side effect. The
post-DFS validation suite (Step 4 in the cycle) stays, but its output feeds
`_pipeline/maintenance-queue.json` rather than being discarded. Maintenance
reads this queue; research does not read maintenance state.

### Maintenance flow (active, three-tier)

A new `scripts/vault_maintain.py` (also callable via `./vault maintain`):

**Tier 1 — Detect:** run all validators, `vault_health.py`. Collect issues.

**Tier 2 — Fix (deterministic):** auto-repair what is unambiguous:
- Easy wikilinks: `[[Acronym]]` that resolves to an existing note with a
  known alias → rewrite to canonical form
- Template gaps: add missing required sections with placeholder text
  (marks them as stubs for the research queue, not as valid content)
- Acronym links: apply `fix_acronym_links.py --apply` where safe

**Tier 3 — Queue (research handoff):** items that can't be auto-fixed are
written to `_pipeline/maintenance-queue.json` with structured entries:
```json
{
  "type": "stub",
  "path": "data_vault/01 - Concepts/Foo.md",
  "reason": "body < 200 words",
  "suggested_action": "expand"
}
```
`topic_harvest.py` (already running in the cycle) reads from this queue and
includes these items in the backlog, so the next research cycle picks them up.

### Query flow (three modes, unified escalation)

All three modes share the same escalation logic:
1. **Vault-first**: search existing notes for grounding
2. **Escalate if insufficient AND in-scope**: call `./vault research --target <topic>`
3. **Surface source gap if sources don't cover it**: feed into `sources.db`

Modes differ in output and dialogue:

| Mode | Trigger | Output | Dialogue |
|------|---------|--------|----------|
| Conversational | `/ask` command | Inline answer | Yes — follow-ups |
| Document | `/write` command | File | No — blocking |
| Agent/MCP | `.claude/commands/` or MCP | Structured | None |

The `/ask` and `/write` command templates already handle mode A and B
structurally. What they lack is the escalation wiring — calling research
scripts when vault content is insufficient. This is specified in spec 005
(query escalation section) and does not require flow separation to land.

Mode C (agent/MCP) is the current default via `.claude/commands/`. An MCP
server wrapping the vault is a separate future item.

### Independence contract

Flows communicate via files, never via Python imports across flow boundaries:

```
Research → writes: research reports, scout reports, harvest manifests
Maintenance → reads: research reports; writes: maintenance-queue.json
Query → reads: data_vault/, _pipeline/; writes: nothing (read-only)
Source manager → read/write: sources.db (shared, owned by no single flow)
```

## Non-Goals

- Rewriting the existing research cycle machinery — extraction, not rewrite
- A formal plugin system or dependency injection — flat-file interfaces are
  sufficient for flow independence
- MCP server for the vault (separate future spec)

## Technical Design (high-level)

### New file: `scripts/vault_maintain.py`

```
usage: vault_maintain.py <vault_dir> [--detect-only] [--fix] [--queue]
                         [--dry-run]

--detect-only   run validators only, no fixes, no queue writes
--fix           apply deterministic fixes (default: dry-run)
--queue         write unfixable issues to maintenance-queue.json
--dry-run       show what would be done without writing anything
```

### New file: `_pipeline/maintenance-queue.json`

Structured list of issues that research should address. Read by
`topic_harvest.py` in addition to its existing wikilink and coverage-gap
signals. Schema:

```json
[
  {
    "type": "stub | broken_link | missing_source | template_gap",
    "path": "data_vault/...",
    "reason": "human-readable",
    "suggested_action": "expand | link | source | fill",
    "queued_cycle": 3
  }
]
```

### `topic_harvest.py` change

Read `_pipeline/maintenance-queue.json` and include its entries as
follow-up candidates (deduped against existing backlog entries).

### Research cycle change

Remove validation scripts from the Step 4 "report-only" suite that are
better suited to maintenance (template compliance, acronym links). Keep:
validate_vault.py, check_intent_drift.py, check_code_source_coverage.py
— these are research-cycle concerns. Move to maintenance-only:
check_template_compliance.py, check_acronym_links.py.

## Provisional Acceptance Criteria

1. `./vault maintain --detect-only` produces a list of issues without
   modifying any files
2. `./vault maintain --fix --queue` repairs deterministic issues and writes
   unfixable ones to `maintenance-queue.json`
3. The next research cycle after `--queue` includes maintenance-queued items
   in the scout's `target_topics`
4. A research cycle does not call `check_template_compliance.py` or
   `check_acronym_links.py` — these are maintenance-only
5. Flow interfaces are file-only: no Python import from `maintenance.*` in
   `cycle_runner.py` or vice versa

## Constraints to Preserve Until This Ships

- Don't add cross-flow Python imports — keep the interfaces as files
- Don't call maintenance scripts inside the research cycle's critical path
  (current Step 4 is acceptable as a transitional state)
- `_pipeline/maintenance-queue.json` format must be stable from the moment
  it is introduced — `topic_harvest.py` and `vault_maintain.py` both read it
