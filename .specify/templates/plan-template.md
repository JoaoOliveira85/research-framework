# Implementation Plan: [FEATURE]

**Branch**: `[###-feature-name]` | **Date**: [DATE] | **Spec**: [link]
**Input**: Feature specification from `/specs/[###-feature-name]/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

[Extract from feature spec: primary requirement + technical approach from research]

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: [e.g., Python 3.11, Swift 5.9, Rust 1.75 or NEEDS CLARIFICATION]  
**Primary Dependencies**: [e.g., FastAPI, UIKit, LLVM or NEEDS CLARIFICATION]  
**Storage**: [if applicable, e.g., PostgreSQL, CoreData, files or N/A]  
**Testing**: [e.g., pytest, XCTest, cargo test or NEEDS CLARIFICATION]  
**Target Platform**: [e.g., Linux server, iOS 15+, WASM or NEEDS CLARIFICATION]
**Project Type**: [e.g., library/cli/web-service/mobile-app/compiler/desktop-app or NEEDS CLARIFICATION]  
**Performance Goals**: [domain-specific, e.g., 1000 req/s, 10k lines/sec, 60 fps or NEEDS CLARIFICATION]  
**Constraints**: [domain-specific, e.g., <200ms p95, <100MB memory, offline-capable or NEEDS CLARIFICATION]  
**Scale/Scope**: [domain-specific, e.g., 10k users, 1M LOC, 50 screens or NEEDS CLARIFICATION]

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Source: `.specify/memory/constitution.md` **v1.6.0**. Answer every row. `N/A` is a valid
answer **with a reason**; a blank row is not an answer. A `VIOLATION` answer requires a row
in Complexity Tracking below, or the plan does not proceed.

| # | Gate | Answer |
|---|------|--------|
| I | Does every phase transition or cycle boundary this feature adds get validated by a script **whose exit code the caller propagates**? Name the script and the caller. A report-only check is not a gate. | |
| II | Does this preserve strict phase sequencing, and is loop continuation still orchestrator-owned? An agent's `next_action` is advisory and may not drive it. | |
| III | Is there a test for every new behaviour, written before or with the implementation? Does every new vault-mutating script take `--dry-run`, and is it exercised on a fixture before real data? | |
| IV | Do agents only report while scripts validate? Any new LLM dispatch routes through `scripts/agent_call.py` — a direct `claude`/`codex` subprocess fails `tests/_helpers/test_llm_dispatch_guard.py`. | |
| V | Does this run offline on a clean machine? List **every** new dependency and **every** new outbound network call, each with its justification (constitution requires this in the PR description). | |
| VI | Can this produce a second note for one concept? Name the mechanism that prevents it (`proposed_filenames`, `validate_vault.py`, `validate_cycle.py`). | |
| VII | Does this touch source consultation or Condition B? External sources may not be skipped without a logged reason. | |
| VIII | Is every script this feature *lists* also *implemented* by this feature — no `pass` bodies, no bare `TODO`s? Does the run still refuse to declare success while stubs or orphan wikilinks remain? | |
| IX | Does any output this produces *from* a vault carry Tier-1 (vault notes) and Tier-2 (external `source_urls`) citations, rendered as distinct sections? | |
| X | Does every vault mutation this adds land as a git commit — right branch, right prefix (`framework: ` / `vault: `), non-fatal on failure? | |
| XI | Does this change a payload another repo reads or writes? If so: name the contract, its version, its schema file in this repo, and the sibling repo's mirrored copy. | |
| XII | Does anything added under a `validate_*`, `check_*`, `verify`, `audit`, `quality_report` or gate name **write** to what it reads? Repair must be a separate, opt-in, operator-invoked verb using the canonical codec. | |
| XIII | Does every flag, settings key or field this feature accepts reach a consumer that changes behaviour — name it — or is it refused with exit 2 until one exists? Does every failure or skip it can record reach stderr at ERROR/WARNING naming the record, `--quiet` notwithstanding? Is a phase "done" by artifact, not by exit code? | |
| XIV | If this feature calls a model, does it work against a self-hosted provider (`settings.ollama.yaml`, or `opencode` with a local provider)? Degraded is acceptable; hosted-only is a violation. Does the local profile still ship in the wheel and the bundle? | |

**Domain-agnosticism** (constitution, "What research-framework Is NOT"): does any canonical
schema, prompt, or structural decision here hardcode one domain's vocabulary — typically
web/backend, since that is what built the framework? Few-shot examples may; canonical
schemas must be derivable from the spec at runtime.

**Immutable Architecture Decisions**: does this revisit the two-layer vault, BFS→DFS→repeat,
the five search dimensions, coverage-targets-as-Phase-3-gate, or the 0/1/2 exit-code model?
If yes, **stop** — an ADR comes first (`CONTRIBUTING.md` §6).

**Enforcement honesty**: if this plan claims to enforce a principle, say which artifact
fails when the invariant is breached, and whether it is reached by
`scripts/guards/run_all.py` or `pytest -m "not e2e"` (the local merge gate), only by the
`e2e` tier or `build.sh`, or only by a human checklist. There is no PR-triggered CI; `ci.yml`
re-runs the local battery on version tags and manual dispatch. Adding a guard script that
nothing calls does not change the § Enforcement Register.

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)
<!--
  ACTION REQUIRED: Replace the placeholder tree below with the concrete layout
  for this feature. Delete unused options and expand the chosen structure with
  real paths (e.g., apps/admin, packages/something). The delivered plan must
  not include Option labels.
-->

```text
# [REMOVE IF UNUSED] Option 1: Single project (DEFAULT)
src/
├── models/
├── services/
├── cli/
└── lib/

tests/
├── contract/
├── integration/
└── unit/

# [REMOVE IF UNUSED] Option 2: Web application (when "frontend" + "backend" detected)
backend/
├── src/
│   ├── models/
│   ├── services/
│   └── api/
└── tests/

frontend/
├── src/
│   ├── components/
│   ├── pages/
│   └── services/
└── tests/

# [REMOVE IF UNUSED] Option 3: Mobile + API (when "iOS/Android" detected)
api/
└── [same as backend above]

ios/ or android/
└── [platform-specific structure: feature modules, UI flows, platform tests]
```

**Structure Decision**: [Document the selected structure and reference the real
directories captured above]

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
