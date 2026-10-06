# Research & Decisions: 009 Cross-Platform Portability Guard + PR CI

Captures the Phase 0 decisions. Inputs: the 2026-06-03 portability audit, the clarify
Session 2026-06-03, and a read of `.github/workflows/` (only `release.yml` +
tag-triggered `quality.yml`; no `ci.yml`).

## The audit (what actually exists today)

Ran the four macOS-ism sweeps the original 009 premised on:

| Sweep | Pattern | Result |
|---|---|---|
| BSD in-place sed | `sed -i ''` | **0 hits** in shipped code (the historical `scripts/run_cycle.sh` one was removed in spec 004). |
| Hardcoded macOS paths | `~/Library`, `/opt/homebrew`, `/usr/local/bin`, `/Applications/` | **0 hits** in `src/` or `scripts/`. One macOS cert **instruction** (prose) in `dist-templates/README.md` — legit, doc-only. |
| macOS clipboard/open | `pbcopy`, `pbpaste`, macOS-`open` | **0 command invocations.** |
| bash-4 constructs | `${v^^}`, `${v,,}`, `declare -A`, `mapfile`, `readarray`, `&>>` | **2 hits**, both `${word^^}`, both in **vendored `.specify/` spec-kit tooling**, not shipped to vaults. |

**Conclusion**: the remediation premise is ~90% stale. 009 pivots to **validation +
regression-lock + the missing CI**. This is *better* — it converts a transient "we cleaned
it up" into a permanent "it can't come back".

## D1 — Guard is a stdlib Python script wrapped by pytest (not a shell linter)
**Decision**: `scripts/check_portability.py` (importable + `__main__` CLI, exit 0/1) with the
rule logic in pure stdlib (`pathlib`/`re`), exercised by `tests/scripts/test_portability_guard.py`.
**Why**:
- Runs in the **fast loop** (`pytest -m "not e2e"`) with **no external tool** — contributors
  aren't gated on a local `shellcheck` install (Edge Case in spec).
- **Testable**: positive (inject a bad fixture → FAIL) + negative (clean tree → PASS) cases,
  satisfying Principle III.
- Consistent with the repo's other deterministic gates (`scripts/foreman/verify_test_coverage.py`,
  the LLM-dispatch guard) — all Python, all pytest-exercised.
**Rejected**: a bash+grep linter (not unit-testable, BSD/GNU grep divergence is itself a
portability trap — ironic), and depending on `shellcheck` for *all* rules (it doesn't catch
hardcoded-path or `sed -i ''` semantics, and it's an external dep locally).

## D2 — macOS-path rule exempts docs (`*.md`); scopes paths to `src/` + `scripts/`
**Decision**: the hardcoded-macOS-path rule scans `src/research_framework/**/*.py` +
`scripts/**/*.{py,sh}` + `dist-templates/*.sh` + `build.sh`, and **exempts `**/*.md`**.
**Why**: the only live hit is a macOS keychain-cert **instruction** in `dist-templates/README.md`
— legitimate user guidance, not executed code. Docs describe platform-specific *steps*; code
must not *hardcode* them. Exempting `*.md` prevents a false-positive while keeping every
executable surface honest.
**Rejected**: scanning everything (false-positive on the README), or a per-line allowlist
(brittle; path-type scoping is cleaner).

## D3 — `.specify/` is excluded; the 2 `${word^^}` hits are documented, not fixed
**Decision** (clarify Q → OUT OF SCOPE): the bash-4 rule scopes to **shipped** scripts
(`dist-templates/*.sh`, `scripts/*.sh`, `build.sh`); the 2 `${word^^}` hits in
`.specify/{scripts,extensions/git/scripts}/bash/create-new-feature.sh` are recorded as a
**documented exclusion** in `docs/PORTABILITY.md` and the guard's exclusion list.
**Why**: `.specify/` is vendored upstream spec-kit tooling, run only on the maintainer's box
during spec authoring — never shipped to a vault, never on a contributor's hot path. Patching
vendored code invites merge pain on the next spec-kit sync. If `.specify/` is ever re-vendored
differently, the exclusion is revisited (Edge Case).
**Rejected**: fixing them (touches vendored code for ~zero real-world benefit).

## D4 — CI matrix `{macos-latest, ubuntu-latest}`; macOS REQUIRED
**Decision** (clarify Q → macOS first-class): `ci.yml` runs a 2-leg matrix; **both legs are
required** status checks. macOS is not `continue-on-error`.
**Why**: the user designated macOS the **primary** development + validation target (the main
use case for the whole framework). A macOS regression must fail a PR exactly like a Linux one.
Linux is additive parity — cheap because the feature overlap is near-total — but kept green.
**Cost note**: `macos-latest` minutes bill ~10× Linux; accepted given the primary-target
designation and the fast-loop (`-m "not e2e"`) scoping.
**Rejected**: Linux-only CI (would let a macOS-ism break the primary platform), or macOS as
`continue-on-error` (contradicts primary-target status).

## D5 — `shellcheck` is the CI shell linter; runner-provided
**Decision**: each CI leg runs `shellcheck` over shipped `.sh`
(`dist-templates/*.sh scripts/*.sh build.sh`). Both `macos-latest` and `ubuntu-latest` GitHub
runners ship `shellcheck` pre-installed, so no install step is needed (a defensive
`shellcheck --version || brew install shellcheck` guard MAY be added if a runner image drifts).
**Why**: `shellcheck` is the industry-standard portability linter; it catches the *structural*
bash issues the Python guard intentionally doesn't (quoting, `[[ ]]` vs `[ ]`, unsafe word
splitting). Pairing the two (Python guard for repo-specific rules; `shellcheck` for general
shell hygiene) gives full coverage without a local-dev burden (D1).
**Rejected**: making `shellcheck` part of the local fast loop (external-dep burden on
contributors — kept CI-only per the spec's Edge Case).

## D6 — Shipped scripts target bash 3.2 (macOS stock floor)
**Decision**: the bash-4 construct rule treats **bash 3.2** as the floor for shipped scripts.
**Why**: macOS still ships bash 3.2.57 (`/bin/bash`) for licensing reasons; a contributor on a
Homebrew bash 5 won't notice a bash-4 construct that breaks the stock interpreter the installer
actually runs under. The floor guarantees `install.sh` + `./vault` work on a clean Mac.
**Rejected**: assuming bash 5 (Homebrew) — false on stock macOS, which is precisely the primary
target.

## D7 — `docs/PORTABILITY.md` is the contributor contract (vs a CONTRIBUTING section)
**Decision**: a standalone `docs/PORTABILITY.md` states supported OSes, required tools +
minimum versions (bash 3.2, python 3.11, shellcheck for CI), and the exact rule-set the guard
enforces — mirrored 1:1 with the guard (SC-005). `CONTRIBUTING.md` gets a one-line pointer.
**Why**: portability is a cross-cutting contract worth its own discoverable home (sits beside
`docs/testing-strategy.md`, `docs/observability-strategy.md`). Keeping the rule list in the doc
*and* asserting doc/guard agreement in a test stops the classic "docs say X, linter does Y" drift.
**Rejected**: burying it in CONTRIBUTING (less discoverable; mixes concerns).

## Sequencing with 039
009's CI **US5/FR-009** runs `install.sh … --dry-run`, a flag **039 introduces**. Therefore
009 lands **after** 039 (or the dry-run step is added in the same PR that merges 039). This is
the only hard ordering constraint; everything else in 009 is independent. Recorded in the spec's
Dependencies + the plan's Complexity section.
