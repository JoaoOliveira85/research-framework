# ADR-0007: Smoke gate is mandatory and cannot be skipped

**Status**: Accepted
**Date**: 2026-05-18
**Tags**: testing, release-discipline, spec-018, spec-019

## Context

Between 0.2.20 and 0.2.27 we shipped five back-to-back seam-bug
releases. Every one had the same shape: the unit-test suite passed
(1000+ tests green), the developer shipped, and the bundle crashed
on the first real cycle. Examples:

- 0.2.20: `BatchResult` serialization mismatch between
  `pipeline/batch.py` and the report writer. Both files passed
  their own unit tests.
- 0.2.21: TTY/line-buffering issue in `cycle_runner` only
  manifested when stdout was a real terminal, not a unit-test
  capture buffer.
- 0.2.22: `budget.max_usd` vs `budget.max_cost_usd` field aliasing
  drift. Each component had self-consistent tests; the integration
  was broken.
- 0.2.23: Resume-preconditions skipped a stage on the second
  invocation. Unit tests covered each stage in isolation; nobody
  tested resume.
- 0.2.24: `source_file` URL vs `local_path` shape mismatch
  between the source manager and the scout prompt. Both correct
  individually.

The pattern was unmistakable: contract mismatches between two
correct components, where the existing test suite didn't exercise
them together. Spec 018 introduced an end-to-end smoke gate \u2014 a
small suite of tier-4/5 tests that runs an actual
`run_cycle_steps` against fake agents (zero LLM cost) \u2014 to catch
exactly this class.

The gate worked. The release line stabilized. Spec 019 (0.2.28)
expanded the gate's contents to include tier-2 contract tests
(prompt\u2194validator, validate_cycle variants, preconditions).

Then the question arose: should the gate be skippable for emergency
releases? "I know what I'm doing, just let me ship?"

The answer must be no.

## Decision

The smoke gate is **mandatory**. Specifically:

- `build.sh` runs the smoke gate as Step 0, BEFORE any wheel
  build. If the gate fails, the wheel is never produced.
- There is **NO** `--skip-smoke` flag.
- There is **NO** environment-variable escape hatch (no
  `SKIP_SMOKE=1`, no `CI_FAST=1`, etc.).
- The ONLY way to ship a broken bundle is to remove the gate
  invocation from `build.sh`. That requires a code change in a
  reviewed file. The friction is intentional.

The gate's scope is fixed in spec 019:

- All of `tests/pipeline/test_full_cycle_e2e.py`
- All of `tests/pipeline/test_multi_cycle_e2e.py`
- All of `tests/scripts/test_*_contract.py`
- All of `tests/scripts/test_validate_cycle_*.py`
- All of `tests/pipeline/test_preconditions*.py`
- All of `tests/_helpers/`

Adding tests to the gate is encouraged. Removing tests requires a
PR with an explicit rationale.

## Consequences

**Good**:

- No more seam-bug releases. The gate provably catches the class.
- Developers can't accidentally ship a broken bundle (only
  deliberately, via a reviewed code change).
- The gate's runtime (~2 minutes) is small relative to the cost
  of a bad release (a user's full overnight cycle wasted).

**Trade-offs**:

- Builds take ~2 minutes longer. We accept this. The alternative
  cost (debugging a production crash, releasing a hotfix, eroding
  user trust) is orders of magnitude higher.
- Emergency releases are slower. We accept this. If the gate is
  failing, an "emergency" release would ship a known-broken
  artifact \u2014 the right move is to fix the gate failure, not skip it.

## Alternatives considered

- **Make the gate skippable with a flag**. Rejected: every escape
  hatch we've ever added has eventually been used as the default
  path. The friction of removing the gate manually is a feature.
- **Run the gate in CI but not locally**. Rejected: developers
  who only run unit tests locally will keep shipping the same
  class of bug. The gate must be where developers see it.
- **Replace the gate with stricter unit tests**. Rejected: the
  whole point is that unit tests can't catch contract mismatches
  between components. The gate exercises the integration that
  unit tests cannot.

## Tests

`tests/build/test_smoke_gate_enforces_contract_tier.py` was planned
as the meta-test that verifies `build.sh` invokes the gate on each
named tier. Removing the gate invocation from `build.sh` would break
this meta-test as well — a deliberate trap.

**Status (2026-05-20 audit; triage item #9, now at
`docs/TODO.md#restoration-notes`)**: the planned meta-test file is
NOT present in the working tree. Spec-019 task T002
+ T011 planned it; CHANGELOG [0.2.28] and [0.2.29] documented it as
shipped; ADR refers to it; the file never made it into git. Pytest
silently skipped the non-existent path through 0.2.32.

**Compensating control (added 2026-05-20)**: `build.sh` now contains
a pre-flight loop that asserts every `SMOKE_TESTS` entry exists on
disk before invoking pytest. Missing entries are loud build failures.
This prevents the silent-skip regression class even without the
meta-test. Restoration of the meta-test itself is tracked in
`docs/TODO.md` because the meta-test provides a stronger guarantee
(it proves the `SMOKE_TESTS` list matches the documented manifest)
than the existence-check provides (which only proves listed files
exist, not that the list itself is complete).
