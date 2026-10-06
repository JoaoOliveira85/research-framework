# Quickstart — Pipeline Reliability Hardening (spec 032)

How to exercise and verify each deliverable. Run everything with the project
venv (`.venv/bin/python`, NOT pyenv — pyenv carries a stale editable install
that breaks subprocess tests).

## Prerequisites

```bash
.venv/bin/python -m pytest --version     # confirm the venv interpreter
ruff --version
```

## rc1 GATE — verify the migration (FR-007 / US4)

This is the only rc1-blocking deliverable. The dispatch guard must stay green
with an EMPTY allowlist and `extract.py` no longer excluded.

```bash
# 1. The allowlist MUST be empty (hard CLAUDE.md invariant)
cat tests/_helpers/llm_dispatch_allowlist.yaml          # → empty / [] / null

# 2. The guard test (UPDATED in Phase 1) — extract.py is no longer excluded,
#    and now surfaces ZERO violations (proves the direct claude call is gone)
.venv/bin/python -m pytest tests/_helpers/test_llm_dispatch_guard.py -v

# 3. extract.py no longer shells claude directly
grep -n 'subprocess.run(\["claude"' src/research_framework/processors/extract.py   # → no matches
grep -n 'agent_call\|dispatch' src/research_framework/processors/extract.py        # → the new seam

# 4. extract.py's own suite still green through the dispatch-backed mock seam
.venv/bin/python -m pytest tests/processors/test_extract.py -v

# 5. Lint — both gates (they are SEPARATE)
ruff check .
ruff format --check .
```

**Pass criteria (rc1):** all of the above green; allowlist empty;
`_SCAN_SKIP_REL` in the guard no longer contains `processors/extract.py`.

<a id="sandbox-detection"></a>

## US1 — sandbox detection, fail-closed (FR-001, FR-002; P3)

> **Design rationale** — the layered heuristic, the `RV_DISABLE_SANDBOX_DETECT`
> override, and the fail-closed-vs-WARN posture are documented in
> [`docs/sandbox-detection.md`](../../docs/sandbox-detection.md). The
> `SandboxDetectedError` message links operators back to this anchor (FR-002).

```bash
.venv/bin/python -m pytest tests/processors/test_extract.py -k "sandbox" -v
```

Expected behaviour the tests pin:
- Simulated sandboxed dispatch (stderr auth-failure signature) → `extract`
  **hard-exits non-zero** and writes **ZERO** stub files (SC-001: within 30s
  of first failed extraction).
- Time-based fallback: first ≥3 extractions each <1s AND failed → same
  hard-exit, even without a signature match.
- `RV_`-override env var set → detection suppressed, normal behaviour (SC-005).
- Non-sandboxed run → unchanged (Acceptance #2).
- The error message names (a) what was detected, (b) the
  `dangerouslyDisableSandbox: true` / autonomous-mode-pre-auth workaround,
  (c) a doc link (FR-002).

## US2 — stub auto-retry on resume (FR-003, FR-004; P3)

```bash
.venv/bin/python -m pytest tests/processors/test_extract.py -k "retry or permanent" -v
```

Expected:
- A vault with 3 pre-existing `status: extraction-failed` stubs → re-running
  `extract` (no flags) auto-retries those 3 (SC-002).
- Retries exhaust (default `max_retry_attempts=3`) → stub becomes
  `status: extraction-failed-permanent`.
- `--force` re-attempts even `extraction-failed-permanent` stubs.

## US3 — synthesis timeout ladder (FR-005, FR-006; P3)

```bash
.venv/bin/python -m pytest tests/processors/test_extract.py -k "timeout or chunk or ladder" -v
```

Expected:
- A synthetic over-budget bundle → auto-fallback `--filter <today>` →
  chunked batches → completes without manual intervention (SC-003).
- Chunked output reconciles into the same `context-tree.md`; equivalent to a
  successful full-bundle run (FR-006). Manifest at
  `_pipeline/extracted/context-tree-chunks.json`.
- All retries exhausted → failure message lists what was attempted + missing.

## Full local gate (pre-PR)

```bash
.venv/bin/python -m pytest -m "not e2e"          # fast loop
ruff check . && ruff format --check .
bash build.sh                                     # smoke gate (ADR-0007)
# build.sh --quality only if pipeline/ or quality/ fixtures were touched
```

## Manual / live exercise (optional, opt-in)

The legacy raw_data path (the only caller of `extract.py`) is:

```bash
./vault pipeline extract <vault>        # runs runner.py::_drive_extract → extract()
```

Real-CLI behaviour is covered by `@pytest.mark.live_llm` tests (skipped by
default):

```bash
.venv/bin/python -m pytest tests/processors/test_extract.py --live-llm
```

> Note: no target vault uses this path on its live runs (see research.md §1);
> `./vault research` → `cycle_runner` → spec-020 modules never invoke
> `extract.py`. The live exercise above is for the legacy `/pipeline` flow only.
