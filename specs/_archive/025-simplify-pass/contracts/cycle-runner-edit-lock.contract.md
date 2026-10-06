# Contract: Cycle-Runner Edit Lock (B3 Coordination)

**Owner**: Spec 025 US6 B3 implementer (lock holder) +
spec 022 implementer (lock-aware).
**Status**: pinned at spec 025 plan time (2026-05-21).

Process contract for coordinating edits to
`pipeline/cycle_runner.py` during the long-lived
`025-b3-step-extraction` sub-branch window. Avoids merge
conflicts between B3's step extraction and concurrent 022 metric
hook attachment.

---

## § 1 — Why this contract exists

Q3a (locked 2026-05-21) chose a long-lived sub-branch for B3:
develop all three step extractions (scout, research, postprocess)
in `025-b3-step-extraction`, ship as one big PR. The architect
explicitly warned against this pattern in
`docs/SIMPLIFY-PASS.md` § 6 — long-lived branches drift, merge
conflicts compound, and review cost grows non-linearly.

The user accepted the trade-off for revert simplicity (one
`git revert` undoes all of B3). This contract documents the
mitigation: a **process-level edit lock** on
`pipeline/cycle_runner.py` during the sub-branch window.

The lock is **advisory**, not enforced by git. Discipline is the
mechanism. Bypassing the lock is not a constitutional violation;
it's a calendar risk.

---

## § 2 — Lock lifecycle

### 2.1 — Open the lock

The 025 B3 implementer creates the sub-branch:

```bash
git worktree add ~/src/research-framework-b3 \
    -b 025-b3-step-extraction 025-simplify-pass
```

In the SAME commit that opens the sub-branch, the implementer
adds a `CHANGELOG.md [Unreleased]` entry:

```markdown
## [Unreleased]

### Notes for in-flight work

- **pipeline/cycle_runner.py under refactor** (spec 025 US6 B3):
  long-lived sub-branch `025-b3-step-extraction` opened
  2026-MM-DD. Target ship: 2026-MM-DD+5 (per SC-015). Other PRs
  MUST NOT modify `pipeline/cycle_runner.py` until this branch
  ships. Coordinate via the branch's PR thread or a thread in
  the repo's discussions. See
  `specs/_archive/025-simplify-pass/contracts/cycle-runner-edit-lock.contract.md`.
```

This commit lands on `025-b3-step-extraction` AND is cherry-picked
or merged to `025-simplify-pass` (so the lock signal is visible
to anyone working off either branch).

### 2.2 — Hold the lock

While the lock is active:

1. **Spec 025 B3 implementer**: works in
   `~/src/research-framework-b3/` (the
   sub-branch worktree). Commits land on
   `025-b3-step-extraction`.
2. **Spec 022 implementer** (if 022 v1 is still in flight):
   does NOT touch `pipeline/cycle_runner.py` on main, 022, or
   any other branch. If 022 v1 needs cycle_runner.py changes
   (e.g. to add metric hook callsites at the pre-B3 seams), the
   change is staged in `025-b3-step-extraction` instead (the
   B3 implementer cherry-picks or merges it). 022 v2's metric
   hook retargeting happens AFTER B3 ships.
3. **Any other PR author** who finds themselves needing to
   touch `cycle_runner.py`: pauses, comments on the
   `025-b3-step-extraction` branch's PR thread, and coordinates
   with the B3 implementer.

### 2.3 — Weekly rebase cadence (SC-015)

Every Monday during the lock window (or every 7 days from
open, whichever is more frequent), the B3 implementer:

```bash
cd ~/src/research-framework-b3
git fetch origin
git rebase origin/main         # or origin/025-simplify-pass if 025 has merged-in PRs ahead of main
```

Resolves conflicts immediately. The lock policy means there
SHOULDN'T be conflicts in `cycle_runner.py` itself; any
conflicts are bugs in lock discipline.

### 2.4 — Close the lock

When B3 is ready to ship:

1. Run `./build.sh --quality` locally; confirm exit 0 (Tier B
   gate per SC-014 — assumes 022 v1 has shipped per FR-016).
2. Open the ship PR from `025-b3-step-extraction` →
   `main` (or `025-simplify-pass` if 025 is shipping
   incrementally).
3. PR description splits the diff by step module (scout,
   research, postprocess) and includes before/after cycle output
   diffs from the `tech-lite` fixture (R1 mitigation 4).
4. After the PR merges, **remove the lock signal** from
   `CHANGELOG.md`:
   ```markdown
   ## [Unreleased]

   ### Notes for in-flight work

   - ~~pipeline/cycle_runner.py under refactor~~ (shipped
     2026-MM-DD as part of spec 025 B3 — see
     `specs/_archive/025-simplify-pass/spec.md` US6).
   ```
   (The strikethrough survives until the next release notes
   block is published, at which point the entry is removed
   entirely.)

5. Delete the B3 worktree:
   ```bash
   git worktree remove ~/src/research-framework-b3
   git branch -d 025-b3-step-extraction  # if merged
   ```

---

## § 3 — Escalation paths

### 3.1 — Lock exceeds 5 days (SC-015 soft target)

The B3 implementer posts a status update to the PR thread
explaining the slip. If the slip is "almost done, 1–2 more days",
no action needed. If the slip is "discovered unexpected
complexity, needs scope reduction", trigger Escalation 3.2.

### 3.2 — Lock exceeds 7 days (SC-015 hard escalation)

The B3 implementer escalates by:

1. Posting an escalation comment to the PR thread.
2. Reviewing the work-in-progress: which step modules are
   complete and tested, which aren't.
3. Considering split: ship the complete step module(s) as
   separate PRs to main; keep the rest in a continuing
   sub-branch (or defer per Q3b MVP fallback to spec 026).

The escalation is not punitive. Long-lived branch drift IS a
risk; surfacing it at the 7-day mark prevents a 14-day disaster.

### 3.3 — Concurrent edit need is unavoidable

If a critical issue requires touching `cycle_runner.py` (e.g.
production bug fix on main that can't wait for B3 to ship), the
process is:

1. The bug-fix author posts to the lock PR thread.
2. The B3 implementer either:
   a. Stages the fix in `025-b3-step-extraction` directly (1
      commit, no merge conflict because we're working in a
      common branch).
   b. OR temporarily releases the lock (uncommon): the
      bug-fixer lands on main, the B3 implementer rebases the
      sub-branch over the fix.

Option (a) is preferred because it concentrates `cycle_runner.py`
edits in one place during the lock window.

---

## § 4 — Why this contract is *advisory*

The lock is enforced by team discipline + CHANGELOG visibility,
NOT by git branch protection or pre-commit hooks. Justifications:

1. **Project size**: research-framework's contributor base is
   small enough that announcement-and-coordination is sufficient.
2. **Flexibility**: a hard git lock would block emergency
   bug-fixes; advisory locks handle that case via § 3.3.
3. **Cost**: implementing branch protection rules + pre-commit
   hooks for one file is more overhead than the value provides.
4. **Precedent**: other long-lived refactor branches in the
   project's history (e.g. the 0.2.33 rename) used the same
   CHANGELOG-announcement pattern successfully.

If lock discipline fails materially during the B3 window (e.g.
two parallel PRs both modify `cycle_runner.py` and create a
real conflict), the postmortem decision is whether to upgrade
to git-enforced locks for future long-lived branches. Until
then, this contract codifies the discipline.

---

## § 5 — Audit trail

After B3 ships, the spec 025 implementer captures the lock
window's outcome in a brief addendum to
`docs/SIMPLIFY-PASS.md` § 6 (the section the architect used to
warn against long-lived branches). Format:

```markdown
### 2026-MM-DD addendum: B3 long-lived branch outcome

The B3 sub-branch `025-b3-step-extraction` opened
2026-MM-DD and shipped 2026-MM-DD+N (target: 5 days, actual:
N days). Lock conflicts encountered: <count>. Lessons:
<2–3 sentence summary>. Recommendation for future long-lived
branches: <retain pattern | switch to incremental PRs |
add branch protection>.
```

This addendum is the source of truth for future spec authors
deciding whether to use the long-lived-branch pattern again.
