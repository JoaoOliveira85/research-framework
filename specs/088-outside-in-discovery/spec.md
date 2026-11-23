# Feature Specification: Outside-in discovery — a pass that starts from the field, not from the vault

**Status**: planned — drafted and planned on 2026-11-23 from #52. Lands after
`087-note-currency-and-updates`, whose cycle split and update queue it uses.

**Spec**: `088-outside-in-discovery` · **Builds on**: `087` (the
`pipeline.cycle_split` discovery share, `split_quota`, the update queue and
`observe_update`), `084` (`pipeline/backlog.py`), `083`
(`pipeline/state_layout.py`) · **Issue**: #52 (owner) · **Companion**: #53 /
`087` (what the vault already holds is updated; this spec finds what it does
not hold)

---

## Why this spec exists

Every source of new topics in a cycle starts from text the vault or its spec
already contains:

- **Harvest**: wikilink targets that existing notes cite and that have no note
  yet. By construction these are names the vault already wrote down.
- **Coverage gaps**: unmet categories, described by the labels the spec author
  wrote. The scout prompt requires at least 70% of `topics_found.new` to fall
  in the cycle-focus categories (`templates/prompts/scout-prompt.md.j2`).
- **Proposed tangents**: at most two steps from the notes a cycle touched,
  advisory, and off in every shipped profile.

A vault therefore grows outward from its seed in small steps and never asks
the open question: what exists in this field that the vault has no word for?
In a moving field the successor to an idea usually arrives under a new name,
which is exactly what a search on existing names cannot find. `087` makes the
vault update what it knows; nothing makes it look for what it does not.

A spec author cannot fix this by listing what to look for: they can only name
what they already know.

A reader with no code access must be able to build, from this spec alone, a
pass that asks the field open questions, turns the answers into new topics or
updates, and records what it looked at and found nothing on.

## Scope

**In scope**: the discovery pass and its inputs; the rotation over the spec's
scope; the shape of what the scout reports; the deterministic gate that checks
it; how discovery rows become plan topics or update entries; the share of a
cycle reserved for them; the discovery ledger; what the reader-facing surfaces
say; the off switch.

**Out of scope**: new source modules or a search backend (the pass uses the
sources and tools the scout already has); judging whether a discovered idea is
*better* than what the vault holds (that is `087`'s challenge, on the update
it queues); changing the harvest, coverage-gap or tangent paths; a note field
for "the problem this note addresses" (`087` D4).

## User Scenarios & Testing

### User Story 1 — A topic the vault had no word for (Priority: P1)

A cycle's scout is given three of the spec's scope areas and asked what is new
in each. It reports an approach that appears in no note title, no backlog entry
and no spec label.

**Acceptance**: the row becomes a plan topic with provenance `discovery`, is
dispatched within the cycle's discovery share, and the cycle report says which
scope area it came from.

### User Story 2 — New material about something the vault already holds (Priority: P1)

The pass turns up a recent result about a topic that has a note.

**Acceptance**: no second note is proposed; one `new_material` update entry
exists for that note, carrying the source.

### User Story 3 — "Nothing new" is recorded, not assumed (Priority: P1)

The pass looks at a scope area and finds nothing recent.

**Acceptance**: the discovery ledger records that the area was checked in this
cycle, with the queries the scout reports having asked and a count of zero; a
later reader can tell "checked, nothing found" from "never checked".

### User Story 4 — Every scope area gets looked at (Priority: P2)

**Acceptance**: over successive cycles the pass visits the least recently
checked areas first; after `ceil(areas / per_cycle)` cycles every area has
been checked at least once.

### User Story 5 — Discovery cannot crowd out, or be crowded out (Priority: P2)

**Acceptance**: discovery rows never count toward the 70% cycle-focus rule or
the category-diversity gate; the number dispatched never exceeds the discovery
share; an unused discovery share falls to new topics as it does today.

### User Story 6 — Off means unchanged (Priority: P1)

**Acceptance**: with the discovery share at 0 the scout prompt has no
discovery section and a cycle plans the same work as before this spec.

### Edge Cases

- **A discovery row matches an existing note** → an update entry (`087`
  FR-001), not a new topic.
- **It matches a persistent reject** → dropped, counted in the ledger.
- **It matches an open backlog topic** → that entry is observed again; no
  duplicate.
- **It names a scope area it was not assigned** → dropped with a WARNING (the
  rotation is what guarantees coverage; a scout that ignores it defeats it).
- **It carries no source, or no publication date inside the window** → dropped
  with a WARNING and counted. The date's *shape and range* are checked; whether
  the page really carries that date is not something a script can know.
- **The scout reports no discovery section at all** → the areas it was assigned
  are recorded as "assigned, not reported" and come first in the next
  rotation; the cycle is not failed.
- **`research_mode: refresh`** → the pass still runs; its rows may only become
  update entries, never new topics.
- **A vault with one scope area** → that area is checked every cycle.
- **Simple-format specs** → `scope.include` lines are the areas.

## Requirements

### Functional Requirements

**The pass**

- **FR-001**: When the discovery share is above zero, each cycle's scout prompt
  MUST carry a discovery section naming `N` scope areas
  (`pipeline.discovery.areas_per_cycle`, default 3) and asking, for each: what
  appeared or changed within the window (`pipeline.discovery.window_days`,
  default 180), what is contested, and how practitioners now solve the problem
  the area describes. It MUST instruct the scout to search from the area's
  problem and NOT from the vault's existing note titles.
- **FR-002**: The areas MUST be chosen deterministically, least recently
  checked first (never-checked first, then oldest `last_checked_cycle`, then
  spec order), from `scope.boundaries` (detailed specs) or `scope.include`
  (simple specs).
- **FR-003**: The scout report MAY carry
  `topics_found.discovery: [{title, area, why_new, source_urls, published,
  coverage_category, proposed_filename}]` and
  `discovery_checked: [{area, queries, found}]`. `scripts/validate_cycle.py`
  MUST accept reports with and without them and check their shape when
  present.

**From rows to work**

- **FR-004**: A deterministic gate (`DG-001`) MUST check every discovery row:
  `area` is one of the assigned areas; `source_urls` is non-empty; `published`
  is an ISO date inside the window; `title` is non-empty. A failing row is
  dropped, logged at WARNING and counted; it never fails the cycle.
- **FR-005**: A passing row MUST be routed by its title key: an existing note →
  `observe_update(reason="new_material")` with its sources; a persistent
  reject → dropped; an open backlog topic → observed again; otherwise → a plan
  topic with provenance `discovery`.
- **FR-006**: Discovery rows MUST NOT count toward the cycle-focus rule or the
  category-diversity gate, and `topics_found.new` rules MUST be unchanged for
  the rows that are not discovery.
- **FR-007**: The cycle's quota MUST be split three ways. The discovery share
  is the cap on discovery topics dispatched; discovery topics the share cannot
  hold stay in the backlog as open topics (origin `discovery`); an unused
  discovery share falls to new topics. Under `research_mode: refresh` no
  discovery topic is dispatched.

**The ledger**

- **FR-008**: `_pipeline/state/discovery-ledger.json` (declared in the layout
  registry, tracked) MUST record, per scope area: `last_checked_cycle`,
  `times_checked`, `found_total`, `last_found_cycle`; and per cycle: the areas
  assigned, what the scout reported checking (`queries`, `found`), and the
  rows kept, re-routed and dropped with the reason. Written atomically after
  the scout step.
- **FR-009**: An area assigned and not reported MUST be recorded as such and
  MUST NOT have its `last_checked_cycle` advanced.

**What the reader sees**

- **FR-010**: The cycle summary and `./vault status` MUST say which areas the
  last cycle checked and how many rows were kept, re-routed to updates and
  dropped. `./vault health` MUST list scope areas never checked and areas not
  checked for more than `2 × ceil(areas / areas_per_cycle)` cycles.

**Compatibility**

- **FR-011**: With the discovery share at 0 the scout prompt MUST have no
  discovery section, no ledger is written, and the plan is what it was before
  this spec.
- **FR-012**: A vault whose settings predate this spec MUST get the defaults
  (`areas_per_cycle: 3`, `window_days: 180`) and the split it already has.

### Key entities

- **Scope area** — one `scope.boundaries` / `scope.include` line.
- **Discovery row** — one entry of `topics_found.discovery`.
- **Discovery ledger** — `_pipeline/state/discovery-ledger.json`.
- **Discovery topic** — a plan topic with provenance `discovery`; in the
  backlog, origin `discovery`.

## Success Criteria

- **SC-001**: An end-to-end cycle can dispatch a topic whose title shares no
  term with any existing note, backlog entry or spec label, and its report
  names the scope area that produced it.
- **SC-002**: After `ceil(areas / areas_per_cycle)` cycles every scope area has
  a ledger row with `times_checked >= 1`.
- **SC-003**: With the discovery share at 0, the three committed quality
  fixtures plan the same work as before this spec.
- **SC-004**: A discovery row about an existing note never yields a second
  note.

## Acceptance coverage

| User story | Evidence |
| --- | --- |
| US1 — A topic the vault had no word for | _(deferred to tasks.md)_ |
| US2 — New material about something the vault already holds | _(deferred to tasks.md)_ |
| US3 — "Nothing new" is recorded, not assumed | _(deferred to tasks.md)_ |
| US4 — Every scope area gets looked at | _(deferred to tasks.md)_ |
| US5 — Discovery cannot crowd out, or be crowded out | _(deferred to tasks.md)_ |
| US6 — Off means unchanged | _(deferred to tasks.md)_ |

---

## Known divergences

- **D1 — The pass is only as good as the scout's tools.** A vault whose
  sources are all `kind: strategy_hint` relies on the agent's own web search.
  This spec changes what the scout is asked, not what it can reach.
- **D2 — "Published inside the window" is declared, not verified.** `DG-001`
  checks the date's shape and range. The writer's note then cites the source,
  and the verifier's credibility rules apply to it as to any note.
- **D3 — A long scope line is a broad area.** Some specs carry twenty-line
  boundaries; the pass asks about each as written. Splitting areas is the spec
  author's choice.

## Open questions

- **Q1 — The default discovery share is 10%.** With a cycle quota under 10 that
  rounds to zero topics in most cycles. The plan rounds the split by largest
  remainder and guarantees discovery one slot every `ceil(1 / share)` cycles
  while it has rows waiting; the owner may prefer a larger default.

## Assumptions

- The scout can search by recency with the tools it already has.
- One process mutates a vault at a time (as `084` assumes).
- Fixture vaults used to pin this spec are invented.
