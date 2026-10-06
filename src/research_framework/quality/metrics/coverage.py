"""Coverage metric family for the quality harness (spec 022 US2)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from research_framework.spec.simple import load as load_spec
from research_framework.vault.frontmatter import (
    FrontmatterParseError,
    parse_frontmatter,
)

from ..models import CycleOutput, Fixture
from ._helpers import (
    current_count,
    load_json,
    record_ratio,
    required_count,
    truncate_float,
)


def compute_coverage_metric(
    fixture: Fixture, cycle_outputs: list[CycleOutput]
) -> dict[str, Any]:
    """Return ``{coverage_pct, notes_per_category, spec_drift}`` for *fixture*."""
    # Prefer the live runtime snapshot under ``_pipeline/`` because the
    # cycle_runner mutates ``met_count`` there after every cycle. The root
    # ``coverage-targets.json`` is the immutable spec contract (hashed for
    # baseline integrity) and may lag behind the actual vault state.
    pipeline_targets = (
        fixture.coverage_targets_path.parent / "_pipeline" / "coverage-targets.json"
    )
    targets_source = (
        pipeline_targets
        if pipeline_targets.is_file()
        else fixture.coverage_targets_path
    )
    targets_doc = load_json(targets_source)
    categories = targets_doc.get("categories", [])
    if not isinstance(categories, list):
        categories = []

    # Filesystem ground truth: count actual notes per category in
    # ``data_vault/``. The cycle_runner only updates ``met_count`` via
    # ``orchestrator.update_after_cycle`` — direct ``run_cycle_steps``
    # invocations (e.g. from the quality harness) bypass that hook, so the
    # JSON's ``met_count`` can lag behind disk reality. Counting from
    # disk keeps the metric honest regardless of the entry point.
    vault_dir = fixture.coverage_targets_path.parent
    typed_counts = _notes_per_category_from_typed_results(cycle_outputs, categories)
    disk_counts = _count_notes_per_category_on_disk(vault_dir, categories)
    for name, count in typed_counts.items():
        disk_counts[name] = max(disk_counts.get(name, 0), count)

    met_ok = 0
    total = 0
    notes_per_category: dict[str, int] = {}
    for cat in categories:
        if not isinstance(cat, dict) or not cat.get("name"):
            continue
        name = str(cat["name"])
        required = required_count(cat)
        current_from_json = current_count(cat)
        current_from_disk = disk_counts.get(name, 0)
        # Disk wins when it's larger (the canonical post-cycle truth).
        current = max(current_from_json, current_from_disk)
        total += 1
        notes_per_category[name] = current
        if current >= required:
            met_ok += 1

    coverage_pct = truncate_float(met_ok / total) if total else 0.0

    snapshot = _latest_coverage_snapshot(cycle_outputs)
    if snapshot:
        # Snapshot is the authoritative per-cycle reading. It overrides
        # the targets JSON's static ``current`` field. Exception: when the
        # snapshot reports zero notes for a category but the disk has some
        # (the harness path skips ``orchestrator.update_after_cycle`` so
        # the snapshot can lag behind the data_vault), the disk count wins.
        for name, row in sorted(snapshot.items()):
            if not isinstance(row, dict) or "met" not in row:
                continue
            met_in_snapshot = int(row["met"])
            disk_for_this = disk_counts.get(name, 0)
            notes_per_category[name] = (
                disk_for_this
                if met_in_snapshot == 0 and disk_for_this > 0
                else met_in_snapshot
            )

    spec_names = _spec_category_names(fixture.spec_path)
    vault_names = set(notes_per_category.keys())
    if not vault_names and categories:
        vault_names = {
            str(c["name"]) for c in categories if isinstance(c, dict) and c.get("name")
        }

    out: dict[str, Any] = {
        "coverage_pct": coverage_pct,
        "notes_per_category": dict(sorted(notes_per_category.items())),
    }
    # A vault with no categories has no drift to measure; the previous
    # ``or 1`` denominator turned that into a confident 0.0 (issue #268).
    record_ratio(
        out,
        "spec_drift",
        len(vault_names - spec_names),
        len(vault_names),
        reason="no_coverage_categories",
    )
    return out


def _notes_per_category_from_typed_results(
    cycle_outputs: list[CycleOutput], categories: list[Any]
) -> dict[str, int]:
    """Count notes per category from ``ResearchResult.notes_written`` when present."""
    name_to_folders: dict[str, list[str]] = {}
    for cat in categories:
        if not isinstance(cat, dict) or not cat.get("name"):
            continue
        name = str(cat["name"])
        hints: list[str] = []
        folder_hint = str(cat.get("folder") or "").strip()
        if folder_hint:
            hints.append(folder_hint.lower())
        note_type = str(cat.get("note_type") or "").strip()
        if note_type:
            plural = note_type + "s" if not note_type.endswith("s") else note_type
            hints.append(plural.lower())
        name_to_folders[name] = hints

    counts: dict[str, int] = {name: 0 for name in name_to_folders}
    for cycle in sorted(cycle_outputs, key=lambda c: c.cycle_number):
        research = cycle.research_result
        if research is None or not research.notes_written:
            continue
        for path in research.notes_written:
            if not path.is_file():
                continue
            parts = [p.lower() for p in path.parts]
            for name, hints in name_to_folders.items():
                if any(h in part for part in parts for h in hints if h):
                    counts[name] = counts.get(name, 0) + 1
                    break
    return counts


def _count_notes_per_category_on_disk(
    vault_dir: Path, categories: list[Any]
) -> dict[str, int]:
    """Count ``.md`` files per category folder in ``{vault}/data_vault/``.

    Mapping rules (in order):
    1. Category ``folder:`` in the JSON (if present) — exact subdir match.
    2. Category ``note_type:`` mapped to scaffold folder naming
       ``NN - <Plural>`` (e.g. ``service`` → ``01 - Services``).
    3. Skipped if no mapping resolves to an existing folder.
    """
    out: dict[str, int] = {}
    data_vault = vault_dir / "data_vault"
    if not data_vault.is_dir():
        return out
    for cat in categories:
        if not isinstance(cat, dict) or not cat.get("name"):
            continue
        name = str(cat["name"])
        folder_hint = str(cat.get("folder") or "").strip()
        candidates: list[Path] = []
        if folder_hint:
            candidates.append(data_vault / folder_hint)
        note_type = str(cat.get("note_type") or "").strip()
        if note_type:
            plural = note_type + "s" if not note_type.endswith("s") else note_type
            # Production scaffold uses ``NN - Plural`` (e.g. ``01 - Services``).
            for sub in data_vault.iterdir():
                if not sub.is_dir():
                    continue
                lower = sub.name.lower()
                if lower.endswith(f"- {plural.lower()}") or lower.endswith(
                    f" {plural.lower()}"
                ):
                    candidates.append(sub)
        # De-duplicate while preserving order.
        seen: set[Path] = set()
        unique: list[Path] = []
        for c in candidates:
            if c not in seen:
                seen.add(c)
                unique.append(c)
        total = 0
        for c in unique:
            if c.is_dir():
                total += sum(1 for _ in c.rglob("*.md"))
        out[name] = total
    return out


def _latest_coverage_snapshot(cycle_outputs: list[CycleOutput]) -> dict[str, Any]:
    if not cycle_outputs:
        return {}
    ordered = sorted(cycle_outputs, key=lambda c: c.cycle_number)
    for cycle in reversed(ordered):
        doc = load_json(cycle.quality_report_path)
        snap = doc.get("coverage_snapshot")
        if isinstance(snap, dict) and snap:
            return snap
    return {}


def _spec_category_names(spec_path: Path) -> set[str]:
    if not spec_path.is_file():
        return set()
    try:
        spec = load_spec(spec_path, location=spec_path.parent)
    except (OSError, ValueError, TypeError):
        raw = load_json(spec_path) if spec_path.suffix == ".json" else {}
        if not raw:
            try:
                raw, _body = parse_frontmatter(spec_path)
            except (OSError, FrontmatterParseError):
                raw = {}
        ct = raw.get("coverage_targets") or {}
        cats = ct.get("categories") or []
        return {
            str(c.get("name", ""))
            for c in cats
            if isinstance(c, dict) and c.get("name")
        }
    return {c.name for c in spec.coverage_targets.categories if c.name}
