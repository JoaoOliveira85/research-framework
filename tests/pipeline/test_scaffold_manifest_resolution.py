"""`default_manifest_path` must resolve from an installed wheel, not a checkout.

An installed vault is not a source checkout and its CWD is unrelated to this
repo, so before issue #34 the resolver fell through to the relative fallback
and `regenerate-shim --force` died with
`FileNotFoundError: Scaffold manifest not found at 'dist-templates/scaffold-manifest.json'`.
The wheel now carries the manifest under
`research_framework/_data/dist-templates/`, which is what these tests pin.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.pipeline import scaffold_manifest

_MANIFEST = {
    "framework_version": 1,
    "generator_commit": "0" * 40,
    "generated_at": "2026-01-01T00:00:00Z",
    "entries": [
        {
            "path": "settings.yaml",
            "kind": "yaml",
            "template_version": 1,
            "rendered_sha256": "0" * 64,
        }
    ],
}


def _install_fake_wheel(tmp_path: Path) -> Path:
    """Lay out a site-packages tree the way force-include does, return its manifest."""
    pkg = tmp_path / "site-packages" / "research_framework"
    packaged = pkg / "_data" / "dist-templates" / "scaffold-manifest.json"
    packaged.parent.mkdir(parents=True)
    packaged.write_text(json.dumps(_MANIFEST), encoding="utf-8")
    # __file__ that walks up to site-packages on the way to / — no dist-templates/
    fake_module = pkg / "pipeline" / "scaffold_manifest.py"
    fake_module.parent.mkdir(parents=True)
    fake_module.write_text("", encoding="utf-8")
    return packaged


def test_a_wheel_install_resolves_its_packaged_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    packaged = _install_fake_wheel(tmp_path)
    fake_module = packaged.parents[2] / "pipeline" / "scaffold_manifest.py"
    monkeypatch.setattr(scaffold_manifest, "__file__", str(fake_module))
    monkeypatch.delenv("RESEARCH_VAULT_MANIFEST", raising=False)
    unrelated = tmp_path / "vault"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)

    assert scaffold_manifest.default_manifest_path() == packaged
    manifest = scaffold_manifest.load_manifest(scaffold_manifest.default_manifest_path())
    assert [entry.path for entry in manifest.entries] == ["settings.yaml"]


def test_the_env_override_still_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_wheel(tmp_path)
    override = tmp_path / "custom" / "manifest.json"
    override.parent.mkdir()
    override.write_text(json.dumps(_MANIFEST), encoding="utf-8")
    monkeypatch.setenv("RESEARCH_VAULT_MANIFEST", str(override))

    assert scaffold_manifest.default_manifest_path() == override
