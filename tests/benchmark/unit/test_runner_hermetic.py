"""Hermetic matrix sweep + skip-isolation (spec 056; T021, T022, T031).

All dispatch here is fixture replay — NO live LLM, no subprocess (Principle IV /
SC-007). The live path (``runner.live_dispatch``) is exercised only by the opt-in
``@pytest.mark.live_llm`` smoke test.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from research_framework.benchmark import gating, reporter, runner
from research_framework.benchmark import matrix as M


def _run(
    fixture_dir: Path,
    matrix_path: Path,
    manifest: dict,
    tmp_path: Path,
    dispatch_fn=runner.hermetic_dispatch,
) -> dict:
    cells = M.expand_cells(M.load_matrix(matrix_path))
    run_dir = reporter.create_run_dir(tmp_path, reporter.run_id_now())
    return runner.run_matrix(
        cells,
        fixture_dir=fixture_dir,
        run_dir=run_dir,
        manifest=manifest,
        matrix_path=matrix_path,
        dispatch_fn=dispatch_fn,
        ack_mode="dry-run",
    )


def _best_executor(cells: list[dict], task: str) -> str:
    task_cells = [
        c for c in cells if c["task"] == task and c.get("quality") is not None
    ]
    return max(task_cells, key=lambda c: c["quality"])["executor"]


def test_full_matrix_fake_agent(
    fixture_dir: Path, matrix_path: Path, manifest: dict, tmp_path: Path
) -> None:
    """2×2×3 dry-run → 12 ok cells + report.json/report.md + per-cell artifacts (SC-001)."""
    report = _run(fixture_dir, matrix_path, manifest, tmp_path)
    cells = report["cells"]
    assert len(cells) == 12
    assert all(c["status"] == "ok" for c in cells)

    run_dir = reporter.benchmarks_root(tmp_path) / report["run_id"]
    assert (run_dir / "report.json").is_file()
    assert (run_dir / "report.md").is_file()
    for c in cells:
        cell_dir = run_dir / c["artifact_dir"]
        assert (cell_dir / "stdout.txt").is_file()
        assert (cell_dir / "scored.json").is_file()
        # Hermetic responses carry recorded cost + latency.
        assert c["cost_source"] == "sidecar"
        assert c["latency_ms"] is not None


def test_per_task_ranking_differs(
    fixture_dir: Path, matrix_path: Path, manifest: dict, tmp_path: Path
) -> None:
    """Fixture is engineered so the best executor differs by task (SC-008, T022)."""
    report = _run(fixture_dir, matrix_path, manifest, tmp_path)
    cells = report["cells"]
    scout_best = _best_executor(cells, "scout")
    note_best = _best_executor(cells, "note-writer")
    assert scout_best == "claude"
    assert note_best == "codex"
    assert scout_best != note_best


def test_dispatch_unavailable_skipped(
    fixture_dir: Path, matrix_path: Path, manifest: dict, tmp_path: Path
) -> None:
    """A runtime that can't dispatch ⇒ status skipped; the sweep continues (FR-011, T031)."""

    def flaky(cell, *, fixture_dir, cell_dir):
        if cell.executor == "codex":
            return runner.RawCellOutput(
                stdout="", status="skipped", reason="codex API key not set"
            )
        return runner.hermetic_dispatch(
            cell, fixture_dir=fixture_dir, cell_dir=cell_dir
        )

    report = _run(fixture_dir, matrix_path, manifest, tmp_path, dispatch_fn=flaky)
    cells = report["cells"]
    assert len(cells) == 12  # nothing dropped — sweep ran every cell
    codex = [c for c in cells if c["executor"] == "codex"]
    claude = [c for c in cells if c["executor"] == "claude"]
    assert codex and all(c["status"] == "skipped" for c in codex)
    assert all("key not set" in c["reason"] for c in codex)
    assert claude and all(c["status"] == "ok" for c in claude)


def test_failed_cell_cost_counts_toward_cap(
    fixture_dir: Path, matrix_path: Path, manifest: dict, tmp_path: Path
) -> None:
    """A failure that still BILLED carries its cost into the report + cap (Copilot review).

    A dispatch can error after the agent already ran (and was charged). The runner
    must record that cost and let it trip ``--max-usd`` — not treat failures as free.
    """

    def billed_failure(cell, *, fixture_dir, cell_dir):
        return runner.RawCellOutput(
            stdout="boom",
            status="failed",
            reason="errored after billing",
            cost_usd=0.03,
            cost_source="sidecar",
        )

    cells = M.expand_cells(M.load_matrix(matrix_path))
    run_dir = reporter.create_run_dir(tmp_path, reporter.run_id_now())
    report = runner.run_matrix(
        cells,
        fixture_dir=fixture_dir,
        run_dir=run_dir,
        manifest=manifest,
        matrix_path=matrix_path,
        dispatch_fn=billed_failure,
        cost_cap=gating.CostCap(0.05),
        ack_mode="dry-run",
        max_usd=0.05,
    )
    reported = report["cells"]
    # 0.03 (ok, ≤0.05) then 0.06 (>0.05) → stop after the 2nd cell.
    assert len(reported) == 2
    assert all(c["status"] == "failed" and c["cost_usd"] == 0.03 for c in reported)


def test_capture_stdout_prefers_output_file(tmp_path: Path) -> None:
    """Structured --output-file content wins over captured stdout, including on a
    failure exit; empty/absent file falls back to proc.stdout (Copilot re-review)."""
    # A bare stand-in (not a real subprocess) keeps this test hermetic — the marker
    # guard forbids ``import subprocess`` here; _capture_stdout only reads .stdout.
    proc = SimpleNamespace(stdout="raw-stdout")
    out = tmp_path / "agent-stdout.txt"

    assert runner._capture_stdout(out, proc) == "raw-stdout"  # absent file
    out.write_text("   \n", encoding="utf-8")
    assert runner._capture_stdout(out, proc) == "raw-stdout"  # blank file ignored
    out.write_text("structured-note", encoding="utf-8")
    assert runner._capture_stdout(out, proc) == "structured-note"  # file wins
