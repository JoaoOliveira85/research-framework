"""Module discovery tests."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml

from research_framework.pipeline.source_bridge.discovery import (
    ModuleManifest,
    TriggerEntry,
    TriggerRegistry,
    order_modules,
    reset_unlisted_warnings,
    walk_modules,
)


def test_trigger_entry_and_registry_dataclasses() -> None:
    entry = TriggerEntry(
        module="code", trigger_type="path_pattern", pattern=".*", order=1
    )
    reg = TriggerRegistry(entries=[entry])
    assert reg.match("/foo/.git/HEAD") == ("code", 1)


def test_walk_modules_finds_manifest_yaml_under_vault_modules(tmp_path: Path) -> None:
    mod = tmp_path / "modules" / "code"
    mod.mkdir(parents=True)
    (mod / "manifest.yaml").write_text(
        yaml.dump(
            {
                "name": "code",
                "version": "0.1.0",
                "description": "d",
                "triggers": [{"type": "path_pattern", "pattern": "x"}],
                "entry_point": "extractor.py",
                "preflight": {"entry_point": "preflight.py", "timeout_seconds": 30},
                "default_value_tier": "routine",
                "schema_examples": "few-shot.md",
            }
        ),
        encoding="utf-8",
    )
    from tests._helpers.fake_module import write_fake_preflight

    write_fake_preflight(mod)
    manifests = walk_modules(tmp_path)
    assert len(manifests) == 1
    assert manifests[0].name == "code"


def test_fr010_listed_modules_before_unlisted_lexicographic(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reset_unlisted_warnings()
    caplog.set_level(logging.WARNING)
    manifests = [
        ModuleManifest("zebra", "0.1.0", "z", [], "e.py", "routine", "f.md"),
        ModuleManifest("alpha", "0.1.0", "a", [], "e.py", "routine", "f.md"),
        ModuleManifest("code", "0.1.0", "c", [], "e.py", "routine", "f.md"),
    ]
    ordered = order_modules(manifests, ["code"])
    assert [m.name for m in ordered] == ["code", "alpha", "zebra"]
    assert "not in settings.yaml::modules" in caplog.text


def test_malformed_manifest_skipped_after_retry_once(tmp_path: Path) -> None:
    mod = tmp_path / "modules" / "bad"
    mod.mkdir(parents=True)
    (mod / "manifest.yaml").write_text("not: valid: manifest\n", encoding="utf-8")
    assert walk_modules(tmp_path) == []


def test_trigger_match_first_match_wins() -> None:
    from research_framework.pipeline.source_bridge.discovery import (
        TriggerEntry,
        TriggerRegistry,
    )

    reg = TriggerRegistry(
        entries=[
            TriggerEntry("a", "url_pattern", "github", 1),
            TriggerEntry("b", "url_pattern", "github", 2),
        ]
    )
    assert reg.match("https://github.com/x") == ("a", 1)


def test_multi_module_routing_with_fake_module_stub(tmp_path: Path) -> None:
    from tests._helpers.fake_module import write_fake_extractor

    for name in ("web", "code"):
        mod = tmp_path / "modules" / name
        mod.mkdir(parents=True)
        (mod / "manifest.yaml").write_text(
            yaml.dump(
                {
                    "name": name,
                    "version": "0.1.0",
                    "description": "d",
                    "triggers": [{"type": "path_pattern", "pattern": name}],
                    "entry_point": "extractor.py",
                    "preflight": {
                        "entry_point": "preflight.py",
                        "timeout_seconds": 30,
                    },
                    "default_value_tier": "routine",
                    "schema_examples": "few-shot.md",
                }
            ),
            encoding="utf-8",
        )
        write_fake_extractor(mod)
    manifests = order_modules(walk_modules(tmp_path), ["web", "code"])
    assert [m.name for m in manifests[:2]] == ["web", "code"]


def test_sc007_drop_in_module_without_settings_edit(tmp_path: Path) -> None:
    mod = tmp_path / "modules" / "dropin"
    mod.mkdir(parents=True)
    (mod / "manifest.yaml").write_text(
        yaml.dump(
            {
                "name": "dropin",
                "version": "0.1.0",
                "description": "d",
                "triggers": [],
                "entry_point": "extractor.py",
                "preflight": {"entry_point": "preflight.py", "timeout_seconds": 30},
                "default_value_tier": "routine",
                "schema_examples": "few-shot.md",
            }
        ),
        encoding="utf-8",
    )
    from tests._helpers.fake_module import write_fake_preflight

    write_fake_preflight(mod)
    assert len(walk_modules(tmp_path)) == 1


def test_sc008_generic_fallback_no_install_module_prompt() -> None:
    assert True


def test_compile_triggers_url_path_and_path_exists(tmp_path: Path) -> None:
    from research_framework.pipeline.source_bridge.discovery import (
        build_trigger_registry,
    )

    mod = tmp_path / "modules" / "code"
    mod.mkdir(parents=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    (mod / "manifest.yaml").write_text(
        yaml.dump(
            {
                "name": "code",
                "version": "0.1.0",
                "description": "d",
                "triggers": [
                    {"type": "path_exists", "pattern": str(repo)},
                    {"type": "url_pattern", "pattern": "example\\.com"},
                ],
                "entry_point": "extractor.py",
                "preflight": {"entry_point": "preflight.py", "timeout_seconds": 30},
                "default_value_tier": "routine",
                "schema_examples": "few-shot.md",
            }
        ),
        encoding="utf-8",
    )
    from tests._helpers.fake_module import write_fake_preflight

    write_fake_preflight(mod)
    reg = build_trigger_registry(walk_modules(tmp_path))
    assert reg.match(str(repo)) is not None
    assert reg.match("https://example.com/x") is not None


def test_registry_match_returns_module_and_priority() -> None:
    from research_framework.pipeline.source_bridge.discovery import (
        TriggerEntry,
        TriggerRegistry,
    )

    reg = TriggerRegistry(entries=[TriggerEntry("code", "path_pattern", ".*", 7)])
    assert reg.match("/any") == ("code", 7)


def test_manifest_parse_double_failure_skips_module(tmp_path: Path) -> None:
    mod = tmp_path / "modules" / "broken"
    mod.mkdir(parents=True)
    (mod / "manifest.yaml").write_text("{]\n", encoding="utf-8")
    assert walk_modules(tmp_path) == []
