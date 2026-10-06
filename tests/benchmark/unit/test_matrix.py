"""Spec 064 (US6) — opencode as a benchmark cell + optional executor label.

opencode is dispatchable (Phase 2 registered it), so it must appear in
`valid_runtimes()` and sweep arbitrary models. The optional `label` lets the
same runtime be swept under several configs in one readable report.
"""

from __future__ import annotations

from pathlib import Path

from research_framework.benchmark import matrix as M
from research_framework.benchmark.runner import RawCellOutput, _cell_result


def test_opencode_in_valid_runtimes() -> None:
    """FR-018: opencode is a dispatchable benchmark runtime (guard test)."""
    assert "opencode" in M.valid_runtimes()


def test_executor_label_replaces_runtime_in_cell_key() -> None:
    cell = M.Cell(
        task="scout",
        executor="opencode",
        model="ollama/qwen",
        label="opencode-local-qwen",
    )
    assert cell.key == "scout__opencode-local-qwen__ollama/qwen"


def test_executor_absent_label_key_byte_identical() -> None:
    """FR-020: no label ⇒ key is byte-identical to the pre-064 form."""
    cell = M.Cell(task="scout", executor="opencode", model="ollama/qwen")
    assert cell.key == "scout__opencode__ollama/qwen"


def test_two_opencode_blocks_distinct_labels_produce_distinct_cells() -> None:
    """FR-019/020: two opencode configs (local + hosted) coexist as distinct,
    labeled cells."""
    raw = [
        {"runtime": "opencode", "label": "oc-local", "models": ["ollama/qwen"]},
        {"runtime": "opencode", "label": "oc-hosted", "models": ["openai/gpt-4o"]},
    ]
    executors = M._parse_executors(raw, M.valid_runtimes())
    matrix = M.Matrix(path=Path("x"), tasks=("scout",), executors=executors)
    keys = [c.key for c in M.expand_cells(matrix)]
    assert len(set(keys)) == 2
    assert "scout__oc-local__ollama/qwen" in keys
    assert "scout__oc-hosted__openai/gpt-4o" in keys


def test_executor_label_surfaces_in_reporter_row() -> None:
    cell = M.Cell(
        task="scout", executor="opencode", model="ollama/qwen", label="oc-local"
    )
    raw = RawCellOutput(
        status="ok", stdout="", cost_usd=0.0, cost_source="runtime", latency_ms=10
    )
    row = _cell_result(cell, raw, None, "cells/x")
    assert row["executor"] == "oc-local"
