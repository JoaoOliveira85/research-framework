"""Benchmark matrix loading + validation + cell expansion (spec 056, contract §1–2).

The matrix YAML declares ``tasks`` (subset of the v1 trio) and ``executors`` (each
a ``runtime`` + explicit ``models`` list). Runtimes are validated at LOAD time
against the runtimes ``agent_call.py`` can actually dispatch — both the CLI
adapters (``_RUNTIME_ADAPTERS``) and the HTTP runtimes (``_HTTP_RUNTIMES``, e.g.
``ollama`` from spec 047) — so a typo is a loud config error, not a silent
all-skipped sweep.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# v1 scored task ids (FR-016 / contract §2) and their agent_call stage names.
STAGE_FOR_TASK: dict[str, str] = {
    "scout": "scout",
    "note-writer": "note_writer",
    "verifier": "verifier",
}
V1_TASKS: tuple[str, ...] = tuple(STAGE_FOR_TASK)


class MatrixError(ValueError):
    """Raised on any structural / validation problem loading the matrix YAML."""


@dataclass(frozen=True)
class Cell:
    """One ``{task × executor × model}`` matrix cell."""

    task: str
    executor: str
    model: str
    # Spec 064 (FR-020): optional human-readable label so the SAME runtime can be
    # swept under several configs (e.g. `opencode-local-qwen`, `opencode-gpt5`).
    label: str | None = None

    @property
    def key(self) -> str:
        """Stable cell id used for artifact dirs + recorded-response lookup.

        A ``label`` (when set) replaces the runtime name so distinct configs of
        one runtime get distinct keys; absent a label the key is byte-identical to
        the pre-064 ``task__executor__model`` form.
        """
        return f"{self.task}__{self.label or self.executor}__{self.model}"

    @property
    def stage(self) -> str:
        return STAGE_FOR_TASK[self.task]


@dataclass(frozen=True)
class Executor:
    runtime: str
    models: tuple[str, ...]
    label: str | None = None  # spec 064 FR-020 (optional)


@dataclass(frozen=True)
class Matrix:
    path: Path
    tasks: tuple[str, ...]
    executors: tuple[Executor, ...]


def _repo_root() -> Path:
    # src/research_framework/benchmark/matrix.py → parents[3] == repo root.
    return Path(__file__).resolve().parents[3]


_RUNTIME_CACHE: set[str] | None = None


def valid_runtimes() -> set[str]:
    """Runtime names ``agent_call.py`` can dispatch: CLI adapters ∪ HTTP runtimes.

    Loaded once (cached) from ``scripts/agent_call.py`` by path — it is a script,
    not an importable package module — so this stays the single source of truth and
    picks up new runtimes automatically (spec 047 ``ollama``, spec 052
    ``cursor-agent``).
    """
    global _RUNTIME_CACHE
    if _RUNTIME_CACHE is not None:
        return set(_RUNTIME_CACHE)

    script = _repo_root() / "scripts" / "agent_call.py"
    # Unique module name (script path digest) avoids cross-call/test collisions.
    mod_name = f"_agent_call_runtimes_{abs(hash(str(script))):x}"
    spec = importlib.util.spec_from_file_location(mod_name, script)
    if spec is None or spec.loader is None:  # pragma: no cover — defensive.
        raise MatrixError(f"cannot load runtime registry from {script}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec so module-level ``@dataclass`` can resolve
    # ``cls.__module__`` (dataclasses reads ``sys.modules[__module__].__dict__``);
    # remove it afterwards so we don't leak a synthetic module.
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
        adapters = set(getattr(module, "_RUNTIME_ADAPTERS", {}))
        http = set(getattr(module, "_HTTP_RUNTIMES", set()))
    finally:
        sys.modules.pop(mod_name, None)
    _RUNTIME_CACHE = adapters | http
    return set(_RUNTIME_CACHE)


def load_matrix(path: Path, *, runtimes: set[str] | None = None) -> Matrix:
    """Parse + validate the matrix YAML at *path*.

    ``runtimes`` overrides the dispatchable-runtime set (tests inject a fixed
    set; production resolves it from ``agent_call.py``).
    """
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise MatrixError(f"matrix file unreadable: {path} ({exc})") from exc
    except yaml.YAMLError as exc:
        raise MatrixError(f"matrix YAML invalid: {path} ({exc})") from exc
    if not isinstance(raw, dict):
        raise MatrixError(f"matrix root must be a mapping, got {type(raw).__name__}")

    tasks = _parse_tasks(raw.get("tasks"))
    allowed = runtimes if runtimes is not None else valid_runtimes()
    executors = _parse_executors(raw.get("executors"), allowed)
    return Matrix(path=path, tasks=tasks, executors=executors)


def _parse_tasks(raw: object) -> tuple[str, ...]:
    if raw is None:
        return V1_TASKS
    if not isinstance(raw, list) or not raw:
        raise MatrixError("`tasks` must be a non-empty list when present")
    tasks: list[str] = []
    for item in raw:
        task = str(item)
        if task not in STAGE_FOR_TASK:
            raise MatrixError(
                f"unknown task id {task!r}; v1 supports {sorted(STAGE_FOR_TASK)} "
                "(topic-classifier/model-router/dfs-research/ask/write are deferred)"
            )
        tasks.append(task)
    return tuple(tasks)


def _parse_executors(raw: object, allowed: set[str]) -> tuple[Executor, ...]:
    if not isinstance(raw, list) or not raw:
        raise MatrixError("`executors` must be a non-empty list")
    executors: list[Executor] = []
    for block in raw:
        if not isinstance(block, dict):
            raise MatrixError(f"each executor must be a mapping, got {block!r}")
        runtime = str(block.get("runtime") or "").strip()
        if not runtime:
            raise MatrixError("executor missing `runtime`")
        if runtime not in allowed:
            raise MatrixError(
                f"unknown runtime {runtime!r}; dispatchable runtimes are "
                f"{sorted(allowed)} (add the adapter/HTTP runtime to agent_call.py "
                "before listing it here)"
            )
        models_raw = block.get("models")
        if not isinstance(models_raw, list) or not models_raw:
            raise MatrixError(f"executor {runtime!r} needs a non-empty `models` list")
        models = tuple(str(m) for m in models_raw)
        # Spec 064 PR review: normalise whitespace-only labels (``label: "   "``)
        # to None so the parsed model never carries an empty string that callers
        # treat as falsy anyway — keeps the executor surface clean and predictable.
        label_raw = block.get("label")
        label_stripped = str(label_raw).strip() if label_raw is not None else ""
        label = label_stripped or None
        executors.append(Executor(runtime=runtime, models=models, label=label))
    return tuple(executors)


def expand_cells(matrix: Matrix) -> list[Cell]:
    """Full ``{task × executor × model}`` product, in declared order."""
    cells: list[Cell] = []
    for task in matrix.tasks:
        for executor in matrix.executors:
            for model in executor.models:
                cells.append(
                    Cell(
                        task=task,
                        executor=executor.runtime,
                        model=model,
                        label=executor.label,
                    )
                )
    return cells


def apply_scope(
    cells: list[Cell],
    *,
    tasks: list[str] | None = None,
    executors: list[str] | None = None,
    models: list[str] | None = None,
) -> list[Cell]:
    """Filter cells to the CLI ``--task/--executor/--model`` subset (FR-002)."""
    task_set = set(tasks) if tasks else None
    exec_set = set(executors) if executors else None
    model_set = set(models) if models else None
    return [
        c
        for c in cells
        if (task_set is None or c.task in task_set)
        and (exec_set is None or c.executor in exec_set)
        and (model_set is None or c.model in model_set)
    ]
