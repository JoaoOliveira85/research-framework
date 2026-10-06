"""Spec 048 observability surfaces: Tier-5 logger + Tier-6 ``bridge.log``.

Exports the ``BridgeLogWriter`` (per-cycle file + lock + framing) and
``start_capture`` (reader thread). The ``current_bridge_writer``
ContextVar carries the active writer for the current cycle so the
source-bridge extractor can find it without threading it through every
function signature in the pipeline call chain.

The ``publish_bridge_writer`` context manager is the only sanctioned way
to mutate ``current_bridge_writer`` — it pushes the writer on entry and
**resets the token** on exit. Direct ``.set()`` calls without a matching
``.reset(token)`` will leak a closed-writer reference into later
``run_cycle_steps`` invocations in the same process (real bug seen
under the full pytest suite — extractor invocations in later tests
tried to write to a closed file and marked their source as failed).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from .bridge_log import BridgeLogWriter, KillReason, PayloadVerdict
from .extractor_capture import start_capture

current_bridge_writer: ContextVar[BridgeLogWriter | None] = ContextVar(
    "current_bridge_writer", default=None
)


@contextmanager
def publish_bridge_writer(writer: BridgeLogWriter) -> Iterator[BridgeLogWriter]:
    """Publish ``writer`` on ``current_bridge_writer`` for the duration of the block.

    Use as a ``with``-clause alongside ``BridgeLogWriter(...)`` so the
    writer is both opened AND advertised to the extractor call chain for
    exactly the lifetime of one cycle. The token is reset on exit even
    if the body raises, preventing stale-writer leakage across cycles
    (and across pytest test boundaries).
    """
    token = current_bridge_writer.set(writer)
    try:
        yield writer
    finally:
        current_bridge_writer.reset(token)


__all__ = [
    "BridgeLogWriter",
    "KillReason",
    "PayloadVerdict",
    "current_bridge_writer",
    "publish_bridge_writer",
    "start_capture",
]
