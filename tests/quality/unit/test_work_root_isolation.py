"""Issue #288 (rf-assurance, reported PLAUSIBLE/not reproduced in isolation):
the quality harness's work root used to be one process-independent constant
(``_DEFAULT_OUTPUT_DIR / "work"``), and :func:`isolate_fixture` unconditionally
``rmtree``\\ s then ``copytree``\\ s it — so two harness invocations running
concurrently in one checkout could ``rmtree`` out from under each other's
in-flight cycle. The fix salts the root with :func:`os.getpid`; these tests
pin that two different processes now resolve two different, non-colliding
roots.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_work_root_is_salted_with_the_current_pid() -> None:
    from research_framework.quality.runner import _WORK_ROOT

    assert str(os.getpid()) in _WORK_ROOT.name


def _start_work_root_process() -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from research_framework.quality.runner import _WORK_ROOT; "
            "print(_WORK_ROOT)",
        ],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_two_processes_resolve_different_non_colliding_work_roots() -> None:
    """The actual concurrency claim: two SEPARATE, SIMULTANEOUSLY-ALIVE
    processes must never agree on a work root, so neither can ``rmtree`` the
    other's in-flight fixture copy out from under it. Started together with
    ``Popen`` (not run sequentially) so both hold distinct PIDs at the OS
    level while the import — and the salting — happens; a sequential
    run-then-run could in principle have the second reuse the first's just-
    freed PID."""
    proc_a = _start_work_root_process()
    proc_b = _start_work_root_process()
    out_a, err_a = proc_a.communicate(timeout=30)
    out_b, err_b = proc_b.communicate(timeout=30)
    assert proc_a.returncode == 0, err_a
    assert proc_b.returncode == 0, err_b
    root_a, root_b = out_a.strip(), out_b.strip()
    assert root_a and root_b
    assert root_a != root_b
