---
type: agent-definition
agent_name: pipeline
version: "1.0"
updated: "2026-05-21"
audience: ai-primary
owns:
  - "_pipeline/pipeline-state.json"
reads:
  - "_pipeline/raw/**/*.md"
  - "_pipeline/extracted/**/*.md"
  - "_pipeline/logs/**/*.md"
  - "data_vault/AGENTS.md"
  - "CLAUDE.md"
related:
  - path: ".claude/commands/scout.md"
    context: "Phase 3 — produces the radar after triage"
  - path: ".claude/commands/extract.md"
    context: "Phase 2 — extracts raw items into a context tree"
  - path: ".claude/commands/research.md"
    context: "Phase 3 (post-triage) — produces vault notes"
  - path: ".claude/commands/verify.md"
    context: "Phase 4 — quality check"
  - path: ".claude/commands/report.md"
    context: "Phase 5 — weekly briefing"
_template_version: 1
---

# /pipeline — source-rich-quality-fixture Pipeline Orchestrator

This is the entry point for the weekly research pipeline in source-rich-quality-fixture.
It delegates all orchestration to the framework command `research_framework pipeline`,
which sequences collect → extract → scout → [human triage] → research → verify →
report against the vault's spec.

**You are a shim.** For each mode below, shell out to the framework command and
display its output verbatim. Do not reimplement pipeline logic here.

## Modes

| Mode | Framework command | Stops for human? |
|------|-------------------|-----------------|
| `full` | `research_framework pipeline /Users/dev/src/research-framework-022-us3/tests/fixtures/quality/source-rich full` | Yes — after scout |
| `collect` | `research_framework pipeline /Users/dev/src/research-framework-022-us3/tests/fixtures/quality/source-rich collect` | No |
| `extract` | `research_framework pipeline /Users/dev/src/research-framework-022-us3/tests/fixtures/quality/source-rich extract` | No |
| `scout` | `research_framework pipeline /Users/dev/src/research-framework-022-us3/tests/fixtures/quality/source-rich scout` | Yes — at triage |
| `resume` | `research_framework pipeline /Users/dev/src/research-framework-022-us3/tests/fixtures/quality/source-rich resume` | No |
| `finish` | `research_framework pipeline /Users/dev/src/research-framework-022-us3/tests/fixtures/quality/source-rich finish` | No |
| `status` | `research_framework pipeline /Users/dev/src/research-framework-022-us3/tests/fixtures/quality/source-rich status` | No |

### `/pipeline full`

Shell out to:

    research_framework pipeline /Users/dev/src/research-framework-022-us3/tests/fixtures/quality/source-rich full

Print the output verbatim. The framework runs collect → extract → scout in
sequence, then stops with a triage prompt. When ready, run `/pipeline resume`.

### `/pipeline collect`

    research_framework pipeline /Users/dev/src/research-framework-022-us3/tests/fixtures/quality/source-rich collect

Runs Phase 1 collection scripts. No AI involved.

### `/pipeline extract`

    research_framework pipeline /Users/dev/src/research-framework-022-us3/tests/fixtures/quality/source-rich extract

Runs Phase 2 extraction against `_pipeline/raw/`.

### `/pipeline scout`

    research_framework pipeline /Users/dev/src/research-framework-022-us3/tests/fixtures/quality/source-rich scout

Runs Phase 3 scouting from the context tree. Stops at the triage prompt.
Human must review the Topic Radar before running `/pipeline resume`.

### `/pipeline resume`

    research_framework pipeline /Users/dev/src/research-framework-022-us3/tests/fixtures/quality/source-rich resume

Continues after human triage: research → verify → report.

### `/pipeline finish`

    research_framework pipeline /Users/dev/src/research-framework-022-us3/tests/fixtures/quality/source-rich finish

Runs verify → report only (skips research if queue already clear).

### `/pipeline status`

    research_framework pipeline /Users/dev/src/research-framework-022-us3/tests/fixtures/quality/source-rich status

Prints the current `_pipeline/pipeline-state.json` as a structured summary.
Read-only — invokes no agent.

## Why a shim?

The orchestration logic lived inline in this file in earlier vault versions
(~410 lines). It now lives in the framework so improvements propagate to every
vault without manual porting.

To deviate locally from the framework version, create
`.claude/commands/pipeline.local.md` — Claude Code resolves the local override
first. The existing 410-line prose can serve as the body of that local override.

## State file

The framework writes `_pipeline/pipeline-state.json` between phases. Use
`/pipeline status` to inspect it without running anything. To restart from
scratch, delete the state file and run `/pipeline full`.

## Arguments

$ARGUMENTS
