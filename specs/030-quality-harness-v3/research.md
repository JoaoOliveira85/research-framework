# Research: Quality Harness v3

Thin by design — one decision per open computation. Grounding spot-checks
done against the live 022 harness (`quality/runner.py`,
`quality/metrics/`) and a real fixture `_pipeline/sources.db`.

## Data source: `_pipeline/sources.db` (already present per fixture)

Verified schema (SQLite, stdlib `sqlite3`, no new dep):

```sql
CREATE TABLE sources (
    name TEXT PRIMARY KEY, type TEXT, role TEXT, url TEXT,
    first_seen_cycle INTEGER, locked INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active', consecutive_empty_cycles INTEGER DEFAULT 0
);
CREATE TABLE source_cycles (
    name TEXT REFERENCES sources(name), cycle INTEGER,
    notes_generated INTEGER DEFAULT 0, topics_covered INTEGER DEFAULT 0,
    tags_generated INTEGER DEFAULT 0, notes_referencing INTEGER DEFAULT 0,
    PRIMARY KEY (name, cycle)
);
```

This single file feeds 3 of the 4 metrics outright. The calculator opens
the fixture's `sources.db` read-only and aggregates over the cycles the
harness just ran (the harness already knows `cycle_outputs`, so it scopes
to `cycle IN (those cycle numbers)`).

**Decision**: `source_quality.py` reads `sources.db` only — no note-body
parsing, no frontmatter walk. Keeps the calculator deterministic and
fast (sub-second), and reuses the pipeline's own source bookkeeping
rather than re-deriving it.

## Metric 1 — `source_diversity_shannon`

**Unit (Edge Case 4 resolved)**: notes-per-source. The distribution is
`notes_generated` per source over the run's cycles (the `source_cycles`
table). Rationale: the spec's motivating failure is "all notes from one
source" — that is a *note-production* concentration, so notes-per-source
is the faithful unit (not citations-per-source, not facts-per-source,
both of which would require note-body parsing we deliberately avoid).

**Computation**: normalized Shannon entropy in bits.

```
n_i = notes_generated for source i (summed across run cycles)
N   = Σ n_i over sources with n_i > 0
p_i = n_i / N
H   = -Σ p_i * log2(p_i)
S   = number of sources with n_i > 0
shannon = H / log2(S)   if S > 1 else 0.0   (normalized to [0,1])
```

Normalizing by `log2(S)` keeps the metric in `[0,1]` and comparable
across fixtures with different source counts. `1.0` = perfectly even
spread; `0.0` = single-source monopoly (the regression we want to catch).
Truncate via the existing `_helpers.truncate_float` for determinism.

**Broken cases**: `N == 0` (no notes this run) → `0.0`. `S == 1` → `0.0`
(one source carries everything — maximally concentrated). `S == 0` →
`0.0`.

## Metric 2 — `broken_source_rate`

**"Broken" definition (Edge Case 3 resolved)** — a source is *broken*
for the run if EITHER:

- its `sources.status` is not `'active'` (the pipeline marks
  `'broken'` / `'retired'` / `'preflight_failed'` here; spec 051's
  mandatory `preflight()` contract writes failure verdicts that the
  source manager reflects into this column), OR
- it has been empty for the staleness window: `consecutive_empty_cycles
  >= broken_source_empty_cycles` (default **3**, the same threshold the
  source manager already uses to retire a source). This captures
  "returned-empty" from the Edge Case list.

The remaining Edge-Case candidates map as follows: *preflight failure* →
`status` column (set by the orchestrator's preflight sweep); *5xx /
timeout* → also surfaced as `status='broken'` by the
capture/source-incident path. The harness does **not** itself probe the
network (Principle V / offline-first) — it reads the verdict the pipeline
already recorded. This is the correct separation: scripts measure
recorded state, they do not re-run preflight.

**Computation**: `broken_source_rate = (# broken sources) / (total
sources)`. Acceptance Scenario 2 (3 of 10 broken → 0.3) holds directly.
`total == 0` → `0.0`. `lower_is_better`.

## Metric 3 — `spec_source_utilization`

**Definition** (matches Acceptance Scenario 1: `(N-M)/N` with M unused):

```
N = total sources declared (rows in `sources`)
used = sources with Σ notes_generated > 0 over the run's cycles
spec_source_utilization = used / N
```

A source is "used" if it produced at least one note in the cycles the
harness ran (`source_cycles.notes_generated > 0`). `N == 0` → `0.0`
(no declared sources — a degenerate fixture). `higher_is_better`.

**Note for fixture authoring**: the existing `source-rich` fixture has 5
`sources` rows but an empty `source_cycles` table, so on it
`spec_source_utilization == 0.0` today. That is a *correct* baseline
value to commit (the fixture's canned cycles record no per-source note
attribution); fixtures that want a non-zero baseline must seed
`source_cycles` rows. This is a fixture-data decision, not a calculator
bug — captured here so baseline-blessing is not mistaken for a regression.

## Metric 4 — `tier2_source_ratio`

**Intent**: fraction of consulted sources that are Tier-2 (lower-authority
/ aggregator) vs Tier-1 (primary). The spec's failure mode is "tier-2
sources displacing tier-1 sources" — a creeping ratio is the signal.

**The one genuine unknown**: `sources.db` has no `tier` column. Candidate
tier sources, in preference order:

1. Per-module `<vault>/modules/<name>/sources.yaml::tier` (spec 020
   modules expose a `tier:` field) — authoritative where present, but
   the quality fixtures are not module-shaped, so this is empty for them.
2. The `sources.type` column (`external` / `code`) as a coarse proxy —
   present but does not encode authority tier.
3. A per-fixture `tier-map.json` sidecar declaring `source_name → tier`
   that the fixture author commits alongside `coverage-targets.json`.

**Recommendation (assumed, proceed)**: weight the consulted-source count
by a tier map resolved in this order — module `sources.yaml::tier` if
present, else a fixture-local `tier-map.json`, else default every source
to tier-1 (so the ratio is `0.0` and never produces a false WARN on a
fixture that hasn't declared tiers). `tier2_source_ratio = (# tier-2
sources used) / (# sources used)`. `lower_is_better`.

> [NEEDS CLARIFICATION: is a fixture-local `tier-map.json` the accepted
> tier source for the quality fixtures, or should v3 add a `tier` column
> to `sources.db` (a pipeline-schema change, Ask-First per the
> constitution)? The plan ASSUMES the sidecar map to avoid a schema
> change; confirm before `/speckit.tasks` finalizes the fixture
> contract.]

## Comparison deltas (US3, opt-in)

Each fixture's `canonical-questions.json` lists 5–10 `{question,
expected_shape}` pairs. The comparison runs each question twice: a
**baseline** prompt with zero vault context, and the vault `/ask` prompt
(Principle IX two-tier citations). Four deltas, each `vault_score −
baseline_score` averaged over the question set:

- `accuracy_delta` — fraction of questions whose answer matches
  `expected_shape` key facts (rubric-scored by the comparison step's own
  grader prompt; deterministic given fixed model output is NOT assumed —
  this is why the step is opt-in and non-gating).
- `specificity_delta` — presence of concrete specifics (names, numbers,
  dates) vs vague prose.
- `citation_density_delta` — Tier-1 `[[wikilink]]` count per answer
  (vault run should be strictly higher; baseline has none → typically the
  full vault density).
- `hallucination_delta` — fraction of claims not supported by any cited
  source (lower for the vault run; reported as `baseline − vault` so a
  positive delta means the vault reduced hallucination).

**Edge Case 1 (no live_llm)**: if no `claude`/`codex` CLI is reachable (or
the `quality_comparison` marker is not selected), the step is *skipped*,
not failed — it writes no `comparison.json` and emits a skip line. The
default `./build.sh --quality` never reaches this step.

**Edge Case 2 (empty question set)**: a fixture with an empty or absent
`canonical-questions.json` is skipped for the comparison with an INFO
line; the 4 deltas are reported as `null` (not `0.0`, which would imply
"measured no lift"). The non-comparison metrics still run.

## Spot-check: does the 022 architecture extend cleanly?

Yes (Assumption 1 confirmed):

- A 4th family is one more `MetricFamily(...)` entry in
  `REGISTERED_METRIC_FAMILIES`; `compute_all_metrics` /
  `runner._compute_metrics` iterate the list generically — no per-family
  branching to touch.
- `baseline_subset` already drives the regression gate per-metric with
  `higher_is_better` / `lower_is_better` directions and the moderate
  >5% WARN / >15% FAIL thresholds (FR-002) — the 4 new metrics just add
  their direction entries.
- `CurrentJSON.metrics` is an open `dict[str, dict]`; the new subtree
  needs no model change. `assert_deterministic` already wraps it.

## Typed-step holes — exact present state (US4)

Confirmed by reading source (not inferred):

- `pipeline/steps/_types.py`: `ScoutResult.sg_trips` and
  `ScoutResult.exit_code` **fields exist**; `ResearchResult.notes_rejected`
  **field exists**; `ResearchResult` has **NO `exit_code` field** (FR-009
  must add it).
- `pipeline/steps/scout.py::run_scout` builds `trips: list = []` and never
  appends — `sg_trips` always empty (FR-007 fix: harvest SG-001/002/003
  FAIL/WARN trips from the cycle's gate results / batch JSON into the
  list).
- `pipeline/steps/research.py::run_research` builds `rejected: list = []`
  and never appends — `notes_rejected` always empty (FR-008 fix: read the
  verifier report's `rejected` verdicts into `VerifierRejection` rows).
- `pipeline/steps/postprocess.py::run_postprocess` returns
  `coverage_delta=CoverageDelta()` (zeroed) and `wikilink_fixes=fixes`
  where `fixes` is stubbed (FR-011 fix: populate from the actual
  wikilink-normalization + coverage-promotion counts already computed in
  the step body).
- `quality/metrics/cycle_health.py::_sg002_trips_for_cycle` prefers the
  typed `scout_result.sg_trips` but **falls back** to filesystem-scraped
  `cycle.sg_trips`; `compute_cycle_health_metric` similarly falls back to
  `cycle-NNN-verifier.json` for rejections. FR-010: once FR-007/008 land,
  delete both fallbacks and assert (test) they cannot reappear.

No architectural change required — these are local population fixes plus
one additive dataclass field.
