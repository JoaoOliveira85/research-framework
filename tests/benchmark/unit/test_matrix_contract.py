"""Matrix load / validation / scope / expansion contract (spec 056 T007–T010, T030).

Negative cases inject a fixed ``runtimes`` set so they don't depend on the live
``agent_call.py`` registry; the positive default-matrix test exercises the real
``valid_runtimes()`` path so a registry regression (e.g. dropping ``ollama``) is
caught here too.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework.benchmark import matrix as M

_RUNTIMES = {"claude", "codex", "cursor-agent", "ollama", "python"}


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "matrix.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_default_matrix_three_tasks(matrix_path: Path) -> None:
    """Default fixture matrix → the v1 task trio + claude/codex executors (FR-016, SC-009)."""
    mtx = M.load_matrix(matrix_path)
    assert mtx.tasks == ("scout", "note-writer", "verifier")
    runtimes = {e.runtime for e in mtx.executors}
    assert {"claude", "codex"} <= runtimes
    # 2 executors × (2 + 2) models × 3 tasks = 12 cells.
    assert len(M.expand_cells(mtx)) == 12


def test_unknown_task_rejected(tmp_path: Path) -> None:
    """A task id outside the v1 trio is a load error, not a silent skip (T008)."""
    path = _write(
        tmp_path,
        "tasks: [ask]\nexecutors:\n  - runtime: claude\n    models: [sonnet]\n",
    )
    with pytest.raises(M.MatrixError, match="unknown task"):
        M.load_matrix(path, runtimes=_RUNTIMES)


def test_unknown_runtime_rejected(tmp_path: Path) -> None:
    """A runtime not dispatchable by agent_call is a load error (typo guard, T009)."""
    path = _write(
        tmp_path,
        "tasks: [scout]\nexecutors:\n  - runtime: gpt4turbo\n    models: [default]\n",
    )
    with pytest.raises(M.MatrixError, match="unknown runtime"):
        M.load_matrix(path, runtimes=_RUNTIMES)


def test_ollama_runtime_is_valid(tmp_path: Path) -> None:
    """spec-047 ``ollama`` (an HTTP runtime, not a CLI adapter) must load (regression)."""
    path = _write(
        tmp_path,
        "tasks: [scout]\nexecutors:\n  - runtime: ollama\n    models: [qwen3:14b]\n",
    )
    # Real registry path — proves valid_runtimes() unions _HTTP_RUNTIMES.
    mtx = M.load_matrix(path)
    assert mtx.executors[0].runtime == "ollama"


def test_scope_filters_cells(matrix_path: Path) -> None:
    """``--task scout --model haiku`` reduces the 12-cell product (FR-002, T010)."""
    cells = M.expand_cells(M.load_matrix(matrix_path))
    scoped = M.apply_scope(cells, tasks=["scout"], models=["haiku"])
    assert 0 < len(scoped) < len(cells)
    assert all(c.task == "scout" and c.model == "haiku" for c in scoped)


def test_add_model_expands_cells(tmp_path: Path) -> None:
    """Appending one model string adds exactly one cell per task — no code (FR-010, T030)."""
    base = _write(
        tmp_path,
        "tasks: [scout, note-writer, verifier]\n"
        "executors:\n  - runtime: claude\n    models: [sonnet, haiku]\n",
    )
    n_base = len(M.expand_cells(M.load_matrix(base, runtimes=_RUNTIMES)))
    bigger = tmp_path / "bigger.yaml"
    bigger.write_text(
        "tasks: [scout, note-writer, verifier]\n"
        "executors:\n  - runtime: claude\n    models: [sonnet, haiku, opus]\n",
        encoding="utf-8",
    )
    n_bigger = len(M.expand_cells(M.load_matrix(bigger, runtimes=_RUNTIMES)))
    assert n_bigger == n_base + 3  # one new model × three tasks
