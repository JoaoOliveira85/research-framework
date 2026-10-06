# Quickstart: Vault Quality Fix

**Audience**: developer implementing or operating this feature.
**Prereqs**: Python 3.11+, repo cloned, `pip install -e ".[dev]"` succeeded, `pytest` green.

This quickstart shows how to (1) verify the new pipeline locally, (2) run the gates against an existing vault, and (3) regenerate `reference_vault_v3` end-to-end.

---

## 1. Verify the new pipeline modules are wired up

After implementation lands:

```bash
cd ~/src/research-framework
pytest tests/pipeline/ tests/scripts/ -v
```

Expected: all new tests in `tests/pipeline/test_research_plan.py`, `test_gates_*.py`, `test_batch.py`, `test_correction.py`, `test_preflight.py`, `test_probes.py`, `test_quality_report.py`, `test_orchestrator_retry.py` pass. Existing tests under `tests/scripts/` continue to pass (no regressions).

```bash
ruff check src/research_vault scripts tests
black --check src/research_vault scripts tests
```

Both must be clean (constitution: "Formatted with `black` (88 chars). Linted with `ruff`").

---

## 2. Run preflight against an existing vault

The standalone preflight CLI (FR-007):

```bash
python scripts/preflight_sources.py /path/to/vault
```

Exit codes:

- `0` — all sources reachable (or only enrichment sources degraded; warnings logged).
- `1` — at least one **required** source unreachable. The cycle would not start.
- `2` — structural error (e.g., spec missing `data_sources` block).

Inspect the result:

```bash
cat /path/to/vault/_pipeline/preflight.json | jq
```

Expected JSON shape conforms to [`contracts/preflight.schema.json`](./contracts/preflight.schema.json). Required-source failures appear with `"role": "required", "status": "unreachable"`.

---

## 3. Inspect a cycle quality report

After any cycle (whether it succeeded or aborted), the quality report lives at:

```bash
cat /path/to/vault/_pipeline/cycles/cycle-001-quality-report.json | jq
```

Quick checks:

```bash
# Every gate's status
jq '.gates | to_entries | map({gate: .key, status: .value.status})' \
   /path/to/vault/_pipeline/cycles/cycle-001-quality-report.json

# Coverage delta this cycle
jq '.coverage_snapshot | to_entries | map({cat: .key, delta: .value.delta_this_cycle, fill: .value.fill_pct})' \
   /path/to/vault/_pipeline/cycles/cycle-001-quality-report.json

# Queryability score + trajectory
jq '{score: .queryability_score, trajectory: .queryability_trajectory}' \
   /path/to/vault/_pipeline/cycles/cycle-001-quality-report.json
```

The CLI helper (`scripts/quality_report.py`) prints a human-formatted summary:

```bash
python scripts/quality_report.py /path/to/vault --cycle 1
```

---

## 4. Inspect the research plan

```bash
cat /path/to/vault/_pipeline/research-plan.md
```

The file has 5 sections in strict order: `## Focus rationale` → `## Coverage state` → `## Cycle focus` → `## Priority queue` → `## Exclusions`. See [`contracts/research-plan.schema.md`](./contracts/research-plan.schema.md).

To regenerate the plan manually (e.g., after editing the spec):

```bash
python -m research_vault.pipeline.research_plan /path/to/vault --cycle 4
```

This produces a fresh plan body but **does not** invoke the narrator. To regenerate with the narrator:

```bash
python -m research_vault.pipeline.plan_narrator /path/to/vault --cycle 4
```

The narrator reads the deterministic body and prepends the `## Focus rationale` section. If the narrator fails or times out, the plan ships with a canned header — never blocks the cycle.

---

## 5. Regenerate reference_vault_v3 end-to-end

This is the canonical end-to-end test of the feature (spec User Story 3).

### 5a. Update the spec

Edit `reference_vault_v3/research.spec.md` and add (per [`contracts/spec-extension.schema.md`](./contracts/spec-extension.schema.md)):

```yaml
forbidden_filename_prefixes:
  - oms_
  - wms_
  - pim_
  - erp_
  - oebh_
  - oecdh_
  - oehk_
  - cms_
```

Optionally also set high-priority categories:

```yaml
note_types:
  - name: spring-feature
    priority: 90
    target_count: 36
    # ... existing fields ...
  - name: java-jvm
    priority: 85
  - name: concept
    priority: 80
  - name: learning-module
    priority: 75
```

Validate:

```bash
python scripts/validate_spec.py reference_vault_v3/research.spec.md --strict
```

Expect: zero errors, zero warnings about the new fields.

### 5b. Wipe and regenerate

```bash
research-vault clean reference_vault_v3 --confirm    # removes _pipeline/ and data_vault/
research-vault generate reference_vault_v3
```

### 5c. Watch the gates fire

In another terminal, tail the cycle outputs:

```bash
watch -n 2 'ls reference_vault_v3/_pipeline/cycles/'
```

You should see, per cycle:

- `cycle-NNN-research.json` (existing)
- `cycle-NNN-harvest.json` (existing)
- `cycle-NNN-research-plan.md` (NEW — historical copy)
- `cycle-NNN-batch-001.json`, `cycle-NNN-batch-002.json`, … (NEW — one per batch)
- `cycle-NNN-quality-report.json` (NEW — final per-cycle summary)
- `cycle-NNN-probe-results.json` (NEW — queryability scoring evidence)

### 5d. Verify the success criteria

After the run completes (success or constrained exit per Principle II):

```bash
# SC-002: at least 10 of 13 categories non-empty
python scripts/vault_metrics.py reference_vault_v3 | grep -c '"met_count": [1-9]'

# SC-009: < 20% notes have forbidden-prefix filenames
python scripts/check_abstraction.py reference_vault_v3

# SC-001: structural integrity gates pass
python scripts/validate_vault.py reference_vault_v3

# SC-007: vault answers ≥ 4/5 queryability probes
jq '.queryability_score' reference_vault_v3/_pipeline/cycles/cycle-*-quality-report.json | tail -1

# SC-013: zero cycles where SG-001 caught empty topics_found.new without correction
jq '.gates["SG-001"].status' reference_vault_v3/_pipeline/cycles/cycle-*-quality-report.json | sort -u
# expect: "PASS" (and possibly "WARN") only — no "FAIL" remaining unresolved

# Aggregate cycle outcomes
python scripts/quality_report.py reference_vault_v3 --all
```

### 5e. Decide what to do

- **All success criteria green** → run `research-vault finalize reference_vault_v3` (Phase 3).
- **Constrained exit** (budget cap or max_cycles tripped) → inspect `_pipeline/research-backlog.md` for unresolved fuel; decide whether to top up budget and `research-vault generate reference_vault_v3--resume`.
- **Hard ABORT** on a gate FAIL after 2 retries → read `_pipeline/cycles/cycle-NNN-quality-report.json`'s `abort_reason`; fix the underlying issue; resume.

---

## 6. Tune the gates / batch size for a specific vault

Edit the vault's `settings.yaml` (the framework writes a default at scaffold time):

```yaml
pipeline:
  note_writer_batch_size: 6              # 3..10; default 6 (R-004)
  source_failure_thresholds:
    required_quorum_loss: 2              # cycle aborts if ≥ this many required sources fail (R-003)
    enrichment_max_failures: 0           # 0 = unlimited (R-003)
  queryability_score_regression_pp: 5    # WARN trajectory if drop > this many pp (R-002)
  backlog_promotion_threshold: 2         # existing (constitution: Coverage Targets)

gates:
  cg_003_warn_pct: 0.30                  # tunable per vault
  cg_003_fail_pct: 0.60
  sg_003_warn_pct: 0.20
  cg_006_warn_pct: 0.10
  cg_006_fail_pct: 0.30
  cg_007_warn_pct: 0.20
```

Defaults match the spec's Story 9 thresholds. Override per vault when justified (e.g., a vault for a tightly-scoped microservice may legitimately have a higher service-prefix tolerance — set `cg_003_warn_pct: 0.50`).

---

## 7. Common pitfalls

- **"Plan generator says cycle_quota=0"** → all targets met. The orchestrator should already be in Phase 3 transition; if not, check `coverage-targets.json` for stale `met_count` values.
- **"Narrator step times out every cycle"** → the narrator agent is overloaded or unreachable. The plan ships with the canned header (R-005) and the cycle proceeds. Check `_pipeline/narrator-incidents.md` for retry history.
- **"SG-003 reports NA every cycle"** → the spec doesn't declare `forbidden_filename_prefixes`. If the vault is code-derived and you want abstraction enforcement, add the field per [`contracts/spec-extension.schema.md`](./contracts/spec-extension.schema.md).
- **"All my notes are getting service-prefix filenames anyway"** → SG-003 is firing but the scout isn't being re-prompted with the correction. Confirm `pipeline/correction.py` is wired into `cycle_runner.py`'s scout retry path.
- **"Cycle keeps retrying forever"** → check `retry_count` in the latest quality report. If it's stuck at 2 with `aborted: false`, that's a bug — `pipeline/orchestrator.py` should set `aborted: true` on retry exhaustion. File a regression.

---

## 8. Manual gate-level smoke test

Step and cycle gates run inside `cycle_runner` / `orchestrator` during normal cycles (US2/US9). There is **no** `python -m research_vault.pipeline.gates_step` or `gates_cycle` CLI — those modules are libraries. For local sanity checks you can use the small helper scripts that wrap that logic:

```bash
# SG-003 (abstraction / forbidden-prefix ratio on latest scout output)
python scripts/check_abstraction.py /path/to/vault/research.spec.md /path/to/vault
```

Stdout: one JSON object (`GateResult`). Exit codes: `0` (PASS, WARN, or NA), `1` (FAIL), `2` (structural error — missing spec, no `cycle-*-research.json`, etc.).

```bash
# Inspect the per-cycle quality report JSON already on disk (read-only)
python scripts/quality_report.py --vault /path/to/vault --cycle 1
```

This **does not** run or emit gates; it loads `_pipeline/cycles/cycle-NNN-quality-report.json` if present and prints a human summary. That file is written by the pipeline when a cycle finishes (and aggregates gate results the orchestrator already computed). Exit code is `0` even when the file is missing (a message is printed to stderr) — the tool is for ad-hoc inspection only.

```bash
# Tabular overview of every quality report file found under _pipeline/cycles/
python scripts/quality_report.py --vault /path/to/vault --all
```

**Note:** If you need a dedicated “run one SG/CG gate from the shell” UX (separate from `check_abstraction.py` / the full cycle), that would be a future small CLI wrapper — not part of the current `research_vault.pipeline.*` modules.
