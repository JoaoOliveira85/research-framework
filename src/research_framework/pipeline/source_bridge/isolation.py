"""Retry-once + salvage isolation (D9)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from ..atomic_write import write_json, write_text
from .agent_logging import record_from_dispatch, write_agent_call_record
from .cache import append_bridge_log, quarantine_dir

logger = logging.getLogger(__name__)

T = TypeVar("T")


def isolated_call(
    fn: Callable[..., T],
    *args: Any,
    vault_dir: Path,
    module: str,
    source_id: str,
    kind: str,
    cycle: int | None = None,
    **kwargs: Any,
) -> T | None:
    """Run ``fn`` with retry-once; return None after double failure (D9)."""
    last_exc: BaseException | None = None
    partial_output: Any = None
    for attempt in (1, 2):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            partial_output = getattr(exc, "partial", None) or partial_output
            _log_failure(
                vault_dir,
                module,
                source_id,
                kind,
                attempt,
                exc,
                cycle=cycle,
            )
            if attempt == 1:
                continue
    if partial_output is not None and kind == "extractor":
        _write_quarantine(vault_dir, module, source_id, partial_output)
    mark_source_failed(vault_dir, module, source_id, kind, last_exc)
    return None


def mark_source_failed(
    vault_dir: Path,
    module: str,
    source_id: str,
    kind: str,
    exc: BaseException | None,
) -> None:
    """Record isolated failure without aborting other modules."""
    msg = str(exc) if exc else "unknown"
    append_bridge_log(
        vault_dir,
        module,
        f"[{datetime.now(UTC).isoformat()}] FAILED {kind} {source_id}: {msg}",
    )


def _log_failure(
    vault_dir: Path,
    module: str,
    source_id: str,
    kind: str,
    attempt: int,
    exc: BaseException,
    *,
    cycle: int | None = None,
) -> None:
    msg = (
        f"[{datetime.now(UTC).isoformat()}] attempt={attempt} {kind} {source_id}: {exc}"
    )
    append_bridge_log(vault_dir, module, msg)
    if cycle is not None:
        record = record_from_dispatch(
            stage=f"source_bridge_{kind}",
            prompt=f"{module}/{source_id}",
            response=str(exc),
            model="isolation",
            tier=None,
            latency_ms=0,
            error=str(exc),
            retry_attempt=attempt,
        )
        write_agent_call_record(vault_dir, cycle, record)


def _write_quarantine(
    vault_dir: Path,
    module: str,
    source_id: str,
    partial_output: Any,
) -> None:
    qdir = quarantine_dir(vault_dir, module)
    safe = source_id.replace("/", "_")[:120]
    path = qdir / f"{safe}.partial.json"
    if isinstance(partial_output, (dict, list)):
        write_json(path, partial_output)
    else:
        write_text(path, str(partial_output))
