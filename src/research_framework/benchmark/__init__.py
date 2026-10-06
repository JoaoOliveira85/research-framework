"""Spec 056 — Executor × Model benchmarking harness (eval tooling).

Standalone, operator-invoked sweep over a ``{task × executor × model}`` matrix
against a frozen fixture vault. NOT a hermetic test surface and NOT imported by
any pipeline hot path (FR-001 / SC-007): the live entrypoint is
``scripts/benchmark_executors.py``; the modules here are the testable core.
"""
