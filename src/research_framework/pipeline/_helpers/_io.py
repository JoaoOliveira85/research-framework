"""Shared pure filesystem helpers (SC-001 sub-leaf under state concern)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .. import atomic_write


def _state_write(state_path: Path, payload: dict) -> None:
    """Atomically merge ``payload`` into ``_pipeline/state.json``.

    Read-modify-write: loads any existing JSON, applies ``payload`` as a
    top-level dict update, then persists via the canonical
    :mod:`research_framework.pipeline.atomic_write` helpers (mkstemp +
    fsync + ``os.replace`` + best-effort parent fsync). Previously used
    an ad-hoc ``tmp = .json.tmp; tmp.replace`` pattern.
    """
    existing: dict = {}
    if state_path.is_file():
        try:
            raw = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                existing = raw
        except json.JSONDecodeError:
            existing = {}
    existing.update(payload)
    atomic_write.write_json(state_path, existing)


def _vault_notes_content_sha1(vault_dir: Path) -> str:
    dv = vault_dir / "data_vault"
    if not dv.is_dir():
        return hashlib.sha1(b"").hexdigest()
    h = hashlib.sha1()
    for p in sorted(dv.rglob("*.md")):
        try:
            rel = p.relative_to(dv)
        except ValueError:
            continue
        if rel.name in ("_index.md", "_concepts.md", "_graph.md"):
            continue
        if "_templates" in rel.parts:
            continue
        try:
            blob = rel.as_posix().encode() + b"\0" + p.read_bytes()
        except OSError:
            continue
        h.update(blob)
    return h.hexdigest()


def _discover_new_markdown_files(data_vault: Path, before: set[str]) -> list[Path]:
    if not data_vault.is_dir():
        return []
    new_paths: list[Path] = []
    for p in sorted(data_vault.rglob("*.md")):
        if p.name in ("_index.md", "_concepts.md", "_graph.md"):
            continue
        try:
            rel = p.relative_to(data_vault)
        except ValueError:
            continue
        if "_templates" in rel.parts:
            continue
        key = rel.as_posix()
        if key not in before and p.name not in before:
            new_paths.append(p)
    return new_paths
