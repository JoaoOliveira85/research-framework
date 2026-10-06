"""Read-only: vault root → VaultBaseline. Only paths listed in the manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .scaffold_models import FileBaseline, ScaffoldManifest, VaultBaseline
from .template_drift import read_template_version

__all__ = ["read_vault_baseline"]


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read_framework_version(vault_root: Path) -> int | None:
    spec_parse = vault_root / "_pipeline" / "spec-parse.json"
    if not spec_parse.exists():
        return None
    try:
        data = json.loads(spec_parse.read_text(encoding="utf-8"))
        val = data.get("framework_version")
        if isinstance(val, int):
            return val
    except (json.JSONDecodeError, OSError):
        pass
    return None


def read_vault_baseline(vault_root: Path, manifest: ScaffoldManifest) -> VaultBaseline:
    """Snapshot the on-disk state of every path listed in *manifest*.

    Files outside the manifest are NOT scanned: they are user content by
    definition and the migrator never touches them.
    """
    files: dict[str, FileBaseline] = {}
    for entry in manifest.entries:
        abs_path = vault_root / entry.path
        if abs_path.exists() and abs_path.is_file():
            raw = abs_path.read_bytes()
            files[entry.path] = FileBaseline(
                path=entry.path,
                content_sha256=_sha256(raw),
                template_version=read_template_version(abs_path),
                exists=True,
            )
        else:
            files[entry.path] = FileBaseline(
                path=entry.path,
                content_sha256="",
                template_version=None,
                exists=False,
            )

    return VaultBaseline(
        vault_root=vault_root,
        from_framework_version=_read_framework_version(vault_root),
        files=files,
    )
