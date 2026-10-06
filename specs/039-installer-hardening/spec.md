# Feature Specification: Installer Hardening

**Feature Branch**: `039-installer-hardening`
**Created**: 2026-05-27 (promoted from `docs/ROADMAP.md` Horizon 2 "Robust installer" during post-Wave-1 doc restructure).
**Status**: shipped(2026-06-04, PR #109) — SHIPPED 0.10.0 (PR #109, 2026-06-04) — `install.sh` now resolves `TARGET` with `$1` > `${VAULT_DIR}` > `ROOT_DIR` (fixing the F2 `./vault update` bug), splits bundle inputs (`ROOT_DIR` wheel/skills) from vault writes (`TARGET` venv/scaffold/summary), adds `--dry-run`, `uname`-based OS + three-tier dependency probing with `[FAIL]`/`[WARN]`/`[INFO]` grammar, idempotent fast re-run (<5s when `.venv` + `install_summary.json` exist), and atomic `TARGET/_pipeline/install_summary.json` on every run. Preserves TTY capture, log tee, spec-051 stale-venv rebuild, check-skills preflight, and the onboarding wizard. Six new pytest modules; spec-027 `user_authored` clobber-guard TODO remains.

**Input**: Promote `dist-templates/install.sh` from "works on macOS in the happy path" to "single command bootstraps a fresh machine on macOS or Linux, idempotent on re-run, supports `--dry-run`, gracefully handles missing system dependencies, respects its `${VAULT_DIR}` argument." Two concrete real-world failure modes drive urgency: (1) Linux installs silently degrade because the script assumes macOS + Homebrew; (2) `install.sh` ignores its `${VAULT_DIR}` argument entirely (2026-05-26 feeds-vault archaeology F2) — the script unconditionally `cd`s to its own directory, so `bash install.sh /path/to/vault` operates on `dist-templates/` instead. This breaks `./vault update`. Hard correctness bug.

## Clarifications

### Session 2026-06-03

- **Q1 (FR-005) — dependency-probe aggressiveness → MIXED.** `python ≥ 3.11`, `git`, `curl` are **MANDATORY** (missing → non-zero exit + the exact install command); `rsync`, `claude` CLI are **WARN** (missing → warn + continue in degraded mode); `codex`, `weasyprint`, `gh` CLI are **INFORMATIONAL** (missing → info log). The three-tier classifier is owned by this spec and reviewed each release.
- **Q2 (FR-009) — dry-run CLI validation depth → PRESENCE-CHECK ONLY.** `--dry-run` verifies `claude`/`codex` with `command -v` (binary resolvable on `PATH`) and does **NOT** invoke them (no `--version` or other no-op call). Rationale: keeps dry-run cheap and decoupled from CLI-invocation contracts that drift; a present-but-broken CLI surfaces at real-run time, not dry-run.
- **Q3 (FR-001/FR-002) — no-arg behaviour → DEFAULT TO `ROOT_DIR` (install-in-place).** *(Corrected during clarify after reading the shipped `install.sh` + the `./vault` shim: a no-arg `./install.sh` is the **tarball happy path**, not an error — the spec's original "scenario 3 = fallback/error" framing pre-dated the code read.)* `TARGET` resolves as `$1` > `${VAULT_DIR}` > `ROOT_DIR`; no-arg ⇒ install in place (info-logged). The real F2 bug is the *inverse* — `./vault update` runs `install.sh "${VAULT_DIR}"` from a tmpdir and the current script ignores `$1`, operating on the tmpdir so the vault is never refreshed. Fix: honour `$1`/`${VAULT_DIR}`; source the **wheel** from `ROOT_DIR` but write `.venv`/scaffold/`rv`/`install_summary.json` into `TARGET`. The prior draft's "remove fallback in 0.6.0" is moot — install-in-place is the supported default, not a deprecated fallback.
- **Q4 (scope boundary with spec 009) — CLEAN SPLIT.** **039 owns `install.sh` runtime behaviour** — `VAULT_DIR` resolution, OS branch, dependency probing, `--dry-run`, idempotency, `install_summary.json`. **009 owns repo-wide portability** — the `sed -i ''` / `~/Library` / `open` / `pbcopy` audit + fixes, the `shellcheck` + no-hardcoded-paths lint gate, and the `ubuntu-latest` CI matrix job (which *exercises* 039's installer via `--dry-run`). 009 is reformatted into the modern User-Story template scoped to that. The two specs co-design but ship as separate PRs.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — `install.sh` respects its destination argument (Priority: P1, BLOCKER)

The operator runs `bash install.sh /home/me/my-vault`. The script operates on `/home/me/my-vault`, NOT on `dist-templates/`. After install, `/home/me/my-vault/research.spec.md` + `/home/me/my-vault/.venv/` exist; `dist-templates/` is untouched.

The same applies when called from `./vault update` (which passes `${VAULT_DIR}`).

**Why this priority**: This is a CORRECTNESS bug. Without this fix, `./vault update` silently writes to the wrong location AND `install.sh /path/to/vault` is effectively a no-op for the intended vault. The 2026-05-26 feeds-vault archaeology surfaced this as F2 (one of two critical bugs). Fixing this is a prerequisite for ANY subsequent installer work.

**Independent Test**: Run `bash install.sh /tmp/test-vault-XXXX` in a clean shell. Verify: `/tmp/test-vault-XXXX/research.spec.md` exists with the scaffolded content; `dist-templates/research.spec.md` is UNCHANGED from its committed version (use `git diff dist-templates/research.spec.md` → empty).

**Acceptance Scenarios**:

1. **Given** the operator runs `bash install.sh /home/me/my-vault`, **When** the install completes, **Then** all scaffold files land in `/home/me/my-vault/`, NOT in `dist-templates/`.
2. **Given** `./vault update` invokes `install.sh` with `${VAULT_DIR}` exported, **When** the install completes, **Then** scaffold files land in the existing vault location.
3. **Given** the operator runs `install.sh` with NO argument AND NO `${VAULT_DIR}` set (the tarball happy path), **When** the script starts, **Then** `TARGET` defaults to `ROOT_DIR`, the install proceeds in place, and an info line names the resolved target (Q3 = default to ROOT_DIR — no error).

---

### User Story 2 — Linux install matches macOS install (Priority: P1)

An operator on Ubuntu 24.04 (or Fedora, or Arch) runs `bash install.sh /home/me/my-vault`. The script detects Linux, probes dependencies via `apt`/`dnf`/`pacman`, and either bootstraps the venv + scaffold successfully OR exits non-zero with a clear list of missing system packages + the exact install command for the operator's distro.

**Why this priority**: Spec 009 (Linux validation pass) is a critical-path Wave-2-adjacent spec. Without 039, Linux support is silently degraded; with 039, Linux is a first-class target. Pairs with 009's CI matrix expansion.

**Independent Test**: Run `bash install.sh /tmp/test-vault-XXXX --dry-run` inside an Ubuntu 24.04 container without `python3.11` installed. Verify: exit code non-zero; stderr names the missing package + the exact `apt install python3.11` command.

**Acceptance Scenarios**:

1. **Given** a fresh Ubuntu 24.04 host with `python3.11`, `git`, `curl` installed, **When** the operator runs `bash install.sh /tmp/v`, **Then** the install completes successfully.
2. **Given** a Linux host missing `python3.11`, **When** the operator runs `bash install.sh /tmp/v`, **Then** the script exits non-zero with `Missing dependency: python3.11. Install via: apt install python3.11` (or distro-appropriate equivalent).
3. **Given** a host with no recognized package manager (e.g. Alpine without `apk` configured), **When** dependencies are missing, **Then** the script prints raw install commands the operator can copy + paste.

---

### User Story 3 — `--dry-run` shows planned actions without mutating (Priority: P2)

The operator runs `bash install.sh /home/me/my-vault --dry-run`. The script reports every action it would take (`would create dir`, `would install package`, `would write file`) with NO filesystem changes. Exit 0 if the install would succeed, non-zero if any blocker is detected.

**Why this priority**: Two use cases: (1) new users surveying the install before committing; (2) CI gates validating installer logic against fixture vaults. Both are high-value, but the bug fix from US1 + Linux support from US2 are higher priority.

**Independent Test**: Run `bash install.sh /tmp/test --dry-run` against a fresh tempdir, then `ls /tmp/test` and verify EMPTY (no files written).

**Acceptance Scenarios**:

1. **Given** `--dry-run` mode, **When** the script runs against a valid destination, **Then** stdout reports planned actions and exit code reflects whether the real install would succeed.
2. **Given** `--dry-run` mode against a fresh destination, **When** the script completes, **Then** the destination directory either doesn't exist or contains zero files.
3. **Given** spec 009's Linux CI workflow, **When** it runs `bash install.sh tests/fixtures/quality/tech-lite --dry-run`, **Then** the workflow's "installer dry-run" step turns green.

---

### User Story 4 — Re-running `install.sh` is idempotent (Priority: P2)

The operator runs `install.sh /path/to/vault` twice in a row. The second invocation:
- Exits 0 within 5 seconds.
- Does NOT re-download wheels already present in `.venv/`.
- Does NOT clobber files the operator customized after install (depends on spec 027's `user_authored` vs `user_customizable` flag split; co-design with 027).

**Why this priority**: Idempotency is the foundation for `./vault update` (spec 027) and for unattended/CI-driven installs. Without it, every re-run is a destructive overwrite.

**Acceptance Scenarios**:

1. **Given** a freshly installed vault, **When** the operator re-runs `install.sh` against it, **Then** the script exits 0 in <5s with `Vault already installed at <PATH>; updating only changed scaffolds`.
2. **Given** an installed vault where the operator customized `settings.yaml`, **When** the operator re-runs `install.sh`, **Then** `settings.yaml` is NOT overwritten (per spec 027's preservation contract).
3. **Given** the script re-runs, **When** wheels are already present in `.venv/`, **Then** `pip install` is invoked with `--prefer-binary --no-deps` or simply skipped if metadata signals no update.

---

### User Story 5 — Pairs with spec 009's Linux CI (Priority: P3)

Spec 009 adds an `ubuntu-latest` job to `.github/workflows/ci.yml`. That job runs `bash install.sh tests/fixtures/quality/tech-lite --dry-run` against a fixture vault. The "tested on Linux" green check appears in PR status without requiring an actual full install.

**Why this priority**: Co-design with spec 009. The CI validation is the public signal that Linux is supported.

**Acceptance Scenarios**:

1. **Given** spec 009's ubuntu-latest job in CI, **When** a PR is opened, **Then** the "installer dry-run" step passes on Linux.
2. **Given** spec 009's CI matrix is expanded to include macos-latest, **When** the same PR runs, **Then** the macOS dry-run also passes (no macOS regression).

---

### Edge Cases

- What if `${VAULT_DIR}` is set BUT the operator passes a different path as `$1`? → `$1` wins (positional arg takes precedence over env var). Behavior consistent with most shell tools.
- What if the destination path doesn't exist? → Create it (mkdir -p), then proceed.
- What if the destination path exists but isn't writable? → Fail loudly with the exact path + uid/gid mismatch context.
- What if `python3.11` exists but the user's `python3` symlink points elsewhere? → Probe with explicit `python3.11 --version`; don't trust `python3`.
- What if a network failure happens mid-`pip install`? → Exit non-zero, leave `.venv/` partial; re-run resumes (idempotency via pip's own resumability).
- What if Homebrew is installed on Linux (it can be)? → Detect via `command -v brew`; offer Homebrew-flavored installs as a third option after `apt`/`dnf`.
- What if `--dry-run` AND a real-mode arg are both passed? → `--dry-run` wins; emit a warning.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `install.sh` MUST resolve a single target directory `TARGET` with precedence `$1` > `${VAULT_DIR}` > `ROOT_DIR` (the script's own dir; FR-002). `TARGET` MUST be created with `mkdir -p` if absent. All install-state — `.venv/`, the `rv` shim, `research.spec.md`, scaffold files, `_pipeline/install_summary.json` — lands under `TARGET`.
- **FR-002**: When neither `$1` nor `${VAULT_DIR}` is set, `TARGET` defaults to `ROOT_DIR` — the **tarball install-in-place happy path** — and the script MUST NOT error (Q3 = default to ROOT_DIR). An info line `[install] installing in place at <ROOT_DIR>` is emitted so the resolved target is explicit in `install.log`. The bug being fixed is the *inverse*: when `$1`/`${VAULT_DIR}` IS provided (the `./vault update` path), it MUST be honoured rather than silently ignored.
- **FR-003**: Every `cd`, `cp`, `mkdir`, venv-create, and scaffold-write MUST target `TARGET` (FR-001), NOT the script's own directory. **Exception — the bundled wheel** (`research_framework-*.whl`) is SOURCED from `ROOT_DIR` (it ships in the bundle/tmpdir, not the vault) and `pip install`-ed into `TARGET/.venv`. Concretely: today's `cd "${ROOT_DIR}"` (line 25) becomes `cd "${TARGET}"`, while the wheel glob (line 186) stays anchored to `${ROOT_DIR}`. This source-vs-target split is the core of the F2 fix.
- **FR-004**: The script MUST detect the host OS via `uname -s` and branch to `darwin` / `linux` paths. Other OSes (`FreeBSD`, etc.) MUST fail with a clear "unsupported OS" message and exit code 3.
- **FR-005**: The script MUST probe required dependencies in three tiers (Q1 = Mixed):
  - **MANDATORY**: `python` ≥ 3.11, `git`, `curl`. Missing → exit non-zero with the exact install command for the detected package manager.
  - **WARN**: `rsync`, `claude` CLI. Missing → warn + continue (degraded mode); name recorded in `degraded_modes`.
  - **INFORMATIONAL**: `codex`, `weasyprint`, `gh` CLI. Missing → log at info level.
- **FR-006**: For the `darwin` branch, the script MUST offer `brew install` commands for missing deps. For the `linux` branch, MUST detect `apt`/`dnf`/`pacman`/`apk` and offer the appropriate install command.
- **FR-007**: When no recognized package manager exists, the script MUST print raw install commands the operator can copy + paste. Never silently fail.
- **FR-008**: The script MUST accept a `--dry-run` flag. In dry-run mode, EVERY filesystem-mutating operation MUST be replaced with a stdout line of the form `[dry-run] would <action> <target>`. Exit code reflects whether the real install would succeed (non-zero if any blocker detected).
- **FR-009**: Dry-run validation MUST cover directory creation, file copy/write, and package install. CLI validation (Q2 = presence-check only) MUST use `command -v claude` / `command -v codex` to confirm the binary is on `PATH`; it MUST NOT invoke the CLIs (no `--version`). A missing `claude` is reported per its FR-005 WARN tier; a missing `codex` per its INFORMATIONAL tier.
- **FR-010**: Re-running `install.sh` against an already-installed vault MUST exit 0 within 5 seconds AND MUST NOT clobber files protected by spec 027's `user_authored` flag.
- **FR-011**: Re-running MUST NOT re-download wheels already present in `.venv/`. The script delegates to `pip`'s own resumability for partial states.
- **FR-012**: All informational/warning/error output MUST be machine-readable enough that spec 009's Linux CI workflow can grep for "[FAIL]" / "[WARN]" lines and surface them in PR comments.
- **FR-013**: The script MUST emit a final `install_summary.json` at `<VAULT_DIR>/_pipeline/install_summary.json` containing: `framework_version`, `installed_at` (ISO8601), `os` (`darwin`/`linux`), `os_version`, `python_version`, `package_manager`, `dry_run` (bool), `warnings`, `degraded_modes` (list of dep names that warned). Idempotent — re-run updates this file.

### Key Entities

- **`install.sh`**: The single-entry installer at `dist-templates/install.sh`. Behavior changes per this spec; binary location does NOT change.
- **`${VAULT_DIR}` / positional `$1`**: The target directory for the install. Resolution per FR-001.
- **`install_summary.json`**: Per FR-013. Persists across runs as the install audit log. Read by `./vault update` (spec 027) for upgrade decisions.
- **OS branch**: Detected from `uname -s`. Determines package-manager probing logic in FR-006.
- **Package manager probe**: Per branch — `brew` (darwin), `apt` / `dnf` / `pacman` / `apk` (linux), in detection precedence.
- **Dependency tier classifier** (per Q1 / FR-005): Mandatory / Warn / Informational. Owned by this spec; reviewed at every release.
- **`--dry-run` mode marker**: An env var (`INSTALL_DRY_RUN=1`) propagated to all child invocations so nested scripts honor the same mode.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After this spec lands, `bash install.sh /tmp/vault-test` on a fresh Ubuntu 24.04 container installs successfully (all deps probed + present) OR exits non-zero with the exact missing-package install command (deps missing). Zero silent failures.
- **SC-002**: `bash install.sh /tmp/vault-test --dry-run` writes zero files to `/tmp/vault-test/` (verified by `find /tmp/vault-test/ -type f | wc -l` → 0).
- **SC-003**: `bash install.sh /existing-vault` (already installed) exits 0 in <5 seconds AND `git status` in `/existing-vault` shows no unwanted file changes.
- **SC-004**: Spec 009's Linux CI workflow has an "installer dry-run" step that passes on PRs against the `tech-lite` fixture.
- **SC-005**: `./vault update` (spec 027) correctly invokes `install.sh ${VAULT_DIR}` and observes the scaffold updates land in `${VAULT_DIR}`, not in `dist-templates/` (regression test for the FR-002 bug fix).

## Assumptions

- Operators on Linux have one of: `apt`, `dnf`, `pacman`, or `apk`. If none, raw install commands are sufficient (operator copies + pastes).
- Spec 027 (`./vault update` hardening) is co-designed with this spec — the `user_authored` vs `user_customizable` flag split lives in 027; this spec just honors it.
- Spec 009 (Linux CI matrix) lands in parallel or just before this spec; the CI dry-run validation in US5 depends on 009's workflow expansion.
- Python 3.11+ is available via the system package manager on all supported distros (Ubuntu 22.04+, Fedora 39+, Arch, macOS via Homebrew).

## Dependencies

- **Hard**: Spec 027 (`./vault update` hardening) — `user_authored` flag for FR-010.
- **Hard**: Spec 009 (Linux validation pass) — CI matrix that exercises this spec's improvements.
- **Soft**: Spec 020 (source-module architecture) — modules' own install steps may flow through this script for env-var preflight (per spec 038's FR-002).
- **Soft**: Spec 040 (vault reports + delivery) — `weasyprint` is an Informational dep here; spec 040 changes that to Mandatory if reports become first-class.

## Acceptance coverage

Draft — evidence cells will be populated by `/speckit.tasks` for
this spec. Listed for the ADR-0008 guard so the spec is accepted
into the queue (the guard refuses any G/W/T-bearing spec without
this section).

| User Story | Evidence |
|------------|----------|
| US1 — `install.sh` respects its destination argument | `tests/scripts/test_install_target_resolution.py` (precedence, in-place default, F2 wheel-source-vs-target lock) |
| US2 — Linux install matches macOS install | `tests/scripts/test_install_os_branch.py` + `tests/scripts/test_install_dep_probe.py` |
| US3 — `--dry-run` shows planned actions without mutating | `tests/scripts/test_install_dry_run.py` (SC-002 file-count oracle) |
| US4 — Re-running `install.sh` is idempotent | `tests/scripts/test_install_idempotency.py` (Step-2 `@pytest.mark.skip` until spec 027) |
| US5 — Pairs with spec 009's Linux CI | `tests/scripts/test_install_dep_probe.py` + `tests/scripts/test_install_dry_run.py` lock the `[FAIL]`/`[WARN]`/`[INFO]` grammar + `--dry-run` contract that 009's `ubuntu-latest` job consumes; the CI wiring itself lands in spec 009 |

## Out of Scope

- Windows native support. WSL2 would inherit Linux behavior; native Windows is not on the roadmap.
- Vendoring system tools (`git`, `curl`, `rsync`, `python`) — we probe + advise, we don't install them ourselves. (Different scope philosophy; an "embedded" installer is its own spec.)
- `./vault update`'s end-to-end polish — spec 027 owns the upgrade flow; this spec owns just `install.sh`.
- Provisioning of cloud credentials (Anthropic API key, etc.) — that's a vault-level concern, not an installer concern. Module preflight (spec 038 FR-002) handles credential probes.
- Multi-vault install in a single command (`install.sh vault-A vault-B vault-C`). Out for v1; can be added if a concrete use case emerges.

---

*Clarified 2026-06-03 (Q1–Q4 resolved). Plan → `plan.md`; Phase-0 decisions → `research.md`; `install_summary.json` contract → `contracts/`; tasks → `tasks.md`. Land paired with spec 009 (shared `install.sh` surface; clean scope split per Q4) — separate PRs.*
