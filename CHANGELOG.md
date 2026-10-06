# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-10-06

**First public release.** This repository was recreated from the framework's
private development repository so it could be published without personal data
or references to the author's workplace, and the public version line starts
again at 1.0.0. The code is the private line's 1.2.0 plus everything listed in
this block; the private commit history is not carried over, and its versions
(0.1.0 – 1.2.0) are kept below under
[Before the public release](#before-the-public-release).

### Repository

- Real vault names, people, organisations and workplace references in specs,
  docs, tests and fixtures are replaced with neutral examples (`acme-corp`,
  reserved `.example` hosts); session handoffs, sprint notes and post-mortems
  are removed.
- Version numbers restart: the roadmap's next tiers are v1.1.0 and v1.2.0, and
  "private X.Y.Z" names a version from the private line.
- The CLI no longer looks for a legacy spec file name; a vault's spec is
  `<vault-name>-spec.md` or `research.spec.md`.

### Added

- **A pipeline run leaves a receipt: `_pipeline/runs/<run_id>/`.** On
  2026-09-01 the weekly runner failed `verify` on seven of eight live vaults
  and left, per vault, a seven-line `pipeline-state.json` with `errors: []`.
  #318/#327/#305 fixed *what* the runner records; this fixes *where*. One
  directory per run now holds `run.json` (the machine receipt), `run-report.md`
  (its rendering for a human), `logs/<stage>.log`,
  `prompts/<stage>.rendered.md`, `agent-calls/<stage>.json` and
  `verify-report.json` — the prompts and logs were flat files under
  `_pipeline/` that the next run overwrote, which is why the prompt behind a
  bad answer was always already gone.

  **Every dispatch now asks for a cost sidecar** (`--cost-sidecar` under the
  run directory), so a weekly run over eight vaults finally has a
  framework-owned record of what it spent. `--output-file` is deliberately
  *not* requested: it is written only on exit 0, so it would be absent in
  exactly the runs an operator needs to read. A sidecar that was **requested**
  and did not arrive is `null` and a `WARNING`, never `0` — a run reporting
  `$0.00` for a phase that dispatched an agent is worse than one that says it
  does not know, because the first is a number an operator adds up across
  eight vaults. Totals computed with any sidecar missing are labelled a lower
  bound wherever they are rendered.

  `run.json` is a **pure function of the state file plus what is on disk**, so
  rewriting it on every phase close loses nothing; a test asserts the
  derivation is deterministic. Its schema is
  `tests/contracts/run-receipt-1.0.schema.json`, validated against a receipt
  the real runner wrote (the way #326 wired the state schema) and versioned
  from the first byte under ADR-0013, so #247's fleet view can refuse a shape
  it does not know. `run_id` gains a `-2`, `-3`, … suffix on collision: it was
  minute-granular and two `full` runs in one minute silently overwrote each
  other's state, and nothing noticed because there was nothing to collide
  with. `resume` and `finish` write into the run the state file names, and
  reconstruct a missing directory rather than refusing — a state file written
  before this shipped is a run to recover, not a run to reject. A re-driven
  stage suffixes rather than overwrites, because the first pass's record is
  usually the reason for the second.

  `status` gains `run_dir`, `receipt`, per-phase `cost_usd` / `cost_source`
  and `cost_total_usd`, present and `null` where unknown so a consumer reads
  one shape. A failed phase's `ERROR` line names the run directory as well as
  the state file, and the spec-070 FR6 backstop stops naming a `run-report.md`
  the runner never wrote. `pipeline <vault> prune-runs --keep N --older-than
  DAYS [--dry-run]` is the explicit ask for retention — nothing is pruned
  automatically, because the record of a bad night is what an operator goes
  looking for weeks later; the run the state file names always survives.
  (spec 080 T001–T005/T007/T008; #221)

- **The report phase is told what the run did, instead of guessing from
  `git log`.** On 2026-09-01 one vault's weekly report claimed **45 notes added
  for a run whose research phase created zero**, and printed "No context tree
  available" twice. The agent was never given the run's own facts, so it
  reconstructed a narrative from the only thing it could see — the repository's
  history — and that narrative was about a different week. The rendered report
  prompt now carries, from `run.json`: the run id and its directory, every
  phase's status, the sources `collect` could not reach, the scout queue size,
  the research phase's created/updated counts, the verify verdict with its
  content/tooling split and its three most frequent flag families, and the
  run's total cost. When the research phase created nothing, the context says
  so **in a sentence, before any instruction to summarise additions** — so a
  report that lists new notes contradicts the input printed above it. This is
  an enforcement boundary, not a rewrite: the prose stays the agent's, the
  facts are handed to it, the same line spec 079 D4 draws for the citation
  block. The report agent definition's `reads:` also stops naming
  `_pipeline/logs/verify-*.md`, a Markdown summary nothing has ever written,
  which is one reason its "Vault health" section reported "Not available" on
  runs that verified fine. (spec 080 T006/T007; #224)

- **`--budget-cap` on `pipeline` verbs stays refused, and now says why**
  (spec 080 T009). The receipt made pipeline spend *recorded*, which was the
  precondition — but a cap has to be checked *before* a dispatch and the
  sidecar exists only *after* one, so enforcing against a running total would
  stop the run at the first phase that overshot, having already paid for it.
  `limits.cycle_budget_usd` is enforced at `agent_call.py`, the surface that
  knows a call is about to happen. The refusal message says that instead of
  the now-false "no pipeline phase records per-call cost yet".

- **Specs 080, 081 and 082 — the v1.3.0 "runs unattended" order is now
  specified.** `specs/080-run-receipt/` (#221, #224) puts every artifact a
  run produces under one `_pipeline/runs/<run_id>/`, adds a cost sidecar to
  every runner dispatch and feeds the report phase the run's own counts; it
  absorbs `078-dispatch-surface` T005 (decided: sidecars, yes) and records
  `075-pipeline-runner` T005 as satisfied by #326. `specs/081-triage-gate/`
  (#334) is the gate #305 deferred when it closed #240: `_pipeline/
  triage.json`, `pipeline triage --approve/--defer/--top N/--all`, `resume`
  refusing an empty approval set. `specs/082-spec-driven-verify/` (#226)
  owns the wider verify contract (`required_sections`, `coverage_targets`)
  as its own spec rather than a `079-note-format` amendment — 079 is a
  shipped record and adds no scope. All three are `planned`; indexed in
  `specs/README.md`.
- **ADR-0013 — cross-repo envelopes are additive within a major and carry
  `schema_version`.** Answers spec 036's Q1 once, for every payload a
  sibling repo reads. `tests/contracts/vault-ask-1.0.schema.json` is
  written under it ahead of any producer, pinned by
  `tests/contracts/test_vault_ask_envelope_schema.py` (18 cases: the FR-003
  keys and bounds, a `1.x` payload with an unknown field validates, a `2.0`
  payload is refused).

- **`settings.ollama.yaml` ships in the wheel and the install bundle.** The
  Ollama profile was committed in 1.0.0rc5 (spec 047 v1) and named by the
  settings loader's own error message as a valid `default_agent`, but
  neither `pyproject.toml`'s wheel force-include table nor `build.sh`'s
  bundle copy list carried it, so no release ever did — only a source
  checkout had the file, and `_assets.asset_path` falls back to the source
  tree in dev mode, so every existing test was green about a profile the
  release did not ship. Packaged per the 2026-09-08 owner decision (D11)
  that a local / self-hosted model path is always supported;
  `tests/build/test_settings_profiles_packaged.py` now pins every committed
  `settings*.yaml` into both surfaces and fails when the two lists
  disagree. `dist-templates/README.md`'s "two profiles" table lists all six
  with what each can do.

- **Research-branch retention: cap-N and max-age, applied at session start
  and after every landing.** Spec 072 FR5 keeps a run's `research/<ts>`
  branch after a constrained landing so a bad landing is one `git reset`
  away — and left the count unbounded (14 branches across seven vaults by
  2026-08-30; #307). The framework now applies a policy of its own, read from
  `settings.yaml::vault_commit.retention`: `keep_last` (default 5) and
  `max_age_days` (default 90), each a ceiling in its own right — a landed
  branch is pruned when it falls outside the newest-N window *or* its tip is
  older than the age limit; `null` switches a rule off, both `null` disables
  automatic pruning. `vault_commit.begin_run` (the start of every vault
  session, resumed or fresh, after the dirty-main hard stop) and
  `vault_commit.complete_run` (once a run has landed and the checkout is
  back on the base branch — never on the rc=2 abort or the constrained
  `auto_merge: false` path, which stay on the branch by design) each run it
  and report what they pruned in one INFO line. A clean run under
  `auto_merge: false` does return to main, with an EMPTY pointer commit
  that carries the same `**Branch:**` line while the content lives only on
  the branch — the classifier reads each matching commit's body and treats
  a pointer (`branch_retention.POINTER_RETAINED_MARKER`, the trailer
  `_emit_pointer_commit` writes) as *not* landed, so a review-gate branch
  is never a candidate at any policy (found in review; pinned by
  `TestAgainstRealVaultCommit::test_real_auto_merge_off_clean_run_is_never_a_candidate`). `scripts/prune_research_branches.py
  <vault> prune` stays the manual verb, gains `--max-age-days`, takes its
  defaults from the vault's settings, and names the reason (`cap`, `age`,
  `cap+age`) per branch; `list` shows each branch's age. Two invariants are
  unchanged and pinned: an unlanded branch is never a candidate at any age or
  count, and "landed" means the landing commit's `**Branch:**` marker is on
  the base branch — which surfaced one new rule: a pruned branch's name is
  never reallocated to a later run in the same minute, because the stale
  marker would otherwise classify the new, in-progress run as landed
  (`vault_commit._branch_name_taken`). Every completed run (rc=0, rc=1 with
  or without commits) leaves the checkout on the base branch, so an open
  research branch is only ever a record — that premise is now a test class
  of its own. (#307; tests: `tests/pipeline/test_branch_retention.py`,
  `tests/pipeline/test_vault_commit.py::TestEveryCompletedRunReturnsToMain`,
  `::TestRetentionAtSessionStart`, `::TestRetentionAfterLanding`,
  `::TestPrunedNamesAreNeverReused`,
  `tests/scripts/test_prune_research_branches.py`)
- **`research-framework export --claims` / `./vault export --claims` — the
  vault→consumer distillation as a versioned contract.** Until now a
  downstream consumer (`consumer_pipeline`'s `pipeline/vault_import.py` was the
  working prototype) walked `data_vault/**/*.md` from outside the framework,
  re-implemented the frontmatter conventions by hand and guessed which files
  were plumbing — so every consumer paid that cost again and a note-format
  change broke all of them without the payload saying so (F9). The new verb
  emits one claim record per qualifying note (`id`, `note_path`, `title`,
  `claim` = the summary, `note_type` + whether the spec declares it, `tags`,
  `verifier_status`, `coverage_category`, `template_version`, dates,
  `support_count`, and per-citation `sources[]` with the declared AND the
  effective credibility — resolved exactly as the verifier resolves it:
  explicit → source default → catalog, COI-capped, off-field downgraded).
  Plumbing is skipped by the framework's own rules and counted per reason
  (`scaffold`: the index trio, `_templates/`, any `_`-prefixed path;
  `exempt`: `verifier_status: exempt` and alias redirect stubs, the
  verifier's `_is_exempt`; `malformed`; `no_frontmatter`; `missing_fields`).
  Quarantined notes are excluded unless `--include-quarantined`, and then
  flagged. The envelope follows ADR-0013: `schema_version` (`"1.0"`) carried
  as a safeguard, append-only within `1.x`, a new schema file per major;
  `tests/contracts/claims-export-1.0.schema.json` is the contract and is
  validated against REAL producer output, with the 1.x pattern, an
  unknown-field payload and a `2.0` refusal each pinned. The verb is
  read-only (byte-for-byte pinned), deterministic (claims sorted by `id`),
  writes only the envelope to stdout (`| jq` works) or `--out FILE`, and
  degrades rather than fails: a missing `spec-parse.json` or a note the codec
  refuses becomes a `warnings[]` line, never a lost export. Exit 2 for a
  missing vault, a directory without a corpus, or no export kind selected.
  (#189; tests: `tests/vault/test_claims_export.py`,
  `tests/contracts/test_claims_export_schema.py`,
  `tests/cli/test_export_verb.py`,
  `tests/generator/test_render_vault_shim.py::test_shim_export_forwards_split_argv`)
- **`applicability:` — a note states where its own claim holds.** A claim that
  is true only in one market, field, audience, product
  version or time window had nowhere to say so, so every consumer that needed
  the distinction kept its own table of which notes apply where — a mapping
  that lives away from the claim, is invisible to the person reading the note,
  and has to be maintained per consumer. The field is optional and free-form
  (`market: EU`, `audience: beginners`; `all` for a dimension the
  claim does not narrow), documented in the generated `CLAUDE.md` and in the
  note-writer's constraints. Deliberately NOT added to the note template's
  frontmatter slots: those are the SG-005 required-key contract, and a field
  that is mandatory-but-usually-empty is worse than one written when it earns
  its place.

### Fixed

- **`scripts/validate_cycle.py` refuses a `--budget-cap` of `nan` or a
  negative.** `nan` fails every comparison that makes Condition C bite
  (`cost >= nan` is never true, and `_cap_is_enforceable(nan)` is false),
  so `--budget-cap nan` ran the cycle uncapped with exit 0 and reported
  "$1000.00 / $nan budget"; a negative did the same. The script now exits 2
  naming the flag, as the budget resolver does for `--max-usd`. `inf` is
  still accepted: it reads as "no cap" honestly, and the pipeline passes it
  when settings say `budget_usd: .inf`, which the settings loader accepts.
  (regression test:
  `tests/scripts/test_validate_cycle_zero_budget_is_unlimited.py::test_a_nan_or_negative_cap_is_refused`)

- **`scripts/validate_vault.py` aborts on a folder with no `data_vault/`.**
  `validate()` returned no findings when `<vault>/data_vault/` did not
  exist, and `main()` printed "all checks passed" with exit 0 — a pass over
  zero notes for any wrong but existing path (the vault's parent,
  `data_vault/` itself). It now raises `FileNotFoundError`, which `main()`
  already reports on stderr with exit 2, as `check_template_compliance.py`
  and `check_acronym_links.py` do. The `validate` verb returns that 2; the
  cycle's SG-004 gate maps any non-duplicate non-zero exit to WARN. As with
  those two scripts, a vault whose corpus folder is not named `data_vault/`
  was passing unvalidated and now gets exit 2.
  (regression test:
  `tests/scripts/test_validate_vault.py::test_a_folder_with_no_data_vault_exits_2`)

- **The `cycle` verb marks a cycle that did not complete, so `--resume`
  returns to it.** The cycle runner writes a cycle's quality report on every
  exit, and `--resume` anchors past the highest report without a spec-070
  F10 abort marker. `run_cycles` writes that marker on rc=2 and when the
  cycle leaves by exception; the single `cycle` verb
  calls `run_single_cycle` itself and wrote it on neither path, so a cycle
  run that way and aborted, interrupted, paused or crashed read as completed
  and a later `--resume` skipped it. The verb now marks it on both paths
  (re-raising the exception) and clears the marker when the cycle
  completes, as `run_cycles` does.
  (regression tests:
  `tests/pipeline/test_aborted_cycle_not_completed.py::test_the_cycle_verb_marks_a_cycle_that_did_not_complete`,
  `::test_the_cycle_verb_clears_the_marker_when_the_cycle_completes`)

- **`generate --resume` refuses `--settings`, `--prepopulate` and
  `--skip-gate` instead of ignoring them.** The three shape Phase 1 — the
  settings baked into the vault, the files copied into its `_pipeline/`,
  the pytest gate — and `--resume` skips Phase 1: `_cmd_generate`
  dispatched to `_resume` before reading them, so `./vault research
  --settings other.yaml` resumed on the vault's own settings without a word.
  Like the resume-only flags outside `--resume` (issue #286), they now exit 2
  and are named on stderr.
  (regression test:
  `tests/cli/test_generate_resume_only_flags.py::test_fresh_only_flag_with_resume_exits_2_without_resuming`)

- **`digest` reads "today" off the clock it buckets cycles by.** A cycle
  falls in a digest range by its UTC finish date
  (`scope._cycle_in_range`), but the range was anchored on the local
  `date.today()` (`cli/digest.py` and `scope.resolve_last_period`'s
  default). Wherever the local date differed from UTC's the window moved by
  a day: behind UTC, a cycle that had just finished was outside
  `--last-week` and `--since <today's UTC date>` was refused as a future
  date; ahead of UTC, the oldest day of the window was dropped. Both now
  use the UTC date.
  (regression test:
  `tests/cli/test_digest_exit_codes.py::test_the_range_ends_on_the_utc_date_the_cycles_are_bucketed_by`)

- **`reindex` refuses a vault path that does not exist.** The indexer
  creates the corpus folder it indexes, parents included, so a mistyped
  `--vault` came back as a new directory holding `data_vault/` and the
  index files, with exit 0. The verb now exits 2 and names the path on
  stderr, creating nothing, as `coverage` and `validate` already do.
  (regression test:
  `tests/test_cli.py::test_reindex_on_a_missing_vault_creates_nothing_and_exits_2`)

- **`refresh-sources` no longer exits 0 when every collector is missing.**
  A collector named in `refresh_sources.collectors` (or by `--only`) whose
  script is absent is skipped as `missing`; when all of them were, nothing
  ran and the verb still reported success. It now exits 2 — the "no
  collectors" code spec 077 gives this verb — and names the missing scripts
  on stderr.
  (regression test:
  `tests/cli/test_refresh_sources.py::test_refresh_sources_exit_2_when_every_collector_is_missing`)

- **`refresh-sources --dry-run` writes nothing.** The installed-module
  preflight sweep ran before the dry-run check, so a dry run executed every
  module's preflight script and recorded each probe in
  `_pipeline/preflight.json` — against the verb's own contract ("list
  collectors that would run; do not execute"). A dry run now skips the
  sweep; its `--json` output carries `"preflight": []`.
  (regression test:
  `tests/cli/test_refresh_sources.py::test_refresh_sources_dry_run_writes_nothing`)

- **`acceptance`, `coverage`, `onboard` and `refresh-sources` say on stderr
  why they exit non-zero.** Spec 077 FR-017 counts stderr and ERROR records
  as "said why"; these four verbs gave their reason on stdout only (or, under
  `refresh-sources --json`/`--dry-run`, not at all), so each legitimate exit —
  a failing acceptance gate, unmet coverage targets, an onboarding abort or
  stop for spec review, a partial or empty collector run — came out with the
  "framework bug" apology attached, and an unattended run that redirects
  stdout lost the reason. Each now writes it to stderr: the failing (or,
  under `--strict`, warning) gate ids, the unmet categories with their
  counts, the step's abort message, the failed collectors or the fact that
  there was none to run. The reports on stdout are unchanged.
  `test_exit_code_contract` only sees literal `return N`, so it could not
  catch this.
  (regression tests:
  `tests/cli/test_fr6_exit_reason_visibility.py::test_coverage_with_unmet_targets_says_why_on_stderr`,
  `::test_acceptance_with_a_failing_gate_says_why_on_stderr`,
  `::test_onboard_abort_says_why_on_stderr`,
  `::test_onboard_stop_for_spec_review_says_why_on_stderr`,
  `::test_refresh_sources_partial_failure_says_why_on_stderr_under_json`,
  `::test_refresh_sources_with_no_collectors_says_why_on_stderr`)

- **A NaN metric fails the quality gate instead of passing it.**
  `_metric_verdict` places a metric on the 5%/15% band with `<`, `<=`, `>`
  and `>=`, and the zero-baseline check with `cur_val > 0`. Every comparison
  with NaN is false, so a metric that came out as NaN, in the current run or
  in the committed baseline, fell through to `pass`, and the gate passed on a
  reading that is not a number. A NaN on either side now fails that metric.
  (regression test:
  `tests/quality/unit/test_zero_baseline_regression.py::test_a_nan_reading_fails_the_gate`)

- **A `sources.db` without its tables no longer crashes the digest or the
  layer-1 report.** The Source Quality Drift section and the
  strongest-signals ranking query `sources` and `source_cycles` with no
  `except` around the queries; only a missing or locked database was
  handled. A database that exists but has no tables yet (or is not SQLite)
  raised `no such table: sources` and no digest or report was written. The
  drift section is now omitted with a footer note naming the error, as for a
  locked database, and the ranking runs without referencing deltas, as when
  there is no `sources.db`.
  (regression test:
  `tests/pipeline/test_digest.py::test_drift_db_without_its_tables_omits_section`)

- **One malformed cycle file no longer stops the Phase 3 report.**
  `generate_report` counted `len(data.get("notes_created", []))`, which
  raises when an agent wrote `null` or a number there, and caught only
  `JSONDecodeError` around the read, so a file that is not UTF-8 or cannot be
  read escaped too. Either way the report was not written. A count that is
  not a list now reads as 0, and a file that cannot be read or decoded is
  skipped like malformed JSON.
  (regression test:
  `tests/pipeline/test_reporter_cost.py::test_phase1_report_survives_a_malformed_cycle_file`)

- **The RSS source-bridge module reads a feed in the encoding its XML prolog
  declares.** `modules/rss/extractor.py` decoded every response as UTF-8 with
  replacement before the XML parse, and ElementTree ignores the prolog of a
  document handed to it as `str`, so a feed starting
  `<?xml version="1.0" encoding="ISO-8859-1"?>` came out with U+FFFD in place
  of every accented letter. It now applies the collectors' rule: the HTTP
  charset when it decodes the body, then the prolog's encoding, then UTF-8.
  The module carries its own copy, since modules are standard library only.
  (regression test:
  `tests/source_bridge/test_rss_module.py::test_fetch_decodes_a_feed_in_the_encoding_its_prolog_declares`)

- **The collectors' fetch helper caps a response body at 32 MiB.**
  `_fetch.get` read the whole body with `resp.read()`, so a misbehaving
  server, or a link that turned out to be a large download, streamed into
  memory without limit. It now reads at most 32 MiB plus one byte; a longer
  body raises `ResponseTooLarge` (a `URLError`), which the RSS collector
  already reports as a failed fetch, and it is not retried. Feeds and article
  pages are kilobytes to a few megabytes.
  (regression test:
  `tests/collectors/test_rss.py::test_fetch_fails_a_body_over_the_size_cap_without_retrying`)

- **The scout merge drops an excluded topic whatever form its name takes.**
  `merge_scout_topics` checked a scout row against the plan's exclusions by
  its `proposed_filename`, or by its title when it had none, lowercased but
  otherwise verbatim. An exclusion is a file stem in either naming convention
  or a phrase from the spec's `out_of_scope`, so the same topic often reached
  the check in another form: a title-only row "Vendor Pricing" survived
  `out-of-scope: vendor-pricing`, and `customer-pii.md` survived the phrase
  `out-of-scope: customer pii`. The rendered plan then promised research the
  spec author had ruled out. Both sides are now compared as slugs (lowercase,
  each run of non-word characters one `-`).
  (regression test:
  `tests/pipeline/test_merge_scout_topics.py::test_merge_matches_exclusions_by_slug_not_verbatim`)

- **`vault_health.py --apply` writes accented frontmatter values as they
  were.** The wikilink fixer re-dumped each note's frontmatter without
  `allow_unicode`, so every note it touched had its non-ASCII text escaped:
  `title: Café` came back as `title: "Caf\xE9"`, and summaries in Portuguese
  or French turned into `\x` and `\u` sequences. It now dumps with
  `allow_unicode=True`, as `fix_wikilinks.py` does.
  (regression test:
  `tests/scripts/test_vault_health.py::TestApplyFixes::test_apply_writes_non_ascii_values_as_they_were`)

- **`fix_acronym_links.py` links the occurrence the checker flagged.** The
  checker skips code fences, inline code, URLs and `(KA)` definitions when it
  looks for the first bare acronym; the fixer confirmed a bare one existed,
  then wikilinked the first raw occurrence in the body. In the note that
  defines KA that was the heading: `# Known Acronym (KA)` became
  `# Known Acronym ([[KA]])`, which satisfied the checker, so `--apply` exited
  0 with the flagged prose still bare. With no heading the next candidate was
  a URL (`https://example.com/[[KA]]/intro`) or code. The excluded regions are
  now masked at their own length, and the link goes in at the masked match's
  offset.
  (regression test:
  `tests/scripts/test_fix_acronym_links.py::test_apply_links_the_occurrence_the_checker_flagged`)

- **The remaining frontmatter readers end the frontmatter at the closing
  `---` line.** Eight call sites still split on the first `---` substring, so
  a `---` inside a line ended the frontmatter there. A note whose
  `source_urls` held a slug URL such as `kafka---a-guide` lost every key below
  it: SG-005 failed a complete note for missing keys, and `vault_metrics.py`,
  `check_intent_drift.py` and `check_code_source_coverage.py` read it without
  them. A `settings.yaml` that opens with YAML's `---` document marker ended at
  its first `# -----` comment rule (the bundled file has dozens), so
  `vault_commit.enabled: false`, the push policy and the retention rules read
  as unset and fell back to the defaults. The preflight spec loader dropped
  `owner` and every key below a dashed value. The package readers now use
  `vault.frontmatter.split_frontmatter`; the standalone scripts carry the same
  line-based split.
  (regression test:
  `tests/vault/test_note_readers_end_frontmatter_at_a_line.py::test_dashes_inside_a_line_do_not_hide_the_keys_below_them`)

- **Stopping `topic_propose.py` stops the agent it dispatched.** The script
  started `agent_call.py` with a plain `subprocess.run`. A SIGTERM killed the
  script on the spot (Python's default, no `finally`) and left the wrapper
  and its agent running; an interrupt made `subprocess.run` SIGKILL the
  wrapper, which a wrapper cannot forward to the agent it runs in a session
  of its own. The wrapper is now started in its own session
  (`popen_session`) and terminated on every path (`terminate_process_tree`:
  SIGTERM to its group, which `agent_call.py` forwards, then SIGKILL), and
  the script run as a process turns SIGTERM into the unwind Ctrl+C already
  was before dying of that signal. Not covered here: Step 7b runs the script
  through `_run_script` without a log file, whose plain `subprocess.run`
  SIGKILLs the script when the pipeline itself is interrupted — no handler
  in the script can run then.
  (regression test:
  `tests/scripts/test_topic_propose.py::test_stopping_the_script_stops_the_wrapper_and_the_agent`)

- **Merging the scout's topics no longer erases the plan's exclusions and
  coverage table.** Step 2.5 of the cycle reads `_pipeline/research-plan.md`
  back with `ResearchPlan.from_markdown`, merges `topics_found.new` and
  writes `to_markdown()` over the file. `from_markdown` returned
  `coverage_state=[]` and `exclusions=[]` ("lossy by design", true while
  nobody rendered a parsed plan), so every cycle with a scout topic handed
  the note-writer a plan whose `## Exclusions` read `- (none)`, whose
  coverage table was empty and whose focus categories all showed
  `(0% filled)` — and the merge itself had no exclusions to check a scout
  topic against, so an already-covered or out-of-scope topic went back to
  the top of the queue. Both sections are now read back as `to_markdown`
  writes them; a section appended after `## Exclusions` and rows that are
  not table data are ignored, as the contract asks.
  (regression tests:
  `tests/pipeline/test_merge_scout_topics.py::test_the_scout_merge_keeps_exclusions_and_coverage_state`,
  `tests/pipeline/test_merge_scout_topics.py::test_a_scout_topic_the_written_plan_excludes_is_not_merged`,
  `tests/pipeline/test_merge_scout_topics.py::test_a_plan_read_back_from_markdown_renders_the_same_file`)

- **The RSS collector reads a feed in the encoding its XML prolog declares.**
  `_fetch.get` decoded every response from the HTTP header's charset alone,
  and as UTF-8 with replacement when the header named none or named one that
  could not decode the body. That happened before the XML parse, and
  ElementTree ignores the prolog of a document handed to it as `str`, so a
  feed starting `<?xml version="1.0" encoding="ISO-8859-1"?>` and served as
  plain `application/xml` reached `_pipeline/raw/rss/` with U+FFFD in place
  of every accented letter — titles, authors and summaries. The HTTP charset
  still comes first when it decodes the body; after it comes the encoding the
  prolog declares, then UTF-8. A declaration the bytes are plainly not in
  (`encoding="utf-16"` written by a serializer onto UTF-8 bytes) is not
  believed.
  (regression tests:
  `tests/collectors/test_rss.py::test_a_latin1_feed_is_collected_without_mojibake`,
  `tests/collectors/test_rss.py::test_fetch_falls_back_to_the_prolog_when_the_header_charset_is_wrong`)

- **The RSS collector no longer records a short article page as a paywall.**
  `_detect_paywall` counted any page with under 200 visible characters as
  paywalled, so a JavaScript shell, a consent wall or a genuinely short post
  was written to `_pipeline/raw/rss/` as "(Paywalled — content not
  available)" with `paywall: true`. The feed's own summary was thrown away,
  and because the written file is what marks an item as seen, the item was
  never looked at again. Page length no longer says anything about a paywall
  (the markers and 401/403 still do): a thin page falls back to the feed
  summary like every other unusable fetch, and to the page's own text when
  the feed carried no summary.
  (regression tests:
  `tests/collectors/test_rss.py::test_a_short_article_page_keeps_the_feed_summary`,
  `tests/collectors/test_rss.py::test_a_short_article_page_without_a_summary_keeps_the_page_text`)

- **The digest lists notes from the corpus folder the vault declares.**
  `digest.sections._notes_in_range` walked `data_vault/` whatever
  `vault.corpus_dir` said, so a vault with its own corpus folder got "No data
  in scope." under Strongest Signals and New Notes by Category. It now
  resolves the folder through `vault.corpus.corpus_dir`, as the ranking step
  beside it already did.
  (regression test:
  `tests/pipeline/test_digest.py::test_notes_are_read_from_the_corpus_folder_the_vault_declares`)

- **CG-006 (word-count compliance) reads the corpus folder the vault declares.**
  The cycle quality report counted each new note's words under `data_vault/`
  whatever `vault.corpus_dir` said. In a vault with its own corpus folder
  nothing was found there, every note of the cycle scored zero words, and
  CG-006 reported FAIL "notes materially below word floor (100%)" for notes
  that were long enough. The count now resolves the corpus folder through
  `vault.corpus.corpus_dir`, as coverage and the indexer do.
  (regression test:
  `tests/pipeline/test_quality_report.py::TestWordCountReadsTheDeclaredCorpus::test_a_vault_with_its_own_corpus_dir_is_not_failed_for_thin_notes`)

- **CG-004 (coverage velocity) no longer fails a cycle over a category that
  was already met.** The cycle quality report scored every coverage category,
  so a finished one — which has no progress left to make — contributed a
  zero delta, the gate takes the minimum, and CG-004 reported FAIL "no
  positive coverage delta versus expected velocity" on every cycle once any
  category had filled, including on a complete vault ("zero while targets
  remain"). The gate now scores the categories that still have a target to
  reach, which is what spec 017 FR-023 describes ("scores 0 on unfilled
  categories"); a category leaves scope only while it is met at both ends of
  the cycle, and a vault with nothing left in scope passes, as CG-001 already
  did. An unfilled category that stood still fails as before.
  (regression tests:
  `tests/pipeline/test_quality_report.py::TestCoverageVelocityScope::test_a_category_that_was_already_met_does_not_fail_the_cycle`,
  `tests/pipeline/test_quality_report.py::TestCoverageVelocityScope::test_a_complete_vault_has_no_velocity_to_fail`,
  `tests/pipeline/test_quality_report.py::TestCoverageVelocityScope::test_an_unfilled_category_that_stood_still_fails`)

- **The digest and the audit report print coverage as a percentage, and stop
  listing met categories as gaps.** A cycle quality report stores
  `coverage_snapshot.<category>.fill_pct` as a fraction, `met / target`
  clamped to 0..1 (spec 017 `cycle-quality-report.schema.json`; CG-005 and
  `status` read it that way). The digest's `coverage_progress` adapter handed
  the fraction to formatters that append `%`, so a half-filled category read
  "0.5%" in Gaps and Coverage Delta, and `detect_gaps` compared the fill with
  the category's target *count*: a fully met category (1.0) was "below
  target" for any target above one note, so every digest listed it as
  stagnant. The adapter now returns a percentage, and stagnant means flat
  below 100%. The digest and reports fixtures carried hand-written percent
  values (`"fill_pct": 50.0`), which is why no test saw it; they are on the
  stored scale now.
  (regression tests:
  `tests/pipeline/test_coverage_digest_integration.py::test_a_met_category_is_not_reported_as_a_gap`,
  `tests/pipeline/test_coverage_digest_integration.py::test_a_flat_unmet_category_is_stagnant_at_its_real_percentage`,
  `tests/pipeline/test_coverage_digest_integration.py::test_coverage_delta_renders_the_stored_fraction_as_a_percentage`,
  `tests/pipeline/test_digest.py::test_coverage_renders_as_percentages_of_the_category_target`)

- **A crashed fixture fails the quality gate, whatever the other fixtures did.**
  `quality.runner.run` exited 2 for a crashed cycle only when *every* fixture
  crashed, and left a partial crash to the metric diff, which books the crash
  as one failed cycle. Against a baseline that already fails that is an
  improvement: `source-poor` is baselined at three failed cycles (SG-002
  aborts each one), so a crash on its first cycle read as `cycles_fail` 3 → 1
  and `build.sh --quality` printed "Verdict: PASS" and built the bundle. Any
  crashed fixture now exits 2 with `HARNESS FAILED: cycle-runner-crash` naming
  it, before a verdict is printed. This replaces the rule spec 022 tasks.md
  T026 recorded ("non-zero only if ALL fixtures crash").
  (regression test:
  `tests/quality/unit/test_harness_cycle_count.py::test_a_crashed_fixture_fails_the_gate_even_when_another_fixture_ran`)

- **Two tests in the default suite no longer run the real `codex` and
  `claude`.** `test_second_dispatch_after_sidecar_exists_uses_suffix_2`
  patched `agent_call.subprocess.run`, which `dispatch()` has not called since
  spec 050 moved it to `Popen`: the mock did nothing and the real `codex exec`
  ran with the test's prompt. `test_cli_regenerate_plan_only_writes_valid_plan`
  ran `research_framework.cli generate --regenerate-plan-only` with the plain
  environment, so the plan narrator dispatched to the real `claude --print`.
  Both pass whatever the CLI answers, so on a machine with those binaries on
  PATH every `pytest -m "not e2e"` made two live LLM calls unnoticed. Both now
  go through the CLI-binary fake seam (`fake_cli_binary.activate`).
  (test:
  `tests/pipeline/test_quality_report_retry_sidecar.py::test_second_dispatch_after_sidecar_exists_uses_suffix_2`,
  `tests/pipeline/test_quickstart_smoke.py::TestQuickstartCliAndScripts::test_cli_regenerate_plan_only_writes_valid_plan`)

- **`kill <pid>` stops what the pipeline was running, not only the pipeline.**
  The stages the CLI dispatches run in sessions of their own, so a SIGTERM
  sent to the pipeline process reached none of them, and Python's default for
  SIGTERM is to die without running a single `finally`: `agent_call.py` and
  the agent ran on, spending and writing into the vault, with nothing left to
  supervise them. `cli.main` now turns SIGTERM into the unwind Ctrl+C already
  was (the exception is a `KeyboardInterrupt`): every supervised wait
  terminates its child's process group on the way out, and the process then
  dies of SIGTERM as before. A terminated run therefore leaves what an
  interrupted one leaves — a quality report with `exit_status: interrupted`
  and a cleared `in_progress_cycle` — where it used to leave the cycle marked
  as running. A SIGTERM handler somebody else installed is left alone, and
  the disposition is put back when `main` returns.
  (regression test:
  `tests/cli/test_sigterm_stops_the_agent.py::test_terminating_the_cli_stops_the_wrapper_and_the_agent`)

- **A benchmark cell timeout stops the agent, not only the wrapper around it.**
  `benchmark.runner.live_dispatch` had the same `subprocess.run(timeout=…)`
  around `agent_call.py` as the verifier: on a cell timeout the wrapper was
  SIGKILLed and the agent CLI, in a session of its own, kept running and
  spending while the matrix moved on to the next cell. The wrapper is now
  started in its own session and terminated on every path, SIGTERM to its
  process group first (which `agent_call.py` forwards), then SIGKILL.
  (regression test:
  `tests/pipeline/test_agent_call_callers_stop_the_agent.py::test_a_benchmark_cell_timeout_stops_the_agent`)

- **A verifier timeout stops the agent, not only the wrapper around it.**
  `_call_verifier` ran `agent_call.py` with `subprocess.run(timeout=…)`, which
  SIGKILLs the direct child when the time is up. `agent_call.py` runs the
  agent CLI in a session of its own and forwards a SIGTERM to it; a SIGKILL
  cannot be forwarded, so the wrapper died and the agent ran on — spending,
  and writing into a vault the cycle had moved on from. The wrapper is now
  started in its own session and terminated on every path (timeout, Ctrl+C,
  clean exit): SIGTERM to its process group first, then SIGKILL.
  (regression test:
  `tests/pipeline/test_agent_call_callers_stop_the_agent.py::test_a_verifier_timeout_stops_the_agent`)

- **A helper script's exit ends the step, whatever the script left running.**
  `_run_script` read the script's stdout to EOF on the calling thread before
  it looked at the exit status, and terminated the script's process group
  only while the script itself was still running. A helper that exited while
  a process it had started still held its stdout — `agent_call.py` on the
  cycle runner's path included — kept the cycle waiting for that process's
  whole lifetime: the shape of the 2026-05-31 zombie cycle. The output is now
  drained on a reader thread while the caller waits for the exit, the process
  group is terminated on every path (a clean exit included), and a descendant
  that left the group, which cannot be killed, holds the call for 5 s at most.
  (regression tests:
  `tests/pipeline/test_cycle_helpers_tree_kill.py::test_what_the_script_left_running_does_not_hold_the_call`,
  `tests/pipeline/test_cycle_helpers_tree_kill.py::test_a_descendant_that_left_the_group_does_not_hold_the_call`)

- **A test double's pid is never signalled as a process group.**
  `process_tree.popen_session` remembered `proc.pid` as the session's process
  group for whatever `subprocess.Popen` returned. The cycle-runner tests
  replace `Popen` with a double whose `pid` is the plain number 4242, so a
  `terminate_process_tree` on that double sends a real SIGTERM, then a
  SIGKILL, to whichever process group on the machine has that id. No test
  reached it yet: `_run_script` only cleaned up a script that was still
  running, and the double reports that it has exited. The group is now
  remembered only for a real `subprocess.Popen`.
  (regression test:
  `tests/pipeline/test_process_tree.py::TestTheGroupOutlivesItsLeader::test_a_test_doubles_pid_is_never_taken_for_a_process_group`)

- **A probe candidate's filename is looked up as a name, not as a glob
  pattern.** `probes._find_note_file` passed the filename returned by the
  retrieval agent straight to `rglob`. A candidate named `*.md` resolved to
  whichever note came first and was scored as if it were that note; a real
  note with `[` or `?` in its name was never found and scored 0. The name is
  now escaped. (test:
  `tests/pipeline/test_probes.py::test_a_candidate_filename_is_matched_as_a_name_not_as_a_glob`)

- **`dispatch()` returns a claude or cursor-agent answer once, not twice.**
  In stream-json the runtime states its answer in the assistant event and
  again as the terminal event's `result`; both were appended to the returned
  `stdout`. The probe-retrieval stage parses that with a strict `json.loads`,
  got two JSON documents, and silently kept none of the candidates it had paid
  for; the plan narrator wrote its rationale into the cycle plan twice.
  `stdout` is now the terminal event's `result` (what the runtime prints in
  plain `--print` mode), falling back to the streamed text when that is empty.
  (test:
  `tests/scripts/test_agent_call.py::TestDispatchAgentCallResult::test_dispatch_returns_the_answer_once`)

- **A timed-out codex, opencode or script call leaves a sidecar.** On the
  non-streaming path `agent_call.py` returned 2 from a timeout without
  writing the `--cost-sidecar`. Exit 2 with no sidecar is its "runtime
  unavailable" signal, so the benchmark reported a cell that had run for the
  whole timeout as `skipped`, and the pipeline's run receipt counted a missing
  sidecar instead of a failed call. A `status: failed`, `exit_code: 2`,
  `timed_out: true` sidecar is now written, with `cost_source: none` because
  nothing was measured. The streaming runtimes already did. (test:
  `tests/scripts/test_agent_call.py::test_run_cli_records_a_timeout_on_the_non_stream_path`)

- **Pipeline stages on opencode and codex record the cost the runtime
  reported.** `agent_call.py` captured the runtime's stdout only when
  `--output-file` was given, and parsed the cost out of what it had captured.
  The pipeline runner passes `--cost-sidecar` and deliberately no
  `--output-file`, so on that path there was nothing to parse: an opencode
  call that reported `cost: 0.0123` was recorded as an estimate, or as
  `cost_source: none` and $0 when the estimator was unavailable, and the
  dollar cap counted that instead. With a sidecar to fill, stdout is now read
  for the cost and passed through line by line as it arrives, so the stage log
  keeps the stream. (test:
  `tests/scripts/test_agent_call.py::test_run_cli_parses_the_runtime_cost_without_an_output_file`)

- **An extractor killed by a signal is reported as that, and keeps its
  salvaged output.** `Popen` reports death by signal N as `-N`; the
  `bridge.log` footer takes a Unix exit code and `BridgeLogWriter` raises on a
  negative one. An extractor that was OOM-killed or crashed with a signal
  therefore surfaced as `ValueError: exit_code must be >= 0`, which replaced
  the real `ExtractorError`, dropped the partial output that would have been
  quarantined, and left the invocation without a footer line. The footer now
  records `128 + N`, as a shell does. (test:
  `tests/source_bridge/test_extractor_contract.py::test_an_extractor_killed_by_a_signal_is_reported_as_such`)

- **A comma in a source id no longer makes the source unextractable.** The
  `bridge.log` header line is comma-separated, so `BridgeLogWriter` raises on
  a source containing a comma or a newline — after the extractor had already
  been spawned. Source ids are taken from `sources.yaml` (a URL, a path, a
  name), where a comma is ordinary, and both attempts failed with
  `ValueError: source must not contain comma or newline` whenever a cycle was
  writing `bridge.log`. The id is now percent-encoded (`%2C`, `%0A`, `%0D`)
  for the header; the format contract is unchanged. (test:
  `tests/source_bridge/test_extractor_contract.py::test_a_comma_in_the_source_id_does_not_fail_the_extraction`)

- **A source extractor with more than 64 KiB of output no longer deadlocks.**
  `invoke_extractor` polled for the extractor's exit and read its stdout only
  afterwards (stderr too, when no `bridge.log` writer was active). An
  extractor printing a signal larger than the pipe could not exit until it was
  read, so it sat blocked until the wall-clock cap killed it and the source
  was recorded as timed out. Both pipes are now drained on threads while the
  extractor runs. The extractor's process group is also terminated as soon as
  it exits, and on any exception raised after the spawn: a descendant it left
  behind (a `yt-dlp` fork, a headless browser) used to hold the unbounded read
  for its whole lifetime, and an error on the bridge's side left the extractor
  running. A reader that still has no EOF 5 s after the group was terminated
  is abandoned. (test:
  `tests/source_bridge/test_extractor_contract.py::test_extractor_stdout_larger_than_the_pipe_is_read`)

- **The runner's "grandchildren are killed too" test can fail again.** Its
  stand-in grandchild was a `python -c` program with a syntax error (an
  escaped newline that became a real one inside a string literal), so it never
  ran: the marker file it should have been appending to did not exist, and the
  test compared two empty reads. It now ticks, the test asserts that it did,
  and killing only the direct child turns the test red. (test:
  `tests/pipeline/test_runner_agent_timeout.py::TestAHungAgentIsBounded::test_the_agents_grandchildren_are_killed_too`)

- **The pipeline runner cleans up an agent's process group after a clean exit
  too.** `_dispatch_agent` terminated the group on a timeout and on an
  interrupt only. When the dispatcher exited 0, whatever it had left in its
  process group kept running and kept the stdout pipe open: the runner waited
  out its 5 s drain and moved on with those processes still alive. The runner
  prefers the vault's own `scripts/agent_call.py`, which can be a copy from
  before the agent ran in a session of its own. (test:
  `tests/pipeline/test_runner_agent_timeout.py::TestAHungAgentIsBounded::test_what_the_agent_left_running_does_not_outlive_a_clean_exit`)

- **A stage timeout now stops the agent, not only the wrapper around it.**
  `agent_call.py` runs the agent CLI in a session of its own, and had no
  SIGTERM handler. When the runner timed a stage out (or was interrupted with
  Ctrl+C) it SIGTERMed `agent_call.py`'s process group: the wrapper died on
  the spot, without running a single `finally`, and the agent carried on —
  spending, and writing into a vault the pipeline had already moved on from.
  Run as a script, `agent_call.py` now turns SIGTERM into an unwind of its
  main thread, as SIGINT already is: the agent's process group gets a SIGTERM,
  one second, then a SIGKILL — inside the two seconds the pipeline allows
  before it SIGKILLs the wrapper — and the wrapper then dies of the same
  SIGTERM, so its exit status is unchanged. An interrupt that lands in the
  middle of a termination's grace period kills the group at once instead of
  abandoning it. In-process callers (`dispatch()`, `main()`) are not given a
  signal handler. Not covered: a parent that SIGKILLs the wrapper outright
  (`subprocess.run(timeout=…)` in `pipeline/verifier.py` and
  `benchmark/runner.py`) still orphans the agent. (test:
  `tests/scripts/test_agent_call_process_tree.py::TestBeingTerminatedStopsTheAgent`)

- **The verifier gets its verdict back on claude and cursor-agent.**
  `agent_call.py --cost-sidecar … --output-file …` never wrote the output file
  on the two stream-json runtimes: `run()` returned straight out of the
  streaming branch. `pipeline/verifier.py` has passed both flags since #234,
  so with claude as the verifier runtime it read back the empty temp file it
  had created and stamped every note `pending` — one paid call per note, and
  no verdict. The benchmark runner passes the same pair and fell back to the
  wrapper's stdout, where the answer appears twice. The file now receives the
  terminal event's `result` text (what `claude --print` prints in plain mode),
  or the streamed assistant text when that is empty; as on every other
  runtime, only after exit 0. (test:
  `tests/scripts/test_agent_call.py::TestRunDispatch::test_output_file_is_written_on_the_stream_json_path`)

- **The claude and cursor-agent dispatch now times out an agent that has gone
  silent.** Both streaming paths (`dispatch()` and the `--cost-sidecar` path
  of `agent_call.py`) read the agent's stdout on the thread that was also the
  clock: the deadline was looked at when a line arrived, so an agent that
  stopped printing was never timed out and the stage ran for as long as the
  agent did. The same thread wrote the prompt and left stderr unread until the
  agent exited, so an agent that did not read a prompt larger than the pipe,
  or that wrote more than a pipe's worth (64 KiB) of stderr, deadlocked the
  call; and an agent that exited leaving a descendant holding its stdout kept
  the call open for that descendant's lifetime (the 2026-05-31 zombie cycle,
  on the claude path). Both paths now run under the supervisor the
  non-streaming runtimes use: the wait is bounded by the timeout alone, the
  prompt and each pipe have a thread of their own, and the agent's process
  group is gone when the call returns. A stream consumer that raises now ends
  the call at once instead of leaving the agent running. (test:
  `tests/scripts/test_agent_call_process_tree.py::TestStreamingCallsAreSupervised`)

- **`agent_call.py` no longer stays alive after the agent has exited.** The
  non-streaming dispatch armed its watchdog for the timeout only: when the
  agent CLI exited first, nothing was signalled, and `communicate()` then
  waited on stdout for as long as any descendant held the pipe — the agent had
  finished and the wrapper sat there until the stage timeout, or for good with
  no timeout. A descendant that had left the process group made even the
  timeout path hang, because the "force-close the pipes" fallback only ran
  when the direct child survived SIGKILL. The child is now waited on by one
  supervisor: the prompt is fed and each pipe drained on its own thread, the
  process group is terminated when the child exits as well as on timeout, and
  a pipe that stays silent for 2 s after that is abandoned instead of awaited.
  (test:
  `tests/scripts/test_agent_call_process_tree.py::TestTheCallEndsWhenTheAgentDoes`)

- **Terminating an agent's process tree now reaches what the agent spawned
  even after the agent itself is gone.** `terminate_process_tree` (and the
  copy in `scripts/agent_call.py`) returned as soon as the direct child had
  exited: at once when it was already dead, and before the SIGKILL when it
  died on the SIGTERM. A sandbox, MCP server or scraper that ignored SIGTERM,
  or that simply outlived its parent, stayed alive in the group holding the
  stdout pipe — the 2026-05-31 zombie cycle. The lookup that should have found
  the group also failed for exactly that case: `getpgid(pid)` has no answer
  once the leader has exited (macOS refuses even for an unreaped zombie).
  `popen_session` now records the group id it created, the group is signalled
  whether or not its leader is alive, and the SIGKILL is skipped only when the
  group is empty. The self-kill guard (never init's group, never our own)
  applies to the recorded id as well. (test:
  `tests/pipeline/test_process_tree.py::TestTheGroupOutlivesItsLeader`)

- **The acronym redirect-stub pass no longer overwrites real notes or writes
  outside the corpus.** Note `aliases` seed the acronym map unfiltered, and
  the stub is written to `<folder>/<alias>.md`: `aliases: [Kubernetes]` on one
  note replaced an existing `kubernetes.md` with a redirect stub, every cycle,
  and an alias containing `/` or `..` named a path outside the folder.
  `_write_redirect_stub` now refuses (WARNING) when the stub path leaves the
  folder or the file there is not itself an alias stub.
  (regression tests:
  `tests/pipeline/test_acronym_alias_coverage.py::test_an_alias_never_replaces_a_real_note_with_a_stub`,
  `::test_an_alias_with_a_path_separator_writes_no_stub_outside_its_folder`)

- **A verifier verdict with `"violations": null` no longer aborts the
  verifier stage.** Iterating `None` raised `TypeError` out of
  `run_verifier_stage`; the research step logged it as a WARN, so every later
  note in the cycle went unverified and no `cycle-NNN-verifier.json` manifest
  was written. A non-list `violations` is now read as an empty list.
  (regression test:
  `tests/pipeline/test_verifier.py::test_null_violations_do_not_abort_the_stage`)

- **A quarantine move no longer overwrites a note already in quarantine.**
  The out-of-scope sweep renamed onto `_pipeline/quarantine/<name>` with no
  check, so two categories' `overview.md` became one; the verifier-rejected
  sweep's collision name `<stem>-<count>` was never checked either, so a later
  sweep replaced an earlier sweep's copy. For a note new this cycle the
  quarantine copy is the only one. All three moves now take the first free
  `<stem>-<n>` name, as the orphan-note path already did.
  (regression tests:
  `tests/pipeline/test_rejected_note_handling.py::test_a_quarantine_move_never_overwrites_an_earlier_quarantined_note`,
  `::test_out_of_scope_quarantine_keeps_same_named_notes_apart`)

- **Report e-mail delivery verifies the SMTP server's certificate.**
  `reports/smtp.send_report` called `starttls()` with no context, which is
  `ssl._create_stdlib_context()` — no certificate and no hostname check — and
  then sent `RF_SMTP_PASSWORD` over it. It now passes
  `ssl.create_default_context()`; a verification failure is an `OSError` and is
  logged and skipped like any other delivery failure.
  (regression test:
  `tests/pipeline/reports/test_smtp_send.py::test_smtp_starttls_verifies_the_server_certificate`)

- **Phase 3's report no longer crashes on a vault with scout gate records.**
  `reporter.generate_report` reads every `cycle-*-*.json`, which includes the
  list-shaped `cycle-NNN-step-gates.json`; calling `.get` on it raised
  `AttributeError` and ended `generate` / `resume` finalisation. Non-object
  JSON is now skipped.
  (regression test:
  `tests/pipeline/test_reporter_cost.py::test_phase1_report_skips_cycle_json_that_is_not_an_object`)

- **The verifier's frontmatter stamp no longer corrupts a note whose
  frontmatter contains `---`.** `_stamp_frontmatter` split on the first `---`
  substring, so a slug URL such as `kafka---a-practical-guide` in
  `source_urls` ended the frontmatter mid-value: the rest of it was written
  into the body and the note no longer parsed. It runs on every note the
  verifier grades. The closing delimiter is now found as a `---` line.
  (regression test:
  `tests/pipeline/test_atomic_write_migrations.py::test_verifier_stamp_keeps_a_frontmatter_value_containing_dashes`)

- **Branch retention no longer treats an unlanded research branch as landed
  because a same-prefix sibling landed.** `is_branch_landed` matched the
  `**Branch:** research/<ts>` marker as a substring, and it is a prefix of
  `**Branch:** research/<ts>-02` — so a stranded `<ts>` run whose same-minute
  rerun landed as `-02` was classified landed and `branch -D`'d once past the
  retention bounds, with its commits on no other ref. The marker is now matched
  as a whole line.
  (regression test:
  `tests/pipeline/test_branch_retention.py::TestListAndClassify::test_a_landed_suffixed_sibling_does_not_land_its_prefix`)

- **A pipeline phase with no `agent_call.py` to dispatch to no longer exits
  0.** `runner._call_agent` treated a missing script as success, so the
  scout / research / report phase was then judged on whatever artifact was
  already on disk — a previous run's `scout-report.json` made a scout that
  never ran `done`. It is now an `ERROR` naming where it looked, and the phase
  fails.
  (regression test:
  `tests/pipeline/test_runner_phase_artifacts.py::TestAMissingAgentScriptIsNotAnExitZero::test_a_previous_runs_report_does_not_make_an_undispatched_scout_done`)

- **`tests/build/` was never collected — the whole tier ran nowhere.**
  `pyproject.toml`'s `[tool.pytest.ini_options]` set `testpaths` but left
  `norecursedirs` unset, so pytest's default applied — and that default
  excludes any directory named `build`. Six modules and 27 tests were
  dropped from every run without a word: not a skip, not a deselect, just
  absent, so nothing in the gate output said the tier existed. Among them
  `tests/build/test_settings_profiles_packaged.py`, the D11 guard that
  proves `settings.ollama.yaml` reaches both the wheel's force-include table
  and `build.sh`'s bundle — the packaging claim landed green against a test
  that never ran. `norecursedirs` is now written out explicitly (the pytest
  default minus `build`), and `tests/spec/test_test_tree_is_fully_collected.py`
  — kept OUTSIDE `tests/build/`, because a guard inside the directory it
  guards vanishes with it — pins the config, fails closed on an empty
  `tests/build/`, and drives a real `--collect-only` to assert both that
  every test directory is reachable and that the D11 guard is selected by
  `pytest -m "not e2e"`. Added to `scripts/guards/run_all.py`'s battery.
  Collection on this branch moves 3839/3868/29 → 3865/3895/30: +26 fast-loop
  tests from `tests/build/` plus this guard's 4, and the tier's one `e2e`
  module (`tests/build/test_e2e_tier_runs_in_automation.py`), which is why
  the `e2e` count changes for the first time since it was pinned.
  (regression test: `tests/spec/test_test_tree_is_fully_collected.py`)

- **A citation carrying the classification tag the vault's own `CLAUDE.md`
  teaches is no longer graded `IX-citation-malformed`.** The generated
  `CLAUDE.md` tells every note-writer to classify each URL
  `[code]`/`[intent]`/`[domain]`, without saying the tags belong to rendered
  citations rather than to the machine-read `source_urls` frontmatter. Applied
  there, `citation_url` returned `"[domain] https://…"`, whose scheme is not
  http(s), so the verifier rejected the note. It is a coin flip per note and it
  is expensive: a live vault (2026-09-09) lost 8
  of 10 notes across three cycles this way while a sibling vault running the
  same build and the same instruction mostly escaped. Two halves: the template
  now scopes the tags to rendered citations and states the frontmatter contract
  explicitly, and `citation_url` strips a leading `[tag]` and the trailing
  `" — Title, accessed …"` tail before grading, so notes written under the old
  wording verify instead of being quarantined. The gate itself is unchanged — a
  string with no URL in it still grades malformed. (test:
  `tests/vault/test_credibility.py::test_citation_url_strips_tag_and_tail` and
  the three cases beside it)

- **The maintainer `install.sh` installs this repo, not the caller's cwd.** It
  built the venv under its own directory but ran `pip install -e ".[dev]"`
  against the working directory, so `bash ~/src/research-framework/install.sh`
  from anywhere else failed, or editable-installed whatever project the caller
  was standing in. It now `cd`s to its own directory first, as `build.sh`
  does. (regression test:
  `tests/scripts/test_maintainer_install_sh.py::test_pip_install_targets_the_script_directory_not_the_cwd`)

- **CI's shellcheck step passes again.** Root `install.sh` was added to the
  step's file list in #332, but its `source .venv/bin/activate` carried no
  `SC1091` annotation (the end-user installer's does), and shellcheck exits 1
  on that info-level finding. CI runs only on tags since #323, so the first
  run to see it would have been a release. (regression test:
  `tests/scripts/test_ci_config.py::test_shellcheck_step_passes_on_this_tree`,
  which runs the workflow step's own script and skips where shellcheck is
  absent)

- **Re-running the end-user `install.sh` after a failed install re-installs
  instead of reporting success.** The idempotent fast path keyed only on
  `.venv/` and `_pipeline/install_summary.json` existing, and the failure exits
  after venv creation (the version-mismatch sanity check, the check-skills
  preflight) write that summary too. A plain re-run printed "already
  installed", exited 0 and rewrote the record from `failed` to `ok` without
  re-running the step that failed. A summary recording `exit_status: failed`
  now skips the fast path. (regression test:
  `tests/scripts/test_install_idempotency.py::TestIdempotentRerun::test_failed_previous_install_does_not_take_the_fast_path`)

- **The RSS collector no longer reads local files named by a feed item's
  link.** `_article_text` fetched each item's `<link>` with `urlopen`, which
  opens `file://` URLs, so a feed whose item linked to `file:///…` had that
  file's contents written into `_pipeline/raw/rss/` and passed on to extract.
  Article links are feed content, therefore untrusted; anything but http(s)
  now falls back to the feed summary. The operator-configured feed URL is
  unchanged. (regression test:
  `tests/collectors/test_rss.py::test_article_fetch_refuses_non_http_link`)

- **`raw_capture_batch.py` no longer copies local files into `raw_data/`.**
  The http(s) check lived only in `raw_capture.main`; the batch calls
  `capture()` directly with URLs read from agent-written notes, so a
  `source_urls` entry of `file:///…` was copied into `raw_data/` and logged
  `OK`. `capture()` now refuses non-http(s) URLs itself, and the batch records
  them `FAILED`. (regression test:
  `tests/scripts/test_raw_capture.py::TestCapture::test_capture_refuses_non_http_url`)

- **`prune` refuses to delete when its pre-prune snapshot commit fails.** A
  failed snapshot (a vault pre-commit hook, a missing git identity) printed a
  WARNING and deleted anyway; for a gitignored or uncommitted target the
  snapshot is the only copy, so the file was lost while the verb exited 0. It
  now exits 2 with nothing deleted. (regression test:
  `tests/cli/test_prune.py::test_failed_pre_snapshot_aborts_before_deleting`)

- **`prune`'s printed rollback restores what it pruned.** It printed
  `git -C <vault> reset --hard HEAD~2`, the commit *before* the pre-prune
  snapshot. Gitignored targets exist only in the snapshot (it force-adds
  them), so following the hint did not bring them back; under `--force` it
  also discarded the dirty work the snapshot had captured, and when the
  post-prune commit had nothing to record it went one commit too far. It now
  prints the vault path and the snapshot's own SHA. (regression test:
  `tests/cli/test_prune.py::test_printed_rollback_restores_a_gitignored_target`)

- **`research-framework validate` runs its validators again.** Since the CLI
  split it looked for them at `Path(__file__).parents[2] / "scripts"` —
  `src/scripts` in a checkout, `site-packages/scripts` in a wheel — which never
  exists, so every check was skipped as "absent", nothing was printed, and the
  verb exited 0. It now resolves the packaged scripts through `asset_path`,
  exits 2 when the vault is missing or no validator could be found, names the
  failing checks on stderr, and counts a signal-killed validator as a failure.
  A vault that "passed" `validate` before this may now fail it: those checks
  were never run. (regression tests: `tests/cli/test_validate_verb.py`)

- **`re-grade` no longer overwrites a live note with a quarantined one of the
  same name.** The spec-062 "rewrite quarantined note" backlog flow puts a
  fresh `foo.md` into `data_vault/` while the rejected `foo.md` is still in
  quarantine. Their bodies differ, so the F9 duplicate guard did not fire, and
  `_reinstate` atomically replaced the live rewrite with the stale copy —
  contrary to the verb's own contract that live notes are never touched. Such
  a note is now reported as skipped and left in quarantine. (regression test:
  `tests/cli/test_regrade_duplicate_guard.py::test_reinstate_never_overwrites_a_live_note_of_the_same_name`)

- **`scripts/fix_wikilinks.py --apply` deletes only unresolved `related`
  links.** It compared each target verbatim against `_vault_note_stems`, which
  holds lowercased names, so every valid link with a capital letter or a folder
  prefix (`[[Cassandra]]`, `[[01 - Concepts/Cassandra]]`) was removed as
  "unresolved" — on a real vault, most of the `related` graph. The rewrite also
  escaped non-ASCII (`caf\xE9`) and added a blank line after the frontmatter
  each run. The fixer now uses `validate_vault.py`'s own resolution predicate
  (extracted as `_related_target_resolves`, acronym redirects included), dumps
  with `allow_unicode=True` and preserves the body byte for byte. (regression
  test: `tests/scripts/test_fix_wikilinks.py`)

- **verify's auto-fix no longer corrupts BOM-prefixed or non-UTF-8 notes.**
  `_load_note` read with `encoding="utf-8", errors="replace"`. A leading BOM
  hid the frontmatter, so the default-on auto-fix prepended a second
  `---\nrelated: []\n---` block above the real one and pushed title and
  summary into the body; a Latin-1 note had its accented bytes replaced with
  U+FFFD on write-back. It now reads `utf-8-sig` strictly, so a BOM note is
  fixed inside its own frontmatter and an undecodable note is flagged
  `malformed_frontmatter` and left untouched — the read path the canonical
  `parse_frontmatter` adopted in #287. (regression tests:
  `tests/processors/test_verify.py::TestAutoFixPreservesFrontmatter::test_bom_note_gets_the_key_inside_its_own_frontmatter`,
  `…::test_non_utf8_note_is_flagged_not_rewritten`)

- **`pipeline <vault> full --dry-run` no longer runs the real pipeline.**
  `--dry-run` is a `prune-runs` flag; on the run verbs (`full`, `collect`,
  `extract`, `scout`, `resume`, `finish`) it parsed cleanly and was read by
  nothing, so an operator asking for a rehearsal started a real, paid run. It
  is now refused with exit 2 on every subcommand but `prune-runs`. (regression
  test: `tests/cli/test_pipeline.py::TestPipelineDryRunIsPruneRunsOnly`)

- **`archive --after-days`, `preprocess --dedupe-strategy` and `extract
  --workers` take effect.** Each processor resolved its option as
  `cfg.get(key, param)`, and `cfg` always carries the `PROCESSOR_DEFAULTS` key,
  so an explicit argument — from Python or from the CLI flag — was silently
  replaced by the default (90 days, `content_hash`, 5 workers). This is the
  same defect verify's `--no-fix`/`--fail-threshold` had (L-002); the three
  now use verify's precedence, explicit argument > spec config > default, and
  their CLI flags default to `None` so they no longer mask spec config either.
  (regression tests: `tests/processors/test_archive.py::test_explicit_after_days_is_honoured`,
  `tests/processors/test_preprocess.py::test_explicit_url_dedupe_strategy_is_honoured`,
  `tests/processors/test_extract.py::test_explicit_workers_is_honoured`)

- **`archive` keeps items inside `_pipeline/archive/`.** The month directory
  was `collected_at[:7]` taken from the item's frontmatter unchecked, so a
  value beginning `../../` or `/` moved the raw item out of the archive (and,
  when the computed path already existed, deleted the raw copy as "already
  archived"). Only a `YYYY-MM` value names the directory now; anything else
  falls back to the current month, as a missing value already did.
  (regression test:
  `tests/processors/test_archive.py::test_malformed_collected_at_cannot_steer_the_destination`)

- **Atlassian `?jql=` and O'Reilly `?q=` source URLs are decoded once.**
  Both extractors ran `unquote_plus` on a value `parse_qs` had already
  decoded, so a literal `+` became a space and `%` sequences were decoded
  twice: `jql=text ~ "C%2B%2B"` searched for `"C  "` and an O'Reilly
  `q=C%2B%2B` for `C  `, silently returning results for a different query.
  (regression tests:
  `tests/source_bridge/test_atlassian_module.py::test_parse_source_decodes_the_jql_exactly_once`,
  `tests/source_bridge/test_oreilly_module.py::test_query_url_is_decoded_exactly_once`)

- **The foreman verifier fails on a requirements block it cannot attribute
  to a task, instead of passing.** `_TASK_HEADER_RE` only matches
  `- [ ] T###` / `- [x] T###`; nine specs (020, 027, 032, 033, 038, 049, 052,
  061, 064) write headers without a checkbox (`- T002 [P] …`), so every one of
  their `### Testing Requirements` blocks was skipped and
  `scripts/foreman/verify_test_coverage.py` printed "All declared Testing
  Requirements satisfied" and exited 0 having checked nothing. A
  requirements heading outside a parsed task is now a `ParseError` (exit 2)
  naming the line. Those specs now fail loudly until their headers are
  normalised; the grammar itself is unchanged. (regression test:
  `tests/foreman/test_verify_test_coverage.py::TestParser::test_requirements_block_outside_a_parsed_task_is_an_error`)

- **`vault_audit.py` fails when a check is killed by a signal.** A
  signal-killed validator has a negative returncode; its row rendered `FAIL`,
  but the overall verdict and the exit gate both tested `rc > 0`, so the report
  read `PASS` overall and the script exited 0. Both now test `rc != 0`.
  (regression test:
  `tests/scripts/test_vault_audit.py::test_signal_killed_check_fails_the_audit`)

- **`quality-baseline-update` refuses to bless a crashed run.**
  `collect_fixture_current` reports whether the fixture's cycle crashed, and
  `update_baseline` discarded that flag (`_crashed`), so a crashed run's
  metrics could be confirmed — or `--yes`-ed in CI — into the committed
  baseline, lowering the bar every later release is gated on. It now exits 2
  with the reason on stderr. (regression test:
  `tests/quality/unit/test_baseline_update_cli.py::test_crashed_run_is_never_blessed`)

- **`--max-usd`, `--budget-cap` and `--max-usd-this-run` refuse `nan` and
  `inf`.** `float("nan")` passed both the `< 0` check and the
  zero-means-unlimited check, so the resolved cap was NaN, and `spent >= nan`
  is never true: a cap the operator set could not trip. Non-finite values are
  now a `BudgetError` (exit 2) on every dollar flag. (regression test:
  `tests/cli/test_budget_resolver.py::test_non_finite_dollar_flag_is_a_usage_error`)

- **`raw_capture_batch.py --since 2026-01-01` works, and its exit-2 paths
  say why.** A date-only (or offset-less) `--since` parsed to a naive
  datetime; comparing it with the aware note mtimes raised `TypeError`, which a
  bare `except Exception` turned into a silent exit 2. A naive `--since` is now
  read as UTC, and the unparseable-`--since` and URL-collection failures print
  their reason on stderr. (regression test:
  `tests/scripts/test_raw_capture_batch.py::test_date_only_since_is_read_as_utc`)

- **`reindex` / `rebuild_all` no longer loses a legacy root index.** It
  unlinked the vault-root `_index.md` / `_concepts.md` / `_graph.md` before
  scanning the corpus, and one non-UTF-8 note raised `UnicodeDecodeError`
  (the parser only wrapped `OSError`), aborting the rebuild with the
  hand-curated root files already deleted. An undecodable note is now skipped
  like any other unparseable one, and the root files are removed only after
  the new indexes carrying their content are written. (regression tests:
  `tests/vault/test_indexer_rebuild_safety.py`)

- **An aborted cycle (rc=2) rewinds only the commit it made itself.**
  `vault_commit._rewind_aborted_tail` reset `HEAD~1` whenever the branch tip
  was the last commit the run had recorded — including when the aborted cycle
  had committed nothing. The scaffold's `.gitignore` keeps most of
  `_pipeline/` out of git, so a cycle that aborts before it writes a note
  (scout validation, say) has no diff: the tip was the previous, good cycle,
  and its notes were hard-reset away, recoverable only from the reflog. A
  failed abort commit lost the uncommitted partial work the same way, and an
  abort folded into HEAD by spec 062's `--amend` took the cycle's earlier
  content with it. `commit_cycle` now records the commit each call makes and
  the tip it started from, in memory only; the rewind resets to that tip when
  HEAD is that commit, and otherwise touches nothing. (regression tests:
  `tests/pipeline/test_vault_commit.py::TestAbortRewindsOnlyItsOwnCommit`)

- **A constrained exit (rc=1) no longer force-deletes a research branch that
  still holds unlanded commits.** `complete_run` decided "this run committed
  nothing" from the in-memory `cycle_commit_shas` list and then ran
  `git branch -D`. An rc=2 abort clears the state file, so the list was empty
  on the `--resume` that followed: when that run ended rc=1 without a new
  commit (a budget cap, a resume anchored past `max_cycles`), every earlier
  cycle on the branch was deleted unlanded — under `auto_merge: false` too,
  and likewise a commit the operator had made on the branch. The question is
  now asked of git (`rev-list --count base..branch`), the empty branch is
  removed with `branch -d` so git itself refuses anything else, and a resume
  that finds no state rebuilds the cycle-commit list from the branch, so the
  run lands (or is retained for review) with the right cycle count.
  (regression tests:
  `tests/pipeline/test_vault_commit.py::TestUnlandedWorkIsNeverDropped`)

- **The auto-commit invariant acts on the vault's own repository only.**
  `vault_commit` asked git `--is-inside-work-tree`, which is true for any
  directory inside any repository. A vault directory with no `.git` of its
  own, sitting in another repo, was therefore "a git repo": `git add -A` is
  repository-wide, so `./vault ask` committed the enclosing repo's unrelated
  uncommitted files under a `vault:` subject, and a research run branched,
  squash-merged and (with a remote) pushed that repository. The vault now
  counts as a repo only when it is the top level of the work tree
  (`rev-parse --show-prefix` is empty); otherwise the invariant is skipped for
  the run with a WARNING naming the enclosing repository. (regression tests:
  `tests/pipeline/test_vault_commit.py::TestVaultInsideAnotherRepository`)

- **A vault that is a linked git worktree can start a research run.** The
  run state was written to `<vault>/.git/research-framework/…`, and in a
  linked worktree (or a submodule) `.git` is a file: `begin_run` raised
  `NotADirectoryError` *after* `git checkout -b`, leaving the vault parked on
  a new `research/*` branch with no state, so the next run refused it as a
  stale branch. The state path is now the one git resolves
  (`rev-parse --git-path`) — unchanged for an ordinary clone, per-worktree
  for a linked one. (regression test:
  `tests/pipeline/test_vault_commit.py::TestVaultIsALinkedWorktree`)

- **`./vault update` no longer refuses the step from a release candidate to
  the final release.** `vault_update.compare_versions` compared only the
  digits in each version string, so the pre-release number read as a fourth
  release component: `1.0.0rc11` → `1.0.0` was `(1, 0, 0, 11)` → `(1, 0, 0)`,
  a "downgrade", and the verb exited 2 with "Refusing downgrade" unless the
  operator pinned `RV_GITHUB_REF` and confirmed. The reverse — final back to
  a release candidate — was waved through as an upgrade. Ordering is now
  PEP 440, the scheme `pyproject.toml` and the release tags use (epoch,
  release, `a`/`b`/`rc`, `.post`, `.dev`, local), hand-rolled because
  `packaging` is not a dependency. A string that is not a PEP 440 version
  still falls back to the digit comparison on both sides rather than raising.
  (regression tests: `tests/pipeline/test_vault_update_decide.py`)

- **`./build.sh --quality` and the installer's summary work under the macOS
  system bash (3.2).** Before bash 4.4, `"${ARR[@]}"` on an empty array is an
  "unbound variable" error under `set -u`. `build.sh` passed its optional
  harness arguments that way, so a plain `./build.sh --quality` (no
  `--fixture`, no `--no-color`) aborted with `QUALITY_ARGS[@]: unbound
  variable` after the smoke gate and before the harness — the existing tier-6
  test always passes `--no-color`, so it never saw the empty array. The
  end-user `install.sh` expanded its warning and degraded-mode arrays the same
  way when writing `install_summary.json`: the summary was still correct, but
  each array that was empty — both, on an install with nothing to warn about —
  printed an `unbound variable` error to the operator's terminal. Both scripts
  now use the `${ARR[@]+"${ARR[@]}"}` form, and the regression test runs
  them under `/bin/bash`. (regression test:
  `tests/scripts/test_bash32_empty_arrays.py`)

- **An install refused for an unsupported OS is recorded as failed.** The
  end-user `install.sh` exits 3 on anything but macOS or Linux, but wrote
  `install_summary.json` first without marking the failure, so the audit
  record of a run that installed nothing said `"exit_status": "ok"`. The exit
  now sets the same flag every other summary-writing failure exit sets.
  (regression test: `tests/scripts/test_install_os_branch.py::TestDetectOs::test_unsupported_os_records_a_failed_summary`)

- **`push_on_complete: false` no longer pushes.** The push policy was a
  string compare against `never`: every other value fell through to `auto`
  and pushed whenever a remote existed. YAML reads `false`, `no` and `off` as
  a boolean, not as the string `never`, so the most natural ways to write
  "do not push" sent the landed run to the remote anyway — as did `Never`, a
  typo such as `nver`, or an empty key. A push cannot be taken back, so the
  policy now fails closed: a YAML false means `never`; `true` / `yes` / `on`
  keep meaning `auto`; the three documented values match case-insensitively;
  and anything else skips the push with a WARNING naming the value.
  (regression tests: `tests/pipeline/test_vault_commit.py::TestPushPolicy`)

- **A landing that hits a merge conflict no longer leaves conflict markers
  on `main`.** When the base branch moved during a run (the operator committed
  to `main`) and the squash-merge conflicted, `complete_run` reported the
  failure but left `main` checked out with an unmerged index and `<<<<<<<`
  markers in the notes. The next `git add -A` — which every `./vault ask` /
  `write` / `sync` auto-commit runs — then committed the half-applied merge,
  markers included, to `main` under a `vault:` title. Spec 072 FR3 asks for
  the opposite: "stop, stay on the branch, and say so". A failed squash-merge
  is now backed out (`git reset --merge`, only when the merge actually left
  unmerged paths, so an operator's own staged or unstaged edits are kept) and
  the run branch is checked back out, with a WARNING that names both branches
  and says the landing has to be merged by hand. `main` is left exactly as the
  operator had it; the run's commits stay on the retained branch. (regression
  tests: `tests/pipeline/test_vault_commit.py::TestLandingConflictStaysOnTheBranch`)

- **`./vault update` no longer calls an unversioned vault "dirty".** The
  verb's pre-flight guard runs `vault_commit.is_working_tree_dirty`, which ran
  `git status` unconditionally. In a vault that is not a git repository that
  raised, and the verb reads any failure of the check as a dirty tree: the
  operator got a traceback and "Working tree is dirty. Commit or stash
  changes, or re-run with --force" for a vault with nothing to commit to. A
  vault nested inside another repository was "dirty" whenever *that*
  repository had uncommitted files. The check now answers `False` — with the
  WARNING every commit hook already logs — when the vault is not a repository
  of its own, which is what spec 027 means by "non-git vaults degrade
  gracefully". (regression tests:
  `tests/pipeline/test_vault_commit.py::test_is_working_tree_dirty_false_when_vault_is_not_a_repository`,
  `::test_is_working_tree_dirty_ignores_the_enclosing_repository`)

- **Branch retention reports only the branches git actually deleted.**
  `prune_research_branches` ignored the exit code of `git branch -D`, so a
  landed branch git refused to delete — one checked out in a linked worktree,
  or behind a ref lock — was still listed in `PruneResult.deleted` and named
  as pruned in the one-line retention report, on every pass. A refused branch
  now stays in `kept_landed`, with a WARNING carrying git's reason.
  (regression test: `tests/pipeline/test_branch_retention.py::TestPrune::test_a_branch_git_refuses_to_delete_is_not_reported_deleted`)

- **One malformed article link no longer aborts the RSS collect.** The
  http(s) guard added for `file:` links called `urlsplit` outside
  `_article_text`'s `try`, and `urlsplit` raises `ValueError` on a link such
  as `http://[broken`. Nothing in `collect` catches that, so a single bad
  `<link>` ended the run: the rest of that feed and every feed after it were
  dropped, where the same link used to fall back to the feed summary. A link
  that is not a URL is now treated like any other non-http(s) one. The
  `file:` guard also gains a test that can fail on the leak itself: the
  earlier one's 19-byte secret was classified as a paywall with or without
  the guard. (regression tests:
  `tests/collectors/test_rss.py::test_a_malformed_article_link_falls_back_to_the_summary`,
  `::test_one_malformed_link_does_not_abort_the_collect`,
  `::test_article_fetch_does_not_read_a_local_file_long_enough_to_leak`)

- **The verifier's frontmatter stamp no longer ends the frontmatter at an
  indented `---`.** The stamp found the closing delimiter with
  `line.strip() == "---"`, so a `---` line inside a YAML block scalar
  (`summary: |` followed by an indented rule) was taken for it: the scalar
  was cut there and every key below it — `coverage_category` included — was
  written into the body, on a note the canonical parser had read correctly.
  The delimiter is now matched at column 0, trailing whitespace allowed.
  (regression test:
  `tests/pipeline/test_atomic_write_migrations.py::test_verifier_stamp_ignores_an_indented_dashes_line_in_a_block_scalar`)

- **A missing-wheel exit from the end-user `install.sh` is recorded as
  failed.** The "no `research_framework-*.whl` found" exit runs after the
  venv exists and writes the install summary, but never set
  `INSTALL_FAILED`, so the record read `ok` (or `degraded`). The fast-path
  guard added for failed installs only looks for `"exit_status": "failed"`,
  so a plain re-run still printed "already installed" and exited 0 with
  nothing installed. That exit now records `failed`, and the re-run fails
  the same way until the bundle is complete. (regression test:
  `tests/scripts/test_install_idempotency.py::TestIdempotentRerun::test_missing_wheel_exit_is_recorded_as_failed`)

- **`prune` refuses to delete a target its snapshot could not add.** The
  pre-prune snapshot commit is `--allow-empty`, and the `git add -f` before
  it was never checked — so when the add failed (a file git rejects under
  `core.safecrlf`, an unreadable file) the commit still succeeded, empty, and
  the target was deleted with no copy in any commit while the verb exited 0
  and printed a rollback to a snapshot that never held it. A failed add now
  aborts with exit 2 and nothing deleted, like a failed snapshot commit.
  (regression test:
  `tests/cli/test_prune.py::test_a_target_the_snapshot_could_not_add_is_not_deleted`)

- **`re-grade` no longer ends a quarantined note's frontmatter at the first
  `---` inside a value.** It split on the first `---` substring, so a slug
  URL such as `…/kafka---a-guide` in `source_urls` cut the frontmatter there.
  Every key below the cut was invisible — `verifier_notes` included, which
  the verifier's stamp sorts below it — so a note rejected for an
  agent-semantic reason read as having no rejection notes and was reinstated
  as `verified`; and the note written to `data_vault/` had the URL cut in two
  and the rest of its frontmatter in the body (the canonical parser could not
  read it), while the quarantine copy was deleted. The frontmatter is now
  split by the canonical parser, at the closing `---` line. (regression test:
  `tests/cli/test_regrade.py::test_reinstatement_keeps_a_frontmatter_value_containing_dashes`,
  `::test_non_credibility_rejection_below_a_dashes_value_is_skipped`)

- **`validate_vault.py` and `fix_wikilinks.py` no longer end a note's
  frontmatter at the first `---` inside a value.** Their shared parser split
  on the first `---` substring, so a slug URL such as `…/kafka---a-guide` in
  `source_urls` cut the frontmatter there. The validator then failed a valid
  note with a YAML parse error, or with each required field below the cut
  reported missing; and `fix_wikilinks.py --apply`, on a note whose `related`
  sits above the URL, wrote the cut frontmatter back with the rest of it as
  body — the URL in two pieces, `title` gone from the frontmatter. The closing
  delimiter is now a `---` line, the canonical parser's rule. (regression test:
  `tests/scripts/test_fix_wikilinks.py::test_apply_keeps_a_frontmatter_value_containing_dashes`,
  `tests/scripts/test_validate_vault.py::test_a_frontmatter_value_containing_dashes_is_not_a_delimiter`)

- **`scripts/vault_health.py --apply` no longer cuts a note at the first `---`
  inside a value, nor pushes its body down a line per run.** Its parser split
  on the first `---` substring, so a slug URL such as `…/kafka---a-guide` in
  `source_urls` ended the frontmatter there; fixing a `related` link then wrote
  the cut note back — the URL truncated to `…/kafka`, `a-guide` and every key
  below it (`verifier_status` included) left in the body. Independently of
  that, the body was read from just after the closing `---` with its newline
  and written back after a second one, so each rewrite added a blank line
  below the frontmatter. The closing delimiter is now a `---` line, the
  canonical parser's rule, and the body starts on the line after it.
  (regression test:
  `tests/scripts/test_vault_health.py::TestApplyFixes::test_apply_keeps_a_frontmatter_value_containing_dashes`,
  `::TestApplyFixes::test_apply_does_not_grow_the_gap_below_the_frontmatter`)

- **`scripts/fix_acronym_links.py --apply` no longer wikilinks an acronym
  inside a note's frontmatter.** The fixer and `check_acronym_links.py` both
  split on the first `---` substring, so a slug URL such as
  `…/kafka---a-guide` in `source_urls` ended the frontmatter there and the
  rest of it was treated as body. The first bare acronym in that rest was
  linked — `summary: [[KA]] in practice`, which is no longer valid YAML —
  while the occurrence in the real body stayed bare and the run still printed
  "validation clean". Both scripts now close the frontmatter at a `---` line,
  the canonical parser's rule. (regression test:
  `tests/scripts/test_fix_acronym_links.py::test_apply_links_the_body_not_a_frontmatter_value_below_dashes`)

- **The SKILL.md preflight no longer replaces a valid skill whose frontmatter
  has `---` inside a value.** `pipeline/skill_check.py` split on the first
  `---` substring, so `description: "Verify every claim --- strictly"` was cut
  inside the quotes, reported as "invalid YAML", and
  `validate_and_repair_skills` copied the bundled SKILL.md over the vault
  owner's edited one. With the value unquoted the cut parsed, and broken YAML
  below it passed unchecked. The frontmatter now closes at a `---` line, read
  by a new `vault.frontmatter.split_frontmatter` helper for the readers that
  must not raise on malformed YAML. (regression test:
  `tests/pipeline/test_skill_check.py::test_a_skill_with_dashes_in_a_value_is_not_overwritten_from_the_bundle`,
  `::test_broken_yaml_below_dashes_in_a_value_is_still_flagged`,
  `tests/vault/test_frontmatter.py::test_split_does_not_end_the_frontmatter_at_dashes_inside_a_line`)

- **A finished note with `---` inside a frontmatter value is no longer a stub
  every cycle.** `pipeline/stubs.py` split on the first `---` substring, so a
  slug URL such as `…/kafka---a-guide` in `source_urls` ended the frontmatter
  there. `verifier_status` and `status` below it read as absent, the note was
  reported with `verifier_status=` as its stub reason, and — stubs being
  continuation fuel — the stub-free exit was never reached for that vault.
  The scanner now splits at the delimiter lines. (regression test:
  `tests/pipeline/test_stubs.py::TestMalformedInput::test_dashes_inside_a_value_do_not_end_the_frontmatter`)

- **A spec's frontmatter no longer ends at the first `---` inside one of its
  lines — and the shipped `examples/research.spec.md` loads whole.** Both spec
  loaders (`spec/parser.py`, `spec/simple.py`, and through them
  `scripts/validate_spec.py`) split on the first `---` substring. The example
  spec separates its sections with `# -------` comment rules, so it was cut at
  the first one: only `name`, `location` and `owner` survived, `note_types`,
  `coverage_targets`, `data_sources`, `scope`, `search_dimensions`, `budget`
  and `max_cycles` were dropped without an error, and `validate_spec.py`
  answered "missing required field 'topic'" for the file the README tells you
  to start from. In a simple spec, `topic: Kafka --- the definitive guide`
  loaded as `Kafka` and every field after it was ignored. The frontmatter now
  closes at a `---` line. (regression test:
  `tests/spec/test_parser.py::test_the_shipped_example_spec_loads_whole`,
  `::test_dashes_inside_a_frontmatter_line_do_not_end_the_spec`,
  `tests/spec/test_simple.py::TestParseSimpleHappyPath::test_dashes_inside_a_value_do_not_end_the_frontmatter`)

- **The remaining note readers end the frontmatter at the closing `---` line
  too.** Three more carried the `text.split("---", 2)` that a slug URL such as
  `…/kafka---a-guide` cuts short: the queryability probe scorer
  (`pipeline/probes.py`) read an empty title and category for such a note and
  scored it irrelevant; `scripts/check_template_compliance.py` skipped the
  note when `type` sat below the cut and reported its `template_version` as
  outdated when only that did; and a generated vault's `update_vault.py
  reindex` listed it under its file name with no summary and left it out of
  `_concepts.md`. (regression test:
  `tests/vault/test_note_readers_end_frontmatter_at_a_line.py`)

- **A valid `[[CAP]]` link to `cap.md` is no longer rewritten to a sibling
  note whose title spells CAP.** `build_acronym_map` skipped an acronym that
  "already is a note stem" only when one of the notes *claiming* the acronym
  had that stem. `cap.md` ("CAP Theorem") does not claim CAP —
  `cache-aside-pattern.md` does — so the map sent CAP there and the
  post-processing pass rewrote every `[[CAP]]`, in bodies and in `related`, to
  `[[cache-aside-pattern]]`; with two claimants the link was reduced to plain
  text instead. An acronym that is the stem of any real note (redirect stubs
  excluded) is now left off the map and off the ambiguous list.
  `scripts/validate_vault.py` mirrors the rule, so it no longer warns that such
  an acronym is "ambiguous — not linked". (regression test:
  `tests/pipeline/test_acronym_alias_coverage.py::test_an_acronym_that_is_a_real_note_is_not_remapped`,
  `::test_an_acronym_that_is_a_real_note_is_not_ambiguous_either`,
  `tests/scripts/test_validate_vault_integrity.py::test_acronym_map_parity_when_the_acronym_is_a_real_note`)

- **verify's auto-fix adds its key and leaves the rest of the frontmatter as
  written.** Adding `related: []` or `status: draft` loaded the whole block and
  dumped it again, and a YAML round trip is not the identity: comments were
  dropped, `zip: 0123` came back as `83`, `public: no` as `false`,
  `version: 1.10` as `1.1`, `duration: 1:30` as `90`, quotes and flow lists
  were restyled, long lines folded, anchors expanded. The key is now appended
  as a new line above the closing delimiter (`vault.frontmatter`'s new
  `append_frontmatter_keys`) and every existing line is kept byte for byte.
  The round trip remains only as the fallback for a block a line cannot be
  appended to — none yet, or a flow-style `{...}` mapping. (regression test:
  `tests/processors/test_verify.py::TestAutoFixPreservesFrontmatter::test_lines_the_fix_does_not_touch_are_kept_as_written`,
  `::test_a_flow_style_block_still_gets_its_key`,
  `tests/vault/test_frontmatter.py::test_append_keeps_every_existing_line`)

- **`check_template_compliance.py` and `check_acronym_links.py` exit 2 on a
  directory that has no `data_vault/`.** Pointed at a wrong path that exists —
  the parent folder, `data_vault/` itself — they printed "all notes comply
  with their templates" and "all acronym first-occurrences are wikilinked" and
  exited 0, a pass over zero notes; `fix_acronym_links.py`, which reads the
  vault through the checker, answered "no unlinked acronyms to fix". Both
  docstrings already promised 2 for a missing vault, and spec 077 FR-013/FR-015
  ask for it. The cycle's post-DFS validation step is report-only, so a cycle
  is not halted by the new code. (regression test:
  `tests/scripts/test_check_template_compliance.py::test_a_directory_without_data_vault_is_an_abort_not_a_pass`,
  `tests/scripts/test_check_acronym_links.py::test_a_directory_without_data_vault_is_an_abort_not_a_pass`,
  `tests/scripts/test_fix_acronym_links.py::test_a_directory_without_data_vault_is_an_abort_not_a_pass`)

- **`scripts/vault_health.py --apply` exits 1 when orphan wikilinks remain.**
  With `--apply` every orphan was left out of the unresolved count as
  "auto-cleared on apply", but apply only strips orphans from `related`; a
  body `[[asdf]]` is left for the scout on purpose. The post-apply rescan
  still found it and the report listed it under `### orphan (1)` — with exit
  0, where the docstring promises 1 for unresolved issues. The count now takes
  the rescan as it is. A dry run is unchanged. (regression test:
  `tests/scripts/test_vault_health.py::TestRun::test_apply_still_fails_on_the_orphans_it_cannot_remove`)

- **A generated vault's `update_vault.py validate` no longer passes when a
  validator is killed, or when it ran none.** The script took `max()` over the
  validators' return codes, and a child killed by a signal — an OOM kill, a
  SIGTERM — has a negative one, so the kill was dropped and the run exited 0;
  `refresh` ended on the same `max()` with the metrics script. With no
  validator scripts present every check was skipped and the exit was 0 too.
  A negative code now counts as 2 and "no validator scripts found" is an
  error — the rule the `validate` verb got earlier. Only newly generated
  vaults get the fixed script: `update_vault.py` is user-owned after its
  first write. (regression test:
  `tests/generator/test_templates.py::test_update_script_validate_fails_on_a_signal_killed_validator`,
  `::test_update_script_validate_without_validators_is_an_error_not_a_pass`,
  `::test_update_script_refresh_fails_on_a_signal_killed_metrics_run`)

- **`--settings settings.codex.yaml` reads `settings.codex.yaml`, not the
  `settings.yaml` next to it.** `load_output_dir_from_settings` and
  `load_cycle_limits_from_settings` asked the canonical loader, which takes a
  directory and reads the `settings.yaml` inside it. With a valid
  `settings.yaml` beside the profile — the install folder ships them together
  — `generate --settings settings.codex.yaml` took `output_dir` from the other
  profile and wrote the vault there, or ignored the codex profile's own
  `output_dir`. The fallback that did read the named file only ran when the
  sibling was missing or invalid, which is the only case the tests covered.
  Any file not named `settings.yaml` is now read as itself. (regression test:
  `tests/test_assets.py::TestLoadOutputDirFromSettings::test_a_profile_is_not_answered_from_the_settings_yaml_beside_it`,
  `tests/test_assets.py::TestLoadCycleLimitsFromSettings::test_a_profile_is_not_answered_from_the_settings_yaml_beside_it`)

- **The stub scan and the cited-source lookup read the corpus folder the vault
  declares.** Both spelled `vault / "data_vault"`. In a vault with
  `vault.corpus_dir` set to anything else, `scan_stubs` found no such folder
  and returned an empty list, so the stub-free exit condition was met without
  a note being read; and `cited_hosts_for_cycle` could not find a note the
  cycle report names by bare file name, so a query's discovered sources were
  never appended to the spec. The scan now uses the spec's
  `vault_corpus_dir` and the lookup the shared `vault.corpus` resolver.
  (regression test:
  `tests/pipeline/test_stubs.py::TestScanWalking::test_a_custom_corpus_dir_is_scanned`,
  `tests/pipeline/test_spec_append.py::test_cited_hosts_looks_in_a_custom_corpus_dir`)

- **A vault whose corpus is its own root (`vault.corpus_dir: "."`) no longer
  appends the previous index to every rebuild.** `rebuild_all` reads any
  `_index.md` / `_concepts.md` / `_graph.md` at the vault root as legacy
  copies and carries their content over under "Migrated from vault root". With
  the corpus at the root those are the files the last rebuild wrote, so each
  rebuild — one per cycle — appended the previous index to the new one: 44,
  118, 192, 266 bytes over four rebuilds of a one-note vault. Nothing is
  pulled when the corpus folder is the vault root. (regression test:
  `tests/vault/test_indexer_rebuild_safety.py::test_a_corpus_at_the_vault_root_does_not_append_its_own_indexes`)

- **A note with unparseable frontmatter no longer aborts the verifier
  stage.** The stamp loaded the note's frontmatter with a bare
  `yaml.safe_load`, so a YAML error (an open quote) or frontmatter that is
  not a mapping raised out of `run_verifier_stage` into `steps/research.py`'s
  blanket WARN: every later note in the cycle was left unverified and
  unstamped, and the cycle's verifier manifest was not written. Such a note
  is now left as it is, with a `WARNING` naming it, and the stage carries on.
  (regression test:
  `tests/pipeline/test_verifier.py::test_unparseable_frontmatter_does_not_abort_the_stage`)

- **Spec 077's `tasks.md` is a ledger again.** #342 ticked five follow-up
  tasks (T002–T005, T007) in a spec whose Status is `shipped(…)`, which the
  shipped-task ledger rule forbids (CONTRIBUTING § 2). Neither the pre-commit
  guard battery nor CI — tags and manual runs only — runs that test, so it
  stayed red on `main` from 2026-09-10, the suite's only failure.
  `scripts/ledgerize_shipped_tasks.py` converted the five boxes; each keeps
  its **Done** note, and the two follow-ups still open (T001, T006) keep
  their `- [ ]`. (regression test:
  `tests/docs/test_shipped_tasks_are_a_ledger.py::test_shipped_specs_have_no_checked_boxes_left`)

- **A note that cannot be read no longer aborts the verifier stage.** The
  stage read each note with a strict UTF-8 decode and nothing caught the
  failure, so one Latin-1 note (`café` saved as `caf\xe9`) raised
  `UnicodeDecodeError` out of `run_verifier_stage`: every later note in the
  cycle was left unverified and unstamped, and the cycle's verifier manifest
  was not written. An unreadable note is now treated like a missing one — a
  `WARNING` naming it, a `pending` verdict, no agent dispatched — and the
  stage carries on. (regression test:
  `tests/pipeline/test_verifier.py::test_unreadable_note_does_not_abort_the_stage`)

- **`./vault ask`, `write` and `sync` no longer run the operator's text as
  Python.** The shim's auto-commit helper built its Python by pasting the
  question, topic or label into the source through an unquoted heredoc
  (`title = """${title}"""`). `./vault ask 'define "idempotent"'` was a
  `SyntaxError`: nothing was committed and the verb exited 1 instead of the
  session's own exit code. A backslash was read as an escape, so `C:\new`
  was committed as `C:`, a newline, `ew`. And a text containing three double
  quotes ran whatever Python followed them — reachable by anything that
  builds a `./vault` command from a note title or a harvested topic. The
  vault's own path went the same way: under a directory named `with\tab`
  every auto-commit was skipped as "not a git repo". The values now reach
  Python through the environment and the heredoc is quoted, so they are
  data. The regression tests push nine hostile or awkward texts through each
  of the three verbs under `/bin/bash`, plus a vault path containing a
  backslash. (regression test: `tests/cli/test_vault_shim_untrusted_text.py`)

- **`./vault update` no longer runs a version string or a ref as Python.**
  The verb's four inline Python snippets were built the same way as the
  auto-commit helper's: `decide("${OLD_VERSION}", "${TARGET_VERSION}", …
  pinned_ref="${REF}")` in an unquoted heredoc. The target version is read
  from the `pyproject.toml` of the archive just fetched and the ref from
  `RV_GITHUB_REF` (git allows double quotes and parentheses in a ref name),
  so either could close the string literal and run as code — before the
  downgrade prompt and the dirty-tree guard had a say. The vault path was
  pasted in as well, and rendered into a fifth snippet by the template.
  Versions, ref, flags and paths now travel in the environment, and every
  heredoc that feeds the interpreter is quoted. (regression tests:
  `tests/cli/test_vault_update.py::test_a_ref_that_closes_a_python_string_is_not_executed`,
  `tests/cli/test_vault_shim_untrusted_text.py::test_no_value_is_pasted_into_the_python_the_shim_runs`)

- **Zero-arg `./update.sh` works from any directory name, and no longer runs
  one as Python.** The end-user wrapper asked Python for `output_dir:` with
  the path of the bundle's `settings.yaml` pasted into the source
  (`Path("${DEFAULT_SETTINGS}")`, unquoted heredoc). A bundle unpacked into
  `my "research" bundle/` died with a `SyntaxError`; under `with\tab/` the
  backslash became a tab and the wrapper reported "could not resolve the
  vault to update" for a perfectly good `settings.yaml`; and a quote followed
  by an expression in the directory name was evaluated. The path now reaches
  Python through the environment and the heredoc is quoted. (regression test:
  `tests/scripts/test_dist_update_settings_path.py::test_zero_arg_update_resolves_the_vault_from_a_hostile_bundle_path`)

- **`./vault update` tells a failed dirty-tree check apart from a dirty
  tree.** The pre-flight guard treated every non-zero exit of its check as
  "dirty", so a check that crashed — `git status` on an unreadable index, for
  one — printed a traceback and then "Working tree is dirty. Commit or stash
  changes, or re-run with --force" about a tree nobody had looked at. The
  check now exits 10 for a dirty tree; any other failure is reported as
  "could not check the working tree for uncommitted changes". Both still
  refuse the update with exit 2. (regression test:
  `tests/cli/test_vault_update.py::test_a_dirty_check_that_fails_is_not_reported_as_a_dirty_tree`)

- **`./build.sh --fixture` without a fixture name is a usage error.** As the
  last argument it made `shift 2` fail, and `set -e` ended the script with
  exit 1 and no output at all. Followed by another option
  (`--fixture --quality`) it took that option as the fixture name, so the
  quality harness that was asked for never ran and the build exited 0. Both
  now print "--fixture needs a fixture name" and exit 2, like an unknown
  option. (regression test:
  `tests/build/test_fixture_flag_needs_a_value.py::test_fixture_without_a_name_is_a_usage_error`)

- **A `settings.yaml` the loader rejects no longer uncaps the cycle.**
  `cycle_runner.run_cycle_steps` caught the `SettingsError` and ran on with no
  budget session, so one invalid key anywhere in the file — `default_agent:
  42` — dropped `limits.cycle_budget_usd`, the token and wall-clock caps and
  every `approval_gates` entry, with nothing logged; the agents then
  dispatched. The cycle now aborts (exit 2, an `ERROR` naming the file and the
  loader's reason) before any dispatch when the rejected file carries a
  `limits` or `approval_gates` block, or cannot be read as a mapping at all. A
  file that configures neither loses nothing and runs as before, and so does a
  vault with no `settings.yaml`.
  (regression test: `tests/pipeline/test_cycle_runner.py::test_unloadable_settings_aborts_the_cycle_before_any_dispatch`)

- **`--resume` returns to a cycle that was interrupted, instead of skipping
  it.** Ctrl-C, a `BUDGET_PAUSED` / `APPROVAL_REQUIRED` pause (`SystemExit`)
  and a crash all leave the cycle through the runner's guard, which writes the
  cycle's quality report and clears `in_progress_cycle` on every exit path —
  so the cycle read as completed and the resume anchor moved one past it. Its
  remaining work was never retried, and a standing `BUDGET_PAUSED` was
  re-checked against the *next* cycle's spend (zero), found "now satisfied"
  and cleared without `--force-budget`. Only the rc=2 return wrote the spec
  070 F10 abort marker. `run_cycles` now writes the same marker when a cycle
  leaves by exception and re-raises; the marker is cleared, as before, when
  the cycle later completes. The `cycle` verb calls `run_single_cycle`
  directly and has never written the marker, on either path.
  (regression tests:
  `tests/pipeline/test_aborted_cycle_not_completed.py::test_a_cycle_that_leaves_by_exception_is_the_resume_anchor`,
  `::test_a_budget_pause_is_re_checked_against_the_cycle_it_paused`,
  `::test_the_marker_is_cleared_when_the_interrupted_cycle_later_completes`)

- **A research step that aborts no longer ends the cycle as a success.**
  `steps.research.run_research` dropped the step's exit code, so the only
  check between its abort — a missing `dfs-prompt.md`, an unloadable
  `research-plan.md`, an `agent_call.py` that cannot be launched, the
  required-source quorum abort — and a CONTINUE was postprocess asking whether
  `cycle-NNN-research.json` exists. An earlier attempt at the same cycle (a
  CG-001 retry, or the run a `--resume` picks up) leaves one behind, so
  postprocess validated the previous attempt's report and the cycle returned
  0. `ResearchResult` now carries `exit_code` like the scout and postprocess
  results, and `run_cycle_steps` returns 2 on it before postprocess runs.
  (regression tests:
  `tests/pipeline/test_cycle_runner.py::test_research_abort_is_not_masked_by_an_earlier_research_report`,
  `tests/pipeline/steps/test_research.py::test_run_research_reports_its_own_abort`)

- **A re-dispatched stage no longer overwrites the cost sidecar of the
  dispatch before it.** The cycle steps pass `agent_call.py` an explicit
  `--cost-sidecar` path (`scout.json`, `note_writer-batch-N.json`), and it
  replaces whatever is there. Every re-dispatch inside a cycle named the same
  file: the validator-directive and SG-003 scout retries, each CG-001 attempt,
  a resumed or re-run cycle. Only the last dispatch's cost survived, so
  `limits.cycle_budget_usd` and the lifetime `--max-usd` cap both counted less
  than was spent — a $2 scout, its $3 retry and a $4 note-writer read as $7.
  The dispatch guard in `cycle_runner` now moves the path to the first unused
  `{stage}-N` sibling (spec 028 FR-005 / FR-012: `scout.json`, `scout-2.json`;
  `note_writer-batch-1.json`, `note_writer-2-batch-1.json`), which every
  reader already globs. The sidecar's content is unchanged. A cycle that is
  run again now adds to what its earlier attempt spent, so it can reach its
  per-cycle cap sooner. The verifier dispatches outside this guard and still
  reuses `verifier-N.json` across attempts.
  (regression tests:
  `tests/pipeline/test_budget_cap_multi_batch.py::test_a_scout_retry_does_not_overwrite_the_first_dispatchs_cost`,
  `::test_a_second_attempt_at_a_cycle_adds_to_its_spend`)

- **A source probe that fails in a way `urllib` or `subprocess` does not wrap
  no longer crashes `generate` and `--resume`.** `preflight.check_source`
  caught `OSError` around the `gh` calls and `HTTPError` / `URLError` around
  the web and RSS probes. A `gh` that hangs past its 30 s timeout raises
  `subprocess.TimeoutExpired`; a server that accepts the connection and then
  stalls raises a bare `TimeoutError`; a source URL with no scheme is a
  `ValueError` from `urllib.request.Request`, a bad port an
  `http.client.InvalidURL`; and an RSS body declaring an encoding expat does
  not know is a `LookupError` from the XML parse. Each went straight through
  `check_all` and `preconditions.check` as a traceback, before any cycle ran.
  They are now verdicts on the source like every other probe failure:
  `degraded` for `gh`, `unreachable` with the reason for web and RSS.
  (regression tests:
  `tests/pipeline/test_preflight.py::test_github_pr_probe_that_times_out_is_degraded`,
  `::test_a_read_that_stalls_after_connecting_is_unreachable`,
  `::test_a_url_urllib_refuses_is_unreachable`,
  `::test_rss_body_in_an_encoding_expat_rejects_is_unreachable`)

- **`pipeline <vault> status` no longer crashes on a state file that is valid
  JSON but not an object.** `runner.status` handled an unreadable or
  unparseable `pipeline-state.json` by returning `{"error": …}` and then
  called `.get` on whatever the file held — a `[]`, `null` or bare string left
  by a truncated or hand-edited write raised `AttributeError`, which the CLI
  reports as a framework bug. That shape is now the same `error` result.
  (regression test: `tests/pipeline/test_runner.py::TestStatus::test_returns_error_dict_on_json_that_is_not_an_object`)

- **Both `run-report.md` files are written atomically.** `_pipeline/run-report.md`
  (the cycle orchestrator's) and `_pipeline/runs/<run_id>/run-report.md` (the
  pipeline runner's, rewritten on every phase close) went through
  `Path.write_text`, which truncates the file before it writes. A rewrite that
  failed — a full disk, or an exit reason carrying a character that cannot be
  encoded — left a zero-byte or torn report where a complete one had been, and
  both writers swallow the error by design. They now use
  `atomic_write.write_text` like the JSON beside them, so a failed rewrite
  leaves the previous report in place. (A report created this way is
  owner-readable only, as every other atomically written `_pipeline` file
  already is.)
  (regression tests:
  `tests/pipeline/test_run_report.py::test_a_report_that_cannot_be_written_leaves_the_previous_one_in_place`,
  `tests/pipeline/test_run_receipt.py::test_a_run_report_that_cannot_be_replaced_is_left_as_it_was`)

- **A non-numeric `limits.tier_thresholds` or `limits.estimator_calibration`
  entry is a `SettingsError`, not a `ValueError`.** Both maps went through a
  bare `float()`, so `tier_thresholds: {basic: abc}` — or a `null` — raised
  `ValueError` / `TypeError` out of `load_vault_settings`. Spec 076 FR-005
  promises a single settings-error type, and every caller that degrades on it
  (`effective_max_cycles`, the verifier, the plan narrator, coverage) crashed
  instead; the cycle runner ended in a traceback rather than its exit-2
  message naming the key. The error now names the entry
  (`limits.tier_thresholds.basic`). Values that loaded before still load.
  (regression tests:
  `tests/pipeline/test_settings_loader.py::test_a_non_numeric_limits_factor_is_a_settings_error`,
  `::test_numeric_limits_factors_still_load`)

### Changed

- **The exit-code model is enforced, and four verbs now obey it** (spec 077
  T002–T005, T007; #248). Spec 070 FR6 — "every non-zero exit MUST write a
  diagnosable message to stderr" — has been marked DONE since v1.0.0, and the
  only thing holding it up was a *backstop*: `cli.main` noticing after the fact
  that a verb exited silently and printing an apology. That is a smoke alarm,
  not a building code, and it fires for whoever ran the command — which on this
  project is a cron job at 03:00 over eight vaults.
  `tests/cli/test_exit_code_contract.py` is the building code: it walks every
  `_cmd_*` / `cmd_*` function and fails when a non-zero `return` has no stderr
  write on the path to it, with a reasoned allowlist for the returns that are
  deliberately not errors. It is in `scripts/guards/run_all.py`'s battery. (Its
  first draft passed on its first run, which for ~20 verbs is a result worth
  distrusting: it was letting the near-universal `if args.vault is None:` check
  at the top of a verb vouch for every silent return below it. The shipped
  version only counts a write that is actually on the path, and a test pins
  that distinction.)

  The four divergences 077 recorded: **the shim's unknown-verb arm exits 2**,
  not 1, and on stderr — argparse always exited 2 for the same typo (D3).
  **`prune` and `regenerate-agents` agree that a declined confirmation is 1**;
  `prune` returned 0, which tells a wrapper the prune happened (D4).
  **`wikilinks` and `re-grade` deliberately stay 0** — they are fixers, not
  gates, a fixer that exits non-zero on a finding cannot be chained, and the
  gate that fails on note problems is `verify`; their counts are on stdout and
  in `--json` (D5). **`./vault sync` now exits on purpose**: the arm had no
  `exit` at all, so it returned whatever the last command left, and the last
  command is an `|| echo` that always succeeds — it exited 0 by accident. It
  exits with the commit's status now, because the commit is the contract and
  the push is best-effort (D5).

- **`digest` stops using one message for three different outcomes** (spec 077
  T005 / D6). A malformed `--since`, a valid future date, and a legitimately
  empty range all printed **"No cycles in scope"** — the first two on stderr
  with exit 1, the third on stdout with exit 0. An operator could not tell a
  typo from a quiet vault. A malformed or future `--since` is now exit **2**
  (the usage class) with a message naming the flag *and* the value; an empty
  range stays exit 0 on stdout and names the window it searched.

- **The last six documents that described a dead CI regime, a dead roadmap
  shape or a CLI list that had drifted.** The 2026-09-08 review found 22 stale
  files and PR #337 fixed sixteen; these are the rest.
  `docs/PORTABILITY.md` and `tests/README.md` still said CI runs "on every PR +
  push to `main`", which #323 reversed — the merge gate is the local suite, and
  both now say so, with `tests/README.md`'s directory map gaining the twelve
  test directories added since it was written. `release.yml`'s header still
  advertised "bump `pyproject.toml`, commit + push to main" as the recommended
  way to cut a release; that path triggers nothing at all now, and the header
  says which two do. `ARCHITECTURE.md` cited three sections of a roadmap that no
  longer exists ("Completed (recent)", "Current focus", `queue #N`), stopped its
  ADR table at 0007 of thirteen, called the constitution 557 lines when it is
  1424, and carried a `./vault` verb list showing 2 of 21 argparse verbs — § 14
  now points at **spec 077** as the owning document and keeps only the shape
  (one entry point, one shim, 18 verbs, three exit codes), because a list
  restated in two places drifts in one of them. § 12 records that Vault
  Specialities *was* specced (046) and subsumed by 053, rather than reading as
  an open idea. `specs/041-release-infrastructure-v2/spec.md` gains a banner
  saying two of its three pillars describe a world that ended with 1.2.0:
  per-PR CI is forbidden by the CI-budget rule and the `pyproject`-bump
  auto-detect is no longer a trigger, so what survives to be planned is the
  manifest-diff release gate and PyPI publication.

- **A live JSON Schema no longer lives in the spec archive.**
  `specs/_archive/README.md` states the rule that puts a folder there:
  tombstoned / pre-format / a 015x draft / a vault-instance plan / a refactor
  diary — *and* no tracked file outside `specs/` opens a file inside it. It had
  exactly one violation, and nothing said so:
  `pipeline-state.schema.json` describes `_pipeline/pipeline-state.json`, a
  file `pipeline/runner.py` writes on every phase transition, and
  `tests/contracts/test_json_schema_validation.py` opened it from
  `015g-pipeline-orchestrator-command/contracts/`. The schema moves to
  `specs/075-pipeline-runner/contracts/` — 075 supersedes 015g as the runner's
  owning document — and 015g keeps a pointer at its new home. 075's D5
  divergence ("a JSON Schema that nothing reads") is closed with it. The rule's
  second half is now enforced by
  `tests/docs/test_spec_index_completeness.py::test_no_tracked_file_outside_specs_opens_a_file_in_the_archive`,
  which walks the tracked tree for a string *literal* naming the directory as a
  path — prose in a comment or docstring is still allowed, since a file may
  describe the rule without breaking it. (#295)

- **No test can monkeypatch `run_cycle_steps` any more — the rule is a guard,
  not a paragraph.** `CLAUDE.md` has called it a hard anti-pattern since the
  2026-05-30 audit found ten sites, and the number moved down by hand and back
  up by accident because nothing failed when a new one appeared. There were
  **twelve** left, not the three the roadmap tracked: it counted the attribute
  spelling (`setattr(mod, "run_cycle_steps", …)`) and nine more used the dotted
  one (`setattr("pkg.mod.run_cycle_steps", …)`). Replacing the module global
  from outside means the code under test still *believes* it called the runner
  — the substitution is invisible at the call site, leaks to every other test
  importing that module in the same process, and depends on import order to
  bind at all. Every site now passes a keyword-only **`cycle_runner=` seam**:
  `orchestrator.run_single_cycle` threads it to the retry helper that already
  had one, and the quality harness declares it on `run` /
  `collect_fixture_current` / `_run_fixture` / `_invoke_cycles`; `None`
  (production, and every `build.sh --quality` run) resolves the real
  `run_cycle_steps` at call time. Stubs live in
  `tests/_helpers/cycle_runner_stub.py` and mirror the runner's real signature
  rather than swallowing `**kwargs`, so a signature change fails loudly instead
  of being absorbed — the failure mode #268 found, where the harness's pinned
  budget pair was invisible to a permissive stub.
  `tests/_helpers/test_cycle_runner_seam_guard.py` (AST, both spellings, in
  `scripts/guards/run_all.py`'s battery) fails the suite if one comes back.
  (#86)

- **Spec 036 clarified.** Q1 additive with `schema_version` recorded but not
  acted on (ADR-0013); Q2 `integrations.assistant.inbox_path` configurable,
  default `~/.assistant/inbox/` (`${ASSISTANT_HOME}/inbox/` when set); Q3
  036 v1 ships first and 023 Phase 2 cites its contract. The spec now says
  what clarifying found: `./vault ask` is an interactive `claude` session, so
  `--format json` needs a headless producer through `agent_call` before it
  is a flag.
- **#221, #224, #246, #247, #248 and #249 re-homed as standalone `type:spec`
  issues** pointing at their spec (080, 080, and 075/077 for the operator
  surface); the `epic:` labels come off so #211 and #214 can close as
  incident-class trackers.

- **`docs/ROADMAP.md` replaced wholesale** (owner decision D3, 2026-09-08).
  The old file was a v1.0.0 release checklist, an rc status matrix, three
  wave narratives and a `#N`-numbered queue with nothing on it that had not
  shipped. It is now a shipped registry by tag date, the next two releases
  as ordered tiers (v1.3.0 — the weekly pipeline runs unattended; v1.4.0 —
  contracts a consumer can build against), v2.0.0 candidates, and a
  Deferred table with one row per parked spec carrying its substance and
  its trigger. The eight stub issues (#42 #47 #53 #58 #59 #60 #61 #147)
  close with a comment pointing at their row (D12): #60 tombstoned (spec 040
  ships the report mirror; `./vault sync` is the whole-tree copy), #58
  folded into #249 (the unattended verb's `--auto-approve` policy is the
  autonomy level). The label taxonomy moved to `CONTRIBUTING.md` § 8.
- **The root docs, release docs and skill inventory say what 1.2.0 is.**
  Every stale statement the 2026-09-08 review found in `README.md`,
  `CLAUDE.md`, `CONTRIBUTING.md`, `docs/RELEASE.md`,
  `docs/testing-strategy.md` and `.agents/skills/README.md` is fixed:
  `./vault write` and `./vault maintain` are marked *listed, not runnable*
  rather than advertised (spec 077 D2 — their backing scripts do not ship;
  documented honestly, not restored); the shim's 18 verbs follow 077
  FR-008; README's hand-maintained spec table (075–079 missing, nineteen
  archived folders listed as active) is a pointer to the guarded
  `specs/README.md`; every test count is a pointer to the one committed
  marker; the install examples cite v1.2.0 and `~/vaults/`; CLAUDE.md's
  rc7 snapshot header, `[Unreleased]` labels on released work, "auto-fires
  on `pyproject` change", 5-milestone / 19-label counts, ADR list ending at
  0010 and the 2026-05-26 "Strategic Sequencing" are corrected or marked
  historical and Recent Changes is pruned to five cycles; CONTRIBUTING's
  pre-ADR-0008 tier table, "Path A auto" release path, `pipeline/agent_call.py`
  and "Principle V" (single dispatch is IV) are fixed and its doc taxonomy
  gains the twelve files it omitted; `docs/RELEASE.md` describes the
  tags-and-dispatch-only regime, that the workflows must be enabled on
  GitHub for a tag to do anything (v1.2.0 has a Release run and no CI /
  quality record), the CHANGELOG heading-date = tag-date rule (D14), the
  `### Migration notes` rule, and the 1.1.1/1.2.0 `limits:` migration;
  `docs/testing-strategy.md`'s automation matrix no longer claims PR CI and
  its `processors/extract.py` "not gated" note is retired (it routes through
  `agent_call.dispatch()`); the skills inventory lists all 26 directories
  instead of 16.

- **Constitution amended to v1.6.0** (`.specify/memory/constitution.md`;
  ratified 2026-04-16, last amended 2026-09-08). MINOR — two principles
  added, one enforcement downgrade, and the Enforcement Register
  re-verified row by row against the tree at v1.2.0. Docs only; no code,
  no spec, no ADR. (no test: governance documentation; the pointer
  guards in `tests/docs/test_one_source_per_fact.py` and
  `tests/docs/test_specify_templates_are_ours.py` cover the propagation)

  - **New Principle XIII (NON-NEGOTIABLE) — Nothing Is Accepted and
    Ignored.** A flag, settings key or field the framework accepts reaches
    a consumer or is refused with exit 2; a recorded failure is spoken on
    stderr at ERROR naming the record; a phase is done by artifact, not
    by exit code. Derived from new failure-record entry **F10** — the
    2026-09-01 run's other half: seven vaults failed with `errors: []` and
    zero bytes of output, phases reported done having written nothing, and
    `--budget-cap` was accepted and read by nothing. Enforced today by
    `scripts/guards/parser_flag_consumers.py`, the non-silent-exit guard
    and `runner._close_phase`; settings keys are the named gap.
  - **New Principle XIV — A Local or Decentralised Model Option Is Always
    Supported** (owner's decision, 2026-09-08). Every model-backed
    capability keeps a self-hosted provider path; degraded is acceptable,
    absent is a violation; a local profile ships with every release. The
    Register row is Partial: `settings.ollama.yaml` is in the source tree
    and not yet in the wheel or the bundle (decision D11 packages it).
  - **Enforcement downgrade.** "Enforced" was defined as "runs in the PR
    gate" and there has been no PR gate since #323; the definition is
    rebound to the local merge gate (`scripts/guards/run_all.py`,
    `pytest -m "not e2e"`, ruff) that `ci.yml` re-runs on tags. The
    Register preamble is rewritten to what exists: the tracked
    `.git-hooks/pre-commit` (opt-in per clone), the guard aggregator's
    three scripts plus thirteen guard test files, `build.sh`'s smoke gate
    carrying the dispatch guard, and the abstraction gates on by default.
  - **Rows re-verified**: III (8 of 35 scripts take `--dry-run`), IV
    (fail-closed scan root, derived binary set, HTTP mode; residual blind
    spots restated), VI (`proposed_filenames` required, SG-004 `duplicate`
    → FAIL), X (twelve modules), XI (**Not met → Partial**: `tests/contracts/`
    exists and spec 079 versions the note format per note), XII (verify
    writes its report outside the corpus; FAIL path pinned). Count: 2
    Enforced, 9 Partial, 3 Review-time only, 0 Not met.
  - Principle I's gate table gains the scout step gates and their
    correction loop, SG-004's duplicate class, CG-001's retry, and the
    weekly runner's artifact checks and verify verdict. The Cross-Repo
    note-format row moves to Partial (versioned per note; not mirrored —
    `consumer_pipeline`'s register has no row for it). Technology Constraints
    name the five spec-078 runtimes and `ruff format`. Out-of-Scope names
    specs 075–079 as authorities. Plan template: v1.6.0 pointer, gate
    rows XIII and XIV, enforcement-honesty wording for a tags-only CI.
- **`pipeline.coverage_growth` — a coverage target says "this much, for now",
  not "this much, forever".** `target_count` was read as a lifetime ceiling, so
  a vault that reached it was finished permanently. Measured on a live vault
  (`feeds-vault`, 2026-09-10): 441 notes on disk against a 55-note target, 54
  counted met, so the planner computed a remaining of 1 and wrote
  `cycle_quota: 2` — two notes per cycle, indefinitely, no matter what the
  sources surfaced. Its own cycle-12 plan records the cost: "the priority queue
  is dominated by company-category orphans (funding concentration, API, Claude
  Cowork, Lean 4, MCP, Copilot Cowork) — none of which map to this cycle's
  three focus categories". The scout was finding current material and the plan
  was discarding it, because the only categories still under target were
  people, trends and future/philosophy at five each.

  `coverage.grow_targets_if_met` raises every target by the configured factor
  at the moment the vault has met them all, and `research_plan.generate_plan`
  calls it before computing the quota. Growth is measured from what the vault
  HOLDS, not from its old target, so a starved vault catches up in one round
  rather than several. It compounds: each round multiplies a larger base, which
  is exponential across rounds rather than a constant increment.

  Deliberately fired on *met* rather than continuously: a target recomputed
  from `met_count` on every plan recedes as the vault approaches it, so the
  Phase 3 gate could never close and "coverage met" would stop meaning
  anything. Freezing the raise to the met moment keeps each round finite and
  reachable.

  Default is `1.0` — one-and-done, byte-identical to today — because some
  vaults answer a fixed question and stop. Archived vaults (spec 071) are never
  grown: that flag means finished. Values below 1.0 are rejected rather than
  clamped, on the same reasoning as `archived`: this decides whether a vault
  keeps pace, and a typo that silently reads as "stop growing" is the failure
  mode worth being strict about. (tests:
  `tests/pipeline/test_coverage_growth.py`, 12 cases)

  The raise is capped per category per round (`pipeline.coverage_growth_cap`,
  default 10). A bare multiplier is compound interest: 1.4 turns a 143-note
  target into 200, 280, 392, 549 in four rounds, and a bar nobody will ever
  write leaves the vault permanently unmet, which is as useless as permanently
  finished. With the cap the shape is multiplicative while a category is small,
  where a percentage is the sensible unit, and linear once it is large, where a
  percentage is absurd.

## Before the public release

Everything below shipped from the private development repository, numbered
0.1.0 to 1.2.0. Those versions are not tags in this repository and the public
line does not continue them: where docs and specs say "shipped in 1.1.0" or
"since 1.2.0", they mean these private versions, and `#NNN` issue and PR
numbers refer to that repository.

## [private 1.2.0] - 2026-09-08

### Added

- **`research-framework pause show | clear` — inspect or abandon a pause
  without resuming.** `budget-marker.contract.md` §5 has listed "operator
  aborts cycle (explicit cleanup command)" as a clear condition since spec 033
  was planned, and nothing implemented it: abandoning a paused cycle meant
  `rm _pipeline/BUDGET_PAUSED`, and no verb would first say what the marker
  held — which stage stopped, what the blocked dispatch was about to cost, how
  much the cycle had already spent. `show` renders exactly the fields the
  resume path re-checks (both markers, `--json` for `status` and the fleet
  view) and is deliberately unfailable: a marker this build cannot parse is
  reported as such and the verb still exits 0, because a diagnostic that
  disappears when the state is broken is not a diagnostic. `clear` destroys
  operator state, so it takes a y/N on a TTY or `--yes` headless, and
  `--marker budget|approval|all` selects; it is also the one sanctioned way to
  remove an unparseable marker, which `budget_resume` deliberately refuses to
  touch. Clearing an approval pause records NO `approval-decisions.json` row:
  walking away from a gate is not a verdict (contract §6.1), and §8 now says
  so. (#237)

- **`--estimate-only`: a cost preflight that dispatches nothing.**
  `cost_estimator.estimate_dispatch` had only ever been asked one dispatch at a
  time, from inside a cycle that was already spending; until #230 seeded real
  ceilings, the first signal an operator got about a run's cost was the bill.
  `generate --estimate-only` / `cycle --estimate-only` project the next cycle
  and exit without dispatching. The numbers are the guard's own — same
  estimator, same ceilings, same p95 floor, and each stage's agent and
  `max_tokens` resolved through `budget_guard.resolve_dispatch_agent` /
  `resolve_max_tokens`, moved there from `cycle_runner` so the preflight and
  the dispatch hook read one implementation instead of two opinions. It counts
  dispatches, not stages (`note_writer` once per batch, `verifier` once per
  note, from the spec-051 yield model and the configured batch size), floored
  at `cycle_yield.min_floor` so a fully-covered vault is never priced at zero.
  Exit code is the verdict: 0 when a `limits.cycle_budget_usd` resolves, 2 when
  none does — the question is "is this safe to leave unattended", and a run
  nothing would stop is not. The estimate prints either way. (#238)

- **`--more-cycles N` and `--max-usd-this-run USD` — the per-run budget
  readings, under their own names.** Spec 070's open questions 4/4a recorded
  that `--max-cycles` / `--max-usd` read as per-run budgets and are lifetime
  ceilings, so "give it $10" was unachievable on a vault that had already spent
  more. Additive by design: neither existing flag changes meaning.
  `--more-cycles 3` from cycle 7 resolves a ceiling of 9 and shares the top
  rung with `--max-cycles` (passing both is a usage error — one rung, one
  answer); `--max-usd-this-run` caps what THIS run adds, measured from a
  baseline taken before the first cycle so history the operator already paid
  for cannot consume the budget they just authorised. Flag-only: a per-run
  ceiling is a launch-time decision, and a settings key would outlive it and
  quietly re-apply to every later run — which is how `cycles.initial_max`
  earned spec 061. Spec 061 carries the amendment (FR3-P1/P2). (#239)

- **`tests/docs/test_one_source_per_fact.py`, a drift guard for facts that
  existed in five hand-copied places.** (test: the module's own 7 tests —
  `test_testing_strategy_tiers_match_adr_0008`,
  `test_architecture_tiers_match_adr_0008`,
  `test_testing_strategy_count_marker_matches_live_collection`,
  `test_testing_strategy_count_prose_matches_marker`,
  `test_pyproject_version_matches_changelog_latest_entry`,
  `test_readme_constitution_citation_matches_constitution`,
  `test_claude_md_constitution_citation_matches_constitution`) Test tiers
  were copied into README, CLAUDE.md, CONTRIBUTING.md, ARCHITECTURE.md and
  `docs/testing-strategy.md`, and had drifted: CONTRIBUTING's decision
  table inverted ADR-0008's Tier 5 (called it "e2e real LLM" when ADR-0008
  defines Tier 5 as the hermetic fake-agent cycle e2e), and
  `docs/testing-strategy.md` still said "six-tier" in two places three
  months after ADR-0008 restructured it to seven. Test counts were quoted
  as literals in five docs and none of them agreed — README/CLAUDE.md said
  3053/3080, `docs/testing-strategy.md`/CONTRIBUTING.md/`docs/RELEASE.md`
  said 1692/1718, and the live suite (`pytest --collect-only -q`) was
  neither. ARCHITECTURE.md called shipped spec 020 "design-locked, not yet
  implemented" (it shipped 0.4.0 on 2026-05-27) and still marked its own
  `source_bridge/` and `modules/` packages "(planned, spec 020)". README
  cited constitution 1.3.4 against the constitution's own 1.4.0 footer.
  **Fix**: `docs/adr/0008-testing-pyramid-restructure.md` is now the
  canonical tier table; `docs/testing-strategy.md` and ARCHITECTURE.md
  carry checked copies (the new test parses all three and fails on any
  name/number mismatch). `docs/testing-strategy.md`'s TL;DR carries the
  only committed test count, as a machine-parseable
  `<!-- test-count: ... -->` comment the guard re-derives from a live
  collection every run; every other doc (README, CLAUDE.md,
  `docs/RELEASE.md`) now points there instead of quoting a number.
  `pyproject.toml` is canonical for the release version (checked against
  CHANGELOG's own latest heading) and the constitution's footer is
  canonical for its version (checked against README.md's and CLAUDE.md's
  citations). ARCHITECTURE.md's spec-020 section and directory-tree
  comments now say SHIPPED. CONTRIBUTING.md's stale tier table and
  README/CLAUDE.md's stale counts were left in place with an explicit
  correction paragraph pointing at the canonical source, rather than
  rewritten in place — those three files are shared across every
  in-flight lane and a wholesale rewrite would conflict with unrelated
  work landing the same week. (#281)

- **`scripts/guards/run_all.py`, one aggregator for every corpus-level
  guard.** (test: tests run via the aggregator itself —
  scripts/guards/run_all.py's own guard-test-battery list) Before this,
  running "the guards" meant a human reading a CLAUDE.md checklist and
  invoking each one by hand; CI ran exactly one (the portability guard) as
  its own named step and left the rest anonymous inside `pytest -m "not
  e2e"`'s ~3000 tests. The aggregator runs the portability guard plus every
  guard test file in one battery with a per-guard pass/fail summary;
  `ci.yml`'s new `Guard battery` step calls it, and a tracked
  `.git-hooks/pre-commit` hook (installed once via
  `scripts/install-git-hooks.sh`, since `.git/hooks/` isn't tracked) calls
  it locally before a commit lands. Deliberately excludes the
  vault-scoped guards (`check_abstraction.py`, `validate_vault.py`,
  `quality_report.py`, etc. — each requires a generated vault this repo
  doesn't ship) and the foreman Arm A verifier (no corpus-sweep mode yet) —
  see `docs/testing-strategy.md` § Guard battery aggregator. (#278)

- **Fail-closed floor assertions on five guards that previously scanned a
  hardcoded root with no check that the root had anything in it.** (test:
  tests/_helpers/test_llm_dispatch_guard.py::test_scan_root_is_not_vacuous,
  tests/quality/unit/test_marker_isolation.py::test_quality_dir_scan_is_not_vacuous,
  tests/quality/test_baseline_update_isolation.py::test_scan_roots_are_not_vacuous,
  tests/benchmark/unit/test_marker_isolation.py::test_benchmark_tests_scan_is_not_vacuous,
  tests/benchmark/unit/test_build_exclusion.py::test_pipeline_scan_is_not_vacuous)
  The LLM-dispatch guard's `SCAN_ROOT` (and four other AST/text guards'
  scan roots) would pass vacuously if the root were moved, renamed, or
  emptied — an empty violations list is indistinguishable from "scanned
  everything, found nothing" and from "scanned nothing." Each guard now
  asserts a floor on how many files it actually scanned. (#278)

- **A durable, bounded retention tracker for spec 072 FR5's research
  branches.** (test: tests/pipeline/test_branch_retention.py,
  tests/scripts/test_prune_research_branches.py) FR5 keeps a run's
  `research/<date>-<time>` branch after landing it on `main`, forever, so
  a bad landing stays one `git reset` away — that guarantee is unchanged.
  Spec 072's own "Open questions" section named the follow-up (14 branches
  across seven vaults as of 2026-08-30, unbounded) and pointed it at
  #307 rather than `docs/TODO.md` (a scratchpad deleted on ship). New
  `pipeline/branch_retention.py`: `list_research_branches` classifies
  every `research/*` branch landed or not, and `prune_research_branches`
  deletes only landed branches beyond a keep-last-N cutoff — an unlanded
  branch is never a deletion candidate, at any age or count, per FR5's own
  caution that a prune "MUST verify the branch's content is on main
  first." "Landed" is deliberately not commit ancestry:
  `vault_commit._squash_merge` commits a *new* object on `main`, so a
  landed branch's own commits are never its ancestors; every landing
  commit's body instead carries an exact, grep-able marker
  (`**Branch:** research/<ts>`, from `vault_commit._format_run_body`),
  which is what this module checks for. Exposed as a shipped CLI,
  `scripts/prune_research_branches.py <vault> {list,prune}` (`prune` is
  dry-run unless `--yes` is passed) — copied into every generated vault
  by the existing `copy_scripts` bundling, same as `preflight_sources.py`.
  Not wired into `complete_run` automatically; this is the "smallest
  honest version" the issue named (list + prune verb), left as an
  operator- or cron-driven step rather than a new implicit behaviour on
  every run. (#307)

- **A fake at the CLI-BINARY seam, so the dispatcher itself runs in e2e
  tests.** (test: `tests/_helpers/test_fake_cli_binary.py` — 16 tests;
  `tests/e2e/test_cli_binary_seam.py`) Every e2e run replaced the vault's
  whole `scripts/agent_call.py` with `fake_agent.install_shim`, so argv
  construction, the prompt-on-stdin convention, stream-json framing, the cost
  parser, sidecar v1.2 and the failure sidecar never executed on any e2e
  path — every sidecar in every test said `agent_kind: "fake"`, and the
  production branch that stamps a real dispatch was never taken. That blind
  spot shipped a `NameError` in the shim's `dispatch` (#259) and a missing
  `model` kwarg (#262). `tests/_helpers/fake_cli_binary.py` moves the fake one
  level down: the vault keeps the real dispatcher and only the leaf
  `claude` / `codex` binary is replaced, installed on `$PATH` *and* through
  the per-profile `CLAUDE_BIN` / `CODEX_BIN` overrides so an ambient real
  `claude` cannot satisfy a test. The stub validates the argv it is handed
  against what each real CLI requires (`--model` + `--print`; `exec` for
  codex) and refuses anything else, so an adapter regression turns a test red
  instead of passing on a stub that ignores argv; it writes no telemetry of
  its own, so every sidecar a binary-seam test reads was written by
  `agent_call.py`. `tests/e2e/` is migrated. The in-process fake stays the
  default for the fast loop and the quality fixtures, as #270 specifies.
  (#270)

- **`scripts/guards/parser_flag_consumers.py` — every CLI flag must reach a
  non-CLI consumer.** (test: `tests/cli/test_parser_flag_consumer_guard.py` —
  17 tests) Six accepted-but-inert options have been found here (`url:`,
  `--target-topics`, `source_policy: hard`, `pipeline --budget-cap` #232,
  `vault.corpus_dir` #251, `verify`'s `auto_fix` / `fail_threshold`) and the
  1.1.0 CHANGELOG names the pattern four times. The guard walks every
  subparser of the *built* parser — argparse's own `dest` inference rather
  than a re-implementation of it — and requires each flag's `dest` both to be
  read under `cli/` and to appear as a real Python identifier (AST, so
  comments, docstrings and string literals do not count) in a module outside
  `cli/`. 68 flags, 212 modules, 13 waived with a written reason each; a
  waiver goes stale — and red — the moment its flag disappears or acquires a
  consumer. Registered as its own named line in the #278 guard battery.
  (#271)

### Changed

- **The CI story matches a workflow that no longer runs per PR.** (test:
  `tests/scripts/test_ci_config.py::test_triggers_on_version_tags_and_by_hand_only`,
  `::test_matrix_is_linux_with_macos_opt_in`,
  `::test_the_macos_opt_in_is_a_declared_workflow_input`) #323 and #324 moved
  `ci.yml` to version tags and `workflow_dispatch` with macOS opt-in; the
  workflow changed and its own contract test did not, leaving two assertions
  red on `main` that still required a `pull_request` trigger and a standing
  two-OS matrix. They now assert the current triggers — a `pull_request`
  trigger re-added by accident is a real billing incident, so it is worth
  failing on — and pin the `macos` input's `default: false`, which is the
  cost control and was previously droppable without any test noticing.
  Spec 009 keeps its record and gains a post-ship note (rewriting a frozen
  shipped spec would falsify history); its quickstart, which is live how-to
  rather than history, is corrected outright; and CONTRIBUTING § 1 no longer
  claims the guard battery runs on every PR.

- **The five missing trunk specs are written: `075-pipeline-runner`,
  `076-settings-schema`, `077-cli-contract`, `078-dispatch-surface`,
  `079-note-format`.** (test: each carries an Acceptance coverage table whose
  evidence cells are checked by
  `tests/spec/test_acceptance_coverage_guard.py::test_every_spec_with_gwt_has_acceptance_coverage`,
  which resolves every cited test path and symbol on disk; plus
  `tests/docs/test_specify_templates_are_ours.py::test_the_trunk_blocks_parse_with_the_foremans_own_grammar`)
  Coverage was inversely correlated with importance: the leaves were heavily
  specified while the trunk was specified inside tombstoned specs (015g,
  034), refactor diaries (025), or nowhere. Each of the five had a live
  defect in the backlog that existed because nothing owned it. Written from
  the code at `6935644` for a reader with no code access — numbered FRs,
  G/W/T user stories, and a Testing Requirements map from FR group to test
  module. Writing them found 30 divergences between the code and the
  documents describing it, each filed as an unchecked task with a Testing
  Requirements block rather than fixed in the same PR; the sharpest are that
  ARCHITECTURE and CONTRIBUTING both name a dispatch-module path that has
  never existed, `./vault write` is documented as shipped and cannot run,
  and the note template the framework ships fails the validator the
  framework ships (#226). (#275)

- **`.specify/templates` are the project's own, and a guard checks them
  against the real parsers.** (test:
  `tests/docs/test_specify_templates_are_ours.py` — 16 tests) The written
  process was model-grade and the templates it ran on were stock spec-kit, so
  the project's own required sections were known only by imitation: the
  tasks template said a `### Testing Requirements` block "SHOULD" be present
  and demonstrated none, and the spec template never mentioned the
  `## Acceptance coverage` section its own guard requires. Both now carry
  what they ask for — `MUST`, a working sample block, and a coverage table
  with the three evidence forms documented. The guard checks them against
  `scripts/foreman/verify_test_coverage.py`'s parser and the
  acceptance-coverage guard's own regexes rather than a copy of what those
  are believed to want, which immediately found two defects in this PR's own
  first draft: a sample block whose bracketed placeholder path the foreman
  rejects, and a coverage heading with a parenthetical after it that made the
  section invisible to the guard. The 20 pre-convention specs that carry no
  block are named in a shrink-only list rather than retro-fitted with a
  block that would claim to have been authored before work that shipped
  months earlier. (#282)

- **`docs/prompts/`: every live prompt reproduced verbatim or hashed, and a
  guard that fails when a copy drifts.** (test:
  `tests/docs/test_prompt_corpus_is_current.py` — 15 tests, including
  `test_a_hand_edited_copy_is_detected`, `test_an_orphaned_copy_is_detected`
  and `test_no_prompt_shaped_file_is_unclassified`) Not one of ~20 live
  prompts was reproduced outside the code that built it, so a clean-room
  reimplementer inherited the orchestration graph and the JSON Schemas the
  outputs must satisfy but not one line of the text that makes a model
  produce conforming output. `scripts/render_prompt_corpus.py` now generates
  the corpus from its sources: the eleven Jinja templates are reproduced
  verbatim, because their text is only ever rendered into a generated vault
  and so does not otherwise exist in the repo in the form a model sees; the
  26 `.agents/skills/*/SKILL.md` files are recorded by path and content hash
  rather than copied, because they are already standalone verbatim files and
  a second copy would be the #281 duplication in a new place. The guard runs
  the script in `--check` mode and additionally fails on any prompt-shaped
  file the renderer has not been told how to classify — so the corpus cannot
  quietly stop being complete when the twelfth template lands. (#280)

- **The spec corpus has an index and an archive: 24 history-only folders
  moved to `specs/_archive/`, 58 remain active.** (test:
  `tests/docs/test_spec_index_completeness.py` — 6 tests;
  `tests/spec/test_acceptance_coverage_guard.py::test_archived_spec_is_not_discovered`,
  `::test_archiving_is_the_only_thing_that_exempts_that_spec`,
  `::test_a_folder_merely_named_like_the_archive_is_still_graded`,
  `::test_the_repo_archive_actually_holds_specs`) 82 folders sat under
  `specs/` with no table of contents and no way to tell a live spec from a
  tombstone without opening each `spec.md`. The corpus is now two sets with
  a stated rule between them: `specs/README.md` indexes both and writes down
  the numbering rule (numbers allocated once, never reused, never changed by
  a move; the `015a`–`015h` letter suffixes are closed), and
  `specs/_archive/README.md` states the rule that put each folder there —
  tombstoned/superseded, pre-format 0.2.x problem statement, 015x
  consolidation draft subsumed by ADR-0009, vault-instance plan, or refactor
  diary — *and* that no tracked file outside `specs/` opens a file inside it.
  Every move is a `git mv`, so `git log --follow` still reaches the history
  and every folder keeps its `NNN-kebab-name`; every in-repo citation was
  re-pointed at the new path. The acceptance-coverage guard skips the
  archive by path segment rather than by a folder allowlist, so it cannot
  fail open the first time someone forgets to update a list, and a test
  asserts the archive is non-empty so the exclusion can never be exempting
  nothing. (#274)

- **Constitution amended to v1.5.0** (`.specify/memory/constitution.md`;
  ratified 2026-04-16, last amended 2026-09-03). MINOR — two principles
  added, two sections added, and one enforcement downgrade. Docs only;
  no code, no spec, no ADR. (no test: governance documentation; the
  repo has no docs-consistency guard that reads this file)

  - **Principle I's gate table is repaired.** It named `pytest
    scripts/tests/`, a directory that has never existed in 400 commits
    (inherited from spec 001's unbuilt intent that a generated vault
    ship its own suite; `generator/scripts.py` copies files only, so no
    generated vault ever received one). Of the nine rows, two named a
    script documented as never failing, three named scripts whose exit
    codes the caller discards, and the "full suite" row overstated
    Phase 3. The table now records the effect of failure per row —
    Blocking, Report-only or None — and two gates block on every path:
    `validate_cycle.py` via `postprocess.py`, and the Phase-3
    coverage-targets gate.
  - **New § Enforcement Register** — invariant → mechanism → failure
    mode → status, one row per principle, with the PR gate's actual
    contents stated up front. **2 Enforced, 6 Partial, 3 Review-time
    only, 1 Not met.**
  - **New § Cross-Repo Obligations** and **Principle XI** — contracts
    are mirrored in each participating repo and guard-synced, not held
    in a shared fourth repo. Five contracts registered.
    `platform-constitution.md`, cited in three repos and existing in
    none, is retired.
  - **New Principle XII (NON-NEGOTIABLE)** — a phase named for
    inspection does not mutate what it inspects; repair is a separate,
    opt-in, operator-invoked verb through the canonical codec. Derived
    from new failure-record entry **F9**, which is the defect fixed
    below in PR #210.
  - **The delegation to `vault-generator-framework.md` is replaced.**
    That document is absent from this repo; schemas, frontmatter fields,
    defaults and CLI flags now name their real present authority, and
    the constitution may no longer delegate to a document that does not
    exist. The F1–F8 failure record is likewise now held here.
  - `plan-template.md`'s Constitution Check was stock spec-kit
    boilerplate; it is now twelve real gates. `tasks-template.md` no
    longer says tests are optional, and carries the `### Testing
    Requirements` block contract that the foreman parses.
  - `CONTRIBUTING.md` §7 gains the rule that an enforcement downgrade is
    a MINOR bump. Constitution version pointers in `README.md` and
    `CLAUDE.md` corrected from the stale v1.3.4.

- **`pipeline.budget_usd: 0` now means UNLIMITED, not a zero-dollar cap.**
  (test: tests/cli/test_budget_usd_zero_is_unlimited.py) A **contract
  change**, decided by the owner on 2026-09-07 and recorded as an amendment
  at the foot of `specs/061-cycle-budget-config/spec.md`. Spec 061's
  `_resolve_usd` returned a literal `0.0` and left the meaning to whoever
  read it next: `orchestrator.run_cycles` guards on
  `cumulative >= budget_cap > 0` and so read it as uncapped, but nothing
  said so and a second reader was free to read the same value as "spend
  nothing" and stop a run before its first dispatch. Every one of the six
  shipped profiles carried `budget_usd: 0.0` until #230, and every vault
  generated from one ran, so "uncapped" is the meaning the corpus already
  carries; the resolver now says it at the one place the value is decided.
  Zero on the `--max-usd` rung means the same thing — one ladder with two
  meanings of zero would be a silent disagreement between its own rungs,
  the class of bug spec 061 exists to remove. Provenance survives: an
  explicitly configured zero still reports `max_usd_source: "settings"`.
  Unchanged: a negative settings value is still ignored, a negative flag is
  still a usage error, `limits.cycle_budget_usd` must still be **positive**
  (a different key, a different rule), and the real ceilings #317 seeded
  into every shipped profile stay as they are. The `budget_usd` comment in
  all six `settings*.yaml` profiles now states the rule instead of pointing
  at the orchestrator's `> 0` comparison.

### Fixed

- **Three run verbs, three budget stories: `cycle`'s hardcoded $10.00 default
  bypassed the spec-061 ladder entirely.** (test:
  tests/cli/test_cycle_verb_budget_ladder.py,
  tests/cli/test_lifetime_vs_per_run_budget.py) Spec 061 SC-001 says the
  per-cycle budget is settable in "exactly ONE settings location and ONE CLI
  flag". That was true of `generate` and false of the framework: `cycle`
  carried a `--budget-cap` default of $10.00 in `cli/_parser.py` and a
  `max_cycles=5` two layers down in `orchestrator.run_single_cycle` /
  `cycle_runner.run_cycle_steps` — the fourth and fifth budget knobs the spec
  was written to eliminate, reachable by *omitting an argument*, the most
  invisible rung there is. Both entry points now take `None` and resolve
  through one shared backfill (`_budget_resolve.fill_missing_run_budget`), and
  `cycle` resolves the ladder like every other verb. The quality harness is the
  one caller that deliberately does not: it pins `HARNESS_BUDGET_CAP_USD` /
  `HARNESS_CYCLE_CEILING` explicitly, because a regression baseline must
  measure the pipeline, not whichever ceiling this month's `settings.yaml`
  carries. `pipeline`'s refusal (#232) stands and now names the ladder to use
  instead. (#233)

- **`cycle` walked straight past a standing pause marker and re-spent.** (test:
  tests/cli/test_cycle_verb_budget_ladder.py::test_cycle_refuses_to_run_over_a_standing_budget_pause,
  ::test_cycle_refuses_to_run_over_a_standing_approval_pause,
  ::test_cycle_refusal_survives_an_unreadable_marker) Only `generate --resume`
  ever read `BUDGET_PAUSED` / `APPROVAL_REQUIRED`, so running `cycle` after a
  pause re-dispatched the paused stage and paid for it a second time — the same
  double-spend `budget-marker.contract.md` §4.5 was amended to stop, reached
  through a different verb. `cycle` has no `--force-budget` / `--approve`
  surface and so is in no position to decide a pause: it refuses with exit 2,
  names the marker's path, `pause show`, and the resume that can clear it, and
  leaves the marker byte-identical. Contract §5.2 documents the rule for any
  such verb. (#233)

- **`--max-usd` and `--max-cycles` advertised themselves as per-run budgets
  while being lifetime ceilings.** (test:
  tests/cli/test_lifetime_vs_per_run_budget.py::test_lifetime_flags_no_longer_advertise_themselves_as_per_run)
  `--max-cycles`' help said "Per-run cycle cap" while `run_cycles` iterates
  `range(start_cycle, max_cycles + 1)` — an absolute cycle NUMBER, which spec
  070 F5 already said in an error message the flag's own help contradicted.
  `--max-usd`' help said "Per-run dollar cap" while the guard compares against
  `_cumulative_sidecar_cost(up_to=cycle)`, every cycle the vault ever ran. The
  semantics were not wrong; the names promised the other ones. Both now say
  "lifetime", and `--max-cycles` points at `--more-cycles` for the reading a
  user expects. (#239)

- **The TTY approval prompt asked for consent without showing the cost.**
  (test: tests/cli/test_approval_prompt_shows_cost.py)
  `approval-marker.contract.md` §5.1 is two steps — "display stage, tier,
  `estimated_cost_usd`, `cumulative_spend_usd`, `prompt_preview`", THEN prompt
  — and only the second existed. The operator approved a paid dispatch with no
  idea what it cost, what the cycle had already spent, or which tier it would
  run on, all of which the marker had persisted at write time. The summary now
  precedes the prompt on stderr (spec 070 FR6's stream rule), including the
  projected cycle total, which is computed at render time rather than stored —
  a derived number in a versioned on-disk schema would give a later reader two
  sources for one fact. Shown before a flag-driven TTY `--approve` too; not
  before `--reject`, which is a decision already taken. The headless refusal
  body is untouched: §5.2 step 4 pins it. Contract §5.1a makes step 1
  normative. (#236)

- **A zero `--budget-cap` meant "spend nothing" inside `validate_cycle.py`.**
  (test: tests/scripts/test_validate_cycle_zero_budget_is_unlimited.py) Spec
  061's FR3-Z amendment settled that a zero dollar budget is UNLIMITED, and the
  orchestrator's `cumulative >= budget_cap > 0` guard already read it that way.
  `validate_cycle.py` is the third reader and disagreed: Condition C is a bare
  `cumulative_cost >= budget_cap`, so a zero TERMINATEs the cycle before its
  first note. It had never been handed one, because `cycle --budget-cap`
  defaulted to $10.00; routing that verb through the ladder is what exposed it,
  which is exactly what one ladder is for. Both the v1 and v2 validators now
  skip the derived comparison when no real ceiling is configured. An explicit
  `termination: "C"` in a report is the scout's own testimony and still stands.
  (spec 061 FR3-Z5) (#233)

- **`approval_gates_fired` was `[]` in every real cycle report.** (test:
  tests/cli/test_research_resume_approval_decisions.py,
  tests/pipeline/test_approval_decision_record.py) The operator's verdict is
  taken in the CLI process at resume time (`cli/budget_resume.py`); the cycle
  cost report that must show it is written much later, deep inside
  `pipeline/cycle_runner.py`, from a budget session that never sees the CLI's
  arguments. Nothing joined the two, so `append_cycle_cost_report`'s
  `approval_gates_fired` keyword was passed by no production caller and the
  field was always empty — while the tests that "covered" it supplied their
  own rows, which is how a dead clause stayed green. The two halves are now
  joined by `_pipeline/approval-decisions.json`: a schema'd, atomically
  written (#314) append-only record of approval-marker contract §6 rows,
  written by every branch where a person actually said yes or no (a
  rejection included, per §5.4) and read back per cycle by the reporter. The
  branches that merely refuse to guess — no `--approve`, a stage mismatch, a
  missing env ack — record nothing: "you gave me no flag" is not a verdict.
  A record this build cannot parse is never truncated to make room for a new
  row; the write declines with a WARNING and the resume proceeds. The
  reporter's keyword argument is removed rather than kept as an override — a
  parameter no caller passes is the defect itself. Contract §6.1 documents
  the record. (#235)

- **`paused_stage` was written into every `BUDGET_PAUSED` marker and read by
  no code, so a resumed cycle re-paid for stages it had already bought.**
  (test: tests/pipeline/test_stage_level_resume.py,
  tests/cli/test_research_resume_stage_resume.py) budget-marker contract
  §4.5's "continue cycle from `paused_stage`" was unimplemented: a cycle that
  paused at the note-writer re-dispatched scout on resume — real money
  re-spent on work already paid for, which is the very thing the caps exist
  to prevent. Resume now restarts the cycle at the **phase** the paused stage
  belongs to (`scout` → scout; `note_writer`/`verifier` → research), skipping
  every phase before it. A skipped phase still yields its result, rebuilt
  from that phase's own on-disk report by `scout_result_from_disk` /
  `research_result_from_disk` — the same collector `run_scout`/`run_research`
  always used, minus the dispatch. An **unmapped** stage re-runs the whole
  cycle with a WARNING naming it: skipping on a name this build cannot place
  would drop work, while re-running only re-spends money. The plan is
  in-process, keyed by cycle and popped on use — a stale plan on disk would
  silently skip phases of an unrelated later run, and popping is also what
  keeps a CG-001 retry honest, since a retry exists because the cycle
  under-produced. Batch-level resume within a stage is out of scope: the
  marker records no batch index. Contract §4.5 is amended to state all of
  this. (#235)

- **`pipeline status` hid the persisted `errors[]` and every phase's
  duration, and had no explicit `--json`.** (test: tests/pipeline/test_runner.py::TestStatus's
  new duration/error cases, tests/cli/test_pipeline.py::TestPipelineStatusCLI's
  new text/json cases) `pipeline.runner.status()` already read
  `errors[]` off `pipeline-state.json` but dropped `started_at`/
  `finished_at` entirely, and the CLI's TTY-only renderer printed neither
  the errors nor a duration — so a correctly-recorded failure reason was
  invisible through the one command an operator would use to ask why a
  run failed. `status()` now returns each phase's `started_at`,
  `finished_at` and a derived `duration_s` (`None` when the phase never
  finished, never a wrong number); the CLI renders both, plus the full
  `summary` dict (previously truncated to its first three keys, which cut
  off the `agent_log` / `report_path` fields #318 added to several
  phases) and each persisted error, one per line. Format is now the
  explicit `--json` flag rather than an inference from `sys.stdout.isatty()`
  — every cron/launchd invocation of `pipeline status` is a pipe, and used
  to be silently forced into JSON with no way to ask for the
  human-readable form instead, or vice versa on a real terminal. Also
  corrects `run_finish`'s docstring: it does not "skip research if the
  queue is empty" — it never runs research at all (the equivalent fix to
  the generated vault shim's wording is tracked separately under #215).
  (#245)

- **The top-level `research-framework status` had no idea a `pipeline`
  run had ever happened.** (test:
  tests/observability/test_vault_status.py::test_inactive_surfaces_pipeline_state_when_no_cycles_exist,
  ::test_json_surfaces_pipeline_state,
  ::test_json_pipeline_is_none_when_no_pipeline_run_happened,
  ::test_active_cycle_state_still_reports_pipeline_state_alongside)
  `status` (spec 048) reads only
  `_pipeline/state.json` (the `cycle`/`resume` world) and the
  `cycle-NNN-summary.md` files under `_pipeline/cycles/`; a vault driven
  entirely through `pipeline full` writes neither, so it reported
  "(no cycles yet)" no matter how many pipeline runs it had, or how badly
  they had failed. `build_status_json` and `render_inactive` now also
  read `_pipeline/pipeline-state.json` (via `pipeline.runner.status`, the
  module that already owns that file's shape) — surfaced as a `pipeline`
  key in the JSON output always, and as a phase-by-phase text block
  (falling back to the pre-existing cycle-based rendering, which already
  has an answer, when there's no other cycle history to report). (#245)

- **A constrained exit with zero commits stranded an empty
  `research/<ts>` branch, once per invocation.** (test:
  tests/pipeline/test_land_constrained_run.py::test_a_run_with_nothing_committed_is_not_landed,
  ::test_a_run_with_nothing_committed_and_auto_merge_off_is_still_dropped,
  tests/pipeline/test_orchestrator_resume_ceiling.py::test_resume_past_ceiling_with_zero_commits_drops_the_empty_branch)
  Spec 072 FR1 promises "any terminal exit lands and checks main out",
  but `vault_commit.complete_run`'s `final_rc == 1` handling only covered
  the case where `ctx.cycle_commit_shas` was non-empty (squash-merge,
  retain branch); a constrained exit that committed nothing fell through
  to the generic "nothing landable" branch, which leaves the branch in
  place "for review" — except there is no per-cycle history on it to
  review. This is exactly the spec-070 F5 path (a `--resume` anchored
  past `--max-cycles` returns rc=1 before running a single cycle), so it
  reproduced routinely rather than as an edge case. `complete_run` now
  checks `ctx.base_branch` back out and deletes the empty branch whenever
  `final_rc == 1` and nothing was committed — independent of
  `vault_commit.auto_merge`, since that flag gates whether *content*
  auto-lands and there is none here either way — clearing the run-commit
  state the same way a clean (rc=0) landing does, and targeting the base
  branch rather than the just-deleted one for the best-effort push. The
  orchestrator-level test drives the real `run_cycles` entry point
  against a git-backed vault rather than calling `vault_commit` directly,
  so the fix is pinned against the actual reproduction, not just the
  narrower unit contract. (#250)

- **Verify counted every structural flag equally, so orphan flags alone
  tripped FAIL.** (test:
  tests/processors/test_verify_flag_classes.py::TestOrphansDoNotFailAVault,
  ::TestFlagClassesAreOnTheResult, ::TestTheReasonNamesWhatCounted)
  The verdict was
  `structural_flags / notes_checked > fail_threshold` with no term for what
  a flag meant, so a note nobody has linked yet weighed as much as
  frontmatter that will not parse and a young or lightly-linked vault
  failed **by construction** — 14 orphans over 18 notes fail a committed
  fixture on their own, and the real feeds-vault scored 840 notes / 9066
  flags. Every flag now carries a `class`. `content` is what only the
  vault's author can fix and is the only thing measured against
  `fail_threshold`; `tooling` is the framework's own bookkeeping —
  orphans, MOC gaps, the two keys verify auto-fixes itself, and the
  `[[Note Name]]` residue its own templates emit. Tooling flags are still
  reported, still counted, and still reach WARN: not fatal is not the same
  as invisible. The threshold sentence in `errors` now names both halves,
  and `VerifyResult` / the report / the phase summary carry
  `content_flags` and `tooling_flags`. (#225)

- **Verify ignored `verifier_status: exempt`, alias stubs and wikilink
  case.** (test:
  tests/processors/test_verify_flag_classes.py::TestExemptNotesAreHonoured,
  ::TestAliasStubsAreNotOrphans, ::TestWikilinkCaseIsFolded)
  The vault format already defines an opt-out
  and an alias node, and `pipeline/wikilinks.py` stamps both onto every
  acronym redirect stub the framework generates — verify graded them
  anyway, so the framework's own generated files came back to their author
  as orphan flags. Worse, wikilinks resolved case-sensitively against
  ADR-0005, which decided in 2026-05 that `[[Cassandra]]` and
  `cassandra.md` are one node: a vault mid-normalisation scored every case
  variant as a broken link **and** an orphan, two flags for one node the
  normaliser was about to fix. Exempt notes and alias stubs are now
  counted in `notes_checked`, never flagged, never auto-fixed and never
  orphaned, while remaining link sources and link targets; wikilink
  resolution is case-folded throughout, including MOC membership. The
  evidence this was tooling noise rather than vault damage was a report
  agent having to reverse-engineer the checker to say so. (#227)

- **Verify was feeds-vault-shaped, not spec-driven: the shipped note
  template could not satisfy its own checker.** (test:
  tests/processors/test_verify_note_format.py) `processors/verify.py` was
  ported from one vault's `scripts/verify.py` and kept that vault's schema
  as module constants — `summary`/`status`/`related` as the required
  frontmatter, `MOC_TO_FOLDERS` naming folders like `13 - AI Tools`. The
  framework's own `templates/note-type.md.j2` declares `type`,
  `template_version`, `source_urls` and `coverage_category` and **no
  `summary`**, so every note the framework generated flagged
  `missing_summary` on sight and the weekly pipeline's verify phase was a
  guaranteed FAIL on every vault the framework itself produced. The
  required frontmatter is now resolved — explicit argument > the spec's
  `processors.verify.required_frontmatter` > the vault's own `_templates/`
  > the historical `summary` — where "what the template declares" means
  the keys it leaves EMPTY for the writer to fill. That is not a new
  contract: it is the one `gates_step.SG005_frontmatter_completeness`
  already enforces at note-write time, and `summary: ""` joins the shipped
  template so the two sets are now identical and a test pins that they
  stay identical. The MOC folder map is derived the same way from the
  vault's declared `note_types`; a vault that declares nothing keeps the
  legacy map, which still describes the vault it came from. Dead constant
  `CONTENT_FOLDER_PREFIXES` removed. Still open on #226: the wider
  contract change (grading `required_sections`, deriving MOC coverage from
  `coverage_targets`, a note-type-aware verdict) wants the spec the issue
  itself asks for. (#226)

- **The pipeline's verify phase never passed `spec_processors`, so a
  vault's own `processors.verify` config was ignored by the one phase that
  reads it.** (test:
  tests/pipeline/test_runner_verify_verdicts.py::TestSpecConfigReachesTheProcessor)
  `verify.py`'s docstring has promised since the processors moved into the
  framework that `fail_threshold` is honoured "when spec_processors config
  is supplied"; `_drive_verify` called `verify(_corpus_dir(vault),
  auto_fix=False)` and supplied nothing. It now reads the `processors` and
  `note_types` sections out of `_pipeline/spec-parse.json` — already
  parsed, already read two lines later for the corpus dir — and passes
  both down along with the vault's `_templates/`. `auto_fix=False` stays
  an explicit argument so the phase's no-mutation guarantee still wins the
  precedence ladder against a spec that asks for auto-fix, and an
  unreadable spec-parse leaves the processor's defaults in charge rather
  than failing the phase. (#228)

- **No test exercised `_drive_verify`'s FAIL path; every `VerifyResult`
  fixture was PASS.** (test:
  tests/pipeline/test_runner_verify_verdicts.py) The live failure mode —
  FAIL verdict → phase `failed`, rc 1, with what error content — was
  unpinned, which is why the empty-`errors` defect survived long enough to
  be filed separately: the runner tests mocked `processors.verify.verify`
  out entirely with a passing result, so an always-FAIL verify was
  invisible to them. Fifteen cases now cover FAIL, WARN, PASS and the
  raising-processor ERROR path, including the rc and the reason text, and
  the last two drive the **real** processor over a real generated vault so
  a mock cannot hide a processor-side regression again. (#229)

- **The changelog regression-link guard read only a bullet's first
  physical line, so every wrapped test annotation in the released
  `[1.1.1]` block failed it.** (test:
  tests/spec/test_changelog_regression_links.py::test_released_wrapped_test_annotation_passes,
  ::test_released_wrapped_regression_tests_plural_passes,
  ::test_multi_path_annotation_with_trailing_prose_passes,
  ::test_nested_sub_bullet_with_its_own_annotation_does_not_double_count,
  ::test_supplementary_annotation_far_later_in_body_does_not_double_count,
  ::test_back_to_back_double_tag_still_rejected)
  `parse_changelog_fixed_bullets`
  captured only the leading `- ` line of each bullet, so any annotation
  that wrapped onto a continuation line (routine once a bullet's own
  bold lead sentence runs long) was invisible — `guard-test-battery`
  reported `FAIL (1 failed, 57 passed)` on a clean `origin/main` for 39
  bullets that are, in fact, fully compliant. The parser now folds a
  bullet's continuation lines into its body (space-joined) until the
  next top-level `- ` or a blank line not followed by further
  continuation, while a nested sub-list (its own `  - ` / `  1. ` items,
  real example: the 0.6.1 "feeds-vault revival post-mortem fixes" entry) is
  skipped rather than folded in, so a nested item's own annotation can't
  be double-counted against its parent. Two further gaps surfaced once
  the whole body was actually read: `(regression tests: ...)` (plural)
  and an `(issue #NNN; regression tests: ...)` lead-in are both real,
  already-shipped spellings the guard's regex never matched; and a single
  annotation may cite more than one test path, comma-separated, with
  plain prose or a bare `::test_name` continuation mixed in — only the
  segments that look like a real path are checked now. A bullet whose
  compliance tag is restated in more granular form much later in its own
  prose (real example: the 0.6.2 "Subprocess timeouts" and
  "raw_capture.py" entries) is elaboration, not a second, conflicting
  classification — only two annotations placed back-to-back (no
  elaboration between them) are still rejected as ambiguous. One
  previously-masked bullet (`CHANGELOG.md:1038`) turned out to have no
  compliant annotation anywhere in its body at all — a genuine content
  gap, not a parsing artifact, left untouched here and tracked as #325.
  (#322)

- **Three fixed-name agent templates hardcoded a renameable command's
  default filename, and nothing rendered them against anything but that
  default.** (test: tests/agents/test_render.py::test_related_frontmatter_follows_a_renamed_research_command,
  scripts/guards/check_agent_asset_references.py) `scout.md.j2`,
  `pipeline.md.j2` and `verify.md.j2`'s `related:` frontmatter each named
  `.claude/commands/research.md` literally, but `research` is one of the
  three commands `spec.settings.commands` can rename (spec 013) — a vault
  that renamed `/research` to, say, `/dig` got a `related:` entry pointing
  at a file `write_agents` never wrote, the same class of two-source drift
  #252 already fixed for `research.md` itself. `tests/agents/test_render.py`
  covered only the default names via a `SimpleNamespace` fixture, which
  can't exercise a rename. The three templates now render the path as
  `.claude/commands/{{ spec.settings.commands.research }}.md`. A new guard,
  `scripts/guards/check_agent_asset_references.py` (registered additively
  in `run_all.py`'s battery as `agent-asset-references`), renders every
  agent template against a REAL `SpecConfig` — not a `SimpleNamespace` fake
  — with `research` deliberately renamed, runs it through the actual
  generator (`scaffold` + `render_all` + `copy_scripts`) into a throwaway
  vault, and asserts every `scripts/*.py`/`*.sh` and structured
  `related:`-frontmatter `.claude/commands/*.md` reference resolves to a
  real file there; it also carries #254's two assertions (no stale "Known
  limitation" text, no baked absolute path) against that real-vault
  render, not only the fake one. The command-reference check is scoped to
  the structured `- path: "..."` frontmatter form rather than every prose
  mention of a `.claude/commands/*.md` path, so it doesn't false-positive
  on `pipeline.md.j2`'s legitimate documentation of the user-created
  `.claude/commands/pipeline.local.md` override file. (#256)

- **Seven of the 20 committed JSON Schemas were referenced by nothing but
  the spec prose that introduced them, and no schema anywhere was
  machine-validated.** (test: tests/contracts/test_json_schema_validation.py,
  tests/scripts/test_agent_call_sidecar_v1.py::test_real_built_sidecar_payload_validates_against_schema,
  ::test_real_written_sidecar_file_validates_against_schema) `jsonschema`
  was not a dependency anywhere in the tree. Took it as a dev dependency
  and wired six of the seven to a test that validates REAL output from the
  production code that writes the artifact (not a hand-typed literal that
  merely looks like the shape): `pipeline-state.schema.json` against
  `runner._blank_state` and a real post-phase-transition
  `pipeline-state.json`; `preflight.schema.json` against a real
  `PreflightResult.to_json_path` write; `validator-yaml.schema.json`
  against a real `load_yaml_validator` read; `agent-call-sidecar-1.1.schema.json`
  (spec 028 — see below) against `agent_call.py`'s actual payload builder
  and its real written file. Wiring `watermark.schema.json` against a real
  `save_watermarks` write caught a real drift the schema had never seen:
  `WatermarkEntry.recent_cycle_verdicts` (added after the schema shipped)
  fails `additionalProperties: false` on every real `watermarks.json` —
  the schema now declares it. Issue #295 reported `tiers.schema.json` and
  `consensus-result.schema.json` as having no writer at all; re-verifying
  against HEAD found that stale — `settings.py::_parse_tiers` (a real,
  hand-validated `settings.yaml::tiers` surface) and
  `source_bridge.consensus.write_consensus_result` (called from
  `source_bridge/orchestrator.py`, writing
  `_pipeline/sources/<module>/consensus/*.json`) are both live, so both
  are wired here instead of deleted — no schema in the original seven
  actually lacked a real artifact once checked against current code, so
  none is deleted. The seventh, `agent-call-record.schema.json` (spec
  020), describes a shape the shipped sidecar writer never actually used
  — the real `agent-calls/` directory has always matched spec 028's shape
  (`tests/fixtures/contracts/agent-call-sidecar-1.1.schema.json`, already
  tested); it now carries a `$comment` tombstone naming the schema that
  matches reality, rather than being deleted, since the directory it
  names is real. (#295)

- **`pipeline <vault> resume` ended silently, with no guidance that `finish`
  (verify + report) is a separate, still-required step.** (test:
  tests/pipeline/test_runner.py::TestRunResume::test_resume_success_prints_finish_as_the_next_step,
  ::test_resume_failure_does_not_print_finish_guidance,
  ::test_resume_quiet_suppresses_finish_guidance) Issue #245 split `resume`
  (research only) from `finish` (verify + report) on purpose, but the only
  printed "then:" trail anywhere in `runner.py` is `full`'s, and it names
  `resume` — never `finish`. An operator who ran `full`, triaged, then
  `resume`, had nothing on screen telling them a second verb existed; `[4/6]
  research ...` just ended. `resume` now prints "Then: ... finish" on a
  successful, non-quiet run. (#285)

- **`generate --approve` / `--approve-all` / `--reject` / `--force-budget`
  were silently accepted no-ops outside `--resume`.** (test:
  tests/cli/test_generate_resume_only_flags.py) The four flags live on the
  `generate` subparser and are documented in its `--help`, but
  `_cmd_generate` only ever reads them from inside the `--resume` branch
  (spec 033's approval gates and budget pauses are markers written mid-run;
  a fresh `generate` has no run yet to approve, reject or force past).
  Passing one without `--resume` did nothing and said nothing. `generate`
  now refuses with exit 2 and names the flag, the same way the neighbouring
  `--dry-run`/`--resume` mutual-exclusion check already does. (#286)

- **The canonical frontmatter parser silently discarded a note's frontmatter
  on a CRLF line ending or a leading UTF-8 BOM.** (test:
  tests/vault/test_frontmatter.py::test_crlf_line_endings_do_not_lose_frontmatter,
  ::test_utf8_bom_does_not_lose_frontmatter,
  ::test_utf8_bom_with_crlf_does_not_lose_frontmatter,
  ::test_bare_cr_line_endings_do_not_lose_frontmatter) `parse_frontmatter`
  read the file in binary mode and compared the first 4 bytes against the
  literal `b"---\n"`; a CRLF or a BOM shifted those bytes and the file was
  treated as having no frontmatter at all — `related`/`coverage_category`
  lost, SG-005 failing with no parse error to explain why. Every other
  reader in this codebase already reads notes through `Path.read_text()`,
  which normalizes line endings for free; `parse_frontmatter` now does the
  same, plus `utf-8-sig` for BOM stripping. (#287)

- **Broken-wikilink severity and hub detection counted link occurrences,
  not distinct citing notes.** (test:
  tests/processors/test_verify.py::test_repeated_broken_link_in_one_note_is_one_flag_not_one_per_mention,
  ::test_repeated_broken_link_from_one_note_is_low_severity,
  ::test_broken_link_severity_scales_with_distinct_citing_notes,
  ::test_hub_notes_counts_distinct_citing_notes_not_mentions,
  ::test_hub_notes_fires_for_three_distinct_citing_notes) `verify`'s
  first pass counted every wikilink occurrence per note as a separate
  citation, so a single note mentioning `[[X]]` four times made X a
  "critical" broken link (`ref_count >= 4`) and a "hub" (`>= 3`), and
  `_find_broken_wikilinks` emitted one flag per occurrence — inflating
  `structural_flags` toward the FAIL threshold for one author's habit, not
  four corroborating notes. Links are now deduped per citing note
  (case-folded, per ADR-0005) before counting. (#287)

- **`_graph.md` gave a note with zero outgoing links an edge to every other
  note in the vault.** (test:
  tests/pipeline/test_indexer.py::TestRebuildAllUs6::test_graph_gives_a_zero_outdegree_note_no_edges)
  The "fallback: all notes" branch in `rebuild_all` meant an orphan note's
  graph section rendered as citing the entire vault — the opposite of the
  truth, disagreeing with `inbound_link_counts` (documented to read the
  same `_outgoing_links` edge set) and O(n^2) noise in a large vault.
  Nothing documented it as intended, and nothing needed it: a note with no
  outgoing links now renders with no targets. (#287)

- **Guard battery gaps: untested detection logic, an asymmetric smoke-gate
  check, a portability-guard coverage gap, dead maintainer scripts shipped
  to every vault, a permanently-skipped placeholder test, and an
  unsalted quality-harness work root.** (test:
  tests/quality/unit/test_marker_isolation.py::test_detection_logic_flags_a_missing_marker,
  tests/quality/test_baseline_update_isolation.py::test_detection_helpers_flag_a_disallowed_baseline_write,
  tests/build/test_smoke_gate_enforces_contract_tier.py::test_required_in_gate_has_no_untracked_smoke_entries,
  tests/scripts/test_portability_guard.py::test_root_shell_entry_points_and_vault_shim_template_are_in_scope,
  tests/generator/test_copy_scripts_merge.py::test_copy_scripts_excludes_maintainer_only_migration_scripts,
  tests/quality/unit/test_work_root_isolation.py,
  tests/benchmark/unit/test_marker_isolation.py::test_detection_logic_flags_an_unmarked_live_dispatch_call)
  Six rf-assurance findings: (1) "marker isolation ×2" is
  `tests/quality/unit/test_marker_isolation.py` AND
  `tests/benchmark/unit/test_marker_isolation.py` — both, plus
  baseline-write-isolation, had a fail-closed vacuous-scan test (#278)
  proving their scan surface wasn't empty but never exercised the
  detection primitives against a known violation — added one each (the
  build-exclusion guard's checks are plain substring
  tests with no comparable logic to pin, left alone); (2)
  `REQUIRED_IN_GATE` only asserted itself a subset of `build.sh`'s
  `SMOKE_TESTS`, so 7 already-shipped ship-blocking entries
  (`test_fixture_isolation`, `test_coverage_recompute_regression`,
  `test_wikilink_corruption_regression`, `test_vault_update`, the three
  `tests/observability` files) could be de-listed from `build.sh`
  invisibly — added them and a reverse-direction test so the two sets can't
  drift apart again; (3) `scripts/check_portability.py` and CI's shellcheck
  step never scanned `install.sh`, `generate_vault.sh` or
  `templates/vault-script.sh.j2` (the source `./vault` renders from in every
  generated vault) — added all three to the Python guard (verified clean)
  and the two pure-shell scripts to CI's shellcheck list (the `.j2` template
  is Jinja, not valid shell, so shellcheck can't parse the template source —
  left to the Python guard, which is unaffected by Jinja markup); (4)
  `scripts/_tmp_diff.py` (throwaway debug scratch) and
  `scripts/_migrate_budgetconfig_spec061.py` (its own docstring: "Run once,
  eyeball the diff, then delete") shipped into every generated vault and
  release bundle — deleted; `scripts/_migrate_prints_spec048.py` is
  deliberately "committed for auditability" (its own docstring) so it stays
  in the repo but is now excluded from `copy_scripts`; (5)
  `tests/scripts/test_install_idempotency.py::TestUserAuthoredPreservation`
  was a permanently-`@pytest.mark.skip`-ped placeholder "gated on spec 027" —
  spec 027 shipped, but at a different surface (`vault_update.is_user_owned`,
  checked by `./vault update`, not `install.sh`, which never writes
  `settings.yaml` at all); the real scenario is already covered end-to-end by
  `tests/cli/test_vault_update.py::test_user_owned_file_survives_upgrade`, so
  the placeholder is removed rather than rewritten against a surface with
  nothing to test (also closes the identical #290 finding); (6) the quality
  harness's work root was one process-independent constant that
  `isolate_fixture` `rmtree`s then `copytree`s into — two concurrent harness
  invocations in one checkout could `rmtree` out from under each other
  (reported PLAUSIBLE, not reproduced in isolation); salted with
  `os.getpid()` so concurrent processes can no longer collide. (#288)

## [private 1.1.1] - 2026-09-04

### Fixed

- **Every shipped settings profile disabled all of spec 033's cost
  enforcement.** (test:
  tests/pipeline/test_shipped_profiles_enforce_budget.py, parametrized over
  every committed `settings*.yaml`) None of the six profiles declared a
  `limits:` block, and all six set `pipeline.budget_usd: 0.0`. Both spellings
  mean "uncapped": `budget_guard` skips any limit that is `None`, and the
  orchestrator's cumulative guard is `cumulative >= budget_cap > 0`. A
  headless `generate` / `--resume` against a freshly generated vault — which
  copies the bundled `settings.yaml` verbatim — therefore ran with no dollar,
  token or wall-clock ceiling at all. Every profile now seeds
  `limits.cycle_budget_usd`, `limits.cycle_budget_warn_at` and
  `limits.cycle_wallclock_budget_minutes` (the metered-token runtimes also
  seed `limits.codex_token_budget`) and a non-zero `pipeline.budget_usd`.
  The dead top-level `budget:` block — never read by the settings loader,
  landing silently in `VaultSettings.extras` — is deleted, so `limits:` is the
  one place a cap is written. (#230)

- **Resuming from a budget pause re-checked only the dollar cap and cleared
  every other marker.** (test:
  tests/cli/test_research_resume_budget_reasons.py,
  tests/pipeline/test_budget_markers.py::test_budget_marker_schema_rejects_an_unknown_schema_version)
  `handle_budget_marker_on_resume` loaded the `BUDGET_PAUSED` marker,
  discarded it, re-summed sidecar dollars and deleted the marker. A pause
  written for `wallclock_exceeded` or `codex_token_cap_exceeded` was therefore
  cleared by a dollar cap the run had never come near — silently, with rc 0
  and no output — and `validate_budget_paused_marker` had zero production
  callers, against `budget-marker.contract.md` §4.2. Resume now validates the
  marker (a bogus `pause_reason`, an unknown `schema_version`, a missing
  required field or unparseable JSON is REFUSED with the marker retained, and
  is not forceable), re-checks the cap named by `pause_reason` and only that
  one, and prints an acknowledgement naming what it re-checked. The
  metered-token cap is re-tallied from the cycle's sidecars
  (`sum_sidecar_metered_tokens`). The wall-clock cap is re-tested against the
  elapsed the marker recorded, because `CycleSpendTally.cycle_started_mono` is
  a `time.monotonic()` reading that cannot survive the process — reading it as
  "the clock restarts" is exactly what made a wall-clock pause free to walk
  past. (#231)

- **`pipeline --budget-cap` was accepted, documented as forwarded, and never
  read.** (test:
  tests/cli/test_pipeline.py::TestPipelineBudgetCapIsRefused) `run_full` took
  a `budget_cap` parameter, the parser advertised it as "passed to agent
  invocations", and no code in `runner.py` consumed it — the fifth instance of
  the "config accepted and silently ignored" class the 1.1.0 CHANGELOG
  records. It cannot be honoured yet: no `pipeline` phase passes
  `--cost-sidecar` (#220/#221), so no spend record exists to check a cap
  against. Following spec 074's precedent, the flag is now REFUSED with exit 2
  and a message naming the surfaces that do enforce a cap
  (`limits.cycle_budget_usd`, `cycle --budget-cap`), for every `pipeline`
  subcommand. `run_full`'s dead keyword is gone. (#232)

- **The verifier stage dispatched without `--cost-sidecar`, so per-note
  verifier spend was invisible to the budget guard.** (test:
  tests/pipeline/test_verifier_cost_sidecar.py::test_verifier_spend_is_tallied_by_the_budget_guard)
  `_call_verifier` passed `--output-file` and nothing else, so the one stage
  that dispatches once per note written produced no telemetry: the dollar cap
  could be blown past by verifier calls alone, and the run report showed none
  of the spend. The fake agent masked it in tests because a fake call costs $0
  either way. Each call now writes
  `cycles/cycle-NNN/agent-calls/verifier-<n>.json` — the only directory
  `budget_guard.list_sidecars_v11` globs — numbered per dispatch so a skipped
  note leaves no gap and no two calls collide. The tests assert the guard's
  own tally, not merely that a file appeared. (#234)

- **`collect` was a no-op on every real vault and still reported `done`.**
  (test: tests/pipeline/test_runner_collect_sources.py) The phase runs one
  collector — RSS, from a `sources.yaml` no vault has — and logged every
  declared web / GitHub / arXiv / Reddit source "not yet implemented" at
  `INFO`, invisible under the non-TTY `WARNING` default, and only for the four
  kinds a keyword guess happened to recognise. It then reported `done,
  items_new=0`: 7 of 7 vaults on 2026-09-01, with a downstream report saying
  "No context tree available". The phase now records `declared_sources` and
  `unsupported_sources` (name plus access method) in its summary, names them
  at `WARNING`, and — when it collected nothing *because* it cannot read what
  the spec declares — records `SKIPPED` with a reason rather than `done`. An
  honest zero (an empty feed, or a vault declaring no external sources) stays
  `done`, and a partial collection stays `done` with the warning. Routing
  `collect` through the spec-020 `source_bridge` modules is the larger fix
  ADR-0009 pointed at and needs the runner's owning spec (#50) first. (#223)

- **The scout, research and report phases were marked `done` on the agent's
  exit code, with no artifact check.** (test:
  tests/pipeline/test_runner_phase_artifacts.py) The runner never checked that
  `scout-report.json` / `research-report.json` existed, that they parsed, or
  that a single note had been written — so on the 2026-09-01 fleet run
  reference-vault's research phase ran for 34 seconds, wrote nothing, and is
  recorded `done`. A phase is now done only when the artifact the NEXT phase
  reads is on disk and carries the field that phase needs: scout ⇔
  `topics_found.new` is a list, research ⇔ notes were written or the queue was
  provably empty (recorded as an explicit `empty_queue_reason`, so "nothing to
  research" stays distinguishable from "researched nothing"), report ⇔ an
  export exists under `_pipeline/exports/`. The counts land in the phase
  summary, and a declared `data_source` the scout did not consult — the shape
  reference-vault produced for web, GitHub and official docs, all `searched: false`
  — is now named at `WARNING` and recorded as `sources_not_consulted`, the
  check the cycle path has had since spec 019 and the pipeline path never did.
  `tests/_helpers/fake_agent.py`'s scout handler now writes the flat
  `scout-report.json` the runner's prompt names, alongside the cycle-numbered
  copy, closing for scout the hole issue #261 closed for research and report.
  (#222)

- **The pipeline runner's agent call had no timeout, no process-group
  isolation, and discarded the agent's output.** (test:
  tests/pipeline/test_runner_agent_timeout.py) `_call_agent` ran a bare
  `subprocess.run(cmd)`, so a hung agent hung the weekly pipeline forever —
  the documented 2026-05-31 zombie-pipe scenario, where the inner 60-minute
  timeout fired correctly and `agent_call.py` stayed alive another 3h 17m
  because its grandchildren never released the stdout pipe. Under `quiet`, the
  one mode an unattended run uses, it captured both streams and threw them
  away, so the agent's own account of why it exited non-zero was
  unrecoverable. Dispatch now goes through `popen_session` +
  `terminate_process_tree` (the primitives the cycle path already used) under
  a wall-clock bound resolved from the vault's own `stages.<stage>.timeout_s`
  plus a grace margin — the runner's bound backstops the inner timeout rather
  than second-guessing it — overridable, including to "unbounded", via
  `RF_PIPELINE_AGENT_TIMEOUT_S`. Output is tee'd to
  `_pipeline/logs/<stage>-<ts>.log`, its tail is appended to the phase's
  `errors` on failure, and the summary names the log. `_call_agent` returns an
  `AgentCallOutcome` rather than an `int`, because an `int` cannot carry any
  of that. (#220)

- **Every pipeline phase failure was persisted and then never spoken.** (test:
  tests/pipeline/test_runner_failure_reporting.py::TestPhaseFailuresAreLoggedAtError)
  All six `_drive_*` drivers wrote their `errors` into `pipeline-state.json`
  and logged nothing above `INFO`. `cli/_log_level` drops to `WARNING` off a
  TTY — every cron / launchd / systemd run — so a failing weekly run emitted
  zero bytes and the FR6 backstop, the only thing that spoke, called it a
  framework bug and pointed at `_pipeline/run-report.md`, a file the pipeline
  runner never writes. A single `_close_phase` helper is now the one place a
  phase ends: it persists the record, reports `FAILED` at `ERROR` (the
  severity `cli.__init__._ReasonCounter` counts as an exit reason) and
  `SKIPPED` at `WARNING`, and names the absolute path of `pipeline-state.json`
  so the bounded log line points at the unbounded record. `--quiet` no longer
  suppresses it: it silences narration, not the reason a run exited non-zero.
  (#219)

- **A verify FAIL carried no recoverable reason.** (test:
  tests/processors/test_verify_failure_reason.py,
  tests/pipeline/test_runner_failure_reporting.py::TestVerifyReportIsPersisted)
  `verify()` computed its verdict from `malformed_count` / `structural_flags`
  and never appended a single string to the `errors` list it declared, so
  `VerifyResult.errors` was `()` for every FAIL the framework has produced;
  `_drive_verify` then extended from that empty tuple, discarded
  `result.report` — the only carrier of per-note flag detail — and persisted
  `{"verdict": "FAIL", "notes_checked": N}`. That is the byte shape seven of
  eight real vaults recorded on 2026-09-01. A FAIL now states its cause
  (which notes are malformed, and the flags/notes ratio against the resolved
  `fail_threshold`, with the dominant flag families named), bounded so a vault
  with 840 bad notes does not put 840 strings into `pipeline-state.json`; the
  full report is written to `_pipeline/logs/verify-<ts>.json` — the file spec
  015f § Path conventions promised and nothing wrote, giving
  `_common.logs_dir()` its first caller — and the phase summary carries
  `structural_flags`, `malformed_count`, `auto_fixes_applied`, the resolved
  `fail_threshold`, a `flags_by_check` breakdown and the report path. (#218)

- **The spec acceptance-coverage guard enforced nothing on 6 of the specs
  in its own intended scope, and never checked that a cited test
  actually exists.** (test:
  tests/spec/test_acceptance_coverage_guard.py::test_mini_multiline_numbered_gwt_is_discovered,
  test_discovery_is_not_vacuous, test_mini_evidence_missing_test_file_fails,
  test_mini_evidence_missing_test_symbol_fails) The numbered-G/W/T
  discovery regex was single-line, so any scenario wrapping
  `**When**`/`**Then**` onto a following line was invisible to the guard —
  specs 001, 002, 019, 020, 021 and 024 all use that shape. Fixed with a
  `re.DOTALL` pattern bounded to the current numbered item. `020-code-bridge`
  was newly discovered and genuinely lacked a coverage section (backfilled,
  historical form — it shipped 0.4.0, before the convention existed); 001,
  002, 019 and 021 are grandfathered by name, per
  `docs/testing-strategy.md`'s own pre-existing non-retroactive rollout
  note. Separately, the guard accepted any string shaped like a test path
  without checking it resolved to anything — one stale citation
  (`specs/025-simplify-pass/spec.md`'s `test_qw2_text_accurate`, retired
  post-0.3.0) was found and fixed this way. Evidence citations are now
  resolved against the filesystem and parsed with `ast`. The newer flat
  `## Acceptance` bullet format (073, 074, 015b-h, 016) remains outside
  the guard's discovery scope — see
  `docs/adr/0012-acceptance-bullet-format-not-guarded.md` for why closing
  that is a separate, larger piece of work. (#283)

### Removed

- **`scripts/run_cycle.sh`, the bash cycle driver spec 004 replaced.** (pinned
  by: tests/generator/test_integration.py,
  tests/docs/test_doc_sync.py::test_root_docs_do_not_point_at_run_cycle_sh)
  Nothing in the framework had invoked it since spec 004, yet `copy_scripts`
  kept copying it into every generated vault and marking it executable — a
  second, silently drifting copy of `cycle_runner.py`'s step sequence. Three
  tracked assertions disagreed about it: `tests/generator/` required it to
  exist in every vault, `tests/docs/` forbade `docs/` and `.specify/` from
  mentioning "the deleted bash driver", and `ARCHITECTURE.md` — outside that
  guard's scan — recorded it as replaced. The constitution lives under
  `.specify/`, so the project's highest-authority document was structurally
  unable to describe a file the project shipped. The file is gone, the
  generator test now asserts its absence, the doc-sync guard says truthfully
  what it always claimed, and a second guard covers the root docs it was
  implicitly about: they may record the history (`ARCHITECTURE.md` still names
  it as what `cycle_runner.py` replaced) but may not point a reader at the
  path. Every remaining present-tense claim that `run_cycle.sh` drives, writes
  or is piped from something was corrected to name the cycle runner.

  **Existing vaults keep their stale copy.** `copy_scripts` merges and never
  deletes — that is what preserves a vault's own collectors — and
  `./vault regenerate-shim` re-renders the `vault` shim, not `scripts/`. So no
  update path removes the file from a vault that already has it. It is inert
  (nothing invokes it, and it is no longer refreshed), and an operator who
  wants it gone deletes it by hand.

### Fixed

- **A cycle JSON writer that truncated before it wrote let a reader observe
  an empty file mid-write.** (regression tests:
  tests/pipeline/test_atomic_write.py::test_write_json_crash_mid_write_never_leaves_destination_truncated,
  tests/pipeline/test_concurrent_ask_research.py::test_concurrent_cycle_json_reads_never_invalid_during_fixture_research)
  `tests/pipeline/test_concurrent_ask_research.py`'s
  `test_concurrent_cycle_json_reads_never_invalid_during_fixture_research`
  failed three times in the 2026-09-06/07 merge train reading an empty
  `cycle-001-scout.json`, passing on every re-run — a real bug caught by a
  test that could only report it as a flake. The cause:
  `steps/scout.py`'s post-scout module-tagging rewrite of
  `cycle-NNN-scout.json` called `Path.write_text()` directly, which opens
  the file with `O_TRUNC` before writing the new content — a window in
  which any concurrent reader sees zero bytes. Routed through
  `pipeline.atomic_write.write_text` (temp file in the same directory +
  `os.replace`), along with every other `_pipeline` JSON/sidecar write site
  found in the same shape: `orchestrator.py`'s quality-report retry-count
  fixup, `cycle_runner.py`'s skill-check sidecar, `vault_commit.py`'s
  commit-failure sidecar, `source_bridge/isolation.py`'s quarantine
  sidecar, `_helpers/_probe_staging.py`'s probe cache, `preflight.py`'s
  report, and `scripts/vault_metrics.py`'s `--output` (which lands under
  `_pipeline/cycles/cycle-NNN-post-metrics.json`). Four independent
  tempfile-plus-`os.replace` reimplementations of the same primitive
  (`quality_report.py`, `coverage.py`, `correction.py`,
  `source_bridge/cache.py`) were collapsed onto the one canonical helper.
  The concurrency test itself was rewritten to be deterministic: rather
  than a free-running reader thread racing an unsynchronized writer — a
  real thread race that could go many runs without ever landing inside the
  narrow write-in-flight window, which is why this flaked instead of
  failing reliably — it now intercepts any call that reaches
  `Path.write_text` on a cycle JSON's own final path (the atomic helper
  never does; only on a temp file, made visible via `os.replace`) and
  forces a reader scan in between that call's own truncate and content
  phases. (#312)

- **`spec_append` never read `coverage_targets`, so every `--target-topics`
  cycle appended a `topic` entry — even an already-covered one.** (regression
  tests: tests/pipeline/test_spec_append.py, from
  `test_covered_topic_with_no_undeclared_source_leaves_spec_untouched`)
  Spec 073 §2's table says a `topic` is appended only when "a query asked for
  an area no `coverage_target` covers", but
  `spec_append.record_query_discoveries` (`src/research_framework/pipeline/spec_append.py:324`)
  joined every `--target-topics` value into the `topic` field unconditionally,
  never comparing it against the spec's own `coverage_targets`. A new
  `_coverage_target_slugs` helper collects every category's `name`,
  `display_name` and `expected_filenames` title, normalised with the same
  `topic_slug` the managed region's own idempotence already uses;
  `record_query_discoveries` now appends a topic only when its slug isn't
  among them, while `asked` keeps recording the full question regardless (it
  is provenance, not a coverage judgement). An undeclared source is still
  recorded even when the topic itself is already covered. (#258)

- **Quarantine backlog pointers were appended outside any managed block, so
  they never cleared.** (regression tests:
  tests/pipeline/test_rejected_note_handling.py::TestQuarantineBacklogReconciliation)
  `orchestrator._quarantine_rejected_notes` plain-appended a
  `- [ ] rewrite quarantined note: ...` line to `research-backlog.md` on every
  quarantine, with nothing to ever prune it — even after the note was fixed
  and its quarantine copy removed (via `./vault re-grade` or by hand), the
  pointer sat in the backlog forever, the same failure mode `topic-harvest`'s
  managed block already solves. Pointers now live inside a `<!-- quarantine
  -->` / `<!-- /quarantine -->` block that every sweep reconciles against
  what's actually still in `_pipeline/quarantine/`: a resolved note's pointer
  drops on the next sweep, and the block itself is removed once nothing is
  left to reconcile. Content outside the block — an operator's own manual
  backlog entries — is untouched, same guarantee as `topic-harvest`. (#257)

- **Spec parsing raised a bare `ValueError` on a non-integer numeric field
  instead of the field-level error the parser promises.** (regression tests:
  tests/spec/test_schema.py::TestIntFieldCoercionErrors) `priority: high`,
  `target_count: five`, `min_word_count`, `timeout_s` and `retry` all called
  `int()` directly inside the schema dataclasses' `from_dict`, so a typo that
  reads like valid YAML — `priority: high` is not one an author would
  suspect — surfaced as an unhandled traceback plus the FR6 "this is a
  framework bug" hint, because `research_generate.py` only catches
  `SpecValidationError`. All eight `int()` coercions in
  `src/research_framework/spec/schema.py` now go through a new `_int_field`
  helper that raises `SpecValidationError(["<path>: <field> must be an
  integer (got <value!r>)"])`, naming the offending data source, note type or
  coverage category by its own `name` field where the dict carries one.
  (#255)

- **The abstraction gates were off on every vault the framework produces, and
  the CLI twin graded a different document than the gate.** (regression tests:
  tests/generator/test_abstraction_gate_active.py,
  tests/scripts/test_check_abstraction.py::TestCheckAbstractionReportSource)
  SG-003 and CG-003 keyed "am I active?" off `spec.forbidden_filename_prefixes`,
  which defaults to empty, is omitted from `spec-parse.json` when empty, and is
  written by nothing under `generator/` — so a stock generated vault scored
  `NA`, "abstraction gate inactive", on every cycle for ever, and `NA` never
  builds a correction directive, so in the cycle log it read as a clean pass.
  Both gates now resolve their prefixes through `pipeline/abstraction.py`: the
  spec's list when the vault declares one, else a framework starter set
  (`svc_`, `srv_`, `lib_`, `pkg_`, `job_`, `tbl_`, `tmp_`, `internal_`). `NA`
  now means one thing only — the vault set
  `pipeline.gates.abstraction_enabled: false` in `settings.yaml`, a new key
  documented in every shipped profile. R-007 forbade hardcoding a *vault's*
  service codes; it did not license shipping a gate that is inactive in the
  only configuration the framework generates.

  The same module owns the report source. `scripts/check_abstraction.py`, which
  ships into every vault, globbed `cycle-*-research.json` — the DFS output —
  while the in-process gate evaluates `cycle-NNN-scout.json`. Only the scout
  report carries `topics_found.new`, so over one cycle the two disagreed, or the
  CLI scored zero rows and exited 0. It now resolves the report through
  `abstraction.latest_scout_report`, takes an explicit `--report` when the newest
  is not the one you mean, and a test asserts its stdout payload is byte-equal to
  the in-process `GateResult` over the same cycle directory. The scout prompt's
  forbidden-prefix section also moved out of the code-first branch, so a
  non-code-first vault is told the rule it is now graded against.

- **Two cycle artefacts were written non-atomically, so a concurrent reader
  saw them empty.** (regression test:
  tests/pipeline/test_concurrent_ask_research.py::test_concurrent_cycle_json_reads_never_invalid_during_fixture_research)
  `orchestrator` wrote `cycle-NNN-batch-NNN.json` and
  `cycle-NNN-retry-state.json` with a plain `Path.write_text`, which truncates
  before it writes. Every other writer under `_pipeline/cycles/` already goes
  through `pipeline/atomic_write.write_json` (temp file → fsync →
  `os.replace`); these two did not, so an `/ask` session or a `run_report`
  read landing in that window got a `JSONDecodeError` on an empty file. Both
  now use the shared helper, byte-for-byte identically. The test that catches
  it has existed since spec 023 and **had never run in automation** — the
  `e2e` job added in this release caught it on its first run. The reader
  thread now names the offending file rather than raising a bare
  `Expecting value: line 1 column 1`.

### Added

- **A CI job that runs the e2e tier.** `.github/workflows/ci.yml` gains an
  `e2e` job running `pytest -m "e2e and not live_llm"` on every PR and push to
  `main`. Until now PR CI ran `pytest -m "not e2e"`, the smoke gate selected
  four e2e files by path, and the quality/release job ran `build.sh --quality`
  (the harness runner, not pytest) — so **17 of 27 e2e-marked tests, across 9
  files, ran in no automation at all**, FR-003 / FR-004 / US3 / SC-002 proofs
  among them. The tier costs ~6.5 minutes; the job is Linux-only because macOS
  runner minutes bill at 10x and the OS-sensitive surfaces (portability guard,
  shellcheck, installer dry-run) are already on both OSes in the `ci` job.

- **A closed Status-header vocabulary + a checkbox-ledger guard for
  specs.** (#279; tests: tests/docs/test_spec_status_headers.py,
  tests/docs/test_shipped_tasks_are_a_ledger.py) `**Status**:` on
  `specs/NNN-name/spec.md` was free-form prose in 25+ distinct forms, and
  576 `- [x]` boxes across 26 `tasks.md` files gated nothing (the foreman
  parses the box only to delimit a task). `scripts/normalize_spec_status.py`
  maps every header to one of five tokens — `planned`, `in-progress`,
  `shipped(<date>, <PR # | commit | version>)`, `superseded(by <ref>)`,
  `archived` — as a prefix on the existing line, so no prose is lost; 73 of
  82 specs normalized, 9 left alone (named in `KNOWN_AMBIGUOUS`) because
  their header asserts both a completion state and unfinished scope of its
  own and no single token says that honestly.
  `scripts/ledgerize_shipped_tasks.py` then converts `- [x]` to a plain
  bullet on every `shipped(...)` spec's `tasks.md` (25 files, 577 boxes) —
  a leftover `- [ ]` is left untouched, since on a shipped spec that is
  real signal, not noise. CONTRIBUTING.md § 2 documents the vocabulary.

### Fixed

- **The e2e marker was a promise nothing kept, and the docs said the
  opposite.** (regression test:
  tests/build/test_e2e_tier_runs_in_automation.py)
  `docs/testing-strategy.md` stated that markers "govern the local developer
  loop only" — while CI was in fact selecting by marker, and selecting the
  tier *out*. The new tier-7 test asks pytest itself which files carry the
  marker (`--collect-only -qq`, not a regex that could drift from pytest's own
  selection) and fails unless each is either in `build.sh::SMOKE_TESTS` or
  covered by the `e2e` job. It pins the inverse convention too:
  `tests/pipeline/test_runner_agent_dispatch.py` must stay **unmarked** — its
  docstring says so and nothing enforced it, so a future `pytestmark = e2e`
  would have quietly moved the spec-209 regression gate off PR CI.
  `docs/testing-strategy.md` and `tests/README.md` both carry a
  tiers-vs-automation matrix now, saying what `ci.yml`, `build.sh` and
  `quality.yml` each actually execute.

- **The source-poor quality fixture's declared failure mode was exercised by
  nothing, and its SG-002 test could not fail.** (regression tests:
  tests/quality/unit/test_fixture_scenario_env.py,
  tests/quality/test_quality_harness_source_poor.py) The harness set
  `FAKE_AGENT_NOTE_WRITER_SCENARIO='substitution'` — a scenario the fake does
  not have, and exits 2 on. It never mattered, because source-poor's canned
  scout puts every topic in one coverage category, so SG-002 fires and aborts
  the cycle immediately after scout on all three cycles and `note_writer` is
  never dispatched at all. The fixture's registered mode
  `gap-pursuit-substitution` therefore described something the fixture cannot
  reach. Meanwhile the SG-002 assertion was tautological: when the typed
  `ScoutResult` carried no trip, `conftest._sg_trips_from_quality_report`
  re-derived SG-002 *from the scout JSON* — re-evaluating the gate from the
  gate's own input, the same single-category property the test asserts on the
  canned scout two lines earlier. It would have passed with the gate deleted.

  Made honest rather than implemented: reaching `gap-pursuit-substitution`
  needs a canned `note_writer` loader, a scout that clears SG-002, and
  per-fixture scenario env in the release runner — a feature, not a rename.
  So the mode is renamed to `low-diversity-scout-abort`, the invalid
  `substitution` (and the equally unreachable `verifier='reject'`) are dropped
  so every fixture gets the same scenario table, the heuristic fallback is
  deleted — `sg_trips` now comes only from the typed `ScoutResult`, exactly as
  in `runner._cycle_output` — and the test asserts the runner's own signals:
  SG-002 in `scout_result.sg_trips`, `exit_code == 2`, and no notes written,
  on every one of the three cycles. A new tier-1 guard validates every
  scenario the harness sets against the fake, in the fast loop, so a
  non-existent scenario name cannot sit in the table unnoticed again.
  `fake_agent_responses/note_writer/` (5 files in source-poor, 4 in each of
  the others) is deleted from all three fixtures: no code has ever read it —
  the fake synthesises notes procedurally from the scout report — and shipping
  it implied coverage that did not exist. `failure_mode` is descriptive
  metadata, absent from `current.json` and every baseline, so the rename moves
  no metric; `build.sh --quality` stays PASS/PASS/PASS with no re-blessing.

- **The four subcommand `--help` goldens were argparse rejections for verbs
  that do not exist.** (regression tests:
  tests/cli/test_build_parser_stable.py::test_subcommand_help_byte_identical,
  `::test_subcommand_golden_pins_help_and_not_an_argparse_error`) Spec 025
  T076 parametrised them over `research`, `audit`, `vault` and `quality` —
  the names of the `cli/` **modules** the refactor created, not registered
  verbs. Every one of the four goldens is therefore
  `error: argument command: invalid choice: 'research' (choose from …)`, so
  all four pinned the same thing the top-level golden already pins (the
  subcommand registry) and **no verb's flags or help text were pinned
  anywhere**, despite SC-009 claiming they were.

  The goldens are regenerated against real verbs — `generate`, `acceptance`,
  `cycle`, `digest`, one per shape the operator surface has — and renamed
  `help_<verb>.txt` (the `_pre_025` suffix claimed a provenance they no longer
  have). A second test asserts each golden starts with
  `usage: research-framework <verb>` and contains no `invalid choice`, so the
  same typo cannot silently produce a vacuous golden again. `COLUMNS=80` is
  now pinned in the help subprocess's environment: argparse wraps to
  `shutil.get_terminal_size()`, which reads `$COLUMNS`, and the goldens hold
  wrapped help text now rather than one-line errors.

- **`test_main_dispatch_table_complete` could not fail.** (regression test:
  tests/cli/test_build_parser_stable.py::test_parsed_namespace_carries_a_callable_handler)
  Its assertion was
  `getattr(action, "func", None) is not None or action.dest is not None`, and
  argparse always sets `dest` on a registered subcommand — so the right-hand
  clause made the whole expression a tautology. It also interrogated the
  *registration* action rather than a parsed namespace, which is where
  `set_defaults(func=...)` actually lands. A subcommand registered without a
  handler would ship green and crash at `args.func` in `main`.

  The replacement parses each verb's minimal argv and asserts
  `callable(namespace.func)` — the object `main` reads, via the code path it
  reads it through. The minimal argv is synthesised from each subparser's own
  required positionals and flags rather than hand-listed, so a new verb is
  covered the moment it is registered. Verified by mutation: commenting out
  one `set_defaults(func=…)` leaves the old test green and fails the new one.

- **The fake agent's "drop-in replacement" claim was prose, and three parts of
  it were false.** (regression tests: tests/_helpers/test_fake_agent_parity.py)
  `tests/_helpers/fake_agent.py` says it stands in for `scripts/agent_call.py`
  with "same argv, same subprocess shape". Nothing checked that, and it had
  drifted on all three surfaces the phrase covers. Its `--prompt-file` was
  **required** while the real CLI falls back to stdin, so a caller that piped
  the prompt died on an argparse error under the fake only. The shim's
  in-process `dispatch()` lacked the real `dispatch()`'s `model=` keyword —
  which `processors/extract.py` passes on *every* call — so that seam
  `TypeError`ed under the fake, and the extract tests worked around it by
  stubbing `_bootstrap_scripts_agent_call`, leaving extract → `agent_call` with
  no fake-shim coverage at all. And its cost sidecar was schema `1.1` with no
  `cost_source` (the real writer moved to `1.2` in the spec-028 rc3 amendment)
  and was written **only on the success path**, so a failed stage left no
  telemetry and `status: "failed"` was never exercised end to end.

  `test_fake_agent_parity.py` now DERIVES all three expectations from
  `scripts/agent_call.py` — the argv table from the parser its `main` actually
  uses, the parameter set from `dispatch`, the key set from
  `_build_sidecar_v11_payload` — and asserts the fake is a superset of each.
  A hand-maintained restatement is what let this drift accumulate, so the
  guard restates nothing. The fake is fixed to match: `--prompt-file` is
  optional (stdin is staged to a scratch file so the path-based handlers are
  unchanged), the shim's `dispatch()` carries `model=`, and the sidecar is
  `1.2` with `cost_source: "none"` — the literal `_resolve_cost` records when
  there is neither a runtime signal nor an estimate — written on the failure
  path too with the real `exit_code` and a `stderr_excerpt`. `#261`'s
  unknown-stage test asserted "no sidecar at all", which overshot its own
  reasoning (what made a failure read green was `status: ok`, not the file);
  it now asserts the failed sidecar. The three committed fixture shims under
  `tests/fixtures/quality/*/scripts/` are regenerated, and the fake-agent
  contract goes to v2.2 — its sidecar example had been stale since before
  schema 1.1 existed.

- **Spec 070 FR6 was marked DONE while every orchestrator exit that returns 1
  stayed invisible.** (regression tests:
  tests/cli/test_fr6_exit_reason_visibility.py) FR6 asks that every non-zero
  exit write a diagnosable message to *stderr*. The backstop in `cli.main`
  shipped; the paths that actually produce rc=1 did not follow.
  `_constrained_exit` narrated its reason, its punch list and its remedy
  entirely at `INFO`, and so did the source-exhausted exit; `_resume`'s
  precondition rejection and both of `_run_phase3`'s gate rejections went to
  *stdout*. `_log_level` FR-005 drops the level to `WARNING` the moment stdout
  is not a TTY — which is every cron, launchd and systemd run, i.e. the mode
  the framework exists for — so an unattended run got `exit 1` and nothing
  else. On 2026-09-06 two live vault runs hit exactly this.

  The exit *reason* of a non-zero exit is now `ERROR` (matching what spec 070
  F5's ceiling diagnostic already did), the punch list and remedy that make it
  actionable are `WARNING`, and the four rejections that used `print` now
  print to stderr. Exit codes and control flow are unchanged throughout; this
  is purely what the operator can see.

- **The pipeline's one human checkpoint pointed at a file that is never
  written.** (regression tests: tests/pipeline/test_runner_triage_prompt.py)
  `run_full` ended with "Open the radar, approve/defer queue items" and the
  generated `/pipeline` command said "Human must review the Topic Radar" — but
  a `pipeline` run writes no Topic Radar. That note belongs to the cycle
  orchestrator; `runner._STAGE_PROMPT_SOURCES` steers the research stage at
  `scout-report.json` for exactly that reason. No document in the repo said
  where triage actually happens, so the operator was sent looking for a file
  that does not exist.

  The pause now names `_pipeline/scout-report.json`'s `topics_found.new`,
  reports how many topics are in it, states plainly that `resume` researches
  every one of them in a single pass with no approve/defer gate, and gives the
  one edit that defers a topic. ARCHITECTURE.md § "The triage checkpoint"
  documents the protocol. The real gate — a generated triage artifact, a
  `pipeline triage` verb, deferred topics carried into `research-backlog.md`,
  a `resume` that refuses an empty approval set — is a contract change across
  three stages and stays open on issue #240 pending its own spec. Until then
  the count is the warning: one live run was handed 107 topics in one pass.

- **The non-TTY `WARNING` default silenced the entire pipeline narrative.**
  (regression tests: tests/cli/test_pipeline_verb_log_level.py) Spec 048
  FR-005 drops the log level to `WARNING` whenever stdout is not a TTY, and
  every phase summary, the `HUMAN TRIAGE REQUIRED` prompt, the verify verdict
  and the "not yet implemented" collect lines are `INFO`. An autonomous
  pipeline runs from cron, launchd or systemd — i.e. *never* on a TTY — so the
  mode the framework is built for was the one mode in which it said nothing.

  `_log_level.resolve` now takes a `verb_default`, consulted before the TTY
  test and only when `--log-level` is absent, and the `pipeline` subparser
  declares `info`. Per-verb rather than global on purpose: the TTY test stays
  a good proxy for "is a human watching" everywhere except the verbs that
  exist to run unattended. An explicit `--log-level` still wins, and a
  `verb_default` is validated on the same path as a flag value. Recorded in
  spec 048's `log-level-flag.contract.md`.

- **`--reject <stage>` exited 1 with zero bytes, so the FR6 backstop called a
  deliberate rejection a framework bug.** (regression tests:
  tests/cli/test_research_resume_approval.py::test_reject_says_what_it_rejected_on_stderr,
  `::test_reject_all_names_the_stage_it_actually_refused`,
  `::test_interactive_decline_says_what_it_left_behind`,
  `::test_force_budget_decline_says_what_it_left_behind`) Refusing an approval
  is the operator getting exactly what they asked for; being told "this is a
  framework bug (spec 070 FR6)" for it is worse than saying nothing. Two
  neighbouring branches were silent the same way: declining the interactive
  approval prompt, and declining the `--force-budget` prompt.

  All three now report on stderr through one helper — what was refused, the
  path the marker was retained at (evidence nothing was silently discarded,
  and the file to delete to abandon the pause), and the flag plus `RF_APPROVE_*`
  ack that would let the next run through. A refusal is not a bug, but it owes
  FR6 the same three things one does.

- **The spec-070 FR6 backstop was a zero-bytes guard, and its test pinned that
  weaker property.** (regression tests:
  tests/cli/test_nonsilent_exit_guard.py::test_main_guard_fires_after_an_unrelated_warning,
  `::test_main_guard_fires_when_the_verb_only_spoke_on_stdout`,
  `::test_reason_counter_counts_only_error_records`) The guard fired only when
  the whole process wrote nothing at all, anywhere — so one unrelated
  deprecation `WARNING` at startup, or a rejection printed to a redirected
  stdout, certified a mute `exit 1` as diagnosed. Its own test asserted
  `stdout + stderr > 0`, which is exactly the OR that lets spec 070 F5's
  failure mode (stdout redirected, stderr empty) through: the specified
  behaviour could be broken with the suite green.

  `_EmissionCounter` is now `_ReasonCounter` with its handler level at `ERROR`,
  the stdout tap is gone, and the backstop condition is stderr bytes plus
  `ERROR` records. A `WARNING` is advisory by definition and cannot be the
  reason a run refused to continue. The two reviewers on this defect asked for
  different floors (`>= WARNING` versus "an unrelated WARNING must not silence
  it"); those are mutually exclusive and the second came with a demonstration,
  so `ERROR` is the floor — recorded in spec 070's FR6 block along with the
  half of the requirement that is still open (verbs returning a structured
  failure that `main()` renders uniformly).

- **`vault.corpus_dir` was honoured by the generator and hardcoded away by
  every reader.** (regression tests: tests/vault/test_corpus_dir_seam.py,
  tests/scripts/test_topic_harvest.py::test_harvest_reads_a_non_default_corpus_dir)
  The simple-spec parser validates `vault.corpus_dir` and scaffold and
  templates honour it, so a vault could legitimately call its corpus `cases/`.
  The indexer, coverage recompute, orchestrator quarantine, harvest and
  wikilinks then each spelled `vault / "data_vault"` — so that vault got a
  second, empty `data_vault/` created under it, its indexes written there, its
  rejected notes never quarantined, its acronyms never linked and `met_count`
  stuck at 0. Config accepted and silently ignored.

  `research_framework.vault.corpus` is now the one place that answers "where is
  this vault's corpus", reading `vault_corpus_dir` from
  `_pipeline/spec-parse.json`. Every reader above goes through it, as do
  `cli/wikilinks`, the digest's strongest-signals section and
  `scripts/topic_harvest.py` (which resolves through the same seam, falling
  back to the default only when the framework is not importable — harvest is
  best-effort by contract). `runner._corpus_dir`, the private helper PR #210
  added for one caller, is now a thin wrapper over the shared
  `existing_corpus_dir`; its extra grade-the-vault-root fallback stays local to
  grading. `prune` and `vault inventory` keep their own resolution: both need
  to *fail* or warn when no corpus is on disk, which is a different question
  from "what is it called".

- **`generate` and `regenerate-agents` wrote two incompatible templates to the
  same `.claude/commands/research.md`.** (regression tests:
  tests/generator/test_templates.py::test_regenerate_agents_preserves_the_generate_time_commands,
  `::test_regenerate_agents_preserves_a_renamed_command`,
  tests/cli/test_regenerate_agents.py::test_regenerate_keeps_the_research_command_a_research_command,
  tests/agents/test_render.py::test_renameable_commands_render_from_the_generator_source,
  `::test_write_agents_honours_configured_command_names`) `generate` wrote
  `templates/commands/research.md.j2` — the single-topic "add a note" command
  that honours `settings.commands.research` — while `regenerate-agents` wrote
  `agents/research.md.j2`, a Topic-Radar agent definition, under a *fixed*
  name. So a plain `regenerate-agents` silently swapped a vault's `/research`
  personality, or left a stray `research.md` beside the vault's renamed one.
  Same for `ask` and `write`. Nothing caught it because no test crossed
  generate → regenerate-agents.

  One owner per command file now. `agents.write_agents` is the only writer
  either path uses; it renders `ask`/`research`/`write` from
  `templates/commands/` and resolves their destination stem from
  `spec.settings.commands`, and renders the five pipeline agent definitions
  from `agents/`. `agents/{ask,research,write}.md.j2` and their tests are
  deleted — they only ever reached a vault through the bug. `ARCHITECTURE.md`
  § 13 gains the ownership table and a section naming the two research entry
  points (the interactive `/research` and the runner's headless `research`
  stage), which until now existed only in a `runner.py` comment; the
  `/pipeline` and `/research` templates point at it.

- **`/verify` Tier 0 told the agent to run a script the framework retired.**
  (regression tests:
  tests/agents/test_verify.py::TestTier0Invocation,
  tests/agents/test_render.py::test_no_rendered_agent_references_a_missing_script)
  `agents/verify.md.j2` opened its only executable step with `python
  scripts/verify.py` — superseded by `processors.verify` in the migration map
  (`migration/superseded_paths.py:18`) and no longer shipped — so Tier 0 was
  broken by construction in every generated vault, and the two AI tiers below
  it fed on a report that never arrived. The step is now `python -m
  research_framework.processors.verify <corpus> --json --no-fix`: the corpus
  folder rather than the vault root (PR #210's scope fix — grading the root
  walks `.claude/`, `README.md` and `.venv/` as notes) and `--no-fix`, which
  PR #210 also made actually take effect. The prose that described the retired
  script — the auto-fix table, the `python-frontmatter` failure mode — now
  describes the processor, including where the two auto-fixable checks surface
  under `--no-fix`. The three quality fixtures' committed copies were
  regenerated. A renderer-level test now fails if any command names a
  `scripts/<name>` the framework does not ship.

- **The `/pipeline` shim told the agent two stages were stubs and named a
  directory on someone else's machine.** (regression tests:
  tests/agents/test_pipeline.py::test_no_known_limitation_disclaimer,
  `::test_vault_location_is_not_baked_in`, `::test_vault_resolved_at_runtime`,
  tests/agents/test_render.py::test_no_rendered_agent_bakes_an_absolute_path,
  `::test_no_rendered_agent_disclaims_a_wired_stage`) `agents/pipeline.md.j2`
  still carried the "Known limitation (as of 1.0.0rc10)" blocks saying
  `research` and `report` fail fast and that the operator should "use
  `./vault research`" instead — PR #209 wired both stages, so the shim now
  misdescribed them in the opposite direction, and the agents reading it are
  the ones that stop mid-run to ask what to do. Both blocks are gone; the
  `resume` section says instead that all three stages run headlessly and that
  the agent must not stop to ask.

  The same template baked `spec.location` — an absolute path resolved when the
  vault was generated — into all fourteen command lines. A vault that is moved,
  renamed or cloned keeps pointing at where it used to be (one live vault's
  `/pipeline` still named a `-rc7` staging directory). The commands now read
  `research_framework pipeline "${VAULT_DIR:-$PWD}" <mode>`, with a "Resolving
  the vault" section telling the agent to run them verbatim rather than
  substitute a path. Both properties are now asserted across *every* rendered
  agent, not just this one.

- **The fake agent's in-process `dispatch()` raised `NameError` on every call
  that carried a `cycle_dir`.** (regression test:
  tests/_helpers/test_fake_agent_shim.py) `_SHIM_TEMPLATE`'s sidecar write
  called `_write_cost_sidecar_v11` unqualified, but the shim imports only
  `fake_agent` and `SimpleNamespace` — so every `plan_narrator` and
  `probe_retrieval` dispatch in every e2e and quality run raised, and
  `plan_narrator.prepend_narrative` / `_probe_staging` swallowed it into their
  canned fallbacks. The symptom was an incident line
  (`agent dispatch failed: name _write_cost_sidecar_v11 is not defined`) in
  every fixture vault, zero narrator/probe sidecars under `agent-calls/`, and
  no dispatched narrative in any `research-plan.md`.
  `tests/quality/test_fake_agent_interception.py` stayed green throughout
  because it inspects `subprocess.Popen` argv and an exception is not a
  spawned subprocess. The new file is the first test of the *installed* shim
  rather than of `fake_agent` itself (issue #259).

- **The fake agent passed every stage it had never heard of.** (regression
  tests: tests/_helpers/test_fake_agent_contract.py,
  tests/pipeline/test_runner_agent_dispatch.py) For any unrecognised
  `--stage` the fake exited 0, wrote nothing and emitted a `status: ok` cost
  sidecar, so a stage-name typo and a genuinely unwired stage both read as a
  completed run. Two of those unwired stages were the weekly runner's own
  `research` and `report`: `research-framework pipeline resume` / `finish`
  recorded each phase DONE having produced no artifact, and
  `test_runner_agent_dispatch`'s "positive proof a rendered file reached the
  agent" proved only that a prompt file existed. An unknown stage is now
  exit 2 naming the stage and the implemented set (`FAKE_AGENT_ALLOW_UNKNOWN_STAGE=1`
  restores the no-op), and `research` / `report` have handlers that write the
  flat artifacts the runner works with — `research` to the
  `research-report.json` path the *prompt* names, so an unrendered
  `{RESEARCH_REPORT}` placeholder fails rather than passing. Contract bumped
  to v2.1. This is the test-side half of #222 (issue #261).

- **`build.sh --quality` and pytest ran two different fake agents.**
  (regression test:
  tests/_helpers/test_fake_agent_shim.py::TestCommittedFixtureShimsMatchTheTemplate)
  The committed fixture shims at `tests/fixtures/quality/*/scripts/agent_call.py`
  were a stale generation of `_SHIM_TEMPLATE` — 81 changed lines, an older
  `dispatch` that wrote no sidecar. The release gate copies the committed tree
  and so ran the old shim; `tests/quality/conftest.run_fixture_cycles`
  re-installs and so ran the new one. `install_shim`'s docstring claimed a
  re-install inside the repo was a `git status` no-op, and nothing checked it.
  The three shims are regenerated from the fixed template, and a parametrised
  test now compares their bytes to `fake_agent.render_shim(None)` — the same
  rendering the installer performs, factored out so the guard cannot agree
  with itself (issue #260).

- **The release quality gate was a third of the gate it documented, and three
  of its readings were fiction.** (regression tests:
  tests/quality/unit/test_harness_cycle_count.py,
  tests/quality/unit/test_unmeasured_metrics.py,
  tests/quality/unit/test_cost_efficiency_metric.py,
  tests/pipeline/test_step_gate_log.py,
  tests/pipeline/test_quality_report_step_gates.py,
  tests/pipeline/test_cycle_runner_step_gate_abort.py) Four defects in the
  spec-022 harness's telemetry, all found by the 2026-09-03 tri-repo review
  (epic #216).

  **One cycle, not three (#268).** `quality.runner._invoke_cycles` drove a
  single cycle per fixture while `docs/testing-strategy.md`, spec 022's plan
  (`max_cycles: 3`), its data model (`CycleOutput (N, one per cycle)`), its
  `source-poor` acceptance scenario ("at least one cycle in the 3-cycle harness
  run") and `tests/quality/conftest.run_fixture_cycles` all said three. The
  code was the outlier and moved; `HARNESS_MAX_CYCLES` is now the single source
  of the number and the pytest wrapper imports it. A full run is ~18s.

  **`cost_per_substantive_note` counted every note twice (#294).** The
  denominator summed both `CycleOutput.notes_written` and
  `research_result.notes_written` — the same list on every output the harness
  builds — so the one cost metric that can still gate reported half its true
  value. Now a union of resolved paths, which also de-duplicates a note
  re-written in a later cycle.

  **A gate that aborted a cycle recorded itself as "not recorded" (#269).**
  `ScoutResult.sg_trips` was hard-coded `[]` and batch reports only ever carry
  SG-004/SG-005, so `quality_report` recorded SG-001..003 as `NA` on *every*
  cycle — and on a cycle SG-002 had just aborted there is no batch at all, so
  the gate that stopped the run was the one reported as unrecorded. The only
  trace was an INFO log line, and `timings.json` stopped at "Step 0", making a
  gate-abort indistinguishable from a crash. `pipeline/step_gate_log.py` now
  persists each verdict as the scout evaluates it; the quality report reads it
  back, the scout opens a timing lap, and `sg002_trip_count` counts. This is a
  product fix as much as a harness one — real vaults had the same blind spot.

  **A metric with nothing to divide reported `0.0` (#268).** Seven of ten
  gated metrics read `0.0` against `0.0` baselines. Some of those zeros are
  real; four were empty denominators — no acronym occurrence, no citation whose
  credibility resolves, no note written, a verifier that never ran. Those now
  report `unmeasured` with a reason, surfaced in the `Summary:` line, the
  printed report and `regression-report.json` (contract § 3), so a
  non-measurement stops reading as a passing gate.

  All three baselines were re-blessed from a 3-cycle run. The committed ones
  encoded the one-cycle shape, `sg002_trip_count: 0` for a fixture whose every
  cycle SG-002 aborts, and a `cost_per_substantive_note` of `0.40` that no run
  has produced (fake-agent sidecars record `cost_usd: 0.0`). Still open under
  #216: #267's zero baselines, and the fake agent writing note bodies with
  none of their template's sections, which pins `template_compliance_pct` at a
  real but ungatable `0.0`.

- **The release quality gate could not fail on any metric whose committed
  baseline is `0` (#267).** `baseline.py::_delta_pct(0, x)` returns `"n/a"`,
  and `_metric_verdict` mapped every `"n/a"` to `"pass"` — with no exception
  for a `lower_is_better` counter that actually got worse. Seven to eight of
  the ten gated metrics are `0.0` in all three committed baselines, so
  `cycles_fail`, `sg002_trip_count` and `verifier_reject_rate` could explode
  from 0 to any real value and `build.sh --quality` would still print PASS. (test: tests/quality/unit/test_zero_baseline_regression.py)

  `_metric_verdict` now takes the raw baseline/current values, not just the
  percentage: a `lower_is_better` metric baselined at `0` fails outright the
  moment `current > 0` — there is no prior magnitude to place it in a 5%/15%
  band, so the increase off zero *is* the regression, in full.
  `higher_is_better` metrics baselined at `0` are left on the existing
  `n/a`-reads-as-`pass` path: those metrics are non-negative, so a `0`
  baseline is already the best possible reading and nothing can regress below
  it — there was never a hidden-failure risk on that side, only on the
  `lower_is_better` one this issue is about.

  This is deliberately narrower than tracking a zero baseline as
  `unmeasured` on the `higher_is_better` side (as the issue's evidence
  suggested): that would have reclassified a case #268 just finished
  establishing as a *real, measured* zero (e.g. `note_quality.acronym_link_pct`
  at `0.0` baseline and `0.0` current is a legitimate, boring "no change", not
  a non-measurement) — see `tests/quality/unit/test_unmeasured_metrics.py::test_a_fully_measured_run_reports_no_unmeasured_metrics`.
  A genuinely unmeasured metric (`current is None`, issue #268) and a real
  regression off a zero baseline are told apart by
  `tests/quality/unit/test_zero_baseline_regression.py`; the former stays
  purely informational, the latter fails the gate.

  Baselines are unchanged by this fix — it only tightens comparison logic, it
  does not re-run the harness. Re-blessing the zero baselines themselves so
  `unmeasured` stops being the normal state is tracked separately (#268).

- **Principle VI's only pre-write enforcement was an optional field, and its
  post-write backstop was downgraded to a WARN.** (issue #293; regression
  tests: tests/scripts/test_validate_cycle_proposed_filenames.py,
  tests/pipeline/test_gates_step_sg004_duplicates.py)

  Constitution Principle VI ("Two notes for the same concept MUST NOT exist")
  names exactly one enforcement point: the naming convention is enforced
  *before DFS writes any file*, with `proposed_filenames` in the scout JSON as
  the coordination mechanism. That check sat in `scripts/validate_cycle.py`
  behind `if proposed and …` with the field in **none** of the three
  required-field lists, so a scout report that omitted the key — or emitted
  `[]` — skipped the only pre-write enforcement of a constitutional principle,
  silently. It also compared proposals against files already on disk only, so
  two entries colliding *within one list* passed, leaving the principle's
  parallel-agent clause ("their topic lists MUST be non-overlapping") with no
  implementation at all.

  `proposed_filenames` is now required on a v2 **scout** report (research
  reports consume proposals rather than emitting them, so
  `REQUIRED_REPORT_FIELDS_V2_RESEARCH` is unchanged). Omitting it is a
  structural error, which the scout-correction retry loop already recovers from
  by re-prompting — a cheap recoverable failure, not a cycle abort. The v1 and
  v2 paths carried byte-identical copies of the collision block; both now call
  one `_filename_collision_errors` helper that checks the list against the
  vault, against itself, and for the `[]` opt-out — the last scoped to a
  *continuing scout*, since a research report or a terminating scout has no
  DFS write left to coordinate. `templates/prompts/scout-prompt.md.j2` now
  states the same contract to the agent — required, no intra-list repeats, no
  `[]` while reporting new topics — so the first attempt satisfies the check
  rather than paying for a correction round.

  **SG-004 no longer downgrades a duplicate note to a warning.**
  `validate_vault.py` detects duplicates and exits 1, but
  `SG004_validate_vault_wrapper` mapped every non-zero exit to `WARN`, and only
  a `FAIL` drives the correction loop — so a duplicate that slipped the
  pre-write check was detected, logged, and written anyway. The gate now
  separates the two classes: a `duplicate` violation is a `FAIL` with a
  correction hint (the loop it feeds already exists and deletes nothing);
  every other finding still `WARN`s. Spec 017's gate table chose WARN
  deliberately for style and hygiene findings and spec 019 US5 kept a soft
  default for backwards compatibility — that judgement is preserved, since it
  never covered a constitutional violation. Spec 019's FR-013/FR-014
  (a settings-driven `gates.sg004.mode`) remain deferred; this is narrower and
  needs no new setting. The `duplicate` field name is now the named contract
  constant `validate_vault.DUPLICATE_FIELD`, pinned by a test that runs the
  real script against a vault with real duplicates.

- **Both LLM-dispatch guards missed `opencode`, disagreed with each other, and
  could not see the HTTP executor path.** (issue #292; regression tests:
  tests/_helpers/test_llm_dispatch_parity.py,
  tests/_helpers/test_llm_dispatch_guard.py::test_opencode_is_a_guarded_binary,
  `::test_http_inference_call_is_a_violation`,
  `::test_binary_set_is_derived_not_declared`)

  Two guards enforce Principle IV's single-dispatch-surface rule — the tier-2
  static AST scan (`tests/_helpers/test_llm_dispatch_guard.py`) and the tier-6
  runtime interception guard
  (`tests/quality/test_fake_agent_interception.py`). Each carried its **own
  hand-maintained binary list**: `{claude, codex, cursor-agent}` and
  `("claude", "codex")` respectively, against a shipped set of
  `{claude, codex, cursor-agent, ollama, opencode}`. So `opencode` (spec 064,
  the 4th first-class executor) was invisible to **both** — a
  `subprocess.run(["opencode", "run", …])` added to
  `src/research_framework/` shipped green — and `cursor-agent` was invisible
  to the runtime guard although the static guard had gated it since spec 052.

  The HTTP executor was invisible to both **by construction**: `ollama` and
  every `type: api` executor are dispatched by `agent_call._dispatch_http` →
  `urllib.request.urlopen`, never by a subprocess, so neither an AST scan for
  `subprocess.run`/`Popen` nor a `subprocess.Popen` monkeypatch could ever see
  one. For those the gap was a missing dispatch *mode*, not a missing name.

  New `tests/_helpers/llm_dispatch.py` is the single source of truth both
  guards now read. It **derives** its sets from `scripts/agent_call.py`
  (`_LLM_AGENT_NAMES`, `_HTTP_RUNTIMES`) rather than re-declaring them, and
  owns the two predicates — `is_llm_command` (basenames `argv[0]`, so an
  absolute `CLAUDE_BIN`-style path still counts) and `is_inference_url`. The
  static guard gained the HTTP mode; non-inference outbound HTTP (feed
  collectors, source preflight, refresh-sources) stays legal, since a blanket
  ban would be noise rather than a guard. The runtime guard now patches
  `urllib.request.urlopen` alongside `subprocess.Popen` and asserts it
  **observed** dispatch traffic before asserting that traffic was clean, so it
  can no longer pass green over zero observations.
  `tests/_helpers/test_llm_dispatch_parity.py` builds each shipped executor's
  real dispatch shape through `agent_call._build_command` / `_http_endpoint`
  and asserts both guards classify all of them identically, and that the
  guarded set equals `settings.DefaultAgent`'s `Literal` — so a sixth executor
  cannot silently un-guard itself.

  Contract `specs/018-testing-strategy/contracts/llm-dispatch-guard.contract.md`
  amended to v2 with the delta. The guard's fail-open scan root is issue #278
  and deliberately untouched here.

- **The verify phase destroyed note frontmatter and graded files that are not
  notes.** (regression tests:
  tests/pipeline/test_runner_verify_scope.py,
  tests/processors/test_verify.py::TestAutoFixPreservesFrontmatter,
  `::TestWalkScope`, `::TestOptionPrecedence`) Two defects that compounded
  into the FAIL seen on 7 of 8 live vaults on 2026-09-01.

  **Frontmatter destruction.** `processors/verify.py` read notes with
  `_common.parse_frontmatter` — a line-scalar parser whose own comment scopes
  it to `_pipeline` raw items ("spec 025 B4 holdout") — and wrote them back
  with a hand-rolled emitter. Against a real note, one auto-fix emptied every
  list field (`tags`, `related`, `source_urls`, `owns`, `reads`), stripped
  quotes off scalars, hoisted a key out of a list-of-dicts to top level,
  turned `tags: [a, b]` into the string `"[a, b]"`, and let a nested `title:`
  overwrite the note's real title. Both directions now go through the
  canonical codec (`vault.frontmatter.parse_frontmatter_str` /
  `dump_frontmatter`, real YAML); `_common`'s parser stays reserved for
  `_pipeline` raw items. Malformed YAML is now reported as
  `malformed_frontmatter` instead of being silently half-parsed and
  rewritten — the check existed but was unreachable.

  **Grading non-notes.** `pipeline/runner.py::_drive_verify` called
  `verify(vault)` on the vault ROOT with auto-fix defaulted on, and
  `EXCLUDE_DIRS` excluded only `_pipeline`, `_templates` and `.obsidian`. So
  `.claude/commands/*.md`, `CLAUDE.md`, `README.md`, `raw_data/README.md`,
  `research.spec.md` and `.venv/**` site-package READMEs were walked as
  notes, flagged as orphans or missing-summary, rewritten in place, and their
  flags pushed the flag/notes ratio past `fail_threshold`. On a freshly
  generated vault that was 18 files graded, 18 files mutated, verdict FAIL —
  with zero notes in the vault. The phase now grades the corpus
  (`vault_corpus_dir` from `_pipeline/spec-parse.json`, vault root as
  fallback) and runs with `auto_fix=False`: a phase named "verify" reports,
  it does not mutate. Auto-fix remains available through the processor CLI,
  where the operator opts in. The walk additionally skips every
  dot-directory, `scripts/`, `node_modules/`, config markdown and
  `*.spec.md`. Framework-generated corpus indexes (`_index.md`,
  `_concepts.md`, `_graph.md` — the same three names
  `vault.indexer._is_note_path` knows) are still scanned for wikilinks, so
  the notes they index are not reported as orphans, but are never graded,
  counted or fixed.

  **`--no-fix` and `--fail-threshold` did nothing.** `cfg.get(key, param)`
  always found the key in `PROCESSOR_DEFAULTS`, so both `verify()` parameters
  were dead and the CLI flags were inert. Precedence is now explicit
  argument > spec config > default; both parameters default to `None` to
  express "not specified".

- **`pipeline resume` and `pipeline finish` never reached their agent.**
  (regression tests: tests/pipeline/test_runner_agent_dispatch.py,
  tests/pipeline/test_runner.py::TestStagePromptRendering) `_drive_research`
  and `_drive_report` passed `prompt_file=None` unconditionally — a
  placeholder left behind when `_drive_scout` got real prompt rendering — so
  both stages died at the fail-fast guard with `no rendered prompt available
  for stage 'research'; this pipeline runner has no template wired up for it
  yet`. The seven-phase weekly pipeline (collect → extract → scout → triage →
  research → verify → report) was therefore not runnable end to end
  headlessly: `full` stops at triage by design, and neither command that
  continues from there could dispatch anything. Reproduced on a live vault.

  Both stages now render a prompt the same way scout does, from a
  `_STAGE_PROMPT_SOURCES` table that also drives the error message when a
  source is genuinely absent (it names the missing file instead of claiming
  the framework has no template). **Research reads the queue this pipeline
  actually writes.** Its source is `_pipeline/prompts/dfs-prompt.md`, the one
  shipped template that consumes `scout-report.json`'s `topics_found.new` —
  the exact path `_drive_scout` hands the scout agent. The
  `.claude/commands/research.md` agent definition drives off a *Topic Radar*
  note instead; that is a cycle-orchestrator artifact a `pipeline` run never
  produces, so pointing the stage at it would have stopped every run on
  "Research queue is clear" (and its filename is user-configurable via
  `spec.settings.commands.research`, so it is not reliably locatable either).
  Report has no prompt template, so it renders the vault's own
  `.claude/commands/report.md` — which *is* the stage's behaviour, and which
  `generator.templates.render_all` writes under that fixed name — prefixed
  with a run-context block naming this run's artifacts by absolute path,
  since an agent definition carries none of the template placeholders. A
  render failure degrades to "no prompt" plus the actionable error rather
  than crashing the phase.

  `run_finish` still runs verify + report only (research stays skipped), and
  verify stays processor-driven and untouched.

## [private 1.1.0] - 2026-08-30

### Added

- **A query that finds new ground records it in the spec (spec 073).** A vault's
  `research.spec.md` was read by every path and written by none — so a question
  that needed a topic and a source the spec did not declare left no trace, and
  since spec 070 an uncatalogued domain is a quarantine reason, meaning a good
  new source silently *creates future quarantines*. Query-driven cycles (those
  invoked with `--target-topics`, which is how `ask.md` escalates) now append
  what they discovered to a managed region delimited by
  `<!-- framework:discovered:begin/end -->`.

  Three rules make it safe. **Append-only**: nothing above the begin-marker is
  read for meaning or rewritten — the prefix and suffix are carried through
  byte-for-byte, so a revert can never lose human prose. **Appending is not
  adopting**: a discovered source does not become a `data_source` and a
  discovered topic does not become a coverage target; promotion stays a human
  edit, because auto-adopting would let one query silently widen what the vault
  trusts. **Discovered sources are `unassessed`**: nobody has judged them, so
  the verifier goes on quarantining notes that cite them — what changes is that
  the operator can now see *which* unvetted source caused it. A malformed or
  hand-edited region is refused rather than reconstructed. Full backlog runs
  record nothing; that scope question is left open for the operator.

- **Spec 070 FR2 — a `default_credibility` that cannot bind is now rejected.**
  `source_backing.credibility_binding` classifies each declared source
  `none` / `bound` / `unbindable`, mirroring the exact key order
  `build_credibility_context` indexes (`repos[]` → `local_path` → `url`/`urls`
  → module trigger-match) so the gate and the resolver cannot disagree. FAILs
  at scaffolding — `spec/validator.py` and `scripts/validate_spec.py` — and
  WARNs at preconditions rather than blocking an existing vault mid-life. That
  split is deliberate: a catch-all source like "Open web search" is
  legitimately unbindable (you cannot enumerate the domains of the open web),
  and three of six live vaults have exactly that shape. F1's lesson stands —
  inert configuration is worse than rejected configuration — but an inert
  credibility claim does not stop a cycle doing its job the way an unbacked
  source does.

### Changed

- **A constrained run now lands on `main`, and leaves you there (spec 072).**
  Every run opened `research/<date>` and, on any non-zero exit, left the vault
  sitting on it with *"branch retained for review"* — handing the operator a
  question the framework is better placed to answer. But a constrained exit
  (rc=1: budget cap, max_cycles, source-exhausted) is a **designed terminal
  state**, not a failure, and its content is as valid as a clean finish. Such a
  run now squash-merges onto the base branch and checks it out, retaining the
  research branch so a bad landing is recoverable. rc=0 is unchanged; rc=2
  (aborted) deliberately still stops for review, since a run that died
  mid-cycle is exactly what a human should look at. Opt out with
  `settings.yaml::vault_commit.auto_merge: false`, which already existed.

### Fixed

- **`cycle --target-topics` was accepted and then discarded (spec 074).** (regression test: tests/cli/test_cycle_target_topics.py) `_cmd_cycle` called `run_single_cycle` without a spec, and the orchestrator
  guards the scout-prompt re-render on `spec is not None` — so the flag was
  accepted, documented in `--help`, threaded through two call layers, and
  inert. Reproduced against 1.0.0 on a live vault: the supplied strings
  appeared nowhere in `_pipeline/`. The command now loads the vault's
  `research.spec.md` and passes it through; if the spec cannot be loaded *and*
  topics were given, it exits 2 naming the file rather than quietly researching
  the backlog instead. Same family as spec 070's F1 and F4 — configuration the
  framework accepts and silently ignores.

- **An absent `sources_consulted` reported N symptoms instead of one cause.** (regression test: tests/scripts/test_sources_consulted_empty_message.py) `feeds-vault` cycle 9 aborted with seven errors of the form
  `required source 'hacker_news' not in sources_consulted`, which reads as "the
  agent skipped seven sources". It had not — there was no
  `cycle-009-research.json` at all. The per-source phrasing described what the
  validator observed rather than what happened, and it is convincing enough to
  send a reader to the wrong fix (in this case, as far as proposing the
  operator change their vault's research design). `validate_sources_v2` already
  handled a *missing* key this way; it did not handle an *empty* block, and
  `validate_sources` handled neither. Both now emit a single error naming the
  cause and pointing at the stage log. A genuinely partial report still names
  each missing source, which is the useful behaviour there.

- **"no reason given" was unanswerable: the prompt never asked.** (regression test: tests/scripts/test_prompt_validator_contract.py) `validate_cycle`
  warns `required source 'X' was not searched: <reason>` — it demands a reason
  from **required** sources. Both prompt templates offered the `reason` field
  only `if not ds.required`, so on a vault where every source is required the
  agent had **nowhere to put one**, and the validator printed "no reason given"
  for something it had never asked for. Observed on `feeds-vault`: 7 required
  sources, 5 skipped, 5 identical unanswerable warnings every cycle. The scout
  template contradicted itself outright — its prose said required sources must
  be "explicitly skipped with a reason" while its JSON schema withheld the
  field, and its rule list scoped `reason` to optional sources only. A skipped
  *required* source is the one that most needs to explain itself, so `reason`
  is now offered for every source and the rule says so.

- **A derived acronym that is an English function word became an alias note.** (regression test: tests/pipeline/test_acronym_function_words.py) `_derive_acronym` accepted any acronym with >= 2 initials, so "Nemotron Omni"
  derived **"NO"**, "Ilya Sutskever" derived **"IS"**, and "Opus 4.7
  Regression" derived **"OR"** — three notes titled with ordinary English words
  appeared in `feeds-vault`. The rule added is about matchability rather than
  spelling: `resolve_acronym_links` rewrites unresolved all-caps `[[TOKEN]]`
  references, so a function-word acronym is far more likely to be hit by
  accident than on purpose. Only the closed class is blocked (pronouns,
  articles, prepositions, conjunctions, auxiliaries), so "AI", "ML", "OS" and
  "RAG" keep working — none is an English word. Applied to both
  `pipeline/wikilinks.py` and the deliberate self-contained copy in
  `scripts/validate_vault.py`, whose parity is already test-guarded.

- **`--resume` hard-errored on a fresh vault (#150).** (regression test: tests/cli/test_resume_fresh_vault.py) `--resume` is the
  documented "safe to re-run if interrupted" verb, but on a brand-new scaffold
  it exited with `no in-progress cycle found; use --cycle <N> to specify` — the
  opposite of safe, at the moment an operator is least sure what is going on.
  The rc7 reference-vault validation hit it on its first invocation and the staging
  script grew a workaround injecting `--cycle 1`, doing by hand exactly what
  `--resume` is for. The resolution order (in-progress → highest completed + 1)
  is unchanged; only the final branch changed, from a hard error to cycle 1.
  This also covers the vault whose only cycle aborted, which spec 070 F10
  correctly makes look identical — it must be retried, not skipped. Corrupt
  `state.json` still errors.

## [private 1.0.0] - 2026-08-27

### Changed

- **Anthropic model tier defaults moved to the Claude 5 family.**
  `pipeline/settings.py::_DEFAULT_MODEL_TIERS` and the shipped `settings.yaml`
  now resolve `basic` → `claude-haiku-4-5`, `normal` → `claude-sonnet-5`,
  `flagship` → `claude-opus-5`. Two notes: the previous values
  (`claude-haiku-4.6`, `claude-sonnet-4.6`, `claude-opus-4.7`) were **dotted**,
  which is not a resolvable Anthropic model id in any version — ids are
  hyphenated; and there is no Haiku 5, so `basic` stays on the newest Haiku
  (4.5). `normal` also gets cheaper in the move (Sonnet 4.6 $3/$15 → Sonnet 5
  $2/$10). cursor-agent's own model scheme
  (`claude-opus-4-8-thinking-high`, `claude-4.6-sonnet-medium-thinking`) is a
  different namespace and is deliberately unchanged in `settings.cursor*.yaml`
  and `agent_call.py::_CURSOR_MODEL_TIERS`.

### Added

- **`settings.yaml::archived` — freeze a finished vault (spec 071).** With
  `archived: true`, every research-writing path refuses with exit 2:
  `./vault research`, `generate`, `generate --resume`, and any direct
  `orchestrator.run_cycles` call. The guard lives in the orchestrator rather
  than only the CLI, so a stale shim, a cron entry or a script is refused too,
  and it sits above `begin_run` so an archived vault comes away with no git
  branch and no run report. Everything else is untouched — the vault stays
  queryable (`ask`, `status`, `digest`, `health`, `audit`), maintainable
  (`re-grade`, `wikilinks`, `reindex`) and upgradeable (`./vault update`).
  The check reads the key with a direct YAML load rather than the typed
  settings loader, because that loader validates the whole file and an archived
  vault is exactly the one whose pipeline config nobody has kept current. Only
  a literal `true` archives; a non-boolean value is rejected outright by the
  typed loader.

- **`data_sources[].url` and `data_sources[].urls` (spec 070 FR1/FR1a).** A
  `kind: strategy_hint` source can now declare the domains it covers, and those
  domains ground citations at the source's `default_credibility`. `url:` was
  already being written in vault specs but had no field on `DataSourceConfig`,
  so it was discarded at parse time; `urls:` is new, because a strategy hint is
  routinely a *set* of domains that a single `url` cannot name. Both are
  additive and optional — a spec that declares neither is unaffected, and a
  source declaring `repos[]` keeps its existing behaviour exactly.
  See `docs/source-credibility.md` and
  `specs/070-.../source-grounding-migration.md`.

### Fixed

- **A declared source could not ground a citation to its own domain (spec 070 F1).** (regression test: tests/vault/test_credibility_strategy_hint.py) `build_credibility_context` indexed `repos[].url` only. A
  `kind: strategy_hint` source has no `repos[]` by definition, so its
  `default_credibility` never reached the index the verifier consults — silently
  inert, with no error and no warning. Notes about `engineering.bravo.example` and
  `engineering.charlie.example` were quarantined for "no visible source
  default_credibility" while both domains were declared sources carrying
  `default_credibility: primary`. Grounding is host-scoped and is consulted
  after the exact source-id index and before the spec-066 domain catalog, which
  is the order `docs/source-credibility.md` has always documented.
- **`github.com/<user>` did not ground, so practitioner notes were rejected (spec 070 F2).** (regression test: tests/vault/test_credibility_catalog_forge_profiles.py) The shipped catalog scoped `github.com` to
  `host_path, min_segments: 2` ("org/repo") — right for citing a repository,
  wrong for citing a person. Relaxed to `>= 1` for `github.com` and
  `gitlab.com`, and `codeberg.org` added at the same scoping. Bare
  `github.com/` still grounds nothing; `sourceforge.net` and `bitbucket.org`
  stay org-scoped, being project hosts rather than profile hosts.
- **A cycle reported notes it destroyed as notes it kept (spec 070 F3).** (regression test: tests/pipeline/test_quality_report_rejection_counts.py) `notes_rejected` in the per-cycle quality report was derived purely from a
  batch's `accepted` flag, so a batch that passed overall recorded
  `notes_written: 4, notes_accepted: 4, notes_rejected: 0` even when the
  per-note verifier had stamped notes inside it `verifier_status: rejected` and
  the orchestrator then swept them into `_pipeline/quarantine/`. A note now
  counts as rejected if its batch was rejected **or** the note itself is
  stamped rejected (quarantine included, so a prior sweep cannot hide it), and
  `accepted + rejected == written` now closes.
- **`--resume` could exit 1 with zero bytes on stdout and stderr (spec 070 F5).** (regression test: tests/pipeline/test_orchestrator_resume_ceiling.py) Indistinguishable from a crashed interpreter, and the blocker for
  every other fix in the spec. Three things composed: the resume anchor is
  `highest_completed + 1`; `max_cycles` is an **absolute ceiling**, not a count
  of additional cycles, so `range(7, 3 + 1)` was empty and the loop body never
  ran; and the resulting fall-through into `_constrained_exit` narrates
  entirely at `INFO`, which the TTY-aware default (spec 048 FR-005) drops when
  stdout is redirected. `run_cycles` now logs an `ERROR` naming the anchor, the
  ceiling, its source and the flag that raises it. Exit codes and control flow
  are unchanged. **`--max-cycles` semantics are unchanged** — it remains an
  absolute ceiling.
- **Any CLI verb exiting non-zero in complete silence (spec 070 FR6).** (regression test: tests/cli/test_nonsilent_exit_guard.py) `cli.main` now taps stdout/stderr and counts emitted log records; a non-zero
  return that produced nothing an operator could see gets a diagnostic pointing
  at `--log-level info`. A backstop, not a substitute for a real message — it
  stays quiet whenever the verb has already explained itself.
- **`./vault update` never refreshed vault-local `scripts/` — on any update.** (regression test: tests/pipeline/test_vault_update_script_sync.py) Three defects stacked, and the symptom was silent: a fix shipped in the wheel
  simply did not run, because `_resolve_script` prefers the VAULT copy and only
  falls back to the packaged one when the vault file is *missing*. (1) The verb
  ran `<archive>/install.sh`, which in a `RV_GITHUB_REF` **git archive** is the
  *maintainer* dev-setup script — it runs `pip install -e` and, with CWD set to
  the vault, tried to pip-install the operator's vault
  (`does not appear to be a Python project`). The end-user installer lives at
  `dist-templates/install.sh`; `vault_update.resolve_installer` now picks the
  right one for both the git-archive and release-tarball layouts. (2) That
  installer requires `--accept-path` in non-interactive mode, which the verb
  never passed, so it exited 2 before syncing anything. (3) It also needs a
  built wheel beside it, which a source archive has none of — so the verb now
  syncs `scripts/` directly from the package pip just installed, via
  `vault_update.sync_vault_scripts`. Set `RV_SKIP_SCRIPT_SYNC=1` to keep a
  deliberately customised vault script.
- **`./vault update --force` could not refresh a same-version bundle.** (regression test: tests/pipeline/test_vault_update_force_same_version.py) `--force` only ever bypassed the dirty-working-tree guard; the version
  short-circuit ran earlier and had no force path, so when the archive's
  version string equalled the vault's, `decide()` returned `noop` and the
  vault-local `scripts/` and `_templates/` were never re-copied — even though
  the Python package in the venv could be entirely different code. The verb
  reported exit 0 having changed nothing, which left an operator testing an
  unreleased build with a stale bundle and a success exit code. `--force` now
  defeats the short-circuit too; it still does **not** wave through an
  unconfirmed downgrade.
- **The scaffold git-ignored the control files spec 058 warns about.** (regression test: tests/generator/test_scaffold_gitignore_control_files.py) The generated `.gitignore` was `/*` plus a corpus re-include, so
  `research.spec.md`, `settings.yaml`, `_pipeline/research-backlog.md` and
  `_pipeline/coverage-targets.json` were all ignored — the framework was
  generating the exact condition `./vault health` then warns about, and an
  operator's edits to their own spec had no version history. The scaffold now
  re-includes those four (the `_pipeline` pair needs an un-ignore /
  re-exclude / un-exclude sequence, since git cannot re-include a path under an
  excluded directory). Regenerable noise — `scripts/`, `raw_data/`, per-cycle
  `_pipeline` artifacts — stays ignored. Existing vaults are unaffected: the
  scaffold only writes `.gitignore` when absent.
- **`--resume` silently skipped aborted cycles (spec 070 F10).** (regression test: tests/pipeline/test_aborted_cycle_not_completed.py) `_highest_completed_cycle` anchors resume on the highest
  `cycle-NNN-quality-report.json`, documenting the assumption that "a cycle
  that aborts mid-stream never writes the report". That assumption was false on
  all five live vaults checked — every aborted (exit 2) cycle had written its
  report — so resume advanced past the aborted cycle and its work was never
  retried, with no operator-visible signal. One such cycle had written 11 notes
  and had all 11 rejected. The orchestrator now writes a
  `cycle-NNN-aborted.json` marker on the exit-2 path (cleared when the cycle
  later completes cleanly), and the resume anchor skips a marked cycle.
- **A simple-format spec silently dropped its source annotations (spec 070 F8).** (regression test: tests/spec/test_simple_source_passthrough.py) `spec/simple.py` built each `DataSourceConfig` from a fixed subset of
  keys that excluded `kind`, `default_credibility`, `url`/`urls` and
  `local_path`. The worst consequence was a deadlock: spec 069's fail-closed
  source-backing gate tells the operator to "annotate `kind: strategy_hint`",
  and the simple parser then discarded that annotation — so a simple-format
  vault was blocked from every run with no legal way to comply. It also put the
  credibility model's source-default rung permanently out of reach for those
  vaults. Found by running the 070 build against a real simple-format vault.
- **`./vault re-grade` reinstated collision-renamed duplicates (spec 070 F9).** (regression test: tests/cli/test_regrade_duplicate_guard.py) The quarantine sweep renames on collision (`foo.md` → `foo-3.md` when the
  first is already quarantined), and re-grade restored both copies under their
  quarantine names — leaving byte-identical duplicates in `data_vault/` that
  inflate the graph and the coverage recount. Re-grade now refuses to reinstate
  a copy when stripping a trailing `-<digits>` names an existing live note
  *and* the bodies are identical; the duplicate is left in quarantine rather
  than deleted, since discarding content is the operator's call.
- **`required source 'X' was not searched: no reason given` (spec 070 F4).** (regression test: tests/scripts/test_validate_cycle_skip_reason.py) Emitted verbatim for five of nine sources every cycle. A reason the
  researcher never recorded cannot be invented, so the message now says exactly
  that and names the artifact the gap is in.

## [private 1.0.0rc11] - 2026-07-31

### Fixed

- **Rejected refresh of an existing note deleted the note instead of just the
  bad draft.** `_quarantine_rejected_notes` (`pipeline/orchestrator.py`) used
  to `rename()` whatever was on disk into `_pipeline/quarantine/` whenever a
  note carried `verifier_status: rejected` — fine for a brand-new note (there
  was nothing to lose), but silent data loss when the note-writer had
  overwritten an **already-committed** note in place and the rewrite was
  rejected: the live file held only the rejected draft, so quarantining it
  removed the note's real content from `data_vault/` entirely, leaving at
  best a dangling alias stub. Surfaced on `feeds-vault` (2026-07-30, cycle 6):
  three existing company/MOC notes were permanently overwritten this way.
  Fixed by adding `vault_git.head_content()`, which reads a path's
  last-committed body at `HEAD` (the auto-commit invariant guarantees `HEAD`
  is clean at the start of every cycle). `_quarantine_rejected_notes` now
  checks it before quarantining: if the note existed at `HEAD`, its committed
  body is restored to the live path and only the rejected *draft* is
  quarantined (under the same filename); if it didn't (a genuinely new note),
  behaviour is unchanged. New tests in `tests/pipeline/test_rejected_note_handling.py`
  cover both paths.

## [private 1.0.0rc10] - 2026-07-23

### Added

- **Spec 058 — `./vault health` warns when critical control files are
  untracked or git-ignored (advisory only).** `scripts/vault_health.py` gains
  a fourth sub-check (`scan_control_file_git_tracking`) that, on a git-backed
  vault, warns for any *present* control file —`research.spec.md`,
  `settings.yaml`, `_pipeline/research-backlog.md`,
  `_pipeline/coverage-targets.json` — that git is not tracking (`untracked`)
  or is ignoring (`ignored`, which wins over untracked). A new
  `## Control-file git tracking` report section renders the all-clear line,
  `- WARN UNTRACKED/IGNORED <path>` bullets (sorted by path), or
  `skipped (not a git work tree)` on non-git vaults. The check is **advisory**:
  warnings are excluded from `HealthReport.unresolved_count` and never flip
  the `./vault health` exit code (FR-004). Absent files and non-git vaults are
  silent; git state is never mutated.
- **Spec 057 — foreman `--tolerant` file-level retro coverage mode.** The
  Arm-A verifier (`scripts/foreman/verify_test_coverage.py`) gains a
  `--tolerant` flag that verifies `### Testing Requirements` blocks at **file**
  granularity (file exists + `pytest -v <path>` prints ≥1 `PASSED`) instead of
  per-node function/TDD checks. This lets *already-shipped* specs earn a
  coverage verdict from cheap file-only `` - **Test N**: `path.py` `` lines
  without back-filling node IDs or a TDD timeline. New surface:
  - `parse_tasks_md(content, matching_mode="strict"|"tolerant")` — tolerant
    parsing accepts file-only lines and ignores `**TDD discipline**:` flags
    (`tdd_required` forced `false`); **strict mode is unchanged** — a file-only
    line is still a `ParseError`/exit-2 (FR-005).
  - `check_file_has_passing_test(workdir, path)` file-level primitive.
  - `summary.matching_mode` (`"strict"` default | `"tolerant"`) in the JSON
    report; tolerant requirement rows set `function_defined`,
    `collected_by_pytest`, and `tdd_timeline_ok` to `null`. The human report
    gains a `MODE: strict` / `MODE: tolerant — file-level coverage only
    (not TDD-verified)` banner. Downstream gates MUST NOT treat a tolerant
    exit-0 as a TDD/strict foreman sign-off. Docs: `docs/foreman.md`.

### Fixed

- **`./vault` shim: `research`/`coverage`/`reindex` verbs were broken on every
  generated vault (exit 127).** `templates/vault-script.sh.j2` built the CLI
  invocation as a single string `RV="${VENV_PYTHON} -m research_framework.cli"`
  and called it quoted (`exec "${RV}" …`), which suppresses word-splitting — so
  bash tried to exec one literal file whose name was the whole string and died
  with `No such file or directory` (exit 127) on all three verbs. `RV` is now a
  bash **array** (`RV=("${VENV_PYTHON}" -m research_framework.cli)`) expanded as
  `"${RV[@]}"` at each call site.
- **`./vault research` pointed `--spec` at the wrong file.** The `research` verb
  passed `--spec "${VAULT_DIR}/settings.yaml"` — the settings profile, not the
  spec — so once the exit-127 bug above was fixed the verb failed immediately
  with `missing YAML frontmatter (must start with '---')`. It now targets
  `${VAULT_DIR}/research.spec.md` (the file `generate` writes into every vault
  for later `--resume` runs). Both fixes are covered by execution-level
  regression tests that run the rendered shim against a stubbed interpreter
  (`tests/generator/test_render_vault_shim.py`) — a render/lint check could not
  have caught either.
- **`/pipeline` command doc no longer misrepresents the `research`/`report`
  stages as working.** Every generated vault's `.claude/commands/pipeline.md`
  documented `resume`/`finish` as running research → verify → report with no
  caveat, but those two CLI-orchestrator stages are unwired stubs (they fail
  fast with `no rendered prompt available for stage '<stage>'`; see the 015g
  entry). `agents/pipeline.md.j2` now carries a "Known limitation" note under
  `/pipeline resume` and `/pipeline finish` directing users to `./vault
  research` until the templates are wired. Wiring them is tracked follow-up work.
- **015g — `pipeline runner` scout/research/report drivers no longer send an
  empty prompt to the agent CLI.** `pipeline/runner.py::_call_agent` invoked
  `agent_call.py` with no `--prompt-file` and nothing piped on stdin;
  `agent_call.py` falls back to reading its own (empty/closed) stdin, so the
  inner non-interactive `claude --print` call received `""` and failed with
  "Input must be provided either through stdin or as a prompt argument when
  using --print" — a message that gives no hint this is a pipeline wiring
  gap. `_drive_scout` now renders `_pipeline/prompts/scout-prompt.md`
  (substituting `{CYCLE_NUM}`/`{SCOUT_REPORT}` for a fixed single-shot run,
  skipping the cycle-based correction-directive injection since this runner
  has no cycle/retry loop) and passes it via `--prompt-file`. `_call_agent`
  now requires an explicit `prompt_file` argument and fails fast with an
  actionable error when it's `None`, instead of silently forwarding an empty
  prompt. `research`/`report` have no rendered template yet (unlike scout,
  which `research-framework generate` already produces) — they now fail
  clearly with that same guard rather than confusingly; wiring their
  templates is tracked as follow-up work.
- **Spec 067 follow-up — `vault wikilinks` now retroactively heals the
  *fully-expanded* self-acronym corruption (PR #179).** The corruption that
  actually shipped in reference-vault-rc7 was the acronym already expanded in full —
  `The CAP Theorem` rewritten to `The [[cache-aside pattern]] Theorem`. The sweep
  (and cycle-time `resolve_acronym_links`) only plain-texted all-caps `[[TOKEN]]`
  links, so it never saw the expanded form and left the corruption on disk
  (write-time prevention via the `IX-wikilink-title-corruption` verifier gate was
  already robust; only the retroactive cleanup had the gap). `_rewrite_acronym_body`
  now also reverse-maps a **bare** `[[phrase]]` whose *derived* acronym is one of
  the containing note's own title-acronyms but resolves to a different note, back to
  the plain acronym. Explicit `[[x|alias]]` links and alias redirect stubs are
  exempt. Verified on a copy of reference-vault-rc7: the 2 corrupted body links in
  `CAP Theorem.md` heal to `CAP`, idempotent on re-run.

## [private 1.0.0rc9] - 2026-06-15

### Added

- **Spec 066 — credibility-model calibration (canonical project domains must
  not 100%-reject; issue #153, rc8-wave #152).** The rc7 reference-vault run
  rejected 12/12 cycle notes with `IX-credibility-unresolved` because every
  canonical citation (`fastify.dev`, `github.com/org/repo`, `wikipedia.org`,
  `docs.aws.amazon.com`, …) hit the spec-055 "no source default applies" floor.
  Shipped:
  - **Default credibility domain catalog** —
    `src/research_framework/data/credibility_catalog.yaml` (~60 entries; the
    operator-facing `tier_1/2/3` vocabulary maps onto spec-055's
    `primary/corroborated/commentary` `Level`). Match types `exact` /
    `host_suffix` (wildcards are tier_3-only in the default) / `host_path`
    (e.g. `github.com` needs `org/repo`, ≥2 path segments). Ships in the wheel
    as package data. Grows via a YAML PR.
  - **`vault/credibility_catalog.py`** — fail-closed `ResolvedCatalog` loader +
    `lookup(url)` (exact → host_path → host_suffix). Wired into
    `effective_level` as the new step after the source-default lookup misses;
    the COI cap + off-field downgrade are unchanged on top of a catalog-supplied
    level.
  - **`settings.yaml::credibility`** (FR3) — `unknown_domain_policy: warn|reject`
    + a `trusted_domains` vault override that fully replaces matching default
    entries (Q11), at any tier.
  - **WARN/FAIL severity split** (FR2) — a catalog-miss well-formed URL is a
    **WARN** under the default `warn` policy (no longer blocks the cycle) and a
    **FAIL** under `reject`; a malformed URL is `IX-citation-malformed` FAIL.
    `_merge_verifier_verdict` only flips `rejected` on a `severity: fail`
    violation. This single seam stops the rc7 100%-reject.
  - **`./vault re-grade`** (FR4) — re-evaluate `_pipeline/quarantine/*.md`
    against the current model and reinstate credibility-only notes that are now
    clean (atomic restamp + move into `data_vault/<NN - Category>/` +
    `regrade(<date>): N notes reinstated` auto-commit; `--dry-run` / `--note` /
    `--json`; idempotent; zero LLM).
  No new runtime dependency; no `schema_version` bump (all additive). Existing
  vaults get the fix on upgrade with no operator action.

- **Spec 069 — declared-source backing validation + stagnant-source WARN
  (issue #160, rc8-wave #152).** The rc7 reference-vault declared 4 primary sources
  but silently dropped 3 of them across 4 cycles (a vault that lies about its
  coverage). Shipped:
  - **Declared-source backing validation** (FR1/FR2) — a declared `data_source`
    is `backed` (its locator trigger-matches an installed spec-020 module),
    `strategy_hint` (explicitly `kind: strategy_hint` — honest LLM-fetch
    guidance), or `unbacked` (neither → a clear scaffold-time error / fail-closed
    preflight FAIL: `source '<name>' declared but has no implementation`). New
    `kind` field on `DataSourceConfig` (additive; absent ⇒ inferred). The
    framework never rewrites `research.spec.md` — the operator annotates or drops
    in a module (Q2).
  - **Stagnant-source WARN signal** (FR3/FR5) — a source yielding zero
    facts/signals for ≥2 consecutive cycles is surfaced (advisory) in the cycle
    report + `./vault status`; never blocks a cycle.
  - **FR4** (relevance-classifier tuning) split to a follow-up sub-spec (needs
    live data). No new runtime dependency.

### Fixed

- **`./vault digest` reported 0% coverage for every category (spec 068; issue
  #156, rc8-wave #152).** The rc7 run drafted 107 substantive notes across 13
  categories, but the digest reported `0% → 0% (+0%)` everywhere and flagged
  each as "stagnant" — a v1.0.0 deliverable telling operators their vault had 0%
  coverage no matter how many notes were written. Coverage is now **recomputed
  from disk** (`recompute_from_disk` + `update_after_cycle` delegation, FR1);
  the cycle-end WARN-and-trust invariant moved before `write_report` (FR2); and
  `digest` / `status` read the recount (FR3/FR4). Build-gated regression guard
  (FR5).

- **Acronym wikilinks corrupted note titles (spec 067; issue #154, rc8-wave
  #152).** The shipped `CAP Theorem.md` opened with "The [[cache-aside pattern]]
  Theorem…" — spec 062's acronym first-occurrence-link logic rewrote the body
  link to a *different* note whose initials also spell C-A-P, visibly corrupting
  the note's own title in its first sentence. Now: multi-expansion acronyms are
  not auto-linked, a note never links its own title (self-title protection,
  FR1/FR2), a deterministic `IX-wikilink-title-corruption` verifier gate FAILs
  the corruption (FR3), and a new idempotent **`./vault wikilinks`** sweep verb
  re-evaluates + fixes existing notes (FR4/FR5). `scripts/validate_vault.py` map
  kept in parity (C1-b).

- **Every simple/throwaway-spec scaffold failed after spec 069 (regression).**
  Spec 069's source-backing validation (`source '<name>' declared but has no
  implementation`) rejected the framework's *own* default `Web` source — the
  one `spec/simple.py::_data_sources` injects when a simple spec declares no
  `sources`. Open web search is honest LLM-fetch guidance, not a module-backed
  source, so the default is now annotated `kind: strategy_hint` (069's
  canonical example). `generate` on a sources-less simple spec scaffolds again;
  regression test
  `tests/spec/test_simple.py::TestExpandCoreShape::test_default_web_source_is_strategy_hint_not_unbacked`.

- **First-cycle hard-abort on a scout-TERMINATE cycle (issue #158).** A
  scout that returned `TERMINATE` ("no DFS this cycle" — Condition A/B/C,
  `run_cycle_steps` rc==1) was wrongly fed through the CG-001 min-cycle-yield
  retry: zero notes is by design on the TERMINATE path, so CG-001 FAILed and
  retried the whole cycle, and on the rc7 reference-vault run the retry's Step 0
  (`vault_metrics.py`) failed and aborted cycle 1 with a spurious
  `cycle_runner returned structural error` — despite scout having seeded 354
  topics. `_incremental_retry_after_cg_fail` now short-circuits on rc==1
  (returns the TERMINATE verdict unchanged, no yield gate, no retry); rc==2
  still aborts immediately. (`pipeline/orchestrator.py` + regression test
  `tests/pipeline/test_orchestrator_retry.py::TestTerminateShortCircuitsYieldGate`.)
  The retry helper also gains an injectable `cycle_runner` seam so the control
  flow is unit-testable without a new monkeypatch-`run_cycle_steps` site
  (ROADMAP QW-9).

## [private 1.0.0rc8] - 2026-06-14

### Fixed

- **Quarantine ordering — verifier-rejected notes now move to
  `_pipeline/quarantine/` BEFORE the per-cycle commit, not after
  (issue #155 / PR #161).** The rc7 reference-vault validation surfaced
  GA-003 FAILing because rejected-note files were being deleted from
  `data_vault/` AFTER `vault_commit.commit_cycle()` had already
  closed the cycle commit, leaving 12 dangling deletes uncommitted on
  the research branch. The sweep (`_quarantine_rejected_notes`) now
  runs at the top of `_commit_this_cycle`, so the MOVE
  (`data_vault/...` delete + `_pipeline/quarantine/...` add) lands
  atomically inside the cycle commit. The post-cycle `_finalise`
  sweep remains as an idempotent safety net.
  (`pipeline/orchestrator.py` + new
  `tests/pipeline/test_quarantine_ordering.py`)
- **Cost telemetry — `_detect_agent_kind` no longer self-matches as
  `"fake"` (issue #157 / PR #162).** The rc7 sidecars all reported
  `agent_kind: "fake"` despite a real `cursor-agent` × Claude run,
  because the production shim's substring heuristic was tripping on
  its own `_FAKE_SHIM_MARKER` string literal. The detector now hunts
  a marker built via `"".join(...)` to defeat ruff's string-concat
  constant-folding, and a CI guard test asserts the marker never
  appears contiguously in `scripts/agent_call.py`. Real cursor /
  claude / codex / opencode runs are now correctly classified.
  (`scripts/agent_call.py` + new
  `tests/scripts/test_agent_call_detect_agent_kind.py`)
- **`./vault acceptance` GA-004 — graded exit-status grading,
  drops stale `"done"` vocabulary (issue #159 / PR #163).** Was a
  binary `exit_status == "done"` ⇒ PASS / else FAIL, which after
  spec 061's `complete` / `constrained` / `aborted` taxonomy meant
  every budget-constrained run FAILed GA-004 even when it had hit
  its configured `max_cycles` cap exactly (a perfectly healthy
  outcome). Now grades four states: `complete` ⇒ PASS,
  `constrained` at `actual == configured` ⇒ PASS,
  `constrained` at `actual < configured` ⇒ WARN ("budget cap tripped
  early"), `aborted` / missing report ⇒ FAIL. Vocabulary uniformly
  says "complete" (never "done"). Re-evaluating the rc7
  `run-report.json` (`exit_status: constrained, actual: 4, configured:
  6`) now correctly reports WARN instead of FAIL.
  (`cli/acceptance.py` + `tests/cli/test_acceptance_gates.py`)

### Notes

- **rc8-wave spec stubs filed for the four deferred validation
  findings (DRAFT, awaiting clarify).** `066-credibility-model-calibration`
  (issue #153 — verifier credibility model rejects every note on
  canonical project domains like apache.org), `067-acronym-wikilink-disambiguation`
  (issue #154 — "CAP Theorem" wikilinks to the unrelated "cache-aside
  pattern" note), `068-coverage-counting-correctness` (issue #156 —
  audit reports 0% coverage despite 107 drafted notes), and
  `069-source-relevance-tuning` (issue #160 — 3 of 4 declared sources
  went cold mid-run despite the spec's `data_sources` block). All are
  on the rc8-wave ROADMAP queue and gate v1.0.0.
- **Validation strategy**: rc7's existing `_pipeline/run-report.json`
  was re-evaluated with rc8's acceptance gates (read-only) to confirm
  the GA-004 grading flip from FAIL → WARN. The #155 + #157 fixes are
  evidenced by their TDD regression tests (deterministic, in the
  fast-loop suite); they were not re-exercised in a live cycle to
  conserve the validation budget.

## [private 1.0.0rc7] - 2026-06-13

### Added

- **Spec 064 — `opencode` executor (4th first-class runtime).** opencode is now a
  selectable executor (`default_agent: opencode` / `default_executor.runtime:
  opencode` / per-stage), wired through the single `agent_call.py` /
  `_RUNTIME_ADAPTERS` dispatch surface — the spec-052 cursor precedent. It is
  **provider-agnostic**: the model provider (Ollama / OpenAI / Anthropic / Google /
  OpenRouter / …) is a config choice (`--model provider/model`), so one executor
  reaches every provider with no new framework code. Closes the spec-047 dead-end
  (raw HTTP was non-agentic and couldn't write stage files); opencode runs a real
  agent loop with filesystem tools.
  - **`settings.opencode.yaml`** profile shipped (wheel force-include + bundle),
    with a local-Ollama tier map and the `--dangerously-skip-permissions`
    unattended posture. Writes are vault-contained via an auto-injected
    `--dir <vault>` (the codex `--cd` / cursor `--workspace` analogue) — no
    full-disk mode.
  - **Honest per-call cost**: opencode's NDJSON `step_finish` events are parsed for
    real tokens + cost. Local runs ⇒ measured `cost_usd: 0.0` + real tokens
    (`cost_source: runtime`); metered providers ⇒ the real pricing-catalog dollar
    (`runtime`), or the spec-033 estimator (`runtime_tokens`) — never a silent $0.
    Sidecars (spec 028) and the budget tally / `BUDGET_PAUSED` caps (spec 033,
    dollar + wall-clock) apply unchanged; no sidecar-schema bump.
  - **FR-015 preflight**: an opencode run fails closed before dispatch when the
    binary is missing, a local provider endpoint is unreachable, or hosted creds
    are absent (best-effort — opencode owns provider creds).
  - **Benchmark (spec 056)**: opencode is a dispatchable cell (guarded
    `valid_runtimes()`), sweeps arbitrary models, and the matrix executor block
    gains an optional `label` so several configs of one runtime show as distinct,
    readable cells (`opencode-local-qwen`, `opencode-gpt5`).
  - **Output text extraction**: opencode's stage output is its assistant *text*
    (the NDJSON `text` events), not the raw event stream — surfaced on both the
    `dispatch()` and CLI `run()` paths so stdout-based consumers (verifier verdict,
    benchmark scorers) get the answer. Cost is still parsed from the raw NDJSON.
  - **CLI-path parity**: the benchmark drives opencode via `agent_call.py run()`,
    which now also classifies opencode cost + fails closed via preflight (it
    previously only did so on the programmatic `dispatch()` path).

### Changed

- **Spec 047 (Backend-Agnostic Agent Layer) TOMBSTONED** — superseded by spec 064.
  Its shipped Ollama-HTTP dispatch primitive is left dormant (a code comment points
  Ollama users at the opencode path). Spec 011 (per-flow routing) now subsumes
  under 064.

### Notes

- **Spec 065 drafted (local-model agentic fit — SPIKE).** First live opencode +
  local-Ollama validation runs showed local 27–30B models don't *complete* the
  framework's autonomous structured stages (they research, then chat-summarise
  instead of writing the required JSON report). The opencode executor + the box
  (RTX 5070 Ti, ~32 tok/s once VRAM was un-wedged) are fine; the gap is
  model/prompt FIT. The **v1.0.0 validation campaign runs on `cursor-agent`**;
  local-model fit is deferred to post-1.0.0 (spec 065 spike: lean/vendor-neutral
  prompts, output-forcing agent profile, OpenHands evaluation).

## [private 1.0.0rc6] - 2026-06-09

### Fixed

- **Atlassian Jira extractor — migrate retired `GET /rest/api/3/search` →
  `POST /rest/api/3/search/jql`.** Atlassian Cloud retired the GET search
  endpoint (HTTP 410 Gone, 2025); the rc5 reference-vault validation run hit it
  live on a real site (`company_name.atlassian.net`) while Confluence — a different
  API — kept working. The Jira fetch path now POSTs a JSON body (`jql` +
  `maxResults` + explicit `fields`) to `/rest/api/3/search/jql`; the response
  shape is unchanged so parsing/identity/rendering are untouched. Two
  regression tests pin the new endpoint + request shape.
  (`modules/atlassian/extractor.py`)
- **`scripts/raw_capture.py` — sanitize YAML-hostile colons in captured
  `<title>`.** Captured titles such as `Exceptions :: Spring Framework` were
  copied verbatim into `source_urls[].title` and broke the whole note's
  frontmatter ("mapping values are not allowed here"). A colon-then-whitespace
  (`": "`) or `"::"` is now collapsed to `" - "`; a colon NOT followed by
  whitespace (`10:30`, `https://`) is left intact (already YAML-safe).
- **`scripts/validate_vault.py` — exempt `note_type: alias` redirect stubs from
  the full-note schema.** The acronym redirect stubs the framework generates
  itself (`pipeline/wikilinks.resolve_acronym_links`) are intentionally minimal
  (title + note_type + redirect_to + verifier_status). The validator was
  applying the required-field + 200-word schema to them and reporting a fistful
  of spurious violations apiece — the dominant driver of the rc5 reference-vault
  113→246 violation growth (the framework failing notes it writes itself).
- **Wikilink resolution — resolve space↔separator title-style links to on-disk
  stems.** Natural-language links like `[[Outcome Matrix Liability Vector
  Calculation]]` never matched `outcome_matrix_order_vector_calculation.md`,
  producing bulk "file not found" violations that drove note quarantines. Both
  `scripts/validate_vault.py` (related-link lookup) and
  `pipeline/wikilinks.py` (body + `related` normalization) now also try
  `space→_` / `space→-` variants; body links preserve the human-readable
  rendering via a pipe alias (`[[stem|Original Title]]`) while `related` entries
  canonicalize to the bare stem. Genuinely missing targets still fail.

## [private 1.0.0rc5] - 2026-06-08

### Added

- **Spec 060 Tier-2 batch-1 — `github` source module + explicit `code` ↔ `github`
  split** (PR #136,
  squash `a8d5240`). First-class `github` module under the spec-020 five-file
  template, leveraging the **`gh` CLI** (session auth — no API key to manage;
  24-hour sessions are ample for a cycle). Extracts PRs / issues / releases as
  `notable` observations; `manifest.yaml::url_pattern` triggers on
  `github.com/<owner>/<repo>` URLs; mandatory spec-051 `preflight()` reports a
  `warning` when `gh auth` is absent (fail-open: the module is skipped, not
  fatal). The overlap with `code` is now **deliberate and documented**: `code`
  is the source-agnostic, works-with-local-checkouts module; `github` is the
  hosted-GitHub-specific surface (PRs/issues/releases). Hermetic via a
  `GH_BIN`-override fake; `get_source_version` ↔ `extract` SHA-256 parity tested.
- **Spec 060 Tier-2 batch-1 — `atlassian` source module (Jira + Confluence on one
  REST surface)** (PR #137,
  squash `642ead5`). One module covering **Jira issues (REST API v3,
  `/rest/api/3`)** and **Confluence pages (REST API, `/wiki/rest/api`)** over a
  shared `urllib` HTTPS client with **Basic auth** (`ATLASSIAN_EMAIL` +
  `ATLASSIAN_API_TOKEN`). Jira sources accept a JQL query; Confluence sources
  resolve a page by ID (no silent space-wide broadening). Mandatory
  `preflight()` fails **closed** (`fatal_fail`) on missing credentials with
  clear per-variable messages, and only runs the live connectivity probe when a
  real Atlassian site is derivable from the source URLs (a misconfigured
  non-Atlassian URL degrades to `warning`, not a misleading probe error).
  Key-leak sentinel test; hermetic via a connectivity fixture seam.
- **Spec 047 v1 (preview) — Ollama HTTP executor: the first non-CLI runtime**
  (PR #138,
  squash `4a8c922`). Adds a guarded `http`/`api` dispatch branch at the single
  `scripts/agent_call.py` dispatch point so an **Ollama server** (e.g. a local
  box on the LAN) can serve stages over HTTP — a $0 cost lever after the
  2026-06-01 codex cap and a multi-vendor fallback. Parses **both** the
  OpenAI-compatible (`/v1/chat/completions`) and native Ollama (`/api/chat`)
  response shapes; `OLLAMA_BASE_URL` env overrides `base_url`; `OLLAMA_HTTP_FIXTURE`
  is the hermetic seam. Local ⇒ **true `cost_usd: 0.0` with REAL token counts**
  ⇒ `cost_source: "runtime"` (distinct from cursor's estimated-dollar
  `runtime_tokens`). Ships `settings.ollama.yaml` as a peer profile;
  `default_agent: ollama` is now valid; estimator + budget-guard updated.
  > **Preview / dispatch-only.** The 2026-06-08 validation run confirmed Ollama
  > over HTTP is a **non-agentic** backend: it returns text but cannot execute
  > the file-writing tools that agentic stages (scout, note-writer) rely on to
  > emit their stage artifacts. v1 is therefore validated as a **dispatch
  > primitive** (programmatic `dispatch()` callers + stages whose output is the
  > returned text), not yet a drop-in full-cycle executor. Closing that gap
  > (an output-file contract for HTTP stages) is deferred to a later 047 stage.
- **Spec 056 — executor × model benchmarking harness** (PR
  #139,
  squash `88504cd`). A standalone, user-run **eval tool**
  (`scripts/benchmark_executors.py` + `src/research_framework/benchmark/`) that
  sweeps a `{task × executor × model}` matrix against a frozen fixture and
  scores **quality** (spec-022 calculators + deterministic checks — Principle IV,
  no LLM-judge), **cost** (spec-028 sidecars / spec-033 estimator, measured-vs-
  estimated split), and **latency** per cell into dated, accumulating
  JSON + Markdown reports. Runtimes are validated against `agent_call`'s
  `_RUNTIME_ADAPTERS ∪ _HTTP_RUNTIMES`, so spec-052 `cursor-agent` and spec-047
  `ollama` are both dispatchable matrix cells. **Outside every CI gate** (fast
  loop / smoke / quality harness) — the canonical `live_llm` opt-in surface;
  a guard test asserts it stays unwired. Hermetic `--dry-run` replay path;
  per-cell cost cap on the live sweep.

### Fixed

- **Source-bridge default validator no longer marks notable-only sources FAILED**
  (PR #140,
  squash `5dfd4dd`). The default rule treated a `verdict: ok` payload with empty
  `facts` as a contract violation, but **every** notable-only module (all Tier-1
  ports + the new `github`/`atlassian`) legitimately emits `facts: {}` with
  observations in `notable` — so successful extractions were being reported
  source-health FAILED. An `ok` verdict is now valid with facts **or** notable
  signal; only a wholly-empty `ok` (neither) remains a violation. Surfaced by
  the 2026-06-08 MCP-free validation run.
- **Ollama `run()` HTTP sidecar now reports honest metadata** (PR #140). The
  `_run_http` path wrote `agent_kind: "fake"` with `2000-01-01` sentinel
  timestamps and `latency_ms: 0` whenever the surrounding vault carried a fake
  shim, even though the dispatch was a real network call. It now reports
  `agent_kind: "real"`, real wall-clock `started_at`/`completed_at`, and a
  measured `latency_ms` — the fake-agent shim is a separate file with no HTTP
  code, so reaching `_run_http` is unambiguously a real dispatch.

## [private 1.0.0rc4] - 2026-06-08

### Added

- **Spec 052 — `cursor-agent` as a first-class third LLM runtime.** A cost
  lever after the 2026-06-01 codex token cap: `cursor-agent` bills against a
  flat-rate Cursor subscription (~$0 marginal), so vaults can run when
  Anthropic/OpenAI quotas are exhausted. Wired through the single dispatch
  surface (`scripts/agent_call.py::_RUNTIME_ADAPTERS`) — no new `claude`/`codex`
  code paths were forked.
  - **Adapter** `_cursor_cmd` / `_cursor_cmd_with_cost`: builds
    `cursor-agent -p --output-format json|stream-json --model <m> --trust
    [--workspace <vault>] [args…]`, reading the prompt from stdin. `--trust`
    is required headless; `--workspace <vault>` is auto-injected (the cursor
    analogue of codex's `--cd`) so the agent writes notes into a vault in a
    sibling directory while staying *contained* to it — no `danger-full-access`
    needed. `CURSOR_BIN` overrides the binary (mirrors `CLAUDE_BIN`/`CODEX_BIN`).
  - **Honest flat-rate cost** (new `cost_source: "runtime_tokens"`): cursor
    emits REAL token counts (`usage` block) but NO dollar figure, so the
    sidecar records the real tokens and derives the dollar from the spec-033
    estimator. The dollar cap fires on that estimate; the metered-token cap
    (`pipeline` token accounting, generalized to `_METERED_TOKEN_AGENTS =
    {codex, cursor-agent}`) fires on the real tokens. Never a silent `$0`.
    `claude`/`codex` sidecars are byte-identical (regression-guarded).
  - **`settings.cursor.yaml`** profile shipped as a peer of `settings.codex.yaml`
    (wheel force-include + bundle copy): `default_executor.runtime: cursor-agent`,
    the `basic→composer-2.5-fast / normal→gpt-5.4-high /
    flagship→claude-opus-4-8-thinking-high` tier map, `--force`/`--approve-mcps`
    for unattended cycles, and the `--workspace` write-confinement story.
    `--settings` is filepath-only, so `rv generate --settings settings.cursor.yaml`
    needs no generator changes.
  - Config: `default_agent: cursor-agent` is now a valid `settings.yaml` value;
    estimator gains a `cursor-agent` calibration + `o200k_base` tokenizer
    branch; the tier-2 LLM-dispatch guard rejects any stray direct
    `cursor-agent` subprocess.

### Fixed

- **Test-infra regression (#128) — the two `tier-5` cycle e2e scenarios
  `test_cycle_oos_topic_rejected_by_verifier` and
  `test_cycle_partial_yield_trips_diversity_gate` failed at 1.0.0rc3.** Root
  cause was an incomplete spec-061 migration in the test scaffold
  (`tests/_helpers/vault_factory.py`), NOT a product regression: spec 061 moved
  the cycle horizon from the research spec into `settings.yaml`
  (`pipeline.max_cycles` + `pipeline.budget_usd`, both required by
  `load_vault_settings`), but `build_minimal_vault` only baked its `max_cycles`
  param into the *default* settings. A test that supplied its own `settings_text`
  (both failing tests do) silently dropped `max_cycles`; the settings then failed
  to load, `effective_max_cycles` fell back to `DEFAULT_MAX_CYCLES` (20), and the
  per-cycle yield quota collapsed to 1 — so only one note was ever written and the
  scout-OOS / note-writer-partial-yield scenarios never got exercised. The factory
  now injects the canonical `pipeline` budget keys on the supplied-`settings_text`
  path too (YAML round-trip; the `max_cycles` param is authoritative, `budget_usd`
  defaults to 10.0 when absent). A new contract test
  (`test_custom_settings_text_still_carries_factory_max_cycles`) locks the
  behaviour. **Surfaced a CI gap**: these are `@pytest.mark.e2e` tests that the
  `-m "not e2e"` fast-loop CI job never ran; `build.sh`'s smoke gate runs only a
  subset, so the break shipped in rc3. (Test-only change, no product code touched,
  no version bump.)
- **Spec 061 FR5 follow-through — the `codex` settings profile no longer ships
  the deprecated `cycles.initial_max: 6` / `update_max: 3` seeds.** `settings.yaml`
  (claude profile) had them removed in 1.0.0rc3, but `settings.codex.yaml` — the
  profile the validation campaign runs on — still carried them. Functionally the
  spec-061 resolver already made the canonical `pipeline.max_cycles: 20` win (so
  no silent 12→6 truncation), but the stale seeds emitted a deprecation `WARNING`
  on every codex run and violated FR5's "seeds agree, no disagreement" acceptance.
  Both shipped profiles now expose exactly one cycle-budget key. (Post-1.0.0rc3
  doc/seed-sync pass; bundle-only change, no version bump — rebuild the bundle
  from `main` to pick it up.)

## [private 1.0.0rc3] - 2026-06-06

### Changed

- **Spec 048 (v2.1 amendment) — the Source-Consideration Ledger now reconciles
  its verdicts against what the notes actually cite.** At ledger-build time it
  builds a note-citation corpus from every `data_vault/**` note's `source_urls`
  frontmatter (data the v2 join never read) and adds a new terminal verdict
  **`LEDGER_DISAGREEMENT`**: a source whose host is cited by ≥1 note can no
  longer read as a 0-contribution `ACCESS_FAIL`/`PIPELINE_DROP`/`NOT_REACHED` —
  the contradiction is relabelled (original join verdict preserved in
  `disagreement_was`) and excluded from the FR-019 required-failure set. Fixes
  the codebase-vault rc1 defect where the ledger asserted ACCESS_FAIL on sources
  cited at 100%/71%/63%. Also adds best-effort `read_via ∈ {direct,mcp,unknown}`
  attribution (FR-024) so an MCP-only source is never silently dropped. Sidecar
  schema `1.0 → 1.1` (additive `read_via`/`disagreement_was`); spec 053's
  trunk-inversion gate treats `LEDGER_DISAGREEMENT` as citation-evidenced.
- **Spec 028 (rc3 amendment) — codex/non-claude dispatches now record a real
  cost, never a silent `$0`.** Sidecar schema bumps `1.1 → 1.2` with one
  additive field, `cost_source ∈ {"runtime","estimated","none"}`. A non-claude
  dispatch tries to parse codex's own per-call cost (best-effort
  `_codex_cost_from_output`; `cost_source: "runtime"`); when codex emits none it
  falls back to the spec-033 `cost_estimator` value (`cost_source: "estimated"`);
  only a total estimator failure yields `cost_source: "none"` plus a loud
  `WARN`. Previously every codex sidecar wrote `cost_usd: 0.0`, defeating budget
  math and the spec-063 GA-005 telemetry gate. The field is additive — v1.1
  readers (`run_report`, `cost_estimator`, `budget_guard`) tolerate both
  versions, and a sidecar that omits `cost_source` still validates.
- **Spec 061 — the per-cycle budget is consolidated onto one canonical key
  (`settings.yaml::pipeline.max_cycles`), resolved by a single precedence
  ladder `--max-cycles flag > pipeline.max_cycles > built-in default (20)`.**
  Fixes the rc1 footgun where `cycles.initial_max: 6` *silently* won over a
  spec asking for 12 cycles (the codebase-vault run did 6). The deprecated
  `cycles.initial_max`/`update_max` keys are now **warn-and-honoured** — used
  only when `pipeline.max_cycles` is absent, and ALWAYS emitting one loud
  `logging.WARNING` naming the canonical key (never silently). The shipped
  `settings.yaml` seed drops those deprecated keys (`settings.codex.yaml`
  already carried only `pipeline.max_cycles: 20`).
- **BREAKING (spec schema): the per-cycle budget + dollar cap were removed from
  the research spec.** `budget.max_cycles`, `budget.max_usd`, and the top-level
  `max_cycles` are gone from `BudgetConfig`/`SpecConfig` — they are *operational
  config* (ADR-0011) and live exclusively in `settings.yaml`
  (`pipeline.max_cycles` / `pipeline.budget_usd`). A stray budget key in an old
  spec is now silently ignored exactly like any unknown field (no validator
  error), so existing specs still parse. Cycle-time yield readers
  (`research_plan`, `quality_report`) and the scaffold read the canonical
  settings value via the new `pipeline.settings.effective_max_cycles`.
- An over-budget override is now a `logging.WARNING` (suppressible by
  `--log-level error`), not a buried `print`; the orchestrator's constrained-exit
  hint names `pipeline.max_cycles` / `--max-cycles` instead of the removed
  `budget.*` spec keys.
- **Spec 062 — verifier-rejected notes are quarantined on ANY exit.** On a
  constrained (or clean) exit, every note still carrying
  `verifier_status: rejected` is moved out of `data_vault/` into
  `_pipeline/quarantine/` (uncited, unindexed) with a research-backlog rewrite
  pointer — so a truncated run can no longer ship rejected notes as if they
  passed the Principle-IX gate. Fixes the rc1 symptom of 14 rejected notes
  indexed and queryable. Clean-exit behaviour is unchanged (the rewrite loop
  clears rejections first; the sweep then finds zero).
- **Spec 062 — the per-cycle auto-commit is idempotent and leak-checked.** A
  same-cycle re-emit (e.g. a metadata correction) now folds into the single
  `research: cycle N` commit via `--amend` instead of producing a second one;
  and any content left untracked under `data_vault/` after the cycle commit is
  a fail-loud **constrained exit** (Principle X), never silently shippable.
  Fixes the rc1 symptom of two `research: cycle 6` commits + 12 untracked
  `… 2.md` files.

### Added

- **Spec 063 — `./vault acceptance`, a framework-generic acceptance harness.** A
  new read-only verb (`research-framework acceptance --vault <vault>`, `--json`,
  `--strict`) runs six deterministic, LLM-call-free gates over the artifacts a
  vault already emits and writes a versioned scorecard to
  `_pipeline/acceptance/report-<date>.{json,md}` (`schema_version: "1.0"`): **GA-001**
  no `verifier_status: rejected` note in the corpus (consumes spec 062 FR1 +
  run-report `rejected_unresolved`), **GA-002** no duplicate notes (spec 062 FR2
  detector), **GA-003** clean `data_vault/` git tree + one `research: cycle N`
  commit per cycle (Principle X; advisory WARN when the vault isn't a git repo),
  **GA-004** a constrained exit can never grade "done" (spec 061 FR4 `cycle_budget`),
  **GA-005** `total_cost_usd > 0` with tokens recorded — FAILs loud on `$0` (spec
  028 amendment), **GA-006** template-drift (advisory WARN). Exit is `1` iff any
  FAIL gate; `--strict` promotes WARN to blocking. Beyond the gates the scorecard
  carries (US2) a **ledger↔citation reconciliation** view that reads the shipped
  `source_ledger.py` and reports a cited-but-failed source as a `LEDGER_DISAGREEMENT`
  instead of a wall of `ACCESS_FAIL`; (US3) per-citation **authority (053) +
  credibility (055) grading** — `derived_trunk_role`, `authority_inversions`,
  `credibility_ungraded`, `coi_flagged` — graded against the vault's *own* derived
  trunk (a journal-/docs-first vault is never punished for not citing code); and
  (US4/US5) a discovered summary of the in-vault `_pipeline/acceptance/` **domain
  probe pack** (GOLD anchors + breadth score; the framework discovers, never
  imports it). The verb is shipped in the vault shim (`./vault acceptance`, exposed
  on `regenerate-shim`) and **auto-runs at a clean orchestrator exit** to record the
  scorecard — without ever changing the run's own 0/1/2 exit code.
- **Spec 062 — title-derived acronym links resolve (FR3).** A deterministic
  acronym map (initials of significant title words ∪ explicit note `aliases:`)
  rewrites unresolved all-caps `[[OECDH]]` references to the canonical note stem
  and generates an idempotent `note_type: alias` redirect stub per acronym.
  Ambiguous acronyms (two notes ⇒ same initials) are dropped — never
  wrong-linked — and surfaced as a `validate_vault.py` WARNING. Alias/redirect
  stubs are classified out of coverage targets, spec-022 quality metrics, and
  Principle-VIII stub-as-fuel accounting (graph-resolution nodes, not research).
- **Spec 062 — `validate_vault.py` gains a duplicate-note + dead-acronym
  class.** A reusable `find_duplicate_notes(data_vault)` detects OS-style
  ` N.md` siblings and byte-identical content duplicates (shared with the spec
  063 harness); the dead-acronym-link class now returns 0 on a vault whose
  titles imply the acronym. `run-report.json`/`run-report.md` gain a
  `rejected_unresolved` count + "Verifier:" headline (spec 063 GA-001 signal).

- **`--max-cycles N` / `--max-usd X` flags on `research-framework generate`**
  (the documented last word, honoured identically across generate / `--resume`
  / inline phase-3). `--max-cycles 0`/negative exits 2 with a clear message.
- **`_pipeline/run-report.json`** — an additive machine-readable run report
  carrying a `cycle_budget {configured, source, actual, exit_status}` provenance
  block (and a "Cycle budget" headline in `run-report.md`), so a constrained
  (`max_cycles`-reached) run is distinguishable from a clean completion. This is
  the signal the spec 063 acceptance harness (GA-004) consumes.

## [private 1.0.0rc2] - 2026-06-05

Bug-fix release candidate. Surfaced during the rc1 live-validation runs: a
reference-vault overnight run aborted in cycle 1 because 15 of the vault's
regenerable `scripts/` (including `validate_cycle.py`) were deleted ~43s into
the scout — the `scripts/` directory is git-ignored (the scaffold tracks
`data_vault/` only) and lives inside the agent's `danger-full-access`
workspace, so an external sweep / sandbox cleanup / stray `git clean -x` can
remove it out from under a long unattended run. The codebase-vault run, whose
scripts survived, completed all six cycles on the identical bundle. rc2 attacks
this on two layers: the **root cause** (the agent ran with `danger-full-access`,
i.e. UNsandboxed full-disk read+write+network — the behavioural pattern that
trips endpoint security; now contained to the vault under `workspace-write`)
and the **symptom** (a missing regenerable script no longer aborts a cycle).

### Changed

- **Codex agents are now contained to the vault under `--sandbox
  workspace-write` — `danger-full-access` is no longer required.** The only
  reason operators were forced onto `danger-full-access` was geometry: codex
  inherited the launcher's cwd (typically `~`/`~/Documents`) as its sandbox
  *working root*, and a vault in a *sibling* directory was unreachable to
  `workspace-write` (which confines writes to that root). `agent_call.py` now
  auto-injects `--cd <vault>` so the working root **is** the vault, making the
  long-standing `settings.codex.yaml` `workspace-write` default actually
  usable. The codex profile also adds
  `-c sandbox_workspace_write.network_access=true` (workspace-write blocks
  outbound network by default; MCP servers run in the codex process so they
  are unaffected, but the research agent's shell fetches need it). Net effect:
  the agent can read anywhere the OS allows (code-first vaults still read repos
  outside the vault) but can only **write** inside the vault — it can no longer
  touch the framework bundle, other vaults, or `~/Documents`, which both
  removes the most likely endpoint-security trigger and bounds the blast
  radius. An explicit operator `-C`/`--cd` in `args` is honoured (no double
  flag). New regression tests in `tests/scripts/test_agent_call.py`
  (`TestCodexWorkingRoot`).

### Fixed

- **Pipeline survives loss of its regenerable vault `scripts/` mid-run.**
  `pipeline/_helpers/script_runner._run_script` now resolves a missing
  `<vault>/scripts/<name>.py` to the immutable packaged copy shipped in the
  wheel (`research_framework/_data/scripts/<name>.py`, via `asset_path`)
  instead of letting `python` exit 2 ("can't open file") and abort the cycle.
  The fallback is per-invocation (so it also covers a script removed
  *between* the cycle start and the call), logs a `WARNING` naming the
  packaged path it fell back to, and is a no-op when the vault copy is present.
  When neither copy exists, the original missing-file behaviour is preserved
  (no surprise redirect). New regression tests in
  `tests/pipeline/test_run_script_streaming.py`.

## [private 1.0.0rc1] - 2026-06-04

First release candidate for v1.0.0. Bundles the complete Wave-3 / rc1
deliverables (specs 035 + 040) on top of the 0.10.0 Wave-2 foundation, for
validation against the three live runs (new reference-vault, new codebase-vault,
feeds-vault update) before the final 1.0.0 cut.

### Added

- **Rich vault reports + delivery (spec 040).** Every cycle now re-renders
  `_pipeline/audit-report.md` with five deterministic sections (Coverage Delta,
  Top Discovered Sources, Cost Summary, Source Quality Drift, Flagged Issues)
  by reusing spec 035's digest section builders plus two new aggregators.
  Optional PDF via `pip install research-framework[reports]` (`fpdf2` extra);
  optional cloud-folder mirror (`reports.mirror.target`) and SMTP delivery
  (`reports.smtp.*` + `RF_SMTP_USER` / `RF_SMTP_PASSWORD` env vars). All
  delivery layers fail closed and non-blocking.
- **`./vault digest` verb (spec 035)** — deterministic, LLM-call-free cross-cycle
  markdown roll-up over local cycle artifacts (`--since`, `--last-week` /
  `--last-month` / `--last-quarter`, optional `--output`). Default output:
  `_pipeline/digests/digest-<start>--<end>.md`. See
  `specs/035-cross-cycle-digest/contracts/digest-format.contract.md`.

## [private 0.10.0] - 2026-06-04

### Added

- **Spec 039 — Installer Hardening.** `dist-templates/install.sh` now honours
  `$1` / `${VAULT_DIR}` for `TARGET` resolution (fixes the F2 bug where
  `./vault update` wrote into the bundle tmpdir instead of the vault),
  splits bundle inputs (wheel + `.agents/skills` from `ROOT_DIR`) from vault
  writes (`.venv/`, `rv`, scaffold, `install_summary.json` under `TARGET`),
  adds `--dry-run` / `INSTALL_DRY_RUN=1` with a `run()` guard wrapper,
  `uname`-based macOS/Linux OS branch (unsupported → exit 3), three-tier
  dependency probing (MANDATORY `python≥3.11`/`git`/`curl`; WARN `rsync`/`claude`;
  INFO `codex`/`weasyprint`/`gh`) via `command -v` only, idempotent fast re-run
  (<5s when `.venv` + `install_summary.json` exist), and atomic
  `TARGET/_pipeline/install_summary.json` on every run. Six new regression
  modules under `tests/scripts/test_install_*.py`.
- **Spec 009 — Cross-Platform Portability Guard + PR CI.** New
  `scripts/check_portability.py` — a deterministic, **stdlib-only** guard
  (<0.3s, runs in `pytest -m "not e2e"`) that fails on a reintroduced macOS-ism
  in shipped code: BSD `sed -i ''`, bash-4 constructs (`${v^^}`/`${v,,}`/
  `declare -A`/`mapfile`/`readarray`/`&>>`) in shipped `.sh`, or a hardcoded
  macOS path (`~/Library`/`/opt/homebrew`/`/usr/local/bin`/`/Applications/`) in
  `.py`/`.sh` code (`*.md` exempt; `.specify/**` excluded). The 2026-06-03 audit
  found the shipped tree already portable — this **regression-locks** that
  state. New **`.github/workflows/ci.yml`**: the project's first PR CI, on a
  `{macos-latest (REQUIRED), ubuntu-latest}` matrix (`fail-fast: false`), each
  leg running the guard + `pytest -m "not e2e"` + `ruff check` +
  `ruff format --check` + `shellcheck` over shipped `.sh` + a 039
  `install.sh … --dry-run` smoke. New contributor contract
  **`docs/PORTABILITY.md`** (mirrored 1:1 with the guard via a drift-lock test).
  Two `SC2012` `ls|head` wheel globs in `install.sh`/`build.sh` annotated with
  justified `# shellcheck disable`. (regression tests:
  `tests/scripts/test_portability_guard.py`, `tests/scripts/test_ci_config.py`)
- **Spec 048 v1.1** — `vault status --vault <path> [--json]` read-only CLI verb
  (active cycle: stage, elapsed, budget remaining, last `cycle.log` line;
  idle: FR-013 health header + days-since-last-success + deferred warnings).
  Regression: `tests/observability/test_vault_status.py`.
- **Spec 048 v1.1** — one-line cycle-health header as line 1 of every
  `cycle-NNN-summary.md` (`health_header()` in `pipeline/cycle_summary.py`).
  Regression: `tests/observability/test_health_header.py`.
- **Spec 048 v1.1** — per-cycle `cycle.log` (`observability/cycle_log.py`) +
  extended `_pipeline/state.json` (`pipeline/cycle_state.py`) for live status.
  Regression: `tests/observability/test_cycle_log.py`,
  `tests/observability/test_cycle_state.py`.
- **Spec 048 v1.1** — pipeline-wide `print()` allowlist gate
  (`tests/observability/print_allowlist.txt` +
  `test_log_surfaces.py::test_pipeline_print_allowlist_no_net_new_unlisted_prints`).
- **Spec 055 — Source Credibility Model.** Four-level ordinal enum
  (`primary` > `corroborated` > `commentary` > `unvetted`) declared per
  citation in Tier-2 `source_urls`, with optional per-source
  `default_credibility`, COI cap at `commentary`, and spec-053-role off-field
  one-step downgrade. Pure resolver at `vault/credibility.py`; verifier emits
  `IX-credibility-*` shape rules; quality harness `source_quality` family adds
  `tier2_source_ratio`. Author guidelines: `docs/source-credibility.md`.
  (regression test: `tests/vault/test_credibility.py`,
  `tests/quality/unit/test_source_quality.py`)
- **Spec 029** — `scripts/reconcile_source_metrics.py`, a one-shot, idempotent
  repair tool for vaults harmed by the attribution bug below. It recomputes each
  source's current citations from `data_vault/` frontmatter and (a) un-archives
  any `status='archived'` source that is still cited, (b) resets that source's
  `consecutive_empty_cycles` to 0, and (c) leaves genuinely-uncited sources
  untouched. `--dry-run` (default) prints a per-source diff and mutates nothing;
  `--apply` writes **only** `sources.db` (never the note tree); a second
  `--apply` is a no-op. On a vault that never ran the buggy code it reports zero
  changes (FR-008 / SC-005).
- **Spec 029** — `source_manager.normalize_source_url()` (stdlib
  `urllib.parse`): canonicalizes URLs for attribution matching (lowercases
  scheme + host, strips a single trailing `/` and the `#fragment`, **preserves
  the query string**). New `mark_resolved(name, vault_dir)` appends an
  append-only `resolved` line to `source-incidents.md` on source recovery
  (FR-007).

### Fixed

- **Quality harness — `source_quality` metric crash on collapsed note paths.** (regression test: tests/quality/unit/test_source_quality.py)
  The spec-055 `source_quality` family walked `cycle_outputs[].notes_written`
  and called `parse_frontmatter` on each path, which raised `FileNotFoundError`
  when `notes_written` recorded a deduped target (e.g. `<slug>-2.md`) that the
  note-writer collapsed onto an existing note and never materialised on disk.
  This crashed `build.sh --quality` (the release gate) on the `tech-lite`
  fixture — invisible to PR CI because the only test exercising it
  (`test_quality_runner_leaves_tracked_tree_pristine`) is `e2e`+`slow` and the
  blessed `tier2_source_ratio` baseline is `0.0` (a `0.0` baseline yields a
  `n/a` delta that can never fail). `_unique_note_paths` now skips phantom
  paths; added a fast-loop regression in
  `tests/quality/unit/test_source_quality.py`.
- **Spec 009 — `vault update` crash on stock macOS bash 3.2.** (regression test: tests/cli/test_vault_update.py) The generated
  `vault` shim expanded `"${UPDATE_ARGS[@]}"` (an array that is empty whenever
  `update` is called with no extra flags) under `set -u`, which is an "unbound
  variable" fatal error on bash 3.2 (macOS's stock `/bin/bash`) — Homebrew bash
  4+/5 tolerates it, so the bug was invisible on developer machines. Switched to
  the `"${UPDATE_ARGS[@]+"${UPDATE_ARGS[@]}"}"` idiom (safe on every supported
  bash). The new macOS PR-CI leg (stock bash 3.2) now permanently guards this
  class of regression via `tests/cli/test_vault_update.py`.
- **Spec 009 — headless-CI test portability.** (regression test: tests/docs/test_doc_sync.py) Several pre-existing tests only
  passed on a primed developer Mac and broke under the new PR CI: `test_doc_sync`
  shelled out to `rg` (not installed on the runners) → rewritten to a stdlib
  walk; the argparse `--help` byte-identical goldens normalise the
  `(choose from …)` choice-quoting that changed across Python 3.11↔3.13 (the
  registry/order assertion is preserved); the 039 installer probe tests now use
  deterministic PATH isolation / version-stubs instead of assuming the host
  lacks `apt`/`python≥3.11`; and `ci.yml` configures a git identity so the
  Principle-X auto-commit path (`prune` boundary snapshots, `vault_commit`)
  works on the identity-less runners.
- **Spec 029 — Source Manager Correctness (two silent bugs).** (regression test: tests/pipeline/test_source_manager_correctness.py)
  (1) `notify_required_source_degraded` called `mark_degraded` with **2 args**
  against its 3-arg `(name, reason, vault_dir)` signature, so the cumulative,
  human-readable `_pipeline/source-incidents.md` operator log was **never
  written** (the `TypeError` was swallowed by a broad `except`). The call site
  now passes the in-scope `vault_dir` and the `except` is narrowed to `OSError`
  so a signature mismatch surfaces loudly instead of being masked (the per-cycle
  `cycle-NNN-source-incidents.json` telemetry sidecar is unchanged — both
  surfaces are kept). (2) `source_manager.record_cycle` counted per-source
  `notes_generated` by substring-matching the source URL/name against note
  **file paths** (which almost never match), corrupting `consecutive_empty_cycles`
  and **prematurely auto-archiving still-useful sources**. It now reads each
  newly-created note's frontmatter `source_urls` and counts via a shared
  `_note_cites_source(fm, name, url)` predicate (normalized-URL OR source-name
  fallback) that also backs the all-time `notes_referencing` metric, so the two
  can never diverge. The FR-005 regression test no longer monkeypatches a 2-arg
  `mark_degraded` lambda that hid bug (1). 29 new regression tests in
  `tests/pipeline/test_source_manager_correctness.py` +
  `tests/scripts/test_reconcile_source_metrics.py`.

- **Spec 026 — Fixture Isolation Hardening.** (regression test: tests/quality/test_fixture_isolation.py) The spec-022 quality harness no
  longer mutates the tracked source-of-truth fixtures under
  `tests/fixtures/quality/`. Both harness entry points — `run_fixture_cycles`
  (pytest, tier-6) and `python -m research_framework.quality.runner` (the path
  `./build.sh --quality` invokes) — now `shutil.copytree` the fixture into a
  throwaway workspace (a pytest `tmp_path`, or the gitignored
  `_pipeline/quality/work/` for the runner) via the new shared
  `quality.runner.isolate_fixture`, run the cycle there, and compute metrics
  against the copy. A clean run leaves no workspace behind (FR-007); a crashed
  cycle preserves it and prints the path (FR-006). `git status` is now clean
  after `./build.sh --quality`. Regression-locked by
  `tests/quality/test_fixture_isolation.py` (added to `build.sh::SMOKE_TESTS`).

### Changed

- **Spec 026** — untracked the volatile SQLite WAL sidecars
  (`tests/fixtures/quality/*/_pipeline/sources.db-{shm,wal}`) and replaced the
  blanket `tests/fixtures/quality/**/_pipeline/` ignore (which hid committed
  seed inputs) with narrow WAL-only patterns, resolving the tracked-and-ignored
  contradiction. The fixture bootstrap
  (`tests/fixtures/quality/_bootstrap_us3_fixtures.py`) is now a `--force`-gated
  dry-run so an accidental invocation can't silently rewrite the committed
  fixtures. The committed fake-agent shims were already machine-agnostic
  (`_BAKED_REPO_ROOT = None`); that invariant is now locked by a test, and
  `install_shim`'s baked-root logic was extracted to a documented
  `_baked_root_for` helper.

## [private 0.9.0] - 2026-06-03

### Added

- **Spec 053 — Plastic-but-Enforceable Source Authority (PR #95).** `role`
  (`behaviour|intent|domain`) + `priority` are now meaningful on every
  `data_sources[]` entry; each `note_type` may declare an `authoritative_role`
  (+ optional `authority_section`/`complementary_section`). The **trunk is derived**
  = the source with the unique minimum `priority` (no `trunk:` flag). New
  `pipeline/source_authority.py` (`build_source_role_index` / `resolve_role` /
  `derive_trunk_dict`) and `scripts/check_trunk_inversion.py` (Gate 4, FR-007).
  US3 ledger wire-in + Polish T020–T022 remain follow-ups.
- **Spec 048 v2 — Source-Consideration Ledger MVP (PR #98).** Read-only
  `scripts/source_ledger.py` emits a per-source verdict ledger (USED /
  SKIPPED_RELEVANCE / ACCESS_FAIL / PIPELINE_DROP / QUALITY_REJECT / NOT_REACHED)
  by joining existing artifacts (`sources.db`, research `searched`/`reason`,
  source-incidents, capture-failures, quality gates). Zero pipeline change.
- **Spec 032 — Pipeline Reliability (PR #100).** Layered sandbox detection for
  `processors/extract.py` (fail-closed; `RV_DISABLE_SANDBOX_DETECT` override; see
  `docs/sandbox-detection.md`); `extraction-failed` stub auto-retry on resume;
  sonnet timeout fallback ladder; `extract.py` migrated to `agent_call.dispatch()`
  with `model=` threading (Principle IV).
- **Spec 038 — Source-Module Resilience (PR #101).** EMPTY-vs-FAILED sustained-error
  gate (`quality/source_health.py` per-cycle aggregation); per-module auth/rate-limit
  preflight sweep; archive.org fallback (absolute snapshot URLs); install-preflight
  checks; manifest schema `authentication` now accepts the string `"none"` or an
  object.
- **Spec 027 — `./vault update` Hardening (PR #99).** Pre-flight existence loop +
  topology/health/dirty-tree/short-circuit guards (registered in
  `build.sh::SMOKE_TESTS`); Bash 3.2-compatible shim (`while read`, not `mapfile`);
  interactive TTY downgrade prompt (FR-012); corrupted-manifest-snapshot fallback in
  the scaffold preserve-path.

### Changed

- **Spec 049 — `_cycle_helpers.py` God-Module Split (PR #97).** Behaviour-preserving
  refactor: the 1354-LOC god-module split into focused submodules under
  `pipeline/_helpers/` (`_io`, `_probe_staging`, `_scout_prompts`,
  `cosmetic_correction`, `cycle_state`, `quality_report_guard`, `scout_correction`,
  …).
- **Spec 053 — strategy-driven enforcement gates (PR #95).** The three existing
  enforcement gates are now **strategy-driven** instead of hardcoded code=behaviour:
  grounding (`check_code_source_coverage.py`) resolves a note's claim-type from its
  `note_type.authoritative_role` and requires a citation of that role (legacy
  `classify_url` retained for note_types without an authoritative role); drift
  (`check_intent_drift.py`) compares the note_type's declared authority/complementary
  sections (opt-in) and reads `authority_drift` (legacy `intent_implementation_drift`
  still accepted); trunk-seed (`validate_cycle.py::check_termination_v2`) derives the
  trunk via the shared min-priority helper, accepts the v3 `topics_from_trunk` /
  `parent_trunk_topic_id` fields (v2 names still accepted), and preserves the
  pure-domain `if signatures:` guard so a journal-/docs-first vault never trips "not
  under enumerated repo". Code-first verdicts are unchanged (regression-locked on
  `vault-code-first`).

## [private 0.8.0] - 2026-06-02

**Spec 051 — Post-Revival Hardening** (PR #91, squash `773bdf7`). Consolidates the
five remaining REVIVAL-NOTES.md lessons. Verified: 1866 fast-loop tests +
`build.sh --quality` (3 fixtures, 0 regressions); Copilot review (4 findings)
addressed. Also carries two doc-only spec drafts (048 v2, 052).

### Added

- **FR1 — configurable CG-001 cycle-yield model.** New `settings.yaml::cycle_yield`
  block (multiplicative `base × cadence_factor × coverage_factor`, clamped to
  `[min_floor, max_ceiling]`); per-cycle `_pipeline/yield-calibration.json` sidecar
  records the model breakdown (the empirical record the FR1 re-tune will use).
- **FR2 — stale-venv detection + `--auto-confirm` on `./vault update`.** `install.sh`
  rebuilds a venv whose `pyvenv.cfg` interpreter no longer exists; `--auto-confirm`
  skips the prompt for unattended runs; a post-install version sanity check (installed
  `__version__` vs the bundled wheel) exits non-zero with remediation on mismatch.
- **FR3 — inbound-link-aware stub policy.** New `settings.yaml::stubs.anchor_link_threshold`
  (default 5); `classify_stub` flags a short note with ≥N inbound wikilinks as an
  `anchor-stub` (protected from deletion); new `vault/indexer.inbound_link_counts`.
- **FR4 — MANDATORY per-module `preflight()` subprocess contract.** All five in-tree
  modules (youtube/reddit/rss/oreilly/code) + `_template` ship a preflight subprocess;
  the orchestrator spawns it per module at cycle start and `./vault refresh-sources`
  runs a preflight sweep; verdict table (success/warning/fatal_fail) with fail-closed
  handling of crash/timeout/garbage.
- **FR5 — regression locks** for the 0.6.2 subprocess-tree-termination and 0.6.3
  quality-report-only completion-marker fixes.
- **Spec 048 v2 — Source-Consideration Ledger** scope (FR-017..021, high-priority eval
  lens) and **spec 052 — Cursor CLI executor** draft (high-priority cost lever) added as
  doc-only follow-ups.

### Changed

- **`manifest.yaml::preflight` is now a required key** (spec 020 manifest schema amended).
  A module without it **degrades gracefully** — skipped with a WARN (fail-closed via
  `isolated_call`), not a cycle crash. All in-tree modules updated.
- CG-001 minimum-yield is now the FR1 model; the 0.6.x staleness-staircase + cold-start
  caps were removed (and `test_remaining_yield_scaling.py` deleted, coverage migrated to
  `test_cg001_yield_model.py`).

### Fixed

- `cg001_yield` registered in the `cycle-quality-report.schema.json` contract — it was emitted by `quality_report` but unregistered (→ schema-shape test failure). (regression test: tests/pipeline/test_quality_report.py)
- `yield-calibration.schema.json` now allows `target: 0` (the fully-covered short-circuit). (regression test: tests/pipeline/test_yield_calibration_sidecar.py)
- Per-module preflight bare-string source entries are now **flagged** (warning "wrap as `{url: ...}`"), not silently accepted, matching the extractor's dict-only `load_module_sources`; `preflight_runner` guards a malformed `timeout_seconds`; `PreflightResult.from_json` rejects a non-boolean `applied`. (regression test: tests/source_bridge/test_preflight_orchestration.py)

## [private 0.7.0] - 2026-06-01

### Added

- **Principle X — Vault History is Append-Only Git (NON-NEGOTIABLE).** (regression test: tests/pipeline/test_vault_commit.py — 24 cases)
  Every framework operation that mutates a vault MUST land on disk as at
  least one git commit. Implementation:
  ``src/research_framework/pipeline/vault_commit.py``. Specification:
  ``specs/050-vault-auto-commit/spec.md``. Constitution amended to
  v1.4.0 (see Sync Impact Report at the top of
  ``.specify/memory/constitution.md``).

  - ``./vault research`` opens a dedicated ``research/<timestamp>``
    branch from a clean ``main`` (HARD STOP, exit 2, on a dirty main —
    the invariant refuses to co-mingle user edits with framework
    output), emits one commit per cycle, and squash-merges back on a
    clean exit. Constrained / source-exhausted exits retain the branch
    for review. Aborted cycles rewind their partial commit. Resume
    reuses the in-flight branch.
  - ``./vault update`` / framework upgrade auto-commits the resulting
    diff on ``main`` so bad upgrades are one ``git revert`` away.
  - ``./vault ask`` / ``./vault write`` / ``./vault sync`` auto-commit
    any files they produce.
  - New settings block: ``vault_commit: {enabled: true,
    push_on_complete: auto, auto_merge: true}``. Push attempts are
    best-effort (never fatal) when a remote is configured; ``never``
    suppresses, ``always`` requires a remote. ``enabled: false`` is
    the explicit opt-out.
  - Failure mode is defensive: commit / push failures WARN and never
    alter the cycle's rc. A sidecar at
    ``_pipeline/commit-failures-<label>.json`` records every failure.

### Fixed

- **`lifecycle.created_at_cycle` is now stamped at note-write time.** (regression test: tests/pipeline/test_stamp_lifecycle_cycle.py)
  Pre-0.7.0 nothing wrote the field — the note-writer skill template
  never mentioned it — so ``orchestrator._parse_note_created_at_cycle``
  returned ``None`` for every note, and downstream consumers (coverage
  attribution, deferred-work lists, cycle-summary writer) silently
  underweighted. ``_cycle_helpers._stamp_lifecycle_cycle`` now
  backfills the field right after each note_writer batch returns,
  idempotently (won't overwrite a value the agent set on purpose).
- **`repo.local_path` auto-bypasses `code_source_url_patterns` when it resolves.** (regression test: tests/spec/test_repo_local_path_auto_whitelist.py)
  Most common feeds-vault revival footgun: users with an internal git host
  and a valid ``local_path: /Users/.../src/foo`` declaration kept hitting
  "url does not match any allowed pattern" because they hadn't also
  added the host to ``code_source_url_patterns``. If ``local_path``
  exists on disk (``~`` and ``$VAR`` expanded) the URL pattern check is
  now skipped for that repo — the user has physically "vouched" for
  the source. ``file://`` defaults still work unchanged.
- **`validate_vault.py` recognises path-prefixed `[[Folder/Note]]` wikilinks.** (regression test: tests/scripts/test_validate_vault_path_prefixed_wikilinks.py)
  Pre-0.7.0 the stem set returned only bare filenames, so a related-link
  of the form ``[[04 - Concepts/Sample]]`` always tripped "file not
  found" even when ``data_vault/04 - Concepts/Sample.md`` existed. On
  the feeds-vault revival this generated 2,120+ false SG-004 WARNs per
  cycle and made the gate report unreadable. Stem set now includes the
  full relative path (case-insensitive); lookup tries bare stem, full
  path, and the trailing path segment.

### Notes

- Spec 050 follow-ups deferred to a future minor release:
  - ``--leave-branch`` flag + ``vault_commit.auto_merge: false``
    override so per-cycle granularity stays on ``main`` rather than
    squashing on success.
  - ``./vault reconcile-branches`` verb to triage stale research
    branches in bulk (relevant once the F1 follow-up lands and users
    actually accumulate multiple unmerged branches).
- B.1 (the 0.6.3 ``_highest_completed_cycle`` aborted-cycle skip) was
  already in place; the existing regression
  ``tests/cli/test_research_resume.py::test_only_a_quality_report_marks_a_cycle_complete``
  pins the behaviour.
- **Release-CI hardening (PRs #87 / #88 / #89, 2026-06-01).** Publishing
  v0.7.0 surfaced a Linux-only smoke-gate failure that had never run on CI
  (the Release workflow runs the gate only on a version bump — last at
  v0.6.0). Root cause: the deadline-abort dispatch test passed a
  ``MagicMock`` proc to the real ``_terminate_process_tree``; its ``.pid``
  coerced to ``1`` → ``os.killpg(1, …)`` SIGTERM'd the CI runner's own
  process group (exit 143). Harmless on macOS (group 1 is launchd →
  ``PermissionError``). Fixed by guarding ``_signal_process_tree`` (both
  helper copies) against signalling a pgid ``<= 1`` or the caller's own
  process group, plus two stale-mock test repairs exposed by 0.7.0's
  ``subprocess.run`` → ``_popen_session`` switch
  (``test_dispatch_sidecar_collision`` patched the wrong function and was
  spawning a real ``codex``; ``test_fake_agent_interception`` substring-
  matched ``/claude`` in a ``$TMPDIR`` path). v0.7.0 was re-tagged to the
  fixed commit (``a62e58e``) and published.

## [private 0.6.3] - 2026-05-31

### Fixed

- **`--resume` no longer picks up sentinel `cycle-NNN/` directories as completed cycles.** (regression test: tests/cli/test_research_resume.py::test_sentinel_cycle_dirs_do_not_count)
  Same-day follow-up to the 0.6.1 resume fallback. The 0.6.1 implementation
  of ``_highest_completed_cycle`` scanned for ANY ``cycle-NNN/`` directory
  or ``cycle-NNN-*.json`` file. That over-counted partial state — in
  particular, ``source_bridge`` writes ``cycle-999/source-signals.json``
  during early sanity testing. A vault carrying that artifact resolved
  the "next cycle" to **1000**, which immediately tripped
  ``start_cycle > max_cycles`` in ``orchestrator.run_cycles`` and exited
  "constrained — max_cycles reached" without doing any work. The scan
  now only counts ``cycle-NNN-quality-report.json`` (the canonical
  atomic-written end-of-cycle artifact). Stray dirs, partial state from
  aborted cycles, and source-bridge sentinels are all ignored.

## [private 0.6.2] - 2026-05-31

### Fixed

- **Subprocess timeouts now actually kill the process tree.** (regression test: tests/scripts/test_agent_call_process_tree.py)
  Post-mortem follow-up. When a stage's timeout fired we were calling
  ``proc.kill()`` (or letting ``subprocess.run(..., timeout=N)`` do the
  equivalent), which only signals the DIRECT child. Grandchildren —
  codex's sandbox, MCP servers, headless scrapers, ``yt-dlp`` forks —
  kept the inherited stdout/stderr pipes open, and the next
  ``communicate()`` call blocked indefinitely waiting for EOF. The
  feeds-vault revival on 2026-05-31 hit this in production: the 60-minute
  ``note_writer`` timeout fired correctly but ``agent_call.py`` stayed
  alive for another **3 hours 17 minutes** as a zombie, with the
  heartbeat thread cheerfully reporting "still alive" the whole time.
  All four affected codepaths now launch their subprocesses in fresh
  process sessions (``start_new_session=True``) and SIGTERM/SIGKILL the
  ENTIRE process group on timeout, with bounded force-close of our pipe
  handles as a last-resort unblock for the pathological case of a
  grandchild that escapes the group via its own ``setsid``. Affected
  files: ``scripts/agent_call.py`` (dispatch + run, claude+codex paths),
  ``src/research_framework/pipeline/source_bridge/extractor.py`` (module
  extractor invocation), ``src/research_framework/pipeline/_cycle_helpers.py``
  (the outer ``_run_helper_script`` cleanup that runs ``agent_call.py``
  itself). New ``src/research_framework/pipeline/process_tree.py`` module
  centralises the helpers (Principle V: stdlib-only, no ``psutil``).
  (regression tests:
  tests/scripts/test_agent_call_process_tree.py::TestRunInSessionWithTimeout::test_timeout_raises_within_bounded_wall_clock,
  tests/scripts/test_agent_call_process_tree.py::TestRunDispatchUsesTreeKill,
  tests/pipeline/test_process_tree.py::TestTerminateProcessTree::test_grandchild_dies_when_tree_is_terminated,
  tests/pipeline/test_process_tree.py::TestTerminateProcessTree::test_terminate_returns_within_bounded_wall_clock)
- **`raw_capture.py` now flags JavaScript-only SPA shells.** (regression test: tests/scripts/test_raw_capture.py::TestClassifyPayload) The same
  feeds-vault cycle that surfaced the timeout bug spent ~56 minutes of
  ``gpt-5.4`` ``xhigh`` reasoning trying to write a "Mistral Vibe" note
  from four URLs that all returned a 1049-byte Vite/React shell with
  ``<div id="root"></div>`` and zero visible text. Codex had no
  scrapeable content to ground a note on but kept reasoning. The
  capture script now classifies each fetched HTML payload into
  ``rich``/``thin``/``js_shell``/``binary``, records the bucket in
  ``meta.json``, and prints the status word (``JS_SHELL`` or ``THIN``)
  as the first token of the CLI line so it's grepable AND visible to the
  LLM reading its own tool output. A ``WARN`` line goes to stderr
  pointing at archive.org / cached copies as recovery paths. This
  doesn't auto-skip the topic (the LLM still decides), but it removes
  the silent-failure mode where the agent didn't even know its source
  was unusable. (regression tests:
  tests/scripts/test_raw_capture.py::TestClassifyPayload::test_real_mistral_shell_classifies_as_js_shell,
  tests/scripts/test_raw_capture.py::TestClassifyPayload::test_cli_emits_js_shell_status_word)

### Added

- **`src/research_framework/pipeline/process_tree.py`** — stdlib-only
  process-group / tree-kill helpers (``popen_session``,
  ``signal_process_tree``, ``terminate_process_tree``). Designed to be
  importable from any package code; the ``scripts/agent_call.py`` script
  carries a duplicated copy because scripts can't import from
  ``src/`` (would create a circular install dependency).

## [private 0.6.1] - 2026-05-30

### Fixed

- **feeds-vault revival post-mortem fixes.** See `docs/POSTMORTEM-2026-05-30-vault-revival.md`. (regression test: tests/pipeline/test_cg001_yield_model.py)
  - **Bare-string scout topics no longer cause CG-001 FAIL.** Codex/GPT
    scouts emit ``topics_found.new`` as ``["AlphaEvolve", ...]`` (bare
    strings) while Claude scouts emit fully-structured dicts. Both call
    sites (``gates_step._topics_found_new_rows`` and
    ``research_plan.merge_scout_topics``) now share a new
    ``normalise_topic_row`` helper that accepts either shape and wraps
    bare strings as ``{"title": ...}``. Previously the bare-string rows
    were silently dropped, leaving the priority queue empty and the
    cycle aborting at CG-001 with "no notes created". (regression test:
    tests/pipeline/test_gates_step_sg001_002.py::TestBareStringTopicTolerance,
    tests/pipeline/test_merge_scout_topics.py::test_merge_accepts_bare_string_topics)
  - **SG-002 (topic-category diversity) degrades to WARN, not FAIL,
    when no scout row carries a ``coverage_category``.** Bare-string
    topics carry no category, so the diversity signal is vacuous —
    downstream the topic-classifier skill enriches each one. Forcing
    FAIL aborted otherwise-recoverable cycles. (regression test:
    tests/pipeline/test_gates_step_sg001_002.py::TestBareStringTopicTolerance::test_sg002_degrades_to_warn_when_all_topics_uncategorised)
  - **``source_bridge.py`` lookup now prefers ``<vault>/scripts/``.**
    On installed deployments ``Path(__file__).parents[3]`` resolves
    inside ``site-packages``, never the repo root, so the source-bridge
    step erroneously reported "source_bridge.py missing". The runner
    now checks the per-vault copy first (always present after
    ``generate.sh``) and only falls back to the repo-root layout in
    dev mode. (regression test:
    tests/pipeline/test_cycle_runner_source_extraction.py::test_source_bridge_prefers_per_vault_script_when_present)
  - **``--resume`` now advances to the next cycle when ``state.json::in_progress_cycle`` is null but completed cycles are on disk.** Previously every re-run after a clean cycle tripped "no in-progress cycle found; use ``--cycle <N>``" — state is cleared on completion, so the shim's unconditional ``--resume`` always failed on subsequent invocations. ``_resolve_resume_cycle`` now falls back to ``max(cycle-NNN on disk) + 1`` when state is null. (regression test: tests/cli/test_research_resume.py::test_null_in_progress_with_completed_cycles_advances_to_next)
  - **CG-001 minimum-yield is now time-scaled and capped.** The static
    ``ceil(unmet/remaining_cycles)`` formula produced absurd thresholds
    on aggressive specs run with low ``max_cycles`` (e.g. 55 notes/cycle
    on the feeds-vault). ``coverage.remaining_yield`` now (1) applies a
    staleness multiplier based on hours-since-last-cycle (0.25 / 0.5
    / 0.75 / 1.0 staircase for <6h / 6-24h / 1-7d / >7d) and (2) caps
    the final threshold at 20 for cold-start runs (no prior cycle) and
    10 for incremental runs. Several smaller cycles is the framework's
    preferred shape over one giant cycle. (regression test:
    tests/pipeline/test_cg001_yield_model.py)
- **Two pre-existing test-suite failures retired** — surfaced by the 2026-05-30 full-matrix quality run after the post-0.6.0 doc-freshness pass. (regression test: tests/observability/test_log_surfaces.py)
  1. `tests/observability/test_log_surfaces.py::test_bridge_log_writer_acquires_lock_during_write`
     — the test signature carried an unused `mocker` parameter from an
     earlier draft. `pytest-mock` is **not** a dev dependency (Principle V
     spirit: minimise even dev deps when stdlib suffices), and the test
     body already hand-rolls `_CountingLock` instead of using `mocker`.
     Dropped the dead parameter. No behaviour change.
  2. `tests/quality/test_metric_determinism.py::test_all_metric_families_registered`
     — the test asserted the 3-family world (`coverage`, `cycle_health`,
     `note_quality`) but spec 033 (shipped 0.4.0) added `cost_efficiency`
     as a fourth family. Added the missing family to the expected set.
  After both fixes the full matrix is GREEN: ruff check ✓, ruff format ✓,
  `pytest -m "not e2e"` 1684 passed / 8 skipped / 0 failures, `pytest -m
  "e2e"` 26 passed / 0 failures, `./build.sh` smoke gate ✓, `./build.sh
  --quality` 3/3 fixtures pass (source-poor, source-rich, tech-lite).
- **Reddit source module: malformed-XML feeds now surface `verdict=error`.** (regression test: tests/source_bridge/test_reddit_module.py)
  instead of silently degrading to `verdict=stale` with an empty `notable`
  array. The internal `_parse_rss_entries` helper now returns `None` on
  `xml.etree.ElementTree.ParseError` (was returning `[]`, which was
  indistinguishable from "valid feed with no entries"). The `cmd_extract`
  caller maps `None` → `verdict=error` with `last_error` populated, while
  legitimately empty feeds keep `verdict=ok`. (PR #80, 2026-05-30; closes
  the boundary identified during the 0.6.x code-quality audit.)
- **`code/extractor.py`: stdin JSON crash protected.** (regression test: tests/source_bridge/test_extractor_contract.py) `_read_stdin()` now
  wraps `json.loads(raw)` in a `try/except JSONDecodeError`, aligning with
  every other Tier-1 extractor. Previously malformed stdin would raise an
  unhandled exception; now it produces a structured `verdict=error` with a
  clear `last_error` message. (PR #80, 2026-05-30.)
- **Tier-1 `truncated` field correctness (RSS + O'Reilly).** (regression test: tests/source_bridge/test_rss_module.py) Both
  extractors now fetch `MAX + 1` items from upstream and compute
  `truncated = len(items) > MAX` before slicing, so the boundary case
  where the upstream count *exactly* equals `MAX_NOTABLE_ENTRIES` /
  `MAX_HITS` correctly reports `truncated: false`. Previously both
  modules pre-sliced to `MAX` then over-reported `truncated: true`,
  causing the consensus layer to spuriously believe more data was
  available. Four boundary tests added under `tests/source_bridge/`.
  (PR #82, 2026-05-30.)

### Changed

- **Atomic-write consolidation.** Migrated three additional ad-hoc atomic-
  write sites onto the canonical `pipeline/atomic_write` module:
  - `pipeline/reporter.py` — phase-1 report and per-cycle cost-report
    writes now use `atomic_write.write_text` (tempfile + `fsync` +
    `os.replace`) instead of direct `Path.write_text`.
  - `pipeline/budget_guard.py::atomic_write_json_marker` — now a thin
    shim over `atomic_write.write_text` while preserving the
    `ensure_ascii=False` JSON output contract. Unused `os` import removed.
  - `pipeline/_cycle_helpers._state_write` — `_pipeline/state.json` RMW
    updates now go through `atomic_write.write_json`.
  (PR #83, 2026-05-30. Closes the "ad-hoc atomic writes" item from the
  0.6.x quality audit; partial torn-file risk eliminated at all known
  cycle-runtime write sites.)
- **Lint baseline: 88 stale `# noqa` directives removed** via
  `ruff check --select "E,F,I,W,UP,RUF100" --fix`. The multi-rule
  selection is critical — running `RUF100` alone falsely marks legitimate
  `noqa`s for non-selected rules as unused (e.g. `noqa: E402` after
  `sys.path.insert` blocks). The current ruff configuration in
  `pyproject.toml` covers all the rules whose `noqa`s were swept.
  (PR #81, 2026-05-30.)
- **Hot-path `print()` cleanup.** Final residual `print()` call in
  `pipeline/_cycle_helpers.py` (the spec-048 logger migration's hot-path
  scope had one straggler) is now `_LOG.warning()`. (PR #80, 2026-05-30.)

### Documentation

- **Code-quality audit (2026-05-30)** — formal explorer pass covering
  ruff stats, dev-tool inventory, size outliers, TODO census, and a
  structured Tier A/B/C/D triage. Findings drove PRs #80-83 (above) and
  surfaced spec 049 (cycle-helpers split, DRAFT stub) + ROADMAP QW-9
  (retire 10 `run_cycle_steps` monkeypatch sites).
- **Spec 049 — `_cycle_helpers.py` god-module split (DRAFT)** at
  `specs/049-cycle-helpers-split/spec.md`. Splits the 1354-LOC helpers
  module into ~7 focused submodules under `pipeline/_helpers/`.
  Scheduling locked: NOT BEFORE Milestone A; AFTER spec 022 stabilizes;
  BEFORE Wave-3 module ports. Effort 2-3 days; one PR per submodule.
- **ROADMAP queue cleanup** — Wave 1 spec status headers (020/023 P1/
  028/033) flipped from `SHIPPED [Unreleased]` to `SHIPPED 0.4.0
  (2026-05-27)`; queue-number collision (`#3` in both Active and
  Drafted sections) resolved by switching Active items to topic-keyed
  bullets while preserving Drafted numbering for downstream cross-refs.
- **Test-count freshness sweep** — `CLAUDE.md`, `README.md`,
  `ARCHITECTURE.md`, `docs/testing-strategy.md`, `CONTRIBUTING.md`, and
  `docs/RELEASE.md` updated from 1278/23 (v0.3.2 figures) to 1692/26
  (v0.6.0 figures; 1718 total).

## [private 0.6.0] - 2026-05-30

**Revival-sprint Wave 2 complete.** All four Tier-1 source modules
(`youtube`, `reddit`, `rss`, `oreilly`) are now ported into the spec-020
subprocess-isolated `<vault>/modules/<name>/` shape; `arxiv` is subsumed
by `rss` (arXiv category feeds are standard RSS at `rss.arxiv.org`).
The framework now has a real source surface for the Milestone A manual
Feeds-Vault validation run.

**Why MINOR (0.5.0 → 0.6.0)**: net-new public surface — four shipped
modules under `src/research_framework/modules/`, each with its own
`sources.yaml.template` extending the per-vault config surface. No
breaking changes; existing vaults continue to work after `./vault
update`.

### Added

- **Wave 2 / `youtube` source module** — YouTube transcript +
  metadata extraction in spec-020 shape at
  `src/research_framework/modules/youtube/`. Shells out to `yt-dlp`
  with the `YT_DLP_BIN` override for hermetic tests; emits per-video
  envelope + `notable[]` (title, uploader, upload date) with
  `verdict=ok` (transcript available), `verdict=empty` (no subtitles),
  or `verdict=error` (binary missing / non-YouTube URL). Closes
  #37.
  Established the 5-file module template (`manifest.yaml`,
  `extractor.py`, `few-shot.md`, `README.md`, `sources.yaml.template`)
  + the `_BIN`/`_FIXTURE` env-override testing pattern that the
  three subsequent ports mirror. *(PR #71,
  doc-sync follow-up PR #72.)*
- **Wave 2 / `reddit` source module** — RSS-based Reddit extraction
  in spec-020 shape at `src/research_framework/modules/reddit/`.
  Stdlib-only Atom parser (no API key, no OAuth); frozen 13-subreddit
  allowlist preserved in `sources.yaml.template` (ported verbatim from
  legacy `reddit_rss.py::SUBREDDITS`); hermetic contract tests via
  `REDDIT_RSS_FIXTURE`. Closes
  #38.
  *(PR #74.)*
- **Wave 2 / `rss` source module** — Generic RSS 2.0 + Atom extraction
  in spec-020 shape at `src/research_framework/modules/rss/`.
  Stdlib-only dual parser (root-element branching: `<rss>` vs `<feed>`);
  conservative URL triggers (`.rss`, `.atom`, `/feed/`, `/rss/`,
  `/atom/`) so scout doesn't mis-route generic XML; representative
  6-feed template (newsletters + blogs + podcast + Atom example);
  hermetic contract tests via `RSS_FIXTURE`. **Subsumes the planned
  `arxiv` port (#41)** —
  arXiv category feeds at `rss.arxiv.org/rss/cs.*` are standard RSS and
  route through this module without arxiv-specific code (a separate
  module would only matter if the export-API query URL shape needs
  paging logic; documented in `modules/rss/README.md` "Scope"). Closes
  #39.
  *(PR #75.)*
- **Wave 2 / `oreilly` source module** — O'Reilly Learning content
  search in spec-020 shape at `src/research_framework/modules/oreilly/`.
  Stdlib-only `urllib` HTTPS client (no `requests` dep); auth-gated via
  `OREILLY_API_KEY` env var with key-leak-safety guaranteed by
  `test_extractor_api_key_never_leaks_in_output` (sentinel-string
  assertion against payload + stdout + stderr); query-driven via
  `learning.oreilly.com/search/?q=…` URL convention (keeps the
  `source.url` field shape uniform across all modules); hermetic
  contract tests via `OREILLY_API_FIXTURE` (JSON fixture file). When
  the API key is missing, emits clean `verdict=error` with an operator
  notable — never crashes, never leaks the key value. Closes
  #40.
  *(PR #76.)*

### Wave 2 sprint footnote

- **Total module surface**: 4 shipped + 1 subsumed = 5/5 Tier-1 sources.
- **Total contract tests added**: 14 (reddit) + 15 (rss) + 15 (oreilly) +
  ~12 (youtube, retroactive) = ~56 hermetic per-module tests.
- **Total runtime deps added**: zero (Principle V upheld — all four
  modules are stdlib-only or shell out to operator-installed tools).
- **Pattern established**: 5-file module shape + per-module `_FIXTURE` /
  `_BIN` env override + signal-payload schema validation. Future Tier-2+
  module ports (HackerNews, GitHub releases, etc.) can follow this
  template verbatim.

### Deferred / next

- **Milestone A** (manual Feeds-Vault cycle on `~/Documents/feeds-vault` using
  the new modules) — unblocked by this release. The framework now has
  enough Tier-1 source coverage to drive a real research cycle.
- LLM-driven `facts: {}` extraction in each module — every module v0.1.0
  ships the envelope + per-source `notable[]` only; LLM-driven schema
  extraction against the vault's per-vault `FactsSchema` is a follow-up
  per-module issue.

## [private 0.5.0] - 2026-05-29

**Observability v1 MVP (spec 048).** First runtime-debuggability surface
for the framework. Before this release, an unattended `./vault research`
run that misbehaved overnight was effectively a black box: no
`logging.basicConfig()` was wired, no global `--log-level` flag existed
on the CLI, and the `bridge.log` referenced in spec 020's quickstart
was vapor (never implemented). After this release, an operator can
`tail -f <vault>/_pipeline/cycles/cycle-NNN/bridge.log` in a second
terminal to watch extractor subprocesses in real time, and can dial
the framework's own log verbosity with `--log-level debug` (or quiet
piped runs to `WARNING` via TTY-aware default).

**Why MINOR (0.4.0 → 0.5.0)**: net-new public surface — the
`--log-level` global flag, the `bridge.log` per-cycle artifact, and
the `research_framework.observability` sub-package. No breaking
changes; existing vaults continue to work after `./vault update`.

### Added (spec 048 — Observability v1 MVP, this release)

- **Global `--log-level {debug,info,warning,error}` flag.** Registered
  at the parser top so every subcommand accepts it. Default is
  TTY-aware (`info` when `sys.stdout.isatty()`, `warning` otherwise),
  per `specs/048-observability-v1/contracts/log-level-flag.contract.md`.
- **Root-logger wiring.** `logging.basicConfig()` is invoked exactly
  once on CLI entry per
  `specs/048-observability-v1/contracts/logger-wiring.contract.md`.
  Format pinned to `%(asctime)s [%(levelname)s] %(name)s: %(message)s`
  (verified by `test_log_record_format_pinned`).
- **Per-cycle `bridge.log` capturing extractor stderr verbatim.**
  Lives at `<vault>/_pipeline/cycles/cycle-NNN/bridge.log`.
  Line-buffered (`tail -f` lag < ~100ms), framed per
  `contracts/bridge-log-format.contract.md`:
  - header: `=== module: X, source: Y, pid: Z, started: ISO ===`
  - body lines: `[<module>:<pid>] <verbatim stderr line>`
  - success footer: `=== exit: N, duration: T.TTTs, payload_status: ok|empty|error ===`
  - KILLED footer: `=== KILLED BY FRAMEWORK (<reason>) after T.TTTs ===`
    with `reason ∈ {wall-clock cap, dollar cap, manual interrupt, parent exit}`.
- **Hot-path `print()` migration.** 111 `print()` calls across 7
  pipeline modules (`cycle_runner`, `orchestrator`, `runner`,
  `steps/{scout,research,postprocess}`, `source_bridge/orchestrator`)
  now use `_LOG.info/warning/error()`. As a result, `--log-level
  warning` actually quiets pipeline progress noise (rather than just
  the few pre-existing `_LOG` calls). The `tests/observability/_baselines/hot_path_print_count.json`
  snapshot + the parametrized
  `test_no_net_new_print_in_hot_path_files` test prevent regressions.
- **Regression suite.** `tests/observability/test_log_surfaces.py`
  (35 tests, all tier 2/3) gates the 5 FR-015 surfaces (root-logger
  config, logger format, bridge.log creation, line-buffered
  guarantee, hot-path print baseline). Added to the smoke gate per
  ADR-0007. The `test_fr015_checks_a_through_e_present` meta-test
  fails loudly if any of the 5 load-bearing test names get renamed.
- **`docs/observability-strategy.md`** — sibling deliverable to
  `docs/testing-strategy.md`. Six-tier ladder (sidecar → cycle
  summary → run report → vault-status → logger → bridge.log),
  decision tree, anti-patterns, composition with the spec 022
  quality harness.

### Fixed (spec 048)

- **ContextVar leakage between cycles.** (regression test: tests/observability/test_log_surfaces.py::test_cycle_runner_creates_bridge_log_at_cycle_start) The `current_bridge_writer`
  ContextVar (used to publish the active `BridgeLogWriter` to the
  extractor call chain without threading it through every signature)
  previously did not reset its token on cycle exit. A second cycle
  in the same process would inherit a closed-writer reference and
  any extractor invocation would raise `RuntimeError: BridgeLogWriter
  is closed`. The new `observability.publish_bridge_writer` context
  manager handles set+reset deterministically; the extractor also
  guards with a defensive `bridge_writer.closed` check.

### Deferred to v1.1 (spec 048 follow-up)

- `vault status` verb for on-demand live progress (FR-009/010/011).
- One-line cycle-health header in `cycle-NNN-summary.md` (FR-013).
- Non-hot-path `print()` allowlist convention + repo-wide ruff
  enforcement (FR-014).

### Explicitly out of scope (v2 horizon)

- External metrics push (Datadog/Prometheus).
- Structured event tracing.
- Real-time alerting.

## [private 0.4.0] - 2026-05-27

**Revival-sprint Wave 1** — dispatch telemetry (spec 028), the foreman
verification pattern (ADR-0010), spec 023 Phase 1 (flow separation revival),
spec 033 (cost enforcement), and spec 020 (source-module architecture) all
land in this release. Spec 023 is the first feature shipped under the
foreman pattern; 033 follows; 020 (the largest of the four — 123 tasks
across 10 blocks) is the third and closes Revival-sprint Wave 1.

**Why MINOR (0.3.2 → 0.4.0)**: net-new feature surface (source modules,
new CLI verbs `refresh-sources` / `regenerate-shim`, cost-enforcement
config keys + resume flags, telemetry sidecar v1.1 schema) but no
breaking changes — existing vaults continue to work after `./vault update`.

### Fixed (runtime version tracking)

- **Runtime version tracking auto-syncs.** (regression test: tests/source_bridge/test_package_init.py::test_root_package_version_matches_installed_package) `research_framework.__version__` was hard-coded at `"0.2.29"` and had drifted through seven releases (0.2.30 → 0.3.2) without being bumped. It is now sourced from `importlib.metadata.version("research-framework")`, which reads the installed package's `pyproject.toml::version` at import time and falls back to `"0.0.0+unknown"` for non-installed (source-only) checkouts. The constant tracks the installed package automatically going forward; output surfaces that stamped a framework version (preflight reports, quality reports, regenerate-shim fingerprint JSON, quality-harness baselines, scaffolder, research plan) now emit the real installed version rather than `"0.2.29"`.

### Added (spec 020 — source-module architecture, PR #32)

- **Subprocess-isolated source modules** under `<vault>/modules/<name>/`
  with `manifest.yaml` + per-module extractor entry points. Bridge spawns
  module-owned extractors via stdin/stdout JSON contract (`extract_payload`
  envelope), keeping vault-local code out of the framework process.
- **Per-source-version signal cache** at
  `_pipeline/sources/<module>/signals/<source_stem>.json`. `source_stem()`
  derives a stable 12-char SHA-256 digest from `(source_id, source_version)`
  so cache filenames survive across processes (the original `hash()`-based
  digest was process-local).
- **Schema generation** with fail-closed drift enforcement
  (`<vault>/_pipeline/sources/<module>/facts-schema.json`). Hand edits to
  the facts-schema raise `SchemaDriftError` unless
  `--force-stale-schema` is set; corrupted schemas fail soft to `{}` rather
  than crashing extraction.
- **Value-tiered M-of-N consensus** for routine/important/critical tiers
  via `pipeline/source_bridge/consensus.py`. N is constrained to odd
  integers `>= 1`; non-int / non-odd values raise `SettingsError` at load
  time. Consensus workers go through `isolated_call()` so a failed worker
  becomes an error/partial vote (retry-once + quarantine per ADR-0006)
  rather than aborting the stage. Futures are collected in submission
  order for deterministic merge of `facts` + `notable`.
- **Payload-size cap** trims `notable` items down until the serialized
  payload fits the configured ceiling (`pipeline/source_bridge/signal.py`).
  Previous implementation popped the original payload regardless of
  remaining size — always trimmed to empty.
- **Per-module YAML + Python validators** (`<vault>/modules/<name>/validators.yaml`
  + `validators.py`) shaping the payload. Empty `{}` validators file is
  honored (skips default fallback) rather than treated as missing.
- **Scout-side signal consumption**: FR-009 dedicated Step 2b tags
  scout-discovered topics with their owning `module` whenever scout
  succeeds, independent of quality-gate spec presence.
- **Heartbeat-aware extractor polling**: when an extractor writes a
  `<run>.heartbeat.json` status file, the orchestrator switches its poll
  interval to `_HEARTBEAT_POLL_SECONDS` (30s) instead of the 0.1s tight
  loop — saves CPU on long-running extractors.
- **`scripts/source_bridge.py`** subprocess entry point for source
  extraction (invoked from `pipeline/cycle_runner.py` and runnable
  standalone via `python scripts/source_bridge.py --vault <path>`
  with `--force-stale-schema`, `--module`, and `--source` filters).
  No new top-level `./vault` verb in Wave 1 — extraction runs as part
  of the normal cycle via `cycle_runner`. A user-facing
  `./vault refresh-modules` verb is queued for the Tier-1 module-ports
  phase.
- **Module-scoped settings**: `VaultSettings` learned `modules:` (per-
  module overrides), `tiers:` (vendor-agnostic value-tier table for
  `routine` / `important` / `critical`), and `consensus.tiers` (per-tier
  N validated via `_validate_consensus_n`).
- **Sidecar telemetry FR-024** wires every extractor invocation through
  `agent_call.py` so per-call cost / token-count records land in the
  per-cycle `agent-calls/` sidecars introduced by spec 028.

### Changed (spec 020)

- `tests/_helpers/fake_repo.py::FakeRepo` commits set `GIT_AUTHOR_*` and
  `GIT_COMMITTER_*` identity env vars so the fixture works in CI
  environments without global `user.name` / `user.email`.
- `tests/_helpers/fake_module.py::_git_head` reads `source_version` via
  `dict.get(..., "v1")` so tests supplying a custom `stdout_payload`
  without that key don't `KeyError`.
- `tests/cli/test_build_parser_stable.py` uses a `_subprocess_env()`
  helper that pins `PYTHONPATH` to the worktree-local `src/` directory
  for every CLI subprocess assertion — prevents an editable install from
  a sibling worktree from contaminating the help-golden check.
- `dist-templates/scaffold-manifest.json` learned `modules/` and
  `_pipeline/sources/` paths with `is_user_owned_after_first_write: true`
  so vault-owned signals + module installs survive `./vault update`.

### Added (spec 023 Phase 1 — flow separation, PR #30)

- `./vault refresh-sources` — run legacy `scripts/collect_*.py` collectors plus frozen `reddit_rss.py` allowlist via vault venv Python (`research-framework refresh-sources --vault <path>`).
- `./vault regenerate-shim` — re-render the vault bash shim from the bundled template; writes `_pipeline/shim-fingerprint.json` (`research-framework regenerate-shim --vault <path>`).
- `research_framework.pipeline.atomic_write` — canonical temp-file + `os.replace` writes for cycle JSON and note paths (FR-018).
- `apply_vault_scaffold_update` / `_pipeline/scaffold-manifest-snapshot.json` — vault-local `scripts/*.py` survive framework script merge on update (FR-015).

### Changed (spec 023 Phase 1)

- `generator.scripts.copy_scripts` — merge mode (never `rmtree` on `<vault>/scripts/`).
- `dist-templates/scaffold-manifest.json` — `vault` entry `is_user_owned_after_first_write: false` for shim repair via update path.
- `templates/vault-script.sh.j2` — `refresh-sources` and `regenerate-shim` case arms.
- Pipeline cycle writers (`research`, `postprocess`, `scout`, `verifier`, `wikilinks`, `runner`, `research_plan`, `plan_narrator`, `timings`, `topic_harvest`, `validate_cycle`, `probes`, `_cycle_helpers`) delegate to `atomic_write`.
- `pipeline.settings` — typed `refresh_sources.collectors` and `refresh_sources.timeout_s` (default 600s).

### Added (spec 033 — cost enforcement, PR #31)

- **Cost enforcement (spec 033)**: Per-cycle dollar cap (`limits.cycle_budget_usd`),
  parallel codex token cap (`limits.codex_token_budget`), wall-clock backstop
  (`limits.cycle_wallclock_budget_minutes`), and opt-in top-level
  `approval_gates` with separate `_pipeline/BUDGET_PAUSED` and
  `_pipeline/APPROVAL_REQUIRED` markers. Pre-dispatch estimates use bundled
  `dist-templates/cost-estimates.yaml` with optional `tiktoken` via
  `pip install research-framework[budget]`. `./vault research --resume` gains
  `--force-budget`, `--approve`, `--approve-all`, and `--reject` with TTY vs
  headless env acks (`RF_FORCE_BUDGET_ACK`, `RF_APPROVE_<STAGE>_ACK`, …).
  Quality harness metric family `cost_efficiency` / `cost_per_substantive_note`.

### Added (foreman verification pattern, PR #29)

- **Foreman verification pattern (ADR-0010)** — three-role testing
  pipeline introduced to defuse single-agent test-discipline drift
  during multi-hour `/speckit.implement` dispatches:
  - **Test-design subagent** (`.agents/skills/test-designer/SKILL.md`)
    reads a spec's `spec.md` + `plan.md` + `tasks.md` + `contracts/`
    (READ-ONLY) and enriches `tasks.md` in place with
    `### Testing Requirements` blocks naming the exact test files +
    function names + tier annotation per task.
  - **Implementer subagent** writes prod + test code blind to the
    foreman's existence; it sees only the `Testing Requirements` block
    the test-design subagent left behind.
  - **Foreman** — two arms. Arm A is a deterministic Python verifier
    (`scripts/foreman/verify_test_coverage.py`, 39 tests) that parses
    `tasks.md`, checks each named test file exists, contains the named
    function (AST), pytest collects, pytest passes (verbose-output
    `PASSED` check distinguishes `SKIPPED` / `XFAIL`), and TDD
    commit-timeline (topological order via `git log --topo-order`,
    not wall-clock) is preserved. Arm B is a review subagent
    (`.agents/skills/foreman/SKILL.md`) for semantic issues scripts
    can't catch (vacuous assertions, mocked-unit-under-test, LLM
    calls in unit tests, scope creep, doc-update misses).
  - **Strict-naming policy**: tests must match the test-designer's
    declared filenames + function names exactly. Path grammar rejects
    absolute paths (`/...`, `C:/...`), parent traversal (`../`), and
    home-dir notation (`~/`) with `ParseError` (CLI exit 2).
    Malformed `### Testing Requirements` lines that *look* like a
    Test entry but don't match the strict grammar raise `ParseError`
    (no silent skips).
  - **Parser contract** at `docs/foreman.md` is the source of truth
    for the `### Testing Requirements` block format. Subagent prompts
    at `.agents/skills/{test-designer,foreman}/SKILL.md`.
  - Pattern is **opt-in per spec** — tasks without `Testing
    Requirements` blocks report `NO_REQUIREMENTS` and are skipped.
    Retroactive enforcement on already-shipped specs is parked under
    `docs/TODO.md` as low-priority (strict-name matching is too
    brittle for retro; needs a tolerant matcher first).
  - Spec 028 (PR #28) shipped concurrently and is NOT foreman-gated;
    spec 023 (PR #30) was the first feature shipped under the
    pattern (29 Copilot findings across the 023/033/020 implementer
    batch, 28 fixed pre-merge — see PRs #30/#31/#32).

**Post-Foundation gate hardening** — closes the two gate gaps surfaced in
the 0.3.2 post-mortem and the doc-sync review. No runtime behaviour
change; gates that previously fired only on a human's memory now fire
automatically.

### Changed

- **Dispatch telemetry (spec 028) — SHIPPED, PR #28 merged 2026-05-27**:
  All new cost sidecars use **schema `1.1`** under
  `<vault>/_pipeline/cycles/cycle-NNN/agent-calls/`. `dispatch()` and
  `--cost-sidecar` capture real `cost_usd` / `tokens_in` / `tokens_out`
  for Claude runs via incremental stream-json parsing (no buffer-all);
  explicit `agent_kind` (`fake` | `real`) drives timestamp format
  (deterministic sentinel pair for fake; wall-clock ISO8601 ms for
  real, with `started_at` captured at dispatch start and `completed_at`
  at completion — not both at completion as in the pre-fix draft).
  Per-batch note-writer costs write `note_writer-batch-{B}.json` (no
  overwrite). Repeat dispatches use numeric suffixes
  (`{stage}-2.json`, …). `status: "ok"` requires `exit_code == 0` AND
  (on the stream path) a terminal `{"type": "result"}` event having
  been observed — protects against silent failures where claude exits
  cleanly mid-stream with no envelope. **Breaking**: flat
  `cycle-{N}-scout.cost.json` / `cycle-{N}-research.cost.json` are no
  longer written or read by `_sum_sidecar_costs` / run reports.
  Per-batch `note_writer` dispatch in `pipeline/steps/research.py`
  now passes `--batch-index` + `--topic-count` to `agent_call.py`
  explicitly (CLI accepted the flags since the spec landed; orchestrator
  just wasn't forwarding).
- **`build.sh::SMOKE_TESTS`** adds
  `tests/quality/test_fake_agent_interception.py` (the canonical "no
  live `claude`/`codex` during fixture cycles" assertion). Previously
  outside both the fast loop and the smoke gate — a Principle-IV
  regression like the 0.3.0/0.3.1 `plan_narrator` bootstrap bug could
  reach `main` silently. Now every `./build.sh` runs the assertion;
  smoke-gate wall-clock +~7s. The companion meta-test
  (`tests/build/test_smoke_gate_enforces_contract_tier.py::REQUIRED_IN_GATE`)
  is updated to keep the entry locked in (removing it again now
  requires a deliberate spec amendment).
- **`.github/workflows/release.yml`** replaces `bash build.sh` with
  `bash build.sh --quality` in the build step. The release pipeline now
  runs the spec-022 quality harness across all 3 fixtures
  (`tech-lite`, `source-poor`, `source-rich`) before publishing a
  release; a >15% metric regression vs the committed baselines fails the
  release. Previously the quality gate was opt-in (developer's manual
  responsibility); now it's enforced by the same workflow that creates
  the GitHub Release.
- **`docs/RELEASE.md`** pre-release checklist replaces the `bash build.sh`
  bullet with `bash build.sh --quality` and adds a CHANGELOG
  regression-link-annotation reminder + a spec-header-flip reminder.
  Workflow description (step 3) updated to mention both gates the
  `--quality` flag enforces.
- **`docs/TODO.md`** entry "Add `test_no_live_claude_or_codex_during_fixture_run`
  to a ship gate" deleted — surfaced 2026-05-22 in 0.3.2 post-mortem,
  resolved 2026-05-22 in `[Unreleased]`.

### Documentation

- **Post-Foundation doc sync** (2026-05-22). `README.md`, `CLAUDE.md`,
  `CONTRIBUTING.md`, `docs/ROADMAP.md`, `docs/testing-strategy.md`,
  `docs/SIMPLIFY-PASS.md`, and the status headers on
  `specs/022-e2e-quality-harness/spec.md` +
  `specs/025-simplify-pass/spec.md` were refreshed to reflect the
  as-shipped state at v0.3.2:
  - Test counts moved from 1156 / "~1158" → **1278** + 23 tier-5/6 e2e.
  - Version-pin references moved from `v0.2.33` → `v0.3.2`.
  - "Six-tier pyramid" → **seven-tier** (ADR-0008).
  - Spec 022 "to draft" → **SHIPPED 0.3.0** (+ 0.3.1 v2 retarget + 0.3.2
    intercept fix). Spec 024 / 025 same treatment.
  - ROADMAP queue items 1 / 1a flipped to `[x]`; QW-1 flipped to `[x]`;
    Strategic Sequencing block rewritten to mark Foundation phase
    SHIPPED with explicit ⏳ markers on what's NEXT (spec 020 unblocked,
    spec 009 Linux CI, efficiency phase).
  - `docs/SIMPLIFY-PASS.md` flagged as 🗄️ ARCHIVED (subsumed by spec
    025); Definition-of-done checklist all ticked.
  - `docs/testing-strategy.md` Phase 2/3 forward-looking sections
    collapsed into a historical traceability table; new
    "Quality harness — `./build.sh --quality`" section added pointing
    at the spec-022 implementation.

## [private 0.3.2] - 2026-05-22

**Tier-6 e2e gate closure** — fixes a latent Principle-IV violation
in `plan_narrator` and `_cycle_helpers` that spawned live `claude`
subprocesses during quality-fixture cycles. The violation was caught
by `tests/quality/test_fake_agent_interception.py` (which was not in
either the smoke gate or the `--quality` gate) and remained silent
in all previous releases. The fix is the **first time** an e2e
LLM-interception assertion holds end-to-end for the quality harness;
0.3.2 also removes the gate gap so future regressions cannot reach
main silently.

### Fixed

- **`pipeline/plan_narrator._bootstrap_scripts_agent_call`** now prefers `<vault_dir>/scripts/agent_call.py` (test: tests/quality/test_fake_agent_interception.py::test_no_live_claude_or_codex_during_fixture_run) over the repo root, loading the
  vault's fake-agent shim under a vault-scoped module name. Previously
  the in-process bootstrap hard-coded the repo path, so the shim's CLI
  intercept never reached the dispatch call and the real `claude`
  subprocess fired on every plan-narration cycle.
- **`pipeline/_cycle_helpers`** (probe-retrieval path) (test: tests/quality/test_fake_agent_interception.py::test_no_live_claude_or_codex_during_fixture_run) now passes
  `vault_dir=` to `_bootstrap_scripts_agent_call`, closing the same
  bypass in the probe path. The two call sites are the only in-process
  agent_call bootstraps in production code — verified via
  `rg "_bootstrap_scripts_agent_call" src/`.

### Changed

- **`tests/_helpers/fake_agent._SHIM_TEMPLATE`** extended to expose
  an in-process `dispatch()` function returning a `SimpleNamespace`
  that duck-types `scripts.agent_call.AgentCallResult`
  (`stdout`/`stderr`/`exit_code` are all `plan_narrator` reads).
  `sys.exit(fake_agent.main(...))` moved under an
  `if __name__ == "__main__":` guard so the shim is safe to load via
  `importlib.util.spec_from_file_location` without killing the parent
  process. Substitution mechanism switched from `str.format()` to
  `str.replace()` (`__FAKE_AGENT_BAKED_REPO_ROOT__` token) so the
  shim body can contain literal `{` / `}` characters.
- **`tests/quality/conftest.run_fixture_cycles`** now installs the
  fake-agent shim at `<fixture.vault_dir>/scripts/agent_call.py` at
  test setup. The committed shims under
  `tests/fixtures/quality/{tech-lite,source-poor,source-rich}/scripts/`
  remain as on-disk placeholders but are unconditionally overwritten
  by `install_shim` at test time — no test relies on the committed
  content.
- **`pyproject.toml [tool.ruff].extend-exclude`** added the fixture
  shim path (`tests/fixtures/quality/*/scripts/agent_call.py`). The
  shim is generated source, not maintainer-edited; its deliberate
  late `from tests._helpers import fake_agent` import (placed after
  `sys.path` manipulation) trips ruff's I001 check.

### Acceptance verification

- **Tier-6 e2e**: `pytest -m e2e` → **23/23 passed** (was 22/23 on
  0.3.1; the `test_no_live_claude_or_codex_during_fixture_run`
  failure that motivated this release is now green). Suite runtime
  dropped from ~644s → ~114s (5.6×); the difference is the live
  `claude --print` round-trips that no longer fire.
- **Fast loop**: `pytest -m "not e2e" -q` → **1278 passed**, 2 skipped.
- **Smoke gate**: `./build.sh` green.
- **Quality gate**: `./build.sh --quality` green; baselines unchanged
  (the narrator now returns a canned string in test mode, but
  baselines do not capture narrator output so they're unaffected).
- **Lint**: `ruff check .` → zero errors.

### Known gate gap closed

`tests/quality/test_fake_agent_interception.py` is the canonical
"no live LLM during fixture cycles" guard. It is marked
`@pytest.mark.e2e` and `@pytest.mark.slow` and was therefore excluded
from both `pytest -m "not e2e"` and the smoke gate. The 0.3.0/0.3.1
verification stack ran neither the full e2e sweep nor this specific
test, so the regression went undetected. A future spec
(022-quality-harness v3 follow-up or a separate FR) should add this
test to either the smoke gate or a dedicated "tier-6 dispatch
guarantees" gate that the release pipeline runs before tagging. For
now, 0.3.2 is the first release where the assertion holds, but the
gate gap is captured in `docs/TODO.md` as a follow-up.

## [private 0.3.1] - 2026-05-22

**Spec 025 Tier B + spec 022 v2 hook retargeting** — completes the
foundation arc started in 0.3.0. Pure refactor + behaviour-preserving
retarget: no new user-facing surface, no new dependencies. Pyramid
shape changes (`pipeline/steps/`, `cli/` subpackage, `vault/frontmatter.py`,
`pipeline/settings.py`) make the next feature cycle cheaper.

### Refactor

- **B3 (spec 025 US6)**: extracted scout / research / postprocess steps
  from `pipeline/cycle_runner.py` into `pipeline/steps/` (`scout.py`,
  `research.py`, `postprocess.py`) with a shared `CycleContext` and
  typed result dataclasses (`ScoutResult`, `ResearchResult`,
  `PostprocessResult`). `cycle_runner.py` reduced from ~2,350 LOC to
  ~232 LOC (orchestrator only); behaviour-preserving per FR-009 — the
  pre-existing `tests/pipeline/test_cycle_runner.py` suite stays
  green UNCHANGED. (test: `tests/pipeline/steps/test_scout.py`,
  `tests/pipeline/steps/test_research.py`,
  `tests/pipeline/steps/test_postprocess.py`,
  `tests/pipeline/steps/test_imports.py`)
- **B4 (spec 025 US7)**: introduced `vault/frontmatter.py` canonical
  parser (`parse_frontmatter`, `parse_frontmatter_str`,
  `dump_frontmatter`, `FrontmatterParseError`); migrated 8 of ≥ 12
  call sites; remaining 6 holdouts documented inline with specific
  reasons (FR-010 + SC-007). (test:
  `tests/vault/test_frontmatter.py` — 13 contract § 7 cases)
- **B5 (spec 025 US8)**: split `cli.py` (~1.3k LOC) into a `cli/`
  subpackage (`_parser.py`, `research.py`, `research_cycles.py`,
  `research_generate.py`, `research_phase3.py`, `research_resume.py`,
  `audit.py`, `vault.py`, `quality.py`, `__main__.py`); `build_parser()`
  re-exported unchanged via `cli/__init__.py`; `./vault --help`
  byte-identical (FR-011 + SC-005 + SC-009). (test:
  `tests/cli/test_build_parser_stable.py` — byte-identical `--help`
  + topology + import path)
- **B7 (spec 025 US9)**: introduced `pipeline/settings.py` canonical
  loader returning a typed `VaultSettings` frozen dataclass; migrated
  6 call sites; refactored A1/A2's defensive
  `settings.get("plan_narrator", {}).get("tier", "standard")` pattern
  to the typed `settings.stage("plan_narrator").tier` accessor
  (FR-012 + SC-008). (test:
  `tests/pipeline/test_settings_loader.py` — 11 contract § 7 cases)

### Changed

- **Spec 022 v2 hook retargeting** — `quality/metrics/{coverage,
  cycle_health, note_quality}.py` now consume the typed
  `ScoutResult` / `ResearchResult` / `PostprocessResult` dataclasses
  from `pipeline.steps` via a `_last_cycle_results` module-level
  cache populated by `run_cycle_steps`. Filesystem-scrape fallback
  preserved for cycles that produced no typed seam. Baselines
  unchanged (behaviour-preserving by construction). (test:
  `tests/quality/unit/test_coverage_metric.py`,
  `tests/quality/unit/test_cycle_health_metric.py`,
  `tests/quality/unit/test_note_quality_metric.py`)
- **`pipeline/cycle_runner.py`** exposes
  `get_last_cycle_results(cycle_num)` for downstream consumers
  (spec 022 harness); `run_cycle_steps` public signature unchanged
  (`(vault_dir, cycle_num) -> int`).

### Fixed

- **`cli/__main__.py` restored** (test: tests/cli/test_build_parser_stable.py::test_help_byte_identical) — after B5 turned `cli.py` into a
  package, `python -m research_framework.cli` failed with
  `'research_framework.cli' is a package and cannot be directly
  executed`. Adding `cli/__main__.py` restores the module-execution
  entry point used by 8 subprocess-based tests.

### Documentation

- **025 spec status** → `SHIPPED 0.3.1`.
- **`docs/SIMPLIFY-PASS.md` § 6** — appended the B3 long-lived sub-
  branch audit trail (lock window: 2026-05-22, ~1 day vs the 5-day
  SC-015 target; conflicts: 1 in `CHANGELOG.md` resolved on umbrella
  merge; lessons documented for future long-lived branches).
- **`docs/ROADMAP.md`** — flipped 025 Tier B queue entry to `[x]`,
  moved to "Completed (recent)".

### Acceptance verification

- **Smoke gate**: `./build.sh` green (ADR-0007).
- **Quality gate**: `./build.sh --quality` green across all three
  fixtures (baselines unchanged from 0.3.0).
- **Fast loop**: `pytest -m "not e2e" -q` → 1278 passed, 2 skipped.
- **Lint**: `ruff check .` → zero errors.
- **SC-004**: `wc -l src/research_framework/pipeline/cycle_runner.py`
  → 232 (< 1500 ✓).
- **SC-005**: `wc -l src/research_framework/cli/__init__.py`
  → 38 (≤ 50 ✓). `cli/_parser.py` is 328 LOC (above the 250 cap by
  ~30%); flagged as a v2 follow-up but does not block the ship per
  spec 025 § Out of scope.
- **SC-007**: 8 frontmatter migrations ≥ 8 required ✓.
- **SC-008**: 6 settings-loader migrations ≥ 6 required ✓.

## [private 0.3.0] - 2026-05-21

**Coordinated Foundation Release** — Specs 022 (E2E Quality Harness),
024 (Testing Infrastructure v2), and 025 Tier A (Code Simplification
Pass — five P1 refactors) ship together. This is the first minor bump
since the rename release; the new public surface area is substantial.

### Highlights

- **`./build.sh --quality`** — new flag chains the mandatory smoke
  gate (ADR-0007) with the spec-022 e2e quality harness against the
  three committed fixture vaults (tech-lite, source-poor, source-rich).
  `--fixture <name>` and `--no-color` modifiers supported.
- **`./vault quality-baseline-update <fixture>`** — new CLI verb that
  re-runs the harness against a fixture and atomically rewrites
  `tests/fixtures/quality/baselines/<fixture>.baseline.json`. CI gate
  on `$CI` for non-interactive `--yes` use.
- **`.github/workflows/quality.yml`** — new workflow fires on
  `v*` tag pushes and `workflow_dispatch` (with optional `fixture`
  input). 20-minute hard ceiling.
- **LLM dispatch guard** — `tests/_helpers/test_llm_dispatch_guard.py`
  enforces Constitution Principle IV at lint time. The allowlist
  (`tests/_helpers/llm_dispatch_allowlist.yaml`) ships **empty** at
  this release per spec-025 Tier A US10.
- **Tier-5 cycle e2e** — three deterministic fake-agent scenarios
  (out-of-scope topic, partial yield, verifier reject) replace the
  legacy `tests/pipeline/test_e2e_synthetic_vault.py` which is
  deleted. CHANGELOG `### Fixed` annotations re-pointed where the
  old test was the cited regression test.
- **Spec acceptance-coverage lint** — `tests/spec/test_acceptance_coverage_guard.py`
  walks every `specs/NNN-*/spec.md` and asserts that every
  `## User Stories` G/W/T scenario maps to a real test path. The
  three previously-missing-coverage specs (015a corpus folder name,
  017 vault quality fix, 018 testing strategy) are backfilled.
- **CHANGELOG regression-link lint** — `tests/spec/test_changelog_regression_links.py`
  walks every released `### Fixed` bullet and asserts each is followed
  by `(test: ...)`, `(regression test: ...)`, or `(no test: <rationale>)`.
  Backfilled for every shipped block from 0.2.10 onward.

### Added

- `src/research_framework/quality/{baseline,baseline_update,exceptions,metrics,models,report,runner,__main__}.py`
  — the e2e quality harness package (spec 022 US1-US5).
- Three metric families: `coverage` (`coverage_pct`,
  `notes_per_category`, `spec_drift`), `cycle_health` (`cycles_pass`,
  `cycles_fail`, `sg002_trip_count`, `retry_once_rate`,
  `verifier_reject_rate`), `note_quality`
  (`avg_word_count`, `template_compliance_rate`, etc.). All
  reproducible via canonical-JSON encoding.
- Three committed fixture vaults under `tests/fixtures/quality/`:
  - `tech-lite/` — Java microservice domain, exercises code-derived
    topic discovery (FR-011).
  - `source-poor/` — single weak wiki source, exercises SG-002
    diversity gate (FR-011).
  - `source-rich/` — five high-quality curated sources, exercises
    no-over-pruning across 3 cycles (FR-011).
- `tests/_helpers/fake_agent.py` v2 stages: `verifier` (accept /
  reject / malformed_json scenarios), `narrator`
  (research_plan_narrator), `probe_retrieval` (happy). Worktree-
  portable shim installer.
- Smoke meta-tests restored to `build.sh`'s mandatory smoke gate:
  `test_install_wizard_skip_redundant_questions.py` and
  `test_smoke_gate_enforces_contract_tier.py` (024 US3 / ADR-0007).

### Changed

- `tests/_helpers/fake_agent.py::write_scout` rotates topics
  round-robin across all spec categories so every cycle covers
  every category (was sequential; tripped SG-002 spuriously on
  multi-category specs). On-disk note counts are now read to
  determine `met_count` instead of trusting the JSON snapshot,
  fixing cross-cycle filename collisions.
- `tests/_helpers/fake_agent.py::process_batch` honors
  `topics_found.new` from the cycle's scout JSON when no
  `## Batch topics (JSON)` block exists. Each topic is routed to
  the `note_type` folder that owns its coverage category, instead
  of dropping everything into the first folder.
- `tests/_helpers/fake_agent.py::install_shim` bakes a runtime-portable
  repo-root resolver into the committed fixture shim. Previously the
  worktree-absolute path was hardcoded; the fixture broke when its
  generating worktree was deleted.
- `src/research_framework/quality/metrics/coverage.py` reads
  `_pipeline/coverage-targets.json` (live runtime state) ahead of
  the root `coverage-targets.json` (immutable spec contract). New
  helper `_count_notes_per_category_on_disk` provides
  filesystem-ground-truth counts when the run path bypasses
  `orchestrator.update_after_cycle` (the harness path).

### Fixed

- `scripts/validate_cycle.validate_sources_v2` dict-form path now indexes entries under both the as-given lowercased key and the `source_key`-normalized form. (test: tests/quality/test_quality_harness_source_poor.py::test_sg002_diversity_warning)
  Previously a dict like `{"only-wiki": {...}}` failed validation when the
  spec expected `"only_wiki"` — the dict path didn't apply the
  hyphen-to-underscore normalization that the list path did.

### Removed

- `tests/pipeline/test_e2e_synthetic_vault.py` (replaced by
  `tests/integration/test_cycle_e2e.py` — see Highlights).

### Documentation

- 022 spec status: `SHIPPED 0.3.0`.
- 024 spec status: `SHIPPED 0.3.0`.
- `docs/ROADMAP.md` queue items #1 + #2 flipped to `[x]`.
- `CLAUDE.md` Recent Changes pruned.

### Acceptance verification

- **Smoke gate**: `./build.sh` still green (ADR-0007).
- **Quality gate**: `./build.sh --quality` green across all three
  fixtures (51.99s wall clock).
- **Fast loop**: `pytest -m "not e2e" -q` → 1209 passed, 2 skipped.
- **Lint**: `ruff check .` → zero errors maintained.

### Spec 025 Tier A — code simplification pass (P1 refactors)

Tier A of the spec-025 simplification arc (`docs/SIMPLIFY-PASS.md`,
ROADMAP queue #3) ships in the same release as 022 v1 + 024 v1.
Five user stories collapse the two known LLM dispatch bypasses
(`plan_narrator`, `probe_retrieval`) through `scripts/agent_call.py`;
collapse ~32 `_write_cycle_quality_report` call sites to 2 via a
`contextlib.contextmanager` guard; auto-detect the in-progress
cycle on `./vault generate --resume`; and sync three stale doc
references to current entry points. The LLM dispatch guard's
allowlist (`tests/_helpers/llm_dispatch_allowlist.yaml`) is now
**empty** for the first time since spec 024 introduced it
(SC-003 satisfied; Principle IV structurally enforced by code).

**Added**

- `scripts/agent_call.py::dispatch()` — single LLM dispatch surface
  returning `AgentCallResult`; sidecar JSON per call to
  `<cycle_dir>/agent-calls/<stage>.json`.
- `stages.plan_narrator.tier` / `stages.probe_retrieval.tier`
  optional keys in `settings.yaml`; `stages.probe_retrieval.enabled`
  gate (default behaviour preserved).
- `./vault generate --resume` auto-detects in-progress cycle from
  `_pipeline/state.json::in_progress_cycle`.
- `pipeline.cycle_runner._state_write` atomic state.json writer;
  `QualityReportState` + `_quality_report_guard` context-manager
  guarantee exactly one `_write_cycle_quality_report` per cycle
  exit across all four exit paths.
- Five new tier-1/2 test files covering the Tier A user stories
  (`tests/pipeline/test_plan_narrator.py`,
  `tests/pipeline/test_cycle_runner_probe.py`,
  `tests/pipeline/test_cycle_runner_quality_report.py`,
  `tests/cli/test_research_resume.py`,
  `tests/docs/test_doc_sync.py`).

**Changed**

- `pipeline/plan_narrator.py::prepend_narrative` and
  `pipeline/cycle_runner.py::_run_probe_retrieval_and_cache` no
  longer invoke `claude` directly via `subprocess.run`; both route
  through `agent_call.dispatch(...)`.
- `.specify/memory/constitution.md` bumped to **v1.3.4** (PATCH);
  Technology Constraints now documents the canonical entry-point
  chain `./vault research` → `cli/research.py` (post-B5) /
  `cli.py` (pre-B5) → `cycle_runner.run_cycle_steps` →
  `scripts/agent_call.py::dispatch`. No `run_cycle.sh` references
  remain anywhere under `.specify/` or `docs/`.

### Documentation

- **Testing strategy: Phase 1 close-out + ADR-0008 (2026-05-21)**.
  Closes Phase 1 of the SIMPLIFY-PASS by landing the architect-review
  accuracy edits (test counts, QW-2 wording, Principle V→IV citation,
  Phase 3 pointer, 022 parallelism, smoke-gate marker-filter note),
  adds the new `## Spec acceptance coverage` convention to
  `docs/testing-strategy.md` (per-spec scenario → test mapping with a
  Phase 2 lint guard), and lands **ADR-0008** restructuring the
  pyramid (6 → 7 tiers):
  - Tier 3 renamed "Seam" → "Integration" so conventional searches
    surface the project's cross-module data-flow tests.
  - Old Tier 4 ("Single-cycle e2e") split into new Tier 4 ("Component
    integration", e.g. `test_cycle_runner.py`) + new Tier 5 ("Cycle
    e2e", the full `run_cycle_steps` via fake agent).
  - Old Tier 5/6 renumbered → new Tier 6/7. ADR-0007's mandatory smoke
    gate is unchanged in substance; only the tier numbers it
    references shifted (the gate selects by file path, not tier).
  - Adds a `## Regression discipline` convention: every released
    `CHANGELOG.md` `### Fixed` entry must link a test (or carry a
    reviewed `(no test: ...)` rationale). Phase 2 lint guard queued.
  - Renames `@pytest.mark.integration` → `@pytest.mark.live_llm` to
    free the namespace (the old marker meant "real LLM call, costs
    money", which is exactly `live_llm`). Only callsite is
    `tests/processors/test_extract.py::test_real_claude_cli_extract`.
  - Adds two voluntary cross-cutting markers: `@pytest.mark.regression`
    and `@pytest.mark.acceptance` (per ADR-0008). Strict-markers config
    in `pyproject.toml` updated.
  - `specs/018-testing-strategy/spec.md` Status header flipped to
    "SHIPPED 0.2.23; pyramid naming superseded in part by ADR-0008".
  - Companion docs synced: `docs/SIMPLIFY-PASS.md`, `docs/ROADMAP.md`,
    `tests/README.md`, `docs/adr/README.md` index, plus new
    `specs/018-testing-strategy/contracts/llm-dispatch-guard.contract.md`
    and `fake-agent.contract.md` v2 (verifier/narrator/probe stages).
  - No code-behaviour changes. Pure doc + marker rename. 1158/1166
    tests still green; ruff baseline still zero.

## [private 0.2.33] - 2026-05-21

**Rename + spec-013 retirement.** The Python package, CLI entry point,
and every docs/templates/scripts reference move from `research-vault`
/ `research_vault` to `research-framework` / `research_framework`. In
the same release the vault migrator (spec 013) is retired as a
standalone subsystem: its CLI and orchestration are deleted, its
shared utility modules are renamed and kept for `inventory` and
`prune`, and `./vault update` is rewired to a pip-upgrade-from-GitHub
flow that re-runs `install.sh`. Onboarding collapses from 5 → 4 steps
(the deleted "migrator assess" step had nothing to call into).

This is an internal-rename + dead-code-removal release. There is no
new user-facing feature; the user-visible effects are limited to the
new CLI/package name, the simplified onboard flow, and the rewired
update path. Pre-existing tech debt (10 ruff errors carried since
spec-017) is cleaned up in the same pass so the new baseline is
ruff-clean.

### Breaking: package + CLI rename

- Python package: `research_vault` → `research_framework`
- CLI entry point: `research-vault` → `research-framework`
- Module entry: `python -m research_vault …` → `python -m research_framework …`
- Anyone importing the package directly (e.g. `from research_vault.spec.simple
  import load`) must update imports. Inside generated vaults the
  `./vault` script absorbs the change — end users of a vault don't
  notice unless they shell out to the framework CLI directly.
- All generated scaffolding, templates, settings, agent skills, and
  docs reference the new name. `CLAUDE.md`, `ARCHITECTURE.md`,
  `CONTRIBUTING.md`, `README.md`, `docs/ROADMAP.md`, `docs/TODO.md`,
  every spec under `specs/`, `.github/workflows/release.yml`,
  `dist-templates/`, `examples/`, `settings.yaml`, `settings.codex.yaml`
  all updated in one pass.
- Old name retained only in historical fixtures under
  `tests/fixtures/migrator/pre-*-vault/` (intentional — these are
  point-in-time snapshots used to test migration assumptions and must
  not be rewritten).

### Removed: spec 013 (vault migrator) — surgical retirement

Spec 013 shipped a standalone `research-vault migrate <vault>
{assess,dry-run,apply}` CLI for rebasing vaults onto framework
upgrades. It turned out the underlying problem is solved more simply
by `pip install --upgrade` + re-running `install.sh`, and the
migrator's CLI was already broken on `main` before this release
(`research-vault migrate <fixture> assess` failed with "not a vault
(no data_vault/ directory)" on every fixture we tried). Rather than
fix vestigial code, the surgical retirement is:

**Deleted entirely**:

- `src/research_framework/pipeline/migrator.py` — orchestrator
- `src/research_framework/pipeline/migrator_apply.py` — apply layer
- `migrate` subparser + `_cmd_migrate` in `cli.py`
- `tests/cli/test_migrate_cli.py`, `tests/pipeline/test_migrator_apply.py`,
  `tests/pipeline/test_migrator_idempotent.py`,
  `tests/pipeline/test_migrator_orchestration.py`,
  `tests/pipeline/test_vault_git_boundary.py` (integration tests for
  the deleted orchestration layer)
- The `_no_real_vault_writes` conftest guardrail (its sole purpose
  was protecting against accidental migrator runs)
- Planning artifacts under `specs/013-vault-migrator/`: `plan.md`,
  `tasks.md`, `research.md`, `quickstart.md`, `lessons-learned.md`,
  `contracts/cli.md`, `contracts/migration-plan.schema.json`,
  `checklists/requirements.md`

**Renamed and kept** (still used by `inventory`, `prune`,
`scaffold-manifest` tooling):

- `pipeline/migrator_baseline.py` → `pipeline/scaffold_baseline.py`
- `pipeline/migrator_diff.py` → `pipeline/scaffold_diff.py`
- `pipeline/migrator_git.py` → `pipeline/vault_git.py`
- `pipeline/migrator_models.py` → `pipeline/scaffold_models.py`
- Their tests renamed to match (`test_scaffold_baseline_scope.py`,
  `test_scaffold_diff.py`, `test_vault_git_helpers.py`,
  `test_scaffold_models_minimal.py`)

**Tombstone**: `specs/013-vault-migrator/spec.md` is overwritten with
a withdrawal notice that documents what was deleted, what was renamed,
and what replaces it. `data-model.md` and
`contracts/scaffold-manifest.schema.json` are kept (the manifest
schema is consumed by `build_scaffold_manifest.py`).

The spec number 013 is **not reused**. Per PEP/RFC convention, spec
numbers are immutable IDs. Future specs continue from the current
high-water mark.

### Changed: `./vault update` rewired

`./vault update` previously delegated to `research-vault migrate
<vault> apply`. With the migrator gone, the new flow is:

1. `pip install --upgrade git+${RV_GITHUB_REPO}@${RV_GITHUB_REF}` into
   the vault's venv (default `${RV_GITHUB_REF}=main`).
2. `curl` the matching source archive from GitHub.
3. Exec the bundled `install.sh` against the vault directory.

This is intentionally a thin wrapper — the heavy lifting now happens
inside `install.sh`, which already knows how to (re-)scaffold a vault
idempotently. The wrapper inherits all of `install.sh`'s safety
properties (manifest-driven, respects `is_user_owned_after_first_write`,
etc.).

**Known limitations of the current wrapper** (tracked as a hardening
backlog item in `docs/TODO.md` under "Harden `./vault update` so it
can handle the bulk of real upgrades"):

- No version pinning or diff output before/after the upgrade —
  framework version drift is silent.
- No idempotency short-circuit — re-running with no remote changes
  still re-downloads + re-runs `install.sh`.
- No pre-flight check that the vault's working tree is clean. The
  spec-013 migrator used to take a snapshot commit before mutating,
  giving users a one-step rollback (`git reset --hard HEAD~1`). The
  current wrapper does NOT do this. **If you're upgrading a vault
  with uncommitted work, commit it first.**
- No post-flight smoke check — `./vault update` declares success
  whenever `install.sh` returns 0, even if the resulting vault would
  fail `./vault health`.
- No documented rollback path. Today: `pip install
  research-framework==<old-version>` in the venv + `git reset --hard
  <pre-snapshot>` inside the vault if you remembered to snapshot.
- No air-gap / offline fallback — the flow requires network access.

These limitations are not blocking for the common case (someone
willing to read this CHANGELOG and `./vault status` their vault
before upgrading). They are blocking for production-grade
"unattended" upgrade automation, which is not a goal for 0.2.x.

### Changed: `onboard` is now a 4-step flow

`research_framework onboard <vault>` no longer has a step 5. The
previous step 5 was `migrator assess` — a read-only sanity check
against the now-deleted CLI. The final step is now step 4
(`parse-spec → _pipeline/spec-parse.json`), and the success message
points users at `./vault research` and `./vault update` instead of
the deleted `research_framework migrate apply`.

If you have automation that asserted on `[onboard 5/5]` in the
output stream, switch it to `[onboard 4/4]`. The exit-code contract
(0 = done, 1 = stopped at step 3 awaiting spec review, 2 = aborted)
is unchanged.

### Fixed (build infrastructure)

- **Smoke-gate silent-skip hole closed.** (test: tests/build/test_smoke_gate_enforces_contract_tier.py::test_smoke_gate_files_actually_exist_on_disk) Two test files referenced by
  `build.sh`'s `SMOKE_TESTS` array
  (`tests/build/test_install_wizard_skip_redundant_questions.py` and
  `tests/build/test_smoke_gate_enforces_contract_tier.py`) had never
  actually been committed to git, despite CHANGELOG [0.2.28] / [0.2.29]
  documenting them as shipped. pytest silently skips non-existent paths,
  so the gate was reporting green while not actually running two of its
  18 contract tests — including the gate's own meta-test. Audit
  surfaced via the 2026-05-20 triage item #9 *(captured at
  `docs/TODO.md#restoration-notes`; the originally-cited
  `docs/FORGOTTEN-LEARNINGS.md` was never committed)*.
- **Hardening**: (test: tests/build/test_smoke_gate_enforces_contract_tier.py::test_smoke_gate_block_exists_and_is_mandatory) `build.sh` now contains a pre-flight loop that asserts
  every entry in `SMOKE_TESTS` exists on disk before invoking pytest.
  Missing entries produce a loud build failure with restoration
  guidance. This prevents the silent-skip regression class from
  recurring even when individual meta-tests are missing.
- ADR-0007 updated to document the audit finding + compensating (no test: documentation-only ADR amendment; behaviour locked by smoke-gate meta-tests above)
  control.
- Restoration of the two missing test files tracked in `docs/TODO.md` (no test: process tracking entry; restoration verified by smoke-gate file-existence tests)
  ("Restore the spec-019 build-smoke-gate meta-tests").

### Fixed (lint baseline)

- Cleared 10 pre-existing ruff errors that had been carried since (no test: ruff baseline reset; enforced by `ruff check .` in CI at release)
  spec-017 — 5 unused-local-variable F841s and 3 ambiguous-`l` E741s
  in `tests/cli/test_onboard.py` (dead `step1_lines` comprehension
  removed; surviving for-loop already enforced the no-re-commit
  invariant), an E402 in `tests/processors/test_extract.py` (the
  late `from research_framework.processors.extract import …` is
  intentional per its module docstring — now suppressed inline), and
  one E741 in `tests/processors/test_preprocess.py` (renamed `l` →
  `line`).
- Rename-script collateral (24 import-sort and unused-import nits in (no test: mechanical ruff autofix collateral from package rename)
  `tests/conftest.py`, `tests/pipeline/test_scaffold_manifest_loader.py`,
  and a handful of `src/research_framework/pipeline/` modules) cleaned
  up by `ruff check . --fix`.
- `scripts/build_scaffold_manifest.py` switched to file-level (test: tests/scripts/test_build_scaffold_manifest.py::test_output_matches_schema)
  `# ruff: noqa: E402` because the per-line `# noqa` ended up in a
  ruff-autofix placement loop on the multi-line `from
  research_framework.pipeline.template_drift import read_template_version`
  line.
- New baseline: `ruff check .` returns "All checks passed!" with zero (no test: release-time ruff sweep; zero-error state is the enforced lint contract)
  errors.

### Migration notes for existing vaults

- **In-vault command surface is unchanged** for the common cases.
  `./vault research`, `./vault status`, `./vault health`, `./vault
  ask`, `./vault write` all behave identically.
- **`./vault update` behaviour changes** as described above — read
  the "Known limitations" list before relying on it for production
  vaults.
- **Direct framework CLI users**: `research-vault` no longer exists.
  Re-install the package (`pip install --upgrade
  git+https://github.com/<owner>/research-framework`) and use
  `research-framework` instead. The `pip install` itself will replace
  the old script when the new package is installed; the old name is
  not aliased.
- **Direct Python importers**: rename `research_vault` → `research_framework`
  in your imports. There is no compatibility shim.
- **CI scripts asserting on output**: update `[onboard N/5]` to
  `[onboard N/4]`. Other CLI output strings are stable.

### Constitution

Amended to **v1.3.3** (PATCH) — Sync Impact Report records the
package-rename ripple through the principles section (no semantic
changes; the rename is mechanical and does not relax any rule).

## [private 0.2.32] - 2026-05-20

**Documentation + plumbing release.** Captures the architectural decisions
that had been living in session memory, exposes the already-shipped vault
migrator to end users, and lights up the release pipeline so future
versions actually become downloadable artifacts.

No behaviour change for vault generation; everything in 0.2.31 still
applies. The user-visible deltas are:

- `./vault update [mode]` is now a real command (wraps the migrator
  shipped at CLI level in spec 013). Default mode is `dry-run` to keep
  it safe.
- `./vault generate` was renamed to `./vault write`. The old name
  remains undocumented but the script's help text now matches the
  README and the `/write` slash command. Old muscle memory will error
  cleanly with an unknown-command message; switch to `write`.
- `./vault ingest`, `./vault sources`, and `./vault report` are gone
  — they always pointed to scripts that don't exist. Pure dead code
  removal.

### New: release workflow that actually publishes

`.github/workflows/release.yml` is reworked end-to-end:

- Fires on `push: branches: [main]` and auto-detects `pyproject.toml`
  version bumps. No manual `git tag` required for the common case.
- Idempotent: if the tag for the current version already exists, the
  workflow exits cleanly without producing a duplicate release.
- Still supports manual `git tag vX.Y.Z && git push --tags` for
  hotfixes from non-main branches.
- Auto-creates the matching `vX.Y.Z` tag in-workflow using `GITHUB_TOKEN`
  — no PAT secret needed. Sidesteps the documented "GITHUB_TOKEN tag
  pushes don't trigger sibling workflows" limitation by doing all
  build + release work in the same run.
- Runs `bash build.sh` so the install bundle
  (`research-vault-X.Y.Z.tar.gz` — the thing `install.sh` expects)
  ships as a Release asset alongside the wheel and sdist.
- Release notes are now (a) git-log between the previous tag and
  this one plus (b) GitHub's native PR/commit auto-summary
  (`generate_release_notes: true` appended).
- The bundle install command is rendered into every release body so
  users can `curl … | tar -xzf … && ./install.sh` directly.

The first time this fires (on the merge that brings 0.2.32 to main)
is the inaugural GitHub Release for this project.

### New: documentation surface

The session generated four new long-form documents and rewrote two
major existing ones. They're the durable artifacts of the work that
went into 0.2.31 + 0.2.32 and the design lockdown for spec 020.

New:

- `ARCHITECTURE.md` — system design covering principles, pipeline
  phases, two-layer vault, five search dimensions, single LLM
  dispatch surface, two-tier citation, source-module architecture
  (spec 020), test pyramid (spec 018), quality harness plan
  (spec 022), ADR process, generated vault structure, CLI surface,
  onboarding sequence.
- `CONTRIBUTING.md` — setup, doc taxonomy, spec-kit workflow, TDD
  discipline, code style, ADR + constitution amendment procedures,
  branching/commits, **release-cutting paths** (now auto-tag-on-
  version-bump per the reworked workflow), pre-PR checklist, common
  gotchas.
- `docs/RENAME-PLAN.md` — self-contained runbook for the deferred
  `research-vault` → `research-framework` rename. Designed to be
  executed in a fresh session without losing institutional knowledge.
- `docs/HANDOFF-2026-05-20-pre-rename.md` — session handoff.
- `docs/adr/` — 7 ADRs back-filling the architectural decisions made
  across the 018 / 019 / 020 / 0.2.31 work. 0001 adopts the pattern;
  0002 phase-scoped source validation; 0003 correction directive
  injection; 0004 tolerant verifier JSON extraction; 0005 cycle-time
  wikilink normalization; 0006 code-bridge as cached infrastructure;
  0007 smoke gate is mandatory.

Rewritten:

- `README.md` — focuses on value proposition (why this exists, what
  users get, what's different) instead of feature enumeration.
  Updated `./vault` command list to match the script. Updated
  "Specs at a glance" table: 010 + 012 marked as subsumed by 023;
  013 marked as shipped at CLI level; 023 marked as the consolidated
  flow-separation + assistant-framework spec.
- `docs/ROADMAP.md` — added Priority queue (single source of truth,
  13 items tickboxed in execution order), Strategic sequencing
  block (quality → features → efficiency arc), Source Modules
  roadmap (Tier 1-4), expanded spec 022 design notes including the
  critical with-vault-vs-without-vault `/ask` comparison as the
  final E2E stage, Obsidian Canvas design notes, assistant-framework
  integration vision under Horizon 3.

Smaller:

- `CLAUDE.md` — added "Important context locations" + "Strategic
  Sequencing" sections.
- `docs/TODO.md` — reset to scratchpad model; captured the
  consensus-validation abstraction idea (reusable primitive across
  modules + pipeline stages); pointer to the rename runbook.

### New: examples folder is now canonical

- `examples/research.spec.md` — rewritten to the detailed format the
  framework now defaults to. Uses macro photography on analog film as
  the domain (non-technical, non-business, to underscore the
  domain-agnostic principle). Demonstrates the full surface:
  scope.boundaries + out_of_scope + contextual_questions, 7
  note_types with required_sections + min_word_count, 5 data_sources
  with required-flag + access_method, search_dimensions,
  coverage_targets, budget.
- `examples/settings.yml` — verbatim copy of the project's root
  `settings.yaml` so users see the full override surface in one
  reference file.
- `examples/reference-vault-seed-notes.txt` removed (bait for a long-shipped
  0.2.20-era end-to-end test).
- `.gitignore` narrows `examples/*` to only the two canonical files
  above. Drop personal specs into the folder freely; they won't be
  tracked.

### New: spec design lockdown (no implementation yet)

- **Spec 020 (Source-Module Architecture)** — full design landed: plan
  (43-task, 10 blocks), research (19 plumbing + 5 clarification-driven
  decisions), data-model (11 entities), 11 contracts (5 JSON Schemas
  + 6 markdown protocols/prompts), 2 quickstart guides, 73-task
  `tasks.md`. Locked decisions: value-tiered consensus (N=1 / 3 / 5
  by `value_tier`, odd-only, majority + union); dynamic schema
  generation at install time via small-model agent; schema drift →
  fail-closed unless `--force`; module exception → retry-once +
  salvage + continue; 30s heartbeat poll / 60s stall threshold /
  warn-only. Implementation is PAUSED pending spec 022.
- **Spec 021 (Spec-Driven Coverage Pursuit)** — sibling draft to 020.
  Coverage-driven scout that biases topic discovery toward the most
  under-served target each cycle. `[PROPOSED]` markers throughout;
  needs an interactive `/speckit.clarify` round before plan/tasks.

### Constitution

Amended to **v1.3.2** (PATCH) — domain-agnostic by construction. In-
place expansion of an existing inviolable (not a new principle).
Schemas, note types, coverage targets, and search dimensions MUST be
derived from the user's `research.spec.md` at runtime — never
hardcoded for any vertical. Caught during spec 020 clarification when
the first design draft slipped toward web-vocabulary buckets.

### Filesystem housekeeping

- `reference-vault-spec.md` moved from repo root to
  `specs/016-reference-vault-rebuild/reference-vault-spec.md` (its canonical
  home — it was always backing 016).
- `HANDOFF-0.2.29.md` and `HANDOFF-0.2.31.md` moved from repo root
  to `docs/`. Repo root is now back to README + LICENSE +
  CHANGELOG + ARCHITECTURE + CONTRIBUTING + pyproject + build.sh.

## [private 0.2.31] - 2026-05-18

**Fixes the silent-verifier and broken-wikilinks issues discovered in
the user's 0.2.30 trial-run audit.** The audit confirmed that 0.2.30's
correction-loop fixes work as designed (6 cycles, zero crashes), but
also surfaced two issues that made the vault feel "much smaller than
expected":

**Bug C — verifier silently dropped every note to `pending`.** Every
`cycle-NNN-verifier.json` across the user's 6 cycles had
`status: "pending"`, `violations: []`, `suggested_fix: null` — the
canonical "I gave up" shape. The root cause was a two-line interaction:

1. `verifier.py::_call_verifier` sent the BARE note content to
   `agent_call.py` as the prompt. There was no instruction telling the
   agent what to do or that JSON output was required — codex (unlike
   Claude Code) doesn't auto-load `.agents/skills/verifier/SKILL.md`,
   so the agent's natural response was narrative summary.
2. The output-parse path was `json.loads(raw)` with a bare `except`
   that defaulted to `pending` on ANY parse failure — narrative text
   never parses as JSON, so every verdict silently dropped to `pending`.

The consequence: 65 perfectly fine notes (~520 words, sourced,
structured) were misclassified as stubs, the orchestrator emitted
"65 stub note(s)" on every cycle, and the stub-free-exit Principle
VIII guarantee became permanently broken on codex runtimes.

The fix is two complementary changes in
`src/research_vault/pipeline/verifier.py`:

- New `_build_verifier_prompt(note_content)` wraps the note in an
  explicit instruction block that names the verifier skill, restates
  the output JSON schema inline, and tells the agent to default to
  `reject` on uncertainty. Short — points to `SKILL.md` instead of
  restating it, so the source of truth stays in one place.
- New `_extract_json_blob(text)` tolerantly extracts JSON from agent
  output. Tries strict parse → code-fenced JSON (`` ```json ``) →
  any code fence → balanced-braces walk over the raw text. Returns
  the parsed dict or None. First valid match wins so malformed
  attempts don't shortcut past valid later attempts. Top-level arrays
  or non-object scalars correctly return None (schema mismatch) so
  the caller still defaults to `pending` deliberately.

13 RED-first unit tests cover the extractor's contract:
`tests/pipeline/test_verifier_json_extraction.py`. All 21 verifier
tests (8 existing + 13 new) GREEN.

**Bug D — case-mismatched wikilinks fragmented the graph.** The
0.2.30 audit found 207 broken wikilinks. The note-writer agent emits
natural-language wikilinks (`[[Cassandra]]`, `[[OMS]]`, `[[Kafka]]`)
but the framework's filename convention is lowercase-snake
(`cassandra.md`, `oms.md`, `kafka.md`). Obsidian + the framework's
wikilink resolver treat these as distinct references, so every cycle
quietly drifted further from a navigable vault graph.

`vault_health.py` already had `apply_wikilink_fixes()` that handles
the `moved` class (case mismatch), but it's an on-demand graph-repair
tool that ALSO creates stub notes and prunes orphans — both heavier
mutations that shouldn't run silently every cycle.

The fix is a new light-touch helper at
`src/research_vault/pipeline/wikilinks.py`:

- `auto_fix_moved_wikilinks(vault)` walks `data_vault/`, rewrites
  case-mismatched body and `related` wikilinks to match the existing
  filename stem. ONLY fixes case mismatches where a lowercase target
  already exists. Does NOT create notes, does NOT delete orphans, and
  DOES skip wikilinks inside fenced code blocks (which are typically
  counter-examples or actual code).
- Idempotent — re-running on a clean vault returns 0. Safe on empty
  vaults or before `data_vault/` is created.
- Returns count of FILES modified, used by cycle_runner for a one-line
  log entry.
- Wired into `cycle_runner.run_cycle_steps` as Step 3c (after the
  verifier, before validate_vault). Each cycle now leaves the graph
  clean instead of accumulating drift.

9 RED-first unit tests:
`tests/pipeline/test_wikilink_normalization.py`. Cover PascalCase →
lowercase, acronyms, alias preservation, code-fence skipping,
idempotency, empty vault, missing `data_vault/`. All 9 GREEN.

**Stats**: +22 tests (13 verifier + 9 wikilink), all GREEN. Zero
regressions. Pre-existing 7 failures in `tests/cli/test_migrate_cli.py`
remain (unrelated; track in 013-vault-migrator).

**Deferred to 0.3.0 / spec 020-code-bridge**: the topic-discovery
bottleneck and coverage-skew issues identified in the same audit are
larger architectural changes \u2014 the spec is committed separately as
`specs/020-code-bridge/spec.md`.

## [private 0.2.30] - 2026-05-18

**Fixes the user's 0.2.29 trial-run failure**: 0.2.29 added the SG-006
correction loop and the validator sidecar, but on the user's reference-vault
cycle 1 the loop ran, the scout was re-prompted, and the cycle still
aborted with the same `sources_consulted` errors. Forensics on the
artifacts proved two separate bugs were stacked.

**Bug A — the directive was written but never read.** `_render_prompt`
performed pure substring substitution and had no way to inject the
contents of `_pipeline/corrections/cycle-NNN.json` into the next prompt
the agent received. On retry, the agent got a byte-identical prompt to
the first attempt — the correction loop was a no-op. This bug had been
latent in the SG-003 retry path since 0.2.17; 0.2.29's SG-006 path
inherited it. 0.2.30 makes `_render_prompt` directive-aware: when a
caller passes `vault_dir` and `cycle_num`, the function reads any
active correction directive and prepends it to the rendered prompt as a
`## CORRECTION DIRECTIVE` markdown block. All four call sites in
`cycle_runner.py` (initial scout, scout retry, SG-003 retry, DFS) now
pass the cycle context. After a successful retry the directive is
moved to `_pipeline/corrections/applied/` so it cannot leak into
later renders this cycle or the first attempt of the next cycle.

**Bug B — `sources_consulted` enforcement conflated scout and research
phases.** The 0.2.28 H2 fix uniformly required every `required: true`
source to appear in every cycle's `sources_consulted`. But the spec
already encodes the right discrimination: `role: behaviour` sources
(code repos) and `role: intent` sources (ADRs, PR conversations,
Confluence) are scout-phase responsibilities, while `role: domain`
sources (Spring docs, OWASP, Oracle Java reference, etc.) are
research-phase responsibilities. The user's scout was being asked to
claim it had consulted 9 docs sources it never touches — and aborting
when it (correctly) didn't. 0.2.30 makes `_spec_data_sources` honor
the spec's existing role taxonomy: when called with `phase="scout"`,
only `role in {behaviour, intent}` sources are required; research and
legacy callers see all sources as before.

**Directive wording is now actionable.** Where 0.2.29 told the agent
to "fix this" without saying how, the 0.2.30 directive gives explicit
examples of both the plain-string and `{name, searched: false,
reason: "..."}` dict-form shapes that `validate_sources_v2` accepts.
The agent now has an unambiguous compliance pattern.

**Integration test that 0.2.29 should have shipped with.** New
`tests/pipeline/test_cycle_runner_directive_injection.py` stubs the
agent with a fake that inspects the prompt text and only agrees to
produce a passing report when the prompt contains `"CORRECTION
DIRECTIVE"`. The test exercises the real `_render_prompt`, real
`_retry_scout_with_validation_directive`, and real `_run_script` —
nothing about directive injection is mocked. The test red-lighted
against 0.2.29's code and green-lights only with Bug A fixed. A second
test guards against stale directives leaking into a fresh first
attempt. `tests/scripts/test_validate_cycle_phase_scoped_sources.py`
(6 cases) locks in Bug B's contract using a fixture that mirrors the
user's reference-vault spec exactly.

Coverage: 1164 tests pass, 2 skipped. The 7 `tests/cli/test_migrate_cli.py`
failures are pre-existing and orthogonal to this release.

Deferred to a future release (captured in `specs/019-pipeline-architecture/`):
US3 vault blueprint stage, US4 per-vault `code_role` field, US5 note-writer
quarantine (SG-004 today is WARN, so vault generation isn't blocked by
it), US6 end-of-pipeline consensus check. These are daylight architectural
work that would prolong the user's current blocking issue if bundled in.

### Added

- `_read_correction_directive_block(vault_dir, cycle_num)` — renders an
  active correction directive as a markdown block; returns `None` for the
  common first-attempt path or for a malformed / empty directive.
- `_archive_applied_directive(vault_dir, cycle_num)` — moves a satisfied
  directive to `_pipeline/corrections/applied/<cycle-NNN-applied-<ts>>.json`
  after a successful retry, so the next render doesn't see a stale
  directive.
- `_SCOUT_PHASE_ROLES = {"behaviour", "intent"}` — single source of truth
  for which `data_sources` roles the scout is expected to consult.

### Changed

- `_render_prompt(...)` now accepts `vault_dir` and `cycle_num` kwargs;
  callers that pass them get directive injection, callers that don't
  (e.g. isolated rendering tests) get the legacy pure-substitution
  behaviour unchanged.
- `_spec_data_sources(...)` now accepts `phase` kwarg with phase-scoped
  source selection; default (no phase) preserves legacy behaviour for
  the v1 `check_termination` path.
- `check_termination_v2(...)` passes the report's `phase` field through
  to `_spec_data_sources`, so scout vs research reports get different
  enforcement automatically.
- SG-006 directive `hint` text now includes both compliance patterns
  (string form for consulted sources, dict form with `searched: false`
  + `reason` for genuinely-skipped sources).

### Fixed

- Scout structural-error correction loop now actually feeds the (test: tests/pipeline/test_cycle_runner_scout_correction.py::test_scout_structural_error_triggers_correction_loop)
  validator's errors back to the agent on retry (Bug A above).
- Scout phase no longer aborts when external-docs sources (`role: (test: tests/scripts/test_validate_cycle_phase_scoped_sources.py::test_scout_report_passes_when_only_behaviour_and_intent_consulted)
  domain`) are absent from `sources_consulted` — that's a research
  phase obligation, not a scout obligation (Bug B above).

## [private 0.2.29] - 2026-05-18

**Fixes the user's day-of regression with 0.2.28**: the new H2 enforcement
in 0.2.28 caught the right bug (scouts that skip required sources) but
ran straight into the wrong escape hatch (abort the cycle, throw away the
agent's actual work). 0.2.29 turns the abort into a **correction loop**
so the validator's structured errors feed back to the scout as a
directive and trigger one retry before any abort. Also resolves the
*"why are you asking when settings already says?"* wizard regression
the user has been pointing at since 0.2.23.

### Why now

Same trial-run thread that produced 0.2.28 fired again immediately after
install with two distinct complaints:

1. *"Why are we crashing the whole pipeline instead of just sending the
   result back with 'you didn't meet this criteria. fix it'?"* — Cycle 1
   scout had completed 18 code topics + 19 intents + 10 generalized
   topics. The scout report was structurally valid except `sources_consulted`
   omitted six required sources. The 0.2.28 H2 fix correctly caught this,
   the cycle correctly refused to advance — but then it threw away ~10 min
   of agent work, instead of treating the validator's six named errors as a
   prompt for a do-over.
2. *"Why is the wizard asking me which runtime to use? settings.yaml says
   codex. I removed claude entirely."* — the wizard's runtime branch only
   inspected which binaries were on `PATH`; if both `claude` and `codex`
   were installed it asked unconditionally, ignoring the declared
   `default_executor.runtime`.

### What shipped

#### Scout-validation correction loop (US2 H2 escalation)

- New helper `_retry_scout_with_validation_directive` in
  `src/research_vault/pipeline/cycle_runner.py`: on `validate_cycle.py`
  exit 2, builds a `GateResult(SG-006, FAIL)` from the validator's
  structured error list, runs the existing `build_directive` machinery
  (same path SG-003 has used since 018), re-renders the scout prompt,
  re-runs the scout agent, re-validates. Caps at
  `MAX_SCOUT_VALIDATION_RETRIES = 1` (so total attempts = 2). Only after
  the retry also exits 2 does the cycle abort, with an explicit message
  pointing the operator at the residual sidecar.
- `scripts/validate_cycle.py` now writes a machine-readable sidecar
  `<report>.validation.json` next to every cycle report (status,
  reason, errors, warnings, metrics_delta, report_path, schema_version)
  on every exit code (CONTINUE, TERMINATE, ABORT). The correction loop
  reads the sidecar to populate the directive; scraping stdout is no
  longer required.
- Safety: when the sidecar is missing or its `errors` list is empty
  (e.g. a JSON-parse failure or schema_version error the agent can't
  fix from a directive), the loop returns immediately with the
  original exit 2 — no spurious retries.

#### Install wizard skip-redundant-questions (US-wizard)

- New shell helpers in `dist-templates/install.sh`:
  `declared_runtime_from_settings` parses `settings.yaml`'s
  `default_executor.runtime`; `declared_output_dir` parses
  `settings.output_dir` and the spec's `location` frontmatter.
- Generate-block now consults the runtime helper *before* the
  interactive ask. When settings declares one and the binary is on
  PATH, the wizard prints `Using runtime '<rt>' (declared in
  settings.yaml — not asking).` and skips the prompt. Same treatment
  for the destination-folder ask.
- Fallback to interactive ask preserved for: (a) settings doesn't
  declare a runtime, (b) declares one but the binary is missing on
  PATH (with a warning), (c) only one binary is on PATH (silent
  pick — current behaviour).
- Strict safe-list: the runtime helper only echoes `claude` or
  `codex`. Unknown runtime values (api / script / friendly aliases)
  trigger the interactive fallback rather than being passed to
  `command -v`.

### New tests

- `tests/scripts/test_validate_cycle_sidecar.py` (4 tests) — locks the
  sidecar contract: written on ABORT, written on CONTINUE/TERMINATE,
  required keys present, `errors` non-empty iff status == ABORT.
- `tests/pipeline/test_cycle_runner_scout_correction.py` (3 tests) —
  the correction loop happy path (one retry, success), the cap
  enforcement (persistent failure → abort after retries exhausted),
  the empty-sidecar safety (no infinite loop on missing/empty errors).
- `tests/build/test_install_wizard_skip_redundant_questions.py` (5 tests)
  — both helpers defined, both invoked before their respective legacy
  prompts, banner text present so users see the inferred decision,
  runtime safe-list enforced in the heredoc.

All 12 new tests are added to the `SMOKE_TESTS` array in `build.sh` so
0.2.29's contract survives any future build.

### Architectural threads (still deferred for a daylight design pass)

User feedback expanded the spec-019 US3-US6 stories. Captured in
`specs/019-pipeline-architecture/spec.md` and `clarify.md`, NOT shipped
in 0.2.29:

- **US3 expansion** — goal hierarchy (vault → pipeline → cycle → agent)
  with measured progress per cycle; orchestrator-as-auditor; "pause"
  (not halt) for user input in extreme cases.
- **US4 expansion** — per-vault `code_role` (`source_of_truth` |
  `guide` | `discovery_signal_only`) so the scout can use code as a
  technology pointer for reference vaults vs. business-logic source for
  codebase vaults.
- **US5 expansion** — generalize the 0.2.29 scout correction loop to
  SG-004 / note-writer; "agent fixes its own mess, with delete /
  quarantine as the floor if it can't."
- **US6** — qualitative consensus as a single end-of-pipeline gate
  rather than per-stage.

## [private 0.2.28] - 2026-05-17

**Stops the seam-bug bleeding** by closing four additional HIGH-severity
contract-drift bugs latent in 0.2.27 AND extending the build smoke gate
so the next four can't ship. This is the surgical subset of spec-019
([`specs/019-pipeline-architecture/spec.md`](specs/019-pipeline-architecture/spec.md));
the rest of spec-019 (Vault Blueprint stage, intent-first scout, SG-004
hard mode, multi-agent consensus) is deferred pending a daylight design
pass.

### Why now

Five seam bugs in eight days (0.2.21 BatchResult, 0.2.24 TTY, 0.2.25
budget field, 0.2.26 resume preconditions, 0.2.27 source_file shape). A
spec-019 code review surfaced **four MORE** of the same shape still
latent in shipped 0.2.27 code:

- **H1** — DFS budget cap reads only `budget_consumed_usd` (validator
  structure check accepts three aliases, so `cumulative_cost_usd`
  satisfies structure but the cap check sees $0 spent and never trips).
- **H2** — v2 `sources_consulted` is never validated; an agent that
  emits `[]` passes the validator, defeating the spec's `required: true`
  flag for every post-017 vault.
- **H3** — DFS prompt example uses `next_action` + `termination_reason`
  but validator only reads `termination_condition`; an agent following
  the prompt example faithfully never triggers Conditions A/B/C.
- **H4** — `cli._resume` skips Phase 3 (coverage gate, code-first
  gate, reindex, generate-report) entirely; resume runs that terminate
  cleanly never produce `run-report.md`.

The 018 testing strategy was supposed to prevent this class of bug, but
its smoke gate only ran `test_full_cycle_e2e.py` + `test_multi_cycle_e2e.py`.
0.2.25 / 0.2.26 / 0.2.27 all shipped DESPITE 018 being merged because
**tier-2 contract tests weren't in the gate**. 0.2.28 extends the gate.

### Fixed

- **H1: DFS budget cap honors all three field aliases.** (test: tests/scripts/test_validate_cycle_budget_aliases.py::test_research_phase_budget_cap_fires_for_each_alias) New helper
  `_resolve_budget_v2` in `scripts/validate_cycle.py` resolves
  `budget_consumed_usd` (canonical) → `cumulative_cost_usd` →
  `cost_estimate_usd`, returning the first non-None numeric value.
  Used by `check_termination_v2`'s Condition C check. Regression:
  `tests/scripts/test_validate_cycle_budget_aliases.py` (6 tests).
- **H2: v2 `sources_consulted` is now enforced.** (test: tests/scripts/test_validate_cycle_sources_consulted.py::test_v2_scout_empty_list_sources_consulted_aborts_with_missing_source) New helper
  `validate_sources_v2` accepts both the v2 prompt's LIST form
  (`["GitHub repos", "Confluence", ...]`) and the v1 DICT form, and
  honors `required: true` from `spec-parse.json`. Wired into
  `check_termination_v2`. Regression:
  `tests/scripts/test_validate_cycle_sources_consulted.py` (6 tests).
  Existing test fixtures updated (`condition-c-met.json`,
  `test_validate_cycle_source_file_shapes.py`) to include their
  declared required sources.
- **H3: DFS termination accepts both shapes during deprecation.** (test: tests/scripts/test_validate_cycle_termination_fields.py::test_prompt_aliases_next_action_terminate_with_reason_b_fires_condition_b) New
  helper `_resolve_termination_v2` reads canonical
  `termination_condition` first; falls back to mapping the legacy
  `next_action: "terminate"` + `termination_reason: "A"|"B"|"C"` shape
  to A/B/C with a one-shot `logging.warning` deprecation notice. The
  DFS prompt template (`templates/prompts/dfs-prompt.md.j2`) now emits
  the canonical field in its JSON example; legacy shape removal slated
  for 0.3.0. Regression:
  `tests/scripts/test_validate_cycle_termination_fields.py` (6 tests).
- **H4: `_resume` now finalizes successful runs.** (test: tests/pipeline/test_resume_phase3_completion.py::test_resume_invokes_phase3_when_run_cycles_returns_zero) New helper
  `_run_phase3(spec, vault_dir)` factored from `_cmd_generate`. Called
  from both `_cmd_generate` (always) and `_resume` (only when
  `run_cycles` returns 0 — failed runs leave the vault for inspection
  and re-resume). Regression:
  `tests/pipeline/test_resume_phase3_completion.py` (3 tests).

### Changed (build infrastructure)

- **`build.sh` smoke gate expanded.** Was: two e2e files +
  `tests/_helpers/`. Now also runs all of:
  `test_prompt_validator_contract.py`, `test_validate_cycle_research_schema.py`,
  `test_validate_cycle_source_file_shapes.py`, the three new H1-H3
  contract tests, `test_validate_spec.py`, `test_check_abstraction.py`,
  `test_quality_report.py`, `test_probe_runner.py`,
  `test_preconditions_resume.py`, `test_resume_phase3_completion.py`,
  and the gate-enforcer itself (`tests/build/test_smoke_gate_enforces_contract_tier.py`).
  Each is shipping-blocked: removing one without updating the manifest
  test causes a loud failure. Comment in build.sh explains rationale
  with pointer to spec-019 US1.

### Spec / docs

- New spec: `specs/019-pipeline-architecture/spec.md` — captures US1
  (extended smoke gate), US2 (the four H-fixes above), plus US3
  (Vault Blueprint stage), US4 (intent-first scout), US5 (SG-004 hard
  mode), and US6 (multi-agent consensus). Last four are explicitly
  deferred pending daylight design with the user.
- `specs/019-pipeline-architecture/plan.md` — implementation plan for
  the 0.2.28 subset (US1 + US2), with risk register.
- `specs/019-pipeline-architecture/tasks.md` — 25 tasks covering the
  0.2.28 work; T010-T060 closed in this release.

### Architectural diagnosis (read this before opening a "vault is too
code-biased" issue)

The user reported four architectural concerns post-0.2.27: (1) the
vault is too code-biased; (2) no vault-shape strategy / "north star";
(3) GitHub PRs listed as intent sources but never drive topics; (4)
single-agent verification missed obvious failures. The code review
confirmed every concern is grounded — these aren't perceptions, they're
design properties of the pipeline. The architectural fixes (US3 through
US6 in spec-019) are real work that needs your input on the tradeoffs.
See `specs/019-pipeline-architecture/spec.md` for the proposed design
and the user-driven decisions still outstanding.

## [private 0.2.27] - 2026-05-17

Fixes the **fifth seam bug** in the v0.2.21 → v0.2.26 chain. A fresh
0.2.26 run aborted cycle 3 at scout-report validation with:

```
ERROR: topic source_file not under enumerated repo:
       'acme-corp/backend/balance-service/README.md' (id=CT-3-004)
```

### Root cause

The spec lists every repo with **two** valid representations of the
same on-disk location:

```yaml
- name: balance-service
  url: https://github.com/acme-corp/balance-service          # canonical shape
  local_path: /Users/dev/acme-corp/backend/balance-service   # on-disk shape
```

`templates/prompts/scout-prompt.md.j2` renders BOTH to the scout (URL
under each repo heading; ``local_path`` in the access blurb). The scout
naturally copies whichever it saw most recently — sometimes
``acme-corp/balance-service/README.md`` (URL shape), sometimes
``acme-corp/backend/balance-service/README.md`` (local-path shape with
the extra ``backend/`` wrapper segment).

``scripts/validate_cycle.py`` only knew the URL shape. Its check was:

```python
matched = any(
    source_file.startswith(key + "/") or key in source_file
    for key in repo_keys   # repo_keys = {"acme-corp/balance-service", ...}
)
```

For ``acme-corp/backend/balance-service/README.md``:
- ``startswith("acme-corp/balance-service/")`` → False (the ``backend/``
  segment breaks the prefix)
- ``"acme-corp/balance-service" in "acme-corp/backend/balance-service/README.md"``
  → False (the literal substring isn't present)

So the validator aborted with "topic source_file not under enumerated
repo" even though the scout had correctly identified a file inside the
enumerated repo.

### Fixed — validator (`scripts/validate_cycle.py`)

- **Replaced** ``_spec_primary_repo_urls`` + ``_repo_ownership_keys`` (test: tests/scripts/test_validate_cycle_source_file_shapes.py::test_match_local_path_shape_source_file_the_fifth_seam_bug_fix)
  (URL-only, substring check) with ``_spec_primary_repos`` +
  ``_repo_match_signatures`` + ``_source_file_matches_repo``.
- For each enumerated repo, the validator now builds **two** (test: tests/scripts/test_validate_cycle_source_file_shapes.py::test_signatures_url_plus_local_path_emits_both_shapes)
  path-segment signatures: one from the URL
  (``("acme-corp", "balance-service")``) and one from the local_path
  tail anchored on the URL's first segment
  (``("acme-corp", "backend", "balance-service")``).
- ``source_file`` matches if any signature appears as a **contiguous (test: tests/scripts/test_validate_cycle_source_file_shapes.py::test_match_url_shape_source_file)
  subsequence** of its path segments (after stripping ``file://`` /
  ``https://`` / ``http://`` URL schemes).
- This is strictly more lenient than v0.2.26 on the user's actual case (test: tests/scripts/test_validate_cycle_source_file_shapes.py::test_reject_repo_name_alone_without_org_context)
  (local-path-shape now accepted) AND strictly stricter on cross-repo
  confusion (e.g., a bare ``balance-service/README.md`` with no
  ``acme-corp`` anchor segment is rejected, where the v0.2.26
  substring check would have accepted it via "in").

### Fixed — scout prompt (`templates/prompts/scout-prompt.md.j2`)

- Added a "**`source_file` shape (mandatory)**" section that explicitly (test: tests/generator/test_templates.py::test_scout_prompt_declares_canonical_source_file_shape)
  shows the canonical URL-derived shape with right/wrong examples.
- Each repo block now renders an explicit ``Canonical `source_file` (test: tests/generator/test_templates.py::test_scout_prompt_declares_canonical_source_file_shape)
  prefix:`` field derived from the URL, plus relabels the on-disk
  access path as ``Access (your filesystem, NOT for `source_file`):``.
- Constraint list updated to require the canonical shape. (test: tests/generator/test_templates.py::test_scout_prompt_declares_canonical_source_file_shape)
- Result: future cycles will converge on the URL shape; the validator (no test: forward-looking behaviour note; validator + prompt tests above lock the contract)
  fix above is the safety net for any leakage of the local-path shape.

### Added — regression tests

- **`tests/scripts/test_validate_cycle_source_file_shapes.py`** —
  16 tests:
  - 4 unit tests for ``_repo_match_signatures`` (URL-only,
    URL+local_path, no-anchor edge case, dedup when both shapes agree).
  - 8 unit tests for ``_source_file_matches_repo`` (URL shape matches,
    local-path shape matches, ``file:///`` URI matches, wrong-repo
    rejected, foreign-org rejected, bare-repo-name rejected, empty
    source_file rejected, no-signatures rejected).
  - 4 subprocess end-to-end tests against a staged vault with the
    user's exact spec shape (``url`` + ``local_path`` with ``backend/``
    wrapper):
    - local-path-shape scout: must validate (was the abort);
    - URL-shape scout: must still validate (v0.2.26 compat);
    - mixed-shape scout: must validate;
    - truly-wrong-repo scout: must still abort with "not under
      enumerated repo" (locks the validator's main job).
- **`tests/generator/test_templates.py`** — 1 new test:
  ``test_scout_prompt_declares_canonical_source_file_shape`` locks the
  prompt fix (canonical-shape callout, per-repo canonical prefix,
  filesystem-only labelling of local_path).

### Process note

This is the FIFTH seam bug in eight days (0.2.21 BatchResult, 0.2.24
TTY, 0.2.25 budget-field, 0.2.26 resume preconditions, 0.2.27
source_file shape). Each one was a contract mismatch between two
individually-correct components that the existing test suite didn't
exercise together. The 018-testing-strategy contracts layer covers the
JSON shapes the prompts emit and the validator consumes, but doesn't
yet exercise **spec-shape variants** — e.g., specs whose ``local_path``
has wrapper segments vs not, specs with ``url`` only vs ``local_path``
only. A follow-up tier-3 (contract) test suite parameterised over
representative spec shapes would catch this whole class.

## [private 0.2.26] - 2026-05-17

Fixes the **fourth seam bug** in the v0.2.21 → v0.2.25 chain. After the
0.2.25 validator + prompt fix unblocked cycle 5 validation, the user ran
``./generate.sh --resume --cycle 6`` and got:

```
Preconditions unmet:
  - precondition 1: pytest tests/scripts/ failed in research-vault repo
  - precondition 2: validate_vault.py reports violations
  - precondition 6: source preflight failed — see _pipeline/preflight.json
```

Three independent bugs in ``pipeline/preconditions.py`` — the same Phase-2
entry gate was reused for ``--resume`` without re-evaluating whether each
check still made sense:

| # | Check | Why it's wrong on --resume |
|---|---|---|
| 1 | Run the **framework's** pytest tests | Framework is already pip-installed (wheel install verified it) and previous cycles ran. The fallback that ran ``pytest tests/scripts/`` from CWD also blew up on every bundled install because the bundle ships no ``tests/`` directory. |
| 2 | ``validate_vault.py`` must exit 0 | Resume's whole purpose is to **fix** existing vault issues with more cycles. Demanding a clean vault upfront is paradoxical. The cycle's own SG-004 gate already downgrades these findings to WARN; only the precondition kept turning them back into a hard block. |
| 6 | Source preflight overall_status != fail | Preflight's recognized-access-method set is narrower than the spec validator's, so specs with ``access_method: "web fetch"`` / ``"local filesystem"`` report every source unreachable. Existing cycles ran fine — the failure is in the preflight checker, not the sources. |

### Fixed

- **``pipeline/preconditions.py``** — ``check`` gains a keyword-only (test: tests/pipeline/test_preconditions_resume.py::test_resume_with_realistic_v0_2_25_user_vault_succeeds)
  ``for_resume: bool = False`` parameter. When ``True``:
  - Precondition 1 (framework tests) is skipped with an INFO breadcrumb.
  - Precondition 2 (validate_vault.py) is skipped with an INFO breadcrumb.
    The cycle's SG-004 gate inside ``run_cycle_steps`` still enforces what
    the orchestrator actually needs.
  - Precondition 6 (source preflight) still runs, but a fail verdict
    becomes a ``logger.warning`` instead of an unmet entry. The log line
    explains *why* the verdict was downgraded so the failure mode is
    inspectable.
  - Preconditions 3/4/5 (structural files: coverage-targets, budget-log,
    CLAUDE.md naming convention) STILL block resume — they're structural
    invariants the orchestrator can't function without.
- **``pipeline/preconditions.py``** — Precondition 1 fallback bug fixed (test: tests/pipeline/test_preconditions_resume.py::test_initial_generate_skips_pytest_fallback_when_not_in_repo)
  even on initial generate. The v0.2.25 code ran ``pytest tests/scripts/``
  with no ``cwd=`` argument, so it picked up *any* ``tests/scripts/``
  directory the caller happened to be standing in (or, more commonly,
  exited non-zero because no such directory existed in the bundle
  folder). v0.2.26 only runs the framework-tests fallback when the CWD is
  detectably the research-framework repo (``pyproject.toml`` declaring
  ``research-vault`` + co-located ``tests/scripts/`` directory). Bundled
  installs skip the check with a INFO breadcrumb instead of inventing a
  failure.
- **``cli.py::_resume``** — passes ``for_resume=True`` to ``check``. (test: tests/pipeline/test_preconditions_resume.py::test_resume_skips_precondition_2_validate_vault_failures)

### Added — regression coverage

- **``tests/pipeline/test_preconditions_resume.py``** — 10 tests that
  lock the v0.2.26 contract:
  - 3 tests: resume skips Pre 1, Pre 2, and downgrades Pre 6 (the
    user's three blockers).
  - 1 end-to-end realistic test that reconstructs the exact shape of the
    user's ``reference-vault-v4`` cycle-6 attempt and asserts ``ok=True,
    unmet=[]``. **This test would have caught the v0.2.25 regression
    before it shipped.**
  - 3 tests: resume STILL blocks on missing coverage-targets, missing
    budget-log, missing CLAUDE.md (structural invariants).
  - 1 test: initial generate skips the pytest fallback when CWD is not
    the framework repo (locks the v0.2.25 phantom-failure regression).
  - 2 tests: initial generate STILL runs validate_vault and preflight
    checks (backwards-compat guard so v0.2.26 doesn't over-relax).
- All 9 pre-existing precondition tests continue to pass (``check()``
  remains backwards-compatible — the new parameter is keyword-only with a
  ``False`` default).

### Process note

This is the second time in three days that ``--resume`` shipped broken in
a way the existing test suite didn't catch (after the 0.2.21 BatchResult
seam and the 0.2.25 budget-field seam). The 018-testing-strategy e2e tier
covers ``run_cycle_steps`` end-to-end with the fake agent, but it doesn't
exercise the resume entry point (Phase-2 preconditions + ``run_cycles``
in resume mode). A follow-up tier-5 scenario will add that coverage so
"resume an existing vault" gets the same protection as "run the first
cycle of a fresh vault".

## [private 0.2.25] - 2026-05-17

### Added — Layered testing strategy + hard build gate (feature 018)

After three back-to-back seam-bug releases (0.2.20 → 0.2.21 → 0.2.22,
followed by 0.2.24's install-wizard regression and 0.2.25's research-phase
budget-field mismatch), the existing 1060+ unit-test suite was proven
inadequate at one specific category of failure: **contract mismatches
between two correct sub-components**. Feature 018 adds the missing
tier-3/4/5 infrastructure plus a hard `build.sh` gate so a tarball cannot
be produced if the end-to-end tier is red. **No production code paths are
modified by this entry** — every change is under `tests/`, `docs/`,
`build.sh`, `pyproject.toml`, `CLAUDE.md`, and `specs/018-testing-strategy/`.

- `tests/_helpers/fake_agent.py` — deterministic stub for `scripts/agent_call.py`.
  Emits a valid v2 scout report and writes notes with full Tier-1+Tier-2
  frontmatter for every `## Batch topics (JSON)` block in a prompt. Scenarios
  (`happy`, `empty_scout`, `fail_frontmatter`, `oos_topic`, `partial_yield`)
  are selected via `FAKE_AGENT_SCENARIO` / `FAKE_AGENT_<STAGE>_SCENARIO`
  env vars. Contract: `specs/018-testing-strategy/contracts/fake-agent.contract.md`.
- `tests/_helpers/vault_factory.py` — `build_minimal_vault(tmp_path, ...)`
  produces a real-looking vault that the production `cycle_runner.py` can drive
  unmodified. Installs the fake-agent shim over `scripts/agent_call.py`.
- `tests/pipeline/test_full_cycle_e2e.py` — 5 tier-4 scenarios that lock the
  three known seam bugs as regression tests (asymmetric tail batch, empty
  scout abort, SKILL.md auto-repair, SG-005 correction loop) plus a happy
  path.
- `tests/pipeline/test_multi_cycle_e2e.py` — 3 tier-5 scenarios (3-cycle
  coverage progression, cycle-to-cycle handoff without overwriting cycle 1
  notes, cross-cycle correction lifetime).
- `tests/build/test_smoke_gate_enforced.py` — structural assertion that
  `build.sh` contains the gate + slow integration test that mutates
  `pipeline/batch.py` and proves `build.sh` aborts before producing a
  tarball.
- `build.sh` — new § 0 "Smoke gate" block. Runs the e2e tier before the
  wheel build. **No `--skip-smoke` flag** — the only way to ship a broken
  bundle is to delete the gate from `build.sh`, which is a code change
  requiring intent.
- `docs/testing-strategy.md` — six-tier pyramid documentation, decision
  tree ("which tier do I add a test at?"), anti-patterns.
- `tests/README.md` — directory map + common invocations.
- `pyproject.toml` — registered `@pytest.mark.e2e` and `@pytest.mark.slow`.
- `CLAUDE.md` — new Testing section pointing at `docs/testing-strategy.md`.

Combined cost: ≈ 90 s for the e2e tier alone (the new floor for `build.sh`),
≈ 3 min for the full `pytest` sweep. Token spend: zero (every external agent
call goes through the fake).

Merged in from the `018-testing-strategy` development clone alongside the
0.2.25 release.

### Fixed — research-phase budget-field seam bug

Fixes the third consecutive **seam bug** in the v0.2.21 → v0.2.24 series.
The user's cycle-5 run aborted at the research-validation step with:

```
============================================================
CYCLE VALIDATION: ABORT
============================================================
Reason: Report has 1 structural error(s)

Errors (1):
  ERROR: missing required v2 field: budget_consumed_usd
============================================================
[orchestrator] cycle 5 aborted (exit 2)
```

Same exact failure shape as v0.2.19 cycle-6 and v0.2.21 BatchResult: two
individually correct components, broken contract between them, every test
green because no test ever exercised the seam.

### Root cause

Three components disagreed on what to call the research-phase budget field:

| Component | Field name(s) |
|---|---|
| `templates/prompts/dfs-prompt.md.j2` (what the agent is TOLD to emit) | `cost_estimate_usd`, `cumulative_cost_usd` |
| `scripts/validate_cycle.py` `REQUIRED_REPORT_FIELDS_V2_RESEARCH` (what the validator DEMANDS) | `budget_consumed_usd` |
| `pipeline/orchestrator.py` budget tracker (what's READ from reports) | all three, with fallback chain |
| `tests/fixtures/stubs/claude` and v2 fixtures (what tests EXERCISE) | `budget_consumed_usd` only |

The stub agents and the JSON fixtures both used the validator-canonical
name, so every test passed. Real agents (Claude / Codex / Gemini)
correctly emitted what the prompt asked for — and every real cycle
aborted. Confirmed against the user's cycle-005-research.json, which
contains `cumulative_cost_usd: 0.0` and no `budget_consumed_usd`.

### Fixed

- **`scripts/validate_cycle.py`** — research-phase validator now accepts (test: tests/scripts/test_validate_cycle_research_schema.py::test_research_report_with_only_cumulative_cost_usd_is_accepted)
  any one of `budget_consumed_usd`, `cumulative_cost_usd`, or
  `cost_estimate_usd` as proof of budget reporting (new
  `BUDGET_FIELDS_V2_RESEARCH` constant). This mirrors the
  orchestrator's existing fallback chain so the validator can never
  again be stricter than the consumer. Scout reports keep the strict
  `budget_consumed_usd` requirement (no fallback there).
- **`templates/prompts/dfs-prompt.md.j2`** — DFS prompt now teaches (test: tests/scripts/test_prompt_validator_contract.py::test_dfs_prompt_emits_canonical_budget_field_v0_2_25)
  agents to emit `schema_version: "2.0"` AND `budget_consumed_usd`
  alongside the legacy `cost_estimate_usd` / `cumulative_cost_usd` so
  future reports are aligned with the v2 schema contract directly.
- **`templates/prompts/scout-prompt.md.j2`** — DFS-phase section in the (test: tests/scripts/test_prompt_validator_contract.py::test_dfs_prompt_emits_every_validator_required_research_field)
  scout prompt mirrors the same change (the file contains two prompt
  shapes; the DFS one had the same bug as the standalone DFS prompt).

### Added — schema-contract / seam coverage (the layer that was missing)

- **`tests/scripts/test_prompt_validator_contract.py`** — first
  schema-contract test in the repo. Parses the actual Jinja prompt
  templates, extracts the JSON-block top-level keys the prompt asks
  agents to emit, and asserts:
  1. The DFS prompt emits every field in
     `REQUIRED_REPORT_FIELDS_V2_RESEARCH`. **This test would have
     caught the v0.2.21 / v0.2.24 crash before either ever shipped.**
  2. The DFS prompt emits at least one budget field from
     `BUDGET_FIELDS_V2_RESEARCH`.
  3. The DFS prompt emits the canonical `budget_consumed_usd` (not
     only the legacy aliases), so cleanup actually sticks.
  4. The scout prompt emits every field in
     `REQUIRED_REPORT_FIELDS_V2` (the superset with `topics_from_code`,
     `intent_from_confluence`, `dimensions_covered`,
     `schema_version`).
  5. The validator's `BUDGET_FIELDS_V2_RESEARCH` constant matches the
     orchestrator's budget-reader source so the two cannot drift apart
     silently.
  6. A realistic cycle-5 report shape (the exact one that broke the
     user's run, sans `budget_consumed_usd`, with `cumulative_cost_usd`
     instead) validates cleanly post-fix. Locked as a permanent
     regression case.
- **`tests/scripts/test_validate_cycle_research_schema.py`** — extended
  with four new behavioural cases: report-with-only-`cumulative_cost_usd`,
  report-with-only-`cost_estimate_usd`, report-with-no-budget-at-all
  (must still reject), and report-with-all-three-aliases. Each case
  invokes the real validator CLI end-to-end so it catches packaging
  regressions too.

### Process note

This is the first contract-layer test that walks both sides of an
agent/validator seam in this repo. The 018 testing-strategy spec
generalises this pattern: every prompt template will get a sibling
contract test, and the test pyramid's middle layer (schema contracts)
becomes the canonical defense against this entire bug class.

## [private 0.2.24] - 2026-05-17

Hot-fix for a self-inflicted regression in the v0.2.23 install-log
work: every install silently degraded to **non-interactive mode**
and the wizard never offered to run `generate.sh`. Users running
`./install.sh` from a real terminal saw:

```
[install] runtime ready.
...
Running non-interactively — skipping the wizard.
Run ./generate.sh once you have a research.spec.md next to it.
```

Root cause was a contract mismatch between two correct components
inside `install.sh` itself:

- v0.2.23 added `exec > >(tee -a install.log) 2>&1` near the top so
  every line of output is mirrored to `install.log` in real time.
- The redirect rewires stdout/stderr to a pipe (the tee process
  substitution). After the redirect, `-t 1` and `-t 2` return false
  even when the user is on a real terminal.
- `is_interactive()` below the redirect tested `-t 0 && -t 1`, so it
  returned false for *every* interactive run and short-circuited the
  whole wizard. The "non-interactive" branch was correct logic
  applied to wrong inputs.

Same class as the 0.2.20–0.2.22 seam bugs — two correct sub-components,
broken contract, no existing test that walked the whole script under
a real pty.

### Fixed

- **`dist-templates/install.sh`** captures `-t 0` / `-t 1` / `-t 2` (test: tests/scripts/test_install_sh_tty_handling.py::test_install_sh_captures_tty_state_before_log_redirect)
  into `RV_STDIN_IS_TTY` / `RV_STDOUT_IS_TTY` / `RV_STDERR_IS_TTY`
  BEFORE the log redirect, then `is_interactive()` consults those
  cached values instead of the live FD state. Both `-t 0 && -t 1`
  live checks are explicitly removed from the function body. The
  wizard fires correctly on every real terminal regardless of the
  log redirect. The `RV_INSTALL_LOG=0` opt-out still works exactly
  as before.

### Added — regression coverage

- **`tests/scripts/test_install_sh_tty_handling.py`** locks the v0.2.24
  contract with 6 tests:
  - 3 structural checks parse `dist-templates/install.sh` and assert
    (a) the TTY-state capture appears BEFORE the log redirect,
    (b) `is_interactive()` consults `RV_STDIN_IS_TTY` /
    `RV_STDOUT_IS_TTY` and NOT live `-t 0` / `-t 1`,
    (c) all three streams (stdin / stdout / stderr) are captured.
  - 3 behavioural checks run a sandboxed copy of the TTY-capture +
    `is_interactive` blocks under controlled stdin/stdout conditions:
    forked under a real pty (decision = interactive), with
    `stdin=/dev/null` (decision = non-interactive), and with
    `RV_NONINTERACTIVE=1` even under a pty (decision =
    non-interactive). The pty test would have caught the v0.2.23 bug
    before it shipped.

### Process note

This is the FIRST time a bug in `install.sh` itself has had test
coverage. The next bundle that breaks the wizard will fail a unit
test before it can ship — and the test pyramid spec (feature 018)
will formalize this for the whole script surface.

## [private 0.2.23] - 2026-05-17

Observability + structural-testing release. **No production behavior
changes to the pipeline logic**; this release fixes the *diagnostic*
gap that has made the last three hot-fix releases (0.2.20 / 0.2.21 /
0.2.22) so expensive to investigate, and adds the spec for the layered
test pyramid that will stop new seam bugs from shipping.

### Fixed — mid-pipeline crash logs are now actually useful

Previously `pipeline/cycle_runner.py::_run_script` ran every subprocess
via `subprocess.run(stdout=PIPE)` and wrote the buffered output to disk
**after** the subprocess exited. Symptoms:

- `cycle-NNN-scout.log` sat at 0 bytes for the 15+ minutes the agent (no test: pre-fix symptom; regression locked by tests/pipeline/test_run_script_streaming.py)
  spent thinking, then suddenly filled at exit. `tail -f` was useless.
- If the parent crashed mid-subprocess, the log stayed empty forever (no test: pre-fix symptom; regression locked by tests/pipeline/test_run_script_streaming.py::test_log_is_line_buffered_so_partial_output_survives_subprocess_crash)
  even though the agent had produced kilobytes of output.
- Parent-side orchestration banners (`[Step N - …]`) block-buffered (no test: pre-fix symptom; regression locked by tests/cli/test_force_line_buffered_stdio.py)
  to 4–8KB chunks whenever stdout was redirected (`./generate.sh | tee
  run.log`), so even the framework's own messages arrived in bursts.
- `install.sh` produced no log file at all — the terminal scrollback (no test: pre-fix symptom; install log redirect is structural shell change without a dedicated regression test)
  was the only record of an install attempt.

The v0.2.23 redesign:

- **`pipeline/cycle_runner.py::_run_script`** — now uses (test: tests/pipeline/test_run_script_streaming.py::test_lines_are_visible_on_disk_while_subprocess_still_running)
  `subprocess.Popen` with line-iteration. Every subprocess line is
  prefixed with `[HH:MM:SS]` and flushed to BOTH the log file and
  parent stdout immediately. Log file is opened `buffering=1`
  (line-buffered) so a parent crash before subprocess exit still leaves
  every line printed before the crash on disk. Startup
  `# launching: …` header and exit `# exited with code N` footer
  bracket each run so post-mortems can read elapsed wall-clock time
  from the log alone.
- **Heartbeat thread** — when the subprocess is silent for longer than (test: tests/pipeline/test_run_script_streaming.py::test_heartbeat_emits_alive_line_for_silent_subprocess)
  30s (configurable via `RV_HEARTBEAT_S`), a `[heartbeat] pid=…
  elapsed=…s still alive` line lands in the log. `tail -f` now always
  shows activity; users can distinguish "agent thinking" from "process
  dead." Thread is daemonic and terminates cleanly when the subprocess
  exits.
- **Graceful subprocess shutdown** — on parent interrupt (no test: graceful shutdown path; subprocess lifecycle covered by streaming tests)
  (`KeyboardInterrupt`) or exception, the subprocess is `terminate`'d
  (and `kill`'d after 5s) so we never orphan an agent worker burning
  tokens after the parent dies.
- **`cli.py::main`** — first action is now (test: tests/cli/test_force_line_buffered_stdio.py::test_main_invokes_force_line_buffered_stdio_on_first_action)
  `_force_line_buffered_stdio()`, which calls
  `sys.stdout.reconfigure(line_buffering=True)` and the same on
  `sys.stderr`. Orchestration banners flush in real time even when
  output is piped to `tee` or redirected to a file.
- **`dist-templates/install.sh`** — re-execs itself with (no test: install.sh log redirect; behavioural contract not unit-tested)
  `exec > >(tee -a install.log) 2>&1` so every line of install output
  is mirrored to `install.log` in real time. The file is truncated on
  each install attempt so it always reflects the most recent run.
  Sets `PYTHONUNBUFFERED=1` so pip and Python child processes flush
  in real time too. Opt-out via `RV_INSTALL_LOG=0`.
- **`dist-templates/generate.sh`** — same treatment with (no test: generate.sh log redirect; behavioural contract not unit-tested)
  `generate.log` so end-to-end pipeline runs always leave a
  postmortem-able log on disk. Opt-out via `RV_GENERATE_LOG=0`.

### Added — regression coverage for the logging fix

- **`tests/pipeline/test_run_script_streaming.py`** locks every facet
  of the new streaming behaviour with 9 tests:
  - Timestamp prefix on every line (format `[HH:MM:SS]`).
  - Header `# launching: …` and footer `# exited with code N`.
  - The keystone:
    `test_lines_are_visible_on_disk_while_subprocess_still_running`
    runs `_run_script` in a background thread and asserts the first
    subprocess line is readable from disk WHILE the subprocess is
    still alive (sleeping on a sentinel flag). Without the v0.2.23
    fix, this test hangs until the timeout — locking the regression
    permanently.
  - Heartbeat fires for silent subprocesses (RV_HEARTBEAT_S=1, 2.5s
    silence) and does NOT fire for fast subprocesses (RV_HEARTBEAT_S=30,
    run < 1s).
  - Output before a non-zero-exit crash is on disk; footer records
    the non-zero exit code.
  - Missing Python binary still raises `_StepError` (preserves the
    v0.2.22 external contract every cycle_runner call-site relies on).
  - No-log-file code path still works for legacy call sites.
- **`tests/cli/test_force_line_buffered_stdio.py`** — 4 tests covering
  the new `_force_line_buffered_stdio` helper: reconfigures both
  streams, swallows `AttributeError` from non-TTY streams, swallows
  `OSError` from closed streams, and is invoked by `cli.main` as the
  first action.

### Added — testing strategy spec (feature 018)

`specs/018-testing-strategy/{spec,plan,tasks}.md` documents the
layered test pyramid (unit → schema contract → seam → single-cycle
e2e → multi-cycle e2e → smoke gate) that will be implemented in a
follow-up feature. Includes the post-mortem of the 0.2.20 → 0.2.22
seam-bug chain and the design decisions that drive the new
infrastructure:

- A reusable `tests/_helpers/fake_agent.py` module replaces every real
  LLM call in tests with a deterministic stub.
- New tier-4 (single-cycle) and tier-5 (multi-cycle) e2e tests drive
  the real `run_cycle_steps` / `run_cycles` against the fake.
- `build.sh` gains a hard smoke gate that refuses to build a bundle
  when the e2e tier is red — no opt-out flag.

Implementation will land in 0.2.24 (tier-3 seam tests already started
landing in 0.2.22 with `test_batch_result_serialization.py`).

### Process note

This release intentionally does NOT change pipeline behavior. The
production code paths are byte-identical to 0.2.22 plus the logging
redesign. Any cycle that completed cleanly on 0.2.22 will complete
cleanly on 0.2.23 — only the diagnostic surface has changed.

## [private 0.2.22] - 2026-05-17

Hot-fix for the **trailing-batch serialization abort** observed on
the v0.2.21 `reference-vault-v4` test run. Cycle 1 successfully dispatched
batches 1 and 2 (3 topics each) and the agent processed batch 3
(2 topics), but `BatchResult.to_dict()` then raised
`ValueError: BatchResult.topics must hold 3..10 PrioritizedTopic rows`
on serialization, aborting cycle 1 with all 8 generated notes orphaned.

Root cause was a contract mismatch between two correct components:
the slicer (`slice_topics_into_batches`) intentionally produces
asymmetric tail batches when the priority queue is not a clean
multiple of the configured batch size — a queue of 8 with
`batch_size=3` yields `3 + 3 + 2`. The serializer enforced the
slicer's *preferred* minimum (3) as a *hard* invariant. Unit tests
passed because every existing test constructed `BatchResult` with
`len(topics) ≥ _MIN_BATCH`; the realistic asymmetric-tail case was
never exercised.

### Fixed

- **`BatchResult.to_dict()` accepts batches of 1..10 topics** (test: tests/pipeline/test_batch_result_serialization.py::test_asymmetric_queue_produces_serializable_tail_batch)
  (`pipeline/batch.py`). The `_MIN_BATCH = 3` constant remains, but
  it now governs only the slicer's preferred batch size, not the
  serialization contract. A trailing batch with 1 or 2 topics is a
  legitimate state — the dispatcher built it, the agent processed
  it, the report must reach disk so the cycle can advance. Oversized
  batches (`> _MAX_BATCH = 10`) and empty/none topic lists still
  raise loudly, since those would indicate a real dispatcher bug.

### Added — regression coverage

- **`tests/pipeline/test_batch_result_serialization.py`** locks the
  relaxed contract in with 19 tests across three groups:
  - `test_to_dict_accepts_realistic_batch_sizes[1|2|3|5|10]` — every
    valid size serializes.
  - `test_to_dict_rejects_*` — empty / `None` / oversized still raise
    (preserves the loud-failure semantics for real dispatcher bugs).
  - `test_asymmetric_queue_produces_serializable_tail_batch` — the
    exact production crash (queue=8, batch_size=3 → 3+3+2) walks
    slicer → `BatchResult` → `to_dict` and asserts every batch
    serializes.
  - `test_every_slicer_output_serializes_for_arbitrary_queue_sizes`
    — a parametric sweep over 10 (queue_size, batch_size) combos
    that exercises the slicer↔serializer seam end-to-end. Any future
    invariant added to `BatchResult.to_dict` will trip this test
    before reaching a tagged release.

### Process note

This is the third consecutive release fixing a bug at the seam
between two correct sub-components (placeholder generation ↔
slicer in 0.2.21, scout output ↔ plan merge in 0.2.21, slicer ↔
serializer in 0.2.22). The pattern was that unit tests verified
each component against *ideal* inputs but never walked the realistic
chain. The new parametric `test_every_slicer_output_serializes_*`
test is the first one in this codebase that exercises the
slicer→serializer chain at the seam level; we should keep adding
similar chain-level tests for the scout→merge→slice and
dispatcher→gates→report seams as they bite us.

## [private 0.2.21] - 2026-05-17

Hot-fix for the **zero-batch cycle abort** observed on the first
v0.2.20 test run (`reference-vault-v4`): scout produced 15 real topics in
`topics_found.new` but the dispatcher saw an all-placeholder priority
queue, dropped every entry, and wrote a 4-line sentinel
`cycle-NNN-research.json` that Step 6 then aborted against with 20
schema errors. Root cause was architectural — the deterministic
research plan was built once **pre-cycle** from static state and never
re-enriched with what scout actually found.

### Fixed

- **Scout topics now reach the dispatcher** (`pipeline/research_plan.py` (test: tests/pipeline/test_merge_scout_topics.py::test_merge_prepends_scout_topics_with_score_one)
  + new Step 2.5 in `pipeline/cycle_runner.py`). Between scout (Step 1)
  and DFS dispatch (Step 3), the cycle runner now loads
  `_pipeline/research-plan.md`, calls
  `merge_scout_topics(plan, cycle-NNN-scout.json)` to fold every
  `topics_found.new` entry into the queue (`provenance="scout"`,
  `priority_score=1.0` so they pin to the top), and rewrites the plan
  on disk. Case-insensitive dedup against existing queue titles and
  exclusion filtering against `proposed_filename` keep the queue
  honest. Best-effort: a malformed or missing scout JSON logs a WARN
  and leaves the plan untouched — it does not abort the cycle.
- **`validate_vault.py` skips generator-owned scaffold files**. (test: tests/scripts/test_validate_vault.py::test_skips_scaffold_index_and_templates) The
  walker now ignores `_index.md` / `_concepts.md` / `_graph.md` at the
  `data_vault/` root and anything under `_templates/`. The first
  v0.2.20 run reported 16 false-positive "missing YAML frontmatter"
  violations every cycle against these files, which the cycle runner
  correctly ignored but which buried any real violations on
  agent-written notes.

### Changed

- **Placeholder topic generation removed** (`_placeholder_titles`
  callers in `_build_priority_queue`). The historical fallback that
  synthesised `"<category>: focus topic N"` rows when a category had
  no enumerated `expected_filenames` was the wrong solution: every
  generated placeholder reached the dispatcher, hit the v0.2.20 batch
  filter, was correctly dropped, and contributed to zero-yield
  cycles. The constants and detection helpers
  (`PLACEHOLDER_PROVENANCE`, `PLACEHOLDER_TITLE_RE`,
  `is_placeholder_topic`) are kept so the batch filter still catches
  any placeholder that round-trips through legacy data, but no new
  placeholders are created.
- **`generate_plan` accepts empty queues by default** (`require_nonempty_queue=False`).
  A pre-cycle plan whose categories have no `expected_filenames` is a
  legitimate state — scout will fill the queue in Step 2.5. The opt-in
  flag preserves the v0.2.20 "fail closed at plan generation"
  semantics for callers that have no scout step downstream (e.g. the
  standalone `research-vault plan` CLI).

## [private 0.2.20] - 2026-05-17

Post-cycle-6 hardening pass: stop the pipeline from silently degrading,
collapse the cycle log down to something a human can actually read, and
reject the "bookkeeping fraud" failure mode that the v0.2.19 SG-005
correction directive accidentally encouraged.

### Fixed

- **SKILL.md preflight + auto-restore** (`pipeline/skill_check.py` + new (test: tests/pipeline/test_skill_check.py::test_validate_and_repair_restores_from_bundle)
  `research-vault check-skills` subcommand). External agent CLIs (Cursor,
  Codex, the Superpowers plugin) auto-discover `.agents/skills/*/SKILL.md`
  and have, in earlier bundles, rewritten the YAML frontmatter on first
  open — flattening multi-line strings, injecting `related: []` /
  `status: draft`, and breaking parse. Both `install.sh` and the
  cycle-runner's new **Step -1** validate every skill, copy the wheel's
  bundled file over any broken one, and refuse to start the cycle if a
  file is unrecoverable. The v0.2.19 cycle-6 symptom — `failed to load
  skill … invalid YAML` for verifier / topic-classifier / source-relevance
  / cycle-report and then a half-loaded skill registry — is now a loud
  fail at preflight rather than a silent skill drop mid-cycle.
- **SG-004 path resolution** (`pipeline/gates_step.py`). (regression test: tests/pipeline/test_gates_step_sg004_005.py::TestSG004ValidateVaultWrapper::test_exit_zero_is_pass) The gate was
  looking up `scripts/validate_vault.py` relative to the repo root, which
  resolves to `<venv>/lib/python3.12/scripts/validate_vault.py` inside an
  installed wheel — i.e. it always failed with `[Errno 2]` and produced a
  `WARN` per batch. Now we resolve first under `vault_dir/scripts/`, fall
  back to `_REPO_ROOT/scripts/`, and **`FAIL`** explicitly when neither
  exists (no more silent WARNs).
- **DFS / research report v2 schema** (`scripts/validate_cycle.py`). (test: tests/scripts/test_validate_cycle_research_schema.py::test_research_report_without_scout_only_fields_is_accepted)
  Research-phase reports are now validated against
  `REQUIRED_REPORT_FIELDS_V2_RESEARCH`, a strict subset that drops the
  scout-only fields (`topics_from_code`, `intent_from_confluence`,
  `dimensions_covered`). The v0.2.19 cycle-6 abort
  (`CYCLE VALIDATION: ABORT … missing required v2 field: …`) is gone;
  scout reports still get the full v2 contract.
- **Anti-fraud guard on correction batches** (`pipeline/cycle_runner.py`). (test: tests/pipeline/test_anti_fraud_correction.py::test_no_changes_at_all_still_fires_on_correction_batch)
  Snapshots the body hash of every vault note before a correction batch
  runs, then fires a new `SG-006` `FAIL` if the batch produces zero new
  files AND leaves every body unchanged. That is the exact signature of
  the v0.2.19 cycle-6 "fake fix" — the agent renamed titles on
  pre-existing notes and rewrote the cycle research report to claim them
  as `notes_updated`.
- **SG-005 correction hint rewritten**. (no test: prompt hint wording only; SG-005 gate behaviour locked by tests/pipeline/test_gates_step_sg004_005.py) The old hint
  ("restore frontmatter completeness — write notes with required
  coverage_category, source_urls, and summary fields") nudged correction
  agents toward cosmetic edits. New wording explicitly tells the agent to
  write a new file in `data_vault/<folder>/` per assigned topic and to
  report blocked topics under `skipped_topics` with
  `reason=insufficient_evidence` rather than faking completion.

### Added

- **Placeholder-topic filter at batch dispatch** (`pipeline/batch.py` +
  `pipeline/research_plan.py`). Spec-gap stubs synthesised by
  `_placeholder_titles` ("flows: focus topic 3", …) carry the new
  `provenance="spec_gap_placeholder"` tag (with a title-regex fallback
  for round-tripped JSON). `slice_topics_into_batches` drops them
  pre-dispatch and skips any batch that shrinks below
  `_MIN_BATCH=3` *because of the filter* — small queues still ship.
- **Per-cycle human-readable summary** at
  `_pipeline/cycles/cycle-NNN-summary.md` (`pipeline/cycle_summary.py`).
  Drains scout report, research report, quality report, and the skill-check
  sidecar into one page: notes created/updated, gate verdicts, cost,
  capture failures (aggregated by host so 11 GitHub URLs collapse to one
  `github.com × 11` bullet), and the cycle's exit decision. Always
  written, even on early abort — best-effort and never raises.
- `_pipeline/cycle-NNN-skill-check.json` sidecar describing scanned /
  repaired / unrecoverable skill files.
- **Per-cycle stage timings + end-of-pipeline run report**
  (`pipeline/timings.py` + `pipeline/run_report.py`). Every cycle now
  prints `Started: <UTC>` / `Finished: <UTC>` banners, and writes
  `_pipeline/cycles/cycle-NNN-timings.json` with each stage's start
  timestamp + wall duration in seconds. The orchestrator finalises
  `_pipeline/run-report.md` on every exit path (success, source-exhausted,
  budget-constrained, abort) — one table per cycle with notes
  created/updated, new scout topics, USD cost, input/output tokens, and
  the top 3 longest stages, plus grand totals across the run. Both are
  best-effort and never influence exit codes; previously, answering
  "where did the time / budget actually go?" meant scraping log timestamps
  by eye.

### Changed

- `dist-templates/scaffold-manifest.json` regenerated against the new
  `dfs-prompt`-derived schema and the rewritten SG-005 hint.

## [private 0.2.19] - 2026-05-16

### Fixed

- **Scout prompt template now matches the SG-001 contract** (feature 017 (test: tests/generator/test_templates.py::test_scout_prompt_instructs_generalize_step_and_topics_found)
  follow-up). The CODE-FIRST branch of
  `templates/prompts/scout-prompt.md.j2` previously instructed the scout to
  emit only `topics_from_code` + `intent_from_confluence`, never mentioning
  `topics_found.new`. With `--print`-mode `claude` not auto-loading the scout
  SKILL.md, every cycle aborted at Step 2 with
  `[gates] SG-001: FAIL — topics_found.new is empty`. The template now
  carries a dedicated **Step 4 — Generalize** section, an updated v2 JSON
  schema example including `topics_found`, and explicit `topics_found.new` /
  `coverage_category` / `forbidden_filename_prefixes` constraints that name
  SG-001 / SG-002 / SG-003 verbatim. `_template_version` bumped 1 → 2 so the
  vault migrator (spec 013) offers a re-render to existing vaults.

### Changed

- `dist-templates/scaffold-manifest.json` regenerated against the new
  scout-prompt rendered output (`rendered_sha256` updated;
  `template_version: 2`).

## [private 0.2.18] - 2026-05-16

### Added

- Feature **017 (vault quality fix)**: hybrid **`_pipeline/research-plan.md`** (deterministic body + optional ≤200-word focus rationale) and **`--regenerate-plan-only`** CLI path to refresh it without a full cycle.
- Per-cycle **`cycle-NNN-quality-report.json`** summarizing deterministic **SG-** and **CG-** gates, coverage snapshot, and queryability fields.
- **Batched note-writer** flow with per-batch artifacts **`cycle-NNN-batch-MMM.json`** (`skipped_topics`, gate results, accept/reject).
- **Source preflight** (`scripts/preflight_sources.py`, shared module) and **`_pipeline/preflight.json`**.
- Post-cycle **reindex**: populated **`_index.md`**, **`_concepts.md`**, **`_graph.md`** inside **`data_vault/`**.
- Scaffold **`data_vault/_templates/`** (one template per note type) for `check_template_compliance.py`.
- Optional vault spec field **`forbidden_filename_prefixes`** for runtime abstraction gates (no hardcoded service prefixes in framework code).

### Changed

- Scout / note-writer prompts receive the shared research plan; note-writer consumes orchestrator-supplied **`batch_topics`** instead of self-selecting from an unbounded topic list.
