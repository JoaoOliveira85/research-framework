"""Guard: every ADR file is indexed, and every indexed row has a file (#277).

ADR-0009's index row went stale (still said "Proposed" after the ADR's own
Status line had moved to "Accepted") because nothing checked the two stayed
in sync. This does not verify the row's *content* — the file itself is the
source of truth for status — only that the index and the directory listing
name the same set of ADRs, so a new ADR can't ship un-indexed and a
renamed/deleted one can't leave a dangling link.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ADR_DIR = REPO_ROOT / "docs" / "adr"

_FILENAME_RE = re.compile(r"^(\d{4})-[a-z0-9-]+\.md$")
_INDEX_ROW_RE = re.compile(r"\[(\d{4})\]\(\.\/(\d{4}-[a-z0-9-]+\.md)\)")


def _adr_files() -> dict[str, str]:
    """Map ADR number -> filename, for every ``NNNN-*.md`` under docs/adr/."""
    found = {}
    for path in sorted(ADR_DIR.glob("*.md")):
        if path.name == "README.md":
            continue
        m = _FILENAME_RE.match(path.name)
        assert m, f"{path.name} does not match the NNNN-kebab-title.md convention"
        found[m.group(1)] = path.name
    return found


def _index_rows() -> dict[str, str]:
    """Map ADR number -> filename, as linked from README.md's index table."""
    text = (ADR_DIR / "README.md").read_text(encoding="utf-8")
    return {number: filename for number, filename in _INDEX_ROW_RE.findall(text)}


def test_every_adr_file_is_indexed() -> None:
    files = _adr_files()
    indexed = _index_rows()
    missing = sorted(set(files) - set(indexed))
    assert not missing, (
        f"docs/adr/README.md's index is missing a row for: {missing} "
        "— add one (see CONTRIBUTING.md §6)."
    )


def test_every_index_row_names_a_real_file() -> None:
    files = _adr_files()
    indexed = _index_rows()
    dangling = sorted(set(indexed) - set(files))
    assert not dangling, (
        f"docs/adr/README.md indexes ADR(s) with no matching file: {dangling}"
    )


def test_index_row_filename_matches_the_actual_file() -> None:
    files = _adr_files()
    indexed = _index_rows()
    mismatched = {
        number: (indexed[number], files[number])
        for number in files
        if number in indexed and indexed[number] != files[number]
    }
    assert not mismatched, (
        "docs/adr/README.md links a filename that doesn't match the file on "
        f"disk (number -> (linked, actual)): {mismatched}"
    )
