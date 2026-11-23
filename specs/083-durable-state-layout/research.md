# Research: the `_pipeline/` inventory (083)

Issue #10 step 1: classify every file written under a vault's `_pipeline/`
as durable or regenerable, with the writer that produces it. Grounded in
(a) a grep of every `_pipeline` path literal and every `pipeline_dir /` join
in `src/`, `scripts/`, `templates/` and `dist-templates/` at `bc39eae`, and
(b) a read-only listing of one live vault's `_pipeline/`
(`danish-working-life`, 40 cycles, last run 2026-10-04, installed from the
private 1.2.0 line).

## The classes

Two classes are what the issue asks for; five are what the code has. The
extra three are kinds of "regenerable" that behave differently when lost,
and the spec needs to say which loss is acceptable.

| Class | Meaning | Tracked? | Loss on `git clean -fdx` |
| --- | --- | --- | --- |
| **S — state** | A later command reads it and behaves differently without it, **and** it cannot be recomputed from tracked inputs without spending again (agent calls, network side effects) or without the operator's own input. | yes, under `_pipeline/state/` | must not happen |
| **R — record** | History of what happened: logs, receipts, reports, per-cycle artefacts. Read only by observational surfaces (status, digest, reports, cost estimates). | no | accepted: reporting is poorer, behaviour is the same (but see "Behaviour derived from records") |
| **C — cache** | Recomputable from tracked inputs, the network, or both, by a command that already exists. | no | accepted: the next run rebuilds it |
| **K — run control** | Live state of one in-flight or paused run. Meaningful until that run ends. | no | accepted: the paused run cannot resume where it stopped and starts again |
| **I — install provenance** | Written by install, scaffold or update to describe what they wrote. | no | accepted: `git clean -fdx` already deletes the shim, `scripts/` and `.venv/` (the root `.gitignore` is `/*`), so a reinstall is required anyway and rewrites these |

## Inventory

`NNN` is a three-digit cycle number; `<m>` a source-module name. "Tracked
today" is what the shipped `.gitignore` (`_render_vault_gitignore`,
`generator/scaffold.py:96`) does.

### S — state (8 artefacts; 2 tracked today)

| Path under `_pipeline/` | Writer(s) | Reader whose behaviour depends on it | Tracked today |
| --- | --- | --- | --- |
| `research-backlog.md` (converted by `084` to `state/research-backlog.json`; the `.md` becomes an ignored view) | `pipeline/orchestrator.py`, `pipeline/research_plan.py`, `scripts/topic_harvest.py`, `scripts/topic_propose.py`, `cli/regrade.py`; the operator by hand | loop continuation (constitution § loop continuation), `research_plan` priority queue, scout prompt | **yes** |
| `coverage-targets.json` | `generator/scaffold.py` (seed from spec), `pipeline/coverage.py::save_targets`, `scripts/topic_harvest.py` (promotes backlog topics to new categories), `coverage.merge_expected_filenames_from_scan` | preconditions, loop termination, `research_plan`, quality metrics | **yes** |
| `propose-rejects.md` | `scripts/topic_propose.py::_append_persistent_rejects`; the operator ("delete a line to let the topic be considered again") | `orchestrator._load_propose_rejects` → scout `exclude_topics` | no |
| `sources.db` | `pipeline/source_manager.py` (`seed`, `append_discovered`, `record_cycle`) | `merge_into_prompt_context` (discovered sources reach the prompt), decay/archival of unlocked sources | no |
| `quarantine/*.md` | `orchestrator._quarantine_orphan_note`, `_quarantine_out_of_scope_notes` (notes moved out of the corpus) | `./vault re-grade` (`cli/regrade.py`) reinstates from here | no |
| `sources/<m>/facts-schema.json` | `source_bridge/schema_gen.py` (agent-generated); `schema_gen.acknowledge_drift` merges an operator-accepted regeneration (its CLI is the orphan `077` T006 names) | drift detection baseline for every later extraction | no |
| `archive-snapshots.json` | `scripts/vault_health.py::run_archive_snapshot_pass` (POSTs each source URL to archive.org) | the same pass skips URLs already `archived` / `unarchivable` | no |
| `approval-decisions.json` | `pipeline/budget_guard.py::record_approval_decision` (operator's `--approve` / `--reject`) | cycle report `approval_gates_fired`; the only record of a human decision | no |

### Behaviour derived from records

Three cross-cycle facts that change what a later run does are not stored
anywhere: they are recomputed each time by scanning `cycles/`, which is
ignored.

| Fact | Derived by | From | Consequence of losing `cycles/` |
| --- | --- | --- | --- |
| Next cycle number | `cli/research_resume.py::_resolve_resume_cycle` | `max(cycle-NNN on disk) + 1` | numbering restarts at 1 while `coverage-targets.json::cycle_number`, `sources.db::source_cycles` and note provenance still say 40 |
| Lifetime spend (`--max-usd`, #239) | `orchestrator._cumulative_sidecar_cost` | every `cycles/cycle-NNN/agent-calls/*.json` | the lifetime cap resets to $0 — a vault that has spent its ceiling may spend it again |
| Hours since the last cycle (CG-001 yield cadence, spec 051) | `coverage._hours_since_last_cycle` | `cycles/cycle-NNN-research.json::timestamp` | the cadence bucket falls back to its default |

These are the reason `git clean -fdx` loses something a later run depends
on even when every **file** above is tracked. The spec's open decision
D-1 is how to store them.

### R — record (ignored)

| Path | Writer | Observational reader |
| --- | --- | --- |
| `cycles/cycle-NNN-*.{json,md,log}` (scout, research, verifier, harvest, propose, postprocess, timings, step-gates, retry-state, probe-results, pre/post-metrics, quality-report, batch, summary, report, research-plan, `*-prompt.rendered.md`, `*.validation.json`) | orchestrator + `pipeline/steps/*`, `observability/cycle_log.py` | status, digest, reports, quality report — and the three facts above |
| `cycles/cycle-NNN/{cycle.log,bridge.log,agent-calls/*.json}` | `observability/cycle_log.py`, `source_bridge/agent_logging.py`, the dispatcher (spec 028 sidecars) | cost estimator p95, status — and lifetime spend above |
| `cycle-NNN-skill-check.json` (at `_pipeline/` root, not under `cycles/`) | `pipeline/cycle_runner.py` | `cycle_summary.py` |
| `runs/<run_id>/` (`run.json`, `run-report.md`, `logs/`, `prompts/`, `agent-calls/`, `verify-report.json`) | `pipeline/run_receipt.py`, `pipeline/runner.py` (spec 080) | `pipeline status` |
| `logs/` (`research-<ts>.log`; pre-080 `<stage>-<ts>.log`, `verify-<ts>.json`) | `processors/_common.py`, the runner before 080 | — |
| `run-report.{md,json}` | `pipeline/run_report.py` (cycle orchestrator) | `cli/acceptance.py`, status |
| `budget-log.md` | `generator/scaffold.py` (header), `orchestrator._append_budget_log` | reporter; **`preconditions.py` refuses a run when it is missing** (precondition 4) |
| `phase1-report.md` | `pipeline/reporter.py` | — |
| `audit-report.md` | `scripts/vault_audit.py`, `pipeline/reports/layer1.py` | — |
| `health-report.md` | `scripts/vault_health.py` | — |
| `narrator-incidents.md` | `pipeline/plan_narrator.py` | — |
| `source-incidents.md` | `source_manager._append_incident_line`, `scripts/source_ledger.py` | quality report `degraded_sources`, digest, cycle summary |
| `source-ledger-run.md` | `scripts/source_ledger.py` | — |
| `yield-calibration.json` | `pipeline/quality_report.py` (append, spec 051 FR1 "auditable") | — |
| `commit-failures-<label>.json` | `pipeline/vault_commit.py` (Principle X) | — |
| `exports/weekly-*.md` | the report agent | `run_receipt` (`latest_export`) |
| `acceptance/report-<date>.*` | `cli/acceptance.py` | — |
| `benchmarks/<run-id>/` | `benchmark/reporter.py` (fixture vaults) | — |
| `corrections/applied/` | `_helpers/scout_correction.py` | — |

### C — cache (ignored)

| Path | Writer | Rebuilt by |
| --- | --- | --- |
| `spec-parse.json` | `generator/scaffold.py`, `onboard.py` | re-parse of `research.spec.md` (#9 adds `spec_sha256` / `parser_version` to make staleness detectable) |
| `research-plan.md` | `pipeline/research_plan.py` via orchestrator | next cycle (rewritten every cycle) |
| `vault-metrics.json` | `pipeline/steps/postprocess.py` | next postprocess |
| `digests/digest-<a>--<b>.md` | `pipeline/digest/` (deterministic) | `./vault digest` |
| `prompts/{scout,dfs}-prompt.md` | `generator/templates.py` (manifest: framework-owned) | re-render |
| `raw/<kind>/*.md`, `archive/<YYYY-MM>/<kind>/*.md` | collectors (`collectors/_dedupe.py`), `processors/archive.py` | `./vault refresh-sources` (re-collect) |
| `extracted/` (`context-tree.md`, `excerpts/`) | `processors/` | extract phase |
| `sources/<m>/{watermarks.json,signals/,consensus/}` | `source_bridge/cache.py`, `preflight_runner.py` | re-extraction (ADR-0006: cached infrastructure) |
| `sources/<m>/facts-schema.{regenerated.json,drift.md}` | `source_bridge/schema_gen.py` | next drift check (transient until acknowledged) |
| `preflight.json` | `pipeline/preflight.py`, `source_bridge/preflight_runner.py` | next preflight |
| `probe-cache.json` | `_helpers/_probe_staging.py` | next probe |
| `repo-scan.json` | `scripts/repo_scan.py` | re-scan |
| `broken-links.md` | `scripts/vault_health.py` | next health |

### K — run control (ignored)

| Path | Writer | Meaning |
| --- | --- | --- |
| `pipeline-state.json` | `pipeline/runner.py` | the weekly runner's `full` → `resume` → `finish` state (spec 075) |
| `state.json` | `pipeline/cycle_state.py` | in-progress cycle, stage, budget snapshot (spec 048 v1.1) |
| `BUDGET_PAUSED`, `APPROVAL_REQUIRED` | `pipeline/budget_guard.py` | a paused run and the stage it resumes at (spec 033) |
| `corrections/cycle-NNN[-batch-NNN].json` | `pipeline/correction.py` | a gate-failure directive for the next prompt, with `expires_after_cycle` (ADR-0003) |
| `scout-report.json`, `research-report.json` | runner phases (agent output) | input to the next phase of the same run |

### I — install provenance (ignored)

| Path | Writer |
| --- | --- |
| `.tmpl-versions.json`, `systemd/.tmpl-versions.json` | `generator/scaffold.py` |
| `systemd/vault-research.service` | `generator/scaffold.py` |
| `scaffold-manifest-snapshot.json` | `scaffold.write_scaffold_manifest_snapshot` |
| `install_summary.json` | `dist-templates/install.sh` |
| `shim-fingerprint.json` | `cli/regenerate_shim.py` |

## Findings beyond the issue's statement

1. **The finding is confirmed and understated.** The allow-list tracks 2 of
   the 8 state artefacts. The other six — including notes in quarantine,
   the discovered-source ledger and the operator's own topic rejections —
   are deleted by `git clean -fdx` today and have never had history.
2. **Three behaviours read records** (table above). Tracking files alone
   cannot meet the definition of done.
3. **`.gitignore` is never rewritten after scaffold.**
   `scaffold()` writes it only `if not gitignore.exists()`;
   `apply_vault_scaffold_update` has no caller; `./vault update` re-runs
   `install.sh`, whose installed-vault fast path writes `install_summary.json`
   and exits. There is no update step today that could deliver a new
   ignore rule — the migration has to bring its own.
4. **`./vault update` on an existing vault runs the vault's own (old) shim.**
   That shim calls `vault_update.sync_vault_scripts` from the freshly
   installed package and then `scripts/vault_health.py` from the freshly
   synced scripts, and finishes with a `framework:` auto-commit. A
   migration reached from either of those runs on vaults whose shim
   predates it; one added only to the shim template does not until the
   shim is regenerated.
5. **`./vault update` short-circuits when the version is unchanged**
   (`vault_update.decide` → `noop`), so a vault whose package was upgraded
   another way is never migrated by it. A standalone entry point is needed.
6. **Readers with no writer.** `rejects.json` is read by
   `research_plan.py` and `reports/flagged_issues.py` and written by
   nothing in the tree. `_pipeline/settings.yaml` is an operator-authored
   legacy override read by `source_manager._decay_threshold` ("holdout …
   until a follow-up unifies paths"); it is ignored today, so `git clean`
   deletes operator configuration.
7. **Stale path claims.** Spec 050 puts `run-commit-state.json` in
   `_pipeline/`; the code keeps it under `.git/` deliberately
   (`vault_commit.py` § Sidecar state). `.migration-plan.json` and
   `.migration-log.md` are named by `cli_inventory.py` and
   `pipeline/vault_git.py`, but the spec-013 migrator that wrote them was
   retired in private 0.2.33.
8. **The scaffold manifest names five `_pipeline/` paths** as user-owned
   (`scripts/build_scaffold_manifest.py::_USER_OWNED_PATTERNS`;
   `dist-templates/scaffold-manifest.json`), and `scripts/vault_health.py::
   CONTROL_FILE_PATHS` names two; both move with the files.
9. **The constitution names `_pipeline/research-backlog.md`** in its loop
   continuation rules; a path change is a PATCH amendment at ship time.
10. **`begin_run`'s dirty check masks all of `_pipeline/`**
    (`vault_commit._PORCELAIN_IGNORED_PREFIXES`). An operator's uncommitted
    edit to a tracked state file is therefore folded into the research
    branch's first cycle commit. True today for the backlog; true for every
    state file once they are tracked.
11. **Outside `_pipeline/`, same shape, out of scope.** The root rule `/*`
    also ignores `modules/` (operator drop-in source modules, spec 020),
    `_templates/` and `.claude/commands/*.md` — all user-owned per the
    scaffold manifest. Recorded here so the next spec does not have to
    rediscover it.

## On the live vault

Every file under `danish-working-life/_pipeline/` maps to a writer above;
no orphan was found. What the listing adds:

- The root of `_pipeline/` holds 40 `cycle-NNN-skill-check.json` files —
  the one per-cycle artefact written beside `cycles/` instead of in it.
- `research-prompt.rendered.md` at the root is the pre-080 runner's flat
  prompt (`runner.py:707` fallback); no `runs/` exists because the vault's
  last weekly run predates 080.
- `sources.db` sits beside `sources.db-wal` (0 bytes) and `sources.db-shm`
  (33 kB): the database runs in WAL mode (`source_manager._connect`), so a
  tracked database needs its WAL checkpointed before it is staged and the
  two sidecars must stay ignored.
- Sizes that bound the cost of tracking: `sources.db` 45 kB,
  `research-backlog.md` 75 kB, `coverage-targets.json` 8 kB after 40
  cycles. `cycles/` holds 1 435 files; tracking it instead of a ledger
  would add ~35 files per cycle.
