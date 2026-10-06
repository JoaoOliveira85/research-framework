# Implementation Plan: Post-Revival Hardening

**Branch**: `051-post-revival-hardening` | **Date**: 2026-06-02 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/051-post-revival-hardening/spec.md`
**Target ship**: **0.7.1** (firm — Q3's mandatory preflight contract justifies a single small MINOR; 0.7.2 carries the FR1 empirical re-tune only)

## Summary

Five independent hardening fixes distilled from the 2026-06-01 feeds-vault revival
(`REVIVAL-NOTES.md`), bundled because each is small and they share no runtime
state. No new runtime dependencies (Principle V), no new principles
(constitution unchanged). The work is overwhelmingly **configuration-driven +
test-driven**: every FR adds a typed settings surface and/or a deterministic
classifier and locks it with tests.

| FR | What | Primary code target (real path, post-recon) |
| --- | --- | --- |
| **FR1** | Configurable cycle-yield threshold model (headline) | `pipeline/coverage.py` (the model actually lives here, not `gates_cycle.py`) + `pipeline/gates_cycle.py` (gate semantics) + `pipeline/settings.py` + `pipeline/quality_report.py` (diagnostic + sidecar) |
| **FR2** | Detect stale venv on `./vault update` | `dist-templates/install.sh` + `templates/vault-script.sh.j2` (`update` verb) |
| **FR3** | Inbound-link-aware stub policy | `pipeline/stubs.py` + a small inbound-count helper sourced from `vault/indexer.py` + `pipeline/settings.py` |
| **FR4** | Mandatory per-module **preflight subprocess** contract (D6/C1) | `source_bridge/discovery.py` (`parse_manifest` makes `preflight.entry_point` required) + `source_bridge/preflight_types.py` (typed result) + `source_bridge/orchestrator.py` (spawn subprocess, popen_session + tree-kill) + 4 in-tree subprocess scripts `src/research_framework/modules/<name>/preflight.py` + `manifest.schema.json` amendment |
| **FR5** | Regression locks for 0.6.2 / 0.6.3 fixes | **Net-new coverage only** — the two headline tests already exist (see research.md D7); FR5 adds the un-covered `_cycle_helpers._run_script` grandchild path + `_highest_completed_cycle` regex edge cases |

**Critical reconciliation (read research.md before implementing):** the spec
references several files by names that don't exist verbatim in the tree. The
plan retargets each to its real home (documented as decisions D1–D7 in
`research.md`). The most consequential is **D7**: FR5's two proposed regression
tests are ~90% already present in the suite, so FR5 is scoped down to the
genuinely-missing slices to avoid duplicating existing coverage.

## Technical Context

**Language/Version**: Python 3.11+ (per `pyproject.toml` `requires-python`); Bash for `install.sh` / `vault` shim (FR2)
**Primary Dependencies**: stdlib + existing only — `pyyaml ≥ 6.0` (settings, manifests), `jinja2 ≥ 3.1` (shim/template render), `urllib`/`xml.etree` (already used by rss/oreilly extractors for FR4 HEAD-probe). **No new runtime dependencies** — Principle V is non-negotiable.
**Storage**: filesystem under vault root. New artifact: `_pipeline/yield-calibration.json` (FR1, append-per-cycle, `schema_version: "1.0"`). New per-module file: `<vault>/modules/<name>/preflight.py` (FR4, copied by `generator/module_refresh.copy_listed_modules`). Reused: `_pipeline/cycles/cycle-NNN-quality-report.json` (FR1 diagnostic field), `data_vault/_graph.md` (FR3 inbound source — read via indexer helper, not re-parsed).
**Testing**: pytest, seven-tier pyramid (ADR-0008). Bash tested via the sandbox-extraction + `pty.fork()` pattern already in `tests/scripts/test_install_sh_tty_handling.py` (FR2).
**Target Platform**: macOS / Linux dev + CI (Linux CI still pending spec 009; FR2 must keep bash POSIX-portable).
**Project Type**: single-project Python CLI + Jinja2-templated vault scaffold.
**Performance Goals**: no hot-path regressions. FR3 must read inbound counts without a full per-call vault re-walk (build the count map once per stub pass). FR4 preflight has a `timeout_seconds` budget (default 30) per module.
**Constraints**: FR1 defaults MUST preserve the existing `tech-lite` quality-harness baseline (so `./build.sh --quality` regression diff doesn't move); the doubling target applies only to a dormant 200-note vault. FR4 manifest amendment is technically breaking but no third-party modules exist (all four Tier-1 modules are in-tree). FR4 preflight is an **isolated subprocess** (D6/C1) — core never imports vault module code at runtime.
**Scale/Scope**: ~16 files, ~3.75 days (FR4 ≈ 1.5d is the long pole). 1740 tests at 0.6.3 baseline; this spec adds ~30–40 tests net.

### Resolved unknowns (full detail in research.md)

The five exploration sweeps resolved every "NEEDS CLARIFICATION" the spec
implied. No open unknowns remain entering Phase 0. Highlights:

- **FR1 model home** — `_COLD_START_MAX_YIELD` / `_INCREMENTAL_MAX_YIELD` /
  `_staleness_multiplier` / `remaining_yield()` all live in
  `pipeline/coverage.py` (not `gates_cycle.py`). `CG001_min_cycle_yield`
  consumes the threshold. (D1)
- **FR1 diagnostic surface** — there is **no** `cycle-NNN-report.md`; the
  canonical per-cycle artifact is `cycle-NNN-quality-report.json`. Diagnostic
  goes there + into the new sidecar. (D2)
- **FR1 settings template** — there is no `dist-templates/settings.yaml.template`;
  the canonical seed is the repo-root `settings.yaml` (shipped as
  `_data/settings.yaml`, tracked in `scaffold-manifest.json`). (D3)
- **FR2 non-interactive flag** — the existing convention is `--non-interactive|-y`
  + `RV_NONINTERACTIVE`, not `--auto-confirm`. Add `--auto-confirm` as an alias. (D4)
- **FR3 inbound source** — no parser exists for `_graph.md`; reuse the
  indexer's in-memory link-graph construction via a small extracted helper. (D5)
- **FR4 reality** — modules are in-tree YAML manifests; `./vault refresh-sources`
  runs only legacy collectors today, so the cycle-time invocation point is
  `source_bridge/orchestrator.run_extraction()`. No `dist-templates/modules/`
  exists; the skeleton lands at `src/research_framework/modules/_template/preflight.py`. (D6)
- **FR5 overlap** — `test_grandchild_dies_when_tree_is_terminated` exists twice;
  `test_sentinel_cycle_dirs_do_not_count` + `test_only_a_quality_report_marks_a_cycle_complete`
  exist in `tests/cli/test_research_resume.py`. FR5 scoped to net-new only. (D7)

## Constitution Check

*GATE: evaluated against constitution v1.4.0. Re-checked post-design — see "Post-Design Re-check" below.*

| Principle | Verdict | Notes |
| --- | --- | --- |
| **I. Script-Validated Quality Gates** | ✅ PASS (spec-authorized semantics change) | FR1 changes CG-001 from "fail below flat threshold" → "warn below `target*0.5`, fail below `min_floor`". This is a gate-semantics change. Per the constitution's *Ask First* list ("Modifying validation exit codes or their semantics") — but the **clarified spec already authorizes it** (FR1 body), so no new approval at plan time. Defaults pinned to preserve the reference-vault baseline (Principle-I "gate that fails stops the process" preserved via `min_floor`). |
| **II. Phase Sequencing** | ✅ PASS | No phase reordering. FR4 preflight runs at cycle start (within Phase 2 entry) and on `refresh-sources`; FR1 gate stays a cycle-boundary check. |
| **III. Test-First (TDD)** | ✅ PASS | Every FR ships its test file(s) before/with impl. Foreman pattern (ADR-0010) opt-in via `### Testing Requirements` in tasks.md. |
| **IV. Agent-Script Separation** | ✅ PASS | FR1/FR3/FR4 are all script-side deterministic classifiers; no agent self-assessment introduced. |
| **V. Offline-First, No External Persistence** | ✅ PASS | No new runtime deps. FR4 rss HEAD-probe uses stdlib `urllib` (already a dep of rss/oreilly extractors) and is network-touching only at preflight time, same class as existing extractor fetches. Yield sidecar is local-only. |
| **VI. No Duplicate Notes** | ✅ N/A | No note-creation path touched. |
| **VII. External Sources Mandatory** | ✅ N/A | Untouched. |
| **VIII. No Placeholders / Stub-as-Fuel + module isolation** | ✅ PASS (reinforces) | FR3 *strengthens* Stub-as-Fuel: anchor-stubs become `needs-research` fuel instead of deletion candidates. FR4 preflight runs as an **isolated subprocess** (D6/C1 — resolves analyze finding C1), preserving spec-020's module-isolation invariant: core never imports vault module code at runtime. `min_floor`/anchor guard never let the loop declare done on stranded graph. |
| **IX. Vault-First Citation** | ✅ N/A | Untouched. |
| **X. Vault History is Append-Only Git** | ✅ PASS | FR2 layers on top of spec-050's existing `./vault update` auto-commit (`framework:` prefix) — a bad rebuild is one `git revert HEAD` away, exactly as FR2's design assumes. No change to the commit invariant. |

**Ask-First items (both pre-authorized by the clarified spec, flagged for the record):**
1. FR1 CG-001 gate-semantics change (warn/fail split) — authorized in FR1.
2. FR4 module-manifest required-key addition (`preflight`) — authorized in Q3.

**Gate result: PASS.** No unjustified violations. No Complexity Tracking entries required.

### Post-Design Re-check (after Phase 1)

Re-evaluated after producing `data-model.md` + `contracts/`, and again after
`/speckit.analyze` (2026-06-02). **No violations:** the design introduced no new
runtime dependencies (Principle V holds — the typed `PreflightResult`/`SourceCorrection`
and the rss HEAD probe are stdlib), no new principle (constitution stays
v1.4.0), and no additional Ask-First items beyond the two already flagged (FR1
gate semantics, FR4 manifest required key — both spec-authorized). **Analyze
finding C1 resolved:** preflight runs as an isolated subprocess (D6/C1), so
spec-020's module-isolation invariant is preserved and analyze finding U1
(in-process import safety) is dissolved. The `yield-calibration.json` sidecar +
both preflight payloads (request + `PreflightResult` response) carry
`schema_version` per the spec-036 cross-boundary discipline. Verdict remains
**PASS**.

## Project Structure

### Documentation (this feature)

```text
specs/051-post-revival-hardening/
├── plan.md              # This file (/speckit.plan output)
├── spec.md              # Feature spec (already present, clarified)
├── research.md          # Phase 0 — decisions D1–D7 (spec→reality reconciliation)
├── data-model.md        # Phase 1 — new entities (settings blocks, sidecar, PreflightResult)
├── quickstart.md        # Phase 1 — how to exercise each FR end-to-end
├── contracts/
│   ├── preflight.contract.md         # FR4 — preflight SUBPROCESS contract (D6/C1)
│   ├── preflight-result.schema.json  # FR4 — PreflightResult stdout JSON schema
│   └── yield-calibration.schema.json # FR1 — sidecar JSON schema
└── tasks.md             # Phase 2 (/speckit.tasks — NOT created here)
```

> FR4 also amends an **existing** contract in place:
> `specs/020-code-bridge/contracts/manifest.schema.json` (adds `preflight` to
> `required`). That amendment is part of implementation, not a new file under 051.

### Source Code (repository root) — files touched, by FR

```text
src/research_framework/
├── pipeline/
│   ├── coverage.py                 # FR1: replace _COLD_START_MAX_YIELD cap + staleness
│   │                               #      multiplier with the multiplicative model;
│   │                               #      remaining_yield() returns (target, breakdown)
│   ├── gates_cycle.py              # FR1: CG001_min_cycle_yield warn-vs-fail split
│   ├── settings.py                 # FR1: CycleYieldSettings; FR3: StubsSettings
│   ├── quality_report.py           # FR1: yield diagnostic field + yield-calibration.json append
│   ├── stubs.py                    # FR3: classify_stub() + StubClassificationContext + anchor branch
│   └── source_bridge/
│       ├── discovery.py            # FR4: ModuleManifest.preflight (required, entry_point); parse_manifest validates
│       ├── preflight_types.py      # FR4 (new): typed PreflightResult/SourceCorrection (parse subprocess JSON)
│       └── orchestrator.py         # FR4: SPAWN preflight subprocess at run_extraction() top (popen_session + tree-kill)
├── vault/
│   └── indexer.py                  # FR3: extract inbound_link_counts() helper (no behaviour change)
├── cli/
│   └── refresh_sources.py          # FR4: preflight pass before/around collector loop
│   └── research_resume.py          # FR5: (read-only; _highest_completed_cycle locked by new test)
└── modules/                       # FR4 preflight.py = SUBPROCESS scripts (main()+check(), emit JSON; can't import src/)
    ├── youtube/preflight.py        # FR4 (new) — whitespace strip, channel-URL shape, @-handle
    ├── reddit/preflight.py         # FR4 (new) — /r/<name> format + normalize
    ├── rss/preflight.py            # FR4 (new) — /feed/feed/ de-dup, arxiv suggest, HEAD probe
    ├── oreilly/preflight.py        # FR4 (new) — learning.oreilly.com/search shape, reject legacy API
    └── _template/preflight.py      # FR4 (new) — subprocess skeleton (emits success JSON; TODO body)

dist-templates/
└── install.sh                      # FR2: _detect_stale_venv() + post-install version sanity + --auto-confirm

templates/
└── vault-script.sh.j2              # FR2: ./vault update plumbs --auto-confirm into install.sh

settings.yaml                       # FR1+FR3: new cycle_yield: and stubs: blocks (canonical seed)

tests/
├── pipeline/
│   ├── test_cg001_yield_model.py   # FR1 (new) — cold/weekly/biweekly/monthly/over-target + dormant fixture
│   └── test_stub_classification.py # FR3 (new) — not-a-stub / anchor-stub / deletable-stub branches
├── scripts/
│   └── test_install_venv_staleness.py  # FR2 (new) — rebuild/stale/mismatch/fresh/--auto-confirm
├── modules/
│   ├── youtube/test_preflight.py   # FR4 (new)  (~6–8 tests each)
│   ├── reddit/test_preflight.py    # FR4 (new)
│   ├── rss/test_preflight.py       # FR4 (new)
│   └── oreilly/test_preflight.py   # FR4 (new)
└── (FR5 net-new — exact homes in research.md D7)
    ├── pipeline/test_cycle_helpers_tree_kill.py   # FR5 (new) — _run_script grandchild path
    └── cli/test_resume_completion_marker.py       # FR5 (new) — regex edge cases only
```

**Structure Decision**: single-project layout (the established research-framework
shape). All new code lands in the existing `src/research_framework/` package and
`tests/` tree following the seven-tier pyramid; bash changes stay in
`dist-templates/` + `templates/`. No new top-level directories except the
in-tree `src/research_framework/modules/_template/` skeleton home (D6).

## Phase Sequencing for implementation (dependency-ordered)

FRs are independent except FR4's internal ordering. Recommended `/speckit.tasks` ordering:

1. **FR5** (≈0.25d, now smaller) — lock existing behaviour first so later refactors can't silently break it. Net-new tests only.
2. **FR1** (≈1d) — settings block → model in `coverage.py` → gate split → diagnostic + sidecar. Pin defaults to reference-vault baseline early.
3. **FR3** (≈0.5d) — indexer helper → `classify_stub` → settings → tests.
4. **FR2** (≈0.5d) — `install.sh` helper + sanity check → shim plumbing → sandbox/pty tests.
5. **FR4** (≈1.5d, long pole) — subprocess contract + `preflight-result.schema.json` + manifest amendment + `preflight_types.py` **first** (defines the shape) → `discovery.py` required-key validation → orchestrator/refresh-sources subprocess spawn (popen_session + tree-kill) → 4 module preflight subprocess scripts + skeleton → 4 test files. All four modules MUST add preflight before 0.7.1 ships (Q3).

## Complexity Tracking

> No Constitution Check violations require justification. Table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
