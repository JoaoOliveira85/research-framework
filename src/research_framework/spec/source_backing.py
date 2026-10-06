"""Declared-source backing resolution (spec 069 FR1/FR2).

A declared `data_source` is either:

- ``backed`` — its locator (a repo URL / local path) trigger-matches an installed
  module via the spec-020 ``TriggerRegistry``;
- ``strategy_hint`` — explicitly annotated ``kind: strategy_hint`` (an LLM-fetch
  guidance string, no module required);
- ``unbacked`` — neither: a scaffold-time error / preflight FAIL (the rc7 trap,
  where "Web" / "Official Documentation" / "Codebase Vault Seed" sources were
  declared but silently produced nothing).

The registry is built from the **available** framework modules (packaged under
``research_framework/modules``) plus any vault-local ``modules/`` — i.e. every
module that can back a source.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from ..pipeline.source_bridge.discovery import (
    ModuleManifest,
    TriggerRegistry,
    build_trigger_registry,
    parse_manifest,
)
from .schema import DataSourceConfig

Backing = Literal["backed", "strategy_hint", "unbacked"]

# Canonical extraction access methods — the exact handlers ``pipeline/preflight.py``
# (and the extraction layer) implement. A source declaring one of these has a
# real implementation path even when its locator doesn't match a spec-020 module
# trigger (e.g. a local working copy whose path isn't a ``.git/HEAD`` file, or a
# generic feed URL). The rc7 trap is the OPPOSITE: sources declared with
# *non-canonical* free-text access strings ("web fetch", "GitHub MCP", "local
# filesystem") that NO handler implements (spec 069 §Context). Those — and pure
# description-only sources — are ``unbacked`` unless annotated ``strategy_hint``.
_CANONICAL_ACCESS_METHODS = frozenset({"local", "github_pr", "web", "rss", "oreilly"})


def source_locator(source: DataSourceConfig) -> str | None:
    """The source's filesystem/URL locator (D2, locked U2).

    First non-empty of ``repos[].url``, ``repos[].local_path``, then the
    source-level ``local_path``. ``None`` ⇒ no locator ⇒ cannot trigger-match.
    """
    for repo in source.repos:
        if (repo.url or "").strip():
            return repo.url.strip()
    for repo in source.repos:
        if (repo.local_path or "").strip():
            return repo.local_path.strip()
    lp = (getattr(source, "local_path", "") or "").strip()
    return lp or None


def source_is_backed(source: DataSourceConfig, registry: TriggerRegistry) -> Backing:
    """Classify a declared source as backed / strategy_hint / unbacked (D2/D3).

    ``kind: strategy_hint`` short-circuits to ``strategy_hint``. Otherwise
    (``module_backed`` or absent ``kind``) the locator must trigger-match ≥1
    installed module; absent-``kind`` infers the same — there is no "ambiguous"
    state (U3).
    """
    if (source.kind or "").strip() == "strategy_hint":
        return "strategy_hint"
    locator = source_locator(source)
    if locator and registry.match(locator) is not None:
        return "backed"
    if (source.access_method or "").strip().lower() in _CANONICAL_ACCESS_METHODS:
        # A canonical access_method has a real preflight/extraction handler, so
        # the source is implemented even without a module-trigger match. Only
        # non-canonical access strings (the rc7 trap) and description-only
        # sources fall through to ``unbacked``.
        return "backed"
    return "unbacked"


def unbacked_message(name: str) -> str:
    """The canonical, source-named error message for an unbacked source (C1)."""
    return (
        f"source '{name}' declared but has no implementation — add a module whose "
        "manifest triggers match its locator, or annotate kind: strategy_hint"
    )


def _framework_modules_root() -> Path:
    # research_framework/modules — packaged source of installable modules.
    return Path(__file__).resolve().parents[1] / "modules"


def _walk_manifests(modules_root: Path) -> list[ModuleManifest]:
    if not modules_root.is_dir():
        return []
    manifests: list[ModuleManifest] = []
    for manifest_path in sorted(modules_root.glob("*/manifest.yaml")):
        if manifest_path.parent.name.startswith("_"):
            continue  # _template is a copy-me stub, not a real module
        try:
            manifests.append(parse_manifest(manifest_path))
        except Exception:
            continue
    return manifests


def build_available_registry(vault_dir: Path | None = None) -> TriggerRegistry:
    """Trigger registry over every module that can back a source.

    Packaged framework modules first (highest precedence), then any vault-local
    ``modules/`` (covers operator-authored modules that aren't shipped). Module
    names already present from the framework set are not duplicated.
    """
    manifests = _walk_manifests(_framework_modules_root())
    seen = {m.name for m in manifests}
    if vault_dir is not None:
        for m in _walk_manifests(Path(vault_dir) / "modules"):
            if m.name not in seen:
                manifests.append(m)
                seen.add(m.name)
    return build_trigger_registry(manifests)


__all__ = [
    "Backing",
    "build_available_registry",
    "source_is_backed",
    "source_locator",
    "unbacked_message",
]


CredibilityBinding = Literal["none", "bound", "unbindable"]


def credibility_binding(
    source: DataSourceConfig, registry: TriggerRegistry
) -> CredibilityBinding:
    """Can this source's ``default_credibility`` reach a citation? (spec 070 FR2)

    ``none``        — no ``default_credibility`` declared; nothing to check.
    ``bound``       — a key exists that ``build_credibility_context`` indexes.
    ``unbindable``  — a credibility claim with nothing to hang it on.

    F1's lesson was that inert configuration is worse than rejected
    configuration: a strategy-hint source declaring ``default_credibility:
    primary`` looked correct, was silently unused, and surfaced cycles later as
    quarantined notes whose message named a field the author *had* set. FR1 gave
    those sources a way to bind; this closes the loop by refusing the ones that
    still cannot.

    Keys mirror the order ``build_credibility_context`` indexes them, so this
    gate and the resolver cannot disagree:

    - ``repos[].url`` / ``repos[].local_path`` → exact source-id index
    - source-level ``local_path``              → same index
    - ``url`` / ``urls``                       → host index (FR1)
    - a module whose triggers match its locator → module source ids via the slug
    """
    if not (getattr(source, "default_credibility", "") or "").strip():
        return "none"

    for repo in source.repos:
        if (repo.url or "").strip() or (repo.local_path or "").strip():
            return "bound"
    if (getattr(source, "local_path", "") or "").strip():
        return "bound"

    # FR1 host binding — only a locator that yields a real host counts, since a
    # malformed one indexes nothing and would be just as inert.
    from research_framework.vault.credibility import source_host

    locators = [getattr(source, "url", "") or ""]
    locators.extend(getattr(source, "urls", []) or [])
    if any(source_host(loc) for loc in locators):
        return "bound"

    if source_is_backed(source, registry) == "backed":
        return "bound"
    return "unbindable"


def unbindable_credibility_message(name: str) -> str:
    """Canonical, source-named message for an unbindable credibility claim."""
    return (
        f"source '{name}' declares default_credibility but nothing can bind it "
        "to a citation — add `url:` (or `urls:`) naming the domain(s) it covers, "
        "give it `repos:`/`local_path:`, or remove `default_credibility` "
        "(spec 070 FR2)"
    )
