# Research — Plastic-but-Enforceable Source Authority (053)

Phase 0. Most unknowns were resolved by `docs/handoff-source-strategy.md` + the
`/speckit.clarify` session (Q1–Q3). Decisions D1..D7 with rationale below.

## D1 — Claim-type is resolved per-note via `note_type` (clarify Q1)
- **Decision**: a note's claim-type T = the authoritative `role` declared on its
  `note_type`; the grounding gate resolves `note → note_type → role T`.
- **Rationale**: keeps authority *declared at spec time* (decision #4), reuses an
  existing entity, gives the gate a deterministic lookup, and stays LLM-free
  (decision #5). Per-claim tagging would risk runtime judgement; inference from
  citations is circular.
- **Alternatives**: per-claim annotation (rejected — heavy + judgement risk);
  infer from cited source roles (rejected — circular).

## D2 — Trunk requires a unique top `priority` (clarify Q2)
- **Decision**: the highest `priority` MUST be held by exactly one source; spec
  validation FAILs on a tie. Trunk = that single source.
- **Rationale**: makes trunk derivation unambiguous + deterministic without
  inventing a global role ranking (decision #2 rejects that). Author
  disambiguates. Lower-priority ties *within* a role remain fine (within-role
  authority tie-breaking only).
- **Alternatives**: role-precedence tie-break (rejected — global ranking, breaks
  #2); first-declared (rejected — silent + order-sensitive).

## D3 — Drift gate is opt-in per `note_type` (clarify Q3)
- **Decision**: only note_types declaring BOTH `authority_section` +
  `complementary_section` are drift-checked; others skipped (no drift dimension).
- **Rationale**: mirrors today's code-first model (drift is behaviour↔intent
  specific); avoids forcing a meaningless authority/complementary split on
  pure-reference note_types; scope is explicit + author-controlled.
- **Alternatives**: required-on-all (rejected — artificial split); role-pairing
  table (rejected — extra mapping, premature).

## D4 — Resolve `citation → role` via `sources_loader.py`, not regex
- **Decision**: replace `classify_url`'s regex URL-guessing (in
  `check_code_source_coverage.py`) with `citation → source_id → owning
  data_source → role`, reusing spec-020 `sources_loader.py` + `manifest.source_id_from`.
- **Rationale**: `source_id` is the existing canonical attribution (spec 020);
  regex-guessing is brittle and code-specific. Reuse > re-invent (Principle V).
- **Alternatives**: keep regex + extend per role (rejected — brittle, doesn't
  generalize across module kinds).

## D5 — Trunk-inversion gate is built on the spec-048-v2 ledger
- **Decision**: FR-007 reads the `cycle-NNN-source-ledger.json` per-source
  verdict; FAIL when the derived trunk is `NOT_REACHED`/`SKIPPED_RELEVANCE` while
  any branch is `USED` (an *explained* trunk `ACCESS_FAIL` is allowed).
- **Rationale**: the ledger already computes per-source verdicts (048 v2
  FR-017..021); the inversion gate is a thin deterministic read over it — the
  cheapest reliable "bad-faith / path-of-least-resistance" detector.
- **Dependency**: **hard depends on spec 048 v2.** FR-004/005/006 are
  independently shippable; FR-007 lands once 048 v2 exists.

## D6 — Scout-report contract bump v2 → v3 (back-compat path)
- **Decision**: rename scout-report fields `topics_from_code → topics_from_trunk`
  and `parent_code_topic_id → parent_trunk_topic_id`; bump the report shape v2→v3.
- **Rationale**: the trunk is now strategy-derived, not always code. Old-shape
  (v2) reports ride the existing `_warn_deprecated_termination_shape_once` path
  (warn, don't fail) for one release; new emitters use v3.
- **Alternatives**: keep `topics_from_code` as an alias forever (rejected — name
  lies for non-code trunks).

## D7 — Generalize, don't rebuild; pure-domain guard preserved
- **Decision**: edit the 3 existing gate scripts + `_spec_primary_repos` /
  `_repo_match_signatures` / `_source_file_matches_repo` to resolve via
  `source_id` across module kinds. Preserve the existing `if signatures:` guard
  (`validate_cycle.py` ~L773) so a pure-domain vault (no derivable trunk) does
  NOT trip "trunk empty".
- **Rationale**: the two-axis model is already implemented; this is a
  generalization (decision: "generalizes existing code; no new subsystem"). The
  guard is the existing escape hatch that makes the journal-first fixture pass.
