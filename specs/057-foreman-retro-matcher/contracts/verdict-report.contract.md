# Contract: Mode-tagged foreman verdict report (057)

Normative JSON + human shape emitted by `scripts/foreman/verify_test_coverage.py`
after this spec ships. Extends `docs/foreman.md` §JSON report shape.

## 1. Summary (additive fields)

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
  "tasks": [ … ]
}
```

| Field | Type | Required | Values |
|-------|------|----------|--------|
| `matching_mode` | string | **yes** (057+) | `"strict"` (default CLI) \| `"tolerant"` (`--tolerant`) |

**MUST**: When CLI omits `--tolerant`, `matching_mode` is `"strict"`.
**MUST**: When `--tolerant` is set, `matching_mode` is `"tolerant"`.

Downstream gates **MUST NOT** treat `matching_mode: "tolerant"` with overall exit 0 as
TDD-verified or strict foreman sign-off.

## 2. Strict requirement row (unchanged)

```json
{
  "test_id": "tests/pipeline/test_foo.py::test_bar",
  "file_exists": true,
  "function_defined": true,
  "collected_by_pytest": true,
  "test_passes": true,
  "tdd_timeline_ok": true,
  "status": "PASS",
  "reason": null
}
```

When `summary.matching_mode` is `"strict"`, rows MUST match the above semantics
(existing verifier behaviour).

## 3. Tolerant requirement row (file-only)

```json
{
  "test_id": "tests/pipeline/test_foo.py",
  "file_exists": true,
  "function_defined": null,
  "collected_by_pytest": null,
  "test_passes": true,
  "tdd_timeline_ok": null,
  "status": "PASS",
  "reason": null
}
```

| Field | Tolerant rule |
|-------|----------------|
| `test_id` | Repo-relative file path only (no `::`) |
| `function_defined` | always `null` |
| `collected_by_pytest` | always `null` |
| `test_passes` | `true` iff ≥1 PASSED in file; else `false` |
| `tdd_timeline_ok` | always `null` — **MUST NOT** be `true` in tolerant mode |

Fail example:

```json
{
  "test_id": "tests/missing/test_none.py",
  "file_exists": false,
  "function_defined": null,
  "collected_by_pytest": null,
  "test_passes": false,
  "tdd_timeline_ok": null,
  "status": "FAIL",
  "reason": "file tests/missing/test_none.py not present in workdir"
}
```

## 4. Task row

```json
{
  "id": "T003",
  "status": "PASS",
  "tdd_required": false,
  "impl_files": [],
  "requirements": [ … ]
}
```

In tolerant mode, `tdd_required` on the task report MUST be `false` even if the
markdown block contained `**TDD discipline**: required` (ignored per tolerant contract).

## 5. Human-readable banner

When `matching_mode` is `"tolerant"`, the text renderer MUST include as the second line
(after the title rule):

```
MODE: tolerant — file-level coverage only (not TDD-verified)
```

When `matching_mode` is `"strict"`, the banner MUST be:

```
MODE: strict
```

(or omit banner only if existing consumers break — **prefer** explicit `MODE: strict` for symmetry; implementer notes in T019).

## 6. Exit codes (unchanged)

| Code | Meaning |
|------|---------|
| 0 | All declared requirements satisfied (or only `NO_REQUIREMENTS` tasks) |
| 1 | ≥1 requirement failed |
| 2 | Parser / workdir error |

`matching_mode` does not change exit-code mapping.
