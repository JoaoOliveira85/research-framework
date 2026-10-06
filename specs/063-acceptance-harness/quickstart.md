# Quickstart: Acceptance harness

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

Run the generic gates on a vault and confirm they reproduce the rc1 off-script
findings deterministically (SC-001). Assumes a dev checkout (`pip install -e .`) of
branch `063-acceptance-harness`.

## Run the harness on demand

```bash
./vault acceptance --vault ~/Documents/codebase-vault-rc1
# or, before the shim is regenerated:
research-framework acceptance --vault ~/Documents/codebase-vault-rc1
```

Output: a verdict table + `_pipeline/acceptance/REPORT-<date>.md` and
`report-<date>.json`. Exit `1` if any FAIL gate.

## Reproduce the rc1 findings (SC-001)

Against the snapshot fixture `tests/fixtures/acceptance/rc1-codebase-snapshot/`, the
six generic gates must FAIL exactly where the human evaluator did:

```bash
research-framework acceptance --vault tests/fixtures/acceptance/rc1-codebase-snapshot --json | jq '.generic_gates[] | {gate_id, status}'
# EXPECT:
#   GA-001 FAIL  (14 rejected notes in corpus)
#   GA-002 FAIL  (12 "... 2.md" duplicates)
#   GA-003 FAIL  (untracked data_vault/ + two "research: cycle 6" commits)
#   GA-004 FAIL  (constrained 6/12 reported, not "done")
#   GA-005 FAIL  ($0 total_cost_usd)
#   GA-006 WARN  (template drift, advisory)
echo "exit=$?"   # EXPECT: 1
```

## US2 — ledger ↔ citation reconciliation

```bash
research-framework acceptance --vault tests/fixtures/acceptance/rc1-codebase-snapshot --json | jq '.ledger_reconciliation'
# EXPECT: disagreements[] lists the sources the ledger marked ACCESS_FAIL/PIPELINE_DROP
#         but the notes cite (citation_rate > 0) — flagged as LEDGER_DISAGREEMENT,
#         NOT a wall of source failures.
```

## US3 — authority / credibility grading

```bash
research-framework acceptance --vault <vault> --json | jq '.citation_grading'
# EXPECT: derived_trunk_role recorded; authority_inversions counts notes citing
#         against the derived trunk (053); credibility_ungraded + coi_flagged from 055.
# Journal-first edge case: derived_trunk_role is the vault's own trunk, not "code".
```

## US5 — reuse across vaults + Q4 auto-run

```bash
# Same generic gates, different vault (proves reuse, SC-002):
research-framework acceptance --vault ~/Documents/reference-vault-rc3

# Q4: a clean run records the scorecard automatically at finalise:
grep -ri 'acceptance' ~/Documents/reference-vault-rc3/_pipeline/acceptance/REPORT-*.md
```

## Done-when

- `pytest tests/cli/test_acceptance_gates.py tests/cli/test_acceptance_ledger_recon.py
  tests/cli/test_acceptance_grading.py tests/cli/test_acceptance_scorecard.py` green.
- The rc1 snapshot reproduces all five off-script findings deterministically (SC-001).
- The generic gates run unchanged against tech-/feeds-vaults (SC-002); a constrained exit
  can never grade "done"; a `$0` run can never pass `GA-005` (SC-003).
- The tier-2 LLM-dispatch guard stays green (the gates are LLM-call-free).
