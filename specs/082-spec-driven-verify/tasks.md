# Tasks: Spec-driven verify

**Spec**: [`spec.md`](spec.md) · **Status of the spec**: `planned`. Task
boxes are live: a `- [ ]` means genuinely not done. `079-note-format` T001
is the precondition for T001 here and lands first, in its own PR.

## Phase 1: One declaration

- [ ] T001 Declare the required-field list once in
      `src/research_framework/vault/note_format.py` and make the note-type
      template renderer, `scripts/validate_vault.py` and
      `src/research_framework/processors/verify.py` read it (FR-001…FR-003).
      `079` T001's two tests are the validator half of the proof and are
      not repeated here.

  ### Testing Requirements

  _Authored 2026-09-08, before implementation._

  - **Test 1**: `tests/vault/test_note_format_contract.py::test_template_validator_and_verifier_share_one_required_field_object`
    - Behavior: import the list from all three readers' modules and assert
      they are the same object (`is`), not three equal copies.
    - Tier: 1
  - **Test 2**: `tests/processors/test_verify_spec_driven.py::test_a_freshly_rendered_note_raises_no_missing_field_flag`
    - Behavior: render the note-type template for a fixture type, fill only
      the agent-filled fields, run `verify()`; no `missing_*` flag on that
      note.
    - Tier: 3
  - **Test 3**: `tests/vault/test_note_format_contract.py::test_adding_a_field_to_the_list_reaches_every_reader`
    - Behavior: monkeypatch one extra name into the list; the rendered
      template emits it and both checkers flag its absence on a note that
      lacks it.
    - Tier: 2

  **TDD discipline**: required — the tests above MUST be added in the same
  commit as or earlier than the implementation commit for
  `src/research_framework/vault/note_format.py`.

## Phase 2: Structure from the spec

- [ ] T002 Decide D1 (how a spec declares MOC structure), record the
      decision at the top of this task, then derive the verifier's MOC and
      content-folder checks from `note_types[]` and delete
      `MOC_TO_FOLDERS` / `CONTENT_FOLDER_PREFIXES` (FR-004…FR-007).
      Implementation in `src/research_framework/processors/verify.py` and
      `src/research_framework/pipeline/runner.py` (the seam that passes
      `note_types` and `coverage_targets` down).

  ### Testing Requirements

  _Authored 2026-09-08, before implementation._

  - **Test 1**: `tests/processors/test_verify_spec_driven.py::test_moc_mapping_comes_from_the_specs_note_types`
    - Behavior: a fixture spec declaring two note types in `guides/` and
      `people/` with a MOC role on one; a note of that type outside its
      folder is flagged, one inside is not, and no folder the spec did not
      declare is mentioned in any flag.
    - Tier: 3
  - **Test 2**: `tests/processors/test_verify_spec_driven.py::test_a_vault_with_no_moc_structure_has_no_moc_gap_flags`
    - Behavior: a spec with note types and no MOC declaration; `verify()`
      over a small corpus raises zero `moc_gap` flags.
    - Tier: 3
  - **Test 3**: `tests/processors/test_verify_spec_driven.py::test_no_vault_specific_folder_names_remain_in_verify`
    - Behavior: read `processors/verify.py` as text; assert the two removed
      constant names are absent and no string matches a numbered-folder or
      `MOC` title pattern.
    - Tier: 2
  - **Test 4**: `tests/pipeline/test_runner_verify_verdicts.py::test_the_declared_coverage_targets_reach_the_processor`
    - Behavior: `_drive_verify` passes `coverage_targets` from
      `spec-parse.json` to `verify()` alongside `note_types`.
    - Tier: 3

  **TDD discipline**: required — the tests above MUST be added in the same
  commit as or earlier than the implementation commit for
  `src/research_framework/processors/verify.py`.

## Phase 3: Sections, categories, parity

- [ ] T003 `missing_section` and `unknown_coverage_category` as `content`
      flags, exemptions honoured (FR-008…FR-010, FR-013). Implementation in
      `src/research_framework/processors/verify.py`.

  ### Testing Requirements

  _Authored 2026-09-08, before implementation._

  - **Test 1**: `tests/processors/test_verify_spec_driven.py::test_a_missing_required_section_is_a_content_flag_naming_the_section`
    - Behavior: a note type declaring `["Overview", "Sources"]`; a note
      without `## Sources` gets `missing_section` with that name, class
      `content`.
    - Tier: 3
  - **Test 2**: `tests/processors/test_verify_spec_driven.py::test_an_undeclared_coverage_category_is_a_content_flag`
    - Behavior: `coverage_category: nonsense` against declared targets;
      `unknown_coverage_category` is raised; a declared value is not.
    - Tier: 3
  - **Test 3**: `tests/processors/test_verify_spec_driven.py::test_exempt_alias_and_sectionless_types_raise_no_new_flags`
    - Behavior: an exempt note, an alias stub and a note of a type with no
      `required_sections` each raise neither new flag.
    - Tier: 3
  - **Test 4**: `tests/processors/test_verify_spec_driven.py::test_the_new_flags_are_never_auto_fixed`
    - Behavior: run with `auto_fix=True`; the note's body and frontmatter
      are byte-unchanged and the flags are still reported.
    - Tier: 3

  **TDD discipline**: required.

- [ ] T004 Parity: the validator, the verifier and template compliance
      report the same shared defects on one fixture note, and the validator
      honours the verifier's exemptions (FR-011, FR-012). Implementation in
      `scripts/validate_vault.py` and
      `scripts/check_template_compliance.py`.

  ### Testing Requirements

  _Authored 2026-09-08, before implementation._

  - **Test 1**: `tests/scripts/test_checker_parity.py::test_three_checkers_report_the_same_shared_defects`
    - Behavior: one note missing a required field, with empty
      `source_urls` and a missing section; each checker's report names all
      three defects it is in scope for, and none calls a defect valid.
    - Tier: 3
  - **Test 2**: `tests/scripts/test_validate_vault.py::test_exempt_and_alias_notes_are_skipped_like_the_verifier_does`
    - Behavior: `verifier_status: exempt` and `note_type: alias` notes
      produce no validator violations for missing fields.
    - Tier: 3

  **TDD discipline**: required.

## Phase 4: Close the record

- [ ] T005 Mark `079` D1 resolved by reference to this spec and tick `079`
      SC-001 as met (FR-014) — a post-ship note on the shipped record, not
      a rewrite of it — and correct README/ARCHITECTURE wherever they still
      say verify is vault-agnostic without qualification.
