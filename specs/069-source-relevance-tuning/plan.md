# Implementation Plan: Source-relevance + declared-source validation

**Branch**: `069-source-relevance-tuning` | **Date**: 2026-06-15 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/069-source-relevance-tuning/spec.md`
**Target ship**: **1.0.0rc8 / 1.0.0** (rc8-wave umbrella #152; issue #160)

## Summary

The rc7 vault declared 4 `data_sources` ("Codebase Vault Seed", "GitHub", "Official
Documentation", "Web") but has **no `modules/` directory at all**; 3 of 4 produced
zero facts/signals across 4 cycles — a vault that lies about its coverage. Phase-0
code audit found the key lever already exists: module manifests **already declare
`triggers[]`** and `pipeline/source_bridge/discovery.py` has `build_trigger_registry`
+ `TriggerRegistry.match()`/`_matches` — but the **match result is discarded** in the
extraction orchestrator (`orchestrator.py:60`), and module↔source linkage today is a
name-slug convention, not trigger matching. `DataSourceConfig` has **no `kind`** field.

Per the operator's Q1 decision, 069 makes modules drop-in-composable by **manifest
triggers** and fails closed on declared-but-unbacked sources (rc8 scope = FR1/FR2 +
FR3 + FR5; **FR4 relevance-classifier tuning is split to a follow-up sub-spec**, Q3):

| FR | What | Primary code target (Phase-0 verified) |
| --- | --- | --- |
| **FR1** | A declared source is "backed" iff some installed module's manifest **triggers** match its locator; else it MUST carry `kind: strategy_hint`, else scaffold-time error | `spec/schema.py` (`DataSourceConfig.kind` NEW) + `spec/validator.py::validate` (generate gate) + `scripts/validate_spec.py` (skill gate); reuse `source_bridge/discovery.py::TriggerRegistry.match` |
| **FR2** | Runtime fail-closed at preflight: a declared source with no trigger-matching module AND no `strategy_hint` errors (doesn't silently emit empty) | `pipeline/preconditions.py` (check #6) + `pipeline/preflight.py::check_all` |
| **FR3** | Stagnant-source signal (WARN): a source yielding zero facts/signals for ≥2 consecutive cycles is surfaced in the cycle report + `./vault status` | `pipeline/quality_report.py` (`_degraded_sources`/`write_report`) + `cli/status.py` (`build_status_json` deferred-warnings) + `scripts/source_ledger.py` (`load_declared_sources`) |
| **FR5** | Spec-053 authority alignment: an authoritative source going cold weights worse than a low-authority one | `pipeline/source_authority.py` (`build_source_role_index`) feeds the FR3 signal |
| ~~FR4~~ | ~~relevance-classifier tuning~~ | **DEFERRED to a follow-up sub-spec** (needs live data; Q3) |

No new runtime dependency (Principle V — stdlib + existing `pyyaml`). `DataSourceConfig`
gains one optional `kind` field (additive; default keeps existing specs valid — **no
`schema_version` bump for absent `kind`**; plan confirms at Post-Design). Operator-driven
migration (Q2): framework WARNs + fails closed; never rewrites `research.spec.md`.
Standalone spec.

## Technical Context

**Language/Version**: Python 3.11+ (per `pyproject.toml::requires-python`).
**Primary Dependencies**: stdlib + existing only — `pyyaml ≥ 6.0` (manifest + spec
frontmatter), `re` (trigger matching, existing `_matches`), `urllib.parse` (locator
host extraction). **No new runtime dependency** (Principle V).
**Storage**: filesystem under vault root. `<vault>/modules/<name>/manifest.yaml`
(`triggers[]`, existing) is the binding surface; `research.spec.md::data_sources[].kind`
(NEW optional). FR3 reads/writes the existing `_pipeline/cycles/cycle-NNN-quality-report.json`
`degraded_sources` + `source-incidents.md`; no new artifact.
**Testing**: pytest, seven-tier pyramid (ADR-0008). New tier-2 validator suite
(backed vs strategy_hint vs error), tier-2 trigger-matching unit tests (reuse
`TriggerRegistry`), tier-3 preflight fail-closed, tier-2 stagnant-signal + status,
hermetic (no live network).
**Target Platform**: macOS / Linux dev + CI.
**Project Type**: single-project Python CLI + Jinja2-templated vault scaffold + drop-in
source modules.
**Performance Goals**: validation is O(sources × modules) at scaffold/preflight time
(tiny); stagnant signal is O(sources) per cycle reading existing JSON. No hot-path
regression.
**Constraints**: determinism (Principle IV) — validation + stagnant signal are pure
(no LLM; the relevance classifier itself, FR4, is deferred). FR1/FR2 must **fail
closed** (clear "source X declared but has no implementation" message), never silently
empty. FR3 is **advisory WARN** (Q4) — never blocks a cycle. Must not break existing
vaults that omit `kind` (treated as "needs a trigger-matching module or it's an error
only when truly unbacked").
**Scale/Scope**: ~4 source files touched (`spec/schema.py`, `spec/validator.py`,
`pipeline/preconditions.py`, `pipeline/quality_report.py`) + `cli/status.py` +
`scripts/validate_spec.py` + reuse of `source_bridge/discovery.py`; ~1–1.5 days. Adds
~35–45 tests. FR4 sub-spec filed separately.

### Resolved unknowns (full detail in research.md)

- **D1** — The binding mechanism already exists: manifest `triggers[]` +
  `TriggerRegistry.match`. 069 **uses** it for validation (its result is discarded
  today). Trigger types: `url_pattern`, `path_pattern`, `path_exists` (+ `domain` in
  code; add to the schema enum).
- **D2** — A declared source's **locator** (what gets matched against triggers) =
  the first non-empty of the **already-existing** fields `repos[].url`,
  `repos[].local_path`, `local_path`. **DECIDED (analyze U2):** v1 does NOT add a new
  `locator`/`url` field — these existing fields cover every rc7 source (incl. the
  `gh`/GitHub case). A dedicated optional `locator` hint is deferred until a real
  source needs one (no schema task in 069). Descriptive sources with **no concrete
  locator** ("Web", "Official Documentation") cannot match a trigger and therefore
  MUST be `kind: strategy_hint` — exactly the honest outcome (LLM-fetch, no module).
- **D3** — `kind` enum: `module_backed` (default/implicit, must trigger-match) and
  `strategy_hint` (LLM-fetch, no module required). Absent `kind` ⇒ inferred: if it
  trigger-matches → backed; if not → **scaffold error** demanding either a module or
  an explicit `strategy_hint`. So existing valid specs (whose sources DO match) keep
  working with no edit; only genuinely-unbacked sources must be annotated.
- **D4** — Two validation gates: `spec/validator.py::validate` (the `generate` path)
  and `scripts/validate_spec.py` (the vault-spec skill pre-scaffold gate). Runtime
  fail-closed lives in `preconditions.py` check #6 (resume path) + a new check on the
  generate path (generate currently skips `preconditions.check`).
- **D5** — Stagnant signal reuses the existing `degraded_sources` surface
  (`quality_report._degraded_sources` + `_pipeline/source-incidents.md`) and the
  `source_ledger.load_declared_sources` join; surfaced via `status.build_status_json`'s
  `deferred_warnings` pattern. ≥2-consecutive-cold is computed from per-cycle ledger
  verdicts.
- **D6** — **FR4 (relevance-classifier tuning) is out of 069's locked scope** (Q3);
  filed as a follow-up sub-spec. 069 ships the honest-coverage structural fix only.

## Constitution Check

*GATE: evaluated against constitution v1.4.0.*

| Principle | Verdict | Notes |
| --- | --- | --- |
| **I. Script-Validated Quality Gates** | ✅ PASS (reinforces) | FR1/FR2 are deterministic scaffold/preflight gates; FR3 is a deterministic signal. No LLM in any new gate. |
| **II. Phase Sequencing** | ✅ PASS | No cycle-phase reordering; FR2 runs at the existing preflight point; FR3 at cycle-end reporting. |
| **III. Test-First (TDD)** | ✅ PASS | Each FR ships tests with/before impl; foreman `Testing Requirements` at `/tasks`. |
| **IV. Agent-Script Separation** | ✅ PASS (reinforces) | Validation + stagnant signal are pure; the LLM relevance classifier (FR4) is **deferred**. Dispatch allowlist stays empty. |
| **V. Offline-First, No External Persistence** | ✅ PASS | No new dep; trigger matching is local pattern matching, no network. |
| **VI. No Duplicate Notes** | ✅ N/A | Source plumbing only. |
| **VII. External Sources Mandatory** | ✅ PASS (reinforces) | 069 makes the framework HONEST about which declared sources actually contribute — directly serves "external sources mandatory" by refusing to pretend an unbacked source is live. |
| **VIII. No Placeholders / Stub-as-Fuel** | ✅ PASS (reinforces) | Fails closed on declared-but-unimplemented sources instead of silently producing empty signals. |
| **IX. Vault-First Citation** | ✅ N/A | Untouched. |
| **X. Vault History is Append-Only Git** | ✅ PASS | No new persisted state beyond the existing quality report; committed by the normal cycle path. |

**Ask-First items (resolved at /analyze):**
1. **`kind` default semantics — DECIDED (analyze U3).** Absent `kind` is inferred:
   trigger-match → backed; no match → scaffold error demanding a module or an explicit
   `strategy_hint`. No third "ambiguous" state. (The alternative — default
   `module_backed` + force every existing spec to add `kind` — is rejected as more
   disruptive.) Encoded in `source_is_backed` (tasks T004/T022).
2. **FR4 split — DECIDED (analyze G1).** Relevance-classifier tuning is deferred to a
   follow-up sub-spec (Q3). 069 does **not** implement FR4; tasks T023 files the
   sub-spec instead. spec.md FR4 is annotated DEFERRED.

**Gate result: PASS.** Complexity Tracking empty.

### Post-Design Re-check (after Phase 1)

One additive optional field (`DataSourceConfig.kind`); existing specs whose sources
trigger-match remain valid without edits, so **no `schema_version` bump** (data-model
"Migration"). The binding reuses the already-shipped `TriggerRegistry` (no new
matching engine). FR4 deferral keeps scope tight. Verdict remains **PASS**.

## Project Structure

### Documentation (this feature)

```text
specs/069-source-relevance-tuning/
├── plan.md          # This file
├── spec.md          # Feature spec (clarified 2026-06-15, 4/4; FR4 split)
├── research.md      # Phase 0 — decisions D1–D6 + rc7 source audit
├── data-model.md    # Phase 1 — DataSource.kind, manifest triggers, backing resolution, stagnant signal
├── contracts/
│   ├── declared-source-validation.contract.md  # backing rule + kind + scaffold/preflight gates
│   └── stagnant-source-signal.contract.md       # ≥2-cold WARN + status surface + 053 weighting
├── quickstart.md    # Phase 1 — reproduce the rc7 silent-empty; prove validation + signal fix it
└── tasks.md         # Phase 2 (/speckit.tasks — NOT created here)
```

### Source Code (repository root) — files touched, by FR

```text
src/research_framework/
├── spec/
│   ├── schema.py            # FR1: DataSourceConfig.kind (NEW optional: module_backed | strategy_hint)
│   └── validator.py         # FR1: backing validation in validate() — trigger-match OR strategy_hint OR error
├── pipeline/
│   ├── source_bridge/
│   │   └── discovery.py     # FR1: reuse build_trigger_registry + TriggerRegistry.match (add `domain` to schema enum)
│   ├── preconditions.py     # FR2: check #6 fails closed on declared-but-unbacked source (resume + add to generate)
│   ├── preflight.py         # FR2: check_all reports backing status per source
│   ├── quality_report.py    # FR3: stagnant-source (≥2-cold) into degraded_sources / write_report
│   └── source_authority.py  # FR5: authority weighting for the stagnant signal
└── cli/
    └── status.py            # FR3: build_status_json surfaces the stagnant-source WARN

scripts/
├── validate_spec.py         # FR1: pre-scaffold skill gate — same backing rule (warn/error)
└── source_ledger.py         # FR3: load_declared_sources join → ≥2-consecutive-cold computation

specs/020-code-bridge/contracts/manifest.schema.json  # FR1: document `domain` trigger type (code already supports it)

tests/
├── spec/
│   └── test_validator_source_backing.py   # FR1: backed (trigger-match) ok; unbacked → error; strategy_hint ok
├── pipeline/
│   ├── test_trigger_matching.py           # FR1: declared-source locator ⊗ manifest triggers
│   ├── test_preflight_source_backing.py   # FR2: fail-closed on unbacked source
│   └── test_stagnant_source_signal.py     # FR3/FR5: ≥2-cold WARN; authority weighting
└── cli/
    └── test_status_stagnant.py            # FR3: status surfaces the WARN
```

**Structure Decision**: single-project layout reusing the spec-020 source-module
architecture. The headline reuse is `source_bridge/discovery.py::TriggerRegistry`
(already shipped, currently under-used) for the backing check; the only schema delta is
one optional `DataSourceConfig.kind`. FR4 is filed as a separate sub-spec.

## Phase Sequencing for implementation (dependency-ordered)

FR1 (schema + backing rule) is the foundation; FR2 wires the same rule into runtime
preflight; FR3/FR5 are the cycle-time signal; FR4 is out of scope. Recommended
`/speckit.tasks` ordering:

1. **FR1** (≈0.5d) — add `DataSourceConfig.kind`; implement `source_is_backed(source,
   modules)` using `TriggerRegistry.match` against the source locator (D2); wire into
   `spec/validator.py::validate` + `scripts/validate_spec.py` (warn at skill stage,
   hard error at generate). Document `domain` trigger in the manifest schema. Tests:
   trigger-matched source ok; unbacked source → error; `strategy_hint` ok.
2. **FR2** (≈0.3d) — `preconditions.py` check #6 fails closed on declared-but-unbacked
   sources (resume) + add the check to the generate path; `preflight.py::check_all`
   reports per-source backing. Tests: unbacked source blocks generate with a clear
   message; `strategy_hint` passes.
3. **FR3 + FR5** (≈0.4d) — compute ≥2-consecutive-cold from `source_ledger`
   verdicts; emit a WARN into `quality_report.degraded_sources` weighted by
   `source_authority` (FR5); surface via `status.build_status_json`. Tests: a source
   cold ≥2 cycles → WARN; authoritative-cold weighted worse; advisory (never blocks).
4. **(out of scope)** FR4 relevance-classifier tuning → **file a follow-up sub-spec**
   (`/speckit.specify`) referencing the `gh`-went-cold rc7 case; not implemented here.

**Pre-`/speckit.implement`**: dispatch the test-design subagent (ADR-0010); implement;
foreman Arm A + Arm B before the PR.

## Complexity Tracking

> No Constitution Check violations require justification. Table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
