"""Claims export — the vault→consumer distillation as a versioned contract (#189).

Before this module, a downstream consumer (``consumer_pipeline``'s
``pipeline/vault_import.py`` is the reference prototype) walked
``data_vault/**/*.md`` from outside the framework, re-implemented the
frontmatter conventions by hand, and guessed which files were plumbing. Every
consumer paid that cost again, and a note-format change broke all of them at
once without anything in the payload saying so (constitution F9).

This module produces the one record the framework can vouch for: one claim per
qualifying note, the plumbing skipped by the framework's OWN rules — the
verifier's exemption rule (``processors.verify._is_exempt``), the indexer's
scaffold rule, the canonical frontmatter codec — and credibility resolved the
way the verifier resolves it (``vault.credibility.effective_level``: explicit
citation → source default → catalog, COI capped, off-field downgraded).
Consumers keep only what is genuinely theirs: mapping ``note_type`` onto their
own taxonomy.

The envelope follows ADR-0013: it carries ``schema_version`` as a safeguard,
evolves append-only within a major (a ``1.0`` consumer accepts every ``1.x``
payload; unknown fields are ignored), and its schema —
``tests/contracts/claims-export-1.0.schema.json`` — is the contract the
producer conforms to, pinned against real output by
``tests/contracts/test_claims_export_schema.py``.

Read-only by construction (constitution Principle XII): nothing here writes
into the vault, and a malformed note is a counted warning, never a failure —
one broken file must not take the whole distillation away from a consumer.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from research_framework import __version__
from research_framework.processors.verify import _is_exempt
from research_framework.spec.schema import SpecConfig
from research_framework.vault.corpus import corpus_dir_name, existing_corpus_dir
from research_framework.vault.credibility import (
    CredibilityContext,
    CredibilityUnresolved,
    build_credibility_context,
    citation_coi,
    citation_credibility,
    citation_url,
    effective_level,
    iter_source_url_entries,
)
from research_framework.vault.frontmatter import (
    FrontmatterParseError,
    parse_frontmatter,
)

_LOG = logging.getLogger(__name__)

__all__ = [
    "KIND",
    "SCHEMA_VERSION",
    "SKIP_REASONS",
    "ClaimsExportError",
    "export_claims",
    "render_claims_json",
]

#: ``<major>.<minor>``; bump MINOR for an additive change, MAJOR (and a new
#: schema file beside the old one) for anything else — ADR-0013 §2–§3.
SCHEMA_VERSION = "1.0"
KIND = "claims-export"

#: Every reason a scanned file can be left out, in the order they are tested.
#: All five keys are always present in ``counts.skipped`` (zero when unused),
#: so a consumer can rely on the shape rather than on ``.get``.
SKIP_REASONS: tuple[str, ...] = (
    "scaffold",
    "exempt",
    "malformed",
    "no_frontmatter",
    "missing_fields",
)

_INDEX_FILES = frozenset({"_index.md", "_concepts.md", "_graph.md"})
_QUARANTINE_REL = Path("_pipeline") / "quarantine"


class ClaimsExportError(Exception):
    """The directory is not something claims can be exported from."""


def export_claims(
    vault: Path,
    *,
    include_quarantined: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return the claims-export envelope for *vault* as a plain dict.

    Raises :class:`ClaimsExportError` when *vault* has no corpus folder (it is
    not a vault, or not one this build can read). Every other problem — a
    missing ``spec-parse.json``, a note that will not parse — degrades to a
    ``warnings[]`` entry so the consumer still gets every claim that IS
    readable.
    """
    vault = Path(vault).expanduser().resolve()
    corpus = existing_corpus_dir(vault)
    if corpus is None:
        raise ClaimsExportError(
            f"no corpus folder under {vault} (expected {corpus_dir_name(vault)!r}); "
            "this does not look like a vault"
        )

    warnings: list[str] = []
    spec = _load_spec(vault, warnings)
    ctx = _credibility_context(spec, vault, warnings)
    declared_types: list[str] | None = (
        sorted({nt.name for nt in spec.note_types if nt.name}) if spec else None
    )

    counts_skipped = {reason: 0 for reason in SKIP_REASONS}
    claims: list[dict[str, Any]] = []
    scanned = 0
    quarantined_count = 0

    roots: list[tuple[Path, Path, str, bool]] = [(corpus, corpus, "", False)]
    if include_quarantined:
        qdir = vault / _QUARANTINE_REL
        if qdir.is_dir():
            roots.append((qdir, qdir, "quarantine/", True))

    for root, id_base, id_prefix, quarantined in roots:
        for path in sorted(p for p in root.rglob("*.md") if p.is_file()):
            scanned += 1
            rel_vault = path.relative_to(vault).as_posix()
            rel_root = path.relative_to(id_base)
            if _is_scaffold(rel_root):
                counts_skipped["scaffold"] += 1
                continue
            try:
                fm, _body = parse_frontmatter(path)
            except FrontmatterParseError as exc:
                counts_skipped["malformed"] += 1
                warnings.append(f"{rel_vault}: malformed frontmatter ({exc})")
                continue
            if not fm:
                counts_skipped["no_frontmatter"] += 1
                continue
            if _is_exempt(fm):
                counts_skipped["exempt"] += 1
                continue
            note_type = _text(fm.get("type"))
            claim_text = _normalise_ws(_text(fm.get("summary")))
            if not note_type or not claim_text:
                counts_skipped["missing_fields"] += 1
                continue
            claims.append(
                _claim_record(
                    fm,
                    note_id=id_prefix + rel_root.with_suffix("").as_posix(),
                    note_path=rel_vault,
                    note_type=note_type,
                    claim_text=claim_text,
                    declared_types=declared_types,
                    quarantined=quarantined,
                    ctx=ctx,
                )
            )
            if quarantined:
                quarantined_count += 1

    claims.sort(key=lambda c: c["id"])
    stamp = now if now is not None else datetime.now(UTC)
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "generated_at": stamp.isoformat(),
        "generator": {"name": "research-framework", "version": str(__version__)},
        "vault": {
            "name": vault.name,
            "corpus_dir": corpus.name,
            "note_types": declared_types or [],
        },
        "counts": {
            "claims": len(claims),
            "quarantined": quarantined_count,
            "notes_scanned": scanned,
            "skipped": counts_skipped,
        },
        "warnings": warnings,
        "claims": claims,
    }


def render_claims_json(doc: dict[str, Any]) -> str:
    """The bytes a consumer parses — identical on stdout and in ``--out``."""
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _load_spec(vault: Path, warnings: list[str]) -> SpecConfig | None:
    parse_path = vault / "_pipeline" / "spec-parse.json"
    try:
        doc = json.loads(parse_path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            raise ValueError("not a JSON object")
        return SpecConfig.from_dict(doc)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        warnings.append(
            f"_pipeline/spec-parse.json unavailable ({exc}): note types are "
            "reported as undeclared and citation credibility stays unresolved"
        )
        return None


def _credibility_context(
    spec: SpecConfig | None, vault: Path, warnings: list[str]
) -> CredibilityContext | None:
    if spec is None:
        return None
    try:
        return build_credibility_context(spec, vault)
    except Exception as exc:  # advisory: a broken module manifest must not
        # take the export down; credibility is then unresolved everywhere.
        _LOG.warning("credibility context unavailable: %s", exc)
        warnings.append(f"credibility context unavailable ({exc})")
        return None


def _is_scaffold(rel: Path) -> bool:
    """The indexer's rule (``vault.indexer._is_note_path``) plus the
    generator's reserved ``_`` prefix: every file the generator owns inside
    the corpus root (``_index.md``, ``_templates/``, ``_overview.md`` …)
    starts with an underscore, and no note the note-writer emits does."""
    if rel.name in _INDEX_FILES:
        return True
    return any(part.startswith("_") for part in rel.parts)


def _claim_record(
    fm: dict[str, Any],
    *,
    note_id: str,
    note_path: str,
    note_type: str,
    claim_text: str,
    declared_types: list[str] | None,
    quarantined: bool,
    ctx: CredibilityContext | None,
) -> dict[str, Any]:
    sources = [
        src
        for src in (
            _source_record(entry, fm, ctx) for entry in iter_source_url_entries(fm)
        )
        if src is not None
    ]
    title = _text(fm.get("title")) or Path(note_id).name
    return {
        "id": note_id,
        "note_path": note_path,
        "title": title,
        "claim": claim_text,
        "note_type": note_type,
        "note_type_declared": (
            None if declared_types is None else note_type in declared_types
        ),
        "tags": _tags(fm.get("tags")),
        "verifier_status": _text(fm.get("verifier_status")) or None,
        "coverage_category": _text(fm.get("coverage_category")) or None,
        "template_version": _text(fm.get("template_version")) or None,
        "created": _text(fm.get("created")) or None,
        "updated": _text(fm.get("updated")) or None,
        "quarantined": quarantined,
        "support_count": len(sources),
        "sources": sources,
    }


def _source_record(
    entry: object, fm: dict[str, Any], ctx: CredibilityContext | None
) -> dict[str, Any] | None:
    url = citation_url(entry)
    if not url:
        return None
    declared = citation_credibility(entry)
    resolved: str | None = None
    if ctx is not None:
        try:
            resolved = effective_level(entry, fm, ctx).value
        except (CredibilityUnresolved, ValueError):
            resolved = None
    rich = entry if isinstance(entry, dict) else {}
    return {
        "url": url,
        "title": _text(rich.get("title")) or None,
        "accessed": _text(rich.get("accessed")) or None,
        "credibility_declared": declared,
        "credibility": resolved,
        "coi": citation_coi(entry),
    }


def _text(value: object) -> str:
    """Frontmatter scalar → string. YAML turns ``2026-09-01`` into a ``date``;
    the export hands it back as the ISO text the note author wrote."""
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value).strip()


def _normalise_ws(text: str) -> str:
    return " ".join(text.split())


def _tags(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_text(v) for v in value if _text(v)]
    text = _text(value)
    return [text] if text else []
