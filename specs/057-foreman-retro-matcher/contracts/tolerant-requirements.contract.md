# Contract: Tolerant Testing Requirements blocks (057)

Extends the parser grammar in `docs/foreman.md` when the verifier runs with
`--tolerant`. Normative for `parse_tasks_md()` and tolerant verification.

## 0. Scope

- **In tolerant mode**: requirements are satisfied at **file** granularity.
- **In strict mode** (default): grammar unchanged — `` `path::function` `` required;
  file-only lines are **`ParseError`** (exit 2).
- Tasks without `### Testing Requirements` still report `NO_REQUIREMENTS` in either mode.

## 1. Task header

Unchanged from `docs/foreman.md`:

```
- [ ] T\d+ <prose>
- [X] T\d+ <prose>
```

`impl_files` extraction unchanged (used only when strict + TDD flag).

## 2. Section header

Unchanged — exact match:

```
### Testing Requirements
```

Optional author banner (informational, ignored by parser):

```
_Authored by … (retro / tolerant). Do not edit during implementation._
```

## 3. Required-test lines (tolerant)

Each required entry is a markdown list item:

```
- **Test <N>**: `<repo-relative-path.py>`
```

Where:
- `N` is a positive integer (`Test 1`, `Test 2`, …).
- `<repo-relative-path.py>` follows the same path rules as strict mode
  (no leading `/`, no `..`, no `~`, must end in `.py`).
- **MUST NOT** include `::function` in tolerant mode (if present, parsers MAY
  treat as strict-shaped and verify per-node — superset behaviour per FR-008).

### Strict-shaped lines in tolerant mode (optional superset)

```
- **Test <N>**: `<path.py>::<test_function>`
```

Accepted; verified with the existing per-node path (function + pass + optional TDD).
Retro authoring SHOULD prefer file-only lines.

## 4. TDD discipline line

In **tolerant mode**, the following lines are **ignored** (never fail, never checked):

```
**TDD discipline**: required
**TDD discipline**: not required
```

Authors SHOULD omit the line for retro blocks. If present, `tdd_required` on the task
report MUST be `false` for tolerant verification purposes.

## 5. Informational sub-bullets

Unchanged — ignored by parser:

```
  - Behavior: …
  - Tier: …
  - Notes: …
```

## 6. Parse errors (fail closed)

| Condition | Mode | Result |
|-----------|------|--------|
| `- **Test` prefix but line fails tolerant + strict grammar | either | `ParseError`, exit 2 |
| File-only line (no `::`) | strict | `ParseError`, exit 2 |
| Absolute / `..` / `~` path | either | `ParseError`, exit 2 |
| No requirements block | either | task `NO_REQUIREMENTS` |

## 7. Verification (tolerant)

For each parsed file requirement `path`:

| Check | Pass criterion |
|-------|----------------|
| `file_exists` | `(workdir / path).is_file()` |
| `has_passing_test` | `pytest -v <path>` output contains ≥1 line matching `PASSED` for a test in that file; skipped/xfail/error-only files → fail |

Requirement `status`: `PASS` iff both checks pass; else `FAIL` with `reason` identifying missing file vs zero passing tests.

Task `status`: `PASS` iff all requirements `PASS`; `FAIL` if any fail; `NO_REQUIREMENTS` if list empty.
