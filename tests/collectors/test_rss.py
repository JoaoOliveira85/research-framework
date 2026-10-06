"""Tests for the RSS/Atom collector (014 slice).

All tests are network-free.  ``_fetch.get`` is monkeypatched to return
fixture file contents.
"""

from __future__ import annotations

import subprocess
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from research_framework.collectors.rss import (
    SOURCE_KIND,
    _parse_feed,
    collect,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "collectors"
RSS_XML = FIXTURES / "sample-rss.xml"
ATOM_XML = FIXTURES / "sample-atom.xml"


# ─── Helper ───────────────────────────────────────────────────────────────────


def _make_sources_yaml(vault: Path, feed_path: Path, name: str = "Test Source") -> None:
    """Write a minimal sources.yaml pointing at a local file URL."""
    url = feed_path.as_uri()
    (vault / "sources.yaml").write_text(
        f"sources:\n  - name: {name}\n    rss_url: {url}\n",
        encoding="utf-8",
    )


def _fake_fetch(url: str, *, timeout: int = 30, retries: int = 3) -> tuple[str, int]:
    """Return local fixture file content; simulates a successful HTTP 200."""
    # Convert file:// URL back to path if needed
    if url.startswith("file://"):
        path = Path(url[7:])
    else:
        path = Path(url)
    return path.read_text(encoding="utf-8"), 200


# ─── 1. RSS parse test ────────────────────────────────────────────────────────


def test_rss_parse_item_count() -> None:
    """Parsing the sample RSS fixture should yield exactly 3 items."""
    xml_text = RSS_XML.read_text(encoding="utf-8")
    entries = _parse_feed(xml_text)
    assert len(entries) == 3


def test_rss_parse_fields() -> None:
    """First RSS item should have expected title, URL and author."""
    xml_text = RSS_XML.read_text(encoding="utf-8")
    entries = _parse_feed(xml_text)
    first = entries[0]
    assert first.title == "First Post"
    assert first.url == "https://testblog.example.com/first-post"
    assert first.author == "Alice Author"
    assert first.date is not None
    assert first.date.year == 2026


def test_rss_parse_content_encoded() -> None:
    """Items with <content:encoded> should have their content field populated."""
    xml_text = RSS_XML.read_text(encoding="utf-8")
    entries = _parse_feed(xml_text)
    # First two items have content:encoded
    assert "<p>" in entries[0].content or entries[0].content  # raw HTML present
    # Third item has no content:encoded
    assert entries[2].content == ""


# ─── 2. Atom parse test ───────────────────────────────────────────────────────


def test_atom_parse_item_count() -> None:
    """Parsing the sample Atom fixture should yield exactly 2 items."""
    xml_text = ATOM_XML.read_text(encoding="utf-8")
    entries = _parse_feed(xml_text)
    assert len(entries) == 2


def test_atom_parse_fields() -> None:
    """Atom entries should have title, URL, author and date."""
    xml_text = ATOM_XML.read_text(encoding="utf-8")
    entries = _parse_feed(xml_text)
    first = entries[0]
    assert first.title == "Atom Entry One"
    assert first.url == "https://atomfeed.example.com/entry-one"
    assert first.author == "Carol Contributor"
    assert first.date is not None
    assert first.date.year == 2026


# ─── 3. Dedupe test ───────────────────────────────────────────────────────────


def test_dedupe_second_run_skips(tmp_path: Path) -> None:
    """Running collect() twice should skip already-written items on the second run."""
    _make_sources_yaml(tmp_path, RSS_XML)

    with patch("research_framework.collectors.rss.fetch_get", side_effect=_fake_fetch):
        result1 = collect(tmp_path)

    assert result1.fetched > 0
    assert result1.skipped_existing == 0

    with patch("research_framework.collectors.rss.fetch_get", side_effect=_fake_fetch):
        result2 = collect(tmp_path)

    assert result2.skipped_existing == result1.fetched
    assert result2.fetched == 0

    # No new files written
    raw_dir = tmp_path / "_pipeline" / "raw" / SOURCE_KIND
    file_count_after = len(list(raw_dir.glob("*.md")))
    assert file_count_after == result1.fetched


# ─── 4. Dry-run test ─────────────────────────────────────────────────────────


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    """dry_run=True should report items without writing any files."""
    _make_sources_yaml(tmp_path, RSS_XML)

    with patch("research_framework.collectors.rss.fetch_get", side_effect=_fake_fetch):
        result = collect(tmp_path, dry_run=True)

    assert result.fetched > 0  # items were counted
    raw_dir = tmp_path / "_pipeline" / "raw" / SOURCE_KIND
    assert not raw_dir.exists() or len(list(raw_dir.glob("*.md"))) == 0


# ─── 5. CLI smoke test ───────────────────────────────────────────────────────


def test_cli_exits_zero(tmp_path: Path) -> None:
    """python -m research_framework.collectors.rss <vault> --dry-run should exit 0."""
    _make_sources_yaml(tmp_path, RSS_XML)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "research_framework.collectors.rss",
            str(tmp_path),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        env={
            **__import__("os").environ,
            "PYTHONPATH": str(Path(__file__).parent.parent.parent / "src"),
        },
    )
    # CLI fetches the real feed file URL — no network needed
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "fetched=" in result.stdout


# ─── 6. --since filter ───────────────────────────────────────────────────────


def test_since_filter_excludes_old_entries(tmp_path: Path) -> None:
    """Entries older than --since date should not be counted."""
    _make_sources_yaml(tmp_path, RSS_XML)

    from datetime import date

    # All RSS fixture entries are from May 2026; filter to 2027 → 0 items
    with patch("research_framework.collectors.rss.fetch_get", side_effect=_fake_fetch):
        result = collect(tmp_path, since=date(2027, 1, 1), dry_run=True)

    assert result.fetched == 0


# ─── 7. --limit cap ──────────────────────────────────────────────────────────


def test_limit_caps_items(tmp_path: Path) -> None:
    """--limit N should cap total items written."""
    _make_sources_yaml(tmp_path, RSS_XML)  # 3 items in fixture

    with patch("research_framework.collectors.rss.fetch_get", side_effect=_fake_fetch):
        result = collect(tmp_path, limit=1)

    assert result.fetched == 1
    raw_dir = tmp_path / "_pipeline" / "raw" / SOURCE_KIND
    assert len(list(raw_dir.glob("*.md"))) == 1


# ─── 8. Output file structure ────────────────────────────────────────────────


def test_output_frontmatter_keys(tmp_path: Path) -> None:
    """Written markdown files must contain required frontmatter keys."""
    _make_sources_yaml(tmp_path, RSS_XML)

    with patch("research_framework.collectors.rss.fetch_get", side_effect=_fake_fetch):
        collect(tmp_path, limit=1)

    raw_dir = tmp_path / "_pipeline" / "raw" / SOURCE_KIND
    md_files = list(raw_dir.glob("*.md"))
    assert md_files, "expected at least one .md file"

    content = md_files[0].read_text(encoding="utf-8")
    for key in (
        "source_kind",
        "source_id",
        "collected_at",
        "original_url",
        "content_hash",
    ):
        assert key in content, f"missing frontmatter key: {key}"


# ─── 9. Article links from feed content are http(s) only ──────────────────────


def test_article_fetch_refuses_non_http_link(tmp_path: Path) -> None:
    """A feed item's <link> is untrusted input; ``file://`` must not be read.

    ``urllib.request.urlopen`` opens ``file://`` URLs, so an item whose link
    pointed at a local file had that file's contents written into
    ``_pipeline/raw/rss/`` and passed on to extract.
    """
    from research_framework.collectors.rss import _article_text, _FeedEntry

    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-CONTENTS", encoding="utf-8")
    entry = _FeedEntry(
        title="t",
        url=secret.as_uri(),
        guid="g",
        author="",
        date=None,
        summary="feed summary",
        content="",
    )

    text, paywall = _article_text(entry)

    assert "TOP-SECRET" not in text
    assert (text, paywall) == ("feed summary", False)


def test_article_fetch_does_not_read_a_local_file_long_enough_to_leak(
    tmp_path: Path,
) -> None:
    """The secret in the test above is 19 bytes, and a page under 200 visible
    characters is never taken for the article (it was classified as a paywall;
    it now falls back to the summary) — so its leak assertion holds with or
    without the guard. A file past that threshold is what the guard keeps out
    of ``_pipeline/raw/rss/``."""
    from research_framework.collectors.rss import _article_text, _FeedEntry

    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET line of a local file.\n" * 40, encoding="utf-8")
    entry = _FeedEntry(
        title="t",
        url=secret.as_uri(),
        guid="g",
        author="",
        date=None,
        summary="feed summary",
        content="",
    )

    text, paywall = _article_text(entry)

    assert "TOP-SECRET" not in text
    assert (text, paywall) == ("feed summary", False)


# ─── 10. A link that is not a URL at all ──────────────────────────────────────


def test_a_malformed_article_link_falls_back_to_the_summary() -> None:
    """``urlsplit`` raises ``ValueError`` on an unbalanced IPv6 bracket. The
    scheme check sat outside ``_article_text``'s ``try``, so the error escaped
    instead of taking the summary fallback every other unfetchable link takes."""
    from research_framework.collectors.rss import _article_text, _FeedEntry

    entry = _FeedEntry(
        title="t",
        url="http://[broken",
        guid="g",
        author="",
        date=None,
        summary="feed summary",
        content="",
    )

    assert _article_text(entry) == ("feed summary", False)


def test_one_malformed_link_does_not_abort_the_collect(tmp_path: Path) -> None:
    """Nothing in ``collect`` catches an exception from ``_article_text``: one
    malformed ``<link>`` ended the run, dropping the rest of that feed and
    every feed after it."""
    feed = tmp_path / "feed.xml"
    feed.write_text(
        '<?xml version="1.0"?><rss version="2.0"><channel><title>f</title>'
        "<item><title>one</title><link>https://example.com/one</link>"
        "<guid>1</guid><description>first</description></item>"
        "<item><title>two</title><link>http://[broken</link>"
        "<guid>2</guid><description>second</description></item>"
        "<item><title>three</title><link>https://example.com/three</link>"
        "<guid>3</guid><description>third</description></item>"
        "</channel></rss>",
        encoding="utf-8",
    )
    vault = tmp_path / "vault"
    vault.mkdir()
    _make_sources_yaml(vault, feed)

    with patch("research_framework.collectors.rss.fetch_get", side_effect=_fake_fetch):
        result = collect(vault)

    assert result.fetched == 3
    assert result.errors == ()
    assert len(list((vault / "_pipeline" / "raw" / SOURCE_KIND).glob("*.md"))) == 3


# ─── 11. A short article page is not a paywall ────────────────────────────────

_ONE_ITEM_FEED = (
    '<?xml version="1.0"?><rss version="2.0"><channel><title>f</title>'
    "<item><title>one</title><link>https://example.com/one</link>"
    "<guid>1</guid><description>{summary}</description></item>"
    "</channel></rss>"
)
_SHORT_PAGE = "<html><body><p>Enable JavaScript to read this.</p></body></html>"


def _collect_one_item(tmp_path: Path, summary: str, page: str) -> tuple[object, str]:
    """Run ``collect`` over a one-item feed whose article page is *page*."""
    feed = tmp_path / "feed.xml"
    feed.write_text(_ONE_ITEM_FEED.format(summary=summary), encoding="utf-8")
    vault = tmp_path / "vault"
    vault.mkdir()
    _make_sources_yaml(vault, feed)

    def fetch(url: str, *, timeout: int = 30, retries: int = 3) -> tuple[str, int]:
        if url.startswith("file://"):
            return _fake_fetch(url)
        return page, 200

    with patch("research_framework.collectors.rss.fetch_get", side_effect=fetch):
        result = collect(vault)

    (written,) = (vault / "_pipeline" / "raw" / SOURCE_KIND).glob("*.md")
    return result, written.read_text(encoding="utf-8")


def test_a_short_article_page_keeps_the_feed_summary(tmp_path: Path) -> None:
    """Under 200 visible characters was classified as a paywall: the body became
    the "(Paywalled …)" placeholder, the feed's own summary was thrown away, and
    the written file marked the item seen for good. A thin page (JS shell,
    consent wall, a short post) is no evidence of a paywall."""
    result, text = _collect_one_item(
        tmp_path, "The summary the feed itself carries.", _SHORT_PAGE
    )

    assert result.fetched == 1
    assert "The summary the feed itself carries." in text
    assert "Paywalled" not in text
    assert "paywall: true" not in text


def test_a_short_article_page_without_a_summary_keeps_the_page_text(
    tmp_path: Path,
) -> None:
    """No summary to fall back on: the page's own text is all there is, and it
    is still more than the placeholder."""
    result, text = _collect_one_item(tmp_path, "", _SHORT_PAGE)

    assert result.fetched == 1
    assert "Enable JavaScript to read this." in text
    assert "Paywalled" not in text
    assert "paywall: true" not in text


def test_a_page_with_a_paywall_marker_is_still_a_paywall(tmp_path: Path) -> None:
    """The markers and 401/403 keep their meaning; only page length lost it."""
    page = '<html><body><div class="paywall">Subscribe</div></body></html>'

    _, text = _collect_one_item(tmp_path, "The summary.", page)

    assert "paywall: true" in text
    assert "(Paywalled — content not available)" in text


# ─── 12. A feed names its own encoding in the XML prolog ──────────────────────

_LATIN1_FEED = (
    '<?xml version="1.0" encoding="ISO-8859-1"?>'
    '<rss version="2.0"><channel><title>f</title>'
    "<item><title>Café com informação</title>"
    "<link>https://example.com/one</link><guid>1</guid>"
    "<description>Resumo da edição de março.</description></item>"
    "</channel></rss>"
)


class _FakeResponse:
    """What ``urlopen`` returns, as far as ``_fetch.get`` looks at it."""

    status = 200

    def __init__(self, raw: bytes, content_type: str) -> None:
        import email.message

        self._raw = raw
        self.headers = email.message.Message()
        self.headers["Content-Type"] = content_type

    def read(self, *args: int) -> bytes:
        return self._raw

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def _get_with_response(raw: bytes, content_type: str) -> str:
    from research_framework.collectors import _fetch

    with patch.object(
        _fetch.urllib.request,
        "urlopen",
        return_value=_FakeResponse(raw, content_type),
    ):
        text, _ = _fetch.get("https://example.com/feed.xml")
    return text


def test_a_latin1_feed_is_collected_without_mojibake(tmp_path: Path) -> None:
    """The feed was decoded from the HTTP header's charset alone, UTF-8 with
    replacement when the header named none — before the XML parser, which
    would have honoured the prolog, ever saw the bytes. A Latin-1 feed served
    without a charset came out with U+FFFD for every accented letter."""
    import urllib.error

    from research_framework.collectors import _fetch

    feed = tmp_path / "feed.xml"
    feed.write_bytes(_LATIN1_FEED.encode("latin-1"))
    vault = tmp_path / "vault"
    vault.mkdir()
    _make_sources_yaml(vault, feed)
    real_get = _fetch.get

    def fetch(url: str, *, timeout: int = 30, retries: int = 3) -> tuple[str, int]:
        if url.startswith("file://"):  # the real fetch + decode, off local disk
            return real_get(url, timeout=timeout, retries=retries)
        raise urllib.error.URLError("no network in tests")

    with patch("research_framework.collectors.rss.fetch_get", side_effect=fetch):
        result = collect(vault)

    assert result.errors == ()
    (written,) = (vault / "_pipeline" / "raw" / SOURCE_KIND).glob("*.md")
    text = written.read_text(encoding="utf-8")
    assert "Café com informação" in text
    assert "Resumo da edição de março." in text
    assert "�" not in text


def test_fetch_falls_back_to_the_prolog_when_the_header_charset_is_wrong() -> None:
    """A server that announces UTF-8 for a Latin-1 document: the header's
    charset cannot decode the body, the document's own declaration can."""
    text = _get_with_response(
        _LATIN1_FEED.encode("latin-1"), "application/rss+xml; charset=utf-8"
    )

    assert "Café com informação" in text
    assert "�" not in text


def test_fetch_still_prefers_a_header_charset_that_decodes() -> None:
    """The HTTP charset outranks the prolog (RFC 7303): a document transcoded
    to UTF-8 in transit keeps a stale ``encoding="ISO-8859-1"``."""
    text = _get_with_response(
        _LATIN1_FEED.encode("utf-8"), "application/rss+xml; charset=utf-8"
    )

    assert "Café com informação" in text


class _SizedResponse(_FakeResponse):
    """A response that hands out at most the bytes a ``read(n)`` asks for."""

    def read(self, *args: int) -> bytes:
        return self._raw[: args[0]] if args else self._raw


def test_fetch_fails_a_body_over_the_size_cap_without_retrying() -> None:
    """``resp.read()`` had no limit: a misbehaving server could stream a body
    into memory without end. A body over the cap is a failed fetch, and is not
    retried (it would only be read again); one at the cap is returned."""
    from research_framework.collectors import _fetch

    urlopen = MagicMock(return_value=_SizedResponse(b"x" * 1025, "application/rss+xml"))
    with (
        patch.object(_fetch, "_MAX_BODY_BYTES", 1024, create=True),
        patch.object(_fetch.urllib.request, "urlopen", urlopen),
    ):
        with pytest.raises(urllib.error.URLError, match="1024 bytes"):
            _fetch.get("https://example.com/feed.xml", retries=3)
        assert urlopen.call_count == 1

        urlopen.return_value = _SizedResponse(b"x" * 1024, "application/rss+xml")
        text, _ = _fetch.get("https://example.com/feed.xml")

    assert text == "x" * 1024


def test_fetch_ignores_a_prolog_encoding_the_bytes_are_not_in() -> None:
    """``encoding="utf-16"`` on a UTF-8 document (a serializer that wrote the
    declaration for an in-memory string) must not be believed: decoding the
    bytes as UTF-16 "succeeds" and yields garbage."""
    raw = _LATIN1_FEED.replace("ISO-8859-1", "utf-16").encode("utf-8")
    raw += b"\n" * (len(raw) % 2)  # an odd length is a UTF-16 decode error
    assert "Café" not in raw.decode("utf-16")  # the garbage, without an error

    text = _get_with_response(raw, "application/rss+xml")

    assert "Café com informação" in text
