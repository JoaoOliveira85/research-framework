# Research: `./vault update` Hardening (spec 027)

**Date**: 2026-06-03 | **Branch**: `027-vault-update-hardening`
**Theme**: *reconcile, don't reimplement* — establish the exact DELTA over the
already-shipped 0.7.0 (Principle X / `vault_commit.py`) and 0.8.0 (spec 051
`install.sh` hardening) surfaces.

This document is the audit the spec's Assumptions block calls for ("Audit during
planning"). It exists so `/speckit.plan` and `/speckit.tasks` build only the
non-duplicative remainder.

---

## 1. Audit: `src/research_framework/pipeline/vault_commit.py` (shipped 0.7.0)

The Principle X auto-commit module. **Public surface relevant to 027:**

| Function | Behaviour | 027 relevance |
|----------|-----------|---------------|
| `commit_framework_change(vault, *, title, body) -> CommitResult` | `git add -A` + commit **directly on the base branch** (`main`/`master`). Idempotent (returns `skipped_reason="no changes"` on a clean tree). Best-effort: never raises; `ok=False` on git failure. | **This is the FR-004 commit path.** Call it **twice** around the upgrade — its docstring (lines 656-661) already says "Called twice around destructive upgrades: once to capture the pre-upgrade state (idempotent if clean), once after." The post-call already exists in the shim; 027 adds the **pre-call** with a labelled subject. |
| `_load_settings` → `vault_commit.enabled` | Opt-out per vault. Disabled ⇒ all commits no-op (`skipped_reason="invariant disabled"`). | FR-004 snapshot inherits the same opt-out automatically — **no separate enable/disable flag for 027**. |
| `_ensure_repo` | Non-git vault ⇒ WARN + no-op (returns `ok=True, skipped_reason="not a git repo"`). | FR-004 degrades gracefully on non-git vaults for free (spec Assumption "non-git vaults degrade gracefully"). |
| `_is_dirty(vault, ignore_pipeline=False)` | Porcelain dirty check; can mask `_pipeline/`. **Private**, not exported. | FR-003's dirty-tree guard wants exactly this predicate. The shim currently has no Python entry point that exposes it. **Decision point** (see §4). |
| `begin_run` / `VaultCommitDirtyError` | Hard-stop for **`research`**, not `update`. Translated to exit 2 by CLI. | Confirms FR-003 is a *genuine gap*: the dirty-tree HARD STOP exists for `research` only. `update` has **no dirty guard at all** today. |

**Finding A1 — FR-004 reuses an existing, already-documented entry point.**
`commit_framework_change` was *designed* to be the pre/post upgrade snapshot pair.
The shipped shim only wires the **post** call (`vault-script.sh.j2` line 154:
`_vault_autocommit framework "upgrade to ${NEW_VERSION}"`). 027's FR-004 is purely:
add the **pre** call with subject `snapshot before update <old> -> <new>` *before*
any mutation (before `pip install`, before the archive fetch). No new commit
mechanism — forbidden by Clarification Q2.

**Finding A2 — the snapshot must be the immediate parent of the upgrade commit.**
For `git reset --hard HEAD~1` to roll back (SC-001, FR-011), the commit topology
must be: `… → [snapshot before update] → [framework: upgrade to <new>]`. Because
`commit_framework_change` commits on the base branch and the pre-snapshot is
idempotent-if-clean, this is automatic **provided the pre-snapshot runs first and
the tree was clean** (FR-003 guarantees clean-or-`--force`). If the tree was dirty
and `--force` was used, the snapshot captures the user's uncommitted edits too —
acceptable, the label tells the story.

**Finding A3 — Principle X already promises rollback "one `git revert` away"
(constitution line 454).** FR-011's documented two-step (`git reset --hard HEAD~1`
+ `pip install ==<old>`) is the *stronger* form (it also reverts the venv, which
git can't). No conflict; RELEASE.md should present both: `git revert` for the
vault tree alone, the two-step for tree + interpreter. **No `./vault rollback`
command** (Clarification Q1).

---

## 2. Audit: `dist-templates/install.sh` (shipped 0.8.0 / spec 051 FR2)

The end-user installer, re-run by `./vault update`. **What 051 already shipped:**

| Surface | Lines | Behaviour | 027 relevance |
|---------|-------|-----------|---------------|
| `--auto-confirm` / `-y` / `--non-interactive` | 83-92 | All three set `NON_INTERACTIVE=1`; suppress every prompt incl. the stale-venv rebuild. | **FR-003 reuses `--auto-confirm`** for prompt suppression (Clarification Q3). `--force` is the *only* net-new flag (dirty-tree override), and it lives on the **`update` verb**, not install.sh. |
| `_detect_stale_venv` + rebuild prompt | 123-172 | `pyvenv.cfg::home` gone ⇒ rebuild venv (auto-accept under `NON_INTERACTIVE`). | **Already done.** FR-005 must NOT re-implement. |
| Post-install version sanity check | 196-208 | Importable `__version__` ≠ bundled wheel version ⇒ `exit 2`. | **Already done.** This is the install-side correctness check. FR-005's remainder (`./vault health` + prominent surfacing) is *additive*, not a duplicate. |
| Skill-file preflight | 232-243 | `check-skills` auto-restore; broken ⇒ `exit 2`. | Out of scope for 027. |

**Finding B1 — `install.sh` ignores positional arguments; it operates on its own
`ROOT_DIR` (the extracted tarball dir), not the vault.** The only arg parsing is
the `--non-interactive|-y|--auto-confirm` loop (lines 83-92) and `--output` is
consumed by *generate.sh*, not install.sh. The `update` verb passes
`"${VAULT_DIR}"` as `$1` to install.sh (`vault-script.sh.j2` line 145) — **that
argument is silently discarded.** Consequence: re-running install.sh during
`./vault update` re-installs the *wheel into the vault's venv* (because the verb
runs it with the vault's `VENV_PYTHON` already on PATH? — no: install.sh creates
its **own** `.venv` under `ROOT_DIR`). This means the current `update` flow's
"re-run install.sh against the vault to refresh scaffolding" comment
(`vault-script.sh.j2` lines 119-121) is **partly aspirational** — install.sh does
not re-scaffold an existing vault tree from the manifest.

**Implication for FR-006 (user-owned files).** The spec's US3 premise — "the
current update path … overwrites everything" — is **not literally true today**
because install.sh doesn't touch the vault tree's scaffold files at all. The real
exposure is the **regenerate path** (`./vault regenerate-shim`, spec 023, and any
future `install.sh <vault>`-style re-scaffold). FR-006 should therefore be scoped
as: *whatever code path regenerates scaffold files MUST consult
`is_user_owned_after_first_write`.* Today that is `regenerate-shim` (vault shim
only) — which the manifest marks `vault: is_user_owned_after_first_write=false`
(line 298), i.e. the shim is intended to be overwritten on update. So **FR-006's
concrete, testable obligation in this spec is a guard helper + its enforcement at
the one place that rewrites manifest-tracked files**, plus a regression test that
proves a manifest `is_user_owned_after_first_write=true` file (e.g. `CLAUDE.md` —
**but note: `CLAUDE.md` is marked `false` in the current manifest, line 116**) is
preserved. **NEEDS CLARIFICATION candidate resolved below (§5).**

**Finding B2 — `--auto-confirm` already plumbs through the verb.** The `update`
verb forwards `"$@"` (post-verb args) to install.sh (line 145), and the verb's
help/behaviour already references spec 051 FR2. So `./vault update --auto-confirm`
works end-to-end **today**. 027 adds `--force` to the **verb's** own pre-flight
(dirty-tree), which must be parsed *before* the pip/archive steps and is NOT
forwarded to install.sh.

---

## 3. Audit: the `update` verb (`templates/vault-script.sh.j2` lines 117-156)

Current flow, in order:
1. Resolve `REPO_URL` / `REF` (env overrides). Default `REF=main`.
2. `pip install --upgrade git+<repo>@<ref>` into the vault venv → on fail `exit 2`.
3. Read `NEW_VERSION` **after** install (line 136).
4. Fetch source archive, untar to tmp.
5. If `install.sh` present + executable: re-run it (forwarding `"$@"`).
6. `_vault_autocommit framework "upgrade to ${NEW_VERSION}"` (post-commit).

**Gaps mapped to FRs (this is the DELTA):**

| FR | Gap in current verb | Delta to add |
|----|--------------------|--------------|
| FR-001 | `NEW_VERSION` read only *after* mutation; no `OLD_VERSION`; no diff print. | Read `OLD_VERSION` before step 2; resolve target version from the ref *before* install; print `Upgrading vX → vY`. |
| FR-002 | No short-circuit; always pip-installs. | If resolved-target == local ⇒ print "Already at vX.Y.Z, nothing to do" + `exit 0` **before** step 2. |
| FR-003 | No dirty-tree guard on `update` at all. | Pre-flight: `git status --porcelain` (via a Python helper that reuses `vault_commit._is_dirty`); refuse unless `--force`. |
| FR-004 | Only post-commit; no labelled pre-snapshot. | Insert `commit_framework_change(... title="snapshot before update <old> -> <new>")` **before** step 2. |
| FR-005 | No `./vault health` after install. | After step 5, run `./vault health`; non-zero ⇒ surface prominently + non-zero exit. (Install-side version check already shipped — don't duplicate.) |
| FR-006 | (See Finding B2 — enforcement lives in the regenerate path.) | Guard helper consulted wherever manifest files are rewritten. |
| FR-008 | Channel policy: default `REF=main` (pulls tip, not latest tag). | Spec SHOULD: default to latest **tagged release**. Documented override. (Spec uses SHOULD, not MUST — see §5.) |
| FR-012 | No version-ordering check. | After resolving target, if `target < local` ⇒ refuse unless explicit pinned ref **and** confirm. |

**Finding C1 — resolving the target version *before* installing is the crux.**
FR-002 (short-circuit) and FR-012 (downgrade refusal) both require knowing the
remote/target version *without* mutating the venv. Options:
- (a) `pip index versions` / `pip install --dry-run` — network, but no mutation.
- (b) Parse the version from the GitHub ref: for a tag `vX.Y.Z`, the version *is*
  the tag (zero network beyond ref existence). For `main`, fetch
  `pyproject.toml` from the archive/raw URL and parse `version = "…"`.
- (c) Download the archive first (the verb already does this at step 4), parse
  `pyproject.toml` from it, then decide. **Lowest-risk**: reorders existing work
  (archive fetch moves before pip install) and needs no new network surface.

**Recommendation: option (c)** — fetch archive → parse `pyproject.toml::version`
as the *target*, read installed version as *local*, then branch (short-circuit /
downgrade-refuse / proceed). Keeps the verb's existing network calls; adds only a
tiny TOML version grep (stdlib `tomllib` in 3.11+, or a `sed`/`grep` line —
prefer `tomllib` via the venv python for robustness).

**Finding C2 — the snapshot label needs both versions.** Subject format (spec Key
Entities): `snapshot before update <old-version> -> <new-version>`. Both are known
after Finding C1's reorder, before any mutation. ✓

---

## 4. Decision: where the new Python logic lives

The verb is bash; FR-001/002/003/004/012 need version comparison + dirty check +
the `commit_framework_change` call. Three placement options:

| Option | Pros | Cons |
|--------|------|------|
| **All inline in `vault-script.sh.j2`** (heredoc python) | No new module; matches existing `_vault_autocommit` heredoc style. | Logic untestable in isolation; FR-009 smoke test would have to drive the whole shim. |
| **New `pipeline/vault_update.py` orchestrator, verb calls it** | Unit-testable; `tests/cli/test_vault_update.py` targets it directly; clean reuse of `vault_commit`. | New module (small). |
| Extend `vault_commit.py` | Reuse. | Pollutes the Principle-X module with update-policy concerns (version compare, downgrade refusal) that aren't commit-invariant logic. Rejected. |

**Recommendation: Option 2 — a thin `pipeline/vault_update.py`** exposing the
*decision* functions (resolve versions, compare, dirty-check delegating to
`vault_commit._is_dirty`, build the snapshot title) so `test_vault_update.py` can
assert them hermetically with a local file-URL repo, while the verb stays a thin
bash dispatcher. The actual `pip install` / archive fetch stay in bash (they're
network/process orchestration, awkward to unit-test and already working). This
keeps the testable surface (FR-009) Python and the I/O surface bash — matching the
project's agent-script separation (Principle IV).

**Expose `_is_dirty` cleanly**: add a tiny public `is_working_tree_dirty(vault)` to
`vault_commit.py` (one-line wrapper over the existing private `_is_dirty`) so
`vault_update.py` doesn't import an underscored name. This is the *only* edit to
the shipped 0.7.0 module — additive, no behaviour change.

---

## 5. Resolved planning questions (were candidate NEEDS CLARIFICATION)

- **FR-006 scope (which file proves it?)** — The manifest marks `CLAUDE.md`,
  `AGENTS.md`, `README.md`, `vault`, `_concepts/_graph/_index.md` as
  `is_user_owned_after_first_write=false` (regenerated on update), and
  `settings.yaml`, `update_vault.py`, `.claude/**`, coverage-targets, etc. as
  `true`. **The spec's US3/AC-1 uses `CLAUDE.md` as the example, but the manifest
  marks `CLAUDE.md` `false`.** Resolution for the plan: FR-006's regression test
  MUST use a file the manifest actually flags `true` — `settings.yaml` is the
  canonical user-owned file (spec text itself lists it: line 62). The plan will
  scope the FR-009 "user-owned file edit survives" assertion to `settings.yaml`
  (and note the spec example wording as a doc nit to fix in tasks). **Not a
  blocker** — the contract (`is_user_owned_after_first_write`) is the source of
  truth, the example file name in prose is illustrative.
- **FR-008 SHOULD vs MUST** — spec uses SHOULD for "default to latest tag". Given
  the current default is `REF=main` and changing it is a behaviour change for
  every vault in the wild, the plan treats FR-008 as: **document** the tag-pinning
  override (`RV_GITHUB_REF=vX.Y.Z`) as the recommended path, and add latest-tag
  *resolution* as the default **only if** it doesn't regress the existing `main`
  workflow. Implemented conservatively: keep `main` working; make
  `RV_GITHUB_REF=latest` (or unset → query latest tag) resolve to the newest
  semver tag. Flagged as a SHOULD, low-risk.
- **FR-007 offline path** — pure docs (RELEASE.md). The bundle already ships a
  wheel + install.sh (US4/AC-1 already works mechanically); 027 only documents it.

## 6. No data-model / contracts warranted

027 adds no new persisted artifact schema (the snapshot is a normal git commit;
the transcript in Key Entities is stdout, optionally a `_pipeline/` line — not a
versioned contract). No new JSON/YAML schema, no new subprocess JSON contract.
`data-model.md` and `contracts/` are therefore omitted (plan-template allows this).
