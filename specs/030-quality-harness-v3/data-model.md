# Data Model: Quality Harness v3

## 1. `source_quality` metric family

Registered as a 4th `MetricFamily` in
`quality/metrics/__init__.py::REGISTERED_METRIC_FAMILIES`, computed by
`quality/metrics/source_quality.py::compute_source_quality_metric(fixture,
cycle_outputs)`. All four values are floats in `[0.0, 1.0]`, truncated via
`_helpers.truncate_float` for byte-determinism.

| Metric | Type | Range | Direction (`baseline_subset`) | Source | Definition |
|---|---|---|---|---|---|
| `source_diversity_shannon` | float | [0,1] | `higher_is_better` | `source_cycles.notes_generated` | normalized Shannon entropy of notes-per-source over the run's cycles; `0.0` = single-source monopoly |
| `broken_source_rate` | float | [0,1] | `lower_is_better` | `sources.status`, `sources.consecutive_empty_cycles` | (# broken sources) / (total sources); broken = `status != 'active'` OR `consecutive_empty_cycles >= broken_source_empty_cycles` (default 3) |
| `spec_source_utilization` | float | [0,1] | `higher_is_better` | `source_cycles.notes_generated` | (# sources with ≥1 note this run) / (total declared sources) = `(N−M)/N` |
| `tier2_source_ratio` | float | [0,1] | `lower_is_better` | tier map (module `sources.yaml::tier` → fixture `tier-map.json` → default tier-1) + `source_cycles` | (# tier-2 sources used) / (# sources used); `0.0` when no tier map declared |

```python
MetricFamily(
    name="source_quality",
    compute_fn=compute_source_quality_metric,
    metrics=[
        "source_diversity_shannon",
        "broken_source_rate",
        "spec_source_utilization",
        "tier2_source_ratio",
    ],
    baseline_subset={
        "source_diversity_shannon": "higher_is_better",
        "broken_source_rate": "lower_is_better",
        "spec_source_utilization": "higher_is_better",
        "tier2_source_ratio": "lower_is_better",
    },
)
```

All four participate in the moderate regression gate (FR-002): a metric
that drifts > 5% in the worse direction WARNs, > 15% FAILs. (Note: for
`lower_is_better` metrics already at `0.0`, the existing `baseline.py`
delta logic governs the divide-by-zero handling — no special case added
here.)

## 2. Baseline JSON shape (per fixture)

`tests/fixtures/quality/baselines/<fixture>.baseline.json` gains one new
subtree under `metrics`. The envelope (`schema_version`,
`baseline_commit`, `coverage_targets_hash`, `last_updated*`) is unchanged.
`schema_version` stays `"1.0"` — the metrics dict is open/additive, so a
new family is **not** a schema-version bump.

```jsonc
{
  "schema_version": "1.0",
  "fixture": "tech-lite",
  "baseline_commit": "<sha>",
  "coverage_targets_hash": "sha256:…",
  "last_updated": "2026-…Z",
  "last_updated_by": "conductor",
  "last_updated_reason": "Spec 030 v3 — add source_quality family",
  "metrics": {
    "coverage": { "...": "unchanged" },
    "cycle_health": { "...": "unchanged" },
    "note_quality": { "...": "unchanged" },
    "cost_efficiency": { "...": "unchanged" },
    "source_quality": {
      "source_diversity_shannon": 0.0,
      "broken_source_rate": 0.0,
      "spec_source_utilization": 0.0,
      "tier2_source_ratio": 0.0
    }
  }
}
```

The 3 existing fixtures (`tech-lite`, `source-poor`, `source-rich`) get
the subtree appended at the blessed run values (likely `0.0` for the
utilization/diversity metrics given their currently-empty `source_cycles`
tables — see research.md). The 3 new fixtures ship full all-family
baselines.

## 3. New fixture vault shape (per the 022 v1 contract)

Each of `embedded-firmware`, `childcare`, `gaming` under
`tests/fixtures/quality/<name>/`:

```text
<name>/
├── research.spec.md          # domain spec (the ONLY domain knowledge source)
├── settings.yaml             # max_cycles ≤ 3 (perf budget)
├── coverage-targets.json     # drives coverage metric + baseline hash
├── _templates/               # note-type templates (read, not hardcoded)
├── fake_agent_responses/     # canned scout/research/verifier JSON
├── data_vault/               # canned notes (vault-shaped content)
├── _pipeline/sources.db      # seeded sources + source_cycles for source_quality
└── canonical-questions.json  # 5–10 {question, expected_shape} pairs (US3)
```

Registered in `runner.py`:

```python
REGISTERED_FIXTURES = {
    "tech-lite": "code-derived-topic-discovery",
    "source-poor": "gap-pursuit-substitution",
    "source-rich": "source-quality-pruning",
    "embedded-firmware": "note-density-citation-precision",
    "childcare": "prompt-vs-domain-mismatch",
    "gaming": "novel-terminology-vault-lift",
}
_NOTE_COUNT_TARGETS = { ...existing..., "embedded-firmware": <n>, "childcare": <n>, "gaming": <n> }
```

## 4. `canonical-questions.json` shape (US3)

```jsonc
[
  {
    "id": "q1",
    "question": "What is <domain concept>?",
    "expected_shape": {
      "key_facts": ["fact a", "fact b"],
      "must_cite": true
    }
  }
]
```

Per-fixture; consumed only by the opt-in comparison step. An empty array
or absent file → comparison skipped for that fixture (Edge Case 2).

## 5. `comparison.json` shape (US3, opt-in, gitignored per-run)

`_pipeline/quality/<fixture>.comparison.json`:

```jsonc
{
  "schema_version": "1.0",
  "fixture": "gaming",
  "run_timestamp": "2026-…Z",
  "question_count": 8,
  "deltas": {
    "accuracy_delta": 0.4,
    "specificity_delta": 0.3,
    "citation_density_delta": 2.1,
    "hallucination_delta": 0.25
  }
}
```

`deltas` values are `null` when the comparison was skipped (no live_llm /
empty question set) — distinct from `0.0` ("measured, no lift"). Whether
a typed `ComparisonResult` dataclass lands in `quality/models.py` is an
implementation choice; the JSON shape above is the stable surface (see
contracts/).

## 6. Typed-step-result fields (US4)

Field-level deltas in `pipeline/steps/_types.py`:

| Dataclass | Field | Status before v3 | v3 action |
|---|---|---|---|
| `ScoutResult` | `sg_trips: list[SafetyGateTrip]` | exists; always `[]` | FR-007: populate |
| `ScoutResult` | `exit_code: int` | exists; populated | (no change) |
| `ResearchResult` | `notes_rejected: list[VerifierRejection]` | exists; always `[]` | FR-008: populate |
| `ResearchResult` | `exit_code: int` | **missing** | FR-009: **add field** + assign |
| `PostprocessResult` | `wikilink_fixes: list[WikilinkFix]` | stubbed | FR-011: populate |
| `PostprocessResult` | `coverage_delta: CoverageDelta` | `CoverageDelta()` zeroed | FR-011: populate |

`ResearchResult.exit_code` is an additive field with a default
(`exit_code: int = 0`) to preserve the frozen-dataclass call sites that
do not yet pass it — non-breaking.
