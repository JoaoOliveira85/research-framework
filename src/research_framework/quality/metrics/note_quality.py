"""Note quality metric family for the quality harness (spec 022 US2)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..models import CycleOutput, Fixture
from ._helpers import (
    ACRONYM_IN_TITLE,
    UNMEASURED_KEY,
    extract_headings,
    parse_frontmatter,
    record_ratio,
    resolve_template_path,
    truncate_float,
)


def compute_note_quality_metric(
    fixture: Fixture, cycle_outputs: list[CycleOutput]
) -> dict[str, Any]:
    """Return template compliance and acronym-link metrics for written notes."""
    note_paths = _unique_note_paths(cycle_outputs)
    if not note_paths:
        # No notes is not 0% compliant — it is nothing to grade (issue #268).
        return {
            "template_compliance_pct": None,
            "per_template_section_fill": {},
            "acronym_link_pct": None,
            UNMEASURED_KEY: {
                "template_compliance_pct": "no_notes_written",
                "acronym_link_pct": "no_notes_written",
            },
        }

    compliant = 0
    section_present: dict[str, int] = {}
    section_total: dict[str, int] = {}
    acronyms = _harvest_acronyms(note_paths)
    acronym_checks = 0
    acronym_linked = 0

    for path in note_paths:
        fm, body = parse_frontmatter(path)
        if fm is None:
            continue
        # Spec 062 FR3: alias/redirect stubs are graph-resolution nodes, not
        # research notes — exclude from spec-022 quality metrics.
        if str(fm.get("note_type", "") or "").strip().lower() == "alias":
            continue
        note_type = str(fm.get("type", "")).strip()
        if not note_type:
            continue
        tmpl_path = resolve_template_path(fixture.vault_dir, note_type)
        if tmpl_path is None:
            continue
        _tmpl_fm, tmpl_body = parse_frontmatter(tmpl_path)
        required = extract_headings(tmpl_body)
        present = set(extract_headings(body))
        missing = [h for h in required if h not in present]
        if not missing:
            compliant += 1
        for heading in required:
            section_total[heading] = section_total.get(heading, 0) + 1
            if heading in present:
                section_present[heading] = section_present.get(heading, 0) + 1

        stripped = _strip_excluded_regions(body)
        for acronym in acronyms:
            wikilinked = re.search(
                rf"\[\[{re.escape(acronym)}(?:\|[^\]]+)?\]\]",
                stripped,
            )
            bare = re.search(rf"(?<![\[\w]){re.escape(acronym)}(?![\]\w])", stripped)
            if bare is None:
                continue
            acronym_checks += 1
            if wikilinked is not None and wikilinked.start() <= bare.start():
                acronym_linked += 1

    out: dict[str, Any] = {
        "per_template_section_fill": {
            heading: truncate_float(
                section_present.get(heading, 0) / section_total[heading]
            )
            for heading in sorted(section_total)
        }
    }
    record_ratio(
        out,
        "template_compliance_pct",
        compliant,
        len(note_paths),
        reason="no_notes_written",
    )
    # Zero acronym occurrences is not "0% linked" — nothing was checked.
    record_ratio(
        out,
        "acronym_link_pct",
        acronym_linked,
        acronym_checks,
        reason="no_acronym_occurrences_in_notes",
    )
    return out


def _unique_note_paths(cycle_outputs: list[CycleOutput]) -> list[Path]:
    seen: set[Path] = set()
    ordered: list[Path] = []
    for cycle in sorted(cycle_outputs, key=lambda c: c.cycle_number):
        paths: list[Path] = []
        if cycle.research_result is not None and cycle.research_result.notes_written:
            paths = list(cycle.research_result.notes_written)
        elif cycle.notes_written:
            paths = list(cycle.notes_written)
        for path in paths:
            resolved = path.resolve()
            if resolved not in seen and resolved.is_file():
                seen.add(resolved)
                ordered.append(resolved)
    return ordered


def _harvest_acronyms(note_paths: list[Path]) -> set[str]:
    acronyms: set[str] = set()
    for path in note_paths:
        fm, _ = parse_frontmatter(path)
        if fm and fm.get("title"):
            for match in ACRONYM_IN_TITLE.findall(str(fm["title"])):
                acronyms.add(match)
    return acronyms


def _strip_excluded_regions(body: str) -> str:
    body = re.sub(r"```.*?```", "", body, flags=re.DOTALL)
    body = re.sub(r"`[^`]*`", "", body)
    body = re.sub(r"https?://\S+", "", body)
    body = re.sub(r"\([A-Z]{2,}\)", "", body)
    return body
