# Tasks: Credibility-model calibration (spec 066)

> **Ledger** — this spec shipped; the boxes below are a historical record, not a live gate (CONTRIBUTING.md § 2). The Status header in `spec.md` is the source of truth for what shipped.

**Status:** IMPLEMENTED (2026-06-15). Tasks authored retroactively from the
contracts + data-model during `/speckit.implement everything`; all complete.
Contracts: `contracts/credibility-catalog.contract.md`,
`contracts/regrade-verb.contract.md`.

## Phase 1 — FR1 default catalog + resolver

- T001 Author `src/research_framework/data/credibility_catalog.yaml` — the
  default catalog (~60 entries; tier_1/2/3; exact / host_suffix / host_path;
  Q6 wildcards-are-tier_3-only). Seed list = research.md "Finalised FR1 default
  catalog".
- T002 `src/research_framework/vault/credibility_catalog.py` —
  `ResolvedCatalog` dataclass + `lookup(url)` (exact → host_path → host_suffix),
  `TIER_TO_LEVEL`, `is_malformed_url`, fail-closed loader
  (`load_default_catalog` / `build_resolved_catalog`) with Q11 override overlay
  and the default-catalog wildcard-tier_3 validation.
- T003 [tests] `tests/vault/test_credibility_catalog.py` — tier mapping,
  rc7 hosts resolve, host_path ≥2 segments, wildcard tier_3, malformed
  detection, override replacement, fail-closed bad-entry drop.

## Phase 2 — FR3 vault override settings

- T004 `pipeline/settings.py` — `CredibilitySettings`
  (`unknown_domain_policy` + `trusted_domains`), `_parse_credibility`,
  `VaultSettings.credibility`, extras-exclusion key.
- T005 [tests] `tests/pipeline/test_settings_credibility.py` — absent block
  defaults, policy + trusted parse, bad-policy / missing-domain / missing-tier /
  non-mapping rejection.

## Phase 3 — FR1/FR2 wire catalog into the credibility model

- T006 `vault/credibility.py` — `CredibilityContext.catalog` +
  `unknown_domain_policy` property; `_load_catalog`; `_lookup_default` consults
  the catalog after the source-default miss; `validate_credibility_shape`
  malformed-vs-unresolved split + per-violation `severity` (warn vs fail).
  (Lazy imports break the `credibility ↔ credibility_catalog` cycle.)
- T007 `pipeline/verifier.py::_merge_verifier_verdict` — only `severity:
  fail` shape violations force `rejected`; `warn` ones attach as advisory
  notes; absent severity defaults to `fail` (055 back-compat).
- T008 [tests] `tests/vault/test_credibility_catalog_resolution.py` +
  `tests/pipeline/test_verifier_severity.py` — catalog-supplied levels,
  COI/off-field on top, override promote/replace, WARN/FAIL split, merge logic.

## Phase 4 — FR4 `./vault re-grade` verb

- T009 `pipeline/coverage.py::resolve_category_folder` (D7) — re-derive the
  `data_vault/<NN - Category>/` destination from `coverage_category`.
- T010 `pipeline/vault_commit.py::commit_regrade` — `regrade(<date>): N
  notes reinstated` one-commit-per-run (Q9; never empty).
- T011 `cli/regrade.py` — `run_regrade` + `_cmd_regrade`; reinstatement
  criterion (credibility-only AND now-clean), atomic restamp + move + backlog
  pointer drop; `--dry-run` / `--note` / `--json`; idempotent; zero LLM.
- T012 `cli/_parser.py` `re-grade` subcommand + `templates/vault-script.sh.j2`
  `re-grade)` case + usage line.
- T013 [tests] `tests/cli/test_regrade.py` + `tests/pipeline/test_resolve_category_folder.py`
  — reinstate / still-quarantined (reject) / reinstate (warn) / skipped
  non-credibility / dry-run / idempotency / `--note` / JSON; folder resolution.

## Phase 5 — ship gates

- T014 `tests/cli/test_build_parser_stable.py` — add `re-grade` to the
  expected subcommand registry + regenerate the help goldens.
- T015 Catalog ships in the wheel (package data under
  `research_framework/data/`, same mechanism as `modules/*/manifest.yaml`).
- T016 `ruff check` + `ruff format --check` clean; `build.sh --quality`
  3/3 fixtures green; spec status flipped to IMPLEMENTED.
