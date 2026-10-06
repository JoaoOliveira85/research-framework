# Tasks: Plastic-but-Enforceable Source Authority

**Feature**: spec 053 | **Branch**: `053-source-authority-strategy`
**Spec**: `specs/053-source-authority-strategy/spec.md` · **Plan**: `plan.md` ·
**Design**: `research.md` (D1–D7), `data-model.md`, `contracts/gates.contract.md`,
`quickstart.md`

## Format: `[ID] [P?] [Story?] Description with file path`
- **[P]** = parallelizable (different files, no incomplete-task dependency).
- **[US1/US2/US3]** = user-story phase tasks only.
- **TDD is mandatory** (spec Guardrails): fixtures/tests are written and seen to
  FAIL before the implementation that makes them pass.
- **Run tests/lint via `.venv/bin/python -m ...`** (NOT bare python — pyenv base
  has a stale editable install).

---

## Phase 1: Setup

- [x] T001 Confirm on branch `053-source-authority-strategy`, capture a green baseline. **DONE** — ruff clean; spec+scripts suites green AFTER fixing a pre-existing **0.8.0 main bug** the baseline surfaced: the 0.8.0 CHANGELOG `### Fixed` bullets lacked the `(regression test: …)` annotations `test_changelog_regression_links` requires (committed separately as a 0.8.0 hotfix; rides this branch until 053 merges).
- [~] T002 **CORRECTED (don't pre-scaffold vault dirs).** Reality check: `tests/fixtures/vault-code-first/` is **flat note `.md` files** (gate-test inputs), NOT a vault dir with `research.spec.md`+`_pipeline/`. The fixtures are **per-gate-shaped** — notes for grounding/drift (T007), spec+scout-report for trunk-seed (T013/US2), spec+`cycle-NNN-source-ledger.json` for trunk-inversion (T016/US3). Build each fixture in its test's shape within T007/T013/T016 rather than pre-scaffold here. (No empty dirs created.)

---

## Phase 2: Foundational (Blocking Prerequisites — shared by all gates)

- [x] T003 [P] Schema: accept `role: behaviour|intent|domain` + `priority: int` on **every** `data_sources[]` entry in the spec parser (`src/research_framework/spec/` schema/parser). (FR-001) **DONE** — fields already existed on `DataSourceConfig` and `parser.py` delegates straight to `from_dict`; `test_parser.py::test_parses_code_first_fields_inline` already pinned `role`/`priority` through the markdown path. Added `test_parses_authority_and_domain_role_fields_inline` to also pin the `domain` role + T004's note_type authority fields end-to-end (7/7 green).
- [x] T004 [P] Schema: accept `authoritative_role` (enum) + optional `authority_section`/`complementary_section` on each `note_type` in the spec parser. (FR-001 / D1) **DONE** — added the 3 fields to `NoteTypeConfig` (`spec/schema.py`, default `""`) + wired `to_dict`/`from_dict`; TDD via `tests/spec/test_schema.py::TestNoteTypeAuthority` (parse+roundtrip+defaults). 42 spec/roundtrip tests green; ruff clean. **Finding**: `DataSourceConfig` already has `role`+`priority` (defaults `behaviour`/`2`) — so T003's data_source half is mostly validation-of-population, not new fields.
- [x] T005 Spec validation (`scripts/validate_spec.py` / spec validator) + unit test in `tests/`: FAIL when (a) any `data_source` lacks `role`/`priority`, (b) the **minimum `priority` value** is shared by ≥2 sources (D2 — trunk ambiguous), (c) any `note_type` lacks `authoritative_role`. Use the shared `derive_trunk` helper (T006b) for the uniqueness check. **DONE** — `spec/validator.py`: (a) was already enforced (role-enum + positive-priority, :122-139); (b) NEW — `derive_trunk(spec) is None` + >1 distinct priority ⇒ ambiguous-trunk FAIL (all-equal pure-domain stays valid per data-model); (c) NEW — authoritative_role enum-validated when present + **opt-in consistency rule** (FAIL if some note_types declare it but not all). TDD via `test_validator.py::TestSourceAuthorityValidation` (6 cases). 192 spec + 28 validate_spec tests green (no legacy-spec regression — codebase-vault-spec.md still validates). **Deviation from contract's literal "any note_type lacks authoritative_role → FAIL"**: made opt-in/consistency-gated so the library `validate()` (which runs on pre-053 specs) stays non-breaking; flagged for the review pass.
- [x] T006 [P] `source_id → owning data_source → role` resolution helper (reuse `src/research_framework/pipeline/source_bridge/sources_loader.py` + `manifest.source_id_from`) + unit test in `tests/`. Replaces regex URL-guessing for all gates. (D4) **DONE** — new `pipeline/source_authority.py`: `build_source_role_index(spec, vault_dir)` (code-repo `url`/`local_path` + module-enumerated `source_id`s via `walk_modules`+`load_module_sources`) and `resolve_role(citation, index)`. TDD via `tests/pipeline/test_source_authority.py` (4 cases: code repo url+local_path→role, unknown→None, module-slug→data_source role, unmatched module→None). RED (ModuleNotFoundError) → GREEN (4/4), ruff clean. **Assumption A1** (no `module:` field on data_sources → match module dir name to slugified data_source name) documented in the module docstring; flagged for the analyze/review pass.
- [x] T006b [P] **Shared `derive_trunk(spec) -> source | None` helper** (Analyze F2/F3): returns the source with the **minimum `priority` value**, or `None` when no unique minimum exists (tie or no priority signal). Generalizes the hardcoded `priority == 1 and role == "behaviour"` (`validate_cycle.py:556`). + unit test (incl. the no-unique-min → `None` case). **Consumed by T005, T011, T018** so all three derive the trunk identically. **DONE** — `derive_trunk` added to `spec/schema.py` next to `primary_source`/`intent_sources`; TDD via `tests/spec/test_schema.py::TestDeriveTrunk` (5 cases: unique-min behaviour, unique-min **domain** journal-first, tie→None, all-equal→None, empty→None). RED (ImportError) → GREEN (37/37). ruff clean.

**Checkpoint**: schema + validation + `source_id→role` resolver + `derive_trunk` helper green → user stories may begin.

---

## Phase 3: User Story 1 — Code-first vault still enforces (Priority: P1) 🎯 MVP

**Goal**: the generalization must not regress the one model that ships today.
**Independent test**: the 3 generalized gates on `vault-code-first` produce
identical pass/fail to the pre-053 hardcoded gates.

### Tests (write first, must capture current behaviour)
- [x] T007 [P] [US1] Extend `tests/fixtures/vault-code-first/` (declare `role`/`priority` + note_type `authoritative_role`/sections) and add a regression test `tests/scripts/test_source_authority_code_first.py` asserting Gate 1/2/3 verdicts are UNCHANGED (trunk=code, behaviour notes cite code, drift flagged, ledger code `USED`). **DONE** — added `research.spec.md` to the fixture (behaviour trunk `GitHub repos` priority 1 w/ oehk-service+shared-lib repos, intent Confluence; `service` note_type with authoritative_role=behaviour + authority/complementary sections). Regression lock `test_source_authority_code_first.py` (3 tests): spec validates as code-first w/ unique trunk; Gate 1 = all 6 service notes PASS; Gate 2 = only `disagree-unflagged` FAILs. **Also resolver-extended for US1** (repo segment-containment in `source_authority.py` so deep code paths resolve, per the chosen default): `test_source_authority.py` now 6 tests. **Gate 3 code-first regression → T008b** (unit-tests `check_termination_v2` directly). 51 existing gate/fixture tests still green (research.spec.md skipped — no drift sections).
- [x] T008 [P] [US1] Unit test the generalized Grounding gate in `tests/scripts/test_check_code_source_coverage.py`: `note → note_type → role` resolution + `citation → source_id → role` (the `T=behaviour` case). **DONE** — `TestGeneralizedGroundingResolution` (3 cases): declared behaviour repo PASS; **undeclared repo FAILs** (the distinguishing case — old `^https://github.com/` regex accepted it); intent-only citation FAILs a behaviour note. RED on the undeclared-repo case → GREEN after T009.
- [x] T008b [P] [US1] Unit test the generalized Trunk-seed gate (Analyze F4) in `tests/scripts/test_validate_cycle.py` (or the existing `check_termination_v2` test): `topics_from_trunk` enforced when a trunk is derivable (code case); the `if signatures:` guard no-ops when `derive_trunk` returns `None`; covers FR-006 directly (not just via fixtures). **DONE** — added to `test_validate_cycle_v2.py`: v3 `topics_from_trunk`+`parent_trunk_topic_id` accepted (RED — old structural validator required `topics_from_code` + no v3 dispatch); legacy `topics_from_code` still accepted; v3 trunk still enforces enumerated-repo membership; **pure-domain/no-repo-trunk vault does NOT trip "not under enumerated repo"** (the `if signatures:` guard). RED→GREEN.

### Implementation (generalize the 3 existing gates)
- [x] T009 [US1] Grounding gate (FR-004): generalize `scripts/check_code_source_coverage.py` — claim-type `T = note_type.authoritative_role`; require ≥1 citation whose `role==T` via the T006 resolver; remove `classify_url` regex-guessing. (depends T006) **DONE** — per-note branch: a scanned note whose note_type declares `authoritative_role` uses `resolve_role` against the spec's data_sources/repos (`_build_role_index` reconstructs the index from spec-parse.json); note_types WITHOUT authoritative_role keep `classify_url` (back-compat, so legacy + simple vaults are unchanged). `classify_url` retained for the legacy path rather than removed — flagged for the review pass (full removal would break pre-053 specs). 18 grounding+lock tests green; ruff clean.
- [x] T010 [US1] Drift gate (FR-005): generalize `scripts/check_intent_drift.py` — compare the note_type's `authority_section` vs `complementary_section` (opt-in: only when BOTH declared, D3); rename frontmatter flag `intent_implementation_drift → authority_drift`; update `tests/scripts/test_check_intent_drift.py`. **DONE** — `_drift_targets_from_spec` resolves targets + headings from note_types declaring BOTH sections (else legacy service|flow + Current Behaviour/Stated Intent); flag now reads `authority_drift` (falls back to legacy `intent_implementation_drift` for back-compat until T021's sweep); action message updated. TDD via `TestGeneralizedDriftSections` (3 cases: custom-heading drift FAILs unflagged [old gate skipped→passed]; `authority_drift:true` honoured; single-section type skipped per D3). RED→GREEN. 15 drift+lock tests green; ruff clean.
- [x] T011 [US1] Trunk-seed/attach gate (FR-006): generalize `scripts/validate_cycle.py::check_termination_v2` — **derive the trunk via `derive_trunk` (T006b)**; `topics_from_code → topics_from_trunk`, `parent_code_topic_id → parent_trunk_topic_id`; generalize `_spec_primary_repos`/`_repo_match_signatures`/`_source_file_matches_repo` to resolve via `source_id`; **preserve the `if signatures:` guard (~L773)** so a no-trunk vault (when `derive_trunk` returns `None`) doesn't trip "trunk empty". Replace the hardcoded `priority == 1 and role == "behaviour"` (`:556`). **DONE** — 4 edits: (1) dispatcher routes `schema_version` `"3"`→code-first handler (D6 v2→v3 bump); (2) structural validator accepts `topics_from_trunk` for the `topics_from_code` requirement; (3) `check_termination_v2` reads trunk/code + parent_trunk/parent_code aliases; (4) `_spec_primary_repos` selects the **unique-min-priority** trunk's repos (mirrors `derive_trunk`; `len(at_min)!=1`→`[]`→guard no-ops). **Deviation flagged for review**: kept dict-native min-priority in `_spec_primary_repos` rather than importing `derive_trunk` (RepoEnumeration↔dict impedance); semantics identical. `_repo_match_signatures`/`_source_file_matches_repo` already resolve by URL/path segments — no `source_id` change needed for code repos. 73 validate_cycle+gate tests green; both ruff gates clean.
- [x] T012 [US1] Run T007/T008 + the existing gate suites; confirm code-first verdicts UNCHANGED (regression green). **DONE** — 73 tests green across `test_validate_cycle{,_v2,_termination_fields,_budget_aliases,_research_schema}.py` + `test_check_intent_drift.py` + `test_check_code_source_coverage.py` + `test_source_authority_code_first.py`. Zero code-first regression; both ruff gates clean. **US1 (MVP) COMPLETE.**

---

## Phase 4: User Story 2 — Journal-first vault enforces with NO behaviour source (Priority: P1, abstraction proof)

**Goal**: prove the model is plastic without per-topic config.
**Depends on US1** (reuses the generalized gates).

- [x] T013 [P] [US2] NEW fixture `tests/fixtures/vault-journal-first/`: trunk = a **domain** source (journals, `priority: 1`), reddit domain `priority: 3`, **NO behaviour source**; note_types with `authoritative_role: domain`. **DONE** — `research.spec.md` (Journals domain priority 1 = trunk, Reddit domain priority 3, `finding` note_type `source_policy: hard` + `authoritative_role: domain`).
- [x] T014 [P] [US2] Test `tests/scripts/test_source_authority_journal_first.py`: Gate 3 demands `topics_from_trunk` = journal AND **does NOT error on missing behaviour** (the `if signatures:` path); Gate 1 requires the authoritative (domain) role; ledger shows journal `USED`. **DONE** — 4 tests: spec validates as non-code-first (trunk=Journals/domain); Gate 1 grounding PASSes a finding citing a journals-module-enumerated URL (resolves→domain) and FAILs one citing an unmatched URL; Gate 3 trunk-seed CONTINUEs with no "not under enumerated repo" / no behaviour-required error. (Ledger=USED is US3/FR-007.)
- [x] T015 [US2] Make T014 pass against the US1-generalized gates; fix any journal-first edge the test surfaces (no new gate logic expected — the generalization should already cover it). (depends US1) **DONE** — only edge surfaced was spec **validation**: `_is_code_first_spec` triggered on `priority==1` alone, wrongly invoking the behaviour-primary invariants on a domain trunk. Refined to `(priority==1 AND role=="behaviour") OR role=="intent" OR repos` (FR-002). Gates needed NO change (US1 generalization already covered journal-first). 195 spec + code-first-lock tests green; both ruff gates clean.

---

## Phase 5: User Story 3 — Bad-faith seeding FAILs deterministically (Priority: P1)

**Goal**: deterministic bad-faith / path-of-least-resistance detector.
**⚠️ Depends on spec 048 v2** (the Source-Consideration Ledger). FR-004/005/006
(US1/US2) ship independently; FR-007 lands once 048 v2's
`cycle-NNN-source-ledger.json` exists.

- [x] T016 [P] [US3] NEW fixture `tests/fixtures/vault-bad-faith/`: spec's derived trunk = code, scout seeds only from Confluence; include a `cycle-NNN-source-ledger.json` (per the 048 v2 contract) with code `NOT_REACHED`, intent `USED`. **DONE** — `research.spec.md` (code trunk GitHub priority 1 + Confluence intent); ledger variants constructed in the test per scenario (contract shape `{source, role, verdict[, reason]}`).
- [x] T017 [P] [US3] Test `tests/scripts/test_check_trunk_inversion.py`: FAIL when trunk `NOT_REACHED`/`SKIPPED_RELEVANCE` while a branch is `USED`; PASS when trunk `USED`; allow an *explained* trunk `ACCESS_FAIL`. **DONE** — 7 tests: bad-faith NOT_REACHED FAIL, SKIPPED_RELEVANCE FAIL, USED PASS, explained ACCESS_FAIL PASS, unexplained ACCESS_FAIL FAIL, no-branch-USED PASS, missing-ledger exit 2. RED→GREEN.
- [x] T018 [US3] Implement `scripts/check_trunk_inversion.py` (FR-007): read `cycle-NNN-source-ledger.json`, **resolve the derived trunk via `derive_trunk` (T006b)**, apply the verdict rule. **If 048 v2 has not shipped, code against its contract + the T016 fixture and gate the wire-in (T019) on 048 v2.** **DONE** — `scripts/check_trunk_inversion.py`: derives trunk via the shared `source_authority.derive_trunk_dict` (new helper — F2 consolidation; `validate_cycle._spec_primary_repos` retrofitted to use it too); matches trunk→ledger entry by source-name then role; FAIL rule = trunk not (USED or explained-ACCESS_FAIL) AND ≥1 branch USED. Coded against the 048 v2 contract + fixture.
- [~] T019 [US3] Wire Gate 4 into the gate-runner alongside the other cycle gates (where `validate_cycle.py` gates run). **HELD — gated on spec 048 v2.** The gate is implemented + tested against the contract; wiring it into the live cycle gate-runner waits until 048 v2 ships the real `cycle-NNN-source-ledger.json` artifact (its entry schema isn't finalized — 048 v2 is DRAFT awaiting `/speckit.clarify`).

---

## Phase 6: Polish & Cross-Cutting Concerns

- [~] T020 [P] Scout-report **v3**: emitters write `topics_from_trunk`/`parent_trunk_topic_id`; v2 (old-field) reports ride `_warn_deprecated_termination_shape_once` (warn, don't fail). Add a test for the deprecation path. (FR-006 / D6) **DEFERRED (read-side done; emitter-side held).** The *validator* already accepts both shapes (T011 — back-compat); this is the forward-consistency change to `templates/prompts/scout-prompt.md.j2` (the agent-facing emitter). Held for the user's eye on prompt wording — it changes real-cycle agent output and is non-blocking because the validator accepts v2 today. Tracked as a 053 follow-up.
- [~] T021 [P] Rename sweep `intent_implementation_drift → authority_drift` across `templates/`, note-type docs, and fixtures that reference it. **DEFERRED (gate back-compat in place).** The drift gate already reads BOTH flags (T010). Full sweep touches 5 agent-facing templates + **3 frozen spec-022 quality fixtures** (incl. their bundled `check_intent_drift.py` snapshots) + the 6 `vault-code-first` notes — wide blast radius on the quality harness, better done with the user's eye. Non-blocking (back-compat). The two NEW fixtures (`vault-journal-first`, `vault-bad-faith`) already use the canonical names. Tracked as a 053 follow-up.
- [~] T022 [P] Docs: update the note-type template + `examples/*-spec.md` to show `role`/`priority` + `authoritative_role` (examples only — `research.spec.md` is user-owned, never rewritten). **DEFERRED.** The new fixtures `vault-code-first/research.spec.md` + `vault-journal-first/research.spec.md` already serve as working schema examples. The `examples/*-spec.md` sweep needs per-note-type `authoritative_role` judgments (11 types in the codebase-vault example) the user will make when authoring the real vaults. Tracked as a 053 follow-up.
- [x] T023 Full lint gate: `ruff check .` AND `ruff format --check .` (separate gates). **DONE** — both gates clean repo-wide (532 files).
- [x] T024 Run `.venv/bin/python -m pytest tests/scripts tests/fixtures -q` + `PYTHON_BIN=.venv/bin/python bash build.sh --quality`; confirm green and the 3 fixtures behave per spec (code-first unchanged, journal-first plastic, bad-faith FAIL). **DONE (partial — quality harness pending).** Full fast suite: **1923 passed**, 8 skipped; the only 3 failures are `test_install_sh_tty_handling.py` (`OSError: out of pty devices` — environment-only, unrelated to 053; no install.sh change on this branch). The 3 new fixtures behave per spec (code-first lock green, journal-first plastic green, bad-faith FAIL green). `build.sh --quality` not run in this autonomous pass (smoke gate + 3-fixture harness; ~4 min + needs a clean env) — flagged to run before merge.

---

## Dependencies & Execution Order
- **Phase 2 (Foundational)** blocks all user stories.
- **US1 → US2** (US2 reuses US1's generalized gates).
- **US3** depends on Phase 2 **and spec 048 v2** (the ledger); its FR-007 wire-in (T019) is gated on 048 v2.
- **Polish** after the stories.

## Parallel opportunities
- Phase 2: T003, T004, T006 in parallel (different files); T005 after T003/T004.
- Fixtures across stories: T002, then T007/T013/T016 are independent `[P]`.
- Polish: T020, T021, T022 in parallel.

## Implementation strategy
- **MVP = US1** (Phase 2 + Phase 3): the generalized gates + the code-first
  regression green proves the generalization is safe. Ship FR-004/005/006.
- **US2** is the abstraction proof (no new gate logic — a new fixture + assertions).
- **US3 (FR-007)** lands when spec 048 v2's ledger exists; until then, code it
  against the contract + fixture and hold the wire-in.
