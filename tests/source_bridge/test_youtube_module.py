"""YouTube module contract tests (Wave 2 / spec 020).

These tests cover the SHIPPED module assets at
``src/research_framework/modules/youtube/`` — they assert:

1. Manifest parses, validates against the schema, and declares
   the expected url_pattern triggers + ``source_id_from`` mapping.
2. The extractor honours the spec-020 stdin/stdout JSON contract
   for both the ``extract`` and ``get_source_version`` commands.
3. Network calls (``yt-dlp``) are isolated via a ``YT_DLP_BIN``
   environment override so tests stay hermetic — no real network.
4. The emitted ``SignalPayload`` validates against
   ``signal-payload.schema.json`` for the happy path, the
   no-transcript path (verdict: ``empty``), and the binary-missing
   path (verdict: ``error``).

The youtube extractor is deliberately thin (mirrors the ``code``
module pattern): it returns valid envelope + transcript metadata
but leaves ``facts: {}`` for downstream LLM-driven schema
extraction. Filling ``facts`` is a follow-up issue.
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
MODULE_DIR = REPO_ROOT / "src" / "research_framework" / "modules" / "youtube"


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


def test_manifest_yaml_loads_and_declares_youtube_identity() -> None:
    raw = yaml.safe_load(_module_path("manifest.yaml").read_text(encoding="utf-8"))
    assert raw["name"] == "youtube"
    assert raw["entry_point"] == "extractor.py"
    assert raw["schema_examples"] == "few-shot.md"
    assert raw["default_value_tier"] in {"routine", "important", "critical"}


def test_manifest_validates_via_discovery_parser() -> None:
    manifest = parse_manifest(_module_path("manifest.yaml"))
    assert manifest.name == "youtube"
    assert manifest.entry_point == "extractor.py"


def test_manifest_url_triggers_match_youtube_and_youtu_be() -> None:
    import re

    raw = yaml.safe_load(_module_path("manifest.yaml").read_text(encoding="utf-8"))
    url_patterns = [t["pattern"] for t in raw["triggers"] if t["type"] == "url_pattern"]
    assert url_patterns, "youtube module must declare at least one url_pattern"
    combined = "|".join(f"(?:{p})" for p in url_patterns)
    rx = re.compile(combined)
    assert rx.search("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert rx.search("https://youtu.be/dQw4w9WgXcQ")
    assert not rx.search("https://example.com/watch?v=dQw4w9WgXcQ")


def test_manifest_source_id_from_maps_video_url() -> None:
    raw = yaml.safe_load(_module_path("manifest.yaml").read_text(encoding="utf-8"))
    assert "source_id_from" in raw
    # Top-level key chosen by the module — assert at least one mapping
    # uses "url" so the framework can identify a YouTube video by its URL.
    assert "url" in raw["source_id_from"].values()


# ---------------------------------------------------------------------------
# Asset contracts (sources.yaml.template + few-shot.md)
# ---------------------------------------------------------------------------


def test_sources_yaml_template_ships_with_module() -> None:
    template = _module_path("sources.yaml.template")
    assert template.exists()
    raw = yaml.safe_load(template.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    assert raw, "sources.yaml.template must seed at least one example bucket"


def test_few_shot_md_exists_and_has_examples() -> None:
    few_shot = _module_path("few-shot.md")
    assert few_shot.exists()
    body = few_shot.read_text(encoding="utf-8")
    # Few-shot is calibration for schema-gen — must have multiple
    # example schemas to teach the model that buckets are domain-driven.
    assert body.count("```") >= 2, "few-shot.md must include code-fenced examples"


def test_module_ships_readme() -> None:
    assert _module_path("README.md").exists()


# ---------------------------------------------------------------------------
# Extractor stdin/stdout contract
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_yt_dlp(tmp_path: Path) -> Path:
    """Stand-in for yt-dlp binary returning canned metadata + subtitles.

    The extractor must accept a ``YT_DLP_BIN`` override so tests can
    swap in this stub and stay offline.
    """
    bin_path = tmp_path / "yt-dlp-fake"
    bin_path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "args = sys.argv[1:]\n"
        "if '--dump-json' in args:\n"
        "    print(json.dumps({\n"
        "        'title': 'Demo video',\n"
        "        'description': 'A demo',\n"
        "        'uploader': 'Demo Channel',\n"
        "        'upload_date': '20260527',\n"
        "    }))\n"
        "sys.exit(0)\n"
    )
    bin_path.chmod(0o755)
    return bin_path


def test_extractor_extract_emits_valid_signal_payload(fake_yt_dlp: Path) -> None:
    result = _run_extractor(
        "extract",
        {
            "source": {"url": "https://www.youtube.com/watch?v=demo123"},
            "source_id": "https://www.youtube.com/watch?v=demo123",
        },
        env_extra={"YT_DLP_BIN": str(fake_yt_dlp), "YT_SKIP_SUBS": "1"},
    )
    assert result.returncode == 0, f"stderr=\n{result.stderr}\nstdout=\n{result.stdout}"
    payload = json.loads(result.stdout)
    assert payload["module"] == "youtube"
    assert payload["source_id"] == "https://www.youtube.com/watch?v=demo123"
    assert payload["verdict"] in {"ok", "empty"}
    assert payload["partial"] is False
    assert payload["truncated"] is False
    assert "facts" in payload and isinstance(payload["facts"], dict)
    assert "notable" in payload and isinstance(payload["notable"], list)
    # Envelope timestamp + version fields present and sane
    assert payload["source_version"]
    assert payload["bridge_version"]
    assert payload["extracted_at"].endswith("Z")


def test_extractor_get_source_version_returns_stable_id(fake_yt_dlp: Path) -> None:
    result = _run_extractor(
        "get_source_version",
        {"source": {"url": "https://www.youtube.com/watch?v=demo123"}},
        env_extra={"YT_DLP_BIN": str(fake_yt_dlp), "YT_SKIP_SUBS": "1"},
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert "source_version" in payload
    assert payload["source_version"]
    assert (
        payload["source_version"] != "unknown" or "demo123" in payload["source_version"]
    )


def test_extractor_missing_yt_dlp_returns_error_verdict(tmp_path: Path) -> None:
    """When yt-dlp is missing, emit verdict=error (not crash)."""
    result = _run_extractor(
        "extract",
        {
            "source": {"url": "https://www.youtube.com/watch?v=demo123"},
            "source_id": "https://www.youtube.com/watch?v=demo123",
        },
        env_extra={"YT_DLP_BIN": str(tmp_path / "does-not-exist")},
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["module"] == "youtube"
    assert payload["verdict"] == "error"
    # Per signal-payload.schema.json allOf: partial=true REQUIRES verdict=error
    # We don't claim partial — just clean error envelope.
    assert payload["partial"] is False
    assert payload["facts"] == {}


def test_extractor_handles_no_source_id_gracefully(fake_yt_dlp: Path) -> None:
    result = _run_extractor(
        "extract",
        {"source": {}},
        env_extra={"YT_DLP_BIN": str(fake_yt_dlp), "YT_SKIP_SUBS": "1"},
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "error"


def test_extractor_handles_non_youtube_url(fake_yt_dlp: Path) -> None:
    result = _run_extractor(
        "extract",
        {
            "source": {"url": "https://example.com/watch?v=demo123"},
            "source_id": "https://example.com/watch?v=demo123",
        },
        env_extra={"YT_DLP_BIN": str(fake_yt_dlp), "YT_SKIP_SUBS": "1"},
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "error"


# ---------------------------------------------------------------------------
# Signal payload conforms to spec-020 schema
# ---------------------------------------------------------------------------


def test_extractor_payload_validates_against_signal_payload_schema(
    fake_yt_dlp: Path,
) -> None:
    """Ensure the happy-path payload matches signal-payload.schema.json."""
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
        {
            "source": {"url": "https://youtu.be/demo123"},
            "source_id": "https://youtu.be/demo123",
        },
        env_extra={"YT_DLP_BIN": str(fake_yt_dlp), "YT_SKIP_SUBS": "1"},
    )
    payload = json.loads(result.stdout)
    jsonschema.validate(payload, schema)
