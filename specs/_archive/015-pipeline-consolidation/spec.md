# Feature Specification: Pipeline Consolidation — Research Loop in the Framework

> **🗄️ PARTIALLY SUBSUMED BY ADR-0009 + spec 020 (2026-05-26).** The
> source-ingestion + orchestrator portions of this umbrella are
> superseded by the 020 source-module architecture and the spec 023
> minimum subset (`./vault refresh-sources`). The other 015a-h
> sub-specs cover orthogonal concerns:
>
> | Sub-spec | Disposition |
> |---|---|
> | `015a-corpus-folder-name` | Orthogonal — corpus folder naming convention; future spec/ADR |
> | `015b-vault-inventory` | Orthogonal — `vault inventory` CLI verb (spec itself uses the pre-rename `research_vault` prefix; separate doc-drift); future work |
> | `015c-vault-onboarding` | Likely absorbed by spec 023 (flow separation) |
> | `015d-note-types-first-class` | Orthogonal — note type taxonomies; future spec |
> | `015e-agent-definitions-as-templates` | Orthogonal — prompt templating; future spec |
> | `015f-processors-in-framework` | ✅ Already shipped (per `migration/superseded_paths.py`) — header doc-drift filed as TODO follow-up |
> | `015g-pipeline-orchestrator-command` | 🗄️ Subsumed by ADR-0009 (tombstoned separately) |
> | `015h-retire-vault-local-scripts` | ✅ Already shipped (per `migration/superseded_paths.py`) — header doc-drift filed as TODO follow-up |
>
> Do NOT plan against 015 as a whole; pick the right sub-spec OR the
> active spec for that concern (020 / 023 / TBD). This file is kept
> as design-history.

**Feature Branch**: `015-pipeline-consolidation` *(umbrella — partially subsumed)*
**Created**: 2026-05-13
**Updated**: 2026-05-13 (after the codebase-vault pass + cross-vault lessons) · 2026-05-26 (clarified per ADR-0009)
**Status**: superseded(by ADR-0009, spec 020) — 🗄️ PARTIALLY SUBSUMED BY ADR-0009 + spec 020 (2026-05-26). See banner above for sub-spec disposition.
**Input**: User direction during the feeds-vault migrator recovery:
> "if the goal is to, eventually, move the research cycles to outside the
> vault I think we should take a moment to realize that the scaffolding
> of the research should be project agnostic and only working details
> should reside inside the vault. … I want to have a research flow and
> pipeline that can evolve as I use and expand the vaults so that lessons
> learned from one vault can be shared to the other vaults research
> flows."

## Premise

A vault has two kinds of content:

| | What | Lives in |
|---|---|---|
| **Corpus** | the notes, sources, indices the vault is *about* | `data_vault/` (per-vault, git-tracked) |
| **Spec** | what the vault researches, how, with what guardrails | `<vault>-spec.md` + `_pipeline/spec-parse.json` (per-vault) |
| **Working state** | run-time artefacts of pipeline runs | `_pipeline/raw/`, `_pipeline/extracted/`, `_pipeline/logs/`, `_pipeline/exports/` (per-vault, mostly ephemeral) |
| **Research hardware** | the *how* — collectors, extractors, agent definitions, orchestrator | currently **inside the vault**; should be in the framework |

The first three are per-vault. The fourth is project-agnostic — every
vault built on this framework runs essentially the same research loop
(collect → extract → scout → triage → research → verify → report) with
per-vault variation supplied by the spec. Today each vault carries its
own copy of the research hardware, which means:

1. **Lessons don't cross-pollinate.** A bug fix or quality improvement
   discovered while running feeds-vault stays in feeds-vault until the user
   manually ports it to codebase-vault.
2. **Drift accumulates.** Two vaults that started from the same
   template will diverge in non-trivial ways within months. The
   migrator can't reconcile this because the agent definitions are
   per-vault user content (and rightly so under [Rule 7](../013-vault-migrator/lessons-learned.md)).
3. **New vaults inherit nothing.** Starting a fresh vault means
   re-writing or copy-pasting the entire research stack.

This proposal describes the destination state and a staged migration
path.

## Destination state

```
research-framework repo                       Each vault
─────────────────────────                     ───────────
src/research_vault/                           data_vault/                <- corpus
  pipeline/                                   <vault>-spec.md            <- spec
    collect/                <- 014           _pipeline/
      rss.py                                    spec-parse.json          <- compiled spec
      youtube.py                                raw/                     <- per-run state
      reddit.py                                 extracted/
      _fetch.py / _sources.py / _frontmatter.py logs/
    extract.py                                  exports/
    scout.py                                  .claude/commands/          <- per-vault overrides
    research.py                                 <name>.local.md         (rare; framework default
    verify.py                                                            renders into <name>.md
    report.py                                                            from the spec)
    pipeline.py             <- orchestrator
  agents/                                     settings.yaml              <- runtime profile
    scout.j2                <- template
    research.j2
    verify.j2
    report.j2
    extract.j2
    pipeline.j2
  prompts/                                    vault-config.yaml          <- vault behaviour
    scout-prompt.j2
    dfs-prompt.j2
```

Concretely:

1. **Collectors** (RSS / YouTube / Reddit / O'Reilly / arXiv / …) live
   as importable Python modules under `research_vault.collectors`.
   Per the 014 proposal; this spec assumes 014 has landed.

2. **Processors** — `extract`, `preprocess`, `verify`, `report` — also
   live as framework modules. They consume per-vault state from
   `<vault>/_pipeline/` and write back into `<vault>/_pipeline/` and
   `<vault>/data_vault/`. They never call across vaults.

3. **Agent definitions** (`.claude/commands/scout.md`, `research.md`,
   etc.) are *templates* in the framework, rendered into each vault
   at scaffold time using the vault's spec. The current feeds-vault's
   `scout.md` hard-codes "newsletters: Import AI, Latent Space, …",
   the source catalogue path, the radar file pattern, the folder
   structure — every one of those values is in the spec already.

4. **Per-vault overrides** are supported via a sibling file
   `.claude/commands/<name>.local.md`: if present, it wins over the
   framework-rendered `.claude/commands/<name>.md`. This is the
   escape hatch for "the framework default is 90% right, but my
   vault needs one section different" without forking the agent.

5. **The orchestrator** (`/pipeline` slash command in feeds-vault today)
   becomes a framework CLI: `research_vault pipeline <subcommand>
   <vault>` — `collect | extract | scout | resume | finish | full | status`.
   It still uses Claude Code under the hood for the LLM phases (via
   `scripts/agent_call.py`, same as the framework's current `cycle`
   command); the difference is the orchestration and the agent
   definitions are framework-owned.

6. **Cross-vault contracts** — the shapes that make this possible:
   - Pipeline state JSON: `_pipeline/pipeline-state.json` with a
     stable schema (currently ad-hoc per feeds-vault).
   - Raw-item shape: every collector emits markdown with the same
     frontmatter (source_kind, source_id, collected_at, original_url,
     content_hash).
   - Context tree shape: `_pipeline/extracted/context-tree.md` with
     a stable schema covering Topics / Strongest Signals /
     Cross-Cutting Themes / Gaps / Cross-Reference Queue.
   - Radar shape: `data_vault/00 - MOC/Topic Radar - <month> <year>.md`
     with stable sections (Tier 1/2/3, Recommended Research Queue,
     Source Cross-Reference, Coverage Gaps).
   - Note shape: the frontmatter quality bar from `SYSTEM_SPEC.md` §8
     (title, type, tags, created, updated, status, summary, related,
     source_urls, confidence, scope, _template_version).

These contracts are what allow the framework to drive multiple vaults
with the same code.

## Why this matters

Three independent forces push in the same direction:

1. **The feeds-vault loss event (2026-05-13).** The migrator overwrote
   three load-bearing agent files because they were framework-owned;
   we then flipped them to user-owned ([Rule 7](../013-vault-migrator/lessons-learned.md)). User-owned
   means "we never touch this again", which means "this vault's agents
   diverge from any other vault's". Acceptable as a stop-gap;
   sub-optimal as a destination.
2. **Two real vaults pending the same migrator pass.** feeds-vault is
   done; codebase-vault is next. Whatever lessons we learn there must
   land somewhere shared.
3. **The third vault is a clean slate.** The user has said the
   reference-vault will be discarded and rebuilt from scratch. It will be
   the first vault to actually exercise the destination state — if
   the framework owns the research loop by then, the reference-vault gets
   it for free.

## Staged migration path

Each stage produces a working framework + working vaults. No stage
requires all the others. The order below reflects what's blocking the
user's **immediate** need (onboard more vaults soon) versus the
longer-term consolidation work.

### Stage 0 — finish 013 (done)

- [x] Migrator works (013).
- [x] Per-vault data files (spec-parse, slash commands) are
      user-owned.
- [x] `parse-spec` CLI for recovery.
- [x] Snapshot boundary captures gitignored framework files.
- [x] Lessons 1-12 in `specs/013/lessons-learned.md` document the
      audit rules for future migrator changes.
- [x] feeds-vault and codebase-vault both migrated cleanly.

### Stage 1 — vault-onboarding ergonomics (CRITICAL PATH for "more vaults soon")

This is the work that pays off **immediately** for the next vault the
user spins up. All three sub-specs below are small, well-scoped, and
unblock multi-vault workflows.

- [ ] **[015a — spec-driven corpus folder name](../015a-corpus-folder-name/spec.md).**
      Today `_validate_vault()` hard-codes `data_vault/`. Real vaults
      use other names (`Codebase Vault/`, `AI Notes/`, …). Move the
      corpus folder name to a spec field; migrator + generator + 014
      collectors all honour it. Eliminates the manual `git mv` step
      from [lesson 8](../013-vault-migrator/lessons-learned.md).
- [ ] **[015b — `research_vault inventory <vault>`](../015b-vault-inventory/spec.md).**
      Read-only subcommand that produces a structured snapshot of a
      vault's scripts / agent definitions / templates / slash
      commands / non-manifest files. JSON output is the input for any
      future cross-vault analysis (and for the human deciding what
      to consolidate into the framework). Scales the audit step we
      did manually across N vaults.
- [ ] **[015c — `research_vault onboard <vault>`](../015c-vault-onboarding/spec.md).**
      One subcommand that runs the uniform recovery flow from
      [lesson 10](../013-vault-migrator/lessons-learned.md): git init
      + seed → corpus rename if needed → draft spec from prose docs
      → parse-spec → assess. The output is a vault ready for
      `migrate apply` with a draft spec the user can edit. Collapses
      ~30 minutes of manual rescue per vault into seconds.

After this stage, onboarding the user's next vault is one command
plus a spec review.

### Stage 2 — first-class detailed spec + reusable collectors

These two unblock 015 Stage 3+ (agents and processors in the
framework).

- [ ] **[015d — note types first-class](../015d-note-types-first-class/spec.md)**.
      The simple spec format expands to only `concept` + `source`;
      real vaults need 10+ types
      ([lesson 11](../013-vault-migrator/lessons-learned.md)). Extend
      `note_types:` in the simple format with short and long forms;
      reframe the detailed format as the de-facto default.
- [ ] **[014 — Reusable collector modules](../014-reusable-collectors/spec.md)**.
      First slice: `rss`. Promote `_fetch` + `_sources` +
      `_frontmatter` shared helpers. Migrate feeds-vault and
      codebase-vault to opt-in.

### Stage 3 — agent definitions as framework templates

- [ ] **[015e — agent definitions as templates](../015e-agent-definitions-as-templates/spec.md)**.
      `scout`, `research`, `verify`, `report`, `extract`,
      `pipeline`, `ask`, `write` ship as Jinja2 templates rendered
      from the spec on `generate`. Files stay user-owned per
      Rule 7; explicit `research_vault regenerate-agents <vault>`
      lets the user opt into upstream improvements. Lessons cross-
      pollinate without forcing per-vault re-edits.

### Stage 4 — processors + orchestrator move into the framework

- [ ] **[015f — processors in the framework](../015f-processors-in-framework/spec.md)**.
      `extract`, `preprocess`, `verify`, `archive` become
      `research_vault.processors.<name>` modules with stable
      Python APIs + CLI entry points. Per-vault behaviour driven
      by spec fields, not source edits.
- [ ] **[015g — pipeline orchestrator command](../015g-pipeline-orchestrator-command/spec.md)**.
      `research_vault pipeline <vault> {full|collect|extract|
      scout|resume|finish|status}` mirrors the feeds-vault's
      `/pipeline` mental model. State schema formalised as
      `_pipeline/pipeline-state.json` (JSON Schema in
      `specs/015g/contracts/`). Vault slash command becomes a
      ~10-line shim.

### Stage 5 — retire vault-local scripts

- [ ] **[015h — retire vault-local scripts](../015h-retire-vault-local-scripts/spec.md)**.
      Once the framework supersedes each script, a `_SUPERSEDED_BY`
      map drives the new `research_vault prune <vault>` subcommand
      (or `migrate apply --prune` flag — see open question).
      feeds-vault and codebase-vault retire their duplicates; future
      vaults never write them.

### Stage 6 — reference-vault rebuild as validation

      Greenfield rebuild of the user's reference-vault using only
      framework primitives. End-to-end validation that the
      consolidated stack works for a new vault without manual
      surgery. The corpus stays small and focused on purpose.

### Stage 1 — inventory + contracts

- [ ] Read the current feeds-vault `.claude/commands/{scout, research,
      extract, verify, report, pipeline}.md` and the codebase-vault
      equivalents. Identify what's per-vault (specific source lists,
      folder names, MOC paths) vs project-agnostic (the algorithm,
      the quality bar, the failure modes).
- [ ] Define the cross-vault contracts (pipeline-state schema, raw-item
      shape, context-tree shape, radar shape, note shape) explicitly.
      These become JSON Schemas under `specs/015/contracts/`.
- [ ] Update `vault-spec-template.md` to require the fields the
      contracts depend on (note types with folder names, source
      catalogue location, MOC naming convention, etc.).

### Stage 2 — extract.py + verify.py + report.py into the framework

- [ ] Promote `~/Documents/feeds-vault/scripts/extract.py` (651 lines)
      to `research_vault.processors.extract`. Reads
      `<vault>/_pipeline/raw/`; writes
      `<vault>/_pipeline/extracted/`.
- [ ] Promote `verify.py` (842 lines) to
      `research_vault.processors.verify`. Reads
      `<vault>/data_vault/`; writes `<vault>/_pipeline/logs/verify-*.md`.
- [ ] Promote `preprocess.py` (307 lines) into
      `research_vault.processors.preprocess` (may roll into extract).
- [ ] Each module exposes `python -m research_vault.processors.<name>
      <vault>` and importable Python API.
- [ ] No agent definition changes in this stage — the vault's slash
      commands continue to shell out to the same script entry points
      (just at the framework path now).

### Stage 3 — agent definitions as framework templates

- [ ] Identify the spec fields needed to render
      `scout.md` / `research.md` / `verify.md` / `report.md` /
      `extract.md` / `pipeline.md` from a generic template. Inputs
      include: source catalogue path, MOC naming pattern, note-type
      → folder mapping, tier definitions, model preferences per stage.
- [ ] Render the six agent files from Jinja2 templates at scaffold
      time. Mark them `is_user_owned_after_first_write: true` so the
      vault keeps the rendered copy, but provide a documented
      `research_vault regenerate-agents <vault>` for when the
      template changes upstream and the vault wants the refresh.
- [ ] Define the `<name>.local.md` override mechanism: if present,
      Claude Code resolves the slash command from there instead of
      `<name>.md`.

### Stage 4 — orchestrator as framework command

- [ ] Implement `research_vault pipeline <subcommand> <vault>` mirroring
      feeds-vault's `/pipeline` modes: `full / collect / extract / scout /
      resume / finish / status`.
- [ ] The pipeline-state schema from Stage 1 is the source of truth.
- [ ] The slash command `.claude/commands/pipeline.md` becomes a thin
      shim that shells out to the framework CLI. The vault never
      contains pipeline orchestration logic again.

### Stage 5 — retire the vault-local scripts

- [ ] After Stages 2-4 ship and both feeds-vault and codebase-vault have
      successfully run a pipeline cycle on the framework versions,
      delete the duplicated scripts from the vaults. The migrator
      can do this because the paths will be in the manifest as
      "managed by the framework, no longer present" — handled by a
      new opt-in `--prune` flag on `migrate apply`.

## Risks and trade-offs

1. **Premature abstraction.** The current feeds-vault scripts work. The
   codebase-vault scripts probably work too. Pulling them into a
   shared framework prematurely risks freezing the wrong abstraction.
   *Mitigation:* Stage 1's contracts inventory is the gate. If the two
   vaults disagree more than they agree, the framework owns the
   contract surface only and per-vault scripts remain.

2. **Latency between vaults.** Pulling codebase-vault's lessons into
   the framework before its scripts are well-exercised would freeze
   bugs into the shared code. *Mitigation:* lessons land as PRs
   reviewed against tests against both vaults' fixtures (or a synthetic
   fixture per stage).

3. **Override-mechanism complexity.** `<name>.local.md` overriding
   `<name>.md` adds a layer Claude Code already handles, but the
   semantics need to be documented and uniformly applied or users
   will be surprised.

4. **Claude Code coupling.** The pipeline depends on Claude Code's
   slash-command resolution for the LLM phases. If we want a CLI
   path that doesn't require Claude Code (for CI runs, headless
   operation), we need to plumb the same agent prompts through
   `scripts/agent_call.py` directly. The framework's current `cycle`
   command already does this for scout/DFS; extending to the full
   pipeline is mechanical.

## Out of scope for this proposal

- A plugin system for third-party collectors / processors / agents.
  Contracts should be designed so plugins are possible in a future
  spec without re-architecting.
- LLM-based collection (research-tool-driven discovery). Today's
  collectors are deterministic fetchers; that's the contract.
- A web UI for triage or status. The pipeline-state schema makes one
  *possible*; building it is a separate spec.
- Cross-vault search/correlation. Each vault still owns its corpus.

## Pre-work — what to do next concretely

1. **Finish the feeds-vault recovery.** Done after [Rule 7](../013-vault-migrator/lessons-learned.md) +
   reconstructed `research.md` in the vault.
2. **Run the migrator pass against `~/Documents/codebase-vault`.**
   Expected to surface a new lesson or two; those go into
   `specs/013-vault-migrator/lessons-learned.md` as rules 8+.
3. **Inventory both vaults' scripts.** Tabulate exact-match vs
   per-vault. The table is Stage 1's primary artefact.
4. **Pick the smallest first promotion.** Likely `_fetch` + `_sources`
   helpers (Stage 0's 014 first slice), since they're trivially
   shared and zero-risk.
5. **Rebuild the reference-vault from scratch** only after Stage 3 ships —
   the reference-vault is the validation harness for "fresh vault inherits
   the framework's research loop".

## Open questions

- How does per-vault customisation of the **research approach itself**
  (not just the agent definition's content) compose? E.g. feeds-vault
  uses adaptive confidence (SYSTEM_SPEC §6); a future legal-research
  vault might need source-of-truth ranking the framework doesn't
  ship. *Tentative answer:* the spec carries optional behaviour
  flags; the framework agents read them; deeply per-vault deviation
  uses the `.local.md` override.
- Does the framework's existing `cycle` command (scout + DFS + harvest)
  retire entirely, or stay as a "headless mode" alternative to the
  `pipeline` command? *Tentative answer:* `cycle` becomes a special
  case of `pipeline scout` + `pipeline resume` — same code path,
  fewer phases.
- Where do the legacy framework-bundled prompts
  (`_pipeline/prompts/scout-prompt.md`, `dfs-prompt.md`) fit once the
  agent definitions are framework-owned templates? *Tentative
  answer:* they're sub-prompts the agent template includes; agents
  reference them by path.

## Acceptance for this proposal

This umbrella spec is **accepted** when:

- [x] Both feeds-vault and codebase-vault have completed their migrator
      pass (Stage 0).
- [ ] Sub-specs 015a / 015b / 015c are drafted and reviewed (Stage 1).
- [ ] At least one sub-spec under Stage 2 is drafted (014 already is;
      015d pending).
- [ ] The user has signed off on the destination state and the staged
      path. Until then this remains a roadmap, not a commitment.

## Note on ad-hoc vs. permanent work

The recovery effort for feeds-vault and codebase-vault (renaming corpus
dirs, hand-drafting specs from prose docs, ad-hoc one-liner Python
scripts to regenerate `spec-parse.json`) is a **one-time necessity** and
must not become a permanent path in the codebase. The session-specific
artefacts (implementation plan doc, /tmp helper scripts) are deleted as
the corresponding work lands.

**What remains:** the framework features that emerged from observing
that recovery — `parse-spec` as a permanent CLI subcommand, the
lessons-learned doc as institutional memory, the manifest's ownership
audit rules — and the roadmap sub-specs that turn the rest of the
recovery flow into proper framework infrastructure. The principle:
*ad-hoc rescue work either becomes a framework command or it gets
deleted*. Nothing in between.
