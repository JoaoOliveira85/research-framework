# Phase 0 — Research: Acronym-wikilink disambiguation (067)

All decisions grounded in (a) a live audit of `~/Documents/reference-vault-rc7/` and
(b) a code audit of `pipeline/wikilinks.py` + `scripts/validate_vault.py` +
`pipeline/verifier.py`.

## rc7 blast-radius data (the evidence)

- `data_vault/cap.md` — `note_type: alias`, `redirect_to: cache-aside pattern`
  (WRONG: should be `CAP Theorem`).
- `data_vault/01 - Concepts/CAP Theorem.md` body line 1: *"The
  [[cache-aside pattern]] Theorem, formally proven by Eric Brewer…"* — first
  sentence corruption.
- **55** `note_type: alias` acronym stubs at `data_vault/` root; spot-checked
  mis-assignments: `ai → apache iceberg`, `cap → cache-aside pattern`,
  `ct → cap theorem`. Several are arguable; CAP is the unambiguous corruption.
- Only **2** notes contain a body `[[cache-aside pattern]]` link (CAP Theorem.md is
  one) — blast radius of *visible* body corruption is small, but the *systemic*
  risk spans all 55 stubs.

## D1 — Root cause: stale state, not a missing ambiguity filter

**Decision**: Treat the bug as stale, un-revisited acronym state. **Rationale**:
`build_acronym_map` (wikilinks.py:236–285) **already** collects all title-initials
claims and drops any acronym with ≥2 claims into `ambiguous` (lines 275–285). So a
*currently*-ambiguous acronym is already left unlinked. The rc7 `cap.md` exists
because, in an earlier cycle, `cache-aside pattern` was the **only** C-A-P note → CAP
mapped unambiguously → stub written + body link rewritten. `CAP Theorem` arrived a
later cycle, making CAP ambiguous — but the **existing** stub and the **existing**
body link were never re-evaluated. **Alternatives considered**: (a) only add the
ambiguity filter — rejected, it already exists and wouldn't fix stale state; (b)
rebuild all links every cycle from scratch — rejected as too broad/expensive and
risks churn. Chosen: a targeted re-evaluation pass (FR2) + self-title protection +
the FR3 backstop + the FR4 one-off sweep for existing vaults.

## D2 — FR3 "title corruption" predicate (deterministic)

**Decision**: A note triggers the FAIL rule iff `_derive_acronym(title)` (its own
title-acronym) appears as the **first** `[[...]]` token in the body AND that token
resolves (via the acronym map) to a stem `!=` the note's own title-stem.
**Rationale**: This is exactly the CAP case (`CAP Theorem` → first link `[[cache-aside
pattern]]`) and is computable with the existing `_derive_acronym` + the acronym map,
no LLM. **Alternatives considered**: LLM "does this read right?" check (rejected —
Principle IV, non-deterministic); flag *any* first-link rewrite (rejected — too
broad; a note legitimately may open with a different concept's link).

## D3 — Duplicate acronym logic must stay in sync

**Decision**: Mirror FR1/FR2 changes in `scripts/validate_vault.py`
(`_build_acronym_map`:176–215, `_derive_acronym`:100–109), which is a standalone copy
of the `wikilinks.py` logic. **Rationale**: `validate_vault.py` builds its own map to
WARN on ambiguous acronyms (lines 431–435); if it drifts from the pipeline rule the
validator and the cycle disagree. **Alternatives considered**: extract a shared helper
both import — cleaner but a wider blast radius across two long-stable modules; flagged
Ask-First, kept out of locked scope for rc8.

## D4 — Sweep verb wiring mirrors `digest` (shipped), not `re-grade` (not in src yet)

**Decision**: `cli/wikilinks.py` + a `wikilinks` subparser in `cli/_parser.py` + a
`wikilinks)` case in `templates/vault-script.sh.j2`, mirroring the **shipped**
`digest` verb (cli/digest.py + parser 407–426 + shim 120–121). **Rationale**: 066's
`re-grade` is only documented in a contract, not implemented in `src/` — `digest` is
the live, read-mostly precedent. Flags: `--vault`, `--fix` (default = dry-run report),
`--json`. **Alternatives considered**: fold into the existing `health` verb
(`scripts/vault_health.py` has `scan_wikilinks`/`apply_wikilink_fixes`) — rejected:
`health` is graph-repair (broken links), not acronym disambiguation; mixing concerns.

## D5 — Stub classification for the sweep (FR4/FR5)

**Decision**: For each `note_type: alias` stub: (1) **fixable** = exactly one valid
(unambiguous) expansion exists → re-point `redirect_to` to it; (2) **orphan/unfixable**
= zero inbound `[[...]]` references AND (ambiguous OR no valid expansion) → delete;
(3) otherwise leave untouched. Body links: any `[[ACRO]]`/`[[stem]]` whose acronym is
ambiguous → convert to **plain text** (the acronym string). **Rationale**: matches Q4
("re-point fixable, remove orphaned/unfixable"). **Alternatives considered**: keep all
stubs as redirects (rejected — leaves the wrong `cap→cache-aside` redirect live);
delete all auto stubs (rejected — discards genuinely-useful single-expansion ones).

## D6 — Scope is the spec-062 title-initials path, not the parenthetical checker

**Decision**: 067 touches `pipeline/wikilinks.py` (title-initials acronyms +
all-caps `[[TOKEN]]` rewrite), not the legacy `scripts/check_acronym_links.py`
(parenthetical `Name (ABBR)` first-occurrence checker, report-only via
`postprocess.py`). **Rationale**: the rc7 corruption (`[[cache-aside pattern]]`
replacing `CAP`) is produced by `_rewrite_acronym_body` mapping a bare `[[CAP]]` to a
stem — the spec-062 path. The parenthetical checker only *reports* missing links and
never rewrites bodies, so it cannot have caused the corruption. **Alternatives
considered**: also harden the parenthetical path — deferred; out of the rc7 evidence
shape and locked scope.

## Summary of locked decisions

| ID | Decision |
| --- | --- |
| D1 | Bug = stale un-revisited state; fix = self-title protection + re-eval pass + backstop gate + one-off sweep (not just an ambiguity filter, which already exists). |
| D2 | FR3 predicate: own title-acronym is the first body `[[...]]` and resolves to a non-self stem → FAIL (deterministic). |
| D3 | Mirror FR1/FR2 in `scripts/validate_vault.py`; consolidation flagged Ask-First. |
| D4 | `./vault wikilinks --fix` mirrors the shipped `digest` wiring; dry-run default. |
| D5 | Sweep: re-point fixable stubs, delete orphan/unfixable, plain-text ambiguous body links; idempotent. |
| D6 | Scope = spec-062 title-initials path (`wikilinks.py`), not the parenthetical checker. |
