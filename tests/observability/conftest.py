"""Shared fixtures for spec 048 observability tests.

Authority: ``specs/048-observability-v1/tasks.md`` T006.

The ``reset_root_logger`` fixture is autouse + function-scoped so each test
in ``tests/observability/`` starts with a known root-logger state. Without
it, tests that call ``_configure_root_logger`` would leak handlers across
the suite and break pytest's own ``caplog`` capture.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

_FIXTURES_DIR = Path(__file__).resolve().parent / "_fixtures"


@pytest.fixture(autouse=True)
def reset_root_logger() -> object:
    """Snapshot ``logging.root.handlers`` + level around each test.

    Tests in this directory often add/remove handlers to test the
    ``_configure_root_logger`` idempotency contract. Without this
    snapshot, pytest's own log-capture handler would either be lost or
    duplicated across tests, producing flaky pass/fail behaviour.
    """
    saved_handlers = list(logging.root.handlers)
    saved_level = logging.root.level
    saved_disable = logging.root.manager.disable
    yield
    # Restore handlers exactly (preserve identity, not just shape).
    logging.root.handlers = saved_handlers
    logging.root.setLevel(saved_level)
    logging.disable(saved_disable)


@pytest.fixture()
def sentinel_extractor_path() -> Path:
    """Absolute path to the sentinel extractor fixture (spec 048 T003)."""
    path = _FIXTURES_DIR / "sentinel_extractor.py"
    assert path.exists(), f"sentinel_extractor.py missing at {path}"
    return path


@pytest.fixture()
def tmp_vault_pipeline_dir(tmp_path: Path) -> Path:
    """Create ``<tmp>/_pipeline/cycles/cycle-001/`` and return its path.

    Used by bridge-log creation tests so each test gets a fresh vault-like
    layout without colliding with siblings.
    """
    cycle_dir = tmp_path / "_pipeline" / "cycles" / "cycle-001"
    cycle_dir.mkdir(parents=True, exist_ok=True)
    return cycle_dir
