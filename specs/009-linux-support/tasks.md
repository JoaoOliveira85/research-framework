# Tasks: 009 Cross-Platform Portability Guard + PR CI

**Input**: `spec.md` (reframed 2026-06-03), `plan.md`, `research.md` (D1–D7), `quickstart.md`.
**Tests**: TDD per Principle III — guard tests + CI-config test land before the artifacts they guard.
**Organization**: by user story. **[P]** = parallelizable (distinct files, no ordering dep).

**Sequencing**: land **after spec 039** (T013 consumes 039's `install.sh --dry-run`). All other tasks are 039-independent.

---

## Phase 1 — Setup
- [ ] **T001** Create `docs/PORTABILITY.md` skeleton (headings only): Supported OSes / Required tools + min versions / Enforced rules / Exclusions. Fill in T010.

## Phase 2 — US1: Portability regressions caught deterministically (P1) 🎯 MVP

**Goal**: a deterministic, stdlib guard that FAILS on a new macOS-ism in shipped code and PASSES on the current (clean) tree.

**Independent test**: add a temp `scripts/_probe.sh` with `sed -i ''` → guard FAILS naming it; remove → PASS.

### Tests first (TDD)
- [ ] **T002** [P] Write `tests/scripts/test_portability_guard.py`:
  - `test_clean_tree_passes` — the guard returns exit 0 / empty findings on the **current repo** (locks in the audit result; this is the regression-lock).
  - `test_bsd_sed_in_place_is_flagged` — write a temp `.sh` with `sed -i ''` under a `tmp_path` repo root → guard reports it with file+line.
  - `test_hardcoded_macos_path_flagged_in_code` — `/opt/homebrew` in a temp `.py` → flagged.
  - `test_macos_path_in_markdown_is_ignored` — same literal in a temp `*.md` → NOT flagged (D2).
  - `test_bash4_construct_flagged_in_shipped_sh` — `${v^^}` in a temp shipped `.sh` → flagged.
  - `test_specify_dir_is_excluded` — `${v^^}` under a temp `.specify/...` path → NOT flagged (D3).
  - Assert these run with **no external tool** (pure stdlib).
  - **MUST FAIL** initially (no `check_portability.py`).

### Implementation
- [ ] **T003** Implement `scripts/check_portability.py` (stdlib `pathlib`/`re`): rule-set per D1/D2/D3/D6 — BSD `sed -i ''`, hardcoded macOS paths (code only, `*.md` exempt), bash-4 constructs (shipped `.sh` only); `.specify/**` excluded. Importable `scan(root) -> list[Finding]` + `__main__` CLI printing `path:line: <rule> — <fix hint>` and exiting 1 on any finding, 0 clean.
- [ ] **T004** Run `pytest tests/scripts/test_portability_guard.py` → all green; confirm `test_clean_tree_passes` proves the **shipped tree is already clean** (no remediation needed — the audit's claim, now locked).

**Checkpoint**: US1 independently shippable — the regression-lock exists even before CI.

---

## Phase 3 — US2: Every PR gets a green cross-platform check (P1)

**Goal**: the missing PR CI exists; runs the full guard on `{macos-latest (required), ubuntu-latest}`.

### Test first
- [ ] **T005** [P] Write `tests/scripts/test_ci_config.py`: parse `.github/workflows/ci.yml` with PyYAML (already a dep) and assert: trigger includes **both** `pull_request` **and** `push` to the default branch (FR-004); matrix `os` == `[macos-latest, ubuntu-latest]`; macOS is **not** `continue-on-error`; each leg's steps include `pytest -m "not e2e"`, `ruff check`, `ruff format --check`, `shellcheck`. (The `--dry-run` step asserted in T012.) **MUST FAIL** (no `ci.yml` yet).

### Implementation
- [ ] **T006** Create `.github/workflows/ci.yml`: `on: { pull_request: {}, push: { branches: [main] } }` (FR-004); `strategy.matrix.os: [macos-latest, ubuntu-latest]` with `fail-fast: false`; checkout + `actions/setup-python@v5` (3.11); `pip install -e .[dev]` (or the repo's existing install step); steps: `pytest -m "not e2e"` → `ruff check .` → `ruff format --check .`. (shellcheck added T008; dry-run added T012.)
- [ ] **T007** Run `pytest tests/scripts/test_ci_config.py` → green for the steps present so far.

**Checkpoint**: PR CI runs the Python + ruff gate on both platforms.

---

## Phase 4 — US3: Shipped shell scripts pass shellcheck (P2)
- [ ] **T008** Add the `shellcheck dist-templates/*.sh scripts/*.sh build.sh` step to both CI legs (after ruff). Defensive `shellcheck --version` check tolerated.
- [ ] **T009** Run `shellcheck` locally over the shipped `.sh`; for each finding either fix it or add an inline `# shellcheck disable=SCxxxx` + one-line justification. Re-run until clean. Update `tests/scripts/test_ci_config.py` to assert the shellcheck step is present.

**Checkpoint**: shell hygiene gated in CI.

---

## Phase 5 — US4: Contributors have a portability contract (P2)
- [ ] **T010** Fill `docs/PORTABILITY.md` (from T001 skeleton): supported OSes (macOS primary + Linux; Windows→WSL2); required tools + min versions (bash 3.2 floor per D6, python 3.11, shellcheck CI-only); the **exact** rule table from `quickstart.md` (mirrors the guard 1:1); the `.specify/**` documented exclusion (D3). Add a one-line pointer from `CONTRIBUTING.md`.
- [ ] **T011** [P] (optional hardening) Add `test_portability_doc_matches_guard` to `tests/scripts/test_portability_guard.py`: assert each rule keyword the guard enforces appears in `docs/PORTABILITY.md` (SC-005 drift-lock).

---

## Phase 6 — US5: CI exercises the installer on both platforms (P3, pairs with 039)
- [ ] **T012** Add the final CI step to both legs: `bash dist-templates/install.sh tests/fixtures/quality/tech-lite --dry-run`, asserting exit 0. Update `tests/scripts/test_ci_config.py` to require this step. **Depends on 039** (the `--dry-run` flag). If 039 hasn't merged, mark the step `continue-on-error: true` with a `# TODO(039): make required once dry-run ships` and flip it in 039's PR.
- [ ] **T013** After 039 merges: remove the `continue-on-error` from T012, confirm both legs run the dry-run as a required step.

---

## Phase 7 — Polish
- [ ] **T014** [P] Full local sweep: `python scripts/check_portability.py` + `pytest -m "not e2e"` + `ruff check .` + `ruff format --check .` → all clean.
- [ ] **T015** [P] Confirm guard runtime < 2 s (SC-004) — time `python scripts/check_portability.py`.
- [ ] **T016** Update `CHANGELOG.md` `[Unreleased]`: new `scripts/check_portability.py` guard, new `ci.yml` PR CI ({macos,ubuntu}, macOS required), `docs/PORTABILITY.md`. Note the audit finding (code was already portable; this is the regression-lock).

---

## Dependencies & ordering
- **T002 → T003 → T004** (TDD: guard test → guard → green).
- **T005 → T006 → T007** (TDD: CI-config test → ci.yml → green).
- **T008/T009** after T006 (shellcheck step added to the existing workflow).
- **T010/T011** after T004 (doc mirrors the implemented rule-set).
- **T012/T013** after **039 merges** (consumes `--dry-run`) — the only cross-spec gate.
- US1 (T002–T004) is the **MVP** and is fully independent of 039 + CI; it can merge alone.

## Parallel example
```
# After T001, in parallel (distinct files):
T002 (test_portability_guard.py) + T005 (test_ci_config.py)
# Later, in parallel:
T011 (doc-drift test) + T014 (sweep) + T015 (timing)
```

## Implementation strategy
1. **MVP = US1** (T001–T004): the regression-lock. Ship-able alone; converts the audit into a permanent invariant.
2. **+ US2/US3** (T005–T009): the missing PR CI + shell hygiene — the infrastructure deliverable.
3. **+ US4** (T010–T011): the contributor contract.
4. **+ US5** (T012–T013): installer smoke — **gated on 039**.
