---
spec_number: 050
title: Mandatory Vault Auto-Commit Invariant
status: SHIPPED 0.7.0
target_version: 0.7.0
shipped: 2026-06-01
created: 2026-06-01
amends_constitution: yes (1.3.4 → 1.4.0, new Principle X)
---

**Status:** shipped(2026-06-01, version 0.7.0) — SHIPPED 0.7.0 (2026-06-01) — `pipeline/vault_commit.py` + 24 lifecycle tests + orchestrator wiring + vault-shim verbs + constitution amendment all landed. `--leave-branch` flag / `auto_merge: false` override / `./vault reconcile-branches` verb explicitly deferred to a future minor (see "FUTURE follow-ups" at the bottom of this spec).


# Spec 050 — Mandatory Vault Auto-Commit Invariant

**Status:** DRAFTED — target 0.7.0

## Why this exists

A vault is its content. The framework is mostly stateless plumbing
around that content, plus a per-cycle structured trail under
`_pipeline/`. Up to 0.6.x, the only thing protecting users from a bad
research cycle, a botched framework upgrade, or a runaway agent was
manual hygiene: "remember to commit before you run things." This is
unsafe by default — every vault we have shipped on has gone through at
least one "the cycle ate my notes and I can't tell what changed" moment.

This spec promotes the existing voluntary `./vault sync` verb into a
**mandatory, deterministic, unskippable** part of every framework
operation that touches the vault. Auto-commit becomes the universal
defensive baseline: if you can roll a vault back via `git`, every other
recovery story (resume, revert, reconcile) becomes tractable.

## Scope

**In scope** (this spec):

1. A new pipeline module `research_framework.pipeline.vault_commit` that
   owns all auto-commit logic.
2. Constitutional amendment introducing **Principle X — Vault History is
   Append-Only Git (NON-NEGOTIABLE)**.
3. Wiring into every framework entry point that mutates the vault:
   - `./vault research` (per-cycle commits on a research branch,
     squash-merge on clean exit)
   - `./vault generate` (bootstrap commit on main)
   - `./vault update` / framework upgrade (commit framework upgrades)
   - `./vault ask` / `./vault write` (commit any output the command
     produced)
4. A documented failure model: commit failures WARN, do not fail the
   cycle; push failures WARN, do not fail the cycle; missing remote is
   a silent skip; dirty `main` on entry to a research run is a HARD
   STOP (the user has uncommitted work that must not be co-mingled).
5. Two new fields in `settings.yaml`:
   - `vault_commit.enabled: true` (default true; users may opt out for
     special-case vaults but the default is invariant-on)
   - `vault_commit.push_on_complete: auto` (`auto` = push iff remote
     configured; `never` = local-only; `always` = error if no remote)
6. Determinism: commit titles + bodies are Jinja-templated; same
   operation + same diff → same commit message.

**Out of scope** (deferred follow-ups, captured in §"Future"):

- Auto-merge override (`vault_commit.auto_merge: false`) and a
  `--leave-branch` flag for users who want the per-cycle granularity
  preserved even on success. **Captured in §Future#F1.**
- A `./vault reconcile-branches` verb to triage and squash leftover
  research branches in bulk. **Captured in §Future#F2.**
- Signed commits / commit-author override. Future-able once a clear
  need emerges; until then we use whatever `git config` is already in
  the vault.
- Multi-remote push fan-out (push to `origin` AND a backup remote).

## Principle X — Vault History is Append-Only Git (NON-NEGOTIABLE)

> Every framework operation that mutates the vault MUST land on disk as
> at least one git commit. Framework upgrades, research cycles, ad-hoc
> agent outputs, scaffold regenerations — all of them. The git history
> of a vault is the canonical, recoverable record of every change the
> framework has ever made to it. If a remote is configured, the
> framework MUST attempt to push (best-effort, never fatal). A user
> who wants to skip the invariant MUST opt out explicitly per-vault via
> `settings.vault_commit.enabled: false` — there is no implicit skip.

This principle exists because the framework runs unattended for hours
at a time, often with full filesystem write access, often through
sandboxed agents whose internal state is opaque. The git log is the
only artifact a future user (or a future agent) can replay
deterministically. Every commit becomes a checkpoint; every checkpoint
is reversible.

## Lifecycle: research run

```
./vault research [--resume]
        │
        ▼
┌────────────────────────────────────────────────────────────────────┐
│ vault_commit.begin_run(vault_dir, kind="research", resume=False)   │
│                                                                    │
│ 1. Require clean `main` (no uncommitted changes outside           │
│    _pipeline/). If dirty → HARD STOP, exit 2.                     │
│ 2. Resolve current branch.                                        │
│    - If already on `research/...` branch → reuse (resume case).   │
│    - Else → create `research/YYYY-MM-DD-HHMM[-NN]` from `main`.   │
│ 3. Record run metadata in _pipeline/run-commit-state.json.        │
└────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌────────────────────────────────────────────────────────────────────┐
│ orchestrator.run_cycles → for each cycle N:                        │
│   run_single_cycle(N)                                              │
│        │                                                           │
│        ▼                                                           │
│   vault_commit.commit_cycle(vault_dir, cycle=N, summary=...)       │
│   - title: "research: cycle N — <human summary>"                  │
│   - body:  added/updated/archived counts + coverage delta +       │
│            wall time + gate verdict + agent token spend           │
│   - on failure: WARN, do not crash; cycle still returns its rc.   │
└────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌────────────────────────────────────────────────────────────────────┐
│ vault_commit.complete_run(vault_dir, final_rc, final_reason)       │
│                                                                    │
│ - rc==0  (success)           → squash-merge research branch into  │
│                                main; commit msg = "research run   │
│                                <timestamp> — <N> cycle(s), <sum>" │
│                                Delete branch. Push if remote.     │
│ - rc==1  (constrained /      → stay on branch, log instructions   │
│           source-exhausted)    for the user (merge / drop /       │
│                                inspect). Push branch if remote.   │
│ - rc==2  (aborted mid-cycle) → reset --hard HEAD~1 on branch (if  │
│                                last commit was an aborted-cycle   │
│                                stub), stay on branch.             │
└────────────────────────────────────────────────────────────────────┘
```

### Resume semantics

`./vault research --resume` MUST detect an in-flight research branch
and reuse it. Resume from `main` is allowed only when there is no
in-flight branch; in that case `begin_run` creates a fresh branch.
Resume MUST NOT silently switch branches if the working tree is dirty
on the wrong branch — HARD STOP, exit 2, surface the situation.

## Lifecycle: framework upgrade

```
./vault update  (or install.sh re-run, or ./vault generate)
        │
        ▼
   vault_commit.commit_framework_change(
       vault_dir,
       title="framework: upgrade to <new_version>",
       body=changelog excerpt + scaffold diff summary,
   )
```

Framework upgrades commit directly on `main` — there is no branching,
because the upgrade itself is a recovery point and rolling back a bad
upgrade should be one `git revert` away. If the operation is destructive
(e.g. `./vault update` replaces scaffolding), `commit_framework_change`
runs *before* the scaffolding overwrite (capturing the pre-upgrade
state) AND *after* (capturing the result).

## Lifecycle: ad-hoc CLI output (ask / write)

```
./vault ask "<question>"     OR     ./vault write "<topic>"
        │
        ▼
   <command produces output: a draft note, an /ask answer, etc>
        │
        ▼
   vault_commit.commit_command_output(
       vault_dir,
       command="ask" | "write",
       output_paths=[paths the command wrote to],
       summary=one-line description,
   )
```

If the command produced nothing on disk, this is a silent no-op (the
invariant is "commit every change," not "commit on every invocation").

## Failure model

| Failure | Severity | Action |
|---|---|---|
| `git status` returns dirty `main` at run start | HARD STOP | Exit 2 with a guiding message ("commit or stash before re-running"). |
| Commit fails mid-cycle (e.g. git lock, disk full) | WARN | Log to `_pipeline/run-report.md`, write a sidecar `_pipeline/commit-failures-cycle-NNN.json`, **let the cycle's own rc stand**. |
| Push fails (no network, auth issue, remote rejection) | WARN | Log to `_pipeline/run-report.md`. The cycle / run rc is **not** affected. |
| No remote configured | INFO | Silent skip. The "always push" setting is the only way to escalate. |
| Squash-merge fails (e.g. merge conflict — shouldn't happen, we're squashing our own branch back) | WARN | Leave branch in place, log instructions for manual reconciliation. Exit code unchanged. |
| `vault_commit.enabled: false` in settings | INFO | All commit operations become silent no-ops. The vault still receives changes. This is an opt-out for users with esoteric workflows; default is `true`. |

## Commit message contract

Every commit message MUST start with one of these prefixes:

- `research: ` — per-cycle commits (on research branch)
- `research run: ` — squashed merge commits (back on main)
- `framework: ` — framework upgrade / scaffolding refresh
- `vault: ` — `./vault ask`, `./vault write`, manual scaffolding regen
- `vault sync: ` — fallback for the existing `./vault sync` verb (still
  supported, now goes through `vault_commit` under the hood)

The body MUST be human-readable Markdown and SHOULD include:

```
**Changed**
- N notes added
- M notes updated
- K notes archived

**Coverage**
- foo: 12/25 (+3 this cycle)
- bar: 4/10 (unchanged)

**Cycle health**
- wall time: 18m 22s
- gate verdict: PASS
- agent tokens: 12k in / 8k out
- $0.034 spent
```

This is rendered from a Jinja template living at
`templates/commit-messages/<commit-kind>.md.j2` so future shape changes
are localized.

## Settings surface

Two new keys in `settings.yaml`:

```yaml
vault_commit:
  enabled: true
  push_on_complete: auto  # auto | never | always
```

Defaults are `enabled: true`, `push_on_complete: auto`. Both are
explicit in the generated template so users always see them.

## Files affected

**New**
- `src/research_framework/pipeline/vault_commit.py` (~400 LOC)
- `templates/commit-messages/research-cycle.md.j2`
- `templates/commit-messages/research-run.md.j2`
- `templates/commit-messages/framework-upgrade.md.j2`
- `templates/commit-messages/vault-output.md.j2`
- `tests/pipeline/test_vault_commit.py` (~25 cases)

**Modified**
- `src/research_framework/pipeline/orchestrator.py` — call
  `begin_run` before the cycle loop, `commit_cycle` after each cycle,
  `complete_run` on every exit path.
- `src/research_framework/cli/research.py` /
  `research_resume.py` / `research_generate.py` — pass through the
  invariant config.
- `templates/vault-script.sh.j2` — `ask` and `write` verbs grow a
  post-hook calling `commit_command_output`; `update` and the
  existing `sync` verb route through `vault_commit`.
- `install.sh` / `dist-templates/install.sh` — call
  `commit_framework_change` after a fresh install or upgrade.
- `templates/vault-config.yaml.j2` — emit the new `vault_commit:`
  block in generated `settings.yaml`.
- `src/research_framework/spec/schema.py` — recognize and validate
  the new settings block.
- `.specify/memory/constitution.md` — add **Principle X**, bump to
  1.4.0, prepend Sync Impact Report.
- `CHANGELOG.md` — `[0.7.0]` entry under a new heading.
- `CLAUDE.md` — Recent Changes block.

## Testing strategy

Six categories of tests live in `tests/pipeline/test_vault_commit.py`.
All hermetic — they use a fresh `git init`'d temp directory as the
vault and never touch the real network.

1. **Branch lifecycle**: `begin_run` on clean main → creates the
   research branch; second `begin_run` on the same branch (resume)
   reuses it; `begin_run` on a dirty main → exits 2.
2. **Per-cycle commits**: `commit_cycle` produces exactly one commit
   per call; commit title/body match the template; staged-but-not-
   committed files end up in the commit (not skipped).
3. **Squash-merge on success**: `complete_run(rc=0)` collapses N
   cycle commits into one on `main`; the research branch is deleted;
   exit unchanged.
4. **Constrained-exit branch retention**: `complete_run(rc=1)` leaves
   the branch in place and the cycle commits intact.
5. **Push behaviour**: with a fake "remote" (another bare repo on
   disk), `push_on_complete: auto` pushes; `never` does not; `always`
   on a no-remote vault produces a WARN but does not fail.
6. **Framework-change commits**: `commit_framework_change` produces
   a single commit on `main` with the right title format, even when
   no other changes have been made.

Additional cross-cutting:

- Linter test: every CLI entry point that mutates the vault has an
  AST-level call to a `vault_commit.*` function (catches regressions
  where someone forgets the hook).
- Smoke test (`build.sh`): a fresh `./vault generate` followed by a
  no-op `./vault research --resume` produces exactly two commits on
  main (bootstrap + a squashed-empty-cycle merge).

## Migration path

Existing vaults running 0.6.x already have their content under git
(it's installed by the scaffold). The 0.7.0 upgrade pathway is:

1. Run `./vault update` → upgrades framework to 0.7.0 → produces the
   first auto-commit (`framework: upgrade to 0.7.0 ...`).
2. The new `settings.yaml` is patched in-place to add the
   `vault_commit:` block (default-on).
3. The next `./vault research` run is the first one to use the new
   branch-and-squash flow.

No vault-content migration is needed; this is purely
defensive-infrastructure on top of existing data.

## Future (deferred follow-ups)

### F1 — `--leave-branch` flag + `auto_merge: false`

Some users (the project author, on a recent feeds-vault audit) prefer to
keep per-cycle granularity on `main` rather than squash-merging.
The follow-up is a CLI flag `./vault research --leave-branch` plus a
settings override `vault_commit.auto_merge: false` that flips
`complete_run(rc=0)` from "squash-merge and delete branch" to "leave
branch in place; emit a one-line summary commit on main referencing
the branch by SHA." Cheap; one additional code path in `complete_run`.

### F2 — `./vault reconcile-branches`

A verb to triage and clean up stale `research/...` branches. Lists
each unmerged branch, shows its last commit + cycle count, and offers
`merge`, `drop`, or `keep`. Useful for users who default to F1's
`auto_merge: false` and accumulate dozens of branches over time. Out
of scope for 0.7.0; revisit when the first user actually has > 10
unmerged research branches.

### F3 — Signed commits / commit-author override

`vault_commit.gpg_sign: true`, `vault_commit.author: "Name <email>"`.
Trivial to add when needed.

### F4 — Multi-remote push fan-out

`vault_commit.push_remotes: [origin, backup]`. Trivial to add when
needed.

### F5 — Enforcement lint + git-module consolidation *(absorbs the tombstoned spec 031, 2026-06-03)*

050 shipped the invariant *mechanism* (`vault_commit.py`) but not its
*enforcement*. A 2026-06-03 audit (originally scoped as spec 031,
"Project-Wide Git Boundary Helper") found:

- **No lint exists** for the "all vault-mutating git goes through one
  surface" rule — even though this spec's acceptance criteria reference
  a "linter rule" (see the CHANGELOG-annotation bullet). **6** modules
  currently run raw `git` subprocesses: `pipeline/vault_commit.py`
  (the sanctioned one), `pipeline/vault_git.py` (legacy migrator
  snapshot helper — `is_git_repo`/`working_tree_dirty`/`snapshot_commit`),
  `prune.py`, `onboard.py`, `generator/scaffold.py`, `cli/_common.py`.
- **Two git modules coexist** — `vault_git.py` (spec-013 migrator
  lineage) alongside `vault_commit.py` (050). The "single point of
  policy" goal wants these consolidated, or at least the lint
  allowlisting exactly the sanctioned surfaces (vault-mutating →
  `vault_commit.py`; repo-setup like scaffold/onboard `git init` →
  explicitly allowlisted, since they are NOT vault-content mutations).
- **Coverage gap** — `commit_command_output` / `commit_framework_change`
  are defined but have no Python callers; ask/write/update commit via
  the bash shim (`vault-script.sh.j2`) rather than the Python invariant
  point. F5 should either wire the Python callers or document the
  shim-level wiring as the sanctioned path (and lint accordingly).

**F5 deliverable**: a deterministic guard (pytest, in the spirit of the
LLM-dispatch guard + spec 009's portability guard) that fails when a
non-allowlisted module under `src/research_framework/` issues a raw
vault-mutating `git commit` / `stash` / `reset` / `checkout -b`. Allowlist
= `vault_commit.py` (+ repo-setup `git init` sites by explicit annotation).
Plus a decision on `vault_git.py`: fold its three helpers into
`vault_commit.py` or formally scope it to migrator-only and allowlist it.

**Why a 050 follow-up and not its own spec**: a single lint + a small
consolidation pass is well under the bar for a standalone spec; spec 031
(which proposed building the helper 050 already shipped) is tombstoned
and points here. Schedule: opportunistic Wave-2/Wave-3; not rc1-gating
(the invariant *works* — F5 hardens it against future drift).

## Acceptance criteria

A 0.7.0 release ships this spec when ALL are true:

- [ ] `vault_commit.py` implemented and all 25 tests green.
- [ ] Constitution amended (Principle X, v1.4.0, Sync Impact Report).
- [ ] `orchestrator.run_cycles` integrates the three hook points.
- [ ] `vault-script.sh.j2` hooks `ask` / `write` / `update`.
- [ ] `install.sh` (root + dist-templates) calls
      `commit_framework_change`.
- [ ] `settings.yaml` template emits the `vault_commit:` block.
- [ ] CHANGELOG `[0.7.0]` entry exists and includes a regression-test
      annotation per the linter rule.
- [ ] `./build.sh` runs clean (smoke-gate produces the expected two
      commits described in §Testing#6).
- [ ] A fresh `./vault generate ... && ./vault research --resume` on a
      throwaway dir produces a `research/...` branch, one cycle
      commit on it, a squash-merge back on main, and a clean
      working tree.
