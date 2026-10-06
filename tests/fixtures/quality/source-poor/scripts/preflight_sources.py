#!/usr/bin/env python3
"""Standalone preflight CLI (FR-007) — wraps pipeline.preflight.check_all."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_SRC = _HERE.parent / "src"
if _REPO_SRC.exists() and str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

from research_framework.pipeline.preflight import (  # noqa: E402
    check_all,
    load_spec_for_preflight,
)
from research_framework.spec.schema import SpecValidationError  # noqa: E402


def _summarize(result: object) -> str:
    lines = [
        f"Preflight {result.overall_status.upper()}",
        f"Framework: {result.framework_version}",
        f"Generated: {result.generated_at}",
        f"Required unreachable: {result.required_unreachable_count}",
        f"Enrichment unreachable: {result.enrichment_unreachable_count}",
        "",
        "Sources:",
    ]
    for s in result.sources:
        d = s.detail or ""
        lines.append(f"  {s.name} ({s.type}): {s.status} — {d}".rstrip())
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run source preflight for a vault.")
    p.add_argument("--vault", type=Path, required=True)
    p.add_argument("--spec", type=Path, default=None)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    vault = args.vault.expanduser().resolve()
    spec_path = args.spec if args.spec is not None else vault / "research.spec.md"
    spec_path = spec_path.expanduser().resolve()

    if not spec_path.is_file():
        print(f"error: spec not found: {spec_path}", file=sys.stderr)
        return 2

    try:
        spec = load_spec_for_preflight(spec_path, vault)
    except SpecValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    result = check_all(spec, vault)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(_summarize(result), end="")

    return 0 if result.overall_status in ("pass", "warn") else 1


if __name__ == "__main__":
    raise SystemExit(main())
