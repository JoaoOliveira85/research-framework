"""Per-module ``sources.yaml`` enumeration (FR-013a/b)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from .discovery import ModuleManifest

logger = logging.getLogger(__name__)

ValueTier = Literal["routine", "important", "critical"]


class SourcesLoaderError(Exception):
    """FAIL-fast enumeration error (FR-013b)."""


@dataclass
class EnumeratedSource:
    module: str
    kind: str
    source_id: str
    record: dict[str, Any]
    index: int
    value_tier: ValueTier = "routine"
    label: str | None = None


@dataclass
class ModuleSourcesFile:
    module: str
    kinds: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def load_module_sources(
    vault_dir: Path,
    module_name: str,
    manifest: ModuleManifest,
) -> list[EnumeratedSource]:
    """Read only ``<vault>/modules/<name>/sources.yaml`` (FR-013a)."""
    path = vault_dir / "modules" / module_name / "sources.yaml"
    if not path.is_file():
        logger.warning("Missing sources.yaml for module %s — zero sources", module_name)
        return []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        logger.warning(
            "Invalid sources.yaml for module %s — skipping module: %s",
            module_name,
            exc,
        )
        return []
    if raw is None:
        return []
    if not isinstance(raw, dict):
        logger.warning("sources.yaml for module %s must be a mapping", module_name)
        return []
    sources_file = ModuleSourcesFile(module=module_name, kinds={})
    for kind, records in raw.items():
        if not isinstance(kind, str):
            continue
        if not isinstance(records, list):
            continue
        sources_file.kinds[kind] = [r for r in records if isinstance(r, dict)]
    return enumerate_sources(sources_file, manifest)


def enumerate_sources(
    sources_file: ModuleSourcesFile,
    manifest: ModuleManifest,
) -> list[EnumeratedSource]:
    seen: set[str] = set()
    out: list[EnumeratedSource] = []
    for kind, records in sources_file.kinds.items():
        for index, record in enumerate(records):
            source_id = derive_source_id(manifest, kind, record, index)
            if source_id in seen:
                logger.warning(
                    "Duplicate source_id %r in module %s — first wins",
                    source_id,
                    sources_file.module,
                )
                continue
            seen.add(source_id)
            tier_raw = record.get("value_tier", manifest.default_value_tier)
            value_tier: ValueTier = (
                tier_raw
                if tier_raw in ("routine", "important", "critical")
                else "routine"
            )
            out.append(
                EnumeratedSource(
                    module=sources_file.module,
                    kind=kind,
                    source_id=source_id,
                    record=record,
                    index=index,
                    value_tier=value_tier,
                    label=record.get("label"),
                )
            )
    return out


def derive_source_id(
    manifest: ModuleManifest,
    kind: str,
    record: dict[str, Any],
    index: int,
) -> str:
    """FAIL-fast ``source_id`` derivation (FR-013b)."""
    field_name = manifest.source_id_from.get(kind)
    if field_name is None:
        if record.get("url"):
            field_name = "url"
        elif record.get("path"):
            field_name = "path"
        elif record.get("name"):
            field_name = "name"
    if not field_name:
        raise SourcesLoaderError(
            f"Module {manifest.name!r} kind {kind!r} record {index}: "
            "cannot derive source_id — missing source_id_from mapping and "
            "no url/path/name on record"
        )
    if field_name not in record:
        raise SourcesLoaderError(
            f"Module {manifest.name!r} kind {kind!r} record {index}: "
            f"source_id_from field {field_name!r} missing on record"
        )
    value = str(record[field_name]).strip()
    if not value:
        raise SourcesLoaderError(
            f"Module {manifest.name!r} kind {kind!r} record {index}: "
            f"source_id_from field {field_name!r} is empty"
        )
    return value
