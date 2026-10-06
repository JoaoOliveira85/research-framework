# Feature Specification: Agent Definitions as Framework Templates

**Feature Branch**: `015e-agent-definitions-as-templates` *(proposal — not yet branched)*
**Parent**: [015 — Pipeline Consolidation](../015-pipeline-consolidation/spec.md), Stage 3
**Created**: 2026-05-13
**Status**: planned — Draft

## Problem

Today, the `.claude/commands/*.md` agent definitions live as
**user-owned** files per [Rule 7](../013-vault-migrator/lessons-learned.md).
The framework seeds three (`ask.md`, `research.md`, `write.md`) on
fresh scaffold; everything else (`scout.md`, `verify.md`, `report.md`,
`extract.md`, `pipeline.md`) is
purely vault-local.

This is the right tradeoff for v0 — losing vault customisations
costs more than missing a few generic improvements. But it has a
serious long-term consequence:

**Lessons learned in one vault can't propagate to others without
manual port.** When the user fixes a bug in feeds-vault's `research.md`,
codebase-vault doesn't get it. When a new evaluation rule is
discovered, every vault has to be edited.

The framework should provide:

1. A **template** for each generic agent (scout, research, verify,
   report, extract, pipeline) that knows how to render against
   a vault's spec.
2. A **regenerate-on-demand** path so users can opt in to upstream
   improvements: "I changed nothing locally — pull the latest
   framework version of `research.md`".
3. A **`.local.md` override mechanism** so per-vault deviations
   coexist with framework updates without forking.

This is the core unlock for "research hardware lives in the
framework" — once agents are framework-owned templates, lessons
cross-pollinate automatically.

## Goals

1. **Each generic agent has a framework template.** Initially:
   `scout`, `research`, `verify`, `report`, `extract`, `pipeline`.
   Plus the seeded `ask` and `write`.
2. **Templates render from the spec.** They use `spec.note_types`,
   `spec.vault_corpus_dir`, `spec.data_sources`, etc. — the values
   that vary per vault.
3. **Local overrides exist and are honoured.** Claude Code already
   resolves slash commands by name from `.claude/commands/`; we
   layer an override convention on top.
4. **Regeneration is explicit.** `research_vault regenerate-agents
   <vault> [--agent NAME]` re-renders one or all agents.

## Non-goals

- **Not** a runtime DSL for agents. Templates are Jinja2; the agent
  body is otherwise the same agent-definition-with-frontmatter we
  already use.
- **Not** automatic LLM-driven prompt improvement. Updates land
  through explicit framework changes + the user choosing to
  regenerate.
- **Not** forcing every vault to migrate. Vaults can keep using
  their hand-rolled agents indefinitely; opt-in is per-agent via
  `regenerate-agents`.

## User scenarios

### Story 1 — New vault inherits framework agents

`research_vault generate --spec my-vault.md` writes:

```
.claude/commands/
  ask.md         # rendered from framework template
  research.md
  write.md
  scout.md
  extract.md
  verify.md
  report.md
  pipeline.md
```

Each carries a `_template_version` in frontmatter and the
agent-definition shape feeds-vault already uses. The vault works
out-of-the-box without per-vault customisation.

### Story 2 — User customises one agent

The user hand-edits `.claude/commands/research.md` to tighten the
research procedure for their domain. They run a `migrate apply`;
the framework leaves `research.md` alone (per [Rule 7](../013-vault-migrator/lessons-learned.md)).

Subsequently, the framework ships an improved scout template. The
user runs:

```bash
research_vault regenerate-agents ~/Documents/my-vault --agent scout
```

`scout.md` is re-rendered from the new template. `research.md` is
untouched. The user gets the upstream improvement without losing
their local edit.

### Story 3 — Override coexists with framework template

The user wants a slightly different `research.md` for one vault
but doesn't want to fork it entirely. They write
`.claude/commands/research.local.md`. Claude Code resolves
`/research` against the `.local.md` first if present, else against
`.md`.

```
.claude/commands/research.md         # framework-rendered
.claude/commands/research.local.md   # per-vault override (takes precedence)
```

The user can regenerate `research.md` whenever; their `.local.md`
is never touched.

## Design

### Template structure

```
research_vault/agents/
  scout.md.j2
  research.md.j2
  verify.md.j2
  report.md.j2
  extract.md.j2
  pipeline.md.j2
  ask.md.j2
  write.md.j2
```

Each Jinja2 template renders to a complete agent-definition file
with frontmatter + body. The template's context is the full
`SpecConfig` plus a few helpers (`note_types_table`,
`corpus_dir_for_type(name)`, etc.).

### Variables every template can use

- `spec.name` — vault display name
- `spec.owner` — owner
- `spec.vault_corpus_dir` — corpus folder name
- `spec.note_types` — list of NoteType
- `spec.data_sources` — list of declared sources
- `spec.scope_include`, `spec.scope_exclude` — scope bullets
- `note_type_for_topic(topic_shape) -> NoteType` — the
  shape→type mapping table used in research.md's "decide note
  type" step

### Rendering rules

- On `research_vault generate`, every agent template renders into
  `<vault>/.claude/commands/<name>.md`. Marked user-owned in the
  manifest (today's behaviour for `ask`, `research`, `write` —
  extends to all generic agents).
- On `research_vault migrate apply`, framework templates **do
  not** re-render existing agent files. The user's local copy
  wins. (Rule 7.)
- On `research_vault regenerate-agents <vault> [--agent NAME]`,
  the specified agents are re-rendered, overwriting the local
  copies. This is destructive and explicit — the command warns
  before overwriting unless `--force`.

### Override mechanism

For each agent `<name>`, Claude Code conventionally resolves
`/<name>` against `.claude/commands/<name>.md`. We add the
convention that if `.claude/commands/<name>.local.md` exists, it
wins. **Implementation note:** Claude Code currently doesn't
honour this automatically — we'd need either (a) to ask Anthropic
to add it, or (b) the `<name>.md` file itself to delegate:

```markdown
---
description: "<vault-specific>"
---

{% if local_override_exists %}
Read .claude/commands/<name>.local.md and execute that procedure
verbatim. The framework default has been overridden for this vault.
{% else %}
<framework default body>
{% endif %}
```

That's ugly. Probably the better route is to require the user to
*delete* the `<name>.md` file when they want full local control —
Claude Code won't find a framework default if there's only a
`.local.md`. Open question (see below).

### CLI

```bash
research_vault regenerate-agents <vault> [--agent NAME ...] [--force]
```

- No `--agent` → regenerates **all** agents (after `--force`
  confirmation).
- `--agent scout --agent verify` → regenerates just those two.
- `--force` → skip the per-file confirm prompt.

## Acceptance

- [ ] Eight agent templates (`scout`, `research`, `verify`,
      `report`, `extract`, `pipeline`, `ask`, `write`) committed
      under `research_vault/agents/`.
- [ ] `research_vault generate` writes all eight to a fresh vault.
- [ ] `research_vault regenerate-agents` works end-to-end.
- [ ] feeds-vault and codebase-vault can opt-in to the framework
      versions (manual one-time `regenerate-agents --agent ...`).
- [ ] Test: a fresh vault generated with the new templates passes
      a sanity check that each rendered agent file has the right
      frontmatter shape.
- [ ] [Lesson 7](../013-vault-migrator/lessons-learned.md)
      annotated: still applies — `_USER_OWNED_PATTERNS` continues
      to include `.claude/commands/*.md`; the new `regenerate-agents`
      command is the framework's explicit channel to override
      user-owned files when the user asks for it.

## Out of scope

- Plugin agents (third-party templates outside the framework).
- Per-folder slash-command scopes.
- The override mechanism's actual Claude Code support — design the
  convention now; pursue platform integration later.

## Open questions

- **Override mechanism**: `.local.md` vs. "delete the framework
  copy" vs. an upstream feature request to Anthropic. The first
  iteration of this spec will likely go with "delete the framework
  copy and write your own" — simplest, no magic.
- **Template versioning**: should each `*.md.j2` carry a
  framework-side version that the rendered output stamps as
  `_template_version`? Probably yes — lets `regenerate-agents`
  detect "your render is at v3, framework now ships v5" and
  surface the option.
- **What's the contract between agents?** scout produces a radar
  that research consumes; research produces notes that verify
  consumes. Today this is encoded prose in each agent. Worth a
  separate sub-spec to formalise the cross-agent contracts as
  JSON Schemas (`Topic Radar shape`, `Note frontmatter shape`,
  `Verify report shape`).
