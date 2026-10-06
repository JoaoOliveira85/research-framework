# Feature Specification: Autonomous-Mode Backend Defaults

**Feature Branch**: `042-autonomous-mode-backend-defaults`
**Created**: 2026-05-27 (promoted from `docs/ROADMAP.md` Horizon 2 "Autonomous-mode defaults across LLM backends" during post-Wave-1 doc restructure).
**Status**: planned — DRAFT (full spec; awaiting `/speckit.clarify` on 3 open questions). Soft-coupled with spec 047 (backend-agnostic agent layer) — this spec sets per-backend defaults; 047 abstracts over them.

**Input**: A per-vault `autonomy_level: interactive | semi-auto | full-auto` setting that drives the scaffolder to write sensible "auto" defaults across all generated LLM backend configs (Claude Code, Codex, Ollama). The follow-on to spec 007 (which pre-authorised specific tool *calls* but deliberately stopped short of setting the default *mode*). Without this, users have to manually flip auto-accept mode at the start of every session — kills the unattended cycle story. Real-world urgency: spec 033's BUDGET_PAUSED + spec 015's autonomous cycles depend on sessions NOT requiring per-stage human approval; today, a fresh Claude Code session opens in interactive mode regardless of the cycle's intent.

## Clarifications

### Pending — `/speckit.clarify` session TBD

- **Q1 (FR-006 / Codex full-auto)**: For Codex, should `full-auto` set a PERMISSIVE `sandbox_mode` OR keep the sandbox STRICT and rely on `approval_mode` alone? Strict sandbox + auto-edit is safer (less surface for autonomous mistakes); permissive sandbox + auto-edit is faster (fewer mid-cycle blocks). Default proposed: STRICT sandbox + auto-edit — safety first, perf optimization is a separate spec.
- **Q2 (FR-008 / CLAUDE.md warning rendering)**: The warning block in `CLAUDE.md` — render it on every `install.sh` / `./vault update` run (idempotent), or only when the autonomy level changes? Default proposed: idempotent every-run (cheap; never stale); use a deterministic block delimiter so re-renders are byte-identical.
- **Q3 (FR-012 / migration prompt)**: Should the migration story include a ONE-TIME prompt during `./vault update` asking the user to pick a level, or stay silent and require explicit opt-in via `settings.yaml`? Default proposed: silent + explicit opt-in (no silent escalation; user must declare intent in writing).

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Unattended cycles run without human approval prompts (Priority: P1)

The operator sets `autonomy_level: full-auto` in `settings.yaml`. They run `./vault update` (or `install.sh`) to apply. The scaffolder writes `.claude/settings.json` with `permissions.defaultMode: "acceptEdits"` AND writes a Codex auto-edit approval mode. A subsequent cron-driven `./vault research` cycle runs end-to-end without any human prompts. The cycle's edits land successfully + the BUDGET_PAUSED / APPROVAL_REQUIRED markers (per spec 033) still fire when expected.

**Why this priority**: This is the FLAGSHIP use case — unattended cycles are the whole point. Without this, every autonomous cycle requires a human at the keyboard at session-start, defeating the cron+autonomous flow.

**Independent Test**: On a fixture vault, set `autonomy_level: full-auto`. Run `install.sh` (or `./vault update`). Verify: `.claude/settings.json` has `permissions.defaultMode: "acceptEdits"`; `.codex/config.toml` has the autoedit approval mode. Run a cycle. Verify: zero interactive prompts; cycle exit 0; spec 033's BUDGET_PAUSED still fires when budget exceeds (orthogonal to autonomy level).

**Acceptance Scenarios**:

1. **Given** `autonomy_level: full-auto` in `settings.yaml`, **When** `./vault update` runs, **Then** `.claude/settings.json` contains `permissions.defaultMode: "acceptEdits"`.
2. **Given** the same setting, **When** `./vault update` runs, **Then** `.codex/config.toml` contains the `auto-edit` approval mode (exact key TBD per Codex docs at impl time).
3. **Given** the same setting, **When** a `./vault research` cycle runs unattended, **Then** zero interactive prompts fire AND cycle exit is 0.
4. **Given** spec 033's BUDGET_PAUSED is enabled, **When** the budget is exceeded mid-cycle, **Then** the cycle pauses + writes BUDGET_PAUSED regardless of `autonomy_level`. (Autonomy and budget enforcement are orthogonal.)

---

### User Story 2 — Interactive default is preserved (Priority: P1)

A user installs a fresh vault with default settings. `autonomy_level` is `interactive` (default). Sessions open in interactive mode requiring Shift+Tab for auto-accept. Spec 007's pre-authorised tool calls still work, but the session-level default is conservative.

**Why this priority**: Default conservatism is non-negotiable. New users should never unwittingly get a vault that auto-accepts edits without their understanding. P1 because this is the safety floor.

**Independent Test**: Install a fresh vault. Verify: no `autonomy_level` setting written (or `autonomy_level: interactive` default written). Verify: `.claude/settings.json` does NOT contain `permissions.defaultMode: "acceptEdits"` (or contains `"default"`). Verify: a session opened against this vault starts in interactive mode.

**Acceptance Scenarios**:

1. **Given** a fresh `install.sh` invocation with no operator-supplied autonomy override, **When** the install completes, **Then** `autonomy_level` defaults to `interactive` (or is absent — same effect).
2. **Given** the default install, **When** the operator opens a Claude Code session, **Then** the session starts in interactive mode (default `permissions.defaultMode`).
3. **Given** spec 007 pre-authorisations exist, **When** the session runs, **Then** the pre-authorised tool calls work without per-call prompts (spec 007's behavior is preserved).

---

### User Story 3 — `full-auto` vaults warn loudly in CLAUDE.md (Priority: P1)

For any vault with `autonomy_level: full-auto`, the scaffolder writes a prominent warning block to the vault's top-level `CLAUDE.md`:

```
> ⚠️ **AUTONOMY POSTURE: full-auto**
> 
> This vault is configured for full-auto operation. Sessions opened
> against this vault auto-accept edits without prompting. To revert,
> set `autonomy_level: interactive` in `settings.yaml` and re-run
> `./vault update`.
```

**Why this priority**: Without a discoverable warning, future maintainers (or a future-self looking at the vault months later) can be surprised by the autonomy posture. Discoverability via the vault's own documentation is the cheapest fix.

**Independent Test**: Install a vault with `full-auto`. Verify: vault's `CLAUDE.md` contains the warning block at the top with the exact wording. Re-run `./vault update` → block is idempotent (no duplication).

**Acceptance Scenarios**:

1. **Given** `autonomy_level: full-auto` is set, **When** `install.sh` or `./vault update` runs, **Then** the warning block exists in the vault's top-level `CLAUDE.md`.
2. **Given** the block was already written, **When** `./vault update` re-runs, **Then** the block is unchanged (idempotent — no duplication).
3. **Given** the operator reverts to `semi-auto` or `interactive`, **When** `./vault update` runs, **Then** the warning block is removed from `CLAUDE.md` (or replaced with the appropriate level's marker).

---

### User Story 4 — `semi-auto` is the recommended middle ground (Priority: P2)

The operator picks `semi-auto` (preferred posture for "supervised autonomy"). Sessions auto-accept edits within the existing spec-007 permission boundary but still require user confirmation for out-of-boundary actions (e.g. network calls, new file creations outside the vault).

**Why this priority**: `semi-auto` is the realistic posture for power-users. P2 (not P1) because it's a refinement on top of US1+US2.

**Acceptance Scenarios**:

1. **Given** `autonomy_level: semi-auto`, **When** `./vault update` runs, **Then** `.claude/settings.json` has `permissions.defaultMode: "acceptEdits"` (same as full-auto for Claude — the difference is in Codex sandbox + the CLAUDE.md warning intensity).
2. **Given** `semi-auto`, **When** `.codex/config.toml` is generated, **Then** the approval mode is `auto-edit` BUT the sandbox_mode stays strict (smaller permission radius than full-auto per Q1).
3. **Given** `semi-auto`, **When** the warning block is rendered, **Then** the wording is less alarmed than full-auto's ("supervised autonomy" framing).

---

### User Story 5 — Existing vaults migrate without surprise (Priority: P2)

An existing vault (pre-spec-042) has no `autonomy_level` key. After upgrading via `./vault update`, the framework treats it as `interactive`. No silent escalation. The operator must explicitly add `autonomy_level: <level>` to settings to opt into anything other than `interactive`.

**Why this priority**: Backward-compat invariant. P2 because new vaults (US1+US2) are higher impact; existing vault migration is the safety net.

**Acceptance Scenarios**:

1. **Given** an existing vault with no `autonomy_level` setting, **When** `./vault update` (post-042) runs, **Then** the vault is treated as `interactive` (current behavior).
2. **Given** the migration runs, **When** it completes, **Then** the operator can verify the autonomy posture by reading `settings.yaml` OR the rendered `.claude/settings.json`.
3. **Given** the migration is silent per Q3 default, **When** the operator wants `full-auto`, **Then** they must explicitly write `autonomy_level: full-auto` and re-run `./vault update`.

---

### Edge Cases

- What if `autonomy_level` has an invalid value (typo, e.g. `full_auto`)? → Validate at startup; refuse install with clear error naming the invalid value + the allowed enum.
- What if the operator deletes `.claude/settings.json` after install? → `./vault update` regenerates it per the current `autonomy_level`.
- What if a session is opened via `./vault sandbox` (one-off invocation) instead of an unattended cycle? → Same autonomy settings apply; one-off sessions still respect the posture.
- What if the warning block in CLAUDE.md is manually edited by the operator? → Per Q2 (idempotent every-run), the block is restored on next `./vault update`. Operator-customized text is OUTSIDE the delimited block — preserved.
- What if a future LLM backend (e.g. local Ollama post-spec-047) doesn't have an analog to `permissions.defaultMode`? → The wrapper owns it (per stub's Section B Ollama row).
- What if the operator wants per-stage autonomy (e.g. note-writer is full-auto, verifier is interactive)? → Out of scope for v1; revisit if real demand surfaces. Today: vault-wide posture only.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A new `autonomy_level: <enum>` setting MUST be supported in `settings.yaml`. Enum: `interactive` (default), `semi-auto`, `full-auto`. Unset → treated as `interactive` (per backward-compat).
- **FR-002**: Invalid enum values MUST fail install with a clear error naming the invalid value + the allowed enum.
- **FR-003**: For `interactive` (or unset), `.claude/settings.json` MUST NOT contain `permissions.defaultMode: "acceptEdits"`. The framework MAY explicitly write `"default"` or simply omit the key.
- **FR-004**: For `semi-auto` AND `full-auto`, `.claude/settings.json` MUST contain `permissions.defaultMode: "acceptEdits"`. The framework MUST NOT default to `bypassPermissions` for any level (safety floor).
- **FR-005**: For `interactive`, `.codex/config.toml` MUST contain `approval_mode = "manual"` (current default).
- **FR-006**: For `semi-auto` AND `full-auto`, `.codex/config.toml` MUST contain `approval_mode = "auto-edit"` (or the latest Codex equivalent). Per Q1 default, `sandbox_mode` stays STRICT in both levels.
- **FR-007**: For each level, the warning block in `<vault>/CLAUDE.md` MUST be rendered per Q2 (idempotent every-run with deterministic block delimiter).
- **FR-008**: The warning block MUST be wrapped with deterministic delimiters (e.g. HTML comment markers `<!-- AUTONOMY_LEVEL_BLOCK_START -->` ... `<!-- AUTONOMY_LEVEL_BLOCK_END -->`) so the framework can replace the block without affecting operator-authored content.
- **FR-009**: The warning text MUST vary by level: `interactive` → no block (or minimal "interactive mode" reminder); `semi-auto` → "supervised autonomy" framing; `full-auto` → loud "AUTONOMY POSTURE: full-auto" warning per US3.
- **FR-010**: Spec 007's pre-authorised tool calls MUST continue to work in all three autonomy levels (no regression).
- **FR-011**: When future LLM backends are added (post-spec-047), each backend's autonomy mapping MUST be documented in this spec OR a follow-up amendment. The wrapper (per stub's Section B Ollama row) owns the mapping for backends without native permission concepts.
- **FR-012**: Per Q3, existing vaults without `autonomy_level` MUST NOT auto-escalate. `./vault update` treats them as `interactive` and writes no `autonomy_level` key unless the operator adds one.
- **FR-013**: Changing `autonomy_level` MUST require re-running `./vault update` for the change to take effect. The framework does NOT hot-reload settings mid-cycle.
- **FR-014**: The framework MUST NOT default to `bypassPermissions` for any autonomy level. That mode is reserved for explicit operator override (out of this spec's scope).

### Key Entities

- **`autonomy_level` setting**: New `settings.yaml` enum field. Vault-wide; one value per vault.
- **`.claude/settings.json` template**: Existing scaffolder output; gains per-level `permissions.defaultMode` rendering.
- **`.codex/config.toml` template**: Existing scaffolder output; gains per-level `approval_mode` + `sandbox_mode` rendering per Q1.
- **CLAUDE.md warning block**: New scaffolder-managed block in `<vault>/CLAUDE.md` with deterministic delimiters per FR-008.
- **Ollama wrapper autonomy mapping** (per FR-011): Reserved for spec 047's local-backend runtime. This spec documents the mapping but doesn't implement it (047 owns the wrapper).
- **Backward-compat migration path**: Existing vaults → `interactive` (silent, per Q3 default).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After this spec ships, a vault with `autonomy_level: full-auto` runs `./vault research` end-to-end without interactive prompts (verified by cron-driven cycle on the feeds-vault fixture).
- **SC-002**: 0 fresh installs default to anything OTHER than `interactive` (safety floor invariant).
- **SC-003**: 100% of `full-auto` vaults have the warning block in their `CLAUDE.md` (discoverability invariant).
- **SC-004**: 0 existing vaults silently escalate during `./vault update` (per Q3 default).
- **SC-005**: Spec 007's pre-authorised tool calls work in all three autonomy levels (no regression in spec 007 tests).

## Assumptions

- Claude Code's `permissions.defaultMode: "acceptEdits"` semantic stays stable through 2026.
- Codex's `approval_mode = "auto-edit"` semantic stays stable; if Codex renames the key, this spec amends.
- Operators who set `full-auto` understand the implications (mitigated by the loud CLAUDE.md warning + the explicit opt-in requirement).
- Spec 007's pre-authorisation list is the safety boundary — full-auto only auto-accepts WITHIN that boundary (modulo Claude/Codex defaults).

## Dependencies

- **Hard**: Spec 007 (pre-authorisation list) — full-auto operates WITHIN this boundary.
- **Soft**: Spec 047 (backend-agnostic agent layer) — handles future backends (Ollama, etc.) per FR-011. Until 047 ships, this spec covers Claude + Codex only.
- **Soft**: Spec 027 (`./vault update` hardening) — the scaffolder re-runs in `./vault update` need to handle the warning-block delimiter correctly.

## Acceptance coverage

Draft — evidence cells populated by `/speckit.tasks` after `/speckit.clarify`.

| User Story | Evidence |
|---|---|
| US1 — Unattended cycles run without human approval prompts | _(deferred to tasks.md — pending /speckit.clarify on open Q1/Q2/Q3)_ |
| US2 — Interactive default is preserved | _(deferred to tasks.md — pending /speckit.clarify on open Q1/Q2/Q3)_ |
| US3 — `full-auto` vaults warn loudly in CLAUDE.md | _(deferred to tasks.md — pending /speckit.clarify on open Q1/Q2/Q3)_ |
| US4 — `semi-auto` is the recommended middle ground | _(deferred to tasks.md — pending /speckit.clarify on open Q1/Q2/Q3)_ |
| US5 — Existing vaults migrate without surprise | _(deferred to tasks.md — pending /speckit.clarify on open Q1/Q2/Q3)_ |

## Out of Scope

- Bypassing permissions entirely (`bypassPermissions` mode). Never defaulted; out of this spec.
- The backend-agnostic agent layer abstraction itself (spec 047).
- Per-stage autonomy (different levels per stage within the same vault). Vault-wide posture only in v1.
- Per-stage model selection — already covered by `settings.yaml::stages.*.model`.
- Time-bound autonomy (e.g. "full-auto Mon-Fri, interactive on weekends"). Out of v1; consider only if real demand.
- Cross-vault autonomy policy (one global setting overriding per-vault). Vaults are independent in v1.

---

*Promote to active queue by running `/speckit.clarify` against this draft; the three pending clarifications (Q1-Q3) gate the promotion to `IMPLEMENTABLE`. Soft-coordinate with spec 047 for backend-agnostic mapping.*
