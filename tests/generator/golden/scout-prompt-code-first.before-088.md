---
_template_version: N
---
You are running BFS scout cycle {CYCLE_NUM} of a recursive research pass on the
Codebase Vault (Code-First) vault.

Domain: Acme Corp Platform team — business logic, services, flows, decisions, risks, org context, products, market
Organization: Acme Corp — Platform team

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


## Source-of-Truth Rule (CODE-FIRST)

Code is the authoritative source for how the system behaves. Confluence/Jira are
consulted only to answer "why does this exist" for topics already surfaced by the
code scan. **You must walk the enumerated repos BEFORE any Confluence call.**

- Code wins on questions of current behaviour (authoritative source is the repository).
- Confluence wins on questions of stated intent and original motivation.
- When code and intent disagree, the note records both and flags the drift via `intent_implementation_drift: true`.

## Step 1 — Walk the enumerated repos

Read the following repos in priority order. For each repo, scan its `priority_paths`
first, honour `ignore_paths`, and extract:

- the service it describes (one `topics_from_code` entry with `topic_type: service`)
- every ADR file under `docs/adr/` or `docs/decisions/` (→ `topic_type: decision`)
- every Kafka topic, REST endpoint, or inter-service event (→ `topic_type: flow`)
- every domain term (class/package/enum name) referenced in 2+ files (→ `topic_type: concept`)

Every topic MUST carry a `source_file` path pointing at the exact repo file that
produced it, plus a short `source_snippet` (line range or class name).

**`source_file` shape (mandatory).** Use the URL-derived canonical shape
`<org>/<repo>/<path-inside-repo>` — i.e., strip `https://github.com/` from the
repo's URL field below and append the path relative to the repo root.

- Right: `acme-corp/oebh-service/README.md`
- Right: `acme-corp/oebh-service/src/main/java/com/acme/oebh/Domain.java`
- Wrong: `acme-corp/backend/oebh-service/README.md` (don't include
  intermediate filesystem segments from the on-disk `Access` path — that is
  shown for your reference only, not for emission in `source_file`)
- Wrong: `/Users/dev/acme-corp/backend/oebh-service/README.md` (no
  absolute paths in `source_file`)

The validator accepts the local-path shape as a fallback (v0.2.27) so the
cycle won't abort, but the canonical URL shape is the contract and reads
cleanly in downstream notes.

Repos:

### CAT
- URL: https://github.com/acme-corp/catalogue-service
- Canonical `source_file` prefix: `acme-corp/catalogue-service/`
- Owning team: Platform
- Access (your filesystem, NOT for `source_file`): both (~/acme-corp/backend/catalogue-service)- Priority paths: README.md, docs/, src/main/resources/application.yml, src/main/java/**/config/
- Ignore paths: target/, build/, generated/, .gradle/
### LDG
- URL: https://github.com/acme-corp/ledger-service
- Canonical `source_file` prefix: `acme-corp/ledger-service/`
- Owning team: Platform
- Access (your filesystem, NOT for `source_file`): both (~/acme-corp/backend/ledger-service)- Priority paths: README.md, docs/, src/main/resources/application.yml, src/main/java/**/config/
- Ignore paths: target/, build/, generated/, .gradle/
### BAL
- URL: https://github.com/acme-corp/balance-service
- Canonical `source_file` prefix: `acme-corp/balance-service/`
- Owning team: Platform
- Access (your filesystem, NOT for `source_file`): both (~/acme-corp/backend/balance-service)- Priority paths: README.md, docs/, src/main/resources/application.yml, src/main/java/**/config/
- Ignore paths: target/, build/, generated/, .gradle/
### CLR
- URL: https://github.com/acme-corp/clearing-service
- Canonical `source_file` prefix: `acme-corp/clearing-service/`
- Owning team: Platform
- Access (your filesystem, NOT for `source_file`): both (~/acme-corp/backend/clearing-service)- Priority paths: README.md, docs/, src/main/resources/application.yml, src/main/java/**/config/
- Ignore paths: target/, build/, generated/, .gradle/
### SET
- URL: https://github.com/acme-corp/settlement-service
- Canonical `source_file` prefix: `acme-corp/settlement-service/`
- Owning team: Platform
- Access (your filesystem, NOT for `source_file`): both (~/acme-corp/backend/settlement-service)- Priority paths: README.md, docs/, src/main/resources/application.yml, src/main/java/**/config/
- Ignore paths: target/, build/, generated/, .gradle/
### CFG
- URL: https://github.com/acme-corp/config-service
- Canonical `source_file` prefix: `acme-corp/config-service/`
- Owning team: Platform
- Access (your filesystem, NOT for `source_file`): both (~/acme-corp/backend/config-service)- Priority paths: README.md, docs/, src/main/resources/application.yml, src/main/java/**/config/
- Ignore paths: target/, build/, generated/, .gradle/
### RPT
- URL: https://github.com/acme-corp/reporting-service
- Canonical `source_file` prefix: `acme-corp/reporting-service/`
- Owning team: Platform
- Access (your filesystem, NOT for `source_file`): both (~/acme-corp/backend/reporting-service)- Priority paths: README.md, docs/, src/main/resources/application.yml, src/main/java/**/config/
- Ignore paths: target/, build/, generated/, .gradle/
### ONB
- URL: https://github.com/acme-corp/onboarding-service
- Canonical `source_file` prefix: `acme-corp/onboarding-service/`
- Owning team: Platform
- Access (your filesystem, NOT for `source_file`): both (~/acme-corp/backend/onboarding-service)- Priority paths: README.md, docs/, src/main/resources/application.yml, src/main/java/**/config/
- Ignore paths: target/, build/, generated/, .gradle/
### REF
- URL: https://github.com/acme-corp/reference-lookup-tool
- Canonical `source_file` prefix: `acme-corp/reference-lookup-tool/`
- Owning team: Platform
- Access (your filesystem, NOT for `source_file`): both (~/acme-corp/backend/reference-lookup-tool)- Priority paths: README.md, docs/
- Ignore paths: target/, build/, generated/, .gradle/

## Step 2 — Collect intent for each code topic

For each `topics_from_code` entry from Step 1, consult intent sources (Confluence, Jira (PLAT project), Slack, Microsoft 365)
to find the **stated intent** — why does this exist, who asked for it, what was it
originally meant to do?

Each `intent_from_confluence` entry MUST reference a `parent_code_topic_id` from Step 1.
Free-floating intents (no parent code topic) are rejected by validation.

Intent sources:

- **Confluence** (external) — Used ONLY to answer 'why does this exist' for code topics already surfaced. Never used to discover new topics. [Atlassian MCP]- **Jira (PLAT project)** (external) — Active-work dimension. Epics and stories show what the team is currently building — concepts referenced here must have notes. [Atlassian MCP]- **Slack** (external) — Channel archives and pinned messages for discussion context. [Slack MCP] *(optional)*- **Microsoft 365** (external) — SharePoint + email context. [M365 MCP] *(optional)*
Domain sources (for market/product/process notes only):

- **Web** (external) — Market and competitor context. Only for note types market, product, process, risk.
## Step 3 — Search dimensions

All five dimensions MUST be covered in this cycle's scout report:

- **technical** (anchored in code — Step 1)- **organizational**- **domain**- **market**- **temporal**
## Step 4 — Generalize: name the engineering concepts

`topics_from_code` and `intent_from_confluence` are **provenance only** — they
record what literal artifacts you found in the codebase. They are NOT what the
note-writer turns into vault notes.

For each artifact (and each cluster of artifacts) from Steps 1–2, name the
**reusable engineering concept, pattern, or technique** it exemplifies and put
that name into `topics_found.new`. A `topics_found.new[*]` row is a *dict* with
this shape:

```json
{
  "title": "<engineering-concept title — reusable, not an internal artifact name>",
  "coverage_category": "<one of the categories listed below>",
  "proposed_filename": "<filename>.md",
  "source_code_topic_ids": ["CT-{CYCLE_NUM}-XXX", "..."],
  "source_intent_ids": ["IT-{CYCLE_NUM}-YYY"]
}
```

**`title`** must be the engineering concept, not the internal name. Examples:
- ✅ `"Single-Writer Cumulative-Total Calculator"` (concept)
- ✅ `"Hexagonal Repository Ports for Risk APIs"` (pattern)
- ✅ `"Kafka Replay Strategy for Cache Eviction"` (technique)
- ❌ `"customer_order_calculator_service"` (internal class/service name)
- ❌ `"OMS Service"` (literal service name — provenance, not concept)

**`coverage_category`** must be one of the spec's configured categories so the
SG-002 diversity gate sees you spreading topics across coverage gaps, not piling
into one folder. Configured categories for this vault:
- `services` — note_type: service- `concepts` — note_type: concept- `flows` — note_type: flow- `decisions` — note_type: decision- `products` — note_type: product- `teams` — note_type: team- `risks` — note_type: risk- `processes` — note_type: process- `market` — note_type: market- `mocs` — note_type: moc
**`source_code_topic_ids` / `source_intent_ids`** trace each generalized topic
back to its provenance — listing every `CT-…` and `IT-…` you condensed into it.
A generalized topic that cites no `CT-…` is rejected by validation.

You should produce **roughly one `topics_found.new` row per coherent
engineering idea you observed**, not one row per file or per class. Cluster
related artifacts under a single concept (e.g. 5 different `*HandlerService`
classes that all implement the same dispatch pattern → 1 topic).


**`proposed_filename`** must follow the vault's `full_name`
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

When in doubt, list it. Filenames follow the spec's naming convention: `full_name`.

## Output

Write the JSON report to: `{SCOUT_REPORT}`

The report MUST follow the v2 schema (no extra commentary, JSON only):

```json
{
  "schema_version": "2.0",
  "cycle": {CYCLE_NUM},
  "phase": "scout",
  "timestamp": "<ISO-8601 timestamp>",
  "dimensions_covered": ["technical", "organizational", "domain", "market", "temporal"],
  "topics_from_code": [
    {
      "id": "CT-{CYCLE_NUM}-001",
      "topic_type": "service" | "flow" | "concept" | "decision" | "config",
      "source_file": "<org>/<repo>/<path>",
      "source_snippet": "lines N-M or class/function ref",
      "proposed_filename": "<filename>.md"
    }
  ],
  "intent_from_confluence": [
    {
      "id": "IT-{CYCLE_NUM}-001",
      "parent_code_topic_id": "CT-{CYCLE_NUM}-001",
      "source_url": "<Confluence/Jira/ADR URL>",
      "intent_summary": "<=200 char statement of intent",
      "intent_type": "description" | "decision" | "risk" | "owner"
    }
  ],
  "topics_found": {
    "new": [
      {
        "title": "<engineering-concept title>",
        "coverage_category": "<one of the categories from Step 4>",
        "proposed_filename": "<filename>.md",
        "source_code_topic_ids": ["CT-{CYCLE_NUM}-001"],
        "source_intent_ids": ["IT-{CYCLE_NUM}-001"]
      }
    ],
    "existing": ["<topic title that the vault already covers>"],
    "updates": [
      {
        "note": "<existing note filename or stem>",
        "source_urls": ["<URL of the source showing what is new>"],
        "summary": "<what is new about it>"
      }
    ],
    "total": <int>
  },
  "proposed_filenames": ["<Topic Title>.md"],
  "sources_consulted": ["GitHub repos", "Confluence", ...],
  "access_methods_used": {"<org>/<repo>": "local" | "mcp"},
  "termination_condition": null | "A" | "B" | "C",
  "notes_created": [],
  "unresolved_wikilinks": [],
  "budget_consumed_usd": <float>
}
```

Constraints:

- `topics_from_code` MUST be non-empty — code-first ordering violation otherwise.
- `topics_found.new` MUST be non-empty (SG-001 will fail the cycle otherwise) and
  each row MUST be a dict with `title`, `coverage_category`, `proposed_filename`,
  and `source_code_topic_ids` (≥ 1 `CT-…` id).
- `topics_found.new[*].coverage_category` values together MUST span at least
  `min(5, unfilled_coverage_categories)` distinct values (SG-002 diversity gate).
- `topics_found.new[*].proposed_filename` MUST NOT start with any forbidden
  prefix listed in Step 4 (SG-003 abstraction gate).
- Every `intent_from_confluence[*].parent_code_topic_id` MUST match a `topics_from_code[*].id`.
- Every `topics_from_code[*].source_file` MUST be under one of the enumerated repos above, in the canonical `<org>/<repo>/<path>` shape (see "`source_file` shape (mandatory)" above).
- Every `topics_found.new[*].source_code_topic_ids[*]` MUST match a `topics_from_code[*].id`.
- `dimensions_covered` MUST contain all five dimensions.
- `proposed_filenames` is REQUIRED and MUST NOT collide with any existing file
  under `data_vault/`, nor repeat an entry within its own list. It is how the
  framework stops two notes being written for one concept before any file is
  created; omitting it or sending `[]` while you report new topics is a
  structural error and the cycle will ask you to redo this report.
- Do NOT write any vault notes in this phase — scout only.
- Do NOT self-assess validation. `validate_cycle.py` and the SG-001..SG-005 gates read this JSON and decide CONTINUE/TERMINATE.

- `topics_found.updates` is OPTIONAL (omit it or send `[]` when nothing changed).
  Each row names a note the vault ALREADY has (`note`: its filename or stem, as
  listed under "Already have a note"), the `source_urls` that show what is new,
  and a one-line `summary`. Never propose a second note for the same topic.

Output ONLY the JSON file at the path above. Do not print the JSON to stdout.
