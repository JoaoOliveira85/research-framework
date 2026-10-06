# research-framework Development Guidelines

Auto-generated from all feature plans; hand-corrected 2026-10-06 to the
**v1.0.0** public release. `CHANGELOG.md` is the record of what
shipped and `docs/ROADMAP.md` the record of what comes next; the "Active
Technologies" bullets below are the spec-kit agent-context digest of each
shipped plan and read as a ledger, oldest first. Where this file and a
guarded source disagree (`docs/testing-strategy.md`'s count marker,
`specs/README.md`, `docs/adr/README.md`), the guarded source wins.

## Active Technologies
- Python 3.11+ (per `pyproject.toml`'s `requires-python = ">=3.11"` and constitution Technology Constraints) + existing — `jinja2 ≥ 3.1` (prompt templates), `pyyaml ≥ 6.0` (settings + spec frontmatter), `sqlite3` (stdlib, used by `pipeline/source_manager.py`). **No new runtime dependencies** — Principle V is non-negotiable. (017-vault-quality-fix)
- filesystem under vault root. New artifacts: `_pipeline/research-plan.md`, `_pipeline/cycles/cycle-NNN-quality-report.json`, `_pipeline/cycles/cycle-NNN-batch-NNN.json`, `_pipeline/preflight.json`, `_pipeline/probe-results-NNN.json`. Existing `_pipeline/sources.db` (SQLite) is reused for source preflight history. Existing `coverage-targets.json`, `research-backlog.md`, `cycle-NNN-research.json`, `cycle-NNN-harvest.json` are unchanged in schema (only consumed). (017-vault-quality-fix)
- Python 3.11+ (per constitution Technology Constraints) + existing only — `jinja2 \u2265 3.1`, `pyyaml \u2265 6.0`, `sqlite3`. Subprocess-isolated source modules: bridge spawns module-owned extractors via stdin/stdout JSON contract. **No new runtime dependencies** — Principle V upheld. (020-code-bridge)
- Filesystem under vault root. New artifacts: `<vault>/modules/<name>/{manifest.yaml,sources.yaml,extractor.py}`, `_pipeline/sources/<module>/{facts-schema.json,watermarks.json,signals/,consensus/}`, `_pipeline/cycles/cycle-NNN/agent-calls/`, `_pipeline/sources/<module>/facts-schema.drift.md` (transient). Per-module `sources.yaml` is the new source-enumeration surface (clarified in spec 020 Session 2026-05-26 + plan refresh PR #20). (020-code-bridge)
- Per-call/per-batch JSON sidecars under `<vault>/_pipeline/cycles/cycle-NNN/agent-calls/` — `schema_version: "1.1"` (bumped from spec 025's `"1.0"` to reflect new required fields `agent_kind`, `status`, `cycle`). Legacy flat-path `cycle-{N}-*.cost.json` artifacts retired for new writes. Stdlib + `pyyaml` only. (028-dispatch-telemetry)
- Two new `./vault` verbs: `refresh-sources` (re-runs legacy `collect_*.py` + frozen-allowlist `reddit_rss.py` collectors with `python <script>.py`, no executable-bit filter) and `regenerate-shim` (atomic Jinja2 re-render of `vault` shim with `stock` / `unverified` / `customized` classification). Atomic-write contract for research / postprocess writers. Stdlib + `jinja2` only. (023-flow-separation Phase 1)
- Cost enforcement markers under `_pipeline/`: `BUDGET_PAUSED` (dollar / wall-clock / codex-token caps with `allOf` JSON Schema conditionals per `pause_reason`) and `APPROVAL_REQUIRED` (per-stage manual gate via `settings.yaml::approval_gates: [<stage>, ...]`). Two-tier estimator: stdlib-only p95 history (default) with optional `tiktoken` precision path via `pip install research-framework[budget]`. TTY-vs-headless UX divergence (caps identical, force/approve UX adapts). (033-cost-enforcement)
- `./vault digest` verb (spec 035, 1.0.0rc1) — deterministic cross-cycle markdown roll-up; `pipeline/digest/` package. `./vault status` verb (spec 048 v1.1, 0.10.0) — live cycle progress read-only. Rich vault reports + opt-in PDF via `pip install research-framework[reports]` (`fpdf2` extra; spec 040, 1.0.0rc1); `pipeline/reports/` delivery layers (mirror + SMTP, fail-closed). (035-cross-cycle-digest, 040-vault-reports-delivery)
- `opencode` as the 4th first-class executor via `_RUNTIME_ADAPTERS` in `scripts/agent_call.py` (`_opencode_cmd` + `--dir` vault-scoping branch; spec-052 cursor pattern). Provider-agnostic — `--model provider/model` (Ollama/OpenAI/Anthropic/…); per-call cost class (local ⇒ `runtime`/$0, metered ⇒ `runtime_tokens`/estimated; no schema bump). `settings.opencode.yaml` peer profile + `_data/`/bundle copy; benchmark gains opencode cells + optional `label`. **No new Python dep** — opencode is an operator-installed binary. (064-opencode-executor)
- Credibility-model calibration: shipped `src/research_framework/data/credibility_catalog.yaml` (domain→tier default catalog; `tier_N` alias onto spec-055 `Level`) + additive `settings.yaml::credibility:` vault override + deterministic `./vault re-grade` quarantine-reinstatement verb. `IX-credibility-unresolved` fails open (WARN) on unknown-but-well-formed URLs, FAILs on malformed; catalog-hit grading unchanged. stdlib + `pyyaml`/`urllib.parse` only — **no new runtime dep** (Principle V); no `schema_version` bump. (066-credibility-model-calibration)
- Acronym-wikilink disambiguation: extends the spec-062 acronym path in `pipeline/wikilinks.py` (single-expansion-only auto-link + self-title protection + stale-stub re-eval) + a deterministic FAIL verifier rule (`pipeline/verifier.py::deterministic_wikilink_violations`, mirroring the credibility twin) for "first body wikilink renames own title" + a deterministic idempotent `./vault wikilinks --fix` sweep (`cli/wikilinks.py`, mirrors the `digest` verb). Duplicate map in `scripts/validate_vault.py` kept in sync. stdlib + `pyyaml` only — **no new runtime dep**; no `schema_version` bump. (067-acronym-wikilink-disambiguation)
- Coverage counting correctness: `pipeline/coverage.py` gains `recompute_from_disk(vault_dir)` (walk `data_vault/`, count by frontmatter `coverage_category`, reuse `classify_note_category`, skip `note_type: alias`) replacing the stale per-cycle `notes_created` increment; `met_count` becomes a **derive-on-read** recomputed cache (digest 035 + `./vault status` 048v1.1 read it), so stale vaults self-heal with no migration verb. Frontmatter wins over `NN - Title` dir (WARN). stdlib + `pyyaml` only — **no new runtime dep**; no `schema_version` bump. (068-coverage-counting-correctness)
- Source-relevance + declared-source validation: a declared `data_sources[]` entry is "backed" iff an installed drop-in module's **manifest `triggers[]`** match its locator (reusing the already-shipped `source_bridge/discovery.py::TriggerRegistry`, currently discarded at orchestrator); else it MUST carry the new optional `DataSourceConfig.kind: strategy_hint` or scaffolding/preflight FAILs closed (`spec/validator.py` + `scripts/validate_spec.py` + `pipeline/preconditions.py`). WARN-only stagnant-source signal (≥2 cold cycles, 053-authority-weighted) via `quality_report.degraded_sources` + `./vault status`. Operator-driven migration (no spec rewrite). FR4 relevance-classifier tuning split to a follow-up sub-spec. stdlib + `pyyaml` only — **no new runtime dep**; additive optional field, no `schema_version` bump. (069-source-relevance-tuning)

- Python 3.11+ + Jinja2 + PyYAML; stdlib for everything else
- MCP (GitHub, Atlassian, Slack, M365) consumed at runtime by generated vault agents
- CLI entry point: `research-framework` (package `research_framework`, dispatched via `src/research_framework/cli/` subpackage with `__main__.py`;
  **ruff baseline at zero errors; seven-tier pyramid (ADR-0008)** — run `pytest -m "not e2e"` for current test count)

## Project Structure

```text
src/research_framework/      # package source — pipeline, processors, generator
src/research_framework/cli/  # CLI subpackage (split into install/onboard/scaffold/etc.) — entry point at cli/__main__.py
src/research_framework/pipeline/steps/  # extracted cycle-runner steps (spec 025 B3) — Step01…Step15 modules feed _cycle_helpers
src/research_framework/vault/frontmatter.py  # canonical frontmatter parser (spec 025 B4 — replaces 12+ ad-hoc parsers)
src/research_framework/pipeline/settings.py  # canonical typed settings loader (spec 025 B7)
src/research_framework/pipeline/digest/    # spec 035 cross-cycle digest section builders + render
src/research_framework/pipeline/reports/   # spec 040 audit-report re-render + PDF/mirror/SMTP delivery
src/research_framework/quality/  # spec-022 metric calculators + baseline I/O + regression diff
tests/                       # tiered test suite (run pytest -m "not e2e" for fast loop; tiers 1-7 per ADR-0008)
tests/_helpers/fake_agent.py # fake-agent shim with verifier/narrator/probe handlers (spec 024)
tests/_helpers/llm_dispatch_allowlist.yaml  # MUST stay empty — Principle IV invariant enforced by tier-2 guard
tests/fixtures/quality/      # spec-022 fixtures (tech-lite / source-poor / source-rich) + baselines
specs/                       # spec-kit specs (NNN-name/); specs/README.md is the guarded index, history under specs/_archive/
dist-templates/              # scaffold + install.sh + manifest (shipped to vaults)
templates/                   # Jinja2 templates rendered by the generator
scripts/                     # maintainer + per-vault scripts (collectors, audit, agent_call)
docs/                        # ROADMAP (source of truth for "what next"), TODO,
                             # ADRs, RELEASE, testing-strategy, generated prompts/
scripts/guards/              # run_all.py — the guard battery the pre-commit hook runs
.git-hooks/                  # tracked pre-commit hook (scripts/install-git-hooks.sh wires it)
.specify/                    # spec-kit framework (constitution + templates)
.github/workflows/           # ci.yml, quality.yml, release.yml — `v*` tags + workflow_dispatch ONLY (§ CI budget)
```

## Commands

```bash
pytest -m "not e2e"          # fast local loop (count: docs/testing-strategy.md TL;DR marker)
pytest -m e2e                # tier-5/6 cycle e2e only
pytest                        # full sweep (ADR-0008)
python scripts/guards/run_all.py   # guard battery — what the pre-commit hook runs
ruff check .                  # lint baseline — must stay at zero
ruff format --check .         # format baseline — must stay at zero (separate gate from `check`)
bash build.sh                 # smoke gate + bundle build (ADR-0007)
bash build.sh --quality       # smoke gate + spec-022 quality harness (3 fixtures, regression diff vs baselines)
```

## Code Style

Python 3.11+. Standard conventions; ruff config in `pyproject.toml`. Lint
baseline is zero errors (reset 2026-05-21 in 0.2.33). New code MUST NOT
introduce ruff errors; if an intentional violation is necessary, add a
line-level `# noqa: <CODE>` with a comment explaining why.

**`ruff check` and `ruff format --check` are SEPARATE gates** — passing one
does not imply passing the other. `build.sh` runs both via the lint
baseline step, so a PR that's green locally on `ruff check` but never
ran `ruff format --check` will fail the release workflow. Always run
both before opening a PR. (Lesson learned in Wave 2: 3 of 4 module-port
PRs missed the format gate, requiring a hotfix PR after the 0.6.0
release tag was cut.)

## Testing

Layered **seven-tier pyramid** (feature 018, restructured under ADR-0008
on 2026-05-21). See `docs/testing-strategy.md` for the full rationale,
decision tree, and anti-patterns. Cross-cutting `@pytest.mark.regression`
and `@pytest.mark.acceptance` markers complement the tier scoping.

- The test count is committed in exactly one place — the
  `<!-- test-count: … -->` marker in `docs/testing-strategy.md`'s TL;DR —
  and `tests/docs/test_one_source_per_fact.py` fails the suite when it
  drifts from a live `pytest --collect-only -q` (#281). Tier 5/6 are
  gated by `build.sh` (hard smoke gate, no `--skip-smoke` flag — see
  ADR-0007; ADR-0007's "tier 4+5" wording refers to what ADR-0008
  re-numbers as tier 5+6).
- `pytest -m "not e2e"` for the fast local loop (~6-7 min on a recent Mac).
- `pytest` for the full sweep including e2e (~12 min); `./build.sh`
  runs the gate before building a wheel.
- `./build.sh --quality` runs the gate **plus** the spec-022 quality harness
  (3 fixtures, 3 metric families, regression diff vs committed baselines).
  Required before any release that touches `pipeline/`, `quality/`, or
  fixture vaults.
- When adding any test, follow the tier decision tree in
  `docs/testing-strategy.md` — choose the lowest tier that catches the bug.
- Never monkey-patch `run_cycle_steps`; never call real `claude` / `codex`
  from a test. Both rules are now **statically guarded**, not prose:
  `tests/_helpers/test_llm_dispatch_guard.py` rejects any new direct
  `claude`/`codex` subprocess in `src/research_framework/` (allowlist **empty
  since 0.3.2** — keep it that way), and
  `tests/_helpers/test_cycle_runner_seam_guard.py` rejects any
  `monkeypatch`/`mock.patch` of `run_cycle_steps` anywhere under `tests/`, in
  either the attribute or the dotted spelling (#86, closed in 1.3.0 — the
  2026-05-30 audit's ten sites are zero). When a test needs a stand-in runner,
  pass the **`cycle_runner=` seam** that `orchestrator.run_single_cycle` and
  the quality harness's `run` / `collect_fixture_current` / `_invoke_cycles`
  declare, with a stub from `tests/_helpers/cycle_runner_stub.py`. Otherwise
  use `tests/_helpers/fake_agent.py` and
  `tests/_helpers/vault_factory.build_minimal_vault`.
- **Foreman verification pattern (ADR-0010, 2026-05-27)**: spec
  `tasks.md` files MAY carry `### Testing Requirements` blocks
  authored by the test-design subagent before implementation. The
  deterministic verifier (`scripts/foreman/verify_test_coverage.py`)
  checks that the named tests exist, pass, and (when flagged) obey
  TDD commit-timeline. The Arm B review subagent
  (`.agents/skills/foreman/SKILL.md`) catches semantic issues scripts
  can't (vacuous assertions, mocked-unit-under-test, scope creep).
  Pattern is opt-in per spec — tasks without `Testing Requirements`
  blocks are reported `NO_REQUIREMENTS` and skipped. See
  `docs/foreman.md` for the parser contract.
- **Spec 022 quality harness SHIPPED 0.3.0** (`./build.sh --quality`). The
  0.3.2-surfaced "interception test not in any ship gate" gap is closed:
  `tests/quality/test_fake_agent_interception.py` is in `build.sh::SMOKE_TESTS`,
  and `release.yml` runs `bash build.sh --quality` on every version tag, so a
  Principle-IV regression hard-fails the release build.

## Architecture Decision Records (`docs/adr/`)

Introduced 2026-05-18 as the durable home for cross-cutting
architectural decisions. ADRs are NEVER edited once accepted — to
change a decision, write a new ADR that supersedes the old one.
Read `docs/adr/README.md` for the index and format.

Active ADRs at the time of this update (`docs/adr/README.md` is the
index — trust it over this list):

- `0001` — Adopt ADRs for architectural decisions (the meta-ADR).
- `0002` — Phase-scoped `sources_consulted` validation (0.2.30).
- `0003` — Correction directives must be injected into prompts (0.2.30).
- `0004` — Verifier output parsing must tolerate non-strict JSON (0.2.31).
- `0005` — Wikilink case is normalized at cycle time (0.2.31).
- `0006` — Code access is cached infrastructure (spec-020, SHIPPED 0.4.0 via PR #32).
- `0007` — Smoke gate is mandatory and cannot be skipped (spec-018/019).
- `0008` — Testing pyramid restructure: seven tiers, scope vs purpose
  markers, `live_llm` opt-in, spec acceptance-coverage convention
  (spec 024, 0.3.0).
- `0009` — Collectors vs Modules reconciliation: **Option A**, 020
  supersedes the 014/015 collectors (recorded 2026-05-26; ACCEPTED
  2026-06-01 once the transition criterion was met, no amendment needed).
- `0010` — Foreman verification pattern (2026-05-27, ACCEPTED; pattern
  shipped via PR #29). Three-role testing (test-design subagent →
  implementer subagent → foreman Arm A verifier + Arm B review). Opt-in
  per spec; strict-naming policy; commit-topology TDD check.
- `0011` — Operational run-control config lives in `settings.yaml`, not
  the spec (2026-06-05; spec 061, 1.0.0rc3).
- `0012` — The flat `## Acceptance` bullet format is not guard-enforced
  (2026-09-07; the G/W/T convention lapsed at spec 061).

## Documentation discipline (DO NOT SKIP)

This project's velocity depends on `docs/ROADMAP.md`, `docs/TODO.md`,
`CHANGELOG.md`, and `.specify/memory/constitution.md` staying truthful.
Documentation drift compounds: every stale entry sends the next session
down a wrong path and burns tokens re-discovering reality.

### Doc-sync trigger checklist (run this AT THE END of every PR-merging session)

Whenever a session merges one or more PRs (whether implementation,
clarify, plan, or tasks), the FINAL action before closing the session is
a doc-sync pass. The user should never need to ask "did you remember
to update the docs?" — assume yes by default. The 7-step trigger:

1. **`git pull` on `main`** to pick up the merged squash commits.
2. **Spec status headers** — for every spec whose impl PR merged,
   flip `**Status:** Tasks + analyze complete (...) Ready for /speckit.implement`
   → `**Status:** SHIPPED [Unreleased]/<version> (PR #N, squash <sha>)`
   with a 1-paragraph what-shipped summary.
3. **`CHANGELOG.md [Unreleased]`** — add Added/Changed/Fixed entries
   for every user-visible change. Even doc-only ships get an entry if
   they change a contract or surface. **One `[Unreleased]` block per
   release cycle**; don't pre-create version blocks.
4. **`docs/ROADMAP.md`** — flip the tier row `[ ]` / `[~]` → `[x]`;
   at release time the version gets a shipped-registry row. There is no
   "Completed (recent)" block any more — `CHANGELOG.md` is that record.
5. **`docs/TODO.md`** — **DELETE** entries that the ship resolved
   (CHANGELOG + git history are the durable record). Collapse entries
   whose detail was promoted into a ROADMAP queue item.
6. **`CLAUDE.md` "Recent Changes"** — prepend an entry summarizing the
   ship; prune the bottom of the list to keep last 3-5 ship cycles.
   Add any new ADRs to the "Architecture Decision Records" list.
7. **Commit the doc-sync as a SEPARATE PR** (typical title:
   `docs: post-ship sync for PRs #X/#Y/#Z`). Doc-sync PRs are
   doc-only, don't run smoke gate, merge cleanly.

**Automation reminder**: the rule "ROADMAP has only OPEN + FUTURE
work; CHANGELOG has SHIPPED work; TODO is a scratchpad for un-triaged
ideas" is non-negotiable. If you find shipped work surviving as a
`[ ]` queue entry, you've hit drift — fix it immediately. Same for
TODO entries that describe shipped work.

**Bonus rule (added 2026-05-27 after Wave-1 doc sync)**: per-spec
implementation detail (FR breakdowns, test coverage tables, design
trade-offs) belongs in `specs/NNN-<name>/spec.md`, NOT in
`docs/ROADMAP.md`. ROADMAP's job is sequencing; specs are
documentation. If a ROADMAP queue entry has > 5 lines of
implementation prose, that prose belongs in the spec.

### When to bump `pyproject.toml` (CHECK AFTER EVERY DOC-SYNC PR)

**Nothing auto-fires**: `release.yml` runs on a `v*` tag
push or a `workflow_dispatch`, never on a push to `main`. The bump still
lands on `main` through a `release: X.Y.Z` PR; the annotated tag on that
merge commit is the release. `docs/RELEASE.md` is the procedure and the
only copy of it. After every doc-sync PR, ask:

- Did `[Unreleased]` accumulate content from 2+ PRs since the last
  released version?
- Are any of those changes user-visible (new CLI verbs, new config
  keys, new file layouts, new features, changed run behaviour)?

**If yes**, bump the version per SemVer (concrete examples):

- **PATCH** (e.g. `1.0.0` → `1.0.1`): bugfixes only; no new
  user-visible features. (1.1.1 was PATCH while deleting a shipped
  shell script.)
- **MINOR** (e.g. `1.0.0` → `1.1.0`): new features; backward-compatible
  changes; new CLI verbs; new config keys.
- **MAJOR** (e.g. `1.4.0` → `2.0.0`): breaking changes (removed CLI
  verbs, removed config keys, format-breaking schema changes).

**How to bump**:

1. `pyproject.toml::version`: `X.Y.Z` → new version.
2. `CHANGELOG.md`: rename `## [Unreleased]` → `## [X.Y.Z] - <tag date>`
   (heading date = tag date, `docs/RELEASE.md`); add a fresh empty
   `## [Unreleased]` heading at the top; add `### Migration notes` if
   an existing vault has to do anything.
3. Merge the `release: X.Y.Z` PR, then `git tag -a vX.Y.Z` on the merge
   commit and `git push origin vX.Y.Z`. `release.yml` verifies the tag
   matches `pyproject.toml` and refuses otherwise.
4. **Verify the workflows actually ran** (`gh run list --workflow ci.yml`,
   `quality.yml`, `release.yml`). A tag with no run is not a release
   record; if Actions is billing-blocked, the local gate is the record
   and the Release notes say so.

**Ship the bump as a separate tiny `release: X.Y.Z` PR.** Doc-sync
PRs (`docs: post-ship sync for …`) are conventionally doc-only; a
release PR is a *different* category because it has a deploy effect.
Keeping them separate makes review intent explicit and lets either one
be reverted independently.

**Recovery if the bump was missed** (e.g. 5 feature PRs merged with
`[Unreleased]` content and `pyproject.toml` never moved): open a
standalone `release: X.Y.Z` PR with just the `pyproject.toml` bump +
CHANGELOG heading rename + this rule revisited. Don't try to
retroactively attribute changes to specific PRs — they're all visible
in git history.

> *Added 2026-05-27 after the Wave-1 ship gap: 5 feature PRs (#28-#32)
> merged in a single afternoon without a version bump because nobody
> explicitly checked. 0.4.0 shipped as a recovery release. Re-learned
> 2026-09-08: v1.1.1 merged on 09-07 and sat unreleased for a day
> because the docs still described push-to-main auto-detect — after
> #323, "merged" is not "released"; the tag is.*

### Per-spec-kit-stage doc-update checklist (CRITICAL)

For every spec the project moves through the spec-kit flow, you MUST
update specific docs at specific stages. Do this in the SAME commit
or PR as the stage's primary deliverable — never as a "follow-up".

**After `/speckit.specify` (spec drafted):**
- [ ] **`docs/ROADMAP.md`** — add the spec to the tier it serves (or
      the Deferred table, with a trigger) with a 1-2 line summary. If it
      supersedes an older spec, say so in both — the archive rule needs
      the banners bidirectional.
- [ ] **`docs/TODO.md`** — if any TODO entries motivated this spec,
      annotate them with `*(now spec NNN)*` and a pointer.
- [ ] **`CLAUDE.md`** "Recent Changes" — note `NNN draft (YYYY-MM-DD)`
      with a one-line summary (only for non-trivial specs).
- [ ] **Constitution** — only if the spec proposes principle changes.

**After `/speckit.clarify` (clarifications recorded):**
- [ ] **`docs/ROADMAP.md`** — update the spec's row if scope shifted
      materially. Flip it to `[?]` if blocked on a named decision; flip
      back to `[ ]` once the decision lands.
- [ ] **Constitution** — if a clarification surfaced a principle
      conflict, amend the constitution (bump PATCH).

**After `/speckit.plan` (technical plan locked):**
- [ ] **`docs/ROADMAP.md`** — if the plan revealed a different effort
      estimate, sequencing constraint, or dependency, update the
      entry. Add cross-refs to ADRs the plan produced.
- [ ] **`docs/adr/`** — write any net-new ADRs the plan committed to.

**After `/speckit.tasks` + `/speckit.analyze` (tasks broken down, plan analyzed):**
- [ ] **`docs/ROADMAP.md`** — if `/analyze` found cross-spec conflicts
      or surfaced new follow-ups, capture them under a `[?]` queue
      item or a `*(blocked by X)*` annotation on the affected entries.
- [ ] **`docs/TODO.md`** — file any leftover items `/analyze` flagged
      as out-of-scope but worth keeping (with `*(surfaced YYYY-MM-DD)*`).
**Before `/speckit.implement` (foreman pre-step — ADR-0010):**
- [ ] **Dispatch the test-design subagent** (`.agents/skills/test-designer/SKILL.md`)
      against the spec's `spec.md` + `plan.md` + `tasks.md` + `contracts/`.
      It enriches `tasks.md` in place with `### Testing Requirements`
      blocks per task (strict-naming: exact filenames + function
      names + TDD-discipline flag). The subagent MUST be blind to any
      pre-existing implementation code; run it in a fresh worktree at
      the spec's base ref, on a `test-design/NNN` branch.
- [ ] **Commit the enrichment** atomically (`test-design(NNN): enrich
      tasks.md with foreman testing requirements`) and merge the
      enrichment into the impl branch BEFORE the implementer subagent
      runs. The implementer treats `Testing Requirements` as part of
      the task definition and is NOT told a foreman exists (prevents
      harness-gaming). See `docs/foreman.md` for the parser contract.

**After `/speckit.implement` (foreman post-step — ADR-0010):**
- [ ] **Run the Arm A verifier**:
      ```bash
      python -m scripts.foreman.verify_test_coverage \
        --tasks specs/NNN-<name>/tasks.md \
        --workdir <impl-worktree-path> \
        --base-ref main
      ```
      Exit 0 ⇒ proceed to PR. Exit 1 ⇒ kick implementer with structured
      feedback (DO NOT mention the foreman by name).
- [ ] **Dispatch the Arm B foreman subagent**
      (`.agents/skills/foreman/SKILL.md`) ONLY if Arm A passed. It does
      semantic review (vacuous tests, mocked-UUT, scope creep) the
      script can't catch. Verdict PASS ⇒ open PR. FAIL ⇒ kick with
      `implementer_feedback`.

**After implementation ships + commit lands:**
- [ ] **`spec.md` status header** — set `**Status:** SHIPPED <version>`
      at the top of the spec's `spec.md`. The spec dir is the spec's
      source of truth; don't rely on ROADMAP entries alone.
- [ ] **`docs/ROADMAP.md`** — flip the tier row `[ ]` → `[x]`. The
      shipped-registry row is written at release time, not per PR.
- [ ] **`docs/TODO.md`** — **DELETE** any entry the work resolved
      (CHANGELOG + git history are the durable record).
- [ ] **`CHANGELOG.md`** — every user-visible change (CLI surface,
      file layout, `./vault` verbs, breaking removals, config schema)
      MUST have an entry under the version block being shipped. No
      silent breaking changes. Add a fresh empty `[Unreleased]`
      heading at the top for the next cycle.
- [ ] **`CLAUDE.md`** — "Recent Changes" gets the ship entry (prune
      to last 3-5 ship cycles). Update "Active Technologies",
      "Project Structure", or "Important context locations" if the
      spec touched those.
- [ ] **`README.md`** / **`ARCHITECTURE.md`** — only if the spec
      changed the user-facing or system-level story (new commands,
      new directories, new design patterns).
- [ ] **`.specify/memory/constitution.md`** — only if the spec
      introduced / clarified / removed a principle. PATCH for
      clarifications, MINOR for new principles, MAJOR for
      removals/redefinitions. ALWAYS prepend a Sync Impact Report
      as an HTML comment block.

### General reference (cross-stage)

- **`docs/ROADMAP.md`** is the source of truth for "what comes next".
  Status convention: `[ ]` planned, `[~]` in progress, `[x]` shipped,
  `[?]` blocked on a named decision. An item sits in exactly one tier
  row or one Deferred row — track progress on ONE tickbox and reference
  it from anywhere else.
- **`docs/TODO.md`** holds scratchpad ideas AND implementation details
  for items promoted to a ROADMAP row. Headings of promoted items name
  the spec or the roadmap row. When an item ships, DELETE its entry.
- **No item should appear twice** in ROADMAP (tier vs Deferred). If you
  see the same work described in two places, consolidate or
  cross-reference — never duplicate the content.
- **Spec status headers** (`**Status:** ...`) at the top of every
  `spec.md` are non-negotiable once a spec has been touched.

### Anti-patterns to avoid

- **"Documentation PR later"** — by the time that PR is written,
  the next 3 sessions have already shipped on top of stale
  assumptions. Doc updates ship with the work.
- **"It's just a one-line change, doesn't need a CHANGELOG entry"**
  — if it's user-visible, it does. The bar is "did the
  CLI/file-layout/script-output change?" not "was it a large diff?"
- **"I'll figure out which doc to update later"** — use the
  per-stage checklist above. Each stage has explicit targets.
- **Leaving a `[ ]` queue item that's actually shipped** — every
  agent reading the queue is misled. Flip + move to Completed in
  the same commit as the ship.

### Safety net

The architect agent (`Task` subagent) will catch drift if you forget,
but it's expensive. The fastest path is the checklist above. Run
`rg "research[-_]vault" docs/ specs/ README.md CLAUDE.md
ARCHITECTURE.md CONTRIBUTING.md` (or equivalent) before a release to
catch stale references.

## Important context locations (read on session start if relevant)

- `ARCHITECTURE.md` — system design source of truth (read first).
- `CONTRIBUTING.md` — spec-kit flow, TDD discipline, doc taxonomy.
- `docs/ROADMAP.md` — shipped registry, the v1.3.0 / v1.4.0 tiers and
  the Deferred table. **Source of truth for "what comes next".**
- `docs/TODO.md` — scratchpad. Often empty. Triage to ROADMAP.
- `CHANGELOG.md` — every user-visible change. Read [1.0.0] for the most
  recent shipped scope. `[Unreleased]` is where in-flight work lands.
- `docs/RELEASE.md` — release process (version tags and `workflow_dispatch`
  only; heading date = tag date; the Migration-notes rule;
  what `./vault update` does and does not rewrite).
- `.specify/memory/constitution.md` — project principles (v1.6.0).
  Sync Impact Reports at the top track principle changes.
- `docs/adr/` — architecture decisions (immutable once accepted).
- `examples/detailed-vault-spec.md` — the detailed
  reference spec format. Use as the template for any new
  detailed vault spec; the `vault-spec` skill produces the same form.
- `examples/research.spec.md` (+ `examples/settings.yml`) — the SIMPLE
  (opt-in) spec format. Produces anemic vaults unless filled in.

## Recent Changes

Every shipped change is recorded in `CHANGELOG.md`.

<!-- MANUAL ADDITIONS START -->
### CI budget (2026-09-07)

- **GitHub Actions run on version tags and by hand only.** Never add a `pull_request`, `push` or `schedule` trigger, and never a macOS runner without an explicit opt-in. The merge gate is the local suite (`pytest`, `scripts/guards/run_all.py`, `ruff`); every PR reports its real counts.

<!-- MANUAL ADDITIONS END -->
