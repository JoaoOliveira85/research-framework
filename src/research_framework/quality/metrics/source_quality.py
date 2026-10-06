"""Source quality metric family for the quality harness (spec 030 / 055)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from research_framework.spec.parser import parse as parse_spec
from research_framework.vault.credibility import (
    TIER2_LEVELS,
    CredibilityContext,
    CredibilityUnresolved,
    build_credibility_context,
    effective_level,
    iter_source_url_entries,
)

from ..models import CycleOutput, Fixture
from ._helpers import load_json, parse_frontmatter, record_ratio, truncate_float


def _unique_note_paths(cycle_outputs: list[CycleOutput]) -> list[Path]:
    seen: set[Path] = set()
    ordered: list[Path] = []
    for cycle in cycle_outputs:
        for path in cycle.notes_written:
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            # notes_written may record a deduped target (e.g. "<slug>-2.md")
            # that the note-writer collapsed onto an existing note and never
            # materialised on disk. The source-citation metrics can only read
            # notes that exist, so skip phantom paths instead of letting
            # parse_frontmatter raise FileNotFoundError on the missing file.
            if not path.is_file():
                continue
            ordered.append(path)
    return ordered


def _credibility_context(fixture: Fixture) -> CredibilityContext:
    spec = parse_spec(fixture.spec_path)
    return build_credibility_context(spec, fixture.vault_dir)


def _tier2_counts(
    fixture: Fixture,
    cycle_outputs: list[CycleOutput],
    ctx: CredibilityContext | None = None,
) -> tuple[int, int]:
    """``(tier2_citations, resolved_citations)`` across this run's notes."""
    context = ctx or _credibility_context(fixture)
    tier2_count = 0
    total = 0
    for path in _unique_note_paths(cycle_outputs):
        fm, _body = parse_frontmatter(path)
        if fm is None:
            continue
        for entry in iter_source_url_entries(fm):
            try:
                level = effective_level(entry, fm, context)
            except (CredibilityUnresolved, ValueError):
                continue
            total += 1
            if level in TIER2_LEVELS:
                tier2_count += 1
    return tier2_count, total


def compute_tier2_source_ratio(
    fixture: Fixture,
    cycle_outputs: list[CycleOutput],
    ctx: CredibilityContext | None = None,
) -> float:
    """Fraction of resolved Tier-2 citations at/below commentary (contract §6).

    Returns ``0.0`` when nothing resolved. Prefer the family calculator, which
    distinguishes that non-measurement from a real zero (issue #268); this
    signature is kept for the callers that want a plain float.
    """
    tier2_count, total = _tier2_counts(fixture, cycle_outputs, ctx)
    if total == 0:
        return 0.0
    return truncate_float(tier2_count / total)


def _source_diversity_shannon(
    fixture: Fixture, cycle_outputs: list[CycleOutput]
) -> float:
    """Shannon entropy of per-source citation counts (030 FR-001; stub until full 030)."""
    counts: dict[str, int] = {}
    for path in _unique_note_paths(cycle_outputs):
        fm, _body = parse_frontmatter(path)
        if fm is None:
            continue
        for entry in iter_source_url_entries(fm):
            if isinstance(entry, dict):
                key = str(entry.get("url", "") or "").strip()
            elif isinstance(entry, str):
                key = entry.strip()
            else:
                continue
            if not key:
                continue
            counts[key] = counts.get(key, 0) + 1
    if len(counts) <= 1:
        return 0.0
    total = sum(counts.values())
    entropy = 0.0
    for count in counts.values():
        p = count / total
        entropy -= p * math.log(p, 2)
    return truncate_float(entropy)


def _broken_source_rate(fixture: Fixture, cycle_outputs: list[CycleOutput]) -> float:
    """Preflight/access failure rate across declared sources (030 FR-001)."""
    del cycle_outputs
    preflight = load_json(fixture.vault_dir / "_pipeline" / "preflight.json")
    modules = preflight.get("modules") if isinstance(preflight, dict) else None
    if not isinstance(modules, list) or not modules:
        return 0.0
    failed = sum(
        1
        for row in modules
        if isinstance(row, dict)
        and str(row.get("verdict", "")).lower() in {"error", "fatal_fail"}
    )
    return truncate_float(failed / len(modules))


def _spec_source_utilization(
    fixture: Fixture, cycle_outputs: list[CycleOutput]
) -> float:
    """Share of declared spec sources consulted this run (030 FR-001)."""
    spec = parse_spec(fixture.spec_path)
    declared = len(getattr(spec, "data_sources", []) or [])
    if declared == 0:
        return 0.0
    consulted: set[str] = set()
    for cycle in cycle_outputs:
        scout = load_json(
            fixture.vault_dir
            / "_pipeline"
            / "cycles"
            / f"cycle-{cycle.cycle_number:03d}-scout.json"
        )
        rows = scout.get("sources_consulted") if isinstance(scout, dict) else None
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and row.get("source"):
                    consulted.add(str(row["source"]))
    unused = max(declared - len(consulted), 0)
    return truncate_float((declared - unused) / declared)


def compute_source_quality_metric(
    fixture: Fixture, cycle_outputs: list[CycleOutput]
) -> dict[str, Any]:
    """Return the four spec-030 source_quality metrics for *fixture*."""
    out: dict[str, Any] = {
        "source_diversity_shannon": _source_diversity_shannon(fixture, cycle_outputs),
        "broken_source_rate": _broken_source_rate(fixture, cycle_outputs),
        "spec_source_utilization": _spec_source_utilization(fixture, cycle_outputs),
    }
    # No citation whose credibility resolves is not "0% Tier-2" — the gate has
    # nothing to grade. On the committed fixtures every synthetic citation
    # raises CredibilityUnresolved, so this metric has never once measured.
    tier2_count, resolved = _tier2_counts(fixture, cycle_outputs)
    record_ratio(
        out,
        "tier2_source_ratio",
        tier2_count,
        resolved,
        reason="no_citation_with_resolvable_credibility",
    )
    return out
