# Tasks — Installer Hardening (039)

> **Ledger** — this spec shipped; the boxes below are a historical record, not a live gate (CONTRIBUTING.md § 2). The Status header in `spec.md` is the source of truth for what shipped.

**Spec**: `specs/039-installer-hardening/spec.md` · **Plan**: `plan.md` · **Research**: `research.md`
**Format**: `[ID] [P?] [Story?] Description with file path` · `[P]` = parallelizable (distinct files, no ordering dep).

> **Foreman note (ADR-0010)**: this is `/speckit.tasks` output. The formal
> `### Testing Requirements` blocks are added by the **test-design subagent** at the
> pre-implement step (run blind to `install.sh`, in a fresh worktree). The test
> file names + assertions below are the design intent for that step to formalize.
> TDD ordering is already encoded (tests precede implementation within each story).

> **Run tests via `.venv/bin/python -m pytest`** (pyenv base python has a stale
> editable install). Keep new tests **non-pty** (sandbox pty-exhaustion).

## Phase 1: Setup
- T001 [Setup] Confirm branch `039-installer-hardening`; capture a green baseline: `.venv/bin/python -m pytest tests/scripts/ -k install -q` + `ruff check .` + `ruff format --check .`. The two existing install tests (`tests/scripts/test_install_venv_staleness.py`, `tests/scripts/test_install_sh_tty_handling.py`) are the regression tripwire — note their current pass count. *(baseline: 15 passed)*

## Phase 2: Foundational (blocking prerequisites — shared by all stories)
- T002 Foundational plumbing in `dist-templates/install.sh` (no behaviour redirected yet — just the primitives), inserted **after** the existing `ROOT_DIR`/TTY-capture/log-tee blocks (lines 24–80) and the arg-parse loop (82–92):
  - (a) **TARGET resolution** — `TARGET="${1:-${VAULT_DIR:-${ROOT_DIR}}}"` with positional `$1` taking precedence over `${VAULT_DIR}`; `mkdir -p "${TARGET}"`; emit `[install] installing in place at <TARGET>` when TARGET resolved to ROOT_DIR. (FR-001/FR-002)
  - (b) **dry-run primitive** — parse `--dry-run` into the existing arg loop; honour `INSTALL_DRY_RUN=1`; add a `run() { if dry; then echo "[dry-run] would $*"; else "$@"; fi }` wrapper + `export INSTALL_DRY_RUN` for children. (FR-008)
  - (c) **status-line helpers** — `fail()`/`warn()`/`info()` emitting the `[FAIL]`/`[WARN]`/`[INFO]` grammar (`contracts/install-summary.contract.md` §2) to the correct stream + a `DEGRADED_MODES` array accumulator. (FR-012)

## Phase 3: User Story 1 — install.sh respects its destination (P1) 🎯 MVP
**Goal**: fix the F2 bug — `$1`/`${VAULT_DIR}` honoured; wheel from `ROOT_DIR`, everything else into `TARGET`.

### Tests (write first — RED)
- T003 [P][US1] `tests/scripts/test_install_target_resolution.py`: TARGET precedence (`$1` > `${VAULT_DIR}` > `ROOT_DIR`); no-arg ⇒ ROOT_DIR (in-place, no error); `mkdir -p` creates an absent TARGET; **F2 regression lock** — with a fixture bundle (fake wheel in ROOT_DIR), the venv + scaffold land under TARGET while `ROOT_DIR`/`dist-templates` is untouched (`git diff` empty). Extract-fn/sandbox-bash harness for unit cases + one `@pytest.mark.slow` real `python -m venv` case.

### Implementation
- T004 [US1] Redirect write-targets in `dist-templates/install.sh` from `ROOT_DIR` → `TARGET`: `cd` (line 25 → `cd "${TARGET}"`), `VENV_DIR` (70), `INSTALL_LOG` placement, the `rv` shim heredoc + path (213–218), `SPEC_FILE`/`SETTINGS_FILE`/`SETTINGS_CODEX` (251–253), `check-skills --vault` (233 → `${TARGET}`), and the wizard's `(cd "${ROOT_DIR}" …)` write sites (439). **Keep anchored to `ROOT_DIR`**: the wheel glob (186) and the `.agents/skills` source (232). (FR-003)
- T005 [US1] Run T003 + the two existing install tests; confirm in-place (no-arg) behaviour is byte-unchanged and the F2 fix works. **US1 / MVP complete.**

## Phase 4: User Story 2 — Linux install matches macOS (P1)
### Tests (write first — RED)
- T006 [P][US2] `tests/scripts/test_install_os_branch.py`: `uname -s`→`darwin`/`linux`; unsupported OS → exit **3**; pkg-mgr probe precedence (`apt`>`dnf`>`pacman`>`apk`; `brew` on darwin; `brew`-on-linux fallback); no recognised manager → raw copy-paste commands (FR-007). (FR-004/006)
- T007 [P][US2] `tests/scripts/test_install_dep_probe.py`: Mixed tiers — `python`/`git`/`curl` missing → `[FAIL]` + exact install cmd + non-zero exit; `rsync`/`claude` missing → `[WARN]` + continue + appended to `degraded_modes`; `codex`/`weasyprint`/`gh` missing → `[INFO]`. Presence-check uses `command -v` only — a poisoned `claude` on PATH (would exit 1 if invoked) MUST NOT be run. (FR-005/009)

### Implementation
- T008 [US2] Add `uname -s` OS branch + package-manager probe to `install.sh` (FR-004/006/007); the existing Python-3.11 check (139–153) becomes the first MANDATORY-tier probe.
- T009 [US2] Add the three-tier dependency probe (FR-005) via `fail()`/`warn()`/`info()` + `command -v` (FR-009); populate `DEGRADED_MODES`.

## Phase 5: User Story 3 — --dry-run shows planned actions without mutating (P2)
### Tests (write first — RED)
- T010 [P][US3] `tests/scripts/test_install_dry_run.py`: every mutating op suppressed (`find "$TARGET" -type f` minus `_pipeline/install_summary.json` == 0, SC-002); `[dry-run] would …` lines emitted for dir/venv/pip/file ops; exit 0 when the real install would succeed, non-zero when a MANDATORY dep is missing; CLI presence-check still runs (no invocation).

### Implementation
- T011 [US3] Route all mutating ops through the `run()` wrapper (T002b): `mkdir`, `python -m venv` (176), `pip install` (181/194), the `rv` heredoc+`chmod` (213–218), `cp`/scaffold writes, `install_summary.json` write. Dry-run prints, real-run executes. (FR-008/009)

## Phase 6: User Story 4 — re-running install.sh is idempotent (P2)
### Tests (write first — RED)
- T012 [P][US4] `tests/scripts/test_install_idempotency.py`: re-run with existing `TARGET/.venv` + `install_summary.json` → fast path, exit 0 in < 5 s (SC-003), `[install] vault already installed …`, pip-skip branch taken; **Step-2 (027-gated)** a `user_authored`-flagged file is not clobbered — `@pytest.mark.skip(reason="gated on spec 027 user_authored flag")` until 027 lands.

### Implementation
- T013 [US4] Add re-run detection + fast path (FR-010/011): detect existing install; skip venv-create; rely on pip resumability/skip for present wheels. **Step 1**: refresh scaffold + update summary. **Step 2 (cross-ref 027)**: gate scaffold overwrite on the `user_authored` predicate (left as a clearly-marked TODO hook until 027 ships the flag).

## Phase 7: User Story 5 — pairs with spec 009's Linux CI (P3)
- T014 [US5] No `install.sh` change. Verify 039's `--dry-run` exit-code + `[FAIL]`-line grammar satisfy the contract spec 009's `ubuntu-latest` job consumes (`bash install.sh tests/fixtures/quality/tech-lite --dry-run` → exit 0, zero `[FAIL]`). The CI job + `shellcheck` + the repo-wide `sed -i ''`/`~/Library` sweep are **spec 009's** tasks (clean split per Q4). Cross-link from 009.

## Phase 8: install_summary.json + Polish
### Tests (write first — RED)
- T015 [P] `tests/scripts/test_install_summary_json.py`: schema per `contracts/install-summary.contract.md` (all fields, correct types); atomic temp-file+rename write; idempotent overwrite on re-run; `exit_status` ok/degraded/failed mapping; dry-run summary exempt from the SC-002 file count.
### Implementation
- T016 Emit `TARGET/_pipeline/install_summary.json` (FR-013) atomically at the end of **every** run (real or dry) with the `exit_status` mapping (ok ⟺ no WARN; degraded ⟺ MANDATORY ok + ≥1 WARN/INFO miss; failed ⟺ MANDATORY miss/step fail, file still written, non-zero exit).
- T017 [Polish] Populate the spec's Acceptance-coverage evidence cells with the test filenames; run `ruff check .` + `ruff format --check .`; `.venv/bin/python -m pytest tests/scripts/ -k install -q` green incl. the 2 existing regressions; confirm SC-001..SC-005. *(45 passed, 7 skipped)*

## Acceptance coverage (populated)
| User Story | Evidence (tests) |
|---|---|
| US1 — respects destination argument | `test_install_target_resolution.py` (precedence, in-place default, F2 wheel-source-vs-target lock) |
| US2 — Linux install matches macOS | `test_install_os_branch.py` + `test_install_dep_probe.py` |
| US3 — `--dry-run` no mutation | `test_install_dry_run.py` (SC-002 file-count oracle) |
| US4 — idempotent re-run | `test_install_idempotency.py` (Step-2 027-gated case skipped until 027) |
| US5 — pairs with 009 CI | covered by spec 009's `ubuntu-latest` job consuming 039's `--dry-run` contract |
| (cross-cutting) audit record | `test_install_summary_json.py` (FR-012/013) |

## Dependencies & parallelization
- **T002 (foundational) blocks everything.** T001 → T002 → stories.
- Within stories, the `[P]` test files are independent and can be written in parallel; each story's implementation depends on its own tests + T002.
- **US1 is the MVP** (the F2 correctness bug) — ship-blocking; US2 next (Linux); US3/US4 are P2; US5 is 009's.
- **Cross-spec**: FR-010 Step 2 ← spec 027 (`user_authored`); US5 ← spec 009 (CI). Land 039 + 009 as separate PRs (Q4).
