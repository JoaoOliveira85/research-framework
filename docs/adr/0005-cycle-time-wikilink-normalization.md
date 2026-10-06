# ADR-0005: Wikilink case is normalized at cycle time, not graph-repair time

**Status**: Accepted
**Date**: 2026-05-18
**Tags**: vault-graph, note-writer, 0.2.31, cycle-runner

## Context

The note-writer agent emits natural-language wikilinks
(`[[Cassandra]]`, `[[OMS]]`, `[[Kafka]]`) when referencing related
concepts. The framework's filename convention is lowercase-snake
(`cassandra.md`, `oms.md`, `kafka.md`). Obsidian and the framework's
wikilink resolver treat `[[Cassandra]]` and `cassandra.md` as
distinct references \u2014 the vault graph fragments along case
variants.

The user's reference-vault-0.2.30 audit found **207 case-broken
wikilinks** after 6 cycles. The fragmentation accumulated silently:
each cycle's notes added a few more broken links, and none of the
existing pipeline stages flagged it as a problem worth halting on.

We already had `scripts/vault_health.py::apply_wikilink_fixes()`
that handles the `moved` classification (case mismatch where a
lowercase target exists). It's a graph-repair tool that ALSO creates
stub notes (for unknown targets) and prunes orphan `related`
entries. Two heavier mutations that need human judgement \u2014 they
shouldn't run silently every cycle.

Two competing ideas existed:

1. **Prevent the drift at the source.** Modify the note-writer
   prompt to instruct the agent to always lowercase wikilink
   targets. Brittle: agents drift from prompt instructions over
   time and across runtimes.
2. **Repair the drift at end-of-cycle.** Run a normalizer
   automatically after each cycle's note-writer step. Belt-and-
   braces; the prompt instruction can co-exist later.

We picked (2). The prompt-engineering path is fragile; the
post-cycle normalizer is deterministic.

## Decision

Introduce `src/research_vault/pipeline/wikilinks.py` with a single
public function `auto_fix_moved_wikilinks(vault) -> int`. It:

- Walks `data_vault/` for every markdown note.
- Builds a set of lowercase filename stems (the "known targets").
- For each note: parses frontmatter + body. In the body, walks
  line-by-line tracking fenced code-block state. For each
  `[[Target]]` (and `[[Target|alias]]`) found OUTSIDE a code
  fence: if `target.lower() in stems` AND `target != target.lower()`,
  rewrites to lowercase. In the frontmatter's `related` list:
  same rule (no code-fence concern there).
- Returns the count of FILES modified, not the count of individual
  fixes. Suitable for a one-line log entry.

ONLY case mismatches are fixed. Unknown targets (orphans) are left
alone. New stub notes are NOT created. Wikilinks inside fenced code
blocks are NEVER touched (they're typically counter-examples or
actual code).

Wired into `cycle_runner.run_cycle_steps` as **Step 3c**, after the
verifier and before validate_vault. The helper is idempotent so it's
safe to call every cycle.

## Consequences

**Good**:

- The vault graph stays clean across cycles. The 207-link
  fragmentation observed in 0.2.30 cannot happen again.
- Idempotency means we can call it from anywhere without worrying
  about double-application.
- The "ONLY fixes case" scope makes the helper safe to enable by
  default. Heavier mutations (stub creation, orphan pruning) stay
  in `vault_health.py --apply` where they require user intent.

**Trade-offs**:

- The helper does a full vault-walk on every cycle. On large
  vaults this is O(N) markdown reads per cycle. We accept this;
  cycles already do a vault-walk for other purposes and this one
  is cheap (regex-based, no LLM calls).
- A note-writer that drifts from convention will still produce
  broken links AT WRITE TIME; the normalizer fixes them between
  cycles. There's a small window (between note-write and the next
  Step 3c) where the graph is inconsistent. We accept this; the
  alternative (block the cycle until every note is clean) is
  worse.

## Alternatives considered

- **Pure prompt engineering** (instruct note-writer to lowercase).
  Rejected as primary fix; brittle. May still be added later as
  belt-and-braces.
- **Reuse `vault_health.py::apply_wikilink_fixes()`**. Rejected:
  that function does heavier work (stub creation, orphan pruning)
  that requires human judgement.
- **Block the cycle when any note has a case-mismatched wikilink**.
  Rejected: too aggressive. The auto-fix is cheap and reliable;
  blocking would just make every cycle red without adding value.

## Tests

`tests/pipeline/test_wikilink_normalization.py` covers 9 cases
including PascalCase, acronyms, alias preservation
(`[[Cassandra|the distributed store]]` \u2192
`[[cassandra|the distributed store]]`), code-fence skipping,
idempotency, empty vault, and missing `data_vault/`. All GREEN at
the time of this ADR.
