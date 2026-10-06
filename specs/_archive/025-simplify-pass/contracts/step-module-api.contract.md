# Contract: `pipeline/steps/` Step Module API (B3)

**Owner**: Spec 025 US6 B3.
**Status**: pinned at spec 025 plan time (2026-05-21).

This contract pins the public API of the three new step modules
introduced by B3. Future work — particularly spec 022 v2's metric
hooks and spec 020's source-module integration — depends on these
signatures being stable.

---

## § 1 — Package layout

```text
src/research_framework/pipeline/steps/
├── __init__.py         # re-exports the three run_* functions + types
├── _types.py           # CycleContext, ScoutResult, ResearchResult, PostprocessResult
├── scout.py            # run_scout
├── research.py         # run_research
└── postprocess.py      # run_postprocess
```

`pipeline/steps/__init__.py` exports:

```python
from .scout import run_scout
from .research import run_research
from .postprocess import run_postprocess
from ._types import (
    CycleContext,
    ScoutResult,
    ResearchResult,
    PostprocessResult,
)

__all__ = [
    "run_scout",
    "run_research",
    "run_postprocess",
    "CycleContext",
    "ScoutResult",
    "ResearchResult",
    "PostprocessResult",
]
```

External callers (including spec 022 metric hooks) MUST import
from `research_framework.pipeline.steps` (or
`research_framework.pipeline.steps.<module>`), NOT from internal
underscored modules (`_types`).

---

## § 2 — `CycleContext`

```python
@dataclass(frozen=True)
class CycleContext:
    vault_dir: Path
    cycle_num: int
    cycle_dir: Path
    settings: VaultSettings
    dry_run: bool
    agent_dispatch: AgentDispatchFn
    # NOTE: additional fields MAY be added but MUST be optional
    # (default values) to preserve construction backwards-compat.
```

**`AgentDispatchFn` type alias**:

```python
AgentDispatchFn = Callable[..., AgentCallResult]
# Equivalent to scripts/agent_call.dispatch's signature.
```

**Construction**: `CycleContext` is constructed once per cycle in
`pipeline/cycle_runner.py::run_cycle_steps`. Steps MUST NOT
construct their own `CycleContext`; they receive it as their
first arg.

**Immutability**: `frozen=True`. Any "state" a step needs to
mutate (e.g. accumulating cost, tracking topic count) lives in
the step's *result* object, NOT in `CycleContext`.

---

## § 3 — Step function signatures

### 3.1 — `run_scout`

```python
def run_scout(ctx: CycleContext) -> ScoutResult:
    """Execute the BFS scouting pass for one cycle.

    Side effects:
        - Calls ctx.agent_dispatch(stage="scout", ...) one or more
          times.
        - Writes _pipeline/cycles/cycle-NNN-scout.json on success.
        - Writes _pipeline/research-backlog.md if any backlog
          items are produced.

    Returns:
        ScoutResult with topics_found, sg_trips, duration_ms,
        cost_usd.

    Raises:
        ScoutError: on scout-specific failures (e.g. SG-002
            diversity gate trip with no recoverable path).
        Any unhandled exception propagates to run_cycle_steps,
        whose _quality_report_guard maps it to exit_status="failure"
        and writes the quality report.
    """
```

### 3.2 — `run_research`

```python
def run_research(
    ctx: CycleContext,
    scout_result: ScoutResult,
) -> ResearchResult:
    """Execute the DFS research pass for one cycle.

    Inputs:
        scout_result.topics_found drives the per-topic note-writer
        invocations.

    Side effects:
        - Calls ctx.agent_dispatch(stage="note_writer", ...) once
          per topic batch.
        - Calls ctx.agent_dispatch(stage="verifier", ...) once
          per note batch.
        - MAY call ctx.agent_dispatch(stage="plan_narrator", ...)
          (the rewired A1 call).
        - MAY call ctx.agent_dispatch(stage="probe_retrieval",
          ...) (the rewired A2 call).
        - Writes data_vault/<category>/<note>.md files.
        - Writes _pipeline/cycles/cycle-NNN-research.json.

    Returns:
        ResearchResult.

    Raises:
        ResearchError on research-specific failures.
        Other exceptions propagate.
    """
```

### 3.3 — `run_postprocess`

```python
def run_postprocess(
    ctx: CycleContext,
    research_result: ResearchResult,
) -> PostprocessResult:
    """Execute the postprocess pass (wikilink fixes, coverage update).

    Side effects:
        - Mutates data_vault/<category>/*.md files (wikilink case
          normalisation per ADR-0005).
        - Updates coverage-targets.json.
        - Updates _pipeline/research-backlog.md.
        - Writes _pipeline/cycles/cycle-NNN-postprocess.json.

    Returns:
        PostprocessResult.

    Raises:
        PostprocessError on postprocess-specific failures.
        Other exceptions propagate.
    """
```

---

## § 4 — Result dataclasses

All result types are `@dataclass(frozen=True)`. Field shapes
derive from the existing `cycle-NNN-{scout,research,postprocess}.json`
file schemas — the result object is the in-memory equivalent.

```python
@dataclass(frozen=True)
class ScoutResult:
    topics_found: list[ScoutedTopic]
    sg_trips: list[SafetyGateTrip]
    duration_ms: int
    cost_usd: float
    raw_json_path: Path     # location of the persisted scout JSON

@dataclass(frozen=True)
class ResearchResult:
    notes_written: list[Path]            # absolute paths in data_vault/
    notes_rejected: list[VerifierRejection]
    duration_ms: int
    cost_usd: float
    raw_json_path: Path

@dataclass(frozen=True)
class PostprocessResult:
    wikilink_fixes: list[WikilinkFix]    # ADR-0005 normalisations applied
    coverage_delta: CoverageDelta
    duration_ms: int
    raw_json_path: Path
```

Auxiliary types (`ScoutedTopic`, `SafetyGateTrip`,
`VerifierRejection`, `WikilinkFix`, `CoverageDelta`) are defined
in `pipeline/steps/_types.py` and are also `@dataclass(frozen=True)`.
Their exact fields are pinned at task-generation time
(`/speckit.tasks`) and aligned with the pre-refactor JSON
schemas.

---

## § 5 — Behaviour preservation

For any input `(vault_dir, cycle_num, ...)` to `run_cycle_steps`:

1. The set of files written under `data_vault/` is **identical**
   pre- and post-B3 (modulo whitespace normalisation in
   wikilink-fix output, which is unchanged because ADR-0005 logic
   moves intact into `postprocess.py`).
2. The cycle JSON files (`cycle-NNN-scout.json`,
   `cycle-NNN-research.json`, `cycle-NNN-postprocess.json`,
   `cycle-NNN-quality-report.json`) have identical content.
3. Agent-calls sidecar files have identical content (modulo
   timestamps when running with the real LLM; identical when
   running with fake_agent in the determinism mode).
4. The function's return value (`CycleResult`) has the same shape
   and field values.
5. The function's exit code is identical for any given input.
6. The existing tests in `tests/pipeline/test_cycle_runner.py`
   pass **unchanged** (no test modifications permitted for B3).

This is the **structural** behaviour-preservation contract for
B3. Pre-022-v1, it's enforced only by the test sweep + smoke
gate. Post-022-v1, the harness's metric-level regression
detection is the additional gate (Tier B PRs cannot merge per
FR-016 + SC-014).

---

## § 6 — Coordination with spec 020 (Source-Module Architecture)

Spec 020 introduces per-vault source modules (`<vault>/modules/
<name>/`) that the cycle calls into. Spec 020 was designed
**before** spec 025 was conceived, so its plan assumes the
pre-B3 cycle_runner shape.

**Forward-compat guarantee from spec 025**: the new step modules
expose stable extension points where 020 modules can attach:

- `run_scout` may call `ctx.agent_dispatch(stage="<module>",
  ...)` for source-module-specific scouting (one stage per
  module).
- `run_research` may call into module-specific extractors for
  note hydration.
- Sidecar JSON `stage` values are free-form strings, so 020
  module stages are permitted post-025.

Spec 020's implementation plan can target either the pre-B3 or
post-B3 cycle_runner; the call sites are stable across both
(only the internal monolithic vs. step-module organisation
differs).
