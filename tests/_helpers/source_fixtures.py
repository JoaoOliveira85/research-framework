"""Declared-source / source-ledger fixture builders (spec 069 T001/T002).

These build the rc7-shaped declared-source spec and a multi-cycle source-ledger
vault (a source cold for >= 2 consecutive cycles) used by the FR1/FR2 backing
tests and the FR3/FR5 stagnant-source tests, without committing static trees.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

_FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "source_ledger"


def build_cold_source_vault(
    tmp_path: Path,
    *,
    cold_cycles: int = 2,
    source_name: str = "GitHub Pull Requests",
) -> Path:
    """Copy the ``skipped_relevance`` fixture and extend it to ``cold_cycles``.

    Each added cycle re-runs (scout present) with the source ``searched`` but
    given a relevance reason ⇒ ``SKIPPED_RELEVANCE`` ⇒ a cold cycle. The result
    is a vault where ``source_name`` is cold for ``cold_cycles`` consecutive
    cycles (T002).
    """
    vault = tmp_path / "cold-source-vault"
    shutil.copytree(_FIXTURE_ROOT / "skipped_relevance", vault)
    cycles_dir = vault / "_pipeline" / "cycles"
    for cycle in range(2, cold_cycles + 1):
        (cycles_dir / f"cycle-{cycle:03d}-scout.json").write_text(
            json.dumps(
                {
                    "schema_version": "2.0",
                    "cycle": cycle,
                    "phase": "scout",
                    "sources_consulted": [
                        {
                            "name": source_name,
                            "searched": True,
                            "reason": "Outside vault scope",
                        }
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (cycles_dir / f"cycle-{cycle:03d}-research.json").write_text(
            json.dumps(
                {"schema_version": "1.0", "cycle": cycle, "capture_failures": []}
            )
            + "\n",
            encoding="utf-8",
        )
    return vault
