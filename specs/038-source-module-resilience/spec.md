# Feature Specification: Source-Module Resilience Polish

**Feature Branch**: `038-source-module-resilience`
**Created**: 2026-05-27 (consolidated from `docs/TODO.md` restoration notes #10/#11/#12 + 5 install-preflight items during post-Wave-1 doc restructure).
**Status**: shipped(2026-06-03, PR #101) — SHIPPED (PR #101) — EMPTY-vs-FAILED gate, auth/rate-limit preflight sweep, archive.org fallback, install-preflight checks. **RESCOPED (Q0) to the *delta* over the shipped spec-051 `preflight()` contract (0.8.0)** — 038 adds probe *content* (auth/connectivity/archive.org/EMPTY-vs-FAILED), not a new preflight harness.

**Input**: Spec 020 ships the architecture but deliberately deferred the resilience contracts (rate-limits, auth probes, raw-URL capture, archive.org fallback, "empty vs failed" distinction, install preflight hardening) to keep the centrepiece shippable. Without these, a real-world revival cycle on `~/Documents/feeds-vault` (or any production vault) will silently swallow network errors, conflate "no hits" with "API broke", and lose source durability whenever the LLM's sandbox blocks network access. This spec is the hardening pass that takes the "happy path works" baseline (0.4.0) and adds the resilience contracts production needs.

## Clarifications

### Session 2026-06-03 — RESOLVED (all recommended)

- **Q0 (NEW, highest impact — rescope onto the shipped 051 `preflight()` contract).**
  Spec 051 (0.8.0) shipped the **mandatory per-module `preflight()` subprocess
  contract** (manifest `preflight` required, orchestrator spawns per module,
  `./vault refresh-sources` sweep, crash/timeout/garbage → `fatal_fail`,
  fail-closed skip-with-WARN), which already delivers much of this spec's original
  US2/US4 harness. **→ 038 rescopes to the *delta***: it adds the probe *content*
  (auth env-vars, connectivity, archive.org, EMPTY-vs-FAILED semantics) **on top of**
  the shipped `preflight()` seam — it does NOT re-implement the preflight machinery.
- **Q1 (FR-006 — raw-URL capture: batch vs per-module hook?) → separate
  `scripts/raw_capture_batch.py`** (centralized, runs once outside the agent loop =
  sandbox-proof; builds on the shipped 0.6.2 `raw_capture.py`; no per-module hook
  burden). (FR-006 resolved.)
- **Q2 (FR-008 — archive.org: throttle vs defer?) → fail-and-defer** (non-blocking;
  throttling 100 dead URLs at ~5 req/s could stall an unattended run — accumulate
  across cycles instead). (FR-008 resolved.)
- **Q3 (FR-013 — mandatory vs optional env probes?) → manifest-owned**: a module's
  `authentication.env_vars` are MANDATORY-for-that-module; external checks
  (`gh auth status`, connectivity) are WARN. Declarative per module (consistent
  with "module declares its needs", and 048-v2's WARN posture). (FR-013 resolved.)
- **Q4 (FR-014 — add `DataSourceConfig.kind`/`module` now?) → defer** until ADR-0009
  is ACCEPTED; FR-014 stays a tombstone. Not needed for the runs (modules already
  declare URL triggers per spec 020). (FR-014 unchanged.)

### Consistency notes (spec ↔ shipped contracts)

- **Verdict aliases (FR-005)**: Spec prose uses `EMPTY`/`FAILED`; the shipped
  spec-020 enum is lowercase `empty`/`error`. Do NOT rename JSON — treat uppercase
  as documentation aliases only.
- **Archive status (US5 / FR-008)**: Contract schema uses
  `archived` | `deferred` | `unarchivable`. Spec AC wording "unarchived" maps to
  `deferred` (retry next cycle) or `unarchivable` (robots/paywall/etc.) — not a
  fourth enum value.
- **Raw capture paths (FR-006)**: FR-006 prose uses `captures/<YYYY-MM-DD>/<sha256>`
  as the logical index key; on disk, bytes land in the shipped `raw_capture.capture()`
  `year/month` layout. The batch driver writes
  `captures/<YYYY-MM-DD>/manifest.json` mapping URL → path + status (manifest-index
  approach; no `target_dir=` fork).

## User Scenarios & Testing *(mandatory)*

### User Story 1 — A failing API is distinguished from an empty search (Priority: P1)

The `youtube` source module runs in cycle N. The API returns 200 OK with 0 new videos (quiet week). The cycle records this as `EMPTY`, source-quality metrics show the module as healthy, no warning fires.

In cycle N+1, the same module's API returns 401 Unauthorized (token expired). The cycle records this as `FAILED`, source-quality metrics flag the module as degraded, the cycle report includes a "source health: youtube FAILED with HTTP 401" entry, and a sustained-failure gate triggers if FAILED rate exceeds threshold over 3 cycles.

**Why this priority**: Conflating `EMPTY` (success, no hits) with `FAILED` (network/auth error) silently auto-deprecates healthy sources during quiet weeks AND silently masks broken sources during active weeks. Both failure modes burn operator trust in the source-quality signal.

**Independent Test**: Construct a fixture with two source modules — one returns valid empty results, one returns auth errors. Run a cycle. Assert: source-quality DB records the first as `EMPTY` and the second as `FAILED`; the cycle report flags only the second under "source warnings"; the source-quality moderate gate fires FAIL only when sustained `FAILED` rate > threshold.

**Acceptance Scenarios**:

1. **Given** `youtube` module returns 200 + 0 results, **When** the cycle completes, **Then** `_pipeline/sources/youtube/watermarks.json` records `last_status: "EMPTY"` and the cycle report does NOT mention youtube under "source warnings".
2. **Given** `youtube` module returns 401, **When** the cycle completes, **Then** `last_status: "FAILED"` is recorded with the underlying error, AND the cycle report includes a "source health: youtube FAILED with HTTP 401" entry, AND the cycle's exit code/behavior follows the module's documented `failure_policy`.
3. **Given** sustained `FAILED` rate >50% over 3 cycles for a single module, **When** the quality harness runs, **Then** the moderate gate fires FAIL with the per-module breakdown.

---

### User Story 2 — Per-module auth probe fails fast at preflight (Priority: P1)

An operator installs a vault with `youtube` + `oreilly` modules configured, but `YOUTUBE_API_KEY` is missing from `.env`. Today (0.4.0), the failure surfaces 15 minutes into cycle 1 when `extractor.py` makes its first API call and times out. After this spec, preflight runs every module's auth probe BEFORE cycle 1 starts; the missing key surfaces in <2 seconds with `module 'youtube': YOUTUBE_API_KEY env var missing`.

**Why this priority**: Catching misconfiguration at install time is dramatically cheaper than catching it mid-cycle. The 2026-05-15 trial run on `reference-vault` lost ~90 minutes to this exact failure mode.

**Independent Test**: A fixture vault with two modules where one has missing credentials. Run `./vault preflight` (or implicit preflight at cycle start). Assert: exit code non-zero; stderr names the misconfigured module + the missing env var(s); zero API calls were issued.

**Acceptance Scenarios**:

1. **Given** a vault with `youtube` configured and `YOUTUBE_API_KEY` unset, **When** the operator runs `./vault research`, **Then** preflight exits within 2 seconds with a clear "module 'youtube': missing env var YOUTUBE_API_KEY" error.
2. **Given** all configured modules' probes pass, **When** preflight completes, **Then** the cycle proceeds normally.
3. **Given** a module's probe issues a successful API call (`200 + valid payload shape`), **When** preflight completes, **Then** a `preflight.json` records `module: youtube, auth_probe_ok: true, probe_response_ms: 187`.

---

### User Story 3 — Raw URLs survive sandbox network blocks (Priority: P2)

A cycle runs with a sandboxed LLM agent (per feeds-vault 2026-05-13 incident). The agent writes notes but cannot fetch source URLs from inside its sandbox. After the cycle, `raw_capture_batch.py` runs OUTSIDE the agent loop, reads the `source_urls` from new-note frontmatter, and mirrors each URL's content to `<vault>/raw_data/captures/<YYYY-MM-DD>/<sha256>.{html,pdf,...}`. The source durability is preserved regardless of the agent's network access.

**Why this priority**: Two-tier citations (Principle IX) require Tier 1 sources to remain reachable. Without raw-URL mirroring, a future link-rot kill + sandbox-blocked agent jointly destroy the citation provenance. Mirroring outside the agent loop sidesteps both failure modes.

**Independent Test**: Run a cycle with `source_urls: [<url1>, <url2>]` in 3 new notes. Stub the agent to fail on all outbound network. Verify: after `raw_capture_batch.py` runs, `<vault>/raw_data/captures/<DATE>/` contains 2 mirror files (one per unique URL); the manifest maps each URL → file + capture timestamp + status; the cycle's notes remain valid.

**Acceptance Scenarios**:

1. **Given** a cycle produces 5 notes with 10 unique `source_urls` across them, **When** `raw_capture_batch.py` completes, **Then** `<vault>/raw_data/captures/<DATE>/` contains 10 mirror files + a manifest.
2. **Given** a URL fails to fetch (5xx or timeout), **When** `raw_capture_batch.py` finishes, **Then** the manifest records `status: "FAILED"` for that URL and the batch exits cleanly (no aborted run).
3. **Given** `raw_capture_batch.py` runs nightly, **When** an operator wants to verify a citation 6 months later, **Then** the captured file is readable from disk even if the original URL has 404'd.

---

### User Story 4 — Install preflight catches misconfigurations LOUDLY (Priority: P2)

Five concrete trial-run issues from the 2026-05-15 install on `reference-vault` get a structured preflight gate. Install wizard explicitly confirms destination path; O'Reilly failures surface as errors (not silent empty results); validator summaries read detailed-spec fields correctly; extended preflight includes `gh auth status`, local repo paths, env-var probes, and connectivity to common APIs; O'Reilly enrichment becomes opt-in via `sources.yaml::tiers:` block instead of broad-query default.

**Why this priority**: Trial runs that pass install but fail cycle 1 burn the most operator goodwill. The 5 items here are the concrete failure modes observed in production; the fix is preflight discipline.

**Acceptance Scenarios**:

1. **Given** an operator runs `install.sh`, **When** they pass `<VAULT_DIR>` argument, **Then** the wizard explicitly echoes "Installing into: <ABSOLUTE_PATH>; confirm? [Y/n]" before any write.
2. **Given** O'Reilly module is configured AND its API is unreachable at install, **When** preflight runs, **Then** it exits non-zero with a clear "module 'oreilly': API unreachable at <URL>" error.
3. **Given** an operator's vault uses detailed-spec frontmatter, **When** validator summaries run, **Then** all detailed-spec fields are correctly traversed (regression test against the pre-spec-025-B4 parser bug).
4. **Given** `gh` is not authenticated, **When** preflight runs on a vault that uses GitHub sources, **Then** preflight warns (or fails — Q3) with `gh auth status` output context.
5. **Given** a vault's `sources.yaml` has no explicit `tiers:` block, **When** the cycle runs, **Then** O'Reilly is NOT auto-included in broad queries (must be opt-in).

---

### User Story 5 — archive.org fallback for fragile URLs (Priority: P3)

A note cites a fragile URL (e.g. a personal blog that may go offline). `vault health --apply` detects URLs at risk (or already 404'ing), creates archive.org snapshots, and records `_pipeline/archive-snapshots.json` mapping URL → snapshot URL + timestamp + status. Subsequent citations can resolve to the archive snapshot if the original 404's later.

**Why this priority**: Two-tier citations are only durable if originals remain reachable OR archived. Most cycles won't trigger this; when they do, link rot is catastrophic.

**Acceptance Scenarios**:

1. **Given** a cycle's frontmatter includes 3 fragile URLs, **When** `vault health --apply` runs, **Then** archive.org snapshots are created and recorded in `_pipeline/archive-snapshots.json`.
2. **Given** archive.org snapshot creation itself fails (rate-limited), **When** the batch finishes, **Then** the URL is marked `deferred` (or `unarchivable` when permanently blocked) with the failure reason; batch exits 0 (non-fatal).

---

### Edge Cases

- What if a module's API returns 200 with a malformed payload that fails schema validation? → `FAILED` with `subtype: "schema_drift"` per spec 020 D8 (fail-closed unless `--force-stale-schema`).
- What if `raw_capture_batch.py` is interrupted (Ctrl-C, OOM)? → The manifest is written incrementally; resuming re-fetches only URLs without a manifest entry.
- What if the same URL appears in 50 notes? → Captured ONCE per cycle (by `sha256(url)`); manifest records all citing notes.
- What if archive.org returns a "snapshot already exists" response? → Treat as success; record the existing snapshot URL.
- What if a sandboxed LLM cannot fetch raw URLs during note writing AND `raw_capture_batch.py` cannot run (host blocks outbound network too)? → Operator-level config issue; raw_capture exits non-zero with clear message; no mirroring possible.
- What if a vault is configured with a module but the module's auth credentials are absent? → Preflight fails LOUDLY at install/cycle start; never wait for first API call.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Each source module's `manifest.yaml` MUST include an `authentication` section enumerating: env vars consumed (list), a probe-command spec (a single API call that validates creds + connectivity), and the expected probe response shape. Modules without auth declare `authentication: none`.
- **FR-002**: Preflight MUST execute every configured module's auth probe BEFORE the cycle starts. Probes failing per their `failure_policy` block the cycle with a clear message naming the module + the missing/invalid credential. Probes succeeding record the probe duration + status in `_pipeline/preflight.json`.
- **FR-003**: Each source module's `manifest.yaml` MUST **declare** per-module rate limits: requests-per-minute cap, requests-per-hour cap, burst policy (default `none`), retry/backoff curve (default `exponential(base=2, max=300s, jitter=0.2)`). Client-side **enforcement is deferred** (out of v1 scope).
- **FR-004**: Each module's `manifest.yaml` MUST include a `failure_policy` field with enum value: `block_cycle` (default — fail the cycle on persistent error), `degrade_gracefully` (warn + skip the module's contribution this cycle), or `defer` (mark for retry next cycle, continue without).
- **FR-005**: The module status enum MUST include `EMPTY` (200 OK, zero hits — success state) as distinct from `FAILED` (network/auth/parsing error). Per spec 020 the enum is owned by the source-bridge contract; this spec amends it. `_pipeline/sources/<module>/watermarks.json` MUST record `last_status` from this enum per cycle.
- **FR-006**: Raw-URL capture MUST mirror new-note `source_urls` to disk OUTSIDE the agent loop via a **separate `scripts/raw_capture_batch.py`** (Clarifications Q1 — centralized, sandbox-proof, builds on the shipped 0.6.2 `raw_capture.py`; NOT a per-module hook). Logical index: `<vault>/raw_data/captures/<YYYY-MM-DD>/manifest.json` mapping URL → captured-path + capture-timestamp + status + citing-notes; mirrored bytes use the shipped `capture()` `year/month` layout (see Consistency notes — no `target_dir=` fork).
- **FR-007**: Raw capture MUST be idempotent — re-running over the same cycle's URLs MUST NOT re-fetch URLs already captured; partial-run resumability MUST follow the manifest's status field.
- **FR-008**: `vault health --apply` MUST create archive.org snapshots for URLs flagged fragile, using a **fail-and-defer** strategy (Clarifications Q2 — non-blocking; on rate-limit/failure it records the URL for a later cycle rather than throttling the run to completion). Output: `_pipeline/archive-snapshots.json` mapping URL → snapshot URL + timestamp + status (incl. `deferred`). The batch MUST exit 0 even when snapshots are deferred (US5 is non-fatal).
- **FR-009**: Install wizard MUST explicitly confirm the destination path: echo the absolute path AND prompt `[Y/n]` in TTY mode, OR refuse to proceed without an explicit `--accept-path <PATH>` flag in headless mode.
- **FR-010**: O'Reilly module (and any module declaring `failure_policy: block_cycle`) MUST surface API/network failures LOUDLY in preflight — exit non-zero with the module name + the underlying error. Silent empty-result regressions are explicit FR-005 violations.
- **FR-011**: Validator summaries MUST read detailed-spec frontmatter fields correctly across the canonical `vault/frontmatter.py` parser. Regression test against the pre-spec-025-B4 parser bug.
- **FR-012**: Extended preflight MUST run: `gh auth status` (where any source module uses GitHub), local repo path checks (clone existence for code-bridge modules), env-var probes per module (FR-001), connectivity probes to module-declared API endpoints. Each check has a status (`ok`/`warn`/`fail`) and feeds the cycle-blocker policy.
- **FR-013**: The env-var probe matrix MUST classify each variable as MANDATORY (block install) or OPTIONAL (warn). Per Q3, the exact matrix is owned by each module's manifest; defaults: anything in `authentication: env_vars:` is MANDATORY for that module.
- **FR-014**: When ADR-0009 reaches ACCEPTED status (Q4), `DataSourceConfig` MAY add a `kind` / `module` field. Implementation deferred until ADR-0009 settles; the spec amendment lives here as a tombstone reference.
- **FR-015**: O'Reilly module MUST default to opt-in enrichment via `sources.yaml::tiers:` block (not broad-query default). Operators wanting O'Reilly in broad queries must explicitly list it under a `tier: broad` block.

### Key Entities

- **`manifest.yaml` extensions** (additions to spec 020's contract): new keys `authentication`, `rate_limits`, `failure_policy`. The `status` enum gains `EMPTY` per FR-005.
- **`raw_capture_batch.py`**: Reads `source_urls` from new-note frontmatter; mirrors HTTP content via shipped `capture()` (year/month byte layout); emits manifest index at `<vault>/raw_data/captures/<YYYY-MM-DD>/manifest.json`. Runs OUTSIDE the agent loop so sandboxed cycles still preserve source durability.
- **`<vault>/raw_data/captures/<YYYY-MM-DD>/manifest.json`**: URL → captured path + capture timestamp + status (`OK` | `FAILED` | `PENDING`) + citing notes (list of note paths).
- **`_pipeline/archive-snapshots.json`**: URL → archive.org snapshot URL + creation timestamp + status. Persistent across cycles.
- **`_pipeline/preflight.json`** extension: existing preflight artifact gains a `module_probes` section with one entry per configured module: `{module, auth_probe_status, auth_probe_ms, connectivity_status, connectivity_ms, errors}`.
- **`empty` vs `failed` classifier** (FR-005): the per-module classifier deciding whether a 200 OK + zero hits is `EMPTY` or `FAILED`. Owned by each module's `extractor.py`; mandatory contract.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of Tier-1 source modules ship `manifest.yaml` with documented + tested `authentication` + `rate_limits` + `failure_policy` sections.
- **SC-002**: For a vault with 5 broken URLs (404 + 5xx) in cycle 1, `raw_capture_batch.py` produces 0 successful mirror files but completes cleanly (no aborts) and records 5 `FAILED` entries in the manifest.
- **SC-003**: A trial install on a fresh machine with all 5 preflight checks from US4 passes when correctly configured; fails LOUDLY with exact missing-field details when misconfigured. Time-to-failure < 5 seconds.
- **SC-004**: Across the feeds-vault fixture's full backlog (Milestones A→B→C of Wave 2), 0 silently-swallowed network errors and 0 `EMPTY`-vs-`FAILED` conflations in the source-quality DB.
- **SC-005**: archive.org fallback creates snapshots for ≥80% of URLs flagged fragile during a `vault health --apply` run on the feeds-vault fixture (the remaining 20% may legitimately fail to snapshot due to robots.txt, paywall, or media types).

## Assumptions

- Spec 020 is shipped (✓ 0.4.0, 2026-05-27). The contract additions here are ADDITIONS, not REPLACEMENTS.
- At least 2 Tier-1 source modules (Wave 2 / Milestones A+B) are ported BEFORE this spec is implemented — we need real-world signal on which failure modes actually occur in production.
- archive.org is a viable fallback for ≥80% of citation URLs (text/HTML content). Media URLs (video, large PDFs) may not snapshot cleanly; that's expected.
- Sandboxed LLM agent environments (per 2026-05-13 feeds-vault incident) are common enough that raw-URL capture outside the agent loop is the right architectural call.

## Dependencies

- **Hard**: Spec 020 (source-module architecture) — manifest.yaml contract owner.
- **Hard**: At least 2 Tier-1 source modules ported (Wave 2 / Milestones A+B). Without real-world signal, this spec is speculative.
- **Soft**: Spec 030 (quality harness v3) — source-quality metrics from 030 incorporate the resilience signals from this spec (`source_quality` metric family).
- **Soft**: ADR-0009 ACCEPTED — `DataSourceConfig.kind` field (Q4 / FR-014).
- **Soft**: Spec 028 (telemetry sidecar) — preflight + module probe timings feed into the sidecar v1.1 schema.

## Acceptance coverage

Evidence populated 2026-06-03 (T050). FR-014 (`DataSourceConfig.kind`/`module`)
remains a **tombstone** — no code shipped; deferred until ADR-0009 is ACCEPTED
(see §Clarifications Q4 / FR-014).

| User Story | Evidence |
|---|---|
| US1 — Empty vs failed distinction | `tests/quality/unit/test_source_health_gate.py` + `tests/scripts/test_raw_capture.py` (SC-004 EMPTY-vs-FAILED) |
| US2 — Per-module auth probe fails fast | `tests/source_bridge/test_preflight_orchestration.py` + `tests/source_bridge/test_preflight_runner.py` |
| US3 — Raw URLs survive sandbox blocks | `tests/scripts/test_raw_capture.py` + `tests/processors/test_archive.py` |
| US4 — Install preflight catches misconfigs | `tests/source_bridge/test_manifest_preflight_required.py` + `tests/cli/test_refresh_sources_host_checks.py` |
| US5 — archive.org fallback for fragile URLs | `tests/scripts/test_vault_health_archive.py` + `tests/processors/test_archive.py` |

## Out of Scope

- Cross-module rate-limit coordination (each module owns its own quota; a shared rate-limit bus would require a synchronization primitive deferred until concrete evidence of cross-module contention).
- Replacing spec 020's consensus contract (this spec sits on TOP of, not under).
- Source module ports themselves (those are Wave 2 / Tier-1 work; this spec lands AFTER).
- Multi-host raw-URL mirroring (e.g. mirror to S3 + local). Local-disk only in v1; cloud mirror is spec 044's territory.
- General-purpose URL-archive-and-search infrastructure (we capture raw bytes; we don't index them).

---

*Tasks + analyze complete 2026-06-03 (Q0-Q4 resolved — see Clarifications). Rescoped onto the shipped spec-051 `preflight()` contract. Next: foreman test-design → `/speckit.implement`.*
