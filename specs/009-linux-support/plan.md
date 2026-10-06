# Implementation Plan: Cross-Platform Portability Guard + PR CI (009)

**Branch**: `009-linux-support` | **Date**: 2026-06-03 | **Spec**: `specs/009-linux-support/spec.md`
**Input**: Reframed spec (post-audit) + clarify Session 2026-06-03 + the 2026-06-03 portability audit (`sed -i ''`, macOS paths, `pbcopy`/`pbpaste`/`open`, bash-4 constructs) + a read of the existing `.github/workflows/` (only `release.yml` + tag-triggered `quality.yml`; **no `ci.yml`**).

## Summary

Convert a one-time portability audit into a **permanent invariant** + stand up the **PR CI that doesn't exist yet**. Two deliverables: (1) a deterministic, stdlib-only **portability guard** (`scripts/check_portability.py` + a pytest) that fails on a new BSD `sed -i ''`, hardcoded macOS path, or bash-4 construct in *shipped* scripts; (2) a new **`.github/workflows/ci.yml`** running the full guard (`pytest -m "not e2e"` + `ruff check` + `ruff format --check` + `shellcheck` + `install.sh --dry-run`) on a `{macos-latest, ubuntu-latest}` matrix with **macOS first-class/required**. Plus a `docs/PORTABILITY.md` contract. The audit confirmed shipped code is already portable, so the remediation surface is near-zero — 009 is **validation + regression-lock + CI**, not remediation.

## Technical Context

**Language/Version**: Python 3.11 (the guard + its tests); Bash ≥ 3.2 (the shipped scripts under guard — macOS stock bash floor); GitHub Actions YAML; `shellcheck` (CI tool).
**Primary Dependencies**: **stdlib only** for the guard (`pathlib`, `re`, `sys`). `shellcheck` is **CI-only** (pre-installed on GitHub `macos-latest` + `ubuntu-latest` runners) — **no new Python runtime dependency** (Principle V).
**Storage**: none — the guard reads source files; CI is config.
**Testing**: `pytest`. The guard IS a pytest (`tests/scripts/test_portability_guard.py`) so it runs in the fast loop; a second test (`tests/scripts/test_ci_config.py`) parses `ci.yml` and asserts the matrix + step set (config-drift lock).
**Target Platform**: macOS (primary dev + validation target) + Linux (parity); Windows out (WSL2).
**Project Type**: single project — one guard script + tests + one CI workflow + one doc.
**Performance Goals**: guard runs in **< 2 s** in the fast loop (SC-004); no runtime hot path.
**Constraints**: macOS leg is REQUIRED (user direction — macOS is primary). Guard must not depend on `shellcheck` locally. The macOS-path rule must exempt docs (`*.md`) to avoid flagging the legit macOS cert instruction in `dist-templates/README.md`.
**Scale/Scope**: ~1 guard script (~80 LOC) + 2 test modules + 1 workflow + 1 doc. No `src/` behaviour change.

## Constitution Check

*GATE: must pass before Phase 0. Re-checked after Phase 1.*

| Principle | Assessment |
|---|---|
| **I. Script-Validated Quality Gates (NON-NEGOTIABLE)** | ✅ This feature *is* Principle I — a deterministic guard with an exit code + its own tests, plus a CI gate. |
| **III. Test-First (TDD — NON-NEGOTIABLE)** | ✅ The guard's tests (positive + negative fixtures) are written before the guard; the CI-config test before `ci.yml`. |
| **IV. Agent-Script Separation** | ✅ Pure tooling — no agent involvement. |
| **V. Offline-First, No New Deps** | ✅ Guard is stdlib; `shellcheck` is CI-only (runner-provided), never a Python/runtime dep. |
| **VI / VII / IX** | ✅ N/A — tooling/CI scope. |
| **VIII. No Placeholders in Deliverables** | ✅ Guard fails loudly with file+line; CI is real (not a stub workflow). |
| **X. Vault History is Append-Only Git (NON-NEGOTIABLE)** | ✅ N/A — repo CI/tooling, not a vault mutation. |

**Result: PASS — no violations, no Complexity-Tracking entries.**

## Project Structure

### Documentation (this feature)
```text
specs/009-linux-support/
├── plan.md          # this file
├── research.md      # Phase 0 — decisions D1..D7
├── quickstart.md    # run the guard, shellcheck, read CI
└── tasks.md         # Phase 2 (/speckit.tasks)
```
No `data-model.md`/`contracts/` — the only "contract" is the guard rule-set, which is
self-documenting (the script) + documented (`docs/PORTABILITY.md`).

### Source touched (repository root)
```text
scripts/check_portability.py              # NEW — stdlib guard (CLI + importable)
tests/scripts/test_portability_guard.py   # NEW — FR-001/002/003 (pos+neg fixtures, clean-tree lock)
tests/scripts/test_ci_config.py           # NEW — FR-004/005 (parse ci.yml; assert matrix + steps)
.github/workflows/ci.yml                  # NEW — PR CI, {macos-latest, ubuntu-latest}, macOS required
docs/PORTABILITY.md                       # NEW — FR-008 contributor contract
# Possible (only if shellcheck surfaces a real finding):
dist-templates/*.sh / scripts/*.sh / build.sh   # add `# shellcheck disable=SCxxxx` + why
```

## Phase 0 — Research (→ research.md)
Decisions **D1–D7**: guard-as-stdlib-pytest (not shell); the docs/`*.md` allowlist for the
macOS-path rule; the `.specify/` exclusion + the 2 documented `${word^^}` hits; the
`{macos,ubuntu}` matrix with macOS required; the bash-3.2 floor for shipped scripts; the
039-sequencing for the CI dry-run step; and `docs/PORTABILITY.md` as the doc home.

## Phase 1 — Design
- The guard rule-set is the design surface — enumerated in `research.md` (D1) and mirrored
  1:1 in `docs/PORTABILITY.md` (FR-008) so contributors and the guard never drift (SC-005).
- `quickstart.md`: run the guard locally (`python scripts/check_portability.py` /
  `pytest -k portability`), the `shellcheck` command, and how to read the CI matrix.
- Agent context refresh deferred to implement time (avoid CLAUDE/ROADMAP drift mid-Wave-1).

## Complexity / risks
- **CI dry-run step depends on 039.** Mitigation (FR-009): land 009 **after** 039, or make
  the step tolerant of a missing `--dry-run`. Sequencing, not a violation.
- **macOS CI minutes** are ~10× Linux. Accepted — the user designated macOS the primary
  target; parity is worth the spend, and the fast loop is `-m "not e2e"` (minutes, not hours).
- **Guard false-positives** (e.g. a `${var^^}` inside a *Python* f-string, or `/usr/local/bin`
  in a comment). Mitigation: scope by file type + path (shipped `.sh` for bash-4; `src`+`scripts`
  for macOS paths; `*.md` exempt) and unit-test the negative cases explicitly.
- **`quality.yml` overlap**: it runs the *quality harness* on tags only; `ci.yml` runs the
  *fast guard* on PRs. Distinct purposes, no duplication. Noted so a future reader doesn't merge them.
