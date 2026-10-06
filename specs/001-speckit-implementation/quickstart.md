# Quickstart: Speckit v0.1 Developer Guide

**Branch**: `001-speckit-implementation` | **Date**: 2026-04-16

This guide gets you from a clean checkout to running the full test suite and using the CLI.

---

## Prerequisites

- Python 3.11+
- `git`
- `pytest`, `black`, `ruff` (installed in dev environment — see below)
- `jinja2` (only runtime dependency)
- `claude` CLI (required for Phase 2 orchestration; not needed for v0.1 scripts work)

---

## Development Setup

```bash
git clone <speckit-repo>
cd speckit

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate  # macOS/Linux

# Install the package in editable mode with dev extras
pip install -e ".[dev]"
# This installs: jinja2, pytest, hypothesis, black, ruff
```

`pyproject.toml` defines the `[dev]` optional dependency group:

```toml
[project.optional-dependencies]
dev = ["pytest", "hypothesis", "black", "ruff"]
```

---

## Running Tests

```bash
# All tests (speckit src + scripts bundle)
pytest tests/ -v --tb=short

# Scripts bundle only (the tests most relevant to v0.1)
pytest tests/scripts/ -v

# Spec parser tests
pytest tests/spec/ -v

# With coverage (optional)
pytest tests/ --cov=src/speckit --cov=scripts --cov-report=term-missing
```

**Expected output at v0.1** (scripts library milestone):

```
tests/scripts/test_validate_vault.py ........  PASSED
tests/scripts/test_validate_cycle.py ......    PASSED
tests/scripts/test_check_template_compliance.py ....  PASSED
tests/scripts/test_check_acronym_links.py .....  PASSED
tests/scripts/test_vault_metrics.py ...        PASSED
```

All tests MUST pass before any work is reported as complete (constitution principle III).

---

## Using the Scripts Bundle Directly (v0.1)

The scripts in `scripts/` can be run directly against any vault — they do not require
the speckit package to be installed.

```bash
# Validate all notes in a vault
python scripts/validate_vault.py ~/Documents/codebase-vault

# Validate a scout cycle report
python scripts/validate_cycle.py ~/Documents/codebase-vault/_pipeline/cycles/cycle-2-scout.json

# Check template section compliance
python scripts/check_template_compliance.py ~/Documents/codebase-vault

# Check acronym links
python scripts/check_acronym_links.py ~/Documents/codebase-vault

# Get vault metrics (stdout JSON)
python scripts/vault_metrics.py ~/Documents/codebase-vault

# Fix acronym links — DRY RUN FIRST, always
python scripts/fix_acronym_links.py ~/Documents/codebase-vault --dry-run
# Review output, then apply only after reviewing:
python scripts/fix_acronym_links.py ~/Documents/codebase-vault --apply
```

**Exit codes**:
- `0` — pass / all checks OK
- `1` — fail / TERMINATE (structural: report violations, stop cycle)
- `2` — abort (structural error in input: broken JSON, missing required field)

---

## Using the speckit CLI (v0.2+)

```bash
# Generate a new vault from a spec file
speckit generate --spec path/to/vault-spec.md

# Generate infrastructure only (no Phase 2 research)
speckit generate --spec path/to/vault-spec.md --dry-run

# Resume Phase 2 on an existing vault
speckit generate --spec path/to/vault-spec.md --resume

# Check coverage targets on an existing vault
speckit coverage --vault ~/Documents/codebase-vault

# Validate a vault (runs all validation scripts)
speckit validate --vault ~/Documents/codebase-vault

# Rebuild Layer 1 indexes only (Phase 3, standalone)
speckit reindex --vault ~/Documents/codebase-vault
```

---

## Code Quality

```bash
# Format (must pass before commit)
black src/ scripts/ tests/

# Lint (must pass before commit)
ruff check src/ scripts/

# Check without modifying
black --check src/ scripts/ tests/
ruff check --no-fix src/ scripts/
```

Both `black` (88-char line length) and `ruff` are configured in `pyproject.toml`. All
public functions require type hints. These are enforced in CI.

---

## Fixture Layout

```
tests/fixtures/
├── sample-spec.md          # Minimal valid vault spec for end-to-end tests
├── vault/                  # Test vault mirroring codebase vault structure
│   ├── data_vault/
│   │   └── 01 - Concepts/
│   │       ├── Valid Concept.md              # All checks pass → expect exit 0
│   │       ├── Long Summary Concept.md       # summary=125 chars → expect exit 1
│   │       ├── Missing Source.md             # no source_urls → expect exit 1
│   │       ├── Missing Section.md            # missing template section → expect exit 1
│   │       └── Unlinked Acronym (UA).md      # first UA not wikilinked → expect exit 1
│   ├── _templates/
│   │   └── concept.md                        # Reference template for compliance check
│   └── _pipeline/
│       ├── coverage-targets.json
│       └── cycles/
│           ├── valid-scout.json
│           └── invalid-scout-missing-market-dim.json
└── stubs/
    └── claude                                # Stub script for orchestrator tests
```

**Each negative fixture tests exactly one failure mode.** Do not combine multiple
violations in a single fixture — it makes it impossible to verify that each script
catches its specific violation independently.

---

## Adding a New Validation Script

1. Write the test first in `tests/scripts/test_{script_name}.py`. Tests MUST fail before
   implementation (TDD — constitution principle III).
2. Implement the script in `scripts/{script_name}.py`.
3. Add `--dry-run` flag if the script modifies any files.
4. Run `pytest tests/scripts/ -v` — all tests must pass.
5. Run `black scripts/{script_name}.py` and `ruff check scripts/{script_name}.py`.
6. Update `tests/fixtures/vault/` with any new fixture files the test requires.

Scripts that modify vault files MUST refuse to write without `--apply` and MUST output a
diff preview in `--dry-run` mode. (Constitution principle III, Never #4.)

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `speckit-constitution.md` | Immutable constraints — read before any implementation |
| `src/speckit/cli.py` | Entry point; phase orchestration; Phase 1 pytest gate |
| `src/speckit/spec/schema.py` | SpecConfig and all sub-dataclasses |
| `src/speckit/spec/parser.py` | vault-spec.md → SpecConfig |
| `src/speckit/spec/validator.py` | SpecValidationError; field-level error messages |
| `src/speckit/pipeline/coverage.py` | CoverageTargets read/write; all_targets_met() |
| `src/speckit/pipeline/orchestrator.py` | run_cycle.sh subprocess; exit code handling |
| `scripts/validate_vault.py` | Note quality validation (exit 0/1/2) |
| `scripts/validate_cycle.py` | Cycle report validation; Condition B sub-conditions |
| `scripts/run_cycle.sh` | BFS → validate → DFS → validate sequence |
| `tests/fixtures/vault/` | Test vault with known good and bad notes |
| `pyproject.toml` | Package definition, deps, black/ruff/pytest config |
