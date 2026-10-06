"""Stand-ins for ``run_cycle_steps``, passed through the ``cycle_runner=`` seam.

A test that needs the pipeline's *control flow* without a real cycle passes one
of these to ``orchestrator.run_single_cycle`` or the quality harness, instead
of monkeypatching the module global — which is a guarded anti-pattern
(``tests/_helpers/test_cycle_runner_seam_guard.py``, issue #86).

Every stub here mirrors ``run_cycle_steps``' real signature rather than
swallowing ``*args, **kwargs``. That is the point: when the runner grows or
loses an argument, a stub that could not be called the new way fails loudly
instead of absorbing the change (the failure mode #268 found, where the
harness's pinned budget pair was invisible to a permissive stub).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

CycleRunner = Callable[..., int]


def no_op_cycle_runner(exit_code: int = 0) -> CycleRunner:
    """A runner that does nothing and returns *exit_code*."""

    def _run(
        vault_dir: Path,
        cycle_num: int,
        budget_cap: float | None = None,
        max_cycles: int | None = None,
        scripts_dir: Path | None = None,
    ) -> int:
        _ = vault_dir, cycle_num, budget_cap, max_cycles, scripts_dir
        return exit_code

    return _run


def recording_cycle_runner(
    calls: list[int],
    *,
    exit_code: int = 0,
    notes_created: Callable[[int], list[str]] | None = None,
) -> CycleRunner:
    """Record each cycle number, and write the research report the cycle would.

    ``notes_created`` maps an attempt count to the note names the cycle claims
    to have written — the input the CG-001 min-yield gate reads back off disk.
    Without the report on disk the orchestrator sees a cycle that ran and
    produced no record, which is a different scenario from the one most callers
    mean.
    """

    def _run(
        vault_dir: Path,
        cycle_num: int,
        budget_cap: float | None = None,
        max_cycles: int | None = None,
        scripts_dir: Path | None = None,
    ) -> int:
        _ = budget_cap, max_cycles, scripts_dir
        calls.append(cycle_num)
        names = notes_created(len(calls)) if notes_created else []
        report_path = (
            vault_dir / "_pipeline" / "cycles" / f"cycle-{cycle_num:03d}-research.json"
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps({"notes_created": names, "notes_updated": []}),
            encoding="utf-8",
        )
        return exit_code

    return _run
