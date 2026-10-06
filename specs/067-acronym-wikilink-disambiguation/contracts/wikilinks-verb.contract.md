# Contract — `./vault wikilinks` sweep verb (067 FR4/FR5)

A deterministic, zero-LLM, idempotent repair pass. Mirrors the shipped `digest`
verb wiring (`cli/digest.py` + `cli/_parser.py` + `templates/vault-script.sh.j2`).

## Surface

```
./vault wikilinks [--fix] [--json]
research-framework wikilinks --vault <dir> [--fix] [--json]
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `--vault <dir>` | (shim injects `$VAULT_DIR`) | vault root |
| `--fix` | off (**dry-run**) | apply repairs; without it, only report |
| `--json` | off | emit `SweepActionRecord[]` as JSON instead of human text |

Exit code: `0` always on a well-formed vault (it reports/repairs; it does not gate).
A vault that cannot be read → non-zero with a clear message.

## Behaviour (per data-model Entity 4)

For the whole `data_vault/` tree:

1. Build the acronym map (`ambiguous` set authoritative).
2. **Body links** — any `[[TOKEN]]` whose acronym is ambiguous, or that renames the
   containing note's own title (C2/C3), → convert to plain text. `action=plaintext_body_link`.
3. **Alias stubs** (`note_type: alias`):
   - exactly one valid expansion → re-point `redirect_to`. `action=repoint_stub`.
   - no inbound `[[...]]` reference AND (ambiguous OR no valid expansion) → delete.
     `action=delete_stub`.
   - else `action=noop`.
4. Print/emit the action list. Under `--fix`, apply via atomic writes / file
   deletes; without `--fix`, report only (no writes).

## Invariants

- **Idempotent** — a second `--fix` run on the same vault yields all `noop`.
- **Zero-LLM** — never dispatches an agent (dispatch allowlist stays empty).
- **No data loss beyond detritus** — only `note_type: alias` stubs are deleted, and
  only orphan/unfixable ones; substantive notes are only edited (body link →
  plain text), never deleted.
- **Commit policy** — *Ask-First (plan §Ask-First #1)*: default leaves changes
  uncommitted for the operator (mirrors `health`); `/tasks` may opt into an
  auto-commit `wikilinks(<date>): N links repaired` (066 `re-grade` precedent).

## Test obligations

| ID | Assertion |
| --- | --- |
| V-a | Dry-run reports actions and writes nothing. |
| V-b | `--fix` on the rc7 fixture: `cap.md` re-pointed/deleted, `CAP Theorem.md` body de-linked. |
| V-c | Second `--fix` run → zero actions (idempotent). |
| V-d | `--json` emits well-formed `SweepActionRecord[]`. |
| V-e | Shim `wikilinks)` case routes to `research_framework.cli wikilinks`. |
