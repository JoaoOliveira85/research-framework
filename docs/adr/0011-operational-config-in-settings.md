# ADR-0011: Operational run-control config lives in settings, not the spec

**Status**: Accepted (2026-06-06) — spec 061 shipped in 1.0.0rc3 (PR #126, squash `2d217be`). *(Proposed 2026-06-05.)*
**Date**: 2026-06-05
**Tags**: configuration, spec-schema, cli, design-decision, rc3
**Evidence base**: 2026-06-05 codebase-vault rc1 acceptance evaluation, §3.1 (root cause). Verified code paths: `cli/research_generate.py:106-114`, `_assets.py:149`, `orchestrator.py:518`.

## Context

The per-cycle budget (`max_cycles`) is currently expressible in at least four
places, with silent precedence that surprised an operator during a live
validation run: a spec asked for 12 cycles and the run did 6, because the
bundle's `settings.yaml::cycles.initial_max: 6` overrode `spec.budget.max_cycles`
(see spec 061 for the full site table and the smoking-gun log line).

The override is *by design* today — `load_cycle_limits_from_settings`'s docstring
states settings is meant to override the spec "so the documented knob actually
does something." But that collides head-on with the operator's mental model,
stated explicitly: **"the spec should supersede settings."** Both cannot be true.

The deeper question the collision exposes: **what belongs in a research-spec, and
what belongs in settings?** A spec answers *what the vault is* — its scope, note
types, coverage targets, data sources, search dimensions, authority model. A
settings file answers *how a particular run executes* — which executor, what
sandbox, how many cycles, what dollar cap. `max_cycles` is squarely the latter,
yet it lives in both, mutated across the boundary at generate time. The ambiguity
itself is the cost (cf. ADR-0009's rejection of the "coexist" option for the same
reason).

## Decision

**Run-control ("operational") config lives in settings; the spec defines the
vault.** Concretely:

1. **The per-cycle budget is removed from the research-spec schema** (top-level
   `max_cycles` + `BudgetConfig.max_cycles`) and from `spec/simple.py`, the
   validator, and the example specs. The spec no longer carries it, so there is
   nothing for settings to "override" — the contradiction disappears by
   construction.
2. **One canonical settings key** carries the per-cycle budget (the two competing
   keys are consolidated; the deprecated key is handled loudly, never silently
   ignored). The exact name + deprecation policy are spec-061 clarify decisions.
3. **An unambiguous precedence ladder**: `--max-cycles` CLI flag (last word) >
   the canonical settings key > a built-in default.
4. **Overrides are loud and recorded** — a higher-precedence source overriding a
   lower one (or a deprecated key being migrated) emits a `logging.WARNING`, and
   the run report records the configured budget, its source, and configured-vs-
   actual cycles. A constrained exit can never again read as a normal completion.
5. **`budget.max_usd` moves too** (resolved 2026-06-05, spec-061 clarify Q3 = **yes**).
   It is the same shape — a run-control knob read off `spec.budget` by the
   orchestrator — so it is reclassified to settings-only in lockstep with
   `max_cycles`, same precedence ladder + loud-override treatment. The reclassification
   is decided *by category* (run-control config), not field-by-field.

## Consequences

**Good**
- The spec-vs-settings precedence question is answered once, by category, not
  per-field. Future run-control knobs default to settings without re-litigation.
- A silent 12→6 truncation becomes impossible: single source + loud override +
  recorded provenance.
- Specs become portable run-definition documents — copying a spec to a new
  machine no longer carries machine-specific run limits.

**Trade-offs**
- **Breaking schema change.** Existing specs that carry `max_cycles` must drop it
  (or tolerate it via a grace period — spec-061 Q2). Acceptable: pre-1.0 is the
  moment to make it, and no third-party specs exist outside the example set and
  the two example vaults.
- A knob moves from the artifact most operators read first (the spec) to the one
  they read second (settings). Mitigated by FR4's loud override + run-report
  provenance and by the `--max-cycles` flag for one-off changes.

## Alternatives considered

- **Keep `max_cycles` in the spec and make the spec win** (honour the operator's
  "spec supersedes settings" literally). Rejected: it keeps a run-control knob in
  the vault-definition artifact, leaves the duplicate settings keys in place, and
  perpetuates the category confusion. It fixes the *symptom* (which value wins)
  without fixing the *cause* (the knob is in two categories of file at once).
- **Keep both locations, just document the precedence loudly.** Rejected for the
  ADR-0009 reason: the ambiguity is the cost. Documentation does not stop the next
  operator from editing the wrong file; removing the field does.
- **Collapse everything (incl. `max_usd`) in this one ADR with no clarify.**
  Rejected as premature: the *principle* is decidable now; the *scope* (max_usd,
  the update-path key, the default value) benefits from the spec-061 clarify pass.

## Relationship to other ADRs

- Echoes **ADR-0009**'s "the ambiguity itself is the cost" reasoning for rejecting
  a coexistence option.
- Does not supersede any existing ADR (none previously ruled on spec-vs-settings
  config ownership).

## Tests

- `tests/spec/test_schema_budget_removed.py` — `max_cycles`/`max_usd` are gone
  from `BudgetConfig` (`test_budget_config_schema_fields_removed`); a stray
  key in either the top-level or `budget:` block parses with zero effect
  (`test_stray_top_level_max_cycles_silently_ignored`,
  `test_stray_budget_max_cycles_parses_with_zero_effect`,
  `test_stray_budget_max_usd_parses_with_zero_effect`); the generate path
  never writes either field back onto a loaded spec
  (`test_generate_path_does_not_mutate_spec_max_cycles_fields`).
- `tests/cli/test_max_cycles_flag.py` — the live precedence ladder in
  `cli/_budget_resolve.resolve_cycle_budget`: flag beats settings
  (`test_flag_beats_settings`), flag beats default
  (`test_flag_beats_default`), and settings beats default when no flag is
  given (`test_absent_flag_falls_through_to_settings_then_default`); an
  invalid value exits 2 (`test_invalid_max_cycles_zero_or_negative_exits_2`).
- `tests/test_assets.py` — the deprecated `cycles:` block's back-compat
  reader (`load_cycle_limits_from_settings`) defaults to `(None, None)` when
  absent or malformed and never accepts a non-positive or non-int value.
- `tests/pipeline/test_run_report_budget_provenance.py` — the run report
  records the configured budget and its source, and a constrained exit
  (`test_max_cycles_reached_reports_constrained_exit`) is distinguishable
  from a clean completion
  (`test_clean_completion_reports_complete_with_actual_lte_configured`) — the
  silent-truncation failure mode this ADR exists to close.
