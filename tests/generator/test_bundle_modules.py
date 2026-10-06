"""Wheel bundle includes framework modules tree."""

from __future__ import annotations

from pathlib import Path


def test_wheel_includes_framework_modules_tree() -> None:
    root = Path(__file__).resolve().parents[2]
    modules = root / "src" / "research_framework" / "modules"
    assert modules.is_dir()
    code = modules / "code" / "manifest.yaml"
    assert code.is_file()
