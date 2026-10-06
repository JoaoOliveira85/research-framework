# Feature Specification: Release Infrastructure v2

**Feature Branch**: `041-release-infrastructure-v2`
**Created**: 2026-05-27 (promoted from `docs/ROADMAP.md` queue item #8 + Horizon 2 "Release & distribution" during post-Wave-1 doc restructure).
**Status**: planned — DRAFT, and **its premise is superseded**. Deferred to
v2.0.0 candidates (`docs/ROADMAP.md`), issue #57.

> **Re-scope before planning (2026-09-10).** Two of this spec's three pillars
> describe a world that ended with v1.2.0. **US1 / FR-001…FR-007 (per-PR CI)**
> is reversed: since #323/#324 every workflow runs on a `v*` tag push or a
> manual dispatch only, never on `pull_request` or `push` — the owner's
> monthly Actions allowance went in under a day on per-PR runs with a macOS
> matrix, and `CLAUDE.md` § CI budget now forbids re-adding those triggers.
> The merge gate is the local suite. **Q1** (macOS on every PR?) is answered
> by that rule: macOS is opt-in on a manual dispatch. The
> **`pyproject.toml`-bump auto-detect** the Input paragraph calls working is
> also gone as a trigger — `release.yml` still reads the version, but only
> when dispatched by hand; a bump pushed to `main` releases nothing.
> What survives is **US3 / FR-008…FR-012 (the manifest-diff release gate)**
> and **FR-013 (PyPI publication)**, neither of which depends on when CI
> runs. Rewrite around those two before `/speckit.clarify`; do not plan the
> CI half as written.

Original status line, kept for the record: **Status**: planned — DRAFT (full spec; awaiting `/speckit.clarify` on 3 open questions). Soft-blocked by spec 009 (Linux CI is the foundation for per-PR CI) and spec 022 (no PyPI publication until the quality baseline is sustainably green).

**Input**: Release & distribution v1 shipped in 0.2.30 → 0.2.33 and works: release workflow auto-detects `pyproject.toml` version bumps, builds wheel + sdist + install bundle, attaches everything to a GitHub Release with auto-generated notes. v2 closes the four gaps that prevent the framework from being properly distributable: (1) no per-PR CI (regressions can ship to main from local-only checks), (2) no manifest contract check (`dist-templates/scaffold-manifest.json` can drift from `dist-templates/` contents silently), (3) no manifest-diff release gate (a template content change without a manifest version bump silently breaks `./vault update`), (4) no PyPI publication (users need GitHub Release URLs to install). Ships under the existing `research-framework` package name.

## Clarifications

### Pending — `/speckit.clarify` session TBD

- **Q1 (FR-002)**: macOS CI runner is expensive (~10x linux-runner cost on GitHub Actions). Should `ci.yml` run macOS on every PR, or only on merge-to-main? Compromise proposed: ubuntu-latest on every PR, macos-latest on `push: branches: [main]` only.
- **Q2 (FR-009)**: What's the right manifest-diff format for the release-gate failure message? Two options: (a) plain-text diff inline in the release-fail message (human-readable), (b) structured JSON the developer can pipe into `jq` (programmatic). Default proposed: both — JSON as the failure artifact + a plain-text summary in the workflow logs.
- **Q3 (FR-013)**: PyPI publishing uses OIDC trusted-publishing via GitHub Actions — does this repo's GitHub Actions OIDC token need to be registered with PyPI under the maintainer's personal account, or under a project-owned account (e.g. `research-framework` PyPI org)? The choice affects backup-publisher access if the maintainer rotates.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — PRs run CI before merge (Priority: P1)

A contributor opens a PR that breaks a test or introduces a ruff violation. The PR status shows "CI / pytest" and "CI / ruff" check failures within ~5 minutes. The PR cannot be merged (branch protection enforces required checks). The contributor sees the failure, fixes locally, pushes, and CI re-runs.

**Why this priority**: Regressions shipping to `main` come from local-environment drift. The 0.2.33 rename surfaced 10 ruff violations that local environments didn't catch but a clean CI environment would have. Per-PR CI is the cheapest defense against this class of failure.

**Independent Test**: Open a PR that intentionally fails one of the gates (e.g. a `print("oops")` that triggers ruff `T201`). Verify: the PR's CI status check turns red within 10 minutes; the failure message names the file + line; merge button is greyed out.

**Acceptance Scenarios**:

1. **Given** a PR with a passing `pytest -m "not e2e"` and clean `ruff check .`, **When** CI runs, **Then** all required checks turn green and the PR is mergeable.
2. **Given** a PR introducing a ruff violation, **When** CI runs, **Then** the `ci / ruff` check fails with the file + line + rule code in stderr.
3. **Given** a PR introducing a failing test, **When** CI runs, **Then** the `ci / pytest` check fails with the test name + assertion error.
4. **Given** branch protection on `main` requires CI checks, **When** the contributor tries to merge a red PR, **Then** GitHub blocks the merge.

---

### User Story 2 — Manifest contract drift is caught at PR time (Priority: P1)

A contributor edits `dist-templates/.codex/config.yaml` (the template) without regenerating `dist-templates/scaffold-manifest.json`. The PR's `ci / manifest-contract` check fails with `Manifest drift detected: dist-templates/.codex/config.yaml content changed but manifest entry unchanged. Run `scripts/regenerate_manifest.py` and commit the result.`

**Why this priority**: Silent manifest drift is the worst class of bug — vaults installed from a release with a stale manifest get inconsistent scaffolding, and the inconsistency only surfaces months later when someone tries to `./vault update`. Catching this at PR time is dramatically cheaper than catching it in user reports.

**Independent Test**: In a fixture PR, modify a template file (`dist-templates/settings.yaml`) and DO NOT regenerate the manifest. Verify: the `ci / manifest-contract` check fails; the failure message names the diverged file + the regen command.

**Acceptance Scenarios**:

1. **Given** a PR that modifies `dist-templates/<file>` AND updates `scaffold-manifest.json` to match, **When** CI runs, **Then** the manifest-contract check passes.
2. **Given** a PR modifying `dist-templates/<file>` BUT NOT updating `scaffold-manifest.json`, **When** CI runs, **Then** the check fails with `Manifest drift detected: <file>`.
3. **Given** a PR adding a new file to `dist-templates/`, **When** CI runs, **Then** the check fails until the manifest has a new entry for that file.
4. **Given** a PR removing a file from `dist-templates/`, **When** CI runs, **Then** the check fails until the manifest's entry for that file is removed.

---

### User Story 3 — Release gate catches missing version bumps (Priority: P1)

A maintainer cuts a release. A template file's contents changed since the last release BUT its `version` in the manifest wasn't bumped. The `release.yml` workflow stops BEFORE building the wheel with `Release gate FAILED: dist-templates/settings.yaml content changed since v0.4.0 but its manifest version (1) was not bumped. Bump to version: 2 in scaffold-manifest.json and re-cut.`

**Why this priority**: Without this gate, vaults in the wild can't detect "update needed" for templates whose content drifted but whose version field stayed flat. The contract degrades silently. This is the operationally-critical complement to US2.

**Independent Test**: Construct a tag where `dist-templates/settings.yaml` content differs from the previous tag BUT the manifest's `settings.yaml` version is unchanged. Run the release gate. Verify: workflow exits non-zero with the exact file + version-bump instruction.

**Acceptance Scenarios**:

1. **Given** every template-file content change is accompanied by a manifest-version bump, **When** the release gate runs, **Then** the release proceeds to wheel build.
2. **Given** a template file changed without a manifest version bump, **When** the release gate runs, **Then** the workflow exits non-zero with a clear error naming the file + the expected next version.
3. **Given** the release gate's output, **When** the maintainer reviews, **Then** they can copy + paste the fix into `scaffold-manifest.json` and re-cut without spelunking through git history.

---

### User Story 4 — `pip install research-framework` works (Priority: P2)

A new user reads the README, runs `pip install research-framework`, and gets the latest stable version. No need to know GitHub Release URLs, no need to download a wheel manually.

**Why this priority**: Discoverability + frictionless install. PyPI publication is the single highest-leverage change for adoption. P2 (not P1) because the current install path (download wheel from Release page) works for existing users; this is purely additive.

**Independent Test**: After this spec lands and a release ships, run `pip install research-framework` in a fresh venv. Verify: the latest released version installs; `research-framework --version` works; the package metadata matches the GitHub release.

**Acceptance Scenarios**:

1. **Given** a release has shipped to GitHub Releases, **When** the `pypi-publish` job runs, **Then** the wheel + sdist appear on `https://pypi.org/project/research-framework/`.
2. **Given** a fresh venv, **When** the user runs `pip install research-framework`, **Then** the latest stable version installs and `research-framework --version` matches.
3. **Given** a user with an older version installed, **When** they run `pip install -U research-framework`, **Then** they get the latest published version.
4. **Given** PyPI publication is additive, **When** an existing user runs `pip install <github-release-wheel-url>`, **Then** that path still works (no regression).

---

### User Story 5 — Two-step upgrade story preserved (Priority: P2)

The constraint that `pip install -U research-framework` upgrades the GENERATOR but does NOT auto-update vaults stays intact. Vault upgrade is a separate explicit `./vault update` invocation (owned by spec 027). Users who pinned a generator version don't get surprised by vault-level changes.

**Why this priority**: Constraint preservation, not a new capability. Documenting this here so it stays an explicit design decision rather than an emergent property.

**Acceptance Scenarios**:

1. **Given** a user with vault A and generator pinned to 0.4.0, **When** the user runs `pip install -U research-framework`, **Then** the generator upgrades but vault A is untouched until the user runs `./vault update`.
2. **Given** PyPI publication, **When** a user runs `pip install research-framework==0.4.0`, **Then** they can pin to a specific version and avoid auto-upgrade.

---

### Edge Cases

- What if `release.yml` is triggered by both a version bump and a manual tag push for the same version? → Idempotent: detect the existing release, skip duplicate publication, exit 0.
- What if the manifest-contract check is the only red signal but the rest of the PR is fine? → Treat as required check; do NOT allow merge. Manifest drift is a contract bug.
- What if `pypi-publish` fails (transient network)? → Retry up to 3 times with exponential backoff; if still failing, exit non-zero AND leave the GitHub Release as the artifact-of-record.
- What if a manifest-diff release-gate failure happens but the maintainer wants to override (e.g. emergency hotfix where the version-bump rule is too strict)? → Provide an explicit `--force-release-gate` workflow input (manual dispatch only); log the override in the GitHub Release notes.
- What if a contributor adds a NEW dependency to `pyproject.toml` without updating `dist-templates/scaffold-manifest.json`? → Manifest-contract check covers `dist-templates/` only; new package deps are caught by Principle V review (no new deps without ADR).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A new `.github/workflows/ci.yml` workflow MUST run on every PR (event: `pull_request`) and on pushes to `main` (event: `push: branches: [main]`).
- **FR-002**: The CI workflow MUST run `pytest -m "not e2e"` on `ubuntu-latest`. macOS coverage follows Q1's clarification (default: ubuntu-latest on every PR, macos-latest on merge-to-main only).
- **FR-003**: The CI workflow MUST run `ruff check .` on `ubuntu-latest`. Zero violations gate (per the 0.2.33 ruff baseline reset).
- **FR-004**: The CI workflow MUST run `python scripts/regenerate_manifest.py` and assert `git diff --exit-code dist-templates/scaffold-manifest.json` is empty. Drift → `FAIL` with the drift summary in stderr.
- **FR-005**: The CI workflow MUST exit non-zero on any sub-check failure; GitHub branch protection on `main` MUST require all sub-checks before merge.
- **FR-006**: The CI workflow's job names MUST be stable (`ci / pytest`, `ci / ruff`, `ci / manifest-contract`) so branch-protection settings don't need to be updated per-PR.
- **FR-007**: The CI workflow MUST cache the pip + venv state across runs (`actions/cache`) so cold-start time stays under 3 minutes on `ubuntu-latest`.
- **FR-008**: A new release gate MUST run in `release.yml` BEFORE the wheel build. The gate diffs `dist-templates/scaffold-manifest.json` against the previous tagged release's manifest.
- **FR-009**: For each file whose `content_hash` (or equivalent identity field) differs between the new tag and previous tag, the gate MUST verify the file's `version` integer in the manifest is strictly greater than the previous tag's `version` for the same file. Mismatch → `FAIL` per Q2's format clarification.
- **FR-010**: For each NEW file in the manifest (not present in previous tag), the gate MUST verify the framework's `pyproject.toml` `version` was bumped relative to previous tag. New scaffolding files require a framework version bump (already required by the release-on-bump trigger; FR-010 is a defensive double-check).
- **FR-011**: For each REMOVED file (present in previous tag, absent in new tag), the gate MUST verify same as FR-010. Removed templates are a contract break worthy of a version bump.
- **FR-012**: A manual `--force-release-gate` workflow_dispatch input MAY override FR-009/010/011 failures, but the override MUST be logged in the GitHub Release notes ("⚠️ Release gate bypassed: <reason>").
- **FR-013**: A `pypi-publish` job MUST be added to `release.yml`, running AFTER the GitHub Release asset upload succeeds. The job uses `pypa/gh-action-pypi-publish@release/v1` with OIDC trusted publishing (no static API token).
- **FR-014**: PyPI publication uses the `research-framework` package name (per the 0.2.33 rename). Pre-rename releases (0.2.30, 0.2.31, 0.2.32) stay on GitHub Releases only.
- **FR-015**: PyPI publication MUST be additive — the GitHub Release asset URLs MUST continue to work after this spec lands. No removal of legacy install paths.
- **FR-016**: `pypi-publish` job MUST be idempotent — if PyPI already has the version, exit 0 with `Version <X.Y.Z> already on PyPI; skipping.`
- **FR-017**: The two-step upgrade story (`pip install -U research-framework` upgrades generator; `./vault update` upgrades vaults) MUST be preserved. No auto-vault-update on generator install.
- **FR-018**: The README + ARCHITECTURE.md MUST be updated to surface the new `pip install research-framework` path as the primary install method (with the GitHub Release path as fallback / for pre-release versions).

### Key Entities

- **`.github/workflows/ci.yml`**: New per-PR CI workflow. Runs `pytest` / `ruff` / `manifest-contract` as required checks.
- **`scripts/regenerate_manifest.py`** (existing): Source-of-truth for `dist-templates/scaffold-manifest.json`. CI invokes this; gate compares output to committed manifest.
- **Manifest entry version field**: Each file in `scaffold-manifest.json` carries a monotonic integer `version`. Bumped whenever the file's content changes. The release gate enforces this contract.
- **Release gate**: A new `release.yml` job (`release-gate`) running BEFORE `build`. Reads previous tag's manifest, diffs, asserts version-bump policy.
- **`pypi-publish` job**: A new `release.yml` job (`pypi-publish`) running AFTER `release` (the GitHub Release creation). Uses OIDC trusted publishing to push to PyPI.
- **`research-framework` PyPI project**: The published package (per the 0.2.33 rename). OIDC trusted-publisher binding lives at `https://pypi.org/manage/account/publishing/`.
- **`--force-release-gate` workflow input**: An emergency-bypass flag (workflow_dispatch only). When set, logs the override in the release notes.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 0 regressions ship to `main` from local-environment-only checks across the 30 PRs following this spec's merge.
- **SC-002**: 0 silently-shipped manifest drifts in the 90 days following the manifest-contract check landing.
- **SC-003**: `pip install research-framework` works on a fresh ubuntu-latest container for 100% of releases shipped after FR-013 lands.
- **SC-004**: CI wall-clock < 5 minutes for the median PR (cached deps; small diff).
- **SC-005**: Time-to-detect for a template-content-without-version-bump regression drops from "discovered weeks later in user reports" to "caught at release-gate time, never ships".

## Assumptions

- Spec 009 (Linux CI matrix) ships first or co-ships with this spec. The `ci.yml` Linux runner depends on 009's expansion of the test matrix.
- Spec 022 (E2E quality harness v1) baseline is sustainably green at the time of PyPI publication. We don't publish a generator that's been failing its own quality gate.
- GitHub Actions OIDC trusted-publishing is sufficiently mature in 2026 (it shipped in 2023; should be stable).
- Maintainer has admin access to the GitHub repo (for branch protection settings) and to a PyPI account (for OIDC binding).

## Dependencies

- **Hard**: Spec 009 (Linux validation pass) — the per-PR CI on ubuntu-latest is built on 009's matrix.
- **Hard**: Spec 022 (E2E quality harness v1) — PyPI publication gated on sustainable harness green.
- **Soft**: Spec 027 (`./vault update` hardening) — the two-step upgrade preservation (FR-017) is co-designed with 027's vault-upgrade story.
- **Soft**: ADR-0007 (smoke gate mandatory) — `release.yml`'s smoke-gate-before-build invariant remains intact.

## Acceptance coverage

Draft — evidence cells populated by `/speckit.tasks` after `/speckit.clarify`.

| User Story | Evidence |
|---|---|
| US1 — PRs run CI before merge | _(deferred to tasks.md — pending /speckit.clarify on open Q1/Q2/Q3)_ |
| US2 — Manifest contract drift caught at PR time | _(deferred to tasks.md — pending /speckit.clarify on open Q1/Q2/Q3)_ |
| US3 — Release gate catches missing version bumps | _(deferred to tasks.md — pending /speckit.clarify on open Q1/Q2/Q3)_ |
| US4 — `pip install research-framework` works | _(deferred to tasks.md — pending /speckit.clarify on open Q1/Q2/Q3)_ |
| US5 — Two-step upgrade story preserved | _(deferred to tasks.md — pending /speckit.clarify on open Q1/Q2/Q3)_ |

## Out of Scope

- The wheel + sdist build itself (works in v1 since 0.2.30).
- The `./vault update` flow (spec 027 owns this).
- Signing / SBOM / supply-chain provenance (Horizon 3+; covered by a future spec).
- Multi-architecture wheels (we ship pure-Python; arch wheels aren't applicable).
- Conda / homebrew / apt package publication. PyPI is the only published index in v2.
- `research-vault` legacy package retention (the pre-rename name). Pre-rename releases stay on GitHub Releases; no PyPI tags for `research-vault`.

---

*Promote to active queue by running `/speckit.clarify` against this draft; the three pending clarifications (Q1-Q3) gate the promotion to `IMPLEMENTABLE`. Land AFTER spec 009 (Linux CI matrix) so US1 has its substrate.*
