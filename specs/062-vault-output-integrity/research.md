# Phase 0 Research: Vault output integrity on constrained exit

**Spec**: [spec.md](./spec.md) | **Date**: 2026-06-05

Reconciles the three symptom-described FRs against the real tree (verified
2026-06-05). The spec explicitly authorises Phase-0 to override its path/source
guesses; D4 exercises that for FR3.

## D1 — FR1: the quarantine seam already exists; indexing scans only `data_vault/`

**Question.** Where do "indexed/citable" notes live, and is there a quarantine
mechanism to reuse?

**Finding.**
- `pipeline/orchestrator.py` already has `_quarantine_orphan_note` (:99 → moves a
  note into `<vault>/_pipeline/quarantine/`) and `_quarantine_out_of_scope_notes`
  (:192, called at :459) — a working "move a note out of the corpus" pattern.
- The indexable/citable surface is `data_vault/*.md`: the indexer + readers skip
  `_index.md`/`_concepts.md`/`_graph.md` and scan `data_vault/` only
  (`steps/research.py:171`, `_helpers/_io.py:43,60`). `_pipeline/quarantine/` is
  outside `data_vault/`, so a quarantined note is automatically uncited + unindexed.
- Rejection data is already collected per cycle: `steps/research.py:353`
  `rejected: list[VerifierRejection]` → `:366 notes_rejected=rejected`. The status
  itself is stamped into frontmatter by `verifier.py` (`verifier_status: rejected`,
  `:117/:134`).

**Decision.** FR1 = a new `_quarantine_rejected_notes(vault_dir)` that scans
`data_vault/` for `verifier_status: rejected`, moves each into
`_pipeline/quarantine/`, and appends a `_pipeline/research-backlog.md` pointer.
Call it from `_finalise` (`orchestrator.py:556`) so it runs on **any** exit
(clean OR constrained). Clean-exit behaviour is preserved because the
correction/rewrite loop clears rejections first; the sweep then finds 0. The count
goes to `run_report.rejected_unresolved` and is headlined. **No indexer change.**

## D2 — FR2: staging is already `git add -A`; the dup is a double-commit / post-commit write

**Question.** How did 12 untracked `… 2.md` files survive in an auto-commit vault,
and what produced two `research: cycle 6` commits?

**Finding.** `vault_commit.py`:
- `commit_cycle` (:553) → `_stage_and_commit` (:731) runs `git add -A` "regardless
  to catch" all writes (:739-741), then `git commit` (with `--allow-empty`, :758).
- Because staging is comprehensive, an *untracked* file at audit time means it was
  written **after** that cycle's commit, or the path is `.gitignore`-matched. Two
  `research: cycle 6` commits means `commit_cycle` was invoked **twice** for cycle 6
  — consistent with the cycle-6 "re-emit to correct SG-006 metadata" path triggering
  a second commit.

**Decision.** FR2 = three guarantees, all in `vault_commit.py` + `validate_vault.py`:
1. **Idempotent per-cycle commit** — `commit_cycle` folds a same-cycle re-emit into
   the cycle's single commit (skip/amend the second `research: cycle N`), so a cycle
   produces exactly one research commit.
2. **Post-commit untracked assertion** — after the cycle commit, `git status
   --porcelain` over `data_vault/` must be empty; non-empty ⇒ constrained exit
   (fail-loud, upholds Principle X). This catches any post-commit fork regardless of
   origin.
3. **Dup detector in `validate_vault.py`** — flag OS-style ` N.md` siblings and
   byte-identical content duplicates (shared with spec 063 §4.1). The framework's own
   writes use `atomic_write` (overwrite), so the ` N.md` fork is never produced by
   core after this; the detector is the safety net.

## D3 — FR3: `wikilinks.py` handles case only; acronyms are unhandled

**Question.** Does the cycle-time wikilink normaliser resolve acronyms?

**Finding.** No. `pipeline/wikilinks.py::auto_fix_moved_wikilinks` rewrites only
**case-mismatched** links (`[[Cassandra]]` → `cassandra.md`) by lowercasing against
the existing stem set. It explicitly does not create notes and does not map
`[[OECDH]]` → `order-engine-customer-data-handler.md`. `vault/indexer.py` has no
alias/acronym handling either.

**Decision.** FR3 extends the same cycle-time hook (ADR-0005 lineage): build an
**acronym → canonical-stem map**, then (a) rewrite unresolved all-caps `[[TOKEN]]`
links whose TOKEN matches exactly one note's acronym, and (b) generate a redirect
stub note per acronym (`OECDH.md` → points at the canonical note) so both the link
and a direct `[[OECDH]]` node resolve (clarify Q3 = "both").

## D4 — FR3: there is NO declared-acronym field; use title-derived extraction

**Question.** The spec says "for every acronym declared **in the spec**." Where in
the schema are acronyms declared?

**Finding.** Nowhere. `spec/schema.py` has no `acronyms`/`aliases`/`abbreviations`
field (grep 2026-06-05), and notes carry no `aliases` frontmatter (the only `aliases`
hits are in the verifier prompt + an unrelated observability comment). The spec's
"declared in the spec" assumed a field that does not exist.

**Decision (overrides the spec wording, per its Phase-0 escape hatch).** The
authoritative, deterministic acronym source is **title-derived extraction**: for each
note, compute its acronym from the canonical title (initials of significant words,
e.g. "Order Engine Customer Data Handler" → `OECDH`), unioned with any explicit
`aliases:` a note declares (additive, honoured if present). The map is built
deterministically in framework code — no LLM in the acronym→note step, satisfying the
spec's "not by whichever aliases an LLM happened to emit." Conflicts (two notes with
the same computed acronym) resolve to "no auto-rewrite" + a `validate_vault.py`
WARNING (ambiguous), never a wrong link.

**Rejected alternatives:**
- *Add a spec-level `acronyms:` glossary* — expands the spec schema surface for an
  rc3 correctness fix; deferrable to a later additive spec if a curated glossary is
  ever wanted.
- *Require note-writer to populate `aliases:`* — reintroduces the "LLM whim"
  dependency the spec rejects; kept only as an additive override, not the source.

## No-change confirmations

- **Verifier judgement** (what counts as rejection) — unchanged; FR1 only acts on
  notes already stamped `verifier_status: rejected`.
- **Cycle-time wikilink case-fix** — unchanged; FR3 is additive to the same pass.
- **spec-050 auto-commit lifecycle** (branch-per-run, squash on clean exit,
  retention on constrained) — unchanged; FR2 only tightens within-cycle commit
  idempotency + adds the untracked assertion.
