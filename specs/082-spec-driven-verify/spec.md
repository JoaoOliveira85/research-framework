# Feature Specification: Spec-driven verify — the checkers read the vault's own declaration

**Status**: planned — batchable in v1.1.0 alongside `079-note-format`
T001–T003, which it depends on and does not replace.

**Spec**: `082-spec-driven-verify` · **Builds on**: `079-note-format` (the
record of the format as it is; its D1–D3 are this spec's starting facts and
its T001–T003 are this spec's preconditions) · **Issue**: #226 (owner;
`079` keeps the narrow template↔validator half under its T001)

---

## Why this spec exists, and why it is not a `079` amendment

`processors/verify.py` was ported from one vault's own `scripts/verify.py`
and still encodes that vault's schema and taxonomy: the folder names its MOC
consistency check expects (`MOC_TO_FOLDERS`, `CONTENT_FOLDER_PREFIXES`) and
the frontmatter fields it requires. A vault the framework itself generates
cannot satisfy it — #226's reviewer ran `verify()` over three committed
quality fixtures, `tests/fixtures/vault` and one real 840-note vault and got
`FAIL` on every one. #327 fixed the verifier's *verdict* (flag classes, the
format's own exemptions, case-folded links) and added `summary` to the
template; `079` D1 records that the shipped template still cannot satisfy
the shipped *validator*, and `079` D2/D3 record that three checkers carry
three field sets and two lifecycle vocabularies. Those are true statements
about the code at `943c7d3`, and `079` is a shipped record: its own header
says it adds no scope, and CONTRIBUTING § 2 freezes a `spec.md` at ship.

What #226 asks for is not a correction to the record. It is a contract
change — *derive the checks from the vault's own `research.spec.md`* —
that touches the generator templates, two checkers and a pipeline phase
together, which CONTRIBUTING § 3 names as exactly the case for a spec. Doing
it as a `079` amendment would either falsify a shipped header or pin
unshipped stories to a `shipped(...)` spec through deferred coverage rows.
So `079` keeps the narrow half it already owns (T001: the template emits
what the validator requires; T002/T003: the vocabulary questions) and this
spec owns the wider contract: one declaration of what a note must carry,
read by every checker, with structure taken from the spec rather than from
one vault's folder names.

A reader with no code access must be able to build checkers that accept any
vault this framework generates, from that vault's spec alone.

## Scope

**In scope**: the single declaration of required frontmatter fields and who
reads it; deriving the verifier's structural checks (MOC↔folder, content
folders) from `research.spec.md`'s `note_types[]` and `coverage_targets[]`;
`required_sections` and `coverage_category` as verify flags; parity between
the vault validator, the verifier and template compliance on the defects
they share; removal of vault-specific constants from the framework.

**Out of scope**: the frontmatter codec (`079` FR-010…FR-013, unchanged);
how notes are produced (`075`); the two-tier citation checker (`079` D4 /
T004 — a different surface); the `status`-vs-`lifecycle` decision (`079`
T003 owns it; this spec records the dependency under § Open questions
rather than deciding it in passing).

---

## User Scenarios & Testing

### User Story 1 — One list of required fields, read by everyone (Priority: P1)

1. **Given** the framework's declared required-field list, **When** the
   note-type template is rendered, the vault validator runs and the
   verifier runs, **Then** all three read the same list object — a test
   asserts identity, not equality of three copies.
2. **Given** a note rendered from the shipped template with only the fields
   an agent fills, **When** the validator and the verifier run, **Then**
   neither reports a missing required field (`079` T001's test is the
   validator half; this story adds the verifier half).
3. **Given** a field is added to the list, **When** nothing else changes,
   **Then** the template emits it, the validator requires it and the
   verifier flags its absence — in one commit, because there is one list.

### User Story 2 — Structure comes from the vault's spec, not one vault's folders (Priority: P1)

1. **Given** a vault whose spec declares note types with folders `guides/`
   and `people/` and no MOC structure, **When** the verifier runs, **Then**
   it reports zero `moc_gap` flags and never mentions a folder the spec did
   not declare.
2. **Given** a vault whose spec declares MOC-bearing note types, **When**
   a note of such a type sits outside the folder its type declares,
   **Then** the verifier flags it under a class the operator can act on.
3. **Given** `processors/verify.py`, **When** a guard greps it, **Then** no
   vault-specific folder name or MOC title remains as a constant.

### User Story 3 — Sections and categories are checked against the declaration (Priority: P2)

1. **Given** a note type declaring `required_sections`, **When** a note of
   that type lacks one of them as a `##` heading, **Then** the verifier
   reports `missing_section` as a `content` flag naming the section, and
   the vault validator reports the same defect.
2. **Given** a note carrying `coverage_category`, **When** its value names
   no declared coverage target, **Then** the verifier reports
   `unknown_coverage_category` as a `content` flag.
3. **Given** a note type with no `required_sections`, **When** the verifier
   runs, **Then** no section flag is raised for its notes.

### User Story 4 — The three checkers agree on the defects they share (Priority: P2)

1. **Given** a note with a missing required field, an empty `source_urls`
   and a missing required section, **When** the validator, the verifier
   and template compliance each run, **Then** each reports the defects in
   its scope, and no checker reports a defect another calls valid.
2. **Given** an exempt or alias note (`079` FR-008a/b), **When** the
   validator runs, **Then** it honours the same exemption the verifier
   does.

### Edge Cases

- A spec with no `note_types` at all → the checkers fall back to the
  framework's declared field list and raise no structural flags; a vault
  with no declaration is not thereby wrong, only unstructured.
- A note whose `type` names no declared note type → `079` FR-005 already
  makes that a violation; this spec adds nothing and changes nothing there.
- A vault mid-migration where some notes carry `lifecycle` and some
  `status` → neither checker rejects a note for carrying the other's key
  until `079` T003 decides (§ Open questions).

---

## Requirements

### Functional Requirements

**One declaration**

- **FR-001**: The framework MUST declare the required frontmatter fields
  once, as a single importable object, and the note-type template
  renderer, `scripts/validate_vault.py` and `processors/verify.py` MUST
  each read that object. A test MUST assert the three are the same object.
- **FR-002**: The list MUST be the eight `079` FR-002 names today; changing
  it is a `079` amendment plus a template change, never an edit in a
  checker.
- **FR-003**: The note-type template MUST emit every field in the list,
  with an empty-but-typed placeholder for those an agent fills (`079`
  T001), and the validator MUST accept a rendered note whose agent-filled
  fields are filled and whose `source_urls` is non-empty.

**Structure from the spec**

- **FR-004**: The verifier's MOC-consistency and content-folder checks MUST
  derive their expected folders from the vault's `research.spec.md`
  `note_types[].folder` and, where a type declares an authoritative or MOC
  role, from that declaration — never from a constant naming a folder.
- **FR-005**: `MOC_TO_FOLDERS` and `CONTENT_FOLDER_PREFIXES` MUST be removed
  from `processors/verify.py`, and a guard test MUST fail if a string
  matching a vault-specific folder or MOC title reappears there.
- **FR-006**: A vault whose spec declares no MOC structure MUST produce
  zero `moc_gap` flags. `orphan` stays (`079` FR-022, class `tooling`).
- **FR-007**: The verifier MUST receive the spec's `note_types` and
  `coverage_targets` through the same seam `075` FR-020's phase already
  uses to pass `processors` and `note_types` (`_drive_verify` reads
  `spec-parse.json`), not by re-parsing the spec itself.

**Sections and categories**

- **FR-008**: `missing_section` MUST be a verifier flag of class `content`,
  raised when a note lacks a `##` heading its note type's
  `required_sections` declares, naming the section. Order is not checked by
  the verifier (`079` FR-014's order rule stays template compliance's).
- **FR-009**: `unknown_coverage_category` MUST be a verifier flag of class
  `content`, raised when `coverage_category` is present and names no
  declared coverage target.
- **FR-010**: Neither flag MUST be raised for exempt or alias notes (`079`
  FR-008a/b), for tooling Markdown (`079` FR-024), or for note types that
  declare no `required_sections`.

**Parity**

- **FR-011**: For the defects all three checkers can see — a missing
  required field, an empty `source_urls`, a missing required section — the
  vault validator, the verifier and template compliance MUST report the
  same defect on the same note. A parity test over one fixture note MUST
  pin this.
- **FR-012**: The vault validator MUST honour `verifier_status: exempt` and
  `note_type: alias` exactly as the verifier does (`079` FR-008a/b), so a
  note cannot be exempt in one checker and violating in another.
- **FR-013**: The verifier's auto-fix scope (`079` FR-023) MUST NOT grow:
  the new flags are reported, never auto-fixed.

**Honesty**

- **FR-014**: `079` SC-001 ("a note written by the shipped template passes
  the shipped validator — not met today") MUST be met when this spec
  ships, and `079`'s D1 marked as resolved by reference to this spec, not
  rewritten.

### Key entities

| Entity | Where | Notes |
| --- | --- | --- |
| Required-field list | one importable object in `src/research_framework/vault/` | FR-001; the eight `079` FR-002 names |
| Note type declaration | `research.spec.md` → `note_types[]` | `folder`, `required_sections`, `authoritative_role`, `template_version` (`079` FR-018) |
| Coverage targets | `research.spec.md` → `coverage_targets[]` | the set `coverage_category` is checked against |
| Verify flags (new) | `_pipeline/runs/<run_id>/verify-report.json` (`080`) or `_pipeline/logs/verify-<ts>.json` until `080` ships | `missing_section`, `unknown_coverage_category`, both class `content` |

## Success Criteria

- **SC-001**: A vault generated by this framework passes this framework's
  validator and verifier on first contact, whatever its note types are
  called and wherever its spec puts them.
- **SC-002**: No folder name or MOC title from any real vault exists in the
  framework's checkers.
- **SC-003**: A required field can be added in one place and every checker
  and template follows.
- **SC-004**: The three checkers cannot disagree on a defect they all see.

---

## Acceptance coverage

| User story | Evidence |
| --- | --- |
| US1 — One list of required fields, read by everyone | _(deferred to tasks.md T001)_ |
| US2 — Structure comes from the vault's spec, not one vault's folders | _(deferred to tasks.md T002)_ |
| US3 — Sections and categories are checked against the declaration | _(deferred to tasks.md T003)_ |
| US4 — The three checkers agree on the defects they share | _(deferred to tasks.md T004)_ |

### Testing Requirements

Per-task blocks live in [`tasks.md`](tasks.md), authored before
implementation. `079` behaviour this spec keeps, and its pins, which MUST
stay green:

| Retained `079` behaviour | Pinned by |
| --- | --- |
| Flag classes drive the verdict; tooling flags never FAIL | `tests/processors/test_verify_flag_classes.py`, `tests/pipeline/test_runner_verify_verdicts.py` |
| Exempt and alias notes are counted, never graded | `tests/processors/test_verify_note_format.py` |
| Auto-fix is surgical and idempotent | `tests/processors/test_verify.py::TestAutoFixPreservesFrontmatter` |
| Tooling Markdown is never counted or mutated | `tests/processors/test_verify.py::TestWalkScope` |
| The phase passes spec config down | `tests/pipeline/test_runner_verify_verdicts.py::TestSpecConfigReachesTheProcessor` |

---

## Known divergences

- **D1 — The MOC check has two possible sources and the spec declares
  neither explicitly.** `research.spec.md`'s `note_types[]` declares
  folders and an optional `authoritative_role`, but no field says "this
  type is a MOC" or "this folder should be linked from that MOC". FR-004
  derives what it can from `folder`; whether a `moc:` declaration is added
  to the spec schema (spec 073's append path exists for it) is T002's first
  decision, recorded there before code.
- **D2 — Template compliance is a script, not a verify flag.**
  `scripts/check_template_compliance.py` already checks sections (`079`
  FR-025) but runs outside the pipeline's verify phase, so a missing
  section has never affected a verdict. FR-008 brings the check into the
  verifier without removing the script.
- **D3 — The validator and the verifier have different ideas of "note".**
  The validator skips scaffold, index and template files by name pattern;
  the verifier walks the corpus directory and excludes tooling by path.
  FR-012 aligns exemptions; aligning the walks is left to the
  implementation to propose if parity proves impossible without it.

## Open questions

- **Q1 — `status` versus `lifecycle`** (`079` T003). This spec does not
  decide it. Until it is decided, FR-011's parity set excludes lifecycle
  keys, and neither checker may reject a note for carrying the other's
  vocabulary. The recommended default, for the owner: keep
  `verifier_status` (the verifier's, already spec'd in `079` FR-008a) and
  the validator's `lifecycle` mapping; retire the bare `status` key the
  verifier auto-adds, since `079` D3 shows nothing else reads it.

## Assumptions

- `_pipeline/spec-parse.json` carries `note_types[]` with `folder` and
  `required_sections`, and `coverage_targets[]`, as the parser writes them
  today; this spec adds no parser field except what D1's decision may add.
- Fixture vaults used to pin this spec are invented (`tests/fixtures/`);
  no real vault's taxonomy is checked in to make a test pass.
