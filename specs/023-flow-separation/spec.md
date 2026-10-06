# Feature Specification: Flow Separation + Multi-Vault + Assistant-Framework Integration

**Feature Branch**: `023-flow-separation`
**Created**: 2026-05-22
**Status**: SHIPPED 0.4.0 Phase 1 (2026-05-27, impl PR #30 squash on main; first feature shipped under the foreman verification pattern of ADR-0010; released via the Wave 1 recovery bump PR #34). Phase 2 remains deferred to post-Revival (ROADMAP queue #10). Phase 1 delivered: `./vault refresh-sources` (FR-013), `./vault regenerate-shim` (FR-014), `<vault>/scripts/` survives `./vault update` via `apply_vault_scaffold_update` + `_pipeline/scaffold-manifest-snapshot.json` (FR-015), and the `pipeline/atomic_write` canonical writer migration (FR-018) — every cycle-JSON writer in the pipeline (across `research`, `postprocess`, `scout`, `verifier`, `wikilinks`, `runner`, `research_plan`, `plan_narrator`, `timings`, `topic_harvest`, `validate_cycle`, `probes`, and `_cycle_helpers`; 13 call sites total) now delegates to `atomic_write`, closing the `JSONDecodeError`-on-concurrent-read class of bugs. Phase 2 scope (US2 `VaultHandle`, US3 `active-sources.json`, US4 `.local.md`, FR-009/010/011/012/016/017) remains deferred to post-Revival. Pre-implement reconciliation (PR #27) addressed 1 HIGH finding before implementation.
**Input**: User description: "Spec 023 slot has been reserved on ROADMAP since 2026-05-20 as the consolidation point for pre-018 specs 010 (flow separation) and 012 (multi-vault). Captures the long-horizon 'research-as-a-service' architecture: research-framework as a service that takes a spec and produces/refreshes a vault; the vault as a passive portable artifact (self-contained, queryable without the framework present); and assistant-framework (sibling project) as the query+workflow layer that composes across multiple vaults via subprocess calls to `./vault ask` / `./vault write`. Extract VaultHandle, harden `./vault` script as the stable public interface, document the assistant-framework integration surface, audit any code that assumes single-vault."

## Clarifications

### Session 2026-05-26

- Q: Minimum-subset carving for the Feeds-Vault Revival Sprint — separate sub-spec, dedicated Phase 1 section, FR additions to US1, or no spec change? → A: **Promote the 3 minimum-subset items into US1's Functional Requirements (FR-013/FR-014/FR-015)** and add a `## Implementation phasing` section that stages Phase 1 (revival = US1 + FR-013/014/015 + FR-018 — the latter added during Q5 to codify the atomic-write contract that read-only `./vault ask` relies on) first, with US2 (`VaultHandle`) / US3 (`active-sources.json`) / US4 (`.local.md`) and the long-horizon FRs (FR-009/010/011/012/016/017) deferred to Phase 2. One spec, one acceptance story, phased delivery. Avoids the doc fragmentation that 015a-h produced.
- Q: Cross-repo contract ownership — where do FR-009's integration test + FR-011's `docs/integration/assistant-framework.md` live? → A: **Both live canonically in `research-framework`** as the contract owner. `assistant-framework` MAY add a consumer-side mirror test that wraps the framework's fixture, but the canonical contract owner is whoever publishes the verb surface — that's the framework. Mirrors the standard "owner publishes, consumer mirrors" pattern (e.g., HTTP API specs live with the server, not the client). FR-009 + FR-011 updated to lock framework-side ownership; `assistant-framework` consumer mirror flagged as optional follow-up.
- Q: Stale-spec `./vault ask` policy — warn-and-continue, block-with-exit-2, auto-refresh, or JSON-only signal? → A: **Warn + continue.** Compute SHA-256 of `research.spec.md` at last successful `./vault update` (store in `_pipeline/spec-fingerprint.json`); on every `./vault ask` invocation, compare against current spec hash. On mismatch: emit stderr warning + add `warnings: ["stale_spec"]` to `--json` payload; still return the answer with the existing vault state. Rationale: the framework's posture for all recoverable inconsistencies is "observe, warn, let the operator decide" (ADR-0005 wikilink normalization, source preflight handling, verifier rejection of individual notes all follow the same pattern). Blocking is too aggressive for a read-mostly verb; auto-refresh would conflict with Principle V + the cost-cap story (a stale-spec auto-refresh could trigger a multi-dollar regeneration without consent). New FR-016 added.
- Q: In-loco modules policy for non-source vault-local code — preserve-indefinitely, registry-file, deprecate-and-prune, or no-formal-policy? → A: **Deprecate-and-prune with a safety net** (Option C). The framework maintains `_pipeline/in-loco-modules.json` tracking every vault-local file with `name`, `hash`, `status` (`active` / `deprecated` / `archived`), and optional `replacement_target` (from a `# REPLACEMENT_TARGET:` comment OR detected by the framework when an official module ships matching the file's role). Lifecycle: **active** files survive `./vault update` unchanged (Phase 1 FR-015 guarantee); when the framework detects a shipped replacement, the entry flips to **deprecated** and `./vault update` emits a warning each run; after `deprecation_grace_runs` further updates (default: 2, configurable in `settings.yaml`), the framework MOVES the file to `_pipeline/in-loco-deprecated/<name>.py.<framework-version>` (NOT deleted — archived with provenance) and the entry becomes **archived**. Operator escape hatch: `settings.yaml` `keep_overrides: [<name>, ...]` permanently exempts a file from archiving (warning still fires; no auto-archive). Rationale: strongest hygiene story without sacrificing safety. The archived file is recoverable; the deprecation warnings are predictable across 2 ship cycles before action. Mirrors major-framework deprecation cycles (Django, Rails). New FR-017 added; FR-012 promoted from "policy doc" to "policy + manifest + lifecycle FR".
- Q: Lock contention — `./vault ask` while `./vault research` is mutating the same vault — succeed-current-state, advisory-lock-fail-fast, atomic-snapshot, or block-on-lock? → A: **Succeed using current state, no lock acquisition** (Option A). `ask` is read-only; the vault is filesystem-based; `sources.db` runs in SQLite WAL mode (already enabled) which handles concurrent reads natively; `research`'s per-note writes are atomic (write-to-temp + rename). Worst case during contention: `ask` reads against a vault mid-grow — that's a snapshot taken mid-flight, not corruption. Stricter consistency models (exit-2 on contention, advisory locks, atomic snapshots) are deferred to a future spec if real-world UX demands it — no such mode exists in the current `./vault` surface, and adding one would be its own design exercise. **Contract:** the `research` writer path MUST remain crash-safe (write-to-temp + rename) so partial files never appear to readers. New FR-018 codifies the contract.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — `./vault` script is a stable public CLI contract (Priority: P1)

External consumers (cron jobs, iOS Shortcuts, the sibling `assistant-framework` project, future MCP clients) need to invoke vault operations via a stable interface. Today the `./vault` script exists but its CLI surface, exit codes, stdout shape, and headless-vs-interactive detection are under-specified. Each external consumer that needs to integrate has to reverse-engineer the contract.

**Why this priority**: This is the load-bearing decoupling. Once `./vault` is a stable contract, multiple downstream consumers can integrate without coupling to the framework's Python internals.

**Independent Test**: Write a smoke test that invokes every documented `./vault` verb in headless mode (no TTY) from a subprocess and asserts:
- Exit code matches the documented semantics (0 = success, 1 = vault-cant-answer for `ask`/`write`, 2 = framework error)
- Stdout JSON shape matches the documented schema for verbs that support `--json`
- No TTY-only prompts appear

**Acceptance Scenarios**:

1. **Given** a generated vault, **When** an external script invokes `./vault ask "question" --json`, **Then** stdout is valid JSON with documented fields (`answer`, `citations`, `confidence`).
2. **Given** a vault that cannot answer the question, **When** the same invocation runs, **Then** exit code is 1 (vault-cant-answer) and stdout JSON has `answer: null` + a `reason` field.
3. **Given** a framework-side error (e.g., corrupt spec), **When** `./vault ask` runs, **Then** exit code is 2 + stderr explains the failure.
4. **Given** documented verbs (`research`, `health`, `audit`, `ask`, `write`, `update`, `query`, etc.), **When** an integration test enumerates them, **Then** each has documented headless behaviour + exit codes.

---

### User Story 2 — `VaultHandle` abstraction enables multi-vault operations (Priority: P2)

The current `orchestrator.run_cycles` takes a single `vault_dir`. Multi-vault use cases (assistant-framework querying N vaults, cross-vault source discovery) need a `VaultHandle` abstraction so the framework code doesn't assume single-vault.

**Why this priority**: This is the architecture change that enables `assistant-framework` integration. Without it, every cross-vault operation has to fork a new framework Python process.

**Acceptance Scenarios**:

1. **Given** a `VaultHandle(vault_dir)` constructor, **When** code paths read spec, sources, coverage targets, **Then** they go through `VaultHandle` methods (no direct file reads scattered across the codebase).
2. **Given** two `VaultHandle` instances pointing at different vaults, **When** they're used concurrently in the same Python process, **Then** there's no cross-contamination of cached state.

---

### User Story 3 — `_pipeline/active-sources.json` projection serves external readers (Priority: P2)

The vault's source state currently lives ONLY in `_pipeline/sources.db` (SQLite). Subprocess consumers reading `_pipeline/` directly cannot query SQLite. Add a deterministic JSON projection that gets written after every source preflight + source-quality update.

**Why this priority**: Hard prerequisite for assistant-framework integration (it reads `_pipeline/` files directly without spinning up Python). Surfaced via the 2026-05-20 triage item #25 (`docs/TODO.md#restoration-notes`).

**Acceptance Scenarios**:

1. **Given** a vault that has run ≥1 cycle, **When** an external consumer reads `_pipeline/active-sources.json`, **Then** the JSON is valid and contains all currently-active sources with their key metadata (name, URL, status, last citation cycle).
2. **Given** a source's status changes (preflight failed, archived, recovered), **When** the cycle completes, **Then** `active-sources.json` reflects the new status.
3. **Given** `sources.db` is the canonical store, **When** `active-sources.json` and `sources.db` are compared, **Then** they agree on active sources for any vault state (idempotent projection).

---

### User Story 4 — `.local.md` override mechanism is a supported customization surface (Priority: P3)

Specs 015e/015g introduced `.claude/commands/<name>.local.md` as the per-vault escape hatch for customizing agent commands. The decision needs to be FORMAL: this is the supported customization surface, framework templates regenerate `<name>.md`, the `.local.md` sibling wins when present.

**Why this priority**: Without a formal decision, users fork templates (drift) or lose useful local behaviour. Surfaced via the 2026-05-20 triage item #4 (`docs/TODO.md#restoration-notes`).

**Acceptance Scenarios**:

1. **Given** a vault with `.claude/commands/foo.md` (framework template) and `.claude/commands/foo.local.md` (user override), **When** Claude Code resolves the command, **Then** `foo.local.md` wins.
2. **Given** the framework regenerates `.claude/commands/foo.md` during `./vault update`, **When** the update completes, **Then** `foo.local.md` is untouched.

---

### Edge Cases

- ✅ **Resolved 2026-05-26 (Clarifications Q5)**: `./vault ask` against a vault concurrently mutated by `./vault research` succeeds using current on-disk state with no lock acquisition. The writer side (FR-018) guarantees atomic writes (write-to-temp + rename; SQLite WAL mode) so readers never see partial files. Stricter consistency (snapshots, advisory locks) is deferred.
- How does multi-vault state isolation work for `agent_call.py`'s sidecar writes (cycle paths differ; no global state, but verify)?
- ✅ **Resolved 2026-05-26 (Clarifications Q3)**: `./vault ask` against a stale spec emits a non-blocking warning (stderr + `warnings: ["stale_spec"]` in `--json`) but still returns the answer. See FR-016.
- ✅ **Resolved 2026-05-26 (Clarifications Q4)**: In-loco modules follow a deprecate-and-prune lifecycle with a safety net (FR-012 + FR-017). Vault-local files survive indefinitely while `active`; flip to `deprecated` when an official replacement ships (warning every update); auto-archive to `_pipeline/in-loco-deprecated/` after `deprecation_grace_runs` updates (default 2). `keep_overrides` in `settings.yaml` permanently exempts files. See `docs/TODO.md#restoration-notes` triage item #5 — this question is now fully resolved.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Every verb of the `./vault` script (`research`, `health`, `audit`, `ask`, `write`, `update`, `query`, `coverage`, `reindex`, `sync`, `maintain`) MUST have a documented exit-code contract: 0 = success, 1 = "the operation completed but the result is null" (e.g., vault can't answer), 2 = framework error, other = stage-specific.
- **FR-002**: Verbs that produce structured output (`ask`, `write`, `coverage`, `health`) MUST support a `--json` flag that emits a documented JSON shape to stdout.
- **FR-003**: All verbs MUST be invokable headless (no TTY required, no interactive prompts). When run in a TTY they MAY add interactive affordances, but the JSON / non-interactive behaviour MUST be authoritative.
- **FR-004**: `VaultHandle(vault_dir: Path)` MUST be the canonical accessor for: spec parse, sources, coverage targets, cycle state, settings. Direct file reads of these from outside `VaultHandle` SHOULD be migrated to it (audit during planning).
- **FR-005**: `_pipeline/active-sources.json` MUST be written after every source preflight, every source-quality update, and at cycle end. Schema: list of objects with `name`, `url`, `tier`, `status`, `last_cited_cycle`, `locked`, `consecutive_empty_cycles`.
- **FR-006**: `_pipeline/active-sources.json` MUST be a strict projection of `sources.db` — running a reconciliation script in `--check` mode MUST report no drift.
- **FR-007**: `.local.md` override mechanism MUST be documented in `dist-templates/install.sh` output, in `CLAUDE.md` for each generated vault, and in `docs/ARCHITECTURE.md`.
- **FR-008**: `./vault update` MUST detect `.local.md` overrides and skip overwriting them (consistent with spec 027 FR-006).
- **FR-009**: A reference integration test MUST exist in `research-framework` (canonical contract owner) demonstrating `assistant-framework`-style subprocess consumption: spawn N vaults, invoke `./vault ask` against each, aggregate results. The fixture is the source of truth for the multi-vault subprocess contract. `assistant-framework` MAY add a consumer-side mirror test that wraps this fixture, but that is OPTIONAL and tracked in `assistant-framework`'s repo, not gated by this spec.
- **FR-010**: Pre-018 specs 010 (flow-separation) + 012 (multi-vault) MUST be marked **Subsumed by 023** with a banner at the top of their `spec.md` files (no separate implementation effort planned).
- **FR-011**: A new `docs/integration/assistant-framework.md` document MUST exist in `research-framework` (canonical contract owner) explaining the subprocess contract, the JSON shapes, and the recommended consumer-side patterns. `assistant-framework` MAY link to it from its own README as a quick-start, but the canonical document lives with the contract owner. This file is the publish-side reference for any integration; the framework's `./vault` verb evolution rule is "this document MUST update in the same PR as any contract-affecting verb change".
- **FR-012**: An "in-loco modules" policy MUST be documented (in `CONTRIBUTING.md` or this spec's `data-model.md`): named middle state, vault-local features classified in `_pipeline/in-loco-modules.json` with `status` ∈ {`active`, `deprecated`, `archived`}, optional `replacement_target` (from `# REPLACEMENT_TARGET: <module>` comment in the file OR detected by the framework when an official module ships matching the file's role), `deprecation_grace_runs` (default 2; configurable per-vault in `settings.yaml`), and `keep_overrides` (list of file names permanently exempt from archiving). The policy section MUST explicitly state the lifecycle transitions defined in FR-017.
- **FR-013** *(Phase 1 — revival sprint)*: `./vault refresh-sources` MUST exist as a documented verb that invokes the vault's local `scripts/collect_*.py` collectors (per ADR-0009's preserved legacy surface), writes harvested data to `raw_data/<source>/`, emits a JSON summary on `--json`, and follows the FR-001 exit-code contract. This is the bridge verb that lets the Feeds-Vault Revival Sprint re-enable Reddit/YouTube/O'Reilly ingestion **before** spec 020 Phase 1 modules port.
- **FR-014** *(Phase 1 — revival sprint)*: `./vault regenerate-shim` MUST exist as a documented verb that re-renders `templates/vault-script.sh.j2` against the current `settings.yaml` and overwrites the vault's `./vault` script (the user-owned shim). Idempotent — running twice produces byte-identical output for the same settings. Resolves archaeology finding F2 (broken hardcoded macOS temp path; old `research_vault` package name baked into shims generated before the 0.2.33 rename).
- **FR-015** *(Phase 1 — revival sprint)*: Vault-local `scripts/*.py` files NOT recorded as framework-owned in `dist-templates/scaffold-manifest.json` MUST survive `./vault update` unchanged. Classification source of truth is `src/research_framework/pipeline/scaffold_diff.py` (existing module; checks the manifest's `is_user_owned_after_first_write` flag plus file-existence at vault root). The vault-side manifest (`_pipeline/scaffold-manifest.json` if/when written for cross-update tracking) MUST persist this classification across updates so the framework cannot accidentally re-classify a vault-local file as framework-owned on a later update. Resolves archaeology finding F6 (`collect_youtube.py` + `collect_oreilly.py` + `reddit_rss.py` survived the migration but only because the destructive copy was never triggered — there is currently no positive contract guaranteeing they survive a real update).
- **FR-016** *(Phase 2 — post-revival)*: `./vault ask` MUST detect stale-spec conditions and emit a non-blocking warning. Detection: SHA-256 of `research.spec.md` recorded at last successful `./vault update` in `_pipeline/spec-fingerprint.json`; compared on every `ask` invocation. On mismatch, stderr emits a single-line warning AND `--json` mode adds `"warnings": ["stale_spec"]` to the payload; the answer is still returned against the current vault state. Aligns with the framework's existing "observe, warn, let the operator decide" posture for recoverable inconsistencies (ADR-0005, source preflight, verifier rejections).
- **FR-017** *(Phase 2 — post-revival)*: `./vault update` MUST enforce the in-loco modules deprecation lifecycle defined in FR-012. **Transitions:** (1) `active` → `deprecated` when the framework detects a shipped official replacement (matching `replacement_target` annotation OR framework-inferred via file role); `./vault update` records `deprecated_since_version` and emits a stderr warning naming the replacement. (2) `deprecated` → `archived` after `deprecation_grace_runs` further `./vault update` invocations; the file is MOVED (not deleted) to `_pipeline/in-loco-deprecated/<name>.py.<framework-version>`. (3) Files named in `settings.yaml`'s `keep_overrides` list MUST NOT auto-archive even after the grace runs elapse; warnings still fire. (4) `archived` files MUST NOT be re-introduced by `./vault update` (the manifest serves as the system-of-record). All transitions MUST be logged in `_pipeline/in-loco-modules.json` with timestamps.
- **FR-018** *(Phase 1 — revival sprint)*: The `./vault research` writer path MUST remain crash-safe so concurrent readers (`./vault ask`, `./vault query`, external subprocess consumers) never observe partial files. Specifically: (a) per-note writes MUST use write-to-temp + atomic `os.rename`; (b) `_pipeline/sources.db` MUST stay in SQLite WAL mode (already enabled); (c) `_pipeline/cycles/cycle-NNN-*.json` writes MUST be atomic (temp + rename). No lock file is required — the contract is "writes are atomic, reads succeed against whatever state exists at read time". `./vault ask` and `./vault query` MUST NOT acquire locks; they read whatever current state is on disk. Stricter consistency models (snapshot reads, advisory locks) are deferred to a future spec.

### Key Entities

- **`VaultHandle`**: Programmatic abstraction over a single vault. Methods: `spec()`, `sources()`, `coverage_targets()`, `cycle_state()`, `settings()`. Stateless beyond per-call file reads.
- **`./vault` script verbs**: Public CLI contract. Each verb is documented with: argv shape, exit-code semantics, stdout shape (text and JSON), env vars consumed, side effects on the filesystem. Phase 1 ships the existing verbs (FR-001) PLUS the two new revival-sprint verbs `refresh-sources` (FR-013) + `regenerate-shim` (FR-014).
- **`active-sources.json`**: Read-mostly projection of `sources.db`. Format: documented JSON schema; one entry per source.
- **`.local.md` overrides**: Per-vault command customization. Resolution: `<name>.local.md` wins over `<name>.md` when Claude Code / Codex loads the file.

## Implementation phasing

This spec is intentionally scoped to span two ship cycles. The
`/speckit.plan` stage MUST honor this phasing — do not lump Phase 2
work into Phase 1 tasks.

### Phase 1 — Feeds-Vault Revival Sprint (target: end of revival sprint, 2026-Q2)

Scope: **US1 only** (`./vault` script is a stable public CLI contract),
PLUS the three minimum-subset FRs that unblock the revival sprint:

- **US1** acceptance scenarios (exit codes, `--json` headless behavior,
  documented verbs for the EXISTING surface).
- **FR-013** `./vault refresh-sources` verb.
- **FR-014** `./vault regenerate-shim` verb.
- **FR-015** vault-local `scripts/` survive `./vault update`.
- **FR-018** atomic-write contract for the research writer path (load-bearing for the multi-vault subprocess story; trivial to verify since it already mostly holds — just needs a positive test).

Ship criteria for Phase 1 (concrete; do NOT defer to a tracked
external doc — `MONDAY.md` is operator-local and gitignored):

1. **`./vault refresh-sources` ships and works for feeds-vault.**
   Invokes `scripts/collect_youtube.py` (or other present
   collectors) successfully against the operator's live feeds-vault;
   writes harvested data under `raw_data/<source>/`; reports a
   JSON summary on `--json` mode; exit code 0 on success, 1
   on partial collector failure, 2 on framework error.
2. **`./vault regenerate-shim` ships and is idempotent.**
   Running it twice in succession against the same `settings.yaml`
   produces byte-identical `./vault` script output (covered by
   a unit test). Re-running on a vault whose shim has a stale
   hardcoded macOS temp path (archaeology finding F2) repairs it
   in-place without operator intervention.
3. **Vault-local `scripts/*.py` survive `./vault update`.**
   A regression test creates a vault with a known-vault-local
   `scripts/custom_collector.py`, runs `./vault update`, and
   asserts the file is byte-identical post-update.
4. **The research writer path is atomic.** A test that runs
   `./vault research` concurrently with `./vault ask` (multiple
   asks during a research cycle) MUST NOT observe any partial
   file content. Verified by inserting `os.fsync`-aware
   assertions around per-note writes and around
   `sources.db` access.
5. **End-to-end revival demo.** Feeds-Vault produces ≥3 new notes
   in one cycle using the framework + legacy collectors,
   captured in `_pipeline/cycles/cycle-N-*.json` and validated
   against the existing `dist-templates/scaffold-manifest.json`
   layout.

### Phase 2 — Post-revival hardening (target: TBD, after revival ships)

Scope: **US2, US3, US4** + the long-horizon FRs:

- **US2** + **FR-004**: `VaultHandle` extraction + call-site migration.
- **US3** + **FR-005** + **FR-006**: `_pipeline/active-sources.json`
  projection of `sources.db`.
- **US4** + **FR-007** + **FR-008**: `.local.md` override mechanism
  formalization.
- **FR-009**: cross-repo integration test fixture/contract.
- **FR-010**: subsume banners on 010 + 012 (mechanical; defer).
- **FR-011**: `docs/integration/assistant-framework.md` document.
- **FR-012**: in-loco modules policy doc.
- **FR-016**: `./vault ask` stale-spec warning + `_pipeline/spec-fingerprint.json`.
- **FR-017**: in-loco modules deprecate-and-prune lifecycle (manifest + grace runs + archive directory).

Phase 2 is intentionally drafted but not staffed during the revival
sprint. `/speckit.plan` for Phase 2 happens AFTER Phase 1 ships.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A consumer can implement an `assistant-framework`-style integration in <1 day by reading only `docs/integration/assistant-framework.md` (no need to read framework source).
- **SC-002**: An integration test demonstrates ≥3 concurrent `VaultHandle` instances operating on different vaults without cross-contamination.
- **SC-003**: `_pipeline/active-sources.json` is a strict projection of `sources.db` — running `python scripts/check_active_sources_projection.py` returns "no drift" on any cycle state.
- **SC-004**: Every `./vault` verb has a test that exercises its `--json` headless contract (when applicable) + a test that verifies its exit-code semantics.
- **SC-005**: A user with a `.local.md` override survives 5 simulated `./vault update` runs without losing the override.

## Assumptions

- `assistant-framework` is a sibling project under active development (path: `~/src/assistant-framework`). The integration surface is mutually agreed between the two projects; this spec owns the contract definition.
- Flat-file interfaces are non-negotiable (Principle V / offline-first). Never an in-process Python API call from outside the framework.
- Multi-vault parallel cycles in the same Python process are NOT a requirement of this spec — the requirement is multi-vault `./vault` subprocess invocations.
- The `.local.md` mechanism already works at the Claude Code level (it's a Claude Code feature); this spec just formalizes the framework's commitment to preserving them.
- The `VaultHandle` extraction is incremental: ship the abstraction; migrate call sites over time; some legacy direct-file-reads MAY persist as documented holdouts.

## Dependencies

- Spec 026 (fixture isolation) — needed for multi-vault tests to not pollute each other's fixtures.
- Spec 027 (vault update hardening) — overlaps in `.local.md` preservation and scaffold-manifest honor.
- Soft on spec 020 (source-module architecture) — `active-sources.json` schema must align with what 020's source modules produce.
- Out: spec 022 v3 (quality v3) — overlaps in the cross-vault `/ask` comparison metric but they're independent ships.

## Acceptance coverage

Draft — evidence cells will be populated by `/speckit.tasks` for
this spec. Listed for the ADR-0008 guard so the spec is accepted
into the queue (the guard refuses any G/W/T-bearing spec without
this section).

| User Story | Evidence |
|------------|----------|
| US1 — `./vault` script is a stable public CLI contract | _(deferred to tasks.md — populated by `/speckit.tasks`)_ |
| US2 — `VaultHandle` abstraction enables multi-vault operations | _(deferred to tasks.md — populated by `/speckit.tasks`)_ |
| US3 — `_pipeline/active-sources.json` projection serves external readers | _(deferred to tasks.md — populated by `/speckit.tasks`)_ |
| US4 — `.local.md` override mechanism is a supported customization surface | _(deferred to tasks.md — populated by `/speckit.tasks`)_ |

## Out of Scope

- Implementing `assistant-framework` itself. It's a sibling project; this spec defines the CONTRACT it consumes.
- Daemon mode for the research engine. Stays CLI-invokable.
- Cross-vault source sharing in v1. Each vault owns its `sources.db`. Opt-in cross-vault discovery is Horizon 4.
- New `./vault` verbs (e.g., `./vault publish`). Stick to the existing surface; add new ones as separate specs.
