#!/usr/bin/env python3
"""RSS module extractor — stdin/stdout JSON contract (spec 020).

Lifecycle:
1. Read JSON request from stdin.
2. Resolve a feed URL from ``source.url``.
3. Fetch RSS/Atom XML (network, or ``RSS_FIXTURE`` for hermetic tests).
4. Parse entries (RSS 2.0 or Atom) and emit a ``SignalPayload`` on stdout.

Handles ONE feed URL per invocation — the framework drives the loop across
``sources.yaml`` entries.

Error policy (D9, spec 020):
- Missing ``RSS_FIXTURE`` file when override is set → ``verdict=error``.
- Missing / non-feed ``source.url`` → ``verdict=error``.
- Malformed XML → ``verdict=error``.
- Feed with zero items/entries → ``verdict=empty``.

``facts`` is intentionally empty in v0.1.0 (mirrors ``youtube`` / ``reddit``).
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
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

BRIDGE_VERSION = "0.0.0"
USER_AGENT = "research-framework-rss/0.1.0 (educational; no auth)"
ATOM_NS = "http://www.w3.org/2005/Atom"
NS_DC = "http://purl.org/dc/elements/1.1/"
NS_CONTENT = "http://purl.org/rss/1.0/modules/content/"

MAX_BODY_CHARS = 2000
# Notable[] cap, enforced inside _notable_from_entries. Truncation is reported
# via `truncated=True` whenever the parsed feed had MORE than this many entries
# (see cmd_extract). The parse step no longer pre-slices, so the boundary case
# (feed has exactly MAX_NOTABLE_ENTRIES entries) correctly reports
# `truncated=False`.
MAX_NOTABLE_ENTRIES = 50
SOURCE_VERSION_ENTRY_COUNT = 5

_FEED_URL_PATTERNS = (
    re.compile(r"^https?://.+\.(?:rss|atom)(?:\?.*)?$", re.IGNORECASE),
    re.compile(r"^https?://.*/(?:feed|rss|atom)(?:/.*)?(?:\?.*)?$", re.IGNORECASE),
)


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


def _looks_like_feed_url(url: str) -> bool:
    return any(rx.search(url) for rx in _FEED_URL_PATTERNS)


# ``<?xml version="1.0" encoding="ISO-8859-1"?>`` — a feed names its own
# encoding at its very start.
_XML_PROLOG = "<?xml"
_XML_PROLOG_ENCODING = re.compile(
    rb"""<\?xml[^>]*?\sencoding\s*=\s*["']([A-Za-z][A-Za-z0-9._-]*)["']"""
)


def _decode_feed(raw: bytes, header_charset: str | None) -> str:
    """Decode a feed body to text for the XML parse.

    The HTTP charset comes first, then the encoding the XML prolog declares,
    then UTF-8; the first that decodes wins. ElementTree ignores the prolog of
    a document handed to it as ``str``, so a feed decoded wrongly here stays
    wrong. The rule is ``collectors/_fetch.py``'s, which a module (standard
    library only) cannot import.
    """
    if header_charset:
        try:
            return raw.decode(header_charset)
        except (UnicodeDecodeError, LookupError):
            pass
    declared = _XML_PROLOG_ENCODING.match(raw[:256])
    if declared:
        try:
            text = raw.decode(declared.group(1).decode("ascii"))
        except (UnicodeDecodeError, LookupError):
            text = ""
        # The prolog was readable as ASCII, so the real encoding keeps ASCII
        # as it is: a declaration that does not (``utf-16`` written by a
        # serializer onto UTF-8 bytes) is not the encoding of these bytes.
        if text.startswith(_XML_PROLOG):
            return text
    return raw.decode("utf-8", errors="replace")


def _fetch_feed_xml(feed_url: str) -> str | None:
    """Return raw RSS/Atom XML or None on failure."""
    fixture = os.environ.get("RSS_FIXTURE", "").strip()
    if fixture:
        path = Path(fixture)
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8", errors="replace")

    req = urllib.request.Request(feed_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return _decode_feed(resp.read(), resp.headers.get_content_charset())
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def _strip_html(content: str) -> str:
    text = html.unescape(content)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_BODY_CHARS:
        return text[:MAX_BODY_CHARS] + "..."
    return text


def _parse_date(raw: str) -> str:
    """Return ISO date string (YYYY-MM-DD) or empty."""
    if not raw:
        return ""
    raw = raw.strip()
    iso_match = re.match(r"(\d{4}-\d{2}-\d{2})", raw)
    if iso_match:
        return iso_match.group(1)
    try:
        dt = parsedate_to_datetime(raw)
        return dt.date().isoformat()
    except (TypeError, ValueError, OverflowError):
        return ""


def _parse_rss2(root: ET.Element) -> list[dict[str, str]]:
    channel = root.find("channel")
    if channel is None:
        channel = root

    entries: list[dict[str, str]] = []
    for item in channel.findall("item"):
        try:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            author = (
                item.findtext("author")
                or item.findtext(f"{{{NS_DC}}}creator")
                or item.findtext("managingEditor")
                or ""
            ).strip()
            pub_date = _parse_date(item.findtext("pubDate") or "")
            summary = _strip_html(item.findtext("description") or "")
            content_el = item.find(f"{{{NS_CONTENT}}}encoded")
            body = ""
            if content_el is not None and content_el.text:
                body = _strip_html(content_el.text)
            elif summary:
                body = summary
            if not link:
                continue
            entries.append(
                {
                    "title": title or link,
                    "link": link,
                    "author": author,
                    "date": pub_date,
                    "body": body,
                }
            )
        except (AttributeError, TypeError):
            continue
    return entries


def _parse_atom(root: ET.Element) -> list[dict[str, str]]:
    def find(el: ET.Element, tag: str) -> ET.Element | None:
        result = el.find(f"{{{ATOM_NS}}}{tag}")
        if result is None:
            result = el.find(tag)
        return result

    def findall(el: ET.Element, tag: str) -> list[ET.Element]:
        result = el.findall(f"{{{ATOM_NS}}}{tag}")
        if not result:
            result = el.findall(tag)
        return result

    def findtext(el: ET.Element, tag: str) -> str:
        child = find(el, tag)
        if child is not None and child.text:
            return child.text.strip()
        return ""

    entries: list[dict[str, str]] = []
    for entry in findall(root, "entry"):
        try:
            title = findtext(entry, "title")
            link = ""
            for link_el in findall(entry, "link"):
                href = link_el.get("href", "")
                rel = link_el.get("rel", "alternate")
                if rel in ("alternate", "") and href:
                    link = href
                    break
            if not link:
                link = findtext(entry, "link")
            author_el = find(entry, "author")
            author = findtext(author_el, "name") if author_el is not None else ""
            raw_date = findtext(entry, "published") or findtext(entry, "updated")
            pub_date = _parse_date(raw_date)
            summary = _strip_html(findtext(entry, "summary"))
            content_el = find(entry, "content")
            body = ""
            if content_el is not None and content_el.text:
                body = _strip_html(content_el.text)
            elif summary:
                body = summary
            if not link:
                continue
            entries.append(
                {
                    "title": title or link,
                    "link": link,
                    "author": author,
                    "date": pub_date,
                    "body": body,
                }
            )
        except (AttributeError, TypeError):
            continue
    return entries


def _parse_feed_entries(xml_text: str) -> list[dict[str, str]] | None:
    """Parse feed XML. Returns None on malformed XML."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    root_tag = root.tag.lower()
    if "}" in root_tag:
        root_tag = root_tag.split("}", 1)[1]

    if root_tag == "rss" or root.find("channel") is not None:
        return _parse_rss2(root)
    if root_tag == "feed":
        return _parse_atom(root)

    # RSS 1.0 (`rdf:RDF`) and unusual roots: try RSS 2.0 first, then Atom.
    entries = _parse_rss2(root)
    if entries:
        return entries
    return _parse_atom(root)


def _source_version_from_entries(entries: list[dict[str, str]], feed_url: str) -> str:
    if not entries:
        digest = hashlib.sha256(feed_url.encode("utf-8")).hexdigest()[:16]
        return f"sha256:{digest}"

    keys = [
        e.get("link") or e.get("title") or ""
        for e in entries[:SOURCE_VERSION_ENTRY_COUNT]
    ]
    keys = [k for k in keys if k]
    if not keys:
        digest = hashlib.sha256(feed_url.encode("utf-8")).hexdigest()[:16]
        return f"sha256:{digest}"
    joined = "|".join(keys)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"


def _error_payload(source_id: str, reason: str) -> dict[str, Any]:
    return {
        "module": "rss",
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


def _notable_from_entries(entries: list[dict[str, str]]) -> list[dict[str, Any]]:
    notable: list[dict[str, Any]] = []
    for i, entry in enumerate(entries[:MAX_NOTABLE_ENTRIES], start=1):
        title = entry.get("title") or "(untitled)"
        author = entry.get("author") or "unknown"
        link = entry.get("link") or ""
        date_str = entry.get("date") or ""
        obs = f"Entry #{i}: {title}"
        if author and author != "unknown":
            obs += f" ({author})"
        if date_str:
            obs += f" — {date_str}"
        if link:
            obs += f" — {link}"
        notable.append(
            {
                "observation": obs,
                "confidence": "high",
                "evidence_ref": link or "rss:feed-entry",
            }
        )
        body = entry.get("body") or ""
        if body:
            preview = body[:200] + ("..." if len(body) > 200 else "")
            notable.append(
                {
                    "observation": f"Preview: {preview}",
                    "confidence": "medium",
                    "evidence_ref": link or "rss:feed-entry",
                }
            )
    return notable


def cmd_get_source_version(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("source") or {}
    url = str(source.get("url", ""))
    if not url or not _looks_like_feed_url(url):
        return {"source_version": "unknown"}

    xml_text = _fetch_feed_xml(url)
    if xml_text is None:
        return {"source_version": "unknown"}

    entries = _parse_feed_entries(xml_text)
    if entries is None:
        return {"source_version": "unknown"}
    return {"source_version": _source_version_from_entries(entries, url)}


def cmd_extract(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("source") or {}
    source_id = str(payload.get("source_id") or source.get("url") or "")
    url = str(source.get("url", ""))

    if not url:
        return _error_payload(source_id, "no source.url provided")

    if not _looks_like_feed_url(url):
        return _error_payload(source_id, "url does not match a common feed shape")

    xml_text = _fetch_feed_xml(url)
    if xml_text is None:
        reason = "feed fetch failed"
        if os.environ.get("RSS_FIXTURE", "").strip():
            reason = "RSS_FIXTURE path missing or unreadable"
        return _error_payload(source_id, reason)

    entries = _parse_feed_entries(xml_text)
    if entries is None:
        return _error_payload(source_id, "malformed feed XML")

    source_version = _source_version_from_entries(entries, url)

    if not entries:
        return {
            "module": "rss",
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

    notable = _notable_from_entries(entries)
    truncated = len(entries) > MAX_NOTABLE_ENTRIES

    return {
        "module": "rss",
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
