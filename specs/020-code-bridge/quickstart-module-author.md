# Quickstart: Building a Source Module

This guide walks you through building a new source module for the
`research-framework`. You'll build a hypothetical `twitter` module
that extracts structured facts from Twitter/X threads.

> ## WARNING: Trust Boundary
>
> Modules execute arbitrary Python code in the framework's process
> (v1; no sandbox). When a vault author lists your module in their
> `settings.yaml::modules:` block, they are granting your code full
> trust to read their filesystem, make network calls, and emit
> arbitrary data into their vault. **Only ship a module you'd be
> comfortable running on someone else's machine.**
>
> A future framework version may add subprocess sandboxing. v1
> relies on documentation and the install wizard's trust prompt.
> Don't break that trust.

## The contract you implement

A module is a directory with:

```
<module-name>/
\u251c\u2500\u2500 manifest.yaml           # required: identity, triggers, source_id_from
\u251c\u2500\u2500 sources.yaml            # required at runtime: instance list (vault copy)
\u251c\u2500\u2500 extractor.py            # required: the LLM-driven extractor entry point
\u251c\u2500\u2500 few-shot.md             # required: schema-gen few-shot examples
\u251c\u2500\u2500 validators.yaml         # optional: default validation rules
\u251c\u2500\u2500 validators.py           # optional: procedural validators
\u2514\u2500\u2500 README.md               # recommended: end-user-facing docs
```

The framework calls `extractor.py` as a subprocess, passes a JSON
request on stdin, and expects a `SignalPayload` JSON on stdout. The
module sees ONLY the inputs the framework gives it \u2014 no framework
imports, no privileged config access.

## Step 1: `manifest.yaml`

```yaml
name: twitter
version: 0.1.0
description: Extract structured signals from Twitter/X threads.

triggers:
  - type: url_pattern
    pattern: '^https?://(www\.)?(twitter\.com|x\.com)/[^/]+/status/\d+'

entry_point: extractor.py
default_value_tier: routine        # routine | important | critical
default_tier: basic                 # basic | normal | flagship (D7 model tier)
schema_examples: few-shot.md
source_id_from:                    # FR-013b: map sources.yaml keys → identity field
  twitter_threads: url
user_owned:                        # optional: extra paths preserved on vault update
  - custom_prompt.md
```

Ship a **`sources.yaml.template`** (or commented `sources.yaml`) in the
bundle so install/update can seed vault copies when absent. Existing
vault `sources.yaml` files are never overwritten on update (FR-025).

Validate against [`manifest.schema.json`](./contracts/manifest.schema.json):

```bash
research-framework schema --validate-manifest <vault>/modules/twitter/manifest.yaml
```

### Triggers

Three trigger types are supported:

| Type | Pattern is | Matched against |
|------|------------|-----------------|
| `url_pattern` | Python regex | `source_id` (the URL or path) |
| `path_pattern` | Python regex | `source_id` |
| `path_exists` | Glob | Resolved path on disk (e.g. `.git/HEAD` to detect a code repo) |

Modules can declare multiple triggers; framework matches the first
one that hits. Triggers route **generic** scout URLs and support
`--debug-triggers`; they do **not** replace `sources.yaml` enumeration
(FR-013a).

## Step 1b: `sources.yaml` (vault operator surface)

Vault authors list **instances** your module should extract. Top-level
keys are module-specific; values are lists of records.

```yaml
# <vault>/modules/twitter/sources.yaml (after install)
twitter_threads:
  - url: https://x.com/foo/status/12345
  - url: https://x.com/bar/status/67890
```

Your `source_id_from` in the manifest tells the framework which record
field becomes `source_id` for each key. Default if omitted: `url`, else
`name`.

Contract: [`sources.yaml.contract.md`](./contracts/sources.yaml.contract.md).

The framework discovers your module on the **next pipeline start** by
walking `<vault>/modules/*/manifest.yaml` — no `settings.yaml` edit
required for drop-in folders. Listing the module in `settings.yaml::modules:`
only affects bundle copy on install/update and trigger precedence order.

## Step 2: `few-shot.md`

This file teaches the per-vault schema-gen what kinds of buckets are
appropriate for YOUR data source. It's NOT the schema itself \u2014 it's
a calibration set the schema-gen LLM uses to figure out the right
granularity for THIS vault.

Format: 2-3 example schemas showing the SHAPE of buckets a twitter
extractor should produce. Vary by domain to teach the model that
buckets are domain-driven, not hard-coded.

```markdown
# Example: web-microservices vault

```json
{
  "type": "object",
  "properties": {
    "technologies": { "type": "array", "items": {"type": "string"} },
    "opinions": { "type": "array", "items": {"type": "string"} },
    "thread_topic": { "type": "string" }
  }
}
```

# Example: AI safety vault

```json
{
  "type": "object",
  "properties": {
    "research_directions": { "type": "array", "items": {"type": "string"} },
    "alignment_concerns": { "type": "array", "items": {"type": "string"} },
    "thread_topic": { "type": "string" }
  }
}
```
```

The schema-gen call composes your few-shot with the vault's
`research.spec.md` and produces the actual `facts-schema.json` for
THIS vault.

## Step 3: `extractor.py`

```python
"""Twitter thread extractor."""
import json
import sys
from datetime import datetime, timezone

def main():
    request = json.loads(sys.stdin.read())
    source_id = request["source_id"]
    schema = request["schema"]                # the per-vault FactsSchema
    framework_meta = request["framework_meta"]
    
    # ... your extraction logic ...
    # Fetch the thread, run an LLM against the schema, build the payload
    
    payload = {
        "module": "twitter",
        "source_id": source_id,
        "source_version": "<thread-content-hash>",
        "bridge_version": framework_meta["bridge_version"],
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "verdict": "ok",
        "truncated": False,
        "partial": False,
        "facts": {
            # buckets per the per-vault schema:
            "technologies": ["FastAPI", "PostgreSQL"],
            "opinions": ["Strongly favors event sourcing"],
            "thread_topic": "..."
        },
        "notable": [
            {
                "observation": "Author cited a specific RFC",
                "confidence": "high",
                "evidence_ref": "tweet:1234567890"
            }
        ]
    }
    
    json.dump(payload, sys.stdout)

if __name__ == "__main__":
    main()
```

### Input contract (stdin)

```json
{
  "source_id": "https://x.com/foo/status/12345",
  "source_version": null,                 // present when the framework has a hint
  "schema": { /* per-vault FactsSchema */ },
  "value_tier": "routine",                // routine | important | critical
  "framework_meta": {
    "bridge_version": "0.3.0",
    "vault_root": "/Users/...",
    "cycle": 12
  }
}
```

### Output contract (stdout)

A single JSON object matching [`signal-payload.schema.json`](./contracts/signal-payload.schema.json).

Framework parses with a tolerant extractor (handles leading/trailing
whitespace) but **emit pure JSON** \u2014 no markdown fences, no prose.

### What you write to stderr

Log lines (one per line). The framework captures stderr verbatim
into `bridge.log` for debugging. Don't write JSON-encoded stdout
content to stderr; the parser doesn't read stderr.

### Status heartbeat (optional but recommended)

For extractions longer than ~30s, write a heartbeat every ~5
seconds:

```python
import os
HEARTBEAT_PATH = f"{vault_root}/_pipeline/sources/twitter/.status/{source_hash}.json"

def heartbeat(progress: float, current: str):
    with open(HEARTBEAT_PATH, "w") as f:
        json.dump({
            "progress": progress,
            "current_file": current,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "extractor_pid": os.getpid(),
        }, f)
```

### How the framework uses your heartbeat

| What | When |
|------|------|
| Recommended write cadence | every ~5s |
| Parent polls your status file | every 30s while your subprocess is alive |
| "Stalled" threshold | 60s without an update |
| Action on stall | WARN + log + surface in run-report's "Stalled extractions" section |
| Hard wall-clock timeout | 600s default \u2014 SIGTERM and apply isolation (D9) |

**Important**: stall \u2260 kill. Even if you miss a heartbeat for 184s,
the framework will still let you run to the 600s hard cap. The
stall is purely a diagnostic surface so the vault author sees where
cycle time went. A future framework version may add an opt-in
`heartbeat_policy: kill_on_stall` for modules that want stricter
recovery; v1 ships warn-only.

### Configurable timeout

If your extraction legitimately needs longer than 600s (e.g. video
transcription, large-monorepo walk), declare it in your manifest:

```yaml
extraction_timeout_seconds: 1800   # 30 minutes; min 30, max 7200
```

Vault authors can override this by setting
`settings.yaml::stages.source_extraction.timeout_seconds`. Their
value wins; respect that if it's set lower than your manifest
default (they're saying "fail fast for this vault").

### Heartbeat parse robustness

The parent reads your status file with `try: json.loads(...)`. If
your module crashes mid-write and leaves a partial JSON file, the
parent treats it as "no recent heartbeat" (= stalled). Your next
successful write fixes the file. **Don't try to be clever with
locking** \u2014 best-effort writes are good enough because the contents
are diagnostic, not load-bearing.

### Multi-process race (consensus)

When the vault's `value_tier` triggers N>1 extractors (D2), all N
spawn for the SAME source and write to the SAME status path. Last
writer wins. This is fine because the contents are diagnostic. Don't
suffix-by-spawn-index in v1 \u2014 the framework doesn't read that yet.

## Step 4: Validators (optional)

Ship a default `validators.yaml`:

```yaml
facts:
  thread_topic:
    required: true
    min_length: 5
notable:
  min_items: 1
```

If you need procedural rules, ship a `validators.py`:

```python
def validate(payload: dict) -> list[str]:
    """Return list of error strings; empty list = pass."""
    errors = []
    facts = payload.get("facts", {})
    # Custom rules...
    return errors
```

> **Module-isolation note**: if your `validate()` function raises
> an unhandled exception, the framework retries the call once, then
> isolates the source for this cycle (per
> [`module-isolation-protocol.md`](./contracts/module-isolation-protocol.md)).
> Other sources continue to extract normally. Test your validators
> against malformed payloads.

## Step 5: Test locally

**Pre-PR gate** (both must pass before opening a PR — the release
workflow blocks on both):

```bash
ruff check src/research_framework/modules/<name>/ tests/source_bridge/test_<name>_module.py
ruff format --check src/research_framework/modules/<name>/ tests/source_bridge/test_<name>_module.py
PYTHONPATH="$(pwd)/src" pytest tests/source_bridge/test_<name>_module.py -v
PYTHONPATH="$(pwd)/src" pytest -m "not e2e"
```

`ruff check` covers lint rules; `ruff format --check` covers auto-
formatting. They're separate gates — passing one does not imply
passing the other. (Caught in Wave 2: the `reddit`/`rss`/`oreilly`
PRs passed `ruff check` but failed `ruff format --check`, requiring a
hotfix PR after the 0.6.0 release tag was cut.)

### Test helper example

The framework ships test helpers for module authors:

```python
# tests/source_bridge/test_twitter_module.py
import json
import subprocess
from pathlib import Path

def test_twitter_extractor_happy_path(tmp_path):
    request = {
        "source_id": "https://x.com/foo/status/12345",
        "source_version": None,
        "schema": json.loads(Path("contracts/example-twitter-schema.json").read_text()),
        "value_tier": "routine",
        "framework_meta": {
            "bridge_version": "0.3.0",
            "vault_root": str(tmp_path),
            "cycle": 1
        }
    }
    result = subprocess.run(
        ["python", "modules/twitter/extractor.py"],
        input=json.dumps(request).encode(),
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["verdict"] in ("ok", "empty")
    assert payload["module"] == "twitter"
    # Validate against signal-payload.schema.json
    # ...
```

## Step 6: Failure-mode discipline

The framework applies retry-once + salvage-and-continue to your
extractor (per
[`module-isolation-protocol.md`](./contracts/module-isolation-protocol.md)).
You don't need to handle retries yourself \u2014 just:

1. **Don't swallow exceptions silently.** Let them propagate to the
   subprocess boundary. The framework retries and surfaces them.
2. **Emit partial output when possible.** If your extractor crashes
   midway, the framework attempts to salvage whatever valid JSON you
   wrote to stdout before the crash. So write your payload in a
   streaming-friendly way (e.g. emit `facts` populated as you
   discover signals, not at the very end).
3. **Set timeouts.** Wrap any network call in a 30s timeout. The
   framework's outer timeout is 600s; you want to fail fast on
   transient flakes.
4. **No global state.** Each extractor call is a fresh subprocess.
   Don't rely on in-memory caches across calls.

## Step 7: Distribution

Modules live in the framework bundle at:

```
research_framework/modules/<your-module>/
```

On vault install, the install wizard copies the modules listed in
`settings.yaml::modules:` into `<vault>/modules/`. On `vault update`,
the migrator refreshes framework code (per D6). **`sources.yaml` and
`user_owned` paths are preserved** if present (FR-025). To fork module
code, rename the folder (e.g. `twitter-custom`) so the migrator skips it.
Operator instances stay in `sources.yaml`.

To contribute a module to the framework upstream:

1. Add your module under `src/research_framework/modules/<name>/`.
2. Add a contract test: `tests/source_bridge/test_<name>_module.py`.
3. Ship few-shot examples covering at least 3 contrasting vault
   domains (web, embedded, non-tech \u2014 e.g. biology research).
4. Update the framework's CHANGELOG.md mentioning the new module.
5. PR to the framework repo.

## Step 8: Versioning

Your module has its OWN semver in `manifest.yaml::version`,
independent of the framework's `bridge_version`. Bump it when:

- The extraction prompt changes substantively (MINOR).
- The few-shot examples expand (MINOR).
- The validators tighten (MINOR or MAJOR depending on impact).
- The manifest schema changes (MAJOR; coordinate with framework
  maintainers \u2014 may need a `bridge_compat:` field in the manifest).

The framework currently does not enforce `bridge_compat` (D6: atomic
refresh from the bundle); a future version may.

## Step 9: Tier-based model selection (D7)

Your manifest declares a `default_tier` (e.g. `basic`, `normal`,
`flagship`). This is your HINT to vault authors; the framework
resolves it via the vault's `settings.yaml::tiers` block.

```yaml
# in your manifest:
default_tier: normal

# vault author's settings.yaml:
tiers:
  basic: claude-haiku-4.6
  normal: claude-sonnet-4.6    # <-- your extractor uses this
  flagship: claude-opus-4.7
```

Vault authors can override per-stage:

```yaml
stages:
  source_extraction:
    tier: flagship             # override your default_tier
```

In your extractor's prompt, **don't hardcode model names**. The
framework gives you the resolved model via the LLM call surface.

## Reference

| File | What it covers |
|------|----------------|
| [`spec.md`](./spec.md) | High-level architecture |
| [`research.md`](./research.md) | Implementation decisions |
| [`data-model.md`](./data-model.md) | Formal entity definitions |
| [`contracts/manifest.schema.json`](./contracts/manifest.schema.json) | Manifest JSON Schema |
| [`contracts/sources.yaml.contract.md`](./contracts/sources.yaml.contract.md) | Per-module source enumeration |
| [`contracts/signal-payload.schema.json`](./contracts/signal-payload.schema.json) | Output payload JSON Schema |
| [`contracts/extractor-prompt-code.md`](./contracts/extractor-prompt-code.md) | Example of a v1 extractor prompt (code module) |
| [`contracts/module-isolation-protocol.md`](./contracts/module-isolation-protocol.md) | How the framework handles your module's failures |
| [`quickstart-vault-author.md`](./quickstart-vault-author.md) | The vault author's side of the contract |
