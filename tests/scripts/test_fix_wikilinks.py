"""`scripts/fix_wikilinks.py --apply` removes only the links validate_vault
flags as unresolved, and leaves the rest of the note intact.

It compared each `related` target verbatim against `_vault_note_stems`, which
holds lowercased names only, so every valid link with a capital letter or a
folder prefix (`[[Cassandra]]`, `[[01 - Concepts/Cassandra]]`) was deleted as
"unresolved". The rewrite also escaped non-ASCII (`caf\\xE9`) and grew the
body by one blank line per run.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "fix_wikilinks.py"

_NOTE = """---
title: Café Notes
related:
- '[[Cassandra]]'
- '[[01 - Concepts/Cassandra]]'
- '[[Missing Note]]'
---

Body text.
"""


def test_apply_keeps_valid_links_and_the_rest_of_the_note(tmp_path: Path) -> None:
    concepts = tmp_path / "data_vault" / "01 - Concepts"
    concepts.mkdir(parents=True)
    (concepts / "Cassandra.md").write_text("---\ntitle: Cassandra\n---\n\nx\n")
    note = concepts / "Cafe Notes.md"
    note.write_text(_NOTE, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path), "--apply"],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode in (0, 1), result.stderr
    text = note.read_text(encoding="utf-8")
    fm = yaml.safe_load(text.split("---\n")[1])
    assert fm["related"] == ["[[Cassandra]]", "[[01 - Concepts/Cassandra]]"]
    assert "title: Café Notes" in text
    assert text.endswith("---\n\nBody text.\n"), repr(text[-40:])


# Keys in the order the verifier's stamp leaves them (``yaml.dump`` sorts), so
# ``related`` sits above the slug URL and the cut frontmatter still parses.
_SLUG_NOTE = """---
related:
- '[[Cassandra]]'
- '[[Missing Note]]'
source_urls:
- https://example.com/kafka---a-guide
title: Slug Notes
---

Body text.
"""


def test_apply_keeps_a_frontmatter_value_containing_dashes(tmp_path: Path) -> None:
    """The frontmatter ends at a ``---`` line, not at the first ``---`` substring."""
    concepts = tmp_path / "data_vault" / "01 - Concepts"
    concepts.mkdir(parents=True)
    (concepts / "Cassandra.md").write_text("---\ntitle: Cassandra\n---\n\nx\n")
    note = concepts / "Slug Notes.md"
    note.write_text(_SLUG_NOTE, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path), "--apply"],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode in (0, 1), result.stderr
    assert note.read_text(encoding="utf-8") == _SLUG_NOTE.replace(
        "- '[[Missing Note]]'\n", ""
    )
