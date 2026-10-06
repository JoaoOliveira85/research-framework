# Portability contract

The framework is **macOS-first** — macOS is both the primary development
platform and the primary validation target — and **Linux-parity**: it also runs
on Linux, kept green because the feature overlap is near-total so the marginal
cost is tiny. This document is the contributor-facing contract: the supported
platforms, the required tooling, and the exact rules the portability guard
enforces. It mirrors `scripts/check_portability.py` **1:1** — a test
(`test_portability_doc_matches_guard`) fails if the two drift (spec 009 SC-005).

## Supported platforms

| Platform | Status | Notes |
|----------|--------|-------|
| **macOS** | **Primary (required)** | The main use case; the CI `macos-latest` leg is a required check — a macOS regression blocks a PR exactly like a Linux one. Stock `/bin/bash` is **3.2.57**, so shipped scripts target bash 3.2 (see below). |
| **Linux** | Parity (required) | The CI `ubuntu-latest` leg is also required. Near-total feature overlap; kept green. |
| **Windows** | Out of scope | Use **WSL2**, which inherits the Linux support. No native-Windows handling. |

## Required tools + minimum versions

| Tool | Minimum | Where |
|------|---------|-------|
| Python | **3.11** | runtime + tests (`pyproject.toml::requires-python`) |
| bash | **3.2** | the floor for **shipped** shell scripts (`install.sh`, `./vault`, `generate.sh`, `update.sh`, `build.sh`) — macOS stock bash |
| git | any recent | vault history (Principle X) + worktrees |
| curl | any recent | source fetching |
| shellcheck | any recent | **CI-only** shell linter — NOT required locally (the Python guard below runs in the fast loop with no external tool) |

## Enforced rules (mirrors the guard 1:1)

The guard scans **shipped** shell scripts (`build.sh`, `install.sh`,
`generate_vault.sh`, `templates/vault-script.sh.j2`, `dist-templates/*.sh`,
`scripts/**/*.sh`) and **executable code** (`src/research_framework/**/*.py`,
`scripts/**/*.{py,sh}`, `dist-templates/*.sh`, `build.sh`, `install.sh`,
`generate_vault.sh`, `templates/vault-script.sh.j2`). Markdown (`*.md`) is
exempt — docs may *describe* a platform-specific step; code must not *hardcode*
it. `templates/vault-script.sh.j2` is the source that renders into every
generated vault's `./vault` shim — the shipped shell script that reaches the
most machines this project doesn't control, so it is in scope even though its
own file extension is `.j2` (issue #288: it was missed for a release).

| Rule | Forbidden | Use instead |
|------|-----------|-------------|
| **BSD in-place sed** (shipped `.sh`) | `sed -i ''` | a `python` rewrite, or the portable `sed -i.bak … && rm …` form |
| **bash-4 construct** (shipped `.sh`) | `${v^^}`, `${v,,}`, `declare -A`, `mapfile`, `readarray`, `&>>` | `tr '[:lower:]' '[:upper:]'` for case; indexed arrays; `>> f 2>&1` for append-both |
| **Hardcoded macOS path** (code; `*.md` exempt) | `~/Library`, `/opt/homebrew`, `/usr/local/bin`, `/Applications/` | `$(brew --prefix)`, `command -v <tool>`, `$HOME`, or an env var |

### Why bash 3.2 for shipped scripts

macOS still ships bash **3.2.57** as `/bin/bash` (licensing). A contributor on
a Homebrew bash 5 won't notice a bash-4 construct that breaks the stock
interpreter the installer actually runs under. Targeting bash 3.2 guarantees
`install.sh` + `./vault` work on a clean Mac.

## Exclusions

- **`.specify/**`** — vendored upstream spec-kit tooling, run only on a
  maintainer's box during spec authoring, never shipped to a vault. It contains
  2 known `${word^^}` hits in `create-new-feature.sh`; these are an **accepted,
  documented exclusion** (spec 009 FR-003), not a bug to fix — patching vendored
  code invites merge pain on the next spec-kit sync. If `.specify/` is ever
  re-vendored differently, revisit.
- **The guard's own source** (`scripts/check_portability.py`) — it necessarily
  contains the forbidden literals as rule definitions, so it excludes itself.

## How to check locally

```bash
# Fast, stdlib-only — runs everywhere pytest does (no shellcheck needed):
python scripts/check_portability.py        # exit 0 clean, exit 1 + file:line on a hit
pytest -k portability                      # the same rules, as a pytest

# CI parity (optional locally — needs shellcheck installed):
shellcheck dist-templates/*.sh scripts/*.sh build.sh install.sh generate_vault.sh
```

`templates/vault-script.sh.j2` is scanned by the Python guard above but not by
`shellcheck` — it's a Jinja2 template, not valid shell (`{{ }}`/`{% %}`
markup), so shellcheck would need to parse the *rendered* output rather than
the template source. Not wired up yet; the Python guard is the one that
covers it today (issue #288).

Intentional `shellcheck` findings carry an inline
`# shellcheck disable=SCxxxx` + a one-line justification (e.g. the two
controlled-name wheel globs in `install.sh` / `build.sh`).

## How CI enforces it

`.github/workflows/ci.yml` runs on a `v*` tag push and on a manual
`workflow_dispatch` only — never per PR, push or schedule (`CLAUDE.md`
§ CI budget). The merge gate is the local suite, which every PR reports.
When it does run it is on a
`{macos-latest, ubuntu-latest}` matrix (both required). Each leg runs the
portability guard, `pytest -m "not e2e"`, `ruff check`, `ruff format --check`,
`shellcheck` over the shipped scripts, and a `dist-templates/install.sh …
--dry-run` smoke (spec 039).
