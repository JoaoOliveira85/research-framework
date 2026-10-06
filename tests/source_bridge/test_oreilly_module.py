"""O'Reilly module contract tests (Wave 2 / spec 020).

These tests cover the SHIPPED module assets at
``src/research_framework/modules/oreilly/`` — they assert:

1. Manifest parses, validates against the schema, and declares
   the expected url_pattern triggers + ``source_id_from`` mapping.
2. The extractor honours the spec-020 stdin/stdout JSON contract
   for both the ``extract`` and ``get_source_version`` commands.
3. API calls are isolated via ``OREILLY_API_FIXTURE`` so tests
   stay hermetic — no real network.
4. The emitted ``SignalPayload`` validates against
   ``signal-payload.schema.json`` for the happy path.
5. ``OREILLY_API_KEY`` never leaks into stdout or stderr.
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
MODULE_DIR = REPO_ROOT / "src" / "research_framework" / "modules" / "oreilly"

SEARCH_URL = "https://learning.oreilly.com/search/?q=LLM+agents+production"
SENTINEL_KEY = "sentinel-do-not-leak-12345"

POPULATED_FIXTURE = {
    "search_results": {
        "urn:orm:book:llm-agents": {
            "title": "Building LLM Agents for Production",
            "url": "https://learning.oreilly.com/library/view/building-llm-agents/",
            "authors": ["Jane Doe", "John Smith"],
            "description": "Patterns for deploying LLM agents in production.",
            "display_format": "book",
            "publication_date": "2026-01-15",
        },
        "urn:orm:course:mcp": {
            "title": "MCP Model Context Protocol",
            "url": "https://learning.oreilly.com/videos/mcp-intro/",
            "authors": ["Alex Dev"],
            "display_format": "course",
            "publication_date": "2025-11-01",
        },
    }
}

EMPTY_FIXTURE = {"search_results": {}}

MALFORMED_FIXTURE = "not valid json <<<"


def _module_path(name: str) -> Path:
    return MODULE_DIR / name


def _run_extractor(
    command: str,
    payload: dict,
    *,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("OREILLY_API_FIXTURE", None)
    env.pop("OREILLY_API_KEY", None)
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


def _write_fixture(tmp_path: Path, name: str, data: object) -> Path:
    path = tmp_path / name
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Manifest contract
# ---------------------------------------------------------------------------


def test_manifest_yaml_loads_and_declares_oreilly_identity() -> None:
    raw = yaml.safe_load(_module_path("manifest.yaml").read_text(encoding="utf-8"))
    assert raw["name"] == "oreilly"
    assert raw["entry_point"] == "extractor.py"
    assert raw["schema_examples"] == "few-shot.md"
    assert raw["default_value_tier"] in {"routine", "important", "critical"}


def test_manifest_validates_via_discovery_parser() -> None:
    manifest = parse_manifest(_module_path("manifest.yaml"))
    assert manifest.name == "oreilly"
    assert manifest.entry_point == "extractor.py"


def test_manifest_url_triggers_match_learning_oreilly_urls() -> None:
    import re

    raw = yaml.safe_load(_module_path("manifest.yaml").read_text(encoding="utf-8"))
    url_patterns = [t["pattern"] for t in raw["triggers"] if t["type"] == "url_pattern"]
    assert len(url_patterns) >= 1
    combined = "|".join(f"(?:{p})" for p in url_patterns)
    rx = re.compile(combined)
    assert rx.search(SEARCH_URL)
    assert rx.search("https://learning.oreilly.com/library/view/some-book/")
    assert not rx.search("https://example.com/search?q=test")


def test_manifest_source_id_from_maps_query_url() -> None:
    raw = yaml.safe_load(_module_path("manifest.yaml").read_text(encoding="utf-8"))
    assert "source_id_from" in raw
    assert raw["source_id_from"]["oreilly_queries"] == "url"


# ---------------------------------------------------------------------------
# Asset contracts (sources.yaml.template + few-shot.md)
# ---------------------------------------------------------------------------


def test_sources_yaml_template_ships_with_module() -> None:
    template = _module_path("sources.yaml.template")
    assert template.exists()
    raw = yaml.safe_load(template.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    queries = raw.get("oreilly_queries", [])
    assert 4 <= len(queries) <= 8
    urls = [e["url"] for e in queries]
    assert all("learning.oreilly.com/search" in u for u in urls)
    assert any("LLM" in u or "llm" in u.lower() for u in urls)
    assert any("MCP" in u or "mcp" in u.lower() for u in urls)


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
def oreilly_fixture_populated(tmp_path: Path) -> Path:
    return _write_fixture(tmp_path, "populated.json", POPULATED_FIXTURE)


@pytest.fixture
def oreilly_fixture_empty(tmp_path: Path) -> Path:
    return _write_fixture(tmp_path, "empty.json", EMPTY_FIXTURE)


def test_extractor_extract_emits_valid_signal_payload(
    oreilly_fixture_populated: Path,
) -> None:
    result = _run_extractor(
        "extract",
        {"source": {"url": SEARCH_URL}, "source_id": SEARCH_URL},
        env_extra={"OREILLY_API_FIXTURE": str(oreilly_fixture_populated)},
    )
    assert result.returncode == 0, f"stderr=\n{result.stderr}\nstdout=\n{result.stdout}"
    payload = json.loads(result.stdout)
    assert payload["module"] == "oreilly"
    assert payload["source_id"] == SEARCH_URL
    assert payload["verdict"] == "ok"
    assert payload["partial"] is False
    assert payload["facts"] == {}
    assert payload["notable"]
    assert payload["source_version"].startswith("sha256:")
    assert payload["extracted_at"].endswith("Z")
    assert SENTINEL_KEY not in result.stdout
    assert SENTINEL_KEY not in result.stderr


def test_extractor_get_source_version_returns_stable_id(
    oreilly_fixture_populated: Path,
) -> None:
    result = _run_extractor(
        "get_source_version",
        {"source": {"url": SEARCH_URL}},
        env_extra={"OREILLY_API_FIXTURE": str(oreilly_fixture_populated)},
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["source_version"].startswith("sha256:")


def test_extractor_missing_api_key_and_fixture_returns_error() -> None:
    result = _run_extractor(
        "extract",
        {"source": {"url": SEARCH_URL}, "source_id": SEARCH_URL},
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "error"
    assert "OREILLY_API_KEY" in payload["notable"][0]["observation"]
    assert SENTINEL_KEY not in result.stdout
    assert SENTINEL_KEY not in result.stderr
    assert "sentinel" not in result.stdout.lower()
    assert "sentinel" not in result.stderr.lower()


def test_extractor_empty_hits_returns_empty_verdict(
    oreilly_fixture_empty: Path,
) -> None:
    result = _run_extractor(
        "extract",
        {"source": {"url": SEARCH_URL}, "source_id": SEARCH_URL},
        env_extra={"OREILLY_API_FIXTURE": str(oreilly_fixture_empty)},
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "empty"
    assert payload["notable"] == []


def test_extractor_malformed_fixture_returns_error_verdict(tmp_path: Path) -> None:
    path = _write_fixture(tmp_path, "bad.json", MALFORMED_FIXTURE)
    result = _run_extractor(
        "extract",
        {"source": {"url": SEARCH_URL}, "source_id": SEARCH_URL},
        env_extra={"OREILLY_API_FIXTURE": str(path)},
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "error"
    obs = payload["notable"][0]["observation"]
    assert "malformed OREILLY_API_FIXTURE JSON" in obs
    assert "missing or unreadable" not in obs


def test_extractor_non_oreilly_url_returns_error(
    oreilly_fixture_populated: Path,
) -> None:
    url = "https://example.com/search?q=test"
    result = _run_extractor(
        "extract",
        {"source": {"url": url}, "source_id": url},
        env_extra={"OREILLY_API_FIXTURE": str(oreilly_fixture_populated)},
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "error"


def _fixture_with_n_hits(n: int) -> dict:
    """Synthesise an O'Reilly search-results fixture with exactly ``n`` hits."""
    return {
        "search_results": {
            f"urn:orm:book:hit-{i}": {
                "title": f"Test Hit {i}",
                "url": f"https://learning.oreilly.com/library/view/test-{i}/",
                "authors": [f"Author {i}"],
                "description": f"Description for hit {i}",
                "display_format": "book",
                "publication_date": "2026-01-01",
            }
            for i in range(n)
        }
    }


def test_extractor_truncated_false_when_hits_equal_max(tmp_path: Path) -> None:
    """Boundary case: fixture returns EXACTLY MAX_HITS results.

    Previously the extractor reported ``truncated=True`` at this exact
    boundary because it fetched at most MAX_HITS items and then checked
    ``len(hits) >= MAX_HITS`` — a false positive when the source genuinely
    had exactly that many results. The fix fetches ``MAX_HITS + 1`` and
    uses strict ``>`` so the boundary case is correctly reported as
    ``truncated=False``.
    """
    from research_framework.modules.oreilly.extractor import MAX_HITS

    fixture_path = _write_fixture(
        tmp_path, "oreilly-exactly-max.json", _fixture_with_n_hits(MAX_HITS)
    )
    result = _run_extractor(
        "extract",
        {"source": {"url": SEARCH_URL}, "source_id": SEARCH_URL},
        env_extra={"OREILLY_API_FIXTURE": str(fixture_path)},
    )
    assert result.returncode == 0, f"stderr=\n{result.stderr}"
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "ok"
    assert payload["truncated"] is False, (
        f"fixture with exactly MAX_HITS={MAX_HITS} hits must report "
        f"truncated=False, got {payload!r}"
    )


def test_extractor_truncated_true_when_hits_exceed_max(tmp_path: Path) -> None:
    """Boundary case: fixture returns MAX_HITS + 1 results.

    This is the case the spec-020 ``truncated`` field actually exists to
    signal: ``notable`` was capped to fit the envelope. Asserts the
    extractor flips ``truncated=True`` at the first true overflow.
    """
    from research_framework.modules.oreilly.extractor import (
        MAX_HITS,
        MAX_NOTABLE_HITS,
    )

    fixture_path = _write_fixture(
        tmp_path, "oreilly-over-max.json", _fixture_with_n_hits(MAX_HITS + 1)
    )
    result = _run_extractor(
        "extract",
        {"source": {"url": SEARCH_URL}, "source_id": SEARCH_URL},
        env_extra={"OREILLY_API_FIXTURE": str(fixture_path)},
    )
    assert result.returncode == 0, f"stderr=\n{result.stderr}"
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "ok"
    assert payload["truncated"] is True
    # _notable_from_hits emits one headline + (optionally) one description
    # observation per hit; cap is on hits, not on notable[]. Assert the
    # cap-tagged headline count instead.
    headlines = [
        n for n in payload["notable"] if n["observation"].startswith("O'Reilly")
    ]
    assert len(headlines) <= MAX_NOTABLE_HITS


def test_extractor_api_key_never_leaks_in_output(
    oreilly_fixture_populated: Path,
) -> None:
    result = _run_extractor(
        "extract",
        {"source": {"url": SEARCH_URL}, "source_id": SEARCH_URL},
        env_extra={
            "OREILLY_API_FIXTURE": str(oreilly_fixture_populated),
            "OREILLY_API_KEY": SENTINEL_KEY,
        },
    )
    assert result.returncode == 0
    assert SENTINEL_KEY not in result.stdout
    assert SENTINEL_KEY not in result.stderr
    payload = json.loads(result.stdout)
    dumped = json.dumps(payload)
    assert SENTINEL_KEY not in dumped


# ---------------------------------------------------------------------------
# Signal payload conforms to spec-020 schema
# ---------------------------------------------------------------------------


def test_extractor_payload_validates_against_signal_payload_schema(
    oreilly_fixture_populated: Path,
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

    result = _run_extractor(
        "extract",
        {"source": {"url": SEARCH_URL}, "source_id": SEARCH_URL},
        env_extra={"OREILLY_API_FIXTURE": str(oreilly_fixture_populated)},
    )
    payload = json.loads(result.stdout)
    jsonschema.validate(payload, schema)


def test_query_url_is_decoded_exactly_once() -> None:
    """``parse_qs`` already decodes ``q``; decoding again turned ``C++`` into
    ``C  `` and searched for something else."""
    from research_framework.modules.oreilly.extractor import _extract_query_from_url

    url = "https://learning.oreilly.com/search/?q=C%2B%2B+templates"
    assert _extract_query_from_url(url) == "C++ templates"
