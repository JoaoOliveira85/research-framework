# O'Reilly source module

Spec 020 source module that searches O'Reilly Learning for paywalled-content
**metadata** (title, authors, description, URL, content type). The platform
body is paywalled; metadata is enough to surface relevant books, courses,
and videos for the research pipeline. Stdlib only (`urllib` + `json`). Ships
in the framework bundle; installed into `<vault>/modules/oreilly/` by the
install wizard or `./vault update`.

## Authentication

**This module requires an API bearer token.**

1. Obtain an O'Reilly Learning API key (content-discovery / MCP access).
2. Export it in the environment **before** running cycles or local tests
   against the live API:
   ```bash
   export OREILLY_API_KEY='your-bearer-token-here'
   ```
3. If `OREILLY_API_KEY` is unset and `OREILLY_API_FIXTURE` is not set, the
   extractor returns `verdict=error` with a clear `notable[]` observation.
   It does **not** crash and never echoes the key value in stdout, stderr,
   or the signal payload.

Never commit the key to `sources.yaml` or vault git — env var only.

## Vault-author setup

1. Add `oreilly` to your `settings.yaml::modules:` list.
2. Copy `sources.yaml.template` to `sources.yaml` and edit entries.
3. Set `OREILLY_API_KEY` in your shell profile or vault launch script.
4. Run a cycle. Signal payloads land in
   `<vault>/_pipeline/sources/oreilly/signals/`.

## Triggers

The module declares a `url_pattern` trigger for:

- `https://learning.oreilly.com/search/…`
- `https://learning.oreilly.com/library/…`
- `https://learning.oreilly.com/api/…`

## Query URL convention (option 3)

Unlike URL-driven modules (`youtube`, `reddit`, `rss`), O'Reilly sources are
**query-driven**. To keep `SignalRequest.source.url` uniform across modules,
each `sources.yaml` entry uses a real browser-pasteable search URL:

```text
https://learning.oreilly.com/search/?q=<url-encoded-query>
```

The extractor parses the `q` parameter and calls the content-discovery API.
Operators can open the same URL in a browser to preview results.

## Per-source identity

`source_id_from` maps `oreilly_queries` to the `url` field — each search
URL is the `source_id` for caching, watermarks, and quarantine.

## What v0.1.0 emits

`extractor.py` honours the spec 020 subprocess contract:

- `verdict=ok` when the API returns at least one hit (up to 20 per query).
- `verdict=empty` when the query succeeds but returns zero hits.
- `verdict=error` when the API key is missing, the URL shape is wrong, the
  fixture path is missing (test override), fetch fails, or JSON is malformed.

`facts: {}` is intentionally empty — LLM-driven schema extraction against
the vault's `FactsSchema` is a follow-up.

`notable[]` carries one observation per hit (e.g. `O'Reilly book: <title> by
<authors>`) plus optional description previews.

## Source version

`source_version` is `sha256:<16 hex chars>` of a hash over **sorted hit URLs**
(stable cache key when the result set is unchanged). If there are no hits,
falls back to a hash of the search query string.

## Test overrides (for module authors and CI)

- `OREILLY_API_FIXTURE=/path/to/response.json` — read JSON from this file
  instead of calling the API. The file may be either:
  - Direct shape: `{"search_results": {"urn:…": {…}, …}}`
  - Full MCP envelope (same as live API response)
  Used by `tests/source_bridge/test_oreilly_module.py` to stay hermetic. If
  set but the path is not a readable file, the extractor returns
  `verdict=error`.

## Costs

No LLM calls in v0.1.0. Cost surface is O'Reilly API usage plus your
subscription. The framework manages request cadence across sources; the
extractor is one-shot per query URL.

## Known limitations

- v0.1.0 does not write `_pipeline/raw/oreilly/` markdown (legacy collector
  file output deliberately not ported).
- Metadata only — no paywalled body text.
- Search URLs only; bare `library/view/…` URLs without a `?q=` query are
  not supported in v0.1.0 (list search URLs in `sources.yaml` instead).
- Per-query cap: 20 hits; no `content_types` / `order_by` filters yet
  (legacy `sources.yaml` fields deferred).

## Spec lineage

- Architecture: `specs/020-code-bridge/spec.md`
- Port template: `specs/020-code-bridge/quickstart-module-author.md`
- Wave-2 issue: #40
- Predecessor (deprecated): `~/Documents/feeds-vault/scripts/collect_oreilly.py`
