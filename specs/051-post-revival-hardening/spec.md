---
spec_number: 051
title: Post-Revival Hardening — yield scaling, source preflight, venv-staleness, regression locks
status: SHIPPED 0.8.0 (2026-06-02, PR #91, squash 773bdf7)
target_version: 0.7.1 (locked at /speckit.plan 2026-06-02; 0.7.2 carries the FR1 empirical re-tune)
created: 2026-06-01
source_input: |
  REVIVAL-NOTES.md (~/Documents/feeds-vault/REVIVAL-NOTES.md) — 10 lessons captured
  during the 2026-06-01 feeds-vault revival session. ~5 of those 10 fit a single
  small-ish follow-up spec; the others are out-of-scope here and either
  shipped already (B.4 / 0.7.0), are deferred to their own spec (#6 scout-tier
  preflight), or live in an existing spec (#10 → spec 022).
---

**Status:** shipped(2026-06-02, PR #91) — SHIPPED **0.8.0** (2026-06-02, PR #91, squash `773bdf7`) — all 5 user
stories (US1–US5, FR1–FR5) + Phase-8 polish. Verified: fast loop 1866 passed +
`build.sh --quality` (0 regressions, 3/3 fixtures); Copilot review (4 findings)
addressed. Shipped as a **MINOR** (0.7.0 → 0.8.0) per SemVer — new CLI flag, new
config keys, and the now-required `manifest.preflight` contract change. (T046
scaffold-manifest regen folds into the release-time regen; a future re-tune of
the FR1 defaults uses the `yield-calibration.json` sidecar telemetry.)

> **⚠️ Supersession notice (2026-06-02):** this spec was drafted from
> `REVIVAL-NOTES.md` recollection. Several FR acceptance bullets name
> files/paths/fixtures that don't exist verbatim in the tree; `plan.md`'s
> Phase-0 research **reconciled each to its real home (decisions D1–D7)**,
> and `tasks.md` implements the *reconciled* versions. Where a bullet below
> has been corrected in place, it carries an inline `(see plan D#)` marker.
> When spec prose and `plan.md`/`data-model.md` disagree, **the plan
> artifacts win** — they reflect the actual code.

# Feature Specification: Post-Revival Hardening

**Feature Branch**: `051-post-revival-hardening`
**Created**: 2026-06-01 (drafted at end of the 2026-05-30 feeds-vault revival session, after spec 050 / Principle X shipped)
**Clarified**: 2026-06-01 (four open questions resolved — see "Clarifications" block below)

## Clarifications (resolved 2026-06-01)

The four open questions on the initial draft have been resolved. Each
decision is propagated into the relevant FR section below; this block
records the resolved state for spec-history purposes (per CLAUDE.md
doc-discipline: clarifications are never lost to subsequent editing).

| Q | Decision | Rationale |
| --- | --- | --- |
| **Q1 — CG-001 yield-model defaults** | **Ship proposed defaults in 0.7.1; add `_pipeline/yield-calibration.json` sidecar; re-tune in 0.7.2 after 3-5 cycles of observed data.** | Progress + measurement. The defaults are intuition-based but we cannot wait for calibration data without blocking the ship. The sidecar makes the tuning evidence-based for the v2 pass. |
| **Q2 — Stub-anchor inbound-link threshold** | **N=5 (settings-overridable).** | The revival's smallest anchor had 20+ inbound links, so 5 is well below the observed floor while still being a meaningful "this stub matters to the graph" signal. Conservative enough to avoid false-positives on weakly-linked stubs. |
| **Q3 — Per-module preflight() optionality** | **MANDATORY. All four shipped Tier-1 modules (youtube, reddit, rss, oreilly) MUST add preflight before 0.7.1 ships.** | Uniform UX matters more than backwards-compat with four still-young modules. A mandatory contract makes the failure modes discoverable and testable across the surface, not piecewise. Adds ~6 hours of work (4 modules × ~90 min each); already absorbed into the FR4 sizing below. |
| **Q4 — FR2 stale-venv rebuild interactivity** | **Prompt user with default=yes-rebuild.** | Good human-UX is the right default; CI / agent runs have `--auto-confirm` flags elsewhere in the shim that should be plumbed through (added as FR2 acceptance criterion). Principle X's `git revert HEAD` rollback means a bad rebuild is one command away. |

All four decisions baked into the FR sections below. No remaining
`/speckit.clarify` items; spec is ready for `/speckit.plan`.

## Why this spec exists

The 2026-05-30 — 2026-06-01 feeds-vault revival put the 0.6.x framework
through its first sustained real-world workout. The session surfaced ten
distinct lessons (captured verbatim in `~/Documents/feeds-vault/REVIVAL-NOTES.md`).
Four of them shipped directly in 0.7.0 as bundled bug fixes:

- **B.2** — `lifecycle.created_at_cycle` is now stamped at note-write time.
- **B.3** — `repo.local_path` auto-bypasses `code_source_url_patterns`.
- **B.4** — `validate_vault.py` resolves path-prefixed `[[Folder/Note]]` wikilinks
  (was REVIVAL-NOTES #3).
- **B.1** — Subprocess timeouts now kill the full process tree
  (was REVIVAL-NOTES #5, originally part of the 0.6.2 fix).

This spec consolidates the **remaining five** that are small enough to bundle
into one focused follow-up spec, ordered by "user-visible pain × engineering
cost":

| ID | Lesson | REVIVAL # | Status entering this spec |
| --- | --- | --- | --- |
| FR1 | CG-001 yield-threshold model is ungrounded and not scalable | #7 | Worked around in 0.6.x with an empirically-chosen `_COLD_START_MAX_YIELD` cap; needs principled, configurable model |
| FR2 | `./vault update` is fragile across venv versions (stale `pyvenv.cfg` silently keeps old bytecode) | #9 | No detection today; user workaround = manually `cp` patched files into site-packages |
| FR3 | Stubs are link anchors first, content second (deletion based on body-length alone strands the graph) | #2 | One-shot grooming script worked but the framework's `pipeline/stubs.py` still has no inbound-link guard |
| FR4 | Each source module has its own URL-shape footguns — ad-hoc per-extractor preflight is brittle | #8 | Per-module first-call error path catches some shapes; no manifest-level contract |
| FR5 | Regression locks for two recent fixes: process-tree termination (#5 / B.1, shipped 0.6.2) and "cycle complete" marker discipline (#4, shipped 0.6.3) | #4 + #5 | Both fixes ship without an explicit regression test; the failure modes will resurface as the source-module surface grows |

> **Headline pain (user wording, 2026-06-01):** "Especially considering how
> far off the number of articles we are." That's FR1 — the yield model
> produced 5–8 notes per cycle when the revived vault could plausibly
> sustain 30+. The other FRs are bundled because they're cheap, related,
> and avoid a future spec-numbering proliferation.

## Out of scope (explicitly)

These are real lessons, but they don't fit "small-ish follow-up" — each
either belongs to an existing spec or needs its own:

- **REVIVAL #1** — Schema-evolution upgrade pass (inline-to-frontmatter URL
  hoist + `./vault repair-citations` verb). Substantial work; touches every
  note in the vault and needs careful idempotency design. **Future spec
  (likely `052-vault-schema-evolution` or absorbed by spec 027 hardening).**
- **REVIVAL #6** — JS-only page pre-flight (HEAD/GET-first-N-bytes probe in
  scout stage). Touches scout architecture, model-router cost story, and
  the source-module manifest. **Future spec (likely `053-scout-tier-preflight`).**
- **REVIVAL #10** — Comprehensive `./vault audit` ergonomics gap (single
  command that produces a full "is this vault healthy?" report).
  **Already owned by spec 022** (E2E quality harness; queued behind 020).
- Schema-version discipline for cross-boundary JSON payloads (sidecar v1.1,
  vault-ask JSON, planned research-result inbox envelope). **Tracked under
  spec 036 cross-project integration**; this spec doesn't touch it.
- `sys.exit()` in CLI business logic (platform-constitution failure #4 —
  research-framework violates it pervasively). **Tactical TODO for a future
  code-quality sweep; not blocking the revival hardening.**

## Functional requirements

### FR1 — Configurable cycle-yield threshold model *(headline)*

**Today.** `pipeline/gates_cycle.py::CG_001_minimum_yield` accepts a flat
"≥3 notes per cycle" minimum, with a hard-coded `_COLD_START_MAX_YIELD`
cap on the first run. The threshold is the same regardless of:

1. How many existing notes the vault has (cold start vs incremental).
2. The `coverage_targets:` scale in the vault's spec.
3. The time elapsed since the last completed cycle.
4. The number of un-covered coverage targets remaining.

**The user-visible symptom** of this rigidity is the headline pain:
on a 200-note vault that hasn't been refreshed in three weeks, the
framework only writes 5–8 notes because the gate is configured for
"daily-cadence cold-start" assumptions.

**Proposed model.**

```yaml
# settings.yaml (new top-level block)
cycle_yield:
  # Multiplicative model: target = base * cadence_factor * coverage_factor
  base_notes_per_cycle: 5          # cold-start single-cycle expectation
  cadence_factor:                  # multiplier by time-since-last-cycle
    daily: 1.0
    weekly: 3.0
    biweekly: 5.0
    monthly: 8.0
  coverage_factor:                 # multiplier by un-covered targets
    coverage_below_50pct: 1.5
    coverage_50_to_80pct: 1.0
    coverage_above_80pct: 0.5
  min_floor: 1                     # never gate below this (Principle VIII override)
  max_ceiling: 50                  # never aim above this (cost guardrail)
```

The CG-001 gate then warns (not fails) below `target * 0.5`, and fails
below `min_floor`. The full model is deterministic from the
`settings.yaml` block + the vault's current state — no env-vars,
no agent-side choices.

Default values: chosen to preserve current behaviour on the `tech-lite`
quality fixture (`tests/fixtures/quality/tech-lite/`, so the existing
quality-harness baseline doesn't move) and to roughly DOUBLE on a 200-note
revival-style vault that's been dormant 3 weeks.

**Acceptance**:

- `tests/pipeline/test_cg001_yield_model.py` covers cold-start, weekly,
  biweekly, monthly, and over-target scenarios using the `tech-lite`
  fixture + a synthetic "dormant 3 weeks" fixture.
- The existing `_COLD_START_MAX_YIELD` cap is removed; behaviour
  flows from the new model.
- **(see plan D3)** The new `cycle_yield:` block ships in the canonical
  seed at the **repo-root `settings.yaml`** (packaged as
  `_data/settings.yaml`, tracked in `dist-templates/scaffold-manifest.json`),
  populated with defaults + a short comment. *(No
  `dist-templates/settings.yaml.template` file exists; that was the spec's
  approximation for the seed file.)*
- **(see plan D2)** The yield diagnostic (computed target, the multipliers
  that produced it, and the actual yield) is recorded in the CG-001 gate
  entry of `_pipeline/cycles/cycle-NNN-quality-report.json` — the canonical
  per-cycle artifact. *(There is no `cycle-NNN-report.md`; that was the
  spec's approximation.)* Makes the gate auditable.
- **(Q1 clarification, 2026-06-01; fields aligned to schema, see plan D2/I4)**
  A `_pipeline/yield-calibration.json` sidecar is appended to (not
  overwritten) every cycle with `{schema_version: "1.0", cycle: N, ts: ISO,
  base, cadence_bucket, cadence_factor, coverage_bucket, coverage_factor,
  target, actual, exit_status}` (see
  `contracts/yield-calibration.schema.json`; `exit_status` ∈
  {PASS, WARN, FAIL}). This is the empirical record we will re-tune defaults
  against in 0.7.2 once 3-5 cycles exist across the tech-lite fixture +
  feeds-vault. Schema-versioned per the spec-036 cross-project payload
  discipline. **0.7.2 retune is a TODO, not a 0.7.1 deliverable.**

### FR2 — Detect stale venv on `./vault update`

**Today.** When a user re-runs `install.sh` against a vault whose
`.venv` was created against an earlier bundle path (because the bundle
was unpacked to a different temp directory and is now gone), pip
silently keeps the older version cached. `pyvenv.cfg` still points at
the original build path; the venv keeps loading old bytecode; the user
sees "I upgraded to 0.7.0!" while every cycle still runs 0.6.x logic.

**Proposed.**

`./vault update` (and a fresh `install.sh` re-run) MUST:

1. **Read `pyvenv.cfg`** and detect when the `home =` line points at a
   path that no longer exists OR points at a different bundle than the
   one currently invoking the install.
2. On detection: **prompt** the user (default: yes) to rebuild the
   venv from scratch (`rm -rf .venv && python -m venv .venv` +
   re-run pip install).
3. **Post-upgrade sanity check**: after `install.sh` returns,
   load `research_framework` in a one-shot subprocess
   (`python -c "import research_framework; print(...)"`) and
   compare `research_framework.__version__` against what the
   bundle's `pyproject.toml` declared.
4. **Refuse to exit clean** if the versions disagree. Print the
   mismatch, the current `pyvenv.cfg`, and the suggested remediation
   (`rm -rf .venv && ./install.sh`).

Combined with the 0.7.0 spec-050 auto-commit on `./vault update`,
a bad upgrade is now `git revert HEAD` away. With FR2 layered on
top, the upgrade either succeeds end-to-end or refuses to lie.

**Acceptance**:

- `tests/scripts/test_install_venv_staleness.py` covers: clean rebuild,
  stale-detection happy path, sanity-check version-mismatch refusal,
  fresh-venv flow, **and `--auto-confirm` non-interactive flow**.
- `dist-templates/install.sh` gains a `_detect_stale_venv()` helper,
  the post-install sanity check, **and respects `--auto-confirm` for
  unattended runs (CI / agent contexts).** (Q4 clarification, 2026-06-01:
  prompt with yes-default; `--auto-confirm` bypasses the prompt with
  `yes`. Other shim verbs already plumb this; FR2 just re-uses the
  convention.)
- Cross-references: extends QW-6 / spec 027 (vault update hardening),
  bundled here because it's a 30-line bash addition.

### FR3 — Inbound-link-aware stub policy

**Today.** `pipeline/stubs.py` identifies stub notes by body-length
heuristics (Principle VIII fields: `summary` length, empty body,
`status: stub`). Deletion is gated only by those body-side checks.
**The framework currently has no concept of "this stub is a graph
anchor."**

The revival surfaced 29 such notes — `[[Elon Musk]]`, `[[Microsoft]]`,
`[[Constitutional AI]]` etc. — each with 20–70 inbound wikilinks.
Deletion would have stranded a third of the vault's graph.

**Proposed.**

Add an inbound-link-count guard to `pipeline/stubs.py`:

```python
def _classify_stub(path, inbound_links_count: int, body_len: int):
    if body_len > STUB_BODY_LEN_THRESHOLD:
        return "not-a-stub"
    if inbound_links_count >= STUB_ANCHOR_LINK_THRESHOLD:  # default 5 (Q2 2026-06-01)
        return "anchor-stub"   # FLAG, never delete
    return "deletable-stub"
```

The framework MUST default to flag-not-delete for any stub with
**≥5 inbound wikilinks** (Q2 clarification, 2026-06-01: revival data
showed every observed anchor-stub had 20+ inbound links, so 5 is well
below the observed floor while still being a meaningful "this stub
matters to the graph" signal). The threshold is overridable in
`settings.yaml::stubs.anchor_link_threshold` (default 5). Anchor-stubs
get `status: needs-research` (matching the 0.6.x ad-hoc grooming
pattern) and are surfaced in the research-backlog with a deferred-work
annotation. Deletable-stubs continue to be candidates for the
normal stub-removal pass.

**Acceptance**:

- `tests/pipeline/test_stub_classification.py` covers each branch.
- `pipeline/stubs.py` exports a public `classify_stub(...)` taking
  a `StubClassificationContext` dataclass (path, inbound count,
  body length).
- **(see plan D5)** Inbound counts come from a new
  `vault/indexer.py::inbound_link_counts(vault_dir) -> dict[str, int]`
  helper, extracted from the link graph the indexer already computes when
  building `data_vault/_graph.md` / `_concepts.md`. The map is built **once
  per stub-scan pass** (no markdown re-parse, no full re-walk per call).
  *(The spec's `_index/graph.md` path was inaccurate — the real Layer-1
  files live under `data_vault/`.)*

### FR4 — Per-module `preflight()` contract *(MANDATORY)*

**Today.** Each source module (`youtube`, `reddit`, `rss`, `oreilly`)
catches malformed URLs in its first-call error path. The patterns are
inconsistent: `youtube` returns a structured error, `rss` raises and
relies on the bridge's exception handler, `reddit` falls back to a
default subreddit list. None of them surface the misshape to the user
before the first cycle runs.

**Proposed (Q3 clarification, 2026-06-01: MANDATORY contract).**

Extend the source-module manifest contract (spec 020 `manifest.yaml`).
**(see plan C1/D6)** Preflight is an **isolated subprocess** mirroring the
extractor — the manifest declares an `entry_point` script (not an in-process
`callable`):

```yaml
# manifest.yaml (YAML, not JSON)
name: youtube
version: 1.0.0
entry_point: extractor.py
preflight:                          # NEW — REQUIRED (manifest amendment)
  entry_point: preflight.py         # spawned as a subprocess (popen_session + tree-kill)
  timeout_seconds: 30
```

The framework MUST:

1. **Reject any module manifest that lacks a `preflight` block** (or whose
   `preflight.entry_point` file is missing) at module-load time. Spec 020
   manifest schema amendment makes `preflight` a required key, not optional. A
   friendly error message tells the module author to add a `preflight.py` (with
   a sample from the template).
2. **(see plan C1/D6)** **Spawn** the module's preflight subprocess (stdin/stdout
   JSON, like the extractor) once at the top of `./vault refresh-sources` and
   once at cycle start. The framework core never imports vault module code
   in-process; crash/timeout/garbage-stdout map to `fatal_fail` (fail-closed).
3. Pass it the parsed `sources.yaml` block for that module + the vault's
   `_pipeline/sources/<module>/watermarks.json`.
4. Receive back a `PreflightResult` (success / warning / fatal-fail) with
   suggested corrections for malformed entries:
   - `arxiv.org/list/cs.AI` → suggest `rss.arxiv.org/rss/cs.AI`
   - YouTube channel URL with trailing whitespace → strip + retry
   - Duplicated `/feed/feed/` segments → de-dup
5. On `warning`: log + record the corrected URL in the cycle report.
6. On `fatal-fail`: refuse to run the module this cycle (don't abort
   the whole cycle — Principle VIII module-isolation).

**Acceptance**:

- **(see plan I2/C1)** `specs/051-post-revival-hardening/contracts/preflight.contract.md`
  (new file, authored at plan stage) defines the preflight **subprocess
  invocation contract** (stdin/stdout JSON, popen_session + tree-kill) + the
  `PreflightResult` payload, with its JSON schema in
  `contracts/preflight-result.schema.json`. The **manifest schema is amended in
  place** at `specs/020-code-bridge/contracts/manifest.schema.json` to make
  `preflight` REQUIRED — Phase-2 amendment, breaking for any third-party module
  (none exist; the four shipped Tier-1 modules are all in-tree). *(The contract
  lives under 051, not 020 — it is owned by this spec; only the existing 020
  manifest schema is edited in place.)*
- **All four shipped Tier-1 modules (youtube, reddit, rss, oreilly)
  add `preflight.py` before 0.7.1 ships** (Q3 clarification, 2026-06-01).
  Each preflight covers the URL shapes that module has hit in
  production:
  - `youtube/preflight.py` — strip trailing whitespace, validate
    channel-URL shape, detect plain-handle-without-`@` prefix.
  - `reddit/preflight.py` — validate subreddit name format
    (`/r/<name>` or `<name>`), normalize, reject obvious typos.
  - `rss/preflight.py` — detect duplicated `/feed/feed/` segments;
    catch `arxiv.org/list/` → suggest `rss.arxiv.org/rss/`; HEAD
    probe to confirm the feed actually emits XML/Atom.
  - `oreilly/preflight.py` — verify `learning.oreilly.com/search/?q=`
    URL shape; reject the legacy `oreilly.com/api/v2/search` URLs.
- `tests/modules/<name>/test_preflight.py` for each module (4 files,
  ~6-8 tests each).
- The new `src/research_framework/modules/_template/preflight.py` skeleton
  *(see plan D6: a plain in-tree `.py`, not `dist-templates/*.j2` — modules
  are copied by `generator/module_refresh.copy_listed_modules`, not
  Jinja-rendered)* is added so future modules pick the right shape by default
  (returns success unconditionally; ships with `# TODO: add module-
  specific checks here` as the body — see `assistant-framework`'s
  per-domain port skeleton pattern for prior art).

### FR5 — Regression locks for two recent fixes

**Today.** Two production fixes (process-tree termination 0.6.2;
quality-report-only completion marker 0.6.3) ship without an explicit
regression test. Both fix subtle behaviour that future refactors could
silently undo. Both are cheap to lock.

**Proposed.**

> **⚠️ Scope reduced at plan stage (see plan D7, 2026-06-02).** Investigation
> found that **both** headline behaviours are *already* locked by existing
> tests: process-tree kill by
> `tests/pipeline/test_process_tree.py::test_grandchild_dies_when_tree_is_terminated`
> + `tests/scripts/test_agent_call_process_tree.py`, and the completion
> marker by `tests/cli/test_research_resume.py::test_sentinel_cycle_dirs_do_not_count`
> + `...::test_only_a_quality_report_marks_a_cycle_complete`. Re-creating the
> files named below verbatim would **duplicate** existing coverage (a
> testing-strategy anti-pattern). FR5 therefore ships **net-new coverage
> only** — the two genuinely-uncovered slices. Original proposal retained
> below for provenance; the *actual* deliverables are the two bullets under
> "Net-new (what actually ships)".

*Original proposal (superseded by the net-new scope below):*

1. **`tests/scripts/test_subprocess_tree_termination.py`** —
   spawn a Python subprocess that itself spawns another (sleep 60),
   pass it to `_run_subprocess_with_timeout` with timeout=1s,
   assert both PIDs are dead within 5s. Locks `os.setsid` + `os.killpg`
   pattern in `scripts/agent_call.py`,
   `pipeline/source_bridge/extractor.py`, and
   `pipeline/_cycle_helpers.py`.

2. **`tests/cli/test_resume_completion_marker.py`** —
   construct a `_pipeline/cycles/` directory with
   `cycle-001-quality-report.json`, `cycle-002-source-signals.json` (no
   quality report), `cycle-999-debug-stuff.json`. Call
   `_highest_completed_cycle`, assert it returns 1 (not 2, not 999).

**Net-new (what actually ships — see plan D7):**

1. **`tests/pipeline/test_cycle_helpers_tree_kill.py`** — the one tree-kill
   call site *without* a dedicated real-grandchild regression test:
   `pipeline/_cycle_helpers.py::_run_script`'s cleanup-on-interrupt path.
   (agent_call and process_tree already have grandchild tests.)

2. **`tests/cli/test_resume_completion_marker.py`** —
   `_highest_completed_cycle` `_QUALITY_REPORT_RX` **edge cases** the
   existing tests don't probe: `cycle-000-…` (zero), `cycle-01-…`
   (non-zero-padded width), `cycle-007-…quality-report.JSON` (upper-case
   suffix must NOT match), and a very large cycle number. (The
   sentinel-dir / quality-report-only behaviour is already locked by
   `test_research_resume.py`.)

**Acceptance**:

- Both net-new tests in `tests/` and green.
- One-line comment in each test pointing back to spec 051 and the
  REVIVAL-NOTES item that motivated it (#5 / 0.6.2 and #4 / 0.6.3).

## Cross-cutting notes

### Relationship to spec 036 (assistant-framework integration)

The 2026-05-27 thread between the two project agents (recorded at
`~/src/assistant-framework/docs/TODO.md`) settled the v1 cross-project
contract: `./vault ask --format json` + a `research.result` inbox
envelope to `~/.assistant/inbox/`. **Both deliverables are tracked
under spec 036** — this spec does NOT touch them. The
`schema_version: "1.0"` top-level field agreed in that thread is the
contract discipline this spec follows for its own new payloads
(`PreflightResult`, `cycle_yield` diagnostic block in the cycle report,
the rebuilt `pyvenv.cfg` check output).

### Relationship to platform-constitution failure record

Platform-constitution failures #2 ("AI model wired directly into 30+
modules") and #4 ("`sys.exit()` in command functions") are real
research-framework hygiene gaps, but they're not in scope here:

- #2 is addressed (different language, same principle) by spec 047
  (backend-agnostic agent layer) when it gets sequenced.
- #4 is a 30-site refactor across `src/research_framework/cli/`; gets
  its own future code-quality sweep, not bundled in a "small-ish
  follow-up."

### Sizing

| FR | Effort | Files touched | Risk |
| --- | --- | --- | --- |
| FR1 | ~1 day | `pipeline/coverage.py` (model) + `pipeline/gates_cycle.py` (gate split) + `pipeline/settings.py` + `pipeline/quality_report.py` (diagnostic + sidecar) + 1 new test file + root `settings.yaml` (+ scaffold-manifest sha) — *(see plan D1/D2/D3)* | LOW (configuration-driven; defaults preserve current behaviour) |
| FR2 | ~0.5 day | `dist-templates/install.sh` + `templates/vault-script.sh.j2` (update verb) + 1 test file + `--auto-confirm` alias of existing `--non-interactive` *(see plan D4)* | LOW-MED (bash is fragile; cross-platform path handling) |
| FR3 | ~0.5 day | `pipeline/stubs.py` + `vault/indexer.py` (inbound-count helper) + `pipeline/settings.py` + 1 test file *(see plan D5)* | LOW |
| FR4 | **~1.5 day** *(was ~1 day before Q3 clarification → mandatory contract)* | spec-020 `manifest.schema.json` amendment (in place) + `051/contracts/preflight.contract.md` + **4 module preflight files (REQUIRED, not optional) + 4 test files** + `src/research_framework/modules/_template/preflight.py` skeleton *(see plan D6: in-tree `.py`, not `dist-templates/*.j2`)* | MED (manifest schema change is technically breaking, but no third-party modules exist; the four in-tree modules are all maintained by us) |
| FR5 | ~0.25 day | 2 narrowly-scoped test files | LOW |
| **Total** | **~3.75 days** *(was ~3.25 before Q3 clarification)* | ~16 files | LOW-MED overall |

Small-ish at ~4 days of focused work. Target ship: **0.7.1** (firm —
Q3's mandatory preflight contract justifies a single small minor;
no need to split across 0.7.1 + 0.7.2).

**0.7.2 follow-up (deferred TODO, captured here)**: re-tune the FR1
yield-model defaults using 3-5 cycles of `_pipeline/yield-calibration.json`
sidecar data from the reference-vault + feeds-vault. Empirical re-calibration
of the cadence/coverage multipliers; ~0.25 day; ships in a patch
release.

Final version decision lockable in `/speckit.plan`.

## Open questions (for `/speckit.clarify`)

All four open questions on the original draft were resolved on
2026-06-01. See the **Clarifications (resolved 2026-06-01)** block
near the top of this spec for the decision record. No remaining open
questions; spec is ready for `/speckit.plan`.

---

## Provenance

This spec consolidates lessons from a single revival session:

- **Primary source**: `~/Documents/feeds-vault/REVIVAL-NOTES.md` (10 items,
  authored 2026-06-01).
- **Secondary input**: 2026-05-30 audit of `~/Documents/feeds-vault`
  + `~/Documents/reference-vault` post-cycle quality.
- **Cross-references**: spec 050 (Principle X / vault auto-commit,
  shipped 0.7.0), spec 022 (E2E quality harness, queued behind 020),
  spec 027 (`./vault update` hardening, drafted), spec 036
  (assistant-framework cross-project contract, drafted).
- **Constitution**: no amendment required (this is a tactical hardening
  spec, no new principles).

Next steps: ~~`/speckit.clarify` to resolve the four open questions~~
(DONE 2026-06-01 — see Clarifications block); next is **`/speckit.plan`**
to lock the design + sequence FR1–FR5. Target ship: **0.7.1**.
