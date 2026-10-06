# Contract: `./vault re-grade` verb (FR4)

**Spec**: 066 — Credibility-model calibration
**Status**: authored 2026-06-15 (post-clarify, Phase-1). Authoritative for the
re-grade CLI surface, the reinstatement criterion, the commit policy, and the
quarantine→corpus move.
**Determinism**: zero LLM calls (Q4/FR4). Pure function of the quarantined
notes' frontmatter + the current credibility model (catalog + override).

---

## 1. Invocation (Q12 — manual only)

```bash
./vault re-grade [--dry-run] [--note <path>]... [--json]
# direct: research-framework re-grade --vault <vault> [...]
```

- Registered in `cli/_parser.py` like `acceptance` (`--vault` required).
- New `re-grade)` case in `templates/vault-script.sh.j2` mirroring `acceptance)`.
- **Never auto-invoked** — not on `./vault update`, framework upgrade, or any
  cycle/lifecycle event.

| flag | default | behaviour |
| --- | --- | --- |
| `--vault PATH` | — (required) | vault root. |
| `--dry-run` | off | compute + print outcomes; **touch nothing, no commit**. |
| `--note PATH` | all | re-grade only the named quarantined note(s); repeatable. |
| `--json` | off | machine-readable summary (else a human table). |

Exit code: `0` on success (including the no-op/0-reinstated case); `2` on a
usage error (missing/invalid `--vault`). It is **not** a gate — it never returns
nonzero because notes remain quarantined.

## 2. Scope (Q8 — quarantine only)

Operates **only** on `<vault>/_pipeline/quarantine/*.md`. Notes already in
`data_vault/` are never touched (no demotion risk on a catalog tweak). A vault
with an empty/absent quarantine dir ⇒ no-op, exit 0, no commit.

## 3. Reinstatement criterion (research D5 — deterministic)

For each quarantined note, read its frontmatter (`verifier_status`,
`verifier_notes`). The note is **reinstated iff both** hold:

1. **Credibility-only rejection** — every `verifier_note` maps to an
   `IX-credibility-*` rule. A note carrying any non-credibility note
   (`skipped_non_credibility`) is left untouched (re-grade cannot re-judge
   agent-semantic rejections without an LLM).
2. **Now clean** — re-running `deterministic_credibility_violations` (backed by
   the post-066 catalog + override + policy) returns **zero** `IX-credibility-*`
   violations (i.e. under `unknown_domain_policy: warn`, an `ungraded` WARN does
   not block reinstatement; under `reject`, an unresolved host keeps it
   quarantined → `still_quarantined`).

There is **no `.failure.json`** — the verdict source is the note's own
frontmatter (research D5 corrects the spec's wording).

## 4. Effect of a reinstatement

Atomic per note (via `pipeline/atomic_write`), in this order so the move +
restamp land together in one commit:
1. Restamp frontmatter: `verifier_status: verified`; drop the credibility
   `verifier_notes`.
2. Move `_pipeline/quarantine/<stem>.md` →
   `data_vault/<NN - Category>/<stem>.md`, where the folder is resolved by
   `resolve_category_folder(vault, frontmatter)` from the note's
   `coverage_category` (research D7 — quarantine flattened the original path).
3. Best-effort remove the note's stale `research-backlog.md` "rewrite
   quarantined note: <stem>" pointer (the spec-062 sweep added it).

Notes that stay quarantined (`still_quarantined`) get their `verifier_notes`
refreshed to the current verdict; `skipped_non_credibility` notes are not
modified.

## 5. Commit policy (Q9)

- After processing, if `N >= 1` reinstated: **one** commit on the current branch:
  `regrade(<YYYY-MM-DD>): N notes reinstated` (body lists each note + its
  catalog basis). Uses the existing `pipeline.vault_commit` surface (the shim's
  `_vault_autocommit` already wraps it for non-cycle verbs; spec-050 invariant).
- If `N == 0`: **no commit** (no empty commits).
- `--dry-run`: never commits, never writes.
- The move (delete from `data_vault`-bound + add) is committed atomically — at
  no point is a reinstatement left uncommitted in the working tree (the rc7
  GA-003 / spec-062 atomicity invariant).

## 6. Idempotency & safety

- Running twice in a row: the second run finds a clean quarantine (or only
  un-reinstatable notes) ⇒ no-op, no commit.
- Zero LLM dispatch (the tier-2 dispatch guard stays green; re-grade must not
  appear in any allowlist because it never dispatches).
- Fail-closed: an unreadable note is reported `still_quarantined` (never
  crashes the run); a `vault_commit` failure WARNs but the on-disk moves persist
  (next run re-commits, idempotent).

## 7. Output

Human (default):
```
Re-grade — <vault name>
  reinstated: 9   still-quarantined: 2   skipped (non-credibility): 1
  Fastify.md     → data_vault/06 - Frameworks/Fastify.md   (tier_2 via fastify.dev)
  Boto3.md       → data_vault/13 - Infrastructure/Boto3.md (tier_1 via docs.aws.amazon.com)
  Backtracking Algorithm.md  ⊘ still-quarantined (cp-algorithms.com ungraded; reject policy)
Committed regrade(2026-06-15): 9 notes reinstated  (abc1234)
```

JSON (`--json`): `{ "vault", "reinstated": [RegradeOutcome...],
"still_quarantined": [...], "skipped": [...], "commit": "<sha>|null" }` —
`RegradeOutcome` per data-model Entity 4.

## 8. Out of scope (this contract)
- Re-grading currently-accepted `data_vault/` notes (Q8 — separable future
  "full corpus re-grade").
- Auto-invocation on any lifecycle event (Q12).
- Any LLM call / agent-semantic re-judgement (FR4).
