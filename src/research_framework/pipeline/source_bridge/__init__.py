"""Source-bridge pipeline stage (spec 020)."""

from __future__ import annotations

from importlib.metadata import version

__all__ = [
    "BRIDGE_VERSION",
    "StaleManualSchemaError",
    "run_extraction",
]

BRIDGE_VERSION = version("research-framework")

from .errors import StaleManualSchemaError  # noqa: E402
from .orchestrator import run_extraction  # noqa: E402
