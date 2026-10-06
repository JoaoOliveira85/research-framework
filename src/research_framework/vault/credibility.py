"""Source credibility model — enum, resolver, and verifier shape checks (spec 055)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from research_framework.pipeline.source_authority import (
    SourceRoleIndex,
    build_source_role_index,
    normalise_source_id,
    resolve_role,
)
from research_framework.pipeline.source_bridge.discovery import walk_modules
from research_framework.pipeline.source_bridge.sources_loader import load_module_sources
from research_framework.spec.schema import SpecConfig

if TYPE_CHECKING:  # credibility_catalog imports Level from here — avoid a cycle.
    from research_framework.vault.credibility_catalog import ResolvedCatalog

_LOG = logging.getLogger(__name__)

__all__ = [
    "COMMENTARY",
    "CredibilityContext",
    "CredibilityUnresolved",
    "Level",
    "TIER2_LEVELS",
    "build_credibility_context",
    "citation_coi",
    "citation_credibility",
    "citation_url",
    "downgrade_one_step",
    "effective_level",
    "iter_source_url_entries",
    "min_rank",
    "off_field",
    "parse_level",
    "source_host",
    "validate_credibility_shape",
]


class Level(StrEnum):
    PRIMARY = "primary"
    CORROBORATED = "corroborated"
    COMMENTARY = "commentary"
    UNVETTED = "unvetted"

    @property
    def rank(self) -> int:
        return _LEVEL_RANKS[self]


_LEVEL_RANKS: dict[Level, int] = {
    Level.PRIMARY: 3,
    Level.CORROBORATED: 2,
    Level.COMMENTARY: 1,
    Level.UNVETTED: 0,
}

_RANK_TO_LEVEL: dict[int, Level] = {v: k for k, v in _LEVEL_RANKS.items()}

COMMENTARY = Level.COMMENTARY
TIER2_LEVELS = frozenset({Level.COMMENTARY, Level.UNVETTED})
_VALID_LEVEL_STRINGS = frozenset(level.value for level in Level)


class CredibilityUnresolved(Exception):
    """Raised when neither citation nor source default supplies a level (FR-001)."""

    def __init__(self, citation: object) -> None:
        self.citation = citation
        url = citation_url(citation) if isinstance(citation, dict) else str(citation)
        super().__init__(f"credibility unresolved for citation: {url!r}")


@dataclass
class CredibilityContext:
    """Frozen inputs for ``effective_level`` and shape validation."""

    role_index: SourceRoleIndex
    default_by_source_id: dict[str, str] = field(default_factory=dict)
    # spec 070 FR1: host → level, built from ``data_sources[].url`` on any source
    # declaring ``default_credibility``. This is the grounding path for a
    # ``kind: strategy_hint`` source, which by definition has no ``repos[]`` to
    # populate ``default_by_source_id``. Host-scoped, never a subdomain wildcard.
    default_by_source_host: dict[str, str] = field(default_factory=dict)
    default_by_role: dict[str, str] = field(default_factory=dict)
    authoritative_role_by_note_type: dict[str, str] = field(default_factory=dict)
    # spec 066: domain catalog (default + vault override) consulted after the
    # source-default lookup misses. ``None`` ⇒ no catalog (pre-066 behaviour).
    catalog: ResolvedCatalog | None = None

    @property
    def unknown_domain_policy(self) -> str:
        """``warn`` (default) | ``reject`` — the FR2 WARN/FAIL split (spec 066)."""
        return self.catalog.unknown_domain_policy if self.catalog else "warn"


def parse_level(value: str) -> Level:
    """Parse a declared level string; raises ``ValueError`` when invalid."""
    try:
        return Level(str(value).strip().lower())
    except ValueError as exc:
        raise ValueError(f"invalid credibility level: {value!r}") from exc


def min_rank(a: Level, b: Level) -> Level:
    """Return the lower-ranked of two levels (COI cap uses this)."""
    return a if a.rank <= b.rank else b


def downgrade_one_step(level: Level) -> Level:
    """One-step ordinal downgrade, floored at ``unvetted``."""
    return _RANK_TO_LEVEL.get(max(level.rank - 1, 0), Level.UNVETTED)


# A citation string may arrive carrying the classification tag the vault's own
# CLAUDE.md teaches ("[code]/[intent]/[domain]"), and/or a trailing " — Title,
# accessed <date>" tail. Both are presentation, not part of the URL. Rejecting
# such an entry as malformed cost a live vault 8 of 10 notes in one run
# (2026-09-09), so the parser strips them and grades the URL underneath.
_CITATION_TAG_RE = re.compile(r"^\[[a-z][a-z0-9_-]*\]\s+", re.IGNORECASE)


def citation_url(entry: object) -> str | None:
    if isinstance(entry, str):
        text = _CITATION_TAG_RE.sub("", entry.strip())
        # The URL is the first whitespace-delimited token; anything after it is
        # the human-readable tail. A tail-only string still returns its first
        # token, which then fails is_malformed_url exactly as it did before.
        return text.split()[0] if text.split() else None
    if isinstance(entry, dict):
        url = entry.get("url")
        return str(url).strip() if url else None
    return None


def citation_credibility(entry: object) -> str | None:
    if isinstance(entry, dict):
        value = entry.get("credibility")
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def citation_coi(entry: object) -> bool:
    if isinstance(entry, dict):
        return bool(entry.get("coi", False))
    return False


def iter_source_url_entries(frontmatter: dict[str, Any]) -> list[object]:
    entries = frontmatter.get("source_urls") or []
    if not isinstance(entries, list):
        return []
    return list(entries)


def _normalise_default(value: str, *, source_name: str) -> str | None:
    raw = (value or "").strip().lower()
    if not raw:
        return None
    if raw not in _VALID_LEVEL_STRINGS:
        _LOG.warning(
            "Ignoring invalid default_credibility=%r on source %r",
            value,
            source_name,
        )
        return None
    return raw


def _module_slug(name: str) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def source_host(value: str) -> str:
    """Return the lowercased host of a declared source locator, or ``""``.

    Spec 070 FR1. Declared ``data_sources[].url`` values are written by hand and
    arrive in every shape an operator might type — ``https://eng.alpha.example/``,
    ``https://eng.alpha.example``, ``eng.alpha.example``, mixed case. All of them must ground
    the same host, because the citations that need grounding carry deep paths
    (``https://eng.alpha.example/some-post``) and would never match an exact-string
    index.

    Deliberately host-only: a host with no dot is rejected so a bare filesystem
    path or a typo cannot ground anything.
    """
    raw = (value or "").strip()
    if not raw:
        return ""
    if "//" not in raw:
        # Bare host (`eng.alpha.example`) or host+path — urlparse needs a scheme to
        # populate netloc, so give it one.
        raw = f"https://{raw}"
    host = urlparse(raw).netloc.lower().split("@")[-1].split(":")[0]
    return host if "." in host else ""


def build_credibility_context(spec: SpecConfig, vault_dir: Path) -> CredibilityContext:
    """Build role + default-credibility indexes from spec declarations."""
    role_index = build_source_role_index(spec, vault_dir)
    defaults: dict[str, str] = {}
    host_defaults: dict[str, str] = {}
    slug_default: dict[str, str] = {}
    role_defaults: dict[str, set[str]] = {}

    for ds in getattr(spec, "data_sources", []) or []:
        default_raw = getattr(ds, "default_credibility", "") or ""
        default = _normalise_default(default_raw, source_name=getattr(ds, "name", ""))
        role = getattr(ds, "role", "") or ""
        if default and role:
            role_defaults.setdefault(str(role), set()).add(default)
        if default:
            slug = _module_slug(getattr(ds, "name", ""))
            if slug:
                slug_default.setdefault(slug, default)
            for repo in getattr(ds, "repos", []) or []:
                for key in (getattr(repo, "url", ""), getattr(repo, "local_path", "")):
                    norm = normalise_source_id(key)
                    if norm:
                        defaults.setdefault(norm, default)
            # spec 070 FR1 — the source's own locators ground their own hosts.
            # This is the ONLY grounding path a `kind: strategy_hint` source has,
            # since it carries no `repos[]` by definition.
            declared_urls = [getattr(ds, "url", "")]
            declared_urls.extend(getattr(ds, "urls", []) or [])
            for locator in declared_urls:
                host = source_host(locator)
                if host:
                    host_defaults.setdefault(host, default)

    if (vault_dir / "modules").is_dir():
        for manifest in walk_modules(vault_dir):
            module_default = slug_default.get(_module_slug(manifest.name))
            for src in load_module_sources(vault_dir, manifest.name, manifest):
                record_default = _normalise_default(
                    str(src.record.get("default_credibility", "") or ""),
                    source_name=f"{manifest.name}:{src.source_id}",
                )
                level = record_default or module_default
                if level:
                    norm = normalise_source_id(src.source_id)
                    if norm:
                        defaults.setdefault(norm, level)

    authoritative: dict[str, str] = {}
    for nt in getattr(spec, "note_types", []) or []:
        name = getattr(nt, "name", "")
        role = getattr(nt, "authoritative_role", "") or ""
        if name and role:
            authoritative[str(name)] = str(role)

    default_by_role = {
        role: next(iter(levels))
        for role, levels in role_defaults.items()
        if len(levels) == 1
    }

    return CredibilityContext(
        role_index=role_index,
        default_by_source_id=defaults,
        default_by_source_host=host_defaults,
        default_by_role=default_by_role,
        authoritative_role_by_note_type=authoritative,
        catalog=_load_catalog(vault_dir),
    )


def _load_catalog(vault_dir: Path) -> ResolvedCatalog:
    """Build the resolved catalog: shipped default overlaid by the vault override.

    Fail-closed — any settings/parse problem yields the default catalog under the
    permissive ``warn`` policy, never an exception (the verifier must not crash).
    """
    from research_framework.vault.credibility_catalog import build_resolved_catalog

    override: list[Any] = []
    policy = "warn"
    try:
        from research_framework.pipeline.settings import load_vault_settings

        cred = load_vault_settings(vault_dir).credibility
        override = list(cred.trusted_domains)
        policy = cred.unknown_domain_policy
    except Exception:  # pragma: no cover - advisory; default catalog is enough
        pass
    return build_resolved_catalog(override, unknown_domain_policy=policy)


def _lookup_default(citation: object, ctx: CredibilityContext) -> str | None:
    url = citation_url(citation)
    if not url:
        return None
    norm = normalise_source_id(url)
    explicit = ctx.default_by_source_id.get(norm)
    if explicit is not None:
        return explicit
    # spec 070 FR1: the declaring vault's own source default, keyed by host.
    # Consulted BEFORE the 066 catalog because `docs/source-credibility.md`
    # documents the order as "explicit citation → source default → FAIL": a
    # vault's declaration about its own sources is more specific than a global
    # domain catalog.
    if ctx.default_by_source_host:
        host = source_host(url)
        if host:
            declared = ctx.default_by_source_host.get(host)
            if declared is not None:
                return declared
    role = resolve_role(url, ctx.role_index)
    if role is not None:
        role_default = ctx.default_by_role.get(role)
        if role_default is not None:
            return role_default
    # spec 066: fall back to the domain catalog (override + default already
    # merged in ``ctx.catalog``). A catalog hit returns the 055 Level value.
    if ctx.catalog is not None:
        level = ctx.catalog.lookup(url)
        if level is not None:
            return level.value
    return None


def off_field(citation: object, note: dict[str, Any], ctx: CredibilityContext) -> bool:
    """True when citation role != note_type authoritative role (contract §3)."""
    url = citation_url(citation)
    if not url:
        return False
    role = resolve_role(url, ctx.role_index)
    if role is None:
        return False
    note_type = str(note.get("type", "") or "").strip()
    authoritative = ctx.authoritative_role_by_note_type.get(note_type)
    if not authoritative:
        return False
    return role != authoritative


def effective_level(
    citation: object,
    note: dict[str, Any],
    ctx: CredibilityContext,
) -> Level:
    """Deterministic credibility resolution (contract §4)."""
    declared_raw = citation_credibility(citation) or _lookup_default(citation, ctx)
    if not declared_raw:
        raise CredibilityUnresolved(citation)
    declared = parse_level(declared_raw)
    after_coi = min_rank(declared, COMMENTARY) if citation_coi(citation) else declared
    if off_field(citation, note, ctx):
        return downgrade_one_step(after_coi)
    return after_coi


def _coi_well_formed(entry: object) -> bool:
    if not isinstance(entry, dict) or "coi" not in entry:
        return True
    return isinstance(entry.get("coi"), bool)


def validate_credibility_shape(
    frontmatter: dict[str, Any],
    ctx: CredibilityContext,
    *,
    location: str,
) -> list[dict[str, str]]:
    """Return IX-credibility-* violations (shape only — contract §5)."""
    from research_framework.vault.credibility_catalog import is_malformed_url

    violations: list[dict[str, str]] = []
    # FR2: a catalog-miss well-formed URL is WARN by default, FAIL under reject.
    unresolved_severity = "fail" if ctx.unknown_domain_policy == "reject" else "warn"
    for entry in iter_source_url_entries(frontmatter):
        if not _coi_well_formed(entry):
            violations.append(
                {
                    "rule_id": "IX-credibility-malformed",
                    "location": location,
                    "message": "coi must be a boolean when present",
                    "severity": "fail",
                }
            )
            continue
        cred_raw = citation_credibility(entry)
        if cred_raw is not None and cred_raw.lower() not in _VALID_LEVEL_STRINGS:
            violations.append(
                {
                    "rule_id": "IX-credibility-malformed",
                    "location": location,
                    "message": f"credibility must be one of {sorted(_VALID_LEVEL_STRINGS)}",
                    "severity": "fail",
                }
            )
            continue
        try:
            effective_level(entry, frontmatter, ctx)
        except CredibilityUnresolved:
            url = citation_url(entry)
            # D2: a malformed citation URL (bad scheme / host has no dot) is a
            # distinct FAIL class, separate from the graded-but-ungraded case.
            if not url or is_malformed_url(url):
                violations.append(
                    {
                        "rule_id": "IX-citation-malformed",
                        "location": location,
                        "message": "citation url is malformed (bad scheme or host)",
                        "severity": "fail",
                    }
                )
            else:
                violations.append(
                    {
                        "rule_id": "IX-credibility-unresolved",
                        "location": location,
                        "message": "citation lacks credibility and no source default applies",
                        "severity": unresolved_severity,
                    }
                )
        except ValueError:
            violations.append(
                {
                    "rule_id": "IX-credibility-malformed",
                    "location": location,
                    "message": "credibility value is not a valid enum member",
                    "severity": "fail",
                }
            )
    return violations
