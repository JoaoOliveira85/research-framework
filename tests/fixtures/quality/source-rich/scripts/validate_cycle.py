#!/usr/bin/env python3
"""Validate a research cycle report against vault state.

Deterministic gate between scout and research phases. Reads a cycle report JSON
produced by an agent, optionally cross-checks against vault metrics, and decides:

    0 — CONTINUE (run the next phase/cycle)
    1 — TERMINATE (a stopping condition is satisfied)
    2 — ABORT    (report is structurally invalid; fix and retry)

Termination conditions:
  A. Max cycles reached (evaluated only on **research** reports — scout runs first
     each cycle; applying A after scout would skip DFS on the final cycle)
  B. No new topics after research AND no unresolved wikilinks remain
  C. Budget cap reached

Required-source list is spec-driven: read from {vault}/_pipeline/spec-parse.json.
Each DataSource with required=true must appear in `sources_consulted` as a key
(name lowercased, spaces → underscores) with `searched: true` (or a reason).

Schema (produced by scout and research agents):
{
    "cycle": 1,
    "phase": "scout" | "research",
    "timestamp": "ISO-8601",
    "prompt": "...",
    "sources_consulted": {
        "<source-key>": {"searched": true, "results_count": 10, ...},
        "<optional>":   {"searched": false, "reason": "not needed"}
    },
    "topics_found": {"new": [...], "existing": [...], "total": N},
    "notes_created": [...],
    "notes_updated": [...],
    "proposed_filenames": [...],          # optional — collision check if present
    "new_wikilinks_discovered": [...],
    "cost_estimate_usd": N.NN,
    "cumulative_cost_usd": N.NN,
    "next_action": "continue" | "terminate",
    "termination_reason": null | "no_new_topics" | "budget_cap" | "max_cycles"
}
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REQUIRED_REPORT_FIELDS = [
    "cycle",
    "phase",
    "timestamp",
    "sources_consulted",
    "topics_found",
    "cost_estimate_usd",
    "cumulative_cost_usd",
]

REQUIRED_REPORT_FIELDS_V2 = [
    "schema_version",
    "cycle",
    "phase",
    "timestamp",
    "dimensions_covered",
    "topics_from_code",
    "intent_from_confluence",
    "sources_consulted",
    "budget_consumed_usd",
]
"""v2 fields required from a **scout** report. Research-phase reports do not
re-emit scout-only fields (``topics_from_code``, ``intent_from_confluence``,
``dimensions_covered``) — that round-trip is a tax the writer agent gets wrong
often enough to crash cycles. See ``REQUIRED_REPORT_FIELDS_V2_RESEARCH`` below."""

REQUIRED_REPORT_FIELDS_V2_RESEARCH = [
    "schema_version",
    "cycle",
    "phase",
    "timestamp",
    "sources_consulted",
]
"""v2 fields required from a **research** (DFS) report. Strict subset of
``REQUIRED_REPORT_FIELDS_V2``: scout-only fields are dropped because the
research stage consumes them rather than producing them.

NOTE: budget reporting is handled by ``BUDGET_FIELDS_V2_RESEARCH`` below
because the DFS prompt template (``templates/prompts/dfs-prompt.md.j2``)
historically asks for ``cost_estimate_usd`` + ``cumulative_cost_usd``,
while the v2 schema names the canonical alias ``budget_consumed_usd``. v0.2.21
through v0.2.24 enforced only the canonical name here, which crashed every
real research-phase cycle because the agent (correctly) emitted the field
names the prompt told it to. v0.2.25 splits the requirement: any ONE of the
three accepted budget fields is enough. See
``tests/scripts/test_validate_cycle_research_schema.py`` for the contract.
"""

BUDGET_FIELDS_V2_RESEARCH = (
    "budget_consumed_usd",
    "cumulative_cost_usd",
    "cost_estimate_usd",
)


def _resolve_budget_v2(report: dict) -> float:
    """H1 fix (spec-019 / 0.2.28): resolve the cumulative budget for a
    v2 research-phase report by trying the three accepted aliases in
    canonical order. Returns ``0.0`` only when ALL aliases are absent
    or non-numeric.

    Pre-v0.2.28, the termination check read ``budget_consumed_usd``
    directly with a default of 0 — silently treating reports that
    emitted ``cumulative_cost_usd`` (the prompt's historical example
    name) as $0 spent, so Condition C never fired.
    """
    for field in BUDGET_FIELDS_V2_RESEARCH:
        value = report.get(field)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


# H3 fix (spec-019 / 0.2.28): map the legacy ``next_action`` +
# ``termination_reason`` shape the DFS prompt's JSON example emitted
# onto the canonical Condition A/B/C strings. To be removed in 0.3.0
# once the prompt has been canonical for one minor version cycle.
_LEGACY_TERMINATION_REASON_TO_CONDITION: dict[str, str] = {
    "A": "A",
    "B": "B",
    "C": "C",
}


def _resolve_termination_v2(report: dict) -> str | None:
    """Return the canonical termination condition string (``"A"`` /
    ``"B"`` / ``"C"``) or ``None`` if neither shape signals a stop.

    Canonical: ``report["termination_condition"]``.
    Legacy (DFS prompt example pre-0.2.28):
        ``next_action == "terminate"`` AND
        ``termination_reason in {"A","B","C"}``.

    Canonical wins when it's a non-None string. When the canonical
    field is absent or explicitly ``None``, we fall through to the
    legacy shape and log a deprecation warning (once per process to
    avoid log spam in cycle loops).
    """
    canonical = report.get("termination_condition")
    if isinstance(canonical, str) and canonical:
        return canonical
    next_action = report.get("next_action")
    reason = report.get("termination_reason")
    if (
        isinstance(next_action, str)
        and next_action.lower() == "terminate"
        and isinstance(reason, str)
    ):
        mapped = _LEGACY_TERMINATION_REASON_TO_CONDITION.get(reason)
        if mapped is not None:
            _warn_deprecated_termination_shape_once()
            return mapped
    return None


_DEPRECATION_WARNED = False


def _warn_deprecated_termination_shape_once() -> None:
    """Emit a one-shot deprecation warning to the ``logging`` channel
    so downstream test harnesses (caplog) can observe it. Process-local
    state: each ``validate_cycle.py`` invocation logs at most once."""
    global _DEPRECATION_WARNED
    if _DEPRECATION_WARNED:
        return
    _DEPRECATION_WARNED = True
    import logging

    logging.warning(
        "validate_cycle: DFS report uses deprecated next_action + "
        "termination_reason fields; please emit canonical "
        "termination_condition instead. The legacy shape will be "
        "removed in 0.3.0. (Spec-019 H3.)"
    )


"""Any ONE of these fields satisfies the budget-reporting requirement for
a research-phase v2 report. ``budget_consumed_usd`` is the canonical
v2-schema name; the other two are the legacy names the DFS prompt template
asks agents to emit, which the orchestrator already reads in
``pipeline/orchestrator.py``. Keeping the three names in sync between the
validator, the prompt, and the orchestrator is enforced by
``tests/scripts/test_prompt_validator_contract.py`` (the seam test added
in v0.2.25)."""

REQUIRED_DIMENSIONS_V2 = {
    "technical",
    "organizational",
    "domain",
    "market",
    "temporal",
}


def source_key(name: str) -> str:
    """Normalize a data-source name to its sources_consulted dict key."""
    return name.strip().lower().replace(" ", "_").replace("-", "_")


@dataclass
class ValidationResult:
    status: str  # CONTINUE, TERMINATE, ABORT
    reason: str
    warnings: list[str]
    errors: list[str]
    metrics_delta: dict[str, Any]


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


#: Source roles that the **scout phase** consults. The scout walks code
#: (``behaviour``) and intent surfaces like Confluence / ADRs / PR
#: conversations (``intent``). External reference documentation
#: (``role: domain`` — Spring docs, OWASP, Oracle Java, etc.) is consulted
#: by the **research phase** when writing notes, not by the scout. This
#: constant drives the spec-019 / 0.2.30 phase-scoped enforcement in
#: ``_spec_data_sources``.
_SCOUT_PHASE_ROLES: frozenset[str] = frozenset({"behaviour", "intent"})


def _spec_data_sources(
    pipeline_dir: Path, *, phase: str | None = None
) -> tuple[list[str], list[str]]:
    """Return (required_keys, optional_keys) from spec-parse.json.

    If spec-parse.json is missing or malformed, returns empty lists — the
    validator falls back to a lenient mode (no source enforcement).

    **Phase scoping (spec-019 / 0.2.30 — fixes the user's H2 trial
    failure)**: when ``phase == "scout"``, sources with ``role`` outside
    ``_SCOUT_PHASE_ROLES`` (today: anything other than ``behaviour`` /
    ``intent``) are excluded from the required list. This honors the
    spec's existing role semantics — domain docs are research-phase
    sources and the scout has no business claiming to have consulted
    them.

    When ``phase is None`` (legacy v1 ``check_termination`` path) OR
    when ``phase == "research"``, every ``required: true`` source is
    included regardless of role. The legacy default preserves
    backwards compatibility with pre-role-aware callers.
    """
    spec = _load_json(pipeline_dir / "spec-parse.json")
    if not spec or not isinstance(spec.get("data_sources"), list):
        return [], []
    required, optional = [], []
    for ds in spec["data_sources"]:
        if not isinstance(ds, dict) or "name" not in ds:
            continue
        # Per the spec schema, ``role`` defaults to ``behaviour`` when
        # absent; pre-role-aware specs are therefore treated as
        # scout-relevant by default — same as the pre-0.2.30 behaviour.
        role = ds.get("role") or "behaviour"
        if phase == "scout" and role not in _SCOUT_PHASE_ROLES:
            # Domain docs source: research-phase enforcement only.
            continue
        key = source_key(ds["name"])
        if ds.get("required", True):
            required.append(key)
        else:
            optional.append(key)
    return required, optional


def _vault_existing_filenames(vault_dir: Path) -> set[str]:
    data = vault_dir / "data_vault"
    if not data.exists():
        return set()
    return {p.name for p in data.rglob("*.md")}


def validate_report_structure(report: dict) -> list[str]:
    errors: list[str] = []
    for field in REQUIRED_REPORT_FIELDS:
        if field not in report:
            errors.append(f"missing required field: {field}")
    phase = report.get("phase")
    if phase not in ("scout", "research"):
        errors.append(f"invalid phase: {phase!r} (must be 'scout' or 'research')")
    return errors


def validate_sources_v2(
    report: dict, required: list[str], optional: list[str]
) -> tuple[list[str], list[str]]:
    """H2 fix (spec-019 / 0.2.28): validate ``sources_consulted`` for
    v2 scout + research reports.

    The v2 scout-prompt example (``scout-prompt.md.j2:269``) emits a
    LIST of strings (``["GitHub repos", "Confluence", ...]``); the v1
    prompt and `validate_sources` expect a DICT. This helper accepts
    both shapes so existing reports keep working but the validator now
    enforces that every required source is named.

    Errors (ABORT-class):
        - sources_consulted is present but neither list nor dict
        - sources_consulted is empty AND the spec lists required sources
        - a required source is not present (by name OR normalized key)
          in the list/dict
    Warnings:
        - dict form: a required source is present but ``searched: false``
          (matches v1 ``validate_sources`` semantics)
        - optional source skipped without a reason (dict form only)
    """
    errors: list[str] = []
    warnings: list[str] = []
    sources = report.get("sources_consulted")
    if sources is None:
        if required:
            errors.append(
                "sources_consulted is missing but spec lists required "
                f"source(s): {required}"
            )
        return errors, warnings
    if not isinstance(sources, (list, dict)):
        errors.append(
            f"sources_consulted must be a list or object (got {type(sources).__name__})"
        )
        return errors, warnings

    # Normalize what we have into a lookup-by-key set + a per-key entry
    # map (None if list-form, dict-value if dict-form). The matcher
    # tolerates either ``payment-repo`` or ``payment_repo`` as keys by
    # indexing each entry under BOTH the as-given lowercased name AND
    # the ``source_key``-normalized form.
    if isinstance(sources, list):
        present: dict[str, object | None] = {}
        for item in sources:
            if isinstance(item, str):
                present[source_key(item)] = None
                present[item.strip().lower()] = None
            elif isinstance(item, dict) and "name" in item:
                present[source_key(item["name"])] = item
                present[str(item["name"]).strip().lower()] = item
    else:  # dict
        present = {}
        for k, v in sources.items():
            k_lower = str(k).strip().lower()
            present[k_lower] = v
            present[source_key(str(k))] = v

    for key in required:
        key_l = key.lower()
        if key_l not in present:
            errors.append(f"required source '{key}' not in sources_consulted")
            continue
        entry = present.get(key_l)
        if isinstance(entry, dict):
            if not entry.get("searched", False):
                reason = entry.get("reason", "no reason given")
                warnings.append(f"required source '{key}' was not searched: {reason}")

    for key in optional:
        key_l = key.lower()
        entry = present.get(key_l)
        if isinstance(entry, dict) and not entry.get("searched", False):
            if not entry.get("reason"):
                warnings.append(f"optional source '{key}' skipped without reason")
    return errors, warnings


def validate_sources(
    report: dict, required: list[str], optional: list[str]
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    sources = report.get("sources_consulted") or {}
    if not isinstance(sources, dict):
        errors.append("sources_consulted must be an object")
        return errors, warnings

    for key in required:
        if key not in sources:
            errors.append(f"required source '{key}' not in sources_consulted")
            continue
        entry = sources[key]
        if not isinstance(entry, dict):
            errors.append(f"sources_consulted['{key}'] must be an object")
            continue
        if not entry.get("searched", False):
            reason = entry.get("reason", "no reason given")
            warnings.append(f"required source '{key}' was not searched: {reason}")

    for key in optional:
        if key in sources and not sources[key].get("searched", False):
            if not sources[key].get("reason"):
                warnings.append(f"optional source '{key}' skipped without reason")

    # At least one external source consulted with results (constitution VII).
    # We identify externality via the spec if available; otherwise skip this check.
    return errors, warnings


def check_termination(
    report: dict,
    metrics: dict | None,
    required_sources: list[str],
    optional_sources: list[str],
    max_cycles: int,
    budget_cap: float,
    vault_dir: Path | None,
) -> ValidationResult:
    errors = validate_report_structure(report)
    src_errors, warnings = validate_sources(report, required_sources, optional_sources)
    errors.extend(src_errors)

    # Filename collision check (constitutional requirement VI)
    proposed = report.get("proposed_filenames") or []
    if proposed and vault_dir is not None:
        existing = _vault_existing_filenames(vault_dir)
        collisions = [name for name in proposed if name in existing]
        if collisions:
            errors.append(
                f"proposed_filenames collision with existing notes: {collisions}"
            )

    if errors:
        return ValidationResult(
            status="ABORT",
            reason=f"Report has {len(errors)} structural error(s)",
            warnings=warnings,
            errors=errors,
            metrics_delta={},
        )

    cycle = int(report.get("cycle", 0))
    phase = report["phase"]
    topics = report.get("topics_found") or {}
    new_topics = topics.get("new") or []
    cumulative_cost = float(report.get("cumulative_cost_usd", 0) or 0)
    notes_created = report.get("notes_created") or []
    notes_updated = report.get("notes_updated") or []

    metrics_delta: dict[str, Any] = {}
    if metrics:
        metrics_delta = {
            "pre_active_notes": metrics.get(
                "active_notes", metrics.get("note_count", 0)
            ),
            "notes_created_this_cycle": len(notes_created),
            "notes_updated_this_cycle": len(notes_updated),
            "new_topics_count": len(new_topics),
        }

    # Condition A: max cycles — research phase only (see module docstring).
    if phase == "research" and cycle >= max_cycles:
        return ValidationResult(
            status="TERMINATE",
            reason=f"Condition A: reached max cycles ({cycle}/{max_cycles})",
            warnings=warnings,
            errors=[],
            metrics_delta=metrics_delta,
        )

    # Condition C: budget cap
    if cumulative_cost >= budget_cap:
        return ValidationResult(
            status="TERMINATE",
            reason=(
                f"Condition C: budget cap reached "
                f"(${cumulative_cost:.2f} / ${budget_cap:.2f})"
            ),
            warnings=warnings,
            errors=[],
            metrics_delta=metrics_delta,
        )

    # Condition B: no new topics after research AND no unresolved references
    if phase == "research" and len(new_topics) == 0:
        if metrics:
            unresolved = metrics.get(
                "unresolved_references",
                metrics.get("unresolved_wikilinks", []),
            )
            # unresolved_wikilinks in research-framework's vault_metrics is an int count, not a list
            if isinstance(unresolved, int):
                unresolved_count = unresolved
                unresolved_list: list[str] = []
            else:
                unresolved_list = list(unresolved or [])
                unresolved_count = len(unresolved_list)

            if unresolved_count > 0:
                preview = ", ".join(unresolved_list[:5]) if unresolved_list else ""
                warnings.append(
                    f"agent reports no new topics but vault has "
                    f"{unresolved_count} unresolved reference(s)"
                    + (f": {preview}" if preview else "")
                )
                return ValidationResult(
                    status="CONTINUE",
                    reason=(
                        "No new topics reported but unresolved references remain "
                        "— needs another cycle"
                    ),
                    warnings=warnings,
                    errors=[],
                    metrics_delta=metrics_delta,
                )

        return ValidationResult(
            status="TERMINATE",
            reason="Condition B: no new relevant topics found after research",
            warnings=warnings,
            errors=[],
            metrics_delta=metrics_delta,
        )

    return ValidationResult(
        status="CONTINUE",
        reason=(
            f"Cycle {cycle}/{max_cycles}: "
            f"{len(new_topics)} new topic(s), "
            f"{len(notes_created)} note(s) created, "
            f"${cumulative_cost:.2f} / ${budget_cap:.2f} budget"
        ),
        warnings=warnings,
        errors=[],
        metrics_delta=metrics_delta,
    )


def _spec_primary_repos(pipeline_dir: Path) -> list[dict]:
    """Return the full enumerated repo records from the code-first primary
    data source. We need both ``url`` (canonical) AND ``local_path``
    (on-disk anchor) to build the validator's allow-list — see
    ``_repo_match_signatures``.
    """
    spec = _load_json(pipeline_dir / "spec-parse.json")
    if not spec or not isinstance(spec.get("data_sources"), list):
        return []
    for ds in spec["data_sources"]:
        if not isinstance(ds, dict):
            continue
        if ds.get("priority") == 1 and ds.get("role") == "behaviour":
            return [r for r in (ds.get("repos") or []) if isinstance(r, dict)]
    return []


def _repo_match_signatures(repos: list[dict]) -> list[tuple[str, ...]]:
    """Return path-segment tuples that a ``source_file`` may "contain" (as a
    contiguous subsequence of its own segments) to count as belonging to one
    of the enumerated repos.

    **Why two signatures per repo.** The spec gives two valid representations
    of the same repo:

    1. ``url`` — ``https://github.com/<org>/<repo>`` → canonical tuple
       ``(<org>, <repo>)``. This is what scout-prompt's JSON example shows
       (``"source_file": "<org>/<repo>/<path>"``).
    2. ``local_path`` — ``/Users/<...>/<org>/<...>/<repo>``. The scout sees
       this in its prompt too (the template renders it via
       ``{% if repo.local_path %}``) and naturally emits paths in this shape
       when the repo lives under an extra wrapper directory on disk
       (e.g., ``/Users/dev/acme-corp/backend/oebh-service``).

    v0.2.27 fixes the **fifth seam bug** in the 0.2.21 → 0.2.26 chain: the
    v0.2.26 validator only knew the URL shape (``acme-corp/oebh-service``)
    and rejected the local-path shape (``acme-corp/backend/oebh-service``)
    with "topic source_file not under enumerated repo", aborting otherwise
    valid scout reports. By emitting BOTH signatures and matching via
    contiguous-subsequence check, the validator accepts either shape the
    scout chose while still rejecting truly-wrong-repo paths.
    """
    signatures: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()

    def _add(sig: tuple[str, ...]) -> None:
        if len(sig) >= 2 and sig not in seen:
            signatures.append(sig)
            seen.add(sig)

    for repo in repos:
        url = (repo.get("url") or "").strip()
        local = (repo.get("local_path") or "").strip()
        repo_name = (repo.get("name") or "").strip()

        # URL-shape signature: ('acme-corp', 'oebh-service')
        url_first_seg: str | None = None
        if url:
            stripped = url.removeprefix("https://github.com/").strip("/")
            url_segs = tuple(s for s in stripped.split("/") if s)
            _add(url_segs)
            if url_segs:
                url_first_seg = url_segs[0]

        # Local-path-shape signature: ('acme-corp', 'backend', 'oebh-service')
        # Anchor on the URL's first segment (e.g., the org). Fall back to
        # ``repo_name`` if there's no URL anchor available.
        if local:
            local_segs = [s for s in local.split("/") if s]
            anchor = url_first_seg or repo_name or None
            if anchor and anchor in local_segs:
                start = local_segs.index(anchor)
                _add(tuple(local_segs[start:]))
            elif repo_name and repo_name in local_segs:
                # No URL anchor; take just the repo name as a one-segment
                # signature wrapped in a "trust" pair with whatever segment
                # immediately precedes it (avoids accidental single-segment
                # matches on a bare directory name).
                idx = local_segs.index(repo_name)
                if idx >= 1:
                    _add(tuple(local_segs[idx - 1 : idx + 1]))

    return signatures


def _source_file_matches_repo(
    source_file: str, signatures: list[tuple[str, ...]]
) -> bool:
    """True if ``source_file`` belongs to any enumerated repo.

    Match semantics: the source_file's path segments must contain at least
    one signature as a **contiguous subsequence**. We strip URL schemes
    (``file://``, ``https://``, ``http://``) so a fully-qualified
    ``file:///Users/dev/acme-corp/backend/oebh-service/README.md`` is
    treated the same as the bare ``acme-corp/backend/oebh-service/README.md``.

    This is strictly more lenient than v0.2.26's "startswith OR substring"
    check on the local-path shape (which silently failed the scout's natural
    output), and strictly stricter on cross-repo confusion — a path like
    ``acme-corp/some-other-service/README.md`` doesn't contain
    ``(acme-corp, oebh-service)`` as a contiguous run and is still
    rejected.
    """
    if not source_file or not signatures:
        return False
    cleaned = source_file
    for prefix in ("file://", "https://", "http://"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
            break
    source_segs = [s for s in cleaned.split("/") if s]
    for sig in signatures:
        n = len(sig)
        if n == 0 or n > len(source_segs):
            continue
        for i in range(len(source_segs) - n + 1):
            if tuple(source_segs[i : i + n]) == sig:
                return True
    return False


def validate_report_structure_v2(report: dict) -> list[str]:
    """Structural check for v2 reports, dispatched on ``phase``.

    Scout reports must populate every field in ``REQUIRED_REPORT_FIELDS_V2``
    (they're the ones generating ``topics_from_code`` / ``intent_from_confluence``
    / ``dimensions_covered``). Research-phase reports use the strict subset in
    ``REQUIRED_REPORT_FIELDS_V2_RESEARCH``; demanding the scout-only fields from
    a DFS report was a v0.2.19 footgun that aborted cycles when the writer
    agent (correctly) omitted them.
    """
    errors: list[str] = []
    phase = report.get("phase")
    if phase not in ("scout", "research"):
        errors.append(f"invalid phase: {phase!r} (must be 'scout' or 'research')")
    required = (
        REQUIRED_REPORT_FIELDS_V2_RESEARCH
        if phase == "research"
        else REQUIRED_REPORT_FIELDS_V2
    )
    for field in required:
        if field not in report:
            errors.append(f"missing required v2 field: {field}")
    # Research-phase budget reporting: any one of the three accepted field
    # names is sufficient (see BUDGET_FIELDS_V2_RESEARCH docstring for the
    # v0.2.21–0.2.24 regression this fixes). Scout reports keep the strict
    # ``budget_consumed_usd`` requirement already enforced via
    # REQUIRED_REPORT_FIELDS_V2.
    if phase == "research" and not any(f in report for f in BUDGET_FIELDS_V2_RESEARCH):
        errors.append(
            "missing required v2 budget field: one of "
            + ", ".join(BUDGET_FIELDS_V2_RESEARCH)
            + " must be present"
        )
    return errors


def check_termination_v2(
    report: dict,
    max_cycles: int,
    budget_cap: float,
    vault_dir: Path | None,
    pipeline_dir: Path | None,
) -> ValidationResult:
    """v2 (code-first) cycle validation. See contracts/scout-report.v2.schema.md."""
    errors = validate_report_structure_v2(report)
    warnings: list[str] = []

    if errors:
        return ValidationResult(
            status="ABORT",
            reason=f"Report has {len(errors)} structural error(s)",
            warnings=warnings,
            errors=errors,
            metrics_delta={},
        )

    # topics_from_code is a scout-only invariant. Research reports consume
    # scout's list; demanding they re-emit it caused the 0.2.19 cycle-6 abort.
    phase = report.get("phase")
    topics_from_code = report.get("topics_from_code") or []
    if phase == "scout" and not topics_from_code:
        errors.append("code-first ordering violated: topics_from_code is empty")

    # All five dimensions must be covered in scout reports
    if phase == "scout":
        covered = set(report.get("dimensions_covered") or [])
        missing = REQUIRED_DIMENSIONS_V2 - covered
        if missing:
            errors.append(f"scout missing required dimension(s): {sorted(missing)}")

    # Every intent must have a matching code topic
    code_ids = {t.get("id") for t in topics_from_code if isinstance(t, dict)}
    for intent in report.get("intent_from_confluence") or []:
        if not isinstance(intent, dict):
            continue
        parent = intent.get("parent_code_topic_id")
        if not parent or parent not in code_ids:
            summary = intent.get("intent_summary", "")[:60]
            errors.append(
                f"intent without matching code topic: "
                f"parent_code_topic_id={parent!r} summary={summary!r}"
            )

    # H2 fix (spec-019 / 0.2.28): v2 sources_consulted enforcement.
    # Pre-0.2.28 this was simply not checked for v2 reports — an agent
    # could emit ``sources_consulted: []`` or ``{}`` and the cycle still
    # advanced. Now we honor the spec's ``required: true`` flag for both
    # scout AND research v2 reports, accepting either list or dict shape.
    #
    # Phase-scoped (spec-019 / 0.2.30 — the H2 trial-run fix): scout
    # reports only require sources with role in {behaviour, intent};
    # role: domain (external reference docs like Spring / OWASP / Oracle
    # Java) is a research-phase responsibility. See _spec_data_sources
    # docstring and the user's 2026-05-18 cycle 1 failure for context.
    if pipeline_dir:
        required, optional = _spec_data_sources(pipeline_dir, phase=phase)
        if required or optional:
            src_errors, src_warnings = validate_sources_v2(report, required, optional)
            errors.extend(src_errors)
            warnings.extend(src_warnings)

    # Every code-sourced topic must point at a file under an enumerated repo.
    # v0.2.27: accept BOTH URL-shape and local-path-shape source_files (the
    # scout sees both representations in its prompt and may emit either) —
    # see _repo_match_signatures docstring for the fifth-seam-bug history.
    if pipeline_dir:
        repos = _spec_primary_repos(pipeline_dir)
        signatures = _repo_match_signatures(repos)
        if signatures:  # Only enforce if we know the spec's repo list
            for topic in topics_from_code:
                if not isinstance(topic, dict):
                    continue
                source_file = topic.get("source_file", "")
                if not _source_file_matches_repo(source_file, signatures):
                    errors.append(
                        f"topic source_file not under enumerated repo: "
                        f"{source_file!r} (id={topic.get('id')})"
                    )

    # Filename collision check (constitutional VI)
    proposed = report.get("proposed_filenames") or []
    if proposed and vault_dir is not None:
        existing = _vault_existing_filenames(vault_dir)
        collisions = [name for name in proposed if name in existing]
        if collisions:
            errors.append(
                f"proposed_filenames collision with existing notes: {collisions}"
            )

    if errors:
        return ValidationResult(
            status="ABORT",
            reason=f"v2 report has {len(errors)} structural error(s)",
            warnings=warnings,
            errors=errors,
            metrics_delta={},
        )

    # Termination conditions
    cycle = int(report.get("cycle", 0))
    phase = str(report.get("phase") or "")
    # H1 fix (spec-019 / 0.2.28): resolve budget across all three
    # accepted aliases, not just budget_consumed_usd. See
    # _resolve_budget_v2 docstring for the rationale.
    cumulative_cost = _resolve_budget_v2(report)
    # H3 fix (spec-019 / 0.2.28): accept BOTH canonical
    # termination_condition AND the legacy next_action +
    # termination_reason shape the pre-0.2.28 DFS prompt example
    # emitted. See _resolve_termination_v2 docstring.
    termination = _resolve_termination_v2(report)

    # Condition A: max cycles — research phase only (scout precedes DFS in run_cycle.sh).
    if phase == "research" and (termination == "A" or cycle >= max_cycles):
        return ValidationResult(
            status="TERMINATE",
            reason=f"Condition A: reached max cycles ({cycle}/{max_cycles})",
            warnings=warnings,
            errors=[],
            metrics_delta={},
        )

    if termination == "C" or cumulative_cost >= budget_cap:
        return ValidationResult(
            status="TERMINATE",
            reason=(
                f"Condition C: budget cap reached "
                f"(${cumulative_cost:.2f} / ${budget_cap:.2f})"
            ),
            warnings=warnings,
            errors=[],
            metrics_delta={},
        )

    if termination == "B":
        return ValidationResult(
            status="TERMINATE",
            reason="Condition B: no new relevant topics after research",
            warnings=warnings,
            errors=[],
            metrics_delta={},
        )

    return ValidationResult(
        status="CONTINUE",
        reason=(
            f"v2 cycle {cycle}/{max_cycles}: "
            f"{len(topics_from_code)} code topic(s), "
            f"{len(report.get('intent_from_confluence') or [])} intent(s), "
            f"${cumulative_cost:.2f} / ${budget_cap:.2f} budget"
        ),
        warnings=warnings,
        errors=[],
        metrics_delta={},
    )


def _print_result(result: ValidationResult) -> None:
    bar = "=" * 60
    print(f"\n{bar}")
    print(f"CYCLE VALIDATION: {result.status}")
    print(bar)
    print(f"Reason: {result.reason}")
    if result.warnings:
        print(f"\nWarnings ({len(result.warnings)}):")
        for w in result.warnings:
            print(f"  WARN: {w}")
    if result.errors:
        print(f"\nErrors ({len(result.errors)}):")
        for e in result.errors:
            print(f"  ERROR: {e}")
    if result.metrics_delta:
        print("\nDelta:")
        for k, v in result.metrics_delta.items():
            print(f"  {k}: {v}")
    print(bar)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a research cycle report.")
    parser.add_argument("report_path", type=Path, help="Path to cycle report JSON")
    parser.add_argument(
        "--vault",
        type=Path,
        default=None,
        help="Vault root (default: inferred from report_path parent chain)",
    )
    parser.add_argument("--max-cycles", type=int, default=5)
    parser.add_argument("--budget-cap", type=float, default=250.0)
    args = parser.parse_args()

    if not args.report_path.exists():
        print(f"ERROR: report not found: {args.report_path}", file=sys.stderr)
        return 2

    try:
        report = json.loads(args.report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"ERROR: JSON parse error in {args.report_path}: {e}", file=sys.stderr)
        return 2
    if not isinstance(report, dict):
        print("ERROR: cycle report must be a JSON object", file=sys.stderr)
        return 2

    vault_dir = args.vault
    if vault_dir is None:
        # Infer: report is typically at {vault}/_pipeline/cycles/{name}.json
        candidate = args.report_path.resolve().parent.parent.parent
        if (candidate / "_pipeline").exists():
            vault_dir = candidate

    pipeline_dir = vault_dir / "_pipeline" if vault_dir else None

    # Dispatch on schema_version. v2 reports use the code-first schema; absence
    # of the field or "1.0" falls through to the v1 handler (back-compat).
    schema_version = str(report.get("schema_version", "1.0"))
    if schema_version.startswith("2"):
        result = check_termination_v2(
            report,
            args.max_cycles,
            args.budget_cap,
            vault_dir,
            pipeline_dir,
        )
    else:
        metrics = (
            _load_json(pipeline_dir / "vault-metrics.json") if pipeline_dir else None
        )
        required, optional = (
            _spec_data_sources(pipeline_dir) if pipeline_dir else ([], [])
        )
        result = check_termination(
            report,
            metrics,
            required,
            optional,
            args.max_cycles,
            args.budget_cap,
            vault_dir,
        )
    _print_result(result)
    # spec-019 / 0.2.29: emit a machine-readable sidecar next to the report
    # so cycle_runner.py can drive a correction loop on structural errors
    # instead of aborting the whole cycle on the first attempt. The sidecar
    # mirrors what _print_result writes to stdout, but as JSON so callers
    # don't have to scrape "ERROR:" lines from a log stream.
    sidecar_path = args.report_path.with_suffix(
        args.report_path.suffix + ".validation.json"
    )
    try:
        sidecar_path.write_text(
            json.dumps(
                {
                    "status": result.status,
                    "reason": result.reason,
                    "errors": list(result.errors),
                    "warnings": list(result.warnings),
                    "metrics_delta": dict(result.metrics_delta),
                    "report_path": str(args.report_path),
                    "schema_version": schema_version,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        # Sidecar emission is best-effort; never block validation on a
        # writable-disk problem the operator can debug separately.
        pass
    return {"CONTINUE": 0, "TERMINATE": 1, "ABORT": 2}.get(result.status, 2)


if __name__ == "__main__":
    sys.exit(main())
