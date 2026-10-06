# Contract: `speckit reindex`

**Sub-command**: `speckit reindex`
**Version**: v1.0+

---

## Synopsis

```
speckit reindex --vault <dir> [--dry-run]
```

---

## Arguments

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `--vault` | path | Yes | — | Path to vault root directory |
| `--dry-run` | flag | No | off | Show what would be written without modifying files |

---

## Behavior

Rebuilds all Layer 1 index files from the current state of Layer 2 notes. Full rebuild
— not incremental. Reads every note in `data_vault/`, parses frontmatter, and regenerates:

| File | Content |
|------|---------|
| `_index.md` | Flat list of all notes by folder, with title and summary |
| `_concepts.md` | Alphabetical index of concept notes only |
| `_graph.md` | Wikilink adjacency from `related` fields; not inferred |
| `AGENTS.md` | Topic index section updated with current note counts |

Layer 1 files are always a projection of Layer 2. `reindex` makes that projection current.

Normally called automatically by `speckit generate` during Phase 3. Expose as a standalone
sub-command for:
- Recovery after manual note edits
- Testing the indexer in isolation
- Running after a targeted Phase 2 cycle without full Phase 3

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All index files rebuilt successfully |
| 1 | One or more notes skipped (malformed frontmatter) — index built from valid notes |
| 2 | Abort: vault directory missing or `data_vault/` empty |

---

## Output

```
Reindexing Acme Corp Codebase Vault
─────────────────────────────────────
Notes read:       166
Notes skipped:    0 (malformed frontmatter)
_index.md:        ✓ (166 entries)
_concepts.md:     ✓ (47 entries)
_graph.md:        ✓ (312 wikilink edges)
AGENTS.md:        ✓ (topic index updated)

Layer 1 rebuild complete.
```

---

## Error Cases

| Condition | Exit | Output |
|-----------|------|--------|
| `--vault` path does not exist | 2 | "vault directory not found: {path}" |
| `data_vault/` empty | 2 | "no notes found in data_vault/" |
| Note has malformed YAML | 1 | "skipped {file}: YAML parse error — {message}" |
