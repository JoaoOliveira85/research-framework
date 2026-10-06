---
_template_version: 1
---
# source-rich-quality-fixture — AGENTS.md

Layer 1 routing index. Agents read this file first to locate content.

## Folder Structure

- `data_vault/01 - Services/` — Service note
- `data_vault/02 - Flows/` — Flow note
- `data_vault/03 - Concepts/` — Concept note
- `data_vault/04 - Decisions/` — Decision note

## Topic Index

_(populated after Phase 2 by `update_vault.py reindex`)_

## Data Sources Consulted

Ordered by priority. Code is source-of-truth for behaviour; Confluence/Jira are
consulted for intent.

- official-docs (external, priority 1, role behaviour)
- oreilly-shelf (external, priority 1, role behaviour)
- github-org (code, priority 1, role behaviour)
- arxiv-feed (external, priority 2, role behaviour)
- confluence-space (external, priority 2, role behaviour)
