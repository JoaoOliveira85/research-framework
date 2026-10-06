---
spec_number: 074
title: research-framework cycle silently discards --target-topics
status: FIXED (2026-08-30) — bug reproduced, fixed, regression-tested
target_version: 1.0.1
created: 2026-08-28
---

**Status:** shipped(2026-08-30, PR #202) — FIXED (2026-08-30, PR #202, commit `e55023e`). Reproduced against
1.0.0 on a live vault, then fixed in `cli/research_cycles.py::_cmd_cycle`.
One acceptance bullet (spec/generate parity) was deliberately not met — see
"Relationship to the stranded branch" and the struck-through bullet under
"Acceptance" below.

## Fix as shipped

`_cmd_cycle` now loads `<vault>/research.spec.md` and passes it to
`run_single_cycle`, so the `spec is not None` guard at `orchestrator.py:552`
lets `_render_cycle_scout_prompt` run and the topics reach the prompt.

Two decisions worth recording:

- **Loaded, not validated.** The scout renderer needs a `SpecConfig`, not a
  conforming one, and hard-validating here would refuse vaults that have been
  running for cycles — the same over-strictness trap spec 070 FR2 hit. A spec
  problem severe enough to matter surfaces at its own gate.
- **Refuse rather than degrade.** If the spec cannot be loaded *and*
  `--target-topics` was given, the command exits 2 naming the file and the load
  error. Silently researching the backlog instead is what made this bug
  invisible for so long; a discarded flag must never look like success. Without
  the flag the spec-less path is unchanged.

# Bug: `cycle --target-topics` has no effect

## Reproduction

```bash
research-framework cycle --vault <vault> --cycle 27 --budget-cap 3.0 \
  --target-topics "Regional engineering consultancies ..." "..."
```

The cycle runs, spends its budget, and researches **its own backlog topics
instead**. The supplied strings appear nowhere in `_pipeline/` — not in the
rendered scout prompt, not in any cycle artefact. Verified by grepping the
whole `_pipeline/` tree for an exact phrase from the flag: zero matches.

## Cause

`cli/research_cycles.py::_cmd_cycle` calls `run_single_cycle` without a spec:

```python
return run_single_cycle(
    args.vault,
    cycle_num=args.cycle,
    budget_cap=args.budget_cap,
    resume=bool(args.target_topics),
    target_topics=args.target_topics,
)                                   # <- no spec=
```

`orchestrator.run_single_cycle` then guards the re-render on the spec being
present:

```python
if spec is not None and (resume or cycle_num >= 2):
    _render_cycle_scout_prompt(spec, vault_dir, cycle_num,
                               target_topics=target_topics)
```

`spec` is `None`, so `_render_cycle_scout_prompt` never runs and
`target_topics` is dropped on the floor. Every layer below this is correct —
`_rerender_scout_prompt` does prepend the supplied topics — so the flag is
accepted, documented in `--help`, threaded through two call layers, and
inert.

## Why this matters more than an unused flag

`--target-topics` is **the only mechanism for steering a cycle at a
question**, and the vault-local `/ask` command's Research Escalation section
tells the operator to use exactly this command when the vault cannot answer:

```bash
research-framework cycle --vault . --cycle 1 --target-topics "<topic>" --budget-cap 2.0
```

So the documented escalation path for "the vault doesn't cover this" spends
money and cannot work. An operator following the instructions gets a
plausible-looking cycle that researched something else, with no warning that
their topics were ignored.

Observed cost of discovering this: two cycles, ~$13, on a question neither
answered.

## Relationship to the stranded branch

`origin/fix/cycle-cmd-missing-spec-plan-regen` (2026-07-24, unmerged, no PR)
is titled *"fix(cycle): load+pass spec so research-plan is regenerated each
cycle"* and changes exactly this call site, with 78 lines of tests.

That branch was assessed on 2026-08-27 and **wrongly dismissed as
superseded**, on the grounds that `research_cycles.py:111` already calls
`load_spec`. Line 111 is inside `_regenerate_plan_only`, a different
function. `_cmd_cycle` still never loads a spec. The branch is the fix and
should be revived rather than deleted.

**Disposition, recorded 2026-08-30.** Not revived. The fix above was
implemented fresh in PR #202 (commit `e55023e`) without merging the branch.
PR #207 (commit `e7c7cd1`) then re-verified the branch as genuinely
superseded — its content had reached `main` by this independent route — and
deleted it along with three other stranded branches. The branch no longer
exists on `origin`.

## Fix

Load the spec in `_cmd_cycle` the way `_regenerate_plan_only` already does,
and pass it through. The branch above does this.

## Acceptance

- A phrase supplied via `--target-topics` appears in
  `_pipeline/cycles/cycle-NNN-scout-prompt.rendered.md`.
- A cycle run with target topics researches them ahead of backlog topics.
- **A missing or invalid spec fails the command loudly** rather than running
  a cycle that silently ignores the flag — the silence is the actual defect
  here, not the missing spec.
- ~~`cycle` and `generate` resolve the spec identically, so the two entry
  points cannot drift again.~~ **Not met, deliberately.** `_cmd_cycle` loads
  the spec but does not validate it ("Loaded, not validated" above);
  `_cmd_generate` (`cli/research_generate.py`) loads AND calls
  `spec.validator.validate`, exiting 2 on `SpecValidationError`. No shared
  spec-resolution helper exists. Parity was dropped on purpose — hard-validating
  in `cycle` would refuse a vault mid-run for the same over-strictness reason
  spec 070 FR2 hit — and this bullet should have been amended rather than left
  to read as met.

## Wider point

Two flags in this project have now been found accepted-but-inert
(`--target-topics` here; `source_policy: hard` was accepted-but-unsatisfiable
in three vault specs). Both cost real money before anyone noticed. A general
rule worth adopting: **an option that cannot take effect should refuse to
run, not run without it.**
