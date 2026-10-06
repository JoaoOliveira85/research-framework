# Feature Specification: Processors in the Framework

**Feature Branch**: `015f-processors-in-framework` *(proposal — not yet branched)*
**Parent**: [015 — Pipeline Consolidation](../015-pipeline-consolidation/spec.md), Stage 2 (second slice)
**Created**: 2026-05-13
**Status**: shipped(2026-05-21, commit e73b6de) — SHIPPED — the framework-side processor model this spec proposed is live: `src/research_framework/processors/{extract,verify,preprocess,archive}.py` are in-tree (landed pre-0.2.33, carried through the 2026-05-21 `research_vault`→`research_framework` rename). Header flipped 2026-06-01 (ROADMAP QW-7).

## Problem

The feeds-vault carries ~4,300 lines of Python under `scripts/`:

| Script | Lines | Role |
|---|---|---|
| `collect_rss.py` | 962 | RSS/Atom poller |
| `verify.py` | 842 | post-collection quality check |
| `reddit_rss.py` | 697 | Reddit collector |
| `extract.py` | 651 | content extraction from raw HTML/PDF |
| `collect_youtube.py` | 468 | YouTube transcripts |
| `collect_oreilly.py` | 430 | O'Reilly Learning chapters |
| `reddit_scraper.py` | 363 | Reddit JSON API |
| `preprocess.py` | 307 | normalisation + dedupe |
| `archive.py` | 164 | move rejected items to `_pipeline/archive/<month>/` |

[014 — Reusable Collectors](../014-reusable-collectors/spec.md)
handles the collectors slice (`collect_rss.py`, `collect_youtube.py`,
`reddit_*.py`, `collect_oreilly.py`). This spec is the second
slice: the **processors** — `extract.py`, `preprocess.py`,
`verify.py`, `archive.py` — which run after collection on the raw
items.

These four scripts also exist in essentially the same shape across
real research vaults (the feeds-vault's `verify.py` is reportedly a
descendant of an earlier codebase-vault `verify.py`; both implement
the "Haiku quick scan + Sonnet deep review" pattern). They drift
independently and improvements don't cross-pollinate.

## Goals

1. Each processor lives as a Python module under
   `research_vault.processors`.
2. Each exposes a stable Python API + a CLI entry point
   `python -m research_vault.processors.<name> <vault>`.
3. Each reads vault state from a documented set of paths under
   `<vault>/_pipeline/` and writes to a documented set under
   `<vault>/_pipeline/` and/or `<vault>/<corpus>/`.
4. The vault's per-vault customisation is configured via spec
   fields (verify thresholds, extract model preferences, etc.)
   — no source-edits required to change behaviour.

## Non-goals

- **Not** a complete replacement for the feeds-vault scripts on day
  one. The first slice promotes one processor (likely `extract`,
  since it's the cleanest dependency boundary) and runs it
  alongside the vault-local versions until parity is verified.
- **Not** a new pipeline orchestrator. That's
  [015g](../015g-pipeline-orchestrator-command/spec.md).
- **Not** the agent definitions. That's
  [015e](../015e-agent-definitions-as-templates/spec.md).

## User scenarios

### Story 1 — Vault opts into the framework extractor

```yaml
# my-vault-spec.md
...
processors:
  extract:
    enabled: true
    model: "claude-haiku-4-5"   # cheap pass
    context_tree_target: "_pipeline/extracted/context-tree.md"
```

After `migrate apply`, the vault's `/extract` slash command (or
`/pipeline extract` step) shells out to:

```bash
python -m research_vault.processors.extract <vault>
```

instead of `python scripts/extract.py`. Output is identical for
the same inputs.

### Story 2 — Framework ships an improved verifier

`research_vault.processors.verify` gains a "claim-source-pinned"
check. Existing vaults get it on `pip install research-vault==X.Y.Z`
— no per-vault edits.

### Story 3 — Vault retains a custom processor

A vault needs domain-specific extraction (e.g. legal opinions
need different extraction than AI papers). The vault's spec:

```yaml
processors:
  extract:
    enabled: false       # use scripts/extract.py instead
```

The vault's slash command falls back to the local script. Best of
both worlds: framework processor for what's generic, local
override where domain knowledge matters.

## Design

### Module structure

```
research_vault/processors/
  __init__.py
  _common.py       # shared helpers (path conventions, frontmatter writer, content hashing)
  extract.py
  preprocess.py
  verify.py
  archive.py
```

### Each processor's contract

```python
# research_vault/processors/extract.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class ExtractResult:
    files_processed: int
    files_skipped: int
    context_tree_path: Path
    errors: tuple[str, ...]

def extract(
    vault: Path,
    *,
    since: str | None = None,
    dry_run: bool = False,
) -> ExtractResult:
    """Read raw items from <vault>/_pipeline/raw/**, synthesise
    a context tree at <vault>/_pipeline/extracted/context-tree.md.
    Idempotent — re-running skips items already in the tree."""
```

CLI entry point:

```bash
python -m research_vault.processors.extract <vault> [--since DATE] [--dry-run]
```

### Shared I/O conventions

All processors agree on:

- **Raw items live in** `<vault>/_pipeline/raw/<source_kind>/<id>.md`.
- **Each raw item carries frontmatter** with `source_kind`,
  `source_id`, `collected_at`, `original_url`, `content_hash`
  (defined by 014).
- **Extracted artefacts** live in `<vault>/_pipeline/extracted/`.
- **Verify outputs** live in `<vault>/_pipeline/logs/verify-<date>.md`.
- **Archive destination** is `<vault>/_pipeline/archive/<YYYY-MM>/<id>.md`.

These conventions become a JSON Schema under
`specs/015f/contracts/raw-item.schema.json` so future processors
can be validated against them.

### Spec field

```yaml
processors:
  extract:
    enabled: true                            # default true
    model: "claude-haiku-4-5"                # default — config below
    context_tree_target: "_pipeline/extracted/context-tree.md"
  preprocess:
    enabled: true
    dedupe_strategy: "content_hash"          # or "url"
  verify:
    enabled: true
    haiku_first_pass: true
    sonnet_deep_review: true
    fail_threshold: 0.20                     # % of flagged notes that fails the run
  archive:
    enabled: true
    after_days: 90                           # rejected items older than this
```

All fields optional with sensible defaults.

## Acceptance

- [ ] Four processor modules implemented; each with a CLI entry
      point and a Python API.
- [ ] One real vault (likely codebase-vault, since its processor
      surface is smaller) is migrated end-to-end to use the
      framework processors. Its `/pipeline extract/verify` calls
      now shell out to `python -m research_vault.processors.X`.
- [ ] Per-processor tests under `tests/processors/` using fixtures
      that exercise the I/O conventions.
- [ ] `raw-item.schema.json` contract committed and used by all
      processors at their input boundary.
- [ ] [015 Stage 2](../015-pipeline-consolidation/spec.md)
      checklist item marked done.

## Out of scope

- LLM provider abstraction across processors. Each processor
  knows how to call its model (today: Claude via `agent_call.py`).
  Provider abstraction is a separate spec.
- The orchestration that sequences processors. That's
  [015g](../015g-pipeline-orchestrator-command/spec.md).
- A web UI for verify reports. The output is a markdown file;
  consumption is up to the user.

## Open questions

- **Migration plan for feeds-vault.** feeds-vault's `extract.py` is
  651 lines. Either we (a) port it as-is into
  `processors/extract.py` (preserving all its quirks and
  becoming responsible for it) or (b) write a fresh implementation
  against the contract and feeds-vault opts in. (b) is cleaner but
  loses any subtle behaviour the script encodes. Tentative: do
  (a) for the first slice — capture the existing behaviour as
  the framework's baseline, then iterate.
- **Per-processor versioning.** Should each processor module carry
  a version that the spec can pin against (e.g. "use extract v2")?
  Defer until we see two incompatible improvements land in the
  same module.
- **Concurrency.** feeds-vault's `extract.py` is "idempotent, resumable,
  and parallel-safe" (per its docstring). The framework processors
  should preserve those properties. Tests required.
