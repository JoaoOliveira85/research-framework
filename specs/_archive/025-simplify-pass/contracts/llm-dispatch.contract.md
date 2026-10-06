# Contract: LLM Dispatch via `scripts/agent_call.py`

**Owners**: Spec 024 US1 (the guard that enforces this) +
spec 025 US1/US2 (the production code that satisfies it).
**Status**: pinned at spec 025 plan time (2026-05-21).

This contract pins the invariants for every LLM-bound dispatch
in the codebase. Spec 024's LLM dispatch guard enforces it
statically; spec 025 A1/A2 satisfy it for the two known bypasses
(`plan_narrator`, `probe_retrieval`).

---

## § 1 — The single dispatcher

**Every** LLM-bound subprocess call (`claude`, `codex`, future
agents) MUST flow through `scripts/agent_call.py`. Direct
`subprocess.run([...])` or `subprocess.Popen([...])` invocations
of an agent CLI from production code are **forbidden**.

The dispatcher signature (current as of v0.2.33, may be tightened
during A1/A2 implementation):

```python
# scripts/agent_call.py
def dispatch(
    stage: str,                # see § 2 for permitted values
    prompt: str,               # the message body
    *,
    tier: str = "standard",    # "basic" | "standard" | "expert"
    agent: str | None = None,  # default = env RESEARCH_FRAMEWORK_DEFAULT_AGENT
    cycle_dir: Path | None = None,  # for cost-sidecar JSON output
    timeout_s: int = 600,
    # ... other existing kwargs ...
) -> AgentCallResult: ...
```

The dispatcher's responsibilities (preserved across spec 025):
1. Spawn the appropriate agent subprocess based on `agent`
   parameter or `RESEARCH_FRAMEWORK_DEFAULT_AGENT` env var.
2. Inject the configured tier as a CLI flag or env var to the
   agent.
3. Capture cost / latency / token metrics from the agent's
   output.
4. Write a cost-sidecar JSON to `cycle_dir / "agent-calls" /
   f"{stage}.json"` if `cycle_dir` is supplied.
5. Return `AgentCallResult` with `{stdout, stderr, exit_code,
   cost_usd, tokens_in, tokens_out, latency_ms}`.

---

## § 2 — Permitted stage values

The `stage` parameter MUST be one of the following enumerated
values (extended by spec 025 with the two new entries):

| Stage value | Producer | Description |
|-------------|----------|-------------|
| `scout` | `pipeline/cycle_runner.py::_run_scout` (pre-B3) / `pipeline/steps/scout.py::run_scout` (post-B3) | BFS scouting pass. |
| `note_writer` | `pipeline/cycle_runner.py` / `pipeline/steps/research.py` | DFS note generation. |
| `verifier` | `pipeline/cycle_runner.py::_run_verifier` (pre-B3) / `pipeline/steps/research.py` (post-B3) | Independent verifier reject pass. |
| `plan_narrator` | `pipeline/plan_narrator.py::prepend_narrative` | **NEW in spec 025 A1**. Plan-narrator stage. |
| `probe_retrieval` | `pipeline/cycle_runner.py` probe block (pre-B3) / `pipeline/steps/research.py` (post-B3) | **NEW in spec 025 A2**. Probe-cache retrieval stage. |
| `topic_classifier` | `pipeline/cycle_runner.py` | Topic classification helper. |
| (future) `source_relevance` | TBD | Future per-source relevance classifier. |
| (future) per-source-module stages | spec 020 modules | One stage per source module (`youtube`, `reddit`, …). |

Stage values are case-sensitive and snake_case. Adding a new
stage requires a spec or ADR (the LLM dispatch guard from spec
024 only permits values in this enumeration, plus the allowlisted
bypasses — which spec 025 reduces to zero).

---

## § 3 — Cost-sidecar JSON contract

Every routed call produces a sidecar JSON file at:

```text
<vault_dir>/_pipeline/cycles/cycle-<NNN>/agent-calls/<stage>.json
```

If a stage runs multiple times per cycle (e.g. `note_writer`
called once per topic batch), the dispatcher uses a numeric
suffix: `note_writer.json`, `note_writer-2.json`,
`note_writer-3.json`, etc. The numbering is monotonic per stage
per cycle.

### Sidecar schema

```json
{
  "schema_version": "1.0",
  "stage": "plan_narrator",
  "agent": "claude",
  "tier": "standard",
  "cost_usd": 0.0423,
  "tokens_in": 8234,
  "tokens_out": 1856,
  "latency_ms": 4127,
  "started_at": "2026-05-21T17:00:00Z",
  "completed_at": "2026-05-21T17:00:04.127Z",
  "exit_code": 0,
  "stderr_excerpt": "..."   # truncated to 500 chars on error
}
```

**Field constraints**:
- `schema_version`: always `"1.0"` for v0.2.33. Bump on
  breaking change.
- `stage`: matches the dispatcher call's `stage` parameter.
- `agent`: actual subprocess used (post-resolution of env
  default).
- `tier`: actual tier used (post-resolution of settings.yaml
  default).
- `cost_usd`: non-negative float; `0.0` for fake_agent stubs.
  Truncated to 4 decimal places.
- `tokens_in` / `tokens_out`: non-negative integers; `0` for
  fake_agent stubs.
- `latency_ms`: non-negative integer (wall-clock).
- `started_at` / `completed_at`: ISO-8601 UTC timestamps;
  `completed_at >= started_at`.
- `exit_code`: subprocess exit code; `0` for success.
- `stderr_excerpt`: only present if `exit_code != 0`; truncated
  to 500 chars.

**Determinism (for tests with fake_agent)**: When `agent` is the
fake_agent, the dispatcher MUST write deterministic timestamps
(e.g. `"2000-01-01T00:00:00Z"` for `started_at`,
`"2000-01-01T00:00:01Z"` for `completed_at` — exact values are
spec 024's contract, not 025's). This makes the sidecar JSON
byte-identical across test runs.

---

## § 4 — Forbidden patterns

The LLM dispatch guard (spec 024 US1) scans the codebase for
these forbidden patterns:

1. `subprocess.run(["claude", ...])` or
   `subprocess.run(["codex", ...])` outside `scripts/agent_call.py`.
2. `subprocess.Popen(["claude", ...])` or
   `subprocess.Popen(["codex", ...])` outside `scripts/agent_call.py`.
3. `os.execv*` of `claude` or `codex` from production code.
4. Shell-string invocations: `subprocess.run("claude -p ...",
   shell=True)`.

The guard reports violations with file:line numbers. An
**allowlist** at `tests/_helpers/llm_dispatch_allowlist.yaml`
(owned by spec 024) lists temporarily-permitted violations. Spec
025's top-level acceptance criterion (SC-003) is that this
allowlist is **EMPTY** after A1 + A2 ship.

---

## § 5 — Migration sequence for spec 025 A1 + A2

**A1 (US1) — `pipeline/plan_narrator.py`**:

Pre-refactor (~v0.2.33):
```python
# pipeline/plan_narrator.py — VIOLATES § 1
result = subprocess.run(
    ["claude", "-p", prompt],
    capture_output=True, text=True,
)
narrative = result.stdout
```

Post-A1:
```python
# pipeline/plan_narrator.py — COMPLIANT
from research_framework.scripts.agent_call import dispatch

call_result = dispatch(
    stage="plan_narrator",
    prompt=prompt,
    tier=settings.stages.get(
        "plan_narrator", StageSettings(tier="standard")
    ).tier,
    cycle_dir=cycle_dir,
)
narrative = call_result.stdout
```

The dispatcher handles env-default agent resolution, cost
sidecar, and tier wiring.

**A2 (US2) — `pipeline/cycle_runner.py` probe block (~lines
1137–1252 at v0.2.33)**:

Same pattern. Replace the direct subprocess call with
`dispatch(stage="probe_retrieval", ...)`.

**Allowlist update**: in the SAME commit, delete the two
allowlist entries for `pipeline/plan_narrator.py` and the probe
block from
`tests/_helpers/llm_dispatch_allowlist.yaml`. The file becomes
empty (or contains only the YAML header comment).

---

## § 6 — Test enforcement

Spec 025 ships these tests for the contract:

| Test | Assertion |
|------|-----------|
| `tests/pipeline/test_plan_narrator.py::test_dispatch_through_agent_call` | The narrator call goes through `agent_call.dispatch(stage="plan_narrator", ...)`. Mock the dispatcher; assert the call was made with the right args. |
| `tests/pipeline/test_plan_narrator.py::test_codex_default_respected` | With `RESEARCH_FRAMEWORK_DEFAULT_AGENT=codex`, the dispatcher receives `agent=None` (defaults to codex) and the resulting sidecar's `agent` field is `"codex"`. |
| `tests/pipeline/test_plan_narrator.py::test_sidecar_written` | After a narrator call, `cycle-NNN/agent-calls/plan_narrator.json` exists with valid schema. |
| `tests/pipeline/test_cycle_runner_probe.py::test_dispatch_through_agent_call` | Same as the narrator test but for probe_retrieval. |
| `tests/_helpers/test_llm_dispatch_allowlist.py::test_allowlist_empty` | After A1 + A2, `tests/_helpers/llm_dispatch_allowlist.yaml` parses to `[]` or `None`. (Owned by spec 024 US1; spec 025 makes the assertion pass.) |

All five tests are tier-1 (unit) per ADR-0008 — they test pure
dispatch logic without invoking the real LLM.
