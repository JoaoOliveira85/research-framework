# ADR-0008: Testing pyramid restructure — integration vocabulary, tier-4 split, regression discipline

**Status**: Accepted
**Date**: 2026-05-21
**Tags**: testing, vocabulary, regression-discipline, spec-018, spec-022-prep
**Supersedes (in part)**: Feature 018's pyramid naming and tier-4 scope. ADR-0007 remains in force; the mandatory smoke gate is unchanged.

## Context

Feature 018 (shipped 0.2.23, 2026-05-17) introduced a six-tier testing pyramid
to stop the 0.2.20 → 0.2.22 seam-bug release chain. The pyramid worked: the
gate stabilised the release line and the project has 1158+ tests across all
six tiers.

Two limitations of the original design have surfaced in the months since:

1. **Vocabulary mismatch with the wider Python community**. Feature 018
   chose project-specific tier names ("Seam", "Single-cycle e2e",
   "Multi-cycle e2e") that are precise but discoverable only to people
   who have read `docs/testing-strategy.md`. New contributors (and AI
   agents) reach for the conventional term "integration testing" and
   find nothing — the project-specific name `seam` does not surface in
   any search. This was a documented gap in the architect review of the
   2026-05-21 testing-strategy refresh (Option L / B / H question).

2. **Tier-4 is over-broad**. The original "Single-cycle e2e" tier covers
   everything from "run `cycle_runner.py` with real settings and the
   fake agent" (one component + its dependencies) to "exercise the full
   `run_cycle_steps` pipeline against a realistic fixture vault" (true
   end-to-end). These are different test classes with different cost,
   different failure-mode coverage, and different smoke-gate inclusion
   logic. Conflating them at one tier hides the gap that "component
   integration without the full cycle" is a real thing the project
   already does (`test_cycle_runner.py`, `test_orchestrator.py`,
   `test_plan_narrator.py`) but cannot point at by name.

A third gap — separate from the pyramid itself but related in scope — is
that the project has no explicit **regression-test discipline**. Today
every shipped bug-fix in `CHANGELOG.md` *should* link a test that
prevents recurrence, but no doc says so and no test enforces it. Tests
like `test_anti_fraud_correction.py`, `test_batch_resume.py`, and
`test_cycle_runner_directive_injection.py` are *de facto* regression
tests but the linkage from `CHANGELOG.md` entry to test exists only in
the author's head.

The 2026-05-21 architect review proposed three options for the
testing-strategy refresh; the project owner selected the heaviest
("Option H"), explicitly requesting the rename + tier-4 split + a new
ADR superseding the relevant parts of Feature 018.

## Decision

### Pyramid restructure (6 → 7 tiers)

| Old (Feature 018) | New (ADR-0008) | Scope |
|-------------------|----------------|-------|
| Tier 1 — Unit | Tier 1 — Unit | One pure function, no I/O |
| Tier 2 — Schema / contract | Tier 2 — Schema / contract | One JSON shape, CLI contract, or guard |
| Tier 3 — **Seam** | Tier 3 — **Integration** | Data flow between two modules (A's output → B's input) |
| Tier 4 — Single-cycle e2e | Tier 4 — **Component integration** (NEW) | One pipeline component + its real dependencies (sub-cycle scope; e.g. `test_cycle_runner.py`) |
| — | Tier 5 — **Cycle e2e** | Full `run_cycle_steps` via fake agent (was old tier 4) |
| Tier 5 — Multi-cycle e2e | Tier 6 — Multi-cycle e2e | Real `run_cycles` × N + fake agent |
| Tier 6 — Smoke gate | Tier 7 — Smoke gate | `build.sh` precondition |

The split between new Tier 4 and new Tier 5 is **scope**, not technology:

- **Tier 4 (Component integration)**: invokes one named component
  (`cycle_runner.py`, `orchestrator.py`, `plan_narrator.py`) directly,
  with real settings and real on-disk fixtures, but does not necessarily
  drive `run_cycle_steps` end-to-end. Fake agent if any LLM seam is
  involved. Sub-cycle.
- **Tier 5 (Cycle e2e)**: drives the full single-cycle pipeline through
  `run_cycle_steps` against `tests/_helpers/fake_agent.py` and a
  fixture vault from `vault_factory.build_minimal_vault`.

### Pytest marker rename

The existing `@pytest.mark.integration` marker (defined in
`pyproject.toml` as "real LLM calls (deselect with '-m not integration')")
**conflicts** with Tier 3's new "Integration" label and must be
renamed to free the namespace:

| Old marker | New marker | Meaning |
|------------|------------|---------|
| `@pytest.mark.integration` | **`@pytest.mark.live_llm`** | Test invokes a real `claude` / `codex` CLI; costs money; opt-in only |
| `@pytest.mark.e2e` | `@pytest.mark.e2e` (unchanged) | Tier 5 or Tier 6 — drives the real cycle runner |
| `@pytest.mark.slow` | `@pytest.mark.slow` (unchanged) | Subprocess-heavy (e.g. invokes `build.sh`) |
| — | **`@pytest.mark.regression`** (NEW, voluntary) | Tags any test that exists to prevent a specific shipped bug from recurring |
| — | **`@pytest.mark.acceptance`** (NEW, voluntary) | Tags any test that proves a specific `specs/NNN-*/spec.md` acceptance scenario |

`regression` and `acceptance` are voluntary cross-cutting tags — they
sit ALONGSIDE the tier classification, not instead of it. A test can be
Tier 3 AND `@pytest.mark.regression`. The voluntary tags exist so
contributors can run focused slices (`pytest -m regression` to verify
no shipped bugs have regressed; `pytest -m "acceptance and not e2e"` to
sanity-check spec coverage before a release).

### Regression discipline

Every entry under `CHANGELOG.md` 's `### Fixed` (or equivalent
bug-class) block in any released version MUST link at least one test
that prevents recurrence. Acceptable forms:

- A test reference: `(test: tests/pipeline/test_full_cycle_e2e.py::test_asymmetric_tail_batch_serializes)`
- A `(regression test: ...)` tag with same shape
- `(no test: <one-sentence rationale>)` — escape hatch for fixes where a
  test is genuinely infeasible (e.g. a documentation-only correction).
  The rationale is reviewed in the PR.

A Phase 2 lint guard (`tests/spec/test_changelog_regression_links.py`,
tier 2) scans `CHANGELOG.md` released-version blocks for `Fixed`
entries and asserts each has either a test reference or a `(no test:
...)` rationale. Pre-ADR-0008 entries are grandfathered via an explicit
allowlist that monotonically shrinks (same discipline as the LLM
dispatch guard allowlist in `llm-dispatch-guard.contract.md`).

### Relationship to ADR-0007 (mandatory smoke gate)

ADR-0007's substance is unchanged: the gate stays mandatory, with no
skip flag. ADR-0007's language about "tier 4+5" tests refers to what
this ADR re-numbers as **tier 5 + 6** (full single-cycle e2e + multi-
cycle e2e). The `build.sh` smoke gate selects tests by **file path**,
not tier number, so the gate's actual contents are unaffected by the
rename. Future ADRs should cite tier numbers in the ADR-0008 scheme.

### What is NOT changing

- The mandatory smoke gate (ADR-0007).
- The fake-agent contract or its v2 stage matrix.
- The LLM dispatch guard contract / allowlist.
- The Phase 2 / Phase 3 / Phase 4 sequencing in
  `docs/testing-strategy.md` § Where this fits in the roadmap.
- The spec acceptance coverage convention added 2026-05-21 (the
  `## Acceptance coverage` table convention for `specs/NNN-*/spec.md`).
  ADR-0008 adds a *cross-cutting* `@pytest.mark.acceptance` tag that
  complements that convention; it does not replace it.

## Consequences

**Good**:

- "Integration testing" surfaces in code search / agent queries —
  closes a known agent-discoverability failure mode.
- The tier-4 split makes "I want to test cycle_runner with its real
  dependencies but without the full pipeline" a first-class concept
  with a named home.
- Regression discipline catches the failure mode where a bug fix
  ships with no test and the same bug returns six weeks later (the
  0.2.20 → 0.2.31 chain ADR-0001 documents).
- Voluntary `regression` and `acceptance` markers let contributors
  slice the suite by purpose, not just by scope.

**Trade-offs**:

- Documentation churn — `tests/README.md`, `docs/testing-strategy.md`,
  `specs/018-testing-strategy/spec.md`, and any future-spec tier
  references all need updating. One-time cost paid in this commit.
- Marker rename touches two callsites (`pyproject.toml`,
  `tests/processors/test_extract.py`). Trivial.
- Re-numbering tier-4/5 to tier-5/6 ripples through external mental
  models. ADR-0007's "tier 4+5" language stays in the ADR (immutable);
  the ADR's tag block above is the bridge.
- CHANGELOG regression discipline applies retroactively only via an
  allowlist; not all past `Fixed` entries have linked tests. The
  allowlist must shrink over time.

## Alternatives considered

- **Option L (Light): rename only, keep marker collision documented**.
  Rejected: the marker collision (`@pytest.mark.integration` =
  real LLM call vs Tier 3 = "Integration") is a confusion landmine.
  Renaming the marker is a 3-line fix; living with the collision is
  permanent friction.
- **Option M (Medium): regression discipline only, no pyramid rename**.
  Rejected: the discovery problem (agents can't find "integration"
  in the docs) is real today, not hypothetical. M addresses one gap;
  H addresses both.
- **Keep six tiers; add cross-cutting markers only**. Rejected: the
  tier-4 over-breadth is a real coverage gap — tests like
  `test_cycle_runner.py` are mis-tiered today (they're not full
  single-cycle e2e but they're not seam either).
- **Use a different tier-3 name like "Module integration"**. Rejected
  in favour of the cleaner conventional term "Integration" once the
  marker collision is resolved.
- **Defer to spec-022 design**. Rejected: 022 is about output quality
  measurement, not test taxonomy. Bundling the pyramid restructure
  into 022 would dilute both efforts and slow 022's critical path.

## Tests

- `tests/spec/test_changelog_regression_links.py` (Phase 2 deliverable,
  tier 2). Scans `CHANGELOG.md` for `Fixed`-block entries and asserts
  test linkage or `(no test: ...)` rationale; allowlist for
  pre-ADR-0008 entries.
- Existing tests are unaffected by the rename. The marker rename
  (`integration` → `live_llm`) is enforced by `pyproject.toml`
  strict-markers + the renamed usage in
  `tests/processors/test_extract.py`.
- No new test runtime cost; the rename is structural / documentary.

## Migration

- Existing tests do NOT need to be re-tiered immediately. The
  decision tree in `docs/testing-strategy.md` is updated; any test
  *touched* after this ADR ships should be re-classified per the new
  pyramid if its current tier is wrong.
- The `@pytest.mark.integration` → `@pytest.mark.live_llm` rename
  lands in the same commit as this ADR. Strict-markers config
  prevents the old name from being silently re-introduced.
- Phase 2 (`refactor/testing-strategy-phase2`) is the natural home for
  the CHANGELOG regression-link lint guard.
