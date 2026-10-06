# Implementation Plan: Vault Control-File Git-Tracking Health Warning (058)

**Branch**: `058-vault-spec-health-warning` | **Date**: 2026-06-03 | **Spec**: `specs/058-vault-spec-health-warning/spec.md`
**Input**: Spec (clarified Session 2026-06-03) + audit of `scripts/vault_health.py` (sub-check orchestrator; `unresolved_count` drives exit 1) and `templates/vault-script.sh.j2` (`health` → `vault_health.py`).

## Summary

Add a **fourth sub-check** to `scripts/vault_health.py`: for git-backed vaults, warn when any **present** critical control file is **untracked** or **git-ignored**. Uses stdlib `subprocess` + `git check-ignore` / `git ls-files` (no PyYAML/gitpython). Warnings surface in `HealthReport`, the Markdown report (`## Control-file git tracking`), and stdout — but **never** increment `HealthReport.unresolved_count` or change `main()`'s exit code (FR-004). Non-git vaults skip silently. Absent files skip (FR-002a).

## Technical Context

**Language/Version**: Python 3.11+ (script style matches existing `vault_health.py`).
**Primary Dependencies**: stdlib only (`subprocess`, `pathlib`, `dataclasses`). **No new runtime dependency** (Principle V).
**Storage**: reads vault filesystem + local git index; writes only the existing `_pipeline/health-report.md` (extended section).
**Testing**: extend `tests/scripts/test_vault_health.py` — `tmp_path` vaults with `git init`, hermetic (no network).
**Target Platform**: macOS/Linux (git CLI assumed on PATH — same assumption as spec 050 `vault_commit`).
**Project Type**: single script extension (~80–120 LOC) + contract tests.
**Performance Goals**: four `git` subprocess calls per present file + one work-tree probe; negligible vs URL scan.
**Constraints**: WARN-only (exit 0/1 unchanged by this sub-check alone); deterministic sorted output; skip absent files; reason priority **ignored** over **untracked** when both apply.
**Scale/Scope**: one script, one test module extension, one contract file, no pipeline/CLI package changes (shim already delegates).

## Constitution Check

*GATE: must pass before implementation. Re-checked after Phase 1 design.*

| Principle | Assessment |
|---|---|
| **I. Script-Validated Quality Gates** | ✅ Deterministic advisory surfaced by `./vault health` (script-validated); does not weaken existing hard gates. |
| **III. Test-First (TDD)** | ✅ RED tests in `test_vault_health.py` before `scan_control_file_git_tracking()` lands. |
| **IV. Agent-Script Separation** | ✅ Pure `git` plumbing — no agent dispatch; same inputs → same warnings. |
| **V. Offline-First, No New Deps** | ✅ stdlib + system `git` only. |
| **IX. Vault-First Citation** | ✅ N/A (structural hygiene, not citation). |
| **X. Vault History is Append-Only Git** | ✅ **Operationalizes X's assumption** — untracked control files are invisible to recovery; this warns before `git clean`/clone data-loss. Does **not** duplicate 050's commit/dirty-tree enforcement (explicitly out of scope). |

**Result: PASS — no violations.**

## Project Structure

### Documentation (this feature)
```text
specs/058-vault-spec-health-warning/
├── plan.md              # this file
├── research.md          # Phase 0 — decisions D1..D5
├── contracts/
│   └── control-file-tracking.contract.md
├── quickstart.md        # reproduce warnings on a tmp_path git vault
└── tasks.md             # Phase 2 (/speckit.tasks)
```

### Source touched (repository root)
```text
scripts/vault_health.py
  • CONTROL_FILE_PATHS (contract §1)
  • ControlFileTrackingWarning dataclass
  • scan_control_file_git_tracking(vault) -> list[ControlFileTrackingWarning]
  • HealthReport.control_file_tracking (+ NOT in unresolved_count)
  • render_report() — new section
  • run() — wire sub-check
tests/scripts/test_vault_health.py
  • TestControlFileGitTracking (git init fixtures)
```

**Structure decision**: extend the existing health orchestrator in-place. `validate_vault.py` and `src/research_framework/cli/audit.py` are **read-only** references — no edits (different command surface).

## Phase 0 — Research (→ research.md)

Decisions **D1–D5**: placement on `vault_health.py`; absent-file skip; fixed path table; git probe algorithm (`rev-parse` → per-file `check-ignore` then `ls-files --error-unmatch`); advisory isolation from `unresolved_count`.

## Phase 1 — Design

- `contracts/control-file-tracking.contract.md`: path table, warning record shape, git algorithm, report line format.
- `quickstart.md`: minimal repro for untracked / ignored / all-clear / non-git.

## TDD strategy

1. **RED** — `TestControlFileGitTracking` cases (SC-001..SC-005) against `scan_*` + `run()` exit code.
2. **GREEN** — implement `scan_control_file_git_tracking` + wire into `run`/`render_report`.
3. **Regression** — existing `TestRun` cases unchanged (`unresolved_count` semantics preserved).

## Complexity / risks

- **Git absent on PATH** → treat as non-git (skip silently) vs hard error. **Decision**: skip silently (same as non-work-tree) — mirrors optional-git dev environments; document in contract §3.
- **Submodule / work-tree edge cases** → use `git -C <vault> …` with vault-relative paths only; no `git add` side effects.
- **Ignored + untracked** → emit **ignored** only (contract §2 reason priority).
