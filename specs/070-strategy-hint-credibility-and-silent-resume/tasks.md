# Tasks — spec 070

> **Ledger** — this spec shipped; the boxes below are a historical record, not a live gate (CONTRIBUTING.md § 2). The Status header in `spec.md` is the source of truth for what shipped.

**Status: 2026-08-26 — Stages 0-3 done, Stage 4 dropped. T014 (FR2) was left
open here and shipped separately 2026-08-29 (PR #203); no items open now.**

Ordered. Stage 0 blocks everything: no other fix here can be verified until a
cycle can be run.

## Stage 0 — F5 (blocking)

- **T001** Reproduce the silent exit against a fresh throwaway vault, to
      establish whether it is state-dependent or reproduces from cycle 1.
- **T002** Bisect the three candidates in `plan.md` §Stage 0 (arg layer /
      resume precondition / swallowed exception). Record the cause in this spec
      — it is the one finding filed without a root cause.
- **T003** Fix the specific cause.
- **T004** Add the CLI-level guard: no non-zero exit may leave stdout AND
      stderr empty.
- **T005** Test: invalid resume invocation exits non-zero and writes >0
      bytes to stderr. Assert on the stream, not the message.

## Stage 1 — F1

- **T010** Determine the matching shape `normalise_source_id` needs for a
      bare origin to match a deep-path citation; reuse `credibility_catalog`'s
      matcher rather than adding a second rule.
- **T011** Index `data_sources[].url` into `default_by_source_id` when
      `default_credibility` is set.
- **T012** Test: strategy-hint source with `url` + `default_credibility`
      grounds a deep-path citation to its own host.
- **T013** Regression test: a source declaring `repos` is unaffected.
- **T014** FR2 — fail closed when `default_credibility` is declared but no
      citation-matchable key can be derived, naming the source. Filed
      DEFERRED here (see outcome note below); shipped separately 2026-08-29
      in PR #203 (commit `61c705f`), following the 069 FR1/FR2
      declared-but-unimplemented precedent as planned.
- **T015** Re-run the subject vault and confirm the 9 recovered notes pass
      verification WITHOUT their hand-added per-citation `credibility:` fields.
      That is the real acceptance test for this stage.

## Stage 2 — F2

- **T020** Decide: relax `github.com` to `min_segments: 1`, or add a
      profile entry. Apply the same decision to `gitlab.com` / `codeberg.org`.
- **T021** Test: `github.com/<user>` grounds; `github.com/<org>/<repo>`
      still grounds; bare `github.com/` does not.
- **T022** If the answer is "vault override", add the recipe to
      `quickstart.md` — the default currently excludes an entire note type in
      silence.

## Stage 3 — F3 / F4

- **T030** Single cycle-summary line: created, quarantined, net, one
      severity.
- **T031** Check whether the spec-068 incremental/recount divergence is the
      same miscount; fix in one place if so.
- **T032** Replace `no reason given` with the real reason, or an explicit
      statement that it is unrecoverable.
- **T033** Test: a cycle whose notes are all rejected reports written and
      quarantined, never `0 created` alone.

## Stage 4 — F6

- [ ] **T040** *(DROPPED — see below)* Report real notes vs alias redirects vs templates in the cycle
      summary or a `--counts` flag.

## Acceptance

- **T050** The subject vault (`community-vault`) runs a clean cycle
      that grounds long-tail citations with **no** hand-added per-citation
      `credibility:` and **no** `settings.yaml` override.
- **T051** `settings-override-example.yaml` is then deleted from this spec
      directory, or demoted to an explicitly-optional tuning example. While it
      is needed, FR1 is not done.


---

## Outcome notes (2026-08-26)

**T001/T002** — reproduced against a copy of the subject vault, not a fresh one:
the bug is state-dependent by nature (it needs completed cycles above the
ceiling). Cause was candidate 2 of `plan.md` §Stage 0, "resume precondition",
though not in the way expected: no precondition rejects anything. The resume
anchor simply lands above an absolute `max_cycles`, the loop range is empty, and
the fall-through narrates only at INFO.

**T010** — the answer was *not* to change `normalise_source_id`. That index is
exact-string-matched against the whole citation URL and other callers depend on
that. A separate host-keyed index sits alongside it, so the two matching rules
stay one each rather than becoming two overlapping ones.

**T014 (FR2) — deferred, not forgotten.** With `url`/`urls` parsed, the common
unbindable case no longer exists. The remaining one belongs at the 069
scaffolding gate that already validates source backing, so the fail-closed
policy stays in one place instead of being re-implemented here.

**Update 2026-08-29** — shipped at that gate as planned:
`source_backing.credibility_binding` plus `spec/validator.py`'s
`_validate_credibility_binding`, in PR #203 (commit `61c705f`). See spec FR2.

**T015/T050 — pass on a copy.** All 9 previously-quarantined notes resolve every
citation with the hand-added `credibility:` fields stripped, using
`source-grounding-migration.md`. Applying it to the live vault is an operator
action on operator data.

**T031 — checked, and they are NOT the same miscount.** The spec-068 divergence
(`incremental expectation 20 != disk recount 18`) is coverage-side and already
self-heals via `recompute_from_disk`. The quality-report accepted/rejected split
fixed here is a different counter with a different source. Fixing one does not
fix the other; both are now right.

**T040 — dropped.** F6 is explicitly "no defect": alias redirects behave as
ADR-0005 describes, and `./vault status` already reports real note counts via
spec 068's `recompute_from_disk`. Adding a second counting surface to guard
against misreading `find | wc -l` would add a maintenance burden for a problem
the existing verb already solves. Reopen if `./vault status` proves insufficient.
