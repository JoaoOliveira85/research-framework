"""Schema drift CLI helpers (spec 020 D8)."""

from __future__ import annotations

import argparse
from pathlib import Path

from research_framework.pipeline.source_bridge.schema_gen import acknowledge_drift


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Per-module facts schema utilities")
    sub = parser.add_subparsers(dest="command", required=True)
    ack = sub.add_parser(
        "acknowledge-drift", help="Merge regenerated schema and clear drift"
    )
    ack.add_argument("module", help="Module name (e.g. code)")
    ack.add_argument("--vault", type=Path, required=True, help="Vault root")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "acknowledge-drift":
        acknowledge_drift(args.vault.resolve(), args.module)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
