"""Test-only stub for ``scripts/agent_call.py`` (feature 018).

This module is the **single source of truth** for how the test suite
replaces real LLM calls. Every tier-4 / tier-5 end-to-end test installs
this module's CLI in place of the real ``scripts/agent_call.py`` so the
production ``cycle_runner.py`` runs unmodified — same argv, same
subprocess shape, same on-disk outputs — but with zero token spend
and full determinism.

Contract: ``specs/018-testing-strategy/contracts/fake-agent.contract.md``.

NEVER import this module from anything under ``src/research_framework/``.
The fake is for tests only — it lives outside the wheel and outside
the bundle, so the production code path cannot accidentally depend on
it.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_LOG = logging.getLogger(__name__)

# Regex for the ``## Batch topics (JSON)`` block embedded in note_writer
# prompts by ``cycle_runner._render_batch_note_writer_prompt``. Locked
# here as a constant so a prompt-template drift breaks the e2e tier
# rather than silently degrading the fake into a "no notes written"
# pass-through.
BATCH_BLOCK_RE = re.compile(
    r"## Batch topics \(JSON\)\s*```json\s*(\[.*?\])\s*```",
    re.DOTALL,
)

DEFAULT_TIMESTAMP_FMT = "2026-05-17T00:00:{cycle:02d}Z"
DEFAULT_TEMPLATE_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Scenario selection
# ---------------------------------------------------------------------------


_SCENARIO_ENV_GLOBAL = "FAKE_AGENT_SCENARIO"
_SCENARIO_ENV_PER_STAGE = {
    "scout": "FAKE_AGENT_SCOUT_SCENARIO",
    "note_writer": "FAKE_AGENT_NOTE_WRITER_SCENARIO",
    "verifier": "FAKE_AGENT_VERIFIER_SCENARIO",
    "research_plan_narrator": "FAKE_AGENT_RESEARCH_PLAN_NARRATOR_SCENARIO",
    "probe_retrieval": "FAKE_AGENT_PROBE_RETRIEVAL_SCENARIO",
}

VALID_SCENARIOS = {
    "happy",
    "empty_scout",
    "fail_frontmatter",
    "oos_topic",
    "partial_yield",
    "accept",
    "reject",
    "malformed_json",
}

# Stage names are authoritative (018 contract); directory layout follows
# data-model.md § Entity 2.
_STAGE_TO_DIR = {
    "verifier": "verifier",
    "research_plan_narrator": "narrator",
    "probe_retrieval": "probe_retrieval",
}

SCENARIOS_ROOT = Path(__file__).resolve().parent / "fake_agent_scenarios"

# ONLY ``{cycle}`` and ``{cycle:03d}`` are honored — anything else stays literal.
_LOAD_SCENARIO_PLACEHOLDER_PATTERN = re.compile(r"\{(cycle(?::\d+d)?)\}")

_STAGE_VALID_SCENARIOS: dict[str, frozenset[str]] = {
    "scout": frozenset(
        {"happy", "empty_scout", "fail_frontmatter", "oos_topic", "partial_yield"}
    ),
    "note_writer": frozenset(
        {"happy", "empty_scout", "fail_frontmatter", "oos_topic", "partial_yield"}
    ),
    "verifier": frozenset({"accept", "reject", "malformed_json"}),
    "research_plan_narrator": frozenset({"happy"}),
    "probe_retrieval": frozenset({"happy"}),
}


def _validate_scenario_for_stage(stage: str, scenario: str) -> None:
    """Reject unknown (stage, scenario) pairs before any handler runs."""
    valid = _STAGE_VALID_SCENARIOS.get(stage)
    if valid is None:
        if scenario not in VALID_SCENARIOS:
            raise ValueError(
                f"unknown FAKE_AGENT_SCENARIO {scenario!r}; valid: {sorted(VALID_SCENARIOS)}"
            )
        return
    if scenario not in valid:
        raise ValueError(
            f"unknown scenario {scenario!r} for stage {stage!r}; valid: {sorted(valid)}"
        )


def _resolve_scenario(stage: str) -> str:
    """Per-stage override beats global; default is ``happy``."""
    per_stage_env = _SCENARIO_ENV_PER_STAGE.get(stage)
    val = ""
    if per_stage_env:
        val = (os.environ.get(per_stage_env) or "").strip()
    if not val:
        val = (os.environ.get(_SCENARIO_ENV_GLOBAL) or "").strip()
    if not val:
        val = "happy"
    _validate_scenario_for_stage(stage, val)
    return val


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify(title: str) -> str:
    """Title → kebab-case slug stable across runs."""
    s = title.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "topic"


def _load_spec_parse(vault_dir: Path) -> dict:
    parse_path = vault_dir / "_pipeline" / "spec-parse.json"
    if not parse_path.is_file():
        raise FileNotFoundError(
            f"fake_agent: missing {parse_path} (vault_factory must write spec-parse.json)"
        )
    return json.loads(parse_path.read_text(encoding="utf-8"))


def _load_coverage_targets(vault_dir: Path) -> list[dict]:
    p = vault_dir / "_pipeline" / "coverage-targets.json"
    if not p.is_file():
        return []
    doc = json.loads(p.read_text(encoding="utf-8")) or {}
    return list(doc.get("categories") or [])


def _atomic_write(path: Path, content: str) -> None:
    """Write bytes via tempfile + os.replace so partial files never appear."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        delete=False,
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)


def _parse_cycle_from_prompt(prompt_text: str) -> int | None:
    """Best-effort extraction of cycle number from a rendered prompt.

    The cycle runner substitutes ``{CYCLE_NUM}`` directly into the prompt
    body via :func:`cycle_runner._render_prompt` BEFORE invoking the
    agent. We rely on that contract: the rendered prompt either contains
    a "Cycle <N>" line or has the number in the scout/research output
    path (e.g. ``cycle-001-scout.json``).
    """
    m = re.search(r"cycle[-_ ]?(\d{1,4})", prompt_text, re.IGNORECASE)
    if m:
        try:
            n = int(m.group(1))
            if 1 <= n <= 9999:
                return n
        except ValueError:
            pass
    return None


def _word_pad(text: str, min_words: int) -> str:
    """Pad ``text`` with deterministic filler until it has ``min_words`` words."""
    words = text.split()
    if len(words) >= min_words:
        return text
    filler_words = (
        "synthetic body produced by fake agent for deterministic end-to-end "
        "testing of the cycle runner does not call any real language model "
    ).split()
    out = list(words)
    while len(out) < min_words:
        out.extend(filler_words)
    return " ".join(out[: max(min_words, len(words))])


# ---------------------------------------------------------------------------
# Stage: scout
# ---------------------------------------------------------------------------


def _derive_scout_topics(
    spec_parse: dict,
    coverage_targets: list[dict],
    *,
    cycle: int,
    scenario: str,
    vault_dir: Path | None = None,
) -> list[tuple[str, str]]:
    """Return ``[(title, coverage_category), ...]`` deterministically.

    Spec-driven: one topic per uncovered target, sorted by category
    declaration order, then by topic index within the category. Capped at
    a sensible ceiling so the priority queue stays small enough for
    fast tests.
    """
    if scenario == "empty_scout":
        return []

    # Count actual existing notes per category from the vault. Pre-0.3.0
    # the fake relied on ``coverage-targets.json::met_count`` being updated
    # between cycles, but the production cycle_runner does not always
    # rewrite that file mid-run, so cycle 2 used to collide with cycle 1's
    # filenames. Reading the vault is the durable source of truth.
    existing_per_cat: dict[str, int] = {}
    if vault_dir is not None:
        data_vault = Path(vault_dir) / "data_vault"
        if data_vault.is_dir():
            for cat in coverage_targets:
                name = str(cat.get("name") or "").strip()
                if not name:
                    continue
                # Filenames follow ``{cat} topic {n}`` → ``{slug}.md``.
                prefix = _slugify(f"{name} topic ")
                count = sum(
                    1 for p in data_vault.rglob("*.md") if p.name.startswith(prefix)
                )
                existing_per_cat[name] = count

    quota_cap = 12  # plenty for the e2e scenarios; deterministic upper bound
    # Round-robin allocation: cycle through categories so every cycle touches
    # all of them (SG-002 diversity gate requires ≥N distinct categories).
    # The pre-0.3.0 sequential algorithm exhausted services before flows and
    # often hit ``quota_cap`` before reaching the last category, tripping
    # SG-002 on cycle 1 of the source-rich + tech-lite fixtures.
    cat_state: list[dict] = []
    for cat in coverage_targets:
        name = str(cat.get("name") or "").strip()
        if not name:
            continue
        target_count = int(cat.get("target_count") or 0)
        met_count = max(int(cat.get("met_count") or 0), existing_per_cat.get(name, 0))
        remaining = max(0, target_count - met_count)
        # Start numbering at met_count+1 so cycle 2 doesn't propose the same
        # filenames cycle 1 already wrote (validate_cycle ABORTs on collision).
        cat_state.append(
            {"name": name, "next_index": met_count + 1, "remaining": remaining}
        )

    out: list[tuple[str, str]] = []
    progress = True
    while progress and len(out) < quota_cap:
        progress = False
        for st in cat_state:
            if st["remaining"] <= 0 or len(out) >= quota_cap:
                continue
            out.append((f"{st['name']} topic {st['next_index']}", st["name"]))
            st["next_index"] += 1
            st["remaining"] -= 1
            progress = True

    if scenario == "oos_topic":
        # Pollute with one out-of-scope title from spec.scope.out_of_scope.
        scope = spec_parse.get("scope") or {}
        oos_tokens = [str(x) for x in (scope.get("out_of_scope") or [])]
        if oos_tokens and coverage_targets:
            first_cat = str(coverage_targets[0].get("name") or "")
            out.insert(0, (f"{oos_tokens[0]} integration patterns", first_cat))

    return out


def write_scout(
    vault_dir: Path,
    cycle: int,
    *,
    scenario: str = "happy",
) -> Path:
    """Write a deterministic v2 scout JSON for ``cycle``. Returns the path."""
    spec_parse = _load_spec_parse(vault_dir)
    coverage_targets = _load_coverage_targets(vault_dir)

    # When a fixture ships a canned scout payload at
    # ``<vault>/fake_agent_responses/scout/<scenario>.json`` we honor it
    # verbatim (with cycle / timestamp / sources_consulted patched). This
    # lets the source-poor and source-rich fixtures preserve their
    # hand-tuned topic distributions (e.g. concentrated single-category
    # scouts that intentionally trip SG-002) instead of being overwritten
    # by the procedural round-robin generator.
    canned_path = (
        Path(vault_dir) / "fake_agent_responses" / "scout" / f"{scenario}.json"
    )
    if canned_path.is_file():
        return _write_scout_from_canned(
            vault_dir, cycle, canned_path, spec_parse=spec_parse
        )

    topics = _derive_scout_topics(
        spec_parse,
        coverage_targets,
        cycle=cycle,
        scenario=scenario,
        vault_dir=vault_dir,
    )

    topics_from_code = []
    topics_found_new = []
    proposed_filenames = []
    for i, (title, category) in enumerate(topics, start=1):
        slug = _slugify(title)
        proposed = f"{slug}.md"
        proposed_filenames.append(proposed)
        topics_from_code.append(
            {
                "id": f"CT-{cycle}-{i:03d}",
                "topic_type": "concept",
                "source_file": f"synthetic/scout/{slug}.md",
                "source_snippet": "lines 1-1",
                "proposed_filename": proposed,
            }
        )
        topics_found_new.append(
            {
                "title": title,
                "coverage_category": category,
                "proposed_filename": proposed,
            }
        )

    sources_consulted: list[str] = []
    for ds in spec_parse.get("data_sources") or []:
        if isinstance(ds, dict) and ds.get("name"):
            sources_consulted.append(str(ds["name"]))
    if not sources_consulted:
        sources_consulted = ["synthetic"]

    report = {
        "schema_version": "2.0",
        "cycle": cycle,
        "phase": "scout",
        "timestamp": DEFAULT_TIMESTAMP_FMT.format(cycle=cycle),
        "dimensions_covered": [
            "technical",
            "organizational",
            "domain",
            "market",
            "temporal",
        ],
        "topics_from_code": topics_from_code,
        "intent_from_confluence": [],
        "topics_found": {
            "new": topics_found_new,
            "existing": [],
            "total": len(topics_found_new),
        },
        "proposed_filenames": proposed_filenames,
        "sources_consulted": sources_consulted,
        "access_methods_used": {"synthetic": "local"},
        "termination_condition": None,
        "notes_created": [],
        "unresolved_wikilinks": [],
        "budget_consumed_usd": 0.0,
    }

    cycles_dir = vault_dir / "_pipeline" / "cycles"
    out = cycles_dir / f"cycle-{cycle:03d}-scout.json"
    _atomic_write(out, json.dumps(report, indent=2) + "\n")
    return out


def _write_scout_from_canned(
    vault_dir: Path,
    cycle: int,
    canned_path: Path,
    *,
    spec_parse: dict,
) -> Path:
    """Write a canned-scout payload, patching cycle-specific fields.

    Patches:
    - ``cycle`` → the current cycle number.
    - ``timestamp`` → deterministic per-cycle timestamp.
    - ``sources_consulted`` → spec's data_source names (or unchanged if the
      canned file already lists them).
    - Filename suffixes ``-c1`` (per US3 fixture convention) get rewritten
      to ``-c{cycle}`` so cycles 2+ don't collide with cycle 1's notes.
    - Topic ID prefixes ``CT-1-`` → ``CT-{cycle}-`` for the same reason.
    """
    raw = json.loads(canned_path.read_text(encoding="utf-8"))
    raw["cycle"] = cycle
    raw["timestamp"] = DEFAULT_TIMESTAMP_FMT.format(cycle=cycle)

    # validate_cycle requires all 5 dimensions. Fixtures sometimes omit
    # ``market`` / ``temporal``; canonicalize to the full set so the
    # canned payloads can stay terse without aborting validation.
    raw["dimensions_covered"] = [
        "technical",
        "organizational",
        "domain",
        "market",
        "temporal",
    ]

    if not raw.get("sources_consulted"):
        sources_consulted: list[str] = []
        for ds in spec_parse.get("data_sources") or []:
            if isinstance(ds, dict) and ds.get("name"):
                sources_consulted.append(str(ds["name"]))
        raw["sources_consulted"] = sources_consulted or ["synthetic"]

    def _rewrite_filename(name: str) -> str:
        if not isinstance(name, str):
            return name
        # The US3 fixtures use a ``-c<cycle>`` suffix convention so cycle 2
        # doesn't collide with cycle 1's filenames. If it's missing we
        # append one; if it points at cycle 1 we shift it forward.
        if name.endswith(f"-c{cycle}.md"):
            return name
        stem = name[:-3] if name.endswith(".md") else name
        # Strip any existing ``-c<digits>`` suffix.
        import re

        stem = re.sub(r"-c\d+$", "", stem)
        return f"{stem}-c{cycle}.md"

    for tfc in raw.get("topics_from_code") or []:
        if isinstance(tfc, dict):
            tid = tfc.get("id")
            if isinstance(tid, str) and tid.startswith("CT-"):
                # CT-1-001 → CT-{cycle}-001
                parts = tid.split("-")
                if len(parts) >= 3:
                    parts[1] = str(cycle)
                    tfc["id"] = "-".join(parts)
            if "proposed_filename" in tfc:
                tfc["proposed_filename"] = _rewrite_filename(tfc["proposed_filename"])

    topics_found = raw.get("topics_found")
    if isinstance(topics_found, dict):
        new_topics = topics_found.get("new") or []
        for t in new_topics:
            if isinstance(t, dict) and "proposed_filename" in t:
                t["proposed_filename"] = _rewrite_filename(t["proposed_filename"])

    if isinstance(raw.get("proposed_filenames"), list):
        raw["proposed_filenames"] = [
            _rewrite_filename(n) for n in raw["proposed_filenames"]
        ]

    cycles_dir = vault_dir / "_pipeline" / "cycles"
    out = cycles_dir / f"cycle-{cycle:03d}-scout.json"
    _atomic_write(out, json.dumps(raw, indent=2) + "\n")
    return out


# ---------------------------------------------------------------------------
# Stage: note_writer
# ---------------------------------------------------------------------------


def _note_type_from_spec(spec_parse: dict) -> dict:
    nts = spec_parse.get("note_types") or []
    if not nts:
        # Fall back to a synthetic concept type so we never explode.
        return {"name": "concept", "folder": "01 - Concepts", "min_word_count": 100}
    nt = nts[0]
    return {
        "name": str(nt.get("name") or "concept"),
        "folder": str(nt.get("folder") or "01 - Concepts"),
        "min_word_count": int(nt.get("min_word_count") or 100),
    }


def _note_type_for_category(spec_parse: dict, category: str) -> dict:
    """Resolve the note_type definition that owns ``category``.

    Lookup order:
    1. Spec's ``coverage_targets.categories`` list → entry with matching
       ``name``; use its ``note_type`` to find the matching ``note_types`` row.
    2. ``note_types`` row whose name matches the category (singular).
    3. First ``note_types`` row as the global default.
    """
    nts = spec_parse.get("note_types") or []
    if not nts:
        return _note_type_from_spec(spec_parse)

    target_nt: str | None = None
    coverage_targets = (spec_parse.get("coverage_targets") or {}).get(
        "categories"
    ) or []
    for cat in coverage_targets:
        if isinstance(cat, dict) and str(cat.get("name") or "") == category:
            target_nt = str(cat.get("note_type") or "") or None
            break

    if target_nt is None and category:
        # Try category-as-note-type (e.g. ``services`` → ``service``).
        singular = category[:-1] if category.endswith("s") else category
        target_nt = singular

    chosen = None
    if target_nt:
        for nt in nts:
            if str(nt.get("name") or "") == target_nt:
                chosen = nt
                break
    if chosen is None:
        chosen = nts[0]

    return {
        "name": str(chosen.get("name") or "concept"),
        "folder": str(chosen.get("folder") or "01 - Concepts"),
        "min_word_count": int(chosen.get("min_word_count") or 100),
    }


def _parse_batch_topics(prompt_text: str) -> list[dict]:
    m = BATCH_BLOCK_RE.search(prompt_text)
    if not m:
        return []
    try:
        rows = json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"fake_agent: malformed JSON inside `## Batch topics (JSON)`: {exc}"
        ) from exc
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict)]


def _render_note(
    *,
    note_type: dict,
    title: str,
    category: str,
    cycle: int,
    omit_source_urls: bool = False,
) -> str:
    slug = _slugify(title)
    fm: dict[str, Any] = {
        "type": note_type["name"],
        "template_version": DEFAULT_TEMPLATE_VERSION,
        "coverage_category": category,
        "summary": (
            f"Synthetic note generated by tests/_helpers/fake_agent.py for "
            f'"{title}" in coverage category {category}.'
        ),
        "related": [],
        "lifecycle": {"created_at_cycle": cycle},
    }
    if not omit_source_urls:
        fm["source_urls"] = [f"https://synthetic.test/fake_agent/{slug}"]
    body_intro = (
        f"# {title}\n\n"
        "Synthetic body produced by fake_agent.py for testing the cycle runner. "
        "This note exists to exercise the end-to-end pipeline without invoking "
        "any real language model."
    )
    body = _word_pad(body_intro, note_type["min_word_count"])
    return f"---\n{yaml.safe_dump(fm, sort_keys=False)}---\n\n{body}\n"


def _required_sources_from_spec(spec_parse: dict) -> list[str]:
    """Source names that ``validate_cycle`` will demand in ``sources_consulted``.

    Returns names normalized the same way ``scripts/validate_cycle.source_key``
    does (lowercased; spaces AND hyphens collapsed to underscores) so the
    research-phase ``sources_consulted`` block always matches the validator's
    expected key.
    """
    out: list[str] = []
    for ds in spec_parse.get("data_sources") or []:
        if not isinstance(ds, dict):
            continue
        if not ds.get("required", True):
            continue
        raw = str(ds.get("name") or "").strip().lower()
        name = raw.replace(" ", "_").replace("-", "_")
        if name:
            out.append(name)
    return out


def _sources_consulted_block(spec_parse: dict) -> dict[str, dict]:
    """Construct a ``sources_consulted`` map with every required source flagged searched."""
    out: dict[str, dict] = {}
    for name in _required_sources_from_spec(spec_parse) or ["synthetic"]:
        out[name] = {"searched": True, "results_count": 1, "pages_read": 1}
    return out


def _write_research_report(
    research_report: Path,
    *,
    cycle: int,
    spec_parse: dict,
    notes_created: list[str],
    skipped: list[dict],
) -> None:
    """Write a fully-formed v2 research report (atomic).

    Merges with any existing report so multiple batches in the same cycle
    accumulate ``notes_created`` rather than clobbering it.
    """
    doc: dict[str, Any] = {}
    if research_report.is_file():
        try:
            doc = json.loads(research_report.read_text(encoding="utf-8")) or {}
        except (OSError, json.JSONDecodeError):
            doc = {}

    prev_notes = list(doc.get("notes_created") or [])
    seen = set(prev_notes)
    for n in notes_created:
        if n not in seen:
            prev_notes.append(n)
            seen.add(n)

    out: dict[str, Any] = {
        "schema_version": "2.0",
        "cycle": cycle,
        "phase": "research",
        "timestamp": DEFAULT_TIMESTAMP_FMT.format(cycle=cycle),
        "sources_consulted": _sources_consulted_block(spec_parse),
        "topics_found": {"new": [], "existing": [], "total": 0},
        "notes_created": prev_notes,
        "notes_updated": list(doc.get("notes_updated") or []),
        "budget_consumed_usd": 0.0,
        "cost_estimate_usd": 0.0,
        "cumulative_cost_usd": 0.0,
        "unresolved_wikilinks": [],
        "skipped_topics": list(skipped)
        if skipped
        else list(doc.get("skipped_topics") or []),
    }
    _atomic_write(research_report, json.dumps(out, indent=2) + "\n")


def process_batch(
    vault_dir: Path,
    prompt_file: Path,
    cycle: int,
    *,
    scenario: str = "happy",
) -> list[Path]:
    """Materialize notes for the topics in a batch prompt. Returns written paths."""
    spec_parse = _load_spec_parse(vault_dir)
    note_type = _note_type_from_spec(spec_parse)
    prompt_text = prompt_file.read_text(encoding="utf-8")
    topics = _parse_batch_topics(prompt_text)
    cycles_dir = vault_dir / "_pipeline" / "cycles"
    research_report = cycles_dir / f"cycle-{cycle:03d}-research.json"

    if not topics:
        # Non-batched path (DFS prompt without an inline ``## Batch topics
        # (JSON)`` block — e.g. the quality-harness fixture cycles that
        # call ``run_cycle_steps`` directly).
        #
        # Prefer the scout report when present: turn every
        # ``topics_found.new`` row into a topic for note-writing. This
        # mirrors what the real DFS-research agent does (read scout, write
        # notes) and keeps per-category counts honest. Fall back to one
        # synthetic note when no scout report exists.
        scout_path = cycles_dir / f"cycle-{cycle:03d}-scout.json"
        if scout_path.is_file():
            try:
                scout_doc = json.loads(scout_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                scout_doc = {}
            new_rows = (scout_doc.get("topics_found") or {}).get("new") or []
            for r in new_rows:
                if not isinstance(r, dict):
                    continue
                title = str(r.get("title") or "").strip()
                category = str(r.get("coverage_category") or "").strip()
                if title:
                    topics.append({"title": title, "category": category})
        if not topics:
            coverage_targets = _load_coverage_targets(vault_dir)
            for cat in coverage_targets:
                name = str(cat.get("name") or "")
                target = int(cat.get("target_count") or 0)
                met = int(cat.get("met_count") or 0)
                if name and met < target:
                    topics = [{"title": f"{name} topic 1", "category": name}]
                    break

    if scenario == "partial_yield" and topics:
        keep = max(1, len(topics) // 2)
        written_topics = topics[:keep]
        skipped_topics = [
            {
                "title": str(t.get("title") or ""),
                "category": str(t.get("category") or ""),
                "reason": "fake_agent_partial_yield_mode",
            }
            for t in topics[keep:]
        ]
    else:
        written_topics = topics
        skipped_topics = []

    written_paths: list[Path] = []
    written_names: list[str] = []
    for topic in written_topics:
        title = str(topic.get("title") or "untitled")
        category = str(topic.get("category") or "")
        # Per-topic note_type lookup so multi-category fixtures (source-rich,
        # tech-lite) route each note to the correct ``data_vault/<folder>``.
        per_topic_nt = (
            _note_type_for_category(spec_parse, category) if category else note_type
        )
        note_dir = vault_dir / "data_vault" / per_topic_nt["folder"]
        note_dir.mkdir(parents=True, exist_ok=True)
        omit = scenario == "fail_frontmatter"
        slug = _slugify(title)
        out_path = note_dir / f"{slug}.md"
        if out_path.exists():
            # Deterministic dedup: append a numeric suffix until we find a free path.
            for n in range(2, 1000):
                cand = note_dir / f"{slug}-{n}.md"
                if not cand.exists():
                    out_path = cand
                    break
        out_path.write_text(
            _render_note(
                note_type=per_topic_nt,
                title=title,
                category=category,
                cycle=cycle,
                omit_source_urls=omit,
            ),
            encoding="utf-8",
        )
        written_paths.append(out_path)
        written_names.append(out_path.relative_to(vault_dir).as_posix())

    _write_research_report(
        research_report,
        cycle=cycle,
        spec_parse=spec_parse,
        notes_created=written_names,
        skipped=skipped_topics,
    )
    return written_paths


# ---------------------------------------------------------------------------
# v2 stage handlers (verifier, research_plan_narrator, probe_retrieval)
# ---------------------------------------------------------------------------


def _interpolate_scenario_placeholders(text: str, *, cycle: int) -> str:
    """Replace whitelisted ``{cycle}`` / ``{cycle:03d}`` placeholders only."""

    def _repl(match: re.Match[str]) -> str:
        spec = match.group(1)
        if spec == "cycle":
            return str(cycle)
        if spec == "cycle:03d":
            return f"{cycle:03d}"
        return match.group(0)

    return _LOAD_SCENARIO_PLACEHOLDER_PATTERN.sub(_repl, text)


def _load_scenario_payload(stage: str, scenario: str) -> str:
    """Load bytes from ``fake_agent_scenarios/<dir>/<scenario>.json``."""
    dir_name = _STAGE_TO_DIR[stage]
    path = SCENARIOS_ROOT / dir_name / f"{scenario}.json"
    if not path.is_file():
        raise FileNotFoundError(f"fake_agent: missing scenario file {path}")
    return path.read_text(encoding="utf-8")


def _emit_stage_output(args: argparse.Namespace, payload: str, *, stdout: bool) -> None:
    if stdout:
        sys.stdout.write(payload)
        if payload and not payload.endswith("\n"):
            sys.stdout.write("\n")
    if args.output_file is not None:
        _atomic_write(args.output_file, payload)


def _handle_verifier(
    args: argparse.Namespace,
    scenario: str,
    prompt_text: str,
) -> None:
    del prompt_text  # verifier scenarios are static; prompt reserved for future use
    if scenario == "malformed_json":
        content = _load_scenario_payload("verifier", scenario)
    else:
        cycle = (
            _parse_cycle_from_prompt(args.prompt_file.read_text(encoding="utf-8")) or 1
        )
        content = _interpolate_scenario_placeholders(
            _load_scenario_payload("verifier", scenario), cycle=cycle
        )
    _emit_stage_output(args, content, stdout=args.output_file is None)


def _handle_narrator(
    args: argparse.Namespace,
    scenario: str,
    prompt_text: str,
) -> None:
    cycle = _parse_cycle_from_prompt(prompt_text) or 1
    raw = _interpolate_scenario_placeholders(
        _load_scenario_payload("research_plan_narrator", scenario), cycle=cycle
    )
    doc = json.loads(raw)
    narrative = str(doc.get("narrative") or "").strip()
    _emit_stage_output(args, narrative, stdout=True)


def _handle_probe_retrieval(
    args: argparse.Namespace,
    scenario: str,
    prompt_text: str,
) -> None:
    del prompt_text
    cycle = _parse_cycle_from_prompt(args.prompt_file.read_text(encoding="utf-8")) or 1
    content = _interpolate_scenario_placeholders(
        _load_scenario_payload("probe_retrieval", scenario), cycle=cycle
    )
    _emit_stage_output(args, content, stdout=True)


# ---------------------------------------------------------------------------
# Weekly-runner stages (research, report)
#
# ``pipeline/runner.py`` drives a single-shot weekly run whose artifacts are
# FLAT (``_pipeline/research-report.json``), not the cycle-numbered set
# ``cycle_runner.py`` writes. Both stages used to fall through to the
# unknown-stage no-op, so ``research-framework pipeline resume`` / ``finish``
# recorded a phase DONE having produced nothing (issue #261).
# ---------------------------------------------------------------------------


# Matches the absolute path the runner substitutes for ``{RESEARCH_REPORT}``.
# Backticks are excluded because the prompt templates wrap the path in them.
_RESEARCH_REPORT_RE = re.compile(r"[^\s`'\"]*research-report\.json")


def _research_report_target(vault: Path, prompt_text: str) -> Path:
    """Resolve the report path the *prompt* named, not one derived from layout.

    Deriving ``<vault>/_pipeline/research-report.json`` would make the fake
    succeed even when the prompt reached it unrendered — the exact failure
    ``test_runner_agent_dispatch`` was written to catch and could not, because
    a prompt file merely existing proved nothing about its contents.
    """
    match = _RESEARCH_REPORT_RE.search(prompt_text)
    if match is None:
        raise ValueError(
            "fake_agent: the research prompt names no research-report.json "
            "path. The runner substitutes {RESEARCH_REPORT} before dispatch, "
            "so an unrendered placeholder or a missing line is a "
            "prompt-rendering bug, not an agent failure."
        )
    named = Path(match.group(0))
    return named if named.is_absolute() else vault / named


def _handle_research(
    args: argparse.Namespace,
    scenario: str,
    prompt_text: str,
) -> None:
    del scenario  # the weekly research stage has no scenario vocabulary yet
    report = _research_report_target(args.vault, prompt_text)
    _write_research_report(
        report,
        cycle=_parse_cycle_from_prompt(prompt_text) or 1,
        spec_parse=_load_spec_parse(args.vault),
        notes_created=[],
        skipped=[],
    )


def _render_weekly_report(cycle: int) -> str:
    """The frontmatter shape the vaults' own ``report.md`` agent specifies."""
    fm: dict[str, Any] = {
        "type": "weekly-report",
        "generated": DEFAULT_TIMESTAMP_FMT.format(cycle=cycle),
        "model": "fake",
        "notes_added": 0,
        "notes_updated": 0,
    }
    body = (
        "# Weekly briefing\n\n"
        "Synthetic briefing produced by tests/_helpers/fake_agent.py so a "
        "report phase that ran is distinguishable from one that no-opped."
    )
    return f"---\n{yaml.safe_dump(fm, sort_keys=False)}---\n\n{body}\n"


def _handle_report(
    args: argparse.Namespace,
    scenario: str,
    prompt_text: str,
) -> None:
    del scenario
    # The real agent names its export ``weekly-<today>.md``; a date would
    # break the determinism guarantee (contract § e), so the fake writes one
    # fixed name into the same directory.
    out = args.vault / "_pipeline" / "exports" / "weekly-report.md"
    _atomic_write(
        out, _render_weekly_report(_parse_cycle_from_prompt(prompt_text) or 1)
    )


# ---------------------------------------------------------------------------
# Cost sidecar
# ---------------------------------------------------------------------------


# Kept in step with ``scripts/agent_call._SIDECAR_SCHEMA_VERSION`` — the fake
# writes the same shape the real dispatcher does, or every reader of the
# agent-calls index (budget guard, digest, run report) is exercised against a
# payload production never produces. ``tests/_helpers/test_fake_agent_parity.py``
# derives both from the real module and fails when they drift.
_SIDECAR_SCHEMA_VERSION = "1.2"
# A fake call's $0 is not a *measurement* — there is no runtime signal and no
# estimate behind it. "none" is the literal the real dispatcher records in
# exactly that situation (``agent_call._resolve_cost``'s final branch).
_COST_SOURCE = "none"


def _write_cost_sidecar_v11(
    path: Path,
    *,
    stage: str,
    cycle: int,
    scenario: str,
    batch_index: int | None = None,
    topic_count: int | None = None,
    status: str = "ok",
    exit_code: int = 0,
    stderr_excerpt: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "schema_version": _SIDECAR_SCHEMA_VERSION,
        "stage": stage,
        "agent": "fake",
        "agent_kind": "fake",
        "tier": "standard",
        "status": status,
        "exit_code": exit_code,
        "cost_usd": 0.0,
        "cost_source": _COST_SOURCE,
        "tokens_in": 0,
        "tokens_out": 0,
        "latency_ms": 0,
        "started_at": "2000-01-01T00:00:00Z",
        "completed_at": "2000-01-01T00:00:01Z",
        "cycle": cycle,
        "scenario": scenario,
    }
    if stderr_excerpt:
        payload["stderr_excerpt"] = stderr_excerpt[:500]
    if batch_index is not None:
        payload["batch_index"] = batch_index
    if topic_count is not None:
        payload["topic_count"] = topic_count
    _atomic_write(path, json.dumps(payload, indent=2) + "\n")


def _write_cost_sidecar(path: Path, scenario: str, *, stage: str = "unknown") -> None:
    cycle = 1
    for parent in path.parents:
        m = re.search(r"cycle-(\d+)", parent.name)
        if m:
            cycle = int(m.group(1))
            break
    batch_m = re.search(r"-batch-(\d+)\.json$", path.name)
    batch_index = int(batch_m.group(1)) if batch_m else None
    _write_cost_sidecar_v11(
        path,
        stage=stage,
        cycle=cycle,
        scenario=scenario,
        batch_index=batch_index,
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


# The FLAT scout artifact the weekly runner names, as distinct from
# ``_pipeline/cycles/cycle-NNN-scout.json`` which ``cycle_runner`` reads.
# Same reasoning as ``_RESEARCH_REPORT_RE``: resolve what the PROMPT said, so
# an unrendered ``{SCOUT_REPORT}`` placeholder cannot pass for a real dispatch.
_SCOUT_REPORT_RE = re.compile(r"[^\s`'\"]*scout-report\.json")


def _handle_scout(
    args: argparse.Namespace,
    scenario: str,
    prompt_text: str,
) -> None:
    cycle = _parse_cycle_from_prompt(prompt_text) or 1
    written = write_scout(args.vault, cycle, scenario=scenario)

    # ``pipeline/runner.py`` is single-shot: its scout prompt substitutes
    # ``{SCOUT_REPORT}`` to ``<vault>/_pipeline/scout-report.json``, and it
    # now REFUSES to call the phase done unless that file is there (issue
    # #222). Before this, the fake wrote only the cycle-numbered copy, so a
    # runner scout phase "succeeded" having produced nothing the runner could
    # read — the same class of hole issue #261 closed for research/report.
    match = _SCOUT_REPORT_RE.search(prompt_text)
    if match is None:
        return
    named = Path(match.group(0))
    target = named if named.is_absolute() else args.vault / named
    if target.resolve() == written.resolve():
        return
    _atomic_write(target, written.read_text(encoding="utf-8"))


def _handle_note_writer(
    args: argparse.Namespace,
    scenario: str,
    prompt_text: str,
) -> None:
    process_batch(
        args.vault,
        args.prompt_file,
        _parse_cycle_from_prompt(prompt_text) or 1,
        scenario=scenario,
    )


# Every stage the fake implements, keyed by the ``--stage`` name the real
# ``scripts/agent_call.py`` accepts. Anything absent from this table is
# rejected by :func:`_reject_unknown_stage`.
_STAGE_HANDLERS = {
    "scout": _handle_scout,
    "note_writer": _handle_note_writer,
    "verifier": _handle_verifier,
    "research_plan_narrator": _handle_narrator,
    "probe_retrieval": _handle_probe_retrieval,
    "research": _handle_research,
    "report": _handle_report,
}

ALLOW_UNKNOWN_STAGE_ENV = "FAKE_AGENT_ALLOW_UNKNOWN_STAGE"


def _reject_unknown_stage(stage: str) -> None:
    """Fail closed on a stage the fake does not implement.

    Until issue #261 an unrecognised ``--stage`` exited 0 and wrote a
    ``status: ok`` cost sidecar, so a stage-name typo and a genuinely unwired
    stage both read as a green run — the weekly runner's own ``research`` and
    ``report`` among them. A fake that cannot fail cannot prove a stage ran.
    """
    if (os.environ.get(ALLOW_UNKNOWN_STAGE_ENV) or "").strip() == "1":
        return
    raise ValueError(
        f"unknown stage {stage!r}; implemented stages: "
        f"{sorted(_STAGE_HANDLERS)}. Set {ALLOW_UNKNOWN_STAGE_ENV}=1 to keep "
        "the pre-#261 no-op for a stage that deliberately has no fake."
    )


@dataclass(frozen=True)
class _StageOutcome:
    """What a stage run leaves behind for the sidecar to record."""

    exit_code: int
    cycle: int
    scenario: str
    error: str | None = None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Test-only stub for scripts/agent_call.py (feature 018)."
    )
    parser.add_argument("--vault", required=True, type=Path)
    parser.add_argument("--stage", required=True)
    # Optional, exactly as in the real CLI: ``agent_call._read_prompt(None)``
    # falls back to stdin. The fake used to make this REQUIRED, so a caller
    # piping the prompt would have died on an argparse error under the fake
    # and worked fine in production.
    parser.add_argument("--prompt-file", type=Path, default=None)
    parser.add_argument("--cost-sidecar", type=Path, default=None)
    parser.add_argument("--batch-index", type=int, default=None)
    parser.add_argument("--topic-count", type=int, default=None)
    # Accepted-and-ignored: the real CLI's --output-file is not used by the
    # cycle_runner for scout / note_writer stages, but we accept it so the
    # fake is a true drop-in.
    parser.add_argument("--output-file", type=Path, default=None)
    return parser


def _materialise_stdin_prompt(args: argparse.Namespace, scratch: Path) -> None:
    """Give the stdin prompt a path, because the handlers want one.

    Two handlers (verifier, probe_retrieval) re-read ``args.prompt_file``
    rather than taking the already-read text, so the cheapest way to support
    the real CLI's stdin fallback is to write stdin to a scratch file and let
    every handler stay path-based.
    """
    if args.prompt_file is not None:
        return
    staged = scratch / "prompt-from-stdin.md"
    staged.write_text(sys.stdin.read(), encoding="utf-8")
    args.prompt_file = staged


def _batch_index_for(args: argparse.Namespace) -> int | None:
    if args.batch_index is not None:
        return args.batch_index
    if args.cost_sidecar is None:
        return None
    match = re.search(r"-batch-(\d+)\.json$", args.cost_sidecar.name)
    return int(match.group(1)) if match else None


def _run_stage(args: argparse.Namespace) -> _StageOutcome:
    """Run one stage, converting its refusals into an outcome record.

    The failure path used to ``return 2`` from ``main`` before the sidecar
    block ran, so a fake stage that failed left no telemetry at all and the
    real dispatcher's ``status: "failed"`` contract was never exercised
    end to end (issue #262).
    """
    scenario = "unknown"
    cycle = 1
    try:
        scenario = _resolve_scenario(args.stage)
        prompt_text = args.prompt_file.read_text(encoding="utf-8")
        cycle = _parse_cycle_from_prompt(prompt_text) or 1
        handler = _STAGE_HANDLERS.get(args.stage)
        if handler is None:
            _reject_unknown_stage(args.stage)
        else:
            handler(args, scenario, prompt_text)
    except (FileNotFoundError, ValueError) as exc:
        print(f"fake_agent ERROR: {exc}", file=sys.stderr)
        return _StageOutcome(2, cycle, scenario, error=str(exc))
    return _StageOutcome(0, cycle, scenario)


def _write_outcome_sidecar(args: argparse.Namespace, outcome: _StageOutcome) -> None:
    if args.cost_sidecar is None:
        return
    _write_cost_sidecar_v11(
        args.cost_sidecar,
        stage=args.stage,
        cycle=outcome.cycle,
        scenario=outcome.scenario,
        batch_index=_batch_index_for(args),
        topic_count=args.topic_count,
        status="ok" if outcome.exit_code == 0 else "failed",
        exit_code=outcome.exit_code,
        stderr_excerpt=outcome.error,
    )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="fake-agent-stdin-") as scratch:
        _materialise_stdin_prompt(args, Path(scratch))
        outcome = _run_stage(args)
    _write_outcome_sidecar(args, outcome)
    return outcome.exit_code


# ---------------------------------------------------------------------------
# Shim installation helpers
# ---------------------------------------------------------------------------


_SHIM_TEMPLATE = '''#!/usr/bin/env python3
"""Test shim — delegates to tests/_helpers/fake_agent.py.

Installed in place of scripts/agent_call.py by the vault_factory so the
production cycle_runner.py invokes the fake without any source change.

The repo root is resolved at runtime in three strategies (in order):

  1. ``$RESEARCH_FRAMEWORK_REPO_ROOT`` env-var override (CI escape hatch).
  2. Walk up from this file's location looking for the helpers tree.
     Works for any shim living inside the repo (e.g. committed fixture
     vaults under ``tests/fixtures/``).
  3. Fall back to the path baked at install time. This branch is ONLY
     populated when ``install_shim()`` writes the shim OUTSIDE the repo
     tree (typically a pytest ``tmp_path``). For installs INSIDE the
     repo the baked value is ``None`` and the strategy raises a clear
     RuntimeError — Strategy 2 should have succeeded.

This keeps committed fixture shims environment-independent (their
content is stable across worktrees) while still letting tmp_path-based
e2e tests bake an absolute path at install time.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


_BAKED_REPO_ROOT = __FAKE_AGENT_BAKED_REPO_ROOT__


def _resolve_repo_root() -> str:
    """Find a worktree root containing ``tests/_helpers/fake_agent.py``."""
    env_root = os.environ.get("RESEARCH_FRAMEWORK_REPO_ROOT")
    if env_root and (Path(env_root) / "tests" / "_helpers" / "fake_agent.py").is_file():
        return env_root
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "tests" / "_helpers" / "fake_agent.py").is_file():
            return str(parent)
    if _BAKED_REPO_ROOT is not None and (
        Path(_BAKED_REPO_ROOT) / "tests" / "_helpers" / "fake_agent.py"
    ).is_file():
        return _BAKED_REPO_ROOT
    raise RuntimeError(
        "fake-agent shim: could not resolve the research-framework repo root. "
        "Tried (1) $RESEARCH_FRAMEWORK_REPO_ROOT, (2) walking up from "
        f"{Path(__file__).resolve()}, (3) the install-time baked path "
        f"({_BAKED_REPO_ROOT!r}). Set $RESEARCH_FRAMEWORK_REPO_ROOT to a "
        "worktree root containing tests/_helpers/fake_agent.py, or run "
        "the shim from inside the worktree tree."
    )


_REPO_ROOT = _resolve_repo_root()

if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
# pythonpath for any nested subprocess the fake might spawn (it doesn't,
# but a future change could).
existing = os.environ.get("PYTHONPATH", "")
parts = existing.split(os.pathsep) if existing else []
if _REPO_ROOT not in parts:
    os.environ["PYTHONPATH"] = os.pathsep.join([_REPO_ROOT] + parts)

from tests._helpers import fake_agent  # noqa: E402


# Duck-typed AgentCallResult — matches the shape that
# ``scripts/agent_call.AgentCallResult`` exposes (stdout, stderr,
# exit_code). plan_narrator.prepend_narrative reads only ``stdout`` and
# ``exit_code``, so a SimpleNamespace is enough. Installed alongside
# ``main`` so callers that import this module (e.g. plan_narrator's
# in-process bootstrap) get a working ``dispatch`` without spawning
# the real ``claude``/``codex`` binary. See spec 025 A1 contract and
# fake-agent.contract.md.
from types import SimpleNamespace  # noqa: E402


def _allocate_fake_sidecar_path(cycle_dir: Path, stage: str) -> Path:
    agent_calls = cycle_dir / "agent-calls"
    agent_calls.mkdir(parents=True, exist_ok=True)
    base = agent_calls / f"{stage}.json"
    if not base.exists():
        return base
    n = 2
    while (agent_calls / f"{stage}-{n}.json").exists():
        n += 1
    return agent_calls / f"{stage}-{n}.json"


def dispatch(stage, prompt, *, tier="standard", agent=None, model=None,
             vault_dir=None, cycle_dir=None, timeout_s=None):
    """Test-mode dispatch — returns canned output for known stages.

    The signature mirrors ``scripts/agent_call.dispatch`` parameter for
    parameter, ``model`` included: ``processors/extract.py`` passes it on
    every call, so without it the extract seam TypeErrored under the fake and
    the extract tests had to stub the bootstrap rather than exercise the shim
    (issue #262). ``tests/_helpers/test_fake_agent_parity.py`` derives the
    expected parameter set from the real function and fails on drift.
    """
    del prompt, agent, model, timeout_s
    cycle_num = 1
    if cycle_dir is not None:
        for part in cycle_dir.parts:
            if part.startswith("cycle-") and part[6:].isdigit():
                cycle_num = int(part[6:])
                break
    if stage in ("plan_narrator", "research_plan_narrator"):
        stdout = (
            f"Cycle {cycle_num} priority rationale "
            "(fake-agent canned narrator)."
        )
        exit_code = 0
    elif stage == "probe_retrieval":
        stdout = '{"probes": {}}'
        exit_code = 0
    else:
        return SimpleNamespace(
            stdout="",
            stderr=f"fake-agent.dispatch: stage {stage!r} has no in-process handler",
            exit_code=1,
            cost_usd=0.0,
            tokens_in=0,
            tokens_out=0,
            latency_ms=0,
        )
    if cycle_dir is not None:
        sidecar_path = _allocate_fake_sidecar_path(cycle_dir, stage)
        # Qualified: this file is a shim, not the fake module. Only
        # ``fake_agent`` and ``SimpleNamespace`` are imported here, so an
        # unqualified name raises NameError — and every caller of this
        # dispatch (plan_narrator, _probe_staging) swallows Exception into a
        # canned fallback, which is how issue #259 stayed invisible for a
        # release.
        fake_agent._write_cost_sidecar_v11(
            sidecar_path,
            stage=stage,
            cycle=cycle_num,
            scenario="happy",
        )
    return SimpleNamespace(
        stdout=stdout,
        stderr="",
        exit_code=exit_code,
        cost_usd=0.0,
        tokens_in=0,
        tokens_out=0,
        latency_ms=0,
    )


if __name__ == "__main__":
    sys.exit(fake_agent.main(sys.argv[1:]))
'''


def _repo_root() -> Path:
    """Resolve the worktree root containing ``tests/_helpers/fake_agent.py``."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "tests" / "_helpers" / "fake_agent.py").is_file():
            return parent
    raise RuntimeError(
        f"fake_agent: could not infer repo root from {here}; tests/_helpers/ "
        "must live two levels above fake_agent.py"
    )


def render_shim(baked_repo_root: str | None) -> str:
    """Render ``_SHIM_TEMPLATE`` with *baked_repo_root* substituted in.

    Split out of :func:`install_shim` so the committed-fixture guard in
    ``test_fake_agent_shim.py`` can compare bytes against the same rendering
    the installer performs, rather than re-implementing the substitution and
    thereby agreeing with itself (issue #260).
    """
    baked = "None" if baked_repo_root is None else repr(baked_repo_root)
    return _SHIM_TEMPLATE.replace("__FAKE_AGENT_BAKED_REPO_ROOT__", baked)


def install_shim(scripts_dir: Path) -> Path:
    """Overwrite ``scripts_dir/agent_call.py`` with the fake-agent shim.

    The shim is a small Python script that re-execs into this module's
    :func:`main`, so the cycle_runner subprocess sees a normal
    ``agent_call.py``. Returns the path to the installed shim.

    When the target ``scripts_dir`` lives INSIDE the source repo (e.g.
    committed fixture vaults under ``tests/fixtures/``), the shim is
    written with ``_BAKED_REPO_ROOT = None`` so its content is
    environment-independent — Strategy 2 (walk-up) handles those at
    runtime. When the target is OUTSIDE the repo (typically a pytest
    ``tmp_path``), the absolute repo root is baked at install time so
    the shim can find this module via Strategy 3. This keeps committed
    fixture shims byte-stable across worktrees, which means a
    re-install inside conftest.py is a content-no-op as far as
    ``git status`` is concerned (one symptom of the spec-026 fixture
    mutation bug — the full fix lives there). ``test_fake_agent_shim.py``
    enforces that no-op claim against the committed shims; before it existed
    they had drifted 83 lines from this template, so ``build.sh --quality``
    (which copies the committed tree) and pytest (which re-installs) ran two
    different fakes.
    """
    target = scripts_dir / "agent_call.py"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    shim_body = render_shim(_baked_root_for(target))
    target.write_text(shim_body, encoding="utf-8")
    target.chmod(0o755)
    return target


def _baked_root_for(target: Path) -> str | None:
    """Return the repo root to bake into a shim installed at *target* (or None).

    Spec 026 / Principle IV — this is the interception-safety hinge:

    * **Out-of-repo target** (a pytest ``tmp_path`` quality-fixture copy): bake
      the ABSOLUTE repo root. The shim's Strategy-3 import needs it to find
      ``tests/_helpers/fake_agent``; without it the fake-agent interception
      silently breaks and a fixture cycle would reach for a live
      ``claude``/``codex`` (the exact regression
      ``test_fake_agent_interception`` guards).
    * **In-repo target** (a committed fixture vault under ``tests/fixtures/``):
      bake ``None`` so the shim's bytes are identical across worktrees
      (machine-agnostic). Strategy-2 walk-up resolves the module at runtime,
      and a re-install is a ``git status`` no-op.
    """
    repo_root = _repo_root()
    try:
        target.resolve().relative_to(repo_root)
    except ValueError:
        return str(repo_root)
    return None


def cli_path() -> Path:
    """Absolute path to this module's file — handy for diagnostics."""
    return Path(__file__).resolve()


__all__: Iterable[str] = (
    "BATCH_BLOCK_RE",
    "SCENARIOS_ROOT",
    "VALID_SCENARIOS",
    "_STAGE_TO_DIR",
    "cli_path",
    "install_shim",
    "main",
    "opencode_step_finish_ndjson",
    "process_batch",
    "render_shim",
    "write_scout",
)


def opencode_step_finish_ndjson(
    *, tokens_in: int, tokens_out: int, cost: float = 0.0
) -> str:
    """Spec 064: one valid opencode ``--format json`` NDJSON ``step_finish``
    line, mirroring the real event shape (research R1) so hermetic dispatch
    tests can feed ``agent_call._parse_opencode_ndjson`` without a live opencode
    run. ``cost=0.0`` models a local-Ollama ($0) step."""
    return (
        json.dumps(
            {
                "type": "step_finish",
                "part": {
                    "tokens": {
                        "input": tokens_in,
                        "output": tokens_out,
                        "total": tokens_in + tokens_out,
                        "reasoning": 0,
                        "cache": {"write": 0, "read": 0},
                    },
                    "cost": cost,
                },
            }
        )
        + "\n"
    )


if __name__ == "__main__":
    sys.exit(main())
