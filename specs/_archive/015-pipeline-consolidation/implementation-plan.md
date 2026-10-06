# 015 Implementation Plan — Analysis Before Execution

**Status:** Draft for user review. **No code yet.**
**Created:** 2026-05-13
**Parent:** [015 — Pipeline Consolidation](./spec.md)

## What this document is

The seven sub-specs (014, 015d-h, 016) describe **what** to build. This
document covers **how to sequence the build** — task decomposition,
dependencies, risks, and recommended execution model — before any
implementation begins.

When this plan is approved, each task gets its own bite-sized
implementation plan via the `writing-plans` skill, then is executed
via subagent-driven development. This document is the analysis layer
above those per-task plans.

## Tasks (mirrored in TaskCreate / TaskList)

| ID  | Sub-spec                                          | Blocks                         | Blocked by              |
|-----|---------------------------------------------------|--------------------------------|-------------------------|
| #37 | S2-014   RSS collector                            | S4b-015g, S5-015h              | —                       |
| #38 | S2-015d  Note types first-class                   | S3-015e                        | —                       |
| #39 | S3-015e  Agent definitions as templates           | S4b-015g                       | S2-015d                 |
| #40 | S4a-015f Processors in framework                  | S4b-015g, S5-015h              | —                       |
| #41 | S4b-015g Pipeline orchestrator command            | S6-016                         | S2-014, S3-015e, S4a-015f |
| #42 | S5-015h  Retire vault-local scripts               | S6-016                         | S2-014, S4a-015f        |
| #43 | S6-016   Reference-vault rebuild                       | —                              | S4b-015g, S5-015h       |

## Dependency graph

```
 #37 014 RSS  ─────┬─────────────────┐
                   │                 │
                   ▼                 ▼
 #38 015d   ──► #39 015e ─────► #41 015g ──┐
 note types     agents          pipeline   │
                                           ▼
                                       #43 016
                                           ▲
 #40 015f   ─────────┐                     │
 processors          │                     │
                     ▼                     │
                #42 015h ──────────────────┘
                prune
```

**Reading the graph:**

- `#38 → #39 → #41` is the longest critical path. Note types must
  exist before agents can be rendered (they reference
  `spec.note_types`); agents must exist before the orchestrator can
  invoke them.
- `#37` and `#40` are independent of the agent chain and can be
  parallelised with it.
- `#41` is the convergence point — orchestrator command needs
  collectors, agents, and processors in place to compose them.
- `#42` (prune) needs the modules that supersede the local scripts
  (#37, #40) but doesn't strictly need the orchestrator.
- `#43` (reference-vault rebuild) is the final validation — everything
  must be in place for it to be a meaningful end-to-end test.

## Recommended execution order

Two reasonable orderings:

### Option A — strict topological order (one task at a time)

```
#38 → #39 → #37 → #40 → #41 → #42 → #43
```

7 sequential tasks. Slow but minimises in-flight complexity.

### Option B — parallel where the graph allows (RECOMMENDED)

```
Wave 1 (parallel):   #37   #38   #40
Wave 2 (parallel):         #39
Wave 3 (parallel):   #41         #42
Wave 4:              #43
```

Wave 1 has zero shared state — three independent module additions.
Wave 2 is one task. Wave 3 has two independent tasks (orchestrator
and prune touch different code paths). Wave 4 is validation.

Subagent-driven execution makes Option B cheap: each wave's tasks
go to separate fresh subagents in parallel, controller verifies
each, then proceeds. Realistic total: 4 "waves" of subagent
dispatch rather than 7 sequential ones.

## Per-task notes — scope, risks, model selection

### #37 — 014 RSS collector module (Stage 2)

**Scope.** Promote `_fetch`, `_sources`, `_frontmatter`, `_dedupe`
helpers + an `rss` collector module from feeds-vault's `collect_rss.py`
(962 lines, but ~30-50% is the reusable plumbing).

**Risks:**
- The feeds-vault `collect_rss.py` has 962 lines of accumulated
  edge-case handling (paywall detection, date parsing variants,
  RSS-vs-Atom routing). Faithful porting matters; "clean rewrite"
  would lose battle-tested behaviour.
- Tests need fixtures with synthetic RSS + Atom feeds.

**Dispatch:** subagent (sonnet) with the feeds-vault script as
reference; ~1 hour. Don't have the subagent invent — port.

**Acceptance gate:** running the new module against the same RSS
feeds the feeds-vault script polls produces the same set of items
(modulo timestamps).

---

### #38 — 015d note types first-class (Stage 2)

**Scope.** Extend `SimpleSpec.note_types` to accept short
(`["case", "statute"]`) and long-form mappings; expander generates
folder names + `_templates/<type>.md` per declared type. Detailed
parser already supports this; mostly a simple-spec extension.

**Risks:**
- Backward compat for existing specs with no `note_types:` block
  (default to today's `concept` + `source`).
- Folder auto-numbering: `01 - Cases/`, `02 - Statutes/` — naive
  pluralisation might surprise users. Tentative: pluralise English
  endings, accept explicit `folder:` in long form.

**Dispatch:** subagent (sonnet) with the 015d spec as the brief.
Small enough to ship in one pass.

**Acceptance gate:** simple spec with 10 string note types expands
to 10 NoteType objects with auto-numbered folders + 10
`_templates/*.md` files; existing specs unaffected.

---

### #39 — 015e agent definitions as templates (Stage 3)

**Scope.** Eight Jinja2 templates under `research_vault/agents/`,
each rendering a complete agent-definition file. New
`research_vault regenerate-agents <vault>` subcommand.

**Risks:**
- This is the **largest** task. Eight templates × ~150-300 lines
  each ≈ 1500-2400 lines of Jinja2. Each template needs to know
  what context variables it consumes from `spec`.
- The override mechanism (`.local.md`) needs documentation if not
  full implementation — Claude Code doesn't natively honour it.
  v1 will document the "delete the framework copy" pattern.
- Risk of templating away meaningful prose. Resist over-DRYing;
  these are human-readable agent definitions, not config files.

**Dispatch:** **split into 8 sub-tasks**, one subagent per agent
template. Each subagent's brief is: "take feeds-vault's `<name>.md`
as the reference, parameterise the per-vault values
(`spec.name`, `spec.note_types`, etc.), commit." Then a final
subagent wires the `regenerate-agents` CLI.

**Acceptance gate:** generating a vault from a fresh spec produces
eight agent files; renderered output matches feeds-vault's surviving
agents in structure (not in detail) for the corresponding agents.

---

### #40 — 015f processors in framework (Stage 4a)

**Scope.** Four processor modules (`extract`, `preprocess`,
`verify`, `archive`) under `research_vault/processors/`. Stable
CLI + Python API. `raw-item.schema.json` contract.

**Risks:**
- Same as #37 — the feeds-vault scripts have accumulated nuance over
  hundreds of edits. Faithful port > clean rewrite.
- `verify.py` is 842 lines and exercises both Haiku and Sonnet —
  cost-sensitive. Mock the LLM calls in tests; real LLM calls only
  in opt-in integration tests.

**Dispatch:** subagent **per processor module** in parallel — they
share helper conventions (`_common.py`) but not logic. ~1 hour
each.

**Acceptance gate:** running each processor against the
corresponding feeds-vault `_pipeline/raw/` or
`_pipeline/extracted/` fixture produces output equivalent (modulo
timestamps and non-determinism) to the feeds-vault script.

---

### #41 — 015g pipeline orchestrator command (Stage 4b)

**Scope.** `research_vault pipeline <vault> {full | collect |
extract | scout | resume | finish | status}`. State schema +
phase drivers + atomic state updates + cost-budget enforcement at
phase boundaries.

**Risks:**
- This is the **integration** task — composes #37/#39/#40. Bugs
  surface here that the unit-tested sub-modules didn't catch.
- The state schema's stability matters. Future-incompatible
  changes break every vault. Get it right in v1 — use Pydantic or
  attrs with strict validation.
- Existing `research_vault cycle` continues to work. Don't break it.

**Dispatch:** single subagent (opus or sonnet — judgment call), or
split into "state schema + status command" then "phase drivers"
then "full/resume composition" if it gets too big. Start with one
subagent and see; promote to split if it returns CONCERNS.

**Acceptance gate:** `research_vault pipeline <vault> full`
runs end-to-end against a fresh fixture vault with mocked LLM
calls; state JSON validates against schema.

---

### #42 — 015h retire vault-local scripts (Stage 5)

**Scope.** `_SUPERSEDED_BY` map. New `research_vault prune <vault>`
subcommand (sub-question per spec: separate command vs.
`migrate --prune`; spec leans toward separate). Inventory grows
`pruneable` section. Snapshot boundary captures deletions.

**Risks:**
- Destructive operation. Pre-snapshot must `git add -f` the
  files-to-be-deleted so HEAD~N rollback restores them.
- False positives in the `_SUPERSEDED_BY` map. Need explicit
  versioning policy: a path enters the map only after the
  superseding module has been validated against ≥1 real vault.
- User edits to a local script before pruning. Need a "show diff
  vs. the framework default" pre-prune check.

**Dispatch:** single subagent (sonnet). Tight scope.

**Acceptance gate:** feeds-vault and codebase-vault prune cleanly;
their `pipeline status` passes afterwards.

---

### #43 — 016 reference-vault rebuild (validation)

**Scope.** Greenfield reference-vault from spec → `research_vault
pipeline … full` → confirm pure-framework operation.

**Risks:**
- This is **operational**, not implementation. The user runs it;
  the framework supports it. Any rough edge that surfaces is a
  fix-PR against the corresponding sub-spec, not new code in #43
  itself.

**Dispatch:** controller-driven (not a subagent task). Interactive
with the user: draft spec, run commands, observe, file issues,
iterate.

**Acceptance gate:** the reference-vault's `inventory` shows zero
user-added scripts and zero user-customised slash commands; one
full pipeline cycle completes without manual intervention beyond
spec editing and triage.

## Cross-cutting concerns

### Tests

Every wave must keep `pytest tests/` green. Subagents should run
the full suite before reporting DONE; the controller verifies
before moving to the next wave.

The test fixture vault `tests/fixtures/vault/_pipeline/health-report.md`
gets a fresh timestamp every test run. **Recommend (separate small
PR before starting):** either gitignore it or stabilise the
timestamp at write-time. Otherwise every commit during this work
will need a `git restore` step.

### Costs

- Subagent dispatches for #37, #40 are sonnet, ~$0.50-1.00 each
  including the per-processor splits (4 subagents).
- #39 split into 8 agent-template subagents — biggest cost block,
  ~$3-5 total. Use sonnet for each.
- #41 is the most complex; sonnet probably, opus if results
  disappoint.
- #42 is small.
- #43 is real-world operation; cost is whatever the pipeline run
  itself costs (~$3-7 per the SYSTEM_SPEC.md estimate).

Total framework-implementation subagent cost rough estimate: $8-15.

### Risks not in any single sub-spec

1. **Migration debt on feeds-vault and codebase-vault.** As each
   framework module ships, the user has to opt the existing
   vaults in. That's their choice and pace; the framework
   shouldn't force it. But the prune step (#42) only validates
   on opted-in vaults.
2. **Claude Code platform coupling.** The agent templates + slash
   command shim assume Claude Code's slash-command resolution.
   If the user wants headless / CI runs, they go through
   `scripts/agent_call.py` (already exists, already supports
   `--stage`). #41's orchestrator should support both paths.
3. **Manifest growth.** After 015e + 015f land, the manifest will
   include 8+ agent template renderings + processor entry-point
   stubs (probably). Manifest may grow from 34 to ~50 entries.
   Keep build_scaffold_manifest.py performant; nothing else to do.

### Definition of done for "015 fully implemented"

- All seven tasks (#37-#43) marked completed in the tracker.
- `research_vault inventory` of a fresh-scaffold vault shows:
  - 0 user-added scripts
  - 0 user-customised slash commands  
  - 11+ note-type templates rendered from spec
- `research_vault pipeline <vault> full` end-to-end works.
- feeds-vault and codebase-vault have opted in to at least one
  framework module each (proves cross-vault propagation works).
- Lessons 7-12 in 013/lessons-learned.md are annotated with
  "resolved by 015X" where applicable.
- Reference-vault rebuild #43 completed.

## User decisions (2026-05-13)

The six open questions from the original draft were resolved as
follows:

1. **Wave 1 parallelism: yes, three in parallel.** Plus the user
   asked: should we use git worktrees so each subagent has its own
   branch we merge back? **Answer: yes.** Worktrees give us free
   isolation and a clean merge boundary. Pattern documented under
   "Worktree-based dispatch" below.
2. **#39 split: yes, eight separate subagents.** Each gets its own
   worktree + branch.
3. **`cycle` deprecation: postpone the decision.** No change to
   `cycle` as part of 015g. `cycle` and `pipeline` coexist; we
   revisit deprecation only if and when redundancy becomes a real
   problem. (No documentation change needed.)
4. **Vault opt-in: in-session, as each feature lands.** Goal is
   feature parity — vaults track the framework rather than
   accumulating "to opt in later" debt. Vault-local modules can
   stay in place per-vault until a framework module supersedes
   them. **Plus: features developed for one vault may be useful
   for others** — the spec-002 code-first scripts
   (`check_intent_drift.py`, `repo_scan.py`, etc.) already live in
   the framework's `scripts/` from the deferred codebase-vault
   rebuild and should be wired into the reference-vault rebuild (#43)
   as an opt-in spec field.
5. **Test fixture stabilisation: yes, but understand the term.**
   "Fixture" = a known-state input that tests run against
   (`tests/fixtures/vault/` = a tiny fake vault). The noisy
   fixture here is `tests/fixtures/vault/_pipeline/health-report.md`
   which gets re-written with `generated: <now>` during the
   vault-health test, polluting `git status` every run. Fix: make
   the test write to a tmp path instead of mutating the fixture
   (option B in the original Q5). Promoted to **Wave 0** below.
6. **#43 (reference-vault rebuild) timing: before pruning.** A new
   vault has nothing to prune, so pruning isn't on the critical
   path. Moving #43 to run after #41 (pipeline orchestrator) and
   in parallel with #42 (prune).

## Revised execution plan

### Wave 0 — preparatory fix

- [ ] **Stabilise `tests/fixtures/vault/_pipeline/health-report.md`.**
      Find the test that writes to it, redirect the write to a
      `tmp_path` instead. ~10 minutes, inline (no subagent).
      Eliminates the per-commit `git restore` dance.

### Wave 1 — three parallel subagents on independent modules

Each runs in its own git worktree against its own branch off
`013-vault-migrator`:

| Task | Worktree                                      | Branch                  |
|------|-----------------------------------------------|-------------------------|
| #37  | `../research-framework.worktrees/wave1-rss`         | `015-impl/014-rss`           |
| #38  | `../research-framework.worktrees/wave1-notetypes`   | `015-impl/015d-note-types`   |
| #40  | `../research-framework.worktrees/wave1-processors`  | `015-impl/015f-processors`   |

Controller:

1. Creates the three worktrees + branches up front.
2. Dispatches three subagents in parallel — one per worktree.
3. Each subagent commits within its worktree, runs the full test
   suite, reports DONE.
4. Controller verifies each worktree's diff + test output.
5. Merges all three branches into `013-vault-migrator` (sequential
   `git merge --no-ff`).
6. **Opts feeds-vault and codebase-vault into the new modules.**
   Documented per-vault: for #37, edit `<vault>/sources.yaml` or
   spec source-list; for #40, add `processors.extract.enabled:
   true` to spec; etc.
7. Runs the full test suite on the merged `013-vault-migrator`
   branch to confirm nothing regressed.

### Wave 2 — eight parallel subagents on agent templates (#39)

Each agent template (`scout`, `research`, `verify`, `report`,
`extract`, `pipeline`, `ask`, `write`) gets its own worktree +
branch:

| Worktree                                            | Branch                         |
|-----------------------------------------------------|--------------------------------|
| `../research-framework.worktrees/wave2-agent-scout`       | `015-impl/015e-scout`            |
| `../research-framework.worktrees/wave2-agent-research`    | `015-impl/015e-research`         |
| `../research-framework.worktrees/wave2-agent-verify`      | `015-impl/015e-verify`           |
| `../research-framework.worktrees/wave2-agent-report`      | `015-impl/015e-report`           |
| `../research-framework.worktrees/wave2-agent-extract`     | `015-impl/015e-extract`          |
| `../research-framework.worktrees/wave2-agent-pipeline`    | `015-impl/015e-pipeline`         |
| `../research-framework.worktrees/wave2-agent-ask`         | `015-impl/015e-ask`              |
| `../research-framework.worktrees/wave2-agent-write`       | `015-impl/015e-write`            |

Each subagent's brief is the same: "take feeds-vault's
`.claude/commands/<name>.md` (where it exists) as reference, port
it as a Jinja2 template under `research_vault/agents/<name>.md.j2`,
parameterise per-vault values from `spec`, commit". One additional
subagent (or controller-inline work) wires the
`regenerate-agents` CLI subcommand once all eight templates exist.

Merge sequence is the same as wave 1 — eight branches merged into
`013-vault-migrator` after verification, then opt feeds-vault and
codebase-vault into the new agent templates via
`research_vault regenerate-agents <vault>`.

### Wave 3 — two parallel subagents (#41 + #42)

| Worktree                                         | Branch                          |
|--------------------------------------------------|---------------------------------|
| `../research-framework.worktrees/wave3-orchestrator`   | `015-impl/015g-orchestrator`        |
| `../research-framework.worktrees/wave3-prune`          | `015-impl/015h-prune`               |

Then opt feeds-vault and codebase-vault into the orchestrator
(replace local `/pipeline` slash with the framework shim), then
prune their now-superseded local scripts.

### Wave 4 — reference-vault rebuild (#43)

Controller-driven, interactive with the user. The user discards
the old reference-vault, drafts a fresh spec, runs `research_vault
generate` → `research_vault pipeline … full`. Each rough edge
encountered files a fix-PR against the relevant 014/015 sub-spec.

**Code-first integration:** the reference-vault spec opts into the
existing 002 code-first scripts via a `code_first:` block:

```yaml
code_first:
  enabled: true
  repos:
    - path: ~/src/some-repo
      role: primary
  intent_drift_threshold: 0.20
```

The pipeline picks this up and invokes `scripts/repo_scan.py`,
`scripts/check_intent_drift.py`, etc. as part of `extract` /
`verify` phases. No new module work needed — the scripts exist;
015g's pipeline command wires them in.

## Worktree-based dispatch — how the controller manages them

Per [superpowers:using-git-worktrees](https://...) (the framework's
own skill for this pattern):

```bash
# Create
git worktree add ../research-framework.worktrees/wave1-rss \
                 -b 015-impl/014-rss 013-vault-migrator

# Dispatch subagent
#   prompt: "Work in /Users/.../research-framework.worktrees/wave1-rss.
#            Implement task #37 per specs/_archive/014-reusable-collectors/spec.md.
#            Commit on branch 015-impl/014-rss. Run pytest in your
#            worktree before reporting DONE."

# Verify
cd ../research-framework.worktrees/wave1-rss
git log --oneline 013-vault-migrator..HEAD          # what changed
pytest tests/ -q                                    # all green?

# Merge back
cd ~/src/research-framework
git merge --no-ff 015-impl/014-rss -m "wave1: merge #37 — 014 RSS collector"

# Clean up after all wave-1 merges land
git worktree remove ../research-framework.worktrees/wave1-rss
git branch -d 015-impl/014-rss
```

The skill's `EnterWorktree` / `ExitWorktree` tooling can automate
the setup/teardown; the controller will use those rather than
shell calls when dispatching.

## Approval

This plan reflects all six user decisions. Ready to execute when
you say go. The first action will be Wave 0 (test fixture fix —
inline, ~10 min) followed by Wave 1 worktree setup + parallel
dispatch.

If anything in the revised plan is wrong, tell me before any
worktrees are created.
