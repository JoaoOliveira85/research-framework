# Phase 0 Research: Acceptance harness

**Spec**: [spec.md](./spec.md) | **Date**: 2026-06-05

Reconciles §4's five user stories against the real tree (verified 2026-06-05). The
headline finding: **every primitive exists** — 063 is composition behind a new verb,
not new infrastructure.

## D1 — Verb surface: mirror the recently-added `status` / `digest` verbs

**Question.** Q1 chose a new `./vault acceptance` verb. How are verbs wired?

**Finding.** `cli/_parser.py::build_parser` registers each subcommand with
`sub.add_parser(...)` + `.set_defaults(func=...)`; the two most recent additions
(`status` :381, `digest` :386) are the cleanest templates (`--vault` required,
`--json` optional, a handler imported from a sibling module). The vault shim
(`templates/vault-script.sh.j2`) dispatches via `case "${CMD}" in` (:68) with explicit
`status)` (:117) / `digest)` (:120) entries.

**Decision.** Add an `acceptance` subparser (handler `_cmd_acceptance` in new
`cli/acceptance.py`) + an `acceptance)` shim case mirroring `status)`. Existing vaults
pick it up via `./vault regenerate-shim`. `--vault` required; `--json` for
machine-readable output; `--strict` to make WARN gates also non-zero (CI lever).

## D2 — The source-ledger is real, first-class, and importable

**Question.** US2 says "stop hand-joining; read the shipped ledger." Does it exist?

**Finding.** Yes — `scripts/source_ledger.py` is the 048-v2 MVP:
- `KIND = "source-ledger"`; `Verdict` enum = USED / SKIPPED_RELEVANCE / ACCESS_FAIL /
  PIPELINE_DROP / QUALITY_REJECT / NOT_REACHED.
- `resolve_verdict(signals)` (FR-020 state machine) + `collapse_verdict(...)` (per-cycle
  → highest precedence).
- Joins `cycle-NNN-scout.json`, `<vault>/_pipeline/sources.db`, `cycle-NNN-research.json`,
  `cycle-NNN-quality-report.json`. Contract:
  `specs/048-observability-v1/contracts/source-ledger-v2.contract.md`.
- Tests: `tests/scripts/test_source_ledger.py`.

**Decision.** US2's harness side **invokes** `scripts/source_ledger.py` (same
maintainer-script import pattern the pipeline already uses) rather than re-joining
artifacts. The harness reads the per-source verdicts and overlays the citation
cross-check.

## D3 — The citation join is the missing piece (and it's the 048-v2 amendment)

**Question.** rc1's ledger asserted ACCESS_FAIL/PIPELINE_DROP on sources the notes
*cited at 100%/71%/63%*. Where does that contradiction live?

**Finding.** `source_ledger.py` has `_source_urls(spec_sources)` (maps **spec**
sources → host set) but does **not** join the **notes'** cited `source_urls`. So the
ledger never sees that a "failed" source was, in fact, cited. The fix is two-sided:
- **Framework side (048-v2 amendment, sibling rc3 change):** build the note-citation
  corpus at ledger-build time; when a source's verdict ∈ {ACCESS_FAIL, PIPELINE_DROP}
  but it is demonstrably cited, downgrade the verdict to a new `LEDGER_DISAGREEMENT`
  marker.
- **Harness side (063 US2):** read the (reconciled) ledger and report
  `LEDGER_DISAGREEMENT` as the finding; grade SA-3/SA-4 against the reconciled view,
  not a wall of ACCESS_FAIL.

**Decision.** 063 US2 depends on the 048-v2 amendment for the *clean* signal but also
performs its own citation cross-check defensively, so the harness reports the
disagreement even if run against a pre-amendment ledger. The two pair (spec
§"Relationship to existing specs").

## D4 — Authority (053) + credibility (055) primitives already exist

**Question.** US3 grades 053 authority/trunk + 055 credibility/coi. New model code?

**Finding.** No.
- 053: `pipeline/source_authority.py` — `build_source_role_index(spec, vault_dir)` →
  `SourceRoleIndex` (role + priority + **derived trunk** = highest priority);
  `resolve_role(...)`. `scripts/check_trunk_inversion.py` already gates trunk inversion.
- 055: `vault/credibility.py` — `citation_credibility(entry)` (tier),
  `citation_coi(entry)` (COI bool), `build_credibility_context(spec, vault_dir)`,
  `validate_credibility_shape`.

**Decision.** US3's grader calls these per note citation: flag a note that cites
*against* its vault's derived trunk (authority inversion) and grade credibility tiers
+ COI presence (not just two-tier citation presence). The edge case "journal-first
vault" (spec §Edge Cases) is handled for free — `build_source_role_index` derives the
trunk from the vault's declared priorities, so a no-code vault grades against its own
trunk, never an assumed code trunk.

## D5 — Generic vs domain boundary is expressed by location

**Question.** Q3/Q5 — how is "framework owns generic, vault owns domain" expressed?

**Finding.** The generic gates are pure deterministic checks over framework-emitted
artifacts (run-report, ledger, frontmatter, git) — they belong in the installed
package. The domain probes (fingerprint trap, convergence confidence, breadth
probes) are *data + judgement* specific to one vault.

**Decision.** Generic gates live in `cli/acceptance.py` (framework, reusable across
tech-/ai-/codebase-vaults — SC-002). Domain probes live in-vault under
`_pipeline/acceptance/` (the same dir as the scorecard). The verb runs the generic
gates always and *discovers* (does not import) the in-vault domain probe pack. The
business `codebase-vault-acceptance-probes.md` shrinks to just domain probes (US4
GOLD anchors P1/P12 retained + breadth probes added). The framework never imports
vault domain code at runtime (boundary preserved, like spec-020 module isolation).

## Gate-to-sibling-signal map (why 063 is sequenced last)

| §4.1 gate | Consumes | From |
| --- | --- | --- |
| 1. No rejected notes in corpus | quarantine invariant + `rejected_unresolved` | spec 062 FR1 |
| 2. No duplicate note files | ` N.md`/content-hash detector | spec 062 FR2 (shared) |
| 3. Git integrity | untracked + one-commit-per-cycle | spec 062 FR2 / spec 050 |
| 4. Run-completion semantics | run-report `cycle_budget` provenance | spec 061 FR4 |
| 5. Cost / telemetry sanity | codex `cost_usd`/tokens | spec 028 amendment (FAILs $0 regardless) |
| 6. Template-version drift | note `template_version` vs shipped | self-contained |

Gates 5 + US2 degrade gracefully if their sibling amendment isn't present yet (they
FAIL-loud / cross-check defensively), so 063 is correct even if shipped slightly out
of order — but the clean signal needs 061/062/028/048 first.
