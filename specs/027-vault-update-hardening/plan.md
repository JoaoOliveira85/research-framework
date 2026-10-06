# Implementation Plan: `./vault update` Hardening

**Branch**: `027-vault-update-hardening` | **Date**: 2026-06-03 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/027-vault-update-hardening/spec.md`
**Theme**: *reconcile, don't reimplement* — DELTA over shipped 0.7.0 (Principle X /
`vault_commit.py`) + 0.8.0 (spec 051 `install.sh` hardening). See [research.md](./research.md)
for the full audit.

## Summary

Harden `./vault update` with a pre-flight safety net: detect-and-skip when already
current (FR-002), refuse dirty trees without `--force` (FR-003), take a *labelled
pre-snapshot via the existing `vault_commit.commit_framework_change`* so
`git reset --hard HEAD~1` rolls back (FR-004), refuse accidental downgrades (FR-012),
run `./vault health` after install and fail loudly on regression (FR-005), honour the
`is_user_owned_after_first_write` scaffold contract wherever manifest files are
rewritten (FR-006), and document the rollback + offline + channel-pin paths in
`docs/RELEASE.md` (FR-007/008/011). All commit behaviour reuses the shipped
Principle-X module; all prompt-suppression reuses the shipped `--auto-confirm`; the
shipped stale-venv + post-install version check are NOT re-implemented.

The testable decision logic lands in a thin new `pipeline/vault_update.py`; the verb
(`templates/vault-script.sh.j2`) stays a bash dispatcher that calls it. FR-009's
`tests/cli/test_vault_update.py` drives the orchestrator against a local file-URL repo
and gates releases via `build.sh::SMOKE_TESTS` (FR-010).

## Technical Context

**Language/Version**: Python 3.11+ (`tomllib` available stdlib); Bash (vault shim, install.sh)
**Primary Dependencies**: stdlib only (`subprocess`, `tomllib`, `pathlib`); `pyyaml` (already a dep, via settings). **No new runtime deps** — Principle V.
**Storage**: vault filesystem + git. The pre-snapshot is a normal git commit on the base branch; no new persisted-artifact schema.
**Testing**: pytest. New `tests/cli/test_vault_update.py` (tier-3 integration; local file-URL repo, no network, no live `claude`/`codex`). Added to `build.sh::SMOKE_TESTS`.
**Target Platform**: macOS + Linux (vault operators); shim is bash.
**Project Type**: single project (CLI / pipeline package).
**Performance Goals**: SC-002 short-circuit < 5 s (no pip/install.sh); SC-003 dirty-tree refusal < 2 s; SC-005 smoke test < 15 s.
**Constraints**: reconcile-don't-reimplement (binding scope). No parallel commit path (Q2). Reuse `--auto-confirm` (Q3). No `./vault rollback` command (Q1). Refuse downgrade by default (Q4).
**Scale/Scope**: per-vault upgrade flow; ~1 new small module + verb edits + RELEASE.md + 1 test file.

## Shipped already vs 027 adds (the DELTA table)

| Concern | Shipped (where) | 027 adds | FR |
|---------|-----------------|----------|----|
| Auto-commit of upgrade diff | 0.7.0 `commit_framework_change` (post-call wired in shim) | **Pre-snapshot** call with labelled subject, run before any mutation | FR-004 |
| Rollback mechanism | Principle X: "one `git revert` away"; commit topology exists | **Document** two-step (`git reset --hard HEAD~1` + `pip install ==<old>`) in RELEASE.md; NO command | FR-011 |
| Prompt suppression for unattended runs | 0.8.0 `--auto-confirm`/`-y`/`--non-interactive` (install.sh) | Reuse verbatim; forward through verb (already works) | FR-003 (Q3) |
| Stale-venv rebuild | 0.8.0 `_detect_stale_venv` (install.sh) | — (do NOT re-implement) | — |
| Post-install correctness | 0.8.0 importable-version-vs-wheel check ⇒ exit 2 (install.sh) | — (do NOT re-implement); FR-005 adds only the `./vault health` run | FR-005 |
| Dirty-tree HARD STOP | 0.7.0 `begin_run` for **`research`** only | Extend the guard to **`update`** (`--force` override) | FR-003 |
| Version diff / short-circuit | none | Resolve target before mutating; print diff; skip if equal | FR-001/002 |
| Downgrade protection | none | Refuse older target unless explicit pinned ref + confirm | FR-012 |
| User-owned-file honouring | manifest `is_user_owned_after_first_write` exists; no consumer in update path | Guard helper consulted where manifest files are rewritten | FR-006 |
| Offline / channel docs | partial (RELEASE.md "Known limitations") | Replace limitations block with hardened-wrapper + offline + tag-pin docs | FR-007/008 |

## Constitution Check

*GATE: must pass before Phase 0. Re-checked after design — still passing.*

| Principle | Verdict | Notes |
|-----------|---------|-------|
| I — Script-Validated Quality Gates | PASS | FR-005 wires `./vault health` (a deterministic script gate) into the update flow. New test in smoke gate (FR-010). |
| III — Test-First (TDD) | PASS | `test_vault_update.py` written before the orchestrator; foreman `### Testing Requirements` to be authored at `/speckit.tasks`. |
| IV — Agent-Script Separation | PASS | Decision logic = Python (`vault_update.py`), I/O orchestration = bash verb. No `claude`/`codex` invoked anywhere in 027. |
| V — Offline-First / No New Deps | PASS | stdlib `tomllib` + existing `pyyaml`. FR-007 explicitly *adds* an offline path. |
| X — Vault History is Append-Only Git (NON-NEGOTIABLE) | PASS — and *strengthened* | FR-004 reuses `commit_framework_change` (no parallel commit path, Q2). The pre-snapshot makes "rollback one revert away" (constitution line 454) literally true for `update`. Inherits the per-vault `enabled` opt-out + non-git graceful skip + non-fatal-commit-failure semantics for free. |

No violations ⇒ Complexity Tracking table omitted.

## Phases

### Phase 0 — Audit (DONE — [research.md](./research.md))
Findings A1–A3 (vault_commit), B1–B2 (install.sh), C1–C2 (verb), the placement
decision (new `vault_update.py`), and the resolved planning questions (§5). Confirms
the DELTA table above. **No NEEDS CLARIFICATION remain** (the FR-006-example-file and
FR-008-SHOULD-vs-MUST ambiguities are resolved in research §5).

### Phase 1 — Design (this plan)
- **New module** `src/research_framework/pipeline/vault_update.py` — pure decision
  functions (no network, no pip), unit-testable:
  - `resolve_local_version(vault) -> str` — importable `research_framework.__version__` via the vault venv.
  - `resolve_target_version(archive_or_ref) -> str` — parse `pyproject.toml::version` from the fetched archive (research C1 option c) with `tomllib`.
  - `compare_versions(local, target) -> {"same"|"upgrade"|"downgrade"}` — semver-ish tuple compare.
  - `snapshot_title(old, new) -> str` → `"snapshot before update {old} -> {new}"`.
  - `is_user_owned(manifest, rel_path) -> bool` — read `dist-templates/scaffold-manifest.json` (or the vault's copy) and honour `is_user_owned_after_first_write` (FR-006 helper).
  - `decide(local, target, *, force, pinned_ref, confirmed) -> Decision` — encodes FR-002 (same⇒noop), FR-012 (downgrade⇒refuse unless pinned+confirmed), else proceed; returns a small dataclass `(action, message, exit_code)`.
- **One additive edit to `vault_commit.py`**: public `is_working_tree_dirty(vault) -> bool` wrapping the existing private `_is_dirty` (so `vault_update.py` and the verb avoid importing an underscored name). No behaviour change to 0.7.0.
- **Verb edit** `templates/vault-script.sh.j2::update` — reordered flow:
  1. Parse `--force` off the verb's own args (NOT forwarded to install.sh); keep forwarding the rest (incl. `--auto-confirm`).
  2. Resolve `REPO_URL`/`REF`; **fetch the archive first** (research C1c).
  3. Call `vault_update.decide(...)` with local + target (parsed from archive).
     - `same` ⇒ print "Already at vX.Y.Z, nothing to do" + `exit 0` (FR-002, SC-002).
     - `downgrade` + not (pinned+confirmed) ⇒ refuse + non-zero exit (FR-012).
  4. Dirty-tree guard via `is_working_tree_dirty` ⇒ refuse unless `--force` (FR-003, SC-003).
  5. Print version diff (FR-001).
  6. **Pre-snapshot**: `commit_framework_change(title=snapshot_title(old,new))` (FR-004).
  7. `pip install --upgrade …` (existing).
  8. Re-run install.sh (existing; inherits 0.8.0 stale-venv + version check).
  9. `./vault health` ⇒ surface + non-zero exit on failure (FR-005).
  10. Post-commit: existing `_vault_autocommit framework "upgrade to ${NEW_VERSION}"`.
- **Regenerate-path guard (FR-006)**: wherever manifest-tracked files are rewritten
  (today: `regenerate-shim` / any `install.sh`-driven re-scaffold), consult
  `is_user_owned`. Concrete obligation = the guard helper + a regression test proving
  a `true`-flagged file (`settings.yaml`) survives. See research §5 (the spec's
  `CLAUDE.md` example is `false` in the manifest — tasks will fix the prose, test
  uses `settings.yaml`).
- **Docs (FR-007/008/011)** — rewrite `docs/RELEASE.md` "Updating an existing vault"
  to replace the "Known limitations" block with: hardened-wrapper description; the
  two-step rollback (`git reset --hard HEAD~1` + `pip install ==<old>`) *and* the
  `git revert` form; the offline/air-gap commands (`pip install <wheel>` +
  `bash <bundle>/install.sh`); the channel/tag pin (`RV_GITHUB_REF=vX.Y.Z`). Also
  update CHANGELOG `[Unreleased]` per SC-006.

### Phase 2 — Tasks (`/speckit.tasks`, NOT this command)
Will produce `tasks.md` with foreman `### Testing Requirements` blocks (ADR-0010),
populate the spec's Acceptance coverage evidence cells, and decompose the above.

## Concrete delta files

| File | Change | FR |
|------|--------|----|
| `src/research_framework/pipeline/vault_update.py` | **NEW** — decision functions (versions, compare, snapshot title, user-owned, `decide`) | FR-001/002/006/012 |
| `src/research_framework/pipeline/vault_commit.py` | **EDIT (additive)** — public `is_working_tree_dirty()` wrapper | FR-003 |
| `templates/vault-script.sh.j2` (`update` case) | **EDIT** — reordered flow: archive-first → decide → dirty-guard → version diff → pre-snapshot → install → health | FR-001/002/003/004/005/012 |
| `src/research_framework/generator/scaffold.py` | **EDIT** — consult `is_user_owned` before overwriting manifest-tracked files | FR-006 |
| `src/research_framework/cli/regenerate_shim.py` | **EDIT** — consult `is_user_owned` where manifest files are rewritten on regenerate | FR-006 |
| `docs/RELEASE.md` | **EDIT** — hardened-wrapper + rollback two-step + offline + tag-pin; drop "Known limitations" | FR-007/008/011 |
| `CHANGELOG.md` | **EDIT** — `[Unreleased]` entry | SC-006 |
| `tests/cli/test_vault_update.py` | **NEW** — integration smoke (local file-URL repo) | FR-009 |
| `build.sh` (`SMOKE_TESTS`) | **EDIT** — add the new test | FR-010 |

## Test approach

**`tests/cli/test_vault_update.py`** (tier-3 integration, hermetic — local file-URL
repo, no network, no live agents):

- `test_short_circuit_when_already_current` — local == target ⇒ exit 0, no pip/install.sh side effects, < 5 s (SC-002). Asserts on `decide(...).action == "noop"` + verb dry behaviour.
- `test_dirty_tree_refused_without_force` — dirty vault ⇒ non-zero, clear message, no snapshot/no install (SC-003). `--force` ⇒ proceeds.
- `test_pre_snapshot_then_upgrade_topology` — after an upgrade v0.3.0→v0.3.1: `git log` shows `snapshot before update 0.3.0 -> 0.3.1` as `HEAD~1` of the `framework: upgrade` commit (FR-004, US1/AC-1).
- `test_downgrade_refused_by_default` — target < local ⇒ refuse; refuse persists without `confirmed`; explicit pinned ref + confirm ⇒ proceeds (FR-012, Q4).
- `test_user_owned_file_survives_upgrade` — edit `settings.yaml` (manifest `is_user_owned_after_first_write=true`), run update, assert byte-identical afterward (FR-006, SC-004, US3).
- `test_health_failure_surfaces_nonzero` — stub a failing `./vault health` ⇒ update exits non-zero with prominent message (FR-005).
- Unit-level: `compare_versions`, `snapshot_title`, `is_user_owned`, `decide` truth-table (covers FR-002/012 branches without the full verb).

Reuse `tests/_helpers/vault_factory.build_minimal_vault` for fixture vaults (spec
Assumption). The "remote" is a local git repo / file-URL or a tmp archive with a
crafted `pyproject.toml::version` — no GitHub, no network (Principle V / dispatch
guard).

**Smoke-gate (FR-010)**: add `tests/cli/test_vault_update.py` to
`build.sh::SMOKE_TESTS` so a regression hard-fails the release workflow.

## Project Structure (this feature)

```text
specs/027-vault-update-hardening/
├── plan.md          # this file
├── research.md      # Phase 0 audit (vault_commit.py + install.sh + verb)
├── quickstart.md    # operator-facing walkthrough of the hardened flow
├── checklists/      # (existing)
├── spec.md          # clarified
└── tasks.md         # Phase 2 (/speckit.tasks — not created here)
```

Source touched (repository root):
```text
src/research_framework/pipeline/vault_update.py   # NEW
src/research_framework/pipeline/vault_commit.py   # +is_working_tree_dirty()
templates/vault-script.sh.j2                      # update verb reorder
docs/RELEASE.md                                   # rollback/offline/tag-pin
tests/cli/test_vault_update.py                    # NEW (smoke-gated)
build.sh                                          # SMOKE_TESTS += new test
```

**Structure Decision**: single-project layout (existing). Decision logic in the
pipeline package (testable), I/O in the bash verb (Principle IV), no new top-level
dirs. No `data-model.md` / `contracts/` (no new persisted schema — research §6).

## Complexity Tracking

No constitution violations → not applicable.
