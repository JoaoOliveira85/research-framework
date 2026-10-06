#!/usr/bin/env python3
"""Reddit module extractor — stdin/stdout JSON contract (spec 020).

Lifecycle:
1. Read JSON request from stdin.
2. Resolve a subreddit feed or single-post RSS URL from ``source.url``.
3. Fetch Atom XML (network, or ``REDDIT_RSS_FIXTURE`` for hermetic tests).
4. Parse entries and emit a ``SignalPayload`` on stdout.

Handles ONE subreddit OR ONE post per invocation — the framework drives
the loop across ``sources.yaml`` entries.

Error policy (D9, spec 020):
- Missing ``REDDIT_RSS_FIXTURE`` file when override is set → ``verdict=error``.
- Missing / non-Reddit ``source.url`` → ``verdict=error``.
- Network / parse failure → ``verdict=error``.
- Feed with zero entries → ``verdict=empty``.

``facts`` is intentionally empty in v0.1.0 (mirrors ``youtube``).
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

BRIDGE_VERSION = "0.0.0"
USER_AGENT = "research-framework-reddit/0.1.0 (educational; no auth)"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
MAX_NOTABLE_POSTS = 25

_POST_RX = re.compile(
    r"^https?://(?:www\.)?reddit\.com/r/([A-Za-z0-9_]+)/comments/([A-Za-z0-9]+)"
)
_SUBREDDIT_RX = re.compile(r"^https?://(?:www\.)?reddit\.com/r/([A-Za-z0-9_]+)")


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_stdin() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _parse_reddit_url(url: str) -> dict[str, str] | None:
    """Return ``{kind, subreddit, post_id?}`` or None if not Reddit."""
    post_match = _POST_RX.match(url)
    if post_match:
        return {
            "kind": "post",
            "subreddit": post_match.group(1),
            "post_id": post_match.group(2),
        }
    sub_match = _SUBREDDIT_RX.match(url)
    if sub_match:
        return {"kind": "subreddit", "subreddit": sub_match.group(1)}
    return None


def _rss_url_for_source(url: str, parsed: dict[str, str]) -> str:
    """Build the RSS URL to fetch for this source (preserves query string)."""
    parsed_url = urlparse(url)
    query = f"?{parsed_url.query}" if parsed_url.query else ""

    if url.rstrip("/").endswith(".rss"):
        return f"{url.split('?')[0]}{query}"
    if parsed["kind"] == "post":
        base = url.split("?")[0].rstrip("/")
        return f"{base}.rss{query}"
    # Subreddit: preserve sort path if present (e.g. /top/.rss)
    path = parsed_url.path.rstrip("/")
    if path.endswith(".rss"):
        return f"https://www.reddit.com{path}{query}"
    if re.search(r"/r/[^/]+/(top|hot|new|rising|controversial)", path, re.I):
        return f"https://www.reddit.com{path}.rss{query}"
    return f"https://www.reddit.com/r/{parsed['subreddit']}/.rss{query}"


def _fetch_rss_xml(rss_url: str) -> str | None:
    """Return raw Atom XML or None on failure."""
    fixture = os.environ.get("REDDIT_RSS_FIXTURE", "").strip()
    if fixture:
        path = Path(fixture)
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8", errors="replace")

    req = urllib.request.Request(rss_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def _plain_from_html(content_html: str) -> str:
    plain = re.sub(r"<[^>]+>", " ", html.unescape(content_html))
    plain = re.sub(r"\s+", " ", plain).strip()
    if len(plain) > 500:
        return plain[:500] + "..."
    return plain


def _parse_rss_entries(xml_text: str) -> list[dict[str, str]] | None:
    """Parse Atom entries — distilled from legacy ``fetch_rss``.

    Returns:
        * ``None`` on malformed XML (caller should emit ``verdict=error``).
        * ``[]`` on well-formed XML with no ``<atom:entry>`` elements (caller
          should emit ``verdict=empty``).
        * non-empty list on the happy path.

    Mirrors the contract of the sibling ``rss`` module's
    ``_parse_feed_entries`` so the two stdlib-only RSS extractors stay
    consistent in their error policy (spec-020 D9 — extractor never
    swallows parse errors as empty results).
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    posts: list[dict[str, str]] = []
    for entry in root.findall("atom:entry", ATOM_NS):
        title = entry.findtext("atom:title", "", ATOM_NS) or ""
        link_el = entry.find("atom:link", ATOM_NS)
        link = link_el.get("href", "") if link_el is not None else ""
        author_el = entry.find("atom:author/atom:name", ATOM_NS)
        author = (author_el.text if author_el is not None else None) or "[unknown]"
        if author.startswith("/u/"):
            author = author[3:]
        updated = entry.findtext("atom:updated", "", ATOM_NS) or ""
        content_html = entry.findtext("atom:content", "", ATOM_NS) or ""
        body = _plain_from_html(content_html) if content_html else ""
        posts.append(
            {
                "title": title,
                "link": link,
                "author": author,
                "updated": updated,
                "body": body,
            }
        )
    return posts


def _source_version_from_xml(xml_text: str) -> str:
    digest = hashlib.sha256(xml_text.encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"


def _error_payload(source_id: str, reason: str) -> dict[str, Any]:
    return {
        "module": "reddit",
        "source_id": source_id or "unknown",
        "source_version": "unknown",
        "bridge_version": BRIDGE_VERSION,
        "extracted_at": _utc_now_iso(),
        "verdict": "error",
        "truncated": False,
        "partial": False,
        "facts": {},
        "notable": [
            {
                "observation": reason,
                "confidence": "high",
                "evidence_ref": "extractor:precondition",
            }
        ],
    }


def _notable_from_posts(
    posts: list[dict[str, str]], subreddit: str
) -> list[dict[str, Any]]:
    notable: list[dict[str, Any]] = []
    for i, post in enumerate(posts[:MAX_NOTABLE_POSTS], start=1):
        title = post.get("title") or "(untitled)"
        author = post.get("author") or "unknown"
        link = post.get("link") or ""
        obs = f"r/{subreddit} post #{i}: {title} (u/{author})"
        if link:
            obs += f" — {link}"
        notable.append(
            {
                "observation": obs,
                "confidence": "high",
                "evidence_ref": link or f"reddit:r/{subreddit}",
            }
        )
        body = post.get("body") or ""
        if body:
            notable.append(
                {
                    "observation": f"Preview: {body[:200]}{'...' if len(body) > 200 else ''}",
                    "confidence": "medium",
                    "evidence_ref": link or f"reddit:r/{subreddit}",
                }
            )
    return notable


def cmd_get_source_version(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("source") or {}
    url = str(source.get("url", ""))
    parsed = _parse_reddit_url(url) if url else None
    if not parsed:
        return {"source_version": "unknown"}

    rss_url = _rss_url_for_source(url, parsed)
    xml_text = _fetch_rss_xml(rss_url)
    if xml_text is None:
        return {"source_version": "unknown"}
    return {"source_version": _source_version_from_xml(xml_text)}


def cmd_extract(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("source") or {}
    source_id = str(payload.get("source_id") or source.get("url") or "")
    url = str(source.get("url", ""))

    if not url:
        return _error_payload(source_id, "no source.url provided")

    parsed = _parse_reddit_url(url)
    if not parsed:
        return _error_payload(source_id, "url is not a recognised Reddit URL")

    rss_url = _rss_url_for_source(url, parsed)
    xml_text = _fetch_rss_xml(rss_url)
    if xml_text is None:
        reason = "RSS fetch failed"
        if os.environ.get("REDDIT_RSS_FIXTURE", "").strip():
            reason = "REDDIT_RSS_FIXTURE path missing or unreadable"
        return _error_payload(source_id, reason)

    posts = _parse_rss_entries(xml_text)
    if posts is None:
        return _error_payload(source_id, "malformed Reddit feed XML")

    subreddit = parsed["subreddit"]
    source_version = _source_version_from_xml(xml_text)

    if not posts:
        return {
            "module": "reddit",
            "source_id": source_id,
            "source_version": source_version,
            "bridge_version": BRIDGE_VERSION,
            "extracted_at": _utc_now_iso(),
            "verdict": "empty",
            "truncated": False,
            "partial": False,
            "facts": {},
            "notable": [],
        }

    notable = _notable_from_posts(posts, subreddit)
    truncated = len(posts) > MAX_NOTABLE_POSTS

    return {
        "module": "reddit",
        "source_id": source_id,
        "source_version": source_version,
        "bridge_version": BRIDGE_VERSION,
        "extracted_at": _utc_now_iso(),
        "verdict": "ok",
        "truncated": truncated,
        "partial": False,
        "facts": {},
        "notable": notable,
    }


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "extract"
    payload = _read_stdin()
    if command == "get_source_version":
        out = cmd_get_source_version(payload)
    else:
        out = cmd_extract(payload)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
