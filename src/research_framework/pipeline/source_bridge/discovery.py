"""Module discovery + trigger registry (FR-010)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

logger = logging.getLogger(__name__)

ValueTier = Literal["routine", "important", "critical"]
FailurePolicy = Literal["block_cycle", "degrade_gracefully", "defer"]
_VALID_FAILURE_POLICIES = frozenset({"block_cycle", "degrade_gracefully", "defer"})
_unlisted_warned: set[str] = set()


@dataclass
class TriggerEntry:
    module: str
    trigger_type: str
    pattern: str
    order: int


@dataclass
class TriggerRegistry:
    entries: list[TriggerEntry] = field(default_factory=list)

    def match(self, target: str) -> tuple[str, int] | None:
        """First-match-wins; returns ``(module, priority_order)``."""
        for entry in self.entries:
            if _matches(entry, target):
                return entry.module, entry.order
        return None


@dataclass
class AuthenticationBlock:
    env_vars: list[str] = field(default_factory=list)


@dataclass
class RateLimitsBlock:
    requests_per_minute: int | None = None
    requests_per_hour: int | None = None
    burst: str = "none"
    backoff: str = "exponential"


@dataclass
class ModuleManifest:
    name: str
    version: str
    description: str
    triggers: list[dict[str, Any]]
    entry_point: str
    default_value_tier: ValueTier
    schema_examples: str
    preflight: dict[str, Any] = field(default_factory=dict)
    default_tier: str | None = None
    source_id_from: dict[str, str] = field(default_factory=dict)
    user_owned: list[str] = field(default_factory=list)
    extraction_timeout_seconds: int = 600
    bridge_compat: dict[str, Any] | None = None
    authentication: AuthenticationBlock | None = None
    rate_limits: RateLimitsBlock | None = None
    failure_policy: FailurePolicy = "block_cycle"


def _parse_authentication(
    raw: dict[str, Any], path: Path
) -> AuthenticationBlock | None:
    auth_raw = raw.get("authentication")
    if auth_raw is None or auth_raw == "none":
        return None
    if not isinstance(auth_raw, dict):
        raise ValueError(f"authentication must be a mapping or 'none': {path}")
    env_vars_raw = auth_raw.get("env_vars") or []
    if not isinstance(env_vars_raw, list):
        raise ValueError(f"authentication.env_vars must be a list: {path}")
    env_vars = [str(v) for v in env_vars_raw if str(v)]
    if not env_vars:
        return None
    return AuthenticationBlock(env_vars=env_vars)


def _parse_rate_limits(raw: dict[str, Any], path: Path) -> RateLimitsBlock | None:
    limits_raw = raw.get("rate_limits")
    if limits_raw is None:
        return None
    if not isinstance(limits_raw, dict):
        raise ValueError(f"rate_limits must be a mapping: {path}")
    rpm = limits_raw.get("requests_per_minute")
    rph = limits_raw.get("requests_per_hour")
    burst = str(limits_raw.get("burst", "none"))
    backoff = str(limits_raw.get("backoff", "exponential"))
    if rpm is not None:
        rpm = int(rpm)
    if rph is not None:
        rph = int(rph)
    if rpm is None and rph is None and burst == "none" and backoff == "exponential":
        return None
    return RateLimitsBlock(
        requests_per_minute=rpm,
        requests_per_hour=rph,
        burst=burst,
        backoff=backoff,
    )


def _parse_failure_policy(raw: dict[str, Any], path: Path) -> FailurePolicy:
    policy = raw.get("failure_policy", "block_cycle")
    if policy not in _VALID_FAILURE_POLICIES:
        raise ValueError(
            f"unknown failure_policy {policy!r} — must be one of "
            f"{sorted(_VALID_FAILURE_POLICIES)}: {path}"
        )
    return policy  # type: ignore[return-value]


def parse_manifest(path: Path) -> ModuleManifest:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"manifest must be a mapping: {path}")
    name = str(raw["name"])
    # spec 051 FR4: every module MUST declare a preflight subprocess.
    preflight = raw.get("preflight")
    if not isinstance(preflight, dict) or not preflight.get("entry_point"):
        raise ValueError(
            "manifest missing required 'preflight' block — add preflight.py and "
            f"declare it (see modules/_template/): {path}"
        )
    preflight_entry = str(preflight["entry_point"])
    if not (path.parent / preflight_entry).is_file():
        raise ValueError(
            f"manifest preflight.entry_point {preflight_entry!r} does not exist in "
            f"{path.parent} (see modules/_template/): {path}"
        )
    return ModuleManifest(
        name=name,
        version=str(raw["version"]),
        description=str(raw["description"]),
        triggers=list(raw.get("triggers") or []),
        entry_point=str(raw["entry_point"]),
        default_value_tier=raw.get("default_value_tier", "routine"),  # type: ignore[arg-type]
        schema_examples=str(raw["schema_examples"]),
        preflight=dict(preflight),
        default_tier=raw.get("default_tier"),
        source_id_from=dict(raw.get("source_id_from") or {}),
        user_owned=list(raw.get("user_owned") or []),
        extraction_timeout_seconds=int(raw.get("extraction_timeout_seconds", 600)),
        bridge_compat=raw.get("bridge_compat"),
        authentication=_parse_authentication(raw, path),
        rate_limits=_parse_rate_limits(raw, path),
        failure_policy=_parse_failure_policy(raw, path),
    )


def walk_modules(vault_dir: Path) -> list[ModuleManifest]:
    """Filesystem walk of ``<vault>/modules/*/manifest.yaml``."""
    from .isolation import isolated_call

    modules_root = vault_dir / "modules"
    if not modules_root.is_dir():
        return []
    manifests: list[ModuleManifest] = []
    for manifest_path in sorted(modules_root.glob("*/manifest.yaml")):
        module_name = manifest_path.parent.name

        def _parse() -> ModuleManifest:
            return parse_manifest(manifest_path)

        parsed = isolated_call(
            _parse,
            vault_dir=vault_dir,
            module=module_name,
            source_id=module_name,
            kind="manifest",
        )
        if parsed is None:
            logger.warning(
                "Skipping module at %s after manifest parse failures", manifest_path
            )
            continue
        manifests.append(parsed)
    return manifests


def order_modules(
    manifests: list[ModuleManifest],
    listed_modules: list[str],
) -> list[ModuleManifest]:
    """FR-010: listed modules first, then unlisted lexicographic + WARN once."""
    by_name = {m.name: m for m in manifests}
    ordered: list[ModuleManifest] = []
    for name in listed_modules:
        if name in by_name:
            ordered.append(by_name.pop(name))
    for name in sorted(by_name):
        if name not in _unlisted_warned:
            logger.warning(
                "Module %r installed on disk but not in settings.yaml::modules — "
                "registered with lower precedence",
                name,
            )
            _unlisted_warned.add(name)
        ordered.append(by_name[name])
    return ordered


def build_trigger_registry(manifests: list[ModuleManifest]) -> TriggerRegistry:
    entries: list[TriggerEntry] = []
    order = 0
    for manifest in manifests:
        for trigger in manifest.triggers:
            order += 1
            entries.append(
                TriggerEntry(
                    module=manifest.name,
                    trigger_type=str(trigger.get("type", "")),
                    pattern=str(trigger.get("pattern", "")),
                    order=order,
                )
            )
    return TriggerRegistry(entries=entries)


def _matches(entry: TriggerEntry, target: str) -> bool:
    if entry.trigger_type == "url_pattern":
        return bool(re.search(entry.pattern, target))
    if entry.trigger_type == "path_pattern":
        return bool(re.search(entry.pattern, target))
    if entry.trigger_type == "path_exists":
        return Path(target).expanduser().exists()
    if entry.trigger_type == "domain":
        return entry.pattern in target
    return False


def reset_unlisted_warnings() -> None:
    """Test helper — clear FR-010 once-per-start WARN state."""
    _unlisted_warned.clear()
