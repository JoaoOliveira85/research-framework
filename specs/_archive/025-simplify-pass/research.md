# Phase 0 Research — Spec 025 Code Simplification Pass

**Date**: 2026-05-21 (post-`/speckit.clarify`)
**Spec**: `specs/_archive/025-simplify-pass/spec.md`
**Audience**: Implementer of spec 025 (this session or a follow-on);
the `/speckit.tasks` invocation will reference these decisions.

This document captures the technical design decisions for HOW to
execute the refactor, distinct from spec.md's "what + why". Each
decision has a rationale + alternatives considered + status.

---

## D1 — A1/A2: how to migrate LLM dispatch to `scripts/agent_call.py`

**Decision**: Add two new stage names to `scripts/agent_call.py`'s
existing stage dispatch enumeration — `plan_narrator` and
`probe_retrieval` — and rewrite `pipeline/plan_narrator.py` +
the probe-retrieval block in `pipeline/cycle_runner.py` to call
through. No schema change to the cost-sidecar JSON output.

**Rationale**:
- `scripts/agent_call.py` already supports an extensible stage-tag
  mechanism (it's how `scout`, `note_writer`, `verifier`, etc.
  already work). Adding two more stage tags is the lightest-weight
  integration possible.
- The existing cost-sidecar JSON schema (`{stage, agent, tier,
  cost_usd, tokens_in, tokens_out, latency_ms}`) already supports
  any stage name as a free-form string. No schema bump needed.
- Cost-capture and fake_agent stubbability flow through automatically
  — both are properties of `agent_call.py`, not of individual
  stages.

**Alternatives considered**:
- *Alt 1 — write new dispatchers per stage*: rejected. Duplicates
  agent_call.py logic; defeats the purpose of having a single
  dispatcher (Principle IV).
- *Alt 2 — refactor agent_call.py to a plugin architecture*:
  rejected. Spec 025 is behaviour-preserving; agent_call.py's
  current shape is already adequate. A future spec can do this.
- *Alt 3 — keep the bypasses but add cost-capture sidecars from
  outside agent_call.py*: rejected. Doesn't satisfy the LLM
  dispatch guard from spec 024 (the guard explicitly looks for
  direct `subprocess.run([claude|codex, ...])` calls, regardless
  of cost-capture).

**Status**: locked.

**Implementation pointer**: `scripts/agent_call.py::STAGE_TAGS`
(or equivalent enumeration); add `"plan_narrator"` and
`"probe_retrieval"`. `pipeline/plan_narrator.py::prepend_narrative`
(or wherever the call lives — verify at task-generation time)
rewires from `subprocess.run(["claude", "-p", prompt])` to
`agent_call.dispatch(stage="plan_narrator", prompt=prompt, tier=...)`.
Tier is read from `settings.yaml::stages.plan_narrator.tier`
(default `"standard"` if missing — see edge case in spec.md
Edge Cases). Same pattern for probe-retrieval in `cycle_runner.py`.

---

## D2 — A6: quality-report context-manager design

**Decision**: Implement `pipeline/cycle_runner._quality_report_guard`
as a `contextlib.contextmanager`-decorated function that owns the
"write quality report exactly once on exit" guarantee. `run_cycle_steps`
wraps its existing body in `with _quality_report_guard(...) as
report_state:`, mutating `report_state` throughout the cycle and
relying on the context manager's `__exit__` (including the implicit
`finally`-equivalent semantics of `@contextmanager` generators) to
serialise the final write. Existing call sites of
`_write_cycle_quality_report` collapse to:
- ONE entry/exit pair via the context manager (the wrapper itself).
- AT MOST ONE deliberate mid-cycle "progress log" call (kept only
  if a use case exists; the architect's preference is "ideally
  zero secondary call sites").

**Rationale**:
- `contextlib.contextmanager` is stdlib (Principle V compliant).
- The decorator pattern handles **both** normal-exit (yield returns
  normally) and exception-exit (yield raises) without writing
  explicit try/finally in the consumer — the consumer reads as
  linear code.
- `__exit__` runs even on `KeyboardInterrupt` (CPython propagates
  `BaseException` through `@contextmanager` generators, executing
  the `finally`-equivalent code path) — satisfies spec.md US3
  scenario 2.
- FR-007's "at most 2 call sites" lets us keep one deliberate
  progress-log call site if needed; the default plan is **zero**
  secondary sites, with the slot reserved if a use case surfaces
  during implementation.

**Alternatives considered**:
- *Alt 1 — explicit try/finally*: rejected. More verbose at the
  consumer site (`run_cycle_steps`) than the context manager
  approach; less idiomatic Python.
- *Alt 2 — class-based context manager (`__enter__`/`__exit__`)*:
  rejected. Heavier-weight than `@contextmanager` for a single-use
  case; `@contextmanager` reads more linearly.
- *Alt 3 — decorator on `run_cycle_steps` itself
  (`@write_quality_report_on_exit`)*: rejected. Couples the
  decorator to a specific function shape; less flexible if a
  future caller needs to instantiate the report state explicitly.

**Status**: locked.

**Implementation pointer**: New helper
`pipeline/cycle_runner._quality_report_guard(cycle_dir: Path) ->
ContextManager[QualityReportState]`. The state object is a mutable
dataclass that `run_cycle_steps` updates throughout the cycle.
`__exit__` calls the existing `_write_cycle_quality_report(state)`
function exactly once. Cleanup of the 32 scattered call sites
happens in one PR (it's atomic with the context-manager wiring).

---

## D3 — A4: resume-cycle auto-detect mechanism

**Decision**: Read `_pipeline/state.json::in_progress_cycle` (an
existing field if present; if absent, A4's implementation adds the
write-side hook at cycle start). The resume command's argument
parser treats `--cycle <N>` as overriding auto-detect. Three error
modes:
1. No state file or `in_progress_cycle` field absent + no `--cycle`
   → error: `"no in-progress cycle found; use --cycle <N> to specify"`.
2. Multiple in-progress cycles (theoretically impossible but
   defensively handled) → error: `"multiple in-progress cycles
   found: [N1, N2]; specify with --cycle <N>"`.
3. `state.json` exists but is malformed → error: `"_pipeline/
   state.json is corrupted: <details>; use --cycle <N> to
   specify manually"`. (Edge case from spec.md.)

**Rationale**:
- `_pipeline/state.json` already exists for other purposes
  (verify at task-generation time; if not, A4's implementation
  creates the contract).
- The override semantics (`--cycle` wins) match spec.md US4
  scenario 3.
- Error messages name the corrective action ("use `--cycle <N>`")
  — matches spec.md Edge Cases preference for "fail clear, not
  silent".

**Alternatives considered**:
- *Alt 1 — scan `_pipeline/cycles/cycle-*-research.json` for the
  highest unfinished cycle number*: rejected. State-via-derived
  files is fragile (what if scout ran but research didn't? what
  if research wrote partial output?); explicit state.json is more
  reliable.
- *Alt 2 — lock file (`_pipeline/.cycle-lock`)*: rejected. Adds a
  cleanup burden if a crash leaves the lock file orphaned; users
  would have to `rm` it manually. State.json with a clear
  `in_progress_cycle` value or `null`/absent for "no cycle in
  progress" is the simpler invariant.

**Status**: locked, contingent on confirming `state.json` exists.

**Implementation pointer**: `cli/research.py::handle_resume(args)`
reads `_pipeline/state.json` via the new B7 settings loader (or
a separate `_pipeline/state.py` helper); fails gracefully on the
three error modes above. Tests in `tests/cli/test_research_resume.py`
cover each mode.

---

## D4 — B3: cycle-runner step extraction strategy

**Decision**: Extract three step modules under `pipeline/steps/`:

```python
# pipeline/steps/scout.py
def run_scout(ctx: CycleContext) -> ScoutResult: ...

# pipeline/steps/research.py
def run_research(ctx: CycleContext, scout_result: ScoutResult)
    -> ResearchResult: ...

# pipeline/steps/postprocess.py
def run_postprocess(ctx: CycleContext, research_result: ResearchResult)
    -> PostprocessResult: ...
```

Each step is a **single public function** taking a `CycleContext`
(immutable dataclass with paths, settings, and stage handles)
plus the previous step's result. Returns a typed result dataclass
that the next step consumes. `pipeline/cycle_runner.py`'s
`run_cycle_steps` becomes a thin orchestrator:

```python
def run_cycle_steps(vault_dir, cycle_num, ...) -> CycleResult:
    ctx = CycleContext(...)
    with _quality_report_guard(ctx.cycle_dir) as report_state:
        scout_result = run_scout(ctx)
        report_state.scout = scout_result
        research_result = run_research(ctx, scout_result)
        report_state.research = research_result
        post_result = run_postprocess(ctx, research_result)
        report_state.postprocess = post_result
        return CycleResult.from_steps(scout_result, research_result,
                                       post_result)
```

**Rationale**:
- Three modules match the existing BFS → DFS → Repeat model
  (Phase 2 sub-phases). Constitution architecturally defines this
  as the cycle structure; extracting along these boundaries
  preserves Principle II.
- Functional signatures (no shared mutable state outside
  `CycleContext` and the explicit `report_state`) make each step
  independently testable.
- Spec 022's metric hooks attach at the **step return value**
  boundary — `report_state.scout`, `report_state.research`,
  `report_state.postprocess` are obvious metric-injection points
  for 022 v2 (post-025).

**Alternatives considered**:
- *Alt 1 — extract by file size (split cycle_runner.py at
  arbitrary line boundaries)*: rejected. Doesn't follow the BFS
  → DFS structure; would create awkward "first half / second
  half" modules without semantic meaning.
- *Alt 2 — class-based steps (each step is a class with
  `__call__`)*: rejected. Adds a layer of indirection without
  benefit; functional signatures are simpler.
- *Alt 3 — keep the monolith and just expose internal functions*:
  rejected. Doesn't reduce `cycle_runner.py` to < 1500 lines
  (FR-008); doesn't help 022's metric-hook attachment story.
- *Alt 4 — extract MORE granular steps (e.g.
  `steps/scout/bfs.py`, `steps/scout/validate.py`, ...)*:
  rejected for v1. Future spec could decompose further if needed;
  3 modules is the right granularity for the initial extraction.

**Status**: locked.

**Implementation pointer**: New package
`pipeline/steps/{__init__.py, scout.py, research.py, postprocess.py}`.
The `CycleContext` and `ScoutResult` / `ResearchResult` /
`PostprocessResult` dataclasses live in `pipeline/steps/_types.py`
(or `pipeline/cycle_context.py`). Migration happens in the
long-lived `025-b3-step-extraction` branch per Q3a; ship as one
big PR after `./build.sh --quality` clears (Tier B gate per
FR-016).

---

## D5 — B4: frontmatter parser unification

**Decision**: Canonical parser at `vault/frontmatter.py` with
signature:

```python
def parse_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from a markdown file.

    Returns:
        (frontmatter_dict, body_markdown). frontmatter_dict is
        empty if no frontmatter present; body_markdown is the
        full file content if no frontmatter present.

    Raises:
        FrontmatterParseError: on malformed YAML or missing
            closing `---` delimiter. Error includes file path
            and line number.
    """
```

Auxiliary helpers exposed:
- `parse_frontmatter_str(content: str) -> tuple[dict, str]` for
  in-memory content (e.g. tests).
- `dump_frontmatter(frontmatter: dict, body: str) -> str` for
  symmetric write operations.
- `FrontmatterParseError` exception class.

≥ 8 of the 12+ existing call sites migrate; holdouts carry inline
comments. Edge cases covered by tests:
- Empty frontmatter (just `---\n---\n<body>`).
- Missing closing `---`.
- Multi-document YAML (rejected with clear error — vault notes
  use single-doc only).
- Nested keys (preserved as nested dicts).
- Unicode keys/values.
- Frontmatter-only files (empty body).

**Rationale**:
- A single signature `(Path) -> (dict, str)` covers ~90% of the
  existing call sites' patterns. The 4 holdouts that may not
  migrate are sites with side-effects (e.g. schema-drift
  detection logic baked into the parser); these get inline
  comments explaining the constraint.
- Typed return value (`tuple[dict, str]`) makes downstream callers
  testable without mocking.
- `FrontmatterParseError` as a dedicated exception lets call
  sites distinguish parse failures from other I/O errors.

**Alternatives considered**:
- *Alt 1 — return a dataclass (`FrontmatterDoc(frontmatter, body)`)*:
  rejected for v1. Tuple is simpler; if downstream code wants
  named access, it can unpack. A future spec could add the
  dataclass wrapper if it helps.
- *Alt 2 — adopt an existing PyPI package (e.g. `python-frontmatter`)*:
  rejected. Violates Principle V (no new runtime deps).
- *Alt 3 — keep the 12+ parsers but assert their outputs match*:
  rejected. Doesn't reduce duplication; the architect's concern
  (parsers might drift and produce metric disagreement post-022)
  remains unresolved.

**Status**: locked.

**Implementation pointer**: New module `vault/frontmatter.py` with
the canonical parser. Existing call sites enumerated by
`rg "yaml.safe_load.*frontmatter|^---$"` at task-generation time.
Migration happens incrementally in B4's PR (sliceable: each call
site is an independent test target).

---

## D6 — B5: `cli.py` split organisation

**Decision**: New `cli/` subpackage organised by command group:

```text
cli/
├── __init__.py     # re-exports `build_parser()` unchanged (FR-011 / SC-009)
├── _common.py      # shared parser helpers (subparser registration, etc.)
├── research.py     # ./vault research, --resume (US4 A4 touches here)
├── audit.py        # ./vault audit
├── vault.py        # ./vault write, update, onboard, install, etc.
├── quality.py      # ./vault quality-baseline-update (spec 022 owns; placeholder OK pre-022)
└── (others as discovered during implementation — likely <8 total)
```

Each `cli/<group>.py` exports:
- `register(subparsers)` — adds the group's subparser(s).
- `handle(args)` — dispatches based on the chosen subcommand.

`build_parser()` in `cli/__init__.py` aggregates them:

```python
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="research-framework", ...)
    subparsers = parser.add_subparsers(dest="command", required=True)
    from . import research, audit, vault, quality
    for module in (research, audit, vault, quality):
        module.register(subparsers)
    return parser
```

The old `cli.py` becomes a 1-line file:
`from research_framework.cli import build_parser  # re-export
for backward compat`.

**Rationale**:
- Mirrors the `./vault <command>` mental model — discovery via
  file naming.
- `register(subparsers)` / `handle(args)` is a 2-function contract
  per module; trivial to add a new command later.
- `build_parser()` re-export from `cli/__init__.py` preserves
  every external caller (CI scripts, test code, `install.sh`).
  SC-009 byte-identical `--help` output is enforceable via a
  golden-file test.

**Alternatives considered**:
- *Alt 1 — single dispatch table*: `cli/__init__.py` holds a
  `{"research": research.handle, "audit": audit.handle, ...}` dict.
  Rejected. Hides the per-module argparse wiring; harder to
  read.
- *Alt 2 — Click or Typer*: rejected. Violates Principle V (new
  dep); also breaks the byte-identical `--help` golden-file test
  (Click/Typer output differs from argparse).
- *Alt 3 — keep `cli.py` monolithic but factor out internal
  helpers*: rejected. Doesn't reduce the file to < 200 lines
  (FR-011); leaves contributors with the same "where do I add my
  new command?" navigation problem.

**Status**: locked.

**Implementation pointer**: `cli/__init__.py::build_parser` is
the public face; old `cli.py` thinned to a re-export. Golden-file
test at `tests/cli/test_build_parser_stable.py` captures the
pre-refactor `./vault --help` output and asserts byte-identical
post-refactor.

---

## D7 — B7: settings loader unification

**Decision**: Canonical loader at `pipeline/settings.py` with
signature:

```python
def load_vault_settings(vault_dir: Path) -> VaultSettings:
    """Load and validate vault settings.yaml.

    Returns:
        Typed VaultSettings dataclass with stage tiers, budget
        caps, dimensions, etc.

    Raises:
        SettingsError: on missing file, malformed YAML, missing
            required keys, or invalid values. Error message names
            the file path and the failing key/value.
    """
```

`VaultSettings` is a `@dataclass(frozen=True)` with typed fields
for every settings.yaml key the framework reads. Unknown keys are
preserved in a catchall `extras: dict[str, Any]` field for
forward-compat (vault generators may set extras for downstream
tools).

≥ 6 of the existing call sites migrate. Holdouts get inline
comments.

**Rationale**:
- A dataclass return type (vs. raw dict) gives IDE autocomplete
  + mypy support to downstream code — every new pipeline stage
  that reads settings gets free type safety.
- `frozen=True` + catchall `extras` field mirrors the YAML spec
  the framework already documents.
- One `SettingsError` exception simplifies error handling at
  every consumer; pre-refactor, each site rolls its own error
  message inconsistently.

**Alternatives considered**:
- *Alt 1 — return a dict*: rejected. Loses type safety; the
  duplication-elimination win is much smaller (the 6+ sites are
  duplicated because they each construct their own dict shape,
  not just because they each call yaml.safe_load).
- *Alt 2 — use Pydantic*: rejected. New runtime dep (Principle V).
- *Alt 3 — TypedDict instead of dataclass*: rejected. TypedDict
  doesn't enforce immutability; `frozen=True` dataclass is the
  closest stdlib equivalent to "immutable typed record".

**Status**: locked.

**Implementation pointer**: New module `pipeline/settings.py`
defining `VaultSettings`, `load_vault_settings`, `SettingsError`.
Existing call sites enumerated via
`rg "yaml.safe_load.*settings\.yaml"` at task-generation.
Migration happens incrementally in B7's PR.

---

## D8 — B3 sub-branch coordination with 022 implementation

**Decision**: A "cycle-runner edit lock" coordination protocol
during the `025-b3-step-extraction` window:

1. **Before opening the sub-branch**, the spec 025 implementer
   announces the lock in `CHANGELOG.md` `[Unreleased]` block:
   `Note: pipeline/cycle_runner.py under refactor (spec 025 B3),
   2026-MM-DD to 2026-MM-DD; coordinate edits via the
   025-b3-step-extraction branch.`
2. **During the lock window**, NO other PR may modify
   `pipeline/cycle_runner.py` directly. Other refactor work
   (e.g. spec 022 metric hooks) targets the **stable seams**
   (the pre-B3 function boundaries) and lands BEFORE the lock
   window. If a 022 implementer needs to touch cycle_runner.py
   during the lock, they coordinate with the 025 implementer via
   the lock-window comment thread (typically: 022 stages its change
   inside the 025 sub-branch, which already has the new step modules).
3. **After the sub-branch ships**, 022 v2 retargets its metric
   hooks from the pre-B3 seams to the new `pipeline/steps/<step>.py`
   return values. This is the planned "022 v2" follow-up
   (~half day per the strategic sequencing in
   `docs/ROADMAP.md`).

**Rationale**:
- The architect's primary concern about long-lived branches is
  merge conflict (`docs/SIMPLIFY-PASS.md` § 6). The edit-lock
  coordination protocol surfaces conflicts as a process gate
  rather than as a git-merge surprise.
- CHANGELOG `[Unreleased]` is already where the team announces
  in-flight work; reusing it for the lock announcement keeps the
  signal in one place.
- 022 v1 attaches hooks to the pre-B3 seams (the current
  monolithic structure); 022 v2 retargets post-B3 — this
  decoupling means 022 doesn't HAVE to wait for B3 to ship.

**Alternatives considered**:
- *Alt 1 — formal branch protection via GitHub*: rejected.
  Heavy-handed; the project doesn't have a formal review-team
  signoff for branch protections.
- *Alt 2 — no lock; just live with conflicts*: rejected. The
  architect's warning would materialise: the sub-branch could
  spiral into a 2-week merge-conflict slog.
- *Alt 3 — atomise B3 into per-step PRs (one PR per module
  extraction)*: this is the alternative the user explicitly
  rejected at Q3a clarify. Documented for completeness; the
  trade-off is captured in the Complexity Tracking section of
  plan.md.

**Status**: locked.

**Implementation pointer**: Documented in
`contracts/cycle-runner-edit-lock.contract.md` (Phase 1 artifact).
Activation by the spec 025 implementer at sub-branch creation;
deactivation at sub-branch merge.

**Interaction with A6 (US3) — surfaced at /speckit.analyze
2026-05-21 (finding L6)**: A6 deletes the 32 scattered
`_write_cycle_quality_report` call sites and wraps `run_cycle_steps`
in a context manager guard. If spec 022 v1 attaches metric hooks
to specific call sites within `cycle_runner.py` (e.g. one hook
per current `_write_cycle_quality_report` invocation), those
hooks will silently NO-OP after A6 deletes the call sites.

The Tier A ship sequence resolves this naturally: A6 ships
**before** 022 v1 starts attaching hooks, because Tier A ships
pre-022-v1 per FR-016 R3 carve-out. 022 v1 implementers
attaching metric hooks should:

1. Anchor hooks to the **stable seams** that survive A6:
   `run_cycle_steps` entry/exit, the `_quality_report_guard`
   context manager's `__enter__` / `__exit__`, and the
   step-boundary call sites that B3 will later extract
   (`_run_scout()`, `_run_research()`, `_run_postprocess()`
   in their pre-B3 inline form).
2. Avoid attaching hooks to anonymous mid-function call sites
   that A6 is going to delete.

The cycle-runner edit lock in D8 covers the B3 window; this
addendum extends the coordination concept to the A6 → 022 v1
sequence as informal guidance (no edit-lock needed because A6
ships in its own PR before 022 v1 starts).

---

## D9 — A5: doc-sync scope and verification

**Decision**: Three specific doc updates:

1. **`.specify/memory/constitution.md`** — search-and-replace
   any references to `run_cycle.sh` (deleted long ago).
   - Verification: `rg "run_cycle\.sh" .specify/` returns 0 hits.
   - The constitution's "Technology Constraints" section currently
     references `run_cycle.sh` (constitution.md line 527-529 at v1.3.3).
     Rewrite to reference the current `./vault research` entry
     point: `The `claude`/`codex` CLI is the agent runtime for
     Phase 2. The `./vault research` command (which calls into
     `cli/research.py` and ultimately `cycle_runner.run_cycle_steps`)
     dispatches the agent via `scripts/agent_call.py`...`.

2. **`docs/ROADMAP.md` QW-2 entry** — currently states "restore
   missing files" but the smoke meta-tests aren't missing —
   they're commented out in `build.sh`. Rewrite QW-2 to
   accurately describe the work: "uncomment the two smoke
   meta-test invocations in `build.sh` and verify they pass
   against the current 022 quality artifacts."
   - Verification: `rg "files never committed|files missing"
     docs/ROADMAP.md` returns 0 hits.
   - This work also gets absorbed into **spec 024 US3** per the
     Q4a clarify; A5's update just ensures ROADMAP reflects
     reality during the transition.

3. **`build.sh` comments** — the file's header comment currently
   references the old smoke-gate contract (pre-spec-019). Update
   to describe the current `SMOKE_TESTS` manifest format.
   - Verification: maintainer reads the file post-A5 and
     confirms accuracy.

**Rationale**:
- Each update is bounded (one specific file, one specific signal
  to verify). Doc sync can drift; bounding it prevents scope
  creep.
- The grep-based assertions in `tests/docs/test_doc_sync.py`
  catch regression: if a future contributor reintroduces
  `run_cycle.sh` somewhere, the test fails.
- `build.sh` doesn't have a grep-able invariant (comments are
  prose), so its verification is manual. Acceptable for a
  one-shot doc fix.

**Alternatives considered**:
- *Alt 1 — full doc audit*: rejected. Scope creep; A5's purpose
  is the three specific known-stale references in
  `docs/SIMPLIFY-PASS.md` § 4. A broader audit is a follow-up
  spec.
- *Alt 2 — auto-generate the constitution's Technology
  Constraints section from `pyproject.toml`*: rejected. Over-
  engineering; the manual fix in A5 is < 1 hour of work.

**Status**: locked.

**Implementation pointer**: One PR per doc (or all three in one
PR — implementer's call). Test in `tests/docs/test_doc_sync.py`
enforces the two grep-able invariants.

---

## Open items (deferred to `/speckit.tasks` time)

These are smaller decisions that don't need a full design
paragraph; the implementer resolves them when generating tasks.

- **O1**: Exact module paths for B4 / B7 — `vault/frontmatter.py`
  vs `processors/_common.py` (spec.md FR-010 allows either). The
  implementer picks at task-generation based on import-cycle
  risk analysis. Recommendation: `vault/frontmatter.py` because
  it's a fresh module with no inbound imports.
- **O2**: Whether `CycleContext` (B3) lives in
  `pipeline/cycle_context.py` (top-level) or
  `pipeline/steps/_types.py` (inside the new subpackage). Pick
  whichever avoids circular imports.
- **O3**: Whether to keep ONE optional `_write_cycle_quality_report`
  mid-cycle progress-log call site (FR-007 allows up to 2). The
  default plan is ZERO secondary sites; the implementer adds one
  only if it surfaces an actual reporting use case during the
  refactor.
- **O4**: Exact handling of A4's edge case "multiple in-progress
  cycles" — the error message is specified in D3; the
  implementer decides whether to also write a recovery hint
  ("did you mean `./vault research --resume --cycle 5`?").
