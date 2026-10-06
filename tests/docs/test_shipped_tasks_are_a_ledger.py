"""Shipped-spec task-ledger guard (issue #279).

576 ``- [x]`` boxes sat across 26 ``tasks.md`` files and nothing read them
— the foreman parses the box only to delimit a task, and ~40% of checked
lines are process/checkpoint steps ("confirm clean working tree") with no
independently-verifiable evidence, so requiring every box to cite a test/
PR/commit would mean inventing citations for work that predates that
convention. The issue itself names the alternative: convert the boxes to a
plain ledger. ``scripts/ledgerize_shipped_tasks.py`` did that migration —
this test is what keeps it from rotting: once a spec's canonical Status
header (issue #279's other half) says ``shipped(...)``, its tasks.md may no
longer carry a ``- [x]`` box. A leftover ``- [ ]`` is untouched by design —
on a shipped spec that is real signal (a sub-task genuinely never done, e.g.
spec 070's T040), not something to silently launder away.
"""

from __future__ import annotations

from pathlib import Path

from scripts.ledgerize_shipped_tasks import CHECKED_BOX_PATTERN
from scripts.normalize_spec_status import SPECS_DIR, find_status_header


def _shipped_spec_dirs() -> list[Path]:
    dirs = []
    for spec_dir in sorted(SPECS_DIR.iterdir()):
        spec_md = spec_dir / "spec.md"
        if not spec_md.is_file():
            continue
        header = find_status_header(spec_md.read_text(encoding="utf-8"))
        if header is not None and header.value.startswith("shipped("):
            dirs.append(spec_dir)
    return dirs


def test_shipped_specs_have_no_checked_boxes_left() -> None:
    failures: list[str] = []
    for spec_dir in _shipped_spec_dirs():
        tasks_md = spec_dir / "tasks.md"
        if not tasks_md.is_file():
            continue
        text = tasks_md.read_text(encoding="utf-8")
        hits = CHECKED_BOX_PATTERN.findall(text)
        if hits:
            failures.append(
                f"{spec_dir.name}/tasks.md: {len(hits)} `- [x]` box(es) left"
            )
    assert failures == [], "shipped specs with un-ledgerized task boxes:\n" + "\n".join(
        f"  - {f}" for f in failures
    )


# --- inline mini-suite (regex behaviour, independent of repo content) -----


def test_checked_box_pattern_matches_lower_and_upper_x() -> None:
    assert CHECKED_BOX_PATTERN.search("- [x] T001 Do the thing.\n")
    assert CHECKED_BOX_PATTERN.search("- [X] T001 Do the thing.\n")


def test_checked_box_pattern_does_not_match_unchecked() -> None:
    assert not CHECKED_BOX_PATTERN.search("- [ ] T001 Not done yet.\n")


def test_checked_box_pattern_matches_indented_bullets() -> None:
    assert CHECKED_BOX_PATTERN.search("  - [x] T001 Nested under a phase heading.\n")
