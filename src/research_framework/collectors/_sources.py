"""YAML source-catalogue loader.

Replaces ``load_sources`` / ``load_subreddits_from_yaml`` from feeds-vault scripts.

Supported sources.yaml shapes
------------------------------
Minimal (used in tests):

    sources:
      - name: My Blog
        rss_url: https://example.com/feed.xml

Full (compatible with feeds-vault's sources.yaml):

    newsletters:
      - name: ...
        rss_url: ...
        tier: 1
        tags: [...]
        url: ...
        status: active
    blogs:
      - ...
    podcasts:
      - ...
    academic:
      - name: ...
        api_url: ...

The loader accepts both shapes and normalises them into a flat list of
``SourceEntry`` objects.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


@dataclass
class SourceEntry:
    name: str
    feed_url: str
    section: str = "rss"
    tier: int = 3
    tags: list[str] = field(default_factory=list)
    url: str = ""
    notes: str = ""
    feed_limit: int | None = None
    status: str = "active"


def load_yaml(vault: Path) -> list[SourceEntry]:
    """Load feed sources from ``<vault>/sources.yaml``.

    Returns a list of active ``SourceEntry`` objects (paused entries are
    excluded).  Accepts both the minimal and feeds-vault full formats.
    """
    if yaml is None:
        print(
            "[ERROR] pyyaml not installed — cannot load sources.yaml", file=sys.stderr
        )
        sys.exit(1)

    sources_path = vault / "sources.yaml"
    if not sources_path.exists():
        return []

    with open(sources_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    sources: list[SourceEntry] = []

    # ── Minimal flat format: top-level "sources" list ─────────────────────────
    if "sources" in data and isinstance(data["sources"], list):
        for entry in data["sources"]:
            feed_url = (
                entry.get("rss_url")
                or entry.get("api_url")
                or entry.get("feed_url", "")
            )
            if not feed_url:
                continue
            if entry.get("status", "active") == "paused":
                continue
            sources.append(
                SourceEntry(
                    name=entry.get("name", ""),
                    feed_url=feed_url,
                    section=entry.get("section", "rss"),
                    tier=int(entry.get("tier", 3)),
                    tags=list(entry.get("tags", []) or []),
                    url=entry.get("url", ""),
                    notes=entry.get("notes", ""),
                    feed_limit=entry.get("feed_limit"),
                    status=entry.get("status", "active"),
                )
            )
        return sources

    # ── Full feeds-vault format: sectioned keys ──────────────────────────────────
    # Map yaml key → section label
    section_map = {
        "newsletters": "newsletter",
        "blogs": "blog",
        "podcasts": "podcast",
        "academic": "academic",
    }
    for yaml_key, section_label in section_map.items():
        entries = data.get(yaml_key, []) or []
        for entry in entries:
            if yaml_key in {"newsletters", "blogs", "podcasts"}:
                feed_url = entry.get("rss_url", "")
            else:
                feed_url = entry.get("api_url", "")
            if not feed_url:
                continue
            if entry.get("status", "active") == "paused":
                continue
            sources.append(
                SourceEntry(
                    name=entry.get("name", ""),
                    feed_url=feed_url,
                    section=section_label,
                    tier=int(entry.get("tier", 3)),
                    tags=list(entry.get("tags", []) or []),
                    url=entry.get("url", ""),
                    notes=entry.get("notes", ""),
                    feed_limit=entry.get("feed_limit"),
                    status=entry.get("status", "active"),
                )
            )

    return sources
