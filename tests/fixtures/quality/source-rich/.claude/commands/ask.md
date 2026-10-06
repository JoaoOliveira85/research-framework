---
description: "Query the source-rich-quality-fixture vault. Vault-first answer with two-tier citations."
argument-hint: "<question>"
_template_version: 1
---

# /ask — Query the vault

You are answering a user's question using the **source-rich-quality-fixture** vault as the
source of truth. Read `AGENTS.md` first, then navigate via
`data_vault/_index.md` and `data_vault/_concepts.md`.

## Question

$ARGUMENTS

## Answer structure

1. Resolve the question against `data_vault/` notes only. Follow the `related`
   frontmatter field and in-body wikilinks to traverse the graph. Do not invent
   facts that are not present in the vault.
2. **Every claim** in the answer MUST be backed by at least one vault note
   (Tier 1). A claim without a vault citation is invalid regardless of how
   plausible it sounds — say "the vault does not cover this" instead.
3. When a note's frontmatter carries `intent_implementation_drift: true`, your
   response MUST explicitly name the disagreement. Quote both sides from the
   note's `drift_notes` entries — do not silently pick one.
4. When an asserted fact has only an `intent`-classified source and no
   `code`-classified source, flag it:
   > *Note: this claim is sourced from intent (Confluence / Jira / Slack) only;
   > the underlying code was not consulted or the behaviour has not been
   > verified against the repository.*

## Citation format (Principle IX — Vault-First Citation)

Every answer MUST end with a two-tier citation block. Tier 1 (Vault Sources)
is the primary citation; Tier 2 (Original Sources) de-references the Tier 1
notes' `source_urls` frontmatter.

```
Vault Sources:
[1] data_vault/<folder>/<note-a>.md — Accessed YYYY-MM-DD
[2] data_vault/<folder>/<note-b>.md — Accessed YYYY-MM-DD

Original Sources:
[a] <url from note-a's source_urls> — [code | intent | domain]
[b] <url from note-b's source_urls> — [code | intent | domain]
```

Classification tags:

- **`[code]`** — repository URL (GitHub/GitLab/Bitbucket/`file://`). Authoritative
  for *how* the system behaves.
- **`[intent]`** — Confluence, Jira, Slack, M365, or equivalent internal doc.
  Describes *why* something exists.
- **`[domain]`** — any other external URL (market data, industry reports,
  academic paper).

Order Tier 2 with `[code]` first for behavioural questions, `[domain]` /
`[intent]` first for context / strategic questions.

## Research Escalation

If the vault does not contain enough grounded information to answer a
question and the topic is within the vault's declared scope:

1. Check the vault scope in `CLAUDE.md` — confirm the topic is in scope.
2. If in scope, run a focused research cycle before answering:
   ```bash
   research-framework cycle --vault . --cycle 1 --target-topics "<topic>" --budget-cap 2.0
   ```
3. After the cycle completes, re-read the relevant vault notes and answer.
4. If the research finds no suitable sources, say so explicitly rather than
   answering from memory or fabricating citations.

Do NOT escalate for topics explicitly out of scope — state the boundary instead.

## What you do NOT do

- Do NOT form opinions or recommend a course of action — surface what the
  vault contains and where it is silent.
- Do NOT fetch from external systems. Answer from the vault only; flag gaps.
- Do NOT bury Tier 2 citations inside Tier 1 prose. Render them as distinct
  sections.
