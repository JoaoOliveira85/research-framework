#!/usr/bin/env python3
"""Standalone research-branch retention CLI (issue #307, spec 072 FR5 follow-up).

Spec 072 FR5 keeps a run's `research/<date>-<time>` branch after landing it
on main so a bad landing is one `git reset` away — that guarantee is
unchanged. Since D10 (2026-09-08) the framework applies a retention policy
itself — `settings.yaml::vault_commit.retention` (`keep_last`, default 5;
`max_age_days`, default 90) — when a session starts and after a run lands.
This is the manual verb the policy keeps for an operator (or a scheduled
job) to trim on demand, or to see what the automatic pass would do:

    scripts/prune_research_branches.py <vault> list
    scripts/prune_research_branches.py <vault> prune [--keep-last N]
                                                   [--max-age-days N] [--yes]

`prune` is dry-run by default (prints what it would delete); pass `--yes` to
actually delete. A flag overrides the vault's configured ceiling for that
run only; an omitted flag means "use the vault's setting" — a flag can only
tighten or loosen a ceiling, not switch one OFF (that is `null` in
`settings.yaml`, deliberately not a CLI knob). An unlanded
branch is never a deletion candidate, at any age or count — see
`pipeline/branch_retention.py`'s module docstring for how "landed" is
verified (it isn't commit ancestry).
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_SRC = _HERE.parent / "src"
if _REPO_SRC.exists() and str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

from research_framework.pipeline.branch_retention import (  # noqa: E402
    RetentionPolicy,
    format_prune_report,
    list_research_branches,
    load_retention_policy,
    prune_research_branches,
)


def _cmd_list(vault: Path) -> int:
    branches = list_research_branches(vault)
    if not branches:
        print("no research/* branches")
        return 0
    now = datetime.now(UTC)
    for b in branches:
        status = "landed" if b.landed else "UNLANDED"
        age = b.age(now)
        age_text = f"{age.days}d" if age is not None else "?"
        print(f"{b.name}\t{status}\ttip={b.tip_committed_at}\tage={age_text}")
    return 0


def _cmd_prune(vault: Path, *, policy: RetentionPolicy, yes: bool) -> int:
    result = prune_research_branches(
        vault,
        keep_last=policy.keep_last,
        max_age_days=policy.max_age_days,
        dry_run=not yes,
    )
    verb = "deleted" if yes else "would delete"
    for name in result.deleted:
        print(f"{verb}: {name} ({result.reasons.get(name, '?')})")
    for name in result.kept_unlanded:
        print(f"kept (unlanded, never touched): {name}")
    keep_text = (
        f"within keep-last {policy.keep_last}"
        if policy.keep_last is not None
        else "no keep-last ceiling"
    )
    age_text = (
        f"max-age-days {policy.max_age_days}"
        if policy.max_age_days is not None
        else "no age ceiling"
    )
    for name in result.kept_landed:
        print(f"kept (landed, {keep_text}, {age_text}): {name}")

    print()
    print(format_prune_report(result, policy))
    if not yes and result.deleted:
        print("(dry run — pass --yes to actually delete)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="List or prune a vault's research/<date>-<time> branches."
    )
    parser.add_argument("vault", type=Path, help="Path to the vault root directory")
    sub = parser.add_subparsers(dest="action", required=True)

    sub.add_parser(
        "list", help="List every research/* branch with its landed/unlanded status"
    )

    pr = sub.add_parser(
        "prune",
        help=(
            "Delete landed research/* branches beyond --keep-last or older than "
            "--max-age-days (dry-run unless --yes is passed)"
        ),
    )
    pr.add_argument(
        "--keep-last",
        type=int,
        default=None,
        dest="keep_last",
        help=(
            "Number of newest landed branches to keep "
            "(default: settings.yaml vault_commit.retention.keep_last, else 5)"
        ),
    )
    pr.add_argument(
        "--max-age-days",
        type=int,
        default=None,
        dest="max_age_days",
        help=(
            "Delete landed branches whose tip is older than this many days "
            "(default: settings.yaml vault_commit.retention.max_age_days, else 90)"
        ),
    )
    pr.add_argument(
        "--yes",
        action="store_true",
        help="Actually delete. Without it, prints what would be deleted and exits.",
    )

    args = parser.parse_args(argv)
    vault = args.vault.expanduser().resolve()
    if not vault.is_dir():
        print(f"error: not a directory: {vault}", file=sys.stderr)
        return 2

    if args.action == "list":
        return _cmd_list(vault)

    configured = load_retention_policy(vault)
    keep_last = args.keep_last if args.keep_last is not None else configured.keep_last
    max_age_days = (
        args.max_age_days if args.max_age_days is not None else configured.max_age_days
    )
    if keep_last is not None and keep_last < 0:
        print("error: --keep-last must be >= 0", file=sys.stderr)
        return 2
    if max_age_days is not None and max_age_days < 1:
        print("error: --max-age-days must be >= 1", file=sys.stderr)
        return 2
    policy = RetentionPolicy(keep_last=keep_last, max_age_days=max_age_days)
    return _cmd_prune(vault, policy=policy, yes=args.yes)


if __name__ == "__main__":
    raise SystemExit(main())
