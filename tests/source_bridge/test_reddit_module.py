"""Reddit module contract tests (Wave 2 / spec 020).

These tests cover the SHIPPED module assets at
``src/research_framework/modules/reddit/`` — they assert:

1. Manifest parses, validates against the schema, and declares
   the expected url_pattern triggers + ``source_id_from`` mapping.
2. The extractor honours the spec-020 stdin/stdout JSON contract
   for both the ``extract`` and ``get_source_version`` commands.
3. Network calls are isolated via ``REDDIT_RSS_FIXTURE`` so tests
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
MODULE_DIR = REPO_ROOT / "src" / "research_framework" / "modules" / "reddit"

POPULATED_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Test post on ML</title>
    <link href="https://www.reddit.com/r/MachineLearning/comments/abc123/test_post/"/>
    <author><name>/u/testuser</name></author>
    <updated>2026-05-27T12:00:00Z</updated>
    <content type="html">&lt;p&gt;Hello from RSS fixture&lt;/p&gt;</content>
  </entry>
</feed>
"""

EMPTY_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
</feed>
"""


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


def test_manifest_yaml_loads_and_declares_reddit_identity() -> None:
    raw = yaml.safe_load(_module_path("manifest.yaml").read_text(encoding="utf-8"))
    assert raw["name"] == "reddit"
    assert raw["entry_point"] == "extractor.py"
    assert raw["schema_examples"] == "few-shot.md"
    assert raw["default_value_tier"] in {"routine", "important", "critical"}


def test_manifest_validates_via_discovery_parser() -> None:
    manifest = parse_manifest(_module_path("manifest.yaml"))
    assert manifest.name == "reddit"
    assert manifest.entry_point == "extractor.py"


def test_manifest_url_triggers_match_subreddit_and_post_urls() -> None:
    import re

    raw = yaml.safe_load(_module_path("manifest.yaml").read_text(encoding="utf-8"))
    url_patterns = [t["pattern"] for t in raw["triggers"] if t["type"] == "url_pattern"]
    assert len(url_patterns) >= 2
    combined = "|".join(f"(?:{p})" for p in url_patterns)
    rx = re.compile(combined)
    assert rx.search("https://www.reddit.com/r/MachineLearning/.rss")
    assert rx.search("https://www.reddit.com/r/LocalLLaMA/comments/abc123/some_title/")
    assert not rx.search("https://example.com/r/MachineLearning/")


def test_manifest_source_id_from_maps_subreddit_url() -> None:
    raw = yaml.safe_load(_module_path("manifest.yaml").read_text(encoding="utf-8"))
    assert "source_id_from" in raw
    assert raw["source_id_from"]["reddit_subreddits"] == "url"
    assert raw["source_id_from"]["reddit_posts"] == "url"


# ---------------------------------------------------------------------------
# Asset contracts (sources.yaml.template + few-shot.md)
# ---------------------------------------------------------------------------


def test_sources_yaml_template_ships_with_module() -> None:
    template = _module_path("sources.yaml.template")
    assert template.exists()
    raw = yaml.safe_load(template.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    subs = raw.get("reddit_subreddits", [])
    assert len(subs) == 13, "frozen allowlist must preserve 13 subreddits"
    urls = [e["url"] for e in subs]
    assert all(u.endswith(".rss") for u in urls)
    assert "https://www.reddit.com/r/MachineLearning/.rss" in urls


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
def rss_fixture_populated(tmp_path: Path) -> Path:
    path = tmp_path / "reddit-populated.xml"
    path.write_text(POPULATED_RSS, encoding="utf-8")
    return path


@pytest.fixture
def rss_fixture_empty(tmp_path: Path) -> Path:
    path = tmp_path / "reddit-empty.xml"
    path.write_text(EMPTY_RSS, encoding="utf-8")
    return path


def test_extractor_extract_emits_valid_signal_payload(
    rss_fixture_populated: Path,
) -> None:
    url = "https://www.reddit.com/r/MachineLearning/.rss"
    result = _run_extractor(
        "extract",
        {"source": {"url": url}, "source_id": url},
        env_extra={"REDDIT_RSS_FIXTURE": str(rss_fixture_populated)},
    )
    assert result.returncode == 0, f"stderr=\n{result.stderr}\nstdout=\n{result.stdout}"
    payload = json.loads(result.stdout)
    assert payload["module"] == "reddit"
    assert payload["source_id"] == url
    assert payload["verdict"] == "ok"
    assert payload["partial"] is False
    assert payload["facts"] == {}
    assert payload["notable"]
    assert payload["source_version"].startswith("sha256:")
    assert payload["extracted_at"].endswith("Z")


def test_extractor_empty_feed_returns_empty_verdict(rss_fixture_empty: Path) -> None:
    url = "https://www.reddit.com/r/MachineLearning/.rss"
    result = _run_extractor(
        "extract",
        {"source": {"url": url}, "source_id": url},
        env_extra={"REDDIT_RSS_FIXTURE": str(rss_fixture_empty)},
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "empty"
    assert payload["notable"] == []


def test_extractor_get_source_version_returns_stable_id(
    rss_fixture_populated: Path,
) -> None:
    url = "https://www.reddit.com/r/MachineLearning/.rss"
    result = _run_extractor(
        "get_source_version",
        {"source": {"url": url}},
        env_extra={"REDDIT_RSS_FIXTURE": str(rss_fixture_populated)},
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["source_version"].startswith("sha256:")


def test_extractor_missing_fixture_returns_error_verdict(tmp_path: Path) -> None:
    url = "https://www.reddit.com/r/MachineLearning/.rss"
    result = _run_extractor(
        "extract",
        {"source": {"url": url}, "source_id": url},
        env_extra={"REDDIT_RSS_FIXTURE": str(tmp_path / "does-not-exist.xml")},
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "error"
    assert payload["partial"] is False


def test_extractor_malformed_xml_returns_error_verdict(tmp_path: Path) -> None:
    """Malformed feed XML must surface as ``verdict=error``, not silently
    bin as ``verdict=empty``. Mirrors the sibling rss-module contract
    test ``test_extractor_malformed_xml_returns_error_verdict`` to keep
    the two RSS-based extractors aligned on spec-020 D9 (extractor never
    swallows parse errors)."""
    malformed = tmp_path / "reddit-malformed.xml"
    malformed.write_text("<not-actually-xml<<<", encoding="utf-8")
    url = "https://www.reddit.com/r/MachineLearning/.rss"
    result = _run_extractor(
        "extract",
        {"source": {"url": url}, "source_id": url},
        env_extra={"REDDIT_RSS_FIXTURE": str(malformed)},
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "error", (
        f"malformed XML should be verdict=error, got {payload!r}"
    )
    assert payload["partial"] is False
    assert payload["facts"] == {}
    assert any(
        "malformed" in note.get("observation", "").lower()
        for note in payload["notable"]
    )


def test_extractor_handles_no_source_id_gracefully(rss_fixture_populated: Path) -> None:
    result = _run_extractor(
        "extract",
        {"source": {}},
        env_extra={"REDDIT_RSS_FIXTURE": str(rss_fixture_populated)},
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "error"


def test_extractor_handles_non_reddit_url(rss_fixture_populated: Path) -> None:
    url = "https://example.com/r/MachineLearning/"
    result = _run_extractor(
        "extract",
        {"source": {"url": url}, "source_id": url},
        env_extra={"REDDIT_RSS_FIXTURE": str(rss_fixture_populated)},
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "error"


# ---------------------------------------------------------------------------
# Signal payload conforms to spec-020 schema
# ---------------------------------------------------------------------------


def test_extractor_payload_validates_against_signal_payload_schema(
    rss_fixture_populated: Path,
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

    url = "https://www.reddit.com/r/ClaudeAI/comments/xyz789/thread/"
    result = _run_extractor(
        "extract",
        {"source": {"url": url}, "source_id": url},
        env_extra={"REDDIT_RSS_FIXTURE": str(rss_fixture_populated)},
    )
    payload = json.loads(result.stdout)
    jsonschema.validate(payload, schema)
