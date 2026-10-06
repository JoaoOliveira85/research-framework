# Feature Specification: First-Class Note Type Taxonomies

**Feature Branch**: `015d-note-types-first-class` *(proposal — not yet branched)*
**Parent**: [015 — Pipeline Consolidation](../015-pipeline-consolidation/spec.md), Stage 2
**Created**: 2026-05-13
**Status**: planned — Draft

## Problem

[Lesson 11](../013-vault-migrator/lessons-learned.md#11-simple-spec-note-type-expansion-is-thinner-than-real-vaults-need)
observed that real vaults use 10+ note types each, while the simple
spec format expands to exactly two (`concept`, `source`):

| Vault | Distinct note types observed |
|---|---|
| feeds-vault | concept, source, company, person, issue, opportunity, trend, deep-dive, learning, society/culture, future/philosophy, tool-guide (~12) |
| codebase-vault | concept, service, flow, product, team, decision, risk, process, market, source (10) |

The two-note-types-by-default expansion was fine when the migrator
never touched `data_vault/`, because the existing vault structure
survived untouched. But [015 Stages 3-4](../015-pipeline-consolidation/spec.md)
will render agent definitions and orchestrator prompts from the spec.
Agents that need to know *"a Service note lives in `02 - Services/`
and requires sections X, Y, Z"* cannot answer from the simple spec.

Today the user's options are:

1. Use the simple spec, then manually create the richer folder
   structure + templates after scaffolding. (What both real vaults
   did.)
2. Use the detailed spec format (`parser.parse()`), which **does**
   support `note_types` blocks — but is framed as "power users
   only" in `examples/research.spec.md` and in the simple spec's
   module docstring.

Neither is great. The simple format is too thin; the detailed format
is too friction-laden for first use.

## Goals

1. **Real vaults can declare their full note-type taxonomy in their
   spec without leaving the friendly format.** A 10-type taxonomy
   should be expressible in ~20 lines of YAML, not 200.
2. **The detailed format becomes the de-facto default.** New vaults
   use it; the simple format remains as the bootstrap convenience
   for "I just want to play with the framework".
3. **Backward compat.** Existing simple-spec vaults (feeds-vault,
   codebase-vault, the examples) keep working with no edits.
4. **The expander stays opinionated.** When a user declares 12 note
   types in their spec, the framework still picks sensible defaults
   for cycle budgets, coverage targets, source ordering, etc.
   — the user shouldn't have to think about those.

## Non-goals

- **Not** a rewrite of the spec format. Both `parser.py` (detailed)
  and `simple.py` keep working; the change is in framing,
  documentation, and a small extension to the simple expander.
- **Not** dynamic note types. The note-type taxonomy is declared
  once in the spec and re-used across the vault's lifetime.
  Changing it = edit spec + re-scaffold relevant templates.
- **Not** validation of the corpus against the taxonomy. The
  migrator never touches `data_vault/`; if a vault contains notes
  in folders not declared in the spec, that's the user's affair.
  ([015b inventory](../015b-vault-inventory/spec.md) may surface
  the mismatch as a warning.)

## User scenarios

### Story 1 — Declare a richer taxonomy in the simple spec

```yaml
name: "Legal Research Vault"
owner: "..."
topic: |
  ...

note_types:
  - case          # folder: 01 - Cases/
  - statute       # folder: 02 - Statutes/
  - opinion       # folder: 03 - Opinions/
  - jurisdiction  # folder: 04 - Jurisdictions/
  - source        # folder: 10 - Sources/
```

The expander generates folder names automatically (`<NN> - <Type>s/`
with auto-numbering), pulls a default frontmatter shape, and creates
matching `_templates/<type>.md` files. The user can override any
default by promoting to the long form:

```yaml
note_types:
  - case
  - name: opinion
    folder: "Opinions"            # custom path
    required_sections:
      - "Holding"
      - "Reasoning"
      - "Dissent (if any)"
    contextual_questions:
      - "Which jurisdiction?"
      - "What's the precedential weight?"
  - statute
  - source
```

Short form and long form coexist in the same list — short is a
string, long is a mapping. The expander normalises both to the
detailed `NoteType` dataclass.

### Story 2 — Existing simple-spec vault unchanged

```yaml
name: "Macro Photography on Analog Film"
owner: "jdoe"
topic: |
  ...
# (no `note_types:` block — same as today's example)
```

The expander uses today's default (`concept` + `source`) when
`note_types` is absent. The example spec at
`examples/research.spec.md` stays unchanged.

### Story 3 — Detailed format reframed as the default

`examples/research.spec.md` keeps the friendly format but adds a
prominent pointer to `examples/detailed.spec.md` (new) for the
"declare everything explicitly" path. Module docstrings in both
parsers are updated to reflect that:

- `simple.py`: "the minimum spec — auto-expands everything you don't
  declare".
- `parser.py`: "the explicit spec — declare every field you care
  about; the simple format is sugar over this".

## Design

### Simple-spec extension

Extend `SimpleSpec` with an optional `note_types: list[str | dict]`
field. The expander (`simple.expand`):

- For each string entry → `NoteType(name=s, folder=f"{i:02d} - {s.title()}s")`
  with auto-incrementing `i` starting at the next number after the
  highest folder index found.
- For each dict entry → `NoteType(**entry)`. Validate required
  fields (`name`).
- If `note_types` is absent or empty → today's default (`concept` +
  `source`).
- Auto-generate `_templates/<type>.md` files for each declared
  note type, using a generic skeleton (frontmatter + the
  `required_sections` as headings).

### Detailed-spec parity

The detailed format already supports `note_types` fully — nothing to
change in `parser.py` beyond the docstring.

### Migrator implications

The migrator currently doesn't render note-type-specific files (it
just ships `_templates/CHANGELOG.md` + `_templates/concept.md`).
After this lands:

- The generator scaffolds one `_templates/<type>.md` per declared
  type (already user-owned per the manifest's
  `_templates/` patterns).
- The manifest's `_templates/concept.md` entry is replaced by a
  loop over `spec.note_types` at manifest-build time. The manifest
  becomes per-vault for the templates section — fine, since these
  are user-owned and never re-rendered.

### `_templates/<type>.md` skeleton

```markdown
---
type: {{ type.name }}
title: ""
tags: []
created: YYYY-MM-DD
updated: YYYY-MM-DD
status: draft
summary: ""
related: []
source_urls: []
confidence: high | medium | low
_template_version: 1
---

# {{ type.name | title }}: <title>

{% for section in type.required_sections %}
## {{ section }}

{% endfor %}
```

User can edit; the framework never overwrites (per [Rule 7](../013-vault-migrator/lessons-learned.md)).

## Acceptance

- [ ] Simple spec accepts `note_types: [str | dict]` and expands
      correctly.
- [ ] Test: simple spec with 10 string entries produces 10 NoteType
      objects with auto-numbered folders.
- [ ] Test: simple spec mixing string and dict entries normalises
      both to NoteType.
- [ ] Test: simple spec with no `note_types` block still expands to
      the historical default (`concept` + `source`).
- [ ] Test: scaffold writes `_templates/<type>.md` per declared note
      type.
- [ ] `examples/research.spec.md` updated to document the
      `note_types` block (without breaking its existing run).
- [ ] [Lesson 11](../013-vault-migrator/lessons-learned.md) annotated
      "resolved by 015d" on landing.
- [ ] feeds-vault and codebase-vault specs updated (separate PR — they
      can adopt the richer taxonomy if desired but are not
      required to).

## Out of scope

- LLM-driven note-type inference from existing prose.
- Renaming an existing note-type's folder after the fact (still a
  manual `git mv` + spec edit, same as the corpus folder).
- Validation that every note in the corpus has a frontmatter `type`
  matching the declared taxonomy. That's an inventory/lint concern,
  not a spec concern.

## Open questions

- **Folder naming convention.** `<NN> - <Type>s/` is what both real
  vaults use, but it's arbitrary. Should the framework leave the
  folder name to the user explicitly (dict form only) instead of
  auto-generating from the type name? Tentative: auto-generate for
  the string form (zero-friction); accept any explicit `folder:` in
  dict form (escape hatch).
- **Pluralisation.** `case` → `Cases/`? `opinion` → `Opinions/`?
  Naive `+ "s"` works for English but fails on `process` →
  `Process` (not "Processs"). Tentative: a tiny pluraliser handling
  the common English cases (`-y` → `-ies`, `-s/x/ch/sh` → `-es`),
  override via dict form.
