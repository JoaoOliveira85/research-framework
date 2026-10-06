#!/usr/bin/env python3
"""Run queryability probes for one cycle; writes cycle-NNN-probe-results.json (read-only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_SRC = _HERE.parent / "src"
if _REPO_SRC.exists() and str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

from research_framework.pipeline.probes import run_cycle_probes  # noqa: E402
from research_framework.pipeline.quality_report import _load_spec_config  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Run deterministic probe scoring for one cycle."
    )
    p.add_argument("--vault", type=Path, required=True, help="Vault root directory")
    p.add_argument("--cycle", type=int, required=True, help="Cycle number (>=1)")
    p.add_argument(
        "--spec",
        type=Path,
        default=None,
        help="Optional research.spec.md path (must exist if passed)",
    )
    args = p.parse_args(argv)
    vault_dir = args.vault.expanduser().resolve()
    cycle = max(1, int(args.cycle))

    note: str | None = None
    if args.spec is not None:
        spec_path = args.spec.expanduser().resolve()
        if spec_path.is_file():
            from research_framework.spec.simple import (
                load as load_spec,
            )

            spec = load_spec(spec_path, location=vault_dir)
        else:
            note = "missing spec"
            spec = _load_spec_config(vault_dir)
    else:
        spec = _load_spec_config(vault_dir)

    try:
        score, trajectory = run_cycle_probes(
            vault_dir=vault_dir, spec=spec, cycle_number=cycle
        )
    except Exception:
        score, trajectory = 0, "stable"
        note = note or "probe run failed"

    out: dict[str, str | int] = {"score": int(score), "trajectory": trajectory}
    if note:
        out["note"] = note
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
