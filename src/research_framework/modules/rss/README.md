# RSS source module

Spec 020 source module that extracts generic RSS 2.0 and Atom feed
signals (newsletters, blogs, podcasts, academic preprint feeds). No API
key — stdlib only. Ships in the framework bundle; installed into
`<vault>/modules/rss/` by the install wizard or `./vault update`.

## Vault-author setup

1. Add `rss` to your `settings.yaml::modules:` list.
2. Copy `sources.yaml.template` to `sources.yaml` and edit entries.
3. Run a cycle. Signal payloads land in
   `<vault>/_pipeline/sources/rss/signals/`.

## Triggers

The module declares conservative `url_pattern` triggers:

- URLs ending in `.rss` or `.atom` (optional query string)
- URLs with path segments `/feed`, `/rss`, or `/atom`

A scout-emitted URL matching either pattern routes to this module.
Listing a feed in `sources.yaml` ensures it is polled every cycle even
when the URL shape is ambiguous (per FR-013a).

## Per-source identity

`source_id_from` maps `rss_feeds` to the `url` field — each feed URL is
the `source_id` for caching, watermarks, and quarantine.

## What v0.1.0 emits

`extractor.py` honours the spec 020 subprocess contract:

- `verdict=ok` when the feed has at least one item/entry.
- `verdict=empty` when the feed parses but has zero entries.
- `verdict=error` when the URL is not a recognised feed shape, the
  fixture path is missing (test override), fetch fails, or XML is
  malformed.

`facts: {}` is intentionally empty — LLM-driven schema extraction
against the vault's `FactsSchema` is a follow-up.

`notable[]` carries entry titles, authors, dates, links, and short
body previews parsed from RSS/Atom.

## Source version

`source_version` is `sha256:<16 hex chars>` of a hash over the first five
entry links in feed document order (stable cache key when the feed head
is unchanged; most feeds list newest entries first).
If the feed has no entries, falls back to a hash of the feed URL.

## Test overrides (for module authors and CI)

- `RSS_FIXTURE=/path/to/feed.xml` — read RSS/Atom XML from this file
  instead of HTTP. Used by `tests/source_bridge/test_rss_module.py` to
  stay hermetic. If set but the path is not a readable file, the
  extractor returns `verdict=error`.

## Costs

No LLM calls in v0.1.0. Cost surface is feed bandwidth only. The
framework manages request cadence across sources; the extractor is
one-shot per source.

## Known limitations

- v0.1.0 does not fetch full article HTML (legacy `collect_rss.py`
  article enrichment deliberately not ported).
- Paywall detection and `archive.py` integration are out of scope.
- `.xml` URLs are not auto-triggered (too many false positives); add
  explicit entries in `sources.yaml` instead.
- Entry cap defaults to 50 per feed; body text capped at 2000 chars.
- RSS 1.0 (`rdf:RDF`) is not explicitly supported; unusual roots fall
  through RSS 2.0 then Atom parsers.

## Scope (arxiv subsumption)

**This module subsumes the planned separate `arxiv` port (#41)** for
Wave 2. arXiv category feeds (`https://rss.arxiv.org/rss/cs.*`) are
ordinary RSS documents parsed by the same dual-parser path; manifest
triggers match `*.rss` URLs with no arXiv-specific logic. Vault authors
list academic feeds under `rss_feeds` in `sources.yaml` (see template
entry for `cs.AI`). A dedicated `arxiv` module would only add value if
we later need export API query URLs or non-RSS arXiv surfaces — deferred.

## Spec lineage

- Architecture: `specs/020-code-bridge/spec.md`
- Port template: `specs/020-code-bridge/quickstart-module-author.md`
- Wave-2 issue: #39
- Predecessor (deprecated): `~/Documents/feeds-vault/scripts/collect_rss.py`
