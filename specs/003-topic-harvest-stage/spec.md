# Topic harvest stage (003)

**Status:** shipped(2026-05-04, commit a3ef8dd) — **SHIPPED (early 0.2.x — pre-status-header-convention).** Phase 1 `topic_harvest` first landed in the genesis impl (commit `a3ef8dd`, pyproject `0.2.13`, 2026-05-04) and is live today, wired into the cycle as a Step-7 postprocess stage (`scripts/topic_harvest.py`, invoked from `pipeline/steps/postprocess.py`); Phase 2 `topic_propose` ships disabled (opt-in).

## Architecture — two independent sub-stages

Feature 003 ships **two sub-stages** that both live in Step 7 of
`run_cycle.sh`. They are **fully independent**: either can be disabled,
retuned, or replaced without touching the other. They share nothing at
runtime except a read-only view of the vault directory.

| Sub-stage | Purpose | Spec | Settings key | Default |
|-----------|---------|------|--------------|---------|
| **Phase 1 — `topic_harvest`** | Deterministic wikilink + coverage-gap scan. Zero LLM cost. Catches "the writer pointed here but there's no note yet." | this file | `stages.topic_harvest` | **enabled** |
| **Phase 2 — `topic_propose`** | Agent-driven, scope-bounded tangent proposer. Catches "nobody pointed here but the vault's scope says it belongs." | [`phase-2-semantic.md`](./phase-2-semantic.md) | `stages.topic_propose` | **disabled** (opt-in) |

Outputs are separate artifacts (`cycle-NNN-harvest.json` vs.
`cycle-NNN-propose.json`) and separate managed blocks inside
`research-backlog.md`, so the scout reads them through the same backlog
but can tell them apart.

The rest of this document is the Phase 1 (`topic_harvest`) spec. For the
agent proposer, see [`phase-2-semantic.md`](./phase-2-semantic.md).

## Problem

The pipeline has no systematic handoff from **research output** to the **next
scout**. The research JSON has slots for `topics_found.new` and
`new_wikilinks_discovered`, but:

- The DFS prompt explicitly tells the writer to keep `topics_found.new` sparse
  (anti–scope-creep), so it under-reports.
- `new_wikilinks_discovered` is optional and inconsistently populated.
- The scout reads `research-backlog.md`, but nothing deterministic appends to
  it between cycles.

Net effect: signals sitting in freshly written notes (unresolved
`[[wikilinks]]`, under-filled coverage categories) never make it onto the
scout's radar. Users observe flat note counts and reasonably expect a
snowball they never get.

## Solution

Insert a **deterministic, per-cycle harvester** between research validation
and cycle exit. It reads the notes touched this cycle, mines three signal
sources, and writes two artifacts the scout already consumes.

## Signals harvested (Phase 1 — no LLM)

1. **Missing wikilink targets** — `[[X]]` in a touched note where no file
   named `X.md` exists anywhere under `data_vault/`. Ranked by the number of
   DISTINCT touched notes that cite the target (demand signal).
2. **Researcher-flagged new links** — titles the researcher listed in
   `new_wikilinks_discovered` on the research report, deduped against (1).
3. **Unmet coverage categories** — categories from
   `_pipeline/coverage-targets.json` with `met_count < target_count`,
   ordered by `required` first, then shortfall.

## Known limitations (explicit non-goals for Phase 1)

- **Obsidian aliases are not resolved.** `[[OEHK]]` surfaces as missing even
  if `OEHK (Order Engine Housekeeper).md` lists `OEHK` as an alias.
  `scripts/check_acronym_links.py` handles that concern separately.
- **No semantic extraction.** Topics implied by prose but not wikilinked are
  not picked up. That is intentionally reserved for Phase 2.
- **No network calls / URL validation.** Stub-free and health gates remain
  separate.

## Pipeline placement

```
scout → validate_scout → DFS → quality suite → post-metrics
    → validate_research → topic_harvest → exit
```

Harvest is best-effort: any failure prints a WARN and exits 0 so the cycle
never dies on it.

## Outputs

### 1. `_pipeline/cycles/cycle-NNN-harvest.json`

```json
{
  "schema_version": "1.0",
  "cycle": 3,
  "phase": "harvest",
  "timestamp": "2026-04-28T22:30:00Z",
  "notes_scanned": ["data_vault/01 - Concepts/Seed.md"],
  "followups": [
    {
      "title": "Ghost Topic",
      "reason": "missing_wikilink_target",
      "cited_from": ["data_vault/01 - Concepts/Seed.md"],
      "citation_count": 1
    }
  ],
  "coverage_gaps": [
    {
      "name": "architecture",
      "note_type": "concept",
      "target_count": 5,
      "met_count": 2,
      "shortfall": 3,
      "required": true
    }
  ]
}
```

### 2. `_pipeline/research-backlog.md`

A managed block is appended / replaced per cycle, wrapped in HTML comments
so re-runs of the same cycle are idempotent and manual entries outside the
block are preserved:

```markdown
<!-- topic-harvest:cycle=003 -->
## Harvest — cycle 003 (2026-04-28)

Follow-on topics (wikilink targets with no note yet, ranked by citation count):

- **Ghost Topic** — cited by 1 note(s): `data_vault/01 - Concepts/Seed.md`

Unmet coverage categories:

- `architecture` [concept] — 2/5 (required)
<!-- /topic-harvest:cycle=003 -->
```

## Scout integration

`templates/prompts/scout-prompt.md.j2` already lists
`_pipeline/research-backlog.md` as required reading. The prompt was extended
to say: when a **Harvest — cycle N** block is present, prefer those bullets
as high-priority follow-ons when composing `topics_found.new`.

## Phase 2 — see separate spec

The LLM-backed tangent proposer is specified in
[`phase-2-semantic.md`](./phase-2-semantic.md). It is a **sibling**
stage, not a successor: Phase 1 keeps running independently even when
Phase 2 is enabled.

## Files

- `scripts/topic_harvest.py` — Phase 1 harvester.
- `scripts/run_cycle.sh` — Step 7 invocation (best-effort).
- `templates/prompts/scout-prompt.md.j2` — backlog / harvest wording.
- `tests/scripts/test_topic_harvest.py` — unit coverage: ranking,
  normalization, existing-note skip, coverage gaps, researcher-flagged
  merge, manual-entry preservation, skip-when-missing-report.
