---
_template_version: 1
---
# tech-lite-quality-fixture — AGENTS.md

Layer 1 routing index. Agents read this file first to locate content.

## Folder Structure

- `data_vault/01 - Services/` — Microservice boundary and responsibilities
- `data_vault/02 - Flows/` — End-to-end messaging or HTTP flow
- `data_vault/03 - Concepts/` — Reusable engineering concept
- `data_vault/04 - Decisions/` — Architecture decision record

## Topic Index

_(populated after Phase 2 by `update_vault.py reindex`)_

## Data Sources Consulted

Ordered by priority. Code is source-of-truth for behaviour; Confluence/Jira are
consulted for intent.

- payment-repo (code, priority 1, role behaviour)
- order-repo (code, priority 1, role behaviour)
