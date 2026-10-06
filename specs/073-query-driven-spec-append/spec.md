---
spec_number: 073
title: A query that finds new ground records it in the spec
status: SHIPPED v1.1.0 (2026-08-30)
target_version: 1.1.0
created: 2026-08-28
---

**Status:** shipped(2026-08-30, PR #201) — SHIPPED v1.1.0 (PR #201, commit `df3158f`) — `pipeline/spec_append.py`, hooked at `_cmd_cycle`.

# Feature Specification: query-driven spec append

## Why

A vault's `research.spec.md` is the only durable statement of what the vault
researches and which sources it trusts. Every path in the framework **reads**
it; nothing writes it. Verified 2026-08-28 across a live vault: `ask.md`,
`research.md`, `source_ledger.py`, `probe_runner.py`, `validate_spec.py` and
`check_abstraction.py` all read `research.spec.md`, and no command in
`.claude/commands/` or `scripts/` writes it.

That is correct for the *spec as contract*. It is wrong for the case the
operator hit:

> The operator asked a vault a question whose answer needed a topic and a
> source the spec did not declare. The research happened, notes were written —
> and the spec still does not know the topic was asked for or the source was
> used. The next run rediscovers nothing, and the credibility catalog never
> learns the domain.

Two consequences, both observed in this project:

1. **Sources used but never declared stay uncatalogued.** Spec 070 made an
   uncatalogued domain a quarantine reason (`IX-credibility-unresolved`). A
   query that pulls a good source therefore *creates future quarantines*
   unless a human remembers to add it to the spec by hand.
2. **Scope discovered by asking is lost.** `_pipeline/research-backlog.md`
   captures deferred *topics*, and orphan wikilinks are auto-promoted to
   coverage targets. Neither touches `data_sources`, and neither records that
   the operator asked for a new area at all.

## What this is not

**Not a rewrite of the spec.** The operator's own framing, and the right one:
regenerating a spec from a model's understanding risks drift — silently
dropping a boundary, an `out_of_scope` line or a credibility tier that was
argued over once and must survive. The spec is a human artifact.

So: **append only, into a dedicated section, never edit what is above it.**

## Design

### 1. One managed section, at the end

Appends land in a single fenced region of `research.spec.md`:

```markdown
<!-- framework:discovered:begin -->
## Discovered by query

Appended automatically when a query needed ground the spec did not declare.
Nothing above this marker is ever modified. Promote an entry into the spec
proper by moving it and deleting it here.

### 2026-08-28 — Regional engineering consultancies
- **asked:** "which agencies do I enrol with for contract work"
- **sources used:**
  - `https://www.prodata.dk/` — primary — bureau's own consultant registration
- **topic:** contract-and-consultancy channel (employ vs B2B)
<!-- framework:discovered:end -->
```

The markers matter more than the format. They make the region machine-owned
and the rest human-owned, so a future append never has to parse or rewrite the
operator's prose.

### 2. What may be appended

Exactly three things, and nothing else:

| Kind | Appended when | Effect on the next run |
|---|---|---|
| `sources used` | a query fetched a domain absent from `data_sources` | **none until promoted** — see §3 |
| `topic` | a query asked for an area no `coverage_target` covers | **none until promoted** |
| `asked` | always, as the provenance line | none |

Nothing else. Not note types, not budgets, not `out_of_scope` — those are
judgements, and a query is not entitled to make them.

### 3. Appending is not adopting

**A discovered source does NOT become an active `data_source`, and a
discovered topic does NOT become a coverage target.** The append is a
*record*, and promotion stays a human edit.

This is the load-bearing decision. Auto-adopting a source would let a single
query silently widen what the vault trusts — precisely the drift the operator
asked to avoid, and worse than the current gap, because it would happen
without anyone reading it.

What the append buys is that the information is **written down where the next
person looks**, instead of living only in a chat transcript.

### 4. The credibility question, stated honestly

A discovered source has no `default_credibility`, because nobody has judged it.
It is recorded with `credibility: unassessed`, and spec 070's verifier
continues to quarantine notes citing it.

That is the correct outcome, not a bug: a source nobody has vetted should not
silently earn a tier. What changes is that the operator can now *see* which
unvetted source caused a quarantine, rather than reverse-engineering it — which
is exactly the triage problem this project hit, where 106 of 114 quarantined
notes carried no recoverable reason.

### 5. Idempotence

Re-asking the same question must not grow the file. An append is skipped when
an entry with the same normalised source URL or topic slug already exists in
the region. Same-day repeats update the existing entry's `asked` list rather
than adding a second block.

### 6. Where it hooks

The append is written by the same component that already knows a query
consulted a source — the source ledger — at the end of a query, not
mid-research. One write, atomic, through `atomic_write.write_text`, so a
crash mid-query cannot leave a half-written spec.

**The spec file is git-tracked in every vault**, so the append shows up in the
vault's own diff and can be reverted with `git checkout`. That is the safety
net, and it is why append-only matters: a revert of an append can never lose
human prose, because the append never touched any.

## Non-goals

- No rewriting or reordering of anything above the marker.
- No auto-promotion of a discovered source into `data_sources`.
- No credibility assignment for a discovered domain.
- No change to `research-backlog.md`, which keeps owning deferred topics.
- No new CLI surface. This is a side effect of asking, not a command.

## Acceptance

- A query that uses an undeclared domain leaves exactly one entry in the
  managed region, with the question that caused it.
- Asking the same question twice leaves one entry, not two.
- Everything above the begin-marker is byte-identical before and after —
  asserted, because it is the whole promise.
- A spec with no managed region gains one; a spec with one gains no second.
- A discovered source does NOT appear in `spec.data_sources` on the next
  parse, and a note citing it is still quarantined until a human promotes it.
- Removing the region by hand is safe: the next append recreates it.
- A malformed or hand-edited region fails loudly rather than being silently
  rewritten — the operator's edits are the point.

## Open question for the operator — answered conservatively

> Should an append also fire for a **full pipeline run** that consults a
> strategy-hint domain outside `data_sources`, or only for interactive queries?

**As shipped: only query-driven cycles** — those invoked with
`--target-topics`. A full backlog run records nothing.

That is the conservative reading, and it is cheap to widen later (one condition
in `record_query_discoveries`). Widening is a judgement about how much a spec
should accrete without anyone asking for it, which is the operator's call.

## Where the hook actually went

The spec said "the source ledger, at the end of a query". That component reads
*cycle artifacts*, and `./vault ask` runs `claude` interactively — there is no
Python end-of-query seam there at all.

But `.claude/commands/ask.md` step 2 escalates a question that needs new ground
by running:

```bash
research-framework cycle --vault . --cycle 1 --target-topics "<topic>" --budget-cap 2.0
```

So the query path *does* pass through `_cmd_cycle`, which is where the hook
lives. **Spec 074 was a prerequisite**: until it was fixed, that command
discarded `--target-topics` entirely, so a query-driven cycle did not even
research the right thing, let alone record it.

## Deviation from the §1 example

The illustrative entry in §1 shows a source recorded `— primary —`. §4 is the
normative text and says `unassessed`; the implementation follows §4. The
example predates that decision.

## Deviation from §5 (idempotence)

§5 says a same-day repeat "update[s] the existing entry's `asked` list rather
than adding a second block." As shipped, `_asked_already`
(`pipeline/spec_append.py`) compares the new question's slug against every
`asked` line already recorded and, on a match, `append_discovery` returns
`False` with no write at all — the existing entry is left exactly as it was,
never merged into. A repeat is idempotent (the file does not grow) but not
additive (a second phrasing of the same question does not join the entry's
provenance). Revisit if an operator needs every phrasing that hit an entry
recorded; today only the first survives.

## Deviation: `asked` records the topic, not the operator's question

The only caller, `record_query_discoveries`, has no operator question to
record — `.claude/commands/ask.md` passes the natural-language question
through as `--target-topics`, so the joined topic string is the only text
available at this layer: `Discovery(asked=topic, ..., topic=topic or None)`.
`asked` and `topic` therefore hold the same string. The rendered
`- **asked:**` line is accurate to what reached the CLI, not to whatever the
operator actually typed to `/ask`.

## Deviation: "fails loudly" holds at the write function, not at the CLI hook

§ Acceptance says "a malformed or hand-edited region fails loudly rather than
being silently rewritten." `pipeline/spec_append.py` keeps that promise at
the layer it owns: a malformed region raises `SpecRegionError` instead of
being repaired or overwritten (`tests/pipeline/test_spec_append.py`
`pytest.raises(SpecRegionError)`). The CLI hook that calls it
(`_cmd_cycle` in `cli/research_cycles.py`) catches that exception — and every
other one `record_query_discoveries` could raise — into a single
`[spec-append] skipped: <exc>` stderr line, with the cycle's own exit code
left unchanged. That is a deliberate, commented choice ("Best-effort by
design: the research has already succeeded, and a bookkeeping failure must
not change this cycle's exit code"), not an oversight: the append is a
best-effort side effect of a query that has already researched and written
its notes successfully, and failing the whole cycle over a spec-file
bookkeeping problem would discard real, successful work over a much smaller
one. At the operator surface this means a corrupted managed region is
reported (the stderr line names it) but does not stop the run — "fails
loudly" describes the write function's refusal to corrupt data, not the
CLI's exit code.
