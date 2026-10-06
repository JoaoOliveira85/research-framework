# Phase 1 Data Model: Vault output integrity on constrained exit

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-06-05

No new on-disk schema files. The entities below are (1) a reused quarantine
location + backlog pointer, (2) an additive run-report field, (3) an in-memory
acronym map, (4) a classified redirect-stub node.

## Entity 1 — Quarantined rejected note (FR1, reuses existing dir)

A note that ended the run with `verifier_status: rejected` is **moved** from
`data_vault/<folder>/<stem>.md` to `<vault>/_pipeline/quarantine/<stem>.md`
(the existing dir used by `_quarantine_out_of_scope_notes`). The note's frontmatter
is preserved verbatim (so the next cycle can re-inspect `verifier_notes`). A pointer
line is appended to the existing `_pipeline/research-backlog.md`:

```
- [ ] rewrite quarantined note: <stem> (verifier_status: rejected — <first verifier_note>)
```

Invariant: after `_finalise`, `data_vault/` contains **zero** notes with
`verifier_status: rejected` (they are all in quarantine), so the indexer/readers
cannot surface or cite them.

## Entity 2 — `rejected_unresolved` run-report field (FR1, additive)

Added to the run-report (JSON + a headline line in `run-report.md`):

| Field | Type | Notes |
| --- | --- | --- |
| `rejected_unresolved` | `int` | Count of notes quarantined at finalise for `verifier_status: rejected`. |

`run-report.md` headline:

```
Verifier: 14 notes ended the run rejected and were quarantined (see _pipeline/quarantine/).
```

This is the signal sibling spec 063 §4.1 gates on ("no rejected notes remain in the
indexed corpus on a clean exit").

## Entity 3 — Acronym map (FR3, in-memory)

Built once per cycle-end wikilink pass in `pipeline/wikilinks.py`:

```python
acronym_map: dict[str, str]   # "OECDH" -> "order-engine-customer-data-handler"
```

Construction (deterministic, research.md D4):
- For each `data_vault/*.md` note, derive the acronym from the canonical title
  (initials of significant words; configurable stop-word set).
- Union with any explicit note `aliases:` entries (additive, if present).
- **Ambiguity rule**: if two notes yield the same acronym, that acronym is dropped
  from the map (no auto-rewrite) and `validate_vault.py` emits an ambiguity WARNING —
  never produce a wrong link.

Consumption:
- Unresolved all-caps `[[TOKEN]]` in note bodies/`related` is rewritten to the mapped
  canonical stem (case-fix pass already exists; this is the acronym branch).
- A redirect stub (Entity 4) is generated per mapped acronym so a direct `[[OECDH]]`
  node also resolves.

## Entity 4 — Redirect stub note (FR3, classified distinctly)

A minimal alias node at `data_vault/<folder>/<ACRONYM>.md`:

```markdown
---
title: OECDH
note_type: alias
redirect_to: order-engine-customer-data-handler
verifier_status: exempt
---
See [[order-engine-customer-data-handler]].
```

Classification rules (so it doesn't distort metrics):
- `note_type: alias` — **excluded** from coverage targets, spec-022 quality metrics,
  and Principle-VIII stub-as-fuel accounting (it is a graph-resolution node, not a
  research stub and not research fuel).
- `verifier_status: exempt` — not subject to the verifier gate (no claims to verify);
  therefore never quarantined by FR1.
- Idempotent: regenerating on a clean vault is a no-op (content-stable).

## Migration / compatibility

- **No schema_version bump.** `rejected_unresolved` is an additive run-report field;
  `note_type: alias` is a new enum value consumed only by the new classifier paths.
- **Existing vaults**: the first cycle after upgrade quarantines any lingering
  rejected notes and generates missing acronym redirects — both idempotent.
