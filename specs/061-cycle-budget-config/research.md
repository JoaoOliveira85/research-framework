# Phase 0 Research: Cycle-budget configuration consolidation

**Spec**: [spec.md](./spec.md) | **Date**: 2026-06-05

Phase 0 reconciles the spec's named surfaces against the real tree (verified
2026-06-05) and resolves the one remaining design choice the clarify block left to
the plan (the resolver location). No "NEEDS CLARIFICATION" remains entering Phase 1.

## D1 — `pipeline.max_cycles` is already the typed canonical field

**Question.** The spec says "expose the per-cycle budget through ONE typed field."
Does that field already exist, or is it net-new?

**Finding.** It exists. `pipeline/settings.py`:
- L21 — `_PIPELINE_TYPED_KEYS = {"max_cycles", "budget_usd", "backlog_promotion_threshold"}`.
- L137 — `VaultSettings.max_cycles: int`.
- L227-231 — `max_cycles = _require_positive_int(pipeline.get("max_cycles"), …)` —
  i.e. `pipeline.max_cycles` is parsed into a required positive int at load time.

**Decision.** FR1 *adopts* `VaultSettings.max_cycles` as the canonical field. No new
settings type. The competing `cycles:` block is **not** typed — it lives in
`.extras` and is consumed only by `_assets.load_cycle_limits_from_settings`
(`_assets.py:165` → `…extras.get("cycles")`). That asymmetry is exactly why the
generate path diverged from the typed field; FR1 closes it by routing the deprecated
extras through the canonical field with a WARNING.

## D2 — Unknown spec keys are already silently dropped (FR2 needs no new code)

**Question.** Clarify Q2 says a leftover `max_cycles:` must behave "like any other
unknown field." What *is* that behaviour today — error, warn, or ignore?

**Finding.** Silent drop. `spec/schema.py` `SpecConfig.from_dict` and
`BudgetConfig.from_dict` read only known keys via `.get()` (no `**kwargs`, no
unknown-key assertion). `spec/parser.py` `parse()` hands the parsed dict straight to
`from_dict`. An unrecognised top-level or `budget:` key never reaches the validator —
identical to a hypothetical `pizza:` field.

**Decision.** FR2 = delete the three fields (`BudgetConfig.max_cycles`,
`BudgetConfig.max_usd`, `SpecConfig.max_cycles`) and the `simple.py` budget emission.
**Do not** add special-case validation. The only net-new artifact is
`test_schema_budget_removed.py` pinning "stray `max_cycles:`/`max_usd:` parses fine
and has no effect." This matches the operator's "pizza field" answer exactly.

## D3 — One resolver, three CLI callers (the single design choice)

**Question.** generate, resume, and phase3 each have piecemeal override hooks. Where
does the precedence ladder (`flag > settings > default`) live?

**Finding.** `cli/research_generate.py`, `cli/research_resume.py`,
`cli/research_phase3.py` all already match on `max_cycles`/`initial_max` independently
(grep 2026-06-05). Implementing the ladder three times invites the same drift that
caused the bug.

**Decision.** New `cli/_budget_resolve.py` exposing
`resolve_cycle_budget(settings, *, flag) -> BudgetResolution` (see data-model.md).
All three entry points call it; it is unit-tested in isolation
(`test_budget_resolver.py`). This is the only structural addition in the spec.

## D4 — The orchestrator is already param-driven

**Question.** Does removing `spec.budget.*` require rewiring the orchestrator?

**Finding.** Mostly no. `run_cycles(..., max_cycles: int = 5, ...)`
(`orchestrator.py:368`) already accepts the cap as a parameter. The only spec reads
are the two internal lines `budget_cap = spec.budget.max_usd` /
`max_cycles = spec.budget.max_cycles` (`:517-518`), plus the user-facing hint at
`:806` ("bump `budget.max_cycles` or `budget.max_usd`").

**Decision.** The CLI resolves both caps and passes them in; delete the two
`spec.budget.*` reads and reword the `:806` hint to name the canonical settings key +
`--max-cycles`. The constrained-exit reason string (`:649`, `max_cycles (N) reached`)
and the `vault_commit.py:445` rc→text map are unchanged.

## D5 — Run-report provenance is additive

**Question.** Where does FR4 record `{configured, source, actual, exit_status}`?

**Finding.** `pipeline/run_report.py` already assembles `run-report.md` + a run-report
JSON and records the final exit code/reason. There is no existing budget-provenance
field.

**Decision.** Add an additive `cycle_budget` object to the run-report JSON and a
short "Cycle budget" line to `run-report.md`. The markdown is prose (no schema); the
JSON gains one nested object. A constrained exit (`exit_status != "complete"`,
`actual == configured`) is now first-class — the signal sibling 063 §4.1 gates on.

## Cross-cutting: defaults & the spec-022 baselines (FR5)

The shipped seeds disagree today (`pipeline.max_cycles: 20` vs `cycles.initial_max: 6`
in both `settings.yaml` and `settings.codex.yaml`). FR5 resolves them to one generous
value on the canonical key. The constraint: the spec-022 quality-harness fixtures must
not silently change cycle count. **Plan resolution of Q4 default**: keep the existing
generous `pipeline.max_cycles` (≈20) as the seed, drop the `cycles.*` seed values
(deprecated), and run `./build.sh --quality` to confirm the three fixture baselines do
not move (the harness fixtures cap cycles independently of the seed, so 20 vs 6 should
not shift them — verify, and if a baseline *does* move, re-cut intentionally and note
it in the FR5 task). A `scaffold-manifest.json` sha refresh accompanies the seed edit.

## No-change confirmations

- **Exit-code model** (`vault_commit.py:445`, constitution § Script Exit Code Model):
  untouched — 0 complete / 1 constrained / 2 aborted stays.
- **Resume highest-completed-cycle logic** (`research_resume.py`): untouched; resume
  only changes *which* cap it reads (canonical, via the shared resolver).
- **spec-033 cost enforcement**: `max_usd` reclassification changes *where the cap is
  configured*, not how the budget guard enforces it — the guard still reads the
  effective cap threaded from the CLI.
