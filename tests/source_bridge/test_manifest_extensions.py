"""Tests for manifest schema extensions (authentication, rate_limits, failure_policy)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.pipeline.source_bridge.discovery import parse_manifest

_BASE = """name: {name}
version: 0.1.0
description: demo module
triggers:
  - type: url_pattern
    pattern: "x"
entry_point: extractor.py
default_value_tier: routine
schema_examples: few-shot.md
preflight:
  entry_point: preflight.py
"""


def _write_module(tmp_path: Path, *, extra: str = "", name: str = "demo") -> Path:
    mod = tmp_path / "modules" / name
    mod.mkdir(parents=True, exist_ok=True)
    (mod / "manifest.yaml").write_text(
        _BASE.format(name=name) + extra, encoding="utf-8"
    )
    (mod / "extractor.py").write_text("# stub\n", encoding="utf-8")
    (mod / "preflight.py").write_text("# stub\n", encoding="utf-8")
    return mod / "manifest.yaml"


def test_legacy_manifest_without_new_blocks_validates(tmp_path: Path) -> None:
    manifest_path = _write_module(tmp_path)
    manifest = parse_manifest(manifest_path)
    assert manifest.authentication is None
    assert manifest.rate_limits is None
    assert manifest.failure_policy == "block_cycle"


def test_full_manifest_blocks_round_trip(tmp_path: Path) -> None:
    extra = """
authentication:
  env_vars: [OREILLY_API_KEY, BACKUP_KEY]
rate_limits:
  requests_per_minute: 60
  requests_per_hour: 1000
  burst: none
  backoff: exponential
failure_policy: degrade_gracefully
"""
    manifest = parse_manifest(_write_module(tmp_path, extra=extra))
    assert manifest.authentication is not None
    assert manifest.authentication.env_vars == ["OREILLY_API_KEY", "BACKUP_KEY"]
    assert manifest.rate_limits is not None
    assert manifest.rate_limits.requests_per_minute == 60
    assert manifest.rate_limits.requests_per_hour == 1000
    assert manifest.rate_limits.burst == "none"
    assert manifest.rate_limits.backoff == "exponential"
    assert manifest.failure_policy == "degrade_gracefully"

    none_extra = "\nauthentication: none\n"
    manifest_none = parse_manifest(
        _write_module(tmp_path, extra=none_extra, name="none-auth")
    )
    assert manifest_none.authentication is None


def test_invalid_failure_policy_raises_value_error(tmp_path: Path) -> None:
    extra = "\nfailure_policy: not_a_real_policy\n"
    with pytest.raises(ValueError, match="failure_policy"):
        parse_manifest(_write_module(tmp_path, extra=extra))


def test_rate_limits_declaration_only_no_enforcement(tmp_path: Path) -> None:
    extra = """
rate_limits:
  requests_per_minute: 30
  requests_per_hour: 500
"""
    manifest = parse_manifest(_write_module(tmp_path, extra=extra))
    assert manifest.rate_limits is not None
    assert manifest.rate_limits.requests_per_minute == 30
    assert manifest.rate_limits.requests_per_hour == 500


def test_tier1_module_manifests_parse_with_new_blocks() -> None:
    """Tier-1 module manifests accept spec-038 optional blocks (SC-001)."""
    modules_root = (
        Path(__file__).resolve().parents[2] / "src" / "research_framework" / "modules"
    )
    for name in ("youtube", "reddit", "rss", "oreilly", "code"):
        manifest = parse_manifest(modules_root / name / "manifest.yaml")
        assert manifest.failure_policy in (
            "block_cycle",
            "degrade_gracefully",
            "defer",
        )
    youtube = parse_manifest(modules_root / "youtube" / "manifest.yaml")
    assert youtube.authentication is not None
    assert youtube.authentication.env_vars == ["YOUTUBE_API_KEY"]

    oreilly = parse_manifest(modules_root / "oreilly" / "manifest.yaml")
    assert oreilly.authentication is not None
    assert oreilly.authentication.env_vars == ["OREILLY_API_KEY"]
    assert oreilly.failure_policy == "block_cycle"

    for name in ("reddit", "rss", "code"):
        manifest = parse_manifest(modules_root / name / "manifest.yaml")
        assert manifest.authentication is None


def test_manifest_schema_accepts_authentication_none_string(tmp_path: Path) -> None:
    pytest.importorskip("jsonschema", reason="jsonschema not installed")
    import jsonschema  # type: ignore
    import yaml

    schema_path = (
        Path(__file__).resolve().parents[2]
        / "specs"
        / "020-code-bridge"
        / "contracts"
        / "manifest.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    manifest_path = _write_module(
        tmp_path, extra="\nauthentication: none\n", name="schema-none"
    )
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    jsonschema.validate(data, schema)

    modules_root = (
        Path(__file__).resolve().parents[2] / "src" / "research_framework" / "modules"
    )
    for name in ("reddit", "rss", "code"):
        module_data = yaml.safe_load(
            (modules_root / name / "manifest.yaml").read_text(encoding="utf-8")
        )
        jsonschema.validate(module_data, schema)
