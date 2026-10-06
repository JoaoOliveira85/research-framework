# Contract: Atomic write protocol (FR-018)

**Phase**: 1 only  
**Status**: Draft (plan artifact)  
**Implements**: FR-018, Clarifications Q5 (readers see consistent snapshots)  
**Module**: `src/research_framework/pipeline/atomic_write.py`

## API

```python
def write_bytes(path: Path, data: bytes, *, mode: int | None = None) -> None: ...

def write_text(
    path: Path,
    text: str,
    *,
    encoding: str = "utf-8",
    mode: int | None = None,
) -> None: ...

def write_json(
    path: Path,
    obj: Any,
    *,
    indent: int = 2,
    trailing_newline: bool = True,
) -> None: ...
```

### Algorithm (normative)

1. `path.parent.mkdir(parents=True, exist_ok=True)`
2. Create `tempfile.NamedTemporaryFile(dir=path.parent, delete=False, prefix=".atomic-", suffix=".tmp")`
3. Write full payload; `flush()`; `os.fsync(fd)`
4. `os.replace(temp_path, path)`
5. Best-effort: open `path.parent` and `os.fsync` (ignore `AttributeError` / unsupported OS)
6. If `mode` is not None, `path.chmod(mode)` after replace
7. On any failure before step 4: unlink temp if it exists; re-raise; **destination unchanged**

## Guarantees

| Guarantee | Description |
|-----------|-------------|
| **Atomic visibility** | Readers never observe a partially written target file |
| **Crash safety** | Kill -9 after step 4 → readers see old or new file entirely |
| **Same-directory temp** | Temp MUST live in `path.parent` so `os.replace` is atomic on POSIX |
| **No locking** | FR-018 explicitly does not add lock files; concurrent readers allowed |

## Failure modes

| Scenario | Outcome |
|----------|---------|
| Disk full during write | `OSError`; destination unchanged |
| Permission denied on parent | Fail before write; no temp left or cleaned |
| SIGKILL before `os.replace` | Orphan `.atomic-*.tmp`; destination unchanged |
| SIGKILL after `os.replace` | New content visible (complete) |
| Reader opens during replace | POSIX atomic — reader gets old or new inode content |
| Destination is directory | Raise before write |

**Not guaranteed**: fsync to physical disk on all platforms (best-effort); NFS caveats documented in module docstring.

## Call sites — Phase 1 MUST adopt

| Priority | Location | File pattern |
|----------|----------|--------------|
| P0 | Research step batch JSON | `_pipeline/cycles/cycle-NNN-batch-NNN.json` |
| P0 | Research report JSON | `_pipeline/cycles/cycle-NNN-research.json` (if written non-atomically) |
| P0 | Postprocess cycle JSON | `_pipeline/cycles/cycle-NNN-postprocess.json` |
| P0 | Verifier frontmatter stamp | `data_vault/**/**.md` via `_stamp_frontmatter` |
| P0 | Wikilink normalization | `wikilinks.py` note body writes |
| P1 | Runner pipeline state | `_pipeline/pipeline-state.json` |
| P1 | Scout plan writes | `research-plan.md` cycle archives |
| P2 | Delegate existing helpers | `runner._atomic_write_json`, `research_plan._atomic_write_text`, etc. |

**Agent-written notes**: Produced by `note-writer` via `agent_call` / fake-agent writing files directly. Phase 1 adds **tier-5 test** that simulates concurrent read during cycle; if gap found in fake-agent write path, file follow-up to route agent writes through a post-write validator — **not blocking** if fake-agent already writes atomically (verify in tasks).

## SQLite WAL

`_pipeline/sources.db` — **no change**; WAL mode already enabled. FR-018(b) satisfied by existing configuration.

## Reader verbs

`./vault ask`, `./vault query` — **MUST NOT** acquire locks (FR-018 + Clarifications Q5). Read whatever exists at read time.

## Test obligations

| Tier | Test |
|------|------|
| 2 | Crash injection via mock `os.replace` failure → destination preserved |
| 2 | Concurrent reader thread: never reads truncated JSON mid-parse |
| 5 | `./vault research` (fixture) + parallel file reads on `data_vault` and cycle JSON |

## Deprecation

Internal `_atomic_write_*` duplicates become thin wrappers calling `atomic_write` in Phase 1 implementation PR (behaviour-preserving).

## Out of scope

- Advisory locks / snapshot isolation (deferred future spec)
- Cross-vault write coordination
