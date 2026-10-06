# Implementation Plan: Quality Harness v3

**Branch**: `030-quality-harness-v3` | **Date**: 2026-06-03 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/030-quality-harness-v3/spec.md`

> **⚠️ SCOPE UPDATE (2026-06-03, post-plan):** `tier2_source_ratio` was **DROPPED**
> from v3 — the `source_quality` family is now **3 metrics**
> (`source_diversity_shannon`, `broken_source_rate`, `spec_source_utilization`).
> The 4th metric needs a real contextual source-credibility model and is deferred
> to **spec 055 (Wave 2)**. **Any `tier2_source_ratio` / `tier-map.json` / "tier"
> content below (incl. in `data-model.md`, `research.md` §Metric 4, and
> `contracts/`) is SUPERSEDED — ignore it at `/speckit.tasks`.** The NEEDS
> CLARIFICATION about a `tier` column / sidecar is resolved by the deferral.

## Summary

Close the three deliberate 022 v1/v2 deferrals plus the audit's hollow
typed-step-result holes, scoped to what `/speckit.clarify` left binding:

1. **4th metric family `source_quality`** (`source_diversity_shannon`,
   `broken_source_rate`, `spec_source_utilization`, `tier2_source_ratio`)
   — a new `quality/metrics/source_quality.py` calculator registered in
   `REGISTERED_METRIC_FAMILIES`, fed entirely from the already-present
   `_pipeline/sources.db` (SQLite) per-fixture, with one new baseline
   subtree per fixture. No new pipeline writes.
2. **3 deferred fixtures** (`embedded-firmware`, `childcare`, `gaming`)
   added under `tests/fixtures/quality/` following the 022 v1 fixture
   contract (vault root + `research.spec.md` + `settings.yaml` +
   `coverage-targets.json` + `fake_agent_responses/` + committed baseline),
   registered in `runner.REGISTERED_FIXTURES` + `_NOTE_COUNT_TARGETS`.
3. **Opt-in with-vault-vs-without-vault `/ask` comparison** — a new harness
   step computing 4 deltas (`accuracy_delta`, `specificity_delta`,
   `citation_density_delta`, `hallucination_delta`), gated behind BOTH the
   existing `live_llm` opt-in marker AND a new `quality_comparison` marker.
   It is **NOT** wired into the default `./build.sh --quality` path and
   **NOT** invoked by `release.yml`; a separate `--quality-deep` flag (or
   `--quality --comparison`) is the only trigger.
4. **Fill the hollow typed-step hooks**: populate `ScoutResult.sg_trips`
   (FR-007), `ResearchResult.notes_rejected` (FR-008), add and assign
   `ResearchResult.exit_code` (FR-009), then delete the filesystem-fallback
   branches in `cycle_health.py` (FR-010). Also make
   `postprocess.run_postprocess` return non-empty `wikilink_fixes` /
   `CoverageDelta` when work happened (FR-011).

**Explicitly OUT (clarify-bound)**: FR-012 `template_section_compliance`
is **DEFERRED to v4** (not implemented here). FR-014 per-release-hotfix
tracking lands as a `docs/RELEASE.md` checklist item, **not** a harness
metric. FR-013 (cost watch-item record-only fields) rides on the
already-shipped `cost_efficiency` family and spec 028 sidecars — recorded,
never gated.

Foundation already exists from 022 v1 (`quality/runner.py`,
`quality/metrics/`, `quality/baseline.py`, `quality/report.py`,
`quality/determinism.py`) and the typed step results in
`pipeline/steps/_types.py`. v3 extends those seams without rework — see
the spot-check in research.md.

## Technical Context

**Language/Version**: Python 3.11+ (per `pyproject.toml`
`requires-python = ">=3.11"` and constitution Technology Constraints).
**Primary Dependencies**: existing only — `pyyaml ≥ 6.0`; stdlib `sqlite3`,
`json`, `pathlib`, `math` (for Shannon entropy), `dataclasses`, `argparse`.
**No new runtime dependencies** — Principle V is non-negotiable. The
`/ask` comparison reuses the existing `claude`/`codex` dispatch path
through `scripts/agent_call.py`; it adds no client library.
**Storage**: filesystem under `tests/fixtures/quality/` (committed) +
`_pipeline/quality/` per-run workspace (gitignored). New committed
artifacts: 3 fixture vault trees + 6 `*.baseline.json` touch-points (3 new
fixtures × all-families baseline + 3 existing fixtures gain a
`source_quality` subtree). New per-run artifacts: the `source_quality`
subtree inside each `<fixture>.current.json`; an opt-in
`<fixture>.comparison.json` (gitignored) only when `--quality-deep` runs.
**Testing**: pytest. Metric-calculator unit tests at tier-1
(`tests/quality/unit/`); fixture round-trip + baseline-diff at the
harness tier (tier-6 e2e). Typed-step-result population tests at tier-1
against `pipeline/steps/{scout,research,postprocess}.py`. The `/ask`
comparison test carries `@pytest.mark.live_llm` + a new
`@pytest.mark.quality_comparison` and is skipped in every default
collection. `.venv/bin/python -m pytest` is the runner; ruff zero-baseline
applies to all new code.
**Target Platform**: macOS (developer) + Linux (GitHub Actions). The
`/ask` comparison only runs where a `claude`/`codex` CLI is reachable;
absent that it skips gracefully (Edge Case 1).
**Project Type**: CLI tool extension — extends `quality/`, adds a
`./build.sh --quality-deep` shell flag, and a `quality_comparison` pytest
marker. No new web service or external interface.
**Performance Goals**: SC-005 — `./build.sh --quality` wall-clock grows by
≤ 50% going from 3 → 6 fixtures (current ~5 min → max ~7:30). The
`source_quality` family is a pure SQLite read per fixture (sub-second), so
the growth is dominated by 3 extra fixture cycle-runs, not the new metric.
The `/ask` comparison is opt-in and excluded from this budget.
**Constraints**: byte-deterministic JSON output (inherited from 022 — no
`datetime.now()` in metric values, sorted keys via `determinism.py`). The
`source_quality` calculator MUST be deterministic given a fixed
`sources.db`. No live LLM in the default/gating path (FR-005). No
auto-baseline-write — baselines are committed via the existing
`quality/baseline_update.py` / `./vault quality-baseline-update` flow.
**Scale/Scope**: 6 fixtures × 4 metric families × ≤ 3 cycles in a default
harness run; +1 opt-in comparison step. Baselines ~6–16 KB each.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|---|---|---|
| I — Script-Validated Quality Gates (NON-NEGOTIABLE) | ✅ Aligned | `source_quality` is a new script-validated signal under the same `./build.sh --quality` exit-0/1 gate. The opt-in comparison is a separate non-gating diagnostic. |
| II — Phase Sequencing (NON-NEGOTIABLE) | ✅ N/A | Harness orchestrates fixture test phases via fake_agent; does not alter the framework's three-phase contract. Typed-step fixes change *what fields carry data*, not phase order. |
| III — Test-First (TDD — NON-NEGOTIABLE) | ✅ Aligned | Metric-calculator + typed-step-population unit tests land before/with implementation; fixtures are themselves e2e tests; baselines ship in the same PR. |
| IV — Agent-Script Separation of Concerns | ✅ Aligned | `source_quality` is pure script reading `sources.db`. The default gate stays fake-agent-only. The opt-in comparison dispatches a *real* agent but only to *measure* its output deltas — it never lets an agent self-assess the harness verdict. |
| V — Offline-First, No External Data Persistence | ✅ Aligned | No new dependency. `source_quality` reads local SQLite. The comparison reuses the existing dispatch path and is opt-in; it persists nothing off-host. |
| VI — No Duplicate Notes | ✅ N/A | Fixture notes are intentionally distinct canned content. |
| VII — External Sources Are Mandatory | ✅ Aligned | `spec_source_utilization` + `broken_source_rate` directly *measure* the external-source contract the principle mandates. |
| VIII — No Placeholders in Deliverables | ⚠️ See justification | New fixtures use vault-shaped canned content (same 022 v1 Option-B precedent). Typed-step hooks are *filled*, removing the previously-hollow `[]` returns — this aligns with "no placeholders". |
| IX — Vault-First Citation (NON-NEGOTIABLE) | ✅ Aligned | `citation_density_delta` measures the Principle-IX citation lift the vault provides; the comparison surfaces (not bypasses) two-tier grounding. |
| X — Vault History is Append-Only Git (NON-NEGOTIABLE) | ✅ N/A | The harness operates on read-only fixture vaults; it does not run `./vault research` against a user vault. No auto-commit surface touched. |

### Boundary checks

- **Always Do**: harness runs metric-calculator unit tests before tier-6;
  reads each fixture's `_templates/` / `coverage-targets.json` — no
  hardcoded structure.
- **Ask First**: none triggered. v3 adds NO frontmatter field, does NOT
  change exit-code semantics, does NOT change `coverage-targets.json`
  structure. `source_quality` is additive to the metrics subtree;
  baselines re-bless via the existing CLI. Adding the
  `ResearchResult.exit_code` field is an additive dataclass field, not a
  frontmatter-schema change.
- **Never Do**: no external dependency added; default gate stays
  fake-agent-only (the comparison never runs `claude`/`codex` in the
  gating path — guarded by the `quality_comparison` marker the default
  collection deselects).

**Constitution gate: PASS** (pre-Phase-0). Re-check after data-model.

## Project Structure

### Documentation (this feature)

```text
specs/030-quality-harness-v3/
├── plan.md          # This file
├── research.md      # Exact metric computation + "broken" definitions
├── data-model.md    # 4 source_quality metrics + baseline JSON shape
├── quickstart.md    # How to run + add baselines
├── contracts/
│   └── source-quality-metric.contract.md  # stable report-JSON subtree
└── checklists/
    └── requirements.md  # (pre-existing)
```

### Source code (repository root)

**Create**:

```text
src/research_framework/quality/metrics/source_quality.py   # 4-metric calculator
src/research_framework/quality/comparison.py               # opt-in /ask delta step
tests/quality/unit/test_source_quality.py                  # tier-1 calc tests
tests/quality/unit/test_typed_step_results.py              # FR-007/008/009 population
tests/quality/test_quality_comparison.py                   # @live_llm + @quality_comparison
tests/fixtures/quality/embedded-firmware/                  # new fixture vault
tests/fixtures/quality/childcare/                          # new fixture vault
tests/fixtures/quality/gaming/                             # new fixture vault
tests/fixtures/quality/embedded-firmware/canonical-questions.json
tests/fixtures/quality/childcare/canonical-questions.json
tests/fixtures/quality/gaming/canonical-questions.json
tests/fixtures/quality/baselines/embedded-firmware.baseline.json
tests/fixtures/quality/baselines/childcare.baseline.json
tests/fixtures/quality/baselines/gaming.baseline.json
```

**Modify**:

```text
src/research_framework/quality/metrics/__init__.py   # register source_quality family
src/research_framework/quality/runner.py             # REGISTERED_FIXTURES + _NOTE_COUNT_TARGETS; --comparison plumb
src/research_framework/quality/metrics/cycle_health.py  # FR-010: delete filesystem fallback
src/research_framework/pipeline/steps/scout.py       # FR-007: populate sg_trips
src/research_framework/pipeline/steps/research.py     # FR-008/009: notes_rejected + exit_code
src/research_framework/pipeline/steps/_types.py       # FR-009: add ResearchResult.exit_code
src/research_framework/pipeline/steps/postprocess.py # FR-011: real wikilink_fixes/CoverageDelta
src/research_framework/quality/models.py             # comparison.json dataclass (if a typed model is warranted)
tests/fixtures/quality/baselines/tech-lite.baseline.json   # + source_quality subtree
tests/fixtures/quality/baselines/source-poor.baseline.json # + source_quality subtree
tests/fixtures/quality/baselines/source-rich.baseline.json # + source_quality subtree
build.sh                                             # --quality-deep flag (opt-in comparison)
pyproject.toml                                       # register quality_comparison marker
docs/RELEASE.md                                      # FR-014 hotfix-tracking checklist item
```

(`docs/RELEASE.md` is outside the spec dir but is the binding FR-014
target; it is listed here for the implementer, edited at implement time,
not in this planning PR.)

## Phases

### Phase 0 — Research (research.md)

Lock the exact computation of each of the 4 `source_quality` metrics, the
precise "broken" definition (Edge Case 3), the Shannon-entropy unit
(Edge Case 4), the comparison-delta math, and the empty-question-set
behaviour (Edge Case 2). Output: research.md (thin, decision-per-metric).

### Phase 1 — Design (data-model.md, contracts/)

- `data-model.md`: the 4 metric fields + their `baseline_subset`
  directions + the baseline JSON shape delta + the comparison.json shape.
- `contracts/source-quality-metric.contract.md`: the stable
  `metrics.source_quality.*` report-JSON subtree (a contract is warranted
  because baselines are committed and diffed byte-for-byte; the subtree is
  a stable surface other tooling reads).

Re-run Constitution Check after design.

### Phase 2 — Implementation (tasks.md, by /speckit.tasks)

Ordered by dependency:

1. **Typed-step hooks first (US4, P1)** — these are prerequisites for the
   harness to consume real signal and for removing the `cycle_health.py`
   fallback. TDD: write population tests, then fill scout/research/
   postprocess, then delete fallback.
2. **`source_quality` family (US1, P1)** — calculator + registration +
   the 3 existing fixtures' baseline subtrees re-blessed.
3. **3 fixtures (US2, P2)** — author vault trees + canonical-questions +
   full baselines; register in runner.
4. **Opt-in comparison (US3, P1)** — `comparison.py` step + `--quality-deep`
   flag + `quality_comparison` marker + graceful-skip.
5. **FR-013 record-only** fold into existing cost_efficiency emission.
6. **FR-014** `docs/RELEASE.md` checklist line (doc-only).

## Test Approach

- **Tier-1 (`tests/quality/unit/`)**: `source_quality` calculator against
  hand-built `sources.db` fixtures covering each Edge Case (all-one-source
  entropy = 0; 3-of-10-broken rate = 0.3; M-unused utilization; tier-2
  ratio with a known tier map; empty DB graceful zero). Typed-step
  population: SG-002 trip flows into `ScoutResult.sg_trips`; 3 verifier
  rejections flow into `ResearchResult.notes_rejected`; early abort sets
  `ResearchResult.exit_code != 0`; `cycle_health` reads typed `sg_trips`
  with **no** filesystem read (assert via a no-file path).
- **Tier-6 (harness)**: run all 6 fixtures, assert each
  `*.current.json` carries a 4-metric `source_quality` subtree, assert the
  diff against committed baselines is PASS, assert SC-005 wall-clock.
- **Opt-in comparison** (`@pytest.mark.live_llm` + `@pytest.mark.quality_comparison`):
  deselected by default; when run, asserts 4 deltas emit and
  `accuracy_delta ≥ 0.2` on a `tech-lite`-equivalent (SC-003). A separate
  default-collection test asserts the comparison is NOT triggered by
  `./build.sh --quality` (Principle-IV guard: no live dispatch in the gate).
- **Determinism**: `assert_deterministic` already wraps `*.current.json`;
  the `source_quality` subtree must pass it (no time/random/float drift).

## Complexity Tracking

| Item | Why it is not a violation |
|---|---|
| New fixtures use canned vault content | 022 v1 Option-B precedent: vault-shaped fixtures are test data, not shipped deliverables (Principle VIII applies to *delivered* vaults). |
| Opt-in comparison dispatches a real agent | Gated behind two markers, excluded from the gate and from `release.yml`; it measures deltas, never self-assesses the verdict (Principle IV preserved). |
| `tier2_source_ratio` needs a source→tier map absent from `sources.db` | Resolution deferred to research.md; flagged as the one genuine unknown (see [NEEDS CLARIFICATION] there). |
