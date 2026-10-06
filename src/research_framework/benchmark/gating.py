"""Cost-safety gating for the live sweep (spec 056, contract §3; reuses spec-033
semantics with benchmark-local flags).

No live LLM call happens before an explicit acknowledgement:
  - ``--yes`` flag                         → proceed (mode ``yes``)
  - ``RF_BENCHMARK_ACK=1`` env             → proceed (mode ``env``)
  - interactive TTY (stdin & stdout)       → y/N prompt (mode ``tty``)
  - headless without flag/env              → refuse (mode ``headless``)

``--max-usd`` is an inclusive cap (equality allowed, strict exceed stops) matching
spec-033; the sweep stops mid-matrix and still writes a partial report (FR-007).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# Conservative per-cell dollar ceiling used for the pre-run estimate when no
# richer per-executor ceiling is supplied (spec-033 FR-003 fallback spirit).
DEFAULT_CELL_CEILING_USD = 0.10


@dataclass(frozen=True)
class AckDecision:
    proceed: bool
    mode: str  # "yes" | "env" | "tty" | "headless"


def resolve_ack(
    *,
    yes: bool,
    env_ack: str | None,
    stdin_isatty: bool,
    stdout_isatty: bool,
    prompt_fn: Callable[[str], str] = input,
) -> AckDecision:
    """Decide whether the live sweep may proceed, and record how it was acked.

    Order: explicit ``--yes`` > ``RF_BENCHMARK_ACK=1`` > interactive prompt >
    headless refusal (SC-003: no dispatch without acknowledgement).
    """
    if yes:
        return AckDecision(True, "yes")
    if (env_ack or "").strip() == "1":
        return AckDecision(True, "env")
    if stdin_isatty and stdout_isatty:
        answer = prompt_fn("Proceed with live benchmark sweep? [y/N] ").strip().lower()
        return AckDecision(answer in ("y", "yes"), "tty")
    return AckDecision(False, "headless")


class CostCap:
    """Inclusive ``--max-usd`` cap (spec-033 semantics: ``> max`` stops)."""

    def __init__(self, max_usd: float | None) -> None:
        self.max_usd = max_usd

    def exceeded(self, accumulated_usd: float) -> bool:
        if self.max_usd is None:
            return False
        return accumulated_usd > self.max_usd


def cost_fields(sidecar: dict[str, Any] | None) -> tuple[float | None, str]:
    """Map a 028 sidecar (or its absence) to ``(cost_usd, cost_source)`` (FR-013).

    The report's provenance vocabulary is ``{"sidecar", "estimated", "n/a"}``;
    the sidecar's own ``cost_source`` is ``{runtime, runtime_tokens, estimated,
    none}`` (spec 028 rc3 / 033 / 047 / 052). The mapping:

    - ``cost_source == "none"`` — agent_call had NO cost signal AND the estimator
      failed, so it wrote a sentinel ``cost_usd: 0``. That is *not* a real $0 ⇒
      ``(None, "n/a")``. Reporting it as $0 would silently undercount the tally
      (FR-013): never imply zero spend from an absent signal.
    - ``cost_source == "estimated"`` — spec-033 fallback dollar ⇒
      ``(cost, "estimated")`` so the report flags it as non-measured.
    - ``runtime`` / ``runtime_tokens`` (measured; includes ollama's TRUE local
      $0) ⇒ ``(cost, "sidecar")``.
    - missing/null ``cost_usd`` or a non-dict sidecar ⇒ ``(None, "n/a")``.
    """
    if not isinstance(sidecar, dict):
        return None, "n/a"
    raw_source = str(sidecar.get("cost_source") or "")
    cost = sidecar.get("cost_usd")
    if raw_source == "none" or cost is None:
        return None, "n/a"
    try:
        cost_usd = float(cost)
    except (TypeError, ValueError):
        return None, "n/a"
    if raw_source == "estimated":
        return cost_usd, "estimated"
    return cost_usd, "sidecar"


def estimate_matrix_cost(
    cells: list[Any], *, cell_ceiling_usd: float = DEFAULT_CELL_CEILING_USD
) -> float:
    """Best-effort pre-run dollar estimate = ``cells × per-cell ceiling`` (§3).

    Coarse on purpose — it backs the y/N gate and the ``--max-usd`` sanity check,
    not billing. The report records the actual measured sum separately.
    """
    return round(len(cells) * float(cell_ceiling_usd), 4)
