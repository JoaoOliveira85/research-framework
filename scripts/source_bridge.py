#!/usr/bin/env python3
"""CLI entry point for the source-extraction subprocess (spec 020)."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from research_framework.pipeline.settings import load_vault_settings  # noqa: E402
from research_framework.pipeline.source_bridge.discovery import (  # noqa: E402
    build_trigger_registry,
    order_modules,
    walk_modules,
)
from research_framework.pipeline.source_bridge.orchestrator import (  # noqa: E402
    run_extraction,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Source-bridge extraction stage")
    parser.add_argument(
        "--vault", type=Path, required=True, help="Vault root directory"
    )
    parser.add_argument("--cycle", type=int, default=1, help="Cycle number")
    parser.add_argument(
        "--debug-triggers",
        nargs="?",
        const="",
        default=None,
        metavar="TARGET",
        help="Print trigger registry resolution for TARGET",
    )
    parser.add_argument(
        "--force-stale-schema",
        action="store_true",
        help="Proceed once despite manual schema drift (D8)",
    )
    return parser


def _debug_triggers(vault_dir: Path, target: str) -> int:
    settings = load_vault_settings(vault_dir)
    manifests = order_modules(walk_modules(vault_dir), list(settings.modules))
    registry = build_trigger_registry(manifests)
    print("# Trigger Registry (settings.yaml::modules order)\n")
    print("| Order | Module | Trigger type | Pattern | Matched? |")
    print("|-------|--------|--------------|---------|----------|")
    match = registry.match(target)
    matched_module = match[0] if match else None
    for entry in registry.entries:
        matched = entry.module == matched_module
        print(
            f"| {entry.order} | {entry.module} | {entry.trigger_type} | "
            f"{entry.pattern[:40]} | {'YES' if matched else 'NO'} |"
        )
    if matched_module:
        print(f"\n# Resolution: source matched module {matched_module!r}")
    else:
        print("\n# Resolution: no module matched")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Spec 048: this is a standalone script (not invoked via the main CLI),
    # so it does its own root-logger wiring. INFO is the right floor —
    # `_log_source_status` fires per-source and was previously a bare
    # `print(..., file=sys.stderr)`, i.e. always-on. Idempotent against a
    # prior basicConfig call (e.g. if some import already wired one).
    if not logging.root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            stream=sys.stderr,
        )
    args = _build_parser().parse_args(argv)
    vault_dir = args.vault.resolve()
    if args.debug_triggers is not None:
        return _debug_triggers(vault_dir, args.debug_triggers)
    summary = run_extraction(
        vault_dir,
        args.cycle,
        force_stale_schema=args.force_stale_schema,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
