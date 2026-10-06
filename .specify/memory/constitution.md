<!--
Sync Impact Report
==================
Version change:    1.5.0 → 1.6.0
Bump rationale:    MINOR — two principles added, one enforcement
                   downgrade, and a re-verification of the Enforcement
                   Register against the tree at private v1.2.0.

                   The downgrade: the Register's "Enforced" status was
                   defined as "runs in the PR gate", and since PR #323
                   (2026-09-07) this repo has no PR gate — `ci.yml` runs
                   on version tags and manual dispatch only. Under the
                   1.5.0 definition no row could be Enforced. The
                   definition is rebound to the LOCAL merge gate that
                   `CONTRIBUTING.md` and `docs/RELEASE.md` name
                   (`scripts/guards/run_all.py`, `pytest -m "not e2e"`,
                   ruff), which `ci.yml` re-runs on a tag. That is a
                   weaker guarantee than "a machine runs it on every
                   PR", so by this document's own §7 rule it is MINOR.

                   Not PATCH: the Register preamble was false in four
                   places (see "Modified sections"), and a false account
                   of what enforces a document is material.

                   Not MAJOR: no principle is removed or redefined.
                   I–XII keep their text. XIII records a defect class
                   the 1.1.0 CHANGELOG named four times and PR #329
                   gave an enforcer; XIV records the owner's standing
                   decision of 2026-09-08.

Modified principles:
  I.   Script-Validated Quality Gates — the gate table gains the rows
       that exist in the tree and were missing from it: the scout step
       gates SG-001..SG-003 and their correction loop; SG-004's
       `duplicate` class, promoted to FAIL by #293; CG-001 with its
       three-attempt retry; and, for the weekly runner (spec 075), the
       phase artifact checks (#222) and the verify verdict (#218, #229).
       The two "silently skipped if absent" rows are re-verified as
       still true (`cli/research_phase3.py:86-88`). The paragraph
       counting blocking gates is rewritten to match.
  Principle text for I–XII is otherwise unchanged.

Added principles:
  XIII. Nothing Is Accepted and Ignored (NON-NEGOTIABLE) — a flag,
        setting key or field the framework accepts MUST reach a
        consumer that changes behaviour, or be refused; a failure the
        framework records MUST be spoken where the operator will see
        it. Derived from failure record entry F10 and from the
        "config accepted and silently ignored" class the CHANGELOG
        names at #232, #251, #271, and spec 074.
  XIV.  A Local or Decentralised Model Option Is Always Supported —
        every model-backed capability keeps a self-hosted provider
        path; degraded is acceptable, absent is a violation; the
        shipped Ollama profile is the proof and ships with every
        release. Owner's decision, 2026-09-08. Its Register row is
        honest about the gap that exists today: `settings.ollama.yaml`
        is in the source tree and is not yet in the wheel or the bundle.

Modified sections:
  - **Enforcement Register**, preamble — rewritten. The 1.5.0 text
    said the PR gate is `ci.yml` and nothing else; that there are no
    git hooks; that `build.sh` executes no guard; and that of twelve
    guard scripts exactly one is executed against this tree. At HEAD:
    `ci.yml` does not run on PRs at all (#323); a TRACKED
    `.git-hooks/pre-commit` runs `scripts/guards/run_all.py` (#315),
    opt-in per clone through `scripts/install-git-hooks.sh`; the
    aggregator runs three guard scripts plus a thirteen-file guard
    test battery; `build.sh`'s smoke gate runs `tests/_helpers/`,
    which includes the static dispatch guard; and the abstraction gates
    SG-003/CG-003 are on by default (#309). The "Enforced" definition
    is rebound as described above.
  - **Enforcement Register**, rows re-verified against the code:
      III — 8 of the 35 Python scripts under `scripts/` take
            `--dry-run` (was "7 of 33"). Still no enforcing artifact.
      IV  — the static guard now fails closed on an empty scan root
            (`test_scan_root_is_not_vacuous`, #278), derives its binary
            set from `scripts/agent_call.py` and sees the HTTP dispatch
            mode (`tests/_helpers/llm_dispatch.py`, #292/#301); the
            runtime guard asserts it observed traffic. The residual
            blind spots are restated: `subprocess.call`/`check_output`,
            `os.system`, and string commands under `shell=True`.
      VI  — mechanism restated after #293/#301: `proposed_filenames`
            is required on a v2 scout report and checked against the
            vault, within the list, and for the `[]` opt-out; SG-004
            maps the `duplicate` class to FAIL.
      X   — twelve test modules (was eight), none `e2e`-marked.
      XI  — **Not met → Partial.** `tests/contracts/` exists (#326) and
            validates seven committed schemas against real writer
            output; the note format has a written form (spec 079), a
            per-note version (`template_version`, FR-006) and a named
            counterparty. No contract has a mirror or a drift guard.
      XII — the verify phase now writes its report to
            `_pipeline/logs/verify-<ts>.json` (#218) — outside the
            corpus it grades, which is the distinction XII draws. The
            FAIL path is pinned (#229). Still no byte-identity test for
            `preprocess`, `extract`, `archive`, `cli/audit.py` or
            `scripts/fix_*.py`.
    Rows XIII and XIV added. Count: **2 Enforced, 9 Partial, 3
    Review-time only, 0 Not met** (was 2 / 6 / 3 / 1).
  - **Cross-Repo Obligations** — the vault note format row: Versioned
    "No" → "Yes, per note" (`template_version`, spec 079 FR-006, since
    PR #327); authoritative form now names spec 079; status
    Non-compliant → Partial. The consumer (`consumer_pipeline/pipeline/
    vault_import.py`) reads `type`, `title`, `summary` and
    `source_urls` and no version field, and `consumer_pipeline`'s own
    register (its constitution §5, C1–C4) has no row for this payload
    — so the mirror half is still unmet, and this amendment says so
    rather than crediting the version field as compliance. Per
    Governance rule 5: the sibling repo's copy did not change.
  - **Boundary System** — one Always Do entry (run the parser-flag
    guard when adding a flag) and two Never Do entries (XIII, XIV).
  - **Technology Constraints** — the agent runtime list is corrected
    from "`claude` / `codex`" to the five spec 078 names (FR-006,
    FR-007), with the self-hosted requirement from XIV; "formatted
    with `black`" → `ruff format` (black-compatible, 88 chars), which
    is what `ci.yml`, `build.sh` and `docs/RELEASE.md` actually run.
  - **Failure Record Reference** — F10 added: the 2026-09-01 run's
    other half. F9 is why seven of eight vaults failed verify; F10 is
    why nobody could read the failure. The intro now says F9 and F10
    occurred in research-framework itself.
  - **Out of Scope for This Constitution** — the table now names the
    trunk specs written by #328 as authorities: 077 (verbs, flags,
    exit codes), 076 (run-control settings, with ADR-0011), 079
    (frontmatter and note types), 078 (LLM dispatch), 075 (the weekly
    runner's phases and state file). Every named file was checked to
    exist at HEAD, per the section's own rule.
  - **Governance** — the Evidence rule now says what "runs in the
    gate" means in a tags-only CI regime, and the Register's closing
    rule allows an upward status change to cite code already merged
    on `main`, verified by path in the amending PR — which is what
    rule 4's re-verification produces, and what XI's promotion here is.

Modified architecture sections: none. The Immutable Architecture
                                Decisions section is untouched, so no
                                ADR is required (`CONTRIBUTING.md` §7.1).

Templates reviewed:
  .specify/templates/plan-template.md   — UPDATED ✅ Version pointer
      1.5.0 → 1.6.0; gate rows XIII and XIV added to the Constitution
      Check; the "Enforcement honesty" paragraph no longer asks
      whether an enforcer "runs in the PR gate (`ci.yml`)" — it asks
      whether it runs in `scripts/guards/run_all.py` or
      `pytest -m "not e2e"`, the gate that exists.
  .specify/templates/spec-template.md   — No structural update needed ✅
      Reviewed against XIII and XIV. A spec that adds a flag or a
      settings key states its consumer under Functional Requirements,
      which the template already accommodates; XIV adds no section.
  .specify/templates/tasks-template.md  — No structural update needed ✅
      Its Principle III block is unaffected; XIII's enforcer runs from
      the guard battery, not from a per-spec task.

Propagated (non-template):
  README.md:401    — constitution pointer v1.5.0 → v1.6.0 (guarded by
                     `tests/docs/test_one_source_per_fact.py`)
  CLAUDE.md:554    — constitution pointer v1.5.0 → v1.6.0 (same guard)
  CHANGELOG.md     — `[Unreleased]` entry.
  NOT propagated here, deliberately: `CONTRIBUTING.md:66` still says
  "The 12 principles". That file is being rewritten in the concurrent
  docs-truth pass (proposal §3); a one-word edit on a row that pass
  replaces wholesale is a merge conflict, not a fix. Named here so it
  is not lost: it should read "The 14 principles".

Deferred items:
  - **Wiring, not writing**, still. Nine Partial rows and three
    Review-time-only rows each name what is missing. Nothing here is
    promoted without code already on `main`.
  - **XIV's proof does not ship yet.** `settings.ollama.yaml` is absent
    from `pyproject.toml`'s wheel force-include and from `build.sh`'s
    bundle copy (decision D11, 2026-09-08, is to package it; that lands
    in the docs-truth PR). The Register row is Partial until a test in
    the shape of `tests/test_assets.py::
    test_settings_opencode_yaml_bundled_in_wheel_data` exists for it.
  - **ADRs for XIII and XIV are NOT filed**, for the reason 1.5.0 gave
    for XI and XII: both transcribe decisions already taken — XIII by
    PR #329 and the class of fixes it closes, XIV by the owner on
    2026-09-08. An ADR IS still required before spec 036's envelope
    schema lands; that ADR (0013) is being written in a sibling PR and
    is not cited here because it is not on `main`.
  - Row XI's promotion covers the written-form and version bullets of
    Principle XI. The mirror-and-guard bullet is unmet for every
    contract, and the counterparty register in `consumer_pipeline` does
    not yet name this payload. Both are the next amendment's evidence,
    not this one's.
  - `CONTRIBUTING.md:66` (above).

============================================================
Earlier Sync Impact Report (preserved for history)
============================================================
Version change:    1.4.0 → 1.5.0
Bump rationale:    MINOR — two principles added, two sections added, and
                   one factual repair whose effect is an **enforcement
                   downgrade**.

                   Not PATCH: the repair to Principle I's gate table is
                   not a wording fix. Six of its nine rows claimed a
                   blocking gate that does not block, and one named a
                   path (`scripts/tests/`) that has never existed in 400
                   commits. Correcting a document's account of what
                   enforces it changes what a reader may rely on, so it
                   is material. This amendment writes that rule down:
                   an enforcement downgrade is MINOR, never PATCH.

                   Not MAJOR: no principle is removed, and none is
                   redefined so that previously-compliant work becomes
                   non-compliant. Principles I-X keep their text. What
                   changes is the accuracy of the mechanisms recorded
                   beneath them, plus two new obligations that record
                   decisions already taken (XI records the owner's
                   cross-repo decision; XII records the fix shipped in
                   PR #210) rather than deciding anything new.

Modified principles:
  I.   Script-Validated Quality Gates — gate table rewritten. The row
       naming `pytest scripts/tests/` is removed (the directory has never
       existed; `generator/scripts.py` copies files only, so a generated
       vault never receives one). Each remaining row now records the
       effect of failure: **Blocking**, **Report-only**, or **None**.
       Two gates are blocking on every path; the rest are advisory. Two
       standing rules added: a row MUST name a mechanism that can fail,
       and a row MUST NOT be promoted to Blocking before the code
       propagates the exit code.
  Principle text for I-X is otherwise unchanged.

Added principles:
  XI.  Cross-Repo Contracts Are Mirrored, Versioned and Guard-Synced
       (records the owner's decision: contracts are mirrored in each
       participating repo and kept in sync by a guard, NOT held in a
       shared fourth repo). Aligned in intent with `JoaoOliveira.eu`
       Principle VI (PR #82) and `consumer_pipeline` Principle XII (PR #227).
  XII. Inspection Does Not Mutate (NON-NEGOTIABLE) — a phase, script or
       processor named for inspection MUST NOT modify what it inspects.
       Derived from new failure record entry F9.

Added sections:
  - **Enforcement Register** — one row per principle: invariant,
    enforcing mechanism, failure mode, status. Four status values, and
    the counts are stated rather than implied: **2 Enforced, 6 Partial,
    3 Review-time only, 1 Not met**. Three principles (III, V, and the
    no-placeholder-scripts half of VIII) have no enforcing artifact at
    all; Principle IX's `settings.yaml` keys are read by no Python in
    this repo.
  - **Cross-Repo Obligations** — a register of the five contracts this
    repo participates in, with direction, counterparty, versioning and
    status. Retires `platform-constitution.md`, which is cited in three
    repos and exists in none.

Modified sections:
  - "Failure Record Reference" — F9 added (the verify phase rewrote what
    it graded; PR #210). The paragraph delegating the record to
    `vault-generator-framework.md` is replaced: that document is not in
    this repo and no copy has been found, so **this table is the
    record**.
  - "Out of Scope for This Constitution" — the delegation to the absent
    `vault-generator-framework.md` is replaced by a table naming the
    real, present authority for each concern, plus a rule that this
    constitution MUST NOT delegate to a document that does not exist.
  - "Boundary System" — the Always Do entry naming `pytest
    scripts/tests/` is corrected; the Never Do entry on the Phase-2
    gate now records that the automatic gate skips from an installed
    wheel and under `--skip-gate`, so the rule outlives its enforcer;
    and one Never Do entry is added for Principle XII.
  - "Governance" — enforcement-downgrade rule; a requirement that every
    amendment touching a principle re-verifies that principle's
    Enforcement Register row against the code in the same PR; and that a
    cross-repo contract change names the sibling repo's mirror.

Modified architecture sections: none. The Immutable Architecture
                                Decisions section is untouched, so no
                                ADR is required (`CONTRIBUTING.md` §7.1).

Templates reviewed:
  .specify/templates/plan-template.md   — UPDATED ✅ The Constitution
      Check was stock spec-kit boilerplate ("[Gates determined based on
      constitution file]"). Replaced with a twelve-row gate table derived
      from the principles, plus the domain-agnosticism check and the
      ADR stop-condition for the Immutable Architecture Decisions.
  .specify/templates/tasks-template.md  — UPDATED ✅ Its header declared
      "Tests are OPTIONAL - only include them if explicitly requested",
      which contradicts Principle III (NON-NEGOTIABLE). Corrected, and
      the `### Testing Requirements` block contract (`docs/foreman.md`)
      is now in the template — it is the only mechanism Principle III
      has, and it was absent from the template that feeds it.
  .specify/templates/spec-template.md   — No structural update needed ✅
      Reviewed against XI and XII: neither adds a required spec section.
      A spec that changes a cross-repo payload states it under Key
      Entities / contracts, which the template already accommodates.

Propagated (non-template):
  README.md:389    — constitution pointer v1.3.4 → v1.5.0
  CLAUDE.md:541    — constitution pointer v1.3.4 → v1.5.0
  CONTRIBUTING.md  — §2 taxonomy "10 principles" → "12"; §7 versioning
                     gains the enforcement-downgrade rule so the two
                     documents cannot drift on it.
  CHANGELOG.md     — `[Unreleased]` entry.

Deferred items:
  - **Wiring, not writing.** This amendment records enforcement
    truthfully; it does not add enforcement. The six Partial and three
    Review-time-only rows are work, and each names what is missing.
    Nothing here may be promoted in the Enforcement Register without the
    code to back it.
  - ADRs for XI and XII are NOT filed. `CONTRIBUTING.md` §6 requires an
    ADR for a decision that "adds an invariant that downstream specs must
    respect", but both principles record decisions already made
    elsewhere — XI by the owner and mirrored in two sibling repos, XII by
    PR #210, already shipped and tested. An ADR is for choosing; these
    are transcriptions. An ADR IS required before the first cross-repo
    envelope schema lands (spec 036), because that is a choice.
  - `specs/051-post-revival-hardening/spec.md:105,438` still cite
    `platform-constitution.md`. Spec text is frozen at ship
    (`CONTRIBUTING.md` §2); those two lines are read as pointing at the
    Failure Record below and are left as written.
  - The three docs-only checks
    (`tests/spec/test_acceptance_coverage_guard.py`,
    `tests/spec/test_changelog_regression_links.py`,
    `tests/docs/test_doc_sync.py`) are not in the Enforcement Register:
    they guard documentation hygiene, not a principle. Each can pass on
    evidence that does not exist — the acceptance guard validates cited
    test paths by regex alone and never touches the filesystem. Recorded
    here so the next audit does not mistake them for enforcers.

============================================================
Earlier Sync Impact Report (preserved for history)
============================================================
Version change:    1.3.4 → 1.4.0
Bump rationale:    MINOR — new principle added (spec 050). Introduces
                   **Principle X — Vault History is Append-Only Git
                   (NON-NEGOTIABLE)**: every framework operation that
                   mutates a vault MUST land on disk as at least one
                   git commit. Research cycles run on a dedicated
                   `research/<timestamp>` branch with per-cycle commits,
                   squash-merge to `main` on clean exit. Framework
                   upgrades commit directly on `main`. Ad-hoc
                   `./vault ask` / `./vault write` outputs commit any
                   produced files. Push attempts are best-effort when a
                   remote is configured. Default-on per-vault, opt-out
                   via `settings.vault_commit.enabled: false`. Existing
                   principles I-IX unchanged; this is purely additive
                   defensive infrastructure on top of the same data
                   model. Ratified for 0.7.0.

Modified principles: none modified; **Principle X added**.
Modified architecture sections: none (the auto-commit invariant is
                                  implemented in `pipeline.vault_commit`
                                  but is governed at the principle
                                  level, not the architecture-decision
                                  level).
Added/removed sections: Principle X added under "Core Principles".

Templates reviewed:
  .specify/templates/plan-template.md   — No structural update needed ✅
  .specify/templates/spec-template.md   — No structural update needed ✅
  .specify/templates/tasks-template.md  — No structural update needed ✅

Deferred items: none.

============================================================
Earlier Sync Impact Report (preserved for history)
============================================================
Version change:    1.3.3 → 1.3.4
Bump rationale:    PATCH — doc-sync only (spec 025 US5 / A5). The Technology
                   Constraints section still described the deleted bash cycle
                   driver as the Phase 2 entry point. Rewritten to
                   name the current chain: `./vault research` →
                   `cli/research.py` → `cycle_runner.run_cycle_steps` →
                   `scripts/agent_call.py` for `claude`/`codex` dispatch. No
                   principle changes, no governance changes, no architecture
                   changes — stale reference removal only.

Modified principles: none.
Modified architecture sections: Technology Constraints (wording only).
Added/removed sections: none.

Templates reviewed:
  .specify/templates/plan-template.md   — No structural update needed ✅
  .specify/templates/spec-template.md   — No structural update needed ✅
  .specify/templates/tasks-template.md  — No structural update needed ✅

Deferred items: none.

============================================================
Earlier Sync Impact Report (preserved for history)
============================================================
Version change:    1.3.2 → 1.3.3
Bump rationale:    PATCH — executes the source-level rename deferred by
                   the 1.3.0 → 1.3.1 Sync Impact Report. The Python
                   package (`research_vault` → `research_framework`),
                   CLI entry point (`research-vault` →
                   `research-framework`), and every reference under
                   `src/`, `tests/`, `scripts/`, `templates/`,
                   `dist-templates/`, `examples/`, `.github/`,
                   `settings*.yaml`, top-level `*.md` is rewritten. No
                   principle changes, no governance changes, no
                   architecture changes — pure mechanical rename of the
                   package the constitution governs. Released as v0.2.33.

                   Bundled in the same release: spec 013 (vault
                   migrator) is partially withdrawn — its CLI and
                   orchestration are deleted while four shared utility
                   modules are renamed and kept (see `CHANGELOG.md` and
                   `specs/013-vault-migrator/spec.md` tombstone). This
                   removes a vestigial subsystem; it does not modify
                   any principle.

                   `onboard` collapses from 5 → 4 steps (the deleted
                   step 5 called the now-deleted migrator). Final
                   onboarding message points users at `./vault
                   research` and `./vault update` instead of the
                   removed `migrate apply`.

Modified principles: none.
Modified architecture sections: none.
Added/removed sections: none.

Templates reviewed:
  .specify/templates/plan-template.md   — No structural update needed ✅
  .specify/templates/spec-template.md   — No structural update needed ✅
  .specify/templates/tasks-template.md  — No structural update needed ✅

Deferred items: none. The source-level rename deferred by the 1.3.1
                Sync Impact Report is now fully executed.

============================================================
Earlier Sync Impact Report (preserved for history)
============================================================
Version change:    1.3.1 → 1.3.2
Bump rationale:    PATCH — expand the existing "Not opinionated about
                   domain" definition with more emphatic, concrete
                   language. The principle was already present (line
                   121–122 of v1.3.1) but its quietness allowed designs
                   to drift toward web/backend assumptions during
                   spec-020 (Source-Module Architecture) drafting. The
                   expansion makes domain-agnosticism a property
                   referenced by every downstream spec, prompt design,
                   and test-fixture decision. No new principle, no
                   behaviour change, no governance change — same idea,
                   said louder in the place where it always lived.

Modified principles: none.
Modified architecture sections: none.
Added/removed sections: none ("What research-framework Is NOT"
                       subsection expanded in place).

Templates reviewed:
  .specify/templates/plan-template.md   — No structural update needed ✅
  .specify/templates/spec-template.md   — No structural update needed ✅
  .specify/templates/tasks-template.md  — No structural update needed ✅

Deferred items: none.

============================================================
Earlier Sync Impact Report (preserved for history)
============================================================
Version change:    1.3.0 → 1.3.1
Bump rationale:    PATCH — project rename from Speckit / research-vault to
                   research-framework. No principle changes; pure naming
                   sweep across this document. Resolves the two pending
                   renames the previous Sync Impact Report deferred
                   ("Speckit → Research-Vault" + the broader
                   research-framework alignment), bundling them into a
                   single editorial pass.

Modified principles: none.
Modified architecture sections: none.
Added/removed sections: none.

Templates reviewed:
  .specify/templates/plan-template.md   — No structural update needed ✅
  .specify/templates/spec-template.md   — No structural update needed ✅
  .specify/templates/tasks-template.md  — No structural update needed ✅

Deferred items:
  - Source-level rename: `src/research_vault/` → `src/research_framework/`,
    `pyproject.toml` package name + entry point, every import, every
    test, every template that bakes the CLI name into generated vaults.
    This is the actual implementation work tracked on `docs/ROADMAP.md`
    under "Project rename to research-framework". To be executed as a
    single commit/PR after spec 013 ships and before the first public
    release.

============================================================
Earlier Sync Impact Report (preserved for history)
============================================================
Version change:    1.2.0 → 1.3.0
Bump rationale:    MINOR — reframes Principle VIII's "Stub-Free Exit"
                   invariant. The invariant itself is preserved (a vault is
                   complete only when zero stubs remain), but its enforcement
                   mechanism inverts: stubs and unresolved wikilinks are now
                   *continuation triggers* that keep the research loop alive,
                   not termination blockers that abort it. Coverage targets
                   gain a dynamic-extension mechanic so the orchestrator's
                   "all targets met" condition tracks actual vault maturity
                   rather than spec-author foresight.

                   Same principle ("don't ship a sprawl of half-written
                   notes"); different mechanism ("the loop refuses to declare
                   done while there's fuel left").

Modified principles:
  II.  Phase Sequencing → makes Condition B evaluation explicitly the
       orchestrator's responsibility (not the agent's `next_action`); names
       backlog non-emptiness as a continuation trigger alongside scout
       discovery.
  VIII. No Placeholders in Deliverables → "Stub-Free Exit" subsection
       rewritten as "Stub-as-Fuel". Stubs no longer abort runs; they extend
       the cycle loop until budget or max_cycles trips.

Previous principles retained unchanged:
  I.   Script-Validated Quality Gates (NON-NEGOTIABLE)
  III. Test-First (TDD — NON-NEGOTIABLE)
  IV.  Agent-Script Separation of Concerns
  V.   Offline-First, No External Data Persistence
  VI.  No Duplicate Notes
  VII. External Sources Are Mandatory
  IX.  Vault-First Citation (NON-NEGOTIABLE)

Modified architecture sections:
  - "Coverage Targets as Phase Completion Gate" — adds the dynamic-extension
    mechanic (topic_harvest auto-promotes high-citation orphan wikilinks into
    `coverage-targets.json` so the gate tracks emergent topology).

Added sections:    None
Removed sections:  None

Templates reviewed:
  .specify/templates/plan-template.md   — No structural update needed ✅
  .specify/templates/spec-template.md   — No structural update needed ✅
  .specify/templates/tasks-template.md  — No structural update needed ✅

Deferred items:
  - Parallel scout/research workers (n × n) — agreed-out for v1.3, planned for
    a follow-up amendment after the loop semantics are validated end-to-end.
  - Renaming occurrences of "Speckit" → "research-framework" throughout
    this file (cosmetic; resolved in v1.3.1's editorial pass above).
-->

# research-framework Constitution

> "The next massive software failure will probably not come from a missing line of code.
> It will come from a missing sentence." — César Soto Valero

This constitution is the authoritative source of constraints for all agents working on the
research-framework codebase. It is read before any spec, plan, or implementation. Where it conflicts
with any other file, **this file wins**.

It is deliberately concise. It contains only what agents cannot infer from code. Constraints
here are not preferences — they are hard invariants derived from what went wrong when building
the system this tool is designed to prevent.

## What research-framework Is

A Python command-line tool that takes a vault spec file as input and produces a
fully-structured, script-validated, research-ready knowledge vault as output.

research-framework is a factory. The vault it generates is the product. The product is only as good as
the factory's quality gates.

- **Input**: A `vault-spec.md` file describing what the vault should cover.
- **Output**: A populated, validated, git-initialized Obsidian-compatible vault.
- **Three phases of output**:
  1. Infrastructure — folder structure, templates, scripts (all tested)
  2. Research — BFS/DFS cycles, validation between each cycle
  3. Finalization — index rebuild, git init, completion report

## What research-framework Is NOT

- **Not a content generator.** research-framework generates vault infrastructure and orchestrates
  research agents. It does not write knowledge content itself.
- **Not a documentation tool.** The vault it creates is for knowledge that enables
  decision-making — not for generating documents, code, or presentations from that knowledge.
- **Not opinionated about domain.** research-framework is **domain-agnostic
  by construction**. It is a process tool, not a subject-matter tool. The
  vault may be about Java microservices, embedded firmware, ML research,
  legal case law, biology literature, or any other research target — the
  framework MUST produce the same quality of work regardless. The spec
  file is the ONLY source of domain knowledge; the framework provides
  process rigor.

  When designs, prompts, examples, or tests drift toward a single domain's
  vocabulary (typically web / backend development, since that is what
  built the framework), they violate this property. Examples and few-shot
  prompts MAY reference specific technologies for illustration, but
  canonical schemas and structural decisions MUST be derivable from the
  spec at runtime, not hardcoded in source.
- **Not a Phase 2/3 system.** This tool targets Phase 1 (foundation/population) only. Write
  path, FTS5 indexing, and vector search are separate concerns.

## Core Principles

### I. Script-Validated Quality Gates (NON-NEGOTIABLE)

Every phase transition and cycle boundary MUST be validated by a script, not by agent
judgment. An agent reporting "the notes look good" is not a validation pass.
`validate_vault.py` returning exit code 0 is a validation pass.

The table below records the gates that exist and **what actually happens when each one
fails**. It is a description of the tree, not of the design intent. Three effects:

- **Blocking** — the exit code reaches the caller and the process stops.
- **Report-only** — the check runs, the result is logged, the exit code is discarded.
- **None** — the mechanism cannot fail.

| Gate | Mechanism | When | Effect when it fails |
|------|-----------|------|----------------------|
| Script bundle test | `cli/_common._run_phase1_gate` → `pytest tests/scripts/` in the **framework** checkout | Before Phase 2 | **Blocking in a source checkout only.** From an installed wheel the gate finds no `tests/` directory, prints "skipped (installed package…)" and returns `None`, which `cli/research_generate.py` treats as a pass. `--skip-gate` also bypasses it. There is no per-vault suite: `scripts/tests/` has never existed in this repo, and `generator/scripts.py` copies files only — never subdirectories — so a generated vault never receives one |
| Pre-cycle snapshot | `scripts/vault_metrics.py` | Start of each cycle | **None.** Its own docstring: "Always exits 0 (informational, never fails)". It returns 2 only when the vault directory is missing |
| Scout validation | `scripts/validate_cycle.py` via `pipeline/steps/postprocess.py` | After BFS | **Blocking.** The exit code is propagated. Required sources, five search dimensions, naming and the duplicate-note check (VI) all abort the cycle here. This is the strongest gate the pipeline has |
| Post-DFS validation | `scripts/validate_vault.py` | After DFS | **Report-only.** `postprocess.py`'s post-DFS step is commented "report-only; does not halt the cycle"; failures log at INFO. It also runs as gate SG-004, which maps any non-zero exit to **WARN, never FAIL** |
| Template compliance | `scripts/check_template_compliance.py` | After DFS | **Report-only.** Exit code discarded. Blocking only when a human runs `cli/audit.py` |
| Acronym links | `scripts/check_acronym_links.py` | After DFS | **Report-only.** Exit code discarded |
| Intent drift | `scripts/check_intent_drift.py` | After DFS; again at Phase 3 start | **Report-only** after DFS. Blocking at Phase 3 start — but **skipped silently if the script file is absent** (re-verified 2026-09-08: `cli/research_phase3.py:86-88`, `if not path.exists(): continue`) |
| Code-source coverage | `scripts/check_code_source_coverage.py` | After DFS; again at Phase 3 start | Same as above: report-only after DFS, blocking at Phase 3 start, silently skipped if absent |
| Scout step gates SG-001..SG-003 | `pipeline/gates_step.py`, run from `pipeline/steps/scout.py` | After BFS, before DFS | **Blocking once the correction loop is exhausted.** A FAIL builds a correction directive and re-runs the scout (`MAX_SCOUT_VALIDATION_RETRIES`, default 1); a FAIL that survives returns straight out of the cycle. SG-003 has been active on a stock generated vault only since #309 (`pipeline/abstraction.py`); `NA` now means one thing, `pipeline.gates.abstraction_enabled: false` |
| Duplicate notes (SG-004, `duplicate` class) | `pipeline/gates_step.py::SG004_validate_vault_wrapper` over `scripts/validate_vault.py` | After DFS | **Blocking for the `duplicate` class** — mapped to FAIL and fed to the correction loop since #293 (`validate_vault.DUPLICATE_FIELD`). Every other `validate_vault.py` finding still maps to WARN |
| Minimum cycle yield (CG-001) | `pipeline/gates_cycle.py::CG001_min_cycle_yield`, run from `pipeline/orchestrator.py` | End of each cycle | **Blocking after three attempts.** FAIL builds a correction directive and re-runs the cycle; the third FAIL returns 2. CG-002..CG-007 are computed only by `pipeline/quality_report.py` — **Report-only** |
| Post-cycle snapshot | `scripts/vault_metrics.py` | End of each cycle | **None** — same script, same guarantee |
| Coverage targets | `coverage-targets.json` via `cli/research_phase3.py` | Before Phase 3 | **Blocking.** Unmet targets print the missing categories and return 1; Phase 3 does not run |

The weekly pipeline runner (spec 075, `pipeline/runner.py`) is a second path with its own
gates. They are listed because the 2026-09-01 run (F10) is what happens when they are absent:

| Gate | Mechanism | When | Effect when it fails |
|------|-----------|------|----------------------|
| Phase artifact check | `runner._check_scout_artifact`, `_check_research_artifact`, `_check_report_artifact` (#222) | After the scout, research and report phases | **Blocking.** A phase is done when its artifact exists, parses and carries the field the next phase reads — not when the agent exits 0. Otherwise the phase is FAILED, the run returns 1, and `_close_phase` logs the reason at ERROR with the path of `pipeline-state.json` (#219) |
| Verify verdict | `runner._drive_verify` → `processors/verify.py` | `finish` | **Blocking.** PASS/WARN → done; FAIL/ERROR → FAILED with the reason in `errors` and the full report in `_pipeline/logs/verify-<timestamp>.json` (#218, #229) |
| Collect with nothing collectable | `runner._drive_collect` (#223) | `collect` | **None — not a gate.** Recorded so nobody promotes it: when every declared source needs a collector this version lacks, the phase is SKIPPED at WARNING rather than reported done, and the run continues |

On the cycle path, four mechanisms stop a run: **scout validation**, the **SG-001..004
correction loop** once it is exhausted, **CG-001** after three attempts, and **coverage
targets**. On the runner path, the **artifact checks** and the **verify verdict** stop it.
Everything else is advisory today, and Phase 3's "full suite" is two scripts, either of
which vanishes without complaint if its file is missing.

A gate that fails stops the process **where this table says Blocking**. The generator
reports which gate failed, why, and what to fix. It MUST NOT proceed past a failed blocking
gate.

Two standing rules govern this table:

1. **Every row MUST name a mechanism that can fail.** A script whose docstring says it never
   fails, or whose exit code the caller discards, is a report. Record it as one.
2. **A row MUST NOT be promoted to Blocking before the code propagates the exit code.** The
   advisory rows above are work items, not permission. Promoting a row is an amendment
   (see § Enforcement Register and § Governance).

### II. Phase Sequencing (NON-NEGOTIABLE)

Phases are strictly sequential. No parallelism between phases.

```
Phase 0 (parse)          → exit on invalid spec
Phase 1 (infrastructure) → pytest must pass before Phase 2
Phase 2 (research)       → cycles until termination + coverage met
Phase 3 (finalization)   → coverage-targets gate must pass first
```

Within Phase 2: cycles are sequential. Within a cycle: scout and DFS are sequential.
Research agents within a DFS MAY run in parallel only if their topic lists are
non-overlapping.

Cycle TERMINATE is NOT Phase 1 complete. TERMINATE means the BFS/DFS loop found nothing
new. It does not mean the vault meets its coverage targets — these are different conditions
checked by different mechanisms. If cycles terminate with unmet coverage targets, the
generator identifies which categories are missing and re-enters Phase 2 with a targeted
prompt. It MUST NOT proceed to Phase 3.

**Loop continuation is orchestrator-owned, not agent-owned.** The agent's `next_action`
field is advisory. The orchestrator MUST run another cycle (subject to the budget and
`max_cycles` caps) whenever ANY of these are true:

- The latest scout's `topics_found.new` list is non-empty (agent discovered new material), OR
- `_pipeline/research-backlog.md` has any unresolved entry (orphan wikilinks from prior
  cycles), OR
- Any note in `data_vault/` matches the stub criteria in Principle VIII.

Only when ALL three are false AND coverage targets are met may the loop terminate
successfully. Hitting the budget or `max_cycles` cap with any of the three still true is a
**constrained exit**: the orchestrator exits with a punch-list of deferred items so the user
can `--resume`.

### III. Test-First (TDD — NON-NEGOTIABLE)

Tests MUST be written before or alongside every new script. Every script listed in the
Phase 1 output MUST contain working implementation code. A file with a `TODO` comment or
`pass` body is not a script — it is a false dependency.

`--dry-run` MUST be added to every script that modifies vault files. Dry-run testing on
fixtures MUST occur before running any fix script on real vault data. Fix scripts that
bypass this step have a documented history of producing cascading damage (F7: 71 files
damaged).

### IV. Agent-Script Separation of Concerns

Agents assess whether coverage is sufficient; scripts validate it. These roles MUST NOT be
conflated.

- **Agents** — report, research, and generate notes.
- **Scripts** — validate, gate, and enforce quality.

Agents MUST NOT self-assess their own validation output. The validation pipeline is the
product. Shortcuts in validation are the failure mode the product exists to prevent.

### V. Offline-First, No External Data Persistence

research-framework MUST be fully operable offline on a clean machine. All vault content is potentially
proprietary business information. External libraries or services that persist data outside
the host machine MUST NOT be used. No telemetry, no cloud sync, no package that phones
home. If a dependency is added, it MUST be justified in the PR description.

### VI. No Duplicate Notes

Two notes for the same concept MUST NOT exist. The naming convention is enforced before DFS
writes any file. `proposed_filenames` in the scout JSON is the coordination mechanism. If
two agents are running in parallel, their topic lists MUST be non-overlapping — not their
source lists.

### VII. External Sources Are Mandatory

External sources (web, market, competitors) MUST NOT be skipped without a logged reason.
They are not optional. A vault without domain and market context is an internal
documentation mirror. Condition B (no-new-topics termination) requires external source
consultation as a sub-condition. Skipping external sources violates Condition B.

### VIII. No Placeholders in Deliverables

Every script listed in Phase 1 output MUST be a working implementation. Every note created
during research MUST meet the Note Quality Bar (see below). Placeholder code, empty function
bodies, and stub notes MUST NOT be delivered as final output.

The codebase vault build shipped placeholder scripts and then ran research cycles without the
validation they were supposed to provide. That failure is the direct origin of this
constraint.

**Stub-as-Fuel (applies to every research mode).** A *successful* run (bootstrap, refresh,
or expand) MUST NOT terminate while any note in `data_vault/` matches the stub criteria, OR
while any orphan wikilink remains in the body or `related:` frontmatter of any note. The
stub criteria are unchanged:

- `word_count < note_type.min_word_count`, OR
- frontmatter `source_urls` is empty (zero Tier-2 citations — also a Principle IX violation), OR
- verifier `status` is `pending` or `rejected`, OR
- frontmatter lifecycle `status` is still `draft`.

The enforcement mechanism is **continuation, not abort**. Stubs and orphan wikilinks are
*signals about what to research next* — they are the natural fuel for the cycle loop. The
orchestrator's responsibility is to keep the loop alive on this fuel until either:

- (success) Coverage met AND zero stubs AND scout returns no new topics — the vault is
  declared complete and Phase 3 finalizes, OR
- (constrained) Budget cap or `max_cycles` cap trips — the orchestrator exits with the
  unresolved fuel listed in `_pipeline/research-backlog.md` so the user can `--resume`.

The mechanism that turns stubs into next-cycle work is `scripts/topic_harvest.py`, which
runs at every cycle's tail and writes ranked orphan wikilinks (by citation count) into the
research backlog. The next scout reads the backlog as input and prioritises high-citation
gaps. Auto-promotion of frequently-cited orphans into `coverage-targets.json` (see
"Coverage Targets as Phase Completion Gate" below) closes the loop so "all targets met"
naturally tracks the vault's emergent topology.

Partial vaults are acceptable when explicitly constrained (budget or cycle cap); *sprawling*
vaults that terminate early with stub-heavy content are not. The principle holds; only the
mechanism changes from "abort the run" to "refuse to declare done."

### IX. Vault-First Citation (NON-NEGOTIABLE)

Every answer, generated document, or agent response produced *from* a vault MUST cite vault
notes as its primary sources. Vault notes, in turn, MUST cite original external sources in
their own frontmatter / body. This two-tier structure is the vault's reason for existing: it
keeps users and agents grounded in curated, verified content rather than hallucinated or
ungrounded text.

Concretely:

- **Tier 1 (Vault Sources)** — every claim in an answer or generated document MUST point to
  one or more `[[wikilinks]]` or relative paths inside `data_vault/`. An answer without
  Tier 1 citations is invalid regardless of how accurate it appears.
- **Tier 2 (Original Sources)** — the cited vault notes MUST themselves carry at least one
  `source_urls` entry in frontmatter, resolving to an external or code source. A vault note
  without Tier 2 citations cannot legally be used as a Tier 1 citation.
- **Two-tier rendering** — agent responses and document outputs MUST surface both tiers
  distinctly (e.g., a `Vault Sources` section listing `[[notes]]` and an `Original Sources`
  section de-referencing the Tier 2 URLs). Burying Tier 2 inside Tier 1 prose is a violation.
- **Verifier enforcement** — an independent verifier agent MUST reject any output that
  (a) lacks Tier 1 citations, (b) references Tier 1 notes whose frontmatter has zero
  Tier 2 sources, or (c) conflates the two tiers in rendering. Verifier rejection is a hard
  stop; the generator MUST NOT ship verifier-rejected content to the user.

This principle directly addresses the failure mode where agents produce confident prose
untethered from the vault's curated knowledge. The vault's value is its source grounding;
responses that bypass that grounding eliminate the vault's reason to exist.

### X. Vault History is Append-Only Git (NON-NEGOTIABLE)

Every framework operation that mutates a vault MUST land on disk as at least one git commit.
This is a *defensive* invariant: the framework runs unattended for hours at a time, often
through sandboxed agents whose internal state is opaque. The git log of a vault is the only
artifact a future user (or a future agent) can replay deterministically — every commit
becomes a checkpoint; every checkpoint is reversible.

Concretely:

- **Research cycles** — `./vault research` MUST refuse to start on a dirty `main` (uncommitted
  user edits would be co-mingled with framework output). On a clean `main`, the framework
  MUST create a dedicated `research/<timestamp>` branch, MUST emit one commit per cycle, and
  MUST squash-merge back to `main` on a clean (rc=0) exit. On a constrained exit (rc=1) the
  branch is retained for human review. On an aborted exit (rc=2) the partial cycle commit
  on the branch tail MUST be rewound. Resume runs MUST reuse the in-flight research branch.
- **Framework upgrades** — `./vault update`, `install.sh` re-runs, and any scaffold refresh
  MUST commit the result directly on `main` with a `framework: ` prefix. Upgrades are
  recovery points; rolling back a bad upgrade must be one `git revert` away.
- **Ad-hoc CLI outputs** — `./vault ask`, `./vault write`, and any other verb that produces
  files in the vault MUST commit those files with a `vault: ` prefix. Verbs that produce
  nothing on disk are exempt.
- **Push if remote** — if a remote is configured, the framework MUST attempt to push
  (best-effort, never fatal). Push failures WARN and continue; missing remotes are a silent
  skip. The `vault_commit.push_on_complete` setting can override (`never` to suppress,
  `always` to require a remote).
- **Opt-out is explicit per-vault** — there is no implicit skip. A user who wants to forgo
  the invariant MUST set `settings.vault_commit.enabled: false` in their `settings.yaml`;
  the framework MUST then proceed without committing but MUST log the opt-out at INFO so
  no future operator is surprised.
- **Commit failure is non-fatal** — the cycle's own rc takes precedence. A failed commit
  WARNs and records a sidecar at `_pipeline/commit-failures-<label>.json`. The framework
  MUST NOT exit with a non-zero rc *because of* an auto-commit failure (the cycle decides
  its own fate; the invariant is defensive infrastructure, not a gate).

This principle exists because every vault we have shipped on has gone through at least one
"the cycle ate my notes and I can't tell what changed" moment. The remedy is structural:
make every change replayable, make every checkpoint reversible, make the default safe.
Implementation: `src/research_framework/pipeline/vault_commit.py`. Specification:
`specs/050-vault-auto-commit/spec.md`.

### XI. Cross-Repo Contracts Are Mirrored, Versioned and Guard-Synced

This repo exchanges payloads with sibling repos it does not control. Every such exchange is
a **contract**, and a contract with no written form is a shape that survives only in one
author's head.

The decision, stated once so it stops being re-litigated: **contracts are mirrored in each
participating repo and kept in sync by a guard. They are NOT held in a shared fourth repo.**
A shared repo would be a third deploy unit, a third release cadence and a third place to
forget — and it would break the deploy-time separability that spec 036 US3 makes a P1
invariant. Duplication with a drift detector is the cheaper failure mode: it fails loudly
in CI, where a missing shared dependency fails silently at runtime.

Concretely, every cross-repo contract MUST have:

- **A written form in this repo** — a schema file, not prose, when the payload is
  structured; a named module when it is a file format.
- **A version** carried in the payload itself, so a consumer can refuse a shape it does not
  understand rather than misparse it.
- **A named counterparty**, so the obligation has an address.
- **A mirror** in the counterparty repo, and **a guard that fails when the two diverge.**
  A hand-copied mirror with nothing checking it is not compliant; it is the drift waiting
  to happen.
- **A row in § Cross-Repo Obligations**, with its honest status.

A contract MUST NOT be changed in one repo alone. An amendment or PR that changes a payload
another repo reads MUST name the sibling repo's mirrored copy and say whether it changed.

This repo currently satisfies none of the five contracts in that register fully; the
register says so, per row. The obligation is recorded before it is met, deliberately —
Principle IX was written the same way, and writing the rule is what makes the gap
countable.

### XII. Inspection Does Not Mutate (NON-NEGOTIABLE)

A phase, script or processor named for inspection — `validate_*`, `check_*`, `verify`,
`audit`, `quality_report`, and every gate in Principle I — MUST NOT modify what it
inspects. Read-only is the default, and from inside a pipeline phase it is not configurable
away.

- **Repair is a separate verb.** A tool MAY offer to fix what it finds, but repair MUST be
  opt-in per invocation (off by default), MUST be reachable only through an operator-facing
  CLI, never from a pipeline phase, and MUST honour `--dry-run` (Principle III).
- **A flag that disables mutation MUST be tested to actually disable it.** A dead parameter
  is worse than no parameter: it advertises a safety the operator does not have.
- **Repair writes through the canonical codec** for the format it edits. A bespoke
  reader/writer pair beside a shared one is a second, untested serialiser, and it will
  round-trip differently.
- **A test asserting read-only behaviour MUST assert byte-identity of the inspected files**,
  not a counter, not a substring, and not through a mock of the function under test.

The operator's willingness to run a verifier is the whole basis of its authority. A
verifier that edits is indistinguishable from an unreviewed migration running unattended on
production data — which is exactly what happened (see **F9** in the Failure Record).

### XIII. Nothing Is Accepted and Ignored (NON-NEGOTIABLE)

What the framework accepts, it acts on; what it records, it says. Two halves, one failure
mode: the operator believes something happened that did not.

- **An accepted input MUST reach a consumer that changes behaviour.** A CLI flag, a
  `settings.yaml` key, a spec field or a report field that the framework parses and never
  reads is not a feature — it is a promise the code does not keep. Until a consumer exists
  the input MUST be refused (exit 2, naming the surface that does honour it — the spec 074
  precedent, followed by `pipeline --budget-cap` in #232), never accepted and dropped.
- **A recorded failure MUST be spoken.** A non-zero exit, a FAILED phase, a SKIPPED phase
  or a rejected gate MUST reach stderr at ERROR (or WARNING for a skip) and MUST name the
  file that holds the full record. A diagnosis written only into a JSON file under
  `_pipeline/` has not been reported; under the shipped non-TTY `WARNING` default it has
  been hidden (spec 070 FR6, spec 077 US2).
- **A phase is done when its artifact exists, not when its process exited 0.** The thing
  the next phase reads is the proof of work; an exit code is a claim.
- **Quiet is not silent.** `--quiet` suppresses narration. It MUST NOT suppress the reason a
  run exited non-zero.

The class is older than the incident that named it. The 1.1.0 CHANGELOG records "config
accepted and silently ignored" four times; the inert options found so far are `url:`,
`--target-topics`, `source_policy: hard`, `vault.corpus_dir`, `pipeline --budget-cap`, and
`verify`'s `--no-fix` / `--fail-threshold` until PR #210. Six point fixes are the argument
for an invariant. Enforcement today is
`scripts/guards/parser_flag_consumers.py` (every parser flag must be read under `cli/` and
cross into a non-CLI module), `tests/cli/test_nonsilent_exit_guard.py` (a non-zero exit
writes stderr bytes and an ERROR record), and `pipeline/runner.py::_close_phase` (the one
place a phase ends). Settings keys have no equivalent guard yet; the Register says so.

### XIV. A Local or Decentralised Model Option Is Always Supported

Every model-backed capability in this framework MUST keep a self-hosted provider path: a
way to run it against a model the operator hosts, on hardware the operator controls, with
no vendor account in the loop. This is the owner's standing decision for every AI project
(2026-09-08), and it is not conditional on the local path being as good as the hosted one.

- **Degraded is acceptable; absent is a violation.** A local model that completes a stage
  slowly, or needs a smaller prompt, or cannot yet drive the agentic stages end-to-end
  (spec 065 records exactly that, with evidence) satisfies this principle. A capability
  that can be reached *only* through a hosted vendor does not.
- **The shipped Ollama profile is the proof.** `settings.ollama.yaml` routes every stage to
  a local Ollama server over HTTP (`scripts/agent_call.py::_dispatch_http`, spec 078
  FR-007), and `settings.opencode.yaml` reaches local providers (`ollama`, `local`,
  `lmstudio`, `llamacpp`) through the `opencode` agent loop at a measured `$0`. At least
  one such profile MUST ship with every release — in the wheel and in the bundle — and a
  test MUST fail when it is missing from either.
- **Hardware weakness is not a reason.** A local option that is impractical on today's
  box is kept, documented as degraded, and revisited when the box changes. It is never
  removed because the hosted path is currently better.
- **The dispatch guard MUST know the local runtime.** `tests/_helpers/llm_dispatch.py`
  derives its guarded set from `agent_call._LLM_AGENT_NAMES`; a local runtime that is not
  in that set is a dispatch path the guards cannot see (Principle IV).

This principle strengthens Principle V. Offline-first says vault content stays on the
host; XIV says the *model* can too. A framework whose only inference path is a metered API
is offline-first in name only.

## Enforcement Register

One row per principle: the invariant, the artifact that enforces it, what goes wrong if it
is breached, and — the point of the table — an honest status.

**Status values:**

- **Enforced** — a named artifact fails, on a fresh clone, when the invariant is breached,
  and it runs in the merge gate. Since PR #323 (2026-09-07) that gate is **local**: the
  battery `CONTRIBUTING.md` and `docs/RELEASE.md` name — `scripts/guards/run_all.py`,
  `pytest -m "not e2e"`, `ruff check`, `ruff format --check` — run by the contributor
  before a PR and reported in it, and re-run by `ci.yml` on a version tag or a manual
  dispatch. "Runs in the PR gate" is not a claim this repo can make while `ci.yml` has no
  PR trigger, and this row's definition was rebound in 1.6.0 to say so.
- **Partial** — an enforcer exists, but its coverage is narrower than the principle, or it
  can pass while the invariant is breached.
- **Review-time only** — no artifact enforces this. It holds because a human checks it.
- **Not met** — the repo does not currently satisfy the principle at all.

**Read every row against this context** (re-verified 2026-09-08 at private v1.2.0).
There is no PR gate. `.github/workflows/ci.yml` runs on version tags and
`workflow_dispatch` only (PR #323); `quality.yml` and `release.yml` likewise. Whether a
given tag actually got a run is checked with `gh run list --workflow ci.yml`, never
assumed — Actions billing on this account has interrupted runs before (`CLAUDE.md`, "CI is
billing-blocked"). The merge gate is the local battery: `python scripts/guards/run_all.py`
(#315) runs three guard scripts — `scripts/check_portability.py`,
`scripts/guards/check_agent_asset_references.py`,
`scripts/guards/parser_flag_consumers.py` — plus the fourteen guard test files in its
`GUARD_TEST_PATHS`, and refuses to start if any listed file is missing; then `pytest -m
"not e2e"`, `ruff check`, `ruff format --check`. `ci.yml` re-runs that battery and adds
shellcheck, an `install.sh` dry-run and the `e2e` tier. A TRACKED `.git-hooks/pre-commit`
runs the same aggregator before every commit — but only in a clone that ran
`scripts/install-git-hooks.sh` once (`git config core.hooksPath .git-hooks`); a clone that
did not has no hook, and nothing checks which kind of clone produced a commit. `build.sh`
executes no guard *script*, but its smoke gate runs `tests/_helpers/`, which carries the
static dispatch guard. The foreman verifier is still invoked only by a human checklist in
`CLAUDE.md`. The eleven scripts under `scripts/` that take a vault directory
(`check_abstraction.py`, `check_trunk_inversion.py`, `validate_vault.py`, …) guard a
generated vault, not this corpus; `run_all.py`'s docstring names them as out of scope
rather than skipping them silently. Of those, the abstraction gates SG-003/CG-003 have
been active on a stock generated vault only since #309; `check_trunk_inversion.py` still
has no caller anywhere. **Testing a guard is not running it** — the guard test battery
exists so that distinction has a name.

| # | Invariant | Enforcing mechanism | Failure mode if breached | Status |
|---|-----------|---------------------|--------------------------|--------|
| I | Every phase transition and cycle boundary is validated by a script, not agent judgment | `cli/research_phase3.py` coverage gate (blocking); `scripts/validate_cycle.py` via `pipeline/steps/postprocess.py` with the exit code propagated (blocking); the SG-001..004 correction loop and CG-001's three-attempt retry (blocking once exhausted, #293/#309); on the runner path, `runner._check_*_artifact` and `_drive_verify` (blocking, #222/#229, pinned by `tests/pipeline/test_runner_phase_artifacts.py` and `test_runner_verify_verdicts.py`). The Phase-1→2 gate (`cli/_common._run_phase1_gate`) still returns `None` from an installed wheel and `cli/research_generate.py:218` reads that as a pass; `--skip-gate` bypasses it | Untested scripts corrupt vaults silently (F1, F7); a phase reports done having written nothing (F10) | **Partial** — the Phase-1→2 gate is a no-op for every end user, and the Phase-3 pre-checks vanish silently when their script files are absent |
| II | Phases are strictly sequential; loop continuation is orchestrator-owned, never driven by an agent's `next_action` | `pipeline/orchestrator.py` owns the loop and its docstring restates the three continuation triggers; the spec-071 archived-vault refusal is enforced twice | Cycle TERMINATE mistaken for "done"; a vault ships under its coverage targets (F6) | **Partial** — the sequencing lives in one module, but no test asserts that all three continuation triggers keep the loop alive |
| III | Tests are written before or alongside every script; `--dry-run` on every vault-mutating script, exercised on fixtures first | **No enforcing artifact.** `scripts/foreman/verify_test_coverage.py` is the only mechanism and it is invoked by a human checklist in `CLAUDE.md` — it appears in neither `ci.yml` nor `build.sh`, and on a branch whose `tasks.md` declares no Testing Requirements it exits 0 vacuously. 8 of the 35 Python scripts in `scripts/` take `--dry-run` (re-counted 2026-09-08); `scripts/guards/run_all.py` excludes the foreman verifier by design because it has no corpus-sweep mode | A fix script cascades damage across a real vault (F7: 71 files damaged; F9: 7 of 8 live vaults) | **Review-time only** |
| IV | Agents report; scripts validate. Agents never self-assess their own validation output, and LLM dispatch routes through `scripts/agent_call.py` | `tests/_helpers/test_llm_dispatch_guard.py` (static; in `run_all.py`'s battery and in `build.sh`'s smoke gate) plus `tests/quality/test_fake_agent_interception.py` (runtime, `e2e`-marked — the `e2e` tier). Both read `tests/_helpers/llm_dispatch.py`, which derives the guarded binary set from `agent_call._LLM_AGENT_NAMES` and knows the HTTP dispatch mode (`is_inference_url`), with `tests/_helpers/test_llm_dispatch_parity.py` asserting the two guards classify every shipped executor identically (#292, #301). The static guard fails closed on an empty scan root (`test_scan_root_is_not_vacuous`, floor of 50 files, #278); the runtime guard asserts it observed dispatch traffic before asserting it was clean | An agent grades its own work; validation becomes a formality (F8) | **Partial** — the dispatch-surface half is guarded in both modes; the self-assessment half has no enforcer. The static guard's `_SUBPROCESS_ATTRS` is still `{run, Popen}` with the command taken from a literal list or a simple name binding, so `subprocess.call`/`check_output`, `os.system` and a string command under `shell=True` still pass |
| V | Fully operable offline; no library or service that persists vault content off the host | **No enforcing artifact.** No network-blocking fixture in `tests/conftest.py`, no dependency-set test. Outbound HTTP is unguarded in at least seven modules (`pipeline/preflight.py`, `collectors/_fetch.py`, `cli/refresh_sources.py`, `processors/archive.py`, the RSS module). The constitution's own text names this review-time | Potentially proprietary vault content leaves the machine; a dependency phones home | **Review-time only** |
| VI | Two notes for the same concept MUST NOT exist | Pre-write: `scripts/validate_cycle.py::_filename_collision_errors` — `proposed_filenames` is a required field on a v2 scout report and is checked against the vault, against itself, and for the `[]` opt-out while topics are still being reported (ABORT; #293/#301). Post-write: `SG004_validate_vault_wrapper` maps `validate_vault.py`'s `duplicate` class to FAIL, which drives the correction loop. Tests: `tests/scripts/test_validate_cycle_proposed_filenames.py`, `tests/pipeline/test_gates_step_sg004_duplicates.py` (runs the real script against real duplicates), `tests/pipeline/test_no_duplicate_notes.py` | Parallel agents produce two notes per concept; the graph forks (F3) | **Enforced** |
| VII | External sources MUST NOT be skipped without a logged reason; Condition B requires external consultation | The required-source gate in `scripts/validate_cycle.py` is real and blocking | The vault becomes an internal documentation mirror with no market or domain context (F5) | **Partial** — the *external* sub-condition is not implemented: the code comment "At least one external source consulted with results (constitution VII)" is followed immediately by `return errors, warnings` |
| VIII | Every listed script is a working implementation; a run refuses to declare success while stubs or orphan wikilinks remain | Stub half is real: `pipeline/stubs.py`, consumed by the orchestrator's continuation check, plus gate SG-005. Placeholder-script half: **no enforcing artifact** — nothing scans a shipped script for a `pass` body or a bare `TODO` | Scripts are listed as delivered, research runs, and the validation those scripts were supposed to provide never happens (F2) | **Partial** |
| IX | Every answer cites vault notes (Tier 1); those notes cite external sources (Tier 2); both tiers rendered distinctly; the verifier hard-stops violations | Prompt text in `templates/commands/ask.md.j2`. The only test is a string-presence assertion over that template. **`citation.tier1_required`, `citation.tier2_required` and `citation.render_sections.*` in `settings.yaml` are read by no Python in this repo** — they are configuration that configures nothing. The verifier agent exists but grades notes, not answers | Confident prose untethered from the vault's curated knowledge — the exact failure the vault exists to prevent | **Review-time only** — the enforcement is a prompt, and prompts are advice |
| X | Every vault mutation lands as at least one git commit, on the right branch, with the right prefix | `pipeline/vault_commit.py` + `pipeline/vault_git.py`, called from `orchestrator.run_cycles`. **Twelve test modules reference `vault_commit`/`vault_git` (re-counted 2026-09-08), none `e2e`-marked, so all run under `pytest -m "not e2e"`**; `ci.yml` provisions a git identity specifically so they run | "The cycle ate my notes and I can't tell what changed" | **Enforced** — the best-enforced principle here. Self-limiting by design: a failed commit WARNs rather than failing the run, and the `enabled: false` opt-out is deliberately unguarded |
| XI | Cross-repo contracts are written, versioned, mirrored, and guard-synced | `tests/contracts/test_json_schema_validation.py` (#326) validates seven committed `*.schema.json` files against output the production writers actually produce, with `jsonschema` now a dependency — the written-form bullet has a guard. The note format has a written form (spec 079), a per-note version (`template_version`, FR-006) and a named counterparty. Spec 036 is still DRAFT and the two schemas it names (`tests/contracts/vault-ask-1.0.schema.json`, `research-result-1.0.schema.json`) still do not exist | A consumer misparses a payload whose shape changed under it; the note format that `consumer_pipeline` reads was in fact silently rewritten by F9 | **Partial** (was Not met) — no contract has a mirror in its counterparty or a guard that fails when the two diverge, which is the bullet the principle exists for |
| XII | A phase named for inspection does not modify what it inspects | `tests/pipeline/test_runner_verify_scope.py` drives the real `_drive_verify` over a real vault and asserts `.claude/commands` is byte-identical afterwards; `tests/processors/test_verify.py::TestWalkScope` and `::TestOptionPrecedence` (PR #210); `tests/pipeline/test_runner_verify_verdicts.py` pins the FAIL path (#229). All unmarked, so in `pytest -m "not e2e"`. Since #218 the phase writes its report to `_pipeline/logs/verify-<timestamp>.json` — outside the corpus it grades, which is the line XII draws (#327 rebased the flag classes onto the same path) | An unattended weekly phase rewrites the corpus it was asked to grade (F9) | **Partial** — the verify path is pinned; there is still no byte-identity assertion for the `preprocess`, `extract` or `archive` processors (`tests/processors/test_{preprocess,extract,archive}.py` carry none), for `cli/audit.py`, or for `scripts/fix_acronym_links.py` / `fix_wikilinks.py` |
| XIII | What the framework accepts reaches a consumer or is refused; what it records is spoken | `scripts/guards/parser_flag_consumers.py` + `tests/cli/test_parser_flag_consumer_guard.py` (#271, #329; a named line in `run_all.py`, fail-closed with floors on flags found and files scanned); `tests/cli/test_nonsilent_exit_guard.py` (stderr bytes plus an ERROR record on every non-zero exit, #243); `tests/pipeline/test_runner_failure_reporting.py` and `test_runner_phase_artifacts.py` (#218, #219, #222) | A weekly run fails and nobody can read why; a cap the operator set is never applied (F10) | **Partial** — the flag guard is a floor: a flag threaded into a function that then ignores it passes (that was `--target-topics` and `--budget-cap`), and `settings.yaml` keys have no consumer guard at all (spec 076 T001, strict mode, is unbuilt) |
| XIV | Every model-backed capability keeps a self-hosted provider path; a local profile ships with every release | `tests/scripts/test_agent_call_ollama.py` (hermetic HTTP dispatch, `cost_usd: 0.0` with real tokens); `tests/_helpers/test_llm_dispatch_parity.py` (`ollama` and `opencode` in the guarded set, derived from `agent_call.py`); `tests/pipeline/test_opencode_executor_cycle.py` over `settings.opencode.yaml` | The only inference path is a metered vendor API; a vendor outage or a quota is a framework outage | **Partial** — the path exists and is guarded, but `settings.ollama.yaml` is in neither `pyproject.toml`'s wheel force-include nor `build.sh`'s bundle copy, so it does not ship with a release today (decision D11 packages it), and no test asserts a local profile is in the wheel — `tests/test_assets.py::test_settings_opencode_yaml_bundled_in_wheel_data` is the shape it needs |

**Count: 2 Enforced, 9 Partial, 3 Review-time only, 0 Not met** (1.5.0: 2 / 6 / 3 / 1).
Three principles (III, V, and the no-placeholder-scripts half of VIII) still have no
enforcing artifact whatsoever.

This register is normative about status. Changing a row upward requires the code that makes
it true — in the same PR, or already merged on `main` and cited by path in the amending PR,
which is what Governance rule 4's re-verification produces. Never code that is planned.

## Cross-Repo Obligations

The contracts this repo participates in, per Principle XI. Direction is from this repo's
point of view.

| Contract | Direction | Counterparty | Versioned | Authoritative form today | Status |
|----------|-----------|--------------|-----------|--------------------------|--------|
| **Vault note format** — Markdown + YAML frontmatter under `data_vault/`, with the note-type taxonomy | produced here, read there | `consumer_pipeline` (`pipeline/vault_import.py`, which reads `type`, `title`, `summary` and `source_urls` and maps note types into its knowledge corpus) | **Yes, per note** — `template_version`, stamped on every rendered note (spec 079 FR-006, since PR #327). The consumer does not read it yet | Spec 079 (the written form, shipped 2026-09-08); `REQUIRED_FIELDS` in `scripts/validate_vault.py`; parse/emit by `src/research_framework/vault/frontmatter.py` (the spec 025 B4 canonical codec). No schema file; no mirror in the consumer — `consumer_pipeline`'s own contract register (its constitution §5, C1–C4) has no row for this payload, and its C4 "advice corpus" is what `vault_import.py` *produces*, not what it reads | **Partial** (was Non-compliant) — written, versioned and addressed; not mirrored and not guard-synced. Already breached once: F9 rewrote this exact payload across seven live vaults, and the consumer had no way to notice |
| **Vault scaffold manifest** — what a generated vault receives and what it owns after first write | produced here, consumed by every generated vault | generated vaults (`_pipeline/scaffold-manifest-snapshot.json`) | **Yes** — `framework_version`, `generator_commit`, `generated_at` | `dist-templates/scaffold-manifest.json`, built by `scripts/build_scaffold_manifest.py`; snapshot behaviour tested under `pytest -m "not e2e"` | **Partial** — the closest thing to a model row. No test rebuilds the manifest and compares it to `templates/`, so a template added without regenerating drifts silently |
| **`./vault ask --format json` answer envelope** | produced here, consumed there | `assistant-framework` | declared `1.0`, unbuilt | spec 036 US1 (DRAFT). `tests/contracts/vault-ask-1.0.schema.json` does not exist | **Not met** |
| **Cycle-result inbox envelope** | produced here, consumed there | `assistant-framework` | declared `1.0`, unbuilt | spec 036 US2. `tests/contracts/research-result-1.0.schema.json` does not exist | **Not met** |
| **Deploy-time separability** — neither repo imports the other in-process; every touchpoint is a CLI subprocess or a flat file | bidirectional | `assistant-framework` | n/a | spec 036 US3, a P1 invariant whose stated Independent Test is a manual grep of both codebases | **Review-time only** — this one is currently true, and nothing would tell us if it stopped being true |

### `platform-constitution.md` is retired

It is cited in this repo at `specs/051-post-revival-hardening/spec.md:105` and `:438`, in
`assistant-framework`'s `docs/TODO.md`, and in `JoaoOliveira.eu`'s `docs/roadmap.md`. It
exists in none of the three repos, and no absolute path any of them gives resolves.

There is no platform constitution and there will not be one. Per Principle XI, contracts
live in the repos that participate in them; a platform-wide constitution is the shared
fourth repo under another name. The failure record it was supposed to hold is
§ Failure Record Reference below, which is this repo's own.

The sibling repos reached the same place independently: `consumer_pipeline` retired the
citation for itself in its PR #227, after checking all ten citing lines across the three
repos; `JoaoOliveira.eu` states the mirrored-contracts obligation as its Principle VI in
PR #82. This amendment retires it for research-framework. Spec 051's two citing lines are
frozen spec text and are left as written — read them as pointing here.

## Boundary System

### Always Do

These actions require no approval. Apply whenever relevant.

- Run the framework's own `pytest tests/scripts/` before reporting any Phase 1 completion.
  The automatic gate (`cli/_common._run_phase1_gate`) runs this only from a source
  checkout — from an installed wheel it skips, so there the obligation is the operator's
- Add `--dry-run` flag to every script that modifies vault files
- Update `coverage-targets.json` after every research cycle
- Check for existing notes before creating new ones
- Read the template from `_templates/{type}.md` before writing any note
- Use the `proposed_filenames` field from scout JSON to prevent naming conflicts
- Report validation failures with the specific file path and field name
- Write tests before or alongside every new script (TDD)
- Run `python scripts/guards/parser_flag_consumers.py --list` when adding a CLI flag, and
  name the non-CLI consumer in the PR — or refuse the flag with exit 2 until one exists

### Ask First

These actions have high impact or are hard to reverse. Pause and confirm.

- Changing the Phase 1/2/3 execution sequence
- Modifying validation exit codes (0/1/2) or their semantics
- Adding or removing required fields from the frontmatter schema
- Changing the naming convention for vault note files
- Modifying `coverage-targets.json` structure (breaking change for existing vaults)
- Adding external dependencies (especially any that touch the network at runtime)
- Changing how `validate_cycle.py` evaluates Condition B (termination)

### Never Do

Hard stops. No exceptions.

- **Never allow Phase 2 to begin if `pytest` has not passed.** This gate exists because
  scripts that haven't been tested corrupt vaults silently. The failure mode has already
  occurred — 71 files were damaged by an untested fix script (F7), and a weekly phase
  rewrote seven live vaults (F9). The rule is not optional; the *automatic* gate is
  narrower than the rule. `_run_phase1_gate` skips from an installed wheel and `--skip-gate`
  bypasses it, so on those paths the obligation falls on whoever ran the command.
- **Never treat cycle TERMINATE as Phase 1 complete.** TERMINATE means the BFS/DFS loop
  found nothing new. It does not mean the vault meets its coverage targets.
- **Never let an agent self-assess its own validation output.** `validate_vault.py`
  returning exit code 0 is a validation pass. An agent's assessment is not.
- **Never skip the `--dry-run` test before running a fix script on real vault data.**
  Fix scripts that run without dry-run testing on fixtures have a documented history of
  producing cascading damage.
- **Never write a script as a placeholder.** Every script listed in Phase 1 output must
  contain working implementation code.
- **Never let a validation, verification, check, audit or gate step write to what it
  reads.** Repair is a separate, opt-in, operator-invoked verb, and it goes through the
  canonical codec for the format it edits.
- **Never use external libraries or services that persist data outside the host machine.**
  research-framework must be fully operable offline.
- **Never create two notes for the same concept.** Use `proposed_filenames` in scout JSON
  as the coordination mechanism.
- **Never allow external sources to be skipped without a logged reason.** They are required
  for Condition B termination.
- **Never accept a flag, key or field the framework does not consume.** Wire it to a
  consumer or refuse it with exit 2 naming the surface that works. And never let a failed
  or skipped phase end below the severity the operator's log level shows: a non-zero exit
  says why on stderr and names the record (XIII).
- **Never ship a model-backed capability with no self-hosted provider path.** The local
  option may be slower, smaller or degraded; it may not be absent, and a release without a
  local settings profile in the wheel and the bundle is incomplete (XIV).

## Immutable Architecture Decisions

These decisions are made. Do not revisit them without an ADR.

### Two-Layer Vault Architecture

Every vault research-framework generates has exactly two layers:

- **Layer 1 — Query/Routing**: `AGENTS.md`, `_index.md`, `_concepts.md`, `_graph.md` —
  structured index files. Agents read them first. Simple queries may be answered from Layer 1
  alone. Rebuilt after research cycles.
- **Layer 2 — Full Vault**: Obsidian-compatible notes with frontmatter, wikilinks, citations
  in `data_vault/` subfolders.

Layer 1 is always a projection of Layer 2. They are never independent.

### BFS → DFS → Repeat Research Model

Research proceeds as: scout (BFS) → validate → research (DFS) → validate → repeat up to
`max_cycles`. Validation between phases is not optional. A cycle that skips either validation
gate is incomplete.

Termination condition B (no new topics) requires ALL of:

- Scout reports 0 new topics
- 0 unresolved wikilinks in vault
- All 5 search dimensions covered in most recent BFS
- All required sources from spec consulted at least once
- All mandatory Jira targets met (if spec includes a Jira project)
- At least one external source (web/market) consulted during cycle set

Every sub-condition must be true. Any false sub-condition means the loop continues.

### Five Search Dimensions

Every BFS scout MUST address all five dimensions. Missing a dimension is a scout failure
that `validate_cycle.py` catches and rejects (exit code 2).

| Dimension | What it covers |
|-----------|----------------|
| Technical | Services, APIs, data flows, system architecture |
| Organizational | Teams, capabilities, org structure, decision flow |
| Domain | Industry fundamentals, terminology, concepts |
| Market | Competitors, market context, customer behavior |
| Temporal | Planned changes, migrations, historical decisions |

The domain and market dimensions are NOT secondary. A vault without industry fundamentals
and competitive context is incomplete regardless of how many internal notes it has.

### Coverage Targets as Phase Completion Gate

`coverage-targets.json` is written at Phase 1 from the spec and updated after every
research cycle. Phase 3 MUST NOT begin until all targets are met. If cycles terminate with
unmet targets, the generator re-enters Phase 2 with a targeted prompt for the missing
categories.

**Dynamic extension via backlog promotion.** Spec authors cannot enumerate every concept
the vault will need — most legitimate concepts only emerge once the agent starts writing
notes and cross-linking them. To prevent the gate from declaring "done" while obvious gaps
remain, `scripts/topic_harvest.py` runs at every cycle tail and:

1. Walks every note's body and `related:` frontmatter, collecting unresolved wikilinks.
2. Ranks them by citation count (how many notes reference each one).
3. Auto-promotes any orphan cited at or above the configured threshold (default: 2 notes)
   into `coverage-targets.json` as a new `CoverageCategory` with `note_type: concept` and a
   `target_count: 1`. Promotions are idempotent — re-running the harvester adds no
   duplicates.
4. Writes the residual (low-citation) backlog to `_pipeline/research-backlog.md` so the
   next scout still sees them as candidate topics.

The threshold is tunable per-vault via `settings.yaml` (`pipeline.backlog_promotion_threshold`).
Setting it to a high number disables auto-promotion and reverts to spec-only targets;
setting it to 1 makes every orphan a target (rarely useful — produces noise).

This means Phase 3 advances only when the spec's original targets AND the emergent
high-citation targets are all written. "All targets met" therefore tracks vault maturity,
not author foresight.

### Script Exit Code Model

All scripts exit with a documented code:

- `0` — pass / CONTINUE
- `1` — fail / TERMINATE (structural: cycle is done, move on)
- `2` — abort (error: fix before proceeding)

Exit code 1 from `validate_cycle.py` after a report with no new topics is expected, not an
error. Exit code 2 means a structural problem — broken JSON, missing required fields, naming
conflict.

## Technology Constraints

- **Python** for all research-framework scripts and CLI. Type hints required. Formatted with
  `ruff format` (black-compatible, 88 chars — `ruff format --check` is what `ci.yml`,
  `build.sh` and `docs/RELEASE.md` run; `[tool.black]` in `pyproject.toml` remains for
  editors). Linted with `ruff check`. Tested with `pytest`.
- **No external runtime dependencies** for core functionality. Standard library plus
  explicitly declared dependencies in `pyproject.toml` only.
- **MCP server wrapper (Phase 3 only, if ever built)**: Java with Spring Boot. Not to be
  revisited without an ADR.
- **Git** is available but not required at runtime. research-framework runs `git init` in Phase 3 but
  does not depend on git for its own operation.
- **An external agent runtime** does Phase 2's model work. The five runtimes are the ones
  spec 078 records (FR-006, FR-007): `claude`, `codex`, `cursor-agent` and `opencode` as
  CLI subprocesses, and `ollama` over HTTP. At least one of them MUST be self-hosted
  (Principle XIV); today `ollama` is, and `opencode` reaches local providers. The
  `./vault research` command (via `cli/research.py` → `cycle_runner.run_cycle_steps`)
  dispatches through `scripts/agent_call.py` with the appropriate prompt and flags, and
  that module's `_LLM_AGENT_NAMES` is the registry the dispatch guards derive from.
  research-framework does not embed its own model calls — it orchestrates an external agent.

## Note Quality Bar

A note is not complete unless ALL of these are true:

- [ ] Follows the template section structure for its type (read `_templates/{type}.md`)
- [ ] 200+ words (non-MOC notes)
- [ ] Answers the type-specific contextual questions (why/how/who — see spec)
- [ ] All acronyms wikilinked on first occurrence in body
- [ ] At least one source URL in frontmatter
- [ ] `summary` ≤ 120 chars and specific (not "A note about X")
- [ ] `related` field populated from wikilinks in body
- [ ] Filename matches `proposed_filenames` from scout JSON

A note failing any check is flagged by `validate_vault.py` as an error. Errors block cycle
completion.

## Failure Record Reference

F1–F8 occurred during the system that research-framework is designed to replace. F9 and
F10 occurred in research-framework itself, on the same day. Every principle above is
downstream of one of them.

Earlier versions of this document said F1–F8 were "documented in
`vault-generator-framework.md` (§ Failure Record)". That document is not in this repo and
no copy has been found. **This table is the record.**

| Code | Failure | Key constraint derived |
|------|---------|------------------------|
| F1 | Content created before pipeline | `pytest` gate blocks Phase 2 (I) |
| F2 | Scripts listed but not implemented | No placeholder scripts (VIII) |
| F3 | Parallel agents created duplicate notes | `proposed_filenames` in scout JSON (VI) |
| F4 | Summary overflow not caught | `validate_vault.py` checks summary length |
| F5 | External sources never reached | External sources required for Condition B (VII) |
| F6 | TERMINATE confused with done | `coverage-targets.json` gates Phase 3 (II) |
| F7 | Preconditions skipped | Hard gate enforced by script, not agent (I, III) |
| F8 | Agents self-assessed validation | Scripts validate; agents report (IV) |
| F9 | A phase named "verify" rewrote what it graded | Inspection does not mutate (XII) |
| F10 | Seven vaults failed and reported nothing; flags and keys were accepted and ignored | Nothing is accepted and ignored (XIII) |

### F9 — the verify phase destroyed what it inspected (2026-09-01)

Two defects compounded.

**It wrote through the wrong serialiser.** `processors/verify.py` read notes with
`_common.parse_frontmatter` — a line-scalar parser whose own comment scopes it to
`_pipeline` raw items — and wrote them back with a hand-rolled emitter. One auto-fix on a
real note emptied every list field (`tags`, `related`, `source_urls`, `owns`, `reads`),
turned `tags: [a, b]` into the string `"[a, b]"`, hoisted a key out of a list-of-mappings
to top level, and let a nested `title:` overwrite the note's real title.

**It graded files that are not notes.** `_drive_verify` called `verify()` on the vault
ROOT with auto-fix defaulted **on**, excluding only three directories. On a freshly
generated vault containing *zero notes*, it graded 18 files and rewrote all 18 —
`.claude/commands/*.md`, `CLAUDE.md`, `README.md`, `research.spec.md`, the index files —
and returned FAIL. A fresh vault failed its own verify phase.

**The operator's two defences were inert.** `--no-fix` and `--fail-threshold` both resolved
through `cfg.get(key, param)`, which always found the key in `PROCESSOR_DEFAULTS`, so both
parameters were dead and both flags did nothing.

**Blast radius.** It ran weekly against eight real vaults. Seven show the mutation
signature; `feeds-vault`'s `research.spec.md` lost about 171 lines — every YAML comment and
everything the line parser could not represent. Only the archived vault was clean, and only
because it refuses every writing path.

**Why the tests did not catch it.** `tests/pipeline/test_runner.py` mocked
`processors.verify.verify` out entirely, and `test_auto_fix_adds_status` asserted on a
counter and a substring rather than re-parsing the file. Both tests passed throughout.

Fixed in PR #210: the phase grades the corpus rather than the vault root, runs with
`auto_fix=False` because a phase named "verify" reports rather than mutates, both
directions go through the canonical codec, and the regression tests assert byte-identity of
the files that must not change.

The lesson is narrower than "test better", and it is the one worth enshrining: **a phase
whose name is a promise to the operator has to keep it.** An operator runs a verifier
precisely because it is safe to run. One that edits is an unreviewed migration executing
weekly on unattended data, and the fact that a `--no-fix` flag existed made it worse, not
better — it advertised a safety that had never worked. Hence Principle XII, and hence XII's
requirement that a read-only assertion be a byte-identity assertion: that is exactly the
assertion the pre-existing tests lacked.

### F10 — the same run failed in silence, and its knobs did nothing (2026-09-01)

F9 is why seven of eight vaults failed verify that day. F10 is why nobody could read the
failure, and why the operator's own settings would not have helped if they had.

**The failure was recorded and never spoken.** Every `_drive_*` driver in
`pipeline/runner.py` wrote its `errors` into `pipeline-state.json` and logged nothing above
`INFO`. `cli/_log_level` drops to `WARNING` when stdout is not a TTY — which is every
cron, launchd and systemd run, i.e. every weekly run — so a failing run emitted **zero
bytes**. The only thing on stderr was the spec-070 FR6 backstop, which called it a
framework bug and pointed at `_pipeline/run-report.md`, a file the pipeline runner has
never written. Spec 070 FR6 ("every non-zero exit MUST write a diagnosable message to
stderr") had been marked DONE since 1.0.0.

**The reason was empty even in the record.** `processors/verify.py` computed its verdict
and never appended a single string to the `errors` list it declared; `_drive_verify`
extended from that empty tuple and discarded `result.report`, the only carrier of
per-note detail. The byte shape on seven vaults was `status: failed`, `errors: []`,
`summary: {verdict: FAIL, notes_checked: N}`, `started_at == finished_at`.

**Phases were "done" having done nothing.** The scout, research and report phases were
recorded `done` on the agent's exit code alone. reference-vault's research phase ran for 34
seconds, wrote no notes, and is recorded `done`. `collect` reported `done, items_new=0`
on 7 of 7 vaults because every declared source needed a collector the version did not
have, logged at `INFO`. The agent call had no timeout, no process-group isolation, and
under `--quiet` captured the agent's output and threw it away.

**The knobs were decorative.** `pipeline --budget-cap` was accepted, documented as
forwarded, and read by nothing — the fifth instance of a class the 1.1.0 CHANGELOG had
already named four times (`url:`, `--target-topics`, `source_policy: hard`,
`vault.corpus_dir` are the earlier finds), and PR #210 had just found `verify`'s
`--no-fix` and `--fail-threshold` in the same state (F9's "two defences were inert").

**Why the tests did not catch it.** No test exercised `_drive_verify`'s FAIL path: every
`VerifyResult` fixture carried `verdict='PASS'`, so the exact live failure mode — FAIL →
phase FAILED, with what error content, at what severity — was unpinned, and the
empty-`errors` defect survived long enough to be filed as an issue.

Fixed across #317, #318, #321, #327 and #329: one `_close_phase` helper is the only place
a phase ends, and it reports FAILED at ERROR and SKIPPED at WARNING naming the absolute
path of the state file, `--quiet` notwithstanding; a verify FAIL states its cause and
writes the full report to `_pipeline/logs/verify-<timestamp>.json`; a phase is done when
its artifact exists, parses and carries the field the next phase reads; the agent call
runs under a wall-clock bound with its output tee'd to `_pipeline/logs/`; `--budget-cap`
is refused with exit 2 until a consumer exists; and `scripts/guards/parser_flag_consumers.py`
fails the build when any parser flag never leaves `cli/`.

The lesson is the one XII's paragraph almost said and F10 forces: **an operator can only
act on what the framework tells them, and only rely on what it actually reads.** A
diagnosis that lives in a JSON file under a `WARNING` default has not been reported. A
flag that parses and is never consumed is a promise in the `--help` text that the code
does not keep. Hence Principle XIII, and hence its two halves: accepted means consumed,
and recorded means spoken.

## Out of Scope for This Constitution

The following are governed by the artifacts named below, not by this constitution. They can
change without a constitution revision.

Earlier versions delegated all of this to a spec called `vault-generator-framework.md`.
That document is not in this repo. **A delegation to a missing document is worse than no
delegation** — it reads as authority and resolves to nothing — so each concern now names
the authority that actually exists today.

| Concern | Current authority |
|---------|-------------------|
| Cycle-report JSON shape | `scripts/validate_cycle.py`, plus the per-spec `specs/NNN/contracts/*.schema.json` for that report |
| Validation rules inside each script | the script's own module docstring, pinned by `tests/scripts/test_<script>.py` |
| Required frontmatter fields, note types and template section headings | **Spec 079** (`specs/079-note-format/spec.md`, the record of the on-disk contract); `REQUIRED_FIELDS` in `scripts/validate_vault.py`; parse and emit by `src/research_framework/vault/frontmatter.py` — the canonical codec (spec 025 B4), the only sanctioned reader/writer for note frontmatter; `templates/note-type.md.j2` and the generated vault's `_templates/` |
| Run-control defaults — budget, max cycles, depth thresholds — and the `settings.yaml` schema | **Spec 076** (`specs/076-settings-schema/spec.md`); `settings.yaml` and its per-runtime siblings; `src/research_framework/pipeline/settings.py`; per **ADR-0011** (operational config lives in settings, not the spec) |
| CLI verbs, flags, output format and exit-code semantics | **Spec 077** (`specs/077-cli-contract/spec.md`); `src/research_framework/cli/`; the Script Exit Code Model above governs the scripts, 077 governs the verbs |
| LLM dispatch — runtimes, their command shapes, sidecars, cost provenance | **Spec 078** (`specs/078-dispatch-surface/spec.md`) and `scripts/agent_call.py`, the single dispatch surface Principle IV names |
| The weekly pipeline runner — its phases, `pipeline-state.json`, resume and exit semantics | **Spec 075** (`specs/075-pipeline-runner/spec.md`) and `src/research_framework/pipeline/runner.py` |
| Vault spec file format | `.agents/skills/vault-spec/SKILL.md` and `src/research_framework/spec/schema.py` |

**This constitution MUST NOT delegate to a document that does not exist.** If an authority
in this table is deleted or renamed, this table is amended in the same PR.

## Governance

This constitution supersedes all other practices, specs, and plans when conflicts arise.

**Amendment procedure**:
1. Immutable Architecture Decisions require an ADR before any change.
2. All other amendments require a version bump and a Sync Impact Report prepended as an
   HTML comment at the top of this file.
3. Dependent templates (plan, spec, tasks) MUST be reviewed and updated when principles
   change. The Sync Impact Report records each one by name, with its verdict.
4. **An amendment that touches a principle MUST re-verify that principle's row in the
   § Enforcement Register against the code, in the same PR.** Every row is a claim about
   the tree on the date of the amendment; unverified, it decays into the thing this
   amendment was written to remove.
5. **An amendment that changes a contract in § Cross-Repo Obligations MUST name the sibling
   repo's mirrored copy and say whether it changed.** Contracts are mirrored, not shared
   (Principle XI); a one-sided change is a divergence with a version number on it.

**Versioning policy** (semantic):

- **MAJOR**: Backward-incompatible governance or principle removals/redefinitions.
- **MINOR**: New principle or section added, or materially expanded guidance — **and any
  enforcement downgrade**: discovering that a mechanism this document claimed never ran,
  could not fail, or was narrower than the principle it was cited under. Finding out a rule
  was never enforced is material, not cosmetic. The Enforcement Register moves with it.
- **PATCH**: Clarifications, wording, typo fixes, non-semantic refinements.

**Evidence rule**: every row of Principle I's gate table and of the § Enforcement Register
MUST cite the artifact that fails, by path. A row that cannot name one is written as
"Review-time only" or "Not met". A row claiming an enforcer that cannot fail is worse than
one admitting there is none — it converts an open gap into a closed one on paper only.
"Runs in the gate" means: the artifact is reached by `scripts/guards/run_all.py` or by
`pytest -m "not e2e"`, the local battery this repo merges on; an artifact reached only by
the `e2e` tier, by `build.sh`, or by a human checklist MUST say so in its row. When CI
regains a PR trigger, this sentence is amended, not silently outgrown.

**Compliance review**: All agents working on the research-framework codebase MUST read this
constitution before any spec, plan, or implementation. Plan compliance is verified during
the Constitution Check step in `.specify/templates/plan-template.md`, which carries one
gate per principle.

**Version**: 1.6.0 | **Ratified**: 2026-04-16 | **Last Amended**: 2026-09-08
