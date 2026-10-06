# Contract: `BUDGET_PAUSED` marker

**Status**: Locked at spec 033 plan time (2026-05-26)  
**Companion**: [`approval-marker.contract.md`](./approval-marker.contract.md) (separate pause kind)  
**Input telemetry**: [`specs/028-dispatch-telemetry/contracts/sidecar-v1.contract.md`](../../028-dispatch-telemetry/contracts/sidecar-v1.contract.md)

---

## 1 — File location

```text
<vault>/_pipeline/BUDGET_PAUSED
```

Single file per vault root. **Not** nested under `cycles/` — resume must find it without cycle-dir context. Latest pause wins (overwrite via atomic replace).

**Mutual exclusion per event**: When pausing for budget/wallclock/codex, MUST NOT write `APPROVAL_REQUIRED` in the same atomic transaction. Approval pauses use the sibling contract only.

---

## 2 — JSON document schema

### 2.1 — Required fields

| Field | Type | Constraints |
|-------|------|-------------|
| `schema_version` | string | Must be `"1.0"` |
| `pause_reason` | string | One of §2.2 enum |
| `cycle_number` | integer | ≥ 1 |
| `paused_at` | string | ISO-8601 UTC |
| `paused_stage` | string | Stage that would have been dispatched |
| `cumulative_spend_usd` | number | ≥ 0, 4 decimal places |
| `cycle_budget_usd` | number | > 0 when `pause_reason == dollar_cap_exceeded` |
| `dispatch_estimate_usd` | number | ≥ 0 |

### 2.2 — `pause_reason` enum (normative)

| Value | When |
|-------|------|
| `dollar_cap_exceeded` | `(actual_usd + estimate_usd) > cycle_budget_usd` (FR-002 strict exceed) |
| `wallclock_exceeded` | `elapsed_monotonic > wallclock_cap_seconds` (equality allowed to continue — see research.md §5) |
| `codex_token_cap_exceeded` | `(actual_codex_tokens + estimate_tokens) > codex_token_budget` |

**Forbidden**: `approval_required` or any approval semantics — use `APPROVAL_REQUIRED` marker.

### 2.3 — Conditional fields

| Field | When required |
|-------|---------------|
| `codex_tokens_cumulative` | `pause_reason == codex_token_cap_exceeded` |
| `codex_token_budget` | `pause_reason == codex_token_cap_exceeded` |
| `wallclock_elapsed_seconds` | `pause_reason == wallclock_exceeded` |
| `wallclock_cap_seconds` | `pause_reason == wallclock_exceeded` |
| `blocked_dispatch_preview` | Recommended always; max 200 chars |

### 2.4 — JSON Schema (draft 2020-12)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://research-framework.local/schemas/budget-paused-1.0.json",
  "title": "BudgetPausedMarkerV1",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version",
    "pause_reason",
    "cycle_number",
    "paused_at",
    "paused_stage",
    "cumulative_spend_usd",
    "cycle_budget_usd",
    "dispatch_estimate_usd"
  ],
  "properties": {
    "schema_version": { "const": "1.0" },
    "pause_reason": {
      "enum": [
        "dollar_cap_exceeded",
        "wallclock_exceeded",
        "codex_token_cap_exceeded"
      ]
    },
    "cycle_number": { "type": "integer", "minimum": 1 },
    "paused_at": { "type": "string" },
    "paused_stage": { "type": "string", "minLength": 1 },
    "cumulative_spend_usd": { "type": "number", "minimum": 0 },
    "cycle_budget_usd": { "type": "number", "minimum": 0 },
    "dispatch_estimate_usd": { "type": "number", "minimum": 0 },
    "codex_tokens_cumulative": { "type": "integer", "minimum": 0 },
    "codex_token_budget": { "type": "integer", "minimum": 1 },
    "wallclock_elapsed_seconds": { "type": "number", "minimum": 0 },
    "wallclock_cap_seconds": { "type": "number", "minimum": 0 },
    "blocked_dispatch_preview": { "type": "string", "maxLength": 200 }
  },
  "allOf": [
    {
      "if": {
        "properties": { "pause_reason": { "const": "dollar_cap_exceeded" } },
        "required": ["pause_reason"]
      },
      "then": {
        "properties": {
          "cycle_budget_usd": { "type": "number", "exclusiveMinimum": 0 }
        }
      }
    },
    {
      "if": {
        "properties": { "pause_reason": { "const": "wallclock_exceeded" } },
        "required": ["pause_reason"]
      },
      "then": {
        "required": ["wallclock_elapsed_seconds", "wallclock_cap_seconds"]
      }
    },
    {
      "if": {
        "properties": { "pause_reason": { "const": "codex_token_cap_exceeded" } },
        "required": ["pause_reason"]
      },
      "then": {
        "required": ["codex_tokens_cumulative", "codex_token_budget"]
      }
    }
  ]
}
```

The `allOf` block enforces the §2.1 "`cycle_budget_usd` > 0 when `pause_reason == dollar_cap_exceeded`" rule via `exclusiveMinimum: 0` and the §2.3 conditional `required` fields per `pause_reason` value. JSON Schema validators that don't implement `if/then` (draft-04 etc.) MUST be rejected upstream — spec 033 targets draft 2020-12 specifically.

---

## 3 — Write protocol

1. Compute pause payload from `budget_guard.check()` failure.
2. Write to `<vault>/_pipeline/.BUDGET_PAUSED.<pid>.tmp` (or `secrets.token_hex` suffix).
3. `os.replace(tmp, final)` → `_pipeline/BUDGET_PAUSED`.
4. Exit process with code `1` and stderr message including `pause_reason`, spend snapshot, resume hint.

**Invariant**: Marker MUST exist before process exit on pause. Partial vault state from in-flight stage is acceptable (same as spec 031 constrained exit).

---

## 4 — Read protocol (`./vault research --resume`)

1. If `BUDGET_PAUSED` missing → skip budget resume branch.
2. Parse JSON; validate `schema_version`.
3. Recompute current spend from sidecar v1.1 glob (028 §5.1) — do not trust marker alone for resume decision.
4. If still over cap and no `--force-budget`:
   - TTY: print marker summary; exit `1` with "bump cycle_budget_usd or pass --force-budget".
   - Headless: JSON error; require `RF_FORCE_BUDGET_ACK=1` when `--force-budget` passed.
5. If cap now satisfied (operator bumped settings): delete marker (or rename to `.resolved`) and continue cycle from `paused_stage` — see §4.5 below for what that means.
6. `--force-budget` path: TTY y/N confirmation; headless needs `RF_FORCE_BUDGET_ACK=1`.

**Precedence**: Budget marker checked before `APPROVAL_REQUIRED` when both exist (operator resolves budget first).

### 4.5 — "Continue cycle from `paused_stage`" *(amended 2026-09-07 — issue #235)*

Between spec 033 shipping and this amendment, §4.5 read as one clause and was
implemented by nobody: `paused_stage` was written into every marker and read by
no code, so a cycle that paused at the note-writer re-dispatched scout on resume
and paid for it a second time. This is what the clause means, normatively.

**The unit of resume is the PHASE, not the dispatch.** `paused_stage` names a
dispatch stage (the `--stage` argument of the `agent_call.py` invocation the
guard blocked). Each such stage belongs to one phase of the cycle runner's
sequence, and resume restarts at that phase:

| `paused_stage` | Phase resumed at | Not re-run |
|----------------|------------------|-----------|
| `scout` | scout | *(nothing — no dispatch had happened yet)* |
| `note_writer` | research | source extraction, scout |
| `verifier` | research | source extraction, scout |

Only stages the in-process budget guard can observe are mapped, because only
those can ever appear in a marker. **An unrecognised stage MUST resume the whole
cycle** and MUST say so (one WARNING naming the stage). Skipping a phase on a
name this build cannot place would drop work the cycle still owes; re-running it
only re-spends money, and does it loudly.

**A skipped phase still yields its result**, rebuilt from that phase's own
on-disk report (`cycle-NNN-scout.json`, `cycle-NNN-research.json`) — the same
files the phase's result was always derived from. A resumed cycle must not look
like one that scouted nothing.

**Preflight and pre-cycle metrics always run.** They dispatch nothing, and the
cycle's own bookkeeping depends on them.

**The plan is process-scoped and single-shot.** The stage is read before the
marker is cleared, is acted on only if the read protocol above let the resume
through (a refusal leaves the pause standing and promises no skip), and is
consumed once. It is deliberately NOT persisted: a stale resume plan on disk
would silently skip phases of an unrelated later run, whereas a plan lost to a
crash costs one full re-run. `--force-budget` honours the plan identically —
forcing past a cap is consent to overspend from here, not an instruction to
re-buy what is already bought.

**Not in scope: batch-level resume.** A pause at note-writer batch 3 re-runs
batches 1–3, because the marker records no batch index. Stage granularity is
exactly what the marker's field carries; anything finer needs a new field and a
new version of this contract.

---

## 5 — Clear protocol

Marker removed when:
- Resume succeeds under new cap, or
- `--force-budget` acknowledged, or
- Operator aborts cycle (explicit cleanup command — see §5.1).

### 5.1 — The explicit cleanup command *(amended 2026-09-07 — issue #237)*

The third bullet named a command that did not exist for as long as this
contract has. Abandoning a paused cycle meant `rm _pipeline/BUDGET_PAUSED`, and
nothing would tell an operator what the marker held first. It is now
`research-framework pause show | clear --vault <vault>` (the `./vault
research --clear-pause` sketch above it is superseded: clearing is not a
resume, and giving it its own verb keeps it out of the flag surface of one
that is).

**`show` is read-only and MUST NOT fail on an unreadable marker.** It renders
the fields §4.3 re-checks — `pause_reason`, `paused_stage`, `paused_at`,
`cumulative_spend_usd`, `cycle_budget_usd`, `dispatch_estimate_usd`, the
`pause_reason`-conditional fields of §2.3, and `blocked_dispatch_preview` —
and for a marker this build cannot parse it reports the path and the parse
error and still exits 0. A diagnostic that disappears exactly when the state is
broken is not a diagnostic. It MUST NOT render a field set of its own: a second
reader of this marker drifts from the first.

**`clear` MUST require an explicit acknowledgement** — a y/N on a TTY (with the
marker rendered first), `--yes` headless — because it destroys the operator's
record of why a run stopped.

**`clear` is the ONE sanctioned path for a marker this build cannot read.**
§4.2's refusal is deliberate (resuming over an unreadable pause would drop
whichever cap stopped the run) and left that state with no way out but a manual
delete. Clearing is not resuming: the paused cycle re-runs from its start, so
nothing is skipped on a stage this build could not read.

### 5.2 — No verb may walk past a standing marker *(added 2026-09-07 — issue #233)*

Only `generate --resume` ever read these markers. `research-framework cycle`
ignored one and re-dispatched the paused stage, paying for it a second time —
the same double-spend §4.5 was amended to stop, reached through a different
verb.

A run verb with no `--force-budget` / `--approve` surface is in no position to
DECIDE a pause, so it MUST refuse to start while one stands: exit 2, naming the
marker's path, `pause show`, and the resume that can clear it. The refusal is
cycle-agnostic — the marker is vault-level (§1), and "a pause exists" is the
only reading such a verb is entitled to.

---

## 6 — Consumer checklist

- [ ] Atomic `os.replace` write
- [ ] `pause_reason` never includes approval
- [ ] Pre-dispatch pause (no dispatch that would strict-exceed)
- [ ] Resume re-sums sidecar v1.1 actuals
- [ ] Inclusive `<=` on cap (pause only on `>`)
- [ ] Resume starts at `paused_stage`'s phase (§4.5); an unmapped stage re-runs the whole cycle, loudly
