# YouTube source module

Spec 020 source module that extracts metadata + (when available)
transcripts from YouTube videos via `yt-dlp`. Ships in the
framework bundle; installed into `<vault>/modules/youtube/` by the
install wizard or `./vault update`.

## Vault-author setup

1. Add `youtube` to your `settings.yaml::modules:` list.
2. Edit `<vault>/modules/youtube/sources.yaml` to list the videos
   (or channels — extraction is per-video) you want extracted:

   ```yaml
   youtube_videos:
     - url: https://www.youtube.com/watch?v=dQw4w9WgXcQ
       label: A talk you care about
       value_tier: routine
   ```

3. Ensure `yt-dlp` is installed and on `$PATH`
   (`pipx install yt-dlp` or `brew install yt-dlp`).
4. Run a cycle. Signal payloads land in
   `<vault>/_pipeline/sources/youtube/signals/`.

## Triggers

The module declares two `url_pattern` triggers:

- `^https?://(?:www\.)?youtube\.com/watch\?v=[A-Za-z0-9_-]+`
- `^https?://youtu\.be/[A-Za-z0-9_-]+`

A scout-emitted URL matching either pattern routes to this module
automatically — no explicit `sources.yaml` entry required for
generic URL discovery (per FR-013a). Listing a video in
`sources.yaml` ensures it's polled every cycle.

## Per-source identity

`source_id_from` maps the `youtube_videos` and `youtube_channels`
keys to the `url` field — so each entry's URL becomes the
`source_id` the framework uses for caching, watermarks, and
quarantine.

## What v0.1.0 emits

`extractor.py` honours the spec 020 subprocess contract and emits
a valid `SignalPayload`:

- `verdict=ok` when a transcript was fetched.
- `verdict=empty` when no transcript is available (e.g. the video
  has neither manual nor auto-generated subtitles).
- `verdict=error` when `yt-dlp` is missing, the URL isn't a
  recognised YouTube URL, or metadata fetch fails.

The `facts: {}` bucket is intentionally empty in v0.1.0 — this
module ships the **envelope + transcript pipeline**, and a
follow-up will plug LLM-driven schema extraction into `facts`
using the vault's per-vault `FactsSchema` (driven by `few-shot.md`).

`notable[]` is populated with the video title, uploader, and
upload date so the framework's downstream stages have human-
readable anchors before LLM extraction lands.

## Source version

`source_version` is a SHA-256 (truncated to 16 hex chars) of the
transcript text — so re-running on a video whose transcript hasn't
changed is a cache hit. If no transcript is available, the version
falls back to `no-transcript:<video_id>` so the cache still keys
per-video.

## Test overrides (for module authors and CI)

- `YT_DLP_BIN=/path/to/stub` — override the `yt-dlp` binary the
  extractor shells out to. Used by `tests/source_bridge/test_youtube_module.py`
  to stay hermetic.
- `YT_SKIP_SUBS=1` — skip subtitle fetching entirely (metadata
  only). Used by tests; harmless in production.

## Costs

This module makes **no LLM calls** in v0.1.0. The cost surface is
purely yt-dlp's network bandwidth + your own time. The follow-up
that adds LLM-driven `facts` extraction will land under the
existing `agent_call.py` dispatch surface and respect the cost
cap (spec 033) like any other stage.

## Known limitations

- yt-dlp is occasionally rate-limited by YouTube; transient
  failures surface as `verdict=error` and the framework retries
  once per spec 020 D9 (retry-once + salvage-and-continue).
- Live streams aren't supported (yt-dlp won't return metadata
  reliably until the stream ends).
- Age-gated and members-only videos require yt-dlp cookie
  configuration — out of scope for v0.1.0. Configure via
  `~/.config/yt-dlp/config` directly.

## Spec lineage

- Architecture: `specs/020-code-bridge/spec.md`
- Port template: `specs/020-code-bridge/quickstart-module-author.md`
- Wave-2 issue: #37
- Predecessor (deprecated): `~/Documents/feeds-vault/scripts/collect_youtube.py`
