"""Reusable collector modules for research vaults.

Each collector:
- Exposes ``collect(vault, *, sources, limit, since, dry_run) -> CollectResult``.
- Declares ``SOURCE_KIND: str`` (e.g. "rss", "youtube", "reddit").
- Writes markdown files with YAML frontmatter to ``<vault>/_pipeline/raw/<kind>/``.
- Required frontmatter keys: source_kind, source_id, collected_at, original_url, content_hash.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CollectResult:
    fetched: int
    skipped_existing: int
    errors: tuple[str, ...]
