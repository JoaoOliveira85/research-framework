# ADR-0012: The flat `## Acceptance` bullet format is not guard-enforced

**Status**: Accepted (2026-09-07)
**Date**: 2026-09-07
**Tags**: testing, spec-acceptance-coverage, guards, docs-corpus
**Evidence base**: issue #283 (guard fixed for the numbered-G/W/T discovery
and evidence-existence defects; this ADR records the part deliberately left
open). `tests/spec/test_acceptance_coverage_guard.py`.

## Context

ADR-0008's Spec acceptance coverage convention (`docs/testing-strategy.md`
§ Spec acceptance coverage) and its guard
(`tests/spec/test_acceptance_coverage_guard.py`) were designed around one
spec shape: `### User Story N` headings paired with numbered or bare
`**Given**/**When**/**Then**` scenarios, evidenced by a `## Acceptance
coverage` table keyed `US<N>`.

Specs since spec 061 have grown a second, lighter shape for narrowly-scoped
bug-fix specs (073, 074 are the current examples; the older 015b–015h/016
family predates the convention entirely and is separately grandfathered by
`docs/testing-strategy.md`'s non-retroactive rollout note): a flat
`## Acceptance` heading followed by plain bullets, no `### User Story`
structure, no per-bullet identifier, no coverage table:

```markdown
## Acceptance

- A phrase supplied via `--target-topics` appears in
  `_pipeline/cycles/cycle-NNN-scout-prompt.rendered.md`.
- A cycle run with target topics researches them ahead of backlog topics.
```

The guard's discovery regexes never match this shape (no `**Given**`
anywhere), so these specs are silently out of its scope — issue #283's
finding. Two ways to close that:

1. **Extend discovery** to the flat-bullet heading and require an evidence
   row per bullet (the issue's first suggestion). Doing this immediately
   pulls 10 pre-existing specs (015b, 015c, 015d, 015e, 015f, 015g, 015h,
   016, 073, 074) into scope with no coverage section, i.e. an instant
   red. Retrofitting honest, verified per-bullet test evidence for all ten
   — several from well before the current test layout, reorganized across
   at least two later refactors (025 Tier A/B, 049 cycle-helpers split) —
   is a research task in its own right, not a guard fix, and doing it
   under this issue would mean fabricating plausible-looking test
   citations I have not actually verified. That is worse than the current
   gap.
2. **Record the lapse here** and fix only what's mechanically safe: the
   numbered-G/W/T discovery bug and the missing test-existence check
   (issue #283's other two findings, both fixed in the same PR as this
   ADR).

## Decision

**Option 2.** The guard's enforcement scope stays G/W/T-only. The flat
`## Acceptance` bullet format is a recognized, real convention — it is
**not** currently guard-enforced, and this ADR is that fact recorded
rather than hidden behind a passing test that doesn't check what it looks
like it checks (the same complaint issue #283 raised about the pre-fix
regex).

## Consequences

**Good**
- No fabricated evidence rows. Every row the guard now checks (including
  the four newly-discovered specs 001, 002, 020, 021... — 020 backfilled,
  001/002/021 correctly left to the rollout's non-retroactive carve-out
  alongside 019) is either a real, existence-checked test path or an
  honestly-scoped historical/deferred note.
- The gap is discoverable: a future contributor grepping for "## Acceptance"
  guard coverage finds this ADR instead of assuming silence means covered.

**Trade-offs**
- Specs 073, 074, and the 015b-h/016 family remain unenforced for
  acceptance-scenario traceability. A regression in `pipeline/spec_append.py`
  or `cli/research_cycles.py::_cmd_cycle` that silently un-does 073/074's
  fix would not be caught by this guard — it would need to be caught by
  the tests those PRs actually shipped
  (`tests/pipeline/test_spec_append.py`, `tests/cli/test_cycle_target_topics.py`),
  which exist and are exercised by the normal suite; they are just not
  *linked* from the spec the way the G/W/T convention links its evidence.

## What closing this gap would need

A follow-up spec/issue, not a quick extension of this guard, because the
flat-bullet format lacks the one thing the current design leans on for
free: a stable per-scenario identifier. Concretely it would need:

1. A numbering convention for flat bullets (e.g. requiring `1.`/`2.` list
   markers, or an explicit anchor comment) so a coverage table has
   something to key rows on the way `US<N>` does today.
2. A decision on whether coverage is mandatory for *new* bug-fix specs
   going forward (cheap — one spec at a time, at time of writing) vs.
   retrofitting the ten existing ones (expensive, and only valuable if
   someone is prepared to actually verify each mapping against the real
   test suite rather than infer it from the bullet's prose).
3. Given (2), the pragmatic order is: enforce on new specs first
   (discovery + a coverage requirement, no retrofit), let the existing ten
   get grandfathered by the same non-retroactive rule ADR-0008 already
   uses for 001–019/021, and only backfill one when it is next
   substantively touched — mirroring FR-013's own precedent instead of
   inventing a new one.

## Alternatives considered

- **Extend discovery now and grandfather all ten newly-caught specs by
  name**, mirroring what this PR did for 001/002/019/021. Rejected: those
  four are grandfathered because `docs/testing-strategy.md` already,
  explicitly, by name, says so — that's implementing written policy, not
  inventing an escape hatch. Doing the same for ten specs the *convention
  itself has never applied to* would be inventing the exemption, not
  reading it off an existing ruling.
- **Suppress via the contract's evidence forms** (e.g. treat every bullet
  under `## Acceptance` as automatically satisfied by a single
  `_(historical)_`-style blanket note). Rejected: that produces a guard
  that always passes flat-bullet specs, which is functionally identical
  to not discovering them at all, dressed up as coverage.

## Relationship to other ADRs

- Narrows ADR-0008's Spec acceptance coverage convention: that ADR did not
  anticipate the flat-bullet shape; this ADR is the amendment recording
  where it does and doesn't apply, per ADR-0008's own "tightening via ADR"
  amendment process (`CONTRIBUTING.md` § 7).
- Does not supersede ADR-0008.

## Tests

- `tests/spec/test_acceptance_coverage_guard.py::test_mini_no_gwt_not_discovered`
  already pins "no G/W/T content ⇒ not discovered", which is exactly the
  behavior this ADR keeps for flat-bullet specs.
- No new test asserts flat-bullet specs are *skipped* by name (073, 074,
  015b-h, 016) — that would be pinning the gap as a feature. The gap is
  documented here instead; closing it is the follow-up in "What closing
  this gap would need" above.
