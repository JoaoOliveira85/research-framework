"""Importable wrapper around scripts/vault_metrics.py logic."""

from __future__ import annotations

# Re-use the collect() function from the scripts bundle
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(_SCRIPTS))
from vault_metrics import collect as _collect  # noqa: E402


@dataclass
class VaultMetrics:
    note_count: int
    by_type: dict[str, int]
    by_folder: dict[str, int]
    word_count_buckets: dict[str, int]
    unresolved_wikilinks: int
    timestamp: str = ""
    vault: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VaultMetrics:
        return cls(
            note_count=int(d.get("note_count", 0)),
            by_type=dict(d.get("by_type", {}) or {}),
            by_folder=dict(d.get("by_folder", {}) or {}),
            word_count_buckets=dict(d.get("word_count_buckets", {}) or {}),
            unresolved_wikilinks=int(d.get("unresolved_wikilinks", 0)),
            timestamp=d.get("timestamp", ""),
            vault=d.get("vault", ""),
        )


def collect(vault_dir: Path) -> VaultMetrics:
    return VaultMetrics.from_dict(_collect(vault_dir))
