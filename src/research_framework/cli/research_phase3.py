from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from ._common import _git_init


def _run_phase3(spec, vault_dir: Path) -> int:
    """Phase 3 — shared between ``_cmd_generate`` and ``_resume``.

    H4 fix (spec-019 / 0.2.28): pre-0.2.28 ``_resume`` skipped this
    entire phase, so resume runs that terminated cleanly never produced
    ``run-report.md`` and never enforced the coverage / code-first
    gates. Factoring lets both code paths converge on the same
    post-cycle finalization.

    Returns 0 on full success, non-zero when a gate fails (caller
    surfaces the exit code).
    """
    from ..pipeline.coverage import all_targets_met, unmet_targets
    from ..pipeline.reporter import generate_report
    from ..vault.indexer import rebuild as rebuild_indexes

    if not all_targets_met(vault_dir):
        # Issue #242 / spec 070 FR6: a gate that returns non-zero says so on
        # stderr. Both phase-3 gates used to reject on stdout, which is the
        # stream an unattended run redirects away.
        print("[phase 3 gate] coverage targets unmet:", file=sys.stderr)
        for cat in unmet_targets(vault_dir):
            print(f"  - {cat}", file=sys.stderr)
        return 1

    cf_rc = _phase3_code_first_gate(vault_dir)
    if cf_rc != 0:
        return cf_rc

    rebuild_indexes(vault_dir)
    _git_init(vault_dir, spec.name)
    report = generate_report(vault_dir)
    print(f"[phase 3] report written: {report}")
    return 0


def _prepopulate_pipeline(vault_dir: Path, source_dir: Path) -> None:
    """Copy every file from `source_dir` into `vault_dir/_pipeline/` verbatim.

    Intended for the `research-framework generate --prepopulate <dir>` flow where an
    archived vault's `_pipeline/` meta-files (post-mortem, lessons-learned,
    budget-log) carry forward into a clean rebuild. Existing pipeline files
    (e.g., the fresh budget-log.md scaffold wrote) are OVERWRITTEN by the
    prepopulate copies — the archive wins so the rebuild log can append to
    the historical tally.
    """
    import shutil

    if not source_dir.exists():
        print(f"WARN: --prepopulate source not found: {source_dir}")
        return
    pipeline = vault_dir / "_pipeline"
    pipeline.mkdir(parents=True, exist_ok=True)
    copied = 0
    for src_file in sorted(source_dir.iterdir()):
        if not src_file.is_file():
            continue
        shutil.copy2(src_file, pipeline / src_file.name)
        copied += 1
    print(f"[phase 1] prepopulated {copied} file(s) from {source_dir}")


def _phase3_code_first_gate(vault_dir: Path) -> int:
    """Run the two code-first validators. Return 0 if both pass or either is
    absent (v0.1 back-compat); return 1 if either fails.

    FR-020: Phase 3 MUST NOT unlock until coverage is met AND these two scripts
    return 0. Speckit's cli invokes them AFTER coverage gate passes.
    """
    scripts_dir = vault_dir / "scripts"
    checks = [
        ("intent-drift", scripts_dir / "check_intent_drift.py"),
        ("code-source-coverage", scripts_dir / "check_code_source_coverage.py"),
    ]
    worst = 0
    for name, path in checks:
        if not path.exists():
            # Script not in the bundle (pre-002 vault) → skip gracefully
            continue
        print(f"[phase 3 gate] running {name}")
        rc = subprocess.run([sys.executable, str(path), str(vault_dir)]).returncode
        if rc != 0:
            # Progress stays on stdout; the rejection is the exit reason and
            # belongs on stderr (issue #242).
            print(
                f"[phase 3 gate] {name} FAILED (exit {rc}) — "
                "Phase 3 blocked. Fix the flagged notes and re-run.",
                file=sys.stderr,
            )
            worst = max(worst, 1)
    return worst
