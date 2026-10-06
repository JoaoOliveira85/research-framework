---
description: "Research and add a new note to the tech-lite-quality-fixture vault."
argument-hint: "<topic or claim>"
_template_version: 1
---

# /research — Research and add a note

You are adding a new note to the **tech-lite-quality-fixture** vault. Read `CLAUDE.md`
first for the quality bar, note-inclusion criteria, and note-type rules.

## Topic

$ARGUMENTS

## Discover → expand → write

1. **Check for duplicates**: scan `data_vault/_index.md` and `AGENTS.md`. If a
   note already exists, *update it* — do not create a duplicate (Principle VI).
2. **Determine the note type** from `CLAUDE.md`. The type selects the template
   in `_templates/<type>.md` and fixes the required frontmatter + sections.
   Read that template BEFORE writing.
3. **Source-first discovery**:
   - For every note type marked `source_policy: hard` in the spec (defaults:
     `service`, `flow`, `concept`, `decision`), the note's `source_urls` MUST
     contain at least one entry classified as `[code]` (repository URL or
     `file://` path matching the vault's `code_source_url_patterns`).
   - Start in the authoritative source (code for `hard` types, primary
     data-source for `soft` types). Extract facts from there first, then
     enrich with secondary sources (intent + domain).
4. **Drift awareness**: if the note covers something where code behaviour and
   stated intent can disagree (e.g. a service with both a repo and a Confluence
   page), populate both `## Current Behaviour` and `## Stated Intent`. When
   they disagree on a specific fact (retry count, timeout, owner, enum value),
   set `intent_implementation_drift: true` in frontmatter and record:

   ```yaml
   drift_notes:
     - fact: retries
       code_value: "3"
       intent_value: "5"
       source_code: file://<repo>/<path>
       source_intent: <intent-source-url>
   ```

## Pre-write checklist

Before writing, verify:

- [ ] Type is declared; the template's required sections are all present.
- [ ] Frontmatter has `title`, `type`, `summary` (≤120 chars, specific), `tags`,
      `created`, `updated`, `status`, `source_urls` (≥1), `related`,
      `confidence`, `scope`, `template_version`.
- [ ] For `hard` types: at least one `source_urls` entry is `[code]`-classified
      per the vault's `code_source_url_patterns`.
- [ ] First occurrence of every acronym in the body is wikilinked.
- [ ] Word count ≥ type's `min_word_count`.
- [ ] `related` is populated from wikilinks in the body.

## Post-write validation

After writing the note, run the vault's bundled validators:

```
./update_vault.py validate
```

This runs `check_template_compliance.py`, `check_code_source_coverage.py`,
`check_intent_drift.py`, and `validate_vault.py`. If any reports a violation on
your new note, fix it before the next cycle — the Phase 3 gate blocks on these.

## What you do NOT do

- Do NOT skip the source walk for `hard` types to save time. A note that cites
  only secondary (intent / domain) sources for a hard type is REJECTED.
- Do NOT silently pick intent over code when they disagree. Flag drift
  explicitly.
- Do NOT write notes on topics outside the spec's scope (see `CLAUDE.md` —
  Scope and Out of Scope).
