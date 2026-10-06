# Quickstart — Plastic-but-Enforceable Source Authority (053)

How to exercise each gate + the 3 fixtures once implemented. Dev checkout, TDD
(fixtures first). All gates are deterministic + LLM-free.

## Declare authority (in `research.spec.md`)
```yaml
data_sources:
  - name: "Team service repos"
    role: behaviour
    priority: 1          # unique min → derived trunk (a behaviour source)
  - name: "Confluence ADRs"
    role: intent
    priority: 2
note_types:
  - name: behaviour-note
    authoritative_role: behaviour          # claim-type for the grounding gate
    authority_section: "## Current Behaviour"
    complementary_section: "## Stated Intent"   # both present → drift-checked
  - name: concept-note
    authoritative_role: domain                  # no sections → drift-skipped
```

## The journal-first counter-example (no behaviour source)
```yaml
data_sources:
  - name: "Peer-reviewed journals"
    role: domain
    priority: 1          # unique min → derived trunk (a DOMAIN source)
  - name: "Reddit r/science"
    role: domain
    priority: 3          # same role, lower priority → complementary
```
Expect: Gate 3 demands `topics_from_trunk` = journal, **does not error on missing
behaviour**; the ledger shows journal `USED`.

## Run the gates
```bash
# Gate 1 — Grounding (a behaviour-note must cite a behaviour-role source)
python scripts/check_code_source_coverage.py <vault>            # exit 0 = ok

# Gate 2 — Drift (only note_types declaring both sections)
python scripts/check_intent_drift.py <vault>                    # sets authority_drift

# Gate 3 — Trunk-seed/attach (scout must seed from the derived trunk)
python scripts/validate_cycle.py <vault>                        # check_termination_v2

# Gate 4 — Trunk-inversion (on the 048 v2 ledger)
python scripts/check_trunk_inversion.py <vault>              # latest cycle ledger
python scripts/check_trunk_inversion.py <vault> --ledger _pipeline/cycles/cycle-001-source-ledger.json
```

## Fixtures (write these FIRST, TDD)
1. `tests/fixtures/vault-code-first/` — **regression**. Trunk=code; behaviour
   notes cite code; drift flagged; ledger: code `USED`. Gate verdicts unchanged
   vs the pre-053 hardcoded gates.
2. `tests/fixtures/vault-journal-first/` — **NEW, abstraction proof**. Trunk is a
   *domain* source, **no behaviour source**. Gate 3 demands `topics_from_trunk`=
   journal + does NOT error on missing behaviour; reddit complementary; ledger:
   journal `USED`.
3. `tests/fixtures/vault-bad-faith/` — **NEW**. Spec's derived trunk is code,
   report seeds only from Confluence → **Gate 4 FAILs** (ledger: code
   `NOT_REACHED`, intent `USED`).

## Spec-validation checks (also TDD)
- Missing `role`/`priority` on any `data_source` → FAIL.
- Duplicate minimum `priority` → FAIL (trunk ambiguous).
- `note_type` missing `authoritative_role` when another note_type declares it →
  FAIL (fully-legacy specs with none declared are exempt).
