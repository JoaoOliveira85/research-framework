"""Deterministic `citation → role` resolution for the source-authority gates.

Spec 053 / D4: replace the regex URL-guessing in the grounding gate
(`scripts/check_code_source_coverage.py::classify_url`) with a deterministic
`citation → source_id → owning data_source → role` lookup, reusing the
spec-020 canonical attribution (`source_id`) and module enumeration.

Three ownership signals build the index — all LLM-free:

1. **Code repos (exact)** — each enumerated `data_source.repos[].url` and
   `.local_path` is a `source_id` owned by that data_source.
2. **Code repos (deep paths)** — a citation pointing *inside* a repo
   (`…/oehk-service/src/app.py`) resolves to the repo's role by
   **segment-containment** (mirrors `validate_cycle.py::_source_file_matches_repo`),
   preserving the pre-053 `^https://github.com/` / `^file://` behaviour without
   resurrecting URL regex.
3. **Module-backed sources** — each `<vault>/modules/<name>/sources.yaml`
   record's derived `source_id` inherits the role of the spec `data_source`
   whose name slugifies to the module dir name.

   *Assumption A1 (spec 053 has no explicit `module:` field on `data_sources`):*
   a module is "owned" by the spec data_source whose name slugifies to the
   module dir name (case-insensitive, non-alphanumerics dropped — "Reddit" →
   "reddit"). A module with no matching data_source contributes no entries
   (its citations resolve to ``None`` — the gate treats that as "not the
   authoritative role", the same outcome the old regex gave a non-code URL).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .source_bridge.discovery import walk_modules
from .source_bridge.sources_loader import load_module_sources

__all__ = [
    "SourceRoleIndex",
    "build_source_role_index",
    "derive_trunk_dict",
    "resolve_role",
    "normalise_source_id",
]


@dataclass
class SourceRoleIndex:
    """Resolved `source_id → role` lookup with repo deep-path fallback."""

    exact: dict[str, str] = field(default_factory=dict)
    # (path-segment signature, owning role) for code repos — matched by
    # contiguous-subsequence containment against a citation's segments.
    repo_signatures: list[tuple[tuple[str, ...], str]] = field(default_factory=list)


def normalise_source_id(value: str) -> str:
    """Canonicalise a citation / source_id for exact lookup.

    Trims whitespace and a single trailing slash so ``…/x`` and ``…/x/`` match.
    Case is preserved — URL paths and filesystem paths are case-significant.
    """
    return (value or "").strip().rstrip("/")


def _module_slug(name: str) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def _citation_segments(citation: str) -> list[str]:
    cleaned = citation.strip()
    for prefix in ("file://", "https://", "http://"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
            break
    return [s for s in cleaned.split("/") if s]


def _repo_signatures(repo: object) -> list[tuple[str, ...]]:
    """Path-segment tuples a citation may contain to belong to ``repo``.

    Mirrors `validate_cycle.py::_repo_match_signatures` (URL shape +
    local-path shape), kept here so the resolver has no dependency on the
    gate scripts.
    """
    sigs: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()

    def _add(sig: tuple[str, ...]) -> None:
        if len(sig) >= 2 and sig not in seen:
            sigs.append(sig)
            seen.add(sig)

    url = (getattr(repo, "url", "") or "").strip()
    local = (getattr(repo, "local_path", "") or "").strip()
    repo_name = (getattr(repo, "name", "") or "").strip()

    url_first_seg: str | None = None
    if url:
        stripped = url.removeprefix("https://github.com/").strip("/")
        url_segs = tuple(s for s in stripped.split("/") if s)
        _add(url_segs)
        if url_segs:
            url_first_seg = url_segs[0]

    if local:
        local_segs = [s for s in local.split("/") if s]
        anchor = url_first_seg or repo_name or None
        if anchor and anchor in local_segs:
            start = local_segs.index(anchor)
            _add(tuple(local_segs[start:]))
        elif repo_name and repo_name in local_segs:
            idx = local_segs.index(repo_name)
            if idx >= 1:
                _add(tuple(local_segs[idx - 1 : idx + 1]))

    return sigs


def build_source_role_index(spec: object, vault_dir: Path) -> SourceRoleIndex:
    """Return the `source_id → role` index for everything the spec attributes.

    See module docstring for the three ownership signals and Assumption A1.
    First write wins on a ``source_id`` collision.
    """
    index = SourceRoleIndex()
    data_sources = list(getattr(spec, "data_sources", []) or [])

    # Path 1+2 — code repos: exact url/local_path entries + deep-path signatures.
    for ds in data_sources:
        role = getattr(ds, "role", "")
        for repo in getattr(ds, "repos", []) or []:
            for key in (getattr(repo, "url", ""), getattr(repo, "local_path", "")):
                norm = normalise_source_id(key)
                if norm:
                    index.exact.setdefault(norm, role)
            for sig in _repo_signatures(repo):
                index.repo_signatures.append((sig, role))

    # Path 3 — module-backed sources (Assumption A1).
    role_by_slug: dict[str, str] = {}
    for ds in data_sources:
        slug = _module_slug(getattr(ds, "name", ""))
        if slug:
            role_by_slug.setdefault(slug, getattr(ds, "role", ""))
    if (vault_dir / "modules").is_dir():
        for manifest in walk_modules(vault_dir):
            role = role_by_slug.get(_module_slug(manifest.name))
            if role is None:
                continue
            for src in load_module_sources(vault_dir, manifest.name, manifest):
                norm = normalise_source_id(src.source_id)
                if norm:
                    index.exact.setdefault(norm, role)

    return index


def derive_trunk_dict(data_sources: list[dict]) -> dict | None:
    """Dict-native mirror of ``schema.derive_trunk`` for gate scripts that read
    ``spec-parse.json`` (a dict, not a reconstructed SpecConfig).

    Returns the data_source dict holding the UNIQUE minimum ``priority`` value,
    or ``None`` on a tie / no priority signal (spec 053 FR-002 / Analyze F3).
    Shared by the trunk-seed gate and the trunk-inversion gate so both derive
    the trunk identically (Analyze F2).
    """
    sources = [d for d in (data_sources or []) if isinstance(d, dict)]
    if not sources:
        return None
    min_priority = min(d.get("priority", 2) for d in sources)
    at_min = [d for d in sources if d.get("priority", 2) == min_priority]
    return at_min[0] if len(at_min) == 1 else None


def resolve_role(citation: str, index: SourceRoleIndex) -> str | None:
    """Return the role owning ``citation``, or ``None`` if unattributable.

    Exact `source_id` match first, then repo deep-path segment-containment.
    """
    exact = index.exact.get(normalise_source_id(citation))
    if exact is not None:
        return exact
    if index.repo_signatures:
        segs = _citation_segments(citation)
        for sig, role in index.repo_signatures:
            n = len(sig)
            if 0 < n <= len(segs):
                for i in range(len(segs) - n + 1):
                    if tuple(segs[i : i + n]) == sig:
                        return role
    return None
