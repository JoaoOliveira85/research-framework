# Contract: `source_quality` metric subtree

**Status**: stable. This subtree is committed in every
`tests/fixtures/quality/baselines/<fixture>.baseline.json` and byte-diffed
against each run's `<fixture>.current.json`. Changing its keys, value
types, or rounding is a breaking change that invalidates all committed
baselines and MUST re-bless them in the same PR.

## Location

`<current|baseline>.metrics.source_quality` — a sibling of `coverage`,
`cycle_health`, `note_quality`, `cost_efficiency` under the open `metrics`
dict.

## Shape

```jsonc
"source_quality": {
  "source_diversity_shannon": <float in [0.0, 1.0]>,
  "broken_source_rate":       <float in [0.0, 1.0]>,
  "spec_source_utilization":  <float in [0.0, 1.0]>,
  "tier2_source_ratio":       <float in [0.0, 1.0]>
}
```

- Exactly these 4 keys. No extra keys. No nested objects.
- All values are floats (never int, never null) in `[0.0, 1.0]`.
- Values are truncated for byte-determinism (via
  `quality.metrics._helpers.truncate_float`); the same `sources.db` MUST
  yield byte-identical output across runs and platforms (no
  `datetime.now()`, no set iteration order, no platform float drift).

## Semantics (authoritative — see research.md / data-model.md)

| Key | Direction | Meaning |
|---|---|---|
| `source_diversity_shannon` | higher_is_better | normalized Shannon entropy of notes-per-source; `0.0` = single-source monopoly, `1.0` = perfectly even |
| `broken_source_rate` | lower_is_better | (# broken sources) / (total); broken = `status != 'active'` OR `consecutive_empty_cycles >= 3` |
| `spec_source_utilization` | higher_is_better | (# sources producing ≥1 note this run) / (total declared) |
| `tier2_source_ratio` | lower_is_better | (# tier-2 sources used) / (# sources used); `0.0` when no tier map is declared |

## Regression gate

Each key is registered in the family's `baseline_subset` with its
direction and participates in the moderate gate inherited from 022:
> 5% drift in the worse direction → WARN; > 15% → FAIL (FR-002).

## Degenerate inputs (MUST NOT raise)

| Input | Required output |
|---|---|
| `source_cycles` empty / no notes this run | diversity `0.0`, utilization `0.0` |
| exactly one source with notes | diversity `0.0` |
| `sources` table empty | all four `0.0` |
| no tier map declared anywhere | `tier2_source_ratio` `0.0` |

The calculator opens `sources.db` read-only; a missing DB file yields all
four `0.0` (treated as a fixture with no recorded source activity), never
an exception.
