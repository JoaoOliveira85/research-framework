# Implementation Plan: Installer Hardening

**Branch**: `039-installer-hardening` | **Date**: 2026-06-03 | **Spec**: `specs/039-installer-hardening/spec.md`
**Input**: Feature specification + clarify Session 2026-06-03 (Q1–Q4 resolved) + a read of the shipped `dist-templates/install.sh` and the `./vault` shim (`templates/vault-script.sh.j2`).

## Summary

Harden `dist-templates/install.sh` from "macOS happy-path, install-in-place only" to "one command bootstraps a fresh machine on **macOS or Linux**, honours a **target directory** so `./vault update` actually refreshes the vault, is **idempotent** on re-run, supports **`--dry-run`**, and **never fails silently** on a missing dependency."

The load-bearing fix is the **F2 bug**: `./vault update` runs `install.sh "${VAULT_DIR}"` from a freshly-downloaded tmpdir, but the current script ignores `$1` and operates on its own directory (`ROOT_DIR`), so the vault is never refreshed. The fix introduces a single resolved `TARGET` (`$1` > `${VAULT_DIR}` > `ROOT_DIR`) and a **source-vs-target split**: the bundled wheel is *sourced* from `ROOT_DIR`, while `.venv/`, scaffold, the `rv` shim and `install_summary.json` are *written* to `TARGET`. On top of that: a `uname`-based OS branch with a three-tier dependency probe (Mixed), a `--dry-run` mode, re-run idempotency, and a machine-readable `install_summary.json`.

## Technical Context

**Language/Version**: Bash (the installer; targets bash ≥ 3.2 so macOS stock bash works — Linux-portability lint is spec 009's) + Python 3.11 (the embedded settings sniffers + the pytest harness).
**Primary Dependencies**: stdlib + the system tools the script *probes* (`python`/`git`/`curl`/`rsync`/`claude`/`codex`/`weasyprint`/`gh`). **No new runtime dependency** (Principle V) — the script advises, it never vendors or auto-installs.
**Storage**: filesystem under `TARGET` — `TARGET/.venv/`, `TARGET/rv`, `TARGET/research.spec.md`, scaffold files, `TARGET/_pipeline/install_summary.json`. The wheel is read from `ROOT_DIR`.
**Testing**: `pytest` subprocess tests under `tests/scripts/` using the established **extract-function-and-run-in-sandboxed-bash** harness (see `tests/scripts/test_install_venv_staleness.py` and `test_install_sh_tty_handling.py`). The `--dry-run` surface is the primary deterministic test path (no real mutations); one opt-in slow real-install smoke. `shellcheck` is **009's** gate, not this spec's.
**Target Platform**: macOS (Homebrew) + Linux (`apt`/`dnf`/`pacman`/`apk`). Windows out of scope (WSL2 inherits Linux).
**Project Type**: single project — one bash script (`dist-templates/install.sh`) + pytest harness.
**Performance Goals**: re-run (idempotent) path exits 0 in **< 5 s** (SC-003). No other hot path.
**Constraints**: MUST preserve every existing behaviour — the v0.2.24 TTY-state capture, the crash-safe `install.log` tee, the spec-051 stale-venv rebuild + post-install version sanity check, the `check-skills` preflight, and the interactive onboarding wizard. The `TARGET` refactor inserts cleanly *around* those; `ROOT_DIR` stays as the bundle/wheel/skill anchor.
**Scale/Scope**: one ~560-line script + ~6 new pytest modules. No `src/` changes.

## Constitution Check

*GATE: must pass before Phase 0. Re-checked after Phase 1.*

| Principle | Assessment |
|---|---|
| **I. Script-Validated Quality Gates (NON-NEGOTIABLE)** | ✅ Strengthened — machine-readable `[FAIL]`/`[WARN]` lines (FR-012) + `install_summary.json` (FR-013) give 009's `ubuntu-latest` CI a deterministic signal. |
| **II. Phase Sequencing (NON-NEGOTIABLE)** | ✅ N/A — installer, not a research cycle. No change. |
| **III. Test-First (TDD — NON-NEGOTIABLE)** | ✅ Every FR gets a `pytest` subprocess test written RED-first (the harness pattern already exists). |
| **IV. Agent-Script Separation** | ✅ The installer is a pure script; no runtime agent judgement. The wizard *launches* `claude`/`codex` only on explicit user opt-in — unchanged. |
| **V. Offline-First, No New Deps** | ✅ Probe + advise only; never auto-install system tools; zero new Python deps. |
| **VI. No Duplicate Notes** / **VII. External Sources** / **IX. Vault-First Citation** | ✅ N/A — installer scope. |
| **VIII. No Placeholders in Deliverables** | ✅ Reinforced — fail loudly on a missing mandatory dep, never leave silent partial state, idempotent re-run. |
| **X. Vault History is Append-Only Git (NON-NEGOTIABLE)** | ✅ `install.sh` is the **pre-git bootstrap** — it writes `install_summary.json` before any vault-commit lifecycle exists. The first commit + subsequent mutation-as-commit are owned by **spec 050** and the first `./vault` op, NOT by `install.sh`. Interaction noted; not a violation. |

**Result: PASS — no violations, no Complexity-Tracking entries.** This spec *tightens* the "never fail silently" story and fixes a hard correctness bug.

## Project Structure

### Documentation (this feature)
```text
specs/039-installer-hardening/
├── plan.md          # this file
├── research.md      # Phase 0 — decisions D1..D9
├── contracts/
│   └── install-summary.contract.md   # FR-013 JSON schema + FR-012 grep contract
├── quickstart.md    # Phase 1 — exercise each mode + run the tests
└── tasks.md         # Phase 2 (/speckit.tasks)
```

### Source touched (repository root)
```text
dist-templates/install.sh                       # the ONLY production file changed
tests/scripts/test_install_target_resolution.py # NEW — FR-001/002/003 (TARGET precedence + wheel-source split)
tests/scripts/test_install_os_branch.py         # NEW — FR-004/006/007 (uname branch + pkg-mgr probe)
tests/scripts/test_install_dep_probe.py          # NEW — FR-005 (Mixed tiers) + FR-009 (presence-check)
tests/scripts/test_install_dry_run.py            # NEW — FR-008/009 (no mutations; exit reflects blockers)
tests/scripts/test_install_idempotency.py        # NEW — FR-010/011 (fast re-run; no clobber)
tests/scripts/test_install_summary_json.py       # NEW — FR-012/013 (schema + machine-readable lines)
tests/scripts/test_install_venv_staleness.py     # EXISTING — must stay green (regression)
tests/scripts/test_install_sh_tty_handling.py    # EXISTING — must stay green (regression)
```

## Phase 0 — Research (→ research.md)
All unknowns are resolved by the clarify session + the code read. `research.md` records **D1–D9**: TARGET resolution, the wheel-source-vs-target split, the Mixed dependency tiers, the `--dry-run` guard-wrapper design, OS/pkg-mgr detection, the idempotency strategy (two-step, 027-coupled), the `install_summary.json` schema, the bash-testing strategy, and the "preserve existing behaviours" inventory.

## Phase 1 — Design (→ contracts/, quickstart.md)
- **contracts/install-summary.contract.md**: the `install_summary.json` field schema (FR-013), an atomic-write + idempotent-update contract, and the FR-012 `[FAIL]`/`[WARN]`/`[INFO]` line grammar that 009's CI greps.
- **quickstart.md**: run install-in-place, install-to-target, `--dry-run`, idempotent re-run, and a Linux missing-dep case; plus the `pytest -k install` invocation.
- No `data-model.md` — the only persistent entity is `install_summary.json`, fully specified by its contract.
- Agent context refresh: `.specify/scripts/bash/update-agent-context.sh claude` (run at implement time, not now — avoids ROADMAP/CLAUDE drift while Wave-1 is in flight).

## Complexity / risks
- **Bash is awkward to test.** Mitigation: the repo already proves the **extract-fn-into-sandbox-bash** pattern; `--dry-run` makes the whole flow assertable with zero real mutations; the one real-install smoke is opt-in/slow-marked.
- **Regression surface is large.** The TTY capture (v0.2.24), log tee, stale-venv rebuild + sanity check (051), skill preflight, and wizard must all keep working. Mitigation: `TARGET` resolution slots in right after arg-parse; `ROOT_DIR` is unchanged as the wheel/skill/bundle anchor; only `cd` + write-targets move. The two existing install tests are the regression tripwire.
- **pty exhaustion in the sandbox** (the 3 known `test_install_sh_tty_handling` env failures) — keep new tests non-pty; don't add pty dependence.
- **FR-010 idempotency partially depends on spec 027** (`user_authored` vs `user_customizable` preservation). Mitigation: land FR-010 in **two steps** — basic "detect existing install → fast clean exit" now; the "don't clobber `user_authored`" half is gated on 027's flag and cross-referenced. *(Sequencing, not a violation.)*
- **Co-dependency with spec 009** (CI matrix exercises `--dry-run`). Clean split per Q4; separate PRs; 009 consumes 039's `--dry-run` + `[FAIL]` lines.
