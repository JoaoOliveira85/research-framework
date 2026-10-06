# Phase 0 Research — Post-Revival Hardening (spec 051)

This document resolves every unknown the spec implied and — more importantly —
reconciles the spec's prose against the **actual current code**. The spec was
drafted from `REVIVAL-NOTES.md` recollection and names several files/symbols
that don't exist verbatim. Each decision below retargets the work to its real
home so `/speckit.tasks` and the implementer act on reality, not on the spec's
approximations.

Every decision is grounded in a code citation gathered during planning.

---

## D1 — FR1: the yield model lives in `coverage.py`, not `gates_cycle.py`

**Spec said:** "`pipeline/gates_cycle.py::CG_001_minimum_yield` accepts a flat
'≥3 notes per cycle' minimum, with a hard-coded `_COLD_START_MAX_YIELD` cap."

**Reality:**
- The gate function is `CG001_min_cycle_yield(vault_dir, report, *, cycle_number, max_cycles)` at `src/research_framework/pipeline/gates_cycle.py:12`.
- It **delegates** threshold computation to `remaining_yield(vault_dir, cycle_number, max_cycles)` in `src/research_framework/pipeline/coverage.py:486`.
- `_COLD_START_MAX_YIELD = 20` (`coverage.py:393`), `_INCREMENTAL_MAX_YIELD = 10` (`coverage.py:404`), and `_staleness_multiplier()` (`coverage.py:413`, the 0.25/0.5/0.75/1.0 staircase added in 0.6.1) all live in `coverage.py`.
- The gate is called once per cycle from `orchestrator.py:334` (via `run_gate(...)`) **and** evaluated again in `quality_report.py:440` when assembling the cycle report.

**Decision:** Implement the multiplicative model **inside `coverage.py`**, replacing the cap+staleness logic in `remaining_yield()`. The function's return shape changes from `int` → a small result object (or `(target:int, breakdown:dict)` tuple) so the gate and the diagnostic can both report the multipliers. `gates_cycle.py` consumes the new shape. Keep `remaining_yield` importable for the existing `test_remaining_yield_scaling.py` (update those tests to the new model — see D-test note below).

**Rationale:** The spec's intent (a configurable, vault-state-aware model) is unchanged; only the file is corrected. Centralizing in `coverage.py` keeps the single source of truth and both call sites (orchestrator + quality_report) consistent.

**Test note:** `tests/pipeline/test_remaining_yield_scaling.py` pins the *old* caps (20/10) and staleness staircase. The new model removes `_COLD_START_MAX_YIELD` per the spec. Those tests will be **migrated** into `test_cg001_yield_model.py` (new) expressing the new `base × cadence × coverage` model with `min_floor`/`max_ceiling`; the old file is deleted or gutted. This is an authorized behaviour change (FR1 explicitly removes the cap).

---

## D2 — FR1: diagnostic surface is the quality-report JSON, not a `cycle-NNN-report.md`

**Spec said:** "A diagnostic line in `_pipeline/cycles/cycle-NNN-report.md` lists the computed target, the multipliers that produced it, and the actual yield."

**Reality:** No `cycle-NNN-report.md` is written anywhere. The canonical
auditable per-cycle artifact is `cycle-NNN-quality-report.json`, atomic-written
by `quality_report.write_report` (`quality_report.py:502`). `reporter.py` writes
a `phase1-report.md` (one-shot, end-of-run), not a per-cycle markdown.

**Decision:** Emit the yield diagnostic into the **quality-report JSON** as a
new optional field (e.g. `cg001_yield := {target, base, cadence_factor,
coverage_factor, actual, exit_status}`), surfaced inside the existing `gates`
block's CG-001 entry. This makes the gate auditable in the artifact that already
gates the cycle. **Do not invent a new markdown file.**

**Rationale:** Matches the spec's auditability goal while respecting the
existing artifact contract (and the 0.6.3 discipline that *only*
`cycle-NNN-quality-report.json` marks a cycle complete — see D7). The same
breakdown is also written to the FR1 sidecar (next paragraph), so two consumers
(human-readable report + machine-readable calibration log) are both served.

**Sidecar:** `_pipeline/yield-calibration.json` is **appended** to (never
overwritten) every cycle, `{cycle, ts, base, cadence_factor, coverage_factor,
target, actual, exit_status, schema_version: "1.0"}`. Written via
`pipeline/atomic_write.write_json` (signature confirmed at `atomic_write.py:68`).
Append semantics = read-modify-write the JSON array atomically. Schema in
`contracts/yield-calibration.schema.json`.

---

## D3 — FR1: settings template is the repo-root `settings.yaml`, not `dist-templates/settings.yaml.template`

**Spec said:** "`settings.yaml.template` (in `dist-templates/`) ships with the new block populated with defaults."

**Reality:** No `dist-templates/settings.yaml.template` exists. The canonical
vault `settings.yaml` is seeded from the **repo-root `settings.yaml`** (packaged
as `research_framework/_data/settings.yaml`, tracked in
`dist-templates/scaffold-manifest.json:280` with `template_version: 1`,
`is_user_owned_after_first_write: true`).

**Decision:** Add the new `cycle_yield:` block (FR1) and `stubs:` block (FR3) to
the repo-root **`settings.yaml`**, with a short explanatory comment each.
Because that file is `template_version`-tracked in `scaffold-manifest.json`, the
template_version + rendered_sha256 must be **bumped** in the manifest as part of
the change (the scaffold-manifest discipline). Confirm via
`pipeline/scaffold_manifest.py` / `generator/scaffold.py` whether a regeneration
step recomputes the sha (it does — `cli_inventory.py` consumes the manifest).

**Rationale:** Targets the real seed file; the `dist-templates/` phrasing in the
spec is simply the wrong directory name for the same artifact.

---

## D4 — FR2: reuse existing `--non-interactive|-y` convention; add `--auto-confirm` as an alias

**Spec said (Q4):** "Prompt user with default=yes-rebuild … `--auto-confirm`
bypasses the prompt with yes. Other shim verbs already plumb this."

**Reality:** `dist-templates/install.sh:83–89` already parses
`--non-interactive|-y` and honours `RV_NONINTERACTIVE`, setting
`NON_INTERACTIVE=1`. There is **no** existing `--auto-confirm` flag anywhere; the
spec's "other shim verbs already plumb this" refers to the *non-interactive*
convention under a different name. The `./vault` shim's `update` verb
(`templates/vault-script.sh.j2:117`) calls `bash install.sh "${VAULT_DIR}"`
without forwarding `"$@"`.

**Decision:**
1. In `install.sh`, the venv-staleness rebuild prompt uses an `ask_yn()`-style
   prompt (pattern at `install.sh:183`) with **default = yes**. When
   `NON_INTERACTIVE=1` (set by `--non-interactive`, `-y`, `--auto-confirm`, or
   `RV_NONINTERACTIVE`), skip the prompt and proceed with yes.
2. Add `--auto-confirm` to the arg-parse `case` as an **alias** that sets
   `NON_INTERACTIVE=1` (satisfies the spec's literal flag name while reusing the
   one boolean the script already has).
3. In `templates/vault-script.sh.j2` `update` verb, forward caller `"$@"` to the
   `install.sh` invocation so `./vault update --auto-confirm` plumbs through.

**Rationale:** One non-interactive boolean, two spellings — avoids a parallel
flag with subtly different semantics. CI/agent runs pass `--auto-confirm` (or
keep using `RV_NONINTERACTIVE`); humans get the yes-default prompt.

**Version-mismatch refusal:** the post-install sanity check (`python -c "import
research_framework; print(research_framework.__version__)"` — `__version__`
wired via `importlib.metadata.version` at `src/research_framework/__init__.py:6`)
compares against the bundle's declared version and exits non-zero on mismatch,
printing the `pyvenv.cfg` and `rm -rf .venv && ./install.sh` remediation. This is
the first code in the repo to read `.venv/pyvenv.cfg` (no prior references).

---

## D5 — FR3: inbound counts come from the indexer's link graph, not a `_graph.md` re-parse

**Spec said:** "The classifier consults the vault's `_index/graph.md` or
`_concepts.md` … for inbound counts — no full re-walk per call."

**Reality:** `vault/indexer.py` *builds* `data_vault/_graph.md` (and
`_concepts.md`, `_index.md`) from every note's `related` frontmatter +
body wikilinks (`rebuild_all` at `indexer.py:93`; rebuilt each cycle via
`orchestrator.py:460` `_rebuild_indexes_best_effort`). But the output is
markdown, and **no loader/parser exists** to read inbound counts back out.

**Decision:** Extract a small, pure helper in `vault/indexer.py` —
`inbound_link_counts(vault_dir) -> dict[str, int]` (note-stem → inbound count) —
factored out of the existing graph-building walk (no behaviour change to
`rebuild_all`; the helper just exposes the count map the indexer already
computes internally). FR3's `classify_stub` consumes this map, built **once per
stub-scan pass** and passed into each `StubClassificationContext`. Do **not**
parse `_graph.md` markdown (brittle) and do **not** re-walk per note.

**Rationale:** Reuses the authoritative graph computation, keeps it O(vault)
once per pass rather than O(vault) per stub, and gives FR3 a typed integer
source instead of a markdown scrape. Aligns with Principle "Layer 1 is a
projection of Layer 2" — we read from the same projection logic, not the
rendered file.

**`StubClassificationContext`** does not exist today (confirmed). New frozen
dataclass in `stubs.py`: `(path: Path, inbound_links_count: int, body_len: int)`.
`classify_stub(ctx, *, body_len_threshold, anchor_link_threshold) -> Literal["not-a-stub","anchor-stub","deletable-stub"]`. Anchor-stubs get
`status: needs-research` (matching the 0.6.x ad-hoc grooming) and are surfaced
in the research-backlog. Threshold default **5** (Q2), overridable via
`settings.yaml::stubs.anchor_link_threshold`.

**Wiring note:** `stubs.py::scan_stubs` (`stubs.py:86`) is the current public
scanner; it only *detects*, it does not delete (no deletion path exists in the
pipeline — `orchestrator.py:517,596` uses stubs only as continuation fuel). FR3
adds the *classifier*; it does not add a deletion verb (out of scope). The
anchor distinction feeds the existing backlog/fuel logic.

---

## D6 — FR4: modules are in-tree YAML; the cycle invocation point is `run_extraction()`

**Spec said:** manifest is `manifest.json`; preflight invoked "at the top of
`./vault refresh-sources` and once at cycle start"; skeleton at
`dist-templates/modules/_template/preflight.py.j2`.

**Reality:**
- Manifests are **`manifest.yaml`** (YAML), parsed by `parse_manifest()` at
  `source_bridge/discovery.py:55`; schema is
  `specs/020-code-bridge/contracts/manifest.schema.json` (current `required`:
  name, version, description, triggers, entry_point, default_value_tier,
  schema_examples). `ModuleManifest` dataclass at `discovery.py:39` has **no**
  `preflight` field.
- The four Tier-1 modules are **in-tree** at
  `src/research_framework/modules/<name>/` (5 files each: manifest.yaml,
  extractor.py, few-shot.md, README.md, sources.yaml.template). They are copied
  into a vault by `generator/module_refresh.copy_listed_modules`
  (`module_refresh.py:18`, "copy only `settings.yaml::modules` entries").
- `./vault refresh-sources` (`cli/refresh_sources.py:127`) currently runs **only
  legacy `scripts/collect_*.py` collectors** — it does *not* drive the 020-style
  modules. The 020 module extraction runs from
  `source_bridge/orchestrator.run_extraction()` (`orchestrator.py:39`), which
  walks manifests (`:57`), loads each module's `sources.yaml`
  (`sources_loader.py:40`) and `watermarks.json` (`cache.py:60`).
- There is **no `dist-templates/modules/`** directory; all four extractors use a
  structured `_error_payload()` return (not exceptions) for bad URLs — youtube
  `extractor.py:213–223`, rss `extractor.py:336–350`, reddit `extractor.py:242–254`,
  oreilly `extractor.py:333–346`.

**Decisions:**
1. **Required-key enforcement** in `parse_manifest()` (`discovery.py:55`): add a
   `preflight` field to `ModuleManifest` and raise `ValueError` (caught by the
   existing `isolated_call` fail-closed path at `discovery.py:90`) when the
   `preflight` block is absent or its `entry_point` file does not exist. Amend
   `manifest.schema.json` to add `preflight` to `required` and define its object
   shape (`entry_point: str` matching `*.py`, `timeout_seconds: int` default 30).
   Update all four in-tree `manifest.yaml` files to declare `preflight`.
2. **Cycle-start invocation:** **spawn** the module's preflight subprocess inside
   `run_extraction()` (`orchestrator.py:~74`, after manifest load + sources +
   watermarks, before the source loop). On `fatal_fail`, skip *that module* this
   cycle (Principle VIII module isolation — do not abort the whole cycle); on
   `warning`, log + record corrected URL in the cycle report.
3. **refresh-sources invocation:** add a module-preflight pass to
   `cli/refresh_sources.py` (today it only runs legacy collectors). This is the
   spec's "top of `./vault refresh-sources`" — implemented as a discrete
   preflight sweep over installed modules' `sources.yaml`, independent of the
   legacy collector loop.
4. **Skeleton home:** since there is no `dist-templates/modules/`, place the
   skeleton at **`src/research_framework/modules/_template/preflight.py`** (plain
   `.py`, not `.j2` — modules are copied, not Jinja-rendered, by
   `copy_listed_modules`). It is a subprocess script (a `main()` that emits a
   `success` `PreflightResult` JSON, with a `# TODO: add module-specific checks
   here` body). `_template/` is a reference dir, not a shipped module (not listed
   in any vault's `settings.yaml::modules`).
5. **Preflight runs as an ISOLATED SUBPROCESS** (decided 2026-06-02 with the
   user; supersedes the initial in-process draft of this decision). It mirrors
   the extractor contract exactly: the bridge spawns
   `popen_session([sys.executable, <module>/preflight.py, "preflight"])`, writes
   a `{schema_version, sources, watermarks}` JSON request to stdin, reads a
   `PreflightResult` JSON from stdout, and enforces `timeout_seconds` via
   `terminate_process_tree` (the same machinery FR5 regression-locks).
   **Rationale (user):** modules must be as isolated as possible from core code
   so they stay hot-swappable; the framework core must never import vault-local
   module code at runtime. **This also dissolves the in-process import-safety
   question (former finding U1):** there is no import, only a spawn —
   crash/timeout/garbage-stdout all map to `fatal_fail` (fail-closed). Contracts:
   `contracts/preflight.contract.md` + `contracts/preflight-result.schema.json`.
   The typed `PreflightResult`/`SourceCorrection` dataclasses live orchestrator-
   side in `source_bridge/preflight_types.py`; module scripts (which can't import
   from `src/`, same as extractors) emit the JSON shape directly.

**Per-module preflight scope (Q3 — all four MANDATORY before 0.7.1):**
- `youtube/preflight.py` — strip trailing whitespace; validate channel-URL
  shape; detect plain-handle-without-`@`.
- `reddit/preflight.py` — validate `/r/<name>` or `<name>`; normalize; reject
  obvious typos.
- `rss/preflight.py` — de-dup `/feed/feed/`; `arxiv.org/list/` →
  `rss.arxiv.org/rss/` suggestion; HEAD probe to confirm XML/Atom
  (stdlib `urllib`, within `timeout_seconds`).
- `oreilly/preflight.py` — verify `learning.oreilly.com/search/?q=`; reject
  legacy `oreilly.com/api/v2/search`.

**Test pattern:** mirror the existing module-contract tests
(`tests/source_bridge/test_youtube_module.py::_run_extractor` etc.) — preflight
tests live under `tests/modules/<name>/test_preflight.py` per the spec. The
**contract** is exercised by invoking the preflight **subprocess** (JSON request
on stdin → `PreflightResult` JSON on stdout), asserting verdicts + suggested
corrections; fine-grained URL-shape logic MAY additionally call the pure
`check()` helper directly (it's the module's own test, not core code importing
module code at runtime — the runtime isolation invariant holds). The
`_FIXTURE`/`_BIN` env-override pattern (`YT_DLP_BIN`, `RSS_FIXTURE`,
`REDDIT_RSS_FIXTURE`) is reused for the rss HEAD
probe (a `RSS_PREFLIGHT_HEAD_FIXTURE`-style override so tests stay hermetic /
offline — Principle V).

---

## D7 — FR5: the two headline regression tests already exist; scope FR5 to net-new only

**Spec said:** add `tests/scripts/test_subprocess_tree_termination.py` (spawn a
process that spawns a child, assert both die) and
`tests/cli/test_resume_completion_marker.py` (assert `_highest_completed_cycle`
ignores sentinel dirs / non-quality-report JSON).

**Reality (this is the most consequential finding):**
- **Process-tree termination is already locked twice:**
  - `tests/pipeline/test_process_tree.py::TestTerminateProcessTree::test_grandchild_dies_when_tree_is_terminated` (`:89–108`) spawns a real Python subprocess that forks a grandchild ticking a sentinel file, calls `terminate_process_tree`, and asserts the sentinel stops growing (grandchild dead).
  - `tests/scripts/test_agent_call_process_tree.py` has a **shell-based** grandchild variant (`:181–201`) plus `TestRunInSessionWithTimeout` (`:220–315`) and an end-to-end `TestRunDispatchUsesTreeKill` (`:322–382`) that spawns a vault executor forking a grandchild and asserts `run()` returns within budget on timeout.
- **Completion-marker discipline is already locked:**
  - `tests/cli/test_research_resume.py::test_sentinel_cycle_dirs_do_not_count` (`:234–274`) creates the exact `cycle-999/source-signals.json` poison artifact + a stray `cycle-007-research.json` and asserts resume resolves to 4, not 1000.
  - `tests/cli/test_research_resume.py::test_only_a_quality_report_marks_a_cycle_complete` (`:277–299`) asserts a cycle with scout+research JSON but no quality report resolves as the resume target (not complete).

So ~90% of FR5's proposed coverage **already ships**. Re-creating the proposed
files verbatim would duplicate existing tests — an anti-pattern.

**Decision:** Scope FR5 to the **genuinely-uncovered slices**, and add a
one-line spec-051 / REVIVAL-NOTES pointer comment to each:
1. **`tests/pipeline/test_cycle_helpers_tree_kill.py` (new)** — the
   `_cycle_helpers._run_script` cleanup-on-interrupt tree-kill path
   (`_cycle_helpers.py:162–216`) is the **one** of the three tree-kill call
   sites *without* a dedicated real-grandchild regression test (agent_call and
   process_tree both have one). Spawn a script-with-grandchild via `_run_script`,
   trigger the timeout/interrupt cleanup, assert both PIDs die.
2. **`tests/cli/test_resume_completion_marker.py` (new)** — `_highest_completed_cycle`
   (`research_resume.py:27`) regex edge cases the existing tests don't probe:
   `cycle-000-quality-report.json` (zero), `cycle-01-quality-report.json`
   (non-zero-padded width), `.JSON` upper-case suffix, and a very large cycle
   number. These lock the `_QUALITY_REPORT_RX` boundary, not the already-tested
   sentinel-dir behaviour.

**Rationale:** Honours FR5's intent (lock the 0.6.2/0.6.3 fixes against future
refactors) while respecting the testing-strategy anti-pattern against duplicate
coverage. Effort drops below the spec's 0.25d estimate; value is preserved
because the net-new tests cover the two real gaps.

**⚠️ Surface to user:** this is a scope reduction relative to the spec's literal
wording. It is strictly a *subset* (avoid duplication), not an expansion, so it
needs no new scope approval — but it is flagged here and in the plan summary so
the spec author can object if they wanted the literal duplicate files for
documentation symmetry.

---

## Cross-cutting decisions

### Schema-version discipline (spec 036 alignment)
Per the spec's cross-cutting note, every new cross-boundary payload carries a
top-level `schema_version`. Applies to: the `yield-calibration.json` sidecar
(`"1.0"`) and both preflight payloads — the request (`{schema_version, sources,
watermarks}`) and the `PreflightResult` response (`contracts/preflight-result.schema.json`),
which now genuinely cross the subprocess boundary (decision D6/C1).

### No constitution amendment
Confirmed: this is a tactical hardening spec. No new principle, no modified
principle. Constitution stays at v1.4.0. (The FR1 gate-semantics change and FR4
manifest required-key are governed by the spec + ADR-0009/spec-020 contracts,
not by the constitution — both fall under "Out of Scope for This Constitution:
the specific validation rules inside each script" / "default values".)

### No new runtime dependencies (Principle V)
Every FR is stdlib + already-declared deps. The FR4 rss HEAD probe uses
`urllib.request` (already imported by the rss/oreilly extractors). Verified: no
`pip install` additions.

---

## Consolidated decision table

| ID | Spec assumption | Reality | Decision |
| --- | --- | --- | --- |
| D1 | model in `gates_cycle.py` | model in `coverage.py::remaining_yield` | Implement multiplicative model in `coverage.py`; gate consumes new shape; migrate `test_remaining_yield_scaling.py` |
| D2 | `cycle-NNN-report.md` | only `cycle-NNN-quality-report.json` exists | Diagnostic into quality-report JSON + sidecar; no new markdown file |
| D3 | `dist-templates/settings.yaml.template` | root `settings.yaml` is the seed (manifest-tracked) | Edit root `settings.yaml`; bump scaffold-manifest version+sha |
| D4 | `--auto-confirm` (new) | existing `--non-interactive\|-y` + `RV_NONINTERACTIVE` | Add `--auto-confirm` as alias of the existing boolean; forward `"$@"` in shim |
| D5 | parse `_graph.md`/`_concepts.md` | indexer builds graph but no reader | Extract `inbound_link_counts()` helper from indexer; build once per pass |
| D6 | `manifest.json`, `dist-templates/modules/_template/*.j2`, refresh-sources drives modules, in-process `check()` | YAML manifests, in-tree modules, refresh-sources runs only legacy collectors, extraction in `run_extraction()` | Required-key (`entry_point`) in `parse_manifest`; **preflight runs as an isolated subprocess** (popen_session + terminate_process_tree, stdin/stdout JSON — mirrors extractor; chosen 2026-06-02 w/ user); invoke at `run_extraction()` + module sweep in refresh-sources; skeleton at `src/research_framework/modules/_template/preflight.py` |
| D7 | two new regression test files | both headline tests already exist | Net-new only: `_cycle_helpers` grandchild path + `_highest_completed_cycle` regex edges |
| C1/U1 | preflight isolation + in-process import safety | spec-020 isolates extractors as subprocesses | **Subprocess preflight (D6)** — resolves C1 (isolation preserved, modules hot-swappable) and dissolves U1 (no import; spawn only, fail-closed) |
