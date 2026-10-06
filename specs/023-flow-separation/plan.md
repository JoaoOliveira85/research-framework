# Implementation Plan: Flow Separation — **PHASE 1 ONLY**

**Branch**: `023-flow-separation-phase1-plan` | **Date**: 2026-05-26 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/023-flow-separation/spec.md` — scoped exclusively to the carve-out in **`## Implementation phasing` → Phase 1 — Feeds-Vault Revival Sprint**. Phase 2 (US2/US3/US4, FR-009/010/011/012/016/017) is **out of scope** for this plan and MUST NOT appear in tasks derived from it.

## Summary

Phase 1 unblocks the **Feeds-Vault Revival Sprint** by hardening the `./vault` public surface with three revival-critical verbs and two infrastructure contracts:

| ID | Deliverable |
|----|-------------|
| **US1** (partial) | Documented headless exit codes + `--json` for **new** verbs; existing verbs inherit FR-001/002/003 baseline |
| **FR-013** | `./vault refresh-sources` — subprocess bridge to legacy `scripts/collect_*.py` → `raw_data/<source>/` |
| **FR-014** | `./vault regenerate-shim` — re-render `templates/vault-script.sh.j2` from current `settings.yaml` + vault path (fixes archaeology F2) |
| **FR-015** | Vault-local `scripts/*.py` not in `dist-templates/scaffold-manifest.json` survive `./vault update` / `copy_scripts` |
| **FR-018** | Canonical `pipeline/atomic_write.py`; research writer path + cycle JSON writes use temp + `os.replace` |

Technical approach: stdlib-only Python CLI modules (`cli/refresh_sources.py`, `cli/regenerate_shim.py`), Jinja2 shim render (reuse `generator/scaffold._write_vault_script` logic), manifest-aware script merge in `generator/scripts.py` + `scaffold_diff.py`, centralized atomic I/O with tiered tests per ADR-0008.

**Parallel implementation streams** (for `/dispatching-parallel-agents` at `/speckit.tasks`):

```text
Stream A — FR-013 + vault-script.sh.j2 case arms  (refresh-sources)
Stream B — FR-014 + manifest shim reclassification (regenerate-shim)
Stream C — FR-015 copy_scripts + vault-side manifest (scripts survive update)
Stream D — FR-018 atomic_write + call-site migration (writer crash-safety)
```

Streams A/B touch `templates/vault-script.sh.j2` — **serialize the template edit** (one agent merges both case arms) or split: A adds `refresh-sources`, B adds `regenerate-shim` in non-overlapping hunks. Streams C and D are independent once `contracts/atomic-write.contract.md` is frozen.

## Technical Context

**Language/Version**: Python 3.11+ (constitution Technology Constraints)
**Primary Dependencies**: Existing only — `jinja2 ≥ 3.1` (shim template), `pyyaml ≥ 6.0` (settings), stdlib `pathlib`, `subprocess`, `json`, `hashlib`, `tempfile`, `os.replace`, `argparse`, `dataclasses`
**Storage**: Vault filesystem — `raw_data/`, `scripts/`, `./vault` shim, `_pipeline/cycles/cycle-NNN-*.json`, per-note `data_vault/**/*.md`
**Testing**: pytest seven-tier pyramid (ADR-0008) — tier-2 unit (atomic-write, scaffold-diff, shim idempotency), tier-3 integration (CLI verbs via subprocess), tier-5 e2e (concurrent `ask` + `research` on fixture vault; revival demo optional tier-6)
**Target Platform**: macOS/Linux vault operators; headless subprocess consumers (cron, Shortcuts)
**Project Type**: CLI framework + generated vault shim
**Performance Goals**: `refresh-sources` bounded by slowest collector (operator expectation: minutes, not cycle-scale)
**Constraints**: No new runtime dependencies (Principle V); no live `claude`/`codex` in tests (Principle IV + dispatch guard); planning stage does not modify `src/` or `tests/`
**Scale/Scope**: Phase 1 touches ~8–12 implementation files; 4 design contracts; no `VaultHandle`, no `active-sources.json`, no `spec-fingerprint.json`

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Phase 1 assessment |
|-----------|-------------------|
| **I — Script-validated gates** | New verbs expose documented exit codes; `refresh-sources` delegates validation to collector exit codes aggregated in JSON summary. PASS |
| **II — Phase sequencing** | No change to cycle orchestration order. PASS |
| **III — Test-first** | Plan mandates tier-2/3/5 tests before ship; contracts define assertions. PASS |
| **IV — Agent-script separation** | `refresh-sources` runs deterministic collector subprocesses, not LLM stages. PASS |
| **V — Offline-first, no new deps** | Stdlib + existing jinja2/pyyaml only. PASS |
| **VI — No duplicate notes** | Out of Phase 1 scope. N/A |
| **VII — External sources** | Collectors may hit network; framework does not persist off-host. PASS |
| **VIII — Stub-as-fuel** | Out of Phase 1 scope. N/A |
| **IX — Vault-first citation** | FR-018 ensures readers never see torn note files during concurrent `ask`. PASS |

**Post-design re-check**: PASS — no violations requiring Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/023-flow-separation/
├── plan.md              # This file
├── research.md          # Phase 0 decisions
├── data-model.md        # Phase 1 entities (no spec-fingerprint — Phase 2)
├── quickstart.md        # Operator walkthrough (feeds-vault revival)
├── contracts/
│   ├── refresh-sources-cli.contract.md
│   ├── regenerate-shim-cli.contract.md
│   └── atomic-write.contract.md
└── tasks.md             # /speckit.tasks — NOT created by this command
```

### Source Code (Phase 1 touch points)

```text
src/research_framework/
├── cli/
│   ├── refresh_sources.py      # NEW — FR-013 implementation
│   ├── regenerate_shim.py      # NEW — FR-014 implementation
│   └── _parser.py              # register subcommands; wire vault shim cases
├── pipeline/
│   ├── atomic_write.py         # NEW — FR-018 canonical module
│   ├── scaffold_diff.py        # FR-015 — explicit LEAVE_ALONE for unmanifested scripts/*
│   └── steps/research.py       # FR-018 — cycle-NNN-batch-*.json atomic writes
├── generator/
│   ├── scripts.py              # FR-015 — merge copy, never rmtree vault collectors
│   └── scaffold.py             # FR-014 — extract shared shim render helper
templates/
└── vault-script.sh.j2          # FR-013/014 — new case arms + help text
dist-templates/
└── scaffold-manifest.json      # FR-014/015 — shim + scripts/*.py entry semantics
tests/
├── pipeline/test_atomic_write.py           # tier-2
├── pipeline/test_scaffold_diff_scripts.py  # tier-2 FR-015
├── cli/test_refresh_sources.py             # tier-3
├── cli/test_regenerate_shim.py             # tier-3
└── pipeline/test_concurrent_ask_research.py # tier-5 FR-018 (new)
```

**Structure Decision**: Single Python package; no new top-level projects. Vault shim dispatches to `research_framework.cli` subcommands (same pattern as `coverage`, `reindex`).

## Complexity Tracking

> No constitution violations. Table intentionally empty.

## Phase 0: Research

Completed in [research.md](./research.md). All Technical Context unknowns resolved.

## Phase 1: Design

| Artifact | Path |
|----------|------|
| Data model | [data-model.md](./data-model.md) |
| refresh-sources contract | [contracts/refresh-sources-cli.contract.md](./contracts/refresh-sources-cli.contract.md) |
| regenerate-shim contract | [contracts/regenerate-shim-cli.contract.md](./contracts/regenerate-shim-cli.contract.md) |
| atomic-write contract | [contracts/atomic-write.contract.md](./contracts/atomic-write.contract.md) |
| Operator quickstart | [quickstart.md](./quickstart.md) |

**Explicitly NOT designed (Phase 2)**: `VaultHandle`, `_pipeline/active-sources.json`, `_pipeline/spec-fingerprint.json`, `_pipeline/in-loco-modules.json`, `docs/integration/assistant-framework.md`, FR-016 stale-spec warnings, FR-017 deprecate-and-prune lifecycle.

## Acceptance coverage (Phase 1 evidence slots)

Per spec `## Acceptance coverage` — tasks will populate cells; plan maps evidence targets:

| Scope | Planned evidence |
|-------|------------------|
| US1 (partial) | Tier-3 subprocess tests per new verb `--json` + exit codes; extend headless contract table in contracts |
| FR-013 | `tests/cli/test_refresh_sources.py` + feeds-vault manual ship criterion #1 |
| FR-014 | Idempotent byte-identity unit test + ship criterion #2 |
| FR-015 | `tests/pipeline/test_scaffold_diff_scripts.py` + ship criterion #3 |
| FR-018 | `tests/pipeline/test_atomic_write.py` + tier-5 concurrent read test + ship criteria #4–5 |

## Dependencies & sequencing

| Dependency | Impact on Phase 1 |
|------------|-------------------|
| **ADR-0009 option A** | `refresh-sources` targets legacy `collect_*.py` — recorded ✅ |
| **Spec 027** (`install.sh` `VAULT_DIR`) | Soft — `./vault update` still broken for shim auto-refresh; **FR-014 is the revival escape hatch**. Not a Phase 1 blocker. |
| **Spec 020 Phase 1** | Downstream consumer of `refresh-sources` — see Cross-spec coordination below; no Phase 1 *code* dependency |
| **Spec 028 / 033** | Parallel worktrees — no file overlap |

## Cross-spec coordination (Spec 023 ↔ Spec 020)

Both specs ship in the revival sprint and have one **forward-touching** integration point worth surfacing before `/speckit.tasks` runs:

- **`refresh-sources` iteration surface.** Spec 023's `refresh-sources` CLI (FR-013) is currently planned to invoke `python <vault>/scripts/collect_*.py` for each discovered collector (plus the `reddit_rss.py` frozen-allowlist entry). Spec 020's source-module architecture (FR-013a, clarified 2026-05-26) introduces per-module `<vault>/modules/<name>/sources.yaml` enumeration. The migration path is:
  - **Phase 1 (this spec)**: `refresh-sources` is a thin shell over the legacy `scripts/collect_*.py` collectors. It does NOT read any `<vault>/modules/*/sources.yaml` files. Operators using the revival path get re-runnable legacy collectors, which is the sprint's escape-hatch deliverable.
  - **Spec 020 ships `sources_loader.py`**: per-module `sources.yaml` enumeration moves into the source-extraction stage (Step 1.5 of the pipeline). `refresh-sources` continues to work on legacy `scripts/collect_*.py` collectors only — there's no cross-call between the two systems.
  - **ADR-0009 transition** (post-revival): legacy collectors get ported to 020-shaped modules one at a time. As each port lands, the matching `scripts/collect_*.py` is deleted; `refresh-sources` discovers fewer collectors over time and eventually becomes empty (operator gets a "no legacy collectors found; use `./vault research` for module-driven extraction" message). No code change needed in `refresh-sources` for this transition — it's filesystem-driven.

- **Implication for `/speckit.tasks` generation**: 023's tasks should NOT add any direct dependency on spec 020's `source_bridge/sources_loader.py`. The two systems are intentionally decoupled at this layer. The only shared touch-point is `<vault>/scripts/` lifecycle (preserved by 023 FR-015's `scripts/`-survives-update guarantee, which 020 module ports rely on for the deletion step). If `/speckit.tasks` notices a coupling it can't justify, that's a signal to revisit the boundary before implementation.

## Ship criteria mapping

Maps 1:1 to spec `### Phase 1 — Feeds-Vault Revival Sprint` numbered list:

1. `refresh-sources` on live feeds-vault → Stream A + manual validation
2. `regenerate-shim` idempotent → Stream B + tier-2 test
3. `scripts/custom_collector.py` survives update → Stream C + tier-2 regression
4. Concurrent `ask` + `research` no partial reads → Stream D + tier-5 test
5. End-to-end revival demo → operator quickstart + existing cycle e2e harness (not a new framework feature)

## Post-design Constitution Check

**Status: PASS** — Phase 1 design stays within Principles I, III, IV, V, IX; no new runtime dependencies; test tiers assigned per ADR-0008.
