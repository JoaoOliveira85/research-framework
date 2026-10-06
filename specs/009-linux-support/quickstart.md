# Quickstart: 009 Portability Guard + PR CI

## Run the portability guard locally (fast, stdlib-only)

```bash
# Direct CLI — exit 0 clean, exit 1 + file:line on a violation:
python scripts/check_portability.py

# Or via the fast loop (the guard is a pytest):
pytest tests/scripts/test_portability_guard.py
pytest -k portability        # same, shorter
```

The guard needs **no external tools** — it's pure stdlib, so it runs everywhere `pytest` does.

## What the guard flags (mirrors `docs/PORTABILITY.md`)

In **shipped** scripts (`dist-templates/*.sh`, `scripts/*.sh`, `build.sh`) and code
(`src/research_framework/**/*.py`, `scripts/**/*.py`):

| Rule | Forbidden | Use instead |
|---|---|---|
| BSD in-place sed | `sed -i ''` | `python` rewrite, or `sed -i.bak … && rm …` (portable form) |
| Hardcoded macOS path | `~/Library`, `/opt/homebrew`, `/usr/local/bin`, `/Applications/` (code only; `*.md` exempt) | `$(brew --prefix)`, `command -v`, `$HOME`, env vars |
| bash-4 construct | `${v^^}`, `${v,,}`, `declare -A`, `mapfile`, `readarray`, `&>>` | `tr` for case; indexed arrays; `>> f 2>&1` |

**Excluded** (documented): `.specify/**` vendored spec-kit tooling (2 known `${word^^}` hits).

## Run shellcheck (CI parity, optional locally)

```bash
shellcheck dist-templates/*.sh scripts/*.sh build.sh
# macOS: brew install shellcheck   |   Linux: apt-get install shellcheck
```
Intentional findings carry an inline `# shellcheck disable=SCxxxx` + a one-line why.

## How CI works (`.github/workflows/ci.yml`)

> **Superseded 2026-09-07 (#323, #324).** 009 shipped this as PR CI. It is not
> PR CI any more — the per-PR trigger and the standing macOS leg were withdrawn
> on cost (a month's Actions allowance in under a day; macOS bills at 10x).

- Triggers on **version-tag pushes** and **`workflow_dispatch`**. Not on
  `pull_request`, not on a branch push, not on a schedule.
- Matrix: **`ubuntu-latest`** always; **`macos-latest`** only when a manual run
  passes `macos: true`. The OS-sensitive surfaces — the portability guard,
  shellcheck, the installer dry-run — already pass on Linux.
- Each leg runs: `pytest -m "not e2e"` -> `ruff check .` -> `ruff format --check .` ->
  `shellcheck ...` -> `bash dist-templates/install.sh tests/fixtures/quality/tech-lite --dry-run`.
- **The merge gate is local**, not this workflow: `pytest`,
  `python scripts/guards/run_all.py` and `ruff`, run by the author and reported
  in the PR (CONTRIBUTING § 1). CI showing nothing on a PR is expected.

## Verify the CI config didn't drift

```bash
pytest tests/scripts/test_ci_config.py   # asserts ci.yml has both legs + the full step set
```

## Sequencing note (039)
The CI `--dry-run` step uses a flag **spec 039** adds to `install.sh`. Land **039 first**, or add
that single CI step in the PR that merges 039. The rest of 009 is independent.
