# Contract: Benchmark Comparison Report

**Spec**: 056 — Executor × Model Benchmarking Harness · **Status**: authored 2026-06-03
(post-clarify Q2, Q3, Q5). Normative for `report.json`, human `report.md`, per-cell
artifacts, and quality scoring (Principle IV).

---

## 1. Run directory layout (FR-008, FR-009, FR-018)

```
<fixture>/_pipeline/benchmarks/<run-id>/
├── report.json
├── report.md
└── cells/
    └── <task>__<executor>__<model>/
        ├── stdout.txt
        ├── sidecar.json          # copy of 028 agent-call sidecar if present
        └── scored.json           # deterministic score replay artifact
```

- **`run-id`**: UTC `YYYYMMDDTHHMMSSZ` (e.g. `20260603T143022Z`). New run ⇒ new dir;
  **never** overwrite prior dirs (FR-009).
- Directory is **gitignored** (`.gitignore` entry for `tests/fixtures/benchmark/_pipeline/`).

## 2. `report.json` top-level schema

```json
{
  "schema_version": "1.0",
  "run_id": "20260603T143022Z",
  "started_at": "2026-06-03T14:30:22Z",
  "completed_at": "2026-06-03T14:45:10Z",
  "matrix_path": "tests/fixtures/benchmark/benchmark-matrix.yaml",
  "fixture_path": "tests/fixtures/benchmark",
  "sample_count": 1,
  "cost_gate": { "estimated_usd": 1.2, "ack_mode": "tty", "max_usd": null },
  "cells": [ /* CellResult, §3 */ ]
}
```

## 3. Cell result (`cells[]`)

| field | type | required | notes |
|-------|------|----------|-------|
| `task` | string | yes | §2 task id |
| `executor` | string | yes | runtime key |
| `model` | string | yes | matrix model string |
| `status` | enum | yes | `ok` \| `skipped` \| `failed` \| `unscored` |
| `reason` | string | if not `ok` | human-readable |
| `quality` | number \| null | if scored | primary scalar §4 |
| `quality_detail` | object | if scored | sub-metrics for audit |
| `scoring_mode` | string | if scored | always `"deterministic"` |
| `cost_usd` | number \| null | yes | from sidecar; `null` ⇒ *n/a* (FR-013) |
| `cost_source` | string | yes | `sidecar` \| `estimated` \| `n/a` |
| `latency_ms` | integer | if `ok` | wall-clock |
| `artifact_dir` | string | if attempted | relative path under run dir |

**Status rules**:
- `ok` — live call + deterministic score applied.
- `skipped` — runtime/model unavailable (FR-011).
- `failed` — dispatch error/timeout (FR-012).
- `unscored` — output present but no deterministic scorer (v1 should not emit for the three scored tasks unless output is unusable).

## 4. Per-task quality (FR-005, FR-017, SC-002)

One **primary scalar** `quality` in `[0, 1]` unless noted. Re-scoring `scored.json`
MUST reproduce `quality` (FR-014).

| task | primary `quality` | `quality_detail` (minimum) |
|------|-------------------|----------------------------|
| `scout` | `topics_proposed / topics_expected` capped at 1.0 | `scout_report_valid: bool`, `topics_proposed: int`, `topics_expected: int` (expected from fixture manifest) |
| `note-writer` | `note_quality.template_compliance_pct` (spec-022 returns a **0..1 ratio** despite the `_pct` suffix — used as-is, NOT `/100`) | full `note_quality` subtree from `compute_note_quality_metric` on synthetic single-note cycle |
| `verifier` | `1.0` if verifier verdict `accept`, else `0.0` | `verifier_pass: bool`, `verdict: string` |

**Parser rules**:
- Scout: parse stdout as scout-report v2 JSON; invalid JSON ⇒ `failed`.
- Note-writer: the benchmark prompt requires the FULL note (frontmatter + body) on
  stdout, captured via `agent_call --output-file`; the harness writes it to a file and
  runs 022 note-quality on it. Output with no YAML frontmatter ⇒ `failed` (not a note).
  *(v1 captures stdout directly; production `note_writer`'s vault-file-write path
  extraction is deferred — the benchmark fixture prompt pins stdout-only output.)*
- Verifier: parse verifier JSON (ADR-0004 tolerant); non-accept ⇒ quality 0.0.

No cross-task aggregate score in v1 (FR-015). `report.md` MAY show per-task leader tables only.

## 5. Human `report.md` (FR-008)

Sections in order:
1. **Run header** — `run_id`, matrix path, ack mode, sample_count.
2. **Per-task tables** — one markdown table per task; columns: executor, model, quality,
   cost_usd, latency_ms, status. Sort quality desc within task.
3. **Failures & skips** — appendix listing non-`ok` cells with `reason`.
4. **Cost summary** — estimated vs actual (sum of `cost_usd` where not null).

## 6. Trending / deltas (US4, SC-006)

Given two `report.json` files with overlapping `(task, executor, model)` keys,
delta is derivable by field-wise subtraction (`quality`, `cost_usd`, `latency_ms`).
No merge tool in v1 — manual `diff` or jq is sufficient.

## 7. Repetitions (Q5)

v1: `sample_count` MUST be `1` in report header. v1.1 MAY add `samples[]` array when
`--repeat N` ships; until then, harness MUST reject `--repeat`.
