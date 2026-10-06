---
description: "Generate a document from the source-poor-quality-fixture vault into output/."
argument-hint: "<document spec path OR plain-language instructions>"
_template_version: 1
---

# /write — Generate a document from the vault

You are producing a document (report, summary, memo, briefing, …) whose
source material comes exclusively from the **source-poor-quality-fixture** vault. The
output lands in `output/` at the vault root — never inside `data_vault/` and
never outside the vault.

## Input

$ARGUMENTS

If `$ARGUMENTS` is a path to a `document-spec.md` file, read and obey that
spec (title, audience, sections, length, tone). Otherwise treat the raw string
as the instructions and infer structure.

## Build plan

1. **Plan** — enumerate the sections the document needs. For each section,
   list the vault notes (by path) that will back it. If any section has zero
   backing notes, surface that gap BEFORE writing — do not fabricate coverage.
2. **Draft** — write each section using only claims traceable to the planned
   notes. Maintain the same two-tier citation rule as `/ask`:
   every paragraph's factual claims cite at least one vault note (Tier 1).
3. **Verify** — before saving, confirm:
   - Every cited Tier 1 note exists in `data_vault/` and has at least one
     `source_urls` entry of its own (Tier 2) — that is the precondition for
     citing it. A vault note with zero Tier 2 sources cannot legally appear in
     Tier 1.
   - The document carries an explicit `## Vault Sources` section AND an
     explicit `## Original Sources` section at the end (Principle IX —
     two-tier rendering MUST be visible, never buried inline).

## Output location

Save the finished document to:

```
output/{{ slug }}-{{ YYYYMMDD }}.md
```

where `slug` is derived from the document's working title (kebab-case, ASCII).
If a file with the same name already exists, append `-v2`, `-v3`, … — never
overwrite a prior output.

## What you do NOT do

- Do NOT pull facts from outside the vault. The vault is the authority; if it
  lacks a section's material, note the gap.
- Do NOT drop citations to "clean up" the prose. The citations ARE the value.
- Do NOT write into `data_vault/` — use `/research` for that.
- Do NOT overwrite existing output files; version them.
