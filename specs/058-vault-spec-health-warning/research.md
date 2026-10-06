# Research & Decisions: 058 Vault Control-File Git-Tracking Health Warning

Phase 0 decisions. Inputs: clarify Session 2026-06-03 + read of `scripts/vault_health.py`
(`HealthReport.unresolved_count` → `main()` exit 1), `templates/vault-script.sh.j2`
(`health` verb), `src/research_framework/cli/audit.py` (`validate_vault.py` is audit-only),
`pipeline/preconditions.py` (missing `research.spec.md` on cycle entry), spec 050 (Principle X).

## Surface audit (placement)

| Surface | Command | Role today | 058 placement |
|---|---|---|---|
| `scripts/vault_health.py` | `./vault health` | Wikilinks, URLs, template drift; `unresolved_count` → exit 1 | **✅ Host** — fourth sub-check, advisory only |
| `scripts/validate_vault.py` | `./vault audit` (subprocess) | Per-note frontmatter / wikilink body validation | ❌ Wrong surface — note-level, not vault-control |
| `pipeline/preconditions.py` | cycle preflight | Missing `research.spec.md` → hard block | Complementary — owns **absence**, not tracking |
| `pipeline/vault_commit.py` | auto-commit | Dirty tree / commit failures | Complementary — owns **commit state**, not index tracking |

## D1 — Placement: `vault_health.py` only

**Decision**: implement as `scan_control_file_git_tracking(vault)` inside
`scripts/vault_health.py`, invoked from `run()` after existing sub-checks.
**Why**: `./vault health` is the operator-facing fast check (QW-4 / TODO origin);
`validate_vault.py` never runs on the health path and validates note bodies, not vault
control files. Spec 027's post-update `./vault health` smoke gate is the same entry point.
**Rejected**: new standalone script (extra surface); hooking `validate_vault.py` (wrong
semantics + couples to audit exit codes).

## D2 — Absent files: skip (do not warn)

**Decision**: iterate contract §1 paths; if `not path.exists()`, continue with no output.
**Why**: `preconditions.py` already fails closed on missing `research.spec.md` at cycle
start; inventing a second "missing control file" warning here would duplicate signals and
blur the tracking-only scope (Q1).
**Rejected**: warn on absence (overlaps preconditions; confuses "not tracked" with "not there").

## D3 — Fixed four paths (v1)

**Decision**: canonical vault-relative paths (contract §1):

| Path | Rationale |
|---|---|
| `research.spec.md` | Regenerator, `/ask`, update, audit |
| `settings.yaml` | `agent_call.py`, stage dispatch |
| `_pipeline/research-backlog.md` | Scout/orchestrator backlog (`research_plan.py`) |
| `_pipeline/coverage-targets.json` | CG-001 / yield / phase gates |

**Why**: matches `docs/TODO.md` QW-4 prose + runtime consumers; `_pipeline/` prefix aligns
with scaffold + orchestrator (bare `research-backlog.md` at vault root is not used).
**Rejected**: settings-driven list (v1 scope creep); vault-root `coverage-targets.json`
(stale layout — live state is under `_pipeline/` per 017/051).

## D4 — Git algorithm (deterministic, stdlib + git CLI)

**Decision**:

1. `git -C <vault> rev-parse --is-inside-work-tree` → not `true` ⇒ return `[]` (silent skip).
2. For each **existing** control path (sorted):
   - `git -C <vault> check-ignore -q -- <path>` → exit 0 ⇒ reason `ignored`.
   - else `git -C <vault> ls-files --error-unmatch -- <path>` → exit ≠ 0 ⇒ reason `untracked`.
   - else tracked ⇒ no warning.
3. Sort warnings by `rel_path` ascending before return.

**Why**: `check-ignore` catches parent/global rules (edge case in spec); `ls-files
--error-unmatch` is the canonical tracked probe; sorted output satisfies FR-007/SC-005.
**Rejected**: parsing `.git/index` by hand (fragile); `git status --porcelain` (noisier,
includes dirty-state signal 050 owns).

## D5 — Advisory isolation from exit code

**Decision**: add `control_file_tracking: list[ControlFileTrackingWarning]` to
`HealthReport`; **do not** add to `unresolved_count` property; `main()` unchanged.
Report section uses `WARN` prefix lines; stdout mirrors report.
**Why**: FR-004 / US3 — operators must see risk without blocking `./vault health` or spec
027's post-update smoke when wikilinks are clean.
**Rejected**: counting warnings in `unresolved_count` (would fail health on advisory alone).

## D6 — `--fix` deferred

**Decision**: no `--apply` / `--fix` for git tracking in v1; operator runs `git add` manually.
**Why**: Q3 — auto-staging control files touches Principle X workflow boundaries; QW-4 is
explicitly a warning quick-win (~0.25 day).
**Rejected**: `--apply` auto-`git add` (scope + safety review deferred).

## Cross-spec notes

- **050**: warns that history must be committed; 058 warns that control files must be
  **in the index** — orthogonal. No dirty-tree / uncommitted-change warnings here.
- **027**: `./vault health` remains the post-update smoke; 058 must not break its pass/fail
  semantics when only control files are at risk.
- **048 v1.1**: `vault status` is a separate verb — out of scope; health report section
  is sufficient for v1.
