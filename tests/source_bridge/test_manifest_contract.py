"""Manifest contract validation."""

from __future__ import annotations

import yaml

from research_framework._assets import asset_path
from research_framework.pipeline.source_bridge.discovery import parse_manifest


def test_reference_code_manifest_validates() -> None:
    manifest_path = (
        asset_path("src/research_framework/modules/code/manifest.yaml")
        if (asset_path("src/research_framework/modules/code/manifest.yaml")).exists()
        else None
    )
    if manifest_path is None:
        from pathlib import Path

        manifest_path = (
            Path(__file__).resolve().parents[2]
            / "src/research_framework/modules/code/manifest.yaml"
        )
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert raw["name"] == "code"
    assert raw["entry_point"] == "extractor.py"
    manifest = parse_manifest(manifest_path)
    assert manifest.default_value_tier == "routine"
