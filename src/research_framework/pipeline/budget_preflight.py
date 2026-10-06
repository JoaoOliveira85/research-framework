"""Cost preflight for a whole cycle — the estimate the guard would use (#238).

With every shipped profile capping nothing until issue #230 seeded real
ceilings, the first signal an operator got about a run's cost was the bill.
The estimator that answers "what will this dispatch cost" has existed since
spec 033 — ``cost_estimator.estimate_dispatch`` is where the approval marker's
``estimated_cost_usd`` comes from — but it was only ever asked one dispatch at
a time, from inside a cycle that was already running and already spending.

This module asks it for a whole cycle, before anything is dispatched. Three
design commitments make the number trustworthy rather than decorative:

**It is the guard's own estimate, not a parallel one.** Same
``estimate_dispatch``, same ``cost-estimates.yaml`` ceilings, same p95 history
floor, and the agent/tier for each stage resolved through the same precedence
the dispatch hook uses (``budget_guard.resolve_dispatch_agent`` — moved there
from ``cycle_runner`` so both callers read one implementation). A preflight
that computed its own numbers would be a second opinion, and the useful
property here is that it is the *same* opinion, early.

**It counts dispatches, not stages.** ``note_writer`` runs once per batch and
``verifier`` once per note, so a "total" that assumed one dispatch per stage
would understate a cycle by an order of magnitude. Counts come from the
deterministic spec-051 yield model (``coverage.compute_yield_target``) and the
configured batch size — the same inputs the cycle itself will use.

**It never guesses low.** The yield target is 0 for a fully-covered vault
(CG-001 mandates nothing there), but such a vault can still write notes from
fuel, so the projection floors at ``cycle_yield.min_floor``. An estimator that
under-reports is worse than none: spec 033's contract is that estimates are
conservative, and a preflight inherits that.

What it cannot know is the prompt. Prompts are rendered by the cycle that has
not run yet, so the per-dispatch figure omits the prompt's own token cost —
the smallest term, and the one the stage ceiling floors anyway. The terms that
actually decide a pause (the ceiling, the p95 history floor) are identical.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from research_framework.pipeline.budget_guard import (
    resolve_dispatch_agent,
    resolve_max_tokens,
)
from research_framework.pipeline.settings import (
    SettingsError,
    VaultSettings,
    load_vault_settings,
)

#: The dispatch stages the in-process budget guard can actually see, in cycle
#: order. Exactly the stages ``cycle_runner``'s ``agent_call.py`` hook wraps
#: (``_STAGE_PHASE``'s keys): estimating a stage the guard never observes
#: would put money in this total that the guard would never stop.
_GUARDED_STAGES: tuple[str, ...] = ("scout", "note_writer", "verifier")

_DEFAULT_BATCH_SIZE = 6


@dataclass(frozen=True)
class StageEstimate:
    """One stage's projected spend for a cycle."""

    stage: str
    tier: str
    agent: str
    dispatches: int
    per_dispatch_usd: float
    estimation_method: str

    @property
    def subtotal_usd(self) -> float:
        return self.per_dispatch_usd * self.dispatches

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "tier": self.tier,
            "agent": self.agent,
            "dispatches": self.dispatches,
            "per_dispatch_usd": round(self.per_dispatch_usd, 4),
            "subtotal_usd": round(self.subtotal_usd, 4),
            "estimation_method": self.estimation_method,
        }


@dataclass(frozen=True)
class CycleEstimate:
    """The whole cycle's projection, plus the ceiling it will be judged against."""

    cycle_number: int
    stages: list[StageEstimate]
    projected_notes: int
    batch_size: int
    cycle_budget_usd: float | None

    @property
    def total_usd(self) -> float:
        return sum(row.subtotal_usd for row in self.stages)

    @property
    def exceeds_cycle_budget(self) -> bool:
        """True when the projection alone would trip ``limits.cycle_budget_usd``.

        Advisory, not a refusal: the guard pauses on ACTUALS, and a cycle that
        under-produces relative to the yield model will cost less than this.
        A projection over the cap means the cap is likely to pause the cycle
        part-way, which is a thing to know before leaving it alone overnight.
        """
        cap = self.cycle_budget_usd
        return cap is not None and cap > 0 and self.total_usd > cap

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "cycle_number": self.cycle_number,
            "projected_notes": self.projected_notes,
            "note_writer_batch_size": self.batch_size,
            "cycle_budget_usd": self.cycle_budget_usd,
            "total_usd": round(self.total_usd, 4),
            "exceeds_cycle_budget": self.exceeds_cycle_budget,
            "stages": [row.to_json_dict() for row in self.stages],
        }


def _batch_size(vault_settings: VaultSettings) -> int:
    raw = (vault_settings.extras.get("pipeline") or {}).get("note_writer_batch_size")
    if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
        return raw
    return _DEFAULT_BATCH_SIZE


def _projected_notes(vault_dir: Path, cycle_num: int, settings: VaultSettings) -> int:
    """How many notes to price this cycle for — never below the yield floor.

    ``compute_yield_target`` returns 0 for a vault with no unmet coverage,
    which is the right answer for CG-001 (nothing is *mandated*) and the wrong
    one for a cost projection (the cycle can still write notes from fuel).
    Flooring at the operator's own ``cycle_yield.min_floor`` keeps the estimate
    conservative without inventing a number that is not already in settings.
    """
    from research_framework.pipeline.coverage import compute_yield_target

    target = compute_yield_target(
        vault_dir, cycle_num, settings.max_cycles, settings.cycle_yield
    )
    return max(int(target.target), int(settings.cycle_yield.min_floor))


def _dispatch_count(stage: str, *, notes: int, batch_size: int) -> int:
    if stage == "scout":
        return 1
    if stage == "note_writer":
        return max(1, math.ceil(notes / max(1, batch_size)))
    return notes


def estimate_cycle(
    vault_dir: Path,
    *,
    cycle_num: int,
    vault_settings: VaultSettings | None = None,
) -> CycleEstimate:
    """Project one cycle's spend without dispatching anything."""
    from research_framework.pipeline.cost_estimator import estimate_dispatch

    if vault_settings is None:
        try:
            vault_settings = load_vault_settings(vault_dir)
        except SettingsError:
            vault_settings = VaultSettings(max_cycles=1, budget_usd=0.0)

    notes = _projected_notes(vault_dir, cycle_num, vault_settings)
    batch_size = _batch_size(vault_settings)

    rows: list[StageEstimate] = []
    for stage in _GUARDED_STAGES:
        stage_settings = vault_settings.stage(stage)
        if not stage_settings.enabled:
            continue
        agent = resolve_dispatch_agent(vault_settings, stage)
        est = estimate_dispatch(
            vault_dir=vault_dir,
            cycle_num=cycle_num,
            stage=stage,
            # The prompt does not exist yet; see the module docstring.
            prompt_text="",
            agent=agent,
            tier=stage_settings.tier,
            max_tokens=resolve_max_tokens(vault_settings, stage),
            limits=vault_settings.limits,
        )
        rows.append(
            StageEstimate(
                stage=stage,
                tier=stage_settings.tier,
                agent=agent,
                dispatches=_dispatch_count(stage, notes=notes, batch_size=batch_size),
                per_dispatch_usd=est.cost_usd,
                estimation_method=est.estimation_method,
            )
        )

    return CycleEstimate(
        cycle_number=cycle_num,
        stages=rows,
        projected_notes=notes,
        batch_size=batch_size,
        cycle_budget_usd=vault_settings.limits.cycle_budget_usd,
    )


def render_estimate_text(estimate: CycleEstimate) -> str:
    """Human-readable preflight report (stdout — this is the verb's output)."""
    lines = [
        f"Cost preflight — cycle {estimate.cycle_number} (nothing dispatched)",
        "",
        f"  projected notes this cycle: {estimate.projected_notes} "
        f"(note_writer batch size {estimate.batch_size})",
        "",
        f"  {'stage':<14} {'agent':<12} {'tier':<10} {'calls':>5} "
        f"{'$/call':>10} {'subtotal':>10}",
    ]
    for row in estimate.stages:
        lines.append(
            f"  {row.stage:<14} {row.agent:<12} {row.tier:<10} "
            f"{row.dispatches:>5} {row.per_dispatch_usd:>10.4f} "
            f"{row.subtotal_usd:>10.4f}"
        )
    lines.extend(
        [
            f"  {'TOTAL':<14} {'':<12} {'':<10} {'':>5} {'':>10} "
            f"{estimate.total_usd:>10.4f}",
            "",
        ]
    )
    cap = estimate.cycle_budget_usd
    if cap is None:
        lines.append(
            "  limits.cycle_budget_usd: NOT SET — this run has no ceiling. "
            "Nothing would pause it, whatever it costs."
        )
    else:
        lines.append(f"  limits.cycle_budget_usd: ${cap:.4f}")
        if estimate.exceeds_cycle_budget:
            lines.append(
                "  WARNING: the projection exceeds the per-cycle cap, so the "
                "guard is likely to pause this cycle part-way through."
            )
    lines.append(
        "  Estimates omit the prompt's own tokens (not rendered yet); the "
        "stage ceilings and history floors are the guard's."
    )
    return "\n".join(lines)
