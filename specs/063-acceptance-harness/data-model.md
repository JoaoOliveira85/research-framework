# Phase 1 Data Model: Acceptance harness

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-06-05

Entities are in-memory results + one persisted artifact (the scorecard, schema in
`contracts/acceptance-scorecard.schema.json`). No pipeline mutation; the harness only
reads + writes its own `_pipeline/acceptance/` output.

## Entity 1 — `GateResult` (in-memory, one per gate)

Mirrors the existing `pipeline.gates.GateResult` shape (deliberate — reuse the
project's gate vocabulary).

| Field | Type | Notes |
| --- | --- | --- |
| `gate_id` | `str` | `GA-001`…`GA-006` (generic-gates.contract.md). |
| `status` | `"PASS" \| "FAIL" \| "WARN"` | Severity per Q2. |
| `metric_value` | `number \| str \| None` | Observed value (e.g. count of rejected notes). |
| `threshold` | `number \| str \| None` | The gate's bound (usually `0`). |
| `message` | `str` | Human-readable verdict. |
| `evidence_paths` | `list[str]` | Vault-relative artifacts backing the verdict. |

## Entity 2 — `Scorecard` (persisted, FR-006)

Written to `_pipeline/acceptance/report-<date>.json` (schema:
`contracts/acceptance-scorecard.schema.json`, `schema_version: "1.0"`,
`kind: "acceptance-scorecard"`) and rendered to `REPORT-<date>.md`. Aggregates:
- `overall` — `{status, fail_count, warn_count, exit_code}`. `exit_code` = `1` iff any
  FAIL gate (or any WARN under `--strict`).
- `generic_gates[]` — Entity 1 results for the six gates.
- `ledger_reconciliation` — Entity 3.
- `citation_grading` — Entity 4.
- `domain_probes` — summary of the in-vault pack (discovered, not framework-owned).

## Entity 3 — Ledger-reconciliation view (US2)

Built by overlaying note citations on the shipped ledger
(`scripts/source_ledger.py` output, joined per cycle via `collapse_verdict`).

```json
{
  "sources_total": 7,
  "disagreements": [
    { "source": "github:acme-corp/oebh-service", "ledger_verdict": "LEDGER_DISAGREEMENT", "citation_rate": 1.0 }
  ]
}
```

Rule (the rc1 false-negative class): a source whose collapsed ledger verdict ∈
{`ACCESS_FAIL`, `PIPELINE_DROP`} but whose `citation_rate > 0` is a **disagreement**,
not a source failure. The 048-v2 amendment relabels it `LEDGER_DISAGREEMENT` at
ledger-build time; the harness reports it defensively even against a pre-amendment
ledger. SA-3/SA-4 grades read the reconciled view.

## Entity 4 — Citation grading (US3)

Per note, per citation, using existing primitives:
- **Authority (053):** `source_authority.build_source_role_index(spec, vault)` →
  derived trunk = highest-priority role. A note whose citations cite *against* the
  derived trunk (e.g. cites a low-priority role as if it were trunk) → counted in
  `authority_inversions`.
- **Credibility (055):** `credibility.citation_credibility(entry)` (tier) +
  `citation_coi(entry)` (COI). Citations with no resolvable tier → `credibility_ungraded`;
  `coi: true` → `coi_flagged` (surfaced, not auto-failed).

`derived_trunk_role` is recorded so a journal-/docs-first vault is visibly graded
against *its own* trunk (edge case), never an assumed code trunk.

## Entity 5 — In-vault domain probe pack (US4/US5, data not code)

Lives under `<vault>/_pipeline/acceptance/` (Q3). The framework's generic gates
**discover** it (presence + summary) but never import vault code (D5 boundary). The
domain pack shrinks to: GOLD anchors retained verbatim (P1 fingerprint `variantId`
trap, P12 convergence confidence) + breadth probes across ≥N declared products/flows.
Recorded in `domain_probes` as a summary only.

## Persistence & compatibility

- `report-<date>.json` is additive + versioned (`schema_version: "1.0"`); no existing
  artifact is changed.
- The scorecard is the only thing the harness writes; running it twice on the same
  state produces equal `generic_gates` verdicts (determinism guarantee).
- Auto-run at clean exit (Q4) writes the scorecard but does **not** change the run's
  own 0/1/2 exit code; the acceptance verdict is a separate, recorded signal.
