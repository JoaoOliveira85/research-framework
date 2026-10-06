---
_template_version: 1
---
# source-rich-quality-fixture — CLAUDE.md

**Owner**: research-framework-tests
**Naming convention**: full_name
**Domain**: Curated high-quality sources with comfortable coverage targets for source-quality-pruning regression (FR-011).
**Organization**: Synthetic fixture

This is the agent entry point for the source-rich-quality-fixture vault. Read this file before any
research, write, or validation work. It declares the vault's scope, quality bar, note
types, and data sources.

## Scope

- In scope: Official docs, papers, and org repos
- Out of scope: Low-signal scraper feeds

## Coverage Categories

Every note you write MUST carry a `coverage_category: <slug>` frontmatter key
pointing at EXACTLY ONE of the slugs below. This is how the orchestrator tracks
progress against scope — without it, the fallback classifier has to guess, which
spreads notes unevenly and exits the loop early.

Pick the category whose description best matches the note's primary contribution
(a single note can touch several scope items, but it should be *filed* under one).

- **`services`** (target: 4 service notes)- **`flows`** (target: 3 flow notes)- **`concepts`** (target: 3 concept notes)- **`decisions`** (target: 2 decision notes)- **`integrations`** (target: 2 service notes)
## Quality Bar

Every note MUST satisfy:

- Follows the template section structure for its type (read `_templates/{type}.md`)
- 200+ words (non-MOC notes)
- Answers type-specific contextual questions (why/how/who)
- All acronyms wikilinked on first occurrence in body
- At least one source URL in frontmatter
- `summary` ≤ 120 chars and specific
- `related` field populated from wikilinks in body
- Filename matches proposed_filenames from scout JSONFor note types with `source_policy: hard` (service, flow, concept, decision), at
least one `source_urls` entry MUST point at a code location (`https://github.com/...`
or `file://.../<enumerated-repo>/...`).
## Note Types

### service

**Folder**: `01 - Services/`
**Min word count**: 60
**Source policy**: hard (≥1 code source URL required)
Service note

**Required sections**:
- `## Overview`
- `## API Surface`
- `## Dependencies`
- `## Related`
**Contextual questions**:
### flow

**Folder**: `02 - Flows/`
**Min word count**: 60
**Source policy**: hard (≥1 code source URL required)
Flow note

**Required sections**:
- `## Overview`
- `## Trigger`
- `## Steps`
- `## Failure Modes`
- `## Related`
**Contextual questions**:
### concept

**Folder**: `03 - Concepts/`
**Min word count**: 60
**Source policy**: hard (≥1 code source URL required)
Concept note

**Required sections**:
- `## Overview`
- `## Mechanism`
- `## Trade-offs`
- `## Related`
**Contextual questions**:
### decision

**Folder**: `04 - Decisions/`
**Min word count**: 60
**Source policy**: hard (≥1 code source URL required)
Decision note

**Required sections**:
- `## Context`
- `## Decision`
- `## Consequences`
- `## Related`
**Contextual questions**:

## Data Sources

Ordered by priority (1 = primary). Code is the authoritative source of truth for
behaviour; intent sources are consulted only to supplement code topics.

- **official-docs** (external, priority 1, role **behaviour**): Curated official documentation — REQUIRED- **oreilly-shelf** (external, priority 1, role **behaviour**): Curated O'Reilly excerpts — REQUIRED- **github-org** (code, priority 1, role **behaviour**): Curated GitHub organization — REQUIRED- **arxiv-feed** (external, priority 2, role **behaviour**): Curated arXiv feed — REQUIRED- **confluence-space** (external, priority 2, role **behaviour**): Curated Confluence space — REQUIRED
## Search Dimensions

All BFS scout passes must cover:

- technical
- organizational
- domain

## Contextual Questions (all notes)

## Autonomous Operation

This vault is configured for autonomous operation. Proceed without asking
for confirmation when:
- Running research cycles, validation, health checks, or audit
- Reading or writing files under `data_vault/`, `_pipeline/`, `raw_data/`
- Fetching URLs for source health checks or raw data capture
- Committing changes to git (with appropriate commit messages)

Always ask before:
- Deleting any note from `data_vault/`
- Pushing to a git remote
- Spending more than `40.0` USD in a single session
- Making changes outside the vault root directory

## Citation Format

When citing sources, classify each URL and order them:

1. `[code]` — `file://.../<enumerated-repo>/...`
2. `[intent]` — intent-source URLs (Confluence, Jira, Slack, etc.)
3. `[domain]` — any other external URL (market research, industry reports)

For notes where `intent_implementation_drift: true` in frontmatter, responses MUST
name the disagreement explicitly ("code says X; intent says Y") rather than picking
one silently.