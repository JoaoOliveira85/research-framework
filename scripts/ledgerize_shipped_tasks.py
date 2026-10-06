#!/usr/bin/env python3
"""Turn a shipped spec's checked task boxes into a plain ledger (issue #279).

576 ``- [x]`` boxes sat across 26 ``tasks.md`` files and nothing read them —
the foreman parses the box only to delimit a task, and ~40% of checked
lines are process/checkpoint steps ("confirm clean working tree") with no
independently-verifiable evidence at all, so requiring every box to cite a
test/PR/commit would be inventing citations for work that predates this
convention. That is the option the issue itself offers instead: **the boxes
are converted to a plain ledger** — a checkbox on a *shipped* spec's frozen
tasks.md (CONTRIBUTING.md § 2: "frozen at ship") was never a live gate to
begin with, so stop drawing it as one.

Only ``- [x]`` (done) markers are stripped to a plain ``- `` bullet. A
leftover ``- [ ]`` (never checked) is left exactly as-is: on a shipped spec
that is a real, honest signal — a sub-task that was never completed (e.g.
spec 049's 4, spec 070's 1) — and stripping it would erase that signal
instead of just retiring a redundant one. See
``tests/docs/test_shipped_tasks_are_a_ledger.py`` for the enforced shape.

Scope: every spec whose canonical Status header (see
``normalize_spec_status.py``) opens with ``shipped(``. Draft/in-progress
specs keep live checkboxes — those tasks.md files are still real trackers.

Usage::

    python scripts/ledgerize_shipped_tasks.py            # apply
    python scripts/ledgerize_shipped_tasks.py --dry-run   # report only

Exit codes: 0 always — one-time migration aid, not a CI gate.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from scripts.normalize_spec_status import SPECS_DIR, find_status_header

CHECKED_BOX_PATTERN = re.compile(r"^(\s*-\s*)\[[xX]\]\s+", re.MULTILINE)
_LEDGER_BANNER = (
    "> **Ledger** — this spec shipped; the boxes below are a historical "
    "record, not a live gate (CONTRIBUTING.md § 2). The Status header in "
    "`spec.md` is the source of truth for what shipped.\n"
)


def is_shipped(spec_dir: Path) -> bool:
    spec_md = spec_dir / "spec.md"
    if not spec_md.is_file():
        return False
    header = find_status_header(spec_md.read_text(encoding="utf-8"))
    return header is not None and header.value.startswith("shipped(")


def ledgerize(text: str) -> str:
    """Strip ``[x]``/``[X]`` markers and add the ledger banner (idempotent:
    a text with no checked boxes and an existing banner is returned as-is)."""
    lines = text.splitlines(keepends=True)
    changed = False
    for i, line in enumerate(lines):
        new_line = CHECKED_BOX_PATTERN.sub(r"\1", line)
        if new_line != line:
            lines[i] = new_line
            changed = True
    text = "".join(lines)
    if changed and _LEDGER_BANNER not in text:
        text = _insert_banner(text)
    return text


def _insert_banner(text: str) -> str:
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.startswith("# "):
            lines[i + 1 : i + 1] = ["\n", _LEDGER_BANNER]
            return "".join(lines)
    return _LEDGER_BANNER + text


def process_spec(spec_dir: Path, dry_run: bool) -> str | None:
    tasks_md = spec_dir / "tasks.md"
    if not tasks_md.is_file() or not is_shipped(spec_dir):
        return None
    original = tasks_md.read_text(encoding="utf-8")
    updated = ledgerize(original)
    if updated == original:
        return None
    if not dry_run:
        tasks_md.write_text(updated, encoding="utf-8")
    tag = "[dry-run] " if dry_run else ""
    checked = len(CHECKED_BOX_PATTERN.findall(original))
    return f"{tag}LEDGERIZED {spec_dir.name}: {checked} boxes converted"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    reports = [
        process_spec(spec_dir, args.dry_run) for spec_dir in sorted(SPECS_DIR.iterdir())
    ]
    for line in filter(None, reports):
        print(line)
    print(f"\n{sum(1 for r in reports if r)} tasks.md files ledgerized")
    return 0


if __name__ == "__main__":
    sys.exit(main())
