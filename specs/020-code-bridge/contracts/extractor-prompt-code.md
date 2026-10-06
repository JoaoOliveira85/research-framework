# Code Module Extractor Prompt (v1)

Used by `<vault>/modules/code/extractor.py` to invoke an LLM that
produces a SignalPayload for a single source (one local repo
checkout) per extraction call.

**Resolution**: Module's manifest declares `default_tier: normal`.
Vault authors can override via `stages.source_extraction.tier:` in
`settings.yaml`. The value_tier in the request payload then maps to
the consensus N (1/3/5) per D2; each spawned extractor uses the
resolved tier model.

## Input contract (stdin)

```json
{
  "source_id": "/Users/.../my-repo",
  "source_version": "abc123...",
  "schema": { /* the per-vault FactsSchema from facts-schema.json */ },
  "value_tier": "routine",
  "framework_meta": {
    "bridge_version": "0.3.0",
    "vault_root": "/Users/.../my-vault",
    "cycle": 12
  }
}
```

## Output contract (stdout)

A JSON object matching `contracts/signal-payload.schema.json`. The
module strips no envelope fields. Module writes ONLY to stdout for
the payload; status heartbeat + warnings to stderr.

## Prompt template

```text
You are a code-repository fact extractor for a research vault. Your
job is to read the codebase at the path provided and emit a structured
SignalPayload that captures what THIS VAULT cares about.

## What this vault cares about

The vault's `facts` schema has these top-level buckets:

{{schema_buckets_with_descriptions}}

Each bucket's `description` tells you what kinds of signals belong
there. Fill each bucket with concrete signals you find in the
codebase. If a bucket doesn't apply to this repo, emit an empty
value.

## Repository at: {{source_id}}

The repository is a local git checkout. You have read access to all
files. Useful starting points:

- `README.md`, `CONTRIBUTING.md`, `ARCHITECTURE.md` (if present)
- `docs/`, `documentation/`, `adr/`, `decisions/` directories
- Configuration: `pyproject.toml`, `package.json`, `Cargo.toml`,
  `pom.xml`, `Makefile`, etc.
- Source tree: `src/`, `lib/`, `app/`, etc.
- Git log for recent decision activity:
  `git log --since='30 days ago' --pretty=format:'%h %s'`

Your extraction should reflect the WHOLE repository's content, not
just the README.

## Extraction principles

1. **Cite evidence.** For every `notable` observation, include a
   precise `evidence_ref` (file path + line range, or commit SHA, or
   PR/issue URL if present in git log).
2. **Be specific.** Prefer "React 18 with Server Components" over
   "JavaScript framework".
3. **Respect bucket boundaries.** Don't put architectural decisions
   into `technologies` if a `decisions` bucket exists.
4. **Confidence honestly.** Use `low` if you inferred from indirect
   signals; `high` if there's explicit documentation.
5. **Empty buckets are OK.** A `decisions` bucket with `[]` is more
   honest than fabricated content.

## Verdict policy

- `ok`: extraction succeeded; payload has substantial content.
- `empty`: repository scanned but no relevant signals (e.g. an empty
  repo, or one that's entirely irrelevant to the vault's domain).
- `exhausted`: source has been over-extracted; nothing new compared
  to what's already in the vault (rarely produced by code module \u2014
  more common for transcript modules).
- `error`: extraction encountered an unrecoverable problem
  (corrupt repo, FS permission denied). Set `partial: true` if any
  facts were salvaged.

## Output

Emit the SignalPayload JSON on stdout. NO leading text, NO trailing
text, NO markdown fence \u2014 just the JSON object. The framework
parses with a tolerant extractor but pure JSON is strongly preferred.
```

## Heartbeat policy

For repos > 100 files, the extractor SHOULD write a status heartbeat
to `_pipeline/sources/code/.status/<source-hash>.json` every ~5
seconds with `{"progress": float, "current_file": str, "elapsed_s":
int}`. Bridge uses this for the run-report's "stalled extractions"
warning when no heartbeat for 60s on a long-running call.

## v1 tuning targets

- 95% schema-conformance on the 5-vault validation suite (SC-002).
- Avg latency < 90s per call on a 1k-file repo (SC-001 budget).
- Verifier rejection rate < 15% on signals emitted for vault notes
  (SC-003).

## Test fixtures

`tests/source_bridge/test_extractor_contract.py` runs the extractor
against `tests/fixtures/fake_repo/` (canned repo with known content)
and asserts:

- Output passes `signal-payload.schema.json`.
- Output passes the test fixture's `code.validators.yaml` rules.
- Specific signals are present (e.g. `facts.technologies` includes
  "Python 3.11", `notable` includes a reference to the
  ARCHITECTURE.md decision section).
