"""Typed read/write for extended ``_pipeline/state.json`` (spec 048 v1.1 D1)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import atomic_write

_LOG = logging.getLogger(__name__)

__all__ = [
    "BudgetSnapshot",
    "CycleState",
    "read",
    "write",
    "budget_snapshot_from_session",
]


@dataclass(frozen=True)
class BudgetSnapshot:
    wall_remaining_s: int | None
    dollar_remaining: float | None
    dollar_budget: float | None

    @classmethod
    def from_dict(cls, raw: Any) -> BudgetSnapshot | None:
        if not isinstance(raw, dict):
            return None
        wall = raw.get("wall_remaining_s")
        dollar_rem = raw.get("dollar_remaining")
        dollar_bud = raw.get("dollar_budget")
        return cls(
            wall_remaining_s=int(wall) if wall is not None else None,
            dollar_remaining=float(dollar_rem) if dollar_rem is not None else None,
            dollar_budget=float(dollar_bud) if dollar_bud is not None else None,
        )


@dataclass(frozen=True)
class CycleState:
    in_progress_cycle: int | None
    cycles_budgeted: int | None
    stage: str | None
    cycle_started_at: str | None
    budget_snapshot: BudgetSnapshot | None
    updated_at: str | None

    @property
    def active(self) -> bool:
        return self.in_progress_cycle is not None


def _state_path(vault_dir: Path) -> Path:
    return vault_dir / "_pipeline" / "state.json"


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def read(vault_dir: Path) -> CycleState | None:
    """Return parsed live state, or ``None`` when absent or corrupt."""
    path = _state_path(vault_dir)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, TypeError) as exc:
        _LOG.warning("cycle_state.read: corrupt state.json: %s", exc)
        return None
    if not isinstance(raw, dict):
        _LOG.warning("cycle_state.read: state.json root is not an object")
        return None
    ipc = raw.get("in_progress_cycle")
    return CycleState(
        in_progress_cycle=int(ipc) if ipc is not None else None,
        cycles_budgeted=(
            int(raw["cycles_budgeted"])
            if raw.get("cycles_budgeted") is not None
            else None
        ),
        stage=str(raw["stage"]) if raw.get("stage") is not None else None,
        cycle_started_at=(
            str(raw["cycle_started_at"]) if raw.get("cycle_started_at") else None
        ),
        budget_snapshot=BudgetSnapshot.from_dict(raw.get("budget_snapshot")),
        updated_at=str(raw["updated_at"]) if raw.get("updated_at") else None,
    )


def write(vault_dir: Path, **fields: Any) -> None:
    """Atomically merge ``fields`` into ``state.json`` (single writer seam)."""
    path = _state_path(vault_dir)
    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                existing = raw
        except json.JSONDecodeError:
            existing = {}
    payload = dict(existing)
    payload.update(fields)
    payload["updated_at"] = _utc_now_iso()
    try:
        atomic_write.write_json(path, payload)
    except Exception as exc:
        _LOG.warning("cycle_state.write failed: %s", exc)


def budget_snapshot_from_session(
    session: Any | None,
    *,
    cycle_started_at: str | None,
) -> dict[str, int | float | None]:
    """Best-effort mid-cycle budget snapshot for ``vault status`` (033 surfaces)."""
    if session is None:
        return {
            "wall_remaining_s": None,
            "dollar_remaining": None,
            "dollar_budget": None,
        }
    limits = session.limits
    tally = session.tally
    dollar_budget = limits.cycle_budget_usd
    dollar_remaining: float | None = None
    if dollar_budget is not None:
        dollar_remaining = round(
            max(0.0, float(dollar_budget) - float(tally.actual_usd)), 2
        )

    wall_remaining_s: int | None = None
    wall_min = limits.cycle_wallclock_budget_minutes
    if wall_min is not None and cycle_started_at:
        try:
            start = datetime.fromisoformat(cycle_started_at.replace("Z", "+00:00"))
            elapsed = (datetime.now(UTC) - start).total_seconds()
            cap_sec = int(wall_min) * 60
            wall_remaining_s = max(0, int(cap_sec - elapsed))
        except (TypeError, ValueError, OverflowError):
            wall_remaining_s = None

    return {
        "wall_remaining_s": wall_remaining_s,
        "dollar_remaining": dollar_remaining,
        "dollar_budget": float(dollar_budget) if dollar_budget is not None else None,
    }
