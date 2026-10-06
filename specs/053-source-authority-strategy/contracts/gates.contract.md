# Contract — Source-Authority Gates (053)

All four gates are **deterministic, LLM-free** scripts with exit codes and their
own unit tests (Principle I/III/IV). Exit convention (matches existing gates):
`0` = pass, non-zero = FAIL with a machine-readable reason on stdout/stderr.

---

## Gate 1 — Grounding (`scripts/check_code_source_coverage.py`, FR-004)
**Input**: a note (frontmatter `type` + citations), the spec's `note_types` +
`data_sources`, `sources_loader` for `source_id→role`.
**Rule**: resolve claim-type `T = note_type.authoritative_role`; the note MUST
cite ≥1 source whose `role == T` (resolved `citation → source_id → data_source →
role`). Complementary citations (other roles) are allowed; only the
authoritative-role coverage is required.
**Pass**: ≥1 authoritative-role citation. **FAIL**: zero — message names the note,
its claim-type T, and the missing authoritative role. (Code-first = the
`T=behaviour` case — identical verdicts to the pre-053 hardcoded gate on the
`vault-code-first` fixture.)

## Gate 2 — Drift (`scripts/check_intent_drift.py`, FR-005)
**Applicability**: ONLY note_types declaring BOTH `authority_section` +
`complementary_section` (opt-in, D3); others are skipped (no drift dimension).
**Rule**: compare the note's `authority_section` vs `complementary_section`
content for divergence (the existing drift heuristic, generalized off the
hardcoded `## Current Behaviour`/`## Stated Intent`).
**Output**: sets frontmatter `authority_drift: true|false` (renamed from
`intent_implementation_drift`). Exit code per the existing drift policy.

## Gate 3 — Trunk-seed / attach (`scripts/validate_cycle.py::check_termination_v2`, FR-006)
**Rule**: scout topics must seed from the **derived trunk**
(`topics_from_trunk`); research topics attach via `parent_trunk_topic_id`.
Generalize `_spec_primary_repos` / `_repo_match_signatures` /
`_source_file_matches_repo` to resolve via `source_id` across module kinds.
**Critical guard (D7)**: only enforce trunk-seeding when a trunk is *derivable* —
mirror the existing `if signatures:` guard (~L773). A pure-domain vault MUST NOT
trip "trunk empty".
**Back-compat**: v2 scout reports (`topics_from_code` / `parent_code_topic_id`) are
accepted silently alongside the v3 field names (`topics_from_trunk` /
`parent_trunk_topic_id`); no deprecation warning is emitted for the rename yet
(emitter-side v3 migration is deferred).

## Gate 4 — Trunk-inversion (`scripts/check_trunk_inversion.py`, FR-007) — NEW
**Input**: `cycle-NNN-source-ledger.json` (spec 048 v2 **/ v2.1**), the derived trunk.
**Rule**: the derived-trunk source MUST resolve to verdict `USED` — OR an
*explained* `ACCESS_FAIL`. **FAIL** if the trunk is `NOT_REACHED` or
`SKIPPED_RELEVANCE` while any branch source is `USED` (the bad-faith /
path-of-least-resistance detector).
**`LEDGER_DISAGREEMENT` is citation-evidenced — treat it as `USED`** (spec 048
v2.1 coordination, 048 amendment T006). When the trunk's reported verdict is
`LEDGER_DISAGREEMENT`, the trunk *was* cited by ≥1 note (the join verdict in
`disagreement_was` is the ledger's blind spot, not a real drop), so the gate
PASSES — never a silent trunk drop. The `disagreement_was` field MAY be surfaced
in the FAIL/PASS message for diagnosability.
**Dependency**: hard-depends on spec 048 v2 (the ledger). Ships once 048 v2 lands.

---

## Scout-report v3 shape (FR-006 / D6)
```jsonc
{
  "schema_version": "3",                 // was implied v2
  "topics_from_trunk": [ /* … */ ],      // was topics_from_code
  "topics": [
    { "parent_trunk_topic_id": "…" }     // was parent_code_topic_id
  ]
}
```
v2 reports (old field names) → tolerated via silent back-compat (both shapes validate).

## Spec validation additions
- Every `data_sources[]` entry has `role` + `priority` (else FAIL).
- The minimum `priority` is held by exactly one source (else FAIL — D2).
- Each `note_type` must declare `authoritative_role` **consistently** once any
  note_type opts in; fully-legacy specs (none declare it) are exempt (opt-in).
