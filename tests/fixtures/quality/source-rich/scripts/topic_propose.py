#!/usr/bin/env python3
"""Phase 2: scope-bounded, agent-driven tangent proposer.

Runs after Phase 1 (`topic_harvest`) in Step 7b of `run_cycle.sh`. Reads
this cycle's touched notes, the vault's spec scope, and existing vault /
backlog / Phase 1 state; calls the `topic_propose` stage via
`scripts/agent_call.py`; validates every proposal against a closed set
of structural rules; writes:

    _pipeline/cycles/cycle-NNN-propose.json
    _pipeline/research-backlog.md             (managed "topic-propose" block)
    _pipeline/propose-rejects.md              (scope rejections, persistent)

Opt-in: `stages.topic_propose.enabled` in settings.yaml gates the whole
stage. Best-effort: any failure logs a WARN and exits 0 — the cycle
never dies because of tangent proposal issues.

Spec: specs/003-topic-harvest-stage/phase-2-semantic.md
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_RELATION_TYPES: list[str] = [
    "variant",
    "prerequisite",
    "contrast",
    "sibling",
    "downstream_effect",
    "user_question",
]

_REJECT_REASONS = {
    "schema_invalid",
    "bad_relation",
    "parent_missing",
    "degree_exceeded",
    "scope_check",
    "dedupe_existing_note",
    "dedupe_backlog",
    "dedupe_phase1",
    "cap_exceeded",
}

_BACKLOG_START_FMT = "<!-- topic-propose:cycle={c:03d} -->"
_BACKLOG_END_FMT = "<!-- /topic-propose:cycle={c:03d} -->"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError:
        return {}
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _stage_settings(vault: Path) -> dict[str, Any]:
    settings = _load_yaml(vault / "settings.yaml")
    stages = settings.get("stages") or {}
    block = stages.get("topic_propose") or {}
    return block if isinstance(block, dict) else {}


def _spec_block(vault: Path) -> dict[str, Any]:
    spec_parse = _read_json(vault / "_pipeline" / "spec-parse.json") or {}
    return spec_parse if isinstance(spec_parse, dict) else {}


def _scope(vault: Path) -> dict[str, Any]:
    scope = _spec_block(vault).get("scope") or {}
    return scope if isinstance(scope, dict) else {}


def _existing_note_stems(vault: Path) -> set[str]:
    data_vault = vault / "data_vault"
    if not data_vault.is_dir():
        return set()
    return {
        p.stem.casefold()
        for p in data_vault.rglob("*.md")
        if not p.name.startswith("_")
    }


def _resolve_note(vault: Path, rel: str) -> Path | None:
    rel = rel.replace("\\", "/").strip()
    if not rel:
        return None
    for cand in (vault / "data_vault" / rel, vault / rel):
        if cand.is_file():
            return cand
    base = Path(rel).name
    dv = vault / "data_vault"
    if dv.is_dir():
        for p in dv.rglob(base):
            if p.is_file() and not p.name.startswith("_"):
                return p
    return None


def _backlog_titles(vault: Path) -> set[str]:
    """Casefolded titles already listed in backlog (any **Bold** span)."""
    path = vault / "_pipeline" / "research-backlog.md"
    if not path.is_file():
        return set()
    text = path.read_text(encoding="utf-8")
    return {
        m.group(1).strip().casefold()
        for m in re.finditer(r"\*\*([^*\n]+?)\*\*", text)
        if m.group(1).strip()
    }


def _phase1_titles(vault: Path, cycle: int) -> set[str]:
    data = _read_json(
        vault / "_pipeline" / "cycles" / f"cycle-{cycle:03d}-harvest.json"
    )
    if not data:
        return set()
    out: set[str] = set()
    for f in data.get("followups") or []:
        if not isinstance(f, dict):
            continue
        t = f.get("title")
        if isinstance(t, str) and t.strip():
            out.add(t.strip().casefold())
    return out


def _coverage_gaps(vault: Path) -> list[dict[str, Any]]:
    ct = _read_json(vault / "_pipeline" / "coverage-targets.json")
    if not ct:
        return []
    gaps: list[dict[str, Any]] = []
    for c in ct.get("categories") or []:
        if not isinstance(c, dict):
            continue
        try:
            target = int(c.get("target_count") or 0)
            met = int(c.get("met_count") or 0)
        except (TypeError, ValueError):
            continue
        if target <= met:
            continue
        gaps.append(
            {
                "name": str(c.get("name", "")),
                "note_type": str(c.get("note_type", "")),
                "target_count": target,
                "met_count": met,
                "required": bool(c.get("required", True)),
            }
        )
    return gaps


def _touched_notes(
    vault: Path, cycle: int, *, max_excerpt: int = 800
) -> list[dict[str, Any]]:
    research = _read_json(
        vault / "_pipeline" / "cycles" / f"cycle-{cycle:03d}-research.json"
    )
    if not research:
        return []
    rels: list[str] = []
    rels.extend(research.get("notes_created") or [])
    rels.extend(research.get("notes_updated") or [])
    out: list[dict[str, Any]] = []
    for rel in rels:
        p = _resolve_note(vault, str(rel))
        if p is None:
            continue
        try:
            body = p.read_text(encoding="utf-8")
        except OSError:
            continue
        out.append(
            {
                "path": p.relative_to(vault).as_posix(),
                "title": p.stem,
                "excerpt": body[:max_excerpt],
            }
        )
    return out


def _wikilink_stems_in_touched(notes: list[dict[str, Any]]) -> set[str]:
    """Casefolded stems of wikilinks found in touched notes.

    Used to compute degree-2 parent eligibility (a parent that isn't
    touched this cycle but is cited via `[[…]]` from a touched note).
    """
    stems: set[str] = set()
    pat = re.compile(r"\[\[([^\[\]]+?)\]\]")
    for n in notes:
        for m in pat.finditer(n.get("excerpt", "")):
            raw = m.group(1)
            # Strip alias / anchor / folder prefix / .md
            if "|" in raw:
                raw = raw.split("|", 1)[0]
            if "#" in raw:
                raw = raw.split("#", 1)[0]
            if "/" in raw:
                raw = raw.rsplit("/", 1)[-1]
            raw = raw.strip()
            if raw.endswith(".md"):
                raw = raw[:-3].strip()
            if raw:
                stems.add(raw.casefold())
    return stems


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------


def render_prompt(
    *,
    spec_name: str,
    domain: str,
    out_of_scope: list[str],
    relation_types: list[str],
    touched_notes: list[dict[str, Any]],
    covered_titles: list[str],
    backlog_titles: list[str],
    phase1_titles: list[str],
    coverage_gaps: list[dict[str, Any]],
    max_proposals: int,
    max_degree: int,
) -> str:
    lines: list[str] = []
    lines.append(f"You are running the 'topic-propose' skill on the {spec_name} vault.")
    lines.append("")
    lines.append(f"Domain: {domain or '(unset)'}")
    lines.append("")
    if out_of_scope:
        lines.append("## Out of scope (HARD fence — reject anything matching these)")
        for t in out_of_scope:
            lines.append(f"- {t}")
        lines.append("")
    lines.append("## Relation types (closed enum — use exactly one per proposal)")
    for rt in relation_types:
        lines.append(f"- `{rt}`")
    lines.append("")
    lines.append("## This cycle's touched notes (degree-1 anchors)")
    for n in touched_notes:
        lines.append(f"### [[{n['title']}]] — `{n['path']}`")
        lines.append(n["excerpt"])
        lines.append("")
    lines.append("## Already covered (do NOT re-propose)")
    if covered_titles:
        for t in covered_titles[:40]:
            lines.append(f"- {t}")
        extra = len(covered_titles) - 40
        if extra > 0:
            lines.append(f"…and {extra} more.")
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("## Already queued in backlog")
    if backlog_titles:
        for t in backlog_titles[:40]:
            lines.append(f"- {t}")
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("## Already flagged by Phase 1 (topic_harvest)")
    if phase1_titles:
        for t in phase1_titles[:40]:
            lines.append(f"- {t}")
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("## Unmet coverage categories (priority signal)")
    if coverage_gaps:
        for g in coverage_gaps:
            req = " (required)" if g.get("required") else ""
            lines.append(
                f"- `{g['name']}` [{g['note_type']}] — "
                f"{g['met_count']}/{g['target_count']}{req}"
            )
    else:
        lines.append("(none)")
    lines.append("")
    lines.append("## Caps")
    lines.append(
        f"- Emit **at most {max_proposals}** proposals. "
        "Overflow → `rejected[]` with `cap_exceeded`."
    )
    lines.append(f"- `degree` ≤ {max_degree}.")
    lines.append("")
    lines.append("## Output")
    lines.append("")
    lines.append(
        "Emit a single JSON object with `proposals[]` and `rejected[]`. "
        "No prose, no fences."
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Agent call (subprocess by default; injectable for tests)
# ---------------------------------------------------------------------------


def subprocess_agent_caller(vault: Path) -> Callable[[str], str]:
    """Return a callable that sends ``prompt`` to ``agent_call.py`` and
    returns its stdout. Raises on non-zero exit or missing script.
    """
    agent_script = vault / "scripts" / "agent_call.py"

    def _call(prompt: str) -> str:
        if not agent_script.is_file():
            raise FileNotFoundError(f"agent_call.py not found at {agent_script}")
        proc = subprocess.run(
            [
                sys.executable,
                str(agent_script),
                "--vault",
                str(vault),
                "--stage",
                "topic_propose",
            ],
            input=prompt,
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"agent_call.py exited {proc.returncode}: {proc.stderr}")
        return proc.stdout

    return _call


def _extract_json(text: str) -> dict[str, Any] | None:
    """Parse the first JSON object in ``text``, tolerating fences / prose."""
    if not text or not text.strip():
        return None
    stripped = text.strip()
    try:
        data = json.loads(stripped)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    first = stripped.find("{")
    last = stripped.rfind("}")
    if first >= 0 and last > first:
        try:
            data = json.loads(stripped[first : last + 1])
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None
    return None


# ---------------------------------------------------------------------------
# Validation gate
# ---------------------------------------------------------------------------


def _reject(prop: dict[str, Any], rejected_by: str, reason: str) -> dict[str, Any]:
    return {
        "title": str(prop.get("title", "")),
        "relation_type": str(prop.get("relation_type", "")),
        "parent_note": str(prop.get("parent_note", "")),
        "justification": str(prop.get("justification", "")),
        "rejected_by": rejected_by,
        "reason": reason,
    }


def validate_proposals(
    raw_proposals: list[Any],
    raw_rejected: list[Any],
    *,
    vault: Path,
    allowed_relations: list[str],
    max_degree: int,
    max_proposals: int,
    out_of_scope_terms: list[str],
    covered_stems: set[str],
    backlog_titles_cf: set[str],
    phase1_titles_cf: set[str],
    touched_paths: set[str],
    wikilink_stems: set[str],
    require_out_of_scope: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run every structural / scope / dedup rule. Returns (accepted, rejected).

    Rejections from the agent (``raw_rejected``) are carried through
    verbatim as diagnostic signal; our own rejections are appended.
    """
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for r in raw_rejected or []:
        if isinstance(r, dict):
            rejected.append(r)

    if not isinstance(raw_proposals, list):
        raw_proposals = []

    seen_titles_cf: set[str] = set()
    relations_lower = {r.lower() for r in allowed_relations}
    oos_lower = [
        t.lower() for t in out_of_scope_terms if isinstance(t, str) and t.strip()
    ]

    for prop in raw_proposals:
        if not isinstance(prop, dict):
            continue

        title = str(prop.get("title", "")).strip()
        relation = str(prop.get("relation_type", "")).strip().lower()
        parent_raw = str(prop.get("parent_note", "")).strip()
        justification = str(prop.get("justification", "")).strip()

        degree_val = prop.get("degree", None)
        try:
            degree = int(degree_val)
        except (TypeError, ValueError):
            degree = -1

        if not title or not relation or not parent_raw or not justification:
            rejected.append(_reject(prop, "schema_invalid", "missing required field"))
            continue

        if relation not in relations_lower:
            rejected.append(
                _reject(
                    prop,
                    "bad_relation",
                    f"'{relation}' not in configured enum",
                )
            )
            continue

        # Resolve parent_note. Accept vault-relative, data_vault/-relative,
        # or basename; normalize to a vault-relative POSIX path on success.
        parent_path: Path | None = None
        for candidate in (
            vault / parent_raw,
            vault / "data_vault" / parent_raw,
        ):
            if candidate.is_file():
                parent_path = candidate
                break
        if parent_path is None:
            base = Path(parent_raw).name
            dv = vault / "data_vault"
            if dv.is_dir():
                for p in dv.rglob(base):
                    if p.is_file() and not p.name.startswith("_"):
                        parent_path = p
                        break

        if parent_path is None:
            rejected.append(
                _reject(
                    prop,
                    "parent_missing",
                    f"parent_note not found: {parent_raw}",
                )
            )
            continue

        parent_rel = parent_path.relative_to(vault).as_posix()
        parent_stem_cf = parent_path.stem.casefold()

        # Degree inference / validation.
        # Degree 1: parent was touched this cycle.
        # Degree 2: parent is cited by a touched note (wikilink).
        # If the agent set a degree, respect it if plausible; otherwise
        # infer from state so degrees are consistent.
        inferred: int
        if parent_rel in touched_paths or parent_path.name in touched_paths:
            inferred = 1
        elif parent_stem_cf in wikilink_stems:
            inferred = 2
        else:
            inferred = 3  # too far — rejected below

        final_degree = degree if degree in (1, 2) else inferred
        if final_degree > max_degree:
            rejected.append(
                _reject(
                    prop,
                    "degree_exceeded",
                    f"degree {final_degree} > max {max_degree}",
                )
            )
            continue

        # Scope check: any out_of_scope term appearing in title or
        # justification rejects pre-write. Fail-closed.
        title_lower = title.lower()
        just_lower = justification.lower()
        scope_hit: str | None = None
        for term in oos_lower:
            if term in title_lower or term in just_lower:
                scope_hit = term
                break
        if scope_hit:
            rejected.append(
                _reject(
                    prop,
                    "scope_check",
                    f"matches out_of_scope term '{scope_hit}'",
                )
            )
            continue

        # Dedup
        key = title.casefold()
        if key in covered_stems:
            rejected.append(
                _reject(
                    prop,
                    "dedupe_existing_note",
                    "title matches an existing note",
                )
            )
            continue
        if key in backlog_titles_cf:
            rejected.append(
                _reject(
                    prop,
                    "dedupe_backlog",
                    "title already queued in backlog",
                )
            )
            continue
        if key in phase1_titles_cf:
            rejected.append(
                _reject(
                    prop,
                    "dedupe_phase1",
                    "title already found by topic_harvest",
                )
            )
            continue
        if key in seen_titles_cf:
            rejected.append(
                _reject(
                    prop,
                    "dedupe_backlog",
                    "duplicate within this response",
                )
            )
            continue
        seen_titles_cf.add(key)

        # scope_check label
        raw_scope_check = str(prop.get("scope_check", "")).strip().lower()
        if raw_scope_check in ("in_scope", "warn"):
            scope_check = raw_scope_check
        else:
            scope_check = "in_scope"
        if not out_of_scope_terms and not require_out_of_scope:
            # No fence configured and the stage was told to proceed
            # anyway → every proposal carries a warn flag for review.
            scope_check = "warn"

        accepted.append(
            {
                "title": title,
                "relation_type": relation,
                "parent_note": parent_rel,
                "justification": justification,
                "degree": final_degree,
                "scope_check": scope_check,
                "suggested_note_type": str(prop.get("suggested_note_type") or ""),
            }
        )

    # Cap enforcement: honour the agent's ordering, push overflow to rejected.
    if len(accepted) > max_proposals:
        overflow = accepted[max_proposals:]
        accepted = accepted[:max_proposals]
        for p in overflow:
            rejected.append(
                {
                    "title": p["title"],
                    "relation_type": p["relation_type"],
                    "parent_note": p["parent_note"],
                    "justification": p["justification"],
                    "rejected_by": "cap_exceeded",
                    "reason": f"exceeds max_proposals={max_proposals}",
                }
            )

    return accepted, rejected


# ---------------------------------------------------------------------------
# Output rendering
# ---------------------------------------------------------------------------


def _render_backlog_body(cycle: int, ts: str, accepted: list[dict[str, Any]]) -> str:
    lines = [
        f"## Proposed tangents — cycle {cycle:03d} ({ts[:10]}, agent)",
        "",
        (
            "Scope-bounded tangents the agent identified. Lower priority than "
            "the Phase 1 Harvest block; the scout can still consult them."
        ),
        "",
    ]
    for p in accepted:
        parent = Path(p["parent_note"]).stem if p.get("parent_note") else "?"
        warn = " ⚠️" if p.get("scope_check") == "warn" else ""
        lines.append(
            f"- **{p['title']}**{warn} ({p['relation_type']} of "
            f"[[{parent}]]) — {p['justification']}"
        )
    return "\n".join(lines).rstrip() + "\n"


def _replace_managed_block(backlog: str, cycle: int, body: str) -> str:
    start = _BACKLOG_START_FMT.format(c=cycle)
    end = _BACKLOG_END_FMT.format(c=cycle)
    wrapped = f"{start}\n{body.strip()}\n{end}\n"
    if start in backlog and end in backlog:
        pre, _, rest = backlog.partition(start)
        _, _, post = rest.partition(end)
        return pre.rstrip("\n") + "\n\n" + wrapped + post.lstrip("\n")
    sep = "" if backlog.endswith("\n") else "\n"
    return backlog + sep + "\n" + wrapped


def _append_persistent_rejects(
    vault: Path, cycle: int, ts: str, rejected: list[dict[str, Any]]
) -> int:
    """Append scope-check rejections to _pipeline/propose-rejects.md.

    Other rejection reasons (cap_exceeded, dedupe_*, parent_missing, …)
    are transient — excluding them from the persistent file means we
    don't permanently disallow topics that were rejected for fixable
    reasons.
    """
    persistent = [r for r in rejected if r.get("rejected_by") == "scope_check"]
    if not persistent:
        return 0
    path = vault / "_pipeline" / "propose-rejects.md"
    if not path.parent.is_dir():
        return 0
    lines: list[str] = []
    if not path.is_file():
        lines.append("# Persistent tangent rejections\n\n")
        lines.append(
            "Titles rejected by the Phase 2 scope check. The orchestrator\n"
            "unions these into the next scout's `exclude_topics` so the\n"
            "agent doesn't re-propose them cycle after cycle. Delete a\n"
            "line to let the topic be considered again.\n\n"
        )
    for r in persistent:
        title = str(r.get("title") or "").strip()
        reason = str(r.get("reason") or "").strip()
        if not title:
            continue
        lines.append(f"- **{title}** — cycle {cycle:03d} ({ts[:10]}): {reason}\n")
    mode = "a" if path.is_file() else "w"
    with path.open(mode, encoding="utf-8") as f:
        f.writelines(lines)
    return len(persistent)


def _write_empty_manifest(
    vault: Path, cycle: int, *, reason: str, model: str = ""
) -> Path:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = {
        "schema_version": "1.0",
        "cycle": cycle,
        "phase": "propose",
        "timestamp": ts,
        "model": model,
        "proposals": [],
        "rejected": [],
        "stats": {
            "proposed": 0,
            "accepted": 0,
            "rejected": 0,
            "rejected_reason": reason,
        },
    }
    out = vault / "_pipeline" / "cycles" / f"cycle-{cycle:03d}-propose.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------


def propose(
    vault_dir: Path,
    cycle: int,
    *,
    agent_caller: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    settings = _stage_settings(vault_dir)

    if not settings.get("enabled", False):
        return {"skipped": True, "reason": "topic_propose disabled in settings"}

    max_proposals = int(settings.get("max_proposals", 10) or 10)
    max_degree = int(settings.get("max_degree", 2) or 2)
    relation_types = (
        list(settings.get("relation_types") or DEFAULT_RELATION_TYPES)
        or DEFAULT_RELATION_TYPES
    )
    model = str(settings.get("model", "") or "")
    on_missing = (
        str(settings.get("on_missing_out_of_scope", "skip") or "skip").strip().lower()
    )
    require_oos = True  # spec mandates it when enabled

    scope = _scope(vault_dir)
    domain = str(scope.get("domain", "") or "")
    out_of_scope = [
        str(t).strip() for t in (scope.get("out_of_scope") or []) if str(t).strip()
    ]

    # Missing-out-of-scope policy
    if not out_of_scope:
        if on_missing == "skip":
            _write_empty_manifest(
                vault_dir,
                cycle,
                reason="no_out_of_scope (on_missing=skip)",
                model=model,
            )
            return {
                "skipped": True,
                "reason": "scope.out_of_scope missing; on_missing_out_of_scope=skip",
            }
        if on_missing == "error":
            _write_empty_manifest(
                vault_dir,
                cycle,
                reason="no_out_of_scope (on_missing=error)",
                model=model,
            )
            return {
                "skipped": True,
                "reason": "scope.out_of_scope missing; on_missing_out_of_scope=error",
            }
        # "warn" → proceed with empty fence; every accepted prop tagged warn.
        require_oos = False

    research_path = (
        vault_dir / "_pipeline" / "cycles" / f"cycle-{cycle:03d}-research.json"
    )
    if not research_path.is_file():
        return {
            "skipped": True,
            "reason": f"missing {research_path.name}",
        }

    touched = _touched_notes(vault_dir, cycle)
    if not touched:
        return {"skipped": True, "reason": "no touched notes this cycle"}

    touched_paths = {n["path"] for n in touched}
    touched_paths |= {Path(n["path"]).name for n in touched}
    wikilink_stems = _wikilink_stems_in_touched(touched)
    existing_stems = _existing_note_stems(vault_dir)
    backlog_titles_cf = _backlog_titles(vault_dir)
    phase1_titles_cf = _phase1_titles(vault_dir, cycle)

    # Surface candidate titles to the agent (not casefolded — it needs to
    # read them).
    covered_titles_display = (
        sorted(
            {
                p.stem
                for p in (vault_dir / "data_vault").rglob("*.md")
                if not p.name.startswith("_")
            }
        )
        if (vault_dir / "data_vault").is_dir()
        else []
    )
    backlog_titles_display: list[str] = []
    backlog_path = vault_dir / "_pipeline" / "research-backlog.md"
    if backlog_path.is_file():
        for m in re.finditer(
            r"\*\*([^*\n]+?)\*\*", backlog_path.read_text(encoding="utf-8")
        ):
            title = m.group(1).strip()
            if title:
                backlog_titles_display.append(title)
    phase1_titles_display: list[str] = []
    p1 = _read_json(
        vault_dir / "_pipeline" / "cycles" / f"cycle-{cycle:03d}-harvest.json"
    )
    if p1:
        for f in p1.get("followups") or []:
            if isinstance(f, dict):
                t = f.get("title")
                if isinstance(t, str) and t.strip():
                    phase1_titles_display.append(t.strip())

    gaps = _coverage_gaps(vault_dir)
    spec_name = str(_spec_block(vault_dir).get("name") or "vault")

    prompt = render_prompt(
        spec_name=spec_name,
        domain=domain,
        out_of_scope=out_of_scope,
        relation_types=relation_types,
        touched_notes=touched,
        covered_titles=covered_titles_display,
        backlog_titles=backlog_titles_display,
        phase1_titles=phase1_titles_display,
        coverage_gaps=gaps,
        max_proposals=max_proposals,
        max_degree=max_degree,
    )

    # Agent call
    caller = agent_caller or subprocess_agent_caller(vault_dir)
    try:
        raw = caller(prompt)
    except Exception as e:
        _write_empty_manifest(
            vault_dir, cycle, reason=f"agent_call_error: {e}", model=model
        )
        return {"skipped": False, "error": f"agent call failed: {e}"}

    parsed = _extract_json(raw)
    if parsed is None:
        _write_empty_manifest(
            vault_dir, cycle, reason="malformed_agent_output", model=model
        )
        return {"skipped": False, "error": "agent returned unparsable JSON"}

    raw_proposals = parsed.get("proposals") or []
    raw_rejected = parsed.get("rejected") or []

    accepted, rejected = validate_proposals(
        raw_proposals,
        raw_rejected,
        vault=vault_dir,
        allowed_relations=relation_types,
        max_degree=max_degree,
        max_proposals=max_proposals,
        out_of_scope_terms=out_of_scope,
        covered_stems=existing_stems,
        backlog_titles_cf=backlog_titles_cf,
        phase1_titles_cf=phase1_titles_cf,
        touched_paths=touched_paths,
        wikilink_stems=wikilink_stems,
        require_out_of_scope=require_oos,
    )

    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "cycle": cycle,
        "phase": "propose",
        "timestamp": ts,
        "model": model,
        "proposals": accepted,
        "rejected": rejected,
        "stats": {
            "proposed": len(raw_proposals) if isinstance(raw_proposals, list) else 0,
            "accepted": len(accepted),
            "rejected": len(rejected),
        },
    }
    out_path = vault_dir / "_pipeline" / "cycles" / f"cycle-{cycle:03d}-propose.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    backlog_updated = False
    if accepted:
        body = _render_backlog_body(cycle, ts, accepted)
        prev = (
            backlog_path.read_text(encoding="utf-8")
            if backlog_path.is_file()
            else "# Research Backlog\n\nTopics deferred from scout passes.\n"
        )
        backlog_path.write_text(
            _replace_managed_block(prev, cycle, body), encoding="utf-8"
        )
        backlog_updated = True

    persistent = _append_persistent_rejects(vault_dir, cycle, ts, rejected)

    return {
        "skipped": False,
        "accepted": len(accepted),
        "rejected": len(rejected),
        "persistent_rejects": persistent,
        "backlog_updated": backlog_updated,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Propose scope-bounded tangents from this cycle's research output "
            "(Phase 2 — agent, opt-in, best-effort)."
        )
    )
    parser.add_argument("vault_dir", type=Path, help="Vault root directory")
    parser.add_argument("cycle", type=int, help="1-based cycle number")
    args = parser.parse_args()

    vault = args.vault_dir.resolve()
    if not vault.is_dir():
        print(f"WARN: vault_dir not found: {vault}", file=sys.stderr)
        return 0

    try:
        result = propose(vault, args.cycle)
    except Exception as e:
        print(f"WARN: topic_propose failed: {e}", file=sys.stderr)
        return 0

    if result.get("skipped"):
        print(f"[topic_propose] skipped: {result.get('reason')}")
    elif "error" in result:
        print(f"[topic_propose] error: {result['error']}")
    else:
        print(
            f"[topic_propose] cycle {args.cycle}: "
            f"{result['accepted']} accepted, "
            f"{result['rejected']} rejected "
            f"(persistent: {result['persistent_rejects']}); "
            f"backlog_updated={result['backlog_updated']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
