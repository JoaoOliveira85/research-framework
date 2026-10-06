# Contract — Stagnant-source signal (069 FR3/FR5)

A deterministic, advisory (WARN-only) signal that surfaces sources which yield
nothing for ≥2 consecutive cycles. Reuses the existing `degraded_sources` surface.

## C1 — Detection (FR3)

- At cycle-end, compute per declared source the count of consecutive recent cycles
  with zero facts/signals, using `scripts/source_ledger.py::load_declared_sources` +
  per-cycle verdicts (incl. the existing `SKIPPED_RELEVANCE`).
- A source with `cold_cycles >= 2` emits exactly one `StagnantSourceSignal` (WARN).
- **Advisory only (Q4):** the signal NEVER blocks or FAILs a cycle. The hard gate is
  the FR1/FR2 backing validation.

## C2 — Authority weighting (FR5)

- Each signal carries the source's authority (from
  `source_authority.build_source_role_index`). When multiple sources are cold, an
  **authoritative** source going cold is ranked above a low-authority one (a worse
  smell).

## C3 — Surfaces

- `pipeline/quality_report.py` — the signal is written into the cycle quality
  report's `degraded_sources` (extending the existing surface, not a new artifact).
- `cli/status.py::build_status_json` — surfaces the same WARN via the
  `deferred_warnings` pattern, so `./vault status` and the digest agree.

## Test obligations

| ID | Assertion |
| --- | --- |
| C1-a | A source cold for exactly 2 consecutive cycles → one WARN; cold for 1 → none. |
| C1-b | The signal never changes the cycle gate verdict (advisory). |
| C2-a | Two cold sources, one authoritative → the authoritative one ranks first. |
| C3-a | `./vault status` surfaces the stagnant WARN; consistent with the quality report. |
