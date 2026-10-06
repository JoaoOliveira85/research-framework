# Implementation Plan (v2.1 amendment): ledger ↔ citation reconciliation

**Parent spec**: [spec.md](./spec.md) (v1.0 SHIPPED 0.5.0; v2 = source-ledger; this
plans the **v2.1 amendment** only) | **Branch**: rc3 wave | **Date**: 2026-06-05 |
**Target**: 1.0.0rc3

> Scope: the "v2.1 amendment" FRs added to spec 048 (codebase-vault rc1 defect 3.4 —
> the ledger asserted ACCESS_FAIL/PIPELINE_DROP on sources the notes cited at
> 100%/71%/63%). The shipped v1.0 (logger + bridge.log) and the v2 source-ledger MVP
> (`scripts/source_ledger.py`) are otherwise untouched.

## Summary

The v2 ledger (`scripts/source_ledger.py`) fuses scout + `sources.db` + research
capture-failures + quality gates into per-source verdicts — but Phase-0 confirmed it
**never joins the notes' actually-cited `source_urls`**. It infers "referenced" from
`sources.db` `notes_referencing`, which missed the rc1 case where a source was
genuinely cited yet verdicted ACCESS_FAIL/PIPELINE_DROP. The amendment adds the
citation-corpus join at ledger-build time and a new terminal verdict
**`LEDGER_DISAGREEMENT`**: a source whose failure verdict contradicts a non-zero note
citation rate is relabelled rather than reported as a (false) source failure.

| FR | What | Primary code target (verified path) |
| --- | --- | --- |
| B1 | Build the note-citation corpus (frontmatter `source_urls` → host map) | `scripts/source_ledger.py` (new `_note_citation_hosts(vault)`, sibling to `_source_urls`) |
| B2 | Cross-check verdicts; relabel contradictions `LEDGER_DISAGREEMENT` | `scripts/source_ledger.py` `resolve_verdict`/a post-`collapse_verdict` pass + `Verdict` enum + precedence |
| B3 | Attribute direct vs MCP reads (FR-018 blind spot) | `scripts/source_ledger.py` evidence map (mark MCP-host citations) |

**Clarify decisions baked in** (amendment Clarifications): flag the mismatch as
`LEDGER_DISAGREEMENT` (reported verdict; original kept in `disagreement_was`); join the
citation corpus at ledger-build time (not a separate pass); a source cited by a note can
never end as a `0-contribution ACCESS_FAIL`.

**Requirement map**: B1 → FR-023 (citation path covered); B2 → FR-022 (reconcile
verdicts); B3 → FR-024 (direct/MCP attribution).

## Phase-0 findings (spec→code reconciliation)

- **F1** — the citation join is the gap. `source_ledger.py:241 _source_urls()` maps
  **spec** sources → hosts; `_capture_failure_signals` (:256) reads
  `cycle-NNN-research.json` capture-failures; `_quality_signals` (:276) reads quality
  gates; `_fuse_signals` (:302) pulls `notes_generated`/`notes_referencing` from
  `sources.db`. None reads the **notes'** `source_urls` frontmatter — so a cited-but-
  failed source is invisible to the verdict machine.
- **F2** — the citation data is on the notes. Each `data_vault/**` note carries
  `source_urls` frontmatter (Principle IX Tier-2). B1 scans these once, maps each URL
  to a host (reusing the `urlparse().netloc` logic already in `_source_urls`), and
  builds `host → citation_count`.
- **F3** — the verdict machine is pure + testable. `resolve_verdict` (FR-020 state
  machine) + `collapse_verdict` (per-cycle → precedence) are pure functions with
  existing tests (`tests/scripts/test_source_ledger.py`). B2 adds `LEDGER_DISAGREEMENT`
  to the `Verdict` enum + `VERDICT_PRECEDENCE` and a reconciliation step: after
  `collapse_verdict`, if `verdict ∈ {ACCESS_FAIL, PIPELINE_DROP}` and the source's
  host has `citation_count > 0`, relabel `LEDGER_DISAGREEMENT`.
- **F4** — pairs with spec 063 US2. The amendment makes the *ledger itself* reconcile
  (framework side); 063 US2 reports the disagreement as the finding (harness side) and
  also cross-checks defensively, so the two are independently correct.

## Constitution Check (v1.4.0)

- **IV. Agent-Script Separation** ✅ — pure deterministic verdict logic; no LLM.
- **V. Offline-First / no deps** ✅ — stdlib only (`sqlite3`, `urllib.parse`, yaml).
- **I/II/III** ✅ — no gate semantics change (the ledger is observability, not a gate);
  tests-first; no phase reordering.
- **Ask-First**: adding a `Verdict` enum member is additive; the contract
  (`contracts/source-ledger-v2.contract.md`) gains `LEDGER_DISAGREEMENT` — flagged,
  authorised by the amendment Clarifications.

**Gate: PASS.**

## Files touched

```text
scripts/source_ledger.py                                   # B1 _note_citation_hosts; B2 Verdict.LEDGER_DISAGREEMENT + reconcile; B3 MCP attribution
specs/048-observability-v1/contracts/source-ledger-v2.contract.md  # add LEDGER_DISAGREEMENT verdict + reconciliation rule
tests/scripts/test_source_ledger_reconciliation.py         # cited-but-failed → LEDGER_DISAGREEMENT; not-cited-failed stays; MCP attribution
```

## Sequencing

1. B1 — `_note_citation_hosts(vault)` (scan note `source_urls` → host counts) + unit
   test on a fixture vault.
2. B2 — add `LEDGER_DISAGREEMENT` to `Verdict` + precedence; reconciliation pass after
   `collapse_verdict`; update the v2 contract; tests for both directions (cited-failed
   relabels; genuinely-unreached stays ACCESS_FAIL/NOT_REACHED).
3. B3 — tag MCP-host citations in the evidence map (FR-018 blind spot) so a managed
   source reading as PIPELINE_DROP-but-cited is attributable.
