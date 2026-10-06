# Implementation Plan: Acronym-wikilink disambiguation

**Branch**: `067-acronym-wikilink-disambiguation` | **Date**: 2026-06-15 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/067-acronym-wikilink-disambiguation/spec.md`
**Target ship**: **1.0.0rc8 / 1.0.0** (rc8-wave umbrella #152; issue #154)

## Summary

The rc7 reference-vault shipped `CAP Theorem.md` with a corrupted first sentence —
*"The [[cache-aside pattern]] Theorem, formally proven by Eric Brewer…"* — and a
wrong alias stub `cap.md → redirect_to: cache-aside pattern`. Root cause
(confirmed by Phase-0 code audit of `pipeline/wikilinks.py`): `build_acronym_map`
**already drops ≥2-claim acronyms to `ambiguous`**, but the stub + body rewrite for
`CAP` were produced in an **earlier cycle when `cache-aside pattern` was the only
C-A-P note**. When `CAP Theorem` landed later, the acronym became ambiguous but the
**stale stub and stale body link were never re-evaluated** — and nothing protects a
note from having its own title's acronym rewritten to a sibling.

067 fixes this with four input-suppliers to the existing spec-062 acronym path
(the `_derive_acronym`/`build_acronym_map`/`_rewrite_acronym_body`/`_write_redirect_stub`
pipeline is reused; only the matching + a re-evaluation pass + a backstop gate are
added):

| FR | What | Primary code target (Phase-0 verified) |
| --- | --- | --- |
| **FR1** | Single-expansion-only auto-link; ambiguous → plain text (already partly true; harden + make stubs follow the same rule) | `pipeline/wikilinks.py` (`build_acronym_map`, `_rewrite_acronym_body`, `_write_redirect_stub`) + the **duplicate** in `scripts/validate_vault.py` (`_build_acronym_map`, `_derive_acronym`) kept in sync |
| **FR2** | Self-title protection: a note never links its own title's acronym to a sibling expansion (self-link or no-link wins); stale stubs/links re-evaluated when an acronym becomes ambiguous | `pipeline/wikilinks.py` (`_rewrite_acronym_body` self-skip + `resolve_acronym_links` stale-stub re-eval) |
| **FR3** | **FAIL** verifier rule: a note whose first body wikilink renames its own title is rejected ("wikilink title corruption") | `pipeline/verifier.py` (new `deterministic_wikilink_violations`, mirrors `deterministic_credibility_violations`; merged in `run_verifier_stage`) + `.agents/skills/verifier/SKILL.md` rule entry |
| **FR4/FR5** | Deterministic `./vault wikilinks --fix` sweep: repair ambiguous-acronym body links → plain text; re-point fixable stubs; remove orphaned/unfixable stubs | `cli/wikilinks.py` (NEW) + `cli/_parser.py` subparser + `templates/vault-script.sh.j2` case (mirror `digest`) |

No new runtime dependency (Principle V — stdlib + existing `pyyaml`). No `schema_version`
bump (alias-stub frontmatter shape unchanged). No ADR (calibrates existing spec-062
logic within existing principles). Standalone spec (Q5), not an amendment to 062.

## Technical Context

**Language/Version**: Python 3.11+ (per `pyproject.toml::requires-python`).
**Primary Dependencies**: stdlib + existing only — `pyyaml ≥ 6.0` (frontmatter),
`re` (acronym derivation + body rewrite), `pathlib`. **No new runtime dependency**
(Principle V).
**Storage**: filesystem under vault root. The sweep (FR4) *moves/edits* notes in
`data_vault/` and *deletes* orphaned `note_type: alias` stubs; no new `_pipeline/`
artifact. The verifier rule (FR3) is read-only at gate time (rejects, never rewrites).
**Testing**: pytest, seven-tier pyramid (ADR-0008). Extends
`tests/pipeline/test_acronym_alias_coverage.py` (FR1/FR2 map + rewrite + stub +
ambiguity), new tier-2 `pipeline/test_verifier.py` cases (FR3 FAIL), new
`cli/test_wikilinks_verb.py` (FR4/FR5 sweep + shim), and
`tests/scripts/test_validate_vault_*` for the synced duplicate.
**Target Platform**: macOS / Linux dev + CI.
**Project Type**: single-project Python CLI + Jinja2-templated vault scaffold.
**Performance Goals**: acronym map built once per cycle pass (existing); sweep is
O(notes) one-shot, zero-LLM. No hot-path regression.
**Constraints**: determinism boundary non-negotiable — **no LLM at gate or sweep
time** (Principle IV; dispatch allowlist stays empty). FR3 must not reject notes
whose first link is legitimately a different term (only the *own-title-acronym*
rewrite case). FR4 must be idempotent and never delete a stub that still has a
unique valid expansion + inbound links.
**Scale/Scope**: ~3 source files touched (`wikilinks.py`, `verifier.py`,
`scripts/validate_vault.py`) + 1 new CLI module + 1 shim case + 1 skill rule;
~1 day. Adds ~25–35 tests.

### Resolved unknowns (full detail in research.md)

- **D1** — Root cause is **stale state**, not a missing ambiguity check:
  `build_acronym_map` already drops ≥2-claim acronyms; the rc7 corruption is a
  stub/link created when the acronym was *singly* claimed and never revisited.
  → FR2 must add a re-evaluation pass, not just an ambiguity filter.
- **D2** — "First body wikilink renames the note's own title" (FR3) is defined
  deterministically: the note's title-acronym (`_derive_acronym(title)`) appears as
  the first `[[...]]` token in the body AND resolves to a stem ≠ the note's own
  title-stem. No LLM needed.
- **D3** — The acronym logic is **duplicated** in `scripts/validate_vault.py`
  (`_build_acronym_map`/`_derive_acronym`); FR1/FR2 changes MUST be mirrored or the
  validator drifts. Phase-0 flags consolidating to a shared helper as an optional
  cleanup (kept out of locked scope to limit blast radius).
- **D4** — Sweep verb mirrors the **shipped** `digest` wiring (`cli/digest.py` +
  `_parser.py` + `vault-script.sh.j2` case), NOT the 066 `re-grade` pattern (which
  isn't in `src/` yet). Flags: `--vault`, `--fix` (default dry-run), `--json`.
- **D5** — Orphan = `note_type: alias` stub with no inbound `[[...]]` reference AND
  no unambiguous expansion. Fixable stub = exactly one valid expansion → re-point
  `redirect_to`. Otherwise → delete (Q4).
- **D6** — Scope is the **spec-062 title-initials path** (`wikilinks.py`), not the
  legacy parenthetical-acronym checker (`scripts/check_acronym_links.py`), which is
  report-only and not the corruption source. Confirmed by the rc7 evidence shape.

## Constitution Check

*GATE: evaluated against constitution v1.4.0.*

| Principle | Verdict | Notes |
| --- | --- | --- |
| **I. Script-Validated Quality Gates** | ✅ PASS (reinforces) | FR3 adds a deterministic verifier rule; FR4 is a deterministic verb. Both are scripts, no LLM. |
| **II. Phase Sequencing** | ✅ PASS | No cycle-phase reordering. FR4 is an out-of-cycle ops verb (like `digest`). |
| **III. Test-First (TDD)** | ✅ PASS | Each FR ships its test file with/before impl; foreman `Testing Requirements` enriched at `/tasks` (ADR-0010). |
| **IV. Agent-Script Separation** | ✅ PASS (reinforces) | Disambiguation, the FAIL rule, and the sweep are all deterministic; **no LLM at gate or verb time**. Dispatch allowlist stays empty. |
| **V. Offline-First, No External Persistence** | ✅ PASS | No new dep; all logic is local string/frontmatter manipulation. |
| **VI. No Duplicate Notes** | ✅ PASS (reinforces) | FR4 *removes* detritus stubs and repairs links; never creates a duplicate. |
| **VII. External Sources Mandatory** | ✅ N/A | Untouched. |
| **VIII. No Placeholders / Stub-as-Fuel** | ✅ PASS (reinforces) | Alias stubs are graph-resolution nodes (062 FR3), explicitly exempt; FR4 prunes orphaned ones, reducing detritus. |
| **IX. Vault-First Citation** | ✅ N/A | Citations untouched. |
| **X. Vault History is Append-Only Git** | ✅ PASS | FR4 edits/deletes are committed by the normal cycle/ops commit path; the sweep is a manual verb whose changes the operator commits (or `--fix` can be made to commit — D4 defers commit policy to /tasks, Ask-First). |

**Ask-First items:**
1. **FR4 commit policy** — whether `./vault wikilinks --fix` auto-commits (like 066
   `re-grade`) or leaves changes staged for the operator. Plan recommends
   leave-uncommitted (simplest, mirrors `health` graph repair); **flagged** for
   `/tasks` confirmation.
2. **D3 duplicate-map consolidation** — keep two synced copies (low risk, locked
   scope) vs extract a shared helper (cleaner, wider blast radius). Plan keeps them
   synced; **flagged**.

**Gate result: PASS.** Complexity Tracking empty.

### Post-Design Re-check (after Phase 1)

No new dependency, no new principle, no `schema_version` bump. The one design
subtlety — that the bug is stale state rather than a missing filter (D1) — is
captured in the data-model "lifecycle" and the FR2 re-evaluation pass. Verdict
remains **PASS**.

## Project Structure

### Documentation (this feature)

```text
specs/067-acronym-wikilink-disambiguation/
├── plan.md          # This file
├── spec.md          # Feature spec (clarified 2026-06-15, 5/5)
├── research.md      # Phase 0 — decisions D1–D6 + rc7 blast-radius data
├── data-model.md    # Phase 1 — acronym map, alias stub lifecycle, title-corruption predicate, sweep action record
├── contracts/
│   ├── acronym-disambiguation.contract.md  # map rules + self-title protection + FR3 FAIL predicate
│   └── wikilinks-verb.contract.md          # ./vault wikilinks surface + sweep actions
├── quickstart.md    # Phase 1 — reproduce the rc7 CAP corruption; prove each FR fixes it
└── tasks.md         # Phase 2 (/speckit.tasks — NOT created here)
```

### Source Code (repository root) — files touched, by FR

```text
src/research_framework/
├── pipeline/
│   ├── wikilinks.py        # FR1/FR2: build_acronym_map (harden), _rewrite_acronym_body
│   │                       #   (self-title skip), _write_redirect_stub (ambiguity-aware),
│   │                       #   resolve_acronym_links (stale-stub re-eval pass)
│   └── verifier.py         # FR3 (NEW helper): deterministic_wikilink_violations + merge in run_verifier_stage
└── cli/
    ├── wikilinks.py        # FR4/FR5 (NEW): sweep — repair body links, re-point/remove stubs; --fix/--json
    └── _parser.py          # FR4: register `wikilinks` subparser (mirror `digest`)

scripts/
└── validate_vault.py       # FR1/FR2 (D3): mirror _build_acronym_map/_derive_acronym changes (keep in sync)

templates/
└── vault-script.sh.j2      # FR4: `wikilinks)` case + help line (mirror `digest)`)

.agents/skills/verifier/
└── SKILL.md                # FR3: add "wikilink title corruption" rule entry (deterministic twin is authoritative)

tests/
├── pipeline/
│   ├── test_acronym_alias_coverage.py   # FR1/FR2: self-title skip; stale-stub re-eval; ambiguous → plain text (extend)
│   └── test_verifier.py                 # FR3: first-link-renames-own-title → rejected; legit first link → not rejected (extend)
├── cli/
│   └── test_wikilinks_verb.py           # FR4/FR5 (NEW): dry-run report; --fix repairs links; re-point vs delete stubs; idempotency; shim routing
└── scripts/
    └── test_validate_vault_integrity.py # FR1/FR2 (D3): validator map stays in sync (extend)
```

**Structure Decision**: single-project layout, in-place extension of the spec-062
acronym module (`pipeline/wikilinks.py`) + the spec-055 verifier deterministic-check
seam (`pipeline/verifier.py`) + the shipped `digest` CLI-verb pattern. One genuinely
new file: `cli/wikilinks.py` (FR4). Everything else extends an existing surface; the
`scripts/validate_vault.py` duplicate is kept in sync (D3).

## Phase Sequencing for implementation (dependency-ordered)

FR1→FR2 are sequential (both in the acronym map/rewrite path); FR3 is independent
(verifier); FR4 depends on the FR1/FR2 rules (the sweep applies the same
disambiguation decision retroactively); FR5 is the sweep's stub branch. Recommended
`/speckit.tasks` ordering:

1. **FR1** (≈0.2d) — harden `build_acronym_map` (single-expansion-only is the
   contract; document the existing ambiguous-drop); make `_write_redirect_stub`
   refuse to (re)create a stub for an acronym that is now ambiguous. Mirror in
   `scripts/validate_vault.py`. Tests: ambiguous acronym yields no stub + no body
   link.
2. **FR2** (≈0.3d) — self-title protection in `_rewrite_acronym_body` (never rewrite
   a `[[ACRO]]` whose stem == the containing note's own title-stem to a sibling);
   add a stale-stub/link re-evaluation pass in `resolve_acronym_links` (when an
   acronym that previously mapped is now ambiguous, plain-text its body links and
   mark its stub orphaned). Tests: the exact rc7 CAP timeline (cache-aside first,
   CAP Theorem later) → no corruption.
3. **FR3** (≈0.2d) — `deterministic_wikilink_violations(vault_dir, note_rel, body)`:
   FAIL when the first body `[[...]]` token is the note's title-acronym resolving to
   a stem ≠ own title-stem; wire into `run_verifier_stage` before merge; add the rule
   to `verifier/SKILL.md`. Tests: CAP-class note rejected; clean note + legitimate
   first link not rejected.
4. **FR4/FR5** (≈0.3d) — `cli/wikilinks.py`: scan vault, build ambiguity set, repair
   ambiguous body links to plain text, re-point fixable stubs (single valid
   expansion), delete orphaned/unfixable stubs; `--fix` (default dry-run report) +
   `--json`; `_parser.py` subparser; shim `wikilinks)` case + help. Tests: dry-run
   reports without writing; `--fix` repairs the rc7 vault fixture; idempotency;
   stub re-point vs delete; shim routing.

**Pre-`/speckit.implement`**: dispatch the test-design subagent (ADR-0010) to enrich
`tasks.md` with `### Testing Requirements`; then implement; then foreman Arm A
(`verify_test_coverage.py`) + Arm B review before the PR.

## Complexity Tracking

> No Constitution Check violations require justification. Table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
