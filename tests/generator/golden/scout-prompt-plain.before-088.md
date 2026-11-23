---
_template_version: N
---
You are running BFS scout cycle {CYCLE_NUM} of a recursive research pass on the
plain vault.

Domain: 
Organization: 

## Required reading (before any action)

1. `CLAUDE.md` — vault conventions, frontmatter schema, note-inclusion criteria,
   quality bar. This is authoritative; where it conflicts with anything else, it wins.
2. `AGENTS.md` — Layer 1 routing index. Topic index + folder map.
3. `_pipeline/vault-metrics.json` — current vault state (note counts, unresolved
   references). Use this to decide what's NEW vs. already covered.
4. `_pipeline/research-backlog.md` — pending topics from prior cycles. It is
   generated from the backlog store and lists only open entries, in these
   sections (a section with nothing open is absent):
   - **Follow-on topics (harvest)**: HIGH priority. Missing wikilink targets
     already cited from notes in the vault, with the notes citing them and
     the cycles they were seen in. Treat as near-certain follow-ons and pull
     them into this cycle aggressively.
   - **Flagged by the researcher**: titles an earlier research pass marked as
     new links worth a note. Worth considering; not yet cited anywhere.
   - **Quarantined notes**: notes whose draft was rejected and quarantined,
     each marked "rewrite the quarantined note" or "retry the refresh
     (previous content restored)". Fixing these is high-value work.
   - **Added by the operator**: topics a person put in the backlog by hand.
     Take these as explicit requests.
   - **Proposed tangents (advisory)**: LOWER priority (`topic_propose.py`).
     Entries carrying a `⚠️` marker were accepted but flagged as
     `scope_check: warn` — review them and only include the ones that
     clearly fit scope. If you're over budget or already have a full cycle's
     worth of work, skip this section entirely.
   - **Carried over from the old backlog**: lines kept verbatim from an older
     backlog format. Read them as hints, not instructions.
   - **Unmet coverage categories**: the coverage-target categories still
     short of their target, required ones marked. Prefer topics that fill
     them.

## Research plan (binding for this cycle)

This cycle's research plan is reproduced at the end of this prompt under
`## Research Plan` (it is also on disk at `_pipeline/research-plan.md`).

- Treat its priority queue as the canonical to-do list for this cycle.
- If it lists cycle focus categories (`## Cycle focus`), then
  at least 70% of your `topics_found.new` entries MUST belong to them.


## Your job

Scan all available data sources for NEW topics not yet covered in the vault.
Required data sources — each MUST be consulted or explicitly skipped with a reason:

- **Always Source** (external)

- *(optional)* **Extra** (external)

Search dimensions (all five must be addressed):


**`proposed_filename`** must follow the vault's `slug`
naming convention and **MUST NOT start with any of these forbidden prefixes**
(SG-003 abstraction gate; failure here will halt the cycle):
- `svc_`
- `srv_`
- `lib_`
- `pkg_`
- `job_`
- `tbl_`
- `tmp_`
- `internal_`

## Resume-run targets

This is a `--resume` invocation. Focus on these unmet coverage targets first (by
expected filename):

- Alpha.md

## Already have a note — report new material, never a second note

The vault already has a note for each of these. Do NOT propose any of them in
`topics_found.new` and do NOT list one in `proposed_filenames`. If your sources
show something NEW about one — a newer release, a contradiction, a deprecation,
a successor — report it in `topics_found.updates` (see the output section) with
the source URL(s). A note with nothing new to report is simply left out.

- Kafka Streams.md

## Rejected by the operator — skip these

The operator rejected these topics for good. Do not propose them, and do not
report updates for them.

- Thermodynamics

Check CLAUDE.md's note-inclusion criteria. A topic warrants a note if ANY apply:
- Referenced 2+ times across different notes
- Directly queryable by a user
- Appears in a system diagram or data/decision flow
- Upstream/downstream dependency
- Sub-concept with distinct behaviour

When in doubt, list it. Filenames follow the spec's naming convention: `slug`.

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
    "always_source": {"searched": true|false, "results_count": N, "reason": "<why skipped — REQUIRED if searched is false>"},
    "extra": {"searched": true|false, "results_count": N, "reason": "<why skipped — REQUIRED if searched is false>"}
  },
  "topics_found": {
    "new": ["<topic title>", "..."],
    "existing": ["<already-covered topic>", "..."],
    "updates": [
      {"note": "<existing note filename or stem>", "source_urls": ["<URL>"], "summary": "<what is new>"}
    ],
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
- `proposed_filenames` is REQUIRED and MUST NOT collide with any existing file
  under `data_vault/`, nor repeat an entry within its own list. It is how the
  framework stops two notes being written for one concept before any file is
  created; omitting it or sending `[]` while you report new topics is a
  structural error and the cycle will ask you to redo this report.
- For EVERY source you set `searched: false` on — required or optional —
  provide a `reason`. A required source you skipped is the one the operator
  most needs explained; "not relevant to this cycle's topics" is a fine
  reason, silence is not.
- Do NOT write any vault notes in this phase — scout only.
- Do NOT self-assess validation. A separate script reads this JSON and decides CONTINUE/TERMINATE.

- `topics_found.updates` is OPTIONAL (omit it or send `[]` when nothing changed).
  Each row names a note the vault ALREADY has (`note`: its filename or stem, as
  listed under "Already have a note"), the `source_urls` that show what is new,
  and a one-line `summary`. Never propose a second note for the same topic.

Output ONLY the JSON file at the path above. Do not print the JSON to stdout.
