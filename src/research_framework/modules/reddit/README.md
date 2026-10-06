# Reddit source module

Spec 020 source module that extracts subreddit and post signals via
public Reddit RSS/Atom feeds. No API key, no OAuth — stdlib only.
Ships in the framework bundle; installed into `<vault>/modules/reddit/`
by the install wizard or `./vault update`.

## Vault-author setup

1. Add `reddit` to your `settings.yaml::modules:` list.
2. Copy `sources.yaml.template` to `sources.yaml` and edit entries,
   or start from the frozen 13-subreddit AI allowlist in the template.
3. Run a cycle. Signal payloads land in
   `<vault>/_pipeline/sources/reddit/signals/`.

## Triggers

The module declares two `url_pattern` triggers:

- `^https?://(?:www\.)?reddit\.com/r/<sub>/?` (subreddit feeds)
- `^https?://(?:www\.)?reddit\.com/r/<sub>/comments/<id>` (single posts)

A scout-emitted URL matching either pattern routes to this module
automatically. Listing a subreddit in `sources.yaml` ensures it is
polled every cycle.

## Per-source identity

`source_id_from` maps `reddit_subreddits` and `reddit_posts` to the
`url` field — each entry's URL is the `source_id` for caching,
watermarks, and quarantine.

## What v0.1.0 emits

`extractor.py` honours the spec 020 subprocess contract:

- `verdict=ok` when the RSS feed has at least one entry.
- `verdict=empty` when the feed parses but has zero entries.
- `verdict=error` when the URL is not Reddit, the fixture path is
  missing (test override), or fetch/parse fails.

`facts: {}` is intentionally empty — LLM-driven schema extraction
against the vault's `FactsSchema` is a follow-up.

`notable[]` carries post titles, authors, links, and short body
previews parsed from Atom content.

## Source version

`source_version` is `sha256:<16 hex chars>` of the raw RSS XML so
unchanged feeds are cache hits.

## Test overrides (for module authors and CI)

- `REDDIT_RSS_FIXTURE=/path/to/feed.xml` — read Atom XML from this
  file instead of HTTP. Used by `tests/source_bridge/test_reddit_module.py`
  to stay hermetic. If set but the path is not a readable file, the
  extractor returns `verdict=error`.

## Costs

No LLM calls in v0.1.0. Cost surface is RSS bandwidth only. The
framework manages request cadence across sources; the extractor is
one-shot per source.

## Known limitations

- RSS omits score, comment count, and flair (legacy `.json` path
  deliberately not ported — keeps stdlib-only, no auth).
- Rate limits apply to unauthenticated Reddit requests; transient
  failures surface as `verdict=error` (framework retries per D9).
- Sort/time filters only apply when the source URL includes them
  (e.g. `/r/ML/top/.rss?t=week`).

## Spec lineage

- Architecture: `specs/020-code-bridge/spec.md`
- Port template: `specs/020-code-bridge/quickstart-module-author.md`
- Wave-2 issue: #38
- Predecessor (deprecated): `~/Documents/feeds-vault/scripts/reddit_rss.py`
