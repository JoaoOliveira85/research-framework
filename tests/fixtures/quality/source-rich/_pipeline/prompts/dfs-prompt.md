---
_template_version: 1
---
You are running DFS research cycle {CYCLE_NUM} of a recursive research pass on the
source-rich-quality-fixture vault.

Domain: Curated high-quality sources with comfortable coverage targets for source-quality-pruning regression (FR-011).
Organization: Synthetic fixture

## Required reading (before any action)

1. `CLAUDE.md` — vault conventions, frontmatter schema, note quality bar.
2. `AGENTS.md` — Layer 1 routing index.
3. The scout report at `{SCOUT_REPORT}` — this contains `topics_found.new` and
   `proposed_filenames`. The research below must cover those topics.
4. `_templates/{type}.md` for each note type you plan to write. The template's
   section headings are MANDATORY.

## Your job

For each topic in `topics_found.new` from the scout report, create or deepen vault
notes with full research. Apply the note-inclusion criteria and quality bar strictly.

### Quality bar (every note must satisfy)

- Frontmatter: `title`, `type`, `summary` (≤ 120 chars, specific not vague), `tags`,
  `source_urls` (≥ 1), `related` (populated from wikilinks in body), `created`,
  `updated`, `template_version` (copy verbatim from the `_templates/{type}.md`
  frontmatter — this is how `scripts/vault_health.py --check-template-version`
  detects notes that need upgrading when a template changes),
  `coverage_category` (exactly one slug from the Coverage Categories table in
  `CLAUDE.md` — this is what the pipeline counts to decide when the vault is
  "done", so do not leave it blank and do not invent new slugs).
- Body: ≥ 200 words (non-MOC notes).
- Answers the type-specific contextual questions (see `_templates/{type}.md` header).
- Every acronym wikilinked `[[ACRONYM]]` on first occurrence in the body.
- At least one wikilink to another vault note.
- States the "so what" — why this matters.
- Self-contained: makes sense without the scout prompt context.

### Note types available (current template versions)

- **service** (01 - Services/) v1.0.0: Service note
- **flow** (02 - Flows/) v1.0.0: Flow note
- **concept** (03 - Concepts/) v1.0.0: Concept note
- **decision** (04 - Decisions/) v1.0.0: Decision note

### Coverage categories (STAMP EACH NOTE WITH EXACTLY ONE)

Write the matching slug into the note's `coverage_category` frontmatter field.
If the scout report's `coverage_assignments` block already pairs a proposed
filename with a slug, USE THAT — don't reassign. Otherwise pick the slug whose
description best matches the note's primary contribution.

- **`services`** (target: 4 service
  notes)- **`flows`** (target: 3 flow
  notes)- **`concepts`** (target: 3 concept
  notes)- **`decisions`** (target: 2 decision
  notes)- **`integrations`** (target: 2 service
  notes)
Always stamp notes with the template version from this list (also present in
the frontmatter of the matching `_templates/{type}.md`). Never invent a
version string.

### Data sources

Cite sources in frontmatter `source_urls` with URL, title, accessed date. Use the
same sources the scout consulted.

**Before adding any http(s) URL to `source_urls`, run:**

```bash
python scripts/raw_capture.py "<url>" --vault . --source-type <article|paper|video|…>
```

This mirrors the payload into `raw_data/{year}/{month}/…` with a `meta.json`
sidecar. If the capture fails (exit 1), still add the URL but log the failure
in the cycle report's `capture_failures` field — ``vault_health.py`` will fall
back to archive.org next time.

- **official-docs** (external)
- **oreilly-shelf** (external)
- **arxiv-feed** (external)
- **github-org** (code)
- **confluence-space** (external)

### Naming

Filenames MUST match the scout's `proposed_filenames` entry (convention: `full_name`).
If you need to create a note NOT in proposed_filenames, that is a coordination
violation — skip it and report it in `new_wikilinks_discovered` for the next cycle.

## Output

Write the JSON report to: `{RESEARCH_REPORT}`

Same schema as the scout report but with:
- `phase`: `"research"`
- `notes_created`: filenames of notes written this phase
- `notes_updated`: filenames of existing notes deepened this phase
- `topics_found.new`: normally empty after research (only populate if genuinely new
  topics were discovered during deep research that weren't in the scout's list)
- `budget_consumed_usd`: total $ spent so far in this run; if the model can't
  measure cost directly, mirror `cumulative_cost_usd` (both are accepted by the
  validator since v0.2.25, but emitting the canonical `budget_consumed_usd`
  alias keeps reports aligned with the v2 schema contract)
- `termination_condition`: ONE of `null` (continue), `"A"` (max cycles reached),
  `"B"` (no new relevant topics after research), or `"C"` (budget cap reached).
  This is the canonical field the validator reads. The legacy
  `next_action` + `termination_reason` shape is still accepted with a
  deprecation warning, but will be removed in 0.3.0 — emit
  `termination_condition` going forward.

```json
{
  "schema_version": "2.0",
  "cycle": {CYCLE_NUM},
  "phase": "research",
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
    "new": [],
    "existing": ["<topic researched>", "..."],
    "total": <int>
  },
  "notes_created": ["<path/to/Note Name.md>", "..."],
  "notes_updated": [],
  "new_wikilinks_discovered": [],
  "cost_estimate_usd": <float>,
  "cumulative_cost_usd": <float>,
  "budget_consumed_usd": <float>,
  "termination_condition": null | "A" | "B" | "C"
}
```

Constraints:

- Write notes directly to `data_vault/{folder}/` per note type.
- Do NOT modify any note's `type` field once created.
- Do NOT duplicate existing notes — check before writing.
- Do NOT self-assess validation. A separate script reads this JSON + runs
  `validate_vault.py` / `check_template_compliance.py` / `check_acronym_links.py`.
  If any of them fail, the cycle aborts.

Output ONLY the JSON file at the path above.
