# Feature Specification: Fixture Isolation Hardening

**Feature Branch**: `026-fixture-isolation`
**Created**: 2026-05-22
**Status**: shipped(2026-06-04, PR #107) — SHIPPED 0.10.0 (PR #107, 2026-06-04). The quality harness now runs against an isolated copy on both seams (`run_fixture_cycles` + `python -m …quality.runner`) via the shared `quality.runner.isolate_fixture`; `git status` is pristine after `./build.sh --quality`. WAL sidecars untracked + `.gitignore` narrowed; committed-shim machine-agnosticism regression-locked; bootstrap `--force`-gated. Regression-locked by `tests/quality/test_fixture_isolation.py` (in `build.sh::SMOKE_TESTS`). Wave 2 (→ 0.10.0); **feeds spec 009's CI** (a pristine tree after the quality gate is what 009's `git status` check asserts).
**Input**: User description: "Quality fixtures mutate tracked files on every cycle run; running `./build.sh --quality` (now mandatory before release) leaves ~6 modified + 4 untracked entries in `git status` every single time. Also: `fake_agent.install_shim()` overwrites tracked fixture shims; committed shims bake absolute `/Users/<name>/...` paths breaking portability. Migrate the harness to copy each fixture to `tmp_path` before each cycle, point the cycle runner at the copy, leave the tracked tree pristine."

## Clarifications

### Session 2026-06-03 (clarify + code reconciliation)

An audit at the 053 base reconciled the 2026-05-22 premise against the shipped code:

- **US1 confirmed.** `tests/quality/conftest.py::run_fixture_cycles` runs `run_cycle_steps(fixture.vault_dir, cycle)` directly against the **tracked** fixture tree (lines 48-60) — no `tmp_path` copy. The harness still mutates the source-of-truth.
- **The git-status noise has a concrete root cause**: **36 files** under `tests/fixtures/quality/*/_pipeline/` are **tracked** while `.gitignore:79` (`tests/fixtures/quality/**/_pipeline/`) *also* lists that path — the classic tracked-AND-ignored contradiction. Git keeps surfacing them as modified because gitignore never untracks already-tracked files. (Includes volatile `sources.db-shm`/`sources.db-wal` WAL sidecars that should never be committed.)
- **US2 (baked `/Users/` paths) is ALREADY SOLVED — and the spec's literal fix would regress.** `fake_agent.install_shim` (fake_agent.py:1162-1166) bakes the absolute repo root **only when the install target is OUTSIDE the repo** (a `tmp_path`); for in-repo targets it bakes `None`. Committed fixture shims therefore have **zero** machine-specific paths (`rg /Users/ … → 0 hits`). The abs-path baking on `tmp_path` shims is **required** for Strategy-3 module resolution so the fake-agent shim can import `tests/_helpers/fake_agent` and keep intercepting (the `test_fake_agent_interception` Principle-IV guard). So US2 is **re-scoped to a regression-lock on committed shims**, NOT a removal of all absolute paths.

**Resolved questions** (recommended option chosen):

- **Q1 (was FR-010) — Tracked `_pipeline/` baselines → PRESERVE + CLEAN.** Keep the deterministic baselines (`sources.db` seed, `coverage-targets.json`, prompts, etc.) as the pristine copy-source starting state. `git rm --cached` only the volatile SQLite WAL sidecars (`sources.db-shm`, `sources.db-wal`). **Fix `.gitignore:79`** so it no longer claims the fixture `_pipeline/` baselines are ignored (scope the ignore to the per-run `_pipeline/quality/` workspace + the WAL sidecars). Rationale: removing the baselines would cold-start cycles and risk shifting the committed `tests/fixtures/quality/baselines/*.baseline.json`.

**Defaults taken without asking**: the `tmp_path` shim intentionally bakes the abs repo root (US2 reframe — it's correct, not a regression); concurrent runs are isolated by pytest's per-test `tmp_path` (xdist-safe).

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Maintainer runs the quality gate without polluting their working tree (Priority: P1)

A maintainer running `./build.sh --quality` (or `pytest tests/quality/`) locally as part of a pre-release smoke check or while iterating on a feature expects `git status` to be clean afterward. Today they see 6 modified files (`tests/fixtures/quality/*/_pipeline/sources.db`, `_pipeline/research-backlog.md`, `_pipeline/sources.db-shm`) and 4 untracked directories (`tests/fixtures/quality/*/data_vault/01 - Services/` etc.) every time they run the gate.

**Why this priority**: Every maintainer who runs the gate hits this. It bites every weekend audit, every release, every contributor onboarding. It's the daily friction the Foundation arc accidentally introduced. P3.5 in the post-foundation TODO triage.

**Independent Test**: Run `./build.sh --quality` on a clean working tree. Verify `git status --porcelain` returns zero output after the run completes (success or failure).

**Acceptance Scenarios**:

1. **Given** a clean working tree on `main`, **When** maintainer runs `./build.sh --quality`, **Then** `git status --porcelain` returns empty after the run.
2. **Given** the quality harness is mid-run, **When** the run is interrupted (Ctrl-C / SIGTERM), **Then** the tracked fixture tree remains pristine and only a `tmp_path` directory contains partial state.
3. **Given** a quality run fails (any reason), **When** maintainer inspects the failed-run artifacts, **Then** they can locate the cycle output (notes, sidecars, sources.db) in a deterministic temp location (e.g., `/tmp/quality-<fixture>-<timestamp>/`).

---

### User Story 2 — Committed fake-agent shims stay machine-agnostic (regression-lock) (Priority: P2)

**Reframed 2026-06-03** — the audit found this is **already solved**: `install_shim` bakes the absolute repo root **only for out-of-repo (`tmp_path`) targets**; committed in-repo shims bake `None` and have zero machine-specific paths. The remaining work is to **lock that invariant** so it can't regress (e.g. a future refactor that always bakes the abs path, or a maintainer who commits a `tmp_path`-installed shim by mistake).

**Why this priority**: A regressed committed shim is a latent CI killer on a contributor/Linux box (Spec 009). Cheap to lock now; the design already does the right thing.

**Important — do NOT "remove all absolute paths".** The abs-path baking on `tmp_path` shims is **required**: it's how the shim's Strategy-3 import locates `tests/_helpers/fake_agent`, which is what keeps the `test_fake_agent_interception` Principle-IV guard intercepting. US1 (copy-to-`tmp_path`) makes *every* runtime shim a `tmp_path` shim, so the abs-path branch becomes the normal path — and the committed shims are then only ever (re)generated by the bootstrap, with `baked=None`.

**Independent Test**: Grep all committed `tests/fixtures/quality/*/scripts/agent_call.py` for `/Users/`, `/home/`, `/private/var/folders/` → zero hits. Assert the guard test still passes (interception intact) after US1's copy-to-tmp_path lands.

**Acceptance Scenarios**:

1. **Given** a fresh checkout, **When** running `rg "/(Users|home|private/var/folders)/" tests/fixtures/quality/*/scripts/agent_call.py`, **Then** zero hits.
2. **Given** US1's copy-to-`tmp_path` is active, **When** a fixture cycle runs, **Then** the `tmp_path` shim DOES bake the abs repo root (by design) AND the fake-agent interception guard still passes.
3. **Given** a committed shim, **When** `install_shim` regenerates it in-repo (bootstrap path), **Then** the baked value is `None` (machine-agnostic) and the file is byte-stable across worktrees.

---

### User Story 3 — Fixture-bootstrap script is safe to run accidentally (Priority: P3)

`tests/fixtures/quality/_bootstrap_us3_fixtures.py` regenerates committed fixture trees when fingerprints change. Today, running it (intentional or accidental) mutates `git status`. Add a safety guard.

**Why this priority**: Low-frequency footgun; small effort. Worth doing as part of the same migration.

**Acceptance Scenarios**:

1. **Given** the bootstrap script is invoked, **When** it would modify tracked files, **Then** it prompts the user for explicit confirmation (or refuses by default and requires `--force`).

---

### Edge Cases

- **`tmp_path` out of space / permission-constrained**: `shutil.copytree` fails loud (the cycle can't run without its vault) — acceptable; fixtures are <10 MB. No silent fallback to the tracked tree (that would reintroduce the bug).
- **Concurrent runs in one checkout** (parallel CI / `pytest-xdist`): RESOLVED by construction — each test gets its own `tmp_path`, so copies never collide. The tracked tree is read-only at runtime, so concurrent reads are safe.
- **`tmp_path` shim + Strategy-3**: once US1 copies the fixture out-of-repo, `install_shim` bakes the abs repo root into the **copy's** shim (required for import resolution). This is correct and never touches the committed shim. The fake-agent interception guard MUST still pass (US2 scenario 2).
- **Bootstrap vs runtime mutation**: `_bootstrap_us3_fixtures.py` is the *only* legitimate writer of the tracked fixture tree. US3/FR-008 adds a `--force` gate so it can't mutate tracked files accidentally; the runtime harness (FR-001/002) never writes the tracked tree at all. The two paths are now cleanly separated.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `tests/quality/conftest.py::run_fixture_cycles` MUST copy the entire fixture vault from `tests/fixtures/quality/<name>/` to a `tmp_path`-scoped directory before invoking the cycle runner.
- **FR-002**: All cycle-runner invocations from the quality harness MUST point at the `tmp_path` copy, never at the source-of-truth fixture under `tests/fixtures/quality/`.
- **FR-003**: `fake_agent.install_shim(fixture.vault_dir / "scripts")` MUST install the shim into the `tmp_path` copy, NOT the tracked fixture.
- **FR-004**: After any quality cycle (success, failure, or interrupt), `git status --porcelain tests/fixtures/quality/` MUST return empty.
- **FR-005** *(reframed — regression-lock)*: The committed fake-agent shim files (`tests/fixtures/quality/*/scripts/agent_call.py`) MUST contain no machine-specific absolute paths — this is **already true** (`install_shim` bakes `None` for in-repo targets). A regression test MUST lock it. The test MUST NOT assert "no shim ever bakes an abs path" — `tmp_path` shims MUST bake the repo root for Strategy-3 import resolution (FR-003); the assertion is scoped to **committed** shims only. `install_shim`'s in-repo→`None` / out-of-repo→`repr(repo_root)` branch (fake_agent.py:1162-1166) MUST be preserved.
- **FR-006**: When a quality cycle fails, the `tmp_path` MUST be preserved (not auto-deleted) so the failed-run artifacts can be inspected. The path MUST be reported in the test output.
- **FR-007**: When all cycles succeed, the `tmp_path` MAY be cleaned automatically (pytest's `tmp_path` fixture handles this by default — verify it doesn't fight FR-006).
- **FR-008**: `tests/fixtures/quality/_bootstrap_us3_fixtures.py` MUST require an explicit `--force` flag or interactive confirmation before mutating tracked files.
- **FR-009**: A regression test MUST exist that asserts `git status --porcelain tests/fixtures/quality/` returns empty after a representative quality-fixture cycle run.
- **FR-010** *(RESOLVED — Q1: PRESERVE + CLEAN)*: The tracked `_pipeline/` baselines under `tests/fixtures/quality/<name>/` MUST be **preserved** as the pristine copy-source starting state (they make the fixtures deterministic and pin the committed `baselines/*.baseline.json`). Concretely: (a) `git rm --cached` the volatile SQLite WAL sidecars `tests/fixtures/quality/*/_pipeline/sources.db-shm` and `*-wal` (runtime cruft, never a meaningful baseline); (b) **fix `.gitignore`** (currently line ~79, `tests/fixtures/quality/**/_pipeline/`) so it no longer claims the tracked baselines are ignored — replace the blanket ignore with narrow patterns for the WAL sidecars + any genuinely per-run artifact, OR drop the line entirely now that FR-001 stops in-place mutation. After this, `git status` is clean post-gate because (i) the harness mutates only the `tmp_path` copy and (ii) the only formerly-noisy tracked files (WAL sidecars) are untracked + ignored.

### Key Entities

- **Fixture vault** (`tests/fixtures/quality/<name>/`): The source-of-truth committed fixture tree. Read-only at runtime; mutated only by the bootstrap script.
- **Runtime copy** (`<tmp_path>/<name>/`): Per-cycle ephemeral copy. Mutated by the cycle runner. Discarded on success; preserved on failure for inspection.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After running `./build.sh --quality` on a clean working tree, `git status --porcelain` returns exactly zero bytes.
- **SC-002**: Grep for `/Users/` in `tests/fixtures/quality/*/scripts/agent_call.py` returns zero hits.
- **SC-003**: A quality cycle that fails preserves its `tmp_path` and surfaces the path in the test report (one of the existing `pytest` stdout / stderr / log mechanisms).
- **SC-004**: The full `pytest tests/quality/` run wall-clock time does not regress by more than 10% vs the pre-spec baseline (copying fixtures adds I/O — verify it's acceptable).
- **SC-005**: A new regression test `tests/quality/test_fixture_isolation.py` exists, runs in the smoke gate, and asserts `git status --porcelain tests/fixtures/quality/` is clean after a fixture-vault run.
- **SC-006**: The bootstrap script `_bootstrap_us3_fixtures.py` refuses to run silently against a non-bootstrap-mode invocation.

## Assumptions

- The pytest `tmp_path` fixture (or equivalent) gives sufficient disk + permissions for the copy. Fixture sizes are <10 MB each so copying is cheap.
- The cycle runner accepts `vault_dir` as a parameter and doesn't internally hardcode the fixture path anywhere. (Audit needed during planning.)
- The bootstrap script `_bootstrap_us3_fixtures.py` is rarely run (only when fixtures need a fingerprint refresh), so the `--force` UX is acceptable friction.
- Removing the `_pipeline/` files from the gitignore + tracking is OPTIONAL for this spec (depends on the clarification answer in FR-010).

## Dependencies

- **Feeds spec 009 (Wave 2, portability + PR CI).** 009's CI runs the quality gate and (per 009/FR + this spec's SC-001) expects a pristine `git status` afterward. 026 is what *makes* that true. Land 026 before — or with — 009's quality-gate CI step. No code conflict; sequencing only.
- **No hard dependency on other unshipped specs.** Touches existing surfaces shipped in 0.3.0/0.3.1: `tests/quality/conftest.py::run_fixture_cycles`, `tests/_helpers/fake_agent.py::install_shim`, `quality.runner.resolve_fixture` (returns a fixture with `.vault_dir`), `pipeline.cycle_runner.run_cycle_steps(vault_dir, cycle)`.
- **Audit note**: `run_cycle_steps` already takes `vault_dir` as its first arg (confirmed) and does not hardcode the fixture path — so pointing it at a `tmp_path` copy (FR-002) is a drop-in. `resolve_fixture` returns `.vault_dir`; FR-001 copies that dir to `tmp_path` and the harness targets the copy.
- **Light interaction with spec 030 (quality-harness v3, Wave 1).** 030 adds a 4th metric family + fixtures; it builds on `conftest.py::run_fixture_cycles`. If 030 lands first, 026's copy-to-tmp_path refactor must cover 030's new fixtures too (same `run_fixture_cycles` seam — no extra work, just awareness).

## Acceptance coverage

Draft — evidence cells will be populated by `/speckit.tasks` for
this spec. Listed for the ADR-0008 guard so the spec is accepted
into the queue (the guard refuses any G/W/T-bearing spec without
this section).

| User Story | Evidence |
|------------|----------|
| US1 — Maintainer runs the quality gate without polluting their working tree | _(deferred to tasks.md — design-only spec; pristine-tree quality-gate coverage lands with implementation)_ |
| US2 — Committed fake-agent shims stay machine-agnostic (regression-lock) | _(deferred to tasks.md — design-only spec; machine-agnostic shim coverage lands with implementation)_ |
| US3 — Fixture-bootstrap script is safe to run accidentally | _(deferred to tasks.md — design-only spec; bootstrap safety coverage lands with implementation)_ |

## Out of Scope

- Migrating non-quality test fixtures (e.g., `tests/fixtures/spec/`, `tests/fixtures/generator/`) to `tmp_path`. Their failure mode is different.
- Reworking the fake-agent's `_SHIM_TEMPLATE` beyond removing the absolute-path fallback. Wholesale rewrite is Spec 030's domain (quality harness v3).
- Linux CI integration. Spec 009 owns that; this spec's outputs FEED INTO 009's CI definition.
