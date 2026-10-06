from __future__ import annotations

import argparse
import sys


def _cmd_quality_baseline_update(args: argparse.Namespace) -> int:
    from ..quality.baseline_update import update_baseline

    return update_baseline(
        args.fixture,
        reason=args.reason,
        actor=args.actor,
        dry_run=args.dry_run,
        yes=args.yes,
    )


def _cmd_quality_fixture_init(_args: argparse.Namespace) -> int:
    print(
        "fixture init is a v2 feature; for v1 fixtures use "
        "`./vault quality-baseline-update` after editing the fixture by hand",
        file=sys.stderr,
    )
    return 2
