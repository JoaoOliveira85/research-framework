---
spec_number: 072
title: Land a completed run on main, and leave the operator there
status: SHIPPED [Unreleased] (2026-08-29)
target_version: post-1.0.0
created: 2026-08-27
---

**Status:** shipped(2026-08-29, PR #204) — SHIPPED (PR #204, commit `2b5093a`) — the constrained-exit landing
path is in `vault_commit.complete_run`.

# Feature Specification: auto-land a completed run on `main`

## Why

Every run opens `research/<date>-<time>` and, on exit, *leaves the vault on it*
with a note: "branch retained for review". The operator is then holding a
question the framework is better placed to answer — is this content good, and
should it be merged?

In practice the answer is almost always yes: the content passed the verifier,
the rejects were quarantined, the cycle committed. Yet five vaults spent this
session sitting on research branches, and the operator merged `feeds-vault` by
hand:

```
git checkout main && git merge research/2026-08-26-2054   # fast-forward
```

That worked and was correct. It should not have been theirs to do.

> *"once a pipeline run is complete (regardless the exit condition), if the
> content is good and validated let's remember to merge the new content into
> the main branch and checkout the main branch. It makes sense for the user to
> always be on the main branch and not having to guess if they should merge
> something or not"* — operator, 2026-08-27

## As shipped

The infrastructure already existed and was narrower than the draft assumed.
`complete_run` had `auto_merge` (default on), `_squash_merge` for rc=0 — which
already checks out the base branch, so "leave the operator on main" was solved —
and `_rewind_aborted_tail` for rc=2. **The only gap was rc=1.**

So the change is one branch: a constrained exit with committed content
squash-merges onto the base branch and leaves the operator there, retaining the
research branch.

**FR2 collapsed on contact with the code.** The draft agonised over defining
"good and validated". It turns out rc=2 returns *immediately* on an aborted
cycle, so a run that reaches rc=1 has, by construction, completed every cycle it
ran. The gate reduces to "did anything get committed?" — `ctx.cycle_commit_shas`
being non-empty. No health re-run, no marker scan, no new judgement.

**FR5 kept.** rc=0 deletes its branch (unchanged); rc=1 retains it. The
distinction is real rather than cosmetic: a clean exit means the vault is
complete and the branch has no further use, whereas a constrained exit left work
undone and its per-cycle history is worth keeping.

**FR4's key corrected.** The draft named the opt-out
`settings.yaml::auto_merge_research: false`; no such key was ever read. The
switch that ships is the pre-existing `vault_commit.auto_merge` (a
`vault_commit:` settings block, default `true`) — `_load_settings` in
`vault_commit.py` already owned it before this spec, and `complete_run` reads
the same flag it always did. Set `vault_commit.auto_merge: false` to keep the
review gate.

**FR3 is free.** `_squash_merge` already returns `ok=False` and retains the
branch on a merge failure, so a conflict stops rather than auto-resolving.

## Requirements (sketch, as drafted)

**FR1 — on run completion, land the branch on `main` and check `main` out.**
"Completion" is *any* terminal exit, not just rc=0: budget cap, max_cycles and
source-exhausted are designed terminal states (`_constrained_exit`), and the
content they produced is as valid as a clean finish.

**FR2 — "good and validated" needs a definition, and it is the crux.**
Candidate gate: the run's own signals — every cycle committed, quarantine swept,
no `cycle-NNN-aborted.json` for the cycles in this run, `./vault health` not
FAILING. An aborted final cycle (exit 2) is the obvious case to hold back.

**FR3 — fast-forward when possible, never a silent conflict.** Runs branch from
`main` and `main` does not move during a run, so fast-forward is the normal
case. If it is not (the operator committed to `main` mid-run), stop, stay on the
branch, and say so — never auto-resolve a conflict in someone's notes.

**FR4 — the operator can turn it off.** Some workflows genuinely want the review
gate. `settings.yaml::auto_merge_research: false`, defaulting to on.
*(As drafted; see "As shipped" above — the key that ships is
`vault_commit.auto_merge`.)*

**FR5 — it must be recoverable.** The branch is not deleted after merging, so a
bad landing is one `git reset` away.

## Open questions

### Branch retention is unbounded *(logged 2026-08-30 — left as-is)*

FR5 keeps the research branch after landing, so a bad landing stays recoverable.
It also means one branch per run, forever. The seven active vaults carry 14
between them already (`market-vault`: 5), all fully landed on `main`.

Left as-is by the operator — nothing is broken, and the clutter is cheaper than
losing a recovery path. Revisit if it becomes noise: cap at the last N per
vault, or prune landed branches older than N days. Any prune MUST verify the
branch's content is on `main` first; dropping unlanded work would defeat the
very FR it implements. Tracked in
#307 — not
`docs/TODO.md`, which is a scratchpad deleted on ship and the wrong home for a
follow-up on a shipped, frozen spec (#277).

**Resolved 2026-09-08 (owner decision D10, #307).** Retention is bounded by
two ceilings, both in `settings.yaml::vault_commit.retention`: `keep_last`
(default 5) and `max_age_days` (default 90). A *landed* branch is pruned
when it is beyond the newest-N window or its tip is older than the age
ceiling; `null` switches a rule off. The policy runs when a session starts
(`vault_commit.begin_run`) and after a run lands and the checkout is back on
the base branch (`vault_commit.complete_run`), each reporting what it pruned
in one INFO line; `scripts/prune_research_branches.py <vault> prune` is the
manual verb. FR5's caution holds unchanged: "landed" is verified by the
landing commit's `**Branch:**` marker on the base branch, an unlanded branch
is never a candidate, and a pruned branch's name is never reallocated to a
later run (the marker would otherwise make the new run read as landed).
Pinned by `tests/pipeline/test_branch_retention.py` and
`tests/pipeline/test_vault_commit.py::TestEveryCompletedRunReturnsToMain`,
`::TestRetentionAtSessionStart`, `::TestRetentionAfterLanding`,
`::TestPrunedNamesAreNeverReused`.



1. Where does this run? `vault_commit.complete_run` already owns the end-of-run
   git lifecycle and knows the exit reason — the natural home.
2. Does FR2's gate belong here or in the existing acceptance harness (spec 063),
   which already scores a run?
3. What about a run the operator interrupts (Ctrl-C)? Probably: leave the branch,
   since nothing decided the run was finished.
