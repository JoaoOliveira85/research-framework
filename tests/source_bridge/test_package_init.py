"""Package public API smoke tests."""

from __future__ import annotations

import research_framework as rf
import research_framework.pipeline.source_bridge as sb


def test_source_bridge_public_api_importable() -> None:
    assert "BRIDGE_VERSION" in sb.__all__
    assert "StaleManualSchemaError" in sb.__all__
    assert "run_extraction" in sb.__all__
    assert sb.BRIDGE_VERSION


def test_bridge_version_matches_package_version() -> None:
    from importlib.metadata import version

    assert sb.BRIDGE_VERSION == version("research-framework")


def test_root_package_version_matches_installed_package() -> None:
    """`research_framework.__version__` must source from importlib.metadata.

    Regression guard for the 0.4.0 fix: the constant was hard-coded at
    "0.2.29" through seven releases. It must now reflect the installed
    package version OR the documented fallback for source-only checkouts.
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        expected = version("research-framework")
    except PackageNotFoundError:
        expected = "0.0.0+unknown"
    assert rf.__version__ == expected
