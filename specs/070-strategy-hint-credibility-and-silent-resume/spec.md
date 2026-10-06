---
spec_number: 070
title: strategy_hint sources cannot ground a citation, and resume fails silently
status: SHIPPED v1.0.0 (2026-08-27, PR #194, squash c81e990)
target_version: 1.0.0
created: 2026-08-26
source_input: |
  2026-08-26 build-out of a new vault, `~/Documents/vaults/community-vault`
  (people/communities/events/publications in a regional software
  scene). Spec declares 9 data_sources, ALL `kind: strategy_hint`, ALL carrying
  an explicit `default_credibility:` — the exact shape spec 069 FR1 blessed for
  sources with no backing module.

  Across 6 cycles the vault produced 15 real notes and QUARANTINED 9 — including
  every entity the vault exists to record (two practitioners, two conferences,
  one community instance). Every rejection carried the same verifier note:

      citation lacks credibility and no source default applies
      No explicit `credibility` field and no visible source default_credibility
      — cannot resolve a credibility level for this citation.

  The cycle summary reported "0 note(s) created" for cycles 4, 5 and 6 while
  notes were in fact being written and then rejected, so the run read as
  "nothing is happening" rather than "everything is being thrown away".

  A later attempt to resume the vault (`--resume`, with and without
  `--cycle N`) exits **1 with zero bytes on stdout and stderr**.
---

**Status:** shipped(2026-08-27, PR #194) — SHIPPED v1.0.0 (2026-08-27, PR #194, squash `c81e990`) — originally IMPLEMENTED 2026-08-26 — F1/F2/F3/F4/F5 fixed and verified; F7
added during implementation review. One follow-up remains open, listed under
"What is NOT done" below — FR2, filed there as deferred at ship time, shipped
separately 2026-08-29 in PR #203 (commit `61c705f`); see FR2 below. Findings
were re-verified in source before any change; three of them were sharper or
differently-rooted than this draft recorded, and those corrections are marked
**[REVISED]** inline.

**FR6 re-opened and re-shipped 2026-09-06** (issues #242, #243, #244). The
backstop shipped; the contract did not. `_constrained_exit` and the
source-exhausted exit narrated at `INFO`, `_resume`/`_run_phase3` rejected on
stdout, `--reject <stage>` exited 1 with zero bytes, and the guard itself
measured "any bytes anywhere" rather than "a reason was reported" — so all of
that could be true while the suite stayed green. See the FR6 block below for
what the requirement now means and how it is enforced.

# Feature Specification: strategy_hint credibility grounding + non-silent resume

**Feature Branch**: `070-strategy-hint-credibility-and-silent-resume`
**Created**: 2026-08-26

## Why this spec exists

Spec 066 built the credibility model so the verifier would "stop 100%-rejecting
honest project-canonical citations". Spec 069 established `kind: strategy_hint`
as the honest way to declare a source with no backing module. This vault used
both exactly as documented and still lost 9 of 24 notes — 37% — to
credibility rejection, and the losses were not random: they were the
practitioner and event notes, i.e. the vault's entire reason for existing.

The vault's subject makes it a good stress test. Its citations are, by nature,
long-tail: a Finnish conference's organiser page, a person's GitHub profile,
a Mastodon instance. That is not an unusual vault — it is what any
people-and-communities vault looks like — and the current model grounds
almost none of it.

## Findings (verified in source, 2026-08-26)

### F1 — `data_sources[].url` is never indexed for credibility

`vault/credibility.py::build_credibility_context` builds the URL → level index
(`default_by_source_id`) from **`ds.repos[].url` only**:

```python
if default:
    slug = _module_slug(getattr(ds, "name", ""))
    if slug:
        slug_default.setdefault(slug, default)
    for repo in getattr(ds, "repos", []) or []:          # <-- repos only
        for key in (getattr(repo, "url", ""), getattr(repo, "local_path", "")):
            norm = normalise_source_id(key)
            if norm:
                defaults.setdefault(norm, default)
```

A `kind: strategy_hint` source has no `repos` — that is the entire point of
069's strategy-hint concept: a source with no backing module. So its
`default_credibility:` reaches `slug_default` and `role_defaults`, but its
`url:` contributes **nothing** to the domain index the verifier consults.

**[REVISED 2026-08-26 — the root is one layer earlier than written above.]**
`DataSourceConfig` (`spec/schema.py`) had **no `url` field at all**. Every
`url:` in every vault spec was discarded at parse time, so `getattr(ds, "url")`
returned `""` and FR1 as originally worded ("index `data_sources[].url`") could
not be implemented. Confirmed live: all nine of the subject vault's sources
loaded with `url=''` while `research.spec.md` declares a `url:` on each. `url:`
was also not a documented field — it appears in no template or example — so the
author wrote a key that nothing rejected and nothing read. Fixed by adding
`url` (and `urls`, see FR1a) as additive optional schema fields.

**[REVISED — the role fallback is dead too, which answers Open Question 2.]**
`default_by_role` is built correctly (`{'domain': 'primary', 'behaviour':
'commentary'}` for the subject vault) but `build_source_role_index`
(`pipeline/source_authority.py`) is **also repos-only**, so `role_index.exact`
is empty and `resolve_role` returns `None` for every strategy-hint citation.
The correct level was already computed and sitting in the context, unreachable
for want of a citation→source key. Deliberately NOT fixed by binding roles to
source hosts: `off_field` downgrades a citation whose role differs from the note
type's `authoritative_role`, so making roles resolvable would silently
*downgrade* citations that currently resolve clean. Host-keyed grounding (FR1)
gets the same answer without that blast radius.

Net effect: `default_credibility` on a strategy-hint source is silently inert
for citation grounding. A spec author following the documented pattern gets no
error, no warning, and no grounding — the failure surfaces only later, as
quarantined notes whose message names a field the author *did* set.

### F2 — `github.com` is catalogued org-scoped, which excludes people

`data/credibility_catalog.yaml`:

```yaml
- { domain: "github.com", tier: tier_2, match_type: host_path, min_segments: 2,
    notes: "OSS hosting — org/repo scoped" }
```

Correct for citing a repository. Wrong for citing a **person**: a practitioner
note's natural evidence is `github.com/<user>`, one segment, which does not
match. A profile page is first-party evidence that someone ships code, and any
vault whose note type is "a person" will hit this.

### F3 — the cycle summary counts kept notes, not written notes

Cycles 4-6 each reported `0 note(s) created` while notes were written and then
quarantined. The operator-visible signal for "I wrote 4 notes and the verifier
destroyed all 4" is identical to "I found nothing". The quarantine count is
reported separately, at a different severity, in a different line.

This is what made the vault look like it had plateaued, and it is why the first
remediation attempted was *more cycles* — which cost money and could not have
worked.

**[REVISED 2026-08-26 — the "0 note(s) created" wording did not reproduce; a
different, verified miscount did.]** The vault's own artifacts show four entries
in `notes_created` for each of cycles 4-6 and `Notes created: **24**` in
`run-report.md`, so the created count was not zero. What *is* wrong, and is F3's
substance, is the accepted/rejected split: `pipeline/quality_report.py` derived
`notes_rejected` purely from a batch's `accepted` flag, so every cycle recorded
`notes_written: 4, notes_accepted: 4, notes_rejected: 0` while notes inside
those accepted batches carried `verifier_status: rejected` and were swept to
quarantine. Verified against `cycle-006-batch-001.json` (`accepted: true`, four
notes, three of them quarantined). Fixed so a note counts as rejected if its
batch was rejected OR the note itself is stamped rejected; `accepted + rejected
== written` now closes, which it did not before.

### F4 — required sources report "not searched: no reason given"

Every cycle emitted, verbatim:

```
WARN: required source 'w3c_community_groups' was not searched: no reason given
```

Five of nine sources, every cycle. 069 FR3/FR5 shipped the stagnant-source WARN
signal; this is that signal firing with its reason field empty, so it says a
source was skipped without saying why. As an operator signal it is unactionable:
it cannot distinguish "the researcher judged it irrelevant this cycle" from
"the fetch failed" from "the source was never offered to the agent".

### F5 — `--resume` can exit 1 silently

```
$ .venv/bin/python -m research_framework.cli generate \
    --spec <vault>/research.spec.md --output <vault> \
    --resume --max-usd 12 --max-cycles 3 > out.txt 2> err.txt
$ echo $?        # 1
$ wc -c out.txt err.txt   # 0, 0
```

Zero bytes on both streams. Reproduced with and without `--cycle N`, and with
and without a `credibility:` block in `settings.yaml`. The vault's
`_pipeline/state.json` is untouched by the failed invocation
(`in_progress_cycle: null`, `stage: postprocess` from the previous run), so it
fails before doing any work.

An operator cannot distinguish this from a crashed interpreter. Whatever the
cause, a CLI that refuses to run must say why — this is the highest-severity
item here, because it blocks every other remediation.

**[ROOT CAUSE FOUND 2026-08-26 — reproduced exactly, then fixed.]** Not a state
machine bug. Three things compose:

1. `_resolve_resume_cycle` anchors resume at `_highest_completed_cycle() + 1`.
   Six cycles had completed, so `start_cycle = 7`.
2. `max_cycles` is an **absolute ceiling**, not "run N more cycles", so
   `orchestrator.run_cycles` evaluates `range(7, 3 + 1)` — **empty**. The loop
   body never executes and control falls through to `_constrained_exit`, which
   returns 1. This also explains "reproduced with and without `--cycle N`":
   `range(4, 4)` is empty too, so any `--cycle N >= 4` behaves identically.
3. Every diagnostic in `_constrained_exit` is `_LOG.info`, and
   `cli/_log_level.py::_detect_default_level` drops the level to `WARNING` when
   `sys.stdout.isatty()` is false — which redirecting to a file makes false.

Hence exit 1, zero bytes, `state.json` untouched. The known-good contrast holds:
the earlier successful run had `cycles_budgeted: 8`, so `range(4, 9)` ran cycles
4-6. Verified by re-running the exact invocation on a vault copy: clean tree +
redirected stdout reproduced 0/0 bytes; adding `--log-level info` (the only
change) printed the full punch list.

Fixed in two places, neither altering an exit code or the control flow: an
`ERROR`-level diagnostic in `run_cycles` naming the anchor, the ceiling, its
source and the flag that raises it; and the FR6 backstop in `cli.main`.

### F7 — a hand-recovered note is swept straight back to quarantine [ADDED 2026-08-26]

Found while verifying F5, not present in the original filing.

`orchestrator._quarantine_rejected_notes` moves every note whose frontmatter says
`verifier_status: rejected` out of `data_vault/` on **any** exit. It keys purely
off that stamp and never re-verifies. The nine notes recovered by hand (see
"Recovery already performed") still carry `verifier_status: rejected` and were
left uncommitted on the `research/2026-08-25-2344` branch, so the next run
re-quarantines all nine — observed during reproduction:

```
WARN: rejected refresh of data_vault/06 - Sources/publisher_f.md reverted to
      last committed content; draft quarantined at _pipeline/quarantine/...
WARN: 9 verifier-rejected note(s) quarantined (uncitable/unindexed)
```

The manual escape hatch is therefore not durable, and an operator who repeats it
will lose the work again. **No code change made** — the sweep is behaving as
spec 062 FR1 designed it, and re-verifying inside the sweep would be a real
design change. The remedy is the verb that already exists for exactly this:
`./vault re-grade` (spec 066 FR4) re-evaluates quarantined notes against the
current credibility model and reinstates those that now resolve clean. Recorded
here so the recovery advice in this spec is not a trap.

### F8 — the simple spec format silently drops source annotations [ADDED 2026-08-26]

Found by running the 070 build against all five of the operator's live vaults.

`spec/simple.py::_data_sources` built each `DataSourceConfig` from a fixed
subset of keys. `kind`, `default_credibility`, `url`/`urls` and `local_path`
were not among them. Consequences, in order of severity:

1. **A simple-format vault could not satisfy spec 069's fail-closed
   source-backing precondition.** The gate's own message says
   `declared but has no implementation — ... annotate kind: strategy_hint`. In
   a simple spec the parser then discarded that annotation, so the vault was
   permanently blocked with **no legal way to comply**. `feeds-vault` was in
   exactly this state: 7 sources, every run refused.
2. A simple-format vault could never supply a source `default_credibility`, so
   the credibility model's source-default rung did not exist for it.
3. It could never ground a citation via FR1.

The same function already set `kind="strategy_hint"` on the *injected* default
`Web` source, so the field was known to matter — it just was not passed through
from user input. Same shape as F1: a key the author writes that nothing reads.

**Fixed** — the five fields now pass through. `feeds-vault`'s preconditions went
from 7 failures to clean, and it completed cycle 8.

### F9 — re-grade reinstated collision-renamed duplicates [ADDED 2026-08-26]

Found on the live `community-vault` run, and it is a data-integrity bug,
not a reporting one.

`_quarantine_rejected_notes` renames on collision: quarantining `foo.md` when
`_pipeline/quarantine/foo.md` already exists writes `foo-3.md` instead.
`./vault re-grade` then reinstated **both** copies under their quarantine
names, so a vault that quarantined the same note twice got `foo.md` and
`foo-3.md` side by side in `data_vault/` — byte-identical duplicates that
inflate the graph, the coverage recount and the note count.

Observed concretely: the vault re-quarantined its 9 F7 notes (once during the
cycle, once at finalisation), and the subsequent re-grade reinstated 18 files
for 9 notes. All 9 duplicates were verified byte-identical before removal.

**Fixed** — `duplicate_of_live_note` refuses to reinstate a copy when *both*
hold: stripping a trailing `-<digits>` names a note that actually exists in
`data_vault/`, and the two bodies are byte-identical. Deliberately conservative
in two directions: a legitimate title like `http-2` is safe unless an `http`
note also exists, and a genuine variant is never dropped. The duplicate is left
**in quarantine rather than deleted** — discarding content is the operator's
call, not the framework's.

### F10 — an aborted cycle counts as a completed one, so resume skips it [ADDED 2026-08-27]

The most consequential finding of the live validation, and a sibling of F5:
both are `--resume` anchoring bugs.

`_highest_completed_cycle` anchors resume on the highest
`cycle-NNN-quality-report.json` and documents the assumption that makes that
safe:

> A cycle that aborts mid-stream never writes the report, so we correctly fall
> back to the prior cycle as the resume anchor.

**That assumption is false.** Checked on all five live vaults; every aborted
(exit 2) cycle had written its quality report:

| vault | aborted cycle | report | recorded |
|---|---|---|---|
| feeds-vault | 9 | exists | `written: 11, accepted: 0, rejected: 11` |
| planning-vault | 6 | exists | `0 / 0 / 0` |
| community-vault | 11 | exists | `0 / 0 / 0` |
| market-vault | 24 | exists | `0 / 0 / 0` |
| reference-vault | 5 | exists | `written: 8, accepted: 8` |

So `--resume` advances **past** the aborted cycle and its work is never
retried. feeds-vault's cycle 9 had written 11 notes and had all 11 rejected; the
next resume would have skipped straight to cycle 10, abandoning them silently.
There is no operator-visible signal at all — which is what makes this F5's
sibling rather than a mere off-by-one.

**Fixed** — `mark_cycle_aborted` writes `cycle-NNN-aborted.json` on the exit-2
path and `clear_cycle_aborted` removes it when the cycle later completes
cleanly; `_cycle_aborted` makes the anchor skip a marked cycle. The stale
docstring claim is corrected in place rather than left to mislead the next
reader. Markers were backfilled on all five vaults, moving each anchor back
onto its aborted cycle.

## Functional requirements (sketch)

> **Implementation status.** FR1, FR1a, FR3, FR4, FR5, FR6 are **done**.
> FR2 (fail closed on an unbindable declaration) is **not done** — see
> "What is NOT done". FR-numbering below is as originally filed; FR1a was added
> during implementation.

**FR1 — a strategy-hint source's `url` grounds its own domain.** ✅ **DONE**
`build_credibility_context` MUST index `data_sources[].url` into
`default_by_source_id` when the source declares `default_credibility`, not just
`repos[].url`. A source that declares both keeps `repos` behaviour unchanged.

*As shipped:* a separate host-keyed index (`default_by_source_host`) rather than
`default_by_source_id`, because that index is exact-string-matched on the whole
citation URL — indexing a bare origin into it would have matched nothing, since
real citations carry deep paths. Host matching is exact and never a subdomain
wildcard. Consulted after the exact `source_id` index and before the 066
catalog, matching the order `docs/source-credibility.md` documents.

**FR1a — a source may declare more than one domain.** ✅ **DONE** *(added during
implementation)*
A strategy hint is routinely a *set* of domains: "Regional company engineering
blogs" spans alpha, bravo, charlie, delta and echo, and `url:` can name only
one of them. Without this, FR1 grounds the one representative host and
quarantines every other citation from the same declared source — which is most
of them. `urls: [...]` is additive and optional alongside `url:`. This is what
makes the acceptance criterion reachable; see `source-grounding-migration.md`.

**FR2 — declaring `default_credibility` that cannot bind is an error, not silence.**
✅ **DONE (2026-08-29)** — `source_backing.credibility_binding` classifies a
source `none` / `bound` / `unbindable`, mirroring the exact key order
`build_credibility_context` indexes so the gate and the resolver cannot
disagree. **FAILs at scaffolding** (`spec/validator.py` +
`scripts/validate_spec.py`), which is what this FR asked for, and **WARNs at
preconditions** rather than blocking an existing vault mid-life.

That split was forced by real data. Three of the six live vaults declare a
catch-all source — "Open web search" / "Web Search" — carrying a
`default_credibility` and, by nature, no enumerable domains. The declaration
*is* inert, so the gate is right to say so; but the intent behind it ("anything
I find by open search is commentary") is reasonable, and the framework simply
cannot attribute an arbitrary citation to that source today. Blocking those
vaults from running over it would be disproportionate. See Open Question 2 —
if a strategy hint's default ever applies to every citation in a note it
sourced, this becomes bindable and the WARN can be promoted.
If a source declares `default_credibility` and the framework can derive no
citation-matchable key from it, scaffolding MUST fail closed with a message
naming the source — the 069 FR1/FR2 precedent for declared-but-unimplemented
sources. Inert configuration is worse than rejected configuration.

**FR3 — the default catalog SHOULD ground person-scoped forge URLs.** ✅ **DONE**
(`github.com` / `gitlab.com` relaxed to `min_segments: 1`; `codeberg.org` added
at the same scoping; `sourceforge.net` / `bitbucket.org` deliberately left
org-scoped — they are project hosts, not profile hosts.)
Either relax `github.com` to `min_segments: 1` at `tier_2`, or add an explicit
profile entry. Same question applies to `gitlab.com` and `codeberg.org`. If the
answer is "vault override", then the quickstart MUST show that recipe, because
the current default silently excludes an entire note type.

**FR4 — the cycle summary MUST distinguish written from kept.** ✅ **DONE**
(as the accepted/rejected split in the quality report — see the F3 revision.)
Report created, quarantined and net for each cycle in one line, at one severity.
`0 note(s) created` while 4 were written and rejected is a false statement about
the run.

**FR5 — a skipped required source MUST carry a reason.** ✅ **DONE**
Replace `no reason given` with the actual cause, or state explicitly that the
researcher was never offered the source. If the reason genuinely cannot be
recovered, say *that* — it is at least true.

**FR6 — `--resume` MUST NOT exit non-zero silently.** ✅ **DONE**
(both the specific cause and the blanket CLI backstop.)
Every non-zero exit from the CLI MUST write a diagnosable message to stderr:
what was rejected, which file or state it came from, and what would make it
valid. A blanket guard at the CLI entry point is acceptable as a backstop, but
the specific cause behind F5 needs finding first.

*Re-opened and re-shipped 2026-09-06* — issues #242 (the rc=1 paths),
#243 (the guard measured the wrong property), #244 (a deliberate rejection was
reported as a framework bug). What FR6 means as enforced today:

| Obligation | Where it lives |
|------------|----------------|
| A non-zero exit reports its reason at `ERROR`, or by writing to stderr | every rejection path; `tests/cli/test_fr6_exit_reason_visibility.py` |
| The remedy — what would make it valid — rides at `WARNING` beside it | `_constrained_exit`, the source-exhausted exit |
| stdout does not discharge FR6 | `cli.main`'s backstop counts stderr bytes + `ERROR` records only |
| An unrelated earlier `WARNING` does not discharge it either | `_ReasonCounter`'s handler level is `ERROR` |
| A deliberate refusal (`--reject`) states what it refused and what it left behind | `cli/budget_resume.py`; `tests/cli/test_research_resume_approval.py` |

The `ERROR` floor is a deliberate narrowing of one reviewer's `>= WARNING`
suggestion: the two asks on #243 are mutually exclusive, and the one with a
demonstration (an unrelated `WARNING`, then a mute exit 1) requires the
stricter floor.

Still **not** enforced: verbs returning a structured failure (reason + file +
remedy) that `main()` renders uniformly. Until then FR6 is a per-path
obligation with a backstop, not a type. That refactor is the open half of this
requirement.

## Cross-references

- **spec 066** (credibility model calibration) — F1/F2/F3 are gaps in the model
  it introduced; the shipped catalog's rationale ("stop 100%-rejecting honest
  project-canonical citations") is exactly what regressed here for long-tail
  citations.
- **spec 069** (source-relevance tuning) — F4 is its stagnant-source WARN firing
  with an empty reason; F2 extends its declared-but-unimplemented fail-closed
  precedent to declared-but-unbindable credibility.
- **spec 068** (coverage counting correctness) — related but distinct. The run
  also emitted `coverage invariant divergence: incremental expectation 20
  (prior 16 + 4 created) != disk recount 18 — trusting recount`. The recount is
  right and the incremental expectation was counting quarantined notes as
  created, which is F3 seen from the coverage side.
- **spec 067** (acronym wikilink disambiguation) — no defect found. Alias
  redirect notes behaved exactly as ADR-0005 describes. Noted only because they
  inflate a naive `find -name '*.md' | wc -l` (17 files, 9 real notes), which
  cost an operator real time in this session; a counting helper that reports
  real vs alias would prevent the same misreading.

## Open questions

1. ~~**F5 root cause.**~~ **RESOLVED** — see the F5 root-cause block above.
   Not a state-machine bug: an absolute cycle ceiling below the resume anchor
   makes the loop range empty, and the fall-through narrates only at INFO.
2. ~~**Should `default_credibility` on a strategy hint apply to every citation
   in a note whose research came from that source**, rather than only to
   citations whose domain matches the source's own url?~~ **ANSWERED, and the
   answer is no — for now.** The role map that would carry this
   (`default_by_role`) is already correctly populated; only its *lookup* is
   unreachable, because `build_source_role_index` is repos-only. Binding it
   would also make `off_field` fire for strategy-hint citations, silently
   downgrading citations that currently resolve clean. Host-keyed grounding
   reaches the same levels without that risk. Revisit only with a deliberate
   decision about `off_field`.
3. **Is a wildcard floor acceptable for people-vaults?** **STILL OPEN**, but no
   longer load-bearing: `source-grounding-migration.md` closes the subject
   vault's long tail with exact host declarations plus path-scoped platform
   overrides, and needs no wildcard. Keep the question for a vault whose citation
   set is genuinely open-ended.
4a. **`--max-usd` is a CUMULATIVE LIFETIME cap, not a per-run one.** **NEW,
   found 2026-08-26 while validating the 070 build across five live vaults.**
   Same family as the `--max-cycles` trap below, and it bites harder because it
   is silent about *why*. `market-vault` has spent $132.36 over 21
   cycles, so `--resume --max-usd 10` — which reads as "spend at most $10 on
   this run" — trips the cap the moment the first cycle finishes:

   ```
   constrained exit — budget cap reached ($132.3569 ≥ $10.00)
   ```

   The message is honest once you read it, but the flag's *name* is not: every
   one of the five vaults (lifetime $14.10 / $30.72 / $15.53 / $132.36 / $70.00)
   trips a $10 cap immediately, so "give it a $10 budget" is unachievable
   through the flag. The operator has to know the lifetime total and pass
   `lifetime + N`. Either rename/document the semantics, or add a
   `--max-usd-this-run`. Filed rather than fixed — it changes an existing
   flag's meaning for every caller, exactly like the `--max-cycles` question.

4. **Should `--max-cycles` mean "N more cycles" on `--resume`?** **NEW.** Today
   it is an absolute ceiling, which is what made F5 possible. The silence is
   fixed either way, but the semantics are a separate product decision and were
   deliberately left unchanged — flipping them would alter the meaning of an
   existing flag for every caller.
5. **Should a declared source host that collides with a multi-tenant platform
   WARN?** **NEW.** `url: "https://github.com/"` with `default_credibility:
   primary` now grounds *all* of GitHub at primary for that vault. That is what
   the declaration says and it is honoured, but it is the one real footgun in
   FR1. `source-grounding-migration.md` documents it; a WARN was not added
   because it would be inventing policy this spec has not decided.

## What is NOT done

- ~~**FR2 — fail closed on an unbindable `default_credibility`.**~~ **Shipped
  2026-08-29** in PR #203 (commit `61c705f`), after this list was first
  written — see FR2 above (`source_backing.credibility_binding` +
  `spec/validator.py::_validate_credibility_binding`). Left here, struck
  through, so this section's own history stays visible instead of being
  silently rewritten out.
- **F7 — the quarantine sweep does not re-verify.** No code change; the
  remedy is `./vault re-grade`. See F7.
- **T015/T050 acceptance on the live vault.** Verified on a *copy*
  (9/9 notes ground with hand-added `credibility:` stripped). The real vault
  still needs the `urls:` migration applied and `./vault re-grade` run — an
  operator action on operator data, not a framework change.

## Recovery already performed (2026-08-26)

All 9 quarantined notes were recovered by hand and returned to the vault
(15 -> 23 real notes, quarantine empty). Each citation received the explicit
per-citation `credibility:` field the verifier asks for, graded by source type:
a practitioner's own site `primary` (first-party about the person, which is what
the note asserts), forge profiles `corroborated`, self-published platforms and
social `commentary`.

This is a **manual escape hatch, not a fix**, and it is the acceptance test for
FR1: when FR1 lands, those 9 notes must verify with the hand-added `credibility:`
fields REMOVED. Until then the vault is carrying by hand what the framework was
told, in its own spec, how to derive.

**[UPDATE 2026-08-26 — the escape hatch does not survive a run, and the
acceptance test now passes.]** The nine notes still carry
`verifier_status: rejected` and are uncommitted, so the next run re-quarantines
all nine (F7). Do not repeat the hand recovery — run `./vault re-grade` instead.

The acceptance test itself **passes**: with the `urls:` migration in
`source-grounding-migration.md` applied to a copy of the vault and the
hand-added per-citation `credibility:` fields stripped, all nine notes resolve
every citation (9/9). No wildcard, no per-citation edits — declared
configuration only.

## Evidence

Verified against `~/Documents/vaults/community-vault` at 2026-08-26:
15 real notes, 19 alias redirects, **9 quarantined**, $1.49 spent across 6
cycles. All 9 quarantined: `person_c`, `person_b`, `person_a`,
`conf_two`, `conf_four`, `community_e`, `publisher_f`,
`bravo_engineering_blog`, `charlie_engineering_blog`.

**The last two are the sharpest evidence for FR1.** `engineering.bravo.example`
and `engineering.charlie.example` are declared `data_sources` in this vault's
`research.spec.md`, each with `default_credibility: primary`. Notes *about
those very sources*, citing those very domains, were rejected for having "no
visible source default_credibility". A declared source cannot currently ground
a citation to itself.

A `settings.yaml::credibility.trusted_domains` override of 24 domains was
verified to resolve the F1/F2 citations correctly at the resolver level
(`conf-five.example` → primary, `github.com/person-d` → corroborated,
`github.com/org/repo` → corroborated unchanged) but could not be exercised
end-to-end because of F5. That override shipped alongside this spec as
`settings-override-example.yaml` — a workaround for F1/F3, not a fix — and was
removed once FR1 landed (T051), replaced by `source-grounding-migration.md`
(both in PR #194).
