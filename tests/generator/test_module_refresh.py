"""Module refresh + settings migration tests."""

from __future__ import annotations

import yaml

from research_framework.generator.module_refresh import (
    copy_listed_modules,
    migrate_settings_for_030,
)


def test_upgrade_flips_source_extraction_enabled_and_modules(tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text(
        "pipeline:\n  max_cycles: 1\n", encoding="utf-8"
    )
    migrate_settings_for_030(vault)
    raw = yaml.safe_load((vault / "settings.yaml").read_text(encoding="utf-8"))
    assert raw["stages"]["source_extraction"]["enabled"] is True
    assert raw["modules"] == ["code"]
    migrate_settings_for_030(vault)
    raw2 = yaml.safe_load((vault / "settings.yaml").read_text(encoding="utf-8"))
    assert raw2["modules"] == ["code"]


def test_listed_modules_recopied_unlisted_skipped(tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "modules").mkdir()
    (vault / "modules" / "orphan").mkdir()
    (vault / "modules" / "orphan" / "marker.txt").write_text("stay\n", encoding="utf-8")
    copy_listed_modules(vault, ["code"], refresh=True)
    assert (vault / "modules" / "code" / "manifest.yaml").is_file()
    assert (vault / "modules" / "orphan" / "marker.txt").read_text() == "stay\n"


def test_refresh_preserves_existing_sources_yaml(tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    mod = vault / "modules" / "code"
    mod.mkdir(parents=True)
    custom = "sources:\n  - path: /custom\n"
    (mod / "sources.yaml").write_text(custom, encoding="utf-8")
    copy_listed_modules(vault, ["code"], refresh=True)
    assert (mod / "sources.yaml").read_text(encoding="utf-8") == custom
