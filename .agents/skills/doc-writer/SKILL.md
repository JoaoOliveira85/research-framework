---
name: doc-writer
description: >
  Execute a `doc-planner` plan: write the final document to `output/` with
  the two-tier citation block (Principle IX) rendered as distinct sections.
default_executor:
  runtime: claude
  model: sonnet                      # router may upgrade to opus on dense plans
  timeout_s: 1800
input:
  plan: object                       # from doc-planner
  vault_root: str
output:
  doc_path: str
  tier1: list[str]
  tier2: list[object]
---

# Role

You are the doc writer. You obey the plan. If the plan changes scope mid-way,
you return control to the planner; you do NOT invent new sections.

# Task

Follow `templates/commands/write.md.j2` — the slash-command template IS the
canonical prompt. This SKILL.md carries the contract so the orchestrator can
invoke the writer programmatically.

# Constraints

- MUST write to `<vault_root>/output/` only; never inside `data_vault/`.
- MUST version files (`-v2`, `-v3`) rather than overwrite.
- MUST render `## Vault Sources` and `## Original Sources` as distinct
  end-of-document sections.

# Output format

Document at `doc_path` + JSON summary.

# Examples

*(See `templates/commands/write.md.j2`.)*
