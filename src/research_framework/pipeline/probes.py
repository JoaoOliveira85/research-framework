"""Queryability probes: deterministic generation and scoring (FR-020, E-007)."""

from __future__ import annotations

import glob
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from research_framework.spec.schema import (
    BudgetConfig,
    CoverageTargets,
    NoteTypeConfig,
    ScopeConfig,
    SpecConfig,
)
from research_framework.vault.frontmatter import split_frontmatter

logger = logging.getLogger(__name__)

ProbeKind = Literal["coverage", "cross_reference", "findability"]
TOP_K = 3

_STOPWORDS = frozenset(
    {
        "what",
        "how",
        "does",
        "did",
        "the",
        "for",
        "and",
        "with",
        "from",
        "this",
        "that",
        "are",
        "was",
        "has",
        "have",
        "any",
        "why",
        "who",
        "which",
        "when",
        "into",
        "onto",
        "about",
        "under",
        "over",
        "such",
        "its",
    }
)


@dataclass(frozen=True)
class QueryabilityProbe:
    probe_id: str
    kind: ProbeKind
    question: str
    keywords: list[str]
    source_category: str
    source_field: str


@dataclass(frozen=True)
class CandidateNote:
    filename: str
    confidence: Literal["high", "medium", "low"]


@dataclass
class ProbeResult:
    probe_id: str
    candidates: list[CandidateNote]
    scored_candidates: dict[str, int]
    answered: bool
    partial: bool
    reason: str


def _probe_id(kind: str, question: str, source_category: str, source_field: str) -> str:
    h = hashlib.sha1(f"{kind}\0{question}\0{source_category}\0{source_field}".encode())
    return h.hexdigest()[:12]


def _keywords_from_text(text: str) -> list[str]:
    raw = re.findall(r"[a-z0-9][a-z0-9_-]{2,}", text.lower())
    out: list[str] = []
    seen: set[str] = set()
    for tok in raw:
        if tok in _STOPWORDS or tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
    return out


def _note_types_by_name(spec: SpecConfig) -> dict[str, NoteTypeConfig]:
    return {nt.name: nt for nt in spec.note_types}


def generate_probes(spec: SpecConfig) -> list[QueryabilityProbe]:
    out: list[QueryabilityProbe] = []
    nt_map = _note_types_by_name(spec)
    cats = sorted(spec.coverage_targets.categories, key=lambda c: (c.name, c.note_type))
    first_cat = cats[0].name if cats else ""

    for cat in cats:
        nt = nt_map.get(cat.note_type)
        label = (cat.display_name or "").strip() or cat.name
        for q in (f"What is {label}?", f"How does {label} work?"):
            out.append(
                QueryabilityProbe(
                    probe_id=_probe_id("coverage", q, cat.name, "contextual_questions"),
                    kind="coverage",
                    question=q,
                    keywords=_keywords_from_text(q),
                    source_category=cat.name,
                    source_field="contextual_questions",
                )
            )
        if nt:
            for cq in nt.contextual_questions:
                q = str(cq).strip()
                if not q:
                    continue
                out.append(
                    QueryabilityProbe(
                        probe_id=_probe_id(
                            "coverage", q, cat.name, "contextual_questions"
                        ),
                        kind="coverage",
                        question=q,
                        keywords=_keywords_from_text(q),
                        source_category=cat.name,
                        source_field="contextual_questions",
                    )
                )

    anchor = first_cat or "general"
    for cq in spec.scope.contextual_questions:
        q = str(cq).strip()
        if not q:
            continue
        out.append(
            QueryabilityProbe(
                probe_id=_probe_id("coverage", q, anchor, "contextual_questions"),
                kind="coverage",
                question=q,
                keywords=_keywords_from_text(q),
                source_category=anchor,
                source_field="contextual_questions",
            )
        )

    for b in sorted(spec.scope.boundaries):
        q = f"How does {b} fit within the vault scope?"
        out.append(
            QueryabilityProbe(
                probe_id=_probe_id("cross_reference", q, anchor, "boundaries"),
                kind="cross_reference",
                question=q,
                keywords=_keywords_from_text(b) or _keywords_from_text(q),
                source_category=anchor,
                source_field="boundaries",
            )
        )

    for o in sorted(spec.scope.out_of_scope):
        q = f"Why is {o} treated as out of scope?"
        out.append(
            QueryabilityProbe(
                probe_id=_probe_id("findability", q, anchor, "out_of_scope"),
                kind="findability",
                question=q,
                keywords=_keywords_from_text(o) or _keywords_from_text(q),
                source_category=anchor,
                source_field="out_of_scope",
            )
        )

    out.sort(key=lambda p: p.probe_id)
    return out


def _split_frontmatter(body: str) -> tuple[str, str]:
    if not body.startswith("---"):
        return "", body
    # At the delimiter LINES: ``body.split("---", 2)`` ended the frontmatter at
    # the first `---` inside a value (a slug URL such as `kafka---a-guide`).
    return split_frontmatter(body) or ("", body)


def _fm_value(fm_block: str, key: str) -> str:
    for line in fm_block.splitlines():
        line = line.strip()
        if line.lower().startswith(f"{key}:"):
            rest = line.split(":", 1)[1].strip()
            if rest.startswith('"') and rest.endswith('"'):
                return rest[1:-1]
            if rest.startswith("'") and rest.endswith("'"):
                return rest[1:-1]
            return rest
    return ""


def _find_note_file(vault_dir: Path, corpus_dir: str, filename: str) -> Path | None:
    root = vault_dir / corpus_dir
    if not root.is_dir():
        return None
    # The filename is the retrieval agent's: match it as a name, not a pattern.
    base = glob.escape(Path(filename).name)
    for p in root.rglob(base):
        if p.is_file():
            return p
    return None


def _note_meta(
    vault_dir: Path, spec: SpecConfig, filename: str
) -> tuple[str, str, str]:
    path = _find_note_file(vault_dir, spec.vault_corpus_dir, filename)
    if path is None:
        return "", "", ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", "", ""
    fm, body = _split_frontmatter(text)
    title = (_fm_value(fm, "title") or "").strip()
    summary = (_fm_value(fm, "summary") or "").strip()
    cat = (_fm_value(fm, "coverage_category") or "").strip()
    blob = f"{title} {summary} {body}".lower()
    return cat, title, blob


def _is_relevant(probe: QueryabilityProbe, coverage_category: str, title: str) -> bool:
    tl = title.lower()
    if coverage_category == probe.source_category:
        return True
    for kw in probe.keywords:
        if kw and kw.lower() in tl:
            return True
    return False


def _has_keyword(probe: QueryabilityProbe, blob_lower: str) -> bool:
    for kw in probe.keywords:
        if kw and kw.lower() in blob_lower:
            return True
    return False


def score_candidates(
    probe: QueryabilityProbe,
    candidates: list[CandidateNote],
    *,
    vault_dir: Path,
    spec: SpecConfig | None = None,
) -> ProbeResult:
    spec = spec or SpecConfig(
        name="",
        location=vault_dir,
        owner="",
        scope=ScopeConfig(domain="", organization=""),
        note_types=[],
        data_sources=[],
        search_dimensions=[],
        coverage_targets=CoverageTargets(categories=[]),
        budget=BudgetConfig(),
        vault_corpus_dir="data_vault",
    )

    scores: dict[str, int] = {}
    for idx, cand in enumerate(candidates):
        rank = idx + 1
        cat, title, blob = _note_meta(vault_dir, spec, cand.filename)
        blob_l = blob.lower()
        relevant = _is_relevant(probe, cat, title)
        if not relevant:
            scores[cand.filename] = 0
            continue
        if rank > TOP_K:
            scores[cand.filename] = 0
            continue
        in_top = rank <= TOP_K
        has_kw = _has_keyword(probe, blob_l)
        rub = int(relevant) + int(in_top) + int(has_kw)
        scores[cand.filename] = rub

    best = max(scores.values(), default=0)
    answered = best >= 3
    partial = (not answered) and (1 in scores.values())
    reason = ""
    if answered:
        reason = ""
    elif not candidates:
        reason = "no candidate notes"
    else:
        reason = "no candidate satisfied all rubric checks"

    return ProbeResult(
        probe_id=probe.probe_id,
        candidates=list(candidates),
        scored_candidates=scores,
        answered=answered,
        partial=partial,
        reason=reason,
    )


def trajectory_bucket(current: int, previous: int | None) -> str:
    if previous is None:
        return "stable"
    if current - previous > 5:
        return "improving"
    if previous - current > 5:
        return "regressing"
    return "stable"


def _prev_queryability_score(vault_dir: Path, cycle_number: int) -> int | None:
    if cycle_number <= 1:
        return None
    prev_path = (
        vault_dir
        / "_pipeline"
        / "cycles"
        / f"cycle-{cycle_number - 1:03d}-quality-report.json"
    )
    if not prev_path.is_file():
        return None
    try:
        data = json.loads(prev_path.read_text(encoding="utf-8"))
        qs = data.get("queryability_score")
        if qs is None:
            return None
        return int(qs)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _load_probe_candidates(
    vault_dir: Path, cycle_number: int
) -> dict[str, list[CandidateNote]] | None:
    cpath = (
        vault_dir
        / "_pipeline"
        / "cycles"
        / f"cycle-{cycle_number:03d}-probe-candidates.json"
    )
    if not cpath.is_file():
        logger.info(
            "[probes] missing probe candidates file for cycle %s (%s); "
            "using empty candidate lists",
            cycle_number,
            cpath,
        )
        return None
    try:
        doc = json.loads(cpath.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.info(
            "[probes] cannot read probe candidates for cycle %s: %s",
            cycle_number,
            e,
        )
        return None
    raw_map = doc.get("probes")
    if not isinstance(raw_map, dict):
        return {}
    out: dict[str, list[CandidateNote]] = {}
    for pid, rows in raw_map.items():
        notes: list[CandidateNote] = []
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                fn = str(row.get("filename") or "")
                conf = str(row.get("confidence") or "medium").lower()
                if conf not in ("high", "medium", "low"):
                    conf = "medium"
                if fn:
                    notes.append(CandidateNote(filename=fn, confidence=conf))  # type: ignore[arg-type]
        out[str(pid)] = notes
    return out


def _result_json_item(probe: QueryabilityProbe, res: ProbeResult) -> dict:
    sc_list = sorted(
        [[fn, sc] for fn, sc in res.scored_candidates.items()],
        key=lambda x: x[0],
    )
    cand_list = [
        {"filename": c.filename, "confidence": c.confidence} for c in res.candidates
    ]
    return {
        "probe_id": probe.probe_id,
        "kind": probe.kind,
        "question": probe.question,
        "keywords": list(probe.keywords),
        "source_category": probe.source_category,
        "candidates": cand_list,
        "scored_candidates": sc_list,
        "answered": res.answered,
        "partial": res.partial,
        **({"reason": res.reason} if res.reason else {}),
    }


def run_cycle_probes(
    *,
    vault_dir: Path,
    spec: SpecConfig,
    cycle_number: int,
) -> tuple[int, str]:
    vault_dir = vault_dir.resolve()
    probes_list = generate_probes(spec)
    cand_map = _load_probe_candidates(vault_dir, cycle_number) or {}

    results: list[ProbeResult] = []
    json_items: list[dict] = []
    answered_n = 0

    for probe in probes_list:
        raw = cand_map.get(probe.probe_id, [])
        res = score_candidates(probe, raw, vault_dir=vault_dir, spec=spec)
        json_items.append(_result_json_item(probe, res))
        results.append(res)
        if res.answered:
            answered_n += 1

    n = len(probes_list)
    score_pct = 0 if n == 0 else round(100 * answered_n / n)
    prev_q = _prev_queryability_score(vault_dir, cycle_number)
    traj = trajectory_bucket(score_pct, prev_q)

    out_path = (
        vault_dir
        / "_pipeline"
        / "cycles"
        / f"cycle-{cycle_number:03d}-probe-results.json"
    )
    doc = {
        "schema_version": "1",
        "cycle_number": cycle_number,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "score": score_pct,
        "results": json_items,
    }
    from .atomic_write import write_json as _write_json

    _write_json(out_path, doc)

    return score_pct, traj
