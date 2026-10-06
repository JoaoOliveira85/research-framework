# Tasks: The CLI contract

> **Ledger** — this spec shipped; the boxes below are a historical record, not a live gate (CONTRIBUTING.md § 2). The Status header in `spec.md` is the source of truth for what shipped.

**Spec**: [`spec.md`](spec.md) · **Status of the spec**: `shipped` — the
surface described there is the one that exists. These tasks are the follow-up
work § Known divergences identified.

## Phase 1: Stop documenting a verb that cannot run

- [ ] T001 Resolve `./vault write "<topic>"` (D2). Either ship the document
      generator the shim execs, or make the shim exit with the helpful error
      its original spec promised — and correct README and ARCHITECTURE,
      which both present it as shipped.

  ### Testing Requirements

  _Authored 2026-09-07, before implementation._

  - **Test 1**: `tests/generator/test_render_vault_shim.py::test_shim_write_verb_fails_loudly_when_unimplemented`
    - Behavior: invoke the rendered shim's `write` arm in a scaffolded
      vault; assert a non-zero exit and a message naming what is missing,
      rather than a bare interpreter error.
    - Tier: 3

  **TDD discipline**: required.

## Phase 2: Make the exit-code model true, or make it honest

- T002 Align unknown-verb handling across the two surfaces (D3).
      **Done**: the shim's fallback arm exits 2 (was 1) and writes to stderr.
      argparse already exited 2. A typo is a typo on either surface.
- T003 Make `prune` and `regenerate-agents` agree on what declining a
      confirmation prompt returns (D4). **Done: both return 1.**
      `regenerate-agents` already did; `prune` returned 0 and now signals the
      decline through a new `PruneResult.declined`. 1 is the model's
      "fail/terminate — this unit of work is over, move on", which is exactly
      what a declined prompt leaves behind: nothing was done. 0 would tell a
      wrapper the prune happened, and #249's unattended mode is a wrapper.
- T004 Give `wikilinks` and `re-grade` a way to signal a finding through
      the exit code, or record in this spec that they deliberately do not
      (D5). **Decided: they deliberately do not, and `./vault sync` now exits
      on purpose.**

      `wikilinks` and `re-grade` are *fixers*, not gates. A fixer that exits
      non-zero on a finding cannot be chained (`./vault wikilinks --fix &&
      ./vault sync` would stop on the run that did the most good), and the
      gate that must fail on note problems already exists and is `verify`.
      Their findings are on stdout and in `--json` — `wikilinks` emits
      `SweepActionRecord[]`, `re-grade` emits `reinstated` /
      `still_quarantined` / `skipped` — which is the documented channel for a
      count. `status` stays fail-open by its own FR-028.

      `./vault sync` was the real defect here: the arm had **no `exit` at
      all**, so it returned whatever the last command left, and the last
      command is an `|| echo` that always succeeds. It exited 0 by accident.
      It now exits with the commit's status deliberately: the commit is the
      contract, the push is best-effort, and a cron wrapper must not read
      "no network" as a failed sync.
- T005 Split `digest`'s malformed-date error from its empty-range result
      (D6): different causes, currently one message and one exit code.
      **Done**: a new `SinceError` carries the operator's own input, so a
      malformed or future `--since` exits **2** with a message naming the flag
      and the value; a legitimately empty range stays exit **0** on stdout and
      now names the window it looked at, so "wrong range" and "quiet vault"
      are distinguishable. The old behaviour was one message ("No cycles in
      scope") for all three.
- [ ] T006 Wire or delete the orphaned `schema acknowledge-drift` CLI (D7).
- T007 Replace ARCHITECTURE § 14's partial verb list with a pointer to
      this spec (D8). **Done 2026-09-10** — § 14 is now "shape, not the list":
      one entry point, one shim with 18 verbs, three exit codes, and this spec
      named as the owning document.

## On "publish the exit-code contract" (#248)

The issue asked for `docs/exit-codes.md` plus a lint. **The lint shipped; the
document did not, deliberately.** The exit-code table already has an owning
document — this spec's § Requirements — and a second copy in `docs/` is the
drift machine this release has spent its whole length dismantling (a roadmap
that restated the changelog, an ARCHITECTURE § 14 that restated the verb list,
a test count in six files). What was missing was never a reader; it was
enforcement. `tests/cli/test_exit_code_contract.py` walks every `_cmd_*` /
`cmd_*` function and fails when a non-zero return has no stderr write on the
path to it, with a reasoned allowlist for the returns that are deliberately
not errors. It is in `scripts/guards/run_all.py`'s battery.
