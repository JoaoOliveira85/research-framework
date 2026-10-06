# Contract: `speckit coverage`

**Sub-command**: `speckit coverage`
**Version**: v0.3+

---

## Synopsis

```
speckit coverage --vault <dir> [--output json|text]
```

---

## Arguments

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `--vault` | path | Yes | — | Path to vault root directory |
| `--output` | string | No | text | Output format: `text` (human) or `json` (machine) |

---

## Behavior

Reads `{vault}/_pipeline/coverage-targets.json` and reports:
- Which categories are met (met_count ≥ target_count)
- Which categories are unmet and by how much (gap)
- Whether all targets are met (Phase 3 gate status)

Does not modify any files.

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All coverage targets met — Phase 3 gate OPEN |
| 1 | One or more targets unmet — Phase 3 gate CLOSED |
| 2 | Abort: `coverage-targets.json` missing or malformed |

---

## Output Format (text, mixed example)

```
Coverage Targets — 001-speckit-implementation
─────────────────────────────────────────────
Category             Target   Met   Status
concepts             40       31    ✗ UNMET (gap: 9)
services             20       20    ✓ MET
team-structures      10       8     ✗ UNMET (gap: 2)
market-context       15       4     ✗ UNMET (gap: 11)
decision-records     10       10    ✓ MET

Phase 3 gate: CLOSED — 3 categories unmet
Run: speckit generate --spec vault-spec.md --resume
```

---

## Output Format (json)

```json
{
  "phase3_gate": "closed",
  "cycle_number": 2,
  "categories": [
    {
      "name": "concepts",
      "target_count": 40,
      "met_count": 31,
      "met": false,
      "gap": 9
    }
  ],
  "summary": "3 of 5 categories unmet"
}
```

---

## Error Cases

| Condition | Exit | Output |
|-----------|------|--------|
| `--vault` path does not exist | 2 | "vault directory not found: {path}" |
| `coverage-targets.json` missing | 2 | "coverage-targets.json not found; run Phase 1 first" |
| JSON parse failure | 2 | "coverage-targets.json is malformed: {error}" |
