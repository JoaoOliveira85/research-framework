# Spec 005 — Adaptive Sources

**Status:** shipped(2026-05-13, commit 9d6f626) — **SHIPPED (early 0.2.x — pre-status-header-convention).** The adaptive-sources engine landed in the foundational autonomous-pipeline window (`feat/fix(005)` commits incl. `9d6f626`, pyproject `0.2.15`, 2026-05-13); `pipeline/source_manager.py` (SQLite `sources.db`, source growth/decay, inbound-wikilink metric) is live today. Predates the CHANGELOG (which begins at 0.2.18) and the status-header convention.

## Problem Statement

Sources in a vault are currently static: declared in the spec at generation
time, never changed by the pipeline. This creates two failure modes that
compound over time:

**Bloat.** Dead or low-yield sources (a Confluence space that hasn't been
updated in a year, a web source that 301s every call) still appear in every
scout prompt, consuming tokens and scout budget for zero return. The scout
dutifully consults them, finds nothing new, and burns $0.50 per cycle doing
it.

**Gaps.** High-signal sources the researcher encounters mid-cycle — a GitHub
repo referenced three times in new notes, a Slack channel that keeps coming
up in intent discussions — are noted once in the research report and never
seen again. The next scout starts blind, re-discovering the same leads instead
of following them.

Both problems get worse as token costs rise and vaults grow.

## Proposed Solution

**`_pipeline/sources.db`** (SQLite) becomes the live source of truth for all
sources a vault consults. It is seeded from the spec at generation time and
evolves with each cycle. The spec's `data_sources` field remains the
*genesis declaration*; `sources.db` is the *running state*.

Four mechanisms keep the list healthy:

### 1. Scaffold seeding

At vault generation time, `scaffold.py` creates `sources.db` and inserts
every source from `spec.data_sources` with `locked = 1`. These entries are
rated and tracked but never auto-archived — they represent intentional scope
decisions that only the user can revoke.

### 2. Source discovery — growth

When the DFS (note-writer) agent encounters a high-signal source not already
in `sources.db`, it records it in the research report under a new
`discovered_sources` field. After each cycle, `source_manager.record_cycle()`
upserts these entries with `locked = 0`. Discovered sources are visible to
the next cycle's scout prompt immediately (or after a one-line confirmation,
depending on `auto_promote_discovered` in settings).

### 3. Source quality tracking

Every source — spec-declared or discovered — accumulates per-cycle metrics
in `sources.db`. The key signals:

| Column | Type | Meaning |
|--------|------|---------|
| `notes_generated` | int | Notes citing this source this cycle |
| `topics_covered` | int | Distinct topics touched |
| `tags_generated` | int | Tags on notes citing this source |
| `notes_referencing` | int | Distinct notes whose `source_urls` list this source across the whole vault |

`notes_referencing` is the relevance proxy: it measures how much of the
vault's content traces back to this source, computed with a one-pass scan of
`source_urls` frontmatter fields after each cycle.

### 4. Source decay — archiving low-yield unlocked sources

Only unlocked sources (`locked = 0`) are eligible for automatic archiving.
When `consecutive_empty_cycles ≥ decay_after_n_cycles`, the source moves to
`status = 'archived'` and is excluded from the scout prompt. The row is never
deleted — history is preserved for auditability. Re-activating is one SQL
update or `./vault sources reactivate <name>`.

Locking and unlocking is always explicit: `./vault sources lock <name>` /
`./vault sources unlock <name>`, or direct DB edit.

### 5. Query escalation — research on demand

When an agent handling a `/ask` or `/write` query determines that vault
content is insufficient to ground an answer AND the topic is within the
vault's scope, it calls the research scripts directly (via Bash, within the
same session) rather than signalling an external process:

```bash
# The agent runs this itself, using the vault's pre-authorised Bash permissions:
python scripts/run_cycle.py \
    --vault . \
    --target-topics "Charlie AI adoption strategy" \
    --budget-cap 2.0 \
    --max-cycles 1
```

After the mini-cycle completes, the agent re-reads the vault and answers.
If the existing source list has no coverage of the topic, the scout will
surface a source gap which feeds into `sources.db` as a discovered source
candidate.

## Non-Goals

- Auto-archiving spec-declared sources — `locked = 1` by default. Must be
  explicitly unlocked before decay applies.
- Crawling or predictively scoring sources the pipeline has never consulted —
  decay is based on observed yield only.
- Full query-answering within the escalation path — the escalation runs a
  standard research cycle; the re-run query produces the answer.
- Deleting source history — archived rows stay in the DB permanently.
- Replacing `spec-parse.json` — the spec's `data_sources` remains the genesis
  declaration; `sources.db` is the live operational state.

## Technical Design

### New file: `_pipeline/sources.db` (SQLite, stdlib `sqlite3`)

```sql
CREATE TABLE sources (
    name                    TEXT PRIMARY KEY,
    type                    TEXT,       -- "internal" | "external"
    role                    TEXT,       -- "behaviour" | "intent" | "domain"
    url                     TEXT,
    first_seen_cycle        INTEGER,
    locked                  INTEGER DEFAULT 0,    -- 1 = never auto-archive
    status                  TEXT DEFAULT 'active', -- "active" | "archived"
    consecutive_empty_cycles INTEGER DEFAULT 0
);

CREATE TABLE source_cycles (
    name               TEXT REFERENCES sources(name),
    cycle              INTEGER,
    notes_generated    INTEGER DEFAULT 0,
    topics_covered     INTEGER DEFAULT 0,
    tags_generated     INTEGER DEFAULT 0,
    notes_referencing  INTEGER DEFAULT 0,
    PRIMARY KEY (name, cycle)
);
```

`notes_referencing` is computed after each DFS by scanning every note's
`source_urls` frontmatter field for a URL matching this source.

### Schema changes — research report

Add `discovered_sources: list[dict]` to the research report schema (optional,
default `[]`). Each entry: `{name, type, role, url}`. `validate_cycle.py`
accepts but does not require the field.

### Changes to `scaffold.py`

At vault generation:
1. Create `_pipeline/sources.db` with the schema above
2. Insert each `spec.data_sources` entry with `locked = 1`

### New module: `src/research_vault/pipeline/source_manager.py`

```python
def seed(vault_dir: Path, spec: SpecConfig) -> None
    # Called by scaffold.py. Creates DB, inserts spec sources as locked.

def record_cycle(
    vault_dir: Path,
    cycle_num: int,
    research_report: dict,
    notes_dir: Path,
) -> None
    # 1. Upserts source_cycles rows for all active sources from the report.
    # 2. Computes notes_referencing via one-pass vault scan.
    # 3. Updates consecutive_empty_cycles; archives unlocked sources at threshold.
    # 4. Calls append_discovered() for research_report["discovered_sources"].

def append_discovered(vault_dir: Path, new_sources: list[dict]) -> None
    # Inserts with locked=0; skips duplicates by name.

def active_sources(vault_dir: Path) -> list[dict]
    # Returns status="active" rows — fed into scout prompt rendering.

def merge_into_prompt_context(
    spec: SpecConfig, vault_dir: Path
) -> list[DataSourceConfig]
    # Spec sources (priority order) + active discovered sources (low priority).
    # Returns a unified list for _render_cycle_scout_prompt.

def source_quality_summary(vault_dir: Path) -> list[dict]
    # Aggregated per-source metrics across all cycles.
    # Consumed by vault_audit.py (spec 006 prerequisite).
```

### Changes to `cycle_runner.py`

Add **Step 6b** between Step 6 (validate research) and Step 7 (topic harvest):

```
Step 6b: source_manager.record_cycle() — update quality DB (best-effort)
```

Best-effort: any failure logs WARN and continues. Never halts the cycle.

### Changes to `orchestrator.py`

Before rendering each cycle's scout prompt, call
`source_manager.merge_into_prompt_context()` and pass the enriched source
list. Spec sources always render first (higher priority in the prompt).

### Query escalation: `ask.md.j2` and `write.md.j2`

Add an escalation instruction to both command templates:

> If the vault does not contain enough grounded information to answer and
> the topic is within the vault's declared scope, run a focused research
> cycle before answering:
>
> ```bash
> python scripts/run_cycle.py --vault . --target-topics "<topic>" \
>     --budget-cap {{ settings.stages.ask_escalation.budget_cap }} --max-cycles 1
> ```
>
> After the cycle completes, re-read the relevant vault notes and answer.
> If the research cycle finds no suitable sources, note this explicitly and
> do not fabricate an answer.

The agent uses its pre-authorised Bash permissions (from `.claude/settings.json`)
to run the script directly. No external trigger mechanism needed.

### Settings additions

```yaml
stages:
  source_manager:
    enabled: true
    decay_after_n_cycles: 3         # archive unlocked sources after N empty cycles
    auto_promote_discovered: false  # true = no confirmation prompt for new sources

  ask_escalation:
    enabled: true
    budget_cap: 2.0                 # USD cap per escalation mini-cycle
```

## Acceptance Criteria

1. After `scaffold.py` runs, `_pipeline/sources.db` exists and contains one
   row per `spec.data_sources` entry, all with `locked = 1`
2. After a cycle where the DFS report contains `discovered_sources: [{name: "X", ...}]`,
   `sources.db` has an entry for X with `locked = 0, status = "active"`
3. After `decay_after_n_cycles` consecutive empty cycles for an unlocked
   source, `status` moves to `"archived"` and it no longer appears in the
   next cycle's scout prompt
4. Locked sources never change status automatically, regardless of yield
5. `./vault sources reactivate <name>` sets `status = "active"` on an
   archived source; it reappears in the next scout prompt
6. An `/ask` query that lacks vault grounding calls `run_cycle.py` within
   the session and re-answers from the new notes
7. `stages.source_manager.enabled: false` skips all DB writes and prompt
   enrichment; no `sources.db` created
8. `source_quality_summary()` returns a list consumable by `vault_audit.py`
   without 005-specific knowledge in the caller
9. All existing tests pass; `pytest tests/` ≥ 427 after implementation

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| DFS agent invents plausible-sounding source URLs | Medium | Medium | `append_discovered` validates URL format; dedupes by name; invalid entries WARN-logged and dropped |
| Decay archives a useful source during a quiet patch | Medium | Low | Locked sources immune; history preserved; one command re-activates |
| Query escalation burns budget on off-scope topics | Medium | High | Agent instructed to check scope first; `budget_cap: 2.0` hard ceiling; agent reports "out of scope" rather than escalating |
| `notes_referencing` scan is slow on large vaults | Low | Low | One-pass frontmatter scan; deferred to post-cycle (not in critical path); can be skipped if `source_manager.enabled: false` |
