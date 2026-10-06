# Phase 1 Data Model: Cycle-budget configuration consolidation

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-06-05

Two entities: the **resolver result** (in-memory, CLI-internal) and the
**run-report provenance block** (persisted, additive). No new on-disk schema file;
the run-report JSON gains one nested object.

## Entity 1 — `BudgetResolution` (in-memory, `cli/_budget_resolve.py`)

The output of the single precedence resolver (D3). One per run, computed at CLI entry.

| Field | Type | Notes |
| --- | --- | --- |
| `max_cycles` | `int` (≥1) | The effective per-cycle budget. |
| `max_cycles_source` | `"flag" \| "settings" \| "default"` | Where `max_cycles` came from. |
| `max_usd` | `float \| None` | Effective dollar cap (Q3); `None` = uncapped. A configured **zero also resolves to `None`** — see the 2026-09-07 amendment in `spec.md`. |
| `max_usd_source` | `"flag" \| "settings" \| "default"` | Where `max_usd` came from. |
| `deprecated_keys_seen` | `list[str]` | e.g. `["cycles.initial_max"]` — drives the FR1 WARNING. |

### Precedence ladder (the invariant under test)

```
--max-cycles CLI flag                         (highest)
  > settings pipeline.max_cycles              (VaultSettings.max_cycles)
    > built-in default                        (shipped seed value; ≈20)

deprecated alias (warn-and-honour, below canonical):
  settings cycles.initial_max / cycles.update_max
    → migrated into the canonical slot ONLY when pipeline.max_cycles is absent;
      always emits one logging.WARNING naming pipeline.max_cycles.
```

Rules:
- The spec contributes **nothing** (FR2 removed the fields; a stray value is dropped
  at parse time per research.md D2).
- When both `pipeline.max_cycles` and a deprecated `cycles.*` key are present, the
  canonical key wins **and** a WARNING fires (the deprecated value is *not* silently
  honoured — that was the original bug).
- `max_cycles ≤ 0` from any source is a usage error (exit 2).

## Entity 2 — `cycle_budget` run-report provenance (persisted, additive)

Written by `pipeline/run_report.py` into the run-report JSON; mirrored as one prose
line in `run-report.md`. Additive — existing consumers ignore the new object.

```json
{
  "cycle_budget": {
    "configured": 12,
    "source": "settings",
    "actual": 6,
    "exit_status": "constrained"
  }
}
```

| Field | Type | Notes |
| --- | --- | --- |
| `configured` | `int` | The resolved `max_cycles` (Entity 1). |
| `source` | `"flag" \| "settings" \| "default"` | Mirrors `max_cycles_source`. |
| `actual` | `int` | Cycles actually executed. |
| `exit_status` | `"complete" \| "constrained" \| "aborted"` | Mirrors the rc→text map (`vault_commit.py:445`). |

Invariants (pinned by `test_run_report_budget_provenance.py`):
- A `max_cycles`-reached run ⇒ `exit_status == "constrained"` **and**
  `actual == configured` (the rc1 codebase-vault scenario: `configured=6`/`actual=6`
  with a WARNING, instead of a buried `12 → 6` print).
- A clean run ⇒ `exit_status == "complete"` and `actual ≤ configured`.

`run-report.md` line (human surface):

```
Cycle budget: 6 (source: settings) — ran 6 — exit: constrained (max_cycles reached)
```

## Migration / compatibility

- **Specs in the wild** carrying `max_cycles:`/`budget.max_usd:` keep parsing (silent
  drop, D2). No migration tool required.
- **Settings in the wild** carrying `cycles.initial_max`/`update_max` keep working for
  the grace period via the warn-and-honour alias; operators are told to move to
  `pipeline.max_cycles`.
- **No schema_version bump**: the run-report JSON object is additive; `BudgetConfig`
  loses fields but `from_dict` is `.get()`-based so older/newer specs interoperate.
