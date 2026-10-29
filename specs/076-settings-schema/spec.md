# Feature Specification: The `settings.yaml` schema

**Status**: shipped(2026-09-07, commit 6935644) — a *record* of the
configuration contract as it is, written from the code at that commit. It
adds no scope. Divergences it found are filed under § Known divergences, not
fixed here.

**Amended 2026-10-28 (issue #8)**: unlike the rest of this spec, FR-022 to
FR-025 describe behaviour added after the record was taken — the unknown-key
report and `strict_settings`. Everything else is still a record.

**Spec**: `076-settings-schema` · **Epic**: #217 · **Issue**: #275, #230

---

## Why this spec exists

`settings.yaml` is the vault's only configuration file and the single largest
undocumented contract in the repo: ~550 lines of keys, seven shipped
profiles, three independent readers with different precedence rules, and no
schema anywhere. Issue #230 is what an unspecified config surface produces —
a `budget:` block that every shipped profile carried and nothing had ever
parsed. That block is gone from the six root profiles; a schema is what stops
the next one appearing.

A reader with no code access must be able to write a valid `settings.yaml`,
know which keys do something, and know which do not.

## Scope

**In scope**: the file's shape, the loaders and their precedence, every key
and its type/default/reader, what validation rejects, and an explicit dead-key
register.

**Out of scope**: `research.spec.md`'s own `settings:` block (a structurally
narrower mirror — see § Known divergences D2), and the semantics of the
features the keys configure, which live in their own specs (`033`, `061`,
`020`, `055`, `040`).

---

## User Scenarios & Testing

### User Story 1 — A vault loads its settings, or is told exactly why not (Priority: P1)

1. **Given** a `settings.yaml` carrying `pipeline.max_cycles` and
   `pipeline.budget_usd`, **When** the loader runs, **Then** it returns a
   frozen, typed settings object and every unrecognised top-level key is
   preserved verbatim in an `extras` mapping.
2. **Given** a file missing `pipeline.max_cycles`, **When** the loader runs,
   **Then** it raises a settings error naming the vault and the key — those
   two keys are the only hard-required ones in the whole schema.
3. **Given** a file that is not valid YAML, or no file at all, **When** the
   loader runs, **Then** it raises a settings error rather than a parser
   traceback.

### User Story 2 — A budget of zero means unlimited, not "spend nothing" (Priority: P1)

1. **Given** `pipeline.budget_usd: 0`, **When** the budget ladder resolves,
   **Then** the run is uncapped — identical to the key being absent or null.
2. **Given** a `--max-usd` flag and a settings value, **When** both are
   present, **Then** the flag wins; the same precedence applies to
   `--max-cycles` over `pipeline.max_cycles` over the deprecated
   `cycles.initial_max`/`update_max` over the built-in default.
3. **Given** a deprecated `cycles.*` key alongside the canonical one,
   **When** the ladder resolves, **Then** the canonical value wins and the
   deprecation is warned exactly once.

### User Story 3 — Per-stage executor settings compose, they do not clobber (Priority: P1)

1. **Given** a `default_executor` and a `stages.<name>` block, **When** an
   executor is resolved for that stage, **Then** scalar keys (`runtime`,
   `model`, `timeout_s`) take the stage's value if present and the default's
   otherwise.
2. **Given** `args` on both blocks, **When** the executor is resolved,
   **Then** the two lists are **concatenated**, default first — a global
   sandbox flag and a per-stage reasoning-effort flag coexist.
3. **Given** an `args` value that is not a list, **When** the executor is
   resolved, **Then** the error names which of the two blocks is malformed.

### User Story 4 — Invalid values are rejected at load, not at use (Priority: P2)

1. **Given** `stages.<name>.tier` naming no key of `tiers:`, **When** the
   file loads, **Then** it raises, naming the stage and the known tiers
   (issue #13; a value that can only be the 1.0.1 complexity label warns
   instead, for one release — FR-013).
2. **Given** any stage carrying **both** `model` and a `tier` only the new
   vocabulary defines, **When** the file loads, **Then** it raises naming
   the stage — the two are mutually exclusive.
3. **Given** a consensus quorum that is even or below 1, **When** the file
   loads, **Then** it raises: a quorum must be odd.
4. **Given** `archived: "yes-please"`, **When** the file loads, **Then** it
   raises rather than coercing — a typo must not silently un-freeze a
   finished vault.

### Edge Cases

- A settings file that fails full validation still yields `output_dir` and
  the deprecated cycle limits, through a deliberate raw-YAML fallback.
- The runner reads `timeout_s` with its own tolerant raw parse, so a file
  that fails validation cannot stop it bounding a subprocess (`075` FR-025).
- `OLLAMA_BASE_URL` overrides `default_executor.base_url` — the one place an
  environment variable sits above the file.

---

## Requirements

### Functional Requirements

**File and profiles**

- **FR-001**: A vault's settings file MUST be `<vault>/settings.yaml`. There
  is no search path and no environment override for its location.
- **FR-002**: The repo MUST ship one profile per supported runtime
  (`settings.yaml` for claude, plus `codex`, `cursor`, `cursor-claude`,
  `ollama`, `opencode`), differing only in `default_executor`, the matching
  per-stage `model`/`args`, and the metered-token limit where applicable.
  Exactly one profile is copied into a vault at generation time; profiles are
  never stacked or merged with each other.
- **FR-003**: Every shipped profile MUST declare a live cycle dollar cap and
  a live wall-clock cap, and MUST carry no unparsed `budget:` block.

**Loading and precedence**

- **FR-004**: `pipeline.max_cycles` and `pipeline.budget_usd` are the only
  required keys. Every other block MUST default on absence.
- **FR-005**: A missing file, unreadable file or YAML parse error MUST raise
  a single settings-error type carrying the vault path and, where known, the
  offending key.
- **FR-006**: Unrecognised top-level keys MUST be preserved in `extras`
  rather than rejected — a vault written for a newer framework must still
  load. They MUST also be reported (FR-022).
- **FR-007**: The resolved settings object MUST be immutable.
- **FR-008**: Executor resolution precedence MUST be
  `stages.<stage>` > `default_executor` > built-in default for scalars, and
  **additive** (default ++ stage) for `args` — unless the stage sets
  `inherit_args: false`, in which case the stage's `args` are the whole list
  (issue #15: appending cannot take a permission away, and codex refuses a
  second `--sandbox`). `env` is a scalar: the stage's mapping replaces the
  default's.
- **FR-009**: The cycle-limit ladder MUST be, highest first: the CLI flag,
  `pipeline.max_cycles` / `pipeline.budget_usd`, the deprecated
  `cycles.initial_max` / `cycles.update_max` (honoured with a warning only
  when the canonical key is absent), the built-in default.
- **FR-010**: A dollar value of `0` on **any** rung of that ladder MUST mean
  **unlimited**, identical to absent or null. A negative flag MUST be a usage
  error; a negative settings value MUST be ignored.
- **FR-010a** *(issue #33)*: `pipeline.max_cycles: 0` MUST mean **no lifetime
  cycle ceiling**, and every reader of the resolved ceiling (the cycle loop,
  `validate_cycle` Condition A, the plan quota and CG-005, `./vault status`,
  the run report, GA-004, `--estimate-only`) MUST treat it so. A negative or
  non-integer `max_cycles` MUST be refused; `--max-cycles 0` stays a usage
  error. The optional `pipeline.cycles_per_run: N` (integer ≥1) MUST cap a run
  that starts at cycle *k* at cycle *k+N−1* — the settings spelling of
  `--more-cycles N` — or at a finite lifetime ceiling if that is lower;
  `--more-cycles` / `--max-cycles` MUST win over it.
- **FR-011**: `limits.budget_usd` MUST be accepted as a deprecated alias for
  `limits.cycle_budget_usd`, migrating only when the canonical key is absent
  and warning once per process.

**Validation**

- **FR-012**: `stages.<name>.tier`, on every stage, names a key in the
  top-level `tiers:` map — the stage's model tier — and MUST be mutually
  exclusive with `model`; both set MUST raise naming the stage. An unknown
  tier name MUST raise at load, naming the stage and the known tiers.
  *(Issue #13: before this the key was a `basic|standard|expert` complexity
  label on every stage but the two D7 ones.)*
- **FR-013**: For one release, a value that can only be the 1.0.1 label — any of `basic|normal|flagship|standard|expert` in a file with no
  `tiers:` block, `basic|standard|expert` beside `model`, or
  `standard`/`expert` undefined in `tiers:` — MUST warn (`FutureWarning`, naming the settings file and the
  stage) and select no model; the release after refuses them. A tier that
  resolves through a back-filled default while the stage's runtime is not
  `claude` MUST warn, naming the file.
- **FR-014**: `tiers` MUST always resolve `basic`, `normal` and `flagship`,
  back-filling any the vault did not override.
- **FR-015**: `stages.source_extraction.consensus.tiers.<label>` MUST be a
  positive **odd** integer.
- **FR-016**: `archived` MUST be a literal YAML boolean; any other value MUST
  raise, and MUST NOT be treated as archiving the vault.
- **FR-017**: `credibility.unknown_domain_policy` MUST be `warn` or `reject`
  (case-insensitive); each `trusted_domains` entry MUST carry both `domain`
  and `tier`.
- **FR-018**: `cycle_yield.max_ceiling` MUST be `>= cycle_yield.min_floor`;
  factor-map values MUST be `> 0`, and an unknown cadence/coverage bucket
  MUST warn and be dropped rather than raise.
- **FR-019**: `default_agent` MUST be one of `claude`, `codex`,
  `cursor-agent`, `ollama`, `opencode`, and the rejection message MUST list
  the valid set.
- **FR-020**: Validation MUST fail fast on the first violation with an
  actionable message; there is no aggregate validation report.

**Honesty**

- **FR-021**: A key that no code reads MUST NOT ship in a profile. The dead
  keys enumerated in § Known divergences D1 are the current debt, not a
  licence to add more.

**Unknown keys (issue #8)**

- **FR-022**: Every key in the file that is neither a typed field, a
  documented pass-through (§ Key entities — the "Reader" column names who
  consumes it) nor on the inert register (D1) MUST be reported on load as an
  `UnknownSettingsKeyWarning` naming its dotted path and, when one is close
  (`difflib.get_close_matches`), the closest known sibling. Each key is
  reported once per process. Map-valued sections whose keys the operator
  picks — stage names under `stages`, labels under `tiers`, the entries of
  `limits.tier_thresholds` / `limits.estimator_calibration` — are never
  reported, only the keys beneath a stage.
- **FR-023**: `strict_settings: true` MUST make a run refuse to start (exit
  `2`, the "operator must fix it" code of `077` FR-012) while any such key is
  present. One check, `strict_settings_refusal`, backs every refusal; it runs
  before any side effect, reading the flag from the raw file so it holds when
  the rest of the file fails validation. Scope: `orchestrator.run_cycles`
  (every `generate` run and `generate --resume`), `cycle`, `pipeline`
  `full|collect|extract|scout|resume|finish`, and `ask` (issue #15; its ask
  dispatch precedes the `cycle` an escalation runs). Not covered: `cycle
  --estimate-only`, `pipeline status|prune-runs`, and the shim arms that
  invoke an agent directly rather than through those entry points
  (`./vault ask` without `--escalate`, `./vault write`). A non-boolean value MUST raise at load. Default `false`.
- **FR-024**: Every shipped profile, and every tracked fixture settings file
  that the loader can read, MUST load with zero unknown-key reports.
  `examples/settings.yml` is exempt (D3).
- **FR-025**: Unknown keys MUST be computed before validation, so a typo in a
  required key (`pipeline.max_cylces`) is reported with the key meant, and the
  resulting `SettingsError` names it too.

### Key entities — the schema

Types are YAML types. "Reader" is the subsystem that consumes the key;
"—" means nothing reads it (see D1).

**Top level**

| Key | Type | Default | Reader |
| --- | --- | --- | --- |
| `schema_version` | int | `1` | — |
| `archived` | bool | `false` | orchestrator (refuses new cycles) |
| `tiers.{basic,normal,flagship}` | str | `claude-haiku-4-5` / `claude-sonnet-5` / `claude-opus-5` | D7 tier resolution |
| `modules` | list[str] | `[]` | source-module discovery, module refresh |
| `output_dir` | str \| null | `null` | vault destination (`~`, `$VAR` expanded; relative resolves against the settings file's own directory) |
| `local_providers` | list[str] | `[ollama, local, lmstudio, llamacpp]` | opencode cost classifier |
| `default_agent` | enum | `claude` | cycle runner |
| `approval_gates` | list[str] | `[]` | approval gate (`061`) |
| `strict_settings` | bool | `false` | orchestrator — refuses a run over an unknown key (FR-023) |
| `vault_commit.{enabled,push_on_complete,auto_merge}` | bool/enum/bool | `true`/`auto`/`true` | `vault_commit` (`050`/`072`) |
| `vault_commit.retention.{keep_last,max_age_days}` | int \| null | `5` / `90` | branch retention |
| `default_executor` | map | see below | dispatcher (`078`); not part of `VaultSettings` |
| `cycles.{initial_max,update_max}` | int | unset | deprecated cycle limits (FR-009) |
| `source_manager.decay_after_n_cycles` | int | `3` | digest only — the source manager reads `stages.source_manager` (U1) |
| `dimensions` | list[str] | `[]` | — |
| `communication.mode` | enum | `cli` | — |

**`default_executor` and `stages.<name>`** (the same shape; stage wins, `args` concatenates unless `inherit_args: false`)

| Key | Type | Default | Reader |
| --- | --- | --- | --- |
| `type` | `cli` \| `script` \| `api` | `cli` | dispatch (`078`) |
| `runtime` | str | `claude` | dispatch |
| `model` | str | `sonnet` | dispatch |
| `args` | list[str] | `[]` | dispatch (additive) |
| `inherit_args` (stages only) | bool | `true` | dispatch: `false` drops `default_executor.args` for this stage (issue #15) |
| `env` | map[str, str] | `{}` | dispatch: extra variables for the runtime process, e.g. `OPENCODE_PERMISSION` for the read-only `ask` stage (issue #15) |
| `agent` | str | — | dispatch, opencode only: `--agent <name>` |
| `retry` | int | `1` | declared in every profile; `agent_call.py` does not read it today (the `ask` stage sets `0`) |
| `timeout_s` | int | `3600` | dispatch, and the runner's own raw read (`075` FR-025) |
| `skill` | str \| null | `null` | prompt rendering |
| `base_url` / `api_path` | str | `http://127.0.0.1:11434` / `/v1/chat/completions` | HTTP dispatch only |
| `script_path` | str | unset | dispatch, `type: script` only |
| `variant` / `agent` | str | unset | dispatch, opencode runtime only |
| `enabled` (stages only) | bool | `true` (`false` for `source_extraction`) | the stage |
| `tier` (stages only) | key of `tiers:` \| null | `null` (unset) | the stage's model, resolved through `tiers:` at dispatch; exclusive with `model` |

**`pipeline`**

| Key | Type | Default | Reader |
| --- | --- | --- | --- |
| `max_cycles` | int ≥0 | **required** (`0` = no lifetime ceiling) | budget ladder |
| `cycles_per_run` | int ≥1 | unset = no per-run cap | budget ladder (folded into the ceiling like `--more-cycles`) |
| `budget_usd` | float ≥0 | **required** (`0` = unlimited) | budget ladder |
| `backlog_promotion_threshold` | int ≥1 | `2` | topic harvest |
| `coverage_growth` | float ≥1.0 | `1.0` | coverage growth (`pipeline/coverage.py`) |
| `coverage_growth_cap` | int ≥1 | `10` | coverage growth — ceiling per category per round |
| `required_source_failure_threshold` | int | unset | source signals — legacy spelling of `source_failure_thresholds.required_quorum_loss` |
| `note_writer_batch_size` | int | `6` | batch scheduler (clamped 3–10) |
| `max_batches_per_cycle` | int | `10` | batch scheduler |
| `source_failure_thresholds.required_quorum_loss` | int | `2` | source signals |
| `source_failure_thresholds.enrichment_max_failures` | int | `0` | — (D1: no code reads it) |
| `gates.abstraction_enabled` | bool | `true` | SG-003 / CG-003 kill switch |
| `gates.sg_003_abstraction_warn_pct` / `…fail_pct` | int % | `20` / `60` | SG-003 |
| `gates.*` (the other seven) | int | see profile | — (D1) |
| `queryability_score_regression_pp` | int | `5` | — |

**`limits`**

| Key | Type | Default | Reader |
| --- | --- | --- | --- |
| `cycle_budget_usd` | float >0 | unset = opt out | budget guard |
| `budget_usd` | float >0 | — | deprecated alias for the above |
| `codex_token_budget` | int ≥1 | unset | budget guard (metered runtimes only) |
| `cycle_wallclock_budget_minutes` | int ≥1 | unset | budget guard |
| `cycle_budget_warn_at` | float (0,1] | `0.80` | soft warning |
| `tier_thresholds` | map[str,float] | `{}` | tier cost warnings |
| `estimator_calibration` | map[str,float] | `{claude: 1.15, others: 1.0}` | cost estimator |

**`cycle_yield`, `stubs`, `refresh_sources`, `reports`, `credibility`**

| Key | Type | Default | Reader |
| --- | --- | --- | --- |
| `cycle_yield.base_notes_per_cycle` | int ≥1 | `5` | CG-001 yield target |
| `cycle_yield.cadence_factor.{daily,weekly,biweekly,monthly}` | float >0 | `1.0/3.0/5.0/8.0` | CG-001 |
| `cycle_yield.coverage_factor.{coverage_below_50pct,coverage_50_to_80pct,coverage_above_80pct}` | float >0 | `1.5/1.0/0.5` | CG-001 |
| `cycle_yield.min_floor` / `max_ceiling` | int ≥1 | `1` / `50` | CG-001 clamp |
| `stubs.anchor_link_threshold` | int ≥1 | `5` | stub detection |
| `refresh_sources.collectors` | list[str] | `[]` | `refresh-sources` verb |
| `refresh_sources.timeout_s` | int ≥1 | `600` | `refresh-sources` verb |
| `reports.mirror.target` | str \| null | `null` | report delivery |
| `reports.smtp.{enabled,recipient,server,port,from}` | bool/str/str/int/str | `false`/null/null/`587`/null | report delivery (credentials come from `RF_SMTP_USER`/`RF_SMTP_PASSWORD`) |
| `credibility.unknown_domain_policy` | `warn` \| `reject` | `warn` | credibility catalog |
| `credibility.trusted_domains[]` | list of `{domain, tier}` | `[]` | credibility catalog |

**Stage-specific extras**

| Key | Type | Default | Reader |
| --- | --- | --- | --- |
| `stages.source_manager.decay_after_n_cycles` | int | `3` | source manager |
| `stages.source_extraction.signal_retention_days` | int | `30` | source bridge |
| `stages.topic_propose.{enabled,max_proposals,max_degree,relation_types,on_missing_out_of_scope}` | bool/int/int/list/enum | `false`/`10`/`2`/6-item enum/`skip` | topic propose |

## Success Criteria

- **SC-001**: A profile cannot ship a config block nothing parses — a guard
  asserts every shipped profile's `extras` carries no `budget` key.
- **SC-002**: Zero is unambiguously unlimited on every rung of the dollar
  ladder, and the provenance of the resolved value is recorded.
- **SC-003**: Every validation rejection names the key and the vault.

---

## Acceptance coverage

| User story | Evidence |
| --- | --- |
| US1 — A vault loads its settings, or is told exactly why not | `tests/pipeline/test_settings_loader.py::test_load_well_formed`, `tests/pipeline/test_settings_loader.py::test_missing_required_max_cycles` |
| US2 — A budget of zero means unlimited | `tests/cli/test_budget_usd_zero_is_unlimited.py::test_zero_budget_usd_resolves_to_uncapped`, `tests/cli/test_budget_resolver.py::test_flag_beats_pipeline_max_cycles_and_default` |
| US3 — Per-stage executor settings compose | `tests/scripts/test_agent_call.py::test_default_and_stage_args_merge_additively`, `tests/scripts/test_agent_call.py::test_stage_override_wins_over_default` |
| US4 — Invalid values are rejected at load | `tests/pipeline/test_settings_loader.py::test_invalid_tier_value`, `tests/pipeline/test_archived_vault.py::test_non_boolean_archived_is_rejected` |

### Testing Requirements

| FR group | Pinned by |
| --- | --- |
| FR-001…FR-003 (file, profiles) | `tests/pipeline/test_shipped_profiles_enforce_budget.py`, `tests/pipeline/test_settings_templates.py` |
| FR-004…FR-007 (loading) | `tests/pipeline/test_settings_loader.py` |
| FR-008 (executor precedence) | `tests/scripts/test_agent_call.py::TestResolveExecutor` |
| FR-009…FR-011 (budget ladder) | `tests/cli/test_budget_resolver.py`, `tests/cli/test_budget_usd_zero_is_unlimited.py`, `tests/pipeline/test_cycle_budget_settings.py`, `tests/pipeline/test_settings.py::test_budget_usd_alias_migrates_to_cycle_budget_usd` |
| FR-010a (cycle ceiling `0`, `cycles_per_run`) | `tests/cli/test_cycle_limits_settings.py`, `tests/pipeline/test_cycle_limits_orchestrator.py`, `tests/scripts/test_validate_cycle.py::test_condition_a_never_trips_without_a_lifetime_ceiling` |
| FR-012…FR-014 (tiers) | `tests/pipeline/test_tier_resolution.py`, `tests/pipeline/test_default_tier_resolution.py` |
| FR-015 (odd quorum) | `tests/pipeline/test_settings_loader.py::test_consensus_n_values_must_be_odd` |
| FR-016 (`archived`) | `tests/pipeline/test_archived_vault.py` |
| FR-017 (credibility) | `tests/pipeline/test_settings_credibility.py` |
| FR-018 (cycle yield) | `tests/pipeline/test_cg001_yield_model.py` |
| FR-019 (`default_agent`) | `tests/pipeline/test_settings_cursor.py`, `tests/pipeline/test_settings_ollama.py` |
| FR-021 (no dead config in profiles) | `tests/pipeline/test_shipped_profiles_enforce_budget.py::test_profile_has_no_unparsed_budget_block` |
| FR-022…FR-025 (unknown keys, strict mode) | `tests/pipeline/test_settings_unknown_keys.py`, `tests/cli/test_strict_settings_verbs.py` |

---

## Known divergences

- **D1 — Dead config still ships.** These keys are present in shipped
  profiles and read by nothing: `schema_version`; `communication.mode`; the
  whole top-level `model_router` block (distinct from the live
  `stages.model_router` *stage*); the whole `research_modes` block, the
  largest by line count; `exit_invariant`; the top-level `dimensions` list;
  seven of the nine `pipeline.gates.*` thresholds (only `abstraction_enabled`
  and the two `sg_003_*` percentages are live — the gates themselves run, but
  take their thresholds from the plan quota, the yield model or a hardcoded
  value); `pipeline.queryability_score_regression_pp`;
  `stages.source_manager.auto_promote_discovered`;
  `stages.verifier.on_timeout`; `stages.verifier.output_filename`;
  `stages.topic_propose.auto_promote`. Sharpest instance:
  `gates.cg_007_max_orphan_link_pct: 15` in every profile against a hardcoded
  `0.2` default in the gate, whose only production call site passes zeros.
  Found while building the unknown-key register (#8), also read by nothing:
  `citation.*`, `commands.*`, `cycles.max_consecutive_verifier_rejections`,
  `pipeline.source_failure_thresholds.enrichment_max_failures` (an earlier
  revision of the table listed a reader for it; there is none), `skill` / `on_fail` / `retry` under
  `default_executor` and `stages.*` (they are `ExecutorConfig` fields of the
  spec-file loader; the vault dispatcher never reads them), and
  `pipeline.gates.cg_003_{warn,fail}_pct` (quality fixtures only). All of D1 sits
  in `_INERT_PATHS` in `pipeline/settings.py`: tolerated without a report so the
  shipped files stay quiet, never suggested as a correction. T001 deletes a
  line there with each key it removes.
- **D2 — "Spec wins over file" is documented and unimplemented.** The file's
  own header says every value can be overridden by `research.spec.md`'s
  `settings:` block, and a typed mirror of that block exists — but no merge
  reads it for executor resolution. Treat the header as aspirational.
- **D3 — `examples/settings.yml` still carries the `budget:` block #230
  removed.** The guard that removed it globs `settings*.yaml` at the repo
  root, which matches neither that filename nor that directory — so the one
  file a human is most likely to read while learning the schema is the one
  that still shows dead config.
- **D4 — Three independent readers.** The typed loader, the dispatcher's raw
  parse, and the runner's raw `timeout_s` parse can disagree; the source
  manager additionally checks a legacy `_pipeline/settings.yaml` first.
- **D5 — The D7 tier resolver has no confirmed production caller.** It is
  fully specified, validated and unit-tested, but no non-test call site was
  found. *(Resolved by issue #13: `tier` has one meaning — a key in `tiers:`
  — on every stage, and the dispatcher resolves it, so the loader's resolver
  is the validation twin rather than the only resolver.)*
- **D6 — Newer blocks were never back-ported to the alternate profiles.**
  `archived`, `tiers`, `modules`, `cycle_yield`, `stubs`, `reports` and the
  D7 stages appear only in `settings.yaml`. Every one defaults, so this is
  not a bug — but the profiles are no longer the same schema by inspection.

- **U1 — Two readers disagree on where `source_manager` lives.**
  `source_manager.py` reads `stages.source_manager.decay_after_n_cycles`;
  `pipeline/digest/sections.py::_decay_threshold` reads a top-level
  `source_manager.decay_after_n_cycles`. Both spellings are accepted so neither
  is reported, but a value set at the top level only moves the digest.
- **U2 — Stage names are not checked.** `stages.verifer:` is a new stage as far
  as the register can tell. Only the keys *beneath* a stage are checked.

## Assumptions

- One profile per vault; profiles are chosen at generation time and not
  merged.
- YAML 1.1 semantics (PyYAML). Bare `on`/`off`/`yes`/`no` are booleans.
