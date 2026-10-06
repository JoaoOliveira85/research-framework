"""Section builders for cross-cycle digest (spec 035)."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from research_framework.spec.simple import load as load_spec
from research_framework.vault.corpus import corpus_dir
from research_framework.vault.frontmatter import parse_frontmatter
from research_framework.vault.indexer import inbound_link_counts

from .ranker import (
    GapEntry,
    NoteScore,
    composite_score,
    coverage_progress,
    detect_gaps,
    rank_notes,
)
from .scope import (
    CycleScope,
    DateRange,
    DigestScope,
    _git_commit_date,
    resolve_ship_sha,
)

_INCIDENT_RE = re.compile(
    r"^-\s+(\S+)\s+—\s+`([^`]+)`\s+degraded:",
    re.MULTILINE,
)


@dataclass
class SectionModels:
    strongest_signals: list[NoteScore]
    gaps: list[GapEntry]
    new_notes_by_category: list[tuple[str, int, list[str]]]
    source_drift: list[dict[str, Any]]
    omit_source_drift_section: bool
    coverage_delta: list[tuple[str, float, float, float]]
    cost_summary: dict[str, Any]
    cycle_index: list[dict[str, Any]]
    footer_warnings: list[str]


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _wikilink(title: str) -> str:
    return f"[[{title}]]"


def _first_paragraph(body: str) -> str:
    for line in body.splitlines():
        text = line.strip()
        if text and not text.startswith("#"):
            return text
    return ""


def _note_first_written(fm: dict[str, Any], cycle_number: int) -> datetime:
    lifecycle = fm.get("lifecycle")
    if isinstance(lifecycle, dict):
        raw = lifecycle.get("first_written")
        if isinstance(raw, str) and raw.strip():
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                pass
    return datetime(2000 + cycle_number, 1, 1, tzinfo=UTC)


def _notes_in_range(
    vault_dir: Path, cycles: list[CycleScope]
) -> list[tuple[Path, dict[str, Any], str, int]]:
    cycle_nums = {c.number for c in cycles}
    data_vault = corpus_dir(vault_dir)
    if not data_vault.is_dir():
        return []
    rows: list[tuple[Path, dict[str, Any], str, int]] = []
    for note in sorted(data_vault.rglob("*.md")):
        if note.name.startswith("_"):
            continue
        try:
            fm, body = parse_frontmatter(note)
        except Exception:
            continue
        lifecycle = fm.get("lifecycle")
        created_cycle = None
        if isinstance(lifecycle, dict) and isinstance(
            lifecycle.get("created_at_cycle"), int
        ):
            created_cycle = lifecycle["created_at_cycle"]
        if created_cycle not in cycle_nums:
            continue
        rows.append((note, fm, body, created_cycle))
    return rows


def _load_coverage_targets(vault_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    for rel in (
        Path("coverage-targets.json"),
        Path("_pipeline") / "coverage-targets.json",
    ):
        path = vault_dir / rel
        if not path.is_file():
            continue
        data = _load_json(path)
        if not data or not isinstance(data.get("categories"), list):
            continue
        if "cycle_number" not in data:
            warnings.append(
                "[schema-migrated] coverage-targets.json missing cycle_number — "
                "best-effort parse"
            )
        return [c for c in data["categories"] if isinstance(c, dict)], warnings
    return [], warnings


def _referencing_deltas(vault_dir: Path, cycles: list[CycleScope]) -> dict[str, int]:
    db_path = vault_dir / "_pipeline" / "sources.db"
    if not db_path.is_file() or not cycles:
        return {}
    first, last = min(c.number for c in cycles), max(c.number for c in cycles)
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1.0)
    except sqlite3.Error:
        return {}
    try:
        deltas: dict[str, int] = {}
        for (name,) in conn.execute("SELECT name FROM sources"):
            s = conn.execute(
                "SELECT notes_referencing FROM source_cycles WHERE name=? AND cycle=?",
                (name, first),
            ).fetchone()
            e = conn.execute(
                "SELECT notes_referencing FROM source_cycles WHERE name=? AND cycle=?",
                (name, last),
            ).fetchone()
            deltas[str(name)] = (int(e[0]) if e else 0) - (int(s[0]) if s else 0)
        return deltas
    except sqlite3.Error:
        # No tables yet, or not a database: rank without deltas, as when
        # there is no sources.db.
        return {}
    finally:
        conn.close()


def _try_connect_sources_db(
    db_path: Path, *, wait_seconds: float = 5.0
) -> sqlite3.Connection | None:
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1.0)
        except sqlite3.OperationalError:
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.1)


def _decay_threshold(vault_dir: Path) -> int:
    settings_path = vault_dir / "settings.yaml"
    if settings_path.is_file():
        try:
            import yaml

            data = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                sm = data.get("source_manager") or {}
                if isinstance(sm, dict) and isinstance(
                    sm.get("decay_after_n_cycles"), int
                ):
                    return max(1, sm["decay_after_n_cycles"])
        except Exception:
            pass
    return 3


def build_source_drift(
    vault_dir: Path,
    cycles: list[CycleScope],
    date_range: DateRange,
) -> tuple[list[dict[str, Any]], list[str], bool]:
    warnings: list[str] = []
    db_path = vault_dir / "_pipeline" / "sources.db"
    if not db_path.is_file() or not cycles:
        return [], warnings, False

    conn = _try_connect_sources_db(db_path)
    if conn is None:
        warnings.append("sources.db locked — Source Quality Drift omitted")
        return [], warnings, True

    numbers = sorted(c.number for c in cycles)
    first, last = numbers[0], numbers[-1]
    threshold = _decay_threshold(vault_dir)
    degraded: set[str] = set()
    inc_path = vault_dir / "_pipeline" / "source-incidents.md"
    if inc_path.is_file():
        for match in _INCIDENT_RE.finditer(inc_path.read_text(encoding="utf-8")):
            ts_raw, name = match.group(1), match.group(2)
            try:
                day = (
                    datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                    .astimezone(UTC)
                    .date()
                )
            except ValueError:
                continue
            if date_range.start <= day <= date_range.end:
                degraded.add(name)

    rows_out: list[dict[str, Any]] = []
    try:
        for (name,) in conn.execute("SELECT name FROM sources ORDER BY name"):
            start_gen = conn.execute(
                "SELECT notes_generated FROM source_cycles WHERE name=? AND cycle=?",
                (name, first),
            ).fetchone()
            end_gen = conn.execute(
                "SELECT notes_generated FROM source_cycles WHERE name=? AND cycle=?",
                (name, last),
            ).fetchone()
            start_ref = conn.execute(
                "SELECT notes_referencing FROM source_cycles WHERE name=? AND cycle=?",
                (name, first),
            ).fetchone()
            end_ref = conn.execute(
                "SELECT notes_referencing FROM source_cycles WHERE name=? AND cycle=?",
                (name, last),
            ).fetchone()
            gen_delta = (int(end_gen[0]) if end_gen else 0) - (
                int(start_gen[0]) if start_gen else 0
            )
            ref_delta = (int(end_ref[0]) if end_ref else 0) - (
                int(start_ref[0]) if start_ref else 0
            )

            last_touch = first
            prev_empty = 0
            crossed_cold = False
            for num in numbers:
                row = conn.execute(
                    "SELECT notes_generated, notes_referencing FROM source_cycles WHERE name=? AND cycle=?",
                    (name, num),
                ).fetchone()
                gen = int(row[0]) if row else 0
                ref = int(row[1]) if row else 0
                if gen > 0 or ref > 0:
                    last_touch = num
                    prev_empty = 0
                else:
                    prev_empty += 1
                    if prev_empty >= threshold:
                        crossed_cold = True

            signals: list[str] = []
            if gen_delta or ref_delta:
                signals.append(f"yield Δ gen {gen_delta:+d}, ref {ref_delta:+d}")
            if name in degraded:
                signals.append("degraded transition")
            if crossed_cold:
                signals.append(f"went cold (≥{threshold} empty cycles)")
            if signals:
                rows_out.append(
                    {"name": name, "signals": signals, "last_cycle": last_touch}
                )
    except sqlite3.Error as exc:
        # No tables yet, or not a database: omit the section, as for a locked
        # one, rather than render "no drift" from data never read.
        warnings.append(f"sources.db unreadable ({exc}) — Source Quality Drift omitted")
        return [], warnings, True
    finally:
        conn.close()
    return rows_out, warnings, False


def build_strongest_signals(vault_dir: Path, scope: DigestScope) -> list[NoteScore]:
    inbound = inbound_link_counts(vault_dir)
    ref_deltas = _referencing_deltas(vault_dir, scope.cycles)
    data_vault = corpus_dir(vault_dir)
    scores: list[NoteScore] = []
    for note_path, fm, body, cycle_num in _notes_in_range(vault_dir, scope.cycles):
        rel = str(note_path.relative_to(data_vault))
        title = str(fm.get("title") or note_path.stem)
        cited = fm.get("sources_consulted") or []
        cited_names = [str(x) for x in cited] if isinstance(cited, list) else []
        total, inb, drift, fresh = composite_score(
            inbound_links=inbound.get(title, 0),
            cited_sources=cited_names,
            referencing_deltas=ref_deltas,
            first_written=_note_first_written(fm, cycle_num),
            date_range=scope.date_range,
        )
        summary = str(fm.get("summary") or _first_paragraph(body) or "").strip()
        scores.append(
            NoteScore(rel, title, _wikilink(title), total, inb, drift, fresh, summary)
        )
    return rank_notes(scores)


def build_gaps(
    vault_dir: Path, cycles: list[CycleScope], categories: list[dict[str, Any]]
) -> list[GapEntry]:
    if not cycles:
        return []
    first = _load_json(cycles[0].quality_report_path)
    last = _load_json(cycles[-1].quality_report_path)
    if first is None or last is None:
        return []
    return detect_gaps(
        categories=categories,
        first_report=first,
        last_report=last,
        last_cycle=cycles[-1].number,
    )


def build_new_notes_by_category(
    vault_dir: Path, cycles: list[CycleScope]
) -> list[tuple[str, int, list[str]]]:
    note_types: list[str] = []
    spec_path = vault_dir / "research.spec.md"
    if spec_path.is_file():
        try:
            note_types = [
                nt.name for nt in load_spec(spec_path, location=vault_dir).note_types
            ]
        except Exception:
            pass
    grouped: dict[str, list[str]] = {}
    for note_path, fm, _body, _cycle in _notes_in_range(vault_dir, cycles):
        ntype = str(fm.get("type") or "unknown")
        title = str(fm.get("title") or note_path.stem)
        grouped.setdefault(ntype, []).append(_wikilink(title))
    ordered = [t for t in note_types if t in grouped] + sorted(
        t for t in grouped if t not in note_types
    )
    return [(t, len(grouped[t]), sorted(grouped[t])[:3]) for t in ordered]


def build_coverage_delta(
    categories: list[dict[str, Any]], cycles: list[CycleScope]
) -> list[tuple[str, float, float, float]]:
    if not cycles:
        return []
    first = _load_json(cycles[0].quality_report_path)
    last = _load_json(cycles[-1].quality_report_path)
    if first is None or last is None:
        return []
    rows: list[tuple[str, float, float, float]] = []
    for cat in categories:
        name = str(cat.get("name") or "")
        if not name:
            continue
        start = coverage_progress(first, name)
        end = coverage_progress(last, name)
        rows.append((name, start, end, end - start))
    return rows


def _sparkline(values: list[float]) -> str:
    if not values:
        return ""
    blocks = "▁▂▃▄▅▆▇█"
    lo, hi = min(values), max(values)
    if hi == lo:
        return blocks[0] * len(values)
    return "".join(
        blocks[int((val - lo) / (hi - lo) * (len(blocks) - 1))] for val in values
    )


def build_cost_summary(
    vault_dir: Path, cycles: list[CycleScope]
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    per_cycle: list[float] = []
    per_stage: dict[str, float] = {}
    missing: list[int] = []
    for cycle in cycles:
        calls_dir = (
            vault_dir
            / "_pipeline"
            / "cycles"
            / f"cycle-{cycle.number:03d}"
            / "agent-calls"
        )
        if not calls_dir.is_dir():
            missing.append(cycle.number)
            per_cycle.append(0.0)
            continue
        sidecars = sorted(calls_dir.glob("*.json"))
        if not sidecars:
            missing.append(cycle.number)
            per_cycle.append(0.0)
            continue
        total = 0.0
        for sidecar in sidecars:
            data = _load_json(sidecar)
            if data is None:
                continue
            total += float(data.get("cost_usd") or 0.0)
            kind = str(data.get("agent_kind") or data.get("stage") or "unknown")
            per_stage[kind] = per_stage.get(kind, 0.0) + float(
                data.get("cost_usd") or 0.0
            )
        per_cycle.append(total)
    if missing:
        warnings.append(
            "missing cost sidecars for cycle(s): "
            + ", ".join(str(n) for n in missing)
            + " — counted as $0.00"
        )
    return {
        "total_usd": round(sum(per_cycle), 2),
        "per_stage": sorted(per_stage.items()),
        "per_cycle": [
            (c.number, val) for c, val in zip(cycles, per_cycle, strict=True)
        ],
        "sparkline": _sparkline(per_cycle),
    }, warnings


def _parse_cycle_report_h1(path: Path | None) -> str:
    if path is None or not path.is_file():
        return "(no report)"
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    except OSError:
        pass
    return "(no report)"


def build_cycle_index(
    vault_dir: Path, scope: DigestScope
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    rows: list[dict[str, Any]] = []
    head_sha = scope.git_head
    for cycle in scope.cycles:
        if cycle.report_path is None:
            warnings.append(
                f"cycle-{cycle.number:03d}-report.md missing or malformed — skipped summary"
            )
        ship_date = cycle.finished_at
        git_date = _git_commit_date(vault_dir, head_sha)
        if git_date is not None:
            ship_date = git_date
        rows.append(
            {
                "number": cycle.number,
                "ship_date": ship_date.astimezone(UTC).date().isoformat(),
                "summary": _parse_cycle_report_h1(cycle.report_path),
                "ship_sha": resolve_ship_sha(vault_dir, cycle, head_sha),
            }
        )
    return rows, warnings


def build_sections(vault_dir: Path, scope: DigestScope) -> SectionModels:
    footer = list(scope.warnings)
    categories, target_warn = _load_coverage_targets(vault_dir)
    footer.extend(target_warn)
    drift, drift_warn, omit_drift = build_source_drift(
        vault_dir, scope.cycles, scope.date_range
    )
    footer.extend(drift_warn)
    costs, cost_warn = build_cost_summary(vault_dir, scope.cycles)
    footer.extend(cost_warn)
    cycle_index, cycle_warn = build_cycle_index(vault_dir, scope)
    footer.extend(cycle_warn)
    return SectionModels(
        strongest_signals=build_strongest_signals(vault_dir, scope),
        gaps=build_gaps(vault_dir, scope.cycles, categories),
        new_notes_by_category=build_new_notes_by_category(vault_dir, scope.cycles),
        source_drift=drift,
        omit_source_drift_section=omit_drift,
        coverage_delta=build_coverage_delta(categories, scope.cycles),
        cost_summary=costs,
        cycle_index=cycle_index,
        footer_warnings=footer,
    )


__all__ = ["SectionModels", "build_sections"]
