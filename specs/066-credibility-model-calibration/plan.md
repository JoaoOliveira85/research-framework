# Implementation Plan: Credibility-model calibration for canonical project domains

**Branch**: `066-credibility-model-calibration` | **Date**: 2026-06-15 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/066-credibility-model-calibration/spec.md`
**Target ship**: **1.0.0rc9 or 1.0.0** (rc8-wave umbrella #152; issue #153)

## Summary

The rc7 reference-vault run rejected 12/12 cycle notes with
`IX-credibility-unresolved` because the citations are **plain-string**
`source_urls` to canonical project domains (`fastify.dev`, `en.wikipedia.org`,
`github.com/<org>`, `docs.aws.amazon.com`, `martinfowler.com`, …) that carry no
inline `credibility` and match no `data_sources[].default_credibility`. Spec
055's `effective_level` therefore raised `CredibilityUnresolved` → FAIL → the
verifier became a 100%-reject blocker instead of a graded gate.

066 calibrates the model with four pieces, all *input-suppliers* to the existing
spec-055 resolution function (the COI cap + off-field downgrade + the `Level`
enum are untouched — Phase-0 D0/D1):

- **FR1 — default domain catalog** (research D4): a shipped, conservative
  (~67-entry, finalised in research.md) `data/credibility_catalog.yaml` mapping
  canonical hosts to tiers. Hybrid shape (Q6): wildcards (`*.dev`, `*.io`,
  `*.github.io`, `*.apache.org`, …) at **tier_3 only**; exact-match + host-path
  entries at tier_1/tier_2. `tier_N` is the operator-facing alias for the 055
  enum (`tier_1→primary`, `tier_2→corroborated`, `tier_3→commentary`; `unvetted`
  never catalog-assigned — D0).
- **FR2 — fail-open on unknown** (research D2): a catalog-miss but well-formed
  URL (`http(s)` + host has a dot) emits `IX-credibility-unresolved` as **WARN**,
  not FAIL; the note is no longer rejected on that signal alone. Malformed URLs
  (`prometheus:9090`, `<domain>`) keep FAILing on the existing rule.
- **FR3 — vault-local override** (research D3): a `credibility:` section in the
  existing `settings.yaml` with `trusted_domains` (Q11 full-replace) +
  `unknown_domain_policy: warn|reject` (Q10 strict opt-in). Shares the FR1 entry
  schema + loader.
- **FR4 — `./vault re-grade` verb** (research D5–D7): a manual, deterministic,
  zero-LLM pass over `_pipeline/quarantine/` that reinstates notes rejected
  *only* on credibility that now pass, moving them back to
  `data_vault/<NN - Category>/` and auto-committing
  `regrade(<date>): N notes reinstated`.

No new runtime dependency (Principle V — stdlib + existing `pyyaml`). No ADR
(the work calibrates an existing model within existing principles; cf. ADR-0002
phase-scoped citation validation lineage). Two Phase-0 corrections to the spec's
deferred details are recorded in research.md: the re-grade verdict source is
**in-note frontmatter, not `.failure.json`** (D5), and quarantine **flattens**
the category path so re-grade re-derives it (D7).

| FR | What | Primary code target (verified path) |
| --- | --- | --- |
| **FR1** | Default catalog + loader + tier→`Level` map | `src/research_framework/data/credibility_catalog.yaml` (new) + `vault/credibility.py` (catalog loader/resolver) |
| **FR2** | Catalog lookup in resolution + WARN/FAIL split | `vault/credibility.py` (`_lookup_default`, `effective_level`, `validate_credibility_shape` `severity`) + `pipeline/verifier.py` (`_merge_verifier_verdict` honours `severity`) |
| **FR3** | `settings.yaml::credibility:` section + override merge | `pipeline/settings.py` (`Settings.credibility` accessor) + `vault/credibility.py` (override overlay) |
| **FR4** | `./vault re-grade` verb | `cli/regrade.py` (new) + `cli/_parser.py` (subparser) + `templates/vault-script.sh.j2` (case) + shared `resolve_category_folder` helper |
| **FR5** | Regression fixture | `tests/fixtures/quality/` tech-stack fixture citing rc7-class hosts + baseline |

## Technical Context

**Language/Version**: Python 3.11+ (per `pyproject.toml::requires-python`).
**Primary Dependencies**: stdlib + existing only — `pyyaml ≥ 6.0` (catalog +
settings + frontmatter), `urllib.parse` (host extraction), `subprocess`/`git`
(re-grade commit via `pipeline.vault_commit`). **No new runtime dependency**
(Principle V).
**Storage**: filesystem under vault root + one shipped package data file.
New/changed artifacts: `src/research_framework/data/credibility_catalog.yaml`
(shipped, committed); `settings.yaml::credibility:` section (per-vault, additive,
no schema bump); re-grade moves files `_pipeline/quarantine/ → data_vault/` and
restamps frontmatter. No new `_pipeline/` artifact.
**Testing**: pytest, seven-tier pyramid (ADR-0008). New tier-1/2 unit suites
(catalog loader/resolver, override merge, WARN/FAIL split), tier-3 verifier +
re-grade integration, tier-2 CLI-parser/shim wiring, + the FR5 quality fixture
(gated by `build.sh --quality`).
**Target Platform**: macOS / Linux dev + CI.
**Project Type**: single-project Python CLI + Jinja2-templated vault scaffold.
**Performance Goals**: catalog parsed once + cached per `(vault, settings-mtime)`
(data-model Entity 3); resolution is O(1) exact + O(#suffix) per citation — no
hot-path regression. Re-grade is O(quarantined notes), one `git commit`.
**Constraints**: determinism boundary is non-negotiable — no LLM at gate/verb
time (Principle IV; the tier-2 dispatch guard stays empty). FR2 must not change
catalog-hit grading (only the unknown-domain branch). FR4 must never demote a
`data_vault/` note (Q8 quarantine-only) and must never leave a move uncommitted
(spec-062 atomicity / rc7 GA-003).
**Scale/Scope**: ~5 source files touched + 1 new CLI module + 1 data file + 1
shim case; ~1–1.5 days. Adds ~45–55 tests + 1 quality fixture/baseline.

### Resolved unknowns (full detail in research.md)

- **D0** — `tier_N` is an operator-facing alias mapping onto the 055 `Level`
  enum (`tier_1→primary`, `tier_2→corroborated`, `tier_3→commentary`); `unvetted`
  is never catalog-assigned. **Flagged** for operator confirmation at `/tasks`.
- **D1** — catalog slots as fallback steps 3 (override) + 4 (default) in
  `effective_level`, below explicit-citation + source-default, above
  ungraded/reject. Q11 "full override" = override-table-consulted-first.
- **D2** — well-formed = `http(s)` + host has a dot; validated on the real rc7
  messy tail (`prometheus:9090`/`<domain>` stay malformed-FAIL).
- **D3** — override surface = `settings.yaml::credibility:` (not a new file).
- **D4** — default catalog = shipped `data/credibility_catalog.yaml`, shared
  schema+loader with the override; wheel force-include + bundle copy.
- **D5** — **correction:** re-grade reads in-note frontmatter, not
  `.failure.json` (which doesn't exist); reinstate iff credibility-only AND
  now-clean.
- **D6** — `cli/regrade.py` + `re-grade` subparser + shim case; flags
  `--vault/--dry-run/--note/--json`; auto-commit `regrade(<date>): N`.
- **D7** — **correction:** quarantine flattens the path; re-grade re-derives
  `data_vault/<NN - Category>/` from `coverage_category` via the existing
  category→folder convention (shared helper).
- **D8** — scorecard `credibility ungraded` counter refinement is **optional**,
  kept out of locked scope per the spec's "no scorecard change needed".

## Constitution Check

*GATE: evaluated against constitution v1.4.0.*

| Principle | Verdict | Notes |
| --- | --- | --- |
| **I. Script-Validated Quality Gates** | ✅ PASS | FR2 keeps the credibility check a deterministic script; FR4 is a deterministic verb. FR5 adds a `build.sh --quality` regression fixture. No gate becomes LLM-driven. |
| **II. Phase Sequencing** | ✅ PASS | No cycle-phase reordering. FR4 is an out-of-cycle ops verb (like `acceptance`). |
| **III. Test-First (TDD)** | ✅ PASS | Each FR ships its test file with/before impl; foreman `Testing Requirements` enriched at `/tasks` (ADR-0010). |
| **IV. Agent-Script Separation** | ✅ PASS (reinforces) | The catalog/override/resolver/re-grade are all deterministic; **no LLM at gate or verb time**. The dispatch allowlist stays empty (re-grade never dispatches). |
| **V. Offline-First, No External Persistence** | ✅ PASS | No new dep; catalog is a shipped local YAML; override + re-grade are local files/git. The resolver does **not** fetch URLs (it pattern-matches hosts). |
| **VI. No Duplicate Notes** | ✅ PASS | FR4 *moves* a note out of quarantine (no copy); destination collision handling mirrors the spec-062 quarantine move. |
| **VII. External Sources Mandatory** | ✅ N/A | Untouched. |
| **VIII. No Placeholders / Stub-as-Fuel** | ✅ PASS | FR4 reinstates real notes; nothing stubbed. |
| **IX. Vault-First Citation** | ✅ PASS (reinforces) | 066 *unblocks* honest citations to canonical domains while keeping malformed/unknown-strict citations gated. FR4 only reinstates notes that genuinely pass the model. |
| **X. Vault History is Append-Only Git** | ✅ PASS (reinforces) | FR4 commits the reinstatement move atomically (`regrade(<date>): N`); never leaves it uncommitted (the rc7 GA-003 class). Spec-050 invariant via `vault_commit`. |

**Ask-First items:**
1. **D0 tier→`Level` mapping** — the spec says "per spec 055's existing
   tiering" but 055 has no `tier_N`. The plan adopts the only Q6-consistent
   mapping and **flags it** for explicit operator confirmation at `/tasks`
   (research D0). No principle impact; a pure naming decision.
2. **FR2 WARN downgrade** — converts a previously-blocking FAIL to advisory WARN
   by default. Authorised explicitly by Q1/Q10 (strict `reject` opt-in
   preserves the old semantics). Reinforces Principle IX rather than weakening
   it (the gate stops being a false-positive blocker).

**Gate result: PASS.** Complexity Tracking empty.

### Post-Design Re-check (after Phase 1)

No new dependency, no new principle, no `schema_version` bump (data-model
"Migration"). The one design subtlety — the `tier_N`↔`Level` mapping (D0) — is
recorded in the catalog contract and flagged Ask-First. The override's
"fully-replaces" semantics (Q11) falls out of the resolution ordering for free
(D1) with no extra bookkeeping. Verdict remains **PASS**.

## Project Structure

### Documentation (this feature)

```text
specs/066-credibility-model-calibration/
├── plan.md          # This file
├── spec.md          # Feature spec (clarified 2026-06-15, 12/12)
├── research.md      # Phase 0 — decisions D0–D8 + finalised FR1 catalog seed
├── data-model.md    # Phase 1 — catalog entry, settings section, resolved catalog, re-grade record, WARN/FAIL split
├── contracts/
│   ├── credibility-catalog.contract.md  # schema + tier map + resolution order + WARN/FAIL
│   └── regrade-verb.contract.md         # ./vault re-grade surface + reinstatement + commit
├── quickstart.md    # Phase 1 — reproduce the rc7 failure; prove each FR fixes it
└── tasks.md         # Phase 2 (/speckit.tasks — NOT created here)
```

### Source Code (repository root) — files touched, by FR

```text
src/research_framework/
├── data/
│   └── credibility_catalog.yaml   # FR1 (NEW): shipped default catalog (~67 entries, research.md seed)
├── vault/
│   └── credibility.py             # FR1/FR2/FR3: catalog loader + resolver; _lookup_default steps 3/4;
│                                   #   effective_level fall-open; validate_credibility_shape severity; override overlay
├── pipeline/
│   ├── settings.py                # FR3: Settings.credibility accessor (trusted_domains + unknown_domain_policy)
│   └── verifier.py                # FR2: _merge_verifier_verdict honours violation `severity` (warn ≠ reject)
├── cli/
│   ├── regrade.py                 # FR4 (NEW): re-grade verb (scan quarantine → reinstate → commit)
│   └── _parser.py                 # FR4: register `re-grade` subparser (mirror `acceptance`)
└── (shared) resolve_category_folder  # FR4/D7: coverage_category → data_vault/<NN - Cat>/ (extracted helper)

templates/
└── vault-script.sh.j2             # FR4: `re-grade)` case + help line (mirror `acceptance)`)

pyproject.toml                     # FR1: wheel force-include data/credibility_catalog.yaml
build.sh / bundle copy list        # FR1: ship the catalog into vault bundles (settings.*.yaml precedent)

tests/
├── vault/
│   └── test_credibility_catalog.py   # FR1: loader, tier→Level map, wildcard-tier3-only validation, match precedence
│   └── test_credibility.py           # FR2: resolution order steps 3/4; ungraded vs malformed; override overlay (extend existing)
├── pipeline/
│   └── test_verifier.py              # FR2: WARN unresolved does NOT reject; reject-policy FAILs; malformed still FAILs (extend)
│   └── test_settings_credibility.py  # FR3: section parse, defaults, full-replace semantics
├── cli/
│   └── test_regrade.py               # FR4: reinstate credibility-only; skip non-credibility; dry-run; commit/no-empty; destination
│   └── test_vault_script_new_verbs.py# FR4: `re-grade)` shim case routes correctly (extend existing)
└── quality/ + tests/fixtures/quality/
    └── tech-stack fixture + baseline # FR5: rc7-class hosts; rejection rate ≤ 10% on rc8+
```

**Structure Decision**: single-project layout, mostly in-place extension of the
spec-055 credibility module + the spec-062 quarantine/commit seams + the spec-063
CLI-verb pattern. Two genuinely new files: the shipped catalog YAML (FR1) and the
`cli/regrade.py` verb (FR4). Everything else extends an existing surface.

## Phase Sequencing for implementation (dependency-ordered)

FR1→FR2→FR3 are sequential (each builds the resolver); FR4 depends on the FR2
resolver; FR5 validates the whole. Recommended `/speckit.tasks` ordering:

1. **FR1** (≈0.3d) — author `data/credibility_catalog.yaml` (research seed);
   catalog loader + tier→`Level` map + wildcard-tier3-only validation + match
   precedence; wheel/bundle include; loader + resolver unit tests. No behaviour
   change yet (resolver not wired).
2. **FR2** (≈0.3d) — wire `_lookup_default` steps 3/4 into `effective_level`;
   add `severity` to `validate_credibility_shape`; make
   `verifier._merge_verifier_verdict` reject only on `severity: fail`;
   well-formed/malformed split. Tests: rc7-class hosts pass; unknown→WARN;
   malformed→FAIL; catalog-hit grading unchanged.
3. **FR3** (≈0.2d) — `Settings.credibility` accessor; override overlay onto the
   resolved catalog (Q11 full-replace); `unknown_domain_policy` warn/reject
   branch. Tests: section parse + defaults + replace + strict-mode FAIL.
4. **FR4** (≈0.4d) — `cli/regrade.py` (scan quarantine, credibility-only +
   now-clean criterion, restamp + move via `resolve_category_folder`,
   auto-commit `regrade(<date>): N`, `--dry-run/--note/--json`); `_parser.py`
   subparser; shim `re-grade)` case + help. Tests: reinstate, skip
   non-credibility, dry-run no-op, N=0 no-commit, destination resolution,
   idempotency, shim routing.
5. **FR5** (≈0.2d) — tech-stack quality fixture citing rc7-class hosts + committed
   baseline; assert verifier-rejection rate ≤ 10% under `build.sh --quality`.

**Pre-`/speckit.implement`**: dispatch the test-design subagent (ADR-0010) to
enrich `tasks.md` with `### Testing Requirements`; then implement; then foreman
Arm A (`verify_test_coverage.py`) + Arm B review before the PR.

## Complexity Tracking

> No Constitution Check violations require justification. Table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
