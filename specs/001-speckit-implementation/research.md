# Research: Speckit v0.1 — Knowledge Vault Generator

**Branch**: `001-speckit-implementation` | **Date**: 2026-04-16
**Phase**: 0 — Pre-implementation research

All unknowns from Technical Context are resolved. This document records decisions and
alternatives considered.

---

## CLI Framework

**Decision**: `argparse` (stdlib)

**Rationale**: No external dependency for core CLI. Speckit's constitution requires offline
operation and minimal runtime dependencies. `argparse` covers all required sub-command
patterns (`generate`, `cycle`, `coverage`, `reindex`, `validate`) without adding a
dependency that could phone home or require network access during install. `click` or
`typer` would add ergonomics (auto-completion, colored output) but neither is justified
given the constraint.

**Alternatives considered**:
- `click` — popular, ergonomic, but external dependency without clear enough benefit
- `typer` — type-hint driven, built on click, same objection applies
- `argparse` (stdlib) — chosen; sufficient for all required sub-commands

---

## Template Rendering

**Decision**: `jinja2`

**Rationale**: `jinja2` is the only acceptable additional runtime dependency at v1.0.
Vault template files (CLAUDE.md, AGENTS.md, note types, commands) require conditional
blocks, loops over spec-derived lists (note types, data sources, search dimensions), and
filter expressions. The stdlib `string.Template` does not support conditionals or loops.
`jinja2` is industry-standard, Markdown-safe, and well-tested against injection attacks.

**Alternatives considered**:
- `string.Template` (stdlib) — insufficient: no control flow, no filters, no loops
- `chevron` (mustache) — lightweight but adds a dep without adding enough over stdlib
- `jinja2` — chosen; only dep justified by the spec

---

## Packaging

**Decision**: `pyproject.toml` with `hatchling` build backend

**Rationale**: PEP 517/518 compliant, no `setup.py`. `hatchling` is the most minimal
build backend for pure-Python packages. The CLI entry point (`speckit = speckit.cli:main`)
is declared in `[project.scripts]`. All tool configuration (`black`, `ruff`, `pytest`) is
co-located in `pyproject.toml`.

**Alternatives considered**:
- `setuptools` — more complex, legacy `setup.py` risk
- `flit` — simpler, but less commonly used at Acme Corp
- `hatchling` — chosen; minimal, PEP 517 compliant

---

## Spec File Format

**Decision**: YAML frontmatter + Markdown body (`.md` file)

**Rationale**: The spec file is human-authored. YAML frontmatter (delimited by `---`) is
the Obsidian-native format and is already familiar to vault users. The Markdown body
provides free-form description sections. `python-frontmatter` (a thin wrapper around
`pyyaml`) is used in the parser. If avoiding the dependency is preferred, `pyyaml` alone
can be used with a custom `---` delimiter split.

**Decision**: Use `pyyaml` directly (already in Jinja2's indirect deps in many envs; if
not, it is a minimal well-audited package). Parse the YAML block between the first pair of
`---` delimiters; ignore the Markdown body for machine-parsing purposes.

**Alternatives considered**:
- `python-frontmatter` — thin wrapper, slightly more convenient API, but adds a dep
- `pyyaml` direct — chosen; minimal, already widely installed, no extra dep needed
- TOML — not Obsidian-native; would require `tomllib` (stdlib in 3.11) but unfamiliar to
  vault users

---

## Test Approach for `scripts/` Bundle

**Decision**: pytest with real vault fixtures; no mocking of file I/O

**Rationale**: The constitution's Failure Record documents F7 (preconditions skipped) and
F8 (agents self-assessed validation) as the result of tests that didn't run against real
data. The scripts bundle tests MUST use real vault note files (with known violations) as
fixtures, not synthetic strings. This ensures the scripts catch violations that appear in
production notes — format quirks, encoding, whitespace — not just the happy path.

**Implementation**: `tests/fixtures/vault/` contains a minimal vault mirroring the codebase
vault structure. Each negative fixture tests exactly one failure mode (constitution
principle: scripts validate, not agents).

**Alternatives considered**:
- Mock file reads with `unittest.mock` — rejected; too abstract, misses format edge cases
- In-memory string fixtures — rejected for same reason
- Real fixture files — chosen; matches production data shapes

---

## Property-Based Testing

**Decision**: `hypothesis` for spec parser and validator

**Rationale**: The spec parser receives user-authored YAML. Property-based testing with
`hypothesis` ensures that:
- Any structurally valid spec always parses without exception
- Any spec missing a required field always raises `SpecValidationError` with the correct
  field name

This catches edge cases (empty strings, Unicode values, deeply nested YAML) that example-
based tests miss. `hypothesis` is a `dev` dependency only — not a runtime dependency.

**Alternatives considered**:
- Example-based tests only — insufficient; user-authored YAML has too many edge cases
- `hypothesis` — chosen; `dev` dep only, well-maintained

---

## Subprocess Strategy for `claude` CLI

**Decision**: No mocking; use a stub script in tests

**Rationale**: Mocking `subprocess.run` hides the actual invocation contract. Instead, the
test suite provides a stub script at a known path that writes a valid cycle JSON file. The
orchestrator calls this stub rather than the real `claude` CLI during tests. This tests the
actual subprocess call pattern (argument passing, working directory, exit code handling)
without requiring a real `claude` installation in CI.

**Implementation**: `tests/fixtures/stubs/claude` — a Python script that writes a canned
valid scout or research JSON based on `sys.argv`. Tests set `PATH` to include the stubs
directory.

**Alternatives considered**:
- `unittest.mock.patch('subprocess.run')` — rejected; doesn't test argument marshalling
- Real `claude` CLI in CI — rejected; requires authentication, network, and billing
- Stub script — chosen; tests subprocess contract without external dependency

---

## Layer 1 Rebuild Strategy

**Decision**: Full rebuild from Layer 2 on every `indexer.py` call; no incremental tracking

**Rationale**: At v1.0 vault sizes (50–500 notes), a full read of all frontmatter is fast
(< 1s). Incremental tracking (watching for file changes, maintaining a cache) adds
significant complexity for no measurable benefit at this scale. A full rebuild also ensures
Layer 1 is always a correct projection of Layer 2 — no stale entries.

**Decision point for v1.1**: If vault sizes exceed 1000 notes or rebuild time exceeds 5s,
introduce incremental indexing. Not now.

**Alternatives considered**:
- File-watcher based incremental — rejected at v1.0; premature optimization
- SQLite cache — rejected at v1.0; same reason
- Full rebuild — chosen; simple, correct, sufficient at current scale

---

## FTS5 vs. Vector Search Decision Point (v1.1 / v2.0)

**Decision**: FTS5 first (v1.1); vector search only if query miss rate > 15% (v2.0)

**Rationale**: FTS5 SQLite is bundled in Python's stdlib (`sqlite3`). It handles keyword,
prefix, and phrase queries accurately for structured vault content. The codebase vault's
primary query patterns (concept lookup, team lookup, acronym expansion) are all FTS5-
addressable. Vector search adds semantic retrieval but introduces `sqlite-vec` (a C
extension) and a local embedding model — significant complexity. The 15% miss rate
threshold is the trigger: only invest in vector if the simpler approach demonstrably fails.

**Alternatives considered**:
- Vector-first — rejected; premature for current query patterns
- FTS5 + vector from the start — rejected; violates YAGNI at v1.0
- FTS5 only, reassess at v1.1 — chosen
