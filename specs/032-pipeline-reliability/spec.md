# Feature Specification: Pipeline Reliability Hardening

**Feature Branch**: `032-pipeline-reliability`
**Created**: 2026-05-22
**Status**: shipped(2026-06-03, PR #100) — SHIPPED (PR #100) — sandbox detection, extraction-failed stub auto-retry, sonnet timeout fallback ladder, `extract.py` → `agent_call.dispatch()` migration.
**Input**: User description: "Three script-level bugs surfaced by a real `/pipeline full` run on ~/Documents/feeds-vault on 2026-05-13. (1) Nested `claude` CLI auth fails under sandbox — extract.py shells out to claude -p and the nested call can't reach keychain, silently writes extraction-failed stubs. (2) Extraction-failed stubs are not retried — resumable-skip logic treats them as already done. (3) Sonnet synthesis times out on large bundles (176 sources × 300s × 3 retries). Plus the audit's Principle IV bypass: processors/extract.py calls subprocess.run([\"claude\", ...]) directly, intentionally excluded from the dispatch guard. Migrate extract.py through agent_call.py OR formalize as constitutional exception."

## Clarifications

### Session 2026-06-03 — all recommended

- **Q1 (FR-007 — migrate or formalize `extract.py`'s Principle-IV exception?) →
  MIGRATE** to `agent_call.dispatch()`; keep the dispatch-guard allowlist EMPTY.
  (FR-007 resolved.)
- **Q2 (sandbox-failure detection mechanism) → stderr auth-failure signature
  (primary) + time-based fallback (≥3 extractions <1s + failed) + `RV_` override
  env var.** (FR-001 updated.)
- **Q3 (detection policy: hard-exit vs WARN) → hard exit non-zero, write ZERO
  stubs.** Env-broken dispatch fails closed — distinct from 048-v2's
  WARN-on-source-silence. (FR-001 updated.)
- **Q4 (US3 timeout fallback) → ordered ladder**: `--filter <today>` → chunked
  batches → fail (matches FR-005, retry budget configurable).
- **Q5 (is `extract.py` on the rc1 critical path?) → bug-fix-only / transitional.**
  The three live runs use spec-020 subprocess modules, not `extract.py`'s legacy
  raw_data path. **Q1's migration is the only rc1-blocking item**; US1-3 are legacy
  hardening (P3 if a usage audit confirms no target vault exercises `extract.py`).
  `/speckit.plan` MUST confirm target-vault usage before sizing US1-3.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Sandboxed `extract.py` runs detect their environment and fail loudly (Priority: P3 — transitional)

When `extract.py` runs inside Claude Code's default sandbox, the nested `claude -p` call it shells out to cannot reach the keychain — every Haiku extraction silently fails and writes `extraction-failed` stubs. The user only discovers this after the cycle "completes" with no useful data. This must fail LOUDLY with a clear remediation message instead of silently corrupting the raw_data tree.

**Why this priority**: Production-confirmed silent corruption. Affects every cycle that touches `raw_data/` via `extract.py`. Was observed on the 2026-05-13 feeds-vault run.

**Independent Test**: Run `extract.py` inside a simulated sandboxed environment (no keychain access). Assert:
- The script detects the sandbox failure on its FIRST extraction attempt
- It exits non-zero with a clear message pointing to the `dangerouslyDisableSandbox: true` workaround or the autonomous-mode pre-authorization
- No `extraction-failed` stubs are written

**Acceptance Scenarios**:

1. **Given** a sandboxed environment where `claude -p` fails, **When** `extract.py` runs, **Then** it exits non-zero on the first failure with an actionable error message.
2. **Given** a non-sandboxed environment, **When** `extract.py` runs normally, **Then** behaviour is unchanged.
3. **Given** the autonomous-mode pre-authorization (spec 007) extends to nested CLI calls, **When** `extract.py` runs, **Then** it succeeds without needing manual sandbox-disable.

---

### User Story 2 — `extraction-failed` stubs auto-retry on resume (Priority: P3 — transitional)

Once Haiku writes a stub (`status: extraction-failed`), the resumable-skip logic treats it as "already done" on subsequent runs. Recovery today requires the user to know about `--force --filter <date>`. Automate this: detect stub markers and retry them on resume.

**Why this priority**: Recovery should be automatic. Without it, a single transient failure becomes permanent.

**Acceptance Scenarios**:

1. **Given** a previous run wrote `extraction-failed` stubs for 3 sources, **When** the user re-runs `extract.py` without flags, **Then** those 3 stubs are detected and retried.
2. **Given** stubs retry and still fail, **When** the retry exhausts (configurable max-attempts), **Then** the stub is marked `status: extraction-failed-permanent` to distinguish from transient failures.
3. **Given** the operator wants to force a full re-extract, **When** they pass `--force`, **Then** even `extraction-failed-permanent` stubs are re-attempted.

---

### User Story 3 — Sonnet synthesis falls back gracefully on timeout (Priority: P3 — transitional)

Full 176-source synthesis bundles time out at 300s × 3 retries; date-filtered batches succeed. The script must detect timeout and auto-fall-back to `--filter <today>` or chunked batches rather than failing the whole run.

**Why this priority**: Avoids the cycle-killing path. Production-validated workaround (date-filtered batches) becomes the auto-fallback.

**Acceptance Scenarios**:

1. **Given** a synthesis bundle that exceeds 300s, **When** the timeout fires, **Then** `extract.py` automatically retries with `--filter <today>` (or chunks the bundle).
2. **Given** the chunked fallback succeeds, **When** the run completes, **Then** the cycle's resulting raw_data is equivalent to a full-bundle synthesis (no data loss).
3. **Given** all retries (full + chunked) exhaust, **When** the run finally fails, **Then** the failure message lists what was attempted and what's missing.

---

### User Story 4 — `processors/extract.py` Principle IV decision is formalized (Priority: P1 — rc1 gate)

The dispatch guard explicitly excludes `processors/extract.py` because it calls `subprocess.run(["claude", ...])` directly. This is the only Principle IV exception in the codebase. The current state is a comment in the guard; that's not a durable contract.

**Why this priority**: Constitutional clarity — the only Principle IV bypass in the codebase. Clarifications Q1 resolved **MIGRATE** through `agent_call.dispatch()` (no ADR exception path). This is the sole rc1-blocking deliverable (Q5).

**Acceptance Scenarios**:

1. **Given** the migration through `agent_call.dispatch()` ships (Clarifications Q1 → MIGRATE), **When** the guard is re-scanned, **Then** the `processors/extract.py` exclusion is removed, direct `subprocess.run(["claude", ...])` calls are gone, and the dispatch-guard allowlist stays **EMPTY** (Principle IV).
2. ~~**Given** the project commits to keeping `extract.py` as an exception, **When** the spec ships, **Then** a new ADR records the decision with rationale, and the comment in the guard points to the ADR.~~ *(Obsolete — Q1 resolved MIGRATE; no ADR exception path.)*

---

### Edge Cases

- What if `extract.py` runs under a NEW sandbox model (e.g., codex sandbox semantics differ from claude)? The detection logic must be sandbox-agnostic or sandbox-aware.
- What's the precise definition of "sandboxed and failing"? Is the keychain test reliable across platforms (macOS keychain vs Linux gnome-keyring vs nothing)?
- For chunked synthesis, how do chunks reconcile (overlap detection, deduplication)?
- For `extraction-failed-permanent`, is there a TTL after which it gets retried again?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `extract.py` MUST detect the sandboxed-and-failing case and **hard-exit non-zero having written ZERO stubs** (Clarifications Q3 — env-broken dispatch fails closed; deliberately NOT 048-v2's WARN-on-source-silence posture). Detection (Clarifications Q2) uses the **stderr auth-failure signature as primary**, a **time-based fallback** (first ≥3 extractions each exit <1s AND fail), and an **`RV_`-prefixed override env var** for documented mis-fire suppression (SC-005). The error message MUST be actionable.
- **FR-002**: The error message MUST include: (a) what was detected; (b) the workaround (`dangerouslyDisableSandbox: true` OR the autonomous-mode pre-auth path); (c) a link to the relevant doc.
- **FR-003**: `extract.py` MUST detect `status: extraction-failed` stubs on resume and retry them. Configurable max-retry-attempts; default 3.
- **FR-004**: When retries exhaust, the stub MUST be marked `status: extraction-failed-permanent` and recovery requires explicit `--force`.
- **FR-005**: Sonnet synthesis bundles MUST auto-fall-back on timeout: first to `--filter <today>`, then to chunked batches, then fail. The retry budget MUST be configurable.
- **FR-006**: Chunked synthesis MUST produce output equivalent to a full-bundle synthesis when the chunked path succeeds (no data loss vs a hypothetical successful full run).
- **FR-007**: **Resolved (Clarifications Q1) → MIGRATE.** `processors/extract.py` is migrated to dispatch through `agent_call.dispatch()`, removing its LLM-dispatch-guard exclusion so the guard allowlist stays **EMPTY** (a hard CLAUDE.md invariant). The spec-028 telemetry dependency that previously made migration costlier has shipped (0.4.0), so migration is now the principled *and* tractable choice — no permanent constitutional exception is added. The migration is a focused first commit; the bug-fix FRs (US1-3) are independent of it.
- **FR-008**: Any new pipeline script that shells out to `claude` / `codex` MUST declare its sandbox-incompat in its module docstring AND in spec 007's autonomous-op grant. This is a per-script policy enforced by code review (not lint-able).
- **FR-009**: Regression tests MUST exist for each US: sandboxed detection, stub retry, timeout fallback. Tests SHOULD be `live_llm`-opt-in where they touch the real `claude` CLI; static tests should cover the detection / parsing logic.

### Key Entities

- **Extraction stub**: A file under `raw_data/` with `status: extraction-failed` or `status: extraction-failed-permanent`. Schema already exists; this spec adds the `permanent` variant.
- **Sandbox-failure signature**: A recognizable pattern in `claude -p` stderr that indicates auth failure due to sandboxing. Stable across claude CLI versions (verify; may need a fallback heuristic).
- **Chunked synthesis manifest** (new): A small JSON file recording what chunks were attempted, which succeeded, used for reconciliation.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In a simulated sandbox environment, `extract.py` exits non-zero within 30s of first failed extraction. Compare to current behaviour: silently writing N stubs (one per source) over several minutes.
- **SC-002**: For a vault with 3 pre-existing `extraction-failed` stubs, re-running `extract.py` retries them automatically without user intervention.
- **SC-003**: For a 200+ source synthesis bundle that would currently time out, the auto-fallback completes the synthesis without manual intervention. Measured success rate on a representative test bundle.
- **SC-004**: The Principle IV (Agent-Script Separation) decision is recorded by migration only: the `processors/extract.py` guard exclusion is removed, direct `subprocess.run(["claude", ...])` calls are gone, and the dispatch-guard allowlist stays **EMPTY**. No ADR exception path (Clarifications Q1 → MIGRATE).
- **SC-005**: A new ADR or doc page MUST exist explaining the sandbox-detection heuristic, what triggers it, and how to disable it (override env var) in case the heuristic mis-fires.

## Assumptions

- The 2026-05-13 production observations are reproducible on a representative fixture. (Construct one during planning.)
- `claude -p` exit code or stderr pattern for sandboxed-auth-failure is detectable (verify; may require a one-off probe). If unstable, fall back to a TIME-based heuristic ("first 3 extractions all <1s exit + failed" = sandbox).
- Codex sandbox semantics are equivalent or have a different known signature. (Audit during planning if codex synthesis is in scope.)
- The `extract.py` PRINCIPLE IV decision can be made independently of the bug fixes. The bug fixes don't change the Principle IV story.

## Dependencies

- Spec 028 (dispatch telemetry) — FR-007 migration through `agent_call.dispatch()` consumes spec 028's capturable telemetry (shipped 0.4.0).
- Spec 007 (autonomous-op grant) — pre-auth path for sandboxed nested calls.
- Soft on spec 020 (source modules) — `extract.py` is a legacy raw-data path; if spec 020's source modules eventually replace it, this spec's investments may be transitional.

## Acceptance coverage

Evidence populated 2026-06-03 (Phase 7). All four user stories are covered by
`tests/processors/test_extract.py` (US4 also by the Principle-IV dispatch guard).

| User Story | Evidence |
|------------|----------|
| US1 — Sandboxed `extract.py` runs detect their environment and fail loudly | `tests/processors/test_extract.py` (sandbox-detection cases, `-k sandbox`; SC-001/SC-005, FR-001/FR-002) |
| US2 — `extraction-failed` stubs auto-retry on resume | `tests/processors/test_extract.py` (retry / permanent-marker cases, `-k "retry or permanent"`; FR-003/FR-004) |
| US3 — Sonnet synthesis falls back gracefully on timeout | `tests/processors/test_extract.py` (timeout / chunk / ladder cases, `-k "timeout or chunk or ladder"`; FR-005/FR-006) |
| US4 — `processors/extract.py` Principle IV decision is formalized | `tests/_helpers/test_llm_dispatch_guard.py` + `tests/processors/test_extract.py` (dispatch-backed, no direct subprocess; FR-007) |

## Out of Scope

- Replacing `extract.py` entirely with a new architecture. That's spec 020's domain in part.
- Cross-CLI sandboxed-detection (claude + codex + ollama). Each has its own model; this spec focuses on the claude case observed in production.
- The full Horizon 2 "robust installer" sandbox-detection. That's a separate concern at install-time, not runtime.
