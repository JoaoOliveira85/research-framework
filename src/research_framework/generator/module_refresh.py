"""Framework module copy + settings migration for spec 020."""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from ..pipeline.source_bridge.discovery import parse_manifest
from ..pipeline.source_bridge.schema_gen import run as schema_gen_run


def framework_modules_src() -> Path:
    return Path(__file__).resolve().parents[1] / "modules"


def copy_listed_modules(
    vault_dir: Path,
    listed_modules: list[str],
    *,
    refresh: bool = True,
) -> None:
    """D6: copy only ``settings.yaml::modules`` entries; preserve user-owned paths."""
    if not refresh:
        return
    src_root = framework_modules_src()
    for name in listed_modules:
        src = src_root / name
        if not src.is_dir():
            continue
        manifest_path = src / "manifest.yaml"
        if manifest_path.is_file():
            parse_manifest(manifest_path)
        dest = vault_dir / "modules" / name
        backups: dict[str, bytes] = {}
        if dest.is_dir() and manifest_path.is_file():
            manifest = parse_manifest(manifest_path)
            for rel in manifest.user_owned:
                owned = dest / rel
                if owned.is_file():
                    backups[rel] = owned.read_bytes()
        shutil.copytree(src, dest, dirs_exist_ok=True)
        for rel, data in backups.items():
            (dest / rel).write_bytes(data)
        template = src / "sources.yaml.template"
        dest_sources = dest / "sources.yaml"
        if template.is_file() and not dest_sources.is_file():
            shutil.copy2(template, dest_sources)


def migrate_settings_for_030(vault_dir: Path) -> None:
    """Idempotent 0.3.0 flip: enable source_extraction + default modules."""
    settings_path = vault_dir / "settings.yaml"
    if not settings_path.is_file():
        return
    raw = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    stages = raw.setdefault("stages", {})
    extraction = stages.setdefault("source_extraction", {})
    if isinstance(extraction, dict):
        extraction.setdefault("enabled", True)
    if "modules" not in raw:
        raw["modules"] = ["code"]
    settings_path.write_text(yaml.dump(raw, default_flow_style=False), encoding="utf-8")


def run_schema_gen_for_modules(vault_dir: Path, modules: list[str]) -> None:
    spec_path = vault_dir / "research.spec.md"
    for module in modules:
        schema_gen_run(vault_dir, module, spec_path)
