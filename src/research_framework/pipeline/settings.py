"""Canonical vault ``settings.yaml`` loader (spec 025 US9 B7)."""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

# Spec 052: cursor-agent is flat-rate (real tokens, no per-call dollar). Its
# estimator factor mirrors codex (≈1.0) since the dollar is a budget-gating
# estimate, not a bill, and most cursor models tokenise close to o200k_base.
_DEFAULT_ESTIMATOR_CALIBRATION: dict[str, float] = {
    "claude": 1.15,
    "codex": 1.0,
    "cursor-agent": 1.0,
    # Spec 047 v1: local Ollama is genuinely $0, so calibration never bites —
    # kept at 1.0 for completeness so the estimator path doesn't KeyError.
    "ollama": 1.0,
    # Spec 064: opencode is provider-agnostic; the estimator is only the
    # fallback when a metered provider returns no usable cost. 1.0 default.
    "opencode": 1.0,
}
_BUDGET_USD_ALIAS_WARNED = False

Tier = Literal["basic", "standard", "expert"]
DefaultAgent = Literal["claude", "codex", "cursor-agent", "ollama", "opencode"]

_VALID_TIERS = frozenset({"basic", "standard", "expert"})
_VALID_AGENTS = frozenset({"claude", "codex", "cursor-agent", "ollama", "opencode"})
_PIPELINE_TYPED_KEYS = frozenset(
    {"max_cycles", "budget_usd", "backlog_promotion_threshold"}
)
_D7_TIER_RESOLUTION_STAGES = frozenset({"schema_gen", "source_extraction"})
# Anthropic model ids for the runtime-agnostic tier names. Two things to know
# before editing these:
#
#   1. Ids are HYPHENATED, never dotted. The pre-2026-08-27 values
#      (`claude-haiku-4.6`, `claude-sonnet-4.6`, `claude-opus-4.7`) used dots
#      and were not resolvable model ids at all.
#   2. There is no Haiku 5 — 4.5 is the newest Haiku, so `basic` stays there
#      while `normal`/`flagship` move to the 5 family. `normal` also gets
#      cheaper in the process (Sonnet 4.6 $3/$15 → Sonnet 5 $2/$10).
#
# These are ANTHROPIC ids. cursor-agent uses its own scheme
# (`claude-opus-4-8-thinking-high`) — see `_CURSOR_MODEL_TIERS` in
# `scripts/agent_call.py`; do not cross-apply them.
_DEFAULT_MODEL_TIERS = {
    "basic": "claude-haiku-4-5",
    "normal": "claude-sonnet-5",
    "flagship": "claude-opus-5",
}

# Spec 061: the single canonical cycle-budget default. A generous value so a
# bootstrap run never silently truncates (the rc1 12→6 footgun). Both shipped
# seeds (settings.yaml / settings.codex.yaml) carry this value; the CLI
# resolver and the cycle-time yield readers fall back to it.
DEFAULT_MAX_CYCLES = 20


@dataclass(frozen=True)
class LimitsSettings:
    """Typed ``settings.yaml::limits`` slice (spec 033)."""

    cycle_budget_usd: float | None = None
    codex_token_budget: int | None = None
    cycle_wallclock_budget_minutes: int | None = None
    cycle_budget_warn_at: float = 0.80
    tier_thresholds: dict[str, float] = field(default_factory=dict)
    estimator_calibration: dict[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_ESTIMATOR_CALIBRATION)
    )


_DEFAULT_CADENCE_FACTOR: dict[str, float] = {
    "daily": 1.0,
    "weekly": 3.0,
    "biweekly": 5.0,
    "monthly": 8.0,
}
_DEFAULT_COVERAGE_FACTOR: dict[str, float] = {
    "coverage_below_50pct": 1.5,
    "coverage_50_to_80pct": 1.0,
    "coverage_above_80pct": 0.5,
}
_VALID_CADENCE_BUCKETS = frozenset(_DEFAULT_CADENCE_FACTOR)
_VALID_COVERAGE_BUCKETS = frozenset(_DEFAULT_COVERAGE_FACTOR)


@dataclass(frozen=True)
class CycleYieldSettings:
    """Typed ``settings.yaml::cycle_yield`` slice (spec 051 FR1).

    Multiplicative CG-001 model: ``target = base * cadence_factor *
    coverage_factor``, clamped to ``[min_floor, max_ceiling]``.
    """

    base_notes_per_cycle: int = 5
    cadence_factor: dict[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_CADENCE_FACTOR)
    )
    coverage_factor: dict[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_COVERAGE_FACTOR)
    )
    min_floor: int = 1
    max_ceiling: int = 50


@dataclass(frozen=True)
class StubsSettings:
    """Typed ``settings.yaml::stubs`` slice (spec 051 FR3).

    A short note with at least ``anchor_link_threshold`` inbound wikilinks is a
    graph anchor: it is flagged for research, never silently deleted.
    """

    anchor_link_threshold: int = 5


@dataclass(frozen=True)
class StageSettings:
    """Per-stage knobs from ``settings.yaml::stages.<name>``."""

    tier: Tier = "standard"
    enabled: bool = True
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RefreshSourcesSettings:
    """settings.yaml::refresh_sources (spec 023)."""

    collectors: tuple[str, ...] = ()
    timeout_s: int = 600


@dataclass(frozen=True)
class ReportsMirrorSettings:
    """settings.yaml::reports.mirror (spec 040 FR-013)."""

    target: str | None = None


@dataclass(frozen=True)
class ReportsSmtpSettings:
    """settings.yaml::reports.smtp (spec 040 FR-016)."""

    enabled: bool = False
    recipient: str | None = None
    server: str | None = None
    port: int | None = None
    from_address: str | None = None


@dataclass(frozen=True)
class ReportsSettings:
    """settings.yaml::reports (spec 040)."""

    mirror: ReportsMirrorSettings = field(default_factory=ReportsMirrorSettings)
    smtp: ReportsSmtpSettings = field(default_factory=ReportsSmtpSettings)


@dataclass(frozen=True)
class CredibilitySettings:
    """settings.yaml::credibility (spec 066 FR3).

    ``unknown_domain_policy`` controls the FR2 WARN-vs-FAIL split for catalog-miss
    well-formed URLs; ``trusted_domains`` is the vault-local override that fully
    replaces matching default-catalog entries (Q11). Absent section ⇒ permissive
    default (warn) + empty override.
    """

    unknown_domain_policy: str = "warn"
    trusted_domains: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class VaultSettings:
    """Typed access to a vault's ``settings.yaml``."""

    max_cycles: int
    budget_usd: float
    backlog_promotion_threshold: int = 2
    stages: dict[str, StageSettings] = field(default_factory=dict)
    dimensions: list[str] = field(default_factory=list)
    default_agent: DefaultAgent = "claude"
    refresh_sources: RefreshSourcesSettings = field(
        default_factory=RefreshSourcesSettings
    )
    limits: LimitsSettings = field(default_factory=LimitsSettings)
    cycle_yield: CycleYieldSettings = field(default_factory=CycleYieldSettings)
    stubs: StubsSettings = field(default_factory=StubsSettings)
    approval_gates: list[str] = field(default_factory=list)
    tiers: dict[str, str] = field(default_factory=dict)
    modules: list[str] = field(default_factory=list)
    reports: ReportsSettings = field(default_factory=ReportsSettings)
    credibility: CredibilitySettings = field(default_factory=CredibilitySettings)
    # Spec 071: a finished vault. Its notes stay queryable, indexable,
    # digestible and re-gradable, and it still takes framework upgrades — but
    # no research cycle may write to it again. Enforced in the orchestrator so
    # every caller is covered, not just the CLI.
    archived: bool = False
    # How much bigger a vault should get once it has met every coverage target
    # (pipeline.coverage_growth). 1.0 — the default — is one-and-done: the vault
    # answers its question and stops, which is right for a snapshot or a
    # decision vault. Above 1.0 belongs to a subject that moves faster than the
    # vault does; each round multiplies a larger base, so the vault grows
    # exponentially across rounds rather than by a fixed increment. Never
    # applied to an archived vault. See coverage.grow_targets_if_met.
    coverage_growth: float = 1.0
    # Ceiling on what one category may gain in one round
    # (pipeline.coverage_growth_cap). Keeps the multiplier from compounding
    # into a target nobody will ever write; ignored when coverage_growth is 1.0.
    coverage_growth_cap: int = 10
    extras: dict[str, Any] = field(default_factory=dict)

    def stage(self, name: str) -> StageSettings:
        """Return per-stage settings, or defaults when the stage is absent."""
        if name not in self.stages:
            if name == "source_extraction":
                return StageSettings(enabled=False)
            return StageSettings()
        return self.stages[name]

    def resolve_model(
        self,
        stage_name: str,
        *,
        manifest_default_tier: str | None = None,
    ) -> str | None:
        """Resolve executor model for D7 tier stages (FR-014a)."""
        return resolve_stage_model(
            self,
            stage_name,
            manifest_default_tier=manifest_default_tier,
        )


class SettingsError(Exception):
    """Raised for any ``settings.yaml`` issue."""

    def __init__(
        self,
        message: str,
        *,
        vault_dir: Path | None = None,
        key: str | None = None,
    ) -> None:
        self.vault_dir = vault_dir
        self.key = key
        super().__init__(message)


def load_vault_settings(vault_dir: Path) -> VaultSettings:
    """Load and validate ``<vault_dir>/settings.yaml``."""
    settings_path = vault_dir / "settings.yaml"
    if not settings_path.is_file():
        raise SettingsError(
            f"settings.yaml not found at {vault_dir}",
            vault_dir=vault_dir,
        )

    try:
        raw = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SettingsError(
            f"YAML parse error in settings.yaml: {exc}",
            vault_dir=vault_dir,
        ) from exc

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise SettingsError(
            "settings.yaml top-level must be a mapping",
            vault_dir=vault_dir,
        )

    pipeline = raw.get("pipeline")
    if pipeline is None:
        pipeline = {}
    if not isinstance(pipeline, dict):
        raise SettingsError(
            "pipeline must be a mapping",
            vault_dir=vault_dir,
            key="pipeline",
        )

    max_cycles = _require_positive_int(
        pipeline.get("max_cycles"),
        key="max_cycles",
        vault_dir=vault_dir,
        label="max_cycles must be an integer >= 1",
    )
    budget_usd = _require_non_negative_number(
        pipeline.get("budget_usd"),
        key="budget_usd",
        vault_dir=vault_dir,
    )

    threshold_raw = pipeline.get("backlog_promotion_threshold", 2)
    backlog_promotion_threshold = _require_positive_int(
        threshold_raw,
        key="pipeline.backlog_promotion_threshold",
        vault_dir=vault_dir,
        label="backlog_promotion_threshold must be an integer >= 1",
    )

    pipeline_extra = {
        k: v for k, v in pipeline.items() if k not in _PIPELINE_TYPED_KEYS
    }
    extras: dict[str, Any] = {
        k: v
        for k, v in raw.items()
        if k
        not in {
            "pipeline",
            "stages",
            "dimensions",
            "default_agent",
            "refresh_sources",
            "limits",
            "cycle_yield",
            "stubs",
            "approval_gates",
            "reports",
            "credibility",
        }
    }
    if pipeline_extra:
        extras["pipeline"] = pipeline_extra

    archived = _parse_archived(raw.get("archived"), vault_dir=vault_dir)
    coverage_growth = _parse_coverage_growth(
        (raw.get("pipeline") or {}).get("coverage_growth"), vault_dir=vault_dir
    )
    coverage_growth_cap = _parse_coverage_growth_cap(
        (raw.get("pipeline") or {}).get("coverage_growth_cap"), vault_dir=vault_dir
    )
    tiers = _parse_tiers(raw.get("tiers"), vault_dir=vault_dir)
    modules = _parse_modules(raw.get("modules"), vault_dir=vault_dir)
    stages = _parse_stages(raw.get("stages"), vault_dir=vault_dir, tiers=tiers)
    _validate_consensus_n(stages, vault_dir=vault_dir)
    dimensions = _parse_dimensions(raw.get("dimensions"), vault_dir=vault_dir)
    default_agent = _parse_default_agent(
        raw.get("default_agent", "claude"),
        vault_dir=vault_dir,
    )
    refresh_sources = _parse_refresh_sources(
        raw.get("refresh_sources"), vault_dir=vault_dir
    )
    limits = _parse_limits(raw.get("limits"), vault_dir=vault_dir)
    cycle_yield = _parse_cycle_yield(raw.get("cycle_yield"), vault_dir=vault_dir)
    stubs = _parse_stubs(raw.get("stubs"), vault_dir=vault_dir)
    approval_gates = _parse_approval_gates(
        raw.get("approval_gates"), vault_dir=vault_dir
    )
    reports = _parse_reports(raw.get("reports"), vault_dir=vault_dir)
    credibility = _parse_credibility(raw.get("credibility"), vault_dir=vault_dir)

    return VaultSettings(
        max_cycles=max_cycles,
        budget_usd=budget_usd,
        backlog_promotion_threshold=backlog_promotion_threshold,
        stages=stages,
        dimensions=dimensions,
        default_agent=default_agent,
        refresh_sources=refresh_sources,
        limits=limits,
        cycle_yield=cycle_yield,
        stubs=stubs,
        approval_gates=approval_gates,
        archived=archived,
        coverage_growth=coverage_growth,
        coverage_growth_cap=coverage_growth_cap,
        tiers=tiers,
        modules=modules,
        reports=reports,
        credibility=credibility,
        extras=extras,
    )


def effective_max_cycles(vault_dir: Path, default: int = DEFAULT_MAX_CYCLES) -> int:
    """Return the vault's configured ``pipeline.max_cycles`` for cycle-time use.

    Spec 061: the cycle budget lives in ``settings.yaml`` (canonical
    ``pipeline.max_cycles``), not in the baked research spec. Cycle-time
    consumers — the yield model (``research_plan`` / ``quality_report``) and the
    scaffold — read it here instead of the now-removed ``spec.max_cycles``. A
    missing/unreadable settings file falls back to the generous
    :data:`DEFAULT_MAX_CYCLES` so a vault built before the canonical key existed
    still projects a sane horizon (never the rc1 truncated value).
    """
    try:
        return load_vault_settings(vault_dir).max_cycles
    except SettingsError:
        return default


def _parse_reports(raw: object, *, vault_dir: Path) -> ReportsSettings:
    """Parse ``settings.yaml::reports`` (spec 040). Absent block ⇒ defaults."""
    if raw is None:
        return ReportsSettings()
    if not isinstance(raw, dict):
        raise SettingsError(
            "reports must be a mapping", vault_dir=vault_dir, key="reports"
        )
    mirror_raw = raw.get("mirror")
    smtp_raw = raw.get("smtp")
    mirror = ReportsMirrorSettings()
    smtp = ReportsSmtpSettings()
    if mirror_raw is not None:
        if not isinstance(mirror_raw, dict):
            raise SettingsError(
                "reports.mirror must be a mapping",
                vault_dir=vault_dir,
                key="reports.mirror",
            )
        target = mirror_raw.get("target")
        if target is not None and not isinstance(target, str):
            raise SettingsError(
                "reports.mirror.target must be a string",
                vault_dir=vault_dir,
                key="reports.mirror.target",
            )
        mirror = ReportsMirrorSettings(target=target)
    if smtp_raw is not None:
        if not isinstance(smtp_raw, dict):
            raise SettingsError(
                "reports.smtp must be a mapping",
                vault_dir=vault_dir,
                key="reports.smtp",
            )
        enabled = smtp_raw.get("enabled", False)
        if not isinstance(enabled, bool):
            raise SettingsError(
                "reports.smtp.enabled must be a boolean",
                vault_dir=vault_dir,
                key="reports.smtp.enabled",
            )
        recipient = smtp_raw.get("recipient")
        if recipient is not None and not isinstance(recipient, str):
            raise SettingsError(
                "reports.smtp.recipient must be a string",
                vault_dir=vault_dir,
                key="reports.smtp.recipient",
            )
        server = smtp_raw.get("server")
        if server is not None and not isinstance(server, str):
            raise SettingsError(
                "reports.smtp.server must be a string",
                vault_dir=vault_dir,
                key="reports.smtp.server",
            )
        port_raw = smtp_raw.get("port")
        port: int | None = None
        if port_raw is not None:
            if isinstance(port_raw, bool) or not isinstance(port_raw, int):
                raise SettingsError(
                    "reports.smtp.port must be an integer",
                    vault_dir=vault_dir,
                    key="reports.smtp.port",
                )
            port = port_raw
        from_raw = smtp_raw.get("from")
        if from_raw is not None and not isinstance(from_raw, str):
            raise SettingsError(
                "reports.smtp.from must be a string",
                vault_dir=vault_dir,
                key="reports.smtp.from",
            )
        smtp = ReportsSmtpSettings(
            enabled=enabled,
            recipient=recipient,
            server=server,
            port=port,
            from_address=from_raw,
        )
    return ReportsSettings(mirror=mirror, smtp=smtp)


_CREDIBILITY_POLICIES = frozenset({"warn", "reject"})


def _parse_credibility(raw: object, *, vault_dir: Path) -> CredibilitySettings:
    """Parse ``settings.yaml::credibility`` (spec 066 FR3). Absent ⇒ defaults."""
    if raw is None:
        return CredibilitySettings()
    if not isinstance(raw, dict):
        raise SettingsError(
            "credibility must be a mapping", vault_dir=vault_dir, key="credibility"
        )
    policy = raw.get("unknown_domain_policy", "warn")
    if (
        not isinstance(policy, str)
        or policy.strip().lower() not in _CREDIBILITY_POLICIES
    ):
        raise SettingsError(
            "credibility.unknown_domain_policy must be 'warn' or 'reject'",
            vault_dir=vault_dir,
            key="credibility.unknown_domain_policy",
        )
    trusted_raw = raw.get("trusted_domains", [])
    if trusted_raw is None:
        trusted_raw = []
    if not isinstance(trusted_raw, list):
        raise SettingsError(
            "credibility.trusted_domains must be a list",
            vault_dir=vault_dir,
            key="credibility.trusted_domains",
        )
    trusted: list[dict[str, Any]] = []
    for idx, entry in enumerate(trusted_raw):
        if not isinstance(entry, dict):
            raise SettingsError(
                f"credibility.trusted_domains[{idx}] must be a mapping",
                vault_dir=vault_dir,
                key="credibility.trusted_domains",
            )
        if not str(entry.get("domain") or "").strip():
            raise SettingsError(
                f"credibility.trusted_domains[{idx}] requires a non-empty 'domain'",
                vault_dir=vault_dir,
                key="credibility.trusted_domains",
            )
        if not str(entry.get("tier") or "").strip():
            raise SettingsError(
                f"credibility.trusted_domains[{idx}] requires a 'tier'",
                vault_dir=vault_dir,
                key="credibility.trusted_domains",
            )
        trusted.append(dict(entry))
    return CredibilitySettings(
        unknown_domain_policy=policy.strip().lower(),
        trusted_domains=tuple(trusted),
    )


def _parse_factor_map(
    raw: object,
    defaults: dict[str, float],
    valid_keys: frozenset[str],
    *,
    key: str,
    vault_dir: Path,
) -> dict[str, float]:
    """Merge a user factor map over ``defaults``; values must be > 0; WARN unknowns."""
    result = dict(defaults)
    if raw is None:
        return result
    if not isinstance(raw, dict):
        raise SettingsError(f"{key} must be a mapping", vault_dir=vault_dir, key=key)
    for k, v in raw.items():
        if k not in valid_keys:
            warnings.warn(
                f"{key}: unknown bucket {k!r} ignored (valid: {sorted(valid_keys)})",
                stacklevel=2,
            )
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
            raise SettingsError(
                f"{key}.{k} must be a number > 0",
                vault_dir=vault_dir,
                key=f"{key}.{k}",
            )
        result[k] = float(v)
    return result


def _parse_cycle_yield(raw: object, *, vault_dir: Path) -> CycleYieldSettings:
    """Parse ``settings.yaml::cycle_yield`` (spec 051 FR1). Absent block → defaults."""
    if raw is None:
        return CycleYieldSettings()
    if not isinstance(raw, dict):
        raise SettingsError(
            "cycle_yield must be a mapping", vault_dir=vault_dir, key="cycle_yield"
        )
    base = _require_positive_int(
        raw.get("base_notes_per_cycle", 5),
        key="cycle_yield.base_notes_per_cycle",
        vault_dir=vault_dir,
        label="cycle_yield.base_notes_per_cycle must be an integer >= 1",
    )
    min_floor = _require_positive_int(
        raw.get("min_floor", 1),
        key="cycle_yield.min_floor",
        vault_dir=vault_dir,
        label="cycle_yield.min_floor must be an integer >= 1",
    )
    max_ceiling = _require_positive_int(
        raw.get("max_ceiling", 50),
        key="cycle_yield.max_ceiling",
        vault_dir=vault_dir,
        label="cycle_yield.max_ceiling must be an integer >= 1",
    )
    if max_ceiling < min_floor:
        raise SettingsError(
            f"cycle_yield.max_ceiling ({max_ceiling}) must be >= "
            f"min_floor ({min_floor})",
            vault_dir=vault_dir,
            key="cycle_yield.max_ceiling",
        )
    cadence = _parse_factor_map(
        raw.get("cadence_factor"),
        _DEFAULT_CADENCE_FACTOR,
        _VALID_CADENCE_BUCKETS,
        key="cycle_yield.cadence_factor",
        vault_dir=vault_dir,
    )
    coverage = _parse_factor_map(
        raw.get("coverage_factor"),
        _DEFAULT_COVERAGE_FACTOR,
        _VALID_COVERAGE_BUCKETS,
        key="cycle_yield.coverage_factor",
        vault_dir=vault_dir,
    )
    return CycleYieldSettings(
        base_notes_per_cycle=base,
        cadence_factor=cadence,
        coverage_factor=coverage,
        min_floor=min_floor,
        max_ceiling=max_ceiling,
    )


def _parse_stubs(raw: object, *, vault_dir: Path) -> StubsSettings:
    """Parse ``settings.yaml::stubs`` (spec 051 FR3). Absent block → defaults."""
    if raw is None:
        return StubsSettings()
    if not isinstance(raw, dict):
        raise SettingsError("stubs must be a mapping", vault_dir=vault_dir, key="stubs")
    anchor_link_threshold = _require_positive_int(
        raw.get("anchor_link_threshold", 5),
        key="stubs.anchor_link_threshold",
        vault_dir=vault_dir,
        label="stubs.anchor_link_threshold must be an integer >= 1",
    )
    return StubsSettings(anchor_link_threshold=anchor_link_threshold)


def _parse_refresh_sources(raw: object, *, vault_dir: Path) -> RefreshSourcesSettings:
    if raw is None:
        return RefreshSourcesSettings()
    if not isinstance(raw, dict):
        raise SettingsError(
            "refresh_sources must be a mapping",
            vault_dir=vault_dir,
            key="refresh_sources",
        )
    collectors_raw = raw.get("collectors")
    collectors: tuple[str, ...] = ()
    if collectors_raw is not None:
        if not isinstance(collectors_raw, list) or not all(
            isinstance(x, str) for x in collectors_raw
        ):
            raise SettingsError(
                "refresh_sources.collectors must be a list of strings",
                vault_dir=vault_dir,
                key="refresh_sources.collectors",
            )
        collectors = tuple(collectors_raw)
    timeout_raw = raw.get("timeout_s", 600)
    if (
        isinstance(timeout_raw, bool)
        or not isinstance(timeout_raw, int)
        or timeout_raw < 1
    ):
        raise SettingsError(
            f"refresh_sources.timeout_s must be a positive integer, got {timeout_raw!r}",
            vault_dir=vault_dir,
            key="refresh_sources.timeout_s",
        )
    return RefreshSourcesSettings(collectors=collectors, timeout_s=timeout_raw)


def resolve_stage_model(
    settings: VaultSettings,
    stage_name: str,
    *,
    manifest_default_tier: str | None = None,
) -> str | None:
    """Resolve model id for a stage executor (D7 / FR-014a)."""
    stage = settings.stage(stage_name)
    model = stage.extras.get("model")
    tier_key = stage.extras.get("tier") or (
        manifest_default_tier
        if stage_name in _D7_TIER_RESOLUTION_STAGES and not model
        else None
    )
    if model and tier_key:
        raise SettingsError(
            f"stages.{stage_name} cannot set both model and tier",
            vault_dir=None,
            key=f"stages.{stage_name}",
        )
    if model:
        return str(model)
    if tier_key:
        resolved = settings.tiers.get(str(tier_key))
        if resolved is None:
            raise SettingsError(
                f"Unknown tier {tier_key!r} for stage {stage_name!r}",
                key="tiers",
            )
        return resolved
    if stage_name in _D7_TIER_RESOLUTION_STAGES and manifest_default_tier:
        return settings.tiers.get(manifest_default_tier)
    return None


def _parse_coverage_growth_cap(raw: object, *, vault_dir: Path) -> int:
    """Parse ``pipeline.coverage_growth_cap``. Absent ⇒ 10.

    Must be >= 1: a cap of 0 would mean "grow by nothing", which is what
    ``coverage_growth: 1.0`` already says, and silently freezing a vault the
    operator asked to grow is the failure this whole feature exists to end.
    """
    if raw is None:
        return 10
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise SettingsError(
            f"pipeline.coverage_growth_cap must be an integer >= 1, got {raw!r}",
            vault_dir=vault_dir,
            key="pipeline.coverage_growth_cap",
        )
    if raw < 1:
        raise SettingsError(
            f"pipeline.coverage_growth_cap must be >= 1, got {raw!r}",
            vault_dir=vault_dir,
            key="pipeline.coverage_growth_cap",
        )
    return int(raw)


def _parse_coverage_growth(raw: object, *, vault_dir: Path) -> float:
    """Parse ``pipeline.coverage_growth``. Absent ⇒ 1.0 (one-and-done).

    Strict for the same reason as ``archived``: this decides whether a vault
    keeps growing, and a typo that silently reads as 1.0 would quietly freeze a
    vault the operator expects to keep pace. A value below 1.0 is rejected
    rather than clamped — it can only be a mistake, since shrinking a target
    below what the vault already holds means nothing.
    """
    if raw is None:
        return 1.0
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise SettingsError(
            f"pipeline.coverage_growth must be a number >= 1.0, got {raw!r}",
            vault_dir=vault_dir,
            key="pipeline.coverage_growth",
        )
    if float(raw) < 1.0:
        raise SettingsError(
            f"pipeline.coverage_growth must be >= 1.0, got {raw!r}",
            vault_dir=vault_dir,
            key="pipeline.coverage_growth",
        )
    return float(raw)


def _parse_archived(raw: object, *, vault_dir: Path) -> bool:
    """Parse ``settings.yaml::archived`` (spec 071). Absent ⇒ ``False``.

    Deliberately strict: only a real YAML boolean is accepted. A typo like
    ``archived: yes-please`` must not quietly read as "not archived" and let a
    research cycle rewrite a vault the operator considers finished — the whole
    point of the flag is that it holds under every circumstance.
    """
    if raw is None:
        return False
    if isinstance(raw, bool):
        return raw
    raise SettingsError(
        f"archived must be a boolean (true/false), got {raw!r}",
        vault_dir=vault_dir,
        key="archived",
    )


def _parse_tiers(raw: object, *, vault_dir: Path) -> dict[str, str]:
    if raw is None:
        return dict(_DEFAULT_MODEL_TIERS)
    if not isinstance(raw, dict):
        raise SettingsError("tiers must be a mapping", vault_dir=vault_dir, key="tiers")
    out: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not value:
            raise SettingsError(
                f"tiers.{key} must be a non-empty string",
                vault_dir=vault_dir,
                key=f"tiers.{key}",
            )
        out[key] = str(value)
    for required in ("basic", "normal", "flagship"):
        out.setdefault(required, _DEFAULT_MODEL_TIERS[required])
    return out


def _parse_modules(raw: object, *, vault_dir: Path) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise SettingsError(
            "modules must be a list", vault_dir=vault_dir, key="modules"
        )
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise SettingsError(
                "modules must be a list of strings",
                vault_dir=vault_dir,
                key="modules",
            )
        out.append(item)
    return out


def _validate_consensus_n(stages: dict[str, StageSettings], *, vault_dir: Path) -> None:
    stage = stages.get("source_extraction")
    if stage is None:
        return
    consensus = stage.extras.get("consensus")
    if not isinstance(consensus, dict):
        return
    tiers = consensus.get("tiers")
    if not isinstance(tiers, dict):
        return
    normalized: dict[str, int] = {}
    for label, n in tiers.items():
        if isinstance(n, bool):
            raise SettingsError(
                f"stages.source_extraction.consensus.tiers.{label} must be an integer",
                vault_dir=vault_dir,
                key=f"stages.source_extraction.consensus.tiers.{label}",
            )
        if isinstance(n, str) and n.isdigit():
            n = int(n)
        if not isinstance(n, int):
            raise SettingsError(
                f"stages.source_extraction.consensus.tiers.{label} must be an integer",
                vault_dir=vault_dir,
                key=f"stages.source_extraction.consensus.tiers.{label}",
            )
        if n < 1:
            raise SettingsError(
                f"stages.source_extraction.consensus.tiers.{label} must be >= 1",
                vault_dir=vault_dir,
                key=f"stages.source_extraction.consensus.tiers.{label}",
            )
        if n % 2 == 0:
            raise SettingsError(
                f"stages.source_extraction.consensus.tiers.{label} must be odd (FR-020)",
                vault_dir=vault_dir,
                key=f"stages.source_extraction.consensus.tiers.{label}",
            )
        normalized[str(label)] = n
    consensus["tiers"] = normalized


def _parse_stages(
    raw: object,
    *,
    vault_dir: Path,
    tiers: dict[str, str],
) -> dict[str, StageSettings]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise SettingsError(
            "stages must be a mapping",
            vault_dir=vault_dir,
            key="stages",
        )
    out: dict[str, StageSettings] = {}
    for name, cfg in raw.items():
        if not isinstance(name, str):
            continue
        if cfg is None:
            cfg = {}
        if not isinstance(cfg, dict):
            raise SettingsError(
                f"stages.{name} must be a mapping",
                vault_dir=vault_dir,
                key=f"stages.{name}",
            )
        enabled = cfg.get("enabled", True)
        if not isinstance(enabled, bool):
            raise SettingsError(
                f"stages.{name}.enabled must be a boolean, got {type(enabled).__name__}",
                vault_dir=vault_dir,
                key=f"stages.{name}.enabled",
            )
        model = cfg.get("model")
        executor_tier = cfg.get("tier")
        if (
            model is not None
            and executor_tier is not None
            and name in _D7_TIER_RESOLUTION_STAGES
        ):
            raise SettingsError(
                f"stages.{name} cannot set both model and tier (FR-014a)",
                vault_dir=vault_dir,
                key=f"stages.{name}",
            )
        if executor_tier is not None and name in _D7_TIER_RESOLUTION_STAGES:
            if str(executor_tier) not in tiers:
                raise SettingsError(
                    f"Unknown tier {executor_tier!r} for stage {name!r}",
                    vault_dir=vault_dir,
                    key=f"stages.{name}.tier",
                )
            complexity_tier: Tier = "standard"
            stage_extras = {
                k: v for k, v in cfg.items() if k not in {"tier", "enabled", "model"}
            }
            stage_extras["tier"] = str(executor_tier)
            if model is not None:
                stage_extras["model"] = model
        else:
            tier_raw = cfg.get("tier", "standard")
            if tier_raw is None:
                tier_raw = "standard"
            tier = str(tier_raw)
            if tier not in _VALID_TIERS:
                raise SettingsError(
                    f"stages.{name}.tier must be one of basic/standard/expert, got {tier_raw!r}",
                    vault_dir=vault_dir,
                    key=f"stages.{name}.tier",
                )
            complexity_tier = tier  # type: ignore[assignment]
            stage_extras = {
                k: v for k, v in cfg.items() if k not in {"tier", "enabled"}
            }
            if model is not None:
                stage_extras["model"] = model
        out[name] = StageSettings(
            tier=complexity_tier,
            enabled=enabled,
            extras=stage_extras,
        )
    return out


def _parse_dimensions(raw: object, *, vault_dir: Path) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise SettingsError(
            f"dimensions must be a list, got {type(raw).__name__}",
            vault_dir=vault_dir,
            key="dimensions",
        )
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise SettingsError(
                "dimensions must be a list of strings",
                vault_dir=vault_dir,
                key="dimensions",
            )
        out.append(item)
    return out


def _parse_limits(raw: object, *, vault_dir: Path) -> LimitsSettings:
    global _BUDGET_USD_ALIAS_WARNED
    if raw is None:
        return LimitsSettings()
    if not isinstance(raw, dict):
        raise SettingsError(
            "limits must be a mapping",
            vault_dir=vault_dir,
            key="limits",
        )
    cycle_budget: float | None = None
    if "cycle_budget_usd" in raw:
        cycle_budget = _optional_positive_float(
            raw.get("cycle_budget_usd"),
            key="limits.cycle_budget_usd",
            vault_dir=vault_dir,
        )
    if "budget_usd" in raw and cycle_budget is None:
        cycle_budget = _optional_positive_float(
            raw.get("budget_usd"),
            key="limits.budget_usd",
            vault_dir=vault_dir,
        )
        if not _BUDGET_USD_ALIAS_WARNED:
            warnings.warn(
                "limits.budget_usd is deprecated; use limits.cycle_budget_usd",
                DeprecationWarning,
                stacklevel=2,
            )
            _BUDGET_USD_ALIAS_WARNED = True
    codex_raw = raw.get("codex_token_budget")
    codex_budget: int | None = None
    if codex_raw is not None:
        if (
            isinstance(codex_raw, bool)
            or not isinstance(codex_raw, int)
            or codex_raw < 1
        ):
            raise SettingsError(
                f"limits.codex_token_budget must be int >= 1, got {codex_raw!r}",
                vault_dir=vault_dir,
                key="limits.codex_token_budget",
            )
        codex_budget = codex_raw
    wall_raw = raw.get("cycle_wallclock_budget_minutes")
    wall_min: int | None = None
    if wall_raw is not None:
        if isinstance(wall_raw, bool) or not isinstance(wall_raw, int) or wall_raw < 1:
            raise SettingsError(
                "limits.cycle_wallclock_budget_minutes must be int >= 1",
                vault_dir=vault_dir,
                key="limits.cycle_wallclock_budget_minutes",
            )
        wall_min = wall_raw
    warn_at = 0.80
    if "cycle_budget_warn_at" in raw:
        warn_raw = raw.get("cycle_budget_warn_at")
        if isinstance(warn_raw, (int, float)) and 0 < float(warn_raw) <= 1:
            warn_at = float(warn_raw)
        else:
            raise SettingsError(
                "limits.cycle_budget_warn_at must be in (0, 1]",
                vault_dir=vault_dir,
                key="limits.cycle_budget_warn_at",
            )
    tier_thresholds: dict[str, float] = {}
    tt = raw.get("tier_thresholds")
    if isinstance(tt, dict):
        tier_thresholds = _float_map(
            tt, key="limits.tier_thresholds", vault_dir=vault_dir
        )
    calibration = dict(_DEFAULT_ESTIMATOR_CALIBRATION)
    ec = raw.get("estimator_calibration")
    if isinstance(ec, dict):
        calibration.update(
            _float_map(ec, key="limits.estimator_calibration", vault_dir=vault_dir)
        )
    return LimitsSettings(
        cycle_budget_usd=cycle_budget,
        codex_token_budget=codex_budget,
        cycle_wallclock_budget_minutes=wall_min,
        cycle_budget_warn_at=warn_at,
        tier_thresholds=tier_thresholds,
        estimator_calibration=calibration,
    )


def _float_map(raw: dict, *, key: str, vault_dir: Path) -> dict[str, float]:
    """``{name: float}``, or a ``SettingsError`` naming the entry that is not one.

    A bare ``float()`` here raised ``ValueError`` / ``TypeError``, which no
    caller that degrades on ``SettingsError`` catches (spec 076 FR-005).
    """
    out: dict[str, float] = {}
    for name, value in raw.items():
        try:
            out[str(name)] = float(value)
        except (TypeError, ValueError):
            raise SettingsError(
                f"{key}.{name} must be a number, got {value!r}",
                vault_dir=vault_dir,
                key=f"{key}.{name}",
            ) from None
    return out


def _parse_approval_gates(raw: object, *, vault_dir: Path) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise SettingsError(
            "approval_gates must be a list of stage names",
            vault_dir=vault_dir,
            key="approval_gates",
        )
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise SettingsError(
                "approval_gates entries must be strings",
                vault_dir=vault_dir,
                key="approval_gates",
            )
        out.append(item)
    return out


def _optional_positive_float(
    value: object, *, key: str, vault_dir: Path
) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise SettingsError(
            f"{key} must be a positive number, got {value!r}",
            vault_dir=vault_dir,
            key=key,
        )
    return float(value)


def _parse_default_agent(raw: object, *, vault_dir: Path) -> DefaultAgent:
    agent = str(raw) if raw is not None else "claude"
    if agent not in _VALID_AGENTS:
        raise SettingsError(
            "default_agent must be 'claude', 'codex', 'cursor-agent', "
            f"'ollama', or 'opencode', got {raw!r}",
            vault_dir=vault_dir,
            key="default_agent",
        )
    return agent  # type: ignore[return-value]


def _require_positive_int(
    value: object,
    *,
    key: str,
    vault_dir: Path,
    label: str,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SettingsError(
            f"{label}, got {value!r}",
            vault_dir=vault_dir,
            key=key,
        )
    return value


def _require_non_negative_number(
    value: object,
    *,
    key: str,
    vault_dir: Path,
) -> float:
    if isinstance(value, bool):
        raise SettingsError(
            f"budget_usd must be a non-negative number, got {value!r}",
            vault_dir=vault_dir,
            key=key,
        )
    if isinstance(value, (int, float)) and value >= 0:
        return float(value)
    raise SettingsError(
        f"budget_usd must be a non-negative number, got {value!r}",
        vault_dir=vault_dir,
        key=key,
    )
