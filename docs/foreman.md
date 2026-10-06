# Foreman Verification Pattern

> See **ADR-0010** for the architectural decision and rationale. This
> document is the **parser contract** for `Testing Requirements` blocks
> in `tasks.md` files. If you change anything here, update the verifier
> tests (`tests/foreman/test_verify_test_coverage.py`) and the
> test-designer skill (`.agents/skills/test-designer/SKILL.md`).

## Quick start

Every task in a spec's `tasks.md` MAY have a `### Testing Requirements`
subsection authored by the **test-design agent** before implementation
starts. The **deterministic verifier**
(`scripts/foreman/verify_test_coverage.py`) parses these blocks and
checks that each required test exists, is registered with pytest, and
passes.

If a task has no `Testing Requirements` block, the verifier reports
"no requirements declared" and skips the task. The block is opt-in;
adding it makes the task **verifiable**.

## Format

```markdown
- [ ] T003 Implement `pipeline/atomic_write.py` per contract X

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_atomic_write.py::test_write_text_atomic_replace`
    - Behavior: Mock `os.replace`; assert it is the final syscall on `write_text`.
    - Tier: 2
  - **Test 2**: `tests/pipeline/test_atomic_write.py::test_write_json_crash_before_replace`
    - Behavior: Inject fault before `os.replace`; assert target file is byte-unchanged.
    - Tier: 2
  - **Test 3**: `tests/pipeline/test_atomic_write.py::test_concurrent_reader_never_sees_partial_json`
    - Behavior: Thread-based; reader thread asserts only-valid-JSON across 100 iterations.
    - Tier: 3

  **TDD discipline**: required — tests above MUST be added in the same commit as or earlier than the implementation commit for `src/research_framework/pipeline/atomic_write.py`.
```

## Parser grammar (what the verifier reads)

The verifier scans each `tasks.md` line-by-line, accumulating tasks
and their requirements. The grammar is intentionally simple so it can
be parsed with regex; no external markdown library is used (Principle V
— no new runtime deps).

### Task header

```
- [ ] T\d+ <prose>      → start of a task block
- [X] T\d+ <prose>      → same, but already completed
- [x] T\d+ <prose>      → same, lowercase variant
```

The task ID is the `T\d+` portion. The block continues until the next
task header or until a section break (`---` or `## `).

### Testing Requirements header

Inside a task block, the verifier looks for:

```
### Testing Requirements
```

(exact match, case-sensitive, exactly one space between `###` and the
words). Any other heading ends the requirements block.

### Required-test lines

Each required test is a markdown list item of the form:

```
- **Test <N>**: `<path>::<function_name>`
```

Where:
- `N` is a positive integer (Test 1, Test 2, …); ordering is for
  human readability, not enforced.
- `<path>` is a **repo-relative** path ending in `.py`, e.g.
  `tests/pipeline/test_atomic_write.py`. Paths MUST NOT be absolute
  (no leading `/` or Windows drive letter), MUST NOT contain `..`
  segments (no parent traversal), and MUST NOT start with `~`. The
  verifier rejects any of these with a `ParseError` and exits 2.
- `<function_name>` is a Python identifier matching `^[a-z_][a-z0-9_]*$`
  conventionally starting with `test_`.

The `path::function_name` form mirrors pytest's node ID syntax so
operators can copy-paste into `pytest <node-id>`.

#### Strict-grammar enforcement

A line inside a `### Testing Requirements` block that **looks** like
a Test line (matches the weak prefix `- **Test`) but fails the strict
grammar above is treated as a **parser error**, not silently skipped.
The verifier exits 2 with a message identifying the offending line.

This closes a silent-skip loophole: previously, a typo like
`- **Test 1*: \`...\`` (missing one asterisk) or a Test line whose
path used the wrong quoting would parse as "no requirements declared"
and the foreman would report `NO_REQUIREMENTS` — a false-clean
verdict. Now the parser refuses to proceed until the malformed line
is fixed. Sub-bullets like `- Behavior:` and `- Tier:` remain
informational and are still ignored.

#### Optional sub-bullets

Sub-bullets under a `**Test N**` line are **informational** — the
verifier does not parse them. They exist for humans (the implementer
agent reads "Behavior:" to know what the test should do):

```
  - Behavior: <prose>
  - Tier: <number>           ← informational only
  - Notes: <prose>
```

### TDD-discipline flag

If the requirements block ends with:

```
**TDD discipline**: required
```

(exact match), the verifier ALSO checks that for every required test
file, the file's first commit is the same as or earlier than the
first commit of the corresponding implementation file. The
implementation file is inferred from the task's prose using a simple
heuristic: any `\`src/.../*.py\`` mentioned in the task prose. If
multiple impl files are mentioned, the timeline check applies to each.

If the line reads `**TDD discipline**: not required` (or the line is
absent), the timeline check is skipped.

The timeline check uses **commit topological order**
(`git log --reverse --topo-order base_ref..HEAD`), not wall-clock
timestamps. Same-second commits and timestamp-skewed commits (from
rebase, etc.) compare correctly because ordering reflects ancestry,
not the `%ct` field. The first commit that **touched** the impl file
(``ADD`` preferred; falls back to ``MODIFY`` if no add is present)
is compared against the first commit that touched the test file —
test position must be ≤ impl position, otherwise TDD is violated.

### Tolerant file-only lines (spec 057, `--tolerant`)

When the verifier runs with `--tolerant`, the grammar relaxes to **file
granularity** so a *shipped* spec can earn a coverage verdict without
back-filling per-function node IDs or a TDD timeline. A tolerant
required-test line omits the `::function` suffix:

```
- **Test <N>**: `<repo-relative-path.py>`
```

Tolerant-mode rules (full contract: `specs/057-foreman-retro-matcher/contracts/tolerant-requirements.contract.md`):

- File-only lines are **accepted** and verified as "file exists AND
  `pytest -v <path>` prints ≥1 `PASSED`". A missing file, a file with no
  tests, or a file whose tests are all SKIPPED/XFAIL/ERROR → FAIL.
- Strict-shaped `` `path::function` `` lines are **still accepted** (superset
  / FR-008) and verified per node, but the **TDD-timeline check is never run**
  in tolerant mode.
- `**TDD discipline**:` lines are **ignored**; the task row's `tdd_required`
  is forced to `false`. A tolerant PASS is therefore explicitly **not** a
  TDD or strict foreman sign-off.
- In **strict** mode (the default — no `--tolerant`) a file-only line is a
  `ParseError` (exit 2), exactly as before this spec.

## What the verifier does NOT enforce

- **Test quality**: a test that exists, is registered, and passes is
  PASSED, even if its assertions are vacuous. Foreman Arm B (the
  review subagent) catches this; the script does not.
- **Behavior alignment**: the "Behavior:" sub-bullet is documentation
  for the implementer, not a verifier input. The verifier cannot tell
  whether the test that landed actually exercises the behavior.
- **Cross-test coupling**: if Test 2 depends on state from Test 1,
  the verifier will not detect this. (Cross-test coupling is a
  test-design smell anyway.)
- **Tier accuracy**: the `Tier:` sub-bullet is informational. The
  verifier runs pytest in default mode (`pytest <node-id>`); tier
  routing is the spec's testing infrastructure's job (ADR-0008).

## Verifier CLI

```bash
python -m scripts.foreman.verify_test_coverage \
  --tasks specs/023-flow-separation/tasks.md \
  --workdir ~/src/research-framework-impl-023 \
  [--json] \
  [--base-ref origin/main] \
  [--tolerant]
```

| Flag | Description |
|---|---|
| `--tasks <path>` | Path to the `tasks.md` containing `Testing Requirements` blocks. Can be on the same branch or a separate branch. |
| `--workdir <path>` | Working directory to verify against. Must be a git worktree of the project repo. The verifier `cd`s here for AST + pytest invocations. |
| `--json` | Emit a structured JSON report to stdout (default: human-readable text). |
| `--base-ref <ref>` | The reference to compare against for the TDD-timeline check. Defaults to `origin/main`. |
| `--tolerant` | Tolerant retro mode (spec 057): verify at **file** granularity (file exists + ≥1 `PASSED`), accept file-only `` - **Test N**: `path.py` `` lines, and ignore TDD-discipline flags. The text/JSON report is stamped `MODE: tolerant` / `matching_mode: "tolerant"`. A tolerant PASS is **not** a TDD/strict sign-off. |

### Exit codes

| Code | Meaning |
|---|---|
| `0` | All declared `Testing Requirements` satisfied (or no requirements declared). |
| `1` | At least one requirement failed (missing file, missing function, failing test, or TDD timeline violation). |
| `2` | Parser error (malformed `tasks.md`, unparseable requirement line, missing workdir). |

### JSON report shape

The `summary.matching_mode` field (spec 057) is `"strict"` by default and
`"tolerant"` under `--tolerant`. Downstream gates MUST NOT treat a
`matching_mode: "tolerant"` exit-0 as a TDD/strict foreman sign-off. A
tolerant (file-only) requirement row sets `function_defined`,
`collected_by_pytest`, and `tdd_timeline_ok` to `null`, with `test_id` the
bare file path (see `specs/057-foreman-retro-matcher/contracts/verdict-report.contract.md`).

```json
{
  "summary": {
    "matching_mode": "strict",
    "tasks_total": 27,
    "tasks_with_requirements": 18,
    "tasks_without_requirements": 9,
    "tasks_passing": 17,
    "tasks_failing": 1,
    "requirements_total": 42,
    "requirements_passing": 40,
    "requirements_failing": 2
  },
  "tasks": [
    {
      "id": "T003",
      "status": "PASS",
      "tdd_required": true,
      "requirements": [
        {
          "test_id": "tests/pipeline/test_atomic_write.py::test_write_text_atomic_replace",
          "file_exists": true,
          "function_defined": true,
          "collected_by_pytest": true,
          "test_passes": true,
          "tdd_timeline_ok": true,
          "status": "PASS"
        }
      ]
    },
    {
      "id": "T012",
      "status": "FAIL",
      "tdd_required": false,
      "requirements": [
        {
          "test_id": "tests/cli/test_refresh_sources.py::test_exit_code_table",
          "file_exists": true,
          "function_defined": false,
          "collected_by_pytest": false,
          "test_passes": null,
          "tdd_timeline_ok": null,
          "status": "FAIL",
          "reason": "function 'test_exit_code_table' not found in tests/cli/test_refresh_sources.py"
        }
      ]
    }
  ]
}
```

## Authoring guidance (for the test-design agent)

- One `Testing Requirements` block per task that has executable
  behavior. Pure-prose tasks (e.g. "T001 Confirm Phase 1 scope...")
  can omit the block; the verifier ignores blockless tasks.
- Keep test counts realistic: 1–4 tests per task is typical. A task
  that needs 10+ tests is probably too broad and should be split.
- Prefer one test file per `src/...` module. Tests for
  `src/research_framework/pipeline/atomic_write.py` live in
  `tests/pipeline/test_atomic_write.py`, NOT in
  `tests/pipeline/test_atomic_write_<scenario>.py`.
- Test function names: lowercase, snake_case, start with `test_`,
  describe behavior ("test_write_text_atomic_replace"), not
  implementation ("test_calls_os_replace_function").
- TDD-required: set this for any task that introduces new behavior.
  Pure-refactor tasks can mark TDD as not required.
- Cross-reference the task's spec FR / contract: include a
  `Notes:` sub-bullet pointing at the section the test exercises.

## See also

- **ADR-0010**: the architectural decision and rationale.
- **`scripts/foreman/verify_test_coverage.py`**: the verifier
  implementation.
- **`tests/foreman/test_verify_test_coverage.py`**: parser + behavior
  tests for the verifier.
- **`.agents/skills/test-designer/SKILL.md`**: subagent prompt for
  authoring `Testing Requirements` blocks.
- **`.agents/skills/foreman/SKILL.md`**: subagent prompt for the
  Arm B (semantic review) role.
