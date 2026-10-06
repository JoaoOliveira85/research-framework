"""Loads and validates dist-templates/scaffold-manifest.json."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

__all__ = [
    "ManifestEntry",
    "ScaffoldManifest",
    "load_manifest",
    "default_manifest_path",
]

_KIND = Literal["markdown", "yaml", "json", "shell", "python", "other"]
_MANIFEST_ENV_VAR = "RESEARCH_VAULT_MANIFEST"


@dataclass(frozen=True)
class ManifestEntry:
    path: str
    kind: _KIND
    template_version: int
    rendered_sha256: str
    is_user_owned_after_first_write: bool = False


@dataclass(frozen=True)
class ScaffoldManifest:
    framework_version: int
    generator_commit: str
    generated_at: str
    entries: tuple[ManifestEntry, ...]


def default_manifest_path() -> Path:
    """Return the canonical path to the scaffold manifest."""
    env_override = os.environ.get(_MANIFEST_ENV_VAR)
    if env_override:
        return Path(env_override)
    # Walk up from this file to find the repo root containing dist-templates/
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "dist-templates" / "scaffold-manifest.json"
        if candidate.exists():
            return candidate
    # Fallback: relative to CWD (installed wheel, CI)
    return Path("dist-templates") / "scaffold-manifest.json"


def load_manifest(path: Path) -> ScaffoldManifest:
    """Load and validate a scaffold manifest from *path*.

    Raises FileNotFoundError when the file is missing (with a message naming
    the build step that produces it).
    Raises ValueError when the file fails basic schema validation.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Scaffold manifest not found at '{path}'. "
            "Run 'python scripts/build_scaffold_manifest.py' (build_scaffold_manifest) "
            "to generate it before using the migrator."
        )

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Scaffold manifest at '{path}' is not valid JSON: {exc}"
        ) from exc

    required = {"framework_version", "generator_commit", "generated_at", "entries"}
    missing = required - data.keys()
    if missing:
        raise ValueError(
            f"Scaffold manifest at '{path}' is missing required fields: {missing}"
        )

    entries = tuple(
        ManifestEntry(
            path=e["path"],
            kind=e["kind"],
            template_version=e["template_version"],
            rendered_sha256=e["rendered_sha256"],
            is_user_owned_after_first_write=e.get(
                "is_user_owned_after_first_write", False
            ),
        )
        for e in data["entries"]
    )

    return ScaffoldManifest(
        framework_version=data["framework_version"],
        generator_commit=data["generator_commit"],
        generated_at=data["generated_at"],
        entries=entries,
    )
