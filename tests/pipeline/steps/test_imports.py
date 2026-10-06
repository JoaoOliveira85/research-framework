"""Circular-import guard for pipeline/steps (spec 025 T058a)."""

from __future__ import annotations

import pytest


def test_pipeline_steps_imports_resolve() -> None:
    import research_framework.pipeline.steps  # noqa: F401


@pytest.mark.parametrize("mod", ["scout", "research", "postprocess"])
def test_step_module_imports_resolve(mod: str) -> None:
    __import__(f"research_framework.pipeline.steps.{mod}")
