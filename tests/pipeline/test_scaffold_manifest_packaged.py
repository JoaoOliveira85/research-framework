"""The scaffold manifest resolves from the installed package (issue #34).

``default_manifest_path`` used to find the manifest only in a repo checkout or
a working directory holding ``dist-templates/``; the wheel did not carry it, so
``./vault regenerate-shim --force`` died with FileNotFoundError in every
installed vault. These tests simulate the wheel layout (``_data/`` populated,
no repo checkout, unrelated cwd).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework import _assets
from research_framework.generator.scaffold import should_preserve_user_owned_file
from research_framework.pipeline.scaffold_manifest import (
    default_manifest_path,
    load_manifest,
)

REPO = Path(__file__).resolve().parents[2]
REAL_MANIFEST = REPO / "dist-templates" / "scaffold-manifest.json"


@pytest.fixture
def installed_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Wheel layout: manifest only under packaged ``_data``; cwd unrelated."""
    packaged = tmp_path / "site-packages" / "research_framework" / "_data"
    (packaged / "dist-templates").mkdir(parents=True)
    (packaged / "dist-templates" / "scaffold-manifest.json").write_text(
        REAL_MANIFEST.read_text(encoding="utf-8"), encoding="utf-8"
    )
    empty_source = tmp_path / "no-checkout"
    empty_source.mkdir()
    monkeypatch.setattr(_assets, "_PACKAGED_DATA", packaged)
    monkeypatch.setattr(_assets, "_SOURCE_ROOT", empty_source)
    elsewhere = tmp_path / "unrelated-cwd"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.delenv("RESEARCH_VAULT_MANIFEST", raising=False)
    return packaged


def test_manifest_resolves_from_package_without_checkout(
    installed_layout: Path,
) -> None:
    path = default_manifest_path()
    assert path == installed_layout / "dist-templates" / "scaffold-manifest.json"
    assert load_manifest(path).entries


def test_env_override_still_wins(
    installed_layout: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override = tmp_path / "custom.json"
    monkeypatch.setenv("RESEARCH_VAULT_MANIFEST", str(override))
    assert default_manifest_path() == override


def test_repo_checkout_still_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RESEARCH_VAULT_MANIFEST", raising=False)
    assert default_manifest_path().resolve() == REAL_MANIFEST.resolve()


def test_should_preserve_works_from_installed_layout(
    installed_layout: Path, tmp_path: Path
) -> None:
    """The exact call regenerate-shim --force makes, with no vault snapshot."""
    vault = tmp_path / "vault"
    (vault / "_pipeline").mkdir(parents=True)
    (vault / "vault").write_text("#!/bin/sh\n", encoding="utf-8")
    # Raised FileNotFoundError before the fix; the answer itself is irrelevant.
    assert isinstance(should_preserve_user_owned_file(vault, "vault"), bool)
