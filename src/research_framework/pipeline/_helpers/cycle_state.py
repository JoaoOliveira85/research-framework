"""Per-cycle mutable flags (spec 049 US3)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CycleRuntimeState:
    """Mutable runtime flags for a single cycle invocation."""

    should_abort: bool = False
    note_writer_cap_tripped: bool = False
