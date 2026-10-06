# Contract: Per-Module `sources.yaml`

**Spec**: FR-013a, FR-013b, FR-013c, FR-025 | **Entity**: `ModuleSourcesFile` in [data-model.md](../data-model.md)

## Location

`<vault>/modules/<module-name>/sources.yaml`

One file per installed module, beside `manifest.yaml`. Authoritative
input for **source-extraction enumeration** in 0.3.0. Not a substitute
for `research.spec.md::data_sources` (scout coverage + schema-gen only).

## File format

YAML mapping at the top level. Keys are **module-defined source kinds**
(plural nouns). Values are **lists of instance records** (objects).

```yaml
# Required shape (conceptual JSON Schema)
type: object
additionalProperties:
  type: array
  items:
    type: object
    minProperties: 1
```

### Required per record

Enough identity for the framework to derive a stable `source_id` per
FR-013b. At least one of:

| Field | Type | Use when |
|-------|------|----------|
| `url` | string | HTTP(S) resources, GitHub URLs, YouTube channel URLs |
| `path` | string | Absolute or vault-relative filesystem paths (code repos) |
| `name` | string | Slugs or human identifiers (e.g. subreddit name) |

The module's `manifest.yaml::source_id_from` maps each top-level key
to which field wins. **Default** when a key is omitted from that map:
use `url` if the record has a non-empty `url`, else `name`.

### Optional per record

| Field | Type | Description |
|-------|------|-------------|
| `label` | string | Human label for logs/run-report (not used in `source_id`) |
| `value_tier` | enum | `routine` \| `important` \| `critical` — overrides module default for this instance |
| `*` | any | Module-specific metadata ignored by the framework unless the module reads it in `extractor.py` |

## `source_id_from` on manifest

```yaml
# manifest.yaml (excerpt)
name: youtube
source_id_from:
  youtube_channels: url
  playlists: url

name: code
source_id_from:
  github_repos: path

name: reddit
source_id_from:
  subreddits: name
```

Framework algorithm (per record):

1. `kind` = top-level key in `sources.yaml`
2. `field` = `manifest.source_id_from[kind]` or default (`url` then `name`)
3. `source_id` = `str(record[field]).strip()` — MUST be non-empty
4. Stability: same record content → same `source_id` across runs

## Examples

### YouTube module

```yaml
youtube_channels:
  - url: https://www.youtube.com/@TwoMinutePapers
    label: Two Minute Papers
  - url: https://www.youtube.com/@3blue1brown
```

### Code module

```yaml
github_repos:
  - path: /Users/me/src/my-microservice
    value_tier: important
  - path: /Users/me/src/shared-lib
    value_tier: routine
```

### Reddit module

```yaml
subreddits:
  - name: MachineLearning
  - name: LocalLLaMA
    value_tier: important
```

### Empty / template (bundle seed)

```yaml
# Edit this file to add sources for the <module> module.
# See quickstart-vault-author.md
```

## Framework behaviour

| Condition | Behaviour |
|-----------|-----------|
| File missing | Zero sources for that module; WARN once per pipeline start |
| File empty `{}` | Zero sources; no WARN beyond optional debug |
| Invalid YAML | Module-isolation (D9): skip module for enumeration; run-report entry |
| Record missing identity field | **FAIL fast** per `spec.md` §FR-013b: emit a clear error naming the module, top-level key, and 0-indexed record position; abort the source-extraction stage. No silent skip \u2014 a missing identity field would either produce non-deterministic cache keys or silently drop a source the operator intended to scout. |
| Duplicate `source_id` | WARN; process once (first in file order wins) |

## Relationship to `data_sources`

- **Extraction loop** (Step 1.5): iterates `sources.yaml` records only.
- **Scout / schema-gen**: still consume `research.spec.md::data_sources`.
- **Migration**: authors MAY duplicate entries in both files during
  transition; framework does NOT auto-sync in spec 020.
- **Generic fallback**: `data_sources` entries with no matching module
  trigger and no owning `sources.yaml` row use existing generic handling
  (`module=generic`).

## `./vault update` (FR-025)

- If `<vault>/modules/<name>/sources.yaml` **exists** → MUST NOT overwrite.
- If **absent** → migrator MAY copy `sources.yaml.template` from bundle
  (or equivalent) as `sources.yaml`.
- Does not require `settings.yaml::keep_overrides`.
- Independent of spec 023 `in-loco-modules.json` (`scripts/` lifecycle).

## Legacy migration

Vault-level `<vault>/scripts/sources.yaml` (feeds-vault prior art) is a
**one-time porting input** when landing the first 020-shaped module
(youtube on revival sprint). A porting script splits rows into per-module
`sources.yaml` files; it is not read at runtime after port completes.

## Relationship to `./vault refresh-sources` (spec 023)

**Runtime-decoupled.** `./vault refresh-sources` (spec 023 FR-013, the
Phase 1 revival minimum subset) iterates the legacy vault-local
`<vault>/scripts/collect_*.py` directory + the `reddit_rss.py`
allowlist — it does NOT read this per-module `sources.yaml`. The two
paths coexist during the ADR-0009 transition: legacy collectors feed
vaults whose modules have not yet been ported to 020 extractors;
ported modules expose their sources via this file.

`sources_loader.py` (the 020 consumer of this contract) reads
`<vault>/modules/*/sources.yaml` only — it MUST NOT invoke
`./vault refresh-sources` and MUST NOT walk `<vault>/scripts/`. The
boundary is enforced by `tests/source_bridge/test_cross_spec_boundary.py`
(tasks.md T120).

Per-module legacy collector deletion (removing
`<vault>/scripts/collect_<module>.py` once a module is ported) is a
**manual post-port step** gated on 023 FR-015 — neither spec automates
it. See `docs/adr/0009-collectors-vs-modules-reconciliation.md`.

## Tests (tier-2)

- `test_sources_loader.py`: load, `source_id_from`, missing file, defaults
- Contract fixture: minimal valid YAML per module kind in
  `tests/fixtures/modules/*/sources.yaml`
