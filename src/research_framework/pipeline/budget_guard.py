"""Cycle budget enforcement and pause markers (spec 033).

Contracts:
  - ``specs/033-cost-enforcement/contracts/budget-marker.contract.md``
  - ``specs/033-cost-enforcement/contracts/approval-marker.contract.md``
Sidecar reads: ``specs/028-dispatch-telemetry/contracts/sidecar-v1.contract.md``.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

from research_framework.pipeline import atomic_write
from research_framework.pipeline.settings import LimitsSettings, VaultSettings

_LOG = logging.getLogger(__name__)

BUDGET_PAUSED_REL = "_pipeline/BUDGET_PAUSED"
APPROVAL_REQUIRED_REL = "_pipeline/APPROVAL_REQUIRED"
APPROVAL_DECISIONS_REL = "_pipeline/approval-decisions.json"
_MARKER_SCHEMA_VERSION = "1.0"
_DECISION_LOG_SCHEMA_VERSION = "1.0"
#: approval-marker.contract.md §6 `decided_by_mode` — a closed set.
_DECISION_MODES = frozenset({"tty", "headless"})
_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"ANTHROPIC_API_KEY\s*=\s*\S+"),
    re.compile(r"OPENAI_API_KEY\s*=\s*\S+"),
)

_BUDGET_MARKER_SCHEMA: dict[str, Any] = {
    "required": [
        "schema_version",
        "pause_reason",
        "cycle_number",
        "paused_at",
        "paused_stage",
        "cumulative_spend_usd",
        "cycle_budget_usd",
        "dispatch_estimate_usd",
    ],
    "pause_reason_enum": {
        "dollar_cap_exceeded",
        "wallclock_exceeded",
        "codex_token_cap_exceeded",
    },
}

_APPROVAL_MARKER_SCHEMA_MAX_PREVIEW = 500

# Spec 052: runtimes whose real token usage is metered and capped. Codex has a
# hard external token cap; cursor-agent (flat-rate) shares the same
# ``codex_token_budget`` guardrail so an unattended cursor run can't run away.
# claude is dollar-metered only (never tallied here). The marker/setting names
# keep the historical ``codex_`` prefix for back-compat; semantically they are
# the *metered-token* tally + cap.
_METERED_TOKEN_AGENTS = frozenset({"codex", "cursor-agent"})


@dataclass
class CycleSpendTally:
    """In-memory per-cycle spend state (data-model.md)."""

    cycle_num: int = 1
    actual_usd: float = 0.0
    actual_codex_tokens: int = 0
    cycle_started_mono: float = field(default_factory=time.monotonic)
    warn_emitted: bool = False
    last_estimation_method: str = ""
    estimation_methods_used: list[dict[str, str]] = field(default_factory=list)


@dataclass
class BudgetPausedMarker:
    """Persisted ``BUDGET_PAUSED`` payload."""

    pause_reason: str
    cycle_number: int
    paused_stage: str
    cumulative_spend_usd: float
    cycle_budget_usd: float
    dispatch_estimate_usd: float
    codex_tokens_cumulative: int | None = None
    codex_token_budget: int | None = None
    wallclock_elapsed_seconds: float | None = None
    wallclock_cap_seconds: float | None = None
    blocked_dispatch_preview: str | None = None
    schema_version: str = _MARKER_SCHEMA_VERSION
    paused_at: str = field(
        default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    )

    def to_json_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema_version": self.schema_version,
            "pause_reason": self.pause_reason,
            "cycle_number": self.cycle_number,
            "paused_at": self.paused_at,
            "paused_stage": self.paused_stage,
            "cumulative_spend_usd": round(self.cumulative_spend_usd, 4),
            "cycle_budget_usd": round(self.cycle_budget_usd, 4),
            "dispatch_estimate_usd": round(self.dispatch_estimate_usd, 4),
        }
        if self.codex_tokens_cumulative is not None:
            out["codex_tokens_cumulative"] = self.codex_tokens_cumulative
        if self.codex_token_budget is not None:
            out["codex_token_budget"] = self.codex_token_budget
        if self.wallclock_elapsed_seconds is not None:
            out["wallclock_elapsed_seconds"] = self.wallclock_elapsed_seconds
        if self.wallclock_cap_seconds is not None:
            out["wallclock_cap_seconds"] = self.wallclock_cap_seconds
        if self.blocked_dispatch_preview:
            out["blocked_dispatch_preview"] = redact_preview(
                self.blocked_dispatch_preview, max_len=200
            )
        return out

    @classmethod
    def from_path(cls, path: Path) -> BudgetPausedMarker:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            schema_version=str(data.get("schema_version", _MARKER_SCHEMA_VERSION)),
            pause_reason=str(data["pause_reason"]),
            cycle_number=int(data["cycle_number"]),
            paused_at=str(data["paused_at"]),
            paused_stage=str(data["paused_stage"]),
            cumulative_spend_usd=float(data["cumulative_spend_usd"]),
            cycle_budget_usd=float(data["cycle_budget_usd"]),
            dispatch_estimate_usd=float(data["dispatch_estimate_usd"]),
            codex_tokens_cumulative=data.get("codex_tokens_cumulative"),
            codex_token_budget=data.get("codex_token_budget"),
            wallclock_elapsed_seconds=data.get("wallclock_elapsed_seconds"),
            wallclock_cap_seconds=data.get("wallclock_cap_seconds"),
            blocked_dispatch_preview=data.get("blocked_dispatch_preview"),
        )


@dataclass
class ApprovalRequiredMarker:
    """Persisted ``APPROVAL_REQUIRED`` payload."""

    stage_name: str
    cycle_number: int
    prompt_preview: str
    estimated_cost_usd: float
    cumulative_spend_usd: float
    tier: str
    agent: str | None = None
    schema_version: str = _MARKER_SCHEMA_VERSION
    paused_at: str = field(
        default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "stage_name": self.stage_name,
            "cycle_number": self.cycle_number,
            "paused_at": self.paused_at,
            "prompt_preview": redact_preview(
                self.prompt_preview, max_len=_APPROVAL_MARKER_SCHEMA_MAX_PREVIEW
            ),
            "estimated_cost_usd": round(self.estimated_cost_usd, 4),
            "cumulative_spend_usd": round(self.cumulative_spend_usd, 4),
            "tier": self.tier,
            **({"agent": self.agent} if self.agent else {}),
        }

    @classmethod
    def from_path(cls, path: Path) -> ApprovalRequiredMarker:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            schema_version=str(data.get("schema_version", _MARKER_SCHEMA_VERSION)),
            stage_name=str(data["stage_name"]),
            cycle_number=int(data["cycle_number"]),
            paused_at=str(data["paused_at"]),
            prompt_preview=str(data["prompt_preview"]),
            estimated_cost_usd=float(data["estimated_cost_usd"]),
            cumulative_spend_usd=float(data["cumulative_spend_usd"]),
            tier=str(data["tier"]),
            agent=data.get("agent"),
        )


@dataclass(frozen=True)
class ApprovalDecision:
    """One operator verdict on an approval gate (approval-marker.contract.md §6).

    The decision is taken in the CLI process, at resume time; the cycle cost
    report that must show it is written much later, deep inside
    ``cycle_runner``, from a budget session that never sees the CLI's
    arguments. Persisting the verdict is what joins the two — see
    :func:`record_approval_decision`.
    """

    stage_name: str
    cycle_number: int
    approved: bool
    decided_by_mode: str
    decided_at: str = field(
        default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage_name,
            "cycle_number": self.cycle_number,
            "approved": bool(self.approved),
            "decided_at": self.decided_at,
            "decided_by_mode": self.decided_by_mode,
        }


def approval_decisions_path(vault_dir: Path) -> Path:
    return vault_dir / APPROVAL_DECISIONS_REL


def validate_approval_decision_log(doc: dict[str, Any]) -> None:
    """Validate the decision log envelope; raise ``ValueError`` if unusable.

    Same fail-closed rule as the two markers: a ``schema_version`` this build
    does not know may be carrying fields it cannot read, so it is refused
    rather than coerced.
    """
    version = doc.get("schema_version")
    if version != _DECISION_LOG_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported schema_version {version!r} "
            f"(this build reads {_DECISION_LOG_SCHEMA_VERSION!r})"
        )
    if not isinstance(doc.get("decisions"), list):
        raise ValueError("decisions must be a list")


def _load_approval_decision_log(vault_dir: Path) -> dict[str, Any]:
    """Return the parsed log, or a fresh empty one when the file is absent.

    Raises ``ValueError`` for a file that exists but this build must not act
    on — the caller turns that into "leave it alone and say so".
    """
    path = approval_decisions_path(vault_dir)
    if not path.is_file():
        return {"schema_version": _DECISION_LOG_SCHEMA_VERSION, "decisions": []}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"approval decision log is unreadable: {exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError("approval decision log is not a JSON object")
    validate_approval_decision_log(doc)
    return doc


def record_approval_decision(vault_dir: Path, decision: ApprovalDecision) -> bool:
    """Append one verdict to ``_pipeline/approval-decisions.json``.

    Returns ``True`` when the row was written. A log this build cannot read is
    NEVER truncated to make room: it is the operator's record of every earlier
    verdict, and destroying it to add one row would trade an audit trail for a
    telemetry line. The caller WARNs and carries on — a report that cannot say
    what was approved is a smaller harm than a resume that refuses to run.
    """
    if decision.decided_by_mode not in _DECISION_MODES:
        raise ValueError(
            f"decided_by_mode must be one of {sorted(_DECISION_MODES)}, "
            f"got {decision.decided_by_mode!r}"
        )
    try:
        doc = _load_approval_decision_log(vault_dir)
    except ValueError as exc:
        _LOG.warning(
            "not recording approval decision for stage %r: %s "
            "(delete %s to start a new log)",
            decision.stage_name,
            exc,
            approval_decisions_path(vault_dir),
        )
        return False
    doc["decisions"].append(decision.to_json_dict())
    atomic_write_json_marker(approval_decisions_path(vault_dir), doc)
    return True


def read_approval_decisions(vault_dir: Path, cycle_num: int) -> list[dict[str, Any]]:
    """This cycle's verdicts in approval-marker.contract.md §6 row shape.

    ``cycle_number`` is the log's addressing, not part of the §6 row: the cycle
    report it feeds is already per-cycle.
    """
    try:
        doc = _load_approval_decision_log(vault_dir)
    except ValueError as exc:
        _LOG.warning(
            "approval_gates_fired unavailable for cycle %d: %s", cycle_num, exc
        )
        return []
    rows: list[dict[str, Any]] = []
    for row in doc["decisions"]:
        if not isinstance(row, dict) or row.get("cycle_number") != cycle_num:
            continue
        rows.append(
            {
                "stage": row.get("stage"),
                "approved": bool(row.get("approved")),
                "decided_at": row.get("decided_at"),
                "decided_by_mode": row.get("decided_by_mode"),
            }
        )
    return rows


def redact_preview(text: str, *, max_len: int) -> str:
    """Truncate and redact secret-like substrings from preview fields."""
    out = text or ""
    for pat in _SECRET_PATTERNS:
        out = pat.sub("[REDACTED]", out)
    if len(out) > max_len:
        return out[:max_len]
    return out


def validate_budget_paused_marker(doc: dict[str, Any]) -> None:
    """Validate marker JSON against budget-marker.contract.md §2.4 rules.

    ``schema_version`` is checked against the contract's ``const: "1.0"``, not
    merely for presence. The read protocol (§4.2) says "parse JSON; validate
    ``schema_version``", and a budget guard is the wrong place to be liberal:
    a marker whose shape this build does not understand may be carrying a cap
    whose fields this build cannot read, so the only safe answer is to refuse
    and say so. Bumping the marker schema means bumping this constant and the
    contract together.
    """
    for key in _BUDGET_MARKER_SCHEMA["required"]:
        if key not in doc:
            raise ValueError(f"missing required field {key!r}")
    version = doc.get("schema_version")
    if version != _MARKER_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported schema_version {version!r} "
            f"(this build reads {_MARKER_SCHEMA_VERSION!r})"
        )
    reason = doc.get("pause_reason")
    if reason not in _BUDGET_MARKER_SCHEMA["pause_reason_enum"]:
        raise ValueError(f"invalid pause_reason {reason!r}")
    if reason == "approval_required":
        raise ValueError("approval_required is forbidden on budget marker")
    if reason == "dollar_cap_exceeded":
        cap = float(doc.get("cycle_budget_usd", 0))
        if cap <= 0:
            raise ValueError("cycle_budget_usd must be > 0 for dollar_cap_exceeded")
    if reason == "wallclock_exceeded":
        if doc.get("wallclock_elapsed_seconds") is None:
            raise ValueError("wallclock_elapsed_seconds required")
        if doc.get("wallclock_cap_seconds") is None:
            raise ValueError("wallclock_cap_seconds required")
    if reason == "codex_token_cap_exceeded":
        if doc.get("codex_tokens_cumulative") is None:
            raise ValueError("codex_tokens_cumulative required")
        if doc.get("codex_token_budget") is None:
            raise ValueError("codex_token_budget required")


def validate_approval_required_marker(doc: dict[str, Any]) -> None:
    """Validate approval marker (§3.3 preview max 500 chars)."""
    preview = doc.get("prompt_preview", "")
    if (
        not isinstance(preview, str)
        or len(preview) > _APPROVAL_MARKER_SCHEMA_MAX_PREVIEW
    ):
        raise ValueError("prompt_preview exceeds 500 characters")


def _is_talliable_sidecar_version(version: object) -> bool:
    """True for additive v1.x sidecars from 1.1 onward (1.0 is legacy-excluded).

    Guards the budget tally against the 1.1→1.2 footgun: the writer emits 1.2
    (spec 028 rc3 added the ``cost_source`` discriminator), so a hard
    ``== "1.1"`` check silently DROPPED every modern sidecar — leaving
    ``actual_usd`` stuck at 0 and any new cost runtime (cursor, ollama)
    invisible to the dollar cap. 1.1+ is additive by contract (readers use
    ``.get()``), so the whole line is talliable; any future bump (1.3, …) is
    accepted automatically. Only pre-1.1 schemas (1.0 — missing the required
    agent_kind/status/cycle fields) are ignored.
    """
    parts = str(version).split(".")
    if len(parts) != 2 or parts[0] != "1":
        return False
    try:
        return int(parts[1]) >= 1
    except ValueError:
        return False


def list_sidecars_v11(vault_dir: Path, cycle_num: int) -> list[dict[str, Any]]:
    """Glob v1.1+ sidecars; ignore legacy flat ``cycle-*-*.cost.json`` paths and
    pre-1.1 (1.0) schemas."""
    agent_calls = (
        vault_dir / "_pipeline" / "cycles" / f"cycle-{cycle_num:03d}" / "agent-calls"
    )
    if not agent_calls.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(agent_calls.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        if not _is_talliable_sidecar_version(data.get("schema_version")):
            continue
        rows.append(data)
    return rows


def _metered_tokens(row: dict[str, Any]) -> int:
    """Tokens this sidecar contributes to the metered-token tally.

    Zero for a dollar-metered runtime: only the agents in
    ``_METERED_TOKEN_AGENTS`` are capped by ``limits.codex_token_budget``.
    """
    if row.get("agent") not in _METERED_TOKEN_AGENTS:
        return 0
    return int(row.get("tokens_in") or 0) + int(row.get("tokens_out") or 0)


def refresh_actuals(vault_dir: Path, cycle_num: int, tally: CycleSpendTally) -> None:
    """Sum sidecar ``cost_usd`` and codex tokens into *tally*."""
    tally.actual_usd = 0.0
    tally.actual_codex_tokens = 0
    for row in list_sidecars_v11(vault_dir, cycle_num):
        tally.actual_usd += float(row.get("cost_usd") or 0.0)
        tally.actual_codex_tokens += _metered_tokens(row)


def atomic_write_json_marker(final_path: Path, payload: dict[str, Any]) -> None:
    """Write a budget/approval marker JSON file atomically.

    Thin shim over :func:`research_framework.pipeline.atomic_write.write_text`
    — kept for backward-compatibility with downstream callers (tests +
    spec-033 markers) that import this name. Consolidates onto the canonical
    spec-023 atomic-write implementation (mkstemp + fsync + os.replace +
    best-effort parent fsync), which is more robust than the previous
    ad-hoc ``tmp = .name.pid.tmp ; os.replace`` pattern on NFS and
    similar shared-mount filesystems.

    Preserves the original ``ensure_ascii=False`` JSON-output convention so
    non-ASCII marker payloads round-trip unchanged.
    """
    body = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    atomic_write.write_text(final_path, body)


def sum_sidecar_actuals_usd(vault_dir: Path, cycle_num: int) -> float:
    """Re-sum v1.1 sidecar costs for resume validation."""
    return sum(
        float(r.get("cost_usd") or 0.0) for r in list_sidecars_v11(vault_dir, cycle_num)
    )


def sum_sidecar_metered_tokens(vault_dir: Path, cycle_num: int) -> int:
    """Re-sum metered-runtime tokens for resume validation.

    The token analogue of :func:`sum_sidecar_actuals_usd`. Resume must not
    trust the marker's own ``codex_tokens_cumulative``: the contract's §4.3
    "recompute current spend from the sidecar glob — do not trust marker
    alone" applies to whichever currency paused the run, and the sidecars are
    the only record that survives the process.
    """
    return sum(_metered_tokens(r) for r in list_sidecars_v11(vault_dir, cycle_num))


def maybe_emit_budget_warn(
    tally: CycleSpendTally,
    limits: LimitsSettings,
    *,
    logger: logging.Logger | None = None,
) -> None:
    """FR-008: emit one soft WARN when actual spend crosses warn threshold."""
    cap = limits.cycle_budget_usd
    if cap is None or cap <= 0 or tally.warn_emitted:
        return
    threshold = cap * limits.cycle_budget_warn_at
    if tally.actual_usd >= threshold:
        log = logger or _LOG
        log.warning(
            "Cycle spend %.4f USD reached %.0f%% of cycle_budget_usd %.4f",
            tally.actual_usd,
            limits.cycle_budget_warn_at * 100,
            cap,
        )
        tally.warn_emitted = True


@dataclass
class DispatchPauseResult:
    """Typed pause payload returned by ``check_pre_dispatch``."""

    marker: BudgetPausedMarker


def check_pre_dispatch(
    *,
    tally: CycleSpendTally,
    limits: LimitsSettings,
    estimate_cost_usd: float,
    estimate_codex_tokens: int,
    stage: str,
    agent: str,
    prompt_preview: str = "",
) -> DispatchPauseResult | None:
    """Pre-dispatch cap checks; inclusive ``<=`` on caps, pause on strict ``>``."""
    dollar_increment = 0.0 if agent in ("local", "fake") else estimate_cost_usd

    cap_usd = limits.cycle_budget_usd
    if cap_usd is not None and cap_usd > 0:
        if tally.actual_usd + dollar_increment > cap_usd:
            return DispatchPauseResult(
                marker=BudgetPausedMarker(
                    pause_reason="dollar_cap_exceeded",
                    cycle_number=tally.cycle_num,
                    paused_stage=stage,
                    cumulative_spend_usd=tally.actual_usd,
                    cycle_budget_usd=cap_usd,
                    dispatch_estimate_usd=dollar_increment,
                    blocked_dispatch_preview=prompt_preview[:200],
                )
            )

    wall_min = limits.cycle_wallclock_budget_minutes
    if wall_min is not None and wall_min > 0:
        elapsed = time.monotonic() - tally.cycle_started_mono
        cap_sec = float(wall_min) * 60.0
        if elapsed > cap_sec:
            return DispatchPauseResult(
                marker=BudgetPausedMarker(
                    pause_reason="wallclock_exceeded",
                    cycle_number=tally.cycle_num,
                    paused_stage=stage,
                    cumulative_spend_usd=tally.actual_usd,
                    cycle_budget_usd=cap_usd or 0.0,
                    dispatch_estimate_usd=dollar_increment,
                    wallclock_elapsed_seconds=elapsed,
                    wallclock_cap_seconds=cap_sec,
                    blocked_dispatch_preview=prompt_preview[:200],
                )
            )

    codex_cap = limits.codex_token_budget
    if codex_cap is not None and codex_cap > 0 and agent in _METERED_TOKEN_AGENTS:
        projected = tally.actual_codex_tokens + estimate_codex_tokens
        if projected > codex_cap:
            return DispatchPauseResult(
                marker=BudgetPausedMarker(
                    pause_reason="codex_token_cap_exceeded",
                    cycle_number=tally.cycle_num,
                    paused_stage=stage,
                    cumulative_spend_usd=tally.actual_usd,
                    cycle_budget_usd=cap_usd or 0.0,
                    dispatch_estimate_usd=dollar_increment,
                    codex_tokens_cumulative=projected,
                    codex_token_budget=codex_cap,
                    blocked_dispatch_preview=prompt_preview[:200],
                )
            )
    return None


def pause_for_budget(vault_dir: Path, marker: BudgetPausedMarker) -> NoReturn:
    """Write ``BUDGET_PAUSED`` and exit the process."""
    path = vault_dir / BUDGET_PAUSED_REL
    atomic_write_json_marker(path, marker.to_json_dict())
    print(  # noqa: T201 — keep raw print: interactive prompt
        f"BUDGET_PAUSED: {marker.pause_reason} at stage {marker.paused_stage!r}. "
        "Bump limits.cycle_budget_usd or run `./vault research --resume --force-budget`.",
        file=sys.stderr,
    )
    raise SystemExit(1)


def pause_for_approval(vault_dir: Path, marker: ApprovalRequiredMarker) -> NoReturn:
    """Write ``APPROVAL_REQUIRED`` and exit."""
    path = vault_dir / APPROVAL_REQUIRED_REL
    atomic_write_json_marker(path, marker.to_json_dict())
    print(  # noqa: T201 — keep raw print: interactive prompt
        f"APPROVAL_REQUIRED: stage {marker.stage_name!r} needs operator approval. "
        "Resume with `./vault research --resume` and approve the stage.",
        file=sys.stderr,
    )
    raise SystemExit(1)


def check_approval_gate(
    *,
    vault_dir: Path,
    vault_settings: VaultSettings,
    tally: CycleSpendTally,
    stage: str,
    prompt_text: str,
    tier: str,
    agent: str,
    limits: LimitsSettings,
) -> ApprovalRequiredMarker | None:
    """FR-014: pause before gated stage when configured."""
    if stage not in vault_settings.approval_gates:
        return None
    from research_framework.pipeline.cost_estimator import estimate_dispatch

    est = estimate_dispatch(
        vault_dir=vault_dir,
        cycle_num=tally.cycle_num,
        stage=stage,
        prompt_text=prompt_text,
        agent=agent,
        tier=tier,
        limits=limits,
    )
    return ApprovalRequiredMarker(
        stage_name=stage,
        cycle_number=tally.cycle_num,
        prompt_preview=prompt_text,
        estimated_cost_usd=est.cost_usd,
        cumulative_spend_usd=tally.actual_usd,
        tier=tier,
        agent=agent,
    )


def resolve_dispatch_agent(vault_settings: VaultSettings, stage: str) -> str:
    """Mirror ``agent_call.py``'s executor precedence, read-only (spec 033).

    Lived in ``cycle_runner`` and took a live ``CycleBudgetSession``, which
    meant only a running cycle could ask "which runtime will this stage
    dispatch on". The cost preflight (issue #238) has to ask exactly that
    question before any session exists, and a second copy of this precedence
    would be a second answer — the class of drift spec 061 exists to remove.
    """
    stage_runtime = vault_settings.stage(stage).extras.get("runtime")
    if isinstance(stage_runtime, str) and stage_runtime.strip():
        return stage_runtime.strip().lower()
    default_exec = vault_settings.extras.get("default_executor")
    if isinstance(default_exec, dict):
        runtime = default_exec.get("runtime")
        if isinstance(runtime, str) and runtime.strip():
            return runtime.strip().lower()
    return vault_settings.default_agent


def resolve_max_tokens(vault_settings: VaultSettings, stage: str) -> int:
    """The output-token budget the estimator projects for ``stage``."""
    for source in (
        vault_settings.stage(stage).extras,
        vault_settings.extras.get("default_executor") or {},
    ):
        if isinstance(source, dict):
            raw = source.get("max_tokens")
            if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
                return raw
    return 4096


def collect_tier_cost_warnings(
    sidecars: list[dict[str, Any]], tier_thresholds: dict[str, float]
) -> list[dict[str, Any]]:
    """FR-007: one warning row per offending sidecar."""
    warnings: list[dict[str, Any]] = []
    for row in sidecars:
        tier = str(row.get("tier") or "")
        threshold = tier_thresholds.get(tier)
        if threshold is None:
            continue
        cost = float(row.get("cost_usd") or 0.0)
        if cost > threshold:
            warnings.append(
                {
                    "stage": row.get("stage"),
                    "tier": tier,
                    "cost_usd": cost,
                    "threshold": threshold,
                    "delta": round(cost - threshold, 4),
                }
            )
    return warnings


def clear_budget_marker(vault_dir: Path) -> None:
    path = vault_dir / BUDGET_PAUSED_REL
    if path.is_file():
        path.unlink()


def clear_approval_marker(vault_dir: Path) -> None:
    path = vault_dir / APPROVAL_REQUIRED_REL
    if path.is_file():
        path.unlink()


def budget_marker_path(vault_dir: Path) -> Path:
    return vault_dir / BUDGET_PAUSED_REL


def approval_marker_path(vault_dir: Path) -> Path:
    return vault_dir / APPROVAL_REQUIRED_REL


class CycleBudgetSession:
    """Per-cycle budget session wired from ``cycle_runner``."""

    def __init__(
        self,
        vault_dir: Path,
        cycle_num: int,
        vault_settings: VaultSettings,
    ) -> None:
        self.vault_dir = vault_dir
        self.cycle_num = cycle_num
        self.vault_settings = vault_settings
        self.limits = vault_settings.limits
        self.tally = CycleSpendTally(cycle_num=cycle_num)
        refresh_actuals(vault_dir, cycle_num, self.tally)

    def before_agent_call(
        self,
        *,
        stage: str,
        prompt_text: str = "",
        agent: str = "claude",
        tier: str = "standard",
        max_tokens: int = 4096,
    ) -> None:
        from research_framework.pipeline.cost_estimator import estimate_dispatch

        est = estimate_dispatch(
            vault_dir=self.vault_dir,
            cycle_num=self.cycle_num,
            stage=stage,
            prompt_text=prompt_text,
            agent=agent,
            tier=tier,
            max_tokens=max_tokens,
            limits=self.limits,
        )
        self.tally.last_estimation_method = est.estimation_method
        self.tally.estimation_methods_used.append(
            {"stage": stage, "method": est.estimation_method}
        )
        pause = check_pre_dispatch(
            tally=self.tally,
            limits=self.limits,
            estimate_cost_usd=est.cost_usd,
            estimate_codex_tokens=est.codex_tokens,
            stage=stage,
            agent=agent,
            prompt_preview=prompt_text,
        )
        if pause is not None:
            pause_for_budget(self.vault_dir, pause.marker)

        approval = check_approval_gate(
            vault_dir=self.vault_dir,
            vault_settings=self.vault_settings,
            tally=self.tally,
            stage=stage,
            prompt_text=prompt_text,
            tier=tier,
            agent=agent,
            limits=self.limits,
        )
        if approval is not None:
            pause_for_approval(self.vault_dir, approval)

        maybe_emit_budget_warn(self.tally, self.limits)

    def after_agent_call(self) -> None:
        refresh_actuals(self.vault_dir, self.cycle_num, self.tally)
