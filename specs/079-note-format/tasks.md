# Tasks: The note and frontmatter format

**Spec**: [`spec.md`](spec.md) · **Status of the spec**: `shipped` — the
format described there is the one on disk. These tasks are the follow-up work
§ Known divergences identified, and they include the open defect #226.

Since 2026-09-08 the *wider* half of #226 — deriving the checkers' structure
from the vault's own spec, one required-field declaration read by every
checker, sections and coverage categories as verify flags — is owned by
[`082-spec-driven-verify`](../082-spec-driven-verify/spec.md), which depends
on T001 below and does not replace it. T001–T003 stay here: they are the
narrow, record-correcting fixes this shipped spec identified.

## Phase 1: Make the shipped template satisfy the shipped checker (#226)

- [ ] T001 Reconcile `templates/note-type.md.j2` with
      `scripts/validate_vault.py::REQUIRED_FIELDS` (D1). The template emits
      four keys; the validator requires eight and rejects an empty
      `source_urls`. Either the template emits placeholders for all eight,
      or the validator learns to distinguish "scaffold not yet filled" from
      "wrong" — but a note the framework generates must not fail the
      framework's own validator on first contact.

  ### Testing Requirements

  _Authored 2026-09-07, before implementation._

  - **Test 1**: `tests/scripts/test_validate_vault.py::test_a_freshly_rendered_note_template_passes_validation`
    - Behavior: render the note-type template for a fixture note type, fill
      only the fields an agent would fill, and assert the vault validator
      reports zero violations. Fails today with six.
    - Tier: 3
  - **Test 2**: `tests/scripts/test_check_template_compliance.py::test_template_emits_every_required_frontmatter_field`
    - Behavior: assert the rendered template's frontmatter keys are a
      superset of `REQUIRED_FIELDS`, so the two lists cannot drift apart
      again silently.
    - Tier: 2

  **TDD discipline**: required — both tests land before the template or
  validator changes.

## Phase 2: One vocabulary per fact

- [ ] T002 Reconcile the validator's eight required fields with the
      verifier's three flagged ones (D2). A note can pass one and fail the
      other on fields neither shares.
- [ ] T003 Decide between `status` and `lifecycle` (D3). Both describe a
      note's life; one checker requires each and ignores the other.

## Phase 3: Enforce Principle IX somewhere a test can see it

- [ ] T004 Add a checker for the two-tier citation block (D4). Today the
      requirement lives only as an instruction inside the `ask` and `write`
      prompt templates, so a NON-NEGOTIABLE principle has no mechanical
      enforcement on that surface.
- [ ] T005 Decide whether stale `template_version` should gate anything
      (D5); today it is reported and nothing reads the report.
