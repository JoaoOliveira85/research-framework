"""Credibility domain catalog + vault override + resolution (spec 066).

Extends — does not replace — the spec-055 credibility model. The catalog maps
canonical citation domains to the spec-055 :class:`~research_framework.vault.credibility.Level`
enum so honest project-canonical citations (`fastify.dev`, `github.com/org/repo`,
`wikipedia.org`) stop reaching the verifier as "no source default applies" (the
rc7 100%-reject trap, #153).

Both the shipped default catalog (``data/credibility_catalog.yaml``) and the
FR3 vault override (``settings.yaml::credibility.trusted_domains``) parse into the
same :class:`Entry` shape, so the Q11 "override fully replaces default" rule is a
host-keyed overlay. Everything here is a pure function of recorded data + shipped
files — no LLM judgement at gate time (Principle IV).

See ``specs/066-credibility-model-calibration/contracts/credibility-catalog.contract.md``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from .credibility import Level

_LOG = logging.getLogger(__name__)

__all__ = [
    "ResolvedCatalog",
    "TIER_TO_LEVEL",
    "default_catalog_path",
    "load_default_catalog",
    "build_resolved_catalog",
    "is_malformed_url",
]

# Operator-facing tier → spec-055 Level (contract §1 / data-model D0).
TIER_TO_LEVEL: dict[str, Level] = {
    "tier_1": Level.PRIMARY,
    "tier_2": Level.CORROBORATED,
    "tier_3": Level.COMMENTARY,
}

_DEFAULT_MIN_SEGMENTS = 2


@dataclass(frozen=True)
class ResolvedCatalog:
    """In-memory resolved catalog (data-model Entity 3).

    ``exact`` maps a host to its level; ``suffix`` holds ``(".dev", level)`` pairs
    sorted longest-first; ``host_path`` holds ``(host, min_segments, level)``.
    """

    exact: dict[str, Level]
    suffix: tuple[tuple[str, Level], ...]
    host_path: tuple[tuple[str, int, Level], ...]
    unknown_domain_policy: str = "warn"

    def lookup(self, url: str) -> Level | None:
        """Return the catalog ``Level`` for ``url``'s host, or ``None`` (ungraded).

        A malformed host (no dot) returns ``None``; callers distinguish that case
        via :func:`is_malformed_url`. Precedence: exact → host_path → host_suffix.
        """
        host = _host_of(url)
        if not host or "." not in host:
            return None
        if host in self.exact:
            return self.exact[host]
        path_segments = [s for s in urlparse(url).path.split("/") if s]
        for entry_host, min_segments, level in self.host_path:
            if host == entry_host and len(path_segments) >= min_segments:
                return level
        for suffix, level in self.suffix:
            if host.endswith(suffix):
                return level
        return None


def _host_of(url: str) -> str:
    netloc = urlparse((url or "").strip()).netloc.lower()
    return netloc.split("@")[-1].split(":")[0]


def is_malformed_url(url: str) -> bool:
    """A citation URL is malformed when scheme ∉ {http,https} or host has no dot."""
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https"):
        return True
    return "." not in _host_of(url)


def default_catalog_path() -> Path:
    # research_framework/vault/credibility_catalog.py → parents[1] == research_framework/
    return Path(__file__).resolve().parents[1] / "data" / "credibility_catalog.yaml"


def _coerce_entry(
    raw: object, *, source: str, is_default: bool
) -> tuple[str, str, Level] | tuple[str, int, Level] | None:
    """Validate one entry; returns a typed tuple keyed by match_type, or ``None``.

    Fail-closed: a bad entry is dropped with a WARN, never an exception
    (contract §2). Returns one of:
      ("exact", host, level) | ("suffix", suffix_without_star, level)
      | ("host_path", host, min_segments, level)
    """
    if not isinstance(raw, dict):
        _LOG.warning(
            "credibility catalog (%s): dropping non-dict entry %r", source, raw
        )
        return None
    domain = str(raw.get("domain") or "").strip().lower()
    if not domain:
        _LOG.warning(
            "credibility catalog (%s): dropping entry with empty domain", source
        )
        return None
    tier = str(raw.get("tier") or "").strip().lower()
    level = TIER_TO_LEVEL.get(tier)
    if level is None:
        _LOG.warning(
            "credibility catalog (%s): dropping %r — bad tier %r", source, domain, tier
        )
        return None
    match_type = str(raw.get("match_type") or "exact").strip().lower()
    if match_type == "host_suffix":
        # Q6: default-catalog wildcards are tier_3-only; override may use any tier.
        if is_default and level is not Level.COMMENTARY:
            _LOG.warning(
                "credibility catalog (default): dropping wildcard %r at %s "
                "(default-catalog wildcards must be tier_3)",
                domain,
                tier,
            )
            return None
        suffix = domain.lstrip("*")
        if not suffix.startswith("."):
            suffix = "." + suffix.lstrip(".")
        return ("suffix", suffix, level)
    if match_type == "host_path":
        try:
            min_segments = int(raw.get("min_segments", _DEFAULT_MIN_SEGMENTS))
        except (TypeError, ValueError):
            min_segments = _DEFAULT_MIN_SEGMENTS
        return ("host_path", domain, max(0, min_segments), level)
    # default / "exact"
    return ("exact", domain, level)


def _hosts_touched(entries: list[Any]) -> set[str]:
    """The exact/host_path host keys an override speaks to (for Q11 replacement)."""
    hosts: set[str] = set()
    for raw in entries:
        if not isinstance(raw, dict):
            continue
        domain = str(raw.get("domain") or "").strip().lower()
        match_type = str(raw.get("match_type") or "exact").strip().lower()
        if domain and match_type in ("exact", "host_path"):
            hosts.add(domain)
    return hosts


def _suffixes_touched(entries: list[Any]) -> set[str]:
    suffixes: set[str] = set()
    for raw in entries:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("match_type") or "").strip().lower() != "host_suffix":
            continue
        domain = str(raw.get("domain") or "").strip().lower()
        if domain:
            suffix = domain.lstrip("*")
            suffixes.add(suffix if suffix.startswith(".") else "." + suffix.lstrip("."))
    return suffixes


def _build(
    default_entries: list[Any],
    override_entries: list[Any],
    policy: str,
) -> ResolvedCatalog:
    exact: dict[str, Level] = {}
    suffix: list[tuple[str, Level]] = []
    host_path: list[tuple[str, int, Level]] = []

    # Q11: an override host/suffix silently replaces the matching default entry.
    override_hosts = _hosts_touched(override_entries)
    override_suffixes = _suffixes_touched(override_entries)

    def _ingest(entries: list[Any], *, is_default: bool) -> None:
        for raw in entries:
            coerced = _coerce_entry(
                raw,
                source="default" if is_default else "override",
                is_default=is_default,
            )
            if coerced is None:
                continue
            kind = coerced[0]
            if kind == "exact":
                _, host, level = coerced
                if is_default and host in override_hosts:
                    continue
                exact[host] = level
            elif kind == "host_path":
                _, host, min_segments, level = coerced
                if is_default and host in override_hosts:
                    continue
                host_path.append((host, min_segments, level))
            else:  # suffix
                _, sfx, level = coerced
                if is_default and sfx in override_suffixes:
                    continue
                suffix.append((sfx, level))

    _ingest(default_entries, is_default=True)
    _ingest(override_entries, is_default=False)

    suffix.sort(key=lambda pair: len(pair[0]), reverse=True)
    return ResolvedCatalog(
        exact=exact,
        suffix=tuple(suffix),
        host_path=tuple(host_path),
        unknown_domain_policy=(policy or "warn").strip().lower(),
    )


def _read_entries(path: Path) -> list[Any]:
    if not path.is_file():
        return []
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        _LOG.warning("credibility catalog: unreadable %s: %s", path, exc)
        return []
    if not isinstance(doc, dict):
        return []
    entries = doc.get("entries")
    return list(entries) if isinstance(entries, list) else []


def load_default_catalog() -> ResolvedCatalog:
    """Load the shipped default catalog (no override). Fail-closed → empty."""
    return _build(_read_entries(default_catalog_path()), [], "warn")


def build_resolved_catalog(
    override_entries: list[Any] | None = None,
    *,
    unknown_domain_policy: str = "warn",
) -> ResolvedCatalog:
    """Build the resolved catalog: shipped default overlaid by the vault override.

    ``override_entries`` is the parsed ``settings.yaml::credibility.trusted_domains``
    list (Entity 1 dicts). A missing/corrupt default file yields an
    override-only catalog (everything else ungraded) — never an exception.
    """
    return _build(
        _read_entries(default_catalog_path()),
        list(override_entries or []),
        unknown_domain_policy,
    )
