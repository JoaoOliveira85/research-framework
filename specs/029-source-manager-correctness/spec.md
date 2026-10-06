# Feature Specification: Source Manager Correctness

**Feature Branch**: `029-source-manager-correctness`
**Created**: 2026-05-22
**Status**: shipped(2026-06-04, PR #108) — SHIPPED 0.10.0 (PR #108, 2026-06-04). Both bugs fixed on the post-049 `_helpers/` layout: FR-001 arity fix + narrowed `except OSError` in `source_signals.py`; FR-002 frontmatter-based `notes_generated` attribution + shared `normalize_source_url`/`_note_cites_source` predicate in `source_manager.py`; FR-007 append-only `mark_resolved` recovery line wired into `record_cycle`; FR-008 idempotent `scripts/reconcile_source_metrics.py`; FR-005 retired the 2-arg `mark_degraded` monkeypatch shield. 29 new regression tests; full fast loop green.
**Input**: User description: "Two silent correctness bugs in source-manager surfaced by the weekend audit. (1) `notify_required_source_degraded` calls `mark_degraded(source_name, reason)` with 2 args but production `mark_degraded` requires 3 (vault_dir) — always hits except path, source-incidents.md never written. Tests pass because they monkeypatch a 2-arg lambda. (2) `source_manager.record_cycle` counts `notes_generated` by substring-matching source URL against file paths in notes_created, not note frontmatter — corrupts SQLite metrics and triggers premature `consecutive_empty_cycles` archival."

## Clarifications

### Session 2026-06-03 (clarify + code reconciliation)

A code audit at the 053 base re-verified both bugs **still present** and surfaced evolutions the 2026-05-22 draft predates:

- **Bug 1 is real but no longer fully silent.** `notify_required_source_degraded(vault_dir, source_name, *, role, reason)` (in `pipeline/_cycle_helpers.py`) calls `md(source_name, reason)` — 2 args — against `mark_degraded(name, reason, vault_dir)` (3 args, in `pipeline/source_manager.py`). `vault_dir` is already in scope (the function's first param). The call now sits in a `try/except` that **logs `"[sources] mark_degraded failed"`** (observability added post-0.5.0) and the function separately writes a **working `cycle-NNN-source-incidents.json` sidecar**. So only the human-readable `source-incidents.md` is broken; the fix is a one-line arity correction (`md(source_name, reason, vault_dir)`).
- **Bug 2 is confirmed verbatim** (`record_cycle` lines counting `notes_generated` by `url in str(note_path)` / `name in str(note_path)`). The sibling `notes_referencing` metric already uses a frontmatter-scanning helper `_count_notes_referencing` — the `notes_generated` fix reuses/extends it (scoped to this cycle's `notes_created`).
- **Cross-spec (049).** `notify_required_source_degraded` lives in `_cycle_helpers.py`, which **spec 049 (Wave 1) splits** into `pipeline/_helpers/` submodules. 049 lands before 029; the FR-001 fix is trivial wherever the function ends up but **029 must rebase onto the post-049 layout**.

**Resolved questions** (recommended option chosen in each):

- **Q1 — Incident surface → KEEP BOTH.** Fix `source-incidents.md` (cumulative, human-readable operator log) **and** keep the per-cycle `cycle-NNN-source-incidents.json` sidecar (machine telemetry). They serve different consumers.
- **Q2 (was FR-007) — Recovery lifecycle → APPEND-ONLY.** On recovery, append a `Resolved` line with timestamp; never delete prior entries (audit-friendly; matches `mark_degraded`'s existing append semantics).
- **Q3 — URL matching → NORMALIZED-URL + NAME FALLBACK.** `normalize_source_url()` canonicalizes for matching, but source-name substring stays a fallback so a name-only citation still counts (fewest false-negatives; preserves current reach).
- **Q4 — Reconciliation scope → CUMULATIVE.** `scripts/reconcile_source_metrics.py` recomputes cumulative `notes_generated` from current `data_vault/` frontmatter and resets `consecutive_empty_cycles` from the latest cycle's real citations; it does **not** attempt a fragile per-cycle history rebuild.

**Defaults taken without asking** (low-stakes): malformed/missing `source_urls` on a note → skip that entry with a debug log (matches `_count_notes_referencing`'s current `continue`-on-bad-YAML); `notes_generated` is a **per-cycle** count scoped to this cycle's `notes_created` (distinct from the all-time `notes_referencing`).

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Source degradation incidents are durably recorded (Priority: P1)

When a required source has failed N consecutive cycles (per threshold policy), the framework records the degradation in `<vault>/_pipeline/source-incidents.md` so the operator can see what's broken without re-running cycles. Today this file is **never written** because the helper that should write it is called with the wrong arity.

**Why this priority**: Production-blind correctness bug. Cycles run "successfully" but the operator's only signal that a required source has died is when notes stop being generated. By the time they notice, several cycles have wasted budget on a known-broken source.

**Independent Test**: Construct a fixture where a required source is configured to fail consistently. Run N+1 cycles where N is the degradation threshold. Assert `<vault>/_pipeline/source-incidents.md` exists, mentions the source name, and contains the failure reason.

**Acceptance Scenarios**:

1. **Given** a vault with a `required: true` source that fails to fetch, **When** the framework runs N+1 cycles, **Then** `_pipeline/source-incidents.md` exists with an entry for the source.
2. **Given** a source incident is recorded, **When** the operator runs `./vault health`, **Then** the incident is surfaced in the health output.
3. **Given** a source previously degraded recovers, **When** the next cycle runs, **Then** `_pipeline/source-incidents.md` is updated to reflect recovery (timestamp, "resolved" state).

---

### User Story 2 — Source quality metrics accurately reflect note attribution (Priority: P1)

`source_manager.record_cycle` writes per-source `notes_generated` to `_pipeline/sources.db`. Today it counts by substring-matching the source URL against file paths (e.g., does `data_vault/01 - Services/foo.md` contain the URL `https://example.com`? almost never). The correct attribution is via note frontmatter's `source_urls` field. The bug causes `consecutive_empty_cycles` to inflate, triggering premature auto-archival of perfectly-fine sources.

**Why this priority**: Silent corruption of the SQLite metrics that drive source archival. Affects every production vault. Once a source crosses `consecutive_empty_cycles ≥ N`, it gets auto-archived and disappears from scout prompts.

**Independent Test**: Construct a fixture with 3 sources A/B/C and 5 notes whose frontmatter cites:
- Note 1: cites A only
- Note 2: cites B only
- Note 3: cites C only
- Note 4: cites A + B
- Note 5: cites no source (placeholder note)

Run one cycle. Assert `sources.db` records `notes_generated` as 2 for A, 2 for B, 1 for C — not whatever path-substring matching produces.

**Acceptance Scenarios**:

1. **Given** notes with explicit `source_urls` in frontmatter, **When** the cycle ends and `record_cycle` runs, **Then** `sources.db::notes_generated` reflects the actual count per source.
2. **Given** a source is cited in N notes across M cycles, **When** the source has zero new citations in cycle M+1, **Then** `consecutive_empty_cycles` increments by exactly 1.
3. **Given** the source has citations again in cycle M+2, **When** `record_cycle` runs, **Then** `consecutive_empty_cycles` resets to 0.

---

### User Story 3 — Existing test coverage no longer hides production bugs (Priority: P2)

The current test for source-degradation uses a 2-arg lambda monkeypatch that hides the production bug from passing tests. Update the test to exercise the real production code path.

**Why this priority**: Discipline correction. Otherwise a future agent re-introduces the same arity bug and tests still pass.

**Acceptance Scenarios**:

1. **Given** the source-degradation test, **When** the production `mark_degraded` signature changes, **Then** the test breaks loudly (no monkeypatch shielding).

---

### Edge Cases

- **Malformed/missing `source_urls`** (string instead of list, or absent): the attribution scan **skips that entry with a debug log** and continues the cycle — it does NOT bail (matches `_count_notes_referencing`'s existing `continue`-on-bad-YAML; a single bad note must never abort metrics). A `string` value is coerced to a 1-element list (existing helper already does this). *(default taken in clarify Session 2026-06-03)*
- **Fragment / shortened / redirect URL mismatch**: `normalize_source_url()` strips `#fragments` and trailing slashes and lowercases scheme+host (FR-003), so common variants match; genuinely different shorteners (`bit.ly/...`) won't match the canonical URL — the **source-name fallback** (Q3) catches the common case where the note cites the source by name. Exotic redirects that match neither are a known, accepted miss (logged at debug; not a correctness failure for archival because name-fallback covers declared sources).
- **Legacy corrupted counts**: handled by FR-008's cumulative reconciliation (recompute from current frontmatter; reset `consecutive_empty_cycles` from the latest cycle). Per-cycle history is intentionally not rebuilt.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The `notify_required_source_degraded` call site (currently `pipeline/_cycle_helpers.py`; may move under `pipeline/_helpers/` after spec 049) MUST call `mark_degraded` with the correct 3-arg signature, passing the in-scope `vault_dir` (e.g. `md(source_name, reason, vault_dir)`). The existing `try/except` MUST be **narrowed** so an arity/type error is no longer swallowed as a generic warning — a broken signature MUST surface (a `TypeError` here is a programming error, not a runtime source failure). Source-degradation incidents MUST then persist to `<vault>/_pipeline/source-incidents.md` on every required-source detection.
- **FR-001a** *(Q1 — KEEP BOTH)*: The per-cycle `cycle-NNN-source-incidents.json` sidecar that `notify_required_source_degraded` already writes is RETAINED unchanged (machine/telemetry surface). `source-incidents.md` is the complementary cumulative, human-readable operator log. Neither replaces the other.
- **FR-002**: `source_manager.record_cycle` MUST count `notes_generated` per source by reading each newly-created note's frontmatter `source_urls` field — not by substring-matching the source URL/name against file **paths**. The count is **per-cycle**, scoped to this cycle's `notes_created` list (distinct from the all-time `notes_referencing` metric). The implementation MUST reuse the existing frontmatter-scan logic in `_count_notes_referencing` (refactor a shared `_note_cites_source(fm, name, url)` predicate rather than duplicating the parse).
- **FR-003**: A single `normalize_source_url(url) -> str` helper MUST canonicalize URLs for attribution matching (lowercase scheme + host, strip trailing slash, strip `#fragment`; **preserve query string** — many feeds disambiguate by `?q=`/`?v=`). Matching is **normalized-URL OR source-name substring** *(Q3 — name fallback retained)*: a note counts for a source if any normalized `source_urls` entry equals/contains the source's normalized URL, **or** the source name appears as a substring. Both `notes_generated` (FR-002) and `notes_referencing` MUST route through this same predicate so the two metrics can never diverge on matching semantics.
- **FR-004**: `consecutive_empty_cycles` MUST increment by exactly 1 per cycle where a source has zero new citations (per FR-002's frontmatter count), and reset to 0 on any new citation. (No behaviour change to Step 4's SQL — it becomes correct once FR-002 feeds it an accurate `notes_generated`.)
- **FR-005**: A new test `tests/pipeline/test_source_manager_correctness.py` MUST exercise the production code path WITHOUT monkeypatching `mark_degraded` arity. Any existing test that monkeypatches a 2-arg `mark_degraded` lambda (which currently hides Bug 1) MUST be updated to call/observe the real 3-arg signature or removed.
- **FR-006**: `mark_degraded` already creates `source-incidents.md` with a `# Source incidents` header on first write and appends thereafter — this behaviour is CORRECT and MUST be preserved; only the broken call site (FR-001) prevents it from running. The test MUST assert the file is actually created end-to-end through `notify_required_source_degraded`, not just by calling `mark_degraded` directly.
- **FR-007** *(RESOLVED — Q2: APPEND-ONLY)*: When a previously-degraded source gets new citations, `source-incidents.md` MUST be updated by **appending** a `Resolved` line (`- <ts> — \`<name>\` resolved`) — never by deleting or rewriting prior entries. The file is an append-only audit log; current-state is derivable by the reader (last entry per source wins) and is also available structurally via the JSON sidecar (FR-001a).
- **FR-008** *(Q4 — CUMULATIVE)*: A one-shot, idempotent `scripts/reconcile_source_metrics.py` MUST undo the bug's durable harm — **wrongful archival**. For each source it computes `cited_now` = the number of notes in the **current** `data_vault/` that cite it (FR-003 predicate). Then: (a) any source with `status='archived'` **and** `cited_now > 0` is **un-archived** (`status='active'`); (b) any source with `cited_now > 0` has `consecutive_empty_cycles` **reset to 0**; (c) genuinely-uncited sources (`cited_now == 0`) are left untouched. It MAY also correct the **latest** `source_cycles` row's `notes_generated` for reporting accuracy, but MUST NOT rebuild per-cycle history (cumulative `total_notes_generated` is a derived `SUM`, not a stored column). `--dry-run` prints a per-source diff with zero mutations; `--apply` writes only `sources.db` (never the note tree). On a vault that never ran the buggy code, `--dry-run` MUST report no changes (zero false positives). Idempotent: a second `--apply` is a no-op.

### Key Entities

- **Source incident** (`_pipeline/source-incidents.md` entry): timestamp, source name, reason, optional resolution timestamp.
- **`source_urls` frontmatter field**: List of URLs from which this note's facts were drawn. Already exists in note schema; this spec consumes it correctly.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After a cycle where a required source fails, `_pipeline/source-incidents.md` exists in the vault and contains an entry for that source.
- **SC-002**: After a cycle that creates N notes citing source X, the `source_cycles` row for `(X, that cycle)` has `notes_generated == N` (and the summary's derived `total_notes_generated` for X increases by exactly N). *(Note: `notes_generated` is a per-cycle column on `source_cycles`, not on the `sources` table.)*
- **SC-003**: A source with citations in cycle K but zero new citations in cycle K+1 has `consecutive_empty_cycles == 1`, not `consecutive_empty_cycles >= 1`.
- **SC-004**: The regression test in FR-005 catches the original 2-arg-vs-3-arg signature bug. Prove by reverting the FR-001 fix locally — test must FAIL.
- **SC-005**: For an existing production vault that ran ≥10 cycles with the corrupted attribution, `scripts/reconcile_source_metrics.py --dry-run` reports the wrongly-archived / inflated-empty-streak sources; `--apply` un-archives the still-cited ones and resets their empty-streak. Acceptance: zero false positives in `--dry-run` on a vault that never ran the buggy code, and idempotent re-apply.

## Assumptions

- Note frontmatter consistently has `source_urls` on notes that cite sources (and lacks it on placeholder/concept-only notes — SG-005 already gates this). Malformed cases are skipped per Edge Cases.
- `mark_degraded(name, reason, vault_dir)` already has the correct 3-arg production signature and correct file-creation/append behaviour — **re-confirmed at the 053 base** (`pipeline/source_manager.py`). The bug is purely the 2-arg call site in `notify_required_source_degraded`.
- The `try/except` around the `mark_degraded` call was added for runtime-failure resilience but currently masks a *programming* error; narrowing it (FR-001) is safe because the only thing it should guard is a genuine I/O failure writing the markdown, not a signature mismatch.
- `consecutive_empty_cycles` is the canonical archival authority. Other archival signals (manual `locked=1`, spec-declared) are unaffected by this spec.

## Dependencies

- **Soft sequencing — spec 049 (Wave 1, cycle-helpers split).** `notify_required_source_degraded` currently lives in `pipeline/_cycle_helpers.py`, which 049 splits into `pipeline/_helpers/` submodules. 049 lands in Wave 1, **before** 029 (Wave 2). 029's FR-001 fix is a one-line change wherever the function ends up, but the test (FR-005) and any imports MUST target the post-049 module path. **Rebase 029 onto `main` after 049 merges** before implementing. Not a hard code dependency — just import-path coordination.
- **`vault/frontmatter.py`** (B4 canonical parser, shipped 0.3.1) — the attribution scan reads `source_urls` through it where possible. NOTE: `_count_notes_referencing` currently uses a *holdout* hand-rolled YAML parse (it deliberately `continue`s on malformed notes rather than raising `FrontmatterParseError`); FR-002's refactor SHOULD preserve that skip-don't-raise behaviour (Edge Cases) even if it routes through the canonical parser with a try/except.
- No dependency on any *other* unshipped spec.

## Acceptance coverage

Draft — evidence cells will be populated by `/speckit.tasks` for
this spec. Listed for the ADR-0008 guard so the spec is accepted
into the queue (the guard refuses any G/W/T-bearing spec without
this section).

| User Story | Evidence |
|------------|----------|
| US1 — Source degradation incidents are durably recorded | `tests/pipeline/test_source_manager_correctness.py::TestSourceIncidentsDurability` (`test_notify_writes_markdown_and_sidecar`, `test_enrichment_role_not_counted`, `test_resolved_line_appended_on_recovery`, `test_arity_bug_surfaces_not_swallowed`) |
| US2 — Source quality metrics accurately reflect note attribution | `tests/pipeline/test_source_manager_correctness.py::TestNormalizeSourceUrl` + `TestNoteCitesSource` + `TestRecordCycleAttribution` |
| US3 — Existing test coverage no longer hides production bugs | `tests/pipeline/test_source_failure_threshold.py::test_one_required_degraded_warns_and_continues` (now observes the real 3-arg `mark_degraded`) + `TestSourceIncidentsDurability::test_arity_bug_surfaces_not_swallowed` |

## Out of Scope

- Reworking how scout records new sources in the first place (separate concern; the URL-normalization helper introduced here may inform a future cleanup).
- Adding new source archival policies (e.g. value-tier weighting). Spec 005 owns adaptive sources; this spec is correctness-only.
- Cross-vault source quality sharing. Out of scope per ROADMAP H4 deferral.
