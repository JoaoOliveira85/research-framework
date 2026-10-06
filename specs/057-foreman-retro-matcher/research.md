# Research & Decisions: 057 Foreman Retro Coverage — Tolerant Matching Mode

Phase 0 decisions. Inputs: clarify Session 2026-06-03 + audit of
`scripts/foreman/verify_test_coverage.py` + `docs/foreman.md` parser contract +
reference enrichment `test-design/028-retro` @ `fc24a43` (strict-named blocks today;
file-only grammar is net-new).

## Audit (current Arm A, backlog-specs base)

| Surface | Today | Gap for retro |
|---|---|---|
| Parser | `_REQUIRED_TEST_RE` requires `` `path::function` `` | Pre-pattern specs have no blocks; retro needs **file-only** lines |
| Verify | Per-node `pytest path::func` + AST + optional TDD timeline | Retro ignores function + TDD |
| CLI | `--tasks`, `--workdir`, `--json`, `--base-ref` | No `--tolerant` |
| Report | No `matching_mode` field | Cannot distinguish tolerant vs strict PASS |
| Tests | `tests/foreman/test_verify_test_coverage.py` (~770 LOC) | No tolerant paths |

The verifier is already stdlib-only (Principle V) and deterministic (Principle IV).
This feature extends it in-place — no Arm B changes.

## D1 — Mode selection: `--tolerant` flag (Q1)

**Decision**: Add `--tolerant` to `_build_parser()`; thread `matching_mode: Literal["strict","tolerant"]`
through `verify()` → `_verify_requirement()` / new `_verify_file_requirement()`.
Default = strict (unchanged code path when flag absent).

**Why**: Explicit operator intent; avoids auto-detect ambiguity (a strict spec accidentally
parsed as tolerant). Downstream gates can key off `summary.matching_mode`.

**Rejected**: Separate subcommand / script (duplication); auto-detect from file-only lines
without flag (silent mode flip); distinct exit-code tier only (insufficient for JSON consumers).

## D2 — Covered bar: file-level pytest with PASSED-only rule (Q2)

**Decision**: In tolerant mode, satisfaction = `check_file_exists` ∧
`check_file_has_passing_test(workdir, path)` where the latter runs
`pytest -v --tb=short <path>` and applies the **same** `PASSED`-line regex discipline
as `check_pytest_run` (no skip/xfail/empty-file pass — reuses PR #29 lesson).

**Why**: Matches the spec's "≥1 passing test" bar without inventing import-graph analysis.
Arm B already owns vacuous-test / mocked-UUT semantics per `docs/foreman.md` §What the
verifier does NOT enforce.

**Rejected**: `pytest --collect-only` only (doesn't prove pass); AST import-of-`src/` heuristic
(false negatives on integration tests; violates "insurance not diagnosis").

## D3 — File-only grammar: same header, relaxed Test line (Q4 / FR-004)

**Decision**: Under `### Testing Requirements`, tolerant mode accepts:

```
- **Test <N>**: `tests/foo/test_bar.py`
```

(no `::function`). Strict mode continues to require `` `path::function` ``; a file-only
line in strict mode is a `ParseError` (exit 2). In tolerant mode, a line with `::function`
is still accepted (strict-shaped lines are a superset — relaxation property FR-008).

**Rejected**: New heading `### Tolerant Testing Requirements` (splits authoring docs;
foreman.md would need a second grammar); bare `- tests/foo.py` bullets (too loose to parse safely).

## D4 — Report shape: `matching_mode` stamp, no durable ledger (Q4)

**Decision**: Extend JSON `summary` with `"matching_mode": "strict"|"tolerant"`.
Human `_render_text` prepends `MODE: tolerant — file-level coverage only (not TDD-verified)`.
Tolerant requirement rows use `"test_id": "<path>"` only; `function_defined` /
`collected_by_pytest` / `tdd_timeline_ok` are `null` (omitted in tolerant rows is also OK
if tests pin presence). Never set `tdd_timeline_ok: true` in tolerant mode.

**Why**: FR-003 satisfied without a new file format; consumers check one field.

**Rejected**: `_pipeline/foreman-retro.json` ledger; embedding mode only in exit code.

## D5 — Retro rollout: mechanism here, blocks in Phase 7 (Q3)

**Decision**: This spec ships matcher + contracts + verifier tests. Phase 7 tasks author
file-only blocks per retro target in order **028 → 018 → 022 → 025**. `fc24a43` is a
**reference for which test files matter**, not authoritative grammar (those blocks are
strict-shaped today and will be converted or supplemented).

**Why**: SC-001 needs runnable retro, but converting four large `tasks.md` files is
orthogonal to the matcher and can land incrementally after the mechanism PR.

## D6 — Strict regression guard (FR-005 / SC-004)

**Decision**: Copy the existing strict parser/verify golden cases into a dedicated
`TestStrictModeUnchanged` class run **without** `--tolerant`. Add property test: for a
fixture `tasks.md` with strict blocks, `verify(..., tolerant=True)` status is PASS whenever
strict PASS (FR-008).

**Rejected**: Snapshot entire JSON report (brittle on unrelated summary counts).
