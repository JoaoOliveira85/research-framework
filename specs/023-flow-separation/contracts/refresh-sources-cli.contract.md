# Contract: `./vault refresh-sources` (FR-013)

**Phase**: 1 only  
**Status**: Draft (plan artifact)  
**Implements**: FR-013, FR-001 exit-code semantics, FR-002 `--json`  
**Spec reference**: `specs/023-flow-separation/spec.md` → FR-013, Phase 1 ship criterion #1

## Invocation

```bash
./vault refresh-sources [options]
# Framework CLI equivalent (testing):
python -m research_framework.cli refresh-sources --vault <path> [options]
```

### Options

| Flag | Description |
|------|-------------|
| `--json` | Emit machine-readable summary to stdout (FR-002) |
| `--dry-run` | List collectors that would run; do not execute |
| `--only <basename>` | Repeatable; restrict to named scripts. Basename MUST match either `collect_*.py` OR the legacy allowlist documented under [Collector discovery](#collector-discovery) (currently `reddit_rss.py`). |
| `-v` / `--verbose` | Stream each collector's stdout/stderr to terminal |

Vault root: inferred from shim `VAULT_DIR` or `--vault` on direct CLI.

## Collector discovery

1. If `settings.yaml` contains `refresh_sources.collectors`, use that ordered list (basenames only).
2. Else discover via:
   - Glob `<vault>/scripts/collect_*.py`
   - Plus any basename in the **legacy allowlist** (Phase 1, frozen): `reddit_rss.py`. The allowlist captures pre-`collect_*` collector names that exist in the wild (notably feeds-vault's `reddit_rss.py`). Merged with the glob result and sorted lexicographically.
3. Apply `--only` filter if present. `--only` basenames MUST satisfy `collect_*.py` OR appear in the legacy allowlist; other names error with exit 2 (`unknown collector '<basename>': must match collect_*.py or be in the legacy allowlist`).
4. Skip non-files (broken symlinks, directories); emit `skipped` with `reason: "not a file"`. **Do not** filter on the executable bit \u2014 collectors are invoked via `python <script>.py` so mode `0644` files are valid and many vault-local collectors ship that way. Emit `skipped` with `reason: "missing"` if `--only` names a script not present on disk.

## Execution

For each collector:

```text
<venv_python> <vault>/scripts/<collector> [collector-specific args]
cwd = <vault>
env = inherit + PYTHONUNBUFFERED=1
timeout = settings.refresh_sources.timeout_s (default 600)
```

- **No** LLM dispatch (Principle IV).
- Collectors are responsible for writing under `raw_data/<source>/` per vault conventions.
- Framework does not parse collector stdout structure in v1 — only exit code, duration, stderr tail.

## Stdout / stderr

### Human mode (default)

- Progress lines to stderr: `[refresh-sources] running collect_youtube.py ...`
- Final summary to stderr (counts ok/failed/skipped).
- Exit code per table below.

### `--json` mode

Single JSON object on stdout (no other stdout). Schema: `data-model.md` §3.

Example:

```json
{
  "vault": "/Users/me/Documents/feeds-vault",
  "partial_failure": false,
  "collectors": [
    {
      "script": "collect_youtube.py",
      "status": "ok",
      "exit_code": 0,
      "duration_s": 42.1,
      "raw_dirs": ["raw_data/youtube"],
      "stderr_tail": ""
    }
  ]
}
```

## Exit codes (FR-001)

| Code | Meaning |
|------|---------|
| 0 | All executed collectors succeeded |
| 1 | Partial success (≥1 ok, ≥1 failed) OR operational complete with null harvest (reserved — not used v1) |
| 2 | Framework error: no venv, no collectors found, all collectors failed, settings parse error, timeout orchestration failure |

## Idempotency

- **Safe to re-run**: collectors may append/refresh `raw_data/`; framework does not deduplicate.
- **Not byte-idempotent**: output depends on external sources.

## Headless contract

- No TTY prompts in default mode.
- `--dry-run` never prompts.

## Integration points

| Component | Role |
|-----------|------|
| `templates/vault-script.sh.j2` | `refresh-sources)` case → `exec "${RV}" refresh-sources --vault "${VAULT_DIR}" "$@"` |
| `cli/_parser.py` | Subparser registration |
| `cli/refresh_sources.py` | Implementation |
| Legacy `scripts/collect_*.py` | ADR-0009 preserved surface |

## Test obligations

- Tier-3: fixture vault with stub `scripts/collect_stub.py` returning 0 and writing `raw_data/stub/`.
- Tier-3: partial failure → exit 1, JSON `partial_failure: true`.
- Tier-3: missing venv → exit 2.

## Out of scope (Phase 2+)

- Module-based refresh via `modules/*/sources.yaml` (spec 020).
- `_pipeline/active-sources.json` update after refresh.
