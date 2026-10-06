"""FR-015: O'Reilly collector uses ``search_oreilly_content`` and fails cleanly."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COLLECT_SCRIPT = REPO_ROOT / "scripts" / "collect_oreilly.py"


@pytest.mark.skipif(
    not COLLECT_SCRIPT.is_file(),
    reason="scripts/collect_oreilly.py not present in this repository",
)
def test_collect_oreilly_source_mentions_search_oreilly_content() -> None:
    text = COLLECT_SCRIPT.read_text(encoding="utf-8")
    assert "search_oreilly_content" in text, (
        "MCP tool name must be search_oreilly_content (underscores)"
    )


@pytest.mark.skipif(
    not COLLECT_SCRIPT.is_file(),
    reason="scripts/collect_oreilly.py not present in this repository",
)
def test_collect_oreilly_missing_mcp_exits_nonzero_without_traceback() -> None:
    """Without credentials / MCP, fail with a message — not a Python traceback."""
    env = {k: v for k, v in os.environ.items() if k != "OREILLY_API_KEY"}
    proc = subprocess.run(
        [
            sys.executable,
            str(COLLECT_SCRIPT),
            "--from-sources",
            "--dry-run",
        ],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0, (proc.stdout, proc.stderr)
    err = (proc.stderr or "") + (proc.stdout or "")
    assert "Traceback" not in err, err
