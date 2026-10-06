# Contract: `speckit cycle`

**Sub-command**: `speckit cycle`
**Version**: v0.3+

---

## Synopsis

```
speckit cycle --vault <dir> --cycle <N> [--budget-cap <usd>]
```

---

## Arguments

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `--vault` | path | Yes | — | Path to vault root directory |
| `--cycle` | int | Yes | — | Cycle number to run (1-indexed) |
| `--budget-cap` | float | No | from spec | Override budget cap for this cycle only |

---

## Behavior

Runs a single research cycle manually (for debugging, targeted research, or recovery from
a failed cycle). Equivalent to calling `run_cycle.sh` directly but with precondition
checks and budget enforcement.

Sequence:
1. Check preconditions (same 5 as `speckit generate --resume`)
2. Check budget remaining ≥ estimated cycle cost
3. Call `scripts/run_cycle.sh {cycle} {vault} {max_cycles} {budget_cap}`
4. Read exit code from `run_cycle.sh`
5. Report cycle result (CONTINUE / TERMINATE / ABORT)

Does NOT automatically start the next cycle. Use `speckit generate --resume` for
automatic multi-cycle orchestration.

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Cycle completed; result is CONTINUE |
| 1 | Cycle completed; result is TERMINATE (check coverage targets) |
| 2 | Abort: precondition failed, budget exceeded, or structural error in cycle output |

---

## Output

```
Cycle 3 — Acme Corp Codebase Vault
─────────────────────────────────────
Pre-snapshot: 157 notes
Scout: ✓ (all 5 dimensions covered; 3 new topics)
DFS:   ✓ (9 notes written)
Post-snapshot: 166 notes (+9)
Validation: ✓ (0 errors)
Result: CONTINUE

Budget consumed this cycle: $0.42
Total budget consumed: $3.87 / $10.00
```

---

## Error Cases

| Condition | Exit | Output |
|-----------|------|--------|
| `--vault` path does not exist | 2 | "vault directory not found: {path}" |
| Precondition check fails | 2 | Full precondition report |
| Budget cap exceeded | 2 | "budget cap exceeded: {consumed} of {cap} already spent" |
| `run_cycle.sh` exits 2 (abort) | 2 | Full script output + "cycle aborted: fix structural error" |
| `claude` CLI not found in PATH | 2 | "claude CLI not found; install and authenticate before Phase 2" |
