# Implementation Plan: Speckit v0.1 — Knowledge Vault Generator

**Branch**: `001-speckit-implementation` | **Date**: 2026-04-16 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-speckit-implementation/spec.md`

This plan is subordinate to `speckit-constitution.md`. Where they conflict, the constitution
wins. This plan can change; the constitution requires an ADR.

## Summary

Speckit is a Python CLI that reads a vault spec file and produces a populated, validated,
git-initialized Obsidian-compatible knowledge vault. It exists because the codebase vault
build demonstrated what happens when this process is done manually: scripts that never get
implemented, validation that only happens in the agent's head, 157 notes produced with unmet
coverage targets, and 8 documented failure modes.

Build order is driven by value to the codebase vault, not implementation elegance: validation
scripts first (v0.1), then the generator (v0.2), then cycle orchestration (v0.3), then
full end-to-end generation (v1.0).

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: Jinja2 (template rendering only); stdlib for everything else
**Storage**: Files (vault notes as Markdown + YAML frontmatter, JSON cycle reports,
`coverage-targets.json`, `budget-log.md`)
**Testing**: pytest
**Target Platform**: macOS / Linux (offline-capable; no network at runtime)
**Project Type**: CLI tool — single project, `src/speckit/` layout
**Performance Goals**: N/A — process-bound, not latency-sensitive; target <30s cold start
**Constraints**: Offline-capable; no external runtime deps beyond Jinja2; black 88-char;
type hints required on all public functions
**Scale/Scope**: Single user; vaults of 50–500 notes; up to 10 research cycles per vault

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principle | Status | Notes |
|---|-----------|--------|-------|
| I | Script-Validated Quality Gates | ✅ PASS | pytest gate enforced in `cli.py` as hard exit; all 9 gates listed with implementing scripts |
| II | Phase Sequencing | ✅ PASS | Phases 0→1→2→3 strictly sequential; TERMINATE ≠ coverage met |
| III | Test-First (TDD) | ✅ PASS | Tests required before/alongside every script; `--dry-run` required on all write-path scripts |
| IV | Agent-Script Separation | ✅ PASS | Orchestrator reads only script exit codes; never asks agent to self-assess |
| V | Offline-First | ✅ PASS | Only Jinja2 added; no network calls at runtime; no telemetry |
| VI | No Duplicate Notes | ✅ PASS | `proposed_filenames` from scout JSON; parallel DFS agents get non-overlapping topic lists |
| VII | External Sources Mandatory | ✅ PASS | Condition B sub-conditions explicitly require external source consultation |
| VIII | No Placeholders | ✅ PASS | Plan explicitly states every script must have working implementation code |

**Violations**: None. Plan is constitution-compliant.

*Post-Phase 1 re-check*: ✅ PASS — data model, contracts, and component design all
consistent with constitution principles. `SpecValidationError` on parse failure (not
silent). `--dry-run` on both fix scripts. No self-assessment path in orchestrator.

## Project Structure

### Documentation (this feature)

```text
specs/001-speckit-implementation/
├── plan.md              # This file
├── spec.md              # Feature specification (user stories, FR, SC)
├── research.md          # Phase 0: tech decisions + alternatives considered
├── data-model.md        # Phase 1: SpecConfig + sub-entities
├── quickstart.md        # Phase 1: developer getting-started guide
├── contracts/           # Phase 1: CLI sub-command contracts
│   ├── generate.md
│   ├── cycle.md
│   ├── coverage.md
│   ├── reindex.md
│   └── validate.md
└── tasks.md             # Phase 2 output (not yet created — /speckit.tasks)
```

### Source Code (repository root)

```text
speckit/
├── pyproject.toml              # Package definition, deps (hatchling), tool config
├── README.md
├── CLAUDE.md                   # Agent entry point for this project
├── speckit-constitution.md     # Immutable constraints — read before implementing
├── src/
│   └── speckit/
│       ├── __init__.py
│       ├── cli.py              # Entry point: argparse sub-commands, phase orchestration
│       ├── spec/
│       │   ├── __init__.py
│       │   ├── parser.py       # vault-spec.md → SpecConfig dataclass
│       │   ├── validator.py    # Required field checks → SpecValidationError
│       │   └── schema.py       # SpecConfig and all sub-dataclasses (typed)
│       ├── generator/
│       │   ├── __init__.py
│       │   ├── scaffold.py     # Creates vault directory structure
│       │   ├── templates.py    # Renders Jinja2 templates with SpecConfig
│       │   └── scripts.py      # Copies scripts/ bundle verbatim into vault
│       ├── pipeline/
│       │   ├── __init__.py
│       │   ├── preconditions.py # Phase 2 entry checks (5 conditions)
│       │   ├── coverage.py      # Read/write coverage-targets.json
│       │   ├── orchestrator.py  # Calls run_cycle.sh; reads exit codes
│       │   └── reporter.py      # Phase 1 report generation
│       └── vault/
│           ├── __init__.py
│           ├── indexer.py       # Rebuilds Layer 1: _index.md, _concepts.md, _graph.md
│           └── metrics.py       # vault_metrics.py logic (importable + CLI)
├── scripts/                    # Scripts BUNDLED into generated vaults (not speckit src)
│   ├── validate_vault.py
│   ├── validate_cycle.py
│   ├── check_template_compliance.py
│   ├── check_acronym_links.py
│   ├── fix_acronym_links.py    # --dry-run required before --apply
│   ├── fix_wikilinks.py        # --dry-run required before --apply
│   ├── vault_metrics.py
│   └── run_cycle.sh
├── templates/                  # Jinja2 templates for generated vault files
│   ├── CLAUDE.md.j2
│   ├── AGENTS.md.j2
│   ├── README.md.j2
│   ├── vault-config.yaml.j2
│   ├── query-command.md.j2
│   ├── add-command.md.j2
│   ├── note-types/
│   │   ├── concept.md.j2
│   │   ├── service.md.j2
│   │   ├── flow.md.j2
│   │   ├── product.md.j2
│   │   ├── team.md.j2
│   │   ├── decision.md.j2
│   │   ├── risk.md.j2
│   │   ├── process.md.j2
│   │   ├── market.md.j2
│   │   └── source.md.j2
│   └── index-files/
│       ├── _index.md.j2
│       ├── _concepts.md.j2
│       └── _graph.md.j2
└── tests/
    ├── conftest.py             # Shared fixtures (sample spec, temp vault dir)
    ├── fixtures/
    │   ├── sample-spec.md      # Minimal valid vault spec
    │   ├── vault/              # Pre-populated test vault
    │   │   ├── data_vault/
    │   │   │   └── 01 - Concepts/
    │   │   │       ├── Valid Concept.md
    │   │   │       ├── Long Summary Concept.md    # summary > 120 chars → fail
    │   │   │       ├── Missing Source.md           # no source_urls → fail
    │   │   │       ├── Missing Section.md          # template section absent → fail
    │   │   │       └── Unlinked Acronym (UA).md   # first UA not wikilinked → fail
    │   │   └── _templates/
    │   │       └── concept.md
    │   └── cycle-reports/
    │       ├── valid-scout.json
    │       ├── invalid-scout-missing-dimension.json
    │       └── valid-research.json
    ├── spec/
    │   ├── test_parser.py
    │   └── test_validator.py
    ├── generator/
    │   ├── test_scaffold.py
    │   └── test_templates.py
    ├── pipeline/
    │   ├── test_preconditions.py
    │   └── test_coverage.py
    └── scripts/                # Tests for the scripts/ bundle
        ├── test_validate_vault.py
        ├── test_validate_cycle.py
        ├── test_check_template_compliance.py
        ├── test_check_acronym_links.py
        └── test_vault_metrics.py
```

**Structure Decision**: Single project layout. `src/speckit/` is speckit's own code.
`scripts/` is the vault script bundle deployed into generated vaults. Both are tested
independently — `scripts/` tests run against `tests/fixtures/vault/` which mirrors the
codebase vault structure. Every negative fixture tests exactly one failure mode.

## Complexity Tracking

> No constitution violations to justify. All principles pass.

---

## Component Design

### Phase 0: Spec Parser (`spec/`)

**Input**: `vault-spec.md` — YAML-fronted Markdown (see `vault-spec-template.md`).
**Output**: `SpecConfig` dataclass — fully typed, validated, drives all generation.

```python
@dataclass
class SpecConfig:
    name: str
    location: Path
    owner: str
    scope: ScopeConfig
    note_types: list[NoteTypeConfig]
    data_sources: list[DataSourceConfig]
    search_dimensions: list[str]   # must include "domain" and "market"
    coverage_targets: CoverageTargets
    budget: BudgetConfig
    max_cycles: int = 5
    naming_convention: str = "full_name"
    jira_project: str | None = None
    access_modes: list[str] = field(default_factory=list)
```

`validator.py` raises `SpecValidationError` on missing required fields and prints a
human-readable error per missing item. Phase 0 exits with code 2 on any validation
failure. No partial proceeds.

**Output artifact**: `_pipeline/spec-parse.json` written to vault directory.

### Phase 1: Infrastructure Generator (`generator/`)

Three sub-tasks, all sequential:

**1. Scaffold (`scaffold.py`)**: Creates directory tree from spec. Creates `_pipeline/`
with `budget-log.md`, `research-backlog.md`, and skeleton `coverage-targets.json`
populated from spec targets.

**2. Template rendering (`templates.py`)**: Renders each Jinja2 template with `SpecConfig`.
Key files:
- `CLAUDE.md` — note schema, quality bar, naming convention, note types, data sources,
  scope. Not boilerplate — all values from spec.
- `AGENTS.md` — skeleton with correct folder structure; topic index populated after Phase 2.
- Note templates per type — section headings from spec's `contextual_questions` for that
  type.
- Query and add commands — named per spec (e.g., `/acme`, `/acme-add`).

**3. Scripts bundle (`scripts.py`)**: Copies all files from `scripts/` into
`{vault}/scripts/`. Copy is verbatim — scripts are vault-agnostic.

**Phase 1 gate** (enforced in `cli.py` as hard exit):

```python
result = subprocess.run(["pytest", "scripts/tests/", "-v"], cwd=vault_dir)
if result.returncode != 0:
    sys.exit("Phase 1 gate failed: pytest did not pass. Fix scripts before Phase 2.")
```

This prevents F1 and F2. If it fails, the generator stops and reports which tests failed.
No workaround exists.

### Phase 2: Cycle Orchestrator (`pipeline/`)

**`preconditions.py`**: Checks 5 Phase 2 entry conditions (pytest pass, validate_vault
exit 0, `coverage-targets.json` exists, `budget-log.md` initialized, naming convention in
`CLAUDE.md`). Exits with a report of unmet conditions. Used by both initial generation and
`--resume`.

**`coverage.py`** public API:
- `load_targets(vault_dir: Path) → CoverageTargets`
- `update_after_cycle(vault_dir: Path, research_report: dict) → None`
- `all_targets_met(vault_dir: Path) → bool`
- `unmet_targets(vault_dir: Path) → list[str]`

**`orchestrator.py`**: Calls `scripts/run_cycle.sh` via subprocess. The orchestrator:
- Checks budget before each cycle
- Reads cycle JSON reports to detect termination condition
- Decides continue/terminate based on all Condition B sub-conditions
- Does NOT self-assess — reads script exit codes only

**`run_cycle.sh`** (in scripts bundle):

```bash
#!/usr/bin/env bash
set -euo pipefail
# Args: $1=cycle_num $2=vault_dir $3=max_cycles $4=budget_cap

# 1. Pre-cycle snapshot
python scripts/vault_metrics.py "$2" --output "_pipeline/cycles/cycle-$1-pre.json"

# 2. BFS scout
claude --prompt "$(cat _pipeline/prompts/scout-prompt.md)" \
    > "_pipeline/cycles/cycle-$1-scout.json"

# 3. Validate scout — exit $? propagates exit code to orchestrator
python scripts/validate_cycle.py "_pipeline/cycles/cycle-$1-scout.json" || exit $?

# 4. DFS research
claude --prompt "$(cat _pipeline/prompts/dfs-prompt.md)" \
    > "_pipeline/cycles/cycle-$1-research.json"

# 5. Post-DFS validation suite
python scripts/validate_vault.py "$2" && \
python scripts/check_template_compliance.py "$2" && \
python scripts/check_acronym_links.py "$2"

# 6. Validate research report
python scripts/validate_cycle.py "_pipeline/cycles/cycle-$1-research.json" || exit $?

# 7. Post-cycle snapshot
python scripts/vault_metrics.py "$2" --output "_pipeline/cycles/cycle-$1-post.json"
```

### Phase 3: Finalize (`vault/` + `pipeline/reporter.py`)

**`indexer.py`**: Reads all notes in `data_vault/`, parses frontmatter, rebuilds
`_index.md`, `_concepts.md`, `_graph.md`. Graph rebuild reads `related` fields from all
notes — does not infer relationships. Updates `AGENTS.md` topic index and key numbers.

**`reporter.py`**: Generates `_pipeline/phase1-report.md` from cycle JSON files, budget
log, and final `coverage-targets.json` state.

**Phase 3 sequence in `cli.py`**:
1. Run full validation suite
2. Check `coverage.all_targets_met()` — if not met, print `coverage.unmet_targets()`
   and instructions for targeted Phase 2 re-entry. Do NOT proceed.
3. Run `vault/indexer.py` to rebuild Layer 1
4. `git init` + first commit (commit message from spec name)
5. Run `pipeline/reporter.py`

---

## CLI Interface

```bash
# Primary: generate a new vault from a spec
speckit generate --spec path/to/vault-spec.md [--output ~/Documents/my-vault]

# Resume Phase 2 on an existing vault (skips Phase 0/1, checks preconditions)
speckit generate --spec path/to/vault-spec.md --resume [--cycle N]

# Infrastructure only — no Phase 2
speckit generate --spec path/to/vault-spec.md --dry-run

# Run a single cycle manually (debugging)
speckit cycle --vault ~/Documents/my-vault --cycle N

# Check coverage targets
speckit coverage --vault ~/Documents/my-vault

# Rebuild Layer 1 indexes only
speckit reindex --vault ~/Documents/my-vault

# Validate a vault (runs all validation scripts)
speckit validate --vault ~/Documents/my-vault
```

Implemented via `argparse` sub-commands. No external CLI framework dependency.

---

## Implementation Milestones

Ordered by value delivered to the codebase vault, not implementation elegance.

### v0.1 — Scripts Library *(now — unblocks codebase vault Phase 1 completion)*

**Goal**: 5 validation scripts with passing tests. Codebase vault can run them immediately.

| Script | Core logic | Test coverage |
|--------|-----------|---------------|
| `validate_vault.py` | Frontmatter completeness, summary ≤ 120, source URLs, wikilink resolution | Valid note, missing field, long summary, broken wikilink |
| `validate_cycle.py` | JSON schema, 5 dimensions, Condition B sub-conditions | Valid scout, missing dimension, Condition B true/false |
| `check_template_compliance.py` | Load template, diff section headings, report missing | Compliant note, missing section, unknown type |
| `check_acronym_links.py` | Build acronym list from titles, scan bodies for first unlinked | Linked, unlinked, edge cases (code blocks, URLs) |
| `vault_metrics.py` | Note count by type/folder, word count buckets, unresolved wikilinks | Full vault snapshot round-trip |

**Test fixtures**: Built from the codebase vault. Real note files (anonymised where needed)
as both positive and negative cases. Each negative fixture tests exactly one failure mode.

**Fix scripts** (secondary v0.1 deliverable):

| Script | Notes |
|--------|-------|
| `fix_acronym_links.py` | `--dry-run` first; `--apply` writes; validates after |
| `fix_wikilinks.py` | Same pattern |

Both fix scripts require `--dry-run` output review before `--apply`. This is a hard rule
(constitution Never #4).

**Acceptance**: `pytest scripts/tests/` passes. `validate_vault.py` on codebase vault
produces a known list of violations (not zero — the vault has real issues).

### v0.2 — Spec Parser + Infrastructure Generator *(Phase 0 + Phase 1)*

**Goal**: `speckit generate --spec codebase-vault-spec.md --dry-run` produces a vault
directory structure matching the codebase vault layout.

**Deliverables**:
- `vault-spec-template.md` populated for the codebase vault (`codebase-vault-spec.md`)
- `src/speckit/spec/` — parser, validator, schema
- `src/speckit/generator/` — scaffold, templates, scripts copy
- All Jinja2 templates rendering correctly
- Phase 1 gate enforced (pytest must pass after script copy)

**Acceptance**:
```bash
speckit generate --spec codebase-vault-spec.md --dry-run
# → vault directory created at configured path
# → pytest scripts/tests/ passes
# → coverage-targets.json present with codebase vault targets
# → CLAUDE.md reflects spec schema, not boilerplate
```

The generated vault must be structurally identical to the current codebase vault root
(minus content). This is the integration test.

### v0.3 — Cycle Orchestrator + Resume Mode *(Phase 2 entry)*

**Goal**: `speckit generate --spec codebase-vault-spec.md --resume` checks preconditions
and can drive a new research cycle.

**Deliverables**:
1. `src/speckit/pipeline/preconditions.py` — all 5 checks with clear output
2. `src/speckit/pipeline/coverage.py` — read/write `coverage-targets.json`
3. `src/speckit/pipeline/orchestrator.py` — subprocess call to `run_cycle.sh`
4. `scripts/run_cycle.sh` — implemented, not placeholder
5. `speckit coverage` sub-command

**Key test**: `speckit generate --resume` on the existing codebase vault reports which
preconditions are unmet, then after v0.1 fix passes, enters Cycle 3 (targeted external
sources pass).

**Acceptance**:
```bash
speckit coverage --vault ~/Documents/codebase-vault
# → shows external targets unmet (competitor profiles, domain fundamentals)
# → shows quality targets as pass/fail

speckit generate --spec codebase-vault-spec.md --resume
# → precondition check passes (after v0.1 applied)
# → enters Cycle 3 with targeted external source prompt
```

### v1.0 — Complete Phase 1 Generator *(end-to-end)*

**Goal**: `speckit generate --spec any-spec.md` produces a vault passing all quality gates.

**Deliverables**:
- `src/speckit/vault/indexer.py` — Layer 1 rebuild
- `src/speckit/pipeline/reporter.py` — phase1-report.md generation
- Phase 3 gate enforced (coverage check before finalize)
- `git init` + first commit in Phase 3
- End-to-end test from `tests/fixtures/sample-spec.md`

**Acceptance**: A human can create a new vault by writing only a spec file. The generated
vault passes `speckit validate`. No placeholder scripts in any deliverable.

### v1.1 — Write Path + Quality Layer *(enables codebase vault Phase 2)*

**Goal**: Vaults with a working `/acme-add` equivalent and FTS5 SQLite index.

**Deliverables**:
- `add-command.md.j2` — research agent command template (rendered per spec's command names)
- `scripts/build_fts_index.py` — SQLite FTS5 index over frontmatter + body
- `scripts/sync_fts.py` — incremental sync when notes change
- Wikilink integrity enforcer — broken wikilinks in new notes block writes
- Source change detection scaffold — Confluence/Jira webhook stub (detection only)

Note: The `/acme-add` command itself is a Claude Code command, not speckit code.
Speckit generates the command file from the template. Speckit does not embed model calls.

### v2.0 — Intelligence + Integration *(enables codebase vault Phase 3)*

**Goal**: Hybrid FTS5+vector search and Java/Spring MCP server.

**Deliverables**:
- `scripts/build_vector_index.py` — sqlite-vec with local embeddings
  (decision point: only proceed if Phase 2 query miss rate > 15%)
- `scripts/query_hybrid.py` — FTS5 + vector hybrid search
- `speckit-mcp-server/` — separate Java/Spring Boot project (NOT in this Python repo)
- Complexity matrix router — FTS5 for simple, vector for semantic, Opus flag for complex

**Architecture note**: The MCP server is a separate repository using Java + Spring Boot as
specified in the constitution. This decision is not revisitable without an ADR.

---

## Testing Strategy

### Two test targets

**1. Speckit's own code** (`tests/` in repo root):
- Unit tests per module
- Integration test: full `generate` cycle using `sample-spec.md`
- Property-based tests (hypothesis) for spec parser/validator
- No mocking of subprocess calls to `claude` — use a stub script that writes valid cycle JSON

**2. The scripts bundle** (`tests/scripts/`):
- Tests for each of the 5 validation scripts
- Fixtures are real vault notes (both passing and failing)
- Exit code contract tested explicitly (0 / 1 / 2)
- `--dry-run` flag tested: MUST NOT modify any files

### CI behaviour (when configured)

```bash
pytest tests/ -v --tb=short
black src/ scripts/ tests/ --check
ruff check src/ scripts/
```

All three must pass before any merge.

---

## Key Constraints from the Constitution

- **No placeholder scripts.** `scripts/run_cycle.sh` is implemented before v0.3 ships.
  Every script in the bundle has a passing test before it is used on real vault data.
- **`--dry-run` before `--apply` on fix scripts.** `fix_acronym_links.py` refuses to write
  without explicit `--apply` flag.
- **Phase 2 cannot start without `pytest` passing.** Hard exit in `cli.py` — not a warning.
- **TERMINATE ≠ Phase 1 complete.** Orchestrator reads `coverage-targets.json` after every
  cycle termination. Unmet targets → targeted re-entry, not Phase 3 proceed.
- **Agents do not assess their own validation.** Orchestrator reads script exit codes only.
- **No external data persistence.** Jinja2 is the only added runtime dependency.

---

## Risks and Mitigations

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| `claude` CLI API changes break `run_cycle.sh` | Medium | High | Isolate all `claude` invocations in `orchestrator.py`; one change point |
| Codebase vault note structure diverges from spec before v0.2 | Low | Medium | Write `codebase-vault-spec.md` early (v0.1 milestone) as a forcing function |
| Jinja2 template rendering produces invalid Markdown | Low | Medium | Snapshot tests on rendered output; render and lint in CI |
| Fix scripts damage vault on first run | Low | High | `--dry-run` + reviewed diff before `--apply`; fixture test covers real damage patterns |
| sqlite-vec offline risk (v1.1+) | Low | Medium | sqlite-vec is bundled, not downloaded at runtime |

---

## Out of Scope for This Plan

- The exact JSON schema for cycle reports (spec's responsibility)
- Template section headings for each note type (spec + constitution)
- The vault spec file format (`vault-spec-template.md`)
- Default values for budget, max cycles, depth thresholds
- The query command behavior (`/acme`) — speckit generates the file, not the behavior
- Phase 2 and Phase 3 specs for the codebase vault — separate documents

---

## Sequence Summary

```
v0.1  ── scripts library ─────────── validate_vault, validate_cycle, check_* scripts
         (now; unblocks codebase vault Phase 1 completion work)

v0.2  ── spec parser + generator ─── Phase 0 + Phase 1 from spec file
         (prerequisite for new vaults; validates against codebase vault layout)

v0.3  ── cycle orchestrator ─────── Phase 2 entry; --resume on existing vaults
         (enables Cycle 3 on codebase vault: external sources pass)

v1.0  ── complete Phase 1 ─────────  Phase 3 finalize; end-to-end vault generation
         (codebase vault Phase 1 complete; new vaults fully generatable)

v1.1  ── write path + FTS5 ─────────  /acme-add; SQLite search; source monitoring
         (codebase vault Phase 2 delivery)

v2.0  ── intelligence + MCP ─────── vector search; Java/Spring MCP server
         (codebase vault Phase 3 delivery; decision point on query miss rate)
```

---

**Version**: 1.0.0 | **Created**: 2026-04-16 | **Last Updated**: 2026-04-16
