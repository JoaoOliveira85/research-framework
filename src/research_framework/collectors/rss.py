"""RSS/Atom feed collector.

Ported from feeds-vault's ``scripts/collect_rss.py`` (962 lines).  Preserves:
- Paywall detection (``_detect_paywall``).
- Date parsing variants (``_parse_date``).
- RSS 2.0 vs Atom routing (``_parse_rss2``, ``_parse_atom``).
- HTML stripping (``_strip_html``).

Shared plumbing:
- ``_fetch.get`` for URL retrieval with retry.
- ``_sources.load_yaml`` for source catalogue.
- ``_frontmatter.write`` for output files.
- ``_dedupe.seen`` / ``_dedupe.content_hash`` for idempotency.

CLI
---
    python -m research_framework.collectors.rss <vault> [options]

Python API
----------
    from research_framework.collectors.rss import collect, CollectResult
"""

from __future__ import annotations

import html
import re
import sys
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import TYPE_CHECKING

from . import CollectResult
from ._dedupe import content_hash, seen
from ._fetch import get as fetch_get
from ._frontmatter import write as frontmatter_write
from ._sources import load_yaml

if TYPE_CHECKING:
    pass

SOURCE_KIND = "rss"
OUTPUT_SUBDIR = "_pipeline/raw/rss"

# A fetched page with less visible text than this is not taken for the article.
_MIN_ARTICLE_CHARS = 200


# ─── Internal data class ──────────────────────────────────────────────────────


@dataclass
class _FeedEntry:
    title: str
    url: str
    guid: str  # stable identifier from the feed (falls back to url)
    author: str
    date: date | None
    summary: str
    content: str  # content:encoded or Atom <content> (may be HTML)


# ─── HTML helpers ─────────────────────────────────────────────────────────────


def _strip_html(content: str) -> str:
    """Strip HTML tags and decode entities to plain text."""
    text = html.unescape(content)
    text = re.sub(
        r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE
    )
    text = re.sub(
        r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE
    )
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]*\n", "\n\n", text)
    lines = [line.strip() for line in text.splitlines()]
    result: list[str] = []
    prev_blank = False
    for line in lines:
        if not line:
            if not prev_blank:
                result.append("")
            prev_blank = True
        else:
            result.append(line)
            prev_blank = False
    return "\n".join(result).strip()


def _detect_paywall(html_content: str, status_code: int) -> bool:
    """Return True if the response looks paywalled."""
    if status_code in (401, 403):
        return True
    markers = [
        r'<meta[^>]+name=["\']paywall["\']',
        r'class=["\'][^"\']*paywall[^"\']*["\']',
        r'class=["\'][^"\']*subscription-required[^"\']*["\']',
        r'id=["\']paywall["\']',
    ]
    for pattern in markers:
        if re.search(pattern, html_content, re.IGNORECASE):
            return True
    return False


# ─── Date parsing ─────────────────────────────────────────────────────────────


def _parse_date(raw: str | None) -> date | None:
    """Parse a date string from RSS/Atom feeds. Returns ``date`` or ``None``."""
    if not raw:
        return None
    raw = raw.strip()

    # ISO 8601 / Atom: 2026-04-07T12:00:00Z or 2026-04-07
    iso_match = re.match(r"(\d{4}-\d{2}-\d{2})", raw)
    if iso_match:
        try:
            return date.fromisoformat(iso_match.group(1))
        except ValueError:
            pass

    # RFC 2822 (RSS pubDate): Mon, 07 Apr 2026 12:00:00 +0000
    try:
        dt = parsedate_to_datetime(raw)
        return dt.date()
    except Exception:
        pass

    return None


# ─── Feed parsers ─────────────────────────────────────────────────────────────


def _parse_rss2(root: ET.Element) -> list[_FeedEntry]:
    """Parse an RSS 2.0 feed; root may be <rss> or a bare <channel>."""
    channel = root.find("channel")
    if channel is None:
        channel = root

    ns_dc = "http://purl.org/dc/elements/1.1/"
    ns_content = "http://purl.org/rss/1.0/modules/content/"

    entries: list[_FeedEntry] = []
    for item in channel.findall("item"):
        try:
            title = (item.findtext("title") or "").strip()
            url = (item.findtext("link") or "").strip()
            guid = (item.findtext("guid") or url).strip()

            author = (
                item.findtext("author")
                or item.findtext(f"{{{ns_dc}}}creator")
                or item.findtext("managingEditor")
                or ""
            ).strip()

            pub_date = _parse_date(item.findtext("pubDate"))
            summary = _strip_html(item.findtext("description") or "")

            content_el = item.find(f"{{{ns_content}}}encoded")
            content = (content_el.text or "") if content_el is not None else ""

            if not url:
                continue

            entries.append(
                _FeedEntry(
                    title=title or url,
                    url=url,
                    guid=guid or url,
                    author=author,
                    date=pub_date,
                    summary=summary,
                    content=content,
                )
            )
        except Exception:
            continue

    return entries


def _parse_atom(root: ET.Element) -> list[_FeedEntry]:
    """Parse an Atom feed; root is <feed> (with or without namespace)."""
    ns = "http://www.w3.org/2005/Atom"

    def _find(el: ET.Element, tag: str) -> ET.Element | None:
        result = el.find(f"{{{ns}}}{tag}")
        if result is None:
            result = el.find(tag)
        return result

    def _findall(el: ET.Element, tag: str) -> list[ET.Element]:
        result = el.findall(f"{{{ns}}}{tag}")
        if not result:
            result = el.findall(tag)
        return result

    def _findtext(el: ET.Element, tag: str) -> str:
        child = _find(el, tag)
        if child is not None and child.text:
            return child.text.strip()
        return ""

    entries: list[_FeedEntry] = []
    for entry in _findall(root, "entry"):
        try:
            title = _findtext(entry, "title")

            url = ""
            for link_el in _findall(entry, "link"):
                href = link_el.get("href", "")
                rel = link_el.get("rel", "alternate")
                if rel in ("alternate", "") and href:
                    url = href
                    break
            if not url:
                url = _findtext(entry, "link")

            guid = _findtext(entry, "id") or url

            author_el = _find(entry, "author")
            author = ""
            if author_el is not None:
                author = _findtext(author_el, "name")

            raw_date = _findtext(entry, "published") or _findtext(entry, "updated")
            pub_date = _parse_date(raw_date)

            summary = _strip_html(_findtext(entry, "summary"))
            content_el = _find(entry, "content")
            content = (content_el.text or "") if content_el is not None else ""

            if not url:
                continue

            entries.append(
                _FeedEntry(
                    title=title or url,
                    url=url,
                    guid=guid or url,
                    author=author,
                    date=pub_date,
                    summary=summary,
                    content=content,
                )
            )
        except Exception:
            continue

    return entries


def _parse_feed(xml_text: str) -> list[_FeedEntry]:
    """Auto-detect RSS 2.0 vs Atom and delegate to the appropriate parser."""
    root = ET.fromstring(xml_text)
    root_tag = root.tag.lower()
    if "}" in root_tag:
        root_tag = root_tag.split("}", 1)[1]

    if root_tag == "rss" or root.find("channel") is not None:
        return _parse_rss2(root)
    if root_tag in ("feed", "rdf"):
        return _parse_atom(root)
    # Unknown root — try RSS first, then Atom
    entries = _parse_rss2(root)
    if not entries:
        entries = _parse_atom(root)
    return entries


# ─── Source ID ────────────────────────────────────────────────────────────────


def _make_source_id(source_name: str, guid: str) -> str:
    """Derive a stable, filesystem-safe source_id from feed name + entry GUID."""
    import hashlib

    name_slug = re.sub(r"[^a-z0-9]+", "-", source_name.lower()).strip("-")[:30]
    guid_hash = hashlib.sha256(guid.encode()).hexdigest()[:12]
    return f"{name_slug}-{guid_hash}"


# ─── Article text ─────────────────────────────────────────────────────────────


def _article_text(entry: _FeedEntry) -> tuple[str, bool]:
    """Return ``(text, is_paywall)``.

    Priority:
    1. content:encoded / Atom <content> if substantial (>500 chars stripped).
    2. Fetch article URL and strip.
    3. Fall back to summary — also when the fetched page is too thin to be
       the article.
    """
    if entry.content:
        stripped = _strip_html(entry.content)
        if len(stripped) > 500:
            return stripped, False

    # The link comes from feed content, so it is untrusted: urlopen would
    # happily read a file:// URL off local disk.
    try:
        scheme = urllib.parse.urlsplit(entry.url).scheme.lower()
    except ValueError:
        # Not a URL at all (urlsplit rejects e.g. an unbalanced "[" in the
        # host). Nothing to fetch — and one bad link must not end the collect.
        scheme = ""
    if scheme not in ("http", "https"):
        return entry.summary or "", False

    try:
        raw_html, status = fetch_get(entry.url, retries=2)
        if _detect_paywall(raw_html, status):
            return "", True
        page_text = _strip_html(raw_html)
        if len(page_text) < _MIN_ARTICLE_CHARS:
            # A thin page (JS shell, consent wall, a short post) is not
            # evidence of a paywall: keep what the feed itself carried.
            return entry.summary or page_text, False
        return page_text, False
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return "", True
        return entry.summary or "", False
    except Exception:
        return entry.summary or "", False


# ─── Public API ───────────────────────────────────────────────────────────────


def collect(
    vault: Path,
    *,
    sources: list[str] | None = None,
    limit: int | None = None,
    since: date | None = None,
    dry_run: bool = False,
) -> CollectResult:
    """Collect RSS/Atom entries into ``<vault>/_pipeline/raw/rss/``.

    Args:
        vault:    Vault root directory.  Must contain ``sources.yaml``.
        sources:  Optional list of source names to process (filters by name).
        limit:    Maximum total items to write across all sources.
        since:    Skip entries older than this date.
        dry_run:  If ``True``, report what would be written without writing.

    Returns:
        ``CollectResult`` with ``fetched``, ``skipped_existing``, ``errors``.
    """
    all_sources = load_yaml(vault)

    if sources:
        names = {s.lower() for s in sources}
        all_sources = [s for s in all_sources if s.name.lower() in names]

    fetched = 0
    skipped = 0
    errors: list[str] = []
    remaining = limit  # None means no limit

    output_dir = vault / OUTPUT_SUBDIR

    for src in all_sources:
        if remaining is not None and remaining <= 0:
            break

        try:
            xml_text, _ = fetch_get(src.feed_url, retries=3)
        except Exception as exc:
            errors.append(f"{src.name}: feed fetch failed — {exc}")
            continue

        try:
            entries = _parse_feed(xml_text)
        except Exception as exc:
            errors.append(f"{src.name}: feed parse failed — {exc}")
            continue

        # Apply per-source feed_limit
        if src.feed_limit is not None:
            entries = entries[: src.feed_limit]

        for entry in entries:
            if remaining is not None and remaining <= 0:
                break

            # --since filter
            if since and entry.date and entry.date < since:
                continue

            source_id = _make_source_id(src.name, entry.guid)

            if seen(vault, SOURCE_KIND, source_id):
                skipped += 1
                continue

            if dry_run:
                # Count as "would fetch" without writing
                fetched += 1
                if remaining is not None:
                    remaining -= 1
                continue

            # Build article text + content_hash
            text, is_paywall = _article_text(entry)
            raw_content = text or entry.summary or ""
            chash = content_hash(raw_content)

            # Frontmatter
            collected_at = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            fm: dict = {
                "source_kind": SOURCE_KIND,
                "source_id": source_id,
                "collected_at": collected_at,
                "original_url": entry.url,
                "content_hash": chash,
            }
            if entry.title:
                fm["title"] = entry.title
            if entry.author:
                fm["author"] = entry.author
            if entry.date:
                fm["date"] = entry.date.isoformat()
            if is_paywall:
                fm["paywall"] = True

            body = (
                raw_content if not is_paywall else "(Paywalled — content not available)"
            )

            dest = output_dir / f"{source_id}.md"
            try:
                frontmatter_write(dest, fm, body)
            except Exception as exc:
                errors.append(f"{src.name}: write failed for {source_id} — {exc}")
                continue

            fetched += 1
            if remaining is not None:
                remaining -= 1

    return CollectResult(
        fetched=fetched,
        skipped_existing=skipped,
        errors=tuple(errors),
    )


# ─── CLI ──────────────────────────────────────────────────────────────────────


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m research_framework.collectors.rss",
        description="RSS/Atom feed collector",
    )
    parser.add_argument("vault", type=Path, help="Vault root directory")
    parser.add_argument(
        "--source",
        action="append",
        dest="sources",
        metavar="NAME",
        help="Only process this named source (repeatable)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum total items to write",
    )
    parser.add_argument(
        "--since",
        metavar="YYYY-MM-DD",
        help="Skip entries older than this date",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be written without writing",
    )
    args = parser.parse_args(argv)

    since_date: date | None = None
    if args.since:
        try:
            since_date = date.fromisoformat(args.since)
        except ValueError:
            print(
                f"[ERROR] --since must be YYYY-MM-DD, got: {args.since}",
                file=sys.stderr,
            )
            return 1

    vault = args.vault.resolve()
    if not vault.is_dir():
        print(f"[ERROR] vault not found: {vault}", file=sys.stderr)
        return 1

    result = collect(
        vault,
        sources=args.sources,
        limit=args.limit,
        since=since_date,
        dry_run=args.dry_run,
    )

    mode = "dry-run" if args.dry_run else "live"
    print(
        f"RSS collector ({mode}): fetched={result.fetched} skipped={result.skipped_existing} errors={len(result.errors)}"
    )
    for err in result.errors:
        print(f"  [ERROR] {err}", file=sys.stderr)

    return 1 if result.errors and result.fetched == 0 else 0


if __name__ == "__main__":
    sys.exit(_main())
