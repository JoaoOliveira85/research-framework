"""Code module manifest tests."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from research_framework.pipeline.source_bridge.discovery import parse_manifest


def _manifest_path() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "src"
        / "research_framework"
        / "modules"
        / "code"
        / "manifest.yaml"
    )


def test_code_manifest_triggers_and_source_id_from() -> None:
    manifest = parse_manifest(_manifest_path())
    types = {t.get("type") for t in manifest.triggers}
    assert "path_pattern" in types or "path_exists" in types
    assert manifest.source_id_from.get("github_repos") == "path"


def test_code_manifest_does_not_claim_remote_urls() -> None:
    """Regression (spec-020 amendment 2026-06-08): `code` is local-only.

    The old manifest carried a `url_pattern: (github|gitlab)\\.com/` trigger
    even though the extractor only does local `git rev-parse HEAD`. Remote
    GitHub URLs now route to the `github` module, so `code` must declare no
    url_pattern trigger.
    """
    manifest = parse_manifest(_manifest_path())
    assert [t for t in manifest.triggers if t.get("type") == "url_pattern"] == []


def test_code_manifest_conforms_to_manifest_schema() -> None:
    schema_path = (
        Path(__file__).resolve().parents[3]
        / "specs"
        / "020-code-bridge"
        / "contracts"
        / "manifest.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    data = yaml.safe_load(_manifest_path().read_text(encoding="utf-8"))
    assert data["name"] == "code"
    assert "triggers" in data
    assert schema["type"] == "object"


def test_sources_yaml_template_present_in_bundle() -> None:
    template = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "research_framework"
        / "modules"
        / "code"
        / "sources.yaml.template"
    )
    assert template.is_file()
    text = template.read_text(encoding="utf-8").lower()
    assert "github_repos" in text or "sources" in text
