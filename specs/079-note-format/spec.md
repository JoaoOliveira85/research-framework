# Feature Specification: The note and frontmatter format

**Status**: shipped(2026-09-08, commit 943c7d3) — a *record* of the on-disk
note contract as it is, written from the templates and the checkers at that
commit (rebased onto #327, which classed the verify flags and taught verify
the vault format's own exemptions). It adds no scope. Divergences are filed under § Known divergences.

**Spec**: `079-note-format` · **Supersedes as the owning document**:
`specs/_archive/015d-note-types-first-class/` (never implemented as
specified) · **Epic**: #217 · **Issue**: #275, #226

---

## Why this spec exists

A generated vault is a directory of Markdown notes. That directory *is* the
product, and its format has never been written down — it exists as the
intersection of a Jinja template, two independent checkers, a verifier, and a
wikilink normaliser, none of which agree. Issue #226 is the measurable
consequence: the note template the framework ships emits four frontmatter
keys, and the validator the framework ships requires eight and rejects one of
the four for being empty. A note produced by the shipped template fails the
shipped checker on first contact.

A reader with no code access must be able to write a note this framework
accepts, and to build the checkers that accept it.

## Scope

**In scope**: the frontmatter schema, the body structure, the note-type
system, the two-tier citation rendering, wikilink normalisation, and what
each checker asserts, rejects and auto-fixes.

**Out of scope**: how notes are *produced* (the research phase — `075`), how
sources are graded (`055`, `066`), and the cost sidecars, which are dispatch
records rather than note sidecars (`078`).

---

## User Scenarios & Testing

### User Story 1 — A note round-trips without being damaged (Priority: P1)

1. **Given** a note whose frontmatter contains nested mappings, lists,
   quoted scalars and non-ASCII text, **When** it is read and written back
   through the canonical codec, **Then** the file is unchanged.
2. **Given** a note the auto-fixer must add one key to, **When** it is
   fixed, **Then** exactly that key is added and nothing else in the
   frontmatter is reordered, unquoted, hoisted or flattened.
3. **Given** a note whose frontmatter is not valid YAML, **When** the fixer
   runs, **Then** the note is flagged and **not** rewritten — a parser that
   cannot read a file must not be allowed to write it.
4. **Given** frontmatter that is a YAML list rather than a mapping, or uses
   an unsafe YAML tag, **When** it is parsed, **Then** it is rejected.

### User Story 2 — Every claim is traceable to a source (Priority: P1)

1. **Given** a note with an empty `source_urls`, **When** the vault
   validator runs, **Then** it is a violation, not a warning — at least one
   source is required.
2. **Given** an answer or a written document, **When** it is rendered,
   **Then** it carries a Tier-1 `Vault Sources` section and a Tier-2
   `Original Sources` section as distinct, explicitly headed blocks; a
   Tier-2 URL buried inside Tier-1 prose is a violation.
3. **Given** a note whose `summary` exceeds the maximum length, **When** the
   validator runs, **Then** it is a violation.

### User Story 3 — Wikilinks survive a move between filesystems (Priority: P2)

1. **Given** a wikilink whose case does not match the target file, **When**
   normalisation runs, **Then** it is rewritten to the file's real stem, so
   the vault works on a case-sensitive filesystem.
2. **Given** a path-prefixed or title-cased link to an existing note,
   **When** the validator runs, **Then** it resolves rather than being
   reported broken.
3. **Given** a link to a note that genuinely does not exist, **When** the
   validator runs, **Then** it is still reported.

### User Story 4 — Only notes are graded, and only notes are changed (Priority: P1)

1. **Given** a vault containing tooling Markdown (agent definitions, index
   files, `_pipeline/` artefacts), **When** the verifier runs, **Then**
   those files are not counted as notes, do not affect the verdict, and are
   never rewritten.
2. **Given** a note-type template's declared `required_sections`, **When**
   template compliance is checked, **Then** a note missing one of those
   headings is reported.
3. **Given** a note whose `template_version` is older than its template's,
   **When** the version check runs, **Then** the note is reported as needing
   an upgrade.

### Edge Cases

- A note with no frontmatter at all short-circuits the parser rather than
  raising.
- Index and MOC files carry no frontmatter by design and exist to link out;
  they are excluded from orphan and summary checks.
- An alias-redirect stub is exempt from the full frontmatter schema.
- A single malformed note fails the whole vault regardless of the failure
  threshold — an unparseable file is not a percentage.

---

## Requirements

### Functional Requirements

**Frontmatter**

- **FR-001**: A note MUST begin with a YAML frontmatter block delimited by
  `---` lines, parsed in safe mode, and MUST parse to a **mapping**. A list
  or an unsafe tag MUST be rejected.
- **FR-002**: The vault validator MUST require these eight fields on every
  note: `title`, `type`, `summary`, `tags`, `source_urls`, `related`,
  `created`, `updated`.
- **FR-003**: `source_urls` MUST be non-empty — at least one source per
  note.
- **FR-004**: `summary` MUST NOT exceed the configured maximum length
  (120 characters).
- **FR-005**: `type` MUST name a note type declared in the vault's
  `research.spec.md`.
- **FR-006**: `template_version` MUST be stamped on every note rendered from
  a note-type template and MUST follow SemVer, so an upgrade check can
  compare it against the template's own version.
- **FR-007**: `lifecycle`, when present, MUST be a mapping; its
  `created_at_cycle` MUST be an integer cycle number.
- **FR-008**: `coverage_category` MAY be present and names the coverage
  target a note contributes to.
- **FR-008a**: `verifier_status` MAY carry `verified`, `pending` or
  `rejected` (written by the verifier stage) or `exempt` — the vault
  format's own opt-out. An exempt note MUST be counted but never graded,
  never auto-fixed and never reported as an orphan.
- **FR-008b**: `note_type: alias` marks a redirect stub, which exists to
  point at another note and says nothing of its own. Alias stubs MUST be
  treated exactly as exempt notes are.
- **FR-009**: Unknown frontmatter keys MUST be preserved untouched by every
  reader and writer.

**The codec**

- **FR-010**: All note reads and writes MUST go through one frontmatter
  codec. No consumer may use a third-party frontmatter library or a
  hand-rolled split, because a codec that silently normalises nested keys and
  quoted scalars destroys notes when a fixer writes them back.
- **FR-011**: Parse→dump MUST be byte-stable for any note the codec can
  parse.
- **FR-012**: A note that fails to parse MUST be flagged and MUST NOT be
  written back under any circumstance, including auto-fix.
- **FR-013**: A missing closing delimiter MUST raise, not be silently
  treated as a note without frontmatter.

**Body structure**

- **FR-014**: A note's body MUST carry the `required_sections` its note type
  declares, as `##` headings, in the order the type declares them.
- **FR-015**: An answer or generated document MUST end with a two-tier
  citation block: a `Vault Sources` section (Tier 1 — wikilinks into the
  vault) and an `Original Sources` section (Tier 2 — the external URLs the
  Tier-1 notes de-reference to), rendered as separate, explicitly headed
  sections.
- **FR-016**: Tier-2 URLs MUST NOT be embedded inside Tier-1 prose; the
  verifier treats that as a Principle IX violation.

**Note types**

- **FR-017**: Note types MUST be declared per vault in `research.spec.md`,
  never hardcoded in the framework — a childcare vault and a firmware vault
  get different types from their own specs.
- **FR-018**: A note type MUST carry: `name`, `description`, `folder`,
  `required_sections`, `contextual_questions`, `min_word_count` (default
  200), `source_policy` (`hard` or `soft`; resolved from a default set when
  unset), `template_version`, and optionally `authoritative_role`
  (`behaviour` \| `intent` \| `domain`) with its `authority_section` and
  `complementary_section`.
- **FR-019**: The drift gate that compares an authority section against its
  complement MUST run only when both sections are declared — opt-in, so
  legacy specs are unaffected.
- **FR-020**: Once **any** note type declares `authoritative_role`,
  validation MUST require consistency across all of them.

**Checkers**

- **FR-021**: The **vault validator** MUST report, per note: missing required
  fields, empty `source_urls`, an over-long `summary`, broken wikilinks,
  duplicate notes, and `lifecycle` shape errors. It MUST skip scaffold,
  index and template files.
- **FR-022**: The **verifier** MUST flag: `missing_status`,
  `missing_related`, `missing_summary`, `broken_wikilink`, `orphan`,
  `moc_gap` and `malformed_frontmatter`.
- **FR-022a**: Every flag MUST carry a **class**. `content` is what only the
  vault's author can fix; `tooling` is the framework's own bookkeeping — the
  two keys the verifier auto-fixes itself (`missing_status`,
  `missing_related`), plus `orphan` and `moc_gap`, which describe the shape
  of the graph rather than the content of a note. A flag with no class is a
  flag nobody can decide a verdict from.
- **FR-022b**: The verdict MUST be `FAIL` when any note is malformed or when
  the **content**-flag ratio exceeds the threshold; `WARN` above a small
  absolute flag count, which tooling flags do reach; `PASS` otherwise.
  Tooling flags MUST be reported and counted but MUST NOT drive `FAIL` — an
  orphan weighing as much as unparseable frontmatter is what let a young or
  lightly-linked vault fail by construction.
- **FR-022c**: The failure message MUST name both halves, so an operator can
  see what was set aside as well as what failed.
- **FR-022d**: Wikilink resolution inside the verifier MUST be case-folded,
  as ADR-0005 decided. A vault mid-normalisation must not score each case
  variant as both a broken link and an orphan.
- **FR-023**: The verifier MUST auto-fix only the specific missing keys it
  is designed to add (`status`, `related`), MUST make no other change, and
  MUST be idempotent.
- **FR-024**: The verifier MUST grade the corpus directory, not the vault
  root, and MUST never count or mutate tooling Markdown.
- **FR-025**: **Template compliance** MUST compare a note's headings against
  its note type's rendered template and report missing sections, and MUST
  separately report notes whose `template_version` is behind the template's.
- **FR-026**: **Wikilink normalisation** MUST be the single source of the
  case and path rules, MUST run at cycle time so vaults stay portable
  between case-sensitive and case-insensitive filesystems, and MUST resolve
  path-prefixed and title-cased links to their real stems before reporting a
  link broken.
- **FR-027**: Every vault-mutating checker MUST offer `--dry-run`.

### Key entities

| Entity | Where | Notes |
| --- | --- | --- |
| Note | `<corpus>/<folder>/<title>.md` | frontmatter mapping + Markdown body |
| Note type | `research.spec.md` → `note_types[]` | per-vault; drives folder, sections, word floor, source policy |
| Note-type template | rendered from the framework's note-type template | emits `type`, `template_version`, `source_urls`, `coverage_category` and the type's `required_sections` |
| Index / MOC file | `_index.md`, `_graph.md`, `_concepts.md` | no frontmatter by design; links out; excluded from note checks |
| Verify report | `_pipeline/logs/verify-<timestamp>.json` | per-note flags; the state file carries only a bounded summary |

## Success Criteria

- **SC-001**: A note written by the shipped template passes the shipped
  validator. **Not met today** — see D1; this spec is what makes the gap
  statable.
- **SC-002**: No checker can damage a note it could not parse.
- **SC-003**: A vault is portable between case-sensitive and
  case-insensitive filesystems without broken links.
- **SC-004**: Tooling Markdown never influences a vault's verdict.

---

## Acceptance coverage

| User story | Evidence |
| --- | --- |
| US1 — A note round-trips without being damaged | `tests/vault/test_frontmatter.py::test_dump_parse_roundtrip`, `tests/processors/test_verify.py::test_malformed_yaml_is_flagged_not_rewritten` |
| US2 — Every claim is traceable to a source | `tests/scripts/test_validate_vault.py::test_missing_source_urls`, `tests/scripts/test_validate_vault.py::test_summary_overflow` |
| US3 — Wikilinks survive a move between filesystems | `tests/scripts/test_validate_vault_path_prefixed_wikilinks.py::test_case_mismatch_in_path_prefixed_link_resolves`, `tests/scripts/test_validate_vault_path_prefixed_wikilinks.py::test_genuinely_missing_target_still_flags` |
| US4 — Only notes are graded, and only notes are changed | `tests/processors/test_verify.py::test_non_notes_are_never_mutated`, `tests/processors/test_verify_note_format.py` |

### Testing Requirements

| FR group | Pinned by |
| --- | --- |
| FR-001, FR-010…FR-013 (codec) | `tests/vault/test_frontmatter.py` |
| FR-002…FR-004 (required fields) | `tests/scripts/test_validate_vault.py` |
| FR-007 (`lifecycle`) | `tests/scripts/test_validate_vault.py::test_multiple_violations_reported` |
| FR-021 (validator scope) | `tests/scripts/test_validate_vault.py::test_skips_scaffold_index_and_templates`, `tests/scripts/test_validate_vault_integrity.py` |
| FR-022 (verifier flags) | `tests/processors/test_verify.py::TestVerifyFunction`, `tests/processors/test_verify_failure_reason.py` |
| FR-022a…FR-022c (flag classes and the verdict) | `tests/processors/test_verify_flag_classes.py`, `tests/pipeline/test_runner_verify_verdicts.py` |
| FR-008a, FR-008b, FR-022d (exemptions, aliases, case-folding) | `tests/processors/test_verify_note_format.py` |
| FR-023 (auto-fix is surgical) | `tests/processors/test_verify.py::TestAutoFixPreservesFrontmatter` |
| FR-024 (scope) | `tests/processors/test_verify.py::TestWalkScope`, `tests/pipeline/test_runner_verify_scope.py` |
| FR-025 (template compliance) | `tests/scripts/test_check_template_compliance.py`, `tests/scripts/test_check_template_compliance_with_dir.py` |
| FR-026 (wikilinks) | `tests/scripts/test_validate_vault_path_prefixed_wikilinks.py`, `tests/scripts/test_check_acronym_links.py` |

---

## Known divergences

- **D1 — The shipped template still cannot satisfy the shipped validator
  (#226), though the gap narrowed.** #327 added `summary: ""`, so the
  note-type template now emits five keys: `type`, `template_version`,
  `source_urls: []`, `coverage_category: ""`, `summary: ""`. The vault
  validator requires eight — `title`, `type`, `summary`, `tags`,
  `source_urls`, `related`, `created`, `updated` — and rejects an empty
  `source_urls` outright. A note rendered from the template and validated
  without an agent filling it in still produces five violations. The
  template is a *scaffold for an agent to complete*, but nothing says so,
  and nothing distinguishes "not yet filled" from "wrong". Note that #327
  fixed the *verifier* side of this (`missing_summary` is a content flag the
  template now satisfies); the *validator* side is untouched.
- **D2 — Three checkers, three field sets.** The validator requires eight
  fields; the verifier flags three (`status`, `related`, `summary`) — and
  `status` is not in the validator's required list at all, while `title`,
  `tags`, `created` and `updated` are invisible to the verifier. A note can
  pass one and fail the other on fields neither shares.
- **D3 — `status` versus `lifecycle`.** The verifier requires and auto-adds
  a `status` key; the validator has no opinion on it and instead validates a
  `lifecycle` mapping the verifier ignores. Two lifecycle vocabularies exist
  on the same object.
- **D4 — The two-tier citation is enforced only in prompts.** The Tier-1 /
  Tier-2 section requirement lives in the `ask` and `write` command
  templates as instructions to the model. No checker in this repo asserts a
  generated document carries both sections, so Principle IX — declared
  NON-NEGOTIABLE — has prompt-level enforcement only on that surface.
- **D5 — `template_version` upgrade detection is advisory.** Notes without
  a `template_version` are reported, and stale ones are reported, but
  nothing gates on the report.

## Assumptions

- The corpus directory is resolved from `_pipeline/spec-parse.json`, falling
  back to the vault root.
- Notes are UTF-8 and are edited by agents and humans in the same tree; every
  writer therefore has to be non-destructive to keys it does not own.
