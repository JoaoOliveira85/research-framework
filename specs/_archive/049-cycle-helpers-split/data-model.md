# Data Model: `_cycle_helpers.py` God-Module Split

**Spec**: 049 | **Date**: 2026-06-03

This refactor introduces exactly **one** new data entity. Everything else is a code move with
no schema change (FR-005: byte-identical artifacts). The new type exists solely to retire the
two process-global mutable flags (FR-003 / SC-003).

---

## `CycleRuntimeState`

**Home**: `src/research_framework/pipeline/_helpers/cycle_state.py` (new submodule).
**Purpose**: hold the per-cycle mutable runtime flags that were module-level globals in
`_cycle_helpers.py`, so they are passed explicitly and cannot leak across cycles (US3).

```python
import dataclasses


@dataclasses.dataclass
class CycleRuntimeState:
    """Per-cycle mutable runtime flags (formerly module-global in _cycle_helpers).

    Constructed once per cycle in cycle_runner.run_cycle_steps and carried on
    CycleContext.runtime_state so every step sees the same instance. Replaces
    the process-global _should_abort_current_cycle / _last_note_writer_cap_tripped.
    """

    should_abort: bool = False           # was _should_abort_current_cycle (_cycle_helpers:27)
    note_writer_cap_tripped: bool = False  # was _last_note_writer_cap_tripped (_cycle_helpers:28)
```

### Fields

| Field | Type | Default | Replaces | Written by | Read by |
|---|---|---|---|---|---|
| `should_abort` | `bool` | `False` | `_should_abort_current_cycle` (global, `_cycle_helpers.py:27`) | `source_signals.notify_required_source_degraded` (was the `global` write at `_cycle_helpers.py:788`) | `steps/research.py:110` (was `h._should_abort_current_cycle`) |
| `note_writer_cap_tripped` | `bool` | `False` | `_last_note_writer_cap_tripped` (global, `_cycle_helpers.py:28`) | `steps/research.py:120` (was `h._last_note_writer_cap_tripped = True`) | (alias-only today; consumers read via the same field) |

### Lifecycle

1. **Construct** — `cycle_runner.run_cycle_steps` builds a fresh `CycleRuntimeState()` at the
   top of each call, replacing the two `h._… = False` resets at `cycle_runner.py:246-247`. One
   instance per cycle = no cross-cycle leakage (the latent footgun US3 names).
2. **Carry** — the instance is attached to `CycleContext` (the carrier already passed to every
   step) as a new `runtime_state` field. **No change to `run_cycle_steps`'s public signature**
   (CLAUDE.md "never change `run_cycle_steps`" rule).
3. **Mutate in place** — steps and `notify_required_source_degraded` flip `state.should_abort`
   / `state.note_writer_cap_tripped`. **Mutation is in-place attribute assignment on the object,
   not field reassignment on the context** — this is why it works even though `CycleContext` is
   `@dataclass(frozen=True)`: the frozen context holds an immutable *reference* to a mutable
   `CycleRuntimeState`; `state.should_abort = True` is legal, `ctx.runtime_state = …` is not.
4. **Discard** — goes out of scope at cycle end; nothing persists it to disk (these flags were
   never serialized — confirmed: no `_should_abort_current_cycle` / `_last_note_writer_cap_tripped`
   key appears in any artifact). FR-005 holds: no new bytes in any output.

### Carrier change — `CycleContext` (existing, `steps/_types.py:57`)

`CycleContext` is `@dataclass(frozen=True)`. Add one field:

```python
@dataclass(frozen=True)
class CycleContext:
    ...
    timer_label: str | None = None
    runtime_state: "CycleRuntimeState | None" = None   # NEW (Phase 7)
```

- Defaulting to `None` keeps every existing `CycleContext(...)` construction valid (no
  positional break) and keeps the field optional for any test that builds a context directly.
- `cycle_runner` populates it with the real instance for production cycles.
- Forward-reference the annotation (or import under `TYPE_CHECKING`) so `steps/_types.py` does
  not eagerly import `_helpers.cycle_state` — `cycle_state` is a pure leaf (only `dataclasses`),
  so an eager import is also acyclic; the forward-ref is the lighter choice and avoids any
  ordering concern. `/tasks` picks one — both satisfy FR-007.

### Validation / invariants

- **SC-003**: after Phase 7, `grep -rnE "^_[a-z_]+(: [a-zA-Z]+)? = (False|True|\{\}|\[\])$"
  src/research_framework/pipeline/_helpers/` returns **zero** module-level mutable globals.
- **Isolation invariant** (US3): two `CycleRuntimeState()` instances are independent; setting a
  flag on one does not affect the other. This is the single new unit test
  (`tests/pipeline/test_cycle_runtime_state.py`, Phase 1).
- **No serialization**: `CycleRuntimeState` is never written to `state.json` or any cycle
  artifact — it is purely in-memory control flow. (Distinct from `QualityReportState`, which is
  also a per-cycle dataclass but feeds the on-disk quality report; `QualityReportState` is a
  *moved*, not *new*, entity — it lands in `_helpers/state.py` unchanged.)

---

## Entities that MOVE but do NOT change (no schema impact)

For completeness — these are existing types relocated verbatim (no field changes, no behaviour
change, so not modelled in detail here):

- **`QualityReportState`** (dataclass, `_cycle_helpers.py:547`) → `_helpers/state.py`. Feeds the
  on-disk quality report via `_apply_exit_metadata`; moved unchanged.
- **`_StepError`** (Exception, `_cycle_helpers.py:37`) → `_helpers/script_runner.py`.
- **`MAX_SCOUT_VALIDATION_RETRIES`** (int constant, `=1`) → `_helpers/scout_correction.py`.
- **`_FRONTMATTER_DELIM`** (str constant, `"---"`) → `_helpers/cosmetic_correction.py`.

## NEEDS CLARIFICATION

None.
