"""Single source of truth for cycle-budget precedence resolution (spec 061).

Before 061 the per-cycle budget was expressible in ≥4 places with silent
precedence (the codebase-vault rc1 run asked for 12 cycles and ran 6 because
``cycles.initial_max: 6`` silently won over the spec). This module collapses
the budget onto ONE ladder, consumed identically by ``generate`` / ``resume`` /
``phase3`` (research.md D3):

    --max-cycles flag  >  settings pipeline.max_cycles  >  built-in default

The deprecated ``cycles:`` block (``initial_max`` / ``update_max``) is
warn-and-honoured for a grace period: migrated into the canonical slot ONLY
when ``pipeline.max_cycles`` is absent, and it ALWAYS emits one loud
``logging.WARNING`` naming the canonical key (never silently honoured — that was
the original bug). ``max_usd`` (the dollar cap, reclassified off the spec per
clarify Q3) resolves on the same ladder against ``pipeline.budget_usd``, where
**a zero budget means UNLIMITED** — the same as ``None`` or an absent key
(owner's decision 2026-09-07; spec 061 amendment). See :func:`_resolve_usd`.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..pipeline.settings import DEFAULT_MAX_CYCLES

_LOG = logging.getLogger(__name__)

#: FR5 — re-exported from ``pipeline.settings`` (the single source of truth, also
#: consulted by the cycle-time yield readers). The shipped seed carries this
#: value, so resolution is a no-op when the seed is present; it only backstops a
#: settings file that dropped the key. Kept generous so a cold-start bootstrap is
#: never silently truncated (the rc1 pain).
__all__ = [
    "DEFAULT_MAX_CYCLES",
    "BudgetError",
    "BudgetResolution",
    "fill_missing_run_budget",
    "resolve_cycle_budget",
    "resolve_cycle_budget_from_path",
]

_CANONICAL_KEY = "pipeline.max_cycles"
_CANONICAL_USD_KEY = "pipeline.budget_usd"
_DEPRECATED_CYCLE_KEYS = ("initial_max", "update_max")


class BudgetError(ValueError):
    """Raised when a budget value is invalid (e.g. ``max_cycles <= 0``).

    Callers (the CLI entry points) catch this and map it to exit code 2 with a
    clear message — it is a usage error, not an internal failure.
    """


@dataclass(frozen=True)
class BudgetResolution:
    """The effective budget plus where each value came from (FR4 provenance).

    **``max_cycles`` and ``max_usd`` are LIFETIME ceilings, not per-run
    budgets** (issue #239). ``max_cycles`` is an absolute cycle NUMBER —
    ``run_cycles`` iterates ``range(start_cycle, max_cycles + 1)``, so on a
    vault whose seventh cycle is next, ``--max-cycles 5`` runs nothing.
    ``max_usd`` is compared against ``_cumulative_sidecar_cost(up_to=cycle)``,
    which sums every cycle the vault has ever run. Both flags' help text used
    to say "per-run", which is the other semantics entirely: "give it $10" was
    unachievable on any vault that had already spent more, and spec 070's open
    questions 4/4a filed exactly that.

    ``--more-cycles`` and ``max_usd_this_run`` are the per-run readings, given
    their own names rather than taken from the existing flags. They are
    additive by design: nothing that already worked changes meaning.

    ``--more-cycles`` deliberately leaves NO field of its own here: it is an
    input to the ceiling, not a second copy of it. The resolver folds it into
    ``max_cycles`` (with ``max_cycles_source == "flag"``), which is the value
    every consumer already reads. A ``more_cycles`` field would be a number
    nobody consulted — the shape issue #235 called "a parameter no caller
    passes is the defect itself".
    """

    max_cycles: int
    max_cycles_source: str  # "flag" | "settings" | "default"
    max_usd: float | None
    max_usd_source: str  # "flag" | "settings" | "default"
    deprecated_keys_seen: list[str] = field(default_factory=list)
    #: ``--max-usd-this-run N``: a ceiling on what THIS run adds, measured
    #: from the vault's lifetime spend at the moment the run starts. ``None``
    #: means no per-run ceiling; zero resolves to ``None`` for the same reason
    #: every other zero on this ladder does (FR3-Z2).
    max_usd_this_run: float | None = None


def _positive_int(value: Any) -> int | None:
    """Return ``value`` iff it is a positive (non-bool) int, else ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None


def _section(settings_data: dict[str, Any], key: str) -> dict[str, Any]:
    section = settings_data.get(key)
    return section if isinstance(section, dict) else {}


def resolve_cycle_budget(
    settings_data: dict[str, Any] | None,
    *,
    flag_max_cycles: int | None = None,
    flag_max_usd: float | None = None,
    flag_more_cycles: int | None = None,
    flag_max_usd_this_run: float | None = None,
    start_cycle: int = 1,
    usd_flag_name: str = "--max-usd",
) -> BudgetResolution:
    """Resolve the cycle ceiling + dollar caps from the precedence ladder.

    ``settings_data`` is the raw parsed ``settings.yaml`` mapping (not the typed
    :class:`VaultSettings`, which *requires* ``pipeline.max_cycles`` and so cannot
    represent the "canonical absent" rung). ``None``/empty is treated as no
    settings, exercising the built-in default.

    ``flag_more_cycles`` is the per-run spelling of the cycle ceiling (issue
    #239): ``--more-cycles 3`` from ``start_cycle`` 7 resolves to a ceiling of
    9. It sits on the same top rung as ``--max-cycles`` and the two are
    mutually exclusive, because a ladder whose top rung holds two conflicting
    answers is the bug spec 061 exists to remove.
    """
    data = settings_data or {}
    pipeline = _section(data, "pipeline")
    cycles = _section(data, "cycles")

    deprecated_seen: list[str] = [
        f"cycles.{k}"
        for k in _DEPRECATED_CYCLE_KEYS
        if _positive_int(cycles.get(k)) is not None
    ]

    canonical_present = "max_cycles" in pipeline
    canonical_int = _positive_int(pipeline.get("max_cycles"))

    if flag_more_cycles is not None and flag_max_cycles is not None:
        raise BudgetError(
            "--more-cycles and --max-cycles both set the cycle ceiling and "
            "mean different things (N MORE cycles from here, versus an "
            "absolute cycle-number ceiling). Pass one."
        )

    if flag_more_cycles is not None:
        if _positive_int(flag_more_cycles) is None:
            raise BudgetError(
                f"--more-cycles must be a positive integer (got {flag_more_cycles!r})"
            )
        anchor = start_cycle if start_cycle >= 1 else 1
        max_cycles, mc_source = anchor + int(flag_more_cycles) - 1, "flag"
    elif flag_max_cycles is not None:
        if _positive_int(flag_max_cycles) is None:
            raise BudgetError(
                f"--max-cycles must be a positive integer (got {flag_max_cycles!r})"
            )
        max_cycles, mc_source = flag_max_cycles, "flag"
    elif canonical_present:
        if canonical_int is None:
            raise BudgetError(
                f"{_CANONICAL_KEY} must be an integer >= 1 "
                f"(got {pipeline.get('max_cycles')!r})"
            )
        max_cycles, mc_source = canonical_int, "settings"
    elif deprecated_seen:
        migrated = _positive_int(cycles.get("initial_max")) or _positive_int(
            cycles.get("update_max")
        )
        # deprecated_seen is non-empty ⇒ at least one positive value exists.
        max_cycles, mc_source = int(migrated), "settings"
    else:
        max_cycles, mc_source = DEFAULT_MAX_CYCLES, "default"

    if deprecated_seen:
        joined = ", ".join(deprecated_seen)
        if canonical_present:
            _LOG.warning(
                "settings: deprecated %s present but ignored — %s=%d wins. "
                "Remove the `cycles:` block; use %s.",
                joined,
                _CANONICAL_KEY,
                max_cycles,
                _CANONICAL_KEY,
            )
        else:
            _LOG.warning(
                "settings: %s is deprecated — honouring it as %s=%d for now. "
                "Move this to %s before it is removed.",
                joined,
                _CANONICAL_KEY,
                max_cycles,
                _CANONICAL_KEY,
            )

    max_usd, usd_source = _resolve_usd(
        pipeline.get("budget_usd"), flag_max_usd, usd_flag_name
    )
    max_usd_this_run = _resolve_run_usd(flag_max_usd_this_run)

    return BudgetResolution(
        max_cycles=max_cycles,
        max_cycles_source=mc_source,
        max_usd=max_usd,
        max_usd_source=usd_source,
        deprecated_keys_seen=deprecated_seen,
        max_usd_this_run=max_usd_this_run,
    )


def resolve_cycle_budget_from_path(
    settings_path: Path | None,
    *,
    flag_max_cycles: int | None = None,
    flag_max_usd: float | None = None,
    flag_more_cycles: int | None = None,
    flag_max_usd_this_run: float | None = None,
    start_cycle: int = 1,
    usd_flag_name: str = "--max-usd",
) -> BudgetResolution:
    """Read the raw ``settings.yaml`` mapping from disk and resolve the budget.

    The file-level entry point the CLI uses: it reads the raw mapping (so an
    absent ``pipeline.max_cycles`` is observable, unlike the typed
    :class:`VaultSettings`) and delegates to :func:`resolve_cycle_budget`. A
    missing/unreadable file is treated as empty settings → built-in default.
    """
    from .._assets import _legacy_settings_dict

    data: dict[str, Any] | None = None
    if settings_path is not None and settings_path.is_file():
        data = _legacy_settings_dict(settings_path)
    return resolve_cycle_budget(
        data,
        flag_max_cycles=flag_max_cycles,
        flag_max_usd=flag_max_usd,
        flag_more_cycles=flag_more_cycles,
        flag_max_usd_this_run=flag_max_usd_this_run,
        start_cycle=start_cycle,
        usd_flag_name=usd_flag_name,
    )


def fill_missing_run_budget(
    vault_dir: Path,
    budget_cap: float | None,
    max_cycles: int | None,
) -> tuple[float, int]:
    """Backfill omitted ``(budget_cap, max_cycles)`` from the ladder (issue #233).

    The two in-process cycle entry points (``orchestrator.run_single_cycle``,
    ``cycle_runner.run_cycle_steps``) carried hardcoded ``10.0`` / ``5``
    defaults — a budget nobody configured, from a rung the ladder does not
    have, applied to any caller that omitted the argument. ``None`` now means
    "resolve it", and this is the single place that does, so the answer is the
    same one ``generate`` / ``--resume`` / ``cycle`` get.

    Returns the orchestrator's wire form: ``budget_cap`` is ``0.0`` for
    uncapped (the ``cumulative >= budget_cap > 0`` guard reads zero as "off"),
    matching what ``run_cycles`` already does with ``max_usd is None``.
    """
    if budget_cap is not None and max_cycles is not None:
        return float(budget_cap), int(max_cycles)
    resolution = resolve_cycle_budget_from_path(vault_dir / "settings.yaml")
    if budget_cap is None:
        budget_cap = resolution.max_usd if resolution.max_usd is not None else 0.0
    if max_cycles is None:
        max_cycles = resolution.max_cycles
    return float(budget_cap), int(max_cycles)


def _resolve_usd(
    settings_usd: Any, flag_max_usd: float | None, usd_flag_name: str = "--max-usd"
) -> tuple[float | None, str]:
    """Resolve the dollar cap on the same ladder; ``None`` means uncapped.

    **Zero means UNLIMITED** (owner's decision, 2026-09-07 — see the amendment
    at the foot of this spec's ``spec.md``). A ``0`` is never a zero-dollar cap
    and never "ask before every spend": it resolves to ``None``, exactly like
    an absent key.

    This is a contract change, and a deliberate one. The resolver used to
    return a literal ``0.0`` and leave the meaning to whoever read it next —
    ``orchestrator.run_cycles`` happened to guard on
    ``cumulative >= budget_cap > 0`` and so read it as uncapped, but nothing
    said so, and a second reader was free to read the same value as "spend
    nothing". Every shipped profile carried ``budget_usd: 0.0`` for months
    (issue #230) and every vault built from one ran, so "uncapped" is the
    meaning the corpus already carries; this puts it where the value is
    decided instead of three layers downstream.

    Zero on the FLAG rung means the same thing. One ladder with two meanings
    of zero would be a silent disagreement between its own rungs — the class
    of bug spec 061 exists to remove. The provenance (``"flag"`` /
    ``"settings"``) is preserved either way: the operator did configure this,
    explicitly, and FR4 owes the run report that fact.

    A NEGATIVE settings value is still ignored (nonsense, so the ladder falls
    through to the default rung); a negative flag is still a usage error.
    """
    if flag_max_usd is not None:
        # NaN slips past `< 0` and `== 0`, and `spent >= nan` is never True.
        if (
            isinstance(flag_max_usd, bool)
            or not math.isfinite(flag_max_usd)
            or flag_max_usd < 0
        ):
            raise BudgetError(
                f"{usd_flag_name} must be a finite number >= 0 (got {flag_max_usd!r})"
            )
        return _cap_or_unlimited(flag_max_usd), "flag"
    if (
        isinstance(settings_usd, (int, float))
        and not isinstance(settings_usd, bool)
        and settings_usd >= 0
    ):
        return _cap_or_unlimited(settings_usd), "settings"
    return None, "default"


def _resolve_run_usd(flag_max_usd_this_run: float | None) -> float | None:
    """Resolve ``--max-usd-this-run`` — the per-run dollar ceiling (issue #239).

    Flag-only, deliberately. A per-run ceiling answers "how much more am I
    willing to spend in THIS invocation", which is a launch-time decision; a
    settings key would outlive the decision and quietly re-apply to every
    later run, which is how ``cycles.initial_max`` earned spec 061 in the
    first place.

    Zero means unlimited here for the same reason it does on every other rung
    of this ladder (FR3-Z2): one ladder cannot hold two meanings of zero.
    """
    if flag_max_usd_this_run is None:
        return None
    if (
        isinstance(flag_max_usd_this_run, bool)
        or not math.isfinite(flag_max_usd_this_run)
        or flag_max_usd_this_run < 0
    ):
        raise BudgetError(
            f"--max-usd-this-run must be a finite number >= 0 "
            f"(got {flag_max_usd_this_run!r})"
        )
    return _cap_or_unlimited(flag_max_usd_this_run)


def _cap_or_unlimited(value: float) -> float | None:
    """``0`` (any spelling) ⇒ uncapped; anything positive is the cap itself."""
    cap = float(value)
    return None if cap == 0.0 else cap
