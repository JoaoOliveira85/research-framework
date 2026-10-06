"""Deterministic JSON serialisation for harness artefacts (spec 022, D2)."""

from __future__ import annotations

import difflib
import json
import math
from collections.abc import Callable
from numbers import Real
from pathlib import Path
from typing import Any

# Documented list-sort keys (first match wins per list element).
_LIST_SORT_KEYS: tuple[str, ...] = (
    "category",
    "fixture",
    "fixture_name",
    "name",
)


class DeterminismError(Exception):
    """Raised when canonical serialisation is not idempotent."""


def canonical_json_dumps(payload: Any) -> str:
    """Serialise *payload* to canonical JSON text (trailing newline included)."""
    prepared = _prepare_value(payload)
    text = json.dumps(
        prepared,
        sort_keys=True,
        indent=2,
        separators=(",", ": "),
        ensure_ascii=False,
    )
    return text + "\n"


def canonical_json_write(path: Path, payload: Any) -> None:
    """Write *payload* to *path* using :func:`canonical_json_dumps`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json_dumps(payload), encoding="utf-8")


def assert_deterministic(payload: Any, label: str) -> None:
    """Re-serialise *payload* twice; raise :class:`DeterminismError` on mismatch."""
    first = canonical_json_dumps(payload)
    round_trip = json.loads(first)
    second = canonical_json_dumps(round_trip)
    if first == second:
        return
    diff = "\n".join(
        difflib.unified_diff(
            first.splitlines(),
            second.splitlines(),
            fromfile="first_pass",
            tofile="second_pass",
            lineterm="",
        )
    )
    raise DeterminismError(
        f"determinism violation for {label!r}: canonical_json_dumps is not idempotent\n"
        f"{diff}"
    )


def _prepare_value(value: Any, *, _parent_key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {k: _prepare_value(v, _parent_key=k) for k, v in sorted(value.items())}
    if isinstance(value, list):
        prepared = [_prepare_value(item) for item in value]
        sort_key = _list_sort_key(prepared)
        if sort_key is not None:
            prepared.sort(key=sort_key)
        return prepared
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, Real) and isinstance(value, float):
        return _truncate_float(value)
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise TypeError(
        f"canonical JSON cannot encode {type(value).__name__!r} "
        f"(parent key {_parent_key!r})"
    )


def _list_sort_key(items: list[Any]) -> Callable[[Any], Any] | None:
    if not items or not all(isinstance(item, dict) for item in items):
        return None
    for key in _LIST_SORT_KEYS:
        if all(key in item for item in items):
            return lambda item: item[key]
    return None


def _truncate_float(value: float) -> float:
    if math.isnan(value) or math.isinf(value):
        return value
    return float(f"{value:.4f}")
