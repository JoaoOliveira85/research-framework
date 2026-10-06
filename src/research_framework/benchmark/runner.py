"""Cell runner: hermetic replay + live dispatch + matrix orchestration (spec 056).

Two dispatch paths share one ``run_matrix`` driver:
  - **hermetic** (``--dry-run`` / tests): reads recorded outputs from the fixture's
    ``fake_agent_responses/responses.json`` — NO live LLM, fully deterministic.
  - **live** (manual, opt-in): subprocesses ``scripts/agent_call.py`` per cell
    against a per-cell vault whose ``settings.yaml`` pins the cell's runtime+model,
    then reads the spec-028 sidecar for cost + the wall clock for latency.

A registered-but-undispatchable runtime (missing key, binary absent) ⇒ cell
``status: skipped``; an error/timeout ⇒ ``status: failed``; the sweep continues
(FR-011/FR-012). The ``--max-usd`` cap stops mid-sweep with a partial report.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..pipeline.process_tree import popen_session, terminate_process_tree
from . import reporter, scoring
from .gating import CostCap, cost_fields
from .matrix import Cell

# Repo root: src/research_framework/benchmark/runner.py → parents[3].
_REPO_ROOT = Path(__file__).resolve().parents[3]
_AGENT_CALL = _REPO_ROOT / "scripts" / "agent_call.py"

# Per-cell vault ``budget_usd`` when the operator did NOT pass ``--max-usd``. This is
# the agent's *own* per-run budget-guard ceiling for a single cell — deliberately high
# enough to let one legitimate stage call (e.g. an opus note-writer) complete, low
# enough to bound a runaway. It is a DIFFERENT quantity from
# ``gating.DEFAULT_CELL_CEILING_USD`` (the pre-run *estimate* per cell, ~$0.10).
_UNCAPPED_CELL_BUDGET_USD = 5.0


@dataclass
class RawCellOutput:
    """What a dispatch path returns for one cell, before scoring."""

    stdout: str
    status: str  # "ok" | "skipped" | "failed"
    cost_usd: float | None = None
    cost_source: str = "n/a"
    latency_ms: int | None = None
    reason: str | None = None
    sidecar: dict[str, Any] | None = None


DispatchFn = Callable[..., RawCellOutput]

_RESPONSES_CACHE: dict[Path, dict[str, Any]] = {}


def _load_responses(fixture_dir: Path) -> dict[str, Any]:
    path = fixture_dir / "fake_agent_responses" / "responses.json"
    if path not in _RESPONSES_CACHE:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        _RESPONSES_CACHE[path] = data if isinstance(data, dict) else {}
    return _RESPONSES_CACHE[path]


def hermetic_dispatch(
    cell: Cell, *, fixture_dir: Path, cell_dir: Path
) -> RawCellOutput:
    """Return the recorded output for *cell* — no network, no subprocess."""
    rec = _load_responses(fixture_dir).get(cell.key)
    if not isinstance(rec, dict):
        return RawCellOutput(
            stdout="",
            status="skipped",
            reason=f"no recorded response for cell {cell.key}",
        )
    cost = rec.get("cost_usd")
    has_cost = cost is not None
    return RawCellOutput(
        stdout=str(rec.get("stdout", "")),
        status="ok",
        cost_usd=float(cost) if has_cost else None,
        cost_source="sidecar" if has_cost else "n/a",
        latency_ms=rec.get("latency_ms"),
        sidecar={"cost_usd": cost} if has_cost else None,
    )


def _task_prompt(fixture_dir: Path, task: str) -> str:
    name = {
        "scout": "scout-prompt.txt",
        "note-writer": "note-writer-prompt.txt",
        "verifier": "verifier-prompt.txt",
    }[task]
    prompt = (fixture_dir / "tasks" / name).read_text(encoding="utf-8")
    if task == "verifier":
        draft = (fixture_dir / "tasks" / "verifier-draft.md").read_text(
            encoding="utf-8"
        )
        prompt = f"{prompt}\n\n--- DRAFT UNDER REVIEW ---\n\n{draft}"
    return prompt


def _build_cell_vault(
    cell: Cell,
    fixture_dir: Path,
    cell_dir: Path,
    *,
    cell_budget_usd: float | None = None,
) -> Path:
    """Create a per-cell vault whose settings pin this cell's runtime + model.

    Copies the committed fixture vault scaffold (``research.spec.md`` +
    ``_templates/``) so the per-cell vault matches a real vault layout that
    ``agent_call.py`` / downstream stages can resolve; ``settings.yaml`` is then
    written with this cell's runtime+model.
    """
    vault = cell_dir / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        fixture_dir / "_templates", vault / "_templates", dirs_exist_ok=True
    )
    spec_src = fixture_dir / "research.spec.md"
    if spec_src.is_file():
        shutil.copy2(spec_src, vault / "research.spec.md")
    # Defence-in-depth on the LIVE path: the runner can only stop *between* cells, so
    # we pin each cell's vault budget_usd to bound a single runaway cell. When the
    # operator set --max-usd we reuse that whole-run cap (one cell may not exceed it);
    # when uncapped we fall back to _UNCAPPED_CELL_BUDGET_USD (see its definition for
    # why it is intentionally NOT gating.DEFAULT_CELL_CEILING_USD).
    budget = (
        cell_budget_usd if cell_budget_usd is not None else _UNCAPPED_CELL_BUDGET_USD
    )
    settings = {
        "pipeline": {"max_cycles": 1, "budget_usd": round(float(budget), 4)},
        "default_executor": {
            "runtime": cell.executor,
            "model": cell.model,
            "timeout_s": 900,
        },
    }
    (vault / "settings.yaml").write_text(yaml.safe_dump(settings), encoding="utf-8")
    return vault


def _capture_stdout(output_file: Path, proc: subprocess.CompletedProcess[str]) -> str:
    """Prefer the agent's ``--output-file`` over captured stdout.

    ``agent_call.py`` routes structured stage output to ``--output-file``; on a
    non-zero exit the agent may have written (partial) scorable output there before
    erroring, so we read it on BOTH the success and failure paths and only fall back
    to ``proc.stdout`` when the file is absent/empty.
    """
    if output_file.is_file():
        text = output_file.read_text(encoding="utf-8")
        if text.strip():
            return text
    return proc.stdout or ""


def live_dispatch(
    cell: Cell,
    *,
    fixture_dir: Path,
    cell_dir: Path,
    agent_call: Path = _AGENT_CALL,
    timeout_s: int = 1200,
    cell_budget_usd: float | None = None,
) -> RawCellOutput:
    """Subprocess ``agent_call.py`` for one cell against a per-cell vault.

    ``cell_budget_usd`` (wired from the CLI ``--max-usd``) bounds the per-cell vault
    ``budget_usd`` so a single cell can't overrun the whole-run cap before the
    runner gets to stop between cells.
    """
    vault = _build_cell_vault(
        cell, fixture_dir, cell_dir, cell_budget_usd=cell_budget_usd
    )
    sidecar_path = (
        vault
        / "_pipeline"
        / "cycles"
        / "cycle-001"
        / "agent-calls"
        / f"{cell.stage}.json"
    )
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_file = cell_dir / "prompt.txt"
    prompt_file.write_text(_task_prompt(fixture_dir, cell.task), encoding="utf-8")
    output_file = cell_dir / "agent-stdout.txt"
    cmd = [
        sys.executable,
        str(agent_call),
        "--vault",
        str(vault),
        "--stage",
        cell.stage,
        "--prompt-file",
        str(prompt_file),
        "--cost-sidecar",
        str(sidecar_path),
        "--output-file",
        str(output_file),
    ]
    started = time.monotonic()
    with popen_session(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    ) as child:
        try:
            out, err = child.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return RawCellOutput(
                stdout="", status="failed", reason=f"timed out after {timeout_s}s"
            )
        finally:
            # On every path, the timeout and Ctrl+C included. agent_call.py
            # runs the agent CLI in a session of its own and forwards a
            # SIGTERM to it; the SIGKILL of ``subprocess.run(timeout=…)``
            # cannot be forwarded, so it killed the wrapper and left the
            # agent running. SIGTERM to the wrapper's group first, then
            # SIGKILL. A no-op once the wrapper has exited and left nothing.
            terminate_process_tree(child)
    proc = subprocess.CompletedProcess(cmd, child.returncode, out, err)
    latency_ms = int((time.monotonic() - started) * 1000)
    sidecar = None
    if sidecar_path.is_file():
        try:
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            sidecar = None
    if proc.returncode != 0:
        # exit 2 with no sidecar is the agent_call "unavailable" signal (missing
        # key / binary / unknown runtime) → skipped; anything else → failed.
        status = "skipped" if proc.returncode == 2 and sidecar is None else "failed"
        # A failure can still have BILLED (e.g. agent ran then errored): carry the
        # sidecar cost so the report + --max-usd tally don't under-count spend.
        cost_usd, cost_source = cost_fields(sidecar)
        return RawCellOutput(
            stdout=_capture_stdout(output_file, proc),
            status=status,
            reason=(proc.stderr or "").strip()[:500] or f"exit {proc.returncode}",
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            cost_source=cost_source,
            sidecar=sidecar,
        )
    stdout = _capture_stdout(output_file, proc)
    cost_usd, cost_source = cost_fields(sidecar)
    return RawCellOutput(
        stdout=stdout,
        status="ok",
        cost_usd=cost_usd,
        cost_source=cost_source,
        latency_ms=latency_ms,
        sidecar=sidecar,
    )


def _cell_result(
    cell: Cell, raw: RawCellOutput, scored: dict[str, Any] | None, artifact_rel: str
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "task": cell.task,
        # Spec 064 FR-020: a label (when set) names the cell's executor column so
        # several configs of one runtime are distinguishable in the report.
        "executor": cell.label or cell.executor,
        "model": cell.model,
        "status": raw.status,
        "cost_usd": raw.cost_usd,
        "cost_source": raw.cost_source,
        "artifact_dir": artifact_rel,
    }
    if raw.latency_ms is not None and raw.status == "ok":
        result["latency_ms"] = raw.latency_ms
    if raw.reason:
        result["reason"] = raw.reason
    if scored is not None:
        result["quality"] = scored.get("quality")
        result["quality_detail"] = scored.get("quality_detail")
        result["scoring_mode"] = scored.get("scoring_mode")
    return result


def run_matrix(
    cells: list[Cell],
    *,
    fixture_dir: Path,
    run_dir: Path,
    manifest: dict[str, Any],
    matrix_path: Path,
    dispatch_fn: DispatchFn = hermetic_dispatch,
    cost_cap: CostCap | None = None,
    ack_mode: str = "tty",
    estimated_usd: float | None = None,
    max_usd: float | None = None,
) -> dict[str, Any]:
    """Drive every cell, score the ``ok`` ones, write report.json + report.md.

    Stops early (partial report) when ``cost_cap`` is exceeded after a cell.
    """
    started_at = reporter.iso_now()
    cap = cost_cap or CostCap(max_usd)
    accumulated = 0.0
    results: list[dict[str, Any]] = []
    for cell in cells:
        cell_dir = run_dir / "cells" / cell.key
        cell_dir.mkdir(parents=True, exist_ok=True)
        raw = dispatch_fn(cell, fixture_dir=fixture_dir, cell_dir=cell_dir)
        (cell_dir / "stdout.txt").write_text(raw.stdout, encoding="utf-8")
        if raw.sidecar is not None:
            (cell_dir / "sidecar.json").write_text(
                json.dumps(raw.sidecar, indent=2), encoding="utf-8"
            )

        scored: dict[str, Any] | None = None
        if raw.status == "ok":
            scored = scoring.score_task(
                cell.task,
                raw.stdout,
                fixture_dir=fixture_dir,
                manifest=manifest,
                work_dir=cell_dir,
            )
            scoring.write_scored_json(cell_dir, scored)
            if not scored.get("parse_ok", False):
                raw.status = "failed"
                raw.reason = scored.get("reason") or "output not scorable"

        results.append(_cell_result(cell, raw, scored, f"cells/{cell.key}"))

        if raw.cost_usd is not None:
            accumulated += raw.cost_usd
            if cap.exceeded(accumulated):
                break

    report = reporter.build_report(
        run_id=run_dir.name,
        matrix_path=matrix_path,
        fixture_dir=fixture_dir,
        cells=results,
        started_at=started_at,
        completed_at=reporter.iso_now(),
        estimated_usd=estimated_usd,
        ack_mode=ack_mode,
        max_usd=max_usd,
    )
    reporter.write_report(run_dir, report)
    return report
