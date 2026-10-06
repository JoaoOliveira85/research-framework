# Implementation Plan: Source-Module Resilience Polish

**Branch**: `038-source-module-resilience` | **Date**: 2026-06-03 | **Spec**: [spec.md](./spec.md)
**Input**: `specs/038-source-module-resilience/spec.md` (CLARIFIED 2026-06-03, Q0-Q4 resolved)

## Summary

Spec 038 hardens the source-module pipeline for real-world vault runs by adding
**probe content** on top of the already-shipped spec-051 `preflight()` subprocess
contract (0.8.0) and the shipped 0.6.2 `raw_capture.py`. It does **not** re-spec
the preflight harness — that machinery (spawn, timeout, fail-closed verdict table,
orchestrator + `refresh-sources` wiring) already exists and is reused verbatim.

The five user stories reduce, after the spec-051 audit (`research.md`), to a small
set of deltas:

- **US1 (EMPTY vs FAILED)** — the `empty`/`error` enum + per-source watermark
  verdict already ship (`signal.py`, `cache.py`). Delta = surface the distinction
  in the cycle report + a **sustained-failure gate** (rolling `error`-rate over a
  window).
- **US2 (auth probe fails fast)** — delta = env-var-presence + connectivity probe
  *content* inside each module's existing `check()`, emitting the shipped
  `fatal_fail`/`warning` verdicts. Manifest `authentication` block declares the
  vars.
- **US3 (raw URLs survive sandbox)** — delta = a NEW `scripts/raw_capture_batch.py`
  driver that enumerates new-note `source_urls` and calls the shipped
  `raw_capture.capture()` per unique URL, outside the agent loop.
- **US4 (install preflight loud)** — delta = thin wiring: install-path `[Y/n]`
  confirm + `--accept-path`, `gh auth status`/connectivity/local-repo host checks in
  the `refresh-sources` sweep, O'Reilly opt-in tier, validator regression-lock.
- **US5 (archive.org fallback)** — delta = a **fail-and-defer** archive.org pass in
  `vault_health --apply`, recording `_pipeline/archive-snapshots.json`, exit 0.

**FR-014 (`DataSourceConfig.kind`) is DEFERRED** (ADR-0009 still PROPOSED) — tombstone only.

## Technical Context

**Language/Version**: Python 3.11+ (`requires-python = ">=3.11"`).
**Primary Dependencies**: stdlib + `pyyaml` (manifest/sources) + `jinja2` (templates,
unused here). **No new runtime dependencies** — Principle V.
**Storage**: filesystem under vault root. New/extended artifacts:
`_pipeline/sources/<module>/watermarks.json` (extended: `consecutive_error_cycles`),
`<vault>/raw_data/captures/<YYYY-MM-DD>/manifest.json` (new),
`_pipeline/archive-snapshots.json` (new), `_pipeline/preflight.json` /
`module_stats["preflight"]` (extended messages). Manifest schema amended (3 optional blocks).
**Testing**: pytest seven-tier pyramid (ADR-0008); fixture-overridable network probes
(env-override pattern, like `RSS_FIXTURE`/`YT_DLP_BIN`); LLM dispatch guard untouched.
**Target Platform**: macOS/Linux dev host; offline-capable (Principle V).
**Project Type**: single-project Python CLI + library (`src/research_framework/` + `scripts/`).
**Performance Goals**: auth probe < 2 s, time-to-failure < 5 s (SC-003); connectivity
probe bounded by `preflight.timeout_seconds` (≤300 s, default 30).
**Constraints**: modules CANNOT import from `src/research_framework/` (subprocess
isolation, Principle V/VIII) — probe helpers duplicated module-side where needed;
all network access fixture-overridable + opt-in.
**Scale/Scope**: 5 in-tree Tier-1 modules + `_template`; ~10-15 net-new source files
+ ~6 module-side `check()` extensions + ~40-60 tests.

## Constitution Check

*GATE: must pass before Phase 0 and re-check after Phase 1.*

| Principle | Compliance |
| --- | --- |
| **I. Script-Validated Quality Gates** | The sustained-failure gate (US1 #3) is a deterministic script verdict feeding the spec-022 harness — additive, not a new gate kind. PASS. |
| **III. Test-First (TDD)** | Every delta gets tests first (contract subprocess tests for module `check()` extensions; batch-script integration tests; validator regression-lock). PASS. |
| **IV. Agent-Script Separation** | All 038 work is script-side (preflight subprocess, batch driver, health pass). No LLM dispatch added; dispatch guard allowlist stays EMPTY. PASS. |
| **V. Offline-First, No External Persistence** | No new deps. Network probes (connectivity, archive.org) are opt-in + fixture-overridable + never auto-fire offline. `raw_capture_batch` mirrors LOCALLY only (no cloud — cloud is spec 044). PASS. |
| **VIII. Module Isolation / No Placeholders** | Auth/connectivity failures fail-close per module (skip-with-WARN, shipped verdict table) — one broken module never crashes the cycle. PASS. |
| **IX. Vault-First Citation** | `raw_capture_batch` + archive.org fallback *strengthen* Tier-2 citation durability (the principle's reason for existing). PASS. |
| **X. Vault History Append-Only Git** | New artifacts under `_pipeline/` and `raw_data/captures/` are gitignored vault sidecars (consistent with shipped `raw_data/`); no change to the commit lifecycle. PASS. |

**No violations** — Complexity Tracking table omitted. The plan deliberately *reuses*
shipped machinery rather than adding new abstractions (the chief simplicity win).

## Project Structure

### Documentation (this feature)

```text
specs/038-source-module-resilience/
├── plan.md              # this file
├── research.md          # shipped-preflight audit + delta scoping
├── quickstart.md        # operator-facing walkthrough of the new surfaces
├── data-model.md        # manifest blocks + 3 new/extended artifacts
├── contracts/
│   ├── manifest-extensions.md          # authentication/rate_limits/failure_policy
│   ├── raw-capture-batch.contract.md   # batch driver + manifest.json shape
│   └── archive-snapshots.schema.json   # _pipeline/archive-snapshots.json
└── tasks.md             # /speckit.tasks output (NOT created here)
```

### Source Code (delta files only — reuse everything else)

```text
src/research_framework/
├── pipeline/source_bridge/
│   ├── cache.py                 # EXTEND: WatermarkEntry += consecutive_error_cycles
│   ├── orchestrator.py          # EXTEND: bump consecutive_error_cycles on verdict=error;
│   │                            #         emit cycle-report "source health" line for error
│   └── discovery.py             # EXTEND: parse_manifest accepts authentication/rate_limits/
│                                #         failure_policy (optional, validated)
├── quality/
│   └── source_health.py         # NEW (or extend existing metric family): sustained-error gate
├── modules/{youtube,reddit,rss,oreilly,code,_template}/
│   ├── preflight.py             # EXTEND each check(): env-var presence + connectivity probe
│   └── manifest.yaml            # ADD authentication (+ rate_limits/failure_policy where apt)
└── cli/
    └── refresh_sources.py       # EXTEND sweep: gh auth status + connectivity + repo-path host checks

scripts/
├── raw_capture_batch.py         # NEW: batch driver over new-note source_urls (US3/FR-006)
└── vault_health.py              # EXTEND: archive.org fail-and-defer pass under --apply (US5/FR-008)

dist-templates/
└── install.sh                   # EXTEND: [Y/n] path confirm + --accept-path (FR-009)

specs/020-code-bridge/contracts/
└── manifest.schema.json         # AMEND: 3 optional blocks (additionalProperties: false today)

tests/
├── modules/<name>/test_preflight.py     # EXTEND: env-var + connectivity probe cases (fixture-override)
├── scripts/test_raw_capture_batch.py    # NEW: idempotency, exit-0-on-fail, manifest, dedup
├── scripts/test_vault_health_archive.py # NEW: fail-and-defer, exit-0, snapshot JSON
├── source_bridge/test_watermark_error_streak.py  # NEW: consecutive_error_cycles + gate
└── pipeline/test_validator_detailed_spec.py      # NEW: FR-011 regression-lock
```

**Structure Decision**: single-project layout; all deltas land in existing
directories. The only NEW top-level files are `scripts/raw_capture_batch.py`,
`quality/source_health.py` (or a metric added to the existing family), and the
spec-dir contracts. Module-side probe content lives in each module's existing
`preflight.py::check()` (subprocess-isolated; cannot import from `src/`).

## Phases

### Phase 0 — Research (DONE)
`research.md` audits the shipped surface (§A-§H). Key findings:
EMPTY/FAILED is already shipped as `empty`/`error` (don't rename); the preflight
spawn/verdict machinery is reused verbatim; FR-014 deferred; two /tasks-level
unknowns flagged (rate-limit enforcement timing, batch byte layout).

### Phase 1 — Design & Contracts
- `data-model.md`: the 3 manifest blocks + extended `WatermarkEntry` +
  `raw_capture_batch` manifest + `archive-snapshots.json`.
- `contracts/manifest-extensions.md`: `authentication`/`rate_limits`/`failure_policy`
  schema + defaults (absent ⇒ today's behaviour).
- `contracts/raw-capture-batch.contract.md`: CLI shape, manifest.json schema,
  idempotency + exit-0 semantics, frontmatter source.
- `contracts/archive-snapshots.schema.json`: fail-and-defer status enum.
- Amend `specs/020-code-bridge/contracts/manifest.schema.json` (the live schema).
- Re-run Constitution Check (no change expected).

### Phase 2 — Tasks (`/speckit.tasks`, NOT here)
Per-FR task breakdown + `### Testing Requirements` blocks (ADR-0010 foreman).
Resolve the two flagged unknowns at task time.

### Implementation sequencing (story priority)
1. **US1 + US2 (P1)** — manifest blocks + module `check()` probe content +
   `consecutive_error_cycles` + sustained-error gate + cycle-report line. These are
   the highest-value, lowest-risk deltas (reuse shipped machinery).
2. **US3 (P2)** — `raw_capture_batch.py` (independent; builds on shipped `capture()`).
3. **US4 (P2)** — install-path confirm + sweep host checks + O'Reilly opt-in +
   validator lock.
4. **US5 (P3)** — archive.org fail-and-defer in `vault_health --apply`.

Each story is independently testable + shippable (matches the spec's "Independent
Test" framing). US1/US2 alone would already close the headline pain.

## Test approach

- **Tier 1-2 (unit/contract)**: module `check()` extensions tested both via the
  pure `check()` helper AND the subprocess JSON-in/JSON-out contract (mirror the
  shipped `tests/modules/<name>/test_preflight.py` pattern). Env-var presence uses a
  `<MODULE>_PREFLIGHT_FAKE_ENV` override; connectivity uses a HEAD-probe fixture
  override (like `RSS_FIXTURE`). Manifest-block parsing validated in `discovery`.
- **Tier 2-3 (integration)**: `raw_capture_batch` against a fake frontmatter vault
  with stubbed `capture()` (no real network); assert dedup, manifest shape,
  idempotent resume, exit-0-on-all-failed. `vault_health` archive pass with a
  fixture-override snapshot fn; assert deferred status + exit 0.
- **Tier 2 (regression-lock)**: FR-011 validator detailed-spec traversal;
  `consecutive_error_cycles` streak → gate FAIL only past threshold.
- **Quality harness (`build.sh --quality`)**: SC-004 — run the 3 spec-022 fixtures,
  assert 0 EMPTY-vs-FAILED conflations + 0 silently-swallowed errors in source-quality.
- **No live LLM, no real `claude`/`codex`** — dispatch guard allowlist stays EMPTY.
  All network fixture-overridable (Principle V).

## Concrete delta inventory (what this plan commits to building)

| # | Delta | File(s) | FR |
| --- | --- | --- | --- |
| 1 | `authentication`/`rate_limits`/`failure_policy` manifest blocks (optional) | `manifest.schema.json`, `discovery.py`, `modules/*/manifest.yaml` | FR-001/003/004/013 |
| 2 | Env-var presence + connectivity probe in module `check()` | `modules/{youtube,reddit,rss,oreilly,code,_template}/preflight.py` | FR-002/010/012 |
| 3 | `consecutive_error_cycles` + sustained-error gate | `cache.py`, `orchestrator.py`, `quality/source_health.py` | FR-005 |
| 4 | Cycle-report "source health: <m> FAILED with <err>" line | `orchestrator.py` (+ reporter) | FR-005 US1#2 |
| 5 | `scripts/raw_capture_batch.py` (builds on `capture()`) | new | FR-006/007 |
| 6 | archive.org fail-and-defer in `vault_health --apply` | `vault_health.py`, `archive-snapshots.json` | FR-008 |
| 7 | Install path `[Y/n]` + `--accept-path` | `dist-templates/install.sh` | FR-009 |
| 8 | Host checks (`gh auth status`/connectivity/repo path) in sweep | `cli/refresh_sources.py` | FR-012 |
| 9 | Validator detailed-spec regression-lock | `tests/pipeline/test_validator_detailed_spec.py` | FR-011 |
| 10 | O'Reilly opt-in `tier:` default | `modules/oreilly/sources.yaml.template` | FR-015 |
| — | FR-014 `DataSourceConfig.kind` | **DEFERRED** (ADR-0009 PROPOSED) | FR-014 (tombstone) |

## Complexity Tracking

*No constitution violations — table intentionally empty. The plan's design driver is
maximal reuse of the shipped spec-051/0.6.2 surface; it introduces no new abstraction
layer.*

## NEEDS CLARIFICATION (resolve at /speckit.tasks)

1. **FR-003 rate-limit enforcement timing** — declare-only in v1 (recommended,
   matches the spec's "need real-world signal" assumption) vs. enforce client-side
   now (token-bucket duplicated per module). Plan proceeds with declare-only.
2. **`raw_capture_batch` byte layout** — manifest-index over `capture()`'s existing
   `year/month` layout (recommended, no fork) vs. literal `captures/<DATE>/<sha256>`
   via a `capture(target_dir=…)` override. Plan proceeds with manifest-index.

Neither blocks /plan; both are flagged for /tasks.
