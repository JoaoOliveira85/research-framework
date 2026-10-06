"""Pre-dispatch cost estimation (spec 033).

Contracts: ``specs/033-cost-enforcement/contracts/cost-estimator.contract.md``.
Post-dispatch actuals come only from spec 028 sidecar v1.1 files.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path

import yaml

from research_framework._assets import _SOURCE_ROOT, asset_path
from research_framework.pipeline.settings import LimitsSettings

_LOG = logging.getLogger(__name__)

DEFAULT_ESTIMATOR_CALIBRATION: dict[str, float] = {
    "claude": 1.15,
    "codex": 1.0,
    # Spec 052: cursor-agent is flat-rate. The estimator dollar is a budget-
    # gating approximation (the real per-call figure never returns); ≈1.0 like
    # codex, and o200k_base is a fine token-count proxy for cursor's models.
    "cursor-agent": 1.0,
    # Spec 047 v1: local Ollama is $0; calibration is moot but kept for parity
    # so the estimator never KeyErrors on the agent name.
    "ollama": 1.0,
}
_FALLBACK_CEILING_USD = 2.0
_P95_MIN_SAMPLES = 3
_P95_LOOKBACK_CYCLES = 10

# Conservative output-token rates (USD per token) when tiktoken path is active.
_OUTPUT_RATE_CLAUDE = 15.0 / 1_000_000
_OUTPUT_RATE_CODEX = 10.0 / 1_000_000


@dataclass(frozen=True)
class DispatchEstimate:
    """Conservative pre-dispatch estimate (never underestimates)."""

    cost_usd: float
    codex_tokens: int
    estimation_method: str
    vendor: str


def _bundled_ceilings_path() -> Path:
    try:
        return asset_path("dist-templates/cost-estimates.yaml")
    except FileNotFoundError:
        return _SOURCE_ROOT / "dist-templates" / "cost-estimates.yaml"


def load_stage_ceilings(vault_dir: Path) -> dict[str, float]:
    """Merge bundled + vault ``cost-estimates.yaml`` ceilings."""
    ceilings: dict[str, float] = {}
    bundled = _bundled_ceilings_path()
    if bundled.is_file():
        raw = yaml.safe_load(bundled.read_text(encoding="utf-8")) or {}
        if isinstance(raw, dict):
            data = raw.get("ceilings") or {}
            if isinstance(data, dict):
                ceilings.update({str(k): float(v) for k, v in data.items()})
    vault_path = vault_dir / "cost-estimates.yaml"
    if vault_path.is_file():
        raw = yaml.safe_load(vault_path.read_text(encoding="utf-8")) or {}
        if isinstance(raw, dict):
            data = raw.get("ceilings") or {}
            if isinstance(data, dict):
                ceilings.update({str(k): float(v) for k, v in data.items()})
    return ceilings


def _default_ceiling(stage: str, ceilings: dict[str, float]) -> float:
    if stage in ceilings:
        return float(ceilings[stage])
    if "default" in ceilings:
        return float(ceilings["default"])
    return _FALLBACK_CEILING_USD


def _historical_sidecar_costs(
    vault_dir: Path, *, stage: str, agent: str, before_cycle: int
) -> list[float]:
    from research_framework.pipeline.budget_guard import list_sidecars_v11

    pipeline = vault_dir / "_pipeline" / "cycles"
    if not pipeline.is_dir():
        return []
    costs: list[float] = []
    cycle_dirs = sorted(
        (p for p in pipeline.glob("cycle-*") if p.is_dir()),
        key=lambda p: p.name,
        reverse=True,
    )
    for cycle_dir in cycle_dirs[:_P95_LOOKBACK_CYCLES]:
        try:
            cycle_num = int(cycle_dir.name.split("-", 1)[1])
        except (IndexError, ValueError):
            continue
        if cycle_num >= before_cycle:
            continue
        for row in list_sidecars_v11(vault_dir, cycle_num):
            if row.get("stage") == stage and row.get("agent") == agent:
                costs.append(float(row.get("cost_usd") or 0.0))
    return costs


def _historical_metered_tokens(
    vault_dir: Path, *, stage: str, agent: str, before_cycle: int
) -> list[int]:
    """Past per-call token totals for ``agent`` at ``stage`` (metered runtimes).

    Filters on the *requested* agent so each metered-token runtime (codex,
    cursor-agent — spec 052) projects from its OWN history. Passing
    ``agent="codex"`` reproduces the pre-052 codex-only behaviour exactly.
    """
    from research_framework.pipeline.budget_guard import list_sidecars_v11

    pipeline = vault_dir / "_pipeline" / "cycles"
    if not pipeline.is_dir():
        return []
    tokens: list[int] = []
    cycle_dirs = sorted(
        (p for p in pipeline.glob("cycle-*") if p.is_dir()),
        key=lambda p: p.name,
        reverse=True,
    )
    for cycle_dir in cycle_dirs[:_P95_LOOKBACK_CYCLES]:
        try:
            cycle_num = int(cycle_dir.name.split("-", 1)[1])
        except (IndexError, ValueError):
            continue
        if cycle_num >= before_cycle:
            continue
        for row in list_sidecars_v11(vault_dir, cycle_num):
            if row.get("stage") == stage and row.get("agent") == agent:
                tokens.append(
                    int(row.get("tokens_in") or 0) + int(row.get("tokens_out") or 0)
                )
    return tokens


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = max(0, math.ceil(0.95 * len(sorted_vals)) - 1)
    return float(sorted_vals[idx])


def _estimate_tiktoken(
    *,
    prompt_text: str,
    agent: str,
    max_tokens: int,
    limits: LimitsSettings,
    ceilings: dict[str, float],
    stage: str,
) -> DispatchEstimate | None:
    try:
        import tiktoken
    except ImportError:
        return None

    calibration = limits.estimator_calibration
    try:
        # codex + cursor-agent are both o200k_base-tokenised "metered token"
        # runtimes for estimation purposes (spec 052): a real token count feeds
        # the metered-token cap, and the dollar is a conservative approximation.
        if agent in ("codex", "cursor-agent"):
            enc = tiktoken.get_encoding("o200k_base")
            factor = float(calibration.get(agent, 1.0))
            tokens_in = len(enc.encode(prompt_text or ""))
            tokens_out_est = max_tokens
            codex_tokens = tokens_in + tokens_out_est
            cost = (
                tokens_in * _OUTPUT_RATE_CODEX + tokens_out_est * _OUTPUT_RATE_CODEX
            ) * factor
            return DispatchEstimate(
                cost_usd=max(cost, _default_ceiling(stage, ceilings)),
                codex_tokens=codex_tokens,
                estimation_method="tiktoken",
                vendor=agent,
            )
        if agent == "claude":
            enc = tiktoken.get_encoding("cl100k_base")
            factor = float(calibration.get("claude", 1.15))
            tokens_in = int(len(enc.encode(prompt_text or "")) * factor)
            tokens_out_est = max_tokens
            cost = (
                tokens_in * _OUTPUT_RATE_CLAUDE + tokens_out_est * _OUTPUT_RATE_CLAUDE
            )
            return DispatchEstimate(
                cost_usd=max(cost, _default_ceiling(stage, ceilings)),
                codex_tokens=0,
                estimation_method="tiktoken",
                vendor="claude",
            )
    except Exception as exc:
        _LOG.warning("tiktoken estimate failed for %s: %s", stage, exc)
        return None
    return None


def estimate_dispatch(
    *,
    vault_dir: Path,
    cycle_num: int,
    stage: str,
    prompt_text: str,
    agent: str,
    tier: str,
    max_tokens: int = 4096,
    limits: LimitsSettings,
) -> DispatchEstimate:
    """Return a conservative pre-dispatch estimate (spec 033 §2)."""
    ceilings = load_stage_ceilings(vault_dir)
    agent_norm = (agent or "claude").lower()
    if agent_norm in ("local", "fake") or agent_norm == "local":
        return DispatchEstimate(
            cost_usd=0.0,
            codex_tokens=0,
            estimation_method="default_ceiling",
            vendor="local",
        )

    tik = _estimate_tiktoken(
        prompt_text=prompt_text,
        agent=agent_norm,
        max_tokens=max_tokens,
        limits=limits,
        ceilings=ceilings,
        stage=stage,
    )
    if tik is not None:
        hist = _historical_sidecar_costs(
            vault_dir, stage=stage, agent=agent_norm, before_cycle=cycle_num
        )
        floor = _p95(hist) if len(hist) >= _P95_MIN_SAMPLES else 0.0
        cost = max(tik.cost_usd, floor, _default_ceiling(stage, ceilings))
        return DispatchEstimate(
            cost_usd=cost,
            codex_tokens=tik.codex_tokens,
            estimation_method="tiktoken",
            vendor=tik.vendor,
        )

    # Lazy import (mirrors the list_sidecars_v11 usage above) so this module
    # has no top-level dependency on budget_guard, which lazy-imports us back.
    from research_framework.pipeline.budget_guard import _METERED_TOKEN_AGENTS

    hist = _historical_sidecar_costs(
        vault_dir, stage=stage, agent=agent_norm, before_cycle=cycle_num
    )
    if len(hist) >= _P95_MIN_SAMPLES:
        cost = max(_p95(hist), _default_ceiling(stage, ceilings))
        token_hist = _historical_metered_tokens(
            vault_dir, stage=stage, agent=agent_norm, before_cycle=cycle_num
        )
        codex_est = _p95([float(t) for t in token_hist]) if token_hist else 0
        if agent_norm not in _METERED_TOKEN_AGENTS:
            codex_est = 0
        return DispatchEstimate(
            cost_usd=cost,
            codex_tokens=int(codex_est),
            estimation_method="p95_history",
            vendor=agent_norm,
        )

    ceiling = _default_ceiling(stage, ceilings)
    # Cold start (no cost history): project a conservative max_tokens so the
    # metered-token cap has a number for EVERY metered runtime (spec 052 —
    # previously cursor degraded to 0 without the optional tiktoken extra,
    # making its token cap a no-op).
    codex_est = max_tokens if agent_norm in _METERED_TOKEN_AGENTS else 0
    return DispatchEstimate(
        cost_usd=ceiling,
        codex_tokens=codex_est,
        estimation_method="default_ceiling",
        vendor=agent_norm,
    )
