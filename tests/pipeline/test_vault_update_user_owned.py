"""Unit tests for manifest user-owned guard helpers (spec 027 FR-006)."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework.pipeline.scaffold_manifest import load_manifest
from research_framework.pipeline.vault_update import is_user_owned

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "dist-templates" / "scaffold-manifest.json"


@pytest.fixture(scope="module")
def manifest():
    return load_manifest(MANIFEST_PATH)


def test_is_user_owned_true_for_manifest_flagged_paths(manifest) -> None:
    settings = next(e for e in manifest.entries if e.path == "settings.yaml")
    assert settings.is_user_owned_after_first_write is True
    assert is_user_owned(manifest, "settings.yaml") is True


def test_is_user_owned_false_for_non_flagged_paths(manifest) -> None:
    vault_entry = next(e for e in manifest.entries if e.path == "vault")
    assert vault_entry.is_user_owned_after_first_write is False
    assert is_user_owned(manifest, "vault") is False


def test_is_user_owned_matrix_matches_scaffold_manifest(manifest) -> None:
    for entry in manifest.entries:
        assert (
            is_user_owned(manifest, entry.path) == entry.is_user_owned_after_first_write
        )
