# Feature Specification: Note currency and updates — an existing topic is researched again

**Status**: planned — drafted 2026-11-22 from #53; clarified the same day
(owner decisions Q1–Q4, § Clarifications). Not yet on a release row.

**Spec**: `087-note-currency-and-updates` · **Builds on**:
`084-structured-research-backlog` (the queue an update entry lives in; drafted,
not merged), `079-note-format` (the frontmatter record), `082-spec-driven-verify`
(the one declaration of required fields), `068-coverage-counting-correctness`
(the count this spec narrows) · **Issue**: #53 (owner) · **Companion**: #52
(outside-in discovery; out of scope here, and the main feeder of this spec's
update queue once it exists)

---

## Why this spec exists

A topic keeps developing after its note is written: new studies, failed
replications, a changed consensus, a counter-argument, a successor that
replaces it. The pipeline treats a topic with a note as finished. That is true
of every domain, at different speeds.

At `1961f9a` (v2.0.1):

- **Existing notes are an exclusion list.** `pipeline/orchestrator.py` passes
  every existing note filename to `render_scout_prompt(...,
  exclude_topics=sorted(existing))`, and `templates/prompts/scout-prompt.md.j2`
  renders them under "Already covered — skip these".
- **Nothing queues an update.** `pipeline/research_plan.py` builds the cycle's
  queue from coverage gaps and harvested orphans and drops excluded titles. The
  writer prompt says "create or deepen" and the research report has
  `notes_updated`, but no step ever assigns a deepen; a note is touched only
  when a new topic happens to overlap it.
- **`research_mode` is accepted and ignored.** `spec/schema.py` defines
  `RESEARCH_MODES = ("bootstrap", "refresh", "expand")` and documents `refresh`
  as "depth-first currency; merge updates into existing notes only".
  `spec/validator.py` and `spec/simple.py` validate the value. No module under
  `pipeline/` reads `spec.research_mode`; `DataSourceConfig.applies_to()` and
  `phases` have no caller; `pipeline/settings.py` lists `research_modes` among
  its inert paths. This is a Principle XIII violation as shipped.
- **A note carries no date or standing the framework owns.**
  `templates/note-type.md.j2` stamps `type`, `template_version`, `source_urls`,
  `coverage_category`, `summary`. Writers often add `created`, `updated` and
  `status`; nothing requires them and no gate reads them.
- **Coverage counts notes, not current notes.**
  `pipeline/coverage.py::recompute_from_disk` counts every non-alias note, and
  `research_plan._select_cycle_focus` considers only unmet categories, so the
  most complete areas are the ones never revisited.
- **No relation says "replaced by".** `related` and wikilinks exist;
  nothing links a note to its successor.

The README says a vault "keeps itself current". Today it keeps itself growing.

**Why a vault's spec cannot fix it.** A spec author can add scope lines and
acceptance rules asking writers to state a standing and look for a successor.
That shapes only notes written from then on, depends on prose being followed,
and does nothing for the notes already in the vault. The mechanism has to be in
the pipeline.

A reader with no code access must be able to build, from this spec alone, a
pipeline in which new material about an existing topic reaches that topic's
note, and a note nobody has looked at for too long is looked at again.

## Scope

**In scope**: an update as a first-class work item; the currency fields a note
carries; a review interval per note type; the challenge a queued note goes
through and its four outcomes; the share of a cycle given to updates; what
`research_mode` does; what coverage counts; what `ask`, `coverage`, `health`
and `status` say about currency; migration of existing vaults.

**Out of scope**: how new material is *discovered* from outside the vault
(#52); the backlog store's format and its writers (`084`, which this spec
extends by one origin); the frontmatter codec (`079`); the `status` versus
`lifecycle` vocabulary question (`079` T003, `082` Q1 — this spec deliberately
uses neither key); splitting or merging notes; any change to how a *new* note
is written.

## Clarifications

### Session 2026-11-22

- Q: Which of #52 and #53 is specified and built first? → A: #53 (this spec).
  It fixes the notes a vault already holds, and #52's discovery pass needs this
  spec's update queue to hand its findings to.
- Q: Does a note marked superseded still count toward its coverage category's
  target? → A: No. Coverage means current knowledge; a category may fall below
  target when notes are superseded, which pulls research back to it.
- Q: How is a cycle's work split by default between new topics, updates to
  existing notes and open discovery? → A: 60 / 30 / 10, configurable per vault.
  Until #52 ships there is no discovery work, and its share falls to new
  topics (FR-016).
- Q: Which step may declare a note superseded or retracted? → A: The writer
  proposes the outcome with evidence; the existing verifier must pass it, and a
  supersession or retraction needs a primary or corroborated source. No new
  pipeline stage.

## User Scenarios & Testing

### User Story 1 — New material reaches the note it is about (Priority: P1)

An operator's vault holds a note on a topic. A later cycle's scout meets a new
study on that topic. Today the scout is told to skip it.

**Acceptance**: given a vault with a note `T` and a scout report that names new
material on `T`, the cycle queues one update entry for `T`, the writer revises
`T` in place citing the new source, the research report lists `T` under
`notes_updated`, and no second note for the topic exists.

### User Story 2 — A note nobody has looked at is looked at again (Priority: P1)

A note type declares a review interval. A note of that type passes it with no
new material having arrived.

**Acceptance**: given a note whose `as_of` is older than its type's
`review_after_days`, a cycle queues it without the operator naming it; after
the cycle the note carries exactly one recorded outcome and a new `as_of`.

### User Story 3 — A replaced idea says so, and points at its successor (Priority: P1)

The challenge finds, with a primary or corroborated source, that an approach
has been replaced.

**Acceptance**: the older note's `currency` is `superseded` and its
`superseded_by` names the successor; the successor's `supersedes` names the
older note; the older note no longer counts toward coverage; `./vault ask`
answers from the successor and says the older approach existed.

### User Story 4 — `research_mode` does what it says (Priority: P2)

**Acceptance**: `research_mode: refresh` yields a cycle with no new-topic work;
`bootstrap` yields one with no update work; `expand` uses the configured split.
A value the pipeline does not act on is refused at parse time, exit 2.

### User Story 5 — An existing vault upgrades without a flood (Priority: P1)

**Acceptance**: a vault written before this spec gains currency fields on first
run without any note's body changing, its oldest notes are reviewed first, and
no cycle spends more than its update share on review.

### User Story 6 — The operator can see how current the vault is (Priority: P2)

**Acceptance**: `./vault coverage` and `./vault health` report, per category,
how many notes are past review and how many are superseded; `./vault status`
reports the last cycle's outcomes by kind.

### Edge Cases

- **The challenge finds nothing new.** The outcome is `confirmed`: `as_of`
  moves, the body does not change, and the note records which sources were
  consulted. This MUST NOT be reported as an update that produced content
  (the "bookkeeping fraud" failure in `research_plan.py`'s own comment: a
  cosmetic frontmatter edit presented as research).
- **A "replacement" is the same idea renamed or absorbed.** The outcome is
  `revised`, not `superseded`: the note records the new name and the
  relationship. `superseded` is reserved for an approach practitioners have
  stopped using in favour of another.
- **The successor has no note yet.** The cycle queues the successor as a new
  topic and records `superseded_by` as a pending wikilink; the harvest
  (`084` FR-009) already turns a missing wikilink target into an entry.
- **The evidence for supersession is commentary only.** The verifier rejects
  the outcome; the note is recorded as `revised` with the claim attributed, or
  the entry stays open.
- **A note type with no review interval.** Never queued for review; still
  updated when new material arrives.
- **Two cycles queue the same note.** One open entry per note (`084` FR-004's
  id rule extended, FR-003).
- **A superseded note is itself due for review.** It is not queued; a
  superseded or retracted note is reviewed only when new material names it.
- **A vault with updates disabled.** Behaves as v2.0.1 (FR-020).
- **A hand-edited note.** The update preserves operator-authored text outside
  the sections it revises, by the same surgical rule the verifier's auto-fix
  already follows (`079`).

## Requirements

### Functional Requirements

**An update is work**

- **FR-001**: When scouting or research meets material about a topic the vault
  already holds, the pipeline MUST record an update entry for that note
  instead of discarding the finding.
- **FR-002**: The scout prompt MUST stop presenting existing notes as topics to
  skip. It MUST present them as topics that already have a note, with the
  instruction to report new material against the existing note and never to
  propose a second note (Principle VI is unchanged: the rule is "do not create
  a duplicate", not "do not look").
- **FR-003**: An update entry MUST be a `084` backlog entry with a new origin
  `update`, keyed on the note's stem (`update:` plus the stem), carrying
  `reason` (one of `new_material`, `review_due`, `operator`) and, for
  `new_material`, the source that prompted it. One open `update` entry per
  note; a second sighting updates the existing entry.
- **FR-004**: The planner MUST queue open `update` entries alongside new
  topics, within the share FR-015 gives them, ordered by: `new_material`
  before `review_due`; then oldest `as_of` first.
- **FR-005**: The writer MUST revise the note in place, cite every new source
  it used, and list the note under `notes_updated`. It MUST NOT create a new
  note for the same topic.

**Currency fields**

- **FR-006**: Every non-alias, non-exempt note MUST carry `as_of` (ISO date:
  the day its content was last checked against sources) and `currency` (one
  of `emerging`, `current`, `declining`, `superseded`, `retracted`). These
  join the single declaration of required fields (`082` FR-001) and are
  stamped by the note template.
- **FR-007**: A note MAY carry `supersedes` and `superseded_by` (lists of note
  references). A note whose `currency` is `superseded` MUST carry
  `superseded_by`. The relation MUST be symmetric: if `A.superseded_by`
  names `B`, `B.supersedes` names `A`.
- **FR-008**: The field name is `currency`, not `status` or `lifecycle`. Those
  two keys have an open vocabulary question (`079` T003) that this spec does
  not settle and MUST NOT make worse.

**Review**

- **FR-009**: A note type MAY declare `review_after_days` (positive integer)
  in `research.spec.md`. Absent means the type is never queued for review. The
  simple spec format accepts the same key on a `note_types[]` mapping.
- **FR-010**: At the start of a cycle, every note whose type declares an
  interval, whose `currency` is `emerging`, `current` or `declining`, and
  whose `as_of` is older than the interval, MUST have an open `update` entry
  with `reason: review_due`. Deriving this set MUST be deterministic and MUST
  NOT call a model.

**The challenge and its outcomes**

- **FR-011**: For a queued note the writer MUST search for what has changed
  since `as_of` — new results, contradictions, deprecations, successors —
  starting from the problem the note addresses and not only from its title.
- **FR-012**: Each worked update MUST end in exactly one outcome, recorded in
  the research report and on the entry: `confirmed` (nothing changed;
  `as_of` moves, body unchanged), `revised` (body changed; new source cited),
  `superseded` (FR-007), or `retracted` (the note's central claim is shown to
  be wrong; `currency: retracted`, the reason and source recorded in the
  note). An update the writer could not complete stays open with a reason.
- **FR-013**: The writer proposes the outcome; the verifier decides whether it
  stands. A `superseded` or `retracted` outcome MUST cite at least one source
  at credibility `primary` or `corroborated` (spec 055) that supports the
  replacement or the retraction itself. Without one, the verifier MUST reject
  the outcome, deterministically, and the note MUST NOT change `currency`.
- **FR-014**: A `confirmed` outcome MUST record the sources consulted, and
  MUST NOT be counted as a note created or as content produced in any yield,
  quality or coverage figure.

**The cycle's split**

- **FR-015**: `settings.yaml` MUST carry the share of a cycle's planned work
  given to new topics, updates and discovery, default `60 / 30 / 10`. Shares
  are of the cycle's planned topic count, rounded so they sum to it.
- **FR-016**: A share with no work to fill it MUST fall to the others rather
  than be left unspent: discovery's share goes to new topics until #52 ships;
  the update share goes to new topics when no `update` entry is open, and the
  new-topic share goes to updates when every coverage target is met.
- **FR-017**: `research_mode` MUST change what a cycle does: `bootstrap` — no
  update work; `refresh` — no new-topic work; `expand` — the configured split.
  The default for a vault that declares none is `expand`. `DataSourceConfig`
  `phases` MUST either be honoured by the same switch or be refused at parse
  time; it MUST NOT remain accepted and unread (Principle XIII).

**Coverage and what the reader sees**

- **FR-018**: A note whose `currency` is `superseded` or `retracted` MUST NOT
  count toward any coverage target.
- **FR-019**: `./vault coverage` and `./vault health` MUST report, per
  category, the count of notes past review and the count superseded or
  retracted. `./vault status` MUST report the last cycle's update outcomes by
  kind. `./vault ask` MUST say when an answer rests on a note that is past
  review, MUST follow `superseded_by` to the successor, and MUST NOT present a
  superseded or retracted note as current.

**Compatibility and migration**

- **FR-020**: With the update share set to 0 and no `review_after_days`
  declared, a cycle MUST plan the same work as v2.0.1, except that FR-002's
  prompt wording and FR-006's fields still apply.
- **FR-021**: On first run against a vault with notes lacking the fields, each
  such note MUST receive `as_of` from its newest `source_urls[].accessed`
  date (falling back to `updated`, then `created`, then the file's first
  commit date) and `currency: current`. No note body may change. The run MUST
  log one `INFO` line with the count migrated and the date range.
- **FR-022**: Migration MUST NOT queue more review work than the update share
  allows per cycle; the backlog holds the rest, oldest `as_of` first.

### Key entities

- **Update entry** — a `084` backlog entry, origin `update`: note stem,
  `reason`, prompting source, outcome when closed.
- **Currency** — a note's standing: `emerging`, `current`, `declining`,
  `superseded`, `retracted`.
- **Outcome** — the result of one worked update: `confirmed`, `revised`,
  `superseded`, `retracted`.
- **Review interval** — `review_after_days` on a note type.
- **Cycle split** — three shares in `settings.yaml`.

## Success Criteria

- **SC-001**: In an end-to-end cycle on a fixture vault with one note and a
  scout report naming new material on it, `notes_updated` has one entry and
  the note count is unchanged.
- **SC-002**: On a fixture vault with ten notes past review and an update
  share that allows three, exactly three are worked, oldest first, and seven
  entries stay open.
- **SC-003**: A `superseded` outcome backed only by a `commentary` source is
  rejected by the verifier in every run (deterministic, no model call).
- **SC-004**: After a supersession, the category's `met_count` is one lower and
  `./vault ask` on the topic cites the successor.
- **SC-005**: No settings key or spec field this spec touches is parsed and
  unread (`scripts/guards/` gains or extends a guard that proves it).
- **SC-006**: A vault with the feature switched off produces the same research
  plan as v2.0.1 on the three committed quality fixtures.

## Acceptance coverage

| User story | Evidence |
| --- | --- |
| US1 — New material reaches the note it is about | _(deferred to tasks.md)_ |
| US2 — A note nobody has looked at is looked at again | _(deferred to tasks.md)_ |
| US3 — A replaced idea says so, and points at its successor | _(deferred to tasks.md)_ |
| US4 — `research_mode` does what it says | _(deferred to tasks.md)_ |
| US5 — An existing vault upgrades without a flood | _(deferred to tasks.md)_ |
| US6 — The operator can see how current the vault is | _(deferred to tasks.md)_ |

### Testing Requirements

Per-task blocks belong in `tasks.md`, authored before implementation. Shipped
behaviour this spec keeps, which MUST stay green:

| Retained behaviour | Owner |
| --- | --- |
| Two notes for one concept never exist | Principle VI; the scout's `proposed_filenames` coordination |
| Alias stubs are never counted | `068` / `062` FR3 |
| `met_count` is derived on read from disk | `068` |
| Auto-fix and in-place edits are surgical | `079` |
| A vault's git history is append-only | Principle X — an update is a new commit, never a rewrite |

---

## Known divergences

- **D1 — This spec is written against a queue that has not merged.** `084`
  (drafted 2026-10-28, sequenced after `083`) replaces the Markdown backlog
  with a typed store whose entries carry an `origin`. FR-003 adds one origin
  to it. If `087` is implemented before `084` lands, the update queue needs a
  home of its own that `084` then has to absorb. See Q1.
- **D2 — `notes_updated` exists and is not trusted.** The research report
  schema already has the field; nothing validates it, and the v0.2.19 record
  shows cosmetic edits being reported as work. FR-012 and FR-014 are what make
  the field mean something; the plan MUST say which gate checks it.
- **D3 — Writers already write `status`, `created` and `updated`.** 237 of 271
  concept notes in one live vault carry a free-text `status`. FR-008 leaves
  those keys alone; FR-021 reads the dates and ignores `status`.
- **D4 — "Starting from the problem" (FR-011) has no field to read.** No note
  type today declares the problem a note addresses. The plan decides whether
  that is a required section, a frontmatter field, or derived from the note's
  summary.

## Open questions

- **Q1 — Order against `083` / `084`.** Recommended: land `083`, then `084`,
  then this spec, so the update entry is a `084` entry from the start. The
  alternative (ship `087` on the Markdown backlog, migrate later) is faster to
  first value and writes a grammar `084` then has to parse.
- **Q2 — Does a `declining` note count toward coverage?** This spec says yes
  (only `superseded` and `retracted` are excluded). The owner may prefer that
  `declining` also stops counting.
- **Q3 — What a first review costs.** A vault of 700 notes with a 90-day
  interval has every note due on day one. FR-022 bounds the per-cycle work;
  the plan should state the expected cycles and dollars to work through a
  backlog of that size, from the fixtures' cost-per-note.

## Assumptions

- The verifier can read a citation's credibility deterministically (spec 055,
  066), so FR-013 needs no model call.
- `source_urls[].accessed` is present on most existing notes; where it is not,
  FR-021's fallbacks apply.
- Fixture vaults used to pin this spec are invented; no real vault's notes are
  checked in to make a test pass.
- #52 will feed FR-001 through the same update entry; nothing here assumes how
  it discovers material.
