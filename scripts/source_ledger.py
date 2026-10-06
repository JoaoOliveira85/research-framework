"""Read-only Source-Consideration Ledger (spec 048 v2 — FR-017, FR-019, FR-020).

Joins existing pipeline artifacts into per-source verdicts without modifying
the pipeline. See specs/048-observability-v1/contracts/source-ledger-v2.contract.md.

FR-018 MCP blind spot: managed MCP sources may read as PIPELINE_DROP or
SKIPPED_RELEVANCE until spec 054 ships (contract §8). FR-021 health-header
surfacing is deferred.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from research_framework.pipeline.atomic_write import write_json, write_text
from research_framework.pipeline.cycle_summary import _aggregate_capture_failures
from research_framework.spec.parser import parse as parse_spec
from research_framework.spec.schema import DataSourceConfig, SpecValidationError
from research_framework.vault.frontmatter import (
    FrontmatterParseError,
    parse_frontmatter,
)

_LOG = logging.getLogger(__name__)

# Bumped 1.0 → 1.1 on 2026-06-03 (FR-022/FR-023/FR-024): additive ``read_via``
# / ``disagreement_was`` fields + the ``LEDGER_DISAGREEMENT`` terminal
# verdict. This is the only version a consumer may branch on (#297) — it is
# unrelated to this file's own "v2" scope-phase naming or the contract's.
SCHEMA_VERSION = "1.1"
KIND = "source-ledger"


class Verdict(StrEnum):
    USED = "USED"
    # Spec 048 v2.1 (FR-022): a non-USED verdict that contradicts a non-zero
    # note-citation rate — the ledger's blind spot, not a real source failure.
    LEDGER_DISAGREEMENT = "LEDGER_DISAGREEMENT"
    QUALITY_REJECT = "QUALITY_REJECT"
    ACCESS_FAIL = "ACCESS_FAIL"
    SKIPPED_RELEVANCE = "SKIPPED_RELEVANCE"
    PIPELINE_DROP = "PIPELINE_DROP"
    NOT_REACHED = "NOT_REACHED"


VERDICT_PRECEDENCE: list[Verdict] = [
    Verdict.USED,
    # Citation-evidenced; ranks just below USED (also "the source was used") so a
    # multi-cycle collapse never demotes it under a failure verdict.
    Verdict.LEDGER_DISAGREEMENT,
    Verdict.QUALITY_REJECT,
    Verdict.ACCESS_FAIL,
    Verdict.SKIPPED_RELEVANCE,
    Verdict.PIPELINE_DROP,
    Verdict.NOT_REACHED,
]

# read_via attribution literals (FR-024 / B3).
READ_VIA_DIRECT = "direct"
READ_VIA_MCP = "mcp"
READ_VIA_UNKNOWN = "unknown"

FAILURE_VERDICTS: frozenset[Verdict] = frozenset(
    {Verdict.ACCESS_FAIL, Verdict.PIPELINE_DROP, Verdict.QUALITY_REJECT}
)


@dataclass
class VerdictSignals:
    """Input bundle for the FR-020 verdict state machine (data-model-v2 Entity 2)."""

    notes_generated: int = 0
    notes_referencing: int = 0
    quality_rejected: bool = False
    fetch_attempted: bool = False
    fetch_outcome: str = "not_attempted"
    reason: str | None = None
    stage_ran: bool = False


@dataclass
class SourceLedgerEntry:
    """One per declared source per cycle (data-model-v2 Entity 1)."""

    name: str
    role: str
    required: bool
    priority: int
    declared: bool = True
    considered: bool = False
    fetch_attempted: bool = False
    fetch_outcome: str = "not_attempted"
    notes_generated: int = 0
    notes_referencing: int = 0
    reason: str | None = None
    verdict: Verdict = Verdict.NOT_REACHED
    evidence: dict[str, str] = field(default_factory=dict)
    # v2.1 amendment (B2/B3). ``hosts`` is the source's declared host set —
    # internal join key for citation reconciliation, not serialized.
    read_via: str = READ_VIA_UNKNOWN
    disagreement_was: str | None = None
    hosts: list[str] = field(default_factory=list)


@dataclass
class RunRollup:
    """Per-run aggregation (data-model-v2 Entity 3)."""

    vault: str
    cycles_covered: list[int]
    entries: list[SourceLedgerEntry]
    by_role: dict[str, dict[str, int]]
    required_failures: list[str]
    reconciled: bool = True


def resolve_verdict(signals: VerdictSignals) -> Verdict:
    """Pure FR-020 verdict state machine (contract §4 / data-model-v2 Entity 2)."""
    candidates: list[tuple[Verdict, bool]] = [
        (
            Verdict.USED,
            signals.notes_generated > 0 and signals.notes_referencing > 0,
        ),
        (
            Verdict.QUALITY_REJECT,
            signals.notes_generated > 0
            and signals.notes_referencing == 0
            and signals.quality_rejected,
        ),
        (
            Verdict.ACCESS_FAIL,
            signals.fetch_attempted and signals.fetch_outcome == "failed",
        ),
        (
            Verdict.SKIPPED_RELEVANCE,
            bool(signals.reason and signals.reason.strip()),
        ),
        (
            Verdict.PIPELINE_DROP,
            signals.notes_generated == 0
            and not (signals.reason and signals.reason.strip())
            and signals.stage_ran,
        ),
        (
            Verdict.NOT_REACHED,
            not signals.stage_ran,
        ),
    ]
    for verdict, matches in candidates:
        if matches:
            return verdict
    return Verdict.NOT_REACHED


def collapse_verdict(verdicts: list[Verdict]) -> Verdict:
    """Collapse per-cycle verdicts to the highest-precedence member (D2)."""
    if not verdicts:
        return Verdict.NOT_REACHED
    precedence = {verdict: index for index, verdict in enumerate(VERDICT_PRECEDENCE)}
    return min(verdicts, key=lambda verdict: precedence[verdict])


def load_declared_sources(vault: Path) -> list[DataSourceConfig]:
    """Load declared data sources from research.spec.md."""
    return parse_spec(vault / "research.spec.md").data_sources


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _LOG.warning("malformed JSON %s: %s", path, exc)
        return None
    return data if isinstance(data, dict) else None


def _cycles_dir(vault: Path) -> Path:
    return vault / "_pipeline" / "cycles"


def _cycle_ran(cycle_dir: Path, cycle: int) -> bool:
    """A cycle is reachable only when its scout artifact exists (D4 partial-run rule)."""
    return (cycle_dir / f"cycle-{cycle:03d}-scout.json").is_file()


def _normalise_scout_rows(raw: Any) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("name"):
                rows[str(item["name"])] = item
    elif isinstance(raw, dict):
        for name, item in raw.items():
            if isinstance(item, dict):
                row = dict(item)
                row.setdefault("name", name)
                rows[str(name)] = row
            else:
                rows[str(name)] = {"name": name, "searched": bool(item), "reason": ""}
    return rows


def _scout_signals(cycle_dir: Path, cycle: int) -> dict[str, dict[str, Any]]:
    doc = _read_json(cycle_dir / f"cycle-{cycle:03d}-scout.json")
    if not doc:
        return {}
    return _normalise_scout_rows(doc.get("sources_consulted"))


def _source_db_signals(vault: Path, cycle: int) -> dict[str, dict[str, int]]:
    db_path = vault / "_pipeline" / "sources.db"
    if not db_path.is_file():
        return {}
    out: dict[str, dict[str, int]] = {}
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT name, notes_generated, notes_referencing
            FROM source_cycles
            WHERE cycle = ?
            """,
            (cycle,),
        ).fetchall()
        conn.close()
    except sqlite3.Error as exc:
        _LOG.warning("sources.db read failed: %s", exc)
        return {}
    for row in rows:
        out[str(row["name"])] = {
            "notes_generated": int(row["notes_generated"] or 0),
            "notes_referencing": int(row["notes_referencing"] or 0),
        }
    return out


def _parse_incident_names(vault: Path) -> set[str]:
    path = vault / "_pipeline" / "source-incidents.md"
    if not path.is_file():
        return set()
    names: set[str] = set()
    for match in re.finditer(r"`([^`]+)` degraded:", path.read_text(encoding="utf-8")):
        names.add(match.group(1))
    return names


def _incident_signals(vault: Path) -> set[str]:
    return _parse_incident_names(vault)


def _source_urls(spec_sources: list[DataSourceConfig]) -> dict[str, set[str]]:
    hosts: dict[str, set[str]] = {}
    for ds in spec_sources:
        urls: set[str] = set()
        for repo in ds.repos:
            if repo.url:
                urls.add(repo.url)
        ds_url = getattr(ds, "url", "")
        if ds_url:
            urls.add(ds_url)
        host_set = {urlparse(u).netloc.lower() for u in urls if u}
        hosts[ds.name] = {h for h in host_set if h}
    return hosts


def _url_of(entry: object) -> str:
    """Extract the URL from a note ``source_urls`` entry (str or ``{url: …}``)."""
    if isinstance(entry, str):
        return entry.strip()
    if isinstance(entry, dict):
        return str(entry.get("url") or "").strip()
    return ""


def _iter_note_paths(vault: Path):
    """Yield every research note under ``<vault>/data_vault`` (skips indexes +
    templates), matching the canonical ``vault.indexer`` walk."""
    data_vault = vault / "data_vault"
    if not data_vault.is_dir():
        return
    for note in sorted(data_vault.rglob("*.md")):
        rel = note.relative_to(data_vault)
        if "_templates" in rel.parts:
            continue
        if note.name in ("_index.md", "_concepts.md", "_graph.md"):
            continue
        yield note


def _note_citation_hosts(vault: Path) -> dict[str, int]:
    """B1 (FR-023): the corpus of hosts the *notes actually cite*.

    Scans every ``data_vault`` note's ``source_urls`` frontmatter (the Principle-IX
    Tier-2 citation list the v2 ledger never read) and maps each URL to its host,
    returning ``host → citation_count``. This is the ground truth the v2 verdict
    machine was blind to — a source whose host appears here was demonstrably used,
    regardless of what the scout/sources.db join inferred.
    """
    hosts: dict[str, int] = {}
    for note in _iter_note_paths(vault):
        try:
            fm, _body = parse_frontmatter(note)
        except FrontmatterParseError as exc:
            _LOG.warning("skipping unparseable note %s: %s", note, exc)
            continue
        entries = fm.get("source_urls")
        if not isinstance(entries, list):
            continue
        for entry in entries:
            url = _url_of(entry)
            if not url:
                continue
            host = urlparse(url).netloc.lower()
            if host:
                hosts[host] = hosts.get(host, 0) + 1
    return hosts


def reconcile_against_citations(
    entries: list[SourceLedgerEntry], corpus: dict[str, int]
) -> list[SourceLedgerEntry]:
    """B2 (FR-022): relabel cited-but-failed verdicts as ``LEDGER_DISAGREEMENT``.

    A source whose declared host appears in the note-citation *corpus* can never
    honestly read as a 0-contribution failure (``ACCESS_FAIL`` / ``PIPELINE_DROP``
    / ``NOT_REACHED`` / ``QUALITY_REJECT`` / ``SKIPPED_RELEVANCE``). When the
    reported verdict contradicts citation evidence, the original verdict is
    preserved in ``disagreement_was`` and the reported ``verdict`` becomes
    ``LEDGER_DISAGREEMENT`` (spec Q1 — keep the join verdict, flag the mismatch).
    ``USED`` and already-reconciled rows are left untouched. Mutates in place and
    returns the same list for convenience.
    """
    if not corpus:
        return entries
    cited_hosts = set(corpus)
    for entry in entries:
        if entry.verdict in (Verdict.USED, Verdict.LEDGER_DISAGREEMENT):
            continue
        if not any(host in cited_hosts for host in entry.hosts):
            continue
        entry.disagreement_was = entry.verdict.value
        entry.verdict = Verdict.LEDGER_DISAGREEMENT
        entry.evidence["disagreement"] = "data_vault/**/source_urls"
    return entries


def _read_via(source: DataSourceConfig, signals: VerdictSignals) -> str:
    """B3 (FR-024): best-effort direct-vs-MCP attribution.

    A source declared ``access_method: mcp`` (or whose every repo is MCP) is read
    through a managed MCP server, not the raw_capture/sources.db direct path — so
    it must NOT be silently dropped to ``NOT_REACHED`` just because no direct fetch
    signal exists (the FR-018 blind spot). Direct fetch evidence (an attempt or a
    sources.db note) ⇒ ``direct``; otherwise an MCP declaration ⇒ ``mcp``; neither
    ⇒ ``unknown`` (never a false drop).
    """
    access = (getattr(source, "access_method", "") or "").lower()
    repo_access = {
        (getattr(r, "access_method", "") or "").lower() for r in source.repos
    }
    repo_access.discard("")
    mcp_only = access == "mcp" or (bool(repo_access) and repo_access <= {"mcp"})
    if mcp_only:
        return READ_VIA_MCP
    has_direct_signal = signals.fetch_attempted or signals.notes_generated > 0
    if has_direct_signal:
        return READ_VIA_DIRECT
    if access == "both" or "mcp" in repo_access:
        return READ_VIA_MCP
    return READ_VIA_UNKNOWN


def _capture_failure_signals(
    cycle_dir: Path,
    cycle: int,
    spec_sources: list[DataSourceConfig],
) -> dict[str, str]:
    doc = _read_json(cycle_dir / f"cycle-{cycle:03d}-research.json")
    if not doc:
        return {}
    groups = _aggregate_capture_failures(list(doc.get("capture_failures") or []))
    if not groups:
        return {}
    name_hosts = _source_urls(spec_sources)
    out: dict[str, str] = {}
    for ds in spec_sources:
        for group in groups:
            if group.host.lower() in name_hosts.get(ds.name, set()):
                out[ds.name] = group.reason
    return out


def _quality_signals(cycle_dir: Path, cycle: int) -> dict[str, bool]:
    doc = _read_json(cycle_dir / f"cycle-{cycle:03d}-quality-report.json")
    if not doc:
        return {}
    rejected: dict[str, bool] = {}
    gates = doc.get("gates") or {}
    items: list[tuple[str, Any]]
    if isinstance(gates, dict):
        items = list(gates.items())
    elif isinstance(gates, list):
        items = [(str(i), g) for i, g in enumerate(gates)]
    else:
        return {}
    for _key, gate in items:
        if not isinstance(gate, dict):
            continue
        if str(gate.get("status") or "").upper() != "FAIL":
            continue
        message = str(gate.get("message") or gate.get("detail") or "")
        for token in re.findall(r"`([^`]+)`", message):
            rejected[token] = True
        for token in re.findall(r"[A-Za-z][\w .-]{2,}", message):
            rejected.setdefault(token.strip(), True)
    return rejected


def _fuse_signals(
    *,
    source: DataSourceConfig,
    cycle: int,
    cycle_ran: bool,
    scout_row: dict[str, Any] | None,
    db_row: dict[str, int] | None,
    incident_names: set[str],
    capture_reason: str | None,
    quality_hits: dict[str, bool],
) -> tuple[VerdictSignals, dict[str, str], bool]:
    evidence: dict[str, str] = {}
    scout_name = f"cycle-{cycle:03d}-scout.json"
    notes_generated = int((db_row or {}).get("notes_generated", 0))
    notes_referencing = int((db_row or {}).get("notes_referencing", 0))
    if db_row is not None:
        evidence["notes_generated"] = "sources.db"
        evidence["notes_referencing"] = "sources.db"

    considered = bool((scout_row or {}).get("searched"))
    reason_raw = (scout_row or {}).get("reason")
    reason = str(reason_raw).strip() if reason_raw else None
    if scout_row is not None:
        evidence["considered"] = scout_name
        if reason:
            evidence["reason"] = scout_name

    fetch_attempted = notes_generated > 0
    fetch_outcome = "not_attempted"
    if cycle_ran:
        if source.name in incident_names:
            fetch_attempted = True
            fetch_outcome = "failed"
            evidence["fetch_outcome"] = "source-incidents.md"
        if capture_reason:
            fetch_attempted = True
            fetch_outcome = "failed"
            evidence["fetch_outcome"] = f"cycle-{cycle:03d}-research.json"
    if notes_generated > 0:
        fetch_attempted = True
        fetch_outcome = "ok"
        evidence["fetch_outcome"] = "sources.db"

    quality_rejected = bool(quality_hits.get(source.name))
    if quality_rejected:
        evidence["quality_rejected"] = f"cycle-{cycle:03d}-quality-report.json"

    if not cycle_ran:
        stage_ran = False
    elif scout_row is not None or db_row is not None or fetch_attempted:
        stage_ran = True
    else:
        stage_ran = True

    signals = VerdictSignals(
        notes_generated=notes_generated,
        notes_referencing=notes_referencing,
        quality_rejected=quality_rejected,
        fetch_attempted=fetch_attempted,
        fetch_outcome=fetch_outcome,
        reason=reason,
        stage_ran=stage_ran,
    )
    return signals, evidence, considered


def build_cycle_ledger(vault: Path, cycle: int) -> list[SourceLedgerEntry]:
    """Join read-only artifacts into per-source ledger entries for one cycle."""
    sources = load_declared_sources(vault)
    cycle_dir = _cycles_dir(vault)
    cycle_ran = _cycle_ran(cycle_dir, cycle)
    scout = _scout_signals(cycle_dir, cycle)
    db = _source_db_signals(vault, cycle)
    incidents = _incident_signals(vault)
    captures = _capture_failure_signals(cycle_dir, cycle, sources)
    quality = _quality_signals(cycle_dir, cycle)
    name_hosts = _source_urls(sources)

    entries: list[SourceLedgerEntry] = []
    for source in sources:
        scout_row = scout.get(source.name)
        db_row = db.get(source.name)
        signals, evidence, considered = _fuse_signals(
            source=source,
            cycle=cycle,
            cycle_ran=cycle_ran,
            scout_row=scout_row,
            db_row=db_row,
            incident_names=incidents,
            capture_reason=captures.get(source.name),
            quality_hits=quality,
        )
        verdict = resolve_verdict(signals)
        entry_reason = signals.reason if verdict == Verdict.SKIPPED_RELEVANCE else None
        entries.append(
            SourceLedgerEntry(
                name=source.name,
                role=source.role,
                required=source.required,
                priority=source.priority,
                considered=considered,
                fetch_attempted=signals.fetch_attempted,
                fetch_outcome=signals.fetch_outcome,
                notes_generated=signals.notes_generated,
                notes_referencing=signals.notes_referencing,
                reason=entry_reason,
                verdict=verdict,
                evidence=evidence,
                read_via=_read_via(source, signals),
                hosts=sorted(name_hosts.get(source.name, set())),
            )
        )
    # B2: relabel any cited-but-failed verdict against the note-citation corpus.
    reconcile_against_citations(entries, _note_citation_hosts(vault))
    entries.sort(key=lambda entry: (entry.priority, entry.name))
    return entries


def _entry_to_dict(entry: SourceLedgerEntry) -> dict[str, Any]:
    return {
        "name": entry.name,
        "role": entry.role,
        "required": entry.required,
        "priority": entry.priority,
        "declared": entry.declared,
        "considered": entry.considered,
        "fetch_attempted": entry.fetch_attempted,
        "fetch_outcome": entry.fetch_outcome,
        "notes_generated": entry.notes_generated,
        "notes_referencing": entry.notes_referencing,
        "reason": entry.reason,
        "verdict": entry.verdict.value,
        "read_via": entry.read_via,
        "disagreement_was": entry.disagreement_was,
        "evidence": dict(sorted(entry.evidence.items())),
    }


def _deterministic_generated_at(vault: Path, cycle: int) -> str:
    cycle_dir = _cycles_dir(vault)
    mtimes: list[float] = []
    for suffix in ("scout.json", "research.json", "quality-report.json"):
        path = cycle_dir / f"cycle-{cycle:03d}-{suffix}"
        if path.is_file():
            mtimes.append(path.stat().st_mtime)
    db_path = vault / "_pipeline" / "sources.db"
    if db_path.is_file():
        mtimes.append(db_path.stat().st_mtime)
    stamp = max(mtimes) if mtimes else 0.0
    return (
        datetime.fromtimestamp(stamp, UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _ledger_document(
    vault: Path, cycle: int, entries: list[SourceLedgerEntry], *, reconciled: bool
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "cycle": cycle,
        "vault": str(vault),
        "generated_at": _deterministic_generated_at(vault, cycle),
        "reconciled": reconciled,
        "entries": [_entry_to_dict(entry) for entry in entries],
    }


def write_cycle_ledger(
    vault: Path,
    cycle: int,
    entries: list[SourceLedgerEntry],
    *,
    reconciled: bool = True,
) -> Path:
    """Write cycle-NNN-source-ledger.json atomically."""
    cycle_dir = _cycles_dir(vault)
    cycle_dir.mkdir(parents=True, exist_ok=True)
    out_path = cycle_dir / f"cycle-{cycle:03d}-source-ledger.json"
    doc = _ledger_document(vault, cycle, entries, reconciled=reconciled)
    write_json(out_path, doc)
    return out_path


def _discovered_cycles(vault: Path) -> list[int]:
    cycle_dir = _cycles_dir(vault)
    if not cycle_dir.is_dir():
        return []
    cycles: set[int] = set()
    for path in cycle_dir.glob("cycle-*-*.json"):
        match = re.search(r"cycle-(\d+)-", path.name)
        if match:
            cycles.add(int(match.group(1)))
    return sorted(cycles)


def _raw_verdict(entry: SourceLedgerEntry) -> Verdict:
    """The pre-reconciliation join verdict (``disagreement_was`` when set)."""
    if entry.disagreement_was:
        return Verdict(entry.disagreement_was)
    return entry.verdict


def build_run_rollup(vault: Path, cycles: list[int]) -> RunRollup:
    """Collapse per-cycle ledgers into a run roll-up."""
    sources = load_declared_sources(vault)
    per_source: dict[str, list[Verdict]] = {ds.name: [] for ds in sources}
    latest_entry: dict[str, SourceLedgerEntry] = {}
    # B3: a source's read_via is stable across cycles; keep the first
    # non-"unknown" attribution seen.
    read_via_by_source: dict[str, str] = {}

    for cycle in cycles:
        entries = build_cycle_ledger(vault, cycle)
        write_cycle_ledger(vault, cycle, entries)
        for entry in entries:
            # Collapse over the RAW join verdict so LEDGER_DISAGREEMENT is
            # re-derived once, post-collapse, with a clean disagreement_was.
            per_source.setdefault(entry.name, []).append(_raw_verdict(entry))
            latest_entry[entry.name] = entry
            if read_via_by_source.get(entry.name, READ_VIA_UNKNOWN) == READ_VIA_UNKNOWN:
                read_via_by_source[entry.name] = entry.read_via

    name_hosts = _source_urls(sources)
    collapsed: list[SourceLedgerEntry] = []
    for source in sources:
        base = latest_entry.get(source.name)
        if base is None:
            base = SourceLedgerEntry(
                name=source.name,
                role=source.role,
                required=source.required,
                priority=source.priority,
            )
        verdict = collapse_verdict(per_source.get(source.name, []))
        collapsed.append(
            SourceLedgerEntry(
                name=base.name,
                role=base.role,
                required=base.required,
                priority=base.priority,
                declared=base.declared,
                considered=base.considered,
                fetch_attempted=base.fetch_attempted,
                fetch_outcome=base.fetch_outcome,
                notes_generated=base.notes_generated,
                notes_referencing=base.notes_referencing,
                reason=base.reason if verdict == Verdict.SKIPPED_RELEVANCE else None,
                verdict=verdict,
                evidence=base.evidence,
                read_via=read_via_by_source.get(source.name, base.read_via),
                hosts=sorted(name_hosts.get(source.name, set())),
            )
        )
    # B2: re-derive LEDGER_DISAGREEMENT on the collapsed (raw-verdict) set so the
    # roll-up carries a clean disagreement_was.
    reconcile_against_citations(collapsed, _note_citation_hosts(vault))
    collapsed.sort(key=lambda entry: (entry.priority, entry.name))

    by_role: dict[str, dict[str, int]] = {}
    for entry in collapsed:
        role_bucket = by_role.setdefault(entry.role, {})
        role_bucket[entry.verdict.value] = role_bucket.get(entry.verdict.value, 0) + 1

    declared = {ds.name for ds in sources}
    emitted = {entry.name for entry in collapsed}
    reconciled = declared == emitted
    required_failures = [
        entry.name
        for entry in collapsed
        if entry.required and entry.verdict in FAILURE_VERDICTS
    ]
    return RunRollup(
        vault=str(vault),
        cycles_covered=list(cycles),
        entries=collapsed,
        by_role=by_role,
        required_failures=sorted(required_failures),
        reconciled=reconciled,
    )


def compute_exit_code(rollup: RunRollup) -> int:
    if not rollup.reconciled:
        return 2
    if rollup.required_failures:
        return 1
    return 0


def render_rollup_table(rollup: RunRollup) -> str:
    cycles = rollup.cycles_covered
    cycle_label = (
        f"{min(cycles)}-{max(cycles)}"
        if len(cycles) > 1
        else str(cycles[0] if cycles else "?")
    )
    lines = [
        "# Source-Consideration Ledger — run roll-up",
        f"Vault: {rollup.vault}   Cycles: {cycle_label}   Reconciled: "
        f"{'yes' if rollup.reconciled else 'no'}",
        "",
        "| Source | Role | Req | Verdict | notes(gen/cited) | Reason |",
        "|--------|------|-----|---------|------------------|--------|",
    ]
    for entry in rollup.entries:
        req = "yes" if entry.required else "no"
        reason = entry.reason or ""
        lines.append(
            f"| {entry.name} | {entry.role} | {req} | {entry.verdict.value} | "
            f"{entry.notes_generated}/{entry.notes_referencing} | {reason} |"
        )
    lines.extend(["", "## By role", ""])
    for role, counts in sorted(rollup.by_role.items()):
        parts = ", ".join(
            f"{verdict}={count}" for verdict, count in sorted(counts.items())
        )
        lines.append(f"- **{role}**: {parts}")
    if rollup.required_failures:
        lines.extend(["", "## ⚠ Required-source failures (FR-019)", ""])
        for name in rollup.required_failures:
            entry = next(e for e in rollup.entries if e.name == name)
            lines.append(f"- `{name}` → {entry.verdict.value}")
    return "\n".join(lines) + "\n"


def render_rollup_json(rollup: RunRollup) -> str:
    payload = {
        "vault": rollup.vault,
        "cycles_covered": rollup.cycles_covered,
        "entries": [_entry_to_dict(entry) for entry in rollup.entries],
        "by_role": rollup.by_role,
        "required_failures": rollup.required_failures,
        "reconciled": rollup.reconciled,
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only Source-Consideration Ledger (spec 048 v2)",
    )
    parser.add_argument("--vault", required=True, help="Vault root path")
    parser.add_argument(
        "--cycle",
        type=int,
        help="Build ledger for a single cycle only",
    )
    parser.add_argument(
        "--write-rollup",
        action="store_true",
        help="Write _pipeline/source-ledger-run.md",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit run roll-up as JSON on stdout",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    vault = Path(args.vault).expanduser().resolve()
    spec_path = vault / "research.spec.md"
    if not spec_path.is_file():
        print(f"error: missing research.spec.md under {vault}", file=sys.stderr)
        return 2

    if args.cycle is not None:
        try:
            entries = build_cycle_ledger(vault, args.cycle)
        except SpecValidationError as exc:
            print(f"error: invalid research.spec.md: {exc}", file=sys.stderr)
            return 2
        declared = {ds.name for ds in load_declared_sources(vault)}
        emitted = {entry.name for entry in entries}
        reconciled = declared == emitted
        write_cycle_ledger(vault, args.cycle, entries, reconciled=reconciled)
        return 0 if reconciled else 2

    cycles = _discovered_cycles(vault)
    try:
        rollup = build_run_rollup(vault, cycles)
    except SpecValidationError as exc:
        print(f"error: invalid research.spec.md: {exc}", file=sys.stderr)
        return 2
    if not args.json:
        print(render_rollup_table(rollup), end="")
    else:
        print(render_rollup_json(rollup), end="")
    if args.write_rollup:
        out = vault / "_pipeline" / "source-ledger-run.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        write_text(out, render_rollup_table(rollup))
    return compute_exit_code(rollup)


if __name__ == "__main__":
    raise SystemExit(main())
