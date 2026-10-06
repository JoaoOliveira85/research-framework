# Spec 004 — Python-Only Pipeline Orchestration + Verifier Wiring

**Status:** shipped(2026-05-12, commit 604d192) — **SHIPPED (early 0.2.x — pre-status-header-convention).** Landed across the foundational autonomous-pipeline window (`feat(004)` commits incl. `604d192` "verifier.py stage + wired into cycle_runner as Step 3b", pyproject `0.2.15`, 2026-05-12); `pipeline/orchestrator.py` + `pipeline/cycle_runner.py` carry the Python orchestration and verifier wiring today. Predates the CHANGELOG (which begins at 0.2.18) and the status-header convention.

## Problem Statement

The research cycle has two gaps that reduce determinism and testability:

**1. Unnecessary bash layer.** `orchestrator.run_single_cycle()` shells out to
`bash scripts/run_cycle.sh`, which in turn calls every stage as
`${PYTHON_BIN} scripts/<stage>.py`. The shell adds nothing — it forwards
arguments, threads environment variables, and chains exit codes. All of that
belongs in Python where it is testable, debuggable, and traceable. The current
design makes cycle behaviour hard to unit-test (you must mock a subprocess
call that itself calls subprocesses) and introduces subtle bugs around env
propagation and Python path resolution.

**2. Verifier skill is unwired.** `.agents/skills/verifier/SKILL.md` defines
an independent quality gate that checks citations, template compliance, source
policy, and drift flagging on individual notes. It is never called. The
pipeline ships notes that have no verified quality verdict, and `stubs.py`
masks this by treating absent `verifier_status` as neutral so cycles do not
stall — but this means the stub-free exit gate is silently disabled for the
most important quality dimension.

## Proposed Solution

**Part A — Python-native cycle runner**

Replace the `bash run_cycle.sh` subprocess in `run_single_cycle()` with a new
Python module `pipeline/cycle_runner.py`. Each stage is still called via
`subprocess.run([sys.executable, str(scripts_dir / "stage.py"), ...])` —
the scripts remain standalone and their 0/1/2 exit-code contract is unchanged.
What disappears is the bash indirection layer. Every step sequence, exit-code
check, env-var thread-through, and prompt substitution moves into Python.

`run_cycle.sh` stays on disk unchanged — generated vaults can still call it
directly, and it remains a debug escape hatch. The orchestrator just stops
calling it.

**Part B — Verifier stage**

After the DFS research step, before post-metrics:

```
scout → validate_scout → DFS → [NEW: verifier per note] → post-DFS checks
    → post-metrics → validate_research → topic_harvest → topic_propose
```

For each note listed in `notes_created + notes_updated` in the research report:

1. Call `agent_call.py --stage verifier --artifact-path <note> --artifact-type note`
2. Parse JSON verdict (`accept | pending | reject` + `violations` list)
3. Stamp the note's YAML frontmatter: `verifier_status: verified | pending | rejected`
   and `verifier_notes: [...]` on pending/rejected
4. Write `_pipeline/cycles/cycle-NNN-verifier.json` summarising all verdicts

Verdict handling:
- `accept` → `verifier_status: verified`; no other change
- `pending` → `verifier_status: pending`; `verifier_notes` set; note stays; stub scanner queues it for the next cycle
- `reject` → `verifier_status: rejected`; `verifier_notes` set; note stays in vault (not deleted); stub scanner queues it

Best-effort: a verifier failure or timeout on an individual note logs WARN,
stamps `verifier_status: pending`, and continues. The stage never halts the cycle.

**Part C — Re-tighten stub gate**

`pipeline/stubs.py::_FAILING_VERIFIER_STATUSES` currently excludes `""` (absent).
Once the verifier stage is wired, every pipeline-produced note carries an
explicit status. Add `""` back to the failing set (gated on
`stages.verifier.enabled: true`). This re-enables the quality gate that was
softened in v0.2.10.

## Non-Goals

- Rewriting `scripts/*.py` as importable modules — they stay as standalone scripts called via subprocess; changing that is a separate, larger refactor
- Modifying verifier logic, quality rules, or the skill's prompt contract
- Wiring the verifier to the query path (`/ask`, `/write`) — covered in spec 005/006
- Parallelising verifier calls across multiple notes in one cycle
- Removing `run_cycle.sh` — kept indefinitely for direct use by generated vaults

## Technical Design

### New files

| Path | Purpose |
|------|---------|
| `src/research_vault/pipeline/cycle_runner.py` | `run_cycle_steps(vault_dir, cycle_num, budget_cap, max_cycles, scripts_dir) → int`; pure Python cycle driver; no bash |
| `src/research_vault/pipeline/verifier.py` | `run_verifier_stage(vault_dir, cycle_num, scripts_dir, settings) → VerifierSummary`; calls agent_call.py per note; stamps frontmatter |
| `tests/pipeline/test_cycle_runner.py` | Unit tests for cycle_runner step sequencing and exit-code propagation |
| `tests/pipeline/test_verifier.py` | Unit tests for verifier stage: stamp logic, best-effort behaviour, disabled setting |

### Modified files

| Path | Change |
|------|--------|
| `src/research_vault/pipeline/orchestrator.py` | `run_single_cycle()` calls `cycle_runner.run_cycle_steps()` instead of `bash run_cycle.sh`; `RV_PYTHON` thread-through moves here |
| `src/research_vault/pipeline/stubs.py` | Re-add `""` to `_FAILING_VERIFIER_STATUSES` when `stages.verifier.enabled` |
| `settings.yaml` | Add `stages.verifier` block (see schema below) |
| `settings.codex.yaml` | Mirror `stages.verifier` with Codex-appropriate model |

### `stages.verifier` settings block

```yaml
stages:
  verifier:
    enabled: true
    model: sonnet          # matches current verifier skill default
    timeout_s: 600
    on_timeout: pending    # pending | skip  (skip = do not stamp, neutral behaviour)
    output_filename: "cycle-{cycle:03d}-verifier.json"
```

### Step sequence in `cycle_runner.py`

```python
def run_cycle_steps(vault_dir, cycle_num, budget_cap, max_cycles, scripts_dir) -> int:
    # Step 0: pre-metrics
    # Step 1: scout — agent_call.py --stage scout
    # Step 2: validate scout — validate_cycle.py <scout-report> --vault ...
    #         exit 2 → return 2 immediately
    # Step 3: DFS research — agent_call.py --stage note-writer
    # Step 3b: verifier — verifier.run_verifier_stage(...) [best-effort, never returns 2]
    # Step 4: post-DFS validation suite (report-only: validate_vault, check_template_compliance,
    #         check_acronym_links, check_intent_drift, check_code_source_coverage)
    # Step 5: post-metrics
    # Step 6: validate research — validate_cycle.py <research-report> --vault ...
    #         exit code propagates to caller
    # Step 7a: topic_harvest (best-effort)
    # Step 7b: topic_propose (best-effort, settings-gated)
    return exit_code_from_step_6
```

The function is a direct translation of `run_cycle.sh` — same step order, same
exit-code semantics, same best-effort contract for Steps 7a/7b.

### Frontmatter stamping

`verifier.py` reads a note's YAML frontmatter, adds/overwrites `verifier_status`
and `verifier_notes`, and writes the file back atomically (temp file + rename).
It does not touch any other frontmatter field or the note body.

## Acceptance Criteria

1. `pytest tests/` passes (≥405) — no test may import or require `run_cycle.sh`
2. `tests/pipeline/test_cycle_runner.py` covers:
   - Scout → validate → DFS step sequence (in order, no skips)
   - ABORT (exit 2) from validate_scout → function returns 2, no further steps run
   - TERMINATE (exit 1) from validate_research → function returns 1
   - `RV_PYTHON` is set in the subprocess environment for every stage call
3. `tests/pipeline/test_verifier.py` covers:
   - Clean note → `verifier_status: verified` stamped
   - Violations → `verifier_status: pending`, `verifier_notes` populated
   - Agent timeout → `verifier_status: pending`, WARN logged, stage does not raise
   - `stages.verifier.enabled: false` → stage skipped, no notes touched, no manifest written
4. `research-vault generate --spec examples/research.spec.md --output /tmp/rv-004 --skip-gate` exits 0 and `_pipeline/cycles/cycle-001-verifier.json` is written
5. A note with `verifier_status: ""` triggers the stub scanner when `stages.verifier.enabled: true`
6. `scripts/run_cycle.sh` is byte-for-byte identical before and after (not modified)

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Exit-code propagation subtly differs between bash and Python subprocess | Low | High | Explicit test per exit code (0, 1, 2) in test_cycle_runner.py; end-to-end run against fixture vault |
| Verifier stage increases per-cycle cost (one LLM call per note) | Certain | Medium | `stages.verifier.enabled` easy to flip off; haiku is sufficient for structural checks |
| Verifier is over-strict → most notes flagged pending → vault growth slows | Medium | Medium | `pending` keeps notes in vault and in next cycle's queue; rejection never deletes; tune by adjusting skill or setting `enabled: false` for a run |
| Frontmatter write race if two processes stamp the same note | Very low | Low | Atomic rename; orchestrator is single-process |
