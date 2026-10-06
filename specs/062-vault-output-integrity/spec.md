---
spec_number: 062
title: Vault output integrity on constrained exit — rejected-note quarantine, dedupe, acronym links
status: SHIPPED 1.0.0rc3 (PR #126, squash 2d217be)
target_version: 1.0.0rc3
created: 2026-06-05
source_input: |
  2026-06-05 codebase-vault rc1 acceptance evaluation, §3.2 (HIGH), §3.3 (MEDIUM),
  §3.6 (MEDIUM). Three correctness defects that shipped indexed, queryable, or
  dangling content from a single constrained-exit run: 14 verifier-rejected notes
  indexed unflagged; 12 untracked `… 2.md` duplicate notes + duplicate per-cycle
  commits; ~13 dead `[[OECDH]]` acronym wikilinks.
---

**Status:** shipped(2026-06-06, PR #126) — SHIPPED **1.0.0rc3** (2026-06-06, PR #126, squash `2d217be`) — rc3 wave
(sibling specs 061, 063; amendments to 028 + 048 v2). Rejected-note quarantine (FR1),
dedupe + single idempotent per-cycle commit + no-untracked guard (FR2), acronym
alias + wikilink normalisation (FR3). No ADR (correctness fixes within existing
principles VI / IX / X).

> **Note on code homes:** this spec names *symptoms* + their *likely* homes from a
> read-only audit. Per the spec-051 precedent, `/speckit.plan` Phase-0 research
> reconciles each FR to its exact code path (the orchestrator constrained-exit path,
> the note-write / re-emit collision logic, and the acronym-alias generation step);
> where this spec's path guess is wrong, the plan's decision wins.

# Feature Specification: Vault output integrity on constrained exit

**Feature Branch**: `062-vault-output-integrity`
**Created**: 2026-06-05

## Clarifications (resolved 2026-06-05)

| Q | Decision | Notes |
| --- | --- | --- |
| **Q1 — rejected-note policy** | **Quarantine** — verifier-rejected notes are moved out of the indexed/citable corpus (e.g. `_pipeline/quarantine/`) with a research-backlog pointer; not citable, not counted toward coverage. | Cleaner coverage math + a clear "fix next cycle" signal. The run report still headlines the unresolved count (FR1). |
| **Q2 — path-collision resolution** *(in-spec default taken)* | **Overwrite the canonical path; content-hash no-op if byte-identical.** Never create an OS-style ` N.md` sibling under any circumstance. | A re-emit (e.g. metadata correction) replaces; identical re-writes are no-ops; the ` N.md` fork is always wrong. |
| **Q3 — acronym strategy** *(in-spec default taken)* | **Both** — generate an alias/redirect note for *every declared* acronym (deterministic) AND normalise references to the canonical full title at cycle-time (cf. ADR-0005). | Most robust: `[[OECDH]]` resolves whether authored as the acronym or the full title; driven by the declared acronym set, not LLM whim. |

All three resolved; no remaining open questions. Shipped 1.0.0rc3 (PR #126).

## Why this spec exists

The codebase-vault rc1 run was a *truncated bootstrap* (constrained exit at cycle 6
— see spec 061 for the root cause). Three defects that the run surfaced are not about
research quality; they are about the framework shipping content that is **indexed but
unverified, duplicated, or dangling**. Each violates a constitutional invariant and
each is independently cheap to fix:

| FR | Defect | Audit § | Severity | Principle at stake |
| --- | --- | --- | --- | --- |
| FR1 | 14/104 notes carry `verifier_status: rejected` yet are indexed + queryable | 3.2 | HIGH | IX (Vault-First Citation / verifier gate) |
| FR2 | 12 untracked `… 2.md` duplicate notes + two `research: cycle 6` commits | 3.3 | MEDIUM | VI (no duplicate notes) + X (append-only git) |
| FR3 | ~13 dead `[[OECDH]]` wikilinks (acronym alias never generated) | 3.6 | MEDIUM | VI (graph integrity) |

These bite *any* vault on a constrained or resumed run, not just codebase-vault,
which is why they belong in rc3 before the remaining validation runs.

## Out of scope (explicitly)

- **Why the run was truncated** (the `max_cycles` config mess) — owned by spec 061.
- **A harness gate that asserts "no rejected notes remain / no dup files / no dead
  links on a clean exit"** — owned by sibling spec 063 (§4.1 generic gates). This
  spec makes the framework *not produce* the defects; 063 makes the harness *catch*
  them if it ever does.
- **The verifier's judgement itself** (what counts as a rejection) — unchanged; this
  spec only changes what happens to an *already-rejected* note at exit.

## Functional requirements

### FR1 — Verifier-rejected notes are quarantined or flagged, never silently indexed

**Today.** The verifier (Principle IX gate) flags notes with
`verifier_status: rejected` + `verifier_notes` (e.g. a product note:
"presents a planned feature as shipped though linked decisions say not implemented;
missing `intent_implementation_drift`"). On a **clean** exit the rewrite loop clears
them. On a **constrained** exit the run ends before the loop completes — so 14
rejected notes were written to `data_vault/`, indexed, and made queryable with no
visible marker that they failed the gate.

**Proposed (Q1 resolved — quarantine).** A rejected note must never be silently
shippable as if it passed. On *any* exit (clean OR constrained), each note still
carrying `verifier_status: rejected` is **quarantined** — moved out of the
indexed/citable corpus (e.g. to `_pipeline/quarantine/`) so it is not returned by
`/ask`, not cited, and not counted toward coverage — with a **research-backlog
pointer** so the next cycle can rewrite it. The **run report headlines the count**
("N notes ended the run verifier-rejected and were quarantined") so a constrained
exit cannot hide them.

**Acceptance**:
- `tests/pipeline/test_rejected_note_handling.py`: a constrained exit with K
  rejected notes leaves 0 *citable/indexed* rejected notes; the run report records
  `rejected_unresolved: K`.
- An `/ask` / `/write` path cannot cite a rejected note (extends the Principle-IX
  verifier coverage).
- Clean-exit behaviour is unchanged (rewrite loop still clears them first).

### FR2 — No duplicate note files; no duplicate per-cycle commits

**Today.** The run left 12 untracked `… 2.md` files (e.g. `… Risk 2.md`) and two
`research: cycle 6 — cycle 6` git commits — consistent with a messy resume / re-emit
(the cycle-6 "re-emit to correct SG-006 metadata"). This both violates Principle VI
(no duplicate notes) and — worse — leaves content **untracked** in a vault whose
entire premise (spec 050 / Principle X) is auto-commit integrity.

**Proposed.** Three guarantees:
1. **Re-emit replaces, never forks.** When a cycle re-writes an existing note (e.g.
   to correct metadata), it overwrites the canonical file. The framework MUST NOT
   create an OS-style ` N.md` sibling. If a write would collide, it resolves to the
   canonical path (clarify Q2 for whether collisions are an error, a content-hash
   no-op, or a deterministic merge).
2. **No untracked content under `data_vault/` at cycle commit.** The spec-050
   auto-commit MUST stage all cycle-produced notes; a post-commit assertion fails
   the cycle (constrained, not silent) if anything under `data_vault/` is left
   untracked.
3. **One commit per cycle.** A re-emit within a cycle does not produce a second
   `research: cycle N` commit; the per-cycle commit is idempotent.

**Acceptance**:
- `tests/pipeline/test_no_duplicate_notes.py`: a re-emit of an existing note path
  overwrites it; no ` 2.md` sibling is created; a same-cycle re-run produces exactly
  one `research: cycle N` commit.
- `tests/pipeline/test_vault_commit_no_untracked.py` (extends spec-050 coverage): a
  cycle that writes notes leaves zero untracked files under `data_vault/`.
- `validate_vault.py` gains (or its existing duplicate check is extended to) a
  ` N.md` sibling + content-hash duplicate detector (shared with spec 063 §4.1).

### FR3 — Acronym/alias links resolve for every declared service acronym

**Today.** Alias notes were generated for `CMS` / `SPCS` but not `OECDH` — the
service note is titled "Order Engine Customer Data Handler …", so every
`[[OECDH]]` reference dangles (~13 notes). `validate_vault.py` returns exit 1 partly
on this class.

**Proposed.** Acronym handling must be complete and consistent: for every acronym
declared in the spec (service names, declared abbreviations), the framework MUST
either (clarify Q3 picks one, or both):
- **generate an alias/redirect note** for the acronym pointing at the full-title
  note, for *all* declared acronyms (not a subset); and/or
- **normalise references** to the canonical full title at cycle-time wikilink
  normalisation (cf. ADR-0005), so `[[OECDH]]` resolves to the full-title note.

The success condition is concrete: `validate_vault.py` returns 0 on the acronym/
dead-link class for a vault whose spec declares acronyms.

**Acceptance**:
- `tests/pipeline/test_acronym_alias_coverage.py`: a spec declaring N service
  acronyms yields N resolvable acronym references (no dangling `[[ACRONYM]]`).
- The fix is driven by the *declared* acronym set (deterministic), not by whichever
  aliases an LLM happened to emit.
- `validate_vault.py` exit code on a fixture with declared acronyms is 0 for the
  dead-acronym-link class.

## Success criteria

- **SC-001**: On any exit, the indexed/citable corpus contains zero
  `verifier_status: rejected` notes; the run report states the unresolved count.
- **SC-002**: A resumed/re-emitting run produces zero ` N.md` duplicate files, zero
  untracked `data_vault/` content, and exactly one commit per cycle.
- **SC-003**: A vault whose spec declares acronyms has zero dangling acronym
  wikilinks; `validate_vault.py` returns 0 for that class.

## Open questions — RESOLVED 2026-06-05

All three resolved in the **Clarifications** block at the top of this spec; original
text retained below for provenance.

- **Q1 — Rejected-note policy: quarantine vs hard-flag-in-place?** Quarantine
  (move out of corpus) is cleaner for coverage math; flag-in-place keeps the note
  visible for the next cycle's rewrite. Pick one (or quarantine + a backlog pointer).
- **Q2 — Note-path collision resolution.** When a re-emit/write targets an existing
  path: overwrite unconditionally, content-hash no-op if identical, or error? (The
  ` N.md` sibling is wrong in all cases — this is only about the canonical-path
  behaviour.)
- **Q3 — Acronym strategy: alias notes, reference normalisation, or both?** Alias
  notes preserve `[[OECDH]]` as a real (redirect) node; normalisation rewrites
  references to the full title. Both is most robust; pick the rc3 scope.

## Provenance

- **Primary source**: 2026-06-05 codebase-vault rc1 acceptance evaluation §3.2 / 3.3
  / 3.6, plus the structural Phase-0 (`validate_vault.py <vault>` → exit 1, 18
  violations).
- **Constitution**: no amendment (these are correctness fixes *upholding* existing
  Principles VI / IX / X; cf. ADR-0005 for cycle-time wikilink normalisation).
- **Cross-references**: spec 050 (auto-commit / Principle X — FR2 extends its
  coverage), sibling spec 063 §4.1 (the harness gates that catch regressions of all
  three FRs), spec 061 (the constrained exit that exposed them).

Shipped 1.0.0rc3 (2026-06-06, PR #126).
