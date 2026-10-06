---
spec_number: 061
title: Cycle-budget configuration consolidation — one source of truth + loud overrides
status: SHIPPED 1.0.0rc3 (PR #126, squash 2d217be)
target_version: 1.0.0rc3
created: 2026-06-05
source_input: |
  2026-06-05 codebase-vault rc1 acceptance evaluation (defect 3.1 — ROOT CAUSE).
  The validation run terminated on `max_cycles (6) reached` — a constrained exit at
  HALF the spec's 12-cycle budget — because `cycles.initial_max: 6` in the bundle's
  settings.yaml silently overrode the spec's `budget.max_cycles: 12`. Surfaced as a
  single stdout line. The cycle count is currently expressible in ≥4 config sites
  with silent precedence; the least-visible one won.
---

**Status:** shipped(2026-06-06, PR #126) — SHIPPED **1.0.0rc3** (2026-06-06, PR #126, squash `2d217be`) — rc3 wave
(sibling specs 062, 063; amendments to 028 + 048 v2). Canonical `pipeline.max_cycles`
+ single precedence ladder; deprecated `cycles.*` warn-and-honoured; spec-schema
budget keys removed; `--max-cycles`/`--max-usd` flags; run-report `cycle_budget`
provenance. Carries **ADR-0011** (the reclassification reverses an explicit prior
design intent, so it is recorded).

# Feature Specification: Cycle-budget configuration consolidation

**Feature Branch**: `061-cycle-budget-config`
**Created**: 2026-06-05

## Clarifications (resolved 2026-06-05)

All 5 open questions resolved. Decisions are authoritative — where an FR below still
reads as an open question, this block wins (per the spec-051 precedent).

| Q | Decision | Notes |
| --- | --- | --- |
| **Q1 — canonical key** | **`pipeline.max_cycles`** is the single canonical per-cycle-budget key (generate + resume). The `cycles:` block (`initial_max` / `update_max`) is **deprecated** — honoured with a loud WARNING for a grace period, then removed. | Resolves the 20-vs-6 disagreement in favour of the generous, already-present `pipeline.max_cycles`. The cold-start-vs-incremental split is dropped (one knob); `--max-cycles` covers one-offs. |
| **Q2 — spec-schema removal** | **Remove `max_cycles` from the schema; a leftover `max_cycles:` in a spec is silently ignored exactly like any other unknown field** — no special error, no special warning. | Operator's rule: "handle it as if it were a field that doesn't exist." **Verified**: `spec/parser.py` → `SpecConfig.from_dict` reads only known keys via `.get()`; there is **no strict unknown-key rejection**, so an unrecognised `max_cycles:` is dropped at parse time and never reaches the validator — identical to a hypothetical `pizza:`. Example specs are updated so nobody copies a stale field. |
| **Q3 — `budget.max_usd`** | **YES — reclassified alongside `max_cycles`** (operational → settings-only), same precedence ladder + loud-override treatment. Rides this spec. | Consistency: ADR-0011 decides by *category*, not per-field. Removed from `BudgetConfig`; the dollar cap resolves from settings/flag like the cycle budget. |
| **Q4 — default + orchestrator read** *(in-spec default taken)* | The orchestrator no longer reads `spec.budget.*`; the CLI resolves the ladder (flag > `pipeline.max_cycles` > built-in default) and threads the values in. Seed default = the existing generous `pipeline.max_cycles` (≈20 — finalised at plan against the spec-022 fixtures so baselines don't move). | Removing the field forces an explicit param; the generous existing value means a bootstrap is never silently truncated. |
| **Q5 — `cycles.update_max`** *(in-spec default taken)* | Folded: resume/update uses the same canonical `pipeline.max_cycles` (or `--max-cycles`); `cycles.update_max` joins `cycles.initial_max` in the deprecated-with-warning set. | One knob, per Q1. |

## Why this spec exists

The codebase-vault rc1 validation run asked for 12 cycles and did 6. The smoking
gun (`~/Documents/codebase-run.log:2`):

```
[phase 0] cycles.initial_max from settings: 6 (was 12)
```

This is not a one-off mis-config — it's a structural problem. The per-cycle budget
is currently expressible in **at least four places**, and the *least visible* one
wins silently:

| # | Location | Value in the rc1 run | Used at generate? |
| --- | --- | --- | --- |
| 1 | spec top-level `max_cycles` | 12 | overridden |
| 2 | spec `budget.max_cycles` | 12 | overridden |
| 3 | settings `pipeline.max_cycles` | 20 | **ignored** |
| 4 | settings `cycles.initial_max` | **6** | **WON** |

**Verified code path** (2026-06-05):

- `cli/research_generate.py:106-114` calls `load_cycle_limits_from_settings()`,
  reads `cycles.initial_max`, and when it differs from `spec.budget.max_cycles`
  **mutates both `spec.budget.max_cycles` and `spec.max_cycles`** — emitting a
  single `print(...)` to stdout, no warning, nothing recorded in the vault.
- `_assets.py:149` (`load_cycle_limits_from_settings`) reads `cycles.initial_max`
  / `cycles.update_max` only — `pipeline.max_cycles` is never consulted at generate
  time (it governs later `./vault research` runs).
- `orchestrator.py:518` then reads `spec.budget.max_cycles`; the constrained-exit
  reason `max_cycles ({max_cycles}) reached` is emitted at `orchestrator.py:649`.

Both shipped settings profiles carry the inconsistency today:
`settings.yaml` (`pipeline.max_cycles: 20` @ L131 + `cycles.initial_max: 6` @ L394)
and `settings.codex.yaml` (`pipeline.max_cycles: 20` @ L106 + `cycles.initial_max: 6`
@ L277). **The reference-vault re-run will truncate identically** unless this is fixed —
which is why it gates the remaining validation runs.

### The design contradiction this spec resolves

The current behaviour is intentional: `load_cycle_limits_from_settings`'s docstring
says settings is *meant* to override the spec ("so the documented knob actually does
something"). But that directly contradicts the operator's stated model — **"the spec
should supersede settings."** You cannot have both. This spec resolves the
contradiction by **reclassifying the per-cycle budget as operational config**
(belongs in settings; the spec defines *what the vault is*, not *how long a run
goes*), recorded in **ADR-0011**. The resulting precedence ladder is unambiguous:

```
--max-cycles CLI flag   >   one canonical settings key   >   built-in default
```

The spec carries NO cycle budget at all, so there is nothing to contradict.

## Out of scope (explicitly)

- **The CG-001 yield model** (spec 051 FR1) — unrelated; that governs *how many
  notes per cycle*, this governs *how many cycles*.
- **Constrained-exit note handling** (rejected-note quarantine) — owned by sibling
  spec 062.
- **Harness gating on configured-vs-actual cycles** — owned by sibling spec 063
  (§4.1 "run-completion semantics"); this spec only *emits* the signal, 063
  *checks* it.

## Functional requirements

### FR1 — One canonical settings key for the per-cycle budget

**Today.** Two settings keys (`pipeline.max_cycles`, `cycles.initial_max`) plus a
third resume-time meaning for `cycles.update_max`. They disagree (20 vs 6) in the
shipped seed and only one is honoured at generate time.

**Proposed (Q1/Q5 resolved).** **`pipeline.max_cycles` is the single canonical key**
for the per-cycle budget (generate AND resume). The `cycles:` block
(`cycles.initial_max`, `cycles.update_max`) is **deprecated**: on load it emits a loud
`logging.WARNING` naming `pipeline.max_cycles` and is honoured-as-alias for a grace
period (never silently ignored — that was the original bug). The cold-start-vs-
incremental split the old keys encoded is dropped; `--max-cycles` (FR3) covers
one-off changes.

**Acceptance**:
- `pipeline/settings.py` exposes the per-cycle budget through ONE typed field.
- A settings file carrying the deprecated key produces a single, loud WARNING that
  names the canonical key and what the loader did with the old value.
- `tests/pipeline/test_cycle_budget_settings.py` covers: canonical-only, deprecated-
  only (migrated + warned), both-present (canonical wins + warns), neither (default).

### FR2 — Remove the per-cycle budget from the research-spec schema

**Today.** `max_cycles` exists top-level on the spec AND on `BudgetConfig`
(`spec/schema.py:312` + `:454`), is set by `spec/simple.py`, appears in example specs,
and is mutated in place by the generate CLI. `budget.max_usd` (`schema.py:311`) is the
same shape.

**Proposed (ADR-0011; Q2 + Q3 resolved).** The spec no longer defines run-control
budget. Remove **both `max_cycles` and `max_usd`** from the schema (top-level
`max_cycles` + `BudgetConfig.max_cycles` + `BudgetConfig.max_usd`), `spec/simple.py`,
and the example specs. **A leftover `max_cycles:` / `max_usd:` in a spec is silently
ignored exactly like any other unknown field** — no special error, no special warning
(Q2). This is the *existing* parser behaviour, not new code: `SpecConfig.from_dict` /
`BudgetConfig.from_dict` read only known keys via `.get()` (`schema.py:323-328` /
`:531`), so a removed field is dropped at parse time and never reaches the validator —
identical to a hypothetical `pizza:` field. The validator is **not** taught a
special-case rule for the old keys.

**Acceptance**:
- `spec/schema.py` no longer carries `max_cycles` or `max_usd` (top-level or budget);
  loading a spec that still contains either **silently ignores it** (no error, no
  warning) — `tests/spec/test_schema.py` asserts a spec with a stray `max_cycles:`
  parses fine and the value has no effect, identical to an arbitrary unknown key.
- `examples/*.spec.md` / `examples/research.spec.md` / the detailed reference spec no
  longer carry a cycle budget or dollar cap; their settings counterparts do.
- `cli/research_generate.py` no longer mutates `spec.budget.max_cycles` /
  `spec.max_cycles` — it resolves the budget from the precedence ladder and threads
  it to the orchestrator directly (Q4 for where the orchestrator reads it).
- `tests/spec/test_schema.py` (or equivalent) asserts the field is gone and the
  migration behaviour holds.

### FR3 — `--max-cycles N` launch flag (last-word override)

**Today.** CLI override hooks exist piecemeal in `cli/research_generate.py`,
`research_resume.py`, `research_phase3.py`, but there is no single documented
last-word flag; the only override path is editing a settings file.

**Proposed.** A `--max-cycles N` flag on `generate` (and the resume/phase3 entry
points) is the top of the precedence ladder — it beats settings and the default.
`N` must be a positive int; `0`/negative is a usage error.

**Acceptance**:
- `tests/cli/test_max_cycles_flag.py`: flag beats settings; flag beats default;
  absent flag falls through to settings then default; invalid `N` → exit 2 with a
  clear message.

### FR4 — Overrides are LOUD and recorded (never silent again)

**Today.** The 12→6 override was a single stdout `print`. It did not WARN, was not
in the run-report, and the constrained exit (which the framework *did* record as
"constrained" — `vault_commit.py:445`, `run-report.md` "max_cycles (6) reached")
was easy to read as a normal "done".

**Proposed.** Two parts:
1. **At resolution time**, whenever the effective per-cycle budget comes from a
   lower-precedence source being overridden by a higher one (or a deprecated key is
   migrated), emit a real `logging.WARNING` via the spec-048 logger — not a bare
   `print`.
2. **In the run report**, record the budget provenance: the *configured* budget, its
   *source* (flag / settings-key / default), and — at exit — *configured vs actual*
   cycles run. A constrained exit (`max_cycles`/budget) MUST be distinguishable from
   a clean completion in the report (it already is in the commit text; this makes it
   first-class in `run-report.md` + the run-report JSON).

**Acceptance**:
- `tests/pipeline/test_run_report_budget_provenance.py`: run report carries
  `cycle_budget: {configured, source, actual, exit_status}`; a `max_cycles`-reached
  run reports `exit_status` ≠ "complete" and `actual == configured`.
- The override WARNING is emitted through the logger and is suppressible by
  `--log-level error` (proves it's a log record, not a print).
- This is the signal sibling spec 063 §4.1 gates on — cross-referenced there.

### FR5 — Sane shipped default (a bootstrap is never silently capped at 6)

**Today.** The seed `cycles.initial_max: 6` is *below* a typical bootstrap need and,
because it overrode the spec, produced a half-baked vault.

**Proposed.** The shipped seed default for the canonical key MUST NOT silently
truncate a cold-start bootstrap. The concrete default value is a clarify decision
(Q4) — options include raising it, removing the seed value so the built-in growth
default applies, or making the bootstrap default explicitly larger than the
incremental default.

**Acceptance**:
- The shipped `settings.yaml` / `settings.codex.yaml` seeds carry the canonical key
  with a value (and comment) agreed at Q4, and the two no longer disagree.
- A scaffold-manifest sha update accompanies the seed change (per the
  `dist-templates/scaffold-manifest.json` discipline).
- The spec-022 quality-harness baselines do not move (the default must preserve
  fixture behaviour, or the baselines are intentionally re-cut and noted).

## Key entities

- **Per-cycle budget**: a single positive integer — the maximum number of research
  cycles a run may execute. Operational, not a vault-definition concern.
- **Budget provenance**: `{configured: int, source: "flag"|"settings"|"default",
  actual: int, exit_status}` recorded per run.

## Success criteria

- **SC-001**: After this spec, the per-cycle budget is settable in exactly ONE
  settings location and ONE CLI flag; no spec field; no second settings key honoured
  silently.
- **SC-002**: A run whose effective budget differs from a configured source emits a
  WARNING and records provenance — re-running the rc1 codebase-vault scenario would
  have surfaced the 12→6 truncation as a headline, not a buried line.
- **SC-003**: The reference-vault re-run on the rc3 bundle executes its intended cycle
  budget with no silent truncation.

## Open questions — RESOLVED 2026-06-05

All five resolved in the **Clarifications** block at the top of this spec; the original
question text is retained below for provenance.

- **Q1 — Canonical key + deprecation policy.** Which key wins: keep
  `pipeline.max_cycles`, keep `cycles.initial_max`, or introduce a new neutral key
  (e.g. `run.max_cycles`)? And for the deprecated key(s): hard-error, or
  warn-and-honour for a grace period?
- **Q2 — Spec-schema removal: hard vs grace.** Does the validator ERROR on a spec
  that still carries `max_cycles` (clean break, pre-1.0 is the moment for it), or
  WARN-and-ignore for one minor?
- **Q3 — Does `budget.max_usd` get the same reclassification?** Recommended **yes**
  (consistency; it's the same `spec.budget` run-control shape). If yes, it rides
  this spec; if no, it's a noted follow-up.
- **Q4 — Shipped default value + where the orchestrator reads the budget.** What is
  the seed default for the canonical key (and is the cold-start default distinct from
  the incremental `update_max`)? And does the orchestrator keep reading
  `spec.budget.max_cycles` (now populated from settings by the CLI) or take an
  explicit param?
- **Q5 — `cycles.update_max` (resume/update path).** Fold it into the same canonical
  model (e.g. `run.max_cycles` + a separate `run.update_max_cycles`), or leave the
  update path as-is and scope this spec to the generate path only?

## Provenance

- **Primary source**: 2026-06-05 codebase-vault rc1 acceptance evaluation, §3.1
  (ROOT CAUSE · HIGH) + the truncation proof (`~/Documents/codebase-run.log:2`,
  `_pipeline/run-report.md`).
- **Verified against code** 2026-06-05: `cli/research_generate.py:106-114`,
  `_assets.py:149`, `orchestrator.py:518/649`, `settings.yaml:131/394`,
  `settings.codex.yaml:106/277`.
- **ADR**: introduces **ADR-0011** (operational config lives in settings; the spec
  defines the vault) — reverses the `load_cycle_limits_from_settings` intent and
  formalises the precedence ladder. Status Proposed → Accepted when 061 ships.
- **Cross-references**: sibling rc3 specs 062 (constrained-exit note integrity) and
  063 (acceptance harness §4.1 gates on FR4's signal).

Shipped 1.0.0rc3 (2026-06-06, PR #126).

---

## Amendment — a zero dollar budget means UNLIMITED *(added 2026-09-07)*

**Status (amendment):** shipped — owner's decision, 2026-09-07. Amends FR3/Q3's
`max_usd` rung of the ladder only; every other clause of this spec is unchanged.

### The decision

`pipeline.budget_usd: 0` (and `0.0`, and any other spelling of zero, on either
the settings rung or the `--max-usd` flag rung) **MUST resolve to UNLIMITED** —
identical to `None` and to an absent key. It is never a zero-dollar cap, and it
never means "ask before every spend".

### Why this amendment exists

As shipped, `_resolve_usd` treated `0` as an ordinary number and returned a
literal `0.0`, leaving its meaning to whichever consumer read it next.
`orchestrator.run_cycles` guards on `cumulative >= budget_cap > 0` and therefore
read it as uncapped — but nothing in this spec said so, and a second reader was
free to read the same value as "spend nothing" and stop the run before its first
dispatch.

That ambiguity was live for months. Every one of the six shipped settings
profiles carried `pipeline.budget_usd: 0.0` until issue #230 (PR #317) seeded
real ceilings, and every vault generated from one of them ran to completion. So
"uncapped" is the meaning the corpus already carries; this amendment moves it to
the one place the value is decided instead of leaving it as an artifact of a
`> 0` comparison three layers downstream.

PR #317 declined to make this change from a bug-fix branch, on the grounds that
reversing a documented resolution rule is a contract change that wants a spec.
This is that amendment.

### Amendment requirements

- **FR3-Z1 — Zero is uncapped, at the resolver.** `_resolve_usd` returns
  `max_usd=None` for a zero from settings or from the flag.
- **FR3-Z2 — Both rungs agree.** `--max-usd 0` means exactly what
  `pipeline.budget_usd: 0` means. One ladder with two meanings of zero would be
  a silent disagreement between its own rungs — the class of bug this spec
  exists to remove.
- **FR3-Z3 — Provenance survives.** An explicitly configured zero still reports
  `max_usd_source: "settings"` (or `"flag"`), because the operator did configure
  it, and FR4 owes the run report that fact. Only an absent/invalid value
  reports `"default"`.
- **FR3-Z4 — Nothing else moves.** A negative settings value is still ignored
  (falls through the ladder); a negative flag is still a `BudgetError`. The
  per-cycle ceilings under `limits:` are a different key with a different rule
  (`limits.cycle_budget_usd` must be **positive**; the settings loader rejects a
  zero there) and are untouched — as are the real ceilings PR #317 seeded into
  every shipped profile.

### Acceptance (amendment)

`tests/cli/test_budget_usd_zero_is_unlimited.py` — `0`, `0.0`, `-0.0` and `"0"`
resolve uncapped; absent and explicit-null resolve uncapped from the `default`
rung; a positive value still caps; zero on the flag rung is uncapped with
`"flag"` provenance; a negative flag still raises; and a vault configured
`budget_usd: 0.0` reaches `run_cycles`'s cumulative guard without tripping it.

---

## Amendment — one ladder for every run verb, and honest names for it *(added 2026-09-07)*

**Status (amendment):** shipped — issues #233 / #239. Amends FR1/FR3's reach
(which verbs consult the ladder) and FR4's honesty rule (what the flags claim
they are). The precedence order itself is unchanged.

### The problem this amendment fixes

SC-001 says the per-cycle budget is settable in "exactly ONE settings location
and ONE CLI flag". That was true of `generate` (and `--resume`) and false of
the framework: there were three run verbs and three budget stories, and
`--help` could not tell you which enforced what.

| Verb | Budget resolution, as shipped |
| --- | --- |
| `generate` (incl. `--resume`) | the ladder |
| `cycle` | a hardcoded `--budget-cap` default of **$10.00**, and a hardcoded `max_cycles=5` two layers down |
| `pipeline full` | a nullable `--budget-cap` that nothing read (refused since issue #232) |

`cycle`'s $10.00 was the fourth budget knob this spec was written to
eliminate, and it was reachable *by omitting an argument* — the most invisible
rung there is. It appeared in no settings file, no spec and no flag, and
`orchestrator.run_single_cycle` / `cycle_runner.run_cycle_steps` handed it to
every caller that did not pass one.

Separately, both top-rung flags **named the wrong semantics**. Spec 070's open
questions 4/4a recorded it and nobody fixed it:

- `--max-cycles` help said "Per-run cycle cap"; `run_cycles` iterates
  `range(start_cycle, max_cycles + 1)`, so it is an absolute cycle NUMBER
  ceiling. Spec 070 F5 already says so — in an error message the flag's own
  help contradicted.
- `--max-usd` help said "Per-run dollar cap"; it is compared against
  `_cumulative_sidecar_cost(up_to=cycle)`, which sums every cycle the vault has
  ever run.

So "give it $10" was unachievable on a vault that had already spent more, and
the operator had no flag that meant what they wanted.

### Amendment requirements

- **FR1-V1 — Every run verb resolves the same ladder.** `cycle` resolves
  `--budget-cap` (its spelling of the `--max-usd` rung) and `pipeline.max_cycles`
  through `resolve_cycle_budget_from_path`, exactly as `generate` does. No entry
  point may carry a budget default of its own: `run_single_cycle` and
  `run_cycle_steps` take `None` and resolve, via one shared backfill
  (`_budget_resolve.fill_missing_run_budget`).
- **FR1-V2 — `pipeline` still refuses, and says which ladder to use instead.**
  No `pipeline` phase writes a cost sidecar (#220/#221), so there is nothing to
  enforce a cap against; refusing loudly beats a cap that enforces nothing
  (the spec-074 precedent). Its refusal names `limits.cycle_budget_usd` and
  `cycle --budget-cap`.
- **FR1-V3 — No verb may walk past a pause.** A standing `BUDGET_PAUSED` /
  `APPROVAL_REQUIRED` marker stops `cycle` with exit 2 naming the marker path,
  `pause show`, and the resume that can actually clear it. `cycle` carries no
  `--force-budget` / `--approve` surface and so is in no position to decide a
  pause; before this it simply ignored one and re-dispatched the paused stage.
- **FR3-L1 — The lifetime flags say "lifetime".** `--max-cycles` and
  `--max-usd` keep their meaning and lose the word "per-run"; their help states
  the ceiling they actually are, and `--max-cycles`' help names `--more-cycles`
  for the other reading.
- **FR3-P1 — `--more-cycles N`.** N more cycles from wherever the vault stands:
  resolves to `<next cycle> + N - 1`. Occupies the same top rung as
  `--max-cycles`, so passing both is a usage error — one rung cannot hold two
  conflicting answers. It is an INPUT to the ceiling and gets no field of its
  own on `BudgetResolution`: the resolver folds it into `max_cycles` (source
  `"flag"`), which is the value every consumer already reads, and a second
  copy beside it would be a number nobody consults. Waived in issue #271's
  parser-flag consumer guard on exactly that ground.
- **FR3-P2 — `--max-usd-this-run N`.** A ceiling on what THIS run adds,
  measured from the vault's lifetime spend at the instant the run starts.
  Independent of `--max-usd`; whichever ceiling is reached first ends the run.
  Flag-only by design: a per-run ceiling is a launch-time decision, and a
  settings key would outlive that decision and quietly re-apply to every later
  run — which is how `cycles.initial_max` earned this spec.
- **FR3-Z5 — Zero means uncapped in `validate_cycle.py` too.** The FR3-Z
  amendment settled zero-is-unlimited at the resolver, and
  `orchestrator.run_cycles` already read it that way. `validate_cycle.py`'s
  Condition C is a bare `cumulative_cost >= budget_cap` and read a zero as
  "you have spent everything you were given". It had never *seen* a zero,
  because `cycle --budget-cap` defaulted to $10.00; routing that verb through
  the ladder is what handed it one. One ladder means every consumer means the
  same thing by the value. An explicit `termination: "C"` in a report is the
  scout's own testimony and still stands — only the derived comparison needs a
  real ceiling.

### Acceptance (amendment)

- `tests/cli/test_cycle_verb_budget_ladder.py` — `--budget-cap` parses to
  `None`; `run_single_cycle` / `run_cycle_steps` carry no dollar or cycle
  default; settings honoured, flag last word, zero uncapped, absent settings
  fall through to the built-in default; a deprecated `cycles:` block warns on
  this verb too; each marker kind refuses the run, leaves the marker
  byte-identical, and is reported ahead of any config complaint.
- `tests/cli/test_lifetime_vs_per_run_budget.py` — neither lifetime flag's
  help says "per-run" and both say "lifetime"; `--more-cycles` resolves against
  the anchor, beats settings, rejects non-positive values and refuses to
  co-exist with `--max-cycles`; `--max-usd-this-run` is flag-only, zero is
  uncapped, negative raises; and `run_cycles` stops on the run ceiling while a
  vault with $50 of history still gets its full $2 run.
- `tests/scripts/test_validate_cycle_zero_budget_is_unlimited.py` — FR3-Z5, on
  both the v1 and v2 validators.
