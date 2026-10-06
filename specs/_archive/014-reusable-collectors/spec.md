# Feature Specification: Reusable Collector Modules

> **🗄️ SUBSUMED BY ADR-0009 + spec 020 (2026-05-26).** The collector
> module contract this spec proposed is now the 020 manifest contract
> + `tiers:` block + value-tiered consensus + schema-drift fail-closed
> shape. New sources ship as 020 modules under
> `src/research_framework/modules/<name>/` (copied to `<vault>/modules/`
> at install). The partial in-tree implementation (`collectors/rss.py` +
> `_fetch.py` + `_dedupe.py` + `_frontmatter.py` + `_sources.py`) stays
> in place as the legacy raw-capture surface during the revival sprint
> (no deprecation banner per the clarify Q2 decision) and gets retired
> in a batched cleanup once the corresponding 020 modules port.
> Do NOT plan against 014 directly; open
> `docs/adr/0009-collectors-vs-modules-reconciliation.md` and
> `specs/020-code-bridge/spec.md` instead. This file is kept as
> design-history.

**Feature Branch**: `014-reusable-collectors` *(proposal — not branched; subsumed)*
**Created**: 2026-05-13
**Status**: superseded(by ADR-0009, spec 020) — 🗄️ SUBSUMED BY ADR-0009 + spec 020 (2026-05-26)
**Original Input**: User observation while recovering feeds-vault: "this vault has some custom scripts such as `collect_youtube.py`, `collect_oreilly.py`, `collect_rss.py`, `reddit_scraper.py` and `reddit_rss.py`. I think we could/should take these scripts and consider making a spec for smaller reusable modules down the line. I can only assume a reddit scrapper or youtube scrapper might be useful in other vaults."

## Problem

Every vault built on this framework needs to pull external content into
`_pipeline/raw/`. Today each vault carries its own ad-hoc collector
scripts (YouTube, RSS/Atom, Reddit, O'Reilly, …) which:

- Re-implement the same plumbing (URL fetch + retry, YAML source list
  loading, dedupe-by-id, dry-run mode, frontmatter writer, backward-compat
  shadow writes).
- Drift independently — `~/Documents/feeds-vault/scripts/collect_rss.py`
  (962 lines) and a hypothetical equivalent in another vault share maybe
  30-50% of their logic but diverge on conventions, error handling, and
  output schema.
- Don't carry version metadata, so the migrator can't manage them.
- Live as **user files** (under `scripts/`) outside the manifest — every
  vault has to know how to write them from scratch. There's no
  "framework gave you a reddit collector; v2 added a `--since` filter;
  here's how to upgrade" path.

Concrete corpus observed in `~/Documents/feeds-vault/scripts/` (2026-05-13):

| script | lines | function |
|---|---|---|
| `collect_rss.py` | 962 | RSS/Atom poller across sources.yaml entries |
| `verify.py` | 842 | post-collection quality checks |
| `reddit_rss.py` | 697 | Reddit via RSS endpoints |
| `extract.py` | 651 | content extraction from raw HTML/PDF |
| `collect_youtube.py` | 468 | YouTube transcripts via yt-dlp |
| `collect_oreilly.py` | 430 | O'Reilly Learning chapter pull |
| `reddit_scraper.py` | 363 | Reddit via JSON API (fallback) |
| `preprocess.py` | 307 | normalisation + dedupe |
| `archive.py` | 164 | move rejected items to `_pipeline/archive/<month>/` |

~4,300 lines of vault-local code, of which a meaningful fraction is
reusable across any topic-vault. Other vaults built on this framework
would benefit if even half of this lived in a shared, versioned location.

## Goals

1. Define a **collector module contract** so future collectors are
   uniform, swappable, and version-trackable by the migrator.
2. Promote the common plumbing into the framework — vaults import it
   instead of re-implementing it.
3. Make collectors **opt-in per vault** via the spec
   (`sources: [{ name: youtube, collector: youtube, ... }]`), so a vault
   that doesn't want a YouTube collector doesn't get one shipped to it.
4. Keep each collector small enough to read in one sitting (<300 lines
   of vault-specific code on top of the shared plumbing).

## Non-goals

- **Not** a replacement for the existing topic-harvest / scout stage.
  Collectors feed raw content into `_pipeline/raw/`; harvesters consume
  that already-collected content. The two stages remain distinct.
- **Not** a uniform schema for every external service. YouTube's metadata
  shape is irreducibly different from Reddit's; the module contract
  describes the *interface* (inputs, outputs, lifecycle) not the
  per-source data model.
- **Not** a rewrite of the existing vault's scripts during this feature.
  Promotion to the framework is opt-in and gradual; the source vault keeps
  working unchanged.

## User Scenarios

### Story 1 — New vault opts into the YouTube collector (Priority: P1)

A user is building a third research vault. Their spec lists a YouTube
playlist as one of the sources. They expect to write `youtube-playlist.md`
and run `./vault collect youtube` — no plumbing, no 468 lines of script
copy-paste from another vault.

**Acceptance**:
1. The vault spec declares `sources.youtube.playlist_file: youtube-playlist.md`.
2. After `research_vault generate`, the vault has a shared
   `research_vault.collectors.youtube` module available; no `scripts/collect_youtube.py` copy.
3. Running `python -m research_vault.collectors.youtube <vault>` produces
   the same output structure (`_pipeline/raw/youtube/<vid>.md`) the
   current feeds-vault script produces.
4. The collector reads `<vault>/_pipeline/spec-parse.json` to learn its
   per-vault conventions (output dir, frontmatter fields, dedupe key).

### Story 2 — Framework ships an updated Reddit collector (Priority: P2)

The framework releases a new Reddit collector version that adds a
`--since` filter. Existing vaults pick up the change on their next
`./vault update` without editing any script.

**Acceptance**:
1. The collector module is listed in the scaffold manifest with a
   `template_version`.
2. `research_vault migrate apply` upgrades the collector module file in
   place, the user's `sources.yaml` entries continue to work, and the new
   `--since` flag is available immediately.

### Story 3 — Vault contributes a new collector (Priority: P3)

A user has written a `collect_arxiv.py` in their vault. They want to
promote it to the framework so other vaults can opt in.

**Acceptance**:
1. The user follows a documented checklist: refactor against the module
   contract, add a fixture, write a unit test, submit a PR.
2. The CI workflow runs the new collector against its fixture and
   verifies the output schema.
3. Once merged, the collector appears in the manifest and can be opted
   into by any vault's spec.

## The Collector Module Contract (draft)

```python
# research_vault/collectors/<service>.py
"""
Contract:

- Module exposes `collect(vault: Path, *, since: date | None, dry_run: bool) -> CollectResult`.
- Module declares `SOURCE_KIND: str` (e.g. "youtube", "reddit", "rss").
- Module declares `OUTPUT_DIR: str` relative to vault (e.g. "_pipeline/raw/youtube").
- Each emitted file is markdown with YAML frontmatter; required keys:
    source_kind, source_id, collected_at, original_url, content_hash.
- Module's CLI is `python -m research_vault.collectors.<service> <vault>` with
  flags: --dry-run, --since YYYY-MM-DD, --limit N.
- Dedupe is the framework's responsibility, not the collector's:
  collectors emit; framework refuses to overwrite by content_hash.
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class CollectResult:
    fetched: int           # new items written
    skipped_existing: int  # dedupe hits
    errors: tuple[str, ...]
```

Shared plumbing — promoted from the existing scripts and exposed to all
collectors:

| helper | replaces in current scripts |
|---|---|
| `research_vault.collectors._fetch.get(url, *, timeout, retries)` | `fetch_url` in all three of `collect_rss.py`, `reddit_scraper.py`, `collect_youtube.py` |
| `research_vault.collectors._sources.load_yaml(vault)` | `load_sources` in `collect_rss.py`, `load_subreddits_from_yaml` in `reddit_scraper.py` |
| `research_vault.collectors._frontmatter.write(path, fm, body)` | `write_pipeline_file`, `format_pipeline_subreddit` |
| `research_vault.collectors._dedupe.seen(vault, source_kind, source_id)` | `get_existing_video_ids` + scattered `if … in seen` checks |

## Acceptance for the feature itself

- Three collectors ship in the framework: `rss`, `youtube`, `reddit`.
- The feeds-vault and any future vault can opt in via spec; opting out
  means the module is not copied/imported by that vault.
- The collector modules are listed in `scaffold-manifest.json` and
  managed by the migrator.
- Each collector has a fixture-based test in `tests/collectors/`.
- The existing feeds-vault scripts are kept locally until the user
  manually retires them — promotion does not delete vault-local files.

## Open questions

- **Distribution model**: ship collectors as `research_vault.collectors`
  Python modules (preferred) vs. copied scripts in `scripts/`? The
  former is cleaner but breaks the current "all logic in vault" pattern;
  the latter preserves vault portability at the cost of versioning
  complexity.
- **Auth/secrets**: O'Reilly needs an account, Reddit JSON API has rate
  limits, YouTube needs `yt-dlp`. The framework should standardise where
  these credentials live (env vars vs vault-local `secrets.yaml` that
  is gitignored).
- **Schedule integration**: should collectors expose a manifest of
  cron-friendly entry points so `./vault collect --all` can sequence
  them, or stay one-shot?

## Out of scope for v1

- A plugin system for third-party collectors (i.e. anything outside the
  framework repo). The contract should be designed so plugins are
  *possible* in v2 without re-architecting.
- LLM-based collection (e.g. Anthropic-search-tool-driven discovery).
  Collectors here are deterministic data fetchers.

## Pre-work (no commitment yet)

If we decide to pursue this, the smallest first slice is:

1. Pick one collector (`rss` is the most reusable — Reddit and YouTube
   have service-specific quirks) and define the module contract against it.
2. Promote `fetch_url` + `load_yaml` into `research_vault.collectors._fetch`
   and `._sources` shared helpers.
3. Add a single fixture-driven test that exercises both helpers + the rss
   collector end-to-end.
4. Document opt-in in `vault-spec-template.md`.
5. Punt YouTube and Reddit to follow-ups once the contract has survived
   one real consumer.
