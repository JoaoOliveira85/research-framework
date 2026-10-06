#!/usr/bin/env python3
"""Deterministic topic harvester — turns research output into a scout-ready queue.

Runs once per cycle, after `validate_cycle.py` has signed off the research
report. Emits two artifacts the next scout will read:

    _pipeline/cycles/cycle-NNN-harvest.json   — machine-readable manifest
    _pipeline/research-backlog.md             — human + LLM-readable bullets

Signals harvested (Phase 1, no LLM):

  1. Missing wikilink targets — [[X]] in a touched note where `X.md` does not
     exist anywhere under `data_vault/`. Ranked by the number of DISTINCT
     touched notes that cite the target (demand signal).
  2. Researcher-flagged new links — titles the researcher listed in
     `new_wikilinks_discovered` of the research report, deduped against (1).
  3. Unmet coverage categories — categories from
     `_pipeline/coverage-targets.json` with `met_count < target_count`,
     ordered by `required` first, then shortfall descending.

Contract:

  * Best-effort. Any failure prints a WARN and exits 0 so the cycle never
    dies because of harvest issues.
  * Idempotent per cycle: the backlog block for a given cycle is replaced
    on re-run, not duplicated.
  * Preserves manual backlog entries outside the managed block.

See `specs/003-topic-harvest-stage/spec.md`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Match any non-bracket content inside [[...]]. Normalization below handles
# aliases (| ...), anchors (# ...), folder prefixes, and `.md` suffixes.
_WIKILINK_RE = re.compile(r"\[\[([^\[\]]+?)\]\]")

_BLOCK_START_FMT = "<!-- topic-harvest:cycle={c:03d} -->"
_BLOCK_END_FMT = "<!-- /topic-harvest:cycle={c:03d} -->"

# Default citation threshold for auto-promoting orphan wikilinks into
# coverage-targets.json. Overridable via `pipeline.backlog_promotion_threshold`
# in the vault's settings.yaml. See constitution v1.3.0 § "Coverage Targets —
# Dynamic extension via backlog promotion".
DEFAULT_BACKLOG_PROMOTION_THRESHOLD = 2


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Followup:
    """A topic the scout should consider next cycle."""

    title: str
    reason: str  # "missing_wikilink_target" | "researcher_flagged"
    cited_from: list[str] = field(default_factory=list)  # vault-relative paths
    citation_count: int = 0


@dataclass
class CoverageGap:
    name: str
    note_type: str
    target_count: int
    met_count: int
    shortfall: int
    required: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_wikilink(raw: str) -> str | None:
    """Normalize `[[…]]` payload to a bare note title.

    Handles: `[[Foo]]`, `[[Foo|alias]]`, `[[Foo#anchor]]`, `[[folder/Foo]]`,
    `[[Foo.md]]`. Returns ``None`` on empty/whitespace input.
    """
    s = raw.strip()
    if "|" in s:
        s = s.split("|", 1)[0]
    if "#" in s:
        s = s.split("#", 1)[0]
    if "/" in s:
        s = s.rsplit("/", 1)[-1]
    s = s.strip()
    if s.endswith(".md"):
        s = s[:-3].strip()
    return s or None


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _corpus_dir(vault: Path) -> Path:
    """Resolve the vault's corpus folder through the framework seam.

    This script runs as a subprocess from a vault where the framework wheel is
    installed, but harvest is best-effort by contract: if the import fails we
    assume the default name rather than killing the cycle.
    """
    try:
        from research_framework.vault.corpus import corpus_dir
    except ImportError:
        return vault / "data_vault"
    return corpus_dir(vault)


def _existing_note_stems(data_vault: Path) -> set[str]:
    """Set of casefolded note stems currently under ``data_vault/``.

    Skips files whose name starts with `_` (auto-generated indexes / MOCs).
    """
    if not data_vault.is_dir():
        return set()
    stems: set[str] = set()
    for p in data_vault.rglob("*.md"):
        if p.name.startswith("_"):
            continue
        stems.add(p.stem.casefold())
    return stems


def _resolve_touched_note(vault: Path, rel: str) -> Path | None:
    """Resolve a note filename / path from a research report to a real file.

    Research reports list notes in several shapes — bare basename, vault-
    relative path, or corpus-relative. Try each in turn, then fall back to
    a basename search under the corpus.
    """
    rel = rel.replace("\\", "/").strip()
    if not rel:
        return None
    dv = _corpus_dir(vault)
    for cand in (dv / rel, vault / rel):
        if cand.is_file():
            return cand
    base = Path(rel).name
    if dv.is_dir():
        for p in dv.rglob(base):
            if p.is_file() and not p.name.startswith("_"):
                return p
    return None


# ---------------------------------------------------------------------------
# Harvesters
# ---------------------------------------------------------------------------


def _harvest_wikilinks(
    note_paths: list[Path], existing: set[str], vault: Path
) -> list[Followup]:
    """Rank missing wikilink targets by number of distinct citing notes."""
    citations: dict[str, set[str]] = defaultdict(set)
    # Preserve first-seen casing for display (existing-set compare is lower).
    display: dict[str, str] = {}

    for note in note_paths:
        try:
            body = note.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = note.relative_to(vault).as_posix()
        seen_in_note: set[str] = set()
        for m in _WIKILINK_RE.finditer(body):
            title = _normalize_wikilink(m.group(1))
            if not title:
                continue
            key = title.casefold()
            if key in existing or key in seen_in_note:
                continue
            seen_in_note.add(key)
            citations[key].add(rel)
            display.setdefault(key, title)

    followups = [
        Followup(
            title=display[k],
            reason="missing_wikilink_target",
            cited_from=sorted(v),
            citation_count=len(v),
        )
        for k, v in citations.items()
    ]
    followups.sort(key=lambda f: (-f.citation_count, f.title.casefold()))
    return followups


def _harvest_researcher_flags(
    report: dict[str, Any], existing: set[str], already: set[str]
) -> list[Followup]:
    """Pick up titles the researcher explicitly flagged as new links.

    `already` is the set of casefolded titles already covered by wikilink
    harvesting — we don't want double entries.
    """
    raw = report.get("new_wikilinks_discovered") or []
    if not isinstance(raw, list):
        return []
    out: list[Followup] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        title = _normalize_wikilink(item)
        if not title:
            continue
        key = title.casefold()
        if key in existing or key in already or key in seen:
            continue
        seen.add(key)
        out.append(Followup(title=title, reason="researcher_flagged"))
    out.sort(key=lambda f: f.title.casefold())
    return out


def _coverage_gaps(vault: Path) -> list[CoverageGap]:
    data = _read_json(vault / "_pipeline" / "coverage-targets.json")
    if not data:
        return []
    gaps: list[CoverageGap] = []
    for cat in data.get("categories") or []:
        try:
            target = int(cat.get("target_count") or 0)
            met = int(cat.get("met_count") or 0)
        except (TypeError, ValueError):
            continue
        if target <= met:
            continue
        gaps.append(
            CoverageGap(
                name=str(cat.get("name", "")),
                note_type=str(cat.get("note_type", "")),
                target_count=target,
                met_count=met,
                shortfall=target - met,
                required=bool(cat.get("required", True)),
            )
        )
    gaps.sort(key=lambda g: (not g.required, -g.shortfall, g.name))
    return gaps


# ---------------------------------------------------------------------------
# Backlog rendering
# ---------------------------------------------------------------------------


def _render_backlog_body(
    cycle: int,
    ts: str,
    followups: list[Followup],
    gaps: list[CoverageGap],
) -> str:
    lines: list[str] = [f"## Harvest — cycle {cycle:03d} ({ts[:10]})", ""]

    if followups:
        lines.append(
            "Follow-on topics (wikilink targets with no note yet, "
            "ranked by citation count):"
        )
        lines.append("")
        for f in followups:
            if f.reason == "researcher_flagged":
                lines.append(f"- **{f.title}** — flagged by researcher")
                continue
            sample = ", ".join(f"`{p}`" for p in f.cited_from[:3])
            more = f" (+{len(f.cited_from) - 3} more)" if len(f.cited_from) > 3 else ""
            lines.append(
                f"- **{f.title}** — cited by {f.citation_count} note(s): {sample}{more}"
            )
        lines.append("")

    if gaps:
        lines.append("Unmet coverage categories:")
        lines.append("")
        for g in gaps:
            tag = " (required)" if g.required else ""
            lines.append(
                f"- `{g.name}` [{g.note_type}] — {g.met_count}/{g.target_count}{tag}"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _replace_managed_block(backlog: str, cycle: int, body: str) -> str:
    start = _BLOCK_START_FMT.format(c=cycle)
    end = _BLOCK_END_FMT.format(c=cycle)
    wrapped = f"{start}\n{body.strip()}\n{end}\n"
    if start in backlog and end in backlog:
        pre, _, rest = backlog.partition(start)
        _, _, post = rest.partition(end)
        return pre.rstrip("\n") + "\n\n" + wrapped + post.lstrip("\n")
    sep = "" if backlog.endswith("\n") else "\n"
    return backlog + sep + "\n" + wrapped


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _read_promotion_threshold(vault_dir: Path) -> int:
    """Read `pipeline.backlog_promotion_threshold` from `<vault>/settings.yaml`.

    Falls back to ``DEFAULT_BACKLOG_PROMOTION_THRESHOLD`` whenever the file,
    section, or value is missing or malformed — auto-promotion is best-effort
    and should never crash the harvest call.
    """
    # Holdout from spec 025 B7: scripts/ best-effort read; must not raise SettingsError.
    settings_path = vault_dir / "settings.yaml"
    if not settings_path.is_file():
        return DEFAULT_BACKLOG_PROMOTION_THRESHOLD
    try:
        import yaml
    except ImportError:
        return DEFAULT_BACKLOG_PROMOTION_THRESHOLD
    try:
        data = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return DEFAULT_BACKLOG_PROMOTION_THRESHOLD
    pipeline_cfg = data.get("pipeline") if isinstance(data, dict) else None
    if not isinstance(pipeline_cfg, dict):
        return DEFAULT_BACKLOG_PROMOTION_THRESHOLD
    val = pipeline_cfg.get("backlog_promotion_threshold")
    try:
        return int(val) if val is not None else DEFAULT_BACKLOG_PROMOTION_THRESHOLD
    except (TypeError, ValueError):
        return DEFAULT_BACKLOG_PROMOTION_THRESHOLD


def _slug_for_target(text: str) -> str:
    """Slugify a wikilink title for use as a coverage-category name.

    Mirrors ``research_framework.spec.simple._slug`` so a human-typed title and
    an auto-promoted backlog entry produce the same slug for the same
    concept (lowercase, non-alnum runs collapsed to ``-``).
    """
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "topic"


def _promote_high_citation_orphans(
    vault_dir: Path, followups: list[Followup], threshold: int
) -> list[str]:
    """Promote orphan wikilinks cited at or above ``threshold`` into
    ``_pipeline/coverage-targets.json`` as new ``CoverageCategory`` entries.

    Constitution v1.3.0 § "Coverage Targets — Dynamic extension via backlog
    promotion": coverage tracks the vault's emergent topology, not just the
    spec author's foresight. Each promoted orphan becomes a soft (non-required)
    `concept`-typed category with `target_count: 1`.

    Idempotent — re-running on the same harvest doesn't add duplicates.
    Best-effort — any failure (missing wheel, malformed coverage JSON,
    threshold disabled) prints a WARN and returns []; the caller's harvest
    output is unaffected.

    Returns the list of newly added titles (empty if nothing qualified).
    """
    if threshold <= 0 or not followups:
        return []
    qualifying = [
        f for f in followups if f.citation_count >= threshold and f.title.strip()
    ]
    if not qualifying:
        return []

    # Local import: research_framework is shipped in the bundle's wheel and is
    # available whenever `topic_harvest.py` runs out of a vault context.
    # Failing the import (e.g. someone running the script from outside any
    # installed environment) downgrades gracefully rather than crashing.
    try:
        from research_framework.pipeline.coverage import load_targets, save_targets
        from research_framework.spec.schema import CoverageCategory
    except ImportError as e:
        print(
            f"WARN: backlog promotion skipped — research_framework not importable "
            f"({e}). Install the wheel or run via `rv generate` to enable.",
            file=sys.stderr,
        )
        return []

    try:
        targets = load_targets(vault_dir)
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"WARN: backlog promotion skipped — {e}", file=sys.stderr)
        return []

    existing_names = {c.name for c in targets.categories}
    existing_displays = {(c.display_name or "").casefold() for c in targets.categories}
    promoted: list[str] = []
    for f in qualifying:
        title = f.title.strip()
        slug = _slug_for_target(title)
        if slug in existing_names or title.casefold() in existing_displays:
            continue
        targets.categories.append(
            CoverageCategory(
                name=slug,
                note_type="concept",
                target_count=1,
                required=False,
                display_name=title,
            )
        )
        existing_names.add(slug)
        existing_displays.add(title.casefold())
        promoted.append(title)
    if promoted:
        save_targets(vault_dir, targets)
    return promoted


def harvest(vault_dir: Path, cycle: int, *, max_followups: int = 100) -> dict[str, Any]:
    pipeline = vault_dir / "_pipeline"
    cycles_dir = pipeline / "cycles"
    research_path = cycles_dir / f"cycle-{cycle:03d}-research.json"

    report = _read_json(research_path)
    if report is None:
        return {
            "skipped": True,
            "reason": f"missing or unreadable {research_path.name}",
        }

    touched: list[str] = []
    touched.extend(report.get("notes_created") or [])
    touched.extend(report.get("notes_updated") or [])

    resolved = [p for p in (_resolve_touched_note(vault_dir, r) for r in touched) if p]
    existing = _existing_note_stems(_corpus_dir(vault_dir))

    link_followups = _harvest_wikilinks(resolved, existing, vault_dir)
    already = {f.title.casefold() for f in link_followups}
    researcher_followups = _harvest_researcher_flags(report, existing, already)

    followups = (link_followups + researcher_followups)[:max_followups]
    gaps = _coverage_gaps(vault_dir)

    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "cycle": cycle,
        "phase": "harvest",
        "timestamp": ts,
        "notes_scanned": [p.relative_to(vault_dir).as_posix() for p in resolved],
        "followups": [asdict(f) for f in followups],
        "coverage_gaps": [asdict(g) for g in gaps],
    }
    from research_framework.pipeline.atomic_write import write_json

    write_json(cycles_dir / f"cycle-{cycle:03d}-harvest.json", manifest)

    backlog_path = pipeline / "research-backlog.md"
    backlog_updated = False
    if followups or gaps:
        pipeline.mkdir(parents=True, exist_ok=True)
        body = _render_backlog_body(cycle, ts, followups, gaps)
        prev = (
            backlog_path.read_text(encoding="utf-8")
            if backlog_path.is_file()
            else "# Research Backlog\n\nTopics deferred from scout passes.\n"
        )
        backlog_path.write_text(
            _replace_managed_block(prev, cycle, body), encoding="utf-8"
        )
        backlog_updated = True

    # Auto-promote high-citation orphan wikilinks into coverage targets so
    # the Phase-3 gate tracks emergent topology (constitution v1.3.0).
    threshold = _read_promotion_threshold(vault_dir)
    promoted = _promote_high_citation_orphans(vault_dir, followups, threshold)
    if promoted:
        print(
            f"[topic_harvest] promoted {len(promoted)} orphan(s) to coverage "
            f"targets (cited ≥{threshold}x): {', '.join(promoted)}"
        )

    return {
        "skipped": False,
        "followups_count": len(followups),
        "coverage_gaps_count": len(gaps),
        "notes_scanned_count": len(resolved),
        "backlog_updated": backlog_updated,
        "promoted_to_targets": promoted,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Harvest follow-on topics from research output (deterministic, "
            "best-effort)."
        )
    )
    parser.add_argument("vault_dir", type=Path, help="Vault root directory")
    parser.add_argument("cycle", type=int, help="1-based cycle number")
    parser.add_argument(
        "--max-followups",
        type=int,
        default=100,
        help="Cap on followups written to the manifest (default 100).",
    )
    args = parser.parse_args()

    vault = args.vault_dir.resolve()
    if not vault.is_dir():
        print(f"WARN: vault_dir not found: {vault}", file=sys.stderr)
        return 0

    try:
        result = harvest(vault, args.cycle, max_followups=args.max_followups)
    except Exception as e:
        print(f"WARN: topic_harvest failed: {e}", file=sys.stderr)
        return 0

    if result.get("skipped"):
        print(f"[topic_harvest] skipped: {result.get('reason')}")
    else:
        print(
            f"[topic_harvest] cycle {args.cycle}: "
            f"{result['followups_count']} follow-up(s), "
            f"{result['coverage_gaps_count']} coverage gap(s); "
            f"scanned {result['notes_scanned_count']} note(s); "
            f"backlog_updated={result['backlog_updated']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
