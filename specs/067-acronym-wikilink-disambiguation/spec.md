---
spec_number: 067
title: Acronym wikilink disambiguation — multi-expansion acronyms must not auto-link
status: SHIPPED 1.0.0rc9 (2026-06-15, PR #172, squash b106723) — rc8-wave umbrella #152 (CLOSED). Self-title protection + now-ambiguous re-eval in pipeline/wikilinks.py (FR1/FR2), deterministic IX-wikilink-title-corruption verifier gate (FR3), ./vault wikilinks sweep verb (FR4/FR5), validate_vault map parity (C1-b). ~17 new tests green; build.sh-gated regression guard; ruff clean. FOLLOW-UP: PR #179 [Unreleased] — the sweep now also retroactively heals the fully-expanded self-acronym corruption (bare [[phrase]] whose derived acronym is the note's own title-acronym → plain acronym); verified the rc7 CAP Theorem.md body links heal.
target_version: 1.0.0rc9 / 1.0.0
created: 2026-06-14
source_input: |
  2026-06-13 rc7 reference-vault validation run (`~/Documents/reference-vault-rc7/`,
  GitHub issue #154, umbrella #152). The shipped note `CAP Theorem.md`
  opens with "The [[cache-aside pattern]] Theorem, formally proven by
  Eric Brewer in 2002…" — spec 062's acronym alias / first-occurrence-link
  logic identified "CAP" as an acronym and rewrote the body link to
  point at `cache-aside pattern` (whose initials ALSO spell C-A-P) instead
  of `CAP Theorem` (the same note's own title). VISIBLE content corruption
  in a shipped note's first sentence — unshippable.
---

**Status:** shipped(2026-06-15, PR #172) — **SHIPPED 1.0.0rc9** (2026-06-15, PR #172, squash `b106723`; rc8-wave
umbrella #152 CLOSED) — + a post-rc9 follow-up (PR #179, `[Unreleased]`) that taught
the sweep to retroactively heal the fully-expanded self-acronym corruption
(`[[cache-aside pattern]] Theorem` → `CAP Theorem`). Self-title protection + now-ambiguous re-eval in
`pipeline/wikilinks.py` (FR1/FR2), deterministic `IX-wikilink-title-corruption`
verifier gate (FR3), `./vault wikilinks` sweep verb (FR4/FR5), `validate_vault`
map parity (C1-b). ~17 new tests; ruff clean.

# Feature Specification: Acronym-wikilink disambiguation

**Feature Branch**: `067-acronym-wikilink-disambiguation`
**Created**: 2026-06-14

## Clarifications

### Round 1 (resolved 2026-06-15)

Grounded in a live audit of the rc7 vault (`~/Documents/reference-vault-rc7/`):
`cap.md` is an alias stub `redirect_to: cache-aside pattern` (wrong — should be
`CAP Theorem`), and `CAP Theorem.md`'s first sentence reads *"The
[[cache-aside pattern]] Theorem…"*. Sweep found **55 acronym alias stubs**,
several clearly mis-assigned (`ai`→apache iceberg, `cap`→cache-aside pattern).

| Q | Decision | Notes |
| --- | --- | --- |
| **Q1 — disambiguation policy** | **(a)+(d)** — auto-link ONLY single-expansion acronyms; ambiguous acronyms (≥2 candidate target notes) stay **plain text** in the body; AND a note never links its own title's acronym to a sibling expansion (self-link or no-link wins). | Most conservative + least-surprising. Kills the CAP class (the note's own title acronym was rewritten to a sibling) and the general ambiguous-link corruption in one rule. Single-expansion acronyms still auto-link, preserving the useful behaviour. |
| **Q2 — verifier rule (FR3) severity** | **FAIL** — a note whose first body wikilink renames the note's own title is rejected with a clear "wikilink title corruption" message. | First-sentence title corruption is unshippable (the exact rc7 CAP case). A blocking gate is warranted; this is not advisory. |
| **Q3 — migration** | **Ship a deterministic one-off sweep verb** (e.g. `./vault wikilinks --fix`) that walks an existing vault, finds ambiguous-acronym body links + wrong alias redirects, and converts/repairs them (plain text for ambiguous body links; re-point fixable stubs). Zero-LLM, idempotent. | Existing vaults (incl. rc7) have live corruption now; the cycle loop alone is too slow/uncertain. A deterministic verb mirrors the 066 `re-grade` precedent. |
| **Q4 — auto-generated acronym stubs** | **Sweep re-points fixable stubs** to the correct expansion and **removes orphaned/unfixable** ones (no inbound links AND no unambiguous target). | Keeps the genuinely-useful single-expansion redirects; cleans the detritus + mis-assigned stubs the greedy generator produced. |
| **Q5 — scope** | **Standalone spec 067** (not an amendment to 062). | Although 062 owns acronym-stub generation + first-occurrence-link logic, 067 adds a new verifier rule AND a new sweep verb — enough net surface to warrant its own spec dir + plan, mirroring how 066 stayed standalone vs amending 055. The fix still *touches* 062-owned code. |

All five resolved (live-evidence-grounded, not defaulted). Locked shape:
single-expansion-only auto-linking + self-title protection (FR1/FR2), a
**FAIL** verifier rule for first-link title corruption (FR3), a `./vault
wikilinks --fix` deterministic sweep that repairs body links + re-points or
removes acronym stubs (FR4/FR5), shipped as a standalone spec. Ready for
`/speckit.plan`.

## Why this spec exists

Spec 062 introduced acronym alias stubs and first-occurrence wikilink
rewriting. The rc7 vault generated ~75 acronym stubs (`ai.md`, `abp.md`,
`cap.md`, …). When an acronym has multiple possible expansions, the
current logic auto-links the body occurrence to the **wrong** expansion —
documented case: `CAP Theorem.md`'s first sentence links `CAP` to
`[[cache-aside pattern]]` (also CAP). This is content corruption in a
shipped note's most-prominent sentence; the framework cannot promote to
v1.0.0 while it ships notes whose first wikilink is wrong.

## Suggested approach (for the clarify stage)

1. **Quantify the blast radius** — sweep all acronym wikilinks in the rc7
   vault where ≥2 expansions exist; manually verify a sample. Likely many
   more notes have wrong acronym links.
2. **Disambiguation policy** (clarify Q1):
   - (a) Auto-link only when the acronym has a single, unambiguous expansion.
   - (b) Leave the bare acronym (no link) when ambiguous; log a WARN.
   - (c) Detect "did the LLM mean this expansion?" via the note's
     `coverage_category` / `tags` / surrounding context.
   - (d) When a note is self-referenced under its own title's acronym,
     prefer the self-link over any other expansion.
3. **Quality-gate rule** — extend the verifier to reject notes whose first
   body wikilink rewrites the title (this CAP case is exactly that —
   `CAP Theorem`'s body said "The CAP Theorem" and got mangled to "The
   cache-aside pattern Theorem"). That alone catches the most embarrassing
   class of corruption.

## Functional requirements (sketch)

- **FR1** — Multi-expansion acronyms (≥2 candidate target notes for the
  same acronym) do NOT auto-link in the body; the bare acronym remains
  plain text. Single-expansion acronyms still auto-link.
- **FR2** — When the note BEING LINKED FROM has a title whose own acronym
  matches, prefer the self-link (or no-link) over a sibling-expansion link.
- **FR3** — Verifier rule: a note whose first body wikilink renames the
  note's own title is rejected with a clear "wikilink title corruption"
  message.
- **FR4** — **RESOLVED (analyze I1): a new `./vault wikilinks` verb** (not `./vault
  health`) reports ambiguous-acronym body links across the vault so the operator can
  manually triage. The dry-run (no `--fix`) is the report mode; `--fix` applies repairs
  (FR5). Mirrors the shipped `digest` verb wiring.
- **FR5** — Vault-sweep migration: a one-off script that walks an existing
  vault, finds ambiguous-acronym body links, and offers to convert them
  back to bare text + log the rewrite.

## Cross-references

- Issue #154 (this spec's tracking issue)
- Issue umbrella #152 (rc7 validation findings → rc8 wave)
- Spec 062 (Vault-Output Integrity — owns the acronym-stub generation +
  first-occurrence-link logic). Possibly an amendment to 062 rather than
  a standalone spec; clarify Q5 decides.

## Open questions (for /speckit.clarify)

- Q1: Which of the 4 disambiguation policies above? (Option (a) — only
  unambiguous acronyms auto-link — is the most conservative and least
  surprising.)
- Q2: Quality-gate severity for the verifier rule (FR3) — FAIL or WARN?
- Q3: Migration: do we ship a one-off vault-sweep utility (FR5) OR rely
  on the next cycle's rewrite loop to fix existing notes incrementally?
- Q4: Edge case — acronym stubs that the framework auto-generated and
  are now orphaned (no body in the vault links to them). Are these
  detritus to be deleted, or kept as redirect aliases?
- Q5: Scope — is this an **amendment to spec 062** (which owns the
  acronym handling) or a standalone spec? If amendment, this stub
  becomes the source of an "Amendment 1" header in 062's spec.md.

## Deferred to plan/tasks

Full plan + tasks + foreman test-design enrichment happens after clarify.
This stub exists so the rc8-wave umbrella has a concrete spec dir to point
at; full spec-kit work lives in a dedicated session.
