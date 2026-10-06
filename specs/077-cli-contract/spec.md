# Feature Specification: The CLI contract — verbs, flags and exit codes

**Status**: shipped(2026-09-07, commit 6935644) — a *record* of the command
surface as it is, written from the parser and the implementations at that
commit. It adds no scope. Divergences are filed under § Known divergences.

**Spec**: `077-cli-contract` · **Owns as of this spec**: the `./vault` verb
list ARCHITECTURE.md § 14 only partially carries · **Epic**: #217 ·
**Issue**: #275, #248, #244

---

## Why this spec exists

There are two command surfaces — the `research-framework` argparse tree and
the generated vault's `./vault` shell shim — and neither has ever been
specified. ARCHITECTURE.md § 14 lists 2 of 21 argparse verbs and 13 of 18
shim verbs, and presents one verb as shipped that cannot run. The
constitution states a three-value exit-code model that a third of the verbs
do not follow, with no table anywhere saying which. Issue #248 asked for that
table; issue #244 is one instance of what its absence costs.

A reader with no code access must be able to reproduce this surface, argument
for argument and exit code for exit code.

## Scope

**In scope**: every verb on both surfaces, their flags, their exit codes,
their output contracts, and the gap between the constitutional model and what
each verb actually returns.

**Out of scope**: what each verb *does* — that belongs to the verb's own
spec. `pipeline` is specified in `075-pipeline-runner`.

---

## User Scenarios & Testing

### User Story 1 — The verb list is fixed and discoverable (Priority: P1)

1. **Given** the installed package, **When** the parser is built, **Then** it
   registers exactly the 21 documented subcommands, in a fixed order, and
   every one carries a callable handler.
2. **Given** `--help`, **When** it is printed, **Then** the output is stable
   against a committed golden — a verb cannot be added, renamed or reordered
   without the change being visible in review.
3. **Given** a generated vault, **When** `./vault` is run with no arguments
   or `help`, **Then** it prints its own verb list and exits 0.

### User Story 2 — A non-zero exit always says why (Priority: P1)

1. **Given** any verb that returns non-zero, **When** the process ends,
   **Then** the reason has been written to stderr or logged at ERROR.
2. **Given** a verb that returns non-zero having written neither, **When**
   the process ends, **Then** the CLI appends a canned hint naming the file
   that holds the record.
3. **Given** a verb that fails because of the operator's own arguments,
   **When** it exits, **Then** the code is 2, distinguishable from a
   structural "this cycle is finished" 1.

### User Story 3 — Output format is chosen, never inferred (Priority: P2)

1. **Given** `--json`, **When** the verb runs off a TTY, **Then** the output
   is JSON.
2. **Given** no `--json`, **When** the verb runs on a TTY, **Then** the
   output is human text.
3. **Given** the `pipeline` verb group, **When** stdout is redirected,
   **Then** the log level still defaults to `info`, unlike every other verb,
   because every scheduled invocation is redirected.

### Edge Cases

- An unknown `./vault` verb prints an error and exits 1 (not 2 — see D3).
- `./vault update` re-runs the installer and propagates *its* exit code,
  which is outside the 0/1/2 model entirely.
- `./vault sync` has no `exit` statement at all and can never report failure.
- `research-framework quality-fixture-init` always returns 2; it is a
  declared stub, not a bug.

---

## Requirements

### Functional Requirements

**Entry points**

- **FR-001**: The package MUST expose one console script,
  `research-framework`, and MUST be equivalently runnable as
  `python -m research_framework.cli`.
- **FR-002**: A generated vault MUST carry an executable `./vault` shim,
  rendered from a template at scaffold time and re-renderable by the
  `regenerate-shim` verb.
- **FR-003**: The shim MUST refuse to overwrite a shim a user has customised
  unless `--force` is given.

**The argparse surface — 21 verbs**

- **FR-004**: The parser MUST register exactly these subcommands:
  `generate`, `coverage`, `validate`, `reindex`, `check-skills`, `cycle`,
  `inventory`, `onboard`, `regenerate-agents`, `prune`, `parse-spec`,
  `pipeline`, `quality-baseline-update`, `quality-fixture-init`,
  `refresh-sources`, `regenerate-shim`, `status`, `digest`, `acceptance`,
  `wikilinks`, `re-grade`.
- **FR-005**: A global `--log-level {debug,info,warning,error}` MUST be
  registered before the subparsers so every verb inherits it. Its default
  MUST resolve as: explicit flag, else the verb's own declared default, else
  TTY-aware (`info` on a TTY, `warning` when redirected).
- **FR-006**: `pipeline` MUST be the only verb declaring its own log-level
  default, `info`.
- **FR-007**: stdout MUST be line-buffered for every verb.

**The `./vault` surface — 18 verbs**

- **FR-008**: The shim MUST dispatch these verbs: `research`, `health`,
  `audit`, `ask`, `write`, `refresh-sources`, `regenerate-shim`, `status`,
  `digest`, `acceptance`, `wikilinks`, `re-grade` (alias `regrade`),
  `update`, `coverage`, `reindex`, `sync`, `maintain`, `help`.
- **FR-009**: `./vault research` MUST forward to
  `generate --spec <vault>/research.spec.md --output <vault> --resume`,
  passing through any extra flags.
- **FR-010**: Every shim verb that maps 1:1 onto an argparse verb MUST
  forward `--vault <vault>` plus the caller's remaining arguments unchanged.
- **FR-011**: A shim verb whose backing script is absent MUST say so and exit
  non-zero, never appear to succeed.

**Exit codes**

- **FR-012**: The model is: `0` pass/continue, `1` fail/terminate (structural
  — this unit of work is over, move on), `2` abort (an error the operator
  must fix before proceeding).
- **FR-013**: Every verb MUST return 2 for a missing, non-existent or
  non-directory `--vault`.
- **FR-014**: A verb that finds a substantive negative result (unmet
  coverage, a failing acceptance gate, a partial collector run) MUST return 1
  — not 0 with a message.
- **FR-015**: A verb that cannot proceed because of its inputs (bad flag
  combination, unloadable spec, unknown name, refused overwrite) MUST return
  2.
- **FR-016**: `--legacy-cycle-runner` MUST fail rather than silently doing
  something else; the resulting `NotImplementedError` MUST surface as 2.
- **FR-017**: Any verb returning non-zero MUST have written the reason to
  stderr or logged it at ERROR; the CLI MUST backstop a silent non-zero exit
  with a hint naming where the record is.
- **FR-018**: Divergences from FR-012 MUST be recorded in this spec's table
  rather than left to be discovered. The current set is § Known divergences
  D1–D5.

**Output**

- **FR-019**: `--json` MUST exist on `pipeline status`, `refresh-sources`,
  `regenerate-shim`, `status`, `acceptance`, `wikilinks`, `re-grade`, and
  MUST never be inferred from TTY-ness. `inventory` MUST use
  `--format {json,text}` instead, defaulting by TTY.
- **FR-020**: `--dry-run` MUST exist on every verb that mutates a vault:
  `generate`, `refresh-sources`, `regenerate-shim`, `re-grade`,
  `quality-baseline-update`. `wikilinks` inverts the polarity — it is
  report-only by default and mutates only under `--fix`.

### Key entities — the verb tables

**`research-framework <verb>`**

| Verb | Purpose | Key flags | Exit codes |
| --- | --- | --- | --- |
| `generate` | Bootstrap or resume a vault | `--spec` (required unless `--regenerate-plan-only`), `--output`, `--dry-run`, `--resume`, `--cycle`, `--max-cycles`, `--max-usd`, `--skip-gate`, `--prepopulate`, `--settings`, `--regenerate-plan-only`, `--force-budget`, `--approve`, `--approve-all`, `--reject` | 0 dry-run/complete; 1 resume precondition unmet, budget/approval refusal, source-exhausted; 2 usage, archived vault, spec invalid, phase-1 gate failed, dirty tree |
| `coverage` | Coverage-target status | `--vault` (required) | 0 met; 1 unmet; 2 bad vault |
| `validate` | Run the validator suite | `--vault` | max() of five sub-scripts, each 0/1/2 |
| `reindex` | Rebuild index files | `--vault` | 0; 2 import failure |
| `check-skills` | Repair vault SKILL.md files | `--vault` | 0 clean or restored; 2 unrecoverable |
| `cycle` | One research cycle | `--vault`, `--cycle` (both required), `--budget-cap` (default 10.0), `--target-topics` | passthrough 0/1/2; 2 unloadable spec with `--target-topics` |
| `inventory` | Describe a vault | positional path, `--format`, `--out` | 0; 2 not a vault |
| `onboard` | Four-step vault onboarding | positional path, `--draft-only`, `--no-git` | 0 complete; 1 stopped awaiting spec review (normal); 2 aborted |
| `regenerate-agents` | Re-render agent definitions | positional path, `--agent` (repeatable), `--force` | 0; 1 declined prompt; 2 setup error |
| `prune` | Remove generated artefacts | positional path, `--keep` (repeatable), `--yes`, `--force` | 0 (including a declined prompt — see D4); 2 not a vault / dirty tree |
| `parse-spec` | Parse `research.spec.md` | positional path, optional spec path | 0; 2 not a vault, no spec, invalid spec |
| `pipeline` | The weekly runner (`075`) | positional vault + command, `--budget-cap` (always refused), `--quiet`, `--json` | 0/1 from the phases; 2 usage |
| `quality-baseline-update` | Re-baseline a quality fixture | positional fixture, `--reason`, `--actor`, `--dry-run`, `--yes` | 0; 1 declined; 2 usage/harness failure |
| `quality-fixture-init` | (stub) | — | always 2 |
| `refresh-sources` | Re-run collectors | `--vault`, `--json`, `--dry-run`, `--only` (repeatable), `-v/--verbose` | 0 all ok; 1 partial failure; 2 no collectors, unknown `--only`, all failed |
| `regenerate-shim` | Re-render `./vault` | `--vault`, `--json`, `--dry-run`, `--force` | 0; 2 missing spec, customised shim without `--force` |
| `status` | Live vault status | `--vault`, `--json` | 2 bad vault; otherwise always 0 (deliberate fail-open) |
| `digest` | Cross-cycle roll-up | `--vault`, one of `--since`/`--last-week`/`--last-month`/`--last-quarter`, `--output` | 0; 1 bad or future `--since`; 2 bad vault |
| `acceptance` | Acceptance gates | `--vault`, `--json`, `--strict` | 0; 1 any FAIL (or WARN under `--strict`); 2 bad vault |
| `wikilinks` | Wikilink sweep | `--vault`, `--fix`, `--json` | 2 bad vault; otherwise always 0 |
| `re-grade` | Re-grade quarantined notes | `--vault`, `--dry-run`, `--note` (repeatable), `--json` | 2 bad vault; otherwise always 0 |

**`./vault <verb>`**

| Verb | Routes to | Notes |
| --- | --- | --- |
| `research` | `generate --resume` | always forces `--resume` |
| `health`, `audit` | vault-local scripts | |
| `ask` | interactive `claude` in the vault, then auto-commit | exits 1 if `claude` is absent |
| `write "<topic>"` | a document generator | **not shipped** — see D2 |
| `refresh-sources`, `regenerate-shim`, `status`, `digest`, `acceptance`, `wikilinks`, `re-grade`/`regrade`, `coverage`, `reindex` | the identically-named argparse verb | `--vault` injected |
| `update` | a bespoke upgrade flow | exit code is the installer's or the health check's — outside the model (D1) |
| `sync` | best-effort commit + push | cannot report failure (D5) |
| `maintain` | a vault-local maintenance script | honestly gated: exits 1 with "requires spec 023" when absent |
| `help` | usage text | 0 |

## Success Criteria

- **SC-001**: A reader can enumerate every verb and flag from this document
  without opening the parser.
- **SC-002**: Every exit code a verb can return is written down, including
  the ones that break the constitutional model.
- **SC-003**: No verb can be added, removed or reordered without a visible
  diff against the committed help golden.

---

## Acceptance coverage

| User story | Evidence |
| --- | --- |
| US1 — The verb list is fixed and discoverable | `tests/cli/test_build_parser_stable.py::test_argparse_topology_unchanged`, `tests/cli/test_build_parser_stable.py::test_help_byte_identical` |
| US2 — A non-zero exit always says why | `tests/cli/test_nonsilent_exit_guard.py`, `tests/cli/test_fr6_exit_reason_visibility.py::test_resume_precondition_rejection_goes_to_stderr` |
| US3 — Output format is chosen, never inferred | `tests/cli/test_pipeline.py::test_status_default_output_is_text_not_json_regardless_of_tty`, `tests/cli/test_pipeline_verb_log_level.py::test_other_verbs_keep_the_tty_aware_default` |

### Testing Requirements

| FR group | Pinned by |
| --- | --- |
| FR-001, FR-004 (entry points, verb set) | `tests/cli/test_build_parser_stable.py` |
| FR-002, FR-003 (shim) | `tests/cli/test_regenerate_shim.py`, `tests/generator/test_render_vault_shim.py` |
| FR-005, FR-006 (log level) | `tests/cli/test_pipeline_verb_log_level.py` |
| FR-007 (line buffering) | `tests/cli/test_force_line_buffered_stdio.py` |
| FR-009, FR-010 (shim forwarding) | `tests/generator/test_render_vault_shim.py::test_shim_research_forwards_split_argv_and_spec_path` |
| FR-012…FR-015 (exit codes) | `tests/cli/test_refresh_sources.py`, `tests/cli/test_acceptance_gates.py`, `tests/cli/test_onboard.py`, `tests/cli/test_prune.py`, `tests/cli/test_inventory.py`, `tests/cli/test_regenerate_agents.py` |
| FR-016 (`--legacy-cycle-runner`) | `tests/test_cli.py::TestGenerateSettingsFlag::test_legacy_alias_exits_2_with_upgrade_hint` |
| FR-017 (non-silent exit) | `tests/cli/test_nonsilent_exit_guard.py`, `tests/cli/test_fr6_exit_reason_visibility.py` |
| FR-019, FR-020 (output, dry-run) | `tests/cli/test_wikilinks_verb.py::test_dry_run_writes_nothing`, `tests/cli/test_regrade.py::test_dry_run_touches_nothing`, `tests/quality/unit/test_baseline_update_cli.py::test_dry_run_never_writes` |

---

## Known divergences

- **D1 — `./vault update` is outside the exit-code model.** It ends with the
  re-run installer's own exit code, or the health check's, neither of which
  this contract controls.
- **D2 — `./vault write "<topic>"` cannot run.** The shim execs a document
  generator that does not exist anywhere in the tree; the original spec said
  it would ship as a stub with a helpful error and that stub was never
  merged. README and ARCHITECTURE both document it as shipped, unqualified.
  This is the one affirmatively wrong claim in the CLI documentation, as
  opposed to an omission.
- **D3 — Unknown-verb handling disagrees across the two surfaces.** The shim
  exits 1 for an unknown verb; argparse exits 2 for an unknown subcommand.
  Both are "the operator typed something wrong", which the model calls 2.
- **D4 — Declining a confirmation prompt means different things.** `prune`
  returns 0, `regenerate-agents` returns 1, for the identical interaction.
- **D5 — Four verbs cannot signal a finding through their exit code.**
  `status` is deliberately fail-open (it returns 0 even when it could not
  read its own state); `wikilinks` and `re-grade` return 0 however much they
  found; `./vault sync` has no `exit` at all. In each case the signal exists
  only in `--json` or on stdout.
- **D6 — `digest` collapses two different errors into one.** A malformed
  `--since` string (an operator error, class 2) and a valid future date both
  raise the same exception and both exit 1 with the message
  "No cycles in scope" — which is also what a legitimately empty range
  prints, on stdout, with exit 0.
- **D7 — An orphaned second CLI exists.** A `schema acknowledge-drift`
  subcommand is implemented and unit-tested but is registered in no parser
  and reachable from neither entry point. ARCHITECTURE lists it under
  "Planned additions" with a flag-shaped interface that does not match what
  was built.
- **D8 — ARCHITECTURE § 14 is not the verb list.** It shows 2 of 21 argparse
  verbs, omits five `./vault` verbs (`refresh-sources`, `regenerate-shim`,
  `acceptance`, `wikilinks`, `re-grade`), and mentions neither the exit-code
  model nor `--json` nor `--log-level`. This spec is now the owning document;
  ARCHITECTURE should point here.

## Assumptions

- The vault's virtualenv is present and the package installed into it; the
  shim resolves its interpreter from there.
- One CLI invocation per vault at a time.
