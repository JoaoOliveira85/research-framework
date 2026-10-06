"""`parse_manifest` enforces the mandatory `preflight` block (spec 051 FR4,
T032).

A manifest without a `preflight` block — or whose `preflight.entry_point` names
a file that doesn't exist — must raise `ValueError`. The existing
`walk_modules` -> `isolated_call` fail-closed path turns that into a
skipped-module WARN, never a cycle crash.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework.pipeline.source_bridge.discovery import (
    parse_manifest,
    reset_unlisted_warnings,
    walk_modules,
)

_BASE = """name: {name}
version: 0.1.0
description: demo module
triggers:
  - type: url_pattern
    pattern: "x"
entry_point: extractor.py
default_value_tier: routine
schema_examples: few-shot.md
"""

_PREFLIGHT_BLOCK = "preflight:\n  entry_point: preflight.py\n  timeout_seconds: 30\n"


def _write_module(
    tmp_path: Path,
    *,
    name: str = "demo",
    preflight_block: str = _PREFLIGHT_BLOCK,
    with_preflight_file: bool = True,
) -> Path:
    mod = tmp_path / "modules" / name
    mod.mkdir(parents=True, exist_ok=True)
    (mod / "manifest.yaml").write_text(
        _BASE.format(name=name) + preflight_block, encoding="utf-8"
    )
    (mod / "extractor.py").write_text("# stub\n", encoding="utf-8")
    if with_preflight_file:
        (mod / "preflight.py").write_text("# stub\n", encoding="utf-8")
    return mod


def test_missing_preflight_block_raises(tmp_path: Path) -> None:
    mod = _write_module(tmp_path, preflight_block="")
    with pytest.raises(ValueError, match="preflight"):
        parse_manifest(mod / "manifest.yaml")


def test_preflight_entry_point_file_missing_raises(tmp_path: Path) -> None:
    mod = _write_module(tmp_path, with_preflight_file=False)
    with pytest.raises(ValueError, match="preflight"):
        parse_manifest(mod / "manifest.yaml")


def test_valid_preflight_block_parses(tmp_path: Path) -> None:
    mod = _write_module(tmp_path)
    manifest = parse_manifest(mod / "manifest.yaml")
    assert manifest.preflight["entry_point"] == "preflight.py"
    assert manifest.preflight.get("timeout_seconds") == 30


def test_walk_modules_skips_module_missing_preflight(tmp_path: Path) -> None:
    reset_unlisted_warnings()
    _write_module(tmp_path, name="good")
    _write_module(tmp_path, name="broken", preflight_block="")
    names = {m.name for m in walk_modules(tmp_path)}
    assert "good" in names
    assert "broken" not in names  # fail-closed: skipped, cycle continues
