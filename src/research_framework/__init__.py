"""Speckit — knowledge vault generator."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("research-framework")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

__all__ = ("__version__",)
