# Quickstart: Reading dispatch telemetry sidecars

After spec 028 ships, every LLM call in a cycle leaves a JSON sidecar under the cycle's `agent-calls/` folder.

## Where to look

```text
~/Documents/my-vault/_pipeline/cycles/cycle-003/agent-calls/
├── scout.json
├── note_writer-batch-1.json     # batched note-writer (--stage note_writer)
├── note_writer-batch-2.json
├── plan_narrator.json
└── probe_retrieval.json
```

## Inspect one call

```bash
cat ~/Documents/my-vault/_pipeline/cycles/cycle-003/agent-calls/plan_narrator.json | python3 -m json.tool
```

## Example sidecar (real agent, success)

```json
{
  "schema_version": "1.1",
  "stage": "plan_narrator",
  "agent": "claude",
  "agent_kind": "real",
  "tier": "standard",
  "status": "ok",
  "exit_code": 0,
  "cost_usd": 0.0423,
  "tokens_in": 8234,
  "tokens_out": 1856,
  "latency_ms": 4127,
  "started_at": "2026-05-26T17:40:31.256Z",
  "completed_at": "2026-05-26T17:40:35.383Z",
  "cycle": 3
}
```

## Sum cycle spend (operator)

```bash
python3 - <<'PY'
import json
from pathlib import Path
p = Path("~/Documents/my-vault/_pipeline/cycles/cycle-003/agent-calls").expanduser()
total = sum(json.loads(f.read_text()).get("cost_usd", 0) for f in p.glob("*.json"))
print(f"cycle-003 total_cost_usd ≈ {total:.4f}")
PY
```

The framework uses the same files internally for budget caps (`_sum_sidecar_costs`).

## Retries and batches

- Second `plan_narrator` dispatch in the same cycle → `plan_narrator-2.json` (not an overwrite).
- Note-writer batch 2 → `note_writer-batch-2.json` with optional `"batch_index": 2`, `"topic_count": 4`. The `note_writer` prefix matches the actual `--stage` argument used by the batched call (see `pipeline/steps/research.py`).

## Fake-agent test vaults

Fixture cycles keep `agent_kind: "fake"` and sentinel timestamps `2000-01-01T00:00:00Z` / `2000-01-01T00:00:01Z` for deterministic replay.
