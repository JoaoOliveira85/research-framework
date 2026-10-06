"""Tests for source_bridge preflight_runner telemetry (spec 038 US2)."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import yaml

from research_framework.pipeline.source_bridge.discovery import parse_manifest
from research_framework.pipeline.source_bridge.preflight_runner import run_preflight
from tests._helpers.fake_module import FAKE_PREFLIGHT_BLOCK, write_fake_extractor

_PF_SUCCESS = """
import json, sys
sys.stdin.read()
print(json.dumps({"schema_version": "1.0", "verdict": "success",
                  "corrections": [], "messages": []}))
"""


def _build_probe_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "_pipeline").mkdir()
    (vault / "research.spec.md").write_text("# Spec\n", encoding="utf-8")
    (vault / "settings.yaml").write_text(
        textwrap.dedent(
            """
            pipeline:
              max_cycles: 3
              budget_usd: 1.0
            modules: [demo]
            stages:
              source_extraction:
                enabled: true
                tier: basic
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    mod = vault / "modules" / "demo"
    mod.mkdir(parents=True)
    manifest = {
        "name": "demo",
        "version": "0.1.0",
        "description": "d",
        "triggers": [{"type": "path_pattern", "pattern": ".*"}],
        "entry_point": "extractor.py",
        "preflight": FAKE_PREFLIGHT_BLOCK,
        "default_value_tier": "routine",
        "schema_examples": "few-shot.md",
    }
    (mod / "manifest.yaml").write_text(yaml.dump(manifest), encoding="utf-8")
    (mod / "sources.yaml").write_text(
        yaml.dump({"sources": [{"path": "/tmp/repo", "value_tier": "routine"}]}),
        encoding="utf-8",
    )
    write_fake_extractor(mod)
    (mod / "preflight.py").write_text(_PF_SUCCESS.strip() + "\n", encoding="utf-8")
    return vault


def test_preflight_json_records_module_probes_telemetry(tmp_path: Path) -> None:
    vault = _build_probe_vault(tmp_path)
    manifest = parse_manifest(vault / "modules" / "demo" / "manifest.yaml")
    result = run_preflight(vault, manifest)
    assert result.verdict == "success"

    probe_path = vault / "_pipeline" / "preflight.json"
    assert probe_path.is_file()
    data = json.loads(probe_path.read_text(encoding="utf-8"))
    probes = data.get("module_probes")
    assert isinstance(probes, list)
    assert len(probes) == 1
    entry = probes[0]
    for key in (
        "module",
        "auth_probe_status",
        "auth_probe_ms",
        "connectivity_status",
        "connectivity_ms",
        "errors",
    ):
        assert key in entry
    assert entry["module"] == "demo"
    assert entry["auth_probe_status"] == "skip"
    assert entry["connectivity_status"] == "ok"
    assert entry["errors"] == []
