# Implementation Plan: Foreman Retro Coverage — Tolerant Matching Mode (057)

**Branch**: `057-foreman-retro-matcher` | **Date**: 2026-06-03 | **Spec**: `specs/057-foreman-retro-matcher/spec.md`
**Input**: Spec (clarified Session 2026-06-03) + audit of `scripts/foreman/verify_test_coverage.py` + `docs/foreman.md` + ADR-0010.

## Summary

Extend the existing Foreman Arm A verifier with an **opt-in `--tolerant` mode** that
satisfies requirements when a named test **file exists** and `pytest` reports **≥1 PASSED**
test in that file — ignoring function names and TDD timeline. Strict mode (default) is
unchanged. JSON + human output gain `matching_mode` so a tolerant PASS is never mistaken
for a TDD-verified strict PASS. Retro target set (018/022/025/028) and rollout order
(028→018→022→025) are documented in the spec; Phase 7 tasks author file-only blocks.

## Technical Context

**Language/Version**: Python 3.11+ (project `requires-python`).
**Primary Dependencies**: stdlib only (`argparse`, `ast`, `json`, `re`, `subprocess`, `pathlib`) — **no new runtime dependency** (Principle V). Existing dev deps: `pytest` (already used by the verifier's subprocess invocations).
**Storage**: N/A — verdict is ephemeral stdout (`--json` optional). No ledger file.
**Testing**: extend `tests/foreman/test_verify_test_coverage.py` (parser, primitives, e2e with tiny git worktrees + real pytest).
**Target Platform**: macOS/Linux (same as existing foreman tooling).
**Project Type**: single repo — surgical edit to `scripts/foreman/verify_test_coverage.py` + `docs/foreman.md` contract doc + foreman tests.
**Performance Goals**: tolerant file-level `pytest <file>` is comparable to strict per-node runs; acceptable for manual retro (LOW priority).
**Constraints**: strict default unchanged (FR-005/SC-004); deterministic (FR-007); PASSED-only semantics preserved for skips/xfail (edge cases).
**Scale/Scope**: ~150–250 LOC delta in verifier; ~12–18 new tests; `docs/foreman.md` tolerant grammar section; optional Phase 7 edits to four `tasks.md` files (retro authoring).

**Reference sketch**: unmerged branch `test-design/028-retro` @ `fc24a43` — strict-named 028 `tasks.md` enrichment; informs **which files** to list in retro blocks, not the tolerant parser grammar.

## Constitution Check

*GATE: must pass before Phase 0. Re-checked after Phase 1.*

| Principle | Assessment |
|---|---|
| **I. Script-Validated Quality Gates** | ✅ Tolerant coverage is still a deterministic script gate (Arm A), not LLM self-grading. |
| **III. Test-First (TDD)** | ✅ New tolerant parser/verify paths get RED tests in `tests/foreman/` before implementation. Strict-regression tests land in the same PR. |
| **IV. Agent-Script Separation** | ✅ **Core constraint** — tolerant matcher is pure Python + git + pytest; no agent judges coverage. Arm B unchanged. |
| **V. Offline-First, No New Deps** | ✅ stdlib-only extension of existing script. |
| **VII. No Placeholders** | ✅ Real verifier behaviour, not a stub flag. |
| **ADR-0010 foreman pattern** | ✅ Strengthens retro insurance without weakening strict policy for new specs. |

**Result: PASS — no violations.**

## Project Structure

### Documentation (this feature)

```text
specs/057-foreman-retro-matcher/
├── spec.md
├── plan.md              # this file
├── research.md          # D1–D6
├── contracts/
│   ├── tolerant-requirements.contract.md
│   └── verdict-report.contract.md
├── quickstart.md
├── tasks.md
├── analyze-2026-06-03.md
└── checklists/requirements.md
```

### Source touched (repository root)

```text
scripts/foreman/verify_test_coverage.py   # --tolerant, parser, file-level check, report fields
docs/foreman.md                           # tolerant grammar + CLI table + JSON shape
tests/foreman/test_verify_test_coverage.py  # parser + e2e tolerant/strict/regression
# Phase 7 (SC-001 rollout, optional same PR or follow-up):
specs/028-dispatch-telemetry/tasks.md
specs/018-testing-strategy/tasks.md
specs/022-e2e-quality-harness/tasks.md
specs/_archive/025-simplify-pass/tasks.md          # file-only Testing Requirements blocks (Phase 7)
```

## TDD strategy

1. **Contract tests first** — parser accepts/rejects file-only lines per `contracts/tolerant-requirements.contract.md` (strict vs tolerant mode flag to `parse_tasks_md(..., matching_mode=...)`).
2. **Primitive** — `check_file_has_passing_test` RED tests (pass / all-skipped / missing file).
3. **E2E `verify()`** — tiny git worktree + `tasks.md` + test file; assert JSON `matching_mode` + exit codes.
4. **Regression** — run existing strict golden cases with default mode; assert byte-identical behaviour for strict JSON fields (modulo new `matching_mode: "strict"` additive field — document as intentional additive change in tasks T019).
5. **FR-008 property** — strict-PASS fixture also PASSes under `--tolerant`.

## Phase 0 — Research (→ research.md)

Decisions **D1–D6**: flag surface; file-level PASSED bar; file-only grammar; report stamping; retro sequencing; strict regression guard.

## Phase 1 — Design (→ contracts/)

- `contracts/tolerant-requirements.contract.md` — file-only `**Test N**` line grammar + strict/tolerant parse errors.
- `contracts/verdict-report.contract.md` — `summary.matching_mode`, tolerant requirement row shape, human banner text.
- `quickstart.md` — run tolerant retro on a spec; interpret PASS vs strict PASS.

## Complexity / risks

| Risk | Mitigation |
|------|------------|
| File-level `pytest` slower than single node | Acceptable for manual retro; document in quickstart. |
| Additive `matching_mode` field breaks strict JSON consumers | Default `"strict"`; note in CHANGELOG + foreman.md; tests assert field present. |
| Retro `tasks.md` authoring is large (028 `@ fc24a43`) | Phase 7 sequenced; can split to follow-up PR after mechanism merges. |
| Strict-shaped lines in tolerant mode still run per-node path | Allowed (superset); document that file-only is the intended retro shape. |
