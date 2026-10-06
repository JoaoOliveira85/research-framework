"""sources.yaml loader tests."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from research_framework.pipeline.source_bridge.discovery import ModuleManifest
from research_framework.pipeline.source_bridge.sources_loader import (
    ModuleSourcesFile,
    SourcesLoaderError,
    derive_source_id,
    enumerate_sources,
    load_module_sources,
)


def _code_manifest() -> ModuleManifest:
    return ModuleManifest(
        name="code",
        version="0.1.0",
        description="code",
        triggers=[],
        entry_point="extractor.py",
        default_value_tier="routine",
        schema_examples="few-shot.md",
        source_id_from={"github_repos": "path"},
    )


def test_module_sources_file_dataclass_fields() -> None:
    msf = ModuleSourcesFile(module="code", kinds={"github_repos": [{"path": "/x"}]})
    assert msf.module == "code"
    assert "github_repos" in msf.kinds


def test_load_module_sources_reads_only_vault_modules_yaml(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    mod = vault / "modules" / "code"
    mod.mkdir(parents=True)
    (mod / "sources.yaml").write_text(
        "github_repos:\n  - path: /repo\n",
        encoding="utf-8",
    )
    (vault / "research.spec.md").write_text(
        "data_sources:\n  - url: https://example.com\n",
        encoding="utf-8",
    )
    sources = load_module_sources(vault, "code", _code_manifest())
    assert len(sources) == 1
    assert sources[0].source_id == "/repo"


def test_derive_source_id_fail_fast_missing_source_id_from_field() -> None:
    manifest = _code_manifest()
    with pytest.raises(SourcesLoaderError):
        derive_source_id(manifest, "unknown_kind", {}, 0)


def test_derive_source_id_fail_fast_no_url_name_or_path() -> None:
    manifest = ModuleManifest(
        name="code",
        version="0.1.0",
        description="d",
        triggers=[],
        entry_point="extractor.py",
        default_value_tier="routine",
        schema_examples="few-shot.md",
        source_id_from={"items": "missing_field"},
    )
    with pytest.raises(SourcesLoaderError):
        derive_source_id(manifest, "items", {"label": "x"}, 0)


def test_duplicate_source_id_warn_first_wins(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    msf = ModuleSourcesFile(
        module="code",
        kinds={"github_repos": [{"path": "/a"}, {"path": "/a"}]},
    )
    sources = enumerate_sources(msf, _code_manifest())
    assert len(sources) == 1
    assert "Duplicate" in caplog.text


def test_missing_sources_yaml_returns_empty_with_warn(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    vault = tmp_path / "vault"
    (vault / "modules" / "code").mkdir(parents=True)
    assert load_module_sources(vault, "code", _code_manifest()) == []
    assert "Missing sources.yaml" in caplog.text


def test_invalid_sources_yaml_skips_module_with_run_report(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    vault = tmp_path / "vault"
    mod = vault / "modules" / "code"
    mod.mkdir(parents=True)
    (mod / "sources.yaml").write_text("[[[", encoding="utf-8")
    assert load_module_sources(vault, "code", _code_manifest()) == []


def test_sources_loader_happy_path_enumerates_records() -> None:
    msf = ModuleSourcesFile(
        module="code",
        kinds={"github_repos": [{"path": "/repo", "label": "R"}]},
    )
    sources = enumerate_sources(msf, _code_manifest())
    assert sources[0].source_id == "/repo"
    assert sources[0].label == "R"


def test_source_id_from_map_uses_manifest_field() -> None:
    manifest = ModuleManifest(
        name="yt",
        version="0.1.0",
        description="d",
        triggers=[],
        entry_point="extractor.py",
        default_value_tier="routine",
        schema_examples="few-shot.md",
        source_id_from={"youtube_channels": "url"},
    )
    sid = derive_source_id(
        manifest, "youtube_channels", {"url": "https://youtube.com/@x"}, 0
    )
    assert sid == "https://youtube.com/@x"
