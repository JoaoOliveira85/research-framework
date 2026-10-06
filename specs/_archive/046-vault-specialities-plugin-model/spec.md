# Feature Specification: Vault Specialities — Modular Plugin Model

> **🗄️ SUBSUMED BY spec 053 (2026-06-02).** Per the user decision on
> `docs/handoff-source-strategy.md`, vault specialities are addressed by
> **generalizing** the existing source-authority model (declared `role`/
> `priority`, derived trunk) rather than by extracting a plugin subsystem.
> Spec 053 (Plastic-but-Enforceable Source Authority) delivers per-vault-type
> behaviour via *declaration*, which is the value 046 was reaching for — so the
> plugin-interface approach here is superseded. Do NOT plan against 046; see
> `specs/053-source-authority-strategy/spec.md`. Kept as design-history (the
> reuse-candidate notes below may still inform 053).

**Feature Branch**: `046-vault-specialities-plugin-model`
**Created**: 2026-05-27 (promoted from `docs/ROADMAP.md` Horizon 3 "Vault Specialities — modular plugins" during post-Wave-1 doc restructure).
**Status**: superseded(by spec 053) — 🗄️ **SUBSUMED BY spec 053 (2026-06-02)** — vault-type differences are handled by declared source authority (053), not a plugin subsystem. (Was: 🚧 BLOCKED design-space spec.)

> ## ⚠️ Promotion gate
>
> This spec exists to PRESERVE design constraints. It is NOT ready for
> planning or implementation.
>
> **Promotion criterion**: a SECOND concrete speciality (recipes,
> scientific papers, legal documents, etc.) ships a real implementation
> (not just a plan) that would benefit from the plugin contract. Spec
> 002 (codebase-vault code-first) is the FIRST and currently ONLY
> concrete speciality. Until a SECOND arrives, extracting the
> abstraction calcifies it around code's quirks.
>
> **What this spec IS**:
> - A design-space document capturing the proposed plugin contract,
>   the four reuse candidates, and the open clarifications.
> - A constraint-preservation contract — when the trigger fires, the
>   second speciality MUST validate the proposed plugin shape.
>
> **What this spec is NOT**:
> - An IMPLEMENTABLE spec. The promotion criterion gates `/speckit.plan`.
> - A commitment to the proposed plugin shape — the second speciality
>   will inform the final shape, possibly overriding the proposed
>   on-disk layout or contract.

**Input**: The base vault structure is generic and domain-agnostic (Principle II). But some domains (code, recipes, scientific papers, legal documents) benefit from richer, domain-specific structure: extra templates, domain-specific validators, skills that know how to extract structure from the domain's native sources. Today, spec 002 (codebase-vault code-first) is that domain-specific layer for code — but it landed as a core feature, not a plugin. As soon as a second domain wants similar treatment, we'd be cloning spec 002 wholesale, which calcifies the abstraction around code's quirks. The rule-of-three says: preserve the constraints now; extract the plugin interface when duplication forces it.

## Clarifications

### Pending — `/speckit.clarify` session deferred until promotion

- **Q1 (Composability)**: Should specialities be composable (one vault has both "code" and "scientific-papers")? Adds complexity. Default proposed: NO — one speciality per vault in v1; revisit composability if real demand surfaces in v2.
- **Q2 (Validator interaction with verifier stage)**: How do speciality validators interact with the generic verifier stage (spec 020 consensus)? Are they an additional verifier MODE, or a separate PRE-VERIFIER pass? Default proposed: PRE-VERIFIER pass — speciality validators run BEFORE the generic verifier; if they reject, the note never reaches the verifier; if they pass, generic verifier still gets to vote.
- **Q3 (Speciality installation)**: Bundled with framework install (`install.sh` ships ALL specialities, vault picks one), or downloaded on demand (`./vault speciality install code`)? Default proposed: BUNDLED — all specialities ship in the framework's package; vault picks one via `research.spec.md`. Avoids out-of-band install steps; size concern is low (few KB per speciality).
- **Q4 (Speciality versioning)**: Specialities evolve. How does version compatibility work — speciality version pinned in `research.spec.md`, OR speciality version tied to framework version? Default proposed: framework-version pinned in v1 (one less surface to manage); revisit if specialities want independent release cadence.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Code speciality reframed as canonical reference (Priority: P1, AFTER promotion)

When the promotion criterion fires, spec 002's code-first deliverables (the `repo_scan.py` + `check_intent_drift.py` + `check_code_source_coverage.py` trilogy + a code source module post-Wave-2) are reframed as a "code" speciality. They live under `templates/specialities/code/` (framework) and `<vault>/specialities/code/` (when installed). Existing code-first vaults continue working unchanged — the migration is internal restructuring.

**Why this priority**: This is the canonical reference. Without reframing 002 as the speciality model, the second speciality has no on-disk shape to mirror.

**Independent Test**: Reframe spec 002's deliverables into `templates/specialities/code/` structure. Re-run existing codebase-vault tests. Verify: all tests pass; existing code-first vaults install + cycle identically.

**Acceptance Scenarios**:

1. **Given** the migration runs, **When** existing codebase-vault tests are executed, **Then** all tests pass without modification.
2. **Given** an existing code-first vault, **When** `./vault update` runs (post-046), **Then** the vault's behavior is identical to pre-046.
3. **Given** the new layout, **When** a future speciality is added, **Then** it follows the same on-disk shape as `templates/specialities/code/`.

---

### User Story 2 — Second speciality arrives + validates the plugin shape (Priority: P1, TRIGGERS PROMOTION)

ONE of the four candidate specialities ships a real implementation:

1. **Recipes** — ingredient parsing, nutritional fields, dietary tags. Skills that extract structured ingredient lists from recipe URLs.
2. **Scientific papers** — author/year frontmatter, citation graph, abstract-extraction skill. Skills that parse arxiv/journal links.
3. **Legal documents** — case-law citation parser, jurisdiction tags, per-jurisdiction validators. Skills that recognize case citations.
4. **Childcare / domain-light fixture** (used in spec 022) — probably too thin to warrant a full speciality. Listed for completeness.

**Why this priority**: This IS the promotion trigger. Without a second speciality, this spec stays DESIGN-SPACE. With a second speciality, the plugin interface is extracted with real validation.

**Acceptance Scenarios**:

1. **Given** a concrete second speciality is proposed, **When** the trigger is acknowledged, **Then** this spec promotes from BLOCKED to FULL.
2. **Given** the second speciality is implemented, **When** it ships, **Then** it ACTUALLY uses the plugin contract (no parallel codepath that bypasses the contract).
3. **Given** the second speciality reveals design-space surprises, **When** they surface, **Then** the plugin shape is RESHAPED before being canonical.

---

### User Story 3 — Vaults opt into specialities via `research.spec.md` (Priority: P1, AFTER promotion)

The vault's `research.spec.md` declares its speciality: `vault.speciality: code` (or `recipes`, `papers`, etc.). The scaffolder reads this at install time and copies the appropriate speciality's templates, validators, and skills into the vault. Specialities are NOT auto-detected — explicit operator choice.

**Why this priority**: Discoverability + explicit consent. Users always know what speciality is active.

**Acceptance Scenarios**:

1. **Given** `vault.speciality: code` in the spec, **When** `install.sh` runs, **Then** the code speciality's templates land in `<vault>/specialities/code/`.
2. **Given** no `vault.speciality` key, **When** the install runs, **Then** the vault is generic (no speciality directory).
3. **Given** the operator changes `vault.speciality` mid-vault-life, **When** `./vault update` runs, **Then** the new speciality's templates are added + the previous speciality's are removed (with operator confirmation, since this is a destructive change).

---

### Edge Cases

- What if a speciality's validator conflicts with the generic verifier (e.g. speciality requires a field the generic verifier rejects)? → Per Q2 default (pre-verifier pass), speciality validates first; if it passes a note, the generic verifier sees it; if speciality and generic disagree, generic wins (the verifier is the final arbiter).
- What if a speciality's templates collide with the generic templates (same note-type)? → Speciality wins (the operator opted in). Generic version is unreachable while speciality is active.
- What if the operator deletes the speciality directory manually? → `./vault update` restores it. The speciality contract owns those files; operator edits there are lost.
- What if a speciality is removed from the framework in a future release? → Migration warning at `./vault update`: "speciality 'code' no longer ships in 0.6.0; vault still works but speciality features are degraded".
- What if the second speciality reveals that the proposed `templates/specialities/<name>/` layout is wrong? → Reshape; this spec is design-space, not contract.
- What if 12+ months pass with no second speciality? → This spec stays BLOCKED. Re-evaluate for closure (rule-of-three never triggering = the abstraction wasn't needed).

## Requirements *(mandatory)*

### Functional Requirements *(POST-PROMOTION)*

All FRs below are CONDITIONAL on the rule-of-three trigger firing.

- **FR-001 (post-promotion)**: Specialities MUST live at `templates/specialities/<name>/` in the framework + `<vault>/specialities/<name>/` in the vault.
- **FR-002 (post-promotion)**: Each speciality MUST ship a manifest `templates/specialities/<name>/manifest.yaml` declaring: `name`, `version`, `description`, `templates` (list), `validators` (list), `skills` (list), `spec_questions` (list of additional `research.spec.md` questions to elicit at install).
- **FR-003 (post-promotion)**: `research.spec.md` MUST support a `vault.speciality: <name>` key. Unset → generic vault (no speciality directory). Invalid name → install fails with clear error naming the available specialities.
- **FR-004 (post-promotion)**: At install time, the scaffolder MUST copy the chosen speciality's templates / validators / skills into `<vault>/specialities/<name>/`.
- **FR-005 (post-promotion)**: Speciality templates MUST be USED by the cycle when present (override generic templates with same note-type name). Generic templates are unreachable while speciality is active.
- **FR-006 (post-promotion)**: Per Q2 default, speciality validators run as a PRE-VERIFIER pass. If they reject, the note never reaches the generic verifier. If they pass, generic verifier still votes (final arbiter).
- **FR-007 (post-promotion)**: Per Q1 default, ONE speciality per vault. Multiple-speciality vaults are out of v1.
- **FR-008 (post-promotion)**: Per Q3 default, ALL specialities ship in the framework package (bundled). No out-of-band install steps.
- **FR-009 (post-promotion)**: Per Q4 default, speciality version is framework-version pinned. Specialities evolve with framework releases.
- **FR-010 (post-promotion)**: Spec 002's code-first deliverables MUST migrate to `templates/specialities/code/` per FR-001 layout. Existing code-first vaults work unchanged.
- **FR-011 (post-promotion)**: Spec 002 stays SUBSUMED-by-046 in the spec registry; future code-first improvements are amendments to this spec's "code" speciality, not new code-first specs.
- **FR-012 (post-promotion)**: Changing `vault.speciality` mid-vault-life MUST require operator confirmation (destructive — removes prior speciality's templates).

### Functional Requirements *(PRE-PROMOTION — meta-requirements)*

- **FR-100**: This spec MUST NOT be promoted to IMPLEMENTABLE until the rule-of-three trigger fires (a second concrete speciality ships a real implementation).
- **FR-101**: Any future spec proposing a NEW SPECIALITY MUST reference this spec in its Dependencies block AND must articulate why it's the SECOND (not the first — that's spec 002).
- **FR-102**: This spec's Reuse Candidates (US2) MUST be kept up to date — when a candidate ships, this spec's US2 entry MUST link to that spec.
- **FR-103**: If 12+ months pass with no trigger, this spec MAY be re-evaluated for closure / merge into spec 002 documentation.

### Key Entities

- **`templates/specialities/<name>/` directory** (post-promotion): The on-disk home for a speciality's templates / validators / skills / manifest.
- **`manifest.yaml` per speciality**: Declares the speciality's contributions per FR-002.
- **`vault.speciality` setting in `research.spec.md`**: Operator's explicit choice; drives scaffolder behavior.
- **Speciality validator (pre-verifier pass)**: A Python module under `<vault>/specialities/<name>/validators/`. Runs as a pre-verifier per FR-006.
- **Speciality template**: A Jinja2 template under `<vault>/specialities/<name>/templates/`. Overrides generic templates with the same note-type name.
- **Spec-time questions** (per FR-002 `spec_questions`): Domain-specific questions the install wizard asks (e.g. for `code`: "What's the primary language?"; for `papers`: "What's the citation style?").

## Success Criteria *(mandatory, POST-PROMOTION)*

### Measurable Outcomes

- **SC-001**: After promotion + migration, spec 002's existing tests pass 100% unchanged (FR-010 invariant).
- **SC-002**: The second speciality (whichever ships first from US2's candidates) successfully uses the plugin contract in production.
- **SC-003**: Two distinct vaults (one `code`, one second-speciality) coexist on the same machine without interference.
- **SC-004**: A third speciality (if/when it arrives) can be added by a contributor in <1 week of effort using ONLY this spec's documentation (no parallel-spec hand-holding).
- **SC-005 (pre-promotion)**: This spec stays BLOCKED until US2's trigger fires. 0 attempts to promote prematurely.

## Assumptions

- The proposed on-disk layout (`templates/specialities/<name>/`) is a STARTING POINT — the second speciality informs the final shape.
- The four candidate specialities (recipes, papers, legal, childcare) are illustrative. The actual second speciality may be something entirely different.
- Spec 002 (codebase-vault code-first) is shipped and stable. Migration in FR-010 is refactor, not redesign.
- Bundled-with-framework distribution (per Q3 default) is feasible — specialities are small (few KB each).

## Dependencies

- **Hard (post-promotion)**: Spec 002 (codebase-vault code-first) — the first speciality. Migrated in FR-010.
- **Hard (pre-promotion)**: A SECOND concrete speciality ships — THIS is the promotion trigger.
- **Soft**: Spec 020 (source modules) — speciality SKILLS may use source modules (e.g. recipes speciality uses a recipe-website source module).
- **Soft**: Spec 022 (E2E quality harness v1) — speciality validators need fixture testing.

## Acceptance coverage

**Pre-promotion**: No acceptance coverage. This spec is design-space only.

**Post-promotion**: Acceptance cells populated by `/speckit.tasks` AFTER the rule-of-three trigger fires.

| User Story | Evidence |
|---|---|
| US1 — Code speciality reframed as canonical reference | _(deferred to tasks.md — promotion-gated; not implementable until rule-of-three / dual-trigger fires)_ |
| US2 — Second speciality arrives + validates plugin shape | _(deferred to tasks.md — promotion-gated; not implementable until rule-of-three / dual-trigger fires)_ |
| US3 — Vaults opt into specialities via `research.spec.md` | _(deferred to tasks.md — promotion-gated; not implementable until rule-of-three / dual-trigger fires)_ |

## Out of Scope

- Extracting the plugin interface NOW (premature — rule-of-three).
- Replacing or rewriting spec 002. 046 reframes spec 002 as the reference; spec 002's deliverables stay (just relocated on disk).
- Multi-speciality composition (e.g. "code + recipes in the same vault"). Out of v1 (per Q1).
- LLM-driven speciality detection at install time. v1 is explicit user choice (per US3).
- A marketplace of community-contributed specialities. Out of v1; framework-bundled only.
- Custom-built specialities (operator creates their own speciality in their vault). Out of v1; consider for v2 if real demand surfaces.
- Cross-speciality data sharing (`code` vault references `papers` vault's notes). Out — separate vaults are separate.

---

*This spec is **BLOCKED**. Do not run `/speckit.plan` or `/speckit.tasks` against it until US2's promotion trigger fires (a second concrete speciality ships a real implementation). Until then, this spec is a constraint-preservation document.*
