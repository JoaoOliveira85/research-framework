# Data Model — Plastic-but-Enforceable Source Authority (053)

No DB changes. These are declaration-time schema additions (`research.spec.md`,
user-owned — read, never rewrite) + the runtime artifacts the gates read.

## DataSource (schema: `research.spec.md::data_sources[]`)
| Field | Type | Notes |
|---|---|---|
| `name` | str | existing |
| `role` | enum `behaviour\|intent\|domain` | **FR-001 — now required on every entry** (was code-first only) |
| `priority` | int | **FR-001 — now required**; lower = higher priority |
| (access/connection) | — | **out of scope** — stays in settings/vault-config/module manifest |

- **`source_id`** for citation attribution is NOT a new field — reuse spec-020
  `manifest.source_id_from` (`url`/`path`/`name`).
- **Validation (FR-002 / D2)**: the minimum `priority` value MUST be held by
  exactly one source → spec validation FAILs otherwise.

## NoteType (schema: `research.spec.md::note_types[]`)
| Field | Type | Notes |
|---|---|---|
| `authoritative_role` | enum `behaviour\|intent\|domain` | **NEW (D1)** — the claim-type this note_type anchors; how the grounding gate resolves a note's type |
| `authority_section` | str (heading) | **NEW, optional (D3)** — e.g. `## Current Behaviour`; generalizes the hardcoded heading |
| `complementary_section` | str (heading) | **NEW, optional (D3)** — e.g. `## Stated Intent` |
- **Opt-in drift (D3)**: a note_type is drift-checked **iff** it declares BOTH
  `authority_section` AND `complementary_section`.

## Trunk (derived — NOT a stored field)
- `Trunk` = the single source with the **minimum `priority` value** (D2 / Analyze
  F3) — generalizes the existing hardcoded `priority == 1 and role == "behaviour"`
  (`validate_cycle.py:556`). Its `role` scopes which claim-types it seed-anchors.
  **No `trunk:` flag** (FR-002).
- **No unique minimum ⇒ no derivable trunk**: a tie on the minimum (caught by
  validation) or a vault with no `priority` signal at all (pure-domain) is valid
  — the trunk-seed gate no-ops via the `if signatures:` guard (D7).
- Derivation is computed by a **single shared `derive_trunk(spec)` helper**
  (Analyze F2) consumed by spec validation, the trunk-seed gate, and the
  trunk-inversion gate — so all three resolve the same trunk identically.

## Claim-type resolution (read-only, deterministic)
```
note.frontmatter.type  →  note_type  →  note_type.authoritative_role  =  claim-type T
```
The grounding gate then requires: the note cites ≥1 source whose `role == T`,
resolved `citation → source_id → data_source → role` via `sources_loader.py` (D4).

## Ledger verdict (consumed from spec 048 v2 — not owned here)
`cycle-NNN-source-ledger.json[*].verdict ∈ {USED, SKIPPED_RELEVANCE, ACCESS_FAIL,
PIPELINE_DROP, QUALITY_REJECT, NOT_REACHED}`. The trunk-inversion gate (FR-007)
reads the verdict for the derived-trunk source.

## Frontmatter flag rename (FR-005)
`intent_implementation_drift` → **`authority_drift`** (boolean, set by the drift gate).

## Scout-report shape v3 (FR-006 / D6)
`topics_from_code → topics_from_trunk`; `parent_code_topic_id →
parent_trunk_topic_id`. v2 (old) reports tolerated via
`_warn_deprecated_termination_shape_once`.
