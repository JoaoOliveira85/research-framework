# Phase 1 Data Model — Spec 025 Code Simplification Pass

**Date**: 2026-05-21
**Spec**: `specs/_archive/025-simplify-pass/spec.md`
**Research**: `specs/_archive/025-simplify-pass/research.md` (D1–D9 + O1–O4)

Spec 025 is a **refactor**, not a new-feature spec. The "data
model" here is therefore the **API surfaces** affected, organised
into two categories:

- **§ 1 — Preserved public API surfaces** (FR-015): contracts that
  MUST remain byte-identical / signature-stable before and after
  the refactor. These are the regression-detection points.
- **§ 2 — New internal API surfaces**: types and functions
  introduced by the refactor. These are the design targets that
  future code (spec 022 metric hooks, spec 020 modules, etc.) will
  consume.

Plus § 3, the data flow diagram showing how the new internal APIs
fit together, and § 4, validation rules that must hold across the
refactor (the "behaviour preserved" invariants).

---

## § 1 — Preserved public API surfaces (MUST NOT change)

### 1.1 — `research_framework.cli.build_parser`

```python
def build_parser() -> argparse.ArgumentParser:
    """Build and return the top-level CLI argument parser.

    Public — imported by external scripts (install.sh, CI, tests).
    Spec 025 B5 moves the implementation into the new cli/
    subpackage but the import path `research_framework.cli.build_parser`
    is preserved as a re-export.
    """
```

**Stability invariants** (SC-009):
- `./vault --help` output is **byte-identical** pre-/post-refactor.
  Enforced by golden-file test
  `tests/cli/test_build_parser_stable.py`.
- The function returns the same `ArgumentParser` instance topology
  (same subparsers, same arguments, same help text strings).
- Import path `from research_framework.cli import build_parser`
  resolves unchanged.

**Migration**: B5 moves the body into `cli/__init__.py`; the old
`cli.py` shrinks to a 1-line re-export
(`from research_framework.cli import build_parser`).

---

### 1.2 — `research_framework.pipeline.cycle_runner.run_cycle_steps`

```python
def run_cycle_steps(
    vault_dir: Path,
    cycle_num: int,
    *,
    settings: VaultSettings | None = None,  # B7 may add this typed param
    resume: bool = False,
    dry_run: bool = False,
    # ... other existing kwargs ...
) -> CycleResult:
    """Run one full cycle (scout → research → postprocess).

    Public — called by cli/research.py and external tests.
    """
```

**Stability invariants** (FR-009, FR-015):
- The function's externally-observable behaviour is unchanged.
  Specifically: for any input, the function writes the same
  files to the same paths in the same order, produces the same
  exit code, and returns a `CycleResult` with the same shape.
- The existing tests in `tests/pipeline/test_cycle_runner.py`
  pass **unchanged** after the refactor (the most rigorous
  behaviour-preservation proof available pre-022-v1).
- The `_pipeline/cycles/cycle-NNN-quality-report.json` is written
  exactly once per invocation (FR-006).

**Migration**:
- B3 extracts the body into three step modules; `run_cycle_steps`
  becomes a thin orchestrator.
- A6 wraps the orchestrator body in
  `_quality_report_guard(...) as report_state`.
- The signature MAY gain a `settings: VaultSettings | None`
  kwarg (B7) — this is additive (default `None` triggers
  load-from-disk behaviour), so existing callers continue to
  work.

---

### 1.3 — `_pipeline/cycles/cycle-NNN-quality-report.json` schema

```json
{
  "cycle_num": 7,
  "started_at": "2026-05-21T17:00:00Z",
  "completed_at": "2026-05-21T17:14:32Z",
  "exit_status": "success" | "failure" | "interrupted",
  "scout": { "topics_found": [...], "sg_trips": [...], ... },
  "research": { "notes_written": [...], "rejections": [...], ... },
  "postprocess": { "wikilink_fixes": [...], ... },
  "agent_calls": [
    {
      "stage": "scout" | "note_writer" | "verifier" | "plan_narrator" | "probe_retrieval" | ...,
      "agent": "claude" | "codex",
      "tier": "basic" | "standard" | "expert",
      "cost_usd": 0.42,
      "tokens_in": 8234,
      "tokens_out": 1856,
      "latency_ms": 4127
    }
  ],
  // ... other existing fields ...
}
```

**Stability invariants**:
- Top-level field set unchanged. No removed or renamed keys.
- `agent_calls[].stage` is now permitted to include
  `"plan_narrator"` and `"probe_retrieval"` (NEW values, additive
  to the existing enumeration). Downstream consumers MUST treat
  the stage field as a free-form string for forward-compat
  (existing spec 022 metric calculators already do).
- `exit_status` adds no new values for this spec; A6's
  context-manager guard maps `KeyboardInterrupt` to
  `"interrupted"` (a value that already exists for "user-aborted"
  scenarios).

**Migration**: A1/A2 produce the two new stage values in
`agent_calls[]`. The `exit_status` mapping for interrupts is
formalised by A6 (was inconsistent across the 32 scattered call
sites pre-refactor).

---

### 1.4 — `settings.yaml` schema

**Stability invariants**:
- All existing keys preserved unchanged.
- B7 introduces typed access via `VaultSettings`, but the YAML
  file format is unchanged.
- A1 adds an optional key `stages.plan_narrator.tier` (default
  `"standard"` if missing — see spec.md Edge Case). A2 adds
  `stages.probe_retrieval.tier` (same default). Existing vaults
  with neither key continue to work unchanged.

**Migration**: Document the two new optional keys in
`docs/architecture.md` (or wherever settings.yaml is documented)
as part of A1/A2.

---

## § 2 — New internal API surfaces

### 2.1 — `pipeline.steps` package (US6 B3)

#### 2.1.1 — `CycleContext` dataclass

```python
@dataclass(frozen=True)
class CycleContext:
    """Read-only context object passed to every cycle step.

    Holds paths, settings, and stage handles that the step needs
    but should not mutate. Implementations of run_scout /
    run_research / run_postprocess take this as their first
    argument.
    """

    vault_dir: Path
    cycle_num: int
    cycle_dir: Path                # _pipeline/cycles/cycle-NNN/
    settings: VaultSettings        # B7-loaded settings
    dry_run: bool
    # Stage handles for downstream calls (already-resolved):
    agent_dispatch: AgentDispatchFn  # scripts/agent_call.dispatch
    # ... other context items as discovered during implementation ...
```

**Lives at**: `pipeline/steps/_types.py` (per D4 O2; final
location decided at task-generation time based on import-cycle
analysis).

**Validation rules**:
- `vault_dir.exists()` MUST be true.
- `cycle_num >= 1`.
- `cycle_dir` MUST be `vault_dir / "_pipeline" / "cycles" /
  f"cycle-{cycle_num:03d}"` (constructible from `vault_dir +
  cycle_num`; carried explicitly for ergonomics).
- `settings` is loaded ONCE per cycle in `run_cycle_steps` and
  passed down; steps MUST NOT reload.

#### 2.1.2 — Step result dataclasses

```python
@dataclass(frozen=True)
class ScoutResult:
    topics_found: list[Topic]
    sg_trips: list[SafetyGateTrip]
    duration_ms: int
    cost_usd: float

@dataclass(frozen=True)
class ResearchResult:
    notes_written: list[NotePath]
    rejections: list[VerifierRejection]
    duration_ms: int
    cost_usd: float
    # ... fields aligned with existing cycle-NNN-research.json ...

@dataclass(frozen=True)
class PostprocessResult:
    wikilink_fixes: list[WikilinkFix]
    coverage_update: CoverageDelta
    duration_ms: int
```

**Lives at**: `pipeline/steps/_types.py`.

**Validation rules**:
- All fields are typed; no `dict[str, Any]` catchalls.
- `duration_ms >= 0`.
- `cost_usd >= 0.0`.
- Field shapes derive from the existing
  `_pipeline/cycles/cycle-NNN-{scout,research,postprocess}.json`
  schemas (B3 is a structural extraction; field semantics are
  inherited unchanged).

#### 2.1.3 — Step function signatures

```python
# pipeline/steps/scout.py
def run_scout(ctx: CycleContext) -> ScoutResult: ...

# pipeline/steps/research.py
def run_research(
    ctx: CycleContext,
    scout_result: ScoutResult,
) -> ResearchResult: ...

# pipeline/steps/postprocess.py
def run_postprocess(
    ctx: CycleContext,
    research_result: ResearchResult,
) -> PostprocessResult: ...
```

**Validation rules**:
- Each step writes its tier of the cycle JSON
  (`cycle-NNN-scout.json`, etc.) as a side-effect of producing
  its result. The result dataclass is the in-memory equivalent
  of the JSON.
- Steps MUST NOT call `_write_cycle_quality_report` directly —
  the quality report is owned by the context manager guard (A6).
- Steps MAY call `ctx.agent_dispatch(stage=..., ...)` to invoke
  LLM stages; the dispatcher handles cost-sidecar JSON writes.

---

### 2.2 — `pipeline.cycle_runner._quality_report_guard` (US3 A6)

```python
from contextlib import contextmanager

@contextmanager
def _quality_report_guard(
    cycle_dir: Path,
) -> Generator[QualityReportState, None, None]:
    """Guarantee cycle-NNN-quality-report.json is written exactly
    once per cycle exit (success / failure / exception / interrupt).
    """
    state = QualityReportState(cycle_dir=cycle_dir)
    try:
        yield state
        state.exit_status = state.exit_status or "success"
    except KeyboardInterrupt:
        state.exit_status = "interrupted"
        raise
    except Exception as exc:
        state.exit_status = "failure"
        state.exception = repr(exc)
        raise
    finally:
        _write_cycle_quality_report(state)

@dataclass
class QualityReportState:
    cycle_dir: Path
    scout: ScoutResult | None = None
    research: ResearchResult | None = None
    postprocess: PostprocessResult | None = None
    exit_status: str | None = None
    exception: str | None = None
    # ... other fields the report needs ...
```

**Lives at**: `pipeline/cycle_runner.py` (helper local to the
module; not re-exported).

**Validation rules** (FR-006, FR-007):
- `_write_cycle_quality_report` is called **exactly once** per
  `_quality_report_guard` instance lifetime. Enforced
  structurally by the `try/finally` shape.
- `exit_status` is non-None when `_write_cycle_quality_report` is
  called; the context manager's `__exit__` paths cover all four
  values (`"success"`, `"failure"`, `"interrupted"`, plus a
  reserved-future value).
- The guard's `__exit__` is the **ONLY** non-test call site of
  `_write_cycle_quality_report` (FR-007 "at most 2 sites" allows
  one progress-log site, but the default plan is zero — see
  research.md O3).
- The guard MUST NOT raise during the `finally` block; if
  `_write_cycle_quality_report` itself raises, the error is
  logged and swallowed (the original exception, if any,
  propagates per Python's exception-chaining rules).

---

### 2.3 — `vault.frontmatter` module (US7 B4)

```python
def parse_frontmatter(path: Path) -> tuple[dict[str, Any], str]: ...
def parse_frontmatter_str(content: str) -> tuple[dict[str, Any], str]: ...
def dump_frontmatter(frontmatter: dict[str, Any], body: str) -> str: ...

class FrontmatterParseError(Exception):
    """Raised when a markdown file's YAML frontmatter is malformed."""
    path: Path | None
    line_no: int | None
```

**Lives at**: `vault/frontmatter.py` (per D5 + O1).

**Validation rules** (FR-010, SC-007):
- ≥ 8 of the ≥ 12 existing call sites import from
  `vault.frontmatter` after migration.
- Holdout sites carry an inline comment explaining the constraint
  (e.g. `# Holdout: this site preserves malformed YAML to detect
  schema drift; cannot use canonical parser.`).
- Edge cases covered by tests (see plan.md Testing section).
- Parser is **pure** (no side effects, no I/O outside the
  explicit path-read in `parse_frontmatter`). `parse_frontmatter_str`
  has zero I/O.
- Symmetric: `dump_frontmatter(*parse_frontmatter_str(s)) == s`
  for any well-formed input `s` (modulo whitespace normalisation;
  exact contract pinned in `contracts/frontmatter-parser.contract.md`).

---

### 2.4 — `pipeline.settings` module (US9 B7)

```python
@dataclass(frozen=True)
class VaultSettings:
    """Typed access to settings.yaml.

    Fields are typed per the schema documented in
    docs/architecture.md. Unknown YAML keys land in `extras` for
    forward-compat.
    """

    # Pipeline section
    max_cycles: int
    budget_usd: float
    backlog_promotion_threshold: int
    # Stages section
    stages: dict[str, StageSettings]  # stage_name -> {tier, ...}
    # Dimensions section
    dimensions: list[str]
    # ... other typed fields enumerated at impl time ...
    # Forward-compat
    extras: dict[str, Any]

@dataclass(frozen=True)
class StageSettings:
    tier: Literal["basic", "standard", "expert"]
    # ... other per-stage knobs ...

class SettingsError(Exception): ...

def load_vault_settings(vault_dir: Path) -> VaultSettings: ...
```

**Lives at**: `pipeline/settings.py`.

**Validation rules** (FR-012, SC-008):
- ≥ 6 of the existing call sites migrate to
  `load_vault_settings`.
- Required keys (`max_cycles`, `budget_usd`) raise `SettingsError`
  with a clear path-and-key message if missing.
- Optional keys with documented defaults (e.g.
  `backlog_promotion_threshold` = 2, `stages.plan_narrator.tier`
  = "standard") fall back gracefully.
- The settings dataclass is `frozen=True` — downstream code MUST
  treat it as immutable. Mutation requires reloading from disk.

---

### 2.5 — `cli/` subpackage (US8 B5)

See `contracts/cli-subpackage.contract.md` for the full pinned
contract. Summary:

```python
# cli/__init__.py
def build_parser() -> argparse.ArgumentParser: ...   # re-exported

# cli/<group>.py (research.py, audit.py, vault.py, quality.py)
def register(subparsers: argparse._SubParsersAction) -> None: ...
def handle(args: argparse.Namespace) -> int: ...     # returns exit code
```

**Lives at**: `cli/` package replacing the old `cli.py` monolith.

**Validation rules** (FR-011, SC-005, SC-009):
- `cli/__init__.py` re-exports `build_parser` unchanged.
- `cli/__init__.py` ≤ 50 lines (the aggregator).
- Each `cli/<group>.py` ≤ 250 lines.
- Old `cli.py` becomes a 1-line re-export
  (`from research_framework.cli import build_parser`).
- Combined LOC across all `cli/*.py` files ≤ pre-refactor
  `cli.py` LOC + 10% (acceptable overhead for module headers /
  imports).
- Golden-file `--help` test passes byte-identical pre-/post-.

---

### 2.6 — `scripts/agent_call.py` stage tag extensions (US1 A1, US2 A2)

**No new code in `agent_call.py`**. The change is purely
additive at the consumer side: two new permitted values in the
`stage` parameter's enumeration.

If `agent_call.py` currently has a stage allowlist (e.g.
`VALID_STAGES = {"scout", "note_writer", ...}`), extend it:
`VALID_STAGES = {"scout", "note_writer", ..., "plan_narrator",
"probe_retrieval"}`.

If the dispatcher is fully free-form on `stage` (no allowlist),
no `agent_call.py` change at all; the new stage strings are
introduced by `pipeline/plan_narrator.py` and
`pipeline/cycle_runner.py` directly.

**Validation rules** (FR-001, FR-002, FR-003):
- A cost-sidecar JSON file is written under
  `_pipeline/cycles/cycle-NNN/agent-calls/<stage>.json` for every
  routed call. (`<stage>` may include numeric suffix for
  collision avoidance if a stage runs multiple times per cycle.)
- The sidecar's `stage` field matches the new value
  (`"plan_narrator"` or `"probe_retrieval"`).
- `cost_usd > 0.0` for any actually-executed LLM call (i.e. not
  a fake_agent stub). Stub calls write `cost_usd: 0.0`.

---

## § 3 — Data flow (post-refactor)

```text
                            ./vault research (cli/research.py)
                                       │
                                       ▼
                          run_cycle_steps(...)            (pipeline/cycle_runner.py)
                                       │
                          ┌────────────┴────────────┐
                          │                         │
                          ▼                         ▼
                  _quality_report_guard          CycleContext(...)
                  yields report_state           (loaded settings + paths
                                                 + agent_dispatch handle)
                                       │
                                       ▼
                               run_scout(ctx)             (pipeline/steps/scout.py)
                                       │
                                       │ may call ctx.agent_dispatch(
                                       │   stage="scout", ...)
                                       │ which routes through
                                       │ scripts/agent_call.py
                                       │ → writes
                                       │ _pipeline/cycles/cycle-NNN/
                                       │   agent-calls/scout.json
                                       ▼
                              ScoutResult ────► report_state.scout
                                       │
                                       ▼
                               run_research(ctx, scout_result)   (pipeline/steps/research.py)
                                       │
                                       │ may call ctx.agent_dispatch(
                                       │   stage="note_writer", ...)
                                       │   stage="verifier", ...)
                                       │   stage="plan_narrator", ...)  # NEW per A1
                                       │   stage="probe_retrieval", ...)  # NEW per A2
                                       ▼
                              ResearchResult ─► report_state.research
                                       │
                                       ▼
                               run_postprocess(ctx, research_result)  (pipeline/steps/postprocess.py)
                                       │
                                       ▼
                              PostprocessResult ─► report_state.postprocess
                                       │
                                       ▼
                          (context manager exits normally)
                                       │
                                       ▼
                          _write_cycle_quality_report(state)
                          writes _pipeline/cycles/
                            cycle-NNN-quality-report.json
                          (exactly once, regardless of exit path)
```

On exception or interrupt, the same final write happens (via
`finally:` in the context manager), with `exit_status` reflecting
the path: `"failure"` for exceptions, `"interrupted"` for
KeyboardInterrupt.

---

## § 4 — Behaviour-preservation invariants (validated across the refactor)

These are the "regression-detection" assertions. Any 025 PR
breaking one of these is wrong by construction; the test sweep
catches the violation.

| Invariant | Enforcer | Failure mode |
|-----------|----------|--------------|
| `./vault --help` byte-identical pre/post B5 | `tests/cli/test_build_parser_stable.py` (golden file) | Test fails on diff. |
| `run_cycle_steps` signature unchanged | mypy + `tests/pipeline/test_cycle_runner.py` (preserved tests) | Tests fail on shape change. |
| `_write_cycle_quality_report` called exactly once per cycle exit | `tests/pipeline/test_cycle_runner_quality_report.py` (parametrised exit paths) | Test fails if the count is 0 or > 1. |
| `cost_usd > 0` in narrator/probe sidecar (when LLM actually invoked) | `tests/pipeline/test_plan_narrator.py`, `tests/pipeline/test_cycle_runner_probe.py` | Test fails if 0.0 returned when subprocess actually ran. |
| LLM dispatch guard allowlist contains zero entries | `tests/_helpers/test_llm_dispatch_allowlist.py` (spec 024 US1) | Test fails on non-zero count. |
| Pre-refactor `tests/pipeline/test_cycle_runner.py` tests pass unchanged | The test sweep itself (`pytest`) | Test fails on behaviour drift. |
| `settings.yaml` schema additive only (no removed/renamed keys) | Manual review + `tests/pipeline/test_settings_loader.py` edge cases | New keys without defaults break existing vaults. |
| Tier B PRs pass `./build.sh --quality` post-022-v1 | CI workflow `.github/workflows/quality.yml` | PR cannot merge per FR-016. |

The combination of these invariants is the spec's
behaviour-preservation contract. As long as they hold, the
refactor has been faithful.
