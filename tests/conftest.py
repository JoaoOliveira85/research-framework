"""Shared pytest fixtures for research_framework test suite."""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the `--live-llm` opt-in flag.

    Tests carrying `@pytest.mark.live_llm` make real LLM CLI calls (real
    money, network-dependent, slow). They are SKIPPED by default and only
    run when explicitly opted into via `--live-llm` or `LIVE_LLM=1` in the
    environment. This is the safe default — the addopts-based alternative
    (`-m "not live_llm"`) is overridden the moment anyone runs
    `pytest -m "not e2e"`, which silently re-enables live calls.
    """
    parser.addoption(
        "--live-llm",
        action="store_true",
        default=False,
        help=(
            "Opt-in: run @pytest.mark.live_llm tests. These make real LLM "
            "CLI calls (real money). Same effect as setting LIVE_LLM=1 in "
            "the environment."
        ),
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip `@pytest.mark.live_llm` tests unless explicitly opted in.

    Composes correctly with any `-m` filter the caller supplies (because
    skip-markers are applied at collection time, not at selection time).
    """
    opted_in = config.getoption("--live-llm") or os.environ.get("LIVE_LLM") == "1"
    if opted_in:
        return
    skip_live = pytest.mark.skip(
        reason="live_llm test skipped by default — opt in with `--live-llm` or `LIVE_LLM=1`."
    )
    for item in items:
        if "live_llm" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture
def vault_dir() -> Path:
    """Path to the read-only test vault fixture."""
    return FIXTURES_DIR / "vault"


@pytest.fixture
def tmp_vault_dir(tmp_path: Path, vault_dir: Path) -> Iterator[Path]:
    """Writable copy of the test vault for tests that modify files."""
    dest = tmp_path / "vault"
    shutil.copytree(vault_dir, dest)
    yield dest


@pytest.fixture
def sample_spec_path() -> Path:
    """Path to the minimal valid sample spec."""
    return FIXTURES_DIR / "sample-spec.md"


@pytest.fixture
def cycle_reports_dir() -> Path:
    """Directory containing cycle report fixtures."""
    return FIXTURES_DIR / "cycle-reports"


@pytest.fixture
def stubs_dir() -> Path:
    """Directory containing stub executables (e.g., fake claude CLI)."""
    return FIXTURES_DIR / "stubs"


@pytest.fixture
def cycle_reports_v2_dir() -> Path:
    """Directory containing v2 (code-first) cycle report fixtures."""
    return FIXTURES_DIR / "cycle-reports" / "v2"


@pytest.fixture
def repo_fixtures_dir() -> Path:
    """Directory containing mock repo fixtures for repo_scan tests."""
    return FIXTURES_DIR / "repos"


@pytest.fixture
def vault_code_first_fixtures_dir() -> Path:
    """Directory containing code-first note fixtures (drift tests)."""
    return FIXTURES_DIR / "vault-code-first"
