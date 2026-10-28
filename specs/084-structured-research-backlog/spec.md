# Feature Specification: The research backlog as structured state

**Status**: planned — drafted 2026-10-28 from #18; clarify analysis done, four
owner decisions open (§ Open decisions). Low priority. Lands **after**
`083-durable-state-layout` (#10), whose `_pipeline/state/` directory it
writes into (Q1).

**Spec**: `084-structured-research-backlog` · **Depends on**:
`083-durable-state-layout` (the tracked `_pipeline/state/` directory and the
`.gitignore` that ignores the rest of `_pipeline/`) · **Amends**:
`003-topic-harvest-stage` (the backlog half of its harvest/propose output
contract), `062-vault-output-integrity` FR1 (where the quarantine pointer
lives), `058-vault-spec-health-warning` (which path is the control file) ·
**Issue**: #18

---

## Why this spec exists

`_pipeline/research-backlog.md` is three things at once: a queue several
writers append to, an input several readers parse with their own regular
expressions, and a file the operator edits by hand. Each writer owns a
comment-delimited block and promises to leave everything outside it alone;
each reader scans the whole file with a pattern of its own. Nothing defines
the grammar, so nothing keeps the writers and readers in step.

The evidence below was gathered from the code at `bc39eae` and from eleven
live vault backlogs (read-only). Every failure mode #18 reported is real, and
there are more than it named. Each was reproduced by a throwaway probe test
against the shipped functions (the probes are not committed; the acceptance
items below pin the corrected behaviour instead):

| # | Failure | Where | Reproduced |
| --- | --- | --- | --- |
| F1 | An operator line written inside the quarantine block is silently deleted on the next sweep — the sweep keeps only lines carrying a live `<!-- stem:… -->` tag, and it runs on **every** cycle exit | `orchestrator._reconcile_quarantine_block` | yes |
| F2 | `re-grade` removes only the `rewrite quarantined note:` pointer; the orchestrator's second grammar, `retry refresh of <stem> — …`, is never cleared by it | `cli/regrade._drop_backlog_pointer` | yes |
| F3 | `re-grade` matches by substring across the whole file: reinstating `deseq` also deletes the pointer for `deseq2` | same | yes |
| F4 | …and deletes an operator's own line anywhere in the file that happens to contain the phrase (e.g. "do not rewrite quarantined note: foo until Q3") — a writer reaching outside its block | same | yes |
| F5 | The planner queues only `— cited by N note(s)` bullets; the harvest's `— flagged by researcher` bullets (28–110 per live vault) are invisible to it, yet `topic_propose` and the scout prompt both see them | `research_plan._parse_orphans` vs `topic_propose._backlog_titles` | yes |
| F6 | A title wrapped across two lines (`- **Danish Kaffemote Coffee⏎Meeting Networking Norm** — …`, present in 7 of 11 live vaults) is read **with** the newline by the planner (`[^*]+`) and **not at all** by `topic_propose` (`[^*\n]+?`) | same pair | yes |
| F7 | An operator-added topic in any shape other than the harvest's bullet grammar is ignored by the planner — e.g. `ai-vault`'s hand-written `- [[X]]  *(cited by 24 note(s))*` list (≈200 lines) and `business-vault`'s Pending/Completed tables | `research_plan._parse_orphans` | yes |
| F8 | The harvest and the propose writers write the whole file non-atomically (`Path.write_text`); a crash mid-write truncates every operator line along with their own block | `scripts/topic_harvest.py`, `scripts/topic_propose.py` | by reading |
| F9 | The planner takes an orphan's citation count from its **oldest** sighting (first match wins), not its latest | `research_plan._parse_orphans` | by reading |
| F10 | Nothing is ever retired: every cycle appends a new harvest block, so live backlogs run to 700–1,500 lines of repeated, mostly stale entries; quarantine pointers written before #257's managed block (7 of 11 vaults) sit outside it, duplicated, and are never reconciled | all writers | live vaults |

Two claims in #18 do **not** hold and are corrected here so the plan does
not chase them:

- **`pipeline/steps/research.py` and `pipeline/_helpers/_io.py` do not touch
  the backlog.** `steps/research.py` reads `_pipeline/research-plan.md`;
  `_io.py` has no reference to it. `pipeline/stubs.py` only *documents* an
  obligation ("callers MUST … surface [an anchor-stub] in the
  research-backlog") that no caller fulfils — `classify_stub` has no callers
  (D2).
- **The loop-continuation decision does not read the backlog.**
  `orchestrator._harvest_followups` reads this cycle's
  `_pipeline/cycles/cycle-NNN-harvest.json`. The backlog reaches the loop only
  indirectly: the planner queues its orphans into the batches that are
  written, and the scout agent reads the whole file as required reading. Q2
  decides whether that stays so.

The fix #18 proposes is the right shape: one structured file, one module
that writes it, and a Markdown view that is rendered from it and never
parsed back. A reader with no code access must be able to build the store,
its writer API, its view and the migration from this document.

## Scope

**In scope**: the backlog's structured store and its shape; the single
module every writer and reader goes through; entry identity and the
operator-ownership rule; the rendered Markdown view and hand-edit detection;
migration of an existing Markdown backlog; the surfaces that name the
backlog's path (scaffold, `.gitignore` template, spec-058 control-file list,
scaffold manifest, scout prompt).

**Out of scope**: the `_pipeline/state/` directory itself, the rest of the
`.gitignore` rewrite and the `./vault update` step that rewrites an existing
vault's `.gitignore` (all `083`); what the harvest detects (wikilink
normalisation, coverage-gap computation — `003`); the planner's scoring
formula (`017` R-009) beyond which entries it reads (Q3); a CLI verb for
editing the backlog (operators edit the JSON); concurrent mutation of one
vault by two processes (§ Assumptions); surfacing anchor-stubs (D2).

## Clarifications

### Session 2026-10-28

Clarify analysis run without an interactive owner; each answer below was
resolved from code or live-vault evidence. Genuine owner decisions are left
as `[NEEDS DECISION]` under § Open decisions.

- Q: Are coverage-gap lines backlog entries? → A: No. They are a snapshot of
  `_pipeline/coverage-targets.json`, which owns them; `topic_propose` and the
  planner already read gaps from that file, only the scout reads the backlog
  copy, and they are the most numerous bullet kind in 9 of the 10
  framework-generated live backlogs. The view renders
  them live (FR-011, FR-017).
- Q: Who may change an entry an operator touched? → A: No writer may change
  its status or any field outside the writer's own (FR-007/FR-008).
- Q: Which citation count does the planner use for a carried-over orphan? →
  A: The latest (FR-012); today's first-match-wins reads the oldest (F9).
- Q: Are resolved entries pruned? → A: Not in this spec. They are kept with
  `status: resolved`; the store holds one entry per topic, so it grows with
  distinct topics, not with cycles (SC-004). A retention policy can follow
  if a store ever grows uncomfortably.
- Q: When does migration run? → A: Lazily, on the module's first access to
  a vault without a store (FR-020). It cannot wait for `./vault update`,
  because the cycle's vault-local scripts call the module first.
- Q: Is the original Markdown kept? → A: Yes, verbatim under `state/`
  (FR-022). Vaults scaffolded before 2026-08-27 git-ignored it, so git history
  is not a safe fallback.
- Q: What does a malformed store do to a cycle? → A: Writers leave it
  untouched and log `ERROR`; readers see no entries and log `WARNING`; the
  cycle continues, matching the best-effort contract the harvest, propose
  and quarantine steps already have (§ Edge Cases).

---

## Evidence: every reader and writer today

### Writers

| Writer | When | What it owns | Line grammar |
| --- | --- | --- | --- |
| `scripts/topic_harvest.py` (vault-local copy, run by `steps/postprocess.py` Step 7) | every cycle | `<!-- topic-harvest:cycle=NNN -->` … `<!-- /…-->`, one block per cycle, replaced on re-run of the same cycle | `## Harvest — cycle NNN (YYYY-MM-DD)`; `- **T** — cited by N note(s): \`p1\`, \`p2\`, \`p3\` (+k more)`; `- **T** — flagged by researcher`; `` - `category` [note_type] — met/target (required) `` |
| `scripts/topic_propose.py` (Step 7b, opt-in, off on every live vault) | every cycle when enabled | `<!-- topic-propose:cycle=NNN -->` block | `## Proposed tangents — cycle NNN (YYYY-MM-DD, agent)`; `- **T** ⚠️ (relation of [[parent]]) — justification` |
| `orchestrator._write_quarantine_backlog` (spec 062 FR1, #257) | every cycle exit | one `<!-- quarantine -->` block; drops any line without a live stem tag | `- [ ] rewrite quarantined note: STEM (verifier_status: rejected — reason) <!-- stem:STEM -->`; `- [ ] retry refresh of STEM — previous content restored, rejected draft quarantined (verifier_status: rejected — reason) <!-- stem:STEM -->` |
| `cli/regrade._drop_backlog_pointer` | `./vault re-grade` reinstates a note | nothing — filters the whole file | removes any line containing `rewrite quarantined note: <stem>` (case-insensitive substring) |
| `generator/scaffold.py` | vault creation, if absent | the file's seed | `---⏎_template_version: 1⏎---⏎# Research Backlog⏎⏎Topics deferred from scout passes.` (the harvest seeds a *different* header, without the frontmatter, when the file is missing) |
| Pre-#257 orchestrator (historical) | — | — | raw pointer lines appended outside any block; still present in 7 of 11 live vaults |
| Operators and per-vault agents | any time | — | anything: `ai-vault`'s `## A.2 — orphans surfaced …` wikilink list; `business-vault`'s Pending/Completed tables |

### Readers

| Reader | Reads | Pattern |
| --- | --- | --- |
| `research_plan._parse_orphans` → priority queue → batches | whole file | `^\s*-\s+\*\*([^*]+)\*\*\s+—\s+cited by\s+(\d+)\s+note` — first match per lower-cased title wins |
| `topic_propose._backlog_titles` and its prompt's `backlog_titles` | whole file | any `\*\*([^*\n]+?)\*\*` span |
| The scout agent (`templates/prompts/scout-prompt.md.j2`, required reading #4) | whole file, as prose | describes the Harvest and Proposed-tangents blocks only |
| `scripts/vault_health.py` `CONTROL_FILE_PATHS` (spec 058) | the path | warns when untracked or ignored |
| `scaffold._render_vault_gitignore` | the path | re-includes it under an otherwise ignored `_pipeline/` |
| `scripts/build_scaffold_manifest.py` `_USER_OWNED_PATTERNS`, `dist-templates/scaffold-manifest.json` | the path | `./vault update` never overwrites it |
| `orchestrator._constrained_exit` | the path | names it in the punch list |

---

## User Scenarios & Testing

### Story 1 — An operator's entry survives every writer (Priority: P1)

An operator adds a topic, or annotates or closes an existing one, by editing
the backlog file. Whatever the harvest, the quarantine sweep, `re-grade` or
the propose stage do afterwards, the operator's entry and every field they
set are still there, unchanged. A closed entry stays closed; a field the
framework does not know is kept.

### Story 2 — One grammar, so every reader sees the same backlog (Priority: P1)

The planner, the propose stage and the rendered view all read the same
entries through the same module. There is no pattern a writer can emit that
one reader sees and another does not, because there are no patterns: the
store is structured data with a version field.

### Story 3 — Harvest and carry-over (Priority: P1)

A cycle's harvest records each follow-on topic once. A topic harvested again
in a later cycle is the same entry, carried over: its first-seen cycle is
kept, its latest sighting and citation count are updated, and the number of
cycles it has been seen in grows. A topic whose note now exists is marked
resolved, not deleted.

### Story 4 — A readable view that cannot be mistaken for the source (Priority: P2)

The operator and the scout agent still read a Markdown backlog. It says, at
the top, that it is generated and names the file to edit. If someone edits
it anyway, the next render overwrites it and warns, naming the JSON file, so
the edit is not lost silently.

### Story 5 — An existing vault upgrades without losing a line (Priority: P1)

The first time the new module touches a vault that only has the Markdown
backlog, it converts it: every recognised bullet becomes a typed entry,
every line it does not recognise is carried verbatim, and the original file
is kept. Running it again changes nothing.

### Edge Cases

- **Malformed JSON after a hand edit** → no writer overwrites it. Writers
  skip their update and log an `ERROR` naming the file and the parse error;
  readers return no entries and log a `WARNING`. Cycle steps that are
  best-effort today (harvest, propose, quarantine pointer) stay best-effort:
  the cycle does not abort.
- **An entry added by hand without an `id`** → assigned one on the next
  write; the operator's fields are kept. Two entries with the same `id` → a
  malformed store (as above), never a silent merge.
- **A `schema_version` newer than the module knows** → read-only: readers
  read what they understand, writers refuse to write and log an `ERROR`
  (the spec-033 marker rule: a file whose shape this build does not know may
  carry fields it cannot preserve).
- **Both `research-backlog.md` and `research-backlog.json` exist on first
  run** → the JSON wins; the Markdown is treated as a view (hand-edit
  detection applies) and is not migrated again.
- **A stale vault-local `topic_harvest.py` / `topic_propose.py`** (the
  vault's `scripts/` copy predates this spec) → it writes the Markdown view
  directly; the next render detects the change, overwrites the view and warns
  as for any hand edit. Q4 decides whether the overwritten text is kept.
- **A title that differs only in case or internal whitespace** (F6) → the
  same entry.
- **The view is missing** (it is git-ignored, so a fresh clone has none) →
  rendered before anything reads it.

---

## Requirements

### Functional Requirements

**The store**

- **FR-001**: The backlog MUST be stored as one JSON document at
  `_pipeline/state/research-backlog.json`, tracked by git (`083`).
- **FR-002**: The document MUST carry a top-level `schema_version` and an
  `entries` array; each entry MUST carry `id`, `title`, `origin`, `status`,
  `first_seen_cycle`, `last_seen_cycle`, `seen_cycles`, `added` and
  `updated` (dates), and MAY carry origin-specific fields (`citation_count`,
  `cited_from`, `detail`, `parent_note`, `stem`) and any field an operator
  adds (§ Key entities).
- **FR-003**: `origin` MUST be one of `harvest` (a missing wikilink target),
  `researcher` (flagged by the research pass), `proposal` (Phase 2),
  `quarantine` (spec 062 rewrite or retry pointer), `operator` (hand-added)
  or `migrated` (a line migration could not type). `status` MUST be one of
  `open`, `resolved` or `dropped`.
- **FR-004**: An entry's `id` MUST be derived once, at creation, from its
  origin and its key — the title with internal whitespace collapsed and
  case-folded for topics, the note stem for quarantine entries — and MUST
  NOT change afterwards, even if the title is edited.
- **FR-005**: Every write MUST be atomic (the existing
  `pipeline/atomic_write` helper) and MUST be a read-modify-write of the
  current file, so no writer works from a stale copy.

**One writer**

- **FR-006**: Exactly one module in `src/research_framework/` MUST read and
  write the store. `topic_harvest.py`, `topic_propose.py`, the orchestrator's
  quarantine sweep, `re-grade`, the scaffold and the planner MUST go through
  it; a guard test MUST fail if any other file under `src/` or `scripts/`
  opens either backlog path for writing.
- **FR-007**: A writer MUST change only the fields its origin owns:
  `last_seen_cycle`, `seen_cycles`, `citation_count`, `cited_from`, `detail`
  and `updated` on entries of its origin, and `status` only from `open`. It
  MUST NOT delete an entry, MUST NOT reopen an entry whose status an
  operator set, and MUST NOT touch fields it does not own, including fields
  it does not know.
- **FR-008**: An entry is operator-owned when its `origin` is `operator` or
  `migrated`, or when its `status` was last set by hand; the module MUST
  record which (`status_by: operator | <writer>`), and an edit made outside
  the module is by definition an operator's.
- **FR-009**: The harvest MUST upsert one entry per follow-on topic (origin
  `harvest` or `researcher`) and mark `resolved` any open `harvest` or
  `researcher` entry whose note now exists in the corpus.
- **FR-010**: The quarantine sweep MUST upsert one `quarantine` entry per
  quarantined stem, carrying which of the two pointer kinds applies
  (`rewrite` or `retry`), and mark `resolved` an entry whose quarantine file
  is gone. `re-grade` MUST mark resolved exactly the entry whose `stem`
  equals the reinstated note's — both kinds, no substring match (F2–F4).
- **FR-011**: Coverage gaps MUST NOT be stored as entries: they are derived
  from `_pipeline/coverage-targets.json`, which owns them, and the view
  renders them live from it (§ The view).

**Readers**

- **FR-012**: The planner MUST read open entries from the store through the
  module, ordered by `first_seen_cycle` then insertion order, and score an
  orphan with its **latest** `citation_count` (F9). Which origins it queues
  is Q3.
- **FR-013**: The propose stage's duplicate check MUST compare against every
  entry's normalised title regardless of status, as it compares against
  every bold title in the file today.
- **FR-014**: The continuation trigger in `orchestrator.run_cycles`
  MUST keep today's per-cycle semantics — "this cycle's harvest found
  follow-on topics" — and MUST NOT become "the backlog has any open entry"
  (that would loop on topics no source can answer). Its source is Q2.
- **FR-015**: The `source-exhausted` exit message MUST stop saying "backlog
  empty" when what it checked was this cycle's harvest; the constrained-exit
  punch list MUST name the JSON file.

**The view**

- **FR-016**: Every write MUST re-render `_pipeline/research-backlog.md`
  from the store, and any step that reads the view (the scout prompt) MUST
  render it first if it is missing. The view MUST NOT be parsed by any code.
- **FR-017**: The view MUST open with a line stating it is generated and
  naming `_pipeline/state/research-backlog.json` as the file to edit, and
  MUST group open entries by origin in the scout prompt's priority order
  (harvest, researcher, quarantine, operator, proposal, migrated), followed
  by the live unmet coverage categories and a count of resolved and dropped
  entries.
- **FR-018**: Before rendering, the module MUST detect a view that changed
  since it was last rendered and, if so, log a `WARNING` naming the JSON
  file as the place to make the change, then overwrite the view.
- **FR-019**: The scout prompt template's required-reading item MUST
  describe the view's sections instead of the retired comment-delimited
  blocks.

**Migration**

- **FR-020**: When the store is absent and `_pipeline/research-backlog.md`
  exists, the module MUST migrate it on first access, before any read or
  write, and MUST be idempotent.
- **FR-021**: Migration MUST type every bullet in the grammars of § Evidence
  (harvest orphan, researcher-flagged, proposal, both quarantine pointers —
  inside or outside a block, deduplicated by stem), collapsing whitespace in
  wrapped titles. Every other non-blank line that is not seed boilerplate,
  a block marker, a block heading or a coverage-gap snapshot line MUST
  become a `migrated` entry carrying the line verbatim.
- **FR-022**: Migration MUST copy the original file byte-for-byte to
  `_pipeline/state/research-backlog.pre-migration.md` (tracked), because on
  vaults scaffolded before 2026-08-27 the Markdown backlog was git-ignored
  and has no history to fall back on.
- **FR-023**: Migration MUST log one `INFO` line with the counts per origin,
  the number of coverage-gap snapshot lines not carried (derivable), and the
  archive path.

**Surfaces that name the path**

- **FR-024**: The scaffold MUST seed an empty store (and its view) instead
  of the Markdown seed; the spec-058 control-file list, the scaffold
  manifest's user-owned patterns and the `.gitignore` template MUST name the
  JSON file instead of the Markdown one. `_pipeline/research-backlog.md` MUST
  end up ignored by git (by `083`'s single rule).

### Key entities

| Entity | Where | Notes |
| --- | --- | --- |
| Backlog store | `_pipeline/state/research-backlog.json` (tracked) | `{schema_version, entries[]}`; the only source |
| Entry | `entries[]` | `id`, `title`, `origin`, `status`, `status_by`, `first_seen_cycle`, `last_seen_cycle`, `seen_cycles`, `added`, `updated`; origin fields `citation_count`, `cited_from` (harvest), `detail` (researcher/proposal reason, quarantine reason, migrated line), `parent_note` + `relation` (proposal), `stem` + `kind: rewrite\|retry` (quarantine); unknown fields preserved |
| Backlog view | `_pipeline/research-backlog.md` (ignored) | rendered on every write; read by the scout agent and the operator; never parsed |
| Migration archive | `_pipeline/state/research-backlog.pre-migration.md` (tracked) | written once, never read by code |
| Harvest manifest | `_pipeline/cycles/cycle-NNN-harvest.json` (scratch, unchanged) | today's loop-trigger input (Q2) |

## Success Criteria

- **SC-001**: No sequence of framework writers can delete or alter an entry
  or field an operator added or set.
- **SC-002**: Every component that consumes the backlog sees the same set of
  entries; there is one definition of what an entry is.
- **SC-003**: Every live vault's backlog migrates with every non-derived line
  accounted for — as a typed entry or verbatim — and the original kept.
- **SC-004**: A backlog that has run 70 cycles holds one entry per topic, not
  one bullet per topic per cycle.

---

## Acceptance

Each item names behaviour a test can pin; the per-task test names are
authored into `tasks.md` before implementation (ADR-0010). Numbered so a
future coverage table can key on them (ADR-0012, "what closing this gap
would need", item 1).

1. A harvest run over a vault with two cited orphans and one
   researcher-flagged topic leaves three open entries (`harvest`, `harvest`,
   `researcher`) and a view listing all three.
2. Carry-over: the same orphan harvested in cycles 1 and 3, cited by 2 then
   by 5 notes, is one entry with `first_seen_cycle: 1`,
   `last_seen_cycle: 3`, `seen_cycles: 2`, `citation_count: 5`, and the
   planner scores it from 5.
3. A harvest run after the orphan's note was written marks its entry
   `resolved`; the entry is still in the store.
4. A hand-edited JSON entry — an `operator` entry with a field the module
   does not know, plus a `harvest` entry an operator set to `dropped` —
   survives, byte-equal in those fields, a harvest, a propose run, a
   quarantine sweep and a `re-grade`; the dropped entry is not reopened when
   the harvest sees its topic again.
5. A quarantine sweep after a note is reinstated marks that stem's entry
   `resolved`, for both the `rewrite` and the `retry` kind; `re-grade` of
   `deseq` leaves `deseq2`'s entry open (F2, F3).
6. Wrapped titles (`Danish Kaffemote Coffee⏎Meeting Networking Norm`) and
   case variants resolve to one entry, seen identically by the planner and
   the propose stage (F6).
7. A guard test fails when any file under `src/` or `scripts/` other than
   the backlog module opens `research-backlog.json` or
   `research-backlog.md` for writing.
8. Editing the view by hand and then running any writer overwrites the view
   and logs a `WARNING` naming `_pipeline/state/research-backlog.json`.
9. A malformed store is left byte-unchanged by every writer, each logging an
   `ERROR`; the cycle completes.
10. Migration of a fixture assembled from the shapes found in live vaults —
    harvest blocks with wrapped titles, a quarantine block, pre-#257 pointer
    lines outside it with a duplicate, a hand-written wikilink list, a
    Pending/Completed table — yields typed entries for every recognised
    bullet, a `migrated` entry for every other non-boilerplate line, an
    archive byte-equal to the input, and is a no-op on a second run.
11. A freshly scaffolded vault has `_pipeline/state/research-backlog.json`
    tracked and `_pipeline/research-backlog.md` ignored, asserted with real
    `git check-ignore` (as `tests/generator/test_scaffold_gitignore_control_files.py`
    does today).
12. The scout prompt renders with the view present and describes its
    sections, not the retired blocks.

### Retained behaviour that MUST stay green (re-pointed, not deleted)

| Behaviour | Pinned today by |
| --- | --- |
| Manual entries survive the harvest | `tests/scripts/test_topic_harvest.py::test_preserves_manual_backlog_entries` |
| Harvest and propose coexist | `tests/scripts/test_topic_propose.py::test_coexistence_with_phase1_backlog_block` |
| A quarantine pointer carries its reason, clears when its file is gone, and leaves manual entries alone | `tests/pipeline/test_rejected_note_handling.py::test_backlog_pointer_appended_with_reason`, `::test_pointer_clears_once_the_quarantine_file_is_gone`, `::test_manual_backlog_entries_outside_the_block_are_preserved` |
| Orphans reach the priority queue | `tests/pipeline/test_research_plan.py`, `tests/pipeline/test_research_plan_integration.py` |
| The control files are tracked, scratch is not | `tests/generator/test_scaffold_gitignore_control_files.py`, `tests/scripts/test_vault_health.py` |

The quarantine "lives inside a managed block" test
(`test_pointer_lives_inside_a_managed_quarantine_block`) pins a mechanism
this spec retires; it is rewritten against the store, not kept.

---

## Known divergences

Found while writing this spec, from the code at `bc39eae`. Recorded, not
fixed here.

- **D1 — The harvest reports false orphans for wrapped wikilinks.** A
  `[[…]]` broken across a line in a note body is compared, newline and all,
  against existing note stems, so a note that exists is harvested as
  missing (F6's source). FR-004's whitespace collapse plus FR-009's
  auto-resolve makes such an entry resolve itself; fixing the detection is
  `003`'s.
- **D2 — Anchor-stubs are never surfaced.** `stubs.classify_stub` says
  callers MUST surface an anchor-stub in the backlog; it has no callers.
  This spec leaves room (an origin can be added in a minor schema bump) but
  does not implement it.
- **D3 — The harvest and the scaffold seed different headers.** The harvest
  writes a header without the `_template_version` frontmatter when the file
  is missing. Retired by FR-016/FR-024: only the module renders.
- **D4 — Researcher-flagged topics fuel the loop but not the planner.**
  `_harvest_followups` counts them as continuation fuel; the planner never
  queues them (F5). A cycle can therefore continue on fuel only the scout
  agent might act on. Q3 decides.

## Open decisions

The rest were resolved from evidence (§ Clarifications). Four remain.

- **Q1 — Sequencing with `083`.** [NEEDS DECISION] (A) Hard dependency:
  `084` lands after `083`, which owns `_pipeline/state/`, the `.gitignore`
  rule and the `./vault update` step that rewrites existing vaults'
  `.gitignore`. (B) `084` may land first, creating `_pipeline/state/` and
  adding a narrow re-include for it that `083` later subsumes. *Recommended:
  A* — B writes the `.gitignore` template twice and leaves existing vaults
  with an untracked store until `083`'s update step exists. Either way `083`
  MUST classify `_pipeline/research-backlog.md` as *converted by 084*, not
  *moved into `state/`*.
- **Q2 — What the continuation trigger reads.** [NEEDS DECISION] (A) Keep
  reading this cycle's harvest manifest; the store is not a loop input.
  (B) Read the store: open `harvest`/`researcher` entries whose
  `last_seen_cycle` is this cycle — the same set, from the durable file.
  (C) Any open entry in the store — a behaviour change. *Recommended: A* —
  the trigger is a fact about this cycle, which is what the manifest
  records; B adds a dependency on the store's health (a malformed store would
  read as "no fuel" and could end a run as source-exhausted); C can loop
  forever on topics no source answers (FR-014 rules it out).
- **Q3 — Which origins the planner queues.** [NEEDS DECISION] (A) As today:
  `harvest` orphans only. (B) `harvest` plus open `operator` entries.
  (C) B plus `researcher` entries, scored as zero-citation orphans
  (`0.3`). *Recommended: B* — an operator adding a topic to the backlog
  expects it researched, and today that works only if they happen to type
  the harvest's exact bullet grammar (F7); C changes queue length on every
  live vault (28–110 entries each) and is better taken as its own decision
  once D4 is measured. `proposal` entries stay scout-only (they are
  advisory by `003` Phase 2's contract).
- **Q4 — What happens to a hand edit of the view.** [NEEDS DECISION]
  (A) Overwrite and warn (#18's definition of done, literally). (B) Also
  keep the overwritten text, once, at `_pipeline/research-backlog.md.overwritten`
  (ignored) and name it in the warning. *Recommended: B* — the operators
  most likely to edit the view are the ones with years of habit editing the
  old file, and a stale vault-local script (§ Edge Cases) writes there too;
  one ignored file costs nothing and turns "lost" into "recoverable".

## Assumptions

- `083` ships `_pipeline/state/` as the single tracked durable directory and
  ignores the rest of `_pipeline/`, as #10 describes; if its final layout
  differs, FR-001/FR-022's paths follow it.
- One process mutates a vault at a time (the runner and the cycle
  orchestrator already assume this; there is no vault lock today). FR-005
  makes each write atomic; it does not serialise two concurrent writers.
- The vault-local `scripts/topic_harvest.py` and `topic_propose.py` already
  import `research_framework` (they use `pipeline.atomic_write`), so routing
  them through the module adds no dependency. No new runtime dependency
  (Principle V): JSON is stdlib.
- Fixtures are invented from the *shapes* observed in live vaults; no live
  vault's content is checked in.
