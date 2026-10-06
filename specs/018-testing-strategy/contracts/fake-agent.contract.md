# Contract: Fake Agent CLI (`tests/_helpers/fake_agent.py`)

**Status**: v2.2 (dispatch-contract parity, 2026-09-06) — extends v2.1
(unknown-stage fail-closed, 2026-09-06), v2 (testing-strategy refresh,
2026-05-21) and v1 (feature 018)  
**Replaces**: `scripts/agent_call.py` during tests only.  
**Producer**: `tests/_helpers/fake_agent.py` (CLI module + Python API).  
**Consumers**: `src/research_framework/pipeline/cycle_runner.py` (via subprocess),
`pipeline/plan_narrator.py` *(after QW-1)*, `tests/pipeline/test_full_cycle_e2e.py`,
`tests/pipeline/test_multi_cycle_e2e.py`.  
**Stability**: Internal — test-only. Breaking changes require updating every
consumer in the same PR.

**v2 changes**: documents `verifier`, `research_plan_narrator`, and
`probe_retrieval` stages (implementation = phase 2). Fixes stale
`research_vault` path references from v1.

**v2.1 changes** (issue #261): an unknown `--stage` is now **exit 2**, not a
silent exit-0 no-op with a `status: ok` sidecar — a stage-name typo and an
unwired stage used to be indistinguishable from a completed run. Adds the
weekly runner's `research` and `report` stages, which were among the stages
that fell through that no-op. `FAKE_AGENT_ALLOW_UNKNOWN_STAGE=1` restores the
old behaviour for a caller that genuinely wants it.

**v2.2 changes** (issue #262): "drop-in" is now an *enforced* invariant rather
than a claim in this paragraph. `tests/_helpers/test_fake_agent_parity.py`
derives the argv table, the `dispatch()` signature and the cost-sidecar keys
from `scripts/agent_call.py` itself and fails when the fake is not a superset
of each. Three divergences it found and this version closes: `--prompt-file`
is optional again (the real CLI falls back to stdin); the shim's in-process
`dispatch()` carries `model=` (`processors/extract.py` passes it on every
call); and the sidecar is schema **1.2** with `cost_source`, written on the
failure path too as `status: "failed"` with the exit code.

---

## a) Command-line interface

Drop-in replacement for `scripts/agent_call.py`. Every flag the real script
accepts is parsed; unhonored flags are accepted-and-ignored so the cycle
runner can use identical argv.

```text
python3 fake_agent.py \
    --vault <vault_dir>          # required
    --stage <stage>              # required — see § Stages
    [--prompt-file <path>]       # optional — stdin when omitted, as in the real CLI
    [--cost-sidecar <path>]      # optional — always write when provided
    [--output-file <path>]       # optional — stage-dependent (verifier)
    [--batch-index <n>]          # optional — accepted-and-ignored discriminator
    [--topic-count <n>]          # optional — accepted-and-ignored discriminator
```

The required/optional split is not restated here as a second source of truth:
`test_fake_agent_parity.py` reads the real parser and fails if the fake
rejects a flag the real CLI accepts, or demands one it leaves optional.

Exit codes: **0** success, **2** structural failure (missing spec, bad prompt,
unwritable path). Empty scout / skipped batch is **not** exit 2 — gates handle that.

### Stages

| Stage | v1 | v2 | v2.1 |
|-------|----|----|------|
| `scout` | ✅ | ✅ | ✅ |
| `note_writer` | ✅ | ✅ | ✅ |
| `verifier` | no-op | ✅ contract | ✅ |
| `research_plan_narrator` | n/a | ✅ contract | ✅ |
| `probe_retrieval` | n/a | ✅ contract | ✅ |
| `research` | n/a | n/a | ✅ (weekly runner) |
| `report` | n/a | n/a | ✅ (weekly runner) |
| *(unknown)* | exit 0 | exit 0 | **exit 2** unless `FAKE_AGENT_ALLOW_UNKNOWN_STAGE=1` |

### Scenario selection

| Env var | Applies to |
|---------|------------|
| `FAKE_AGENT_SCENARIO` | Global default (`happy`) |
| `FAKE_AGENT_SCOUT_SCENARIO` | `scout` |
| `FAKE_AGENT_NOTE_WRITER_SCENARIO` | `note_writer` |
| `FAKE_AGENT_VERIFIER_SCENARIO` | `verifier` |
| `FAKE_AGENT_RESEARCH_PLAN_NARRATOR_SCENARIO` | `research_plan_narrator` |
| `FAKE_AGENT_PROBE_RETRIEVAL_SCENARIO` | `probe_retrieval` |

Per-stage overrides beat global. Unknown scenario name → `ValueError` at
startup (fail loud in tests).

---

## b) Scenarios by stage

### scout + note_writer (shipped — v1)

| Scenario | scout | note_writer |
|----------|-------|-------------|
| `happy` | One `topics_found.new` row per uncovered target (quota-limited, sorted). | Writes all topics from `## Batch topics (JSON)` block. |
| `empty_scout` | Empty `topics_found.new` → validate_cycle ABORT. | n/a |
| `fail_frontmatter` | Same as `happy`. | First batch omits `source_urls` → SG-005 fail. |
| `oos_topic` | Adds one OOS-scoped topic. | Writes OOS note if asked. |
| `partial_yield` | Same as `happy`. | Writes K of N topics (`K = max(1, N // 2)`). |

### verifier (v2 — phase 2 implementation)

Reads `--prompt-file` for the note under review. Writes verdict JSON matching
`tests/fixtures/verifier/{accept,reject}-verdict.json` shape to stdout and/or
`--output-file`.

| Scenario | Behaviour |
|----------|-----------|
| `accept` | `{"verdict": "accept", "violations": [], "suggested_fix": null}` |
| `reject` | `{"verdict": "reject", "violations": [{"code": "SYNTHETIC", "message": "fake_agent reject scenario"}], "suggested_fix": "Add tier-2 sources"}` |
| `malformed_json` | stdout is `` ```json\n{not valid}\n``` `` or plain prose — exercises parser tolerance (ADR-0004) |

Cycle runner should treat `reject` like production: note flagged, may re-batch
or log per existing Step 3b logic.

### research_plan_narrator (v2 — phase 2 implementation)

| Scenario | Behaviour |
|----------|-----------|
| `happy` | stdout = deterministic markdown paragraph (≤200 words): `"Synthetic focus rationale for cycle N."` |
| `empty` | stdout = empty string → production fallback path in `plan_narrator.py` |
| `timeout_sim` | sleep not allowed — use exit 2 to simulate failure |

Writes cost sidecar when `--cost-sidecar` provided.

### probe_retrieval (v2 — phase 2 implementation)

| Scenario | Behaviour |
|----------|-----------|
| `happy` | stdout = JSON array of `{query, answer, sources[]}` — one entry per probe in prompt |
| `empty` | stdout = `[]` |

Used when cycle runner fills probe cache (Step 0). Deterministic answers only.

### research + report (v2.1 — weekly runner)

`pipeline/runner.py` drives a single-shot weekly run whose artifacts are FLAT
(`_pipeline/research-report.json`), not the cycle-numbered set `cycle_runner.py`
writes. Neither stage carries a scenario vocabulary yet; both accept any
globally valid `FAKE_AGENT_SCENARIO` and ignore it.

| Stage | Behaviour |
|-------|-----------|
| `research` | Writes a v2 research report to the `research-report.json` path **the prompt names**. A prompt naming none (an unrendered `{RESEARCH_REPORT}`) is exit 2 — the fake is the only thing positioned to catch a prompt-rendering bug. |
| `report` | Writes `_pipeline/exports/weekly-report.md` with the `type: weekly-report` frontmatter the vaults' own `report.md` agent specifies. The real agent names it `weekly-<today>.md`; a date would break § e, so the fake uses one fixed name in the same directory. |

---

## c) Input parsing (scout + note_writer)

Unchanged from v1 — see v1 contract in git history or below.

### Stage `scout`

Reads `<vault>/_pipeline/spec-parse.json`. Does **not** parse prompt body for
topic discovery (intentional separation of concerns).

### Stage `note_writer`

```python
BATCH_BLOCK_RE = re.compile(
    r"## Batch topics \(JSON\)\s*```json\s*(\[.*?\])\s*```", re.DOTALL
)
```

Legacy non-batched prompt: one note from first uncovered target.

---

## d) Output artefacts

### scout → `cycle-NNN-scout.json`

Unchanged v1 shape (`schema_version: "2.0"`, duplicate
`topics_from_code` + `topics_found.new` deliberate).

### note_writer → notes + `cycle-NNN-research.json`

Minimum frontmatter (SG-005 + verifier):

```yaml
---
type: concept
template_version: "1.0"
coverage_category: cat_a
source_urls:
  - https://synthetic.test/fake_agent/cat-a-topic-1
summary: |
  Synthetic note generated by tests/_helpers/fake_agent.py for "cat_a topic 1".
related: []
lifecycle:
  created_at_cycle: <cycle>
---
```

### verifier → stdout / `--output-file`

Verdict JSON only (no markdown wrapper in `accept`/`reject` scenarios).

### Cost sidecar (all stages)

When `--cost-sidecar` is provided the fake writes the **same schema the real
dispatcher writes** — `scripts/agent_call._build_sidecar_v11_payload`, schema
`1.2` — plus a `scenario` field the real writer has no analogue for. It is
written on the **failure** path too, because a stage that failed must be
visible in the `agent-calls` index; that is where `status`/`exit_code` earn
their place:

```json
{
  "schema_version": "1.2",
  "stage": "scout",
  "agent": "fake",
  "agent_kind": "fake",
  "tier": "standard",
  "status": "ok",
  "exit_code": 0,
  "cost_usd": 0.0,
  "cost_source": "none",
  "tokens_in": 0,
  "tokens_out": 0,
  "latency_ms": 0,
  "started_at": "2000-01-01T00:00:00Z",
  "completed_at": "2000-01-01T00:00:01Z",
  "cycle": 1,
  "scenario": "happy"
}
```

`cost_source: "none"` is deliberate: a fake call's `$0` is not a measurement,
and `"none"` is the literal `agent_call._resolve_cost` records when there is
neither a runtime signal nor an estimate. On a failed stage the payload
carries `"status": "failed"`, the real `exit_code`, and a `stderr_excerpt`.

---

## e) Determinism guarantee

For fixed `(vault fixture, cycle_num, scenario, stage, prompt_text)`:

- No `datetime.now()`, no `uuid`, no `random.*`
- `sorted()` iteration over dicts/sets
- `tempfile` + `os.replace` for atomic writes
- Timestamps derived: `f"2026-05-17T00:00:{cycle_num:02d}Z"`

---

## f) Phase 2 acceptance tests

Each new stage requires entries in:

1. This contract (§ Scenarios)
2. `fake_agent.py` implementation
3. `tests/_helpers/test_fake_agent_contract.py` — one test per scenario
4. At least one tier-4 test for `verifier` (`reject` path)

Stages `research_plan_narrator` and `probe_retrieval` need contract tests
only in phase 2; tier-4 consumers may wait until phase 3 routes production
through `agent_call.py`.
