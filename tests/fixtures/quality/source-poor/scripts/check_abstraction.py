#!/usr/bin/env python3
"""Abstraction gate CLI for vault scout output (feature 017, SG-003).

Loads ``research.spec.md``, reads the latest ``cycle-*-research.json`` under
``_pipeline/cycles/``, and runs :func:`SG003_topic_abstraction_check`. The script
uses the same synthesized scout-shaped dict you would get from ``--vault`` in a
richer design; here the vault path supplies settings.yaml thresholds and the
research JSON path is derived so the tests' two-argument CLI stays thin.

**Exit codes** (Script Exit Code Model):

- ``0`` — gate status PASS, WARN, or NA
- ``1`` — gate status FAIL
- ``2`` — structural error (missing spec, unreadable research JSON, etc.)

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
    from research_framework.pipeline.gates_step import SG003_topic_abstraction_check
    from research_framework.spec.parser import parse as parse_spec_file
except Exception as e:  # pragma: no cover - import-time failures are fatal
    print(f"[check_abstraction] cannot import research_framework: {e}", file=sys.stderr)
    sys.exit(2)


def _pick_latest_research_json(cycles_dir: Path) -> Path | None:
    paths = sorted(cycles_dir.glob("cycle-*-research.json"))
    return paths[-1] if paths else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Run SG-003 (forbidden filename prefix abstraction) on the latest "
            "scout research JSON in a vault."
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

    cycles_dir = vault_path / "_pipeline" / "cycles"
    if not cycles_dir.is_dir():
        print(
            f"[check_abstraction] missing cycles directory: {cycles_dir}",
            file=sys.stderr,
        )
        return 2

    research_path = _pick_latest_research_json(cycles_dir)
    if research_path is None:
        print(
            f"[check_abstraction] no cycle-*-research.json under {cycles_dir}",
            file=sys.stderr,
        )
        return 2

    try:
        report = json.loads(research_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(
            f"[check_abstraction] invalid JSON in {research_path}: {e}",
            file=sys.stderr,
        )
        return 2
    if not isinstance(report, dict):
        print(
            f"[check_abstraction] scout report must be a JSON object: {research_path}",
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
