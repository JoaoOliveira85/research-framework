#!/usr/bin/env python3
"""Abstraction gate CLI for vault scout output (feature 017, SG-003).

Loads ``research.spec.md``, picks the cycle report through
:func:`research_framework.pipeline.abstraction.latest_scout_report` — the same
resolver the in-process gate's report source is documented against — and runs
:func:`SG003_topic_abstraction_check`. The vault path supplies the
``settings.yaml`` thresholds.

Until #296 this script globbed ``cycle-*-research.json``, the DFS output, while
``pipeline/steps/scout.py`` evaluated ``cycle-NNN-scout.json``. Only the scout
report carries ``topics_found.new``, so run over the same cycle the two
disagreed — or the CLI scored zero rows and called it a pass. ``--report`` names
a report explicitly when the newest one is not the one you mean.

**Exit codes** (Script Exit Code Model):

- ``0`` — gate status PASS, WARN, or NA
- ``1`` — gate status FAIL
- ``2`` — structural error (missing spec, unreadable scout report, etc.)

Stdout: one JSON object matching
``contracts/cycle-quality-report.schema.json#/$defs/gate_result``
(:meth:`GateResult.to_dict`).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_SRC = _HERE.parent / "src"
if _REPO_SRC.exists() and str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

try:
    from research_framework.pipeline.abstraction import latest_scout_report
    from research_framework.pipeline.gates_step import SG003_topic_abstraction_check
    from research_framework.spec.parser import parse as parse_spec_file
except Exception as e:  # pragma: no cover - import-time failures are fatal
    print(f"[check_abstraction] cannot import research_framework: {e}", file=sys.stderr)
    sys.exit(2)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Run SG-003 (forbidden filename prefix abstraction) on the latest "
            "scout report in a vault."
        )
    )
    ap.add_argument(
        "spec_path",
        type=Path,
        help="Path to research.spec.md",
    )
    ap.add_argument(
        "vault_path",
        type=Path,
        help="Vault root (must contain settings.yaml and _pipeline/cycles/)",
    )
    ap.add_argument(
        "--report",
        type=Path,
        default=None,
        help=(
            "Scout report to evaluate; defaults to the newest "
            "cycle-NNN-scout.json under <vault>/_pipeline/cycles/"
        ),
    )
    args = ap.parse_args(argv)

    spec_path: Path = args.spec_path
    vault_path: Path = args.vault_path

    if not spec_path.is_file():
        print(
            f"[check_abstraction] spec not found or not a file: {spec_path}",
            file=sys.stderr,
        )
        return 2

    try:
        spec = parse_spec_file(spec_path)
    except Exception as e:
        print(
            f"[check_abstraction] failed to parse spec {spec_path}: {e}",
            file=sys.stderr,
        )
        return 2

    scout_path = args.report
    if scout_path is None:
        cycles_dir = vault_path / "_pipeline" / "cycles"
        if not cycles_dir.is_dir():
            print(
                f"[check_abstraction] missing cycles directory: {cycles_dir}",
                file=sys.stderr,
            )
            return 2
        scout_path = latest_scout_report(cycles_dir)
        if scout_path is None:
            print(
                f"[check_abstraction] no cycle-*-scout.json under {cycles_dir}",
                file=sys.stderr,
            )
            return 2
    if not scout_path.is_file():
        print(
            f"[check_abstraction] scout report not found: {scout_path}",
            file=sys.stderr,
        )
        return 2

    try:
        report = json.loads(scout_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(
            f"[check_abstraction] invalid JSON in {scout_path}: {e}",
            file=sys.stderr,
        )
        return 2
    if not isinstance(report, dict):
        print(
            f"[check_abstraction] scout report must be a JSON object: {scout_path}",
            file=sys.stderr,
        )
        return 2

    result = SG003_topic_abstraction_check(report, spec, vault_path)
    json.dump(result.to_dict(), sys.stdout, indent=2)
    print()

    if result.status == "FAIL":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
