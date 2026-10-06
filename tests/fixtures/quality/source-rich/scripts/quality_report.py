#!/usr/bin/env python3
"""Read-only inspection of per-cycle quality reports (feature 017, quickstart §3)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_SRC = _HERE.parent / "src"
if _REPO_SRC.exists() and str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))


def _summarize_report(data: dict) -> str:
    lines = [
        f"Cycle: {data.get('cycle_number')}",
        f"Framework: {data.get('framework_version')}",
        f"Generated: {data.get('generated_at')}",
        f"Notes written / accepted / rejected: "
        f"{data.get('notes_written')} / {data.get('notes_accepted')} / "
        f"{data.get('notes_rejected')}",
        f"Queryability: {data.get('queryability_score')} "
        f"({data.get('queryability_trajectory')})",
        f"Retry count: {data.get('retry_count')} aborted={data.get('aborted')}",
        "",
        "Gates:",
    ]
    gates = data.get("gates") or {}
    if isinstance(gates, dict):
        for gk in sorted(gates.keys()):
            g = gates[gk]
            if isinstance(g, dict):
                lines.append(
                    f"  {gk}: {g.get('status')} — {g.get('metric_name')}="
                    f"{g.get('metric_value')}"
                )
    lines.append("")
    lines.append("Coverage snapshot (summary):")
    cs = data.get("coverage_snapshot") or {}
    if isinstance(cs, dict):
        for ck in sorted(cs.keys())[:12]:
            cv = cs[ck]
            if isinstance(cv, dict):
                lines.append(
                    f"  {ck}: met {cv.get('met')}/{cv.get('target')} "
                    f"(Δ {cv.get('delta_this_cycle')})"
                )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Inspect cycle quality reports.")
    p.add_argument("--vault", type=Path, required=True, help="Vault root directory")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--cycle", type=int, help="Single cycle number")
    g.add_argument("--all", action="store_true", help="Summarize all reports on disk")
    args = p.parse_args(argv)
    vault = args.vault.expanduser().resolve()
    cdir = vault / "_pipeline" / "cycles"
    if args.cycle is not None:
        name = f"cycle-{args.cycle:03d}-quality-report.json"
        path = cdir / name
        if not path.is_file():
            print(f"[quality_report] missing: {path}", file=sys.stderr)
            return 0
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"[quality_report] cannot read {path}: {e}", file=sys.stderr)
            return 0
        print(_summarize_report(data), end="")
        return 0
    rows: list[tuple[int, str, int, bool]] = []
    if cdir.is_dir():
        for path in sorted(cdir.glob("cycle-*-quality-report.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(data, dict):
                continue
            cnum = int(data.get("cycle_number") or 0)
            aborted = bool(data.get("aborted") or False)
            qs = int(data.get("queryability_score") or 0)
            rows.append((cnum, path.name, qs, aborted))
    print("cycle\tfile\tqscore\taborted")
    for cnum, fn, qs, ab in sorted(rows):
        print(f"{cnum}\t{fn}\t{qs}\t{ab}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
