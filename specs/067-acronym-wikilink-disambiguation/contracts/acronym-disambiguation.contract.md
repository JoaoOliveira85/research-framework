# Contract — Acronym disambiguation + title-corruption gate (067 FR1/FR2/FR3)

Owns the deterministic rules in `pipeline/wikilinks.py` (mirrored in
`scripts/validate_vault.py`) and the new verifier rule in `pipeline/verifier.py`.

## C1 — Single-expansion-only mapping (FR1)

- An acronym `A` auto-links / gets a stub **iff** exactly one note's title derives
  `A` (single claim). `build_acronym_map` keeps the existing behaviour of dropping
  ≥2-claim acronyms into `ambiguous`; this contract makes that the **documented
  invariant** and extends it to stub creation.
- `_write_redirect_stub(A, stem)` MUST be a no-op when `A ∈ ambiguous`.
- The same rule MUST hold in `scripts/validate_vault.py::_build_acronym_map`.

## C2 — Self-title protection (FR2)

- `_rewrite_acronym_body(body, acronym_map, *, self_stem)` MUST NOT rewrite a
  `[[TOKEN]]` to `mapping[A]` when `A` is the containing note's own title-acronym and
  `mapping[A] != self_stem`. In that case the token is left as plain text (the
  acronym string) or as a self-link `[[self_stem]]` — never a sibling expansion.
- `resolve_acronym_links(vault_dir)` MUST run a **re-evaluation pass**: for any
  acronym now in `ambiguous` that previously produced a stub/body link, convert its
  body links to plain text and mark its stub orphaned (handled by the sweep).

## C3 — Title-corruption FAIL rule (FR3)

- `deterministic_wikilink_violations(vault_dir, note_rel, body) -> list[dict]`
  returns one violation `{rule_id, location, message}` with
  `rule_id == "IX-wikilink-title-corruption"` (LOCKED, analyze A1) when the **first**
  body `[[...]]` token is the note's own title-acronym resolving to a non-self stem
  (predicate in data-model D2). Empty list otherwise.
- `run_verifier_stage` calls it before `_merge_verifier_verdict`; any returned
  violation forces `status="rejected"` (FAIL — Q2). Mirrors
  `deterministic_credibility_violations`.
- `.agents/skills/verifier/SKILL.md` lists the rule for the LLM verifier as a
  redundant check; the **deterministic** twin is authoritative (fail-closed).

## Test obligations

| ID | Assertion |
| --- | --- |
| C1-a | An acronym claimed by 2 titles produces no stub and no body link. |
| C1-b | `scripts/validate_vault.py` map agrees with `wikilinks.py` map on the same fixture. |
| C2-a | rc7 timeline (cache-aside first, CAP Theorem later) → `CAP Theorem.md` body keeps "CAP", no `[[cache-aside pattern]]`. |
| C2-b | A note whose own title-acronym had a single-claim sibling still self-links / plain-texts, never sibling-links. |
| C3-a | A note whose first body link renames its own title → verifier `rejected`. |
| C3-b | A note whose first body link is a legitimate different concept → NOT rejected. |
