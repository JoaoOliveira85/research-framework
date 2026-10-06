"""Optional live parity smoke for the benchmark live path (spec 056 T036).

MANUAL ONLY — carries ``@pytest.mark.live_llm`` so it is skipped by default and by
every CI gate. Run explicitly with real credentials:

    pytest tests/benchmark/test_benchmark_live_smoke.py --live-llm

It dispatches exactly ONE scoped cell through ``runner.live_dispatch`` (real
``agent_call.py`` subprocess) and asserts the cell lands in a terminal state with a
cost-provenance field — proving the live seam matches the hermetic contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework.benchmark import matrix as M
from research_framework.benchmark import runner

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "benchmark"


@pytest.mark.live_llm
def test_single_cell_live_dispatch(tmp_path: Path) -> None:
    cells = M.apply_scope(
        M.expand_cells(M.load_matrix(_FIXTURE / "benchmark-matrix.yaml")),
        tasks=["verifier"],
        executors=["claude"],
        models=["haiku"],
    )
    assert len(cells) == 1
    cell = cells[0]
    out = runner.live_dispatch(cell, fixture_dir=_FIXTURE, cell_dir=tmp_path / cell.key)
    assert out.status in {"ok", "skipped", "failed"}
    assert out.cost_source in {"sidecar", "n/a"}
    if out.status == "ok":
        assert out.latency_ms is not None
