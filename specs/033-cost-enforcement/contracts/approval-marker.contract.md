# Contract: `APPROVAL_REQUIRED` marker

**Status**: Locked at spec 033 plan time (2026-05-26)  
**Companion**: [`budget-marker.contract.md`](./budget-marker.contract.md)  
**Settings**: `settings.yaml::approval_gates: [<stage_name>, ...]` (opt-in; empty = disabled)

---

## 1 — File location

```text
<vault>/_pipeline/APPROVAL_REQUIRED
```

Separate from `BUDGET_PAUSED`. One approval pause at a time; new gate overwrites prior approval marker atomically.

---

## 2 — Opt-in semantics (`approval_gates`)

| Config | Behaviour |
|--------|-----------|
| Key absent or `[]` | No approval gates (FR-014 off) |
| `[stage_a, stage_b]` | Before dispatching `stage_a` or `stage_b`, write marker and exit |
| Unknown stage name | Ignored with WARN at settings load (tasks pin strict vs warn) |

Gates run **in addition to** dollar/wallclock/codex caps — order: budget pre-checks first, then approval gate for listed stages.

---

## 3 — JSON document schema

### 3.1 — Required fields

| Field | Type | Constraints |
|-------|------|-------------|
| `schema_version` | string | `"1.0"` |
| `stage_name` | string | Matches gated stage |
| `cycle_number` | integer | ≥ 1 |
| `paused_at` | string | ISO-8601 UTC |
| `prompt_preview` | string | Max 500 chars (FR-014) |
| `estimated_cost_usd` | number | ≥ 0 |
| `cumulative_spend_usd` | number | ≥ 0 |
| `tier` | string | Resolved tier for display |

### 3.2 — Optional fields

| Field | Type | When |
|-------|------|------|
| `agent` | string | Known resolved runtime pre-dispatch |
| `default_agent` | string | Vault default for context |

### 3.3 — JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://research-framework.local/schemas/approval-required-1.0.json",
  "title": "ApprovalRequiredMarkerV1",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version",
    "stage_name",
    "cycle_number",
    "paused_at",
    "prompt_preview",
    "estimated_cost_usd",
    "cumulative_spend_usd",
    "tier"
  ],
  "properties": {
    "schema_version": { "const": "1.0" },
    "stage_name": { "type": "string", "minLength": 1 },
    "cycle_number": { "type": "integer", "minimum": 1 },
    "paused_at": { "type": "string" },
    "prompt_preview": { "type": "string", "maxLength": 500 },
    "estimated_cost_usd": { "type": "number", "minimum": 0 },
    "cumulative_spend_usd": { "type": "number", "minimum": 0 },
    "tier": { "type": "string" },
    "agent": { "type": "string" },
    "default_agent": { "type": "string" }
  }
}
```

---

## 4 — Write protocol

1. Stage `S` is next dispatch; `S in approval_gates`.
2. Build `prompt_preview` from prompt bytes (truncate 500).
3. Call `cost_estimator.estimate()` for `estimated_cost_usd`.
4. Snapshot `cumulative_spend_usd` from `CycleSpendTally`.
5. Atomic write to `_pipeline/APPROVAL_REQUIRED` (temp + `os.replace`).
6. Exit `1` with message: `Approval required for stage '<S>' — run ./vault research --resume`.

**Must not** set `BUDGET_PAUSED.pause_reason` for approval.

---

## 5 — Resume / approve protocol

Shared entry: `./vault research --resume` (and `research-framework generate --resume`).

### 5.1 — TTY mode

`is_tty = stdin.isatty() and stdout.isatty()`

1. Load marker; display stage, tier, `estimated_cost_usd`, `cumulative_spend_usd`, `prompt_preview`.
2. Prompt: `Approve dispatch for <stage>? [y/N]`
3. `y` → clear marker, proceed with dispatch for that stage only.
4. `n` → keep marker, exit `1` (no retry).

#### 5.1a — Step 1 is normative *(added 2026-09-07 — issue #236)*

Until this amendment, step 1 did not exist in code. The implementation went
straight to step 2, so an operator consented to a paid dispatch with no idea
what it cost, what the cycle had already spent, or which tier it would run on
— every one of which the marker had persisted at §4 write time. This restates
step 1 as a requirement with a shape, not a suggestion.

- **Stream.** The summary goes to **stderr**, with the prompt. It is the reason
  a run stopped, and spec 070 FR6's stream rule exists because `> run.log`
  takes stdout away in the same breath as it drops the log level.
- **Fields.** `stage_name`, `cycle_number`, `tier`, `agent` (when present —
  §3.2 makes it optional and the render must not require it), `paused_at`,
  `estimated_cost_usd`, `cumulative_spend_usd`, `prompt_preview`, plus the
  **projected cycle total** (`cumulative_spend_usd + estimated_cost_usd`).
  That total is computed at render time and is deliberately NOT a marker field:
  it is a rendering of two fields §3.1 already requires, and a derived number
  in a versioned on-disk schema gives a later reader two sources for one fact.
- **When.** Before the y/N of step 2, and also before a `--approve <stage>`
  that clears the gate on a TTY — a flag is still a person watching a gate
  clear, and the cost is the one thing worth showing them. NOT before
  `--reject` (§5.4): that is a decision already taken, and there is nothing
  left to weigh.
- **Headless is unchanged.** §5.2 step 4's body stays exactly
  `{ "error": "approval_required", "stage": "..." }`. This amendment does not
  widen it.

### 5.2 — Headless mode

1. Refuse auto-approve.
2. Require CLI: `--approve <stage_name>` matching marker `stage_name`.
3. Env ack: `RF_APPROVE_<STAGE>_ACK=1` where `<STAGE>` is the stage identifier uppercased (stage names are already snake_case; no character translation needed). Example: `note_writer` → `RF_APPROVE_NOTE_WRITER_ACK=1`. If a stage with literal hyphens ever exists, treat `-` as a separator and replace with `_` for the env-var form.
4. Without flag + env → exit `1` with JSON body `{ "error": "approval_required", "stage": "..." }`.

### 5.3 — `--approve-all`

- TTY: single y/N listing all pending gates (if multiple — v1 may only support one marker; tasks document).
- Headless: requires `RF_APPROVE_ALL_ACK=1` in addition to `--approve-all` (FR-015).

### 5.4 — Rejection

- TTY `n` or `--reject <stage>`: marker retained, exit `1`, cycle report logs `approved: false`.

---

## 6 — Telemetry (cycle report)

Per cycle, append:

```yaml
approval_gates_fired:
  - stage: note_writer
    approved: true
    decided_at: "2026-05-26T18:00:00Z"
    decided_by_mode: tty   # or headless
```

### 6.1 — Decision record *(added 2026-09-07 — issue #235)*

Until this amendment `approval_gates_fired` was always `[]` in a real report.
The verdict is taken in the CLI process at resume time (§5); the cycle cost
report is written much later, inside the cycle runner, from a budget session
that never sees the CLI's arguments. Nothing joined the two, and the only
callers that ever supplied a value were tests passing their own rows.

The two halves are joined by a decision record:

```text
<vault>/_pipeline/approval-decisions.json
```

Vault-level, beside the markers whose resolution it records — not nested under
`cycles/`, for the same reason §1 gives.

```json
{
  "schema_version": "1.0",
  "decisions": [
    {
      "stage": "note_writer",
      "cycle_number": 3,
      "approved": true,
      "decided_at": "2026-09-07T10:00:00Z",
      "decided_by_mode": "tty"
    }
  ]
}
```

- `schema_version` is `const: "1.0"`; `decisions` is an array, append-only in
  decision order. `decided_by_mode` ∈ {`tty`, `headless`}.
- Written atomically (temp + `os.replace`, per issue #314), like every other
  `_pipeline` JSON.
- **A row is a DECISION, not a pause.** It is appended by every §5 branch where
  the operator said yes or no — including a rejection, which §5.4 already
  required to reach the report as `approved: false`. It is NOT appended by the
  branches that refuse to guess (no `--approve`, a stage mismatch, a missing env
  ack): "you gave me no flag" is not a verdict, and recording it as
  `approved: false` would put a decision in the report that nobody made. A gate
  that fired and was never resumed is represented by the marker; that cycle
  writes no report, because its process exited at the pause.
- **A record this build cannot read is never rewritten.** An unparseable file or
  an unrecognised `schema_version` means the write DECLINES (with a WARNING
  naming the file) rather than truncating the operator's record of every earlier
  verdict to make room for one row. Readers return no rows and WARN. A resume is
  never blocked by a telemetry write.
- The report's `approval_gates_fired` is the §6 row shape for that cycle:
  `cycle_number` is the record's addressing, not part of the row, since the
  report is already per-cycle.

---

## 7 — Forbidden patterns

- Auto-approve in headless without `--approve` + env ack.
- Writing approval state into `BUDGET_PAUSED.pause_reason`.
- Silent retry after rejection.
- Removing `BUDGET_PAUSED` when only approval was pending (independent files).
- Prompting for approval without first rendering §5.1a's summary.
- Recording an `ApprovalDecision` for an abandoned gate (§8).

---

## 8 — Abandoning a gate *(added 2026-09-07 — issue #237)*

`research-framework pause clear --vault <vault> [--marker approval]` deletes
`APPROVAL_REQUIRED` under an explicit acknowledgement (y/N on a TTY with the
marker rendered first; `--yes` headless). See
[`budget-marker.contract.md`](./budget-marker.contract.md) §5.1 for the verb's
shape, which is shared.

**It MUST NOT append a row to `approval-decisions.json`.** §6.1 draws the line
already: a row is a DECISION, appended by the branches where an operator said
yes or no, and never by the branches that refuse to guess. Abandoning a gate is
neither a yes nor a no — recording it as `approved: false` would put a verdict
in the cycle report that nobody reached, which is the exact defect §6.1 exists
to prevent.

A cycle whose gate is abandoned writes no report at all: its process exited at
the pause, and the next run starts that cycle over.
