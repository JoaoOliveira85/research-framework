# Code Review — Spec 053: Plastic-but-Enforceable Source Authority

**Branch:** `053-source-authority-strategy` vs `main`
**Scope:** the in-flight spec-053 changeset (30 files, ~2,563 insertions)
**Reviewed:** 2026-06-03
**Spec:** `specs/053-source-authority-strategy/spec.md`
**Status under review:** Foundational + US1 (MVP) + US2 + US3-gate built & green; US3 wire-in (T019) held on spec 048 v2; Polish T020/T021/T022 deferred.

## Verification performed

- `pytest` over all spec-053 + adjacent suites (`tests/spec/`, `tests/scripts/`, `tests/pipeline/test_source_authority.py`): **540 passed, 3 skipped**. The 147 directly spec-053-related tests all pass.
- 3 failures observed in `tests/scripts/test_install_sh_tty_handling.py` are **environmental** (`OSError: out of pty devices` — sandbox pty exhaustion), **not in the spec-053 diff**, and pre-existing.
- `ruff check` + `ruff format --check` on all 7 changed source/script files: **clean** (both gates).
- The authored `codebase-vault-spec.md` still parses + validates (no code-first regression).
- Shipped templates / `dist-templates` / `examples` confirmed to NOT declare the new authority fields, so the FR-001 back-compat exempt path applies to existing vaults.

Overall this is a careful, well-tested generalization. The design intent (decouple *discovery-order trunk* from *claim-type authority*, derive the trunk from a unique-minimum priority, keep every gate deterministic + unit-tested) is faithfully reflected in the code. Findings below are mostly contract-fidelity and edge-coverage items, not correctness defects on the shipped paths.

---

## Critical

None. No merge-blocking defect found on the implemented paths. (US3 wire-in T019 is correctly *held*, not silently shipped.)

---

## Warning

### W1 — Documented deprecation-warn for the `topics_from_code → topics_from_trunk` rename is not emitted
`scripts/validate_cycle.py:736-748`, contract `specs/053-source-authority-strategy/contracts/gates.contract.md:38-39`, spec FR-006 (`spec.md:170-171`)

The contract and FR-006 state the v2→v3 field rename should "ride the existing `_warn_deprecated_termination_shape_once` path for old-shape reports." The implementation accepts the legacy `topics_from_code` field silently (functional back-compat is correct) but `_warn_deprecated_termination_shape_once` (`validate_cycle.py:174`) is still only wired to the *unrelated* `next_action`/`termination_reason` legacy shape — it is never called for the topics rename. Consequence: vault owners emitting v2 reports get no migration signal before the field is eventually removed.

This is **tracked and intentionally deferred** as task T020 (`tasks.md:83`, `[~] DEFERRED`), so it is not an undocumented gap. Flagged because the contract reads as if the warn ships now; either implement the one-shot warn alongside the read-side acceptance, or soften the contract wording to "warn deferred to T020".

**Fix:** call `_warn_deprecated_termination_shape_once()` when `report` carries `topics_from_code`/`parent_code_topic_id` but not the v3 names, and assert it in the back-compat test (see W2).

### W2 — Test docstring claims a behaviour the test does not assert (and that does not yet exist)
`tests/scripts/test_validate_cycle_v2.py:166-174`

`test_v2_legacy_topics_from_code_still_accepted` docstring says the old shape "rides the deprecation-warn path, does not fail," but the test only asserts `returncode == 0`. The deprecation warn does not exist (W1), so the docstring describes an unimplemented behaviour. This is a vacuous-claim-vs-assertion mismatch: a reader trusts the docstring and assumes the warn path is covered.

**Fix:** either add a `caplog`/stderr assertion once W1 lands, or reword the docstring to "validator accepts both shapes; deprecation warn deferred to T020."

### W3 — Pure-domain vault with no derivable trunk can still trip the scout "topics empty" invariant
`scripts/validate_cycle.py:740-748`

FR-006 / data-model D7 promise that trunk-seeding enforcement *no-ops when no trunk is derivable* (a priority tie — caught by validation — or a vault with no priority differentiation at all, which validation explicitly permits). The repo-membership check is correctly guarded by `if signatures:` (line 798), but the separate scout invariant `if phase == "scout" and not topics_from_code: errors.append(... "{trunk_field} is empty")` (line 747) is **not** guarded by trunk-derivability. A genuine pure-domain vault (every source at the default priority, no unique minimum) would be forced to emit `topics_from_trunk` and abort if empty — contradicting the plasticity goal.

Not exercised by the fixtures: `vault-journal-first` has a *derivable* trunk (Journals at priority 1), so this edge is untested. The narrow trigger is the all-equal-priority pure-domain shape that `validator.test_passes_when_all_priorities_equal_pure_domain` proves is valid.

**Fix:** gate the empty-topics scout error on "trunk is derivable" (reuse `derive_trunk_dict`), mirroring the `if signatures:` no-op, and add a fixture/unit test for the no-derivable-trunk pure-domain scout report.

### W4 — Human diagnostic output hardcodes the old section headings even when the spec declares custom ones
`scripts/check_intent_drift.py:253-255`

The drift gate now resolves `authority_section`/`complementary_section` per note_type (FR-005), but `_print_human` still prints `(from ## Current Behaviour)` / `(from ## Stated Intent)` verbatim. For a journal-first or any custom-heading vault, the violation message names sections the note does not contain, which will confuse the operator chasing the drift. (The JSON output is unaffected — it omits headings.)

**Fix:** thread the resolved `(authority_heading, complementary_heading)` into the `Violation` (or into `_print_human`) and print the actual headings.

---

## Nit

### N1 — `derive_trunk_dict` is a cross-module public helper but missing from `__all__`
`src/research_framework/pipeline/source_authority.py:37-42, 156`

`derive_trunk_dict` is imported by `scripts/check_trunk_inversion.py` and `scripts/validate_cycle.py` (it is the F2 "single shared derivation" consolidation point), yet `__all__` lists `normalise_source_id` but not `derive_trunk_dict`. Harmless (only affects `import *`) but inconsistent for a documented cross-cutting helper.

**Fix:** add `"derive_trunk_dict"` to `__all__`.

### N2 — Trunk→ledger role-fallback match can pick the wrong entry when multiple sources share the trunk's role
`scripts/check_trunk_inversion.py:76-89`

`_match_entry` falls back from name-match to `role`-match (first ledger entry with the same role). If the trunk's role is shared by multiple ledger sources (e.g. two `domain` sources) and the name-match misses (ledger uses a different `source` label than the spec `name`), the gate could evaluate the wrong source's verdict. In practice the name-match should win and trunk derivation guarantees a unique source, so this is a degraded-path concern only.

**Fix (optional):** when falling back by role, prefer an exact name match against the trunk's repos/source_id set, or log that a role-fallback occurred so a mis-label is visible.

### N3 — Awkward absence assertion in the code-first regression test
`tests/scripts/test_source_authority_code_first.py:98-100`

`assert "service-disagree-flagged.md" not in result.stdout.replace("service-disagree-flagged", "")` — the `.replace()` dance guards against a substring overlap that cannot occur (`service-disagree-unflagged` does not contain `service-disagree-flagged`). Harmless but obscures intent; a plain `not in` reads clearer.

### N4 — `check_intent_drift._print_human` is reached even on the spec-driven path; keep the action hint generic
`scripts/check_intent_drift.py:255`

The action hint `set 'authority_drift: true'` is correct (canonical name), but sits next to the stale `## Current Behaviour` strings from W4 — fixing W4 resolves the inconsistency.

---

## What the code does well

- **Faithful decoupling.** `trunk ⊥ authority` is preserved: trunk is derived by minimum priority (`schema.derive_trunk`), authority is resolved per claim-type (`source_authority.resolve_role` via `note_type.authoritative_role`). No global "highest priority wins" leaked in.
- **Single derivation source of truth (Analyze F2).** `derive_trunk` (SpecConfig) and `derive_trunk_dict` (dict) use the same min-priority/unique rule, and both gate scripts route through `derive_trunk_dict` with an inline fallback when `research_framework` isn't importable — defensive and consistent. Defaults align (`priority` default 2 in both, and `to_dict` always writes the field, so no divergence in practice).
- **Determinism preserved.** The grounding gate replaces regex URL-guessing with `citation → source_id → role` resolution, with a repo deep-path segment-containment fallback that demonstrably preserves the pre-053 `^https://github.com/` / `^file://` behaviour (`test_deep_code_path_resolves_via_repo_signature`, `test_path_in_a_different_repo_does_not_resolve`).
- **Back-compat is real and narrow.** `_is_code_first_spec` was *narrowed* (priority==1 alone no longer triggers; now requires `priority==1 AND role==behaviour`). Because the trigger is strictly narrower, no previously-passing spec can newly fail — it only *loosens* validation to admit journal-/docs-first vaults. Legacy specs that declare no `authoritative_role` are explicitly exempt from the consistency check.
- **Strong, behaviour-focused test coverage.** Boundary cases are covered: priority tie (FAIL), all-equal (valid pure-domain), unique-min, invalid/inconsistent `authoritative_role`, module-slug match/mismatch, deep-path vs different-repo, unknown citation → None, and the three named fixtures map 1:1 to US1/US2/US3 with both pass and fail assertions.
- **Honest status tracking.** Held (T019) and deferred (T020/T021/T022) tasks are clearly marked `[~]` with rationale; the spec status header matches reality; the trunk-inversion gate is coded against the documented 048-v2 ledger contract but not wired live.

## Open questions / assumptions

- **A1 (module ownership by name-slug)** in `source_authority.py:21-27` is reasonable given 053 has no explicit `module:` field on `data_sources`, and it is unit-tested both ways. Worth a one-line note in the spec's data-model so a future `module:` field doesn't silently collide with the slug heuristic.
- The 3 `test_install_sh_tty_handling.py` failures are assumed environmental (pty exhaustion under the sandbox); they should be re-confirmed green in CI before merge but are unrelated to this changeset.
