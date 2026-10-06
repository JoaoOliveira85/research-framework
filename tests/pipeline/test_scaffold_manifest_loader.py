"""Tests for pipeline/scaffold_manifest.py — loads and validates the scaffold manifest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.pipeline.scaffold_manifest import (
    ScaffoldManifest,
    load_manifest,
)

REPO_ROOT = Path(__file__).parent.parent.parent
DIST_MANIFEST = REPO_ROOT / "dist-templates" / "scaffold-manifest.json"


@pytest.fixture
def valid_manifest_path(tmp_path: Path) -> Path:
    p = tmp_path / "scaffold-manifest.json"
    p.write_text(
        json.dumps(
            {
                "framework_version": 1,
                "generator_commit": "abc1234",
                "generated_at": "2026-05-13T00:00:00Z",
                "entries": [
                    {
                        "path": "CLAUDE.md",
                        "kind": "markdown",
                        "template_version": 1,
                        "rendered_sha256": "a" * 64,
                        "is_user_owned_after_first_write": False,
                    }
                ],
            }
        )
    )
    return p


def test_loads_valid_manifest(valid_manifest_path: Path) -> None:
    """(a) loads and validates a correct manifest, returns ScaffoldManifest."""
    manifest = load_manifest(valid_manifest_path)
    assert isinstance(manifest, ScaffoldManifest)
    assert manifest.framework_version == 1
    assert len(manifest.entries) == 1
    assert manifest.entries[0].path == "CLAUDE.md"


def test_raises_on_missing_manifest(tmp_path: Path) -> None:
    """(b) raises a clear error when the manifest is missing."""
    missing = tmp_path / "scaffold-manifest.json"
    with pytest.raises(FileNotFoundError, match="scaffold-manifest.json"):
        load_manifest(missing)


def test_error_message_names_build_step(tmp_path: Path) -> None:
    """(b) error message names the expected path and references the build step."""
    missing = tmp_path / "scaffold-manifest.json"
    with pytest.raises(FileNotFoundError) as exc_info:
        load_manifest(missing)
    msg = str(exc_info.value)
    assert "build_scaffold_manifest" in msg or "build" in msg.lower()


def test_raises_on_schema_invalid_manifest(tmp_path: Path) -> None:
    """(c) raises a clear error when the manifest fails schema validation."""
    bad = tmp_path / "scaffold-manifest.json"
    bad.write_text(json.dumps({"wrong_key": "totally_wrong"}))
    with pytest.raises((ValueError, KeyError, TypeError)):
        load_manifest(bad)
