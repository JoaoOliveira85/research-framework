---
description: "Task list for Speckit v0.1 — Knowledge Vault Generator"
---

# Tasks: Speckit v0.1 — Knowledge Vault Generator

**Input**: Design documents from `/specs/001-speckit-implementation/`
**Prerequisites**: plan.md ✅, spec.md ✅, data-model.md ✅, contracts/ ✅, research.md ✅, quickstart.md ✅

**Tests**: Included — TDD is a constitutional requirement (Principle III). Tests MUST be
written and confirmed failing before implementation begins.

**Organization**: Tasks are grouped by user story to enable independent implementation and
testing of each story.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US4)
- Exact file paths are included in every task description

## Path Conventions

- `src/speckit/` — speckit's own source code
- `scripts/` — vault scripts bundle (deployed into generated vaults)
- `tests/` — test suite (both speckit src and scripts bundle)
- `templates/` — Jinja2 templates for generated vault files
- All tasks assume single-project layout at repository root

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and package skeleton. No user stories can begin until
this phase is complete.

- [X] T001 Create pyproject.toml with hatchling build backend, `[project.scripts]` entry `speckit = "speckit.cli:main"`, runtime dep `jinja2>=3.0`, dev extras `pytest`, `hypothesis`, `black`, `ruff`; configure `[tool.black]` line-length=88, `[tool.ruff]` select=["E","F","I"], `[tool.pytest.ini_options]` testpaths=["tests"]
- [X] T002 [P] Create `src/speckit/__init__.py`, `src/speckit/spec/__init__.py`, `src/speckit/generator/__init__.py`, `src/speckit/pipeline/__init__.py`, `src/speckit/vault/__init__.py` (empty init files to declare packages)
- [X] T003 [P] Create directory skeleton: `tests/spec/`, `tests/generator/`, `tests/pipeline/`, `tests/scripts/`, `tests/fixtures/vault/data_vault/01 - Concepts/`, `tests/fixtures/vault/_templates/`, `tests/fixtures/vault/_pipeline/`, `tests/fixtures/cycle-reports/`, `tests/fixtures/stubs/`, `scripts/`, `templates/note-types/`, `templates/index-files/`

---

## Phase 2: Foundational (Shared Test Fixtures)

**Purpose**: Shared test fixtures used across all user story test suites. Must be complete
before any Phase 3+ tests can be written.

**⚠️ CRITICAL**: No user story test work can begin until these fixtures exist.

- [X] T004 [P] Create `tests/fixtures/vault/_templates/concept.md` — reference template with three required sections: `## Overview`, `## Key Details`, `## Relationships`; this is the compliance baseline for `check_template_compliance.py` tests
- [X] T005 [P] Create `tests/fixtures/vault/data_vault/01 - Concepts/Valid Concept.md` — note passing all quality checks: YAML frontmatter with title, type=concept, summary≤120 chars, tags, source_urls, related; body 200+ words with first acronym occurrence wikilinked; all three required sections present
- [X] T006 [P] Create `tests/fixtures/vault/data_vault/01 - Concepts/Long Summary Concept.md` — identical to Valid Concept except summary is exactly 125 chars; this is the summary overflow fixture (F4 failure mode)
- [X] T007 [P] Create `tests/fixtures/vault/data_vault/01 - Concepts/Missing Source.md` — identical to Valid Concept except `source_urls: []` (empty list); single failure mode: missing source
- [X] T008 [P] Create `tests/fixtures/vault/data_vault/01 - Concepts/Missing Section.md` — note with valid frontmatter but body missing the `## Relationships` section; single failure mode: template non-compliance
- [X] T009 [P] Create `tests/fixtures/vault/data_vault/01 - Concepts/Unlinked Acronym (UA).md` — note containing "UA" in body without `[[UA]]` wikilink on first occurrence; acronym title contains "(UA)" so it registers in acronym list; single failure mode
- [X] T010 [P] Create `tests/fixtures/cycle-reports/valid-scout.json` — valid BFS scout with all five dimensions covered (`technical`, `organizational`, `domain`, `market`, `temporal`), at least one external source in `sources_consulted`, `termination_condition: null`, `new_topics: ["Topic A", "Topic B"]`
- [X] T011 [P] Create `tests/fixtures/cycle-reports/invalid-scout-missing-dimension.json` — scout JSON identical to valid-scout except `dimensions_covered` omits `"market"`; single failure mode for dimension check
- [X] T012 [P] Create `tests/fixtures/cycle-reports/valid-research.json` — valid DFS research report with `phase: "research"`, `notes_created`, `unresolved_wikilinks: []`, `termination_condition: null`; used for cycle validate tests
- [X] T013 [P] Create `tests/fixtures/vault/_pipeline/coverage-targets.json` — sample coverage targets with two categories: `concepts` (target: 5, met: 3) and `services` (target: 3, met: 3); used to test `all_targets_met` returns False when one unmet
- [X] T014 Create `tests/conftest.py` — shared pytest fixtures: `vault_dir` returning `Path` to `tests/fixtures/vault/`, `tmp_vault_dir` returning a `tmp_path`-based copy for write tests, `sample_spec` returning parsed SpecConfig from `tests/fixtures/sample-spec.md`
- [X] T015 [P] Create `tests/fixtures/stubs/claude` — executable Python stub script that accepts `--prompt` arg and writes a canned valid cycle JSON to stdout; used by orchestrator tests to avoid real claude CLI dependency; `chmod +x`

**Checkpoint**: Fixtures and conftest ready — user story test work can begin in parallel

---

## Phase 3: User Story 1 — Validate an existing vault (Priority: P1)

**Goal**: Five validation scripts (`validate_vault.py`, `check_template_compliance.py`,
`check_acronym_links.py`, `vault_metrics.py`) and two fix scripts exist as working,
tested implementations. Codebase vault can run them immediately.

**Independent Test**: `pytest tests/scripts/ -v` passes with 0 failures. Running
`python scripts/validate_vault.py tests/fixtures/vault/` exits 1 and reports exactly 4
violations (long summary, missing source, missing section, unlinked acronym).

### Tests for User Story 1 ⚠️ Write FIRST — must fail before implementation

> **TDD gate**: Run `pytest tests/scripts/test_validate_vault.py` — confirm it errors with
> `ModuleNotFoundError` or `FileNotFoundError` before writing any implementation.

- [X] T016 [P] [US1] Create `tests/scripts/test_validate_vault.py` — test cases: valid note → exit 0 and "all checks passed"; missing `source_urls` → exit 1 with file path and field name in output; summary 125 chars → exit 1 with char count; broken `[[wikilink]]` → exit 1 with link target; `--dry-run` flag → exits 0 and modifies no files (assert mtime unchanged); vault dir not found → exit 2
- [X] T017 [P] [US1] Create `tests/scripts/test_check_template_compliance.py` — test cases: compliant note (all sections present) → exit 0; note missing `## Relationships` → exit 1 naming the section; note with unknown type (no template file) → exit 1; `_templates/` directory missing → exit 2
- [X] T018 [P] [US1] Create `tests/scripts/test_check_acronym_links.py` — test cases: wikilinked acronym (valid fixture) → exit 0; unlinked first occurrence (UA fixture) → exit 1 naming file + acronym; acronym appearing only inside code fence → exit 0 (skip); acronym in URL → exit 0 (skip)
- [X] T019 [P] [US1] Create `tests/scripts/test_vault_metrics.py` — test cases: JSON output contains `note_count`, `by_type`, `word_count_buckets`, `unresolved_wikilinks` keys; note count matches actual fixture files; `--output path` writes file; stdout JSON is valid JSON; exit always 0

### Implementation for User Story 1

- [X] T020 [US1] Implement `scripts/validate_vault.py` — scan all `.md` files in `data_vault/` recursively; parse YAML frontmatter (pyyaml); for each note: check title, type, summary≤120, tags≥1, source_urls≥1, related wikilinks resolve to existing files, word count≥200 for non-MOC; print `FAIL {filepath}\n      {field}: {reason}` per violation; print summary count; exit 0 (none), 1 (violations), 2 (parse error or vault not found)
- [X] T021 [P] [US1] Implement `scripts/check_template_compliance.py` — for each note in `data_vault/`: read its `type` from frontmatter; load `_templates/{type}.md`; extract section headings (lines starting with `##`); compare to note's headings; report missing sections; exit 0 (all compliant), 1 (missing sections), 2 (template missing or vault not found)
- [X] T022 [P] [US1] Implement `scripts/check_acronym_links.py` — build acronym list: scan all note titles for parenthetical abbreviations `Name (ABBR)` patterns; for each note body: find first occurrence of each acronym not inside `` ` ``code blocks``, URLs, or existing `[[wikilinks]]`; report unlinked occurrences with file path + acronym; exit 0/1/2
- [X] T023 [P] [US1] Implement `scripts/vault_metrics.py` — count notes by folder and type; compute word count distribution (buckets: <200, 200-500, 500-1000, 1000+); count `[[wikilinks]]` that resolve vs. unresolved; output JSON dict to stdout (or `--output path`); accept optional `--vault-dir` arg (default: current directory); exit always 0
- [X] T024 [US1] Implement `scripts/fix_acronym_links.py` — accept `--vault-dir` and `--dry-run`/`--apply` flags; `--dry-run` (default): print diff of proposed changes without modifying files; `--apply`: write changes and re-run `check_acronym_links.py` to confirm 0 violations; refuse to write if `--apply` not explicitly passed; exit 0/1/2
- [X] T025 [P] [US1] Implement `scripts/fix_wikilinks.py` — same pattern as `fix_acronym_links.py`: find broken `[[wikilinks]]` (from validate_vault.py related-field output); `--dry-run` prints proposed fixes; `--apply` writes; re-validates after apply; exit 0/1/2

**Checkpoint**: `pytest tests/scripts/ -k "vault or template or acronym or metrics" -v` passes. Running scripts directly against `tests/fixtures/vault/` produces expected output.

---

## Phase 4: User Story 2 — Validate a BFS scout cycle report (Priority: P1)

**Goal**: `validate_cycle.py` and `run_cycle.sh` exist as working, tested implementations.
Pipeline can validate scout and research JSON reports and drive a full BFS→DFS cycle.

**Independent Test**: `pytest tests/scripts/test_validate_cycle.py -v` passes. Running
`python scripts/validate_cycle.py tests/fixtures/cycle-reports/valid-scout.json` exits 0.
Running with the missing-dimension fixture exits 2 naming "market".

### Tests for User Story 2 ⚠️ Write FIRST — must fail before implementation

- [X] T026 [P] [US2] Create `tests/scripts/test_validate_cycle.py` — test cases: valid scout JSON → exit 0; scout missing "market" dimension → exit 2 with "market" in output; scout with all Condition B sub-conditions true → exit 1 (TERMINATE); scout with any false Condition B sub-condition → exit 0 (CONTINUE); `proposed_filenames` collision with existing vault file → exit 2; `sources_consulted` has no external source → exit 2; malformed JSON → exit 2; research phase with valid JSON → exit 0

### Implementation for User Story 2

- [X] T027 [US2] Implement `scripts/validate_cycle.py` — parse cycle JSON file; validate required fields present; for `phase == "scout"`: verify all five dimensions in `dimensions_covered`; check `proposed_filenames` do not collide with existing files in `data_vault/`; verify at least one external source in `sources_consulted`; evaluate Condition B: all sub-conditions (0 new_topics, 0 unresolved_wikilinks, 5 dimensions, required sources consulted, optional Jira targets, ≥1 external source); exit 0 (CONTINUE), 1 (TERMINATE — all Condition B true), 2 (structural abort)
- [X] T028 [US2] Implement `scripts/run_cycle.sh` — `set -euo pipefail`; accept positional args `$1=cycle_num $2=vault_dir $3=max_cycles $4=budget_cap`; execute in sequence: (1) `python scripts/vault_metrics.py --output "_pipeline/cycles/cycle-$1-pre.json"`, (2) `claude` with scout prompt → cycle JSON, (3) `python scripts/validate_cycle.py ... || exit $?`, (4) `claude` with DFS prompt → research JSON, (5) `python scripts/validate_vault.py && python scripts/check_template_compliance.py && python scripts/check_acronym_links.py`, (6) `python scripts/validate_cycle.py ...|| exit $?`, (7) `python scripts/vault_metrics.py --output "_pipeline/cycles/cycle-$1-post.json"

**Checkpoint**: US1 and US2 complete — codebase vault can now run the full validation suite and cycle validation immediately.

---

## Phase 5: User Story 3 — Generate a new vault from a spec file (Priority: P2)

**Goal**: `speckit generate --spec vault-spec.md --dry-run` produces a fully-structured
vault skeleton matching the spec. The generated vault passes the Phase 1 pytest gate.

**Independent Test**: `speckit generate --spec tests/fixtures/sample-spec.md --dry-run`
exits 0, vault directory created, `pytest scripts/tests/` passes inside it, CLAUDE.md
contains the spec name (not template boilerplate), coverage-targets.json has correct targets.

### Tests for User Story 3 ⚠️ Write FIRST — must fail before implementation

- [X] T029 [P] [US3] Create `tests/spec/test_parser.py` — test cases: valid spec YAML → SpecConfig with correct field values; YAML parse error → SpecValidationError with line reference; missing `name` field → SpecValidationError naming "name"; `search_dimensions` without "domain" → SpecValidationError naming "search_dimensions"
- [X] T030 [P] [US3] Create `tests/spec/test_validator.py` — hypothesis: `@given(valid_spec_strategy())` always parses without exception; `@given(spec_missing_field_strategy())` always raises SpecValidationError and error message contains the missing field name; no `NEEDS CLARIFICATION` strings in any SpecConfig field after parse
- [X] T031 [P] [US3] Create `tests/generator/test_scaffold.py` — test cases: scaffold creates `data_vault/{folder}/` for each NoteTypeConfig; `_pipeline/` created with `budget-log.md`, `research-backlog.md`, `coverage-targets.json`; `coverage-targets.json` has one entry per CoverageCategory; `spec-parse.json` written and deserializes to equivalent SpecConfig
- [X] T032 [P] [US3] Create `tests/generator/test_templates.py` — snapshot test: render CLAUDE.md.j2 with sample SpecConfig and assert spec name appears in output (not `[PROJECT NAME]`); assert note type names appear; render concept.md.j2 and assert required sections appear; snapshot stored in `tests/fixtures/snapshots/`

### Data Models and Fixtures

- [X] T033 [US3] Implement `src/speckit/spec/schema.py` — all dataclasses with type hints: `SpecConfig`, `ScopeConfig`, `NoteTypeConfig`, `DataSourceConfig`, `CoverageTargets`, `CoverageCategory`, `BudgetConfig`; each with `to_dict() → dict` and `@classmethod from_dict(cls, d: dict) → Self`; `SpecValidationError(Exception)` with `field: str` attribute
- [X] T034 [P] [US3] Create `vault-spec-template.md` at repository root — canonical YAML-fronted Markdown format documenting all SpecConfig fields with comments and example values; this is the user-facing spec authoring guide
- [X] T035 [P] [US3] Create `tests/fixtures/sample-spec.md` — minimal valid vault spec: 1 note type (concept), 2 data sources (1 internal Confluence, 1 external web), both "domain" and "market" in search_dimensions, 2 coverage categories, budget $5, max_cycles 2; named "Test Vault" with location pointing to a temp directory

### Generator Implementation

- [X] T036 [US3] Implement `src/speckit/spec/parser.py` — split input file on `---` delimiters to extract YAML block; parse with `yaml.safe_load`; map dict to SpecConfig via `SpecConfig.from_dict()`; raise `SpecValidationError` (exit 2) on YAML parse failure (include line number) or on unmapped required fields; return `SpecConfig`
- [X] T037 [US3] Implement `src/speckit/spec/validator.py` — `validate(spec: SpecConfig) → None`; check: name non-empty, location valid path expression, owner non-empty, search_dimensions contains "domain" and "market", note_types ≥ 1, data_sources ≥ 1, coverage_targets ≥ 1; for each violation, collect error message; raise `SpecValidationError` with all violations if any found; caller prints one line per message
- [X] T038 [US3] Implement `src/speckit/generator/scaffold.py` — `scaffold(spec: SpecConfig, vault_dir: Path) → None`; create `vault_dir`; create `data_vault/{nt.folder}/` for each NoteTypeConfig; create `_templates/`; create `_pipeline/` with empty `budget-log.md`, empty `research-backlog.md`, skeleton `coverage-targets.json` (all met_count=0), `spec-parse.json` (serialized SpecConfig)
- [X] T039 [P] [US3] Create all base Jinja2 templates in `templates/` — `CLAUDE.md.j2` (includes spec.name, spec.scope, note types list, data sources, quality bar, naming convention), `AGENTS.md.j2` (folder structure skeleton), `README.md.j2`, `vault-config.yaml.j2`, `query-command.md.j2`, `add-command.md.j2`; all templates use `{{ spec.name }}`, `{{ spec.owner }}` etc.
- [X] T040 [P] [US3] Create note-type Jinja2 templates in `templates/note-types/` — `concept.md.j2`, `service.md.j2`, `flow.md.j2`, `product.md.j2`, `team.md.j2`, `decision.md.j2`, `risk.md.j2`, `process.md.j2`, `market.md.j2`, `source.md.j2`; each template loops over `note_type.required_sections` to generate section headings and lists `note_type.contextual_questions` as guidance comments
- [X] T041 [P] [US3] Create index file Jinja2 templates in `templates/index-files/` — `_index.md.j2` (flat list skeleton), `_concepts.md.j2` (alphabetical index skeleton), `_graph.md.j2` (wikilink adjacency skeleton); all render with `spec.name` and timestamp
- [X] T042 [US3] Implement `src/speckit/generator/templates.py` — `render_all(spec: SpecConfig, vault_dir: Path) → None`; set up Jinja2 `Environment(loader=FileSystemLoader(templates_dir))`; render each base template → write to vault_dir; render one note template per NoteTypeConfig → write to `{vault_dir}/_templates/{nt.name}.md`; render index files → write to vault_dir; raise on undefined template variable
- [X] T043 [US3] Implement `src/speckit/generator/scripts.py` — `copy_scripts(vault_dir: Path) → None`; use `shutil.copytree` to copy speckit's `scripts/` directory verbatim into `{vault_dir}/scripts/`; verify destination file count matches source; raise if any file is missing after copy
- [X] T044 [US3] Implement `src/speckit/cli.py` — `argparse` with `generate` sub-command; flags: `--spec PATH`, `--output PATH`, `--dry-run`; Phase 0: call `parser.parse(spec_path)` then `validator.validate(spec)` — exit 2 on any error; Phase 1: call `scaffold.scaffold()`, `templates.render_all()`, `scripts.copy_scripts()`; run `pytest scripts/tests/ -v` via subprocess — `sys.exit("Phase 1 gate failed")` on non-zero return; `--dry-run` exits after Phase 1; Phase 2/3 stubs print "Phase N not yet implemented"; main entry point `cli.py:main`

**Checkpoint**: `speckit generate --spec tests/fixtures/sample-spec.md --dry-run` exits 0 and the generated vault directory has all expected files. `pytest tests/spec/ tests/generator/ -v` passes.

---

## Phase 6: User Story 4 — Resume Phase 2 research on an existing vault (Priority: P3)

**Goal**: `speckit generate --resume` checks preconditions on an existing vault and can
drive a new research cycle. `speckit coverage` shows accurate target status.

**Independent Test**: `speckit generate --spec codebase-vault-spec.md --resume` on the
existing codebase vault reports each unmet precondition by name. `speckit coverage --vault
~/Documents/codebase-vault` shows which categories are unmet and the Phase 3 gate status.

### Tests for User Story 4 ⚠️ Write FIRST — must fail before implementation

- [X] T045 [P] [US4] Create `tests/pipeline/test_preconditions.py` — test cases: all 5 conditions met → returns True; pytest fails in vault → condition 1 unmet in report; validate_vault.py exits 1 → condition 2 unmet; coverage-targets.json missing → condition 3 unmet; budget-log.md missing → condition 4 unmet; CLAUDE.md missing naming convention → condition 5 unmet; output message names the specific unmet condition
- [X] T046 [P] [US4] Create `tests/pipeline/test_coverage.py` — test cases: `load_targets` parses valid JSON → CoverageTargets with correct counts; `update_after_cycle` increments met_count for matching categories; `all_targets_met` returns True only when all met_count ≥ target_count; `unmet_targets` returns list of category names where gap > 0; malformed JSON → exits 2; `update_after_cycle` writes atomically (no partial write on exception)

### Implementation for User Story 4

- [X] T047 [US4] Implement `src/speckit/pipeline/preconditions.py` — `check(vault_dir: Path) → tuple[bool, list[str]]`; check 5 conditions: (1) `subprocess.run(["pytest", "scripts/tests/"], cwd=vault_dir)` exits 0; (2) `subprocess.run(["python", "scripts/validate_vault.py", str(vault_dir)])` exits 0; (3) `(vault_dir / "_pipeline/coverage-targets.json").exists()` and valid JSON; (4) `(vault_dir / "_pipeline/budget-log.md").exists()`; (5) `(vault_dir / "CLAUDE.md").exists()` and contains naming convention declaration; return (all_pass, list of unmet condition descriptions)
- [X] T048 [US4] Implement `src/speckit/pipeline/coverage.py` — `load_targets(vault_dir: Path) → CoverageTargets`; `update_after_cycle(vault_dir: Path, research_report: dict) → None` (increment met_count per notes_created type, write atomically via temp file + rename); `all_targets_met(vault_dir: Path) → bool`; `unmet_targets(vault_dir: Path) → list[str]`; validate JSON schema on load; raise exit-code-2 error on malformed
- [X] T049 [US4] Implement `src/speckit/pipeline/orchestrator.py` — `run_cycles(spec: SpecConfig, vault_dir: Path, start_cycle: int = 1) → int`; before each cycle: check budget remaining vs. consumed; call `subprocess.run(["bash", "scripts/run_cycle.sh", cycle_num, vault_dir, max_cycles, budget_cap])`; read exit code: 0=CONTINUE (loop), 1=TERMINATE (check coverage), 2=ABORT (exit); on TERMINATE: call `coverage.all_targets_met()`; if not all met: print `coverage.unmet_targets()` + re-entry instructions, return exit code 1; if all met: proceed to Phase 3; do NOT ask agent to self-assess
- [X] T050 [P] [US4] Implement `src/speckit/pipeline/reporter.py` — `generate_report(vault_dir: Path) → Path`; read all `_pipeline/cycles/cycle-*-scout.json` and `cycle-*-research.json`; read `_pipeline/coverage-targets.json`; read `_pipeline/budget-log.md`; write `_pipeline/phase1-report.md` with sections: Cycles Summary (count, notes per cycle), Coverage Status (met/total per category), Budget Used, Validation Outcomes; return path to report
- [X] T051 [US4] Implement `src/speckit/vault/indexer.py` — `rebuild(vault_dir: Path) → None`; scan `data_vault/**/*.md` recursively; parse YAML frontmatter; build `_index.md` (flat list per folder: `- [[title]] — {summary}`); build `_concepts.md` (alphabetical for type=concept); build `_graph.md` (adjacency list from `related` fields — do not infer, only read declared links); update AGENTS.md topic index section with note counts per type; write all four files; full rebuild (not incremental)
- [X] T052 [P] [US4] Implement `src/speckit/vault/metrics.py` — `collect(vault_dir: Path) → VaultMetrics`; `VaultMetrics` dataclass with fields: `note_count: int`, `by_type: dict[str, int]`, `word_count_buckets: dict[str, int]`, `unresolved_wikilinks: int`, `timestamp: str`; equivalent to `scripts/vault_metrics.py` but as importable Python module
- [X] T053 [US4] Extend `src/speckit/cli.py` — add `--resume` flag to `generate` (skip Phase 0/1, call `preconditions.check()`, exit 1 with report if any unmet, enter `orchestrator.run_cycles()`); add `speckit coverage` sub-command (`--vault` arg, calls `coverage.load_targets()`, prints table, exits 0 if all met else 1); add `speckit validate` sub-command (calls all four validation scripts via subprocess, aggregates exit codes); add `speckit reindex` sub-command (calls `indexer.rebuild()`, `--dry-run` flag); add `speckit cycle` sub-command (single cycle, `--vault`, `--cycle N`, `--budget-cap`); Phase 3 sequence in full generate: coverage gate → `indexer.rebuild()` → `git init` + first commit → `reporter.generate_report()`

**Checkpoint**: All user stories complete. `speckit generate --spec tests/fixtures/sample-spec.md` runs end-to-end. `speckit generate --spec codebase-vault-spec.md --resume` shows precondition report.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Quality enforcement, integration verification, and regression baselines.

- [X] T054 [P] Format all source files: run `black src/ scripts/ tests/` and `ruff check src/ scripts/ --fix`; resolve all violations; confirm `black --check` and `ruff check --no-fix` both exit 0
- [X] T055 Create `tests/generator/test_integration.py` — end-to-end test: call `speckit generate --spec tests/fixtures/sample-spec.md --dry-run` via subprocess; assert exit 0; assert expected directories exist; assert `pytest scripts/tests/ -v` passes inside generated vault; assert `CLAUDE.md` contains spec name "Test Vault"; assert `coverage-targets.json` has 2 entries (matching sample spec)
- [X] T056 [P] Run `python scripts/validate_vault.py ~/Documents/codebase-vault` against the live codebase vault; capture output; write known violation list to `tests/fixtures/codebase-vault-baseline-violations.json`; this baseline is used in future regression tests to confirm validate_vault.py consistently catches the same violations
- [X] T057 Add exit-code contract assertions to `tests/scripts/` — for each of the 7 scripts in `scripts/`: assert `--dry-run` flag exits 0 and no file mtime changes; assert passing input exits 0; assert violation input exits 1; assert structural error input exits 2; this enforces the 0/1/2 contract across all scripts

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 completion — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Phase 2 — no dependency on US2, US3, US4
- **US2 (Phase 4)**: Depends on Phase 2 — no dependency on US1 (but can start in parallel with US1)
- **US3 (Phase 5)**: Depends on Phase 2 — requires US1 scripts to be available for the Phase 1 gate test
- **US4 (Phase 6)**: Depends on US3 (CLI and generator infrastructure required)
- **Polish (Phase 7)**: Depends on all user stories complete

### User Story Dependencies

- **US1 (P1)**: Can start after Foundational — independently testable
- **US2 (P1)**: Can start after Foundational — independently testable; can run in parallel with US1
- **US3 (P2)**: Can start after Foundational; uses US1 scripts in Phase 1 gate test
- **US4 (P3)**: Depends on US3 CLI infrastructure; cannot start until US3 complete

### Within Each User Story

- Tests MUST be written and confirmed failing before implementation (TDD — constitution III)
- schema.py before parser.py before validator.py (US3)
- scaffold.py + templates.py + scripts.py before cli.py (US3)
- preconditions.py + coverage.py before orchestrator.py (US4)
- indexer.py before Phase 3 sequence in cli.py (US4)

---

## Parallel Opportunities

### Phase 2 — Fixture creation (all T004–T015 parallel)

```bash
# All fixture files can be created simultaneously (different files, no dependencies)
Task: "Create tests/fixtures/vault/_templates/concept.md"         # T004
Task: "Create Valid Concept.md fixture"                           # T005
Task: "Create Long Summary Concept.md fixture"                    # T006
Task: "Create Missing Source.md fixture"                          # T007
Task: "Create Missing Section.md fixture"                         # T008
Task: "Create Unlinked Acronym (UA).md fixture"                   # T009
Task: "Create valid-scout.json fixture"                           # T010
Task: "Create invalid-scout-missing-dimension.json fixture"       # T011
Task: "Create valid-research.json fixture"                        # T012
Task: "Create coverage-targets.json fixture"                      # T013
Task: "Create tests/fixtures/stubs/claude"                        # T015
```

### Phase 3 (US1) — Tests in parallel, then scripts in parallel

```bash
# Tests (all parallel — different files):
Task: "Create tests/scripts/test_validate_vault.py"               # T016
Task: "Create tests/scripts/test_check_template_compliance.py"    # T017
Task: "Create tests/scripts/test_check_acronym_links.py"          # T018
Task: "Create tests/scripts/test_vault_metrics.py"                # T019

# Implementation (check_* scripts parallel after validate_vault.py):
Task: "Implement scripts/check_template_compliance.py"            # T021
Task: "Implement scripts/check_acronym_links.py"                  # T022
Task: "Implement scripts/vault_metrics.py"                        # T023
Task: "Implement scripts/fix_wikilinks.py"                        # T025
```

### Phase 5 (US3) — Templates and fixtures parallel

```bash
# All Jinja2 template creation in parallel:
Task: "Create base Jinja2 templates in templates/"                # T039
Task: "Create note-type Jinja2 templates"                         # T040
Task: "Create index file Jinja2 templates"                        # T041
Task: "Create vault-spec-template.md"                             # T034
Task: "Create tests/fixtures/sample-spec.md"                      # T035
```

---

## Implementation Strategy

### MVP First (US1 + US2 Only — v0.1)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational fixtures
3. Complete Phase 3: US1 (vault validation scripts)
4. **STOP and VALIDATE**: `pytest tests/scripts/ -v` passes; scripts work on codebase vault
5. Complete Phase 4: US2 (cycle report validation + run_cycle.sh)
6. **STOP and VALIDATE**: Full validation suite works end-to-end

This delivers the v0.1 milestone: codebase vault can run all validation scripts immediately.

### Incremental Delivery

1. v0.1: US1 + US2 complete → codebase vault Phase 1 unblocked
2. v0.2: US3 complete → `speckit generate` works for new vaults
3. v0.3: US4 complete → `speckit generate --resume` enables Cycle 3
4. v1.0: Phase 7 (polish + integration test) → end-to-end generation certified

---

## Notes

- `[P]` tasks use different files with no inter-task dependencies
- `[US?]` label maps task to user story for traceability
- Each user story is independently completable and testable
- TDD: confirm tests fail before writing implementation (constitution principle III)
- `--dry-run` flag is required on every script that writes to vault files (constitution Never #4)
- Stop at checkpoints to validate story independently before proceeding
- Avoid: same-file conflicts between parallel tasks, cross-story implementation dependencies
