"""Shared helpers for scripts/source_ledger.py tests (spec 048 v2)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

FIXTURE_ROOT = Path(__file__).parent.parent / "fixtures" / "source_ledger"
SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "source_ledger.py"


def fixture_vault(path: Path) -> Path:
    """Return the vault root for a fixture under tests/fixtures/source_ledger/."""
    candidate = path if path.is_absolute() else FIXTURE_ROOT / path
    return candidate.resolve()


def run_ledger(
    vault: Path | str | None, *args: str
) -> subprocess.CompletedProcess[str]:
    """Invoke scripts/source_ledger.py via the active test interpreter."""
    src_root = SCRIPT.parent.parent / "src"
    env = {**os.environ, "PYTHONPATH": str(src_root)}
    cmd = [sys.executable, str(SCRIPT)]
    if vault is not None:
        cmd.extend(["--vault", str(vault)])
    cmd.extend(args)
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def load_ledger_json(cycle_path: Path) -> dict:
    """Load cycle-NNN-source-ledger.json from a vault or cycles directory."""
    path = cycle_path
    if path.is_dir():
        candidates = [
            *sorted(path.glob("cycle-*-source-ledger.json")),
            *sorted((path / "_pipeline" / "cycles").glob("cycle-*-source-ledger.json")),
        ]
        if not candidates:
            raise FileNotFoundError(f"no source-ledger JSON under {cycle_path}")
        path = candidates[0]
    return json.loads(path.read_text(encoding="utf-8"))
