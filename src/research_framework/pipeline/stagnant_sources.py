"""Stagnant-source WARN signal (spec 069 FR3/FR5).

A deterministic, **advisory** signal that surfaces declared sources which yield
nothing for ``>= 2`` consecutive cycles. It reuses the existing
``degraded_sources`` surface in the cycle quality report (no new artifact) and
NEVER blocks or FAILs a cycle — the hard gate is the FR1/FR2 backing validation.

Per-cycle "cold" is read from ``scripts/source_ledger.py`` verdicts: a cycle is
cold for a source unless that source was demonstrably *used* (``USED`` or the
citation-evidenced ``LEDGER_DISAGREEMENT``). When multiple sources are cold the
signals are ranked by authority (``source_authority.build_source_role_index``)
so an authoritative source going cold is surfaced first (FR5 — a worse smell).

See ``specs/069-source-relevance-tuning/contracts/stagnant-source-signal.contract.md``.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .source_authority import build_source_role_index, normalise_source_id

_LOG = logging.getLogger(__name__)

__all__ = [
    "StagnantSourceSignal",
    "STAGNANT_PREFIX",
    "MIN_COLD_CYCLES",
    "USED_VERDICTS",
    "trailing_cold_count",
    "role_authority_rank",
    "stagnant_signals_from_verdicts",
    "detect_stagnant_sources",
    "stagnant_warnings",
]

# A line prefix both surfaces (quality report + status) key off so the two
# always agree on which ``degraded_sources`` entries are stagnant signals.
STAGNANT_PREFIX = "stagnant source"

# Verdicts that mean "the source was actually used this cycle" — everything
# else (SKIPPED_RELEVANCE, ACCESS_FAIL, PIPELINE_DROP, QUALITY_REJECT,
# NOT_REACHED) counts as a cold cycle.
USED_VERDICTS: frozenset[str] = frozenset({"USED", "LEDGER_DISAGREEMENT"})

MIN_COLD_CYCLES = 2

# Lower rank == more authoritative; an unrecognised role sorts last.
_ROLE_AUTHORITY: dict[str, int] = {"behaviour": 0, "intent": 1, "domain": 2}
_DEFAULT_AUTHORITY = 99


@dataclass(frozen=True)
class StagnantSourceSignal:
    """One cold declared source (data-model Entity 4)."""

    name: str
    cold_cycles: int
    role: str
    authority_rank: int
    priority: int

    @property
    def message(self) -> str:
        return (
            f"{STAGNANT_PREFIX} `{self.name}`: cold {self.cold_cycles} "
            f"consecutive cycles (role={self.role or 'unknown'})"
        )


def role_authority_rank(role: str) -> int:
    """Map a declared ``role`` to a sortable authority rank (lower = stronger)."""
    return _ROLE_AUTHORITY.get((role or "").strip().lower(), _DEFAULT_AUTHORITY)


def trailing_cold_count(verdicts: Sequence[str]) -> int:
    """Count the trailing run of cold cycles (oldest→newest verdict order).

    Counts back from the most recent cycle and stops at the first cycle the
    source was used. Pure: same inputs ⇒ same count.
    """
    count = 0
    for verdict in reversed(list(verdicts)):
        if verdict in USED_VERDICTS:
            break
        count += 1
    return count


def stagnant_signals_from_verdicts(
    verdicts_by_source: Mapping[str, Sequence[str]],
    roles: Mapping[str, str],
    priorities: Mapping[str, int] | None = None,
    *,
    min_cold: int = MIN_COLD_CYCLES,
) -> list[StagnantSourceSignal]:
    """Pure core: build the (authority-sorted) signal list from verdict lists.

    ``verdicts_by_source`` maps a declared source name to its per-cycle verdict
    strings ordered oldest→newest. A source with ``>= min_cold`` trailing cold
    cycles emits exactly one signal. Ranking (FR5): authority asc, then
    cold-cycles desc, then declared priority asc, then name.
    """
    priorities = priorities or {}
    signals: list[StagnantSourceSignal] = []
    for name, verdicts in verdicts_by_source.items():
        cold = trailing_cold_count(verdicts)
        if cold < min_cold:
            continue
        role = roles.get(name, "")
        signals.append(
            StagnantSourceSignal(
                name=name,
                cold_cycles=cold,
                role=role,
                authority_rank=role_authority_rank(role),
                priority=int(priorities.get(name, 2)),
            )
        )
    signals.sort(key=lambda s: (s.authority_rank, -s.cold_cycles, s.priority, s.name))
    return signals


def _load_source_ledger(vault_dir: Path):
    """Import ``scripts/source_ledger.py`` by path (vault copy, then framework).

    Returns the module or ``None`` when no copy is reachable — the caller then
    degrades to "no stagnant signal" (advisory, never fatal).
    """
    candidates: list[Path] = [vault_dir / "scripts" / "source_ledger.py"]
    # src/research_framework/pipeline/stagnant_sources.py → parents[3] == repo root.
    candidates.append(
        Path(__file__).resolve().parents[3] / "scripts" / "source_ledger.py"
    )
    for path in candidates:
        if not path.is_file():
            continue
        try:
            spec = importlib.util.spec_from_file_location("source_ledger", path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules["source_ledger"] = module
            spec.loader.exec_module(module)
            return module
        except Exception as exc:  # pragma: no cover - defensive
            _LOG.warning(
                "stagnant: could not load source_ledger from %s: %s", path, exc
            )
            sys.modules.pop("source_ledger", None)
            continue
    return None


def _roles_for_sources(
    spec: object, vault_dir: Path, sources: Sequence[object]
) -> dict[str, str]:
    """Resolve each declared source's authoritative role (FR5 weighting).

    Prefers the ``source_id → role`` lookup from
    :func:`source_authority.build_source_role_index` (the canonical attribution),
    falling back to the source's own declared ``role``.
    """
    from ..spec.source_backing import source_locator

    index = build_source_role_index(spec, vault_dir)
    roles: dict[str, str] = {}
    for source in sources:
        name = getattr(source, "name", "")
        declared_role = getattr(source, "role", "") or ""
        resolved: str | None = None
        locator = source_locator(source)
        if locator:
            resolved = index.exact.get(normalise_source_id(locator))
        roles[name] = resolved or declared_role
    return roles


def detect_stagnant_sources(
    vault_dir: Path,
    current_cycle: int,
    *,
    min_cold: int = MIN_COLD_CYCLES,
) -> list[StagnantSourceSignal]:
    """Compute stagnant-source signals for the cycles run up to ``current_cycle``.

    Read-only join over ``scripts/source_ledger.py`` per-cycle verdicts. Returns
    ``[]`` (never raises) when the ledger script or spec is unavailable.
    """
    if current_cycle < min_cold:
        return []
    ledger = _load_source_ledger(vault_dir)
    if ledger is None:
        return []
    try:
        sources = ledger.load_declared_sources(vault_dir)
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("stagnant: load_declared_sources failed: %s", exc)
        return []
    if not sources:
        return []

    verdicts_by_source: dict[str, list[str]] = {
        getattr(s, "name", ""): [] for s in sources
    }
    for cycle in range(1, current_cycle + 1):
        try:
            entries = ledger.build_cycle_ledger(vault_dir, cycle)
        except Exception as exc:  # pragma: no cover - defensive
            _LOG.warning("stagnant: build_cycle_ledger(%s) failed: %s", cycle, exc)
            continue
        for entry in entries:
            verdicts_by_source.setdefault(entry.name, []).append(
                str(getattr(entry.verdict, "value", entry.verdict))
            )

    try:
        spec = ledger.parse_spec(vault_dir / "research.spec.md")
    except Exception:  # pragma: no cover - defensive
        spec = None
    roles = (
        _roles_for_sources(spec, vault_dir, sources)
        if spec is not None
        else {getattr(s, "name", ""): getattr(s, "role", "") or "" for s in sources}
    )
    priorities = {
        getattr(s, "name", ""): int(getattr(s, "priority", 2) or 2) for s in sources
    }
    return stagnant_signals_from_verdicts(
        verdicts_by_source, roles, priorities, min_cold=min_cold
    )


def stagnant_warnings(vault_dir: Path, current_cycle: int) -> list[str]:
    """Convenience: the stagnant signals rendered as ``degraded_sources`` lines."""
    return [sig.message for sig in detect_stagnant_sources(vault_dir, current_cycle)]
