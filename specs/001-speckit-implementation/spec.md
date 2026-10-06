# Feature Specification: Speckit — Knowledge Vault Generator

**Feature Branch**: `001-speckit-implementation`
**Created**: 2026-04-16
**Status**: Active
**Input**: Implementation plan v1.0.0 authored by João Pedro Oliveira

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Validate an existing vault (Priority: P1)

A developer or agent has a knowledge vault with notes that may violate the quality bar
(missing frontmatter fields, summaries over 120 chars, unlinked acronyms, missing template
sections). They want to run a validation suite and get a structured error report.

**Why this priority**: Unblocks the codebase vault Phase 1 completion immediately. The
validation scripts are the highest-leverage deliverable because they gate Phase 2.

**Independent Test**: Run `validate_vault.py tests/fixtures/vault/` — receives a report
with exactly the known violations in the fixture notes and exit code 1.

**Acceptance Scenarios**:

1. **Given** a vault with a note missing `source_urls`, **When** `validate_vault.py` runs,
   **Then** exit code 1 and the file path + field name are reported.
2. **Given** a vault with a note whose summary is 125 chars, **When** `validate_vault.py`
   runs, **Then** exit code 1 and the exact field and length are reported.
3. **Given** a vault where all notes pass all checks, **When** `validate_vault.py` runs,
   **Then** exit code 0 and "all checks passed" message.

---

### User Story 2 — Validate a BFS scout cycle report (Priority: P1)

After a research agent produces a scout JSON, the pipeline needs to validate it covers all
five search dimensions, uses correct naming, and is structurally sound before DFS begins.

**Why this priority**: Shares P1 priority with US1 — both are pre-Phase 2 gates that the
codebase vault needs immediately.

**Independent Test**: Run `validate_cycle.py tests/fixtures/cycle-reports/valid-scout.json`
— exit 0. Run with missing-dimension fixture — exit 2.

**Acceptance Scenarios**:

1. **Given** a scout JSON missing the "market" dimension, **When** `validate_cycle.py`
   runs, **Then** exit code 2 and names the missing dimension.
2. **Given** a scout JSON where all Condition B sub-conditions are false, **When**
   `validate_cycle.py` runs, **Then** exit code 0 (CONTINUE).
3. **Given** a scout JSON where all Condition B sub-conditions are true, **When**
   `validate_cycle.py` runs, **Then** exit code 1 (TERMINATE).

---

### User Story 3 — Generate a new vault from a spec file (Priority: P2)

A user creates a `vault-spec.md` file describing their knowledge domain and runs
`speckit generate --spec vault-spec.md`. Speckit creates a fully-structured vault with
correct folder layout, rendered templates, copied scripts, and validated infrastructure.

**Why this priority**: Enables new vaults. Depends on US1/US2 scripts being ready. The
codebase vault is the integration test.

**Independent Test**: Run `speckit generate --spec tests/fixtures/sample-spec.md --dry-run`
— vault directory created, `pytest scripts/tests/` passes inside it.

**Acceptance Scenarios**:

1. **Given** a valid spec file, **When** `speckit generate --spec ...` runs,
   **Then** vault directory created with correct folder structure per spec.
2. **Given** spec has invalid YAML or missing required fields, **When** `speckit generate`
   runs, **Then** exit code 2 and each missing field named on a separate line.
3. **Given** a generated vault where a script test fails, **When** Phase 1 gate runs,
   **Then** the generator stops, names the failing tests, and exits before Phase 2.

---

### User Story 4 — Resume Phase 2 research on an existing vault (Priority: P3)

A vault was partially built. The user runs `speckit generate --resume` to check
preconditions and drive another research cycle, or get a clear report of what's blocking.

**Why this priority**: Enables the codebase vault Cycle 3 (targeted external sources).
Depends on US3.

**Independent Test**: Run `speckit generate --spec codebase-vault-spec.md --resume` on the
existing codebase vault — receives a preconditions report with exact unmet conditions.

**Acceptance Scenarios**:

1. **Given** a vault where coverage targets are unmet, **When** `speckit generate --resume`
   runs, **Then** shows which categories are missing and does NOT proceed to Phase 3.
2. **Given** all preconditions pass, **When** `speckit generate --resume` runs,
   **Then** enters a new research cycle.

---

### Edge Cases

- What happens when `speckit generate` is run on a directory that already has vault content?
  → Spec parser detects existing vault; `--resume` flag required; plain generate refuses.
- How does the system handle `run_cycle.sh` if `claude` CLI is not installed?
  → Precondition check catches this; orchestrator does not proceed.
- What if two notes are proposed with the same filename during DFS?
  → `proposed_filenames` coordination enforced; second write is blocked and logged.
- What if `coverage-targets.json` is malformed after a failed cycle?
  → `coverage.py` validates on load; reports parse error and exits with code 2.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST validate vault notes against a quality bar (200+ words,
  frontmatter completeness, summary ≤ 120 chars, source URLs, wikilinks).
- **FR-002**: The system MUST validate BFS scout reports against the five search dimensions.
- **FR-003**: The system MUST enforce Phase 2 cannot begin until `pytest scripts/tests/`
  passes (exit 0).
- **FR-004**: The system MUST parse `vault-spec.md` files and raise `SpecValidationError`
  with field-level errors on invalid input.
- **FR-005**: The system MUST generate a vault directory structure matching the spec.
- **FR-006**: The system MUST render Jinja2 templates with spec-derived values (not
  boilerplate) for CLAUDE.md, AGENTS.md, note templates, and command files.
- **FR-007**: The system MUST copy the scripts bundle into generated vaults verbatim.
- **FR-008**: The system MUST track coverage targets in `coverage-targets.json` and block
  Phase 3 until all targets are met.
- **FR-009**: The system MUST rebuild Layer 1 index files (`_index.md`, `_concepts.md`,
  `_graph.md`) in Phase 3 from Layer 2 note content.
- **FR-010**: The system MUST run `git init` and create the first commit in Phase 3.
- **FR-011**: All scripts that modify vault files MUST support `--dry-run` mode.
- **FR-012**: The system MUST operate fully offline. No network calls at runtime.

### Key Entities

- **SpecConfig**: The parsed, validated vault specification — drives all generation decisions.
- **CoverageTargets**: Tracks required vs. met note counts per category; Phase 3 gate.
- **CycleReport**: JSON output from each BFS or DFS pass; validated by `validate_cycle.py`.
- **VaultNote**: A single Markdown note with YAML frontmatter; validated by
  `validate_vault.py`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `pytest scripts/tests/ -v` passes with 0 failures after v0.1 ships.
- **SC-002**: Running `validate_vault.py` on the codebase vault produces a specific,
  enumerable list of violations (not "no errors" — the vault has real issues that should
  be caught).
- **SC-003**: `speckit generate --spec sample-spec.md --dry-run` completes in under 30s
  on a cold machine.
- **SC-004**: `speckit generate --spec codebase-vault-spec.md` produces a vault structurally
  identical to the current codebase vault root (minus content).
- **SC-005**: The generated vault passes `speckit validate` with 0 errors after Phase 3.

## Assumptions

- Python 3.11+ is available on the target machine.
- `pytest`, `black`, and `ruff` are installed in the development environment.
- The `claude` CLI is installed and authenticated for Phase 2 orchestration.
- The codebase vault exists at `~/Documents/codebase-vault` and serves as the primary
  integration fixture.
- `jinja2` is the only acceptable additional runtime dependency at v1.0.
- The MCP server (v2.0) is a separate Java/Spring Boot repository — not part of this spec.
