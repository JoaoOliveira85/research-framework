"""Maintainer + per-vault scripts package.

Most files in ``scripts/`` are executable standalone scripts (run via
``python scripts/<name>.py`` or as subprocesses). This ``__init__.py``
exists so that *importable* helper modules — currently
``scripts.foreman`` (the test-coverage verifier per ADR-0010) — can be
referenced as ``scripts.<subpackage>`` from tests and other tooling
without the existing standalone scripts being affected.

Standalone scripts in this directory are NOT imported by the framework
at runtime; they remain runnable directly.
"""
