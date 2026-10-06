"""Shared types for cycle step modules (spec 025 US6 B3)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from research_framework.pipeline._helpers.cycle_state import CycleRuntimeState

# B7 will replace with a typed VaultSettings loader; until then use mapping.
VaultSettings = Mapping[str, Any]


class AgentCallResult(Protocol):
    stdout: str
    stderr: str
    exit_code: int
    cost_usd: float


AgentDispatchFn = Callable[..., AgentCallResult]


@dataclass(frozen=True)
class ScoutedTopic:
    title: str
    coverage_category: str | None = None
    note_type: str | None = None


@dataclass(frozen=True)
class SafetyGateTrip:
    gate_id: str
    status: str
    message: str


@dataclass(frozen=True)
class VerifierRejection:
    note_path: Path
    reason: str


@dataclass(frozen=True)
class WikilinkFix:
    file_path: Path
    replacements: int


@dataclass(frozen=True)
class CoverageDelta:
    categories_updated: int = 0
    backlog_touched: bool = False


@dataclass(frozen=True)
class CycleContext:
    vault_dir: Path
    cycle_num: int
    cycle_dir: Path
    settings: VaultSettings
    dry_run: bool = False
    agent_dispatch: AgentDispatchFn | None = None
    scripts_dir: Path | None = None
    pipeline_dir: Path | None = None
    cycles_dir: Path | None = None
    prompts_dir: Path | None = None
    python_bin: str = ""
    env: dict[str, str] = field(default_factory=dict)
    max_cycles: int = 5
    budget_cap: float = 10.0
    timer_label: str | None = None
    runtime_state: CycleRuntimeState | None = None


@dataclass(frozen=True)
class ScoutResult:
    topics_found: list[ScoutedTopic]
    sg_trips: list[SafetyGateTrip]
    duration_ms: int
    cost_usd: float
    raw_json_path: Path
    exit_code: int = 0


@dataclass(frozen=True)
class ResearchResult:
    notes_written: list[Path]
    notes_rejected: list[VerifierRejection]
    duration_ms: int
    cost_usd: float
    raw_json_path: Path
    note_writer_cap_tripped: bool = False
    exit_code: int = 0


@dataclass(frozen=True)
class PostprocessResult:
    wikilink_fixes: list[WikilinkFix]
    coverage_delta: CoverageDelta
    duration_ms: int
    raw_json_path: Path
    exit_code: int = 0


class ScoutError(Exception):
    """Scout step abort (structural failure)."""

    def __init__(self, message: str = "", *, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class ResearchError(Exception):
    """Research step abort."""

    def __init__(self, message: str = "", *, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class PostprocessError(Exception):
    """Postprocess step abort."""

    def __init__(self, message: str = "", *, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code
