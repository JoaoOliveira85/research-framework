---
_template_version: 2
---
You are running BFS scout cycle {CYCLE_NUM} of a recursive research pass on the
source-rich-quality-fixture vault.

Domain: Curated high-quality sources with comfortable coverage targets for source-quality-pruning regression (FR-011).
Organization: Synthetic fixture

## Required reading (before any action)

1. `CLAUDE.md` — vault conventions, frontmatter schema, note-inclusion criteria,
   quality bar. This is authoritative; where it conflicts with anything else, it wins.
2. `AGENTS.md` — Layer 1 routing index. Topic index + folder map.
3. `_pipeline/vault-metrics.json` — current vault state (note counts, unresolved
   references). Use this to decide what's NEW vs. already covered.
4. `_pipeline/research-backlog.md` — pending topics from prior cycles. Two
   independent managed blocks may appear here:
   - **Harvest — cycle N** (Phase 1, `topic_harvest.py`): HIGH priority.
     Bullets are missing wikilink targets that were already cited from
     notes in the vault, plus unmet coverage-target categories. Treat as
     near-certain follow-ons and pull them into this cycle aggressively.
   - **Proposed tangents — cycle N (agent)** (Phase 2, `topic_propose.py`):
     LOWER priority, advisory. Bullets carrying a `⚠️` marker were accepted
     but flagged as `scope_check: warn` — review them and only include
     the ones that clearly fit scope. If you're over budget or already
     have a full cycle's worth of work, skip this block entirely.

## Your job

Scan all available data sources for NEW topics not yet covered in the vault.
Required data sources — each MUST be consulted or explicitly skipped with a reason:

- **official-docs** (external) — Curated official documentation
- **oreilly-shelf** (external) — Curated O'Reilly excerpts
- **arxiv-feed** (external) — Curated arXiv feed
- **github-org** (code) — Curated GitHub organization
- **confluence-space** (external) — Curated Confluence space


Search dimensions (all five must be addressed):

- **technical**
- **organizational**
- **domain**



Check CLAUDE.md's note-inclusion criteria. A topic warrants a note if ANY apply:
- Referenced 2+ times across different notes
- Directly queryable by a user
- Appears in a system diagram or data/decision flow
- Upstream/downstream dependency
- Sub-concept with distinct behaviour

When in doubt, list it. Filenames follow the spec's naming convention: `full_name`.

## Output

Write the JSON report to: `{SCOUT_REPORT}`

The report MUST follow this exact schema (no extra commentary, JSON only):

```json
{
  "cycle": {CYCLE_NUM},
  "phase": "scout",
  "timestamp": "<ISO-8601 timestamp>",
  "prompt": "<short recap of this prompt>",
  "sources_consulted": {
    "official_docs": {"searched": true|false, "results_count": N},
    "oreilly_shelf": {"searched": true|false, "results_count": N},
    "arxiv_feed": {"searched": true|false, "results_count": N},
    "github_org": {"searched": true|false, "results_count": N},
    "confluence_space": {"searched": true|false, "results_count": N}
  },
  "topics_found": {
    "new": ["<topic title>", "..."],
    "existing": ["<already-covered topic>", "..."],
    "total": <int>
  },
  "proposed_filenames": ["<Topic Title>.md", "..."],
  "notes_created": [],
  "notes_updated": [],
  "new_wikilinks_discovered": ["<unresolved term from scan>"],
  "cost_estimate_usd": <float>,
  "cumulative_cost_usd": <float>,
  "budget_consumed_usd": <float>,
  "next_action": "continue" | "terminate",
  "termination_reason": null | "no_new_topics" | "budget_cap" | "max_cycles"
}
```

Constraints:

- `sources_consulted` MUST include every required source key above.
- `proposed_filenames` MUST NOT collide with any existing file under `data_vault/`.
- For each optional source skipped, provide a `reason`.
- Do NOT write any vault notes in this phase — scout only.
- Do NOT self-assess validation. A separate script reads this JSON and decides CONTINUE/TERMINATE.

Output ONLY the JSON file at the path above. Do not print the JSON to stdout.
