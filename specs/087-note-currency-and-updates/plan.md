# Implementation Plan: Note currency and updates

**Spec**: [`spec.md`](spec.md) · **Tasks**: [`tasks.md`](tasks.md) · **Builds
on**: `083` (`pipeline/state_layout.py`, `pipeline/layout_migration.py`) and
`084` (`pipeline/backlog.py`), both on their branches; this branch is rebased
onto `084` before implementation starts.

Grounded in a read-only survey of the code at `1961f9a` (v2.0.1) on
2026-11-23; file and line references below are from it. `RP` is
`src/research_framework/pipeline/research_plan.py`, `ORCH` is
`src/research_framework/pipeline/orchestrator.py`.

## Summary

A note gets a date it was last checked and a standing. New material about an
existing topic, and a note past its review interval, become update entries in
the backlog store. A cycle spends a configured share of its work on update
batches, in which the writer challenges a note and reports one of four
outcomes; a deterministic gate checks each outcome against git and the
verifier refuses a supersession without a credible source. Coverage stops
counting superseded notes, and the reader-facing surfaces say how current the
vault is.

## Technical context

- Python 3.11+, stdlib + `pyyaml` + `jinja2`. No new dependency (Principle V).
- The change crosses the scout prompt, the planner, the batch loop, the
  writer prompt, the verifier, coverage, three reader-facing verbs, the spec
  schema, the settings schema and the migration. It is sequenced so each task
  leaves the suite green and the feature off until T007 turns the split on.

## Constitution check

| Principle | How this plan meets it |
| --- | --- |
| I — script-validated gates | Outcomes are checked by a script against git (`UG-001`); the supersession rule is a deterministic verifier rule; the due sweep calls no model. |
| III — test-first | Every task carries its tests, authored before implementation. |
| IV — agent/script separation | The agent proposes an outcome; scripts decide whether it stands. No new dispatch surface. |
| V — no new dependency | stdlib only. |
| VI — no duplicate notes | Unchanged: the rule becomes "never a second note", enforced where it is today, while an assigned note may be edited. |
| VIII — no placeholders | A `confirmed` outcome is not counted as content anywhere (the "bookkeeping fraud" failure the code already names). |
| X — append-only git | An update is a new commit; a rejected update restores the note from `HEAD`, the path rewrites already use; the migration stamp is its own `framework:` commit. |
| XII — inspection does not mutate | `coverage`, `health`, `status` recompute in memory; the due sweep runs only inside a cycle. |
| XIII — nothing accepted and ignored | `research_mode` and `phases` gain consumers; the inert `research_modes` blocks leave the shipped profiles; a new guard proves every `pipeline.*` key is read. |

## Design decisions

1. **Currency is declared once**: `src/research_framework/vault/note_currency.py`
   holds the field names (`as_of`, `currency`, `supersedes`,
   `superseded_by`), the five values, and three pure functions —
   `countable(frontmatter)` (false for `superseded` and `retracted`),
   `is_due(frontmatter, review_after_days, today)`, and
   `effective(frontmatter)` (a missing `currency` reads as `current`, a
   missing `as_of` as "never due"). The note template, `validate_vault`'s
   required list, `processors/verify.py`'s resolver and coverage read from
   it (spec D5). The template stamps both keys **empty**, because
   `verify._declared_note_format` treats only empty template values as
   required.
2. **Update entries are backlog entries** (`084`): origin `update`, id
   `update:<note stem>`, schema `1.1`. `backlog.py` gains
   `observe_update(stem, reason, prompted_by, cycle)`,
   `close_update(stem, outcome)` and the query `update_topics()`
   (`new_material` before `review_due`, then oldest `as_of`). Writers:
   `scout`, `review`, `research`. The view gains a "Notes to update"
   section. Nothing else writes the store.
3. **The scout reports instead of skipping.** The scout prompt renders
   existing notes under "Already have a note — report new material, never a
   second note" and the operator's persistent rejects under their own skip
   list (they share one list today, `ORCH:1606-1626`). The scout report gains
   `topics_found.updates: [{note, source_urls, summary}]`. After the scout
   merge (`steps/scout.py:487`), each `updates` row, and each `new` row the
   merge drops because it matches an existing note (`RP:931`), becomes
   `observe_update(reason="new_material")`.
4. **The due sweep** is `pipeline/currency.py::queue_due_reviews(vault, spec,
   today)`: walk the corpus, apply `is_due` with each type's
   `review_after_days`, `observe_update(reason="review_due")`. It runs at
   cycle start, before the plan is generated (`ORCH:700`), together with a
   `coverage.recompute_from_disk` so the planner reads current counts.
5. **`review_after_days`** is a new optional `NoteTypeConfig` field: dataclass,
   `to_dict` / `from_dict`, `_expand_note_types` in `spec/simple.py` (which
   passes fields explicitly), a positive-integer check in `spec/validator.py`,
   and a `PARSER_VERSION` bump in `spec/parsed.py`.
6. **The split is a settings key**: `pipeline.cycle_split: {new: 60, updates:
   30, discovery: 10}` (three non-negative integers summing to 100), declared
   the way `cycles_per_run` is (`_PIPELINE_TYPED_KEYS`, dataclass field,
   parser, `_PIPELINE_FIELDS`). `research_mode` chooses how it is applied:
   `bootstrap` gives updates 0, `refresh` gives new topics 0, `expand` uses
   it as written. The default mode becomes `expand` (`schema.py:549`, `:621`,
   `simple.py:116`, `:230`). Shares with no work fall to the others (FR-016).
   A source whose `phases` excludes the cycle's mode is left out of the scout
   prompt's source list (`applies_to`), which gives `phases` its consumer.
   The `research_modes` blocks, and their promise of a `--mode` flag, are
   removed from the shipped profiles and from `_INERT_PATHS`.
7. **The plan carries an update queue.** `ResearchPlan` gains `update_queue`
   (note stem, path, reason, `as_of`, prompting source), written as its own
   section so the Markdown round trip (`to_markdown`,
   `_parse_priority_queue_from_plan_md`) is not overloaded. `_compute_cycle_quota`
   stays the cycle's total; a new `_split_quota` turns it into a new-topic
   count and an update count.
8. **Update batches.** `BatchAssignment` gains `kind`. The batch loop
   (`steps/research.py`) cuts new-topic batches and update batches from their
   own queues and counts each against its own share: new files for one,
   outcomes for the other. For an update batch the prompt renders
   `## Update topics (JSON)`, the "Exclusions (binding)" block exempts the
   assigned notes, the synthetic SG-005 "no new file" failure does not apply,
   and the correction hint does not say "do not edit existing notes".
9. **Outcomes are the record.** The research report gains `update_outcomes:
   [{note, outcome, sources_consulted, evidence_url, superseded_by,
   change}]`. A new step gate `UG-001` (`pipeline/gates_step.py`) checks each
   one against `HEAD`: the note existed; `confirmed` left the body
   byte-identical and moved `as_of`; `revised` changed the body and added at
   least one `source_urls` entry; `superseded` set `currency` and
   `superseded_by` and the successor's `supersedes`; `retracted` set
   `currency` and recorded the reason. A failing outcome restores the note
   from `HEAD` (the path `_quarantine_rejected_notes` already uses for a
   rejected rewrite) and leaves the entry open. `notes_updated` is derived:
   the notes whose outcome is not `confirmed`.
10. **The verifier decides supersession.** A deterministic rule
    `IX-currency-evidence` in `pipeline/verifier.py`, beside the credibility
    rule: a note whose `currency` is `superseded` or `retracted` and differs
    from `HEAD` MUST have its outcome's `evidence_url` among its
    `source_urls`, resolving through `credibility.effective_level` to
    `PRIMARY` or `CORROBORATED`. A second rule, `IX-supersession-symmetry`,
    fails a one-sided link. Both are fail-severity: the note is rejected and
    restored.
11. **Coverage.** `recompute_from_disk` skips notes that are not `countable`.
    `./vault coverage` recounts in memory instead of printing the persisted
    file, so it and `status --json` agree.
12. **Reader-facing surfaces.** `coverage` adds per-category "past review"
    and "superseded" columns; `scripts/vault_health.py` adds a Currency
    section to `HealthReport`; `status` prints the last cycle's outcomes by
    kind; `templates/commands/ask.md.j2` gains the rule about past-review and
    superseded notes, and the prompt corpus is regenerated.
13. **Migration.** `layout_migration.MIGRATION_STEPS` gains
    `stamp_note_currency`, third, using
    `vault/frontmatter.append_frontmatter_keys` (which keeps existing lines
    byte for byte). Its own `framework:` commit, `--dry-run`, one `INFO`
    line.
14. **The guard** `scripts/guards/settings_key_consumers.py`: every key in
    the typed `pipeline:` schema is referenced by code outside
    `pipeline/settings.py`.

## What is not done here

Outside-in discovery (#52): the discovery share exists and falls to new
topics until that spec ships. Splitting or merging notes. The `status` versus
`lifecycle` vocabulary (`079` T003). `vault-config.yaml`'s unread
`warn_on_deprecated` (D6).

## Open questions carried from the spec

- **Q2** — `declining` counts toward coverage in this plan (`countable` is
  false only for `superseded` and `retracted`). One line to change if the
  owner prefers otherwise.
- **Q3** — the cost of a first review pass is measured, not estimated here:
  T013 reports cycles and dollars for working through a fixture's backlog
  and extrapolates to a 700-note vault at its update share.

## Order and risk

T001–T004 add fields, the store's origin, the sweep and the scout's report;
nothing is dispatched differently yet. T005 adds the settings and the mode
switch with the update share still unused. T006–T008 are the behaviour
change: update batches, outcomes and their gate, the verifier rule. They are
the tasks most likely to disturb the batch loop's existing accounting, so
each carries end-to-end tests with the fake agent, and the quality harness
(`build.sh --quality`) is run after T008. T011 migrates every live vault's
notes once and is rehearsed on copies.
