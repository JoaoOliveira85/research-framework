"""RSS module contract tests (Wave 2 / spec 020).

These tests cover the SHIPPED module assets at
``src/research_framework/modules/rss/`` — they assert:

1. Manifest parses, validates against the schema, and declares
   the expected url_pattern triggers + ``source_id_from`` mapping.
2. The extractor honours the spec-020 stdin/stdout JSON contract
   for both the ``extract`` and ``get_source_version`` commands.
3. Network calls are isolated via ``RSS_FIXTURE`` so tests
   stay hermetic — no real network.
4. The emitted ``SignalPayload`` validates against
   ``signal-payload.schema.json`` for the happy path.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from research_framework.pipeline.source_bridge.discovery import parse_manifest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = REPO_ROOT / "src" / "research_framework" / "modules" / "rss"

POPULATED_RSS20 = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Import AI weekly roundup</title>
      <link>https://importai.substack.com/p/test-article</link>
      <author>Jack Clark</author>
      <pubDate>Mon, 27 May 2026 12:00:00 +0000</pubDate>
      <description>Summary of AI research this week.</description>
    </item>
  </channel>
</rss>
"""

POPULATED_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Atom blog post</title>
    <link href="https://simonwillison.net/2026/May/27/test/" rel="alternate"/>
    <author><name>Simon Willison</name></author>
    <updated>2026-05-27T12:00:00Z</updated>
    <summary>Practical LLM engineering notes.</summary>
  </entry>
</feed>
"""

EMPTY_RSS20 = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel></channel>
</rss>
"""

MALFORMED_XML = "not valid xml <<<"


def _module_path(name: str) -> Path:
    return MODULE_DIR / name


def _run_extractor(
    command: str,
    payload: dict,
    *,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(_module_path("extractor.py")), command],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
        check=False,
    )


# ---------------------------------------------------------------------------
# Manifest contract
# ---------------------------------------------------------------------------


def test_manifest_yaml_loads_and_declares_rss_identity() -> None:
    raw = yaml.safe_load(_module_path("manifest.yaml").read_text(encoding="utf-8"))
    assert raw["name"] == "rss"
    assert raw["entry_point"] == "extractor.py"
    assert raw["schema_examples"] == "few-shot.md"
    assert raw["default_value_tier"] in {"routine", "important", "critical"}


def test_manifest_validates_via_discovery_parser() -> None:
    manifest = parse_manifest(_module_path("manifest.yaml"))
    assert manifest.name == "rss"
    assert manifest.entry_point == "extractor.py"


def test_manifest_url_triggers_match_feed_urls() -> None:
    import re

    raw = yaml.safe_load(_module_path("manifest.yaml").read_text(encoding="utf-8"))
    url_patterns = [t["pattern"] for t in raw["triggers"] if t["type"] == "url_pattern"]
    assert len(url_patterns) >= 2
    combined = "|".join(f"(?:{p})" for p in url_patterns)
    rx = re.compile(combined)
    assert rx.search("https://importai.substack.com/feed")
    assert rx.search("https://rss.arxiv.org/rss/cs.AI")
    assert rx.search("https://simonwillison.net/atom/everything/")
    assert not rx.search("https://example.com/blog/post-123")


def test_manifest_source_id_from_maps_feed_url() -> None:
    raw = yaml.safe_load(_module_path("manifest.yaml").read_text(encoding="utf-8"))
    assert "source_id_from" in raw
    assert raw["source_id_from"]["rss_feeds"] == "url"


# ---------------------------------------------------------------------------
# Asset contracts (sources.yaml.template + few-shot.md)
# ---------------------------------------------------------------------------


def test_sources_yaml_template_ships_with_module() -> None:
    template = _module_path("sources.yaml.template")
    assert template.exists()
    raw = yaml.safe_load(template.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    feeds = raw.get("rss_feeds", [])
    assert 4 <= len(feeds) <= 8
    urls = [e["url"] for e in feeds]
    assert "https://importai.substack.com/feed" in urls
    assert "https://rss.arxiv.org/rss/cs.AI" in urls
    assert any("/atom/" in u for u in urls)


def test_few_shot_md_exists_and_has_examples() -> None:
    few_shot = _module_path("few-shot.md")
    assert few_shot.exists()
    body = few_shot.read_text(encoding="utf-8")
    assert body.count("```") >= 2


def test_module_ships_readme() -> None:
    assert _module_path("README.md").exists()


# ---------------------------------------------------------------------------
# Extractor stdin/stdout contract
# ---------------------------------------------------------------------------


@pytest.fixture
def rss_fixture_rss20(tmp_path: Path) -> Path:
    path = tmp_path / "rss20-populated.xml"
    path.write_text(POPULATED_RSS20, encoding="utf-8")
    return path


@pytest.fixture
def rss_fixture_atom(tmp_path: Path) -> Path:
    path = tmp_path / "atom-populated.xml"
    path.write_text(POPULATED_ATOM, encoding="utf-8")
    return path


@pytest.fixture
def rss_fixture_empty(tmp_path: Path) -> Path:
    path = tmp_path / "rss20-empty.xml"
    path.write_text(EMPTY_RSS20, encoding="utf-8")
    return path


def test_extractor_extract_emits_valid_signal_payload_rss20(
    rss_fixture_rss20: Path,
) -> None:
    url = "https://importai.substack.com/feed"
    result = _run_extractor(
        "extract",
        {"source": {"url": url}, "source_id": url},
        env_extra={"RSS_FIXTURE": str(rss_fixture_rss20)},
    )
    assert result.returncode == 0, f"stderr=\n{result.stderr}\nstdout=\n{result.stdout}"
    payload = json.loads(result.stdout)
    assert payload["module"] == "rss"
    assert payload["source_id"] == url
    assert payload["verdict"] == "ok"
    assert payload["partial"] is False
    assert payload["facts"] == {}
    assert payload["notable"]
    assert payload["source_version"].startswith("sha256:")
    assert payload["extracted_at"].endswith("Z")


def test_extractor_extract_emits_valid_signal_payload_atom(
    rss_fixture_atom: Path,
) -> None:
    url = "https://simonwillison.net/atom/everything/"
    result = _run_extractor(
        "extract",
        {"source": {"url": url}, "source_id": url},
        env_extra={"RSS_FIXTURE": str(rss_fixture_atom)},
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "ok"
    assert payload["notable"]


def test_extractor_empty_feed_returns_empty_verdict(rss_fixture_empty: Path) -> None:
    url = "https://importai.substack.com/feed"
    result = _run_extractor(
        "extract",
        {"source": {"url": url}, "source_id": url},
        env_extra={"RSS_FIXTURE": str(rss_fixture_empty)},
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "empty"
    assert payload["notable"] == []


def test_extractor_get_source_version_returns_stable_id(
    rss_fixture_rss20: Path,
) -> None:
    url = "https://importai.substack.com/feed"
    result = _run_extractor(
        "get_source_version",
        {"source": {"url": url}},
        env_extra={"RSS_FIXTURE": str(rss_fixture_rss20)},
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["source_version"].startswith("sha256:")


def test_extractor_missing_fixture_returns_error_verdict(tmp_path: Path) -> None:
    url = "https://importai.substack.com/feed"
    result = _run_extractor(
        "extract",
        {"source": {"url": url}, "source_id": url},
        env_extra={"RSS_FIXTURE": str(tmp_path / "does-not-exist.xml")},
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "error"
    assert payload["partial"] is False


def test_extractor_malformed_xml_returns_error_verdict(tmp_path: Path) -> None:
    path = tmp_path / "bad.xml"
    path.write_text(MALFORMED_XML, encoding="utf-8")
    url = "https://importai.substack.com/feed"
    result = _run_extractor(
        "extract",
        {"source": {"url": url}, "source_id": url},
        env_extra={"RSS_FIXTURE": str(path)},
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "error"


def test_extractor_handles_no_source_id_gracefully(rss_fixture_rss20: Path) -> None:
    result = _run_extractor(
        "extract",
        {"source": {}},
        env_extra={"RSS_FIXTURE": str(rss_fixture_rss20)},
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "error"


def test_extractor_handles_non_feed_url(rss_fixture_rss20: Path) -> None:
    url = "https://example.com/blog/some-article"
    result = _run_extractor(
        "extract",
        {"source": {"url": url}, "source_id": url},
        env_extra={"RSS_FIXTURE": str(rss_fixture_rss20)},
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "error"


def _build_feed_with_n_entries(n: int) -> str:
    """Synthesise a minimal RSS 2.0 feed with exactly ``n`` <item> entries.

    Used by the truncated-semantics boundary tests below.
    """
    items = "\n".join(
        f"""<item>
  <title>Item {i}</title>
  <link>https://example.com/post-{i}</link>
  <description>body {i}</description>
  <pubDate>Mon, 01 Jan 2026 00:00:0{i % 10} +0000</pubDate>
</item>"""
        for i in range(n)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Boundary Test</title>
  <link>https://example.com/</link>
  <description>Boundary fixture</description>
  {items}
</channel></rss>"""


def test_extractor_truncated_false_when_entries_equal_max(tmp_path: Path) -> None:
    """Boundary case: feed has EXACTLY MAX_NOTABLE_ENTRIES items.

    Previously the extractor reported ``truncated=True`` at this exact
    boundary because it pre-sliced entries to MAX_ENTRIES (=50) and then
    checked ``len(entries) >= MAX_ENTRIES`` — which is a false positive when
    the source genuinely had exactly 50 entries.

    The fix removes the pre-slice and uses strict ``>`` so the boundary
    case is correctly reported as ``truncated=False``.
    """
    from research_framework.modules.rss.extractor import MAX_NOTABLE_ENTRIES

    fixture = tmp_path / "rss-exactly-max.xml"
    fixture.write_text(
        _build_feed_with_n_entries(MAX_NOTABLE_ENTRIES), encoding="utf-8"
    )
    url = "https://importai.substack.com/feed"
    result = _run_extractor(
        "extract",
        {"source": {"url": url}, "source_id": url},
        env_extra={"RSS_FIXTURE": str(fixture)},
    )
    assert result.returncode == 0, f"stderr=\n{result.stderr}"
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "ok"
    assert payload["truncated"] is False, (
        f"feed with exactly MAX_NOTABLE_ENTRIES={MAX_NOTABLE_ENTRIES} entries "
        f"must report truncated=False, got {payload!r}"
    )


def test_extractor_truncated_true_when_entries_exceed_max(tmp_path: Path) -> None:
    """Boundary case: feed has MAX_NOTABLE_ENTRIES + 1 items.

    This is the case the spec-020 ``truncated`` field actually exists to
    signal: ``notable`` was capped to fit the envelope. Asserts the
    extractor flips ``truncated=True`` at the first true overflow.
    """
    from research_framework.modules.rss.extractor import MAX_NOTABLE_ENTRIES

    fixture = tmp_path / "rss-over-max.xml"
    fixture.write_text(
        _build_feed_with_n_entries(MAX_NOTABLE_ENTRIES + 1), encoding="utf-8"
    )
    url = "https://importai.substack.com/feed"
    result = _run_extractor(
        "extract",
        {"source": {"url": url}, "source_id": url},
        env_extra={"RSS_FIXTURE": str(fixture)},
    )
    assert result.returncode == 0, f"stderr=\n{result.stderr}"
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "ok"
    assert payload["truncated"] is True
    # _notable_from_entries iterates `entries[:MAX_NOTABLE_ENTRIES]` so the
    # count of `Entry #` observations must not exceed MAX_NOTABLE_ENTRIES
    # (Preview lines are appended only when the body is non-empty, so the
    # total notable length is 1-2x the entry count; assert on the cap-tagged
    # entry-headline observations instead).
    entry_headlines = [
        n for n in payload["notable"] if n["observation"].startswith("Entry #")
    ]
    assert len(entry_headlines) <= MAX_NOTABLE_ENTRIES


# ---------------------------------------------------------------------------
# Signal payload conforms to spec-020 schema
# ---------------------------------------------------------------------------


def test_extractor_payload_validates_against_signal_payload_schema(
    rss_fixture_rss20: Path,
) -> None:
    pytest.importorskip("jsonschema", reason="jsonschema not installed")
    import jsonschema  # type: ignore

    schema_path = (
        REPO_ROOT
        / "specs"
        / "020-code-bridge"
        / "contracts"
        / "signal-payload.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    url = "https://www.interconnects.ai/feed"
    result = _run_extractor(
        "extract",
        {"source": {"url": url}, "source_id": url},
        env_extra={"RSS_FIXTURE": str(rss_fixture_rss20)},
    )
    payload = json.loads(result.stdout)
    jsonschema.validate(payload, schema)


def test_fetch_decodes_a_feed_in_the_encoding_its_prolog_declares(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The extractor decoded every feed as UTF-8 before the XML parse, and a
    parse of ``str`` never consults the prolog: a Latin-1 feed served without
    a charset came out with U+FFFD for each accented letter. The rule is the
    collectors' ``_fetch``: HTTP charset if it decodes, then prolog, then UTF-8.
    """
    import email.message

    from research_framework.modules.rss import extractor

    feed = (
        '<?xml version="1.0" encoding="ISO-8859-1"?>'
        '<rss version="2.0"><channel><title>f</title>'
        "<item><title>Café com informação</title>"
        "<link>https://example.com/one</link></item>"
        "</channel></rss>"
    ).encode("latin-1")

    class _Response:
        def __init__(self) -> None:
            self.headers = email.message.Message()
            self.headers["Content-Type"] = "application/rss+xml"

        def read(self, *args: int) -> bytes:
            return feed

        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

    monkeypatch.delenv("RSS_FIXTURE", raising=False)
    monkeypatch.setattr(
        extractor.urllib.request, "urlopen", lambda *a, **k: _Response()
    )

    xml_text = extractor._fetch_feed_xml("https://example.com/feed.xml")

    assert xml_text is not None
    entries = extractor._parse_feed_entries(xml_text)
    assert [entry["title"] for entry in entries or []] == ["Café com informação"]
