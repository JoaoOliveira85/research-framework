"""The operator's persistent rejects (``propose-rejects.md``).

Shared by the orchestrator (the scout prompt's skip list) and the discovery
routing (a discovery row that names one is dropped), so neither reaches into the
other for a private helper.
"""

from __future__ import annotations

from pathlib import Path

from . import state_layout


def persistent_reject_titles(vault_dir: Path) -> list[str]:
    """Read the persistent propose rejects and return titles to exclude.

    Format written by ``scripts/topic_propose.py`` is::

        - **<title>** — cycle NNN (YYYY-MM-DD): <reason>

    We parse the bolded title from each bullet. Unknown lines are
    silently skipped (the file is human-editable — users may add
    comments or custom annotations).
    """
    import re as _re

    path = state_layout.propose_rejects_path(vault_dir)
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[str] = []
    for line in text.splitlines():
        m = _re.match(r"^\s*-\s+\*\*([^*\n]+?)\*\*", line)
        if m:
            title = m.group(1).strip()
            if title:
                out.append(title)
    return out
