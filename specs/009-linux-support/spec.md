# Feature Specification: Cross-Platform Portability Guard + PR CI

**Feature Branch**: `009-linux-support`
**Created**: original draft pre-0.2.x (old format); **reframed 2026-06-03** after a portability audit + clarify session.
**Status**: shipped(2026-06-04, PR #113) — SHIPPED 0.10.0 (PR #113, 2026-06-04) — reframed from "remediate macOS-isms" to "**guard portability + stand up the missing PR CI**" after a 2026-06-03 audit found the shipped code already portable. Clean scope split with spec 039 (039 owns `install.sh` behaviour; 009 owns repo-wide portability + lint gate + CI). Delivered `scripts/check_portability.py` (stdlib guard, <0.3s), `.github/workflows/ci.yml` (first PR CI; `{macos-latest REQUIRED, ubuntu-latest}`), `docs/PORTABILITY.md` (1:1 drift-locked), shellcheck cleanliness (2 justified SC2012 disables), and the 039 `--dry-run` smoke step. Landed after 039.

**Input**: The project is **macOS-first** — macOS is both the primary development platform and the primary validation target (the main use case for the whole framework). It must (a) **stay** portable as the code evolves, so a future macOS-ism never silently breaks it, and (b) **also** run on Linux — a low-cost nice-to-have, justified because the feature overlap is near-total so the marginal implementation cost is tiny. Today neither is guaranteed: there is **no PR CI at all** (`quality.yml` runs only on version tags; there is no `ci.yml`) and **no regression guard** against macOS-only constructs.

> **Post-ship note (2026-09-07).** Everything below is the record of what 009
> shipped in June 2026, and it is accurate as history. It is no longer a
> description of how this repo runs CI. PRs #323 and #324 withdrew the
> per-PR trigger and the standing macOS leg: the Actions allowance went in
> under a day on per-PR runs with a macOS matrix, which bills at 10x.
> `ci.yml` now runs on **version tags and by hand only**, with macOS opt-in
> on a manual run; the merge gate is the **local** suite each PR reports
> (`pytest`, `scripts/guards/run_all.py`, `ruff`) per CONTRIBUTING § 1.
> `scripts/check_portability.py` — 009's actual invariant — is unchanged and
> still runs in the guard battery on every local run. The contract test
> `tests/scripts/test_ci_config.py` asserts the *current* triggers, and will
> fail if a `pull_request` trigger is re-added.

## Clarifications

### Session 2026-06-03 (post-audit)

A repo-wide audit (`sed -i ''`, `~/Library`/`/opt/homebrew`/`/usr/local/bin`/`/Applications/`, `pbcopy`/`pbpaste`/macOS-`open`, bash-4 constructs) was run before authoring. Findings drove the reframe:

- **The remediation premise is ~90% stale.** Shipped code is already portable: the historical `sed -i ''` in `scripts/run_cycle.sh` was removed in spec 004; there are **no** `~/Library`/`/opt/homebrew`/`/usr/local/bin` literals in `src/` or `scripts/` (only a macOS cert *instruction* in `dist-templates/README.md`); **no** `pbcopy`/`pbpaste`/macOS-`open` command invocations. So 009 becomes **validation + regression-lock**, not remediation.
- **Q (`.specify/` scope) → OUT OF SCOPE.** The only real bash-4 offenders are `${word^^}` (×2) in `.specify/scripts/bash/create-new-feature.sh` and `.specify/extensions/git/scripts/bash/create-new-feature.sh` — **vendored spec-kit tooling** not shipped to vaults. The lint guard scopes to *shipped* scripts (`dist-templates/*.sh`, `scripts/*.sh`, `build.sh`); the 2 hits are recorded as a documented exclusion, not fixed.
- **Q (CI matrix) → macOS + Linux, macOS first-class.** The PR CI runs `{macos-latest, ubuntu-latest}`; the **macOS leg is REQUIRED** (a macOS regression fails the PR exactly like a Linux one), reflecting macOS's primary status. Linux is additive but kept green (cheap given the overlap).
- **Q (CI job contents) → FULL guard.** Each leg runs `pytest -m "not e2e"` + `ruff check .` + `ruff format --check .` + `shellcheck` over shipped `.sh` + `install.sh … --dry-run` (consuming 039).

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Portability regressions are caught deterministically (Priority: P1)
A contributor adds `sed -i '' 's/x/y/' scripts/foo.sh` (BSD-only) or a `~/Library/...` literal in `src/`. A deterministic lint **fails** in the fast local loop and in CI, naming the file + line + the portable alternative — before the change can merge and silently break Linux (or a future non-Homebrew macOS).

**Why this priority**: The code is portable *today*; without a guard it won't *stay* portable. This is the durable deliverable — it converts a one-time audit into a permanent invariant.

**Independent Test**: Add a temp `scripts/_probe.sh` containing `sed -i ''` → run `pytest tests/scripts/test_portability_guard.py` → it FAILS naming `_probe.sh`. Remove it → PASS.

**Acceptance Scenarios**:
1. **Given** a shipped `.sh` with `sed -i ''`, **When** the guard runs, **Then** it fails naming the file + line + "use `python -c` / `perl -pi -e` / a tmp-file rewrite".
2. **Given** a `~/Library`/`/opt/homebrew`/`/usr/local/bin`/`/Applications/` literal in `src/` or `scripts/`, **When** the guard runs, **Then** it fails (docs `*.md` are exempt).
3. **Given** a bash-4 construct (`mapfile`/`readarray`/`declare -A`/`${v^^}`/`${v,,}`) in a shipped `.sh`, **When** the guard runs, **Then** it fails (keeps shipped scripts bash-3.2 compatible — macOS stock bash).
4. **Given** the clean current tree, **When** the guard runs, **Then** it PASSES (locks the audited-clean state).

---

### User Story 2 — Every PR gets a green cross-platform check (Priority: P1)
A contributor opens a PR. A new `ci.yml` runs the full guard on **both** `macos-latest` and `ubuntu-latest`; both must be green to merge. Today no PR-triggered CI exists at all.

**Why this priority**: macOS parity protection + Linux validation both require CI that actually runs on PRs. This is the missing infrastructure.

**Independent Test**: Open a PR; observe `ci (macos-latest)` and `ci (ubuntu-latest)` checks both run pytest + ruff + shellcheck + `install.sh --dry-run` and report status.

**Acceptance Scenarios**:
1. **Given** a clean PR, **When** CI runs, **Then** both `macos-latest` and `ubuntu-latest` legs pass.
2. **Given** a PR that breaks a test only on Linux, **When** CI runs, **Then** the `ubuntu-latest` leg fails (and vice-versa for macOS).
3. **Given** a PR, **When** CI runs, **Then** the lint leg runs the portability guard, `ruff check`, `ruff format --check`, and `shellcheck`.

---

### User Story 3 — Shipped shell scripts pass shellcheck (Priority: P2)
All shipped `.sh` (`dist-templates/*.sh`, `scripts/*.sh`, `build.sh`) pass `shellcheck`; any intentional finding carries a `# shellcheck disable=SCxxxx` with a one-line justification.

**Acceptance Scenarios**:
1. **Given** the shipped `.sh` set, **When** `shellcheck` runs, **Then** exit 0.
2. **Given** an intentional non-portable-looking pattern, **When** it's genuinely required, **Then** it carries a documented `# shellcheck disable`.

---

### User Story 4 — Contributors have a portability contract to follow (Priority: P2)
A `docs/PORTABILITY.md` states supported OSes, required tools + minimum versions, and the rules the guard enforces — so contributors know the constraints before the guard fails them.

**Acceptance Scenarios**:
1. **Given** `docs/PORTABILITY.md`, **When** a contributor reads it, **Then** it lists macOS (primary) + Linux (parity) + Windows (out / WSL2), the tool minimums (python ≥ 3.11, git, curl, bash ≥ 3.2 for shipped scripts), and the guard's rules.
2. **Given** the doc's rules, **When** compared to the guard, **Then** they match (no drift).

---

### User Story 5 — CI exercises the installer on both platforms (Priority: P3, co-design with 039)
Each CI leg runs `bash dist-templates/install.sh tests/fixtures/quality/tech-lite --dry-run` and asserts exit 0 + zero `[FAIL]` lines — the installer-portability smoke. This is the 039/US5 pairing from 009's side.

**Acceptance Scenarios**:
1. **Given** 039 has shipped (`--dry-run` exists), **When** the CI dry-run step runs on each OS, **Then** it exits 0 with no `[FAIL]`.

---

### Edge Cases
- A genuinely macOS-only feature (e.g. a future `open`-to-Finder convenience) → document the gap in `docs/PORTABILITY.md` and make it a logged no-op on Linux, never an error.
- `shellcheck` not installed locally → the guard's shellcheck portion is CI-only; the local fast-loop guard is pure-pytest (no shellcheck dependency) so contributors aren't blocked.
- The 2 `.specify/` `${word^^}` hits → excluded by path; if `.specify/` is ever vendored differently, revisit.

## Requirements *(mandatory)*

### Functional Requirements
- **FR-001**: A deterministic portability guard (`scripts/check_portability.py` + `tests/scripts/test_portability_guard.py`) MUST fail when a **shipped** shell script (`dist-templates/*.sh`, `scripts/*.sh`, `build.sh`) contains `sed -i ''` (BSD in-place) or a bash-4-only construct (`mapfile`, `readarray`, `declare -A`, `${var^^}`, `${var,,}`).
- **FR-002**: The guard MUST fail when `src/` or `scripts/` contains a hardcoded macOS path literal (`~/Library`, `/opt/homebrew`, `/usr/local/bin`, `/Applications/`). Markdown (`*.md`) is exempt (doc instructions, incl. the archived `docs/RENAME-PLAN.md`).
- **FR-003**: `.specify/` vendored spec-kit scripts are EXCLUDED from the guard. The 2 known `${word^^}` hits in `.specify/.../create-new-feature.sh` are documented in `docs/PORTABILITY.md` as a known, accepted exclusion (not fixed).
- **FR-004**: A new `.github/workflows/ci.yml` MUST trigger on `pull_request` and `push` to the default branch, with `strategy.matrix.os: [macos-latest, ubuntu-latest]`. **The macOS leg is REQUIRED** (not `continue-on-error`).
- **FR-005**: Each CI matrix leg MUST run, in order: `pip install -e .[dev]`; `pytest -m "not e2e"`; `ruff check .`; `ruff format --check .`; `shellcheck` over the shipped `.sh` set; and `bash dist-templates/install.sh tests/fixtures/quality/tech-lite --dry-run` (exit 0, zero `[FAIL]`).
- **FR-006**: `shellcheck` MUST pass over `dist-templates/*.sh`, `scripts/*.sh`, `build.sh`. Intentional findings carry `# shellcheck disable=SCxxxx` + a one-line why.
- **FR-007**: The portability guard (FR-001/002) MUST be a **pytest** that runs in the fast local loop (`pytest -m "not e2e"`) AND in CI — so contributors catch violations before pushing. It MUST NOT depend on `shellcheck` being installed locally.
- **FR-008**: `docs/PORTABILITY.md` MUST list supported OSes (macOS primary, Linux parity, Windows out → WSL2), required tools + minimum versions (python ≥ 3.11, git, curl; bash ≥ 3.2 for shipped scripts), the guard's enforced rules, and the `.specify/` exclusion (FR-003).
- **FR-009**: The CI dry-run step (FR-005) depends on spec 039's `--dry-run`. Until 039 merges, the step is either (a) added with 039, or (b) tolerant of a missing flag (skip-with-note). 009 MUST NOT make the dry-run step fail merely because 039 hasn't landed. **Land 009 after 039.**

### Key Entities
- **Portability guard** — `scripts/check_portability.py` (importable + CLI; exit non-zero on violation) wrapped by `tests/scripts/test_portability_guard.py`. The single source of truth for the rules; `docs/PORTABILITY.md` documents them.
- **`ci.yml`** — the new PR CI workflow; matrix `{macos-latest, ubuntu-latest}`.
- **Shipped-script set** — `dist-templates/*.sh`, `scripts/*.sh`, `build.sh` (the scripts that reach end users or run in the project's own automation). Excludes `.specify/`.
- **`docs/PORTABILITY.md`** — the contributor-facing portability contract.

## Success Criteria *(mandatory)*

### Measurable Outcomes
- **SC-001**: A PR adding `sed -i ''` to any shipped `.sh` fails the portability guard (and CI) deterministically, naming file + line.
- **SC-002**: `ci.yml` shows green `macos-latest` AND `ubuntu-latest` checks on a clean PR; a platform-specific break fails the matching leg.
- **SC-003**: `shellcheck dist-templates/*.sh scripts/*.sh build.sh` exits 0.
- **SC-004**: The portability guard runs in < 2 s in the fast local loop and requires no non-stdlib tool.
- **SC-005**: `docs/PORTABILITY.md` exists; an audit confirms its rules == the guard's rules (no drift).

## Assumptions
- macOS is the primary platform; Linux parity is cheap because feature overlap is near-total (user direction, 2026-06-03).
- `shellcheck` is available on GitHub-hosted runners (it is, pre-installed on both `macos-latest` and `ubuntu-latest`).
- The `tech-lite` quality fixture is a valid `--dry-run` target on both OSes.
- Spec 039 lands first (or concurrently); 009's CI dry-run step consumes its `--dry-run`.

## Dependencies
- **Hard (sequencing)**: Spec 039 — CI's `install.sh --dry-run` step (FR-005/009). Land 039 before 009.
- **Soft**: Spec 041 (release-infrastructure-v2, Horizon) may later extend `ci.yml`; 009 establishes it. No conflict — 009 owns the initial PR CI; 041 extends.
- **Tooling**: adds `shellcheck` as a **CI-only** tool (not a Python runtime dep — Principle V intact).

## Acceptance coverage

Draft — evidence cells will be populated by `/speckit.tasks` for
this spec. Listed for the ADR-0008 guard so the spec is accepted
into the queue (the guard refuses any G/W/T-bearing spec without
this section).

| User Story | Evidence |
|------------|----------|
| US1 — Portability regressions are caught deterministically | `tests/scripts/test_portability_guard.py` (`test_bsd_sed_in_place_is_flagged`, `test_hardcoded_macos_path_flagged_in_code`, `test_macos_path_in_markdown_is_ignored`, `test_bash4_uppercase_expansion_flagged`, `test_specify_dir_is_excluded`, `test_clean_tree_passes`) |
| US2 — Every PR gets a green cross-platform check | `tests/scripts/test_ci_config.py` (`test_matrix_is_macos_and_ubuntu`, `test_triggers_on_pull_request_and_push_main`, `test_macos_leg_is_required`, `test_each_leg_runs_the_full_guard_set`) |
| US3 — Shipped shell scripts pass shellcheck | `tests/scripts/test_ci_config.py::test_each_leg_runs_the_full_guard_set` (asserts the `shellcheck` step); `shellcheck dist-templates/*.sh scripts/*.sh build.sh` exits 0 locally + in CI |
| US4 — Contributors have a portability contract to follow | `tests/scripts/test_portability_guard.py::test_portability_doc_matches_guard` (SC-005 doc↔guard drift-lock against `docs/PORTABILITY.md`) |
| US5 — CI exercises the installer on both platforms | `tests/scripts/test_ci_config.py::test_runs_installer_dry_run_smoke` (asserts the `install.sh … --dry-run` step is present and required) |

## Out of Scope
- **Windows native** (WSL2 inherits Linux).
- **`.specify/` vendored tooling** portability (incl. the 2 `${word^^}` hits) — FR-003.
- **Reimplementing macOS-only features on Linux** — document + graceful no-op, don't port.
- **General release infrastructure** beyond standing up PR CI (spec 041, Horizon).
- **`install.sh` runtime behaviour** — spec 039 (clean split, Q4).
