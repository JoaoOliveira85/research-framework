# Implementation Plan: Outside-in discovery

**Spec**: [`spec.md`](spec.md) · **Tasks**: [`tasks.md`](tasks.md) · **Builds
on**: `087` (cycle split, update queue), `084` (backlog store), `083` (state
layout). This branch is stacked on `087-note-currency-and-updates`.

## Summary

Each cycle, the scout is handed a few of the spec's scope areas, least
recently checked first, and asked what is new in them without starting from
the vault's own titles. What it reports is checked by a script, routed to new
topics or to update entries, dispatched inside the discovery share of the
cycle, and recorded in a ledger that also remembers the areas where nothing
was found.

## Technical context

Python 3.11+, stdlib + `pyyaml` + `jinja2`; no new dependency (Principle V).
The pass is a section of the existing scout prompt, not a new stage: no new
dispatch surface (Principle IV), no extra agent call per cycle.

## Constitution check

| Principle | How this plan meets it |
| --- | --- |
| I — script-validated gates | `DG-001` checks every discovery row; rotation and routing are deterministic. |
| III — test-first | Every task carries its tests, authored before implementation. |
| IV — agent/script separation | The agent searches and reports; scripts choose the areas, check the rows and route them. |
| V — no new dependency | stdlib only. |
| VI — no duplicate notes | A discovery row about an existing note becomes an update entry. |
| XII — inspection does not mutate | `status` and `health` read the ledger; only the scout step writes it. |
| XIII — nothing accepted and ignored | The discovery share, which `087` accepts and folds into new topics, gains its consumer; both new settings keys are read (the settings-key guard proves it). |

## Design decisions

1. **Module** `src/research_framework/pipeline/discovery.py`: `scope_areas(spec)`,
   `choose_areas(ledger, areas, n)` (never checked, then oldest, then spec
   order), `evaluate_rows(report, assigned, window, today)` (the `DG-001`
   checks), `route_rows(vault, spec, rows, cycle)` and the ledger
   (`load_ledger`, `record_cycle`). The ledger path comes from `state_layout`
   (`discovery_ledger_path`, a new registry row).
2. **Settings** `pipeline.discovery: {areas_per_cycle: 3, window_days: 180}`,
   declared like `cycle_split`, added to every shipped profile.
3. **Prompt**: a "Discovery pass" section in `scout-prompt.md.j2`, rendered
   only when areas are passed, listing each assigned area verbatim with the
   three questions, the window's start date, and the output shape. It says
   explicitly: do not start from the vault's note titles; a finding about a
   topic that already has a note is reported with its sources all the same.
   `_template_version` bumped, corpus regenerated.
4. **Three-way split**: `split_quota` returns `(new_n, update_n,
   discovery_n)`. The discovery share is carried across cycles as a fractional
   credit in the ledger, so a 10% share yields one slot every ten quota units
   instead of rounding to zero forever (spec Q1). Unused credit is capped at
   one cycle's quota.
5. **Plan and batches**: discovery topics enter the priority queue with
   provenance `discovery` and their own category when the scout gives one.
   The batch loop dispatches at most `discovery_n` of them, ahead of other new
   topics; the rest are recorded in the backlog (`observe_topic`, origin
   `discovery`, a new origin in a minor schema bump) and wait.
6. **Gates**: `SG-001` and `SG-002` read `topics_found.new` only; the 70% rule
   in the prompt is restated as applying to `topics_found.new`. `DG-001` is a
   WARN-only gate recorded with the scout's other gates.
7. **Surfaces**: a discovery line in the cycle summary and in `status`
   (text and `--json`); a "Discovery" section in `vault_health`'s report.

## Order and risk

T001–T002 add the module, the ledger and the settings with nothing calling
them. T003 changes the scout prompt (rendered only when areas are passed).
T004 wires rotation, the gate, routing and the split into the cycle. The risk
is in T004's effect on the scout gates and the batch loop, which is why the
"share at 0 plans the same work" test runs on the three quality fixtures.
