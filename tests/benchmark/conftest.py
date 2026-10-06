"""Shared fixtures for the spec-056 benchmark harness tests (hermetic only)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

BENCHMARK_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "benchmark"


@pytest.fixture
def fixture_dir() -> Path:
    return BENCHMARK_FIXTURE


@pytest.fixture
def matrix_path() -> Path:
    return BENCHMARK_FIXTURE / "benchmark-matrix.yaml"


@pytest.fixture
def manifest() -> dict:
    return json.loads((BENCHMARK_FIXTURE / "manifest.json").read_text(encoding="utf-8"))
