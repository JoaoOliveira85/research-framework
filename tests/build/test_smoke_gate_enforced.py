"""Regression test for the ``build.sh`` smoke gate (feature 018, US4, T026).

The fast structural test (``test_smoke_gate_present_in_build_sh``) runs in
every test invocation — it locks the existence of the gate text so a
casual ``build.sh`` refactor cannot silently delete the gate.

The slow integration test (``test_smoke_gate_aborts_build_on_regression``)
copies the repo into ``tmp_path``, deliberately re-tightens
``BatchResult.to_dict``'s lower bound to ``3`` (reproducing the 0.2.22
seam bug), runs the real ``build.sh``, and asserts it exits non-zero and
no tarball appears. Marked ``@pytest.mark.slow`` so the default ``pytest``
run skips it; CI / release flows that want the full proof can opt in
with ``pytest -m slow``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_smoke_gate_present_in_build_sh() -> None:
    """Fast structural assertion: the gate text is in build.sh."""
    build_sh = REPO_ROOT / "build.sh"
    assert build_sh.is_file(), build_sh
    text = build_sh.read_text(encoding="utf-8")

    required_markers = [
        "smoke gate",
        "test_full_cycle_e2e.py",
        "test_multi_cycle_e2e.py",
        "exit 1",
    ]
    missing = [m for m in required_markers if m not in text]
    assert not missing, (
        f"build.sh is missing smoke-gate markers: {missing}. "
        "The gate must run the e2e tier before the wheel build and exit 1 on failure."
    )

    # Code-level escape hatches: argv parsing, env-var conditional, or
    # commented-out gate. (The comment block explaining "no escape" is fine —
    # we look for active conditionals, not mentions.)
    import re

    suspicious_patterns = [
        re.compile(r'if\s+\[\s*"?\$?\{?SKIP_SMOKE'),
        re.compile(r'if\s+\[\s*"?\$?\{?BYPASS_SMOKE'),
        re.compile(r"case\s+.*--skip-smoke"),
        re.compile(
            r'^\s*#\s*"?\$\{PYTHON_BIN\}"\s+-m\s+pytest.*test_full_cycle', re.MULTILINE
        ),
    ]
    matched = [p.pattern for p in suspicious_patterns if p.search(text)]
    assert not matched, (
        f"build.sh contains a smoke-gate escape pattern ({matched}); per spec "
        "018 § US4, the gate must be hard. Remove the escape or revisit the spec."
    )


@pytest.mark.slow
@pytest.mark.e2e
def test_smoke_gate_aborts_build_on_regression(tmp_path: Path) -> None:
    """Build aborts (no tarball) when the e2e tier is broken.

    Strategy: copy the worktree to ``tmp_path / build_check``, mutate
    ``src/research_framework/pipeline/batch.py`` to re-tighten the
    ``BatchResult.to_dict`` lower bound to ``3`` (reproducing the
    0.2.22 seam bug that ``test_asymmetric_tail_batch_serializes``
    locks as a regression), run ``build.sh``, and assert non-zero exit
    plus no tarball under ``build/``.
    """
    build_check = tmp_path / "build_check"
    excludes = [
        ".git",
        ".venv",
        "build",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "node_modules",
    ]

    def _ignore(_dir: str, names: list[str]) -> list[str]:
        return [n for n in names if n in excludes]

    shutil.copytree(REPO_ROOT, build_check, ignore=_ignore)

    batch_py = build_check / "src" / "research_framework" / "pipeline" / "batch.py"
    text = batch_py.read_text(encoding="utf-8")
    needle = "1 <= len(self.topics) <= _MAX_BATCH"
    assert needle in text, (
        f"could not find current BatchResult invariant in {batch_py}; "
        "this test must be updated to track the production code."
    )
    mutated = text.replace(needle, "3 <= len(self.topics) <= _MAX_BATCH")
    assert mutated != text, "mutation no-op"
    batch_py.write_text(mutated, encoding="utf-8")

    env = dict(os.environ)
    env["PYTHON_BIN"] = sys.executable
    proc = subprocess.run(
        ["bash", str(build_check / "build.sh")],
        cwd=str(build_check),
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )

    assert proc.returncode != 0, (
        f"build.sh unexpectedly succeeded (exit 0) on a tree where the 0.2.22 "
        f"seam bug has been re-introduced.\n"
        f"stdout tail:\n{proc.stdout[-2000:]}\n"
        f"stderr tail:\n{proc.stderr[-2000:]}"
    )
    tarballs = list((build_check / "build").glob("research-framework-*.tar.gz"))
    assert not tarballs, (
        f"build.sh produced a tarball ({tarballs}) despite e2e gate failure"
    )
