# Implementation Plan: The research backlog as structured state

**Spec**: [`spec.md`](spec.md) · **Design decisions**:
[`research.md`](research.md) (R1–R11) · **Data model**:
[`data-model.md`](data-model.md) · **Contracts**:
[`contracts/research-backlog.schema.json`](contracts/research-backlog.schema.json),
[`contracts/backlog-view.contract.md`](contracts/backlog-view.contract.md) ·
**Tasks**: [`tasks.md`](tasks.md)

Code citations in `research.md` are against `bc39eae`; the plan was
re-checked against `1961f9a` (v2.0.1) on 2026-11-22. This branch is rebased
onto `083-durable-state-layout` before implementation starts: it needs
`pipeline/state_layout.py` and `pipeline/layout_migration.py`.

## Summary

One module, `src/research_framework/pipeline/backlog.py`, owns
`_pipeline/state/research-backlog.json`. Writers hand it typed observations;
readers ask it queries; it renders the Markdown view after every write and
never parses it back. An existing Markdown backlog is converted once, as the
second step of `083`'s ordered migration.

## Technical context

- Python 3.11+, stdlib + `pyyaml` + `jinja2` (Principle V: no new
  dependency). JSON and `hashlib` are stdlib.
- Touches: `scripts/topic_harvest.py`, `scripts/topic_propose.py`,
  `pipeline/orchestrator.py` (quarantine sweep, constrained-exit and
  source-exhausted messages), `cli/regrade.py`, `pipeline/research_plan.py`,
  `generator/scaffold.py`, `pipeline/state_layout.py` (two registry rows),
  `pipeline/layout_migration.py` (one step), `scripts/vault_health.py`,
  `scripts/build_scaffold_manifest.py`,
  `templates/prompts/scout-prompt.md.j2` and the rendered prompt corpus.

## Constitution check

| Principle | How this plan meets it |
| --- | --- |
| I — script-validated gates | The store validates against the schema on load; a malformed store is never overwritten. |
| III — test-first | Every task carries its tests, authored before implementation. |
| V — no new dependency | stdlib only. |
| VI — no duplicate notes | Unchanged; topic identity (`topic:<key>`) makes one entry per topic. |
| X — append-only git | Conversion is its own `framework:` commit; the original Markdown is archived byte-for-byte under `state/`; nothing deletes an entry. |
| XII — inspection does not mutate | `--dry-run` converts nothing; readers never write, except rendering a missing view. |
| XIII — nothing accepted and ignored | An unconverted vault is refused through `083` FR-015, not half-read; a store with a newer major version is read-only and says so. |

## Design decisions

`research.md` R1–R11 are the decisions. In short:

1. **API** (R1): observations — `observe_topic`, `observe_quarantine`,
   `resolve_covered`, `resolve_quarantine`, `resolve_quarantine_stem` — and
   queries — `planner_topics`, `all_titles` — over one transaction primitive
   `update(vault, writer, fn)`. No caller holds a mutable entry.
2. **Paths** (R2): `state_layout` gains `research_backlog_archive_path` and
   a registry row for the archive; `research_backlog_path` already exists.
   The module spells only the view's and the overwritten copy's paths.
3. **Conversion** (R3): `layout_migration.MIGRATION_STEPS` gains
   `convert_backlog_to_store`, after `083`'s layout move. `state_layout`'s
   legacy check gains the "unconverted backlog" predicate.
4. **Hand-edit detection** (R4): the digest footer in the view.
5. **Operator status** (R5): `status_by` and `status_written` per entry.
6. **Identity** (R6): `topic:<key>`, origin-independent.
7. **Planner** (R7): queue on evidence — operator-owned, or
   `citation_count >= 1`.
8. **Migration grammar** (R8).
9. **Prompt** (R9): scout prompt item 4 describes the view; the prompt
   corpus is regenerated.
10. **`.gitignore`**: delete `083`'s transitional
    `!_pipeline/research-backlog.md` line (`083` FR-019).

## Room for `087`

`087` (#53) adds an origin `update` and an id form `update:<note stem>` in a
minor schema bump. Nothing here needs to anticipate it beyond what the model
already says: unknown fields are preserved, `origin` is an open enum across
minor versions, and observations are the only way to write.

## Order and risk

T001–T003 build the module with no caller. T004–T007 move the writers and
the reader, one per commit, each keeping its retained tests green. T008 is
the conversion, the one step every live vault goes through once: it is
rehearsed on copies of live backlogs (T011), because their hand-written
shapes are the reason the `migrated` origin exists.
