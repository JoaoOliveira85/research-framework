# Tasks (rc3 amendment, v2.1): ledger ↔ citation reconciliation

**Input**: `specs/048-observability-v1/plan-rc3-amendment.md` + the spec's "v2.1 amendment" section.
**Scope**: the v2.1 amendment to the (v2) Source-Consideration Ledger only; v1 logger/bridge.log untouched.

**Tests**: INCLUDED (Principle III). (Foreman test-design subagent enriches before
`/speckit.implement`, ADR-0010.)

**Organization**: grouped by amendment requirement (B1–B3). Order per plan: B1 → B2 → B3.

**Requirement map (→ spec FR ids)**: **B1** (note-citation corpus) is the mechanism for
**FR-023** (citation path covered); **B2** (`LEDGER_DISAGREEMENT` reconciliation) =
**FR-022** (reconcile verdicts); **B3** (`read_via` attribution) = **FR-024** (direct/MCP).

## Format: `[ID] [P?] [Bx] Description`

---

## Phase 1: Setup

- [x] T001 Confirm green baseline: `pytest tests/observability/ tests/scripts/ -k ledger -q` + `ruff check .` pass.

---

## Phase 2: B1 — Note-citation corpus join

**Goal**: at ledger-build time, build the corpus of cited source URLs/hosts from every note's `source_urls` frontmatter (data the ledger does NOT currently read).
**Independent Test**: given a vault with known `source_urls`, the corpus contains exactly those hosts.

- [x] T002 [P] [B1] Write `tests/scripts/test_source_ledger_reconciliation.py` (RED, corpus half): `_note_citation_hosts(vault)` returns the host set from all notes' `source_urls` frontmatter.
- [x] T003 [B1] Add `_note_citation_hosts(vault)` to `scripts/source_ledger.py` (reuse the canonical `vault/frontmatter.py` parser); make the corpus half of T002 GREEN.

**Checkpoint**: the ledger can see what notes actually cite.

---

## Phase 3: B2 — `LEDGER_DISAGREEMENT` reconciliation verdict

**Goal**: a source whose host appears in the citation corpus can NEVER stay `ACCESS_FAIL`/`NOT_REACHED`/0-contribution; the contradiction is relabelled `LEDGER_DISAGREEMENT` (a true positive about the *ledger's* blind spot).
**Independent Test**: a source cited by ≥1 note but verdicted `ACCESS_FAIL` is re-emitted as `LEDGER_DISAGREEMENT`; a genuinely-unread source keeps its verdict.

- [x] T004 [B2] Add `LEDGER_DISAGREEMENT` to the `Verdict` enum + the verdict precedence/state machine in `scripts/source_ledger.py`. ⚠️ This is a **contract change to `contracts/source-ledger-v2.contract.md`** that **spec 053's trunk-inversion gate consumes** (`tasks-v2.md` T033 warns: do not change the verdict enum without coordinating 053). Confirm in T006.
- [x] T005 [B2] Add a `reconcile_against_citations(rows, corpus)` post-pass: any row with a non-USED verdict whose host ∈ corpus ⇒ reported verdict becomes `LEDGER_DISAGREEMENT` while the **original join verdict is preserved in a `disagreement_was` field** (spec Q1 — "keep the join verdict, flag the mismatch"; satisfies the FR-023 invariant that a cited source can never read as `0-contribution ACCESS_FAIL`). Make T002's reconciliation half GREEN.
- [x] T006 [P] [B2] Update `specs/048-observability-v1/contracts/source-ledger-v2.contract.md` to document `LEDGER_DISAGREEMENT` (terminal verdict) + `disagreement_was`; add a quickstart repro of the rc1 "cited-but-ACCESS_FAIL" case. **Coordinate spec 053**: confirm the trunk-inversion gate treats a derived-trunk source that resolves to `LEDGER_DISAGREEMENT` as citation-evidenced (acceptable, like `USED`), NOT as a silent trunk drop — adjust 053's reader or document the tolerance.

**Checkpoint**: the rc1 false-`ACCESS_FAIL` (Phind/Perplexity cited yet 0-contribution) now self-flags. This is the trust fix spec 063 GA + §4.2 reconciliation gate depend on.

---

## Phase 4: B3 — Direct vs MCP read attribution

**Goal**: best-effort attribution of each USED verdict to `direct` (raw_capture/sources.db) vs `mcp` (Jira/Confluence/GitHub), closing the MCP blind spot.
**Independent Test**: a source read only via an MCP server is attributed `read_via: mcp`, not dropped to `NOT_REACHED`.

- [x] T007 [P] [B3] Extend `tests/scripts/test_source_ledger_reconciliation.py`: an MCP-only source ⇒ `read_via: "mcp"`; a raw_capture source ⇒ `read_via: "direct"`; unknown ⇒ `read_via: "unknown"` (never silently dropped).
- [x] T008 [B3] In `scripts/source_ledger.py`: add a `read_via` field populated by joining the existing MCP/dispatch signals (best-effort; `"unknown"` when unattributable). Make T007 GREEN.

---

## Phase 5: Polish

- [x] T009 [P] `ruff check .` + `ruff format --check .`; run `pytest tests/scripts/test_source_ledger_reconciliation.py`.
- [x] T010 [P] CHANGELOG `[1.0.0rc3]`: ledger↔citation reconciliation (`LEDGER_DISAGREEMENT`, `read_via` attribution) under observability.

---

## Dependencies & Execution Order

- B1 (T002–T003, corpus) is the prerequisite for B2 (T004–T006, reconciliation).
- B3 (T007–T008, attribution) is independent of B2 and can run in parallel after B1.
- This amendment makes `source_ledger.py` trustworthy enough for spec 063 §4.2 (the
  ledger↔citation reconciliation gate **consumes** `LEDGER_DISAGREEMENT`); land before 063.
