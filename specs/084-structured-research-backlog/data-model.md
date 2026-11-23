# Data model: The research backlog as structured state (084)

The machine contract is [`contracts/research-backlog.schema.json`](contracts/research-backlog.schema.json);
this file explains it. Paths are relative to the vault root.

## Entity 1 — Backlog store

`_pipeline/state/research-backlog.json` (tracked; path from `083`'s layout
module).

| Field | Type | Rule |
| --- | --- | --- |
| `schema_version` | string `"1.0"` | a newer major ⇒ read-only (spec § Edge Cases); a newer minor ⇒ read and write, unknown fields preserved |
| `entries` | array of Entry | file order is insertion order; ids unique, or the store is malformed |

Anything else at the top level is preserved and ignored.

## Entity 2 — Entry

### Identity and provenance (set once, never changed by a writer)

| Field | Type | Rule |
| --- | --- | --- |
| `id` | string | `topic:<key>`, `quarantine:<stem>` or `migrated:<NNNN>`; `<key>` = title, whitespace collapsed, stripped, case-folded (research R6). An operator entry without an `id` is assigned one on the next write |
| `title` | string | display title; for quarantine entries the stem; for migrated entries a 80-character prefix of the line |
| `origin` | enum | `harvest`, `researcher`, `proposal`, `quarantine`, `operator`, `migrated` — who created the entry |
| `added` | date (`YYYY-MM-DD`) | creation date |
| `first_seen_cycle` | integer ≥ 1 or `null` | `null` for operator and migrated entries |

### Observation fields (writer-owned; FR-007)

| Field | Written by | Meaning |
| --- | --- | --- |
| `last_seen_cycle` | harvest, propose, quarantine sweep | latest cycle that observed the entry |
| `seen_cycles` | same | number of distinct cycles that observed it — the carry-over count |
| `citation_count` | harvest | distinct touched notes citing the missing target, latest sighting |
| `cited_from` | harvest | vault-relative paths of those notes, latest sighting |
| `detail` | harvest (researcher flag), propose (justification), quarantine sweep (verifier reason), converter (migrated line) | free text |
| `relation`, `parent_note`, `scope_warn` | propose | Phase 2 tangent metadata |
| `stem`, `kind` | quarantine sweep | `kind` ∈ `rewrite`, `retry` |
| `updated` | every writer | date of the last module write to this entry |

### Status

| Field | Type | Rule |
| --- | --- | --- |
| `status` | enum `open`, `resolved`, `dropped` | — |
| `status_by` | `operator` or a writer name (`harvest`, `propose`, `quarantine`, `regrade`, `migration`) | who last set `status` |
| `status_written` | same enum | the `status` the module last wrote; absent or different from `status` ⇒ an operator changed it (research R5) |

Any other field is operator-owned and preserved byte-for-byte in value.

## State transitions

```text
            writer: resolve (note exists / quarantine file gone / re-grade)
   open  ───────────────────────────────────────────────►  resolved
    ▲  │                                                       │
    │  └──── operator only ──────────────►  dropped            │
    │                                         │                │
    ├────────────── operator only ◄───────────┘                │
    └──── operator, or a writer observing it again ◄───────────┘
          (a writer only if a writer resolved it)
```

- A writer moves `open → resolved`, and `resolved → open` only for an entry
  a writer resolved, when it observes that entry again. It never changes the
  status of an entry whose `status_by` is `operator`.
- Only an operator moves an entry to `dropped` or out of it, or reopens an
  entry an operator resolved. The module notices an operator's change on its
  next load (`status != status_written`) and records `status_by: operator`.
- Nothing deletes an entry.

## Writer → observation map

| Writer | Observation | Entries touched |
| --- | --- | --- |
| harvest (`scripts/topic_harvest.py`) | `observe_topic(cycle, title, origin=harvest\|researcher, citation_count, cited_from)` per follow-up; then `resolve_covered(existing_stems)` | `topic:*` |
| propose (`scripts/topic_propose.py`) | `observe_topic(cycle, title, origin=proposal, relation, parent_note, scope_warn, detail)` per accepted proposal | `topic:*` |
| quarantine sweep (`orchestrator._quarantine_rejected_notes`) | `observe_quarantine(stem, kind, detail)` per quarantined note; `resolve_quarantine(live_stems)` | `quarantine:*` |
| `./vault re-grade` | `resolve_quarantine_stem(stem)` | exactly `quarantine:<stem>` |
| scaffold | `create_empty()` | — |
| conversion step (`083` FR-018 step 2) | `convert_legacy(markdown) → store` | all |

`observe_topic` on an existing id updates only observation fields; on a new
id it creates the entry with the given origin, `status: open`,
`status_by` = writer.

## Reader → query map

| Reader | Query |
| --- | --- |
| planner (`research_plan`) | `planner_topics()` — open, (operator-owned **or** `citation_count ≥ 1`); research R7 |
| propose dedupe and prompt | `all_titles()` — every entry's key and display title, any status |
| view renderer | everything, grouped (Entity 4) |
| continuation trigger | **none** — it reads `cycle-NNN-harvest.json` (Q2) |

## Entity 3 — Migration archive

`_pipeline/state/research-backlog.pre-migration.md` (tracked; in `083`'s
FR-002 set). The pre-conversion file, byte-for-byte. Written once by the
conversion step; never read by code.

## Entity 4 — Backlog view

`_pipeline/research-backlog.md` (git-ignored, removed from the index by the
conversion step). Layout in
[`contracts/backlog-view.contract.md`](contracts/backlog-view.contract.md).

## Entity 5 — Overwritten view copy

`_pipeline/research-backlog.md.overwritten` (git-ignored). The last
hand-edited view the module overwrote; replaced by the next one; never read
by code (Q4).
