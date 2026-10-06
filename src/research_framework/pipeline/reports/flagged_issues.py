"""Flagged Issues section builder (spec 040 FR-004)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from research_framework.pipeline.digest.scope import CycleScope, DateRange

_SEVERITY_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1, "warn": 1}


@dataclass(frozen=True)
class FlaggedIssue:
    stage: str
    identifier: str
    severity: str
    suggested_step: str


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _severity_rank(label: str) -> int:
    return _SEVERITY_ORDER.get(label.lower(), 0)


def _issues_from_extraction_summary(
    vault_dir: Path, cycle: CycleScope
) -> list[FlaggedIssue]:
    path = (
        vault_dir
        / "_pipeline"
        / "cycles"
        / f"cycle-{cycle.number:03d}-extraction-summary.json"
    )
    data = _load_json(path)
    if data is None:
        return []
    rows: list[FlaggedIssue] = []
    modules = data.get("modules")
    if not isinstance(modules, list):
        return rows
    for mod in modules:
        if not isinstance(mod, dict):
            continue
        preflight = mod.get("preflight")
        if not isinstance(preflight, dict):
            continue
        verdict = str(preflight.get("verdict") or "")
        if verdict not in {"fatal_fail", "warning"}:
            continue
        name = str(mod.get("name") or "unknown-module")
        messages = preflight.get("messages") or []
        detail = "; ".join(str(m) for m in messages) if messages else verdict
        severity = "high" if verdict == "fatal_fail" else "medium"
        rows.append(
            FlaggedIssue(
                stage="preflight",
                identifier=name,
                severity=severity,
                suggested_step=f"Review module preflight: {detail}",
            )
        )
    return rows


def _issues_from_quality_report(cycle: CycleScope) -> list[FlaggedIssue]:
    data = _load_json(cycle.quality_report_path)
    if data is None:
        return []
    rows: list[FlaggedIssue] = []
    rejected = int(data.get("notes_rejected") or 0)
    if rejected > 0:
        rows.append(
            FlaggedIssue(
                stage="verifier",
                identifier=f"cycle-{cycle.number:03d}",
                severity="medium",
                suggested_step=(
                    f"{rejected} note(s) rejected and not auto-recovered — "
                    "review rejected notes or rejects.json"
                ),
            )
        )
    retry_count = int(data.get("retry_count") or 0)
    aborted = bool(data.get("aborted"))
    if aborted and retry_count >= 2:
        reason = str(data.get("abort_reason") or "retry budget exhausted")
        rows.append(
            FlaggedIssue(
                stage="orchestrator",
                identifier=f"cycle-{cycle.number:03d}",
                severity="high",
                suggested_step=f"Retry exhaustion: {reason}",
            )
        )
    return rows


def _issues_from_rejects(vault_dir: Path) -> list[FlaggedIssue]:
    path = vault_dir / "_pipeline" / "rejects.json"
    data = _load_json(path)
    if data is None:
        return []
    rows: list[FlaggedIssue] = []
    for entry in data.get("rejects") or []:
        if not isinstance(entry, dict):
            continue
        try:
            count = int(entry.get("reject_count") or 0)
        except (TypeError, ValueError):
            continue
        if count < 2:
            continue
        name = str(entry.get("proposed_filename") or "unknown")
        rows.append(
            FlaggedIssue(
                stage="verifier",
                identifier=name,
                severity="high",
                suggested_step="Persistent verifier rejection — exclude or fix topic",
            )
        )
    return rows


def _issues_from_schema_drift(vault_dir: Path) -> list[FlaggedIssue]:
    root = vault_dir / "_pipeline" / "sources"
    if not root.is_dir():
        return []
    rows: list[FlaggedIssue] = []
    for mod_dir in sorted(root.iterdir()):
        if not mod_dir.is_dir():
            continue
        drift = mod_dir / "facts-schema.drift.md"
        if drift.is_file():
            rows.append(
                FlaggedIssue(
                    stage="schema_gen",
                    identifier=mod_dir.name,
                    severity="medium",
                    suggested_step="Acknowledge or merge facts-schema drift sidecar",
                )
            )
    return rows


def build_flagged_issues(
    vault_dir: Path,
    cycles: list[CycleScope],
    *,
    date_range: DateRange,
) -> list[dict[str, Any]]:
    del date_range
    rows: list[FlaggedIssue] = []
    for cycle in cycles:
        rows.extend(_issues_from_extraction_summary(vault_dir, cycle))
        rows.extend(_issues_from_quality_report(cycle))
    rows.extend(_issues_from_rejects(vault_dir))
    rows.extend(_issues_from_schema_drift(vault_dir))
    rows.sort(
        key=lambda row: (-_severity_rank(row.severity), row.stage, row.identifier)
    )
    return [
        {
            "stage": row.stage,
            "identifier": row.identifier,
            "severity": row.severity,
            "suggested_step": row.suggested_step,
        }
        for row in rows
    ]


__all__ = ["FlaggedIssue", "build_flagged_issues"]
