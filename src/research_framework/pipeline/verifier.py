"""Verifier stage: per-note quality check via agent_call.py."""

from __future__ import annotations

import difflib
import json
import logging
import re
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from research_framework._assets import skill_instructions
from research_framework.pipeline import update_outcomes
from research_framework.pipeline.process_tree import (
    popen_session,
    terminate_process_tree,
)
from research_framework.pipeline.settings import SettingsError, load_vault_settings
from research_framework.vault import note_currency as nc
from research_framework.vault.frontmatter import (
    FrontmatterParseError,
    parse_frontmatter_str,
)

_LOG = logging.getLogger(__name__)


@dataclass
class VerifierVerdict:
    note_path: str
    status: str  # "verified" | "pending" | "rejected"
    violations: list[dict] = field(default_factory=list)
    suggested_fix: str | None = None
    # Spec 087: flaws the note already had before the update being judged. They
    # do not reject it; they are recorded (update-outcomes sidecar) and counted.
    pre_existing: list[dict] = field(default_factory=list)


@dataclass
class VerifierSummary:
    cycle: int
    verdicts: list[VerifierVerdict] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "cycle": self.cycle,
            "timestamp": self.timestamp,
            "verdicts": [
                {
                    "note_path": v.note_path,
                    "status": v.status,
                    "violations": v.violations,
                    "suggested_fix": v.suggested_fix,
                    **({"pre_existing": v.pre_existing} if v.pre_existing else {}),
                }
                for v in self.verdicts
            ],
        }


def deterministic_credibility_violations(
    vault_dir: Path,
    note_rel: str,
    note_text: str,
) -> list[dict[str, str]]:
    """Return IX-credibility-* shape violations (spec 055 FR-007; no LLM)."""
    from research_framework.spec.parser import parse as parse_spec
    from research_framework.vault.credibility import (
        build_credibility_context,
        validate_credibility_shape,
    )

    try:
        fm, _body = parse_frontmatter_str(note_text)
    except FrontmatterParseError:
        return []
    if not fm:
        return []
    spec_path = vault_dir / "research.spec.md"
    if not spec_path.is_file():
        return []
    try:
        spec = parse_spec(spec_path)
    except Exception:
        return []
    ctx = build_credibility_context(spec, vault_dir)
    return validate_credibility_shape(
        fm,
        ctx,
        location=f"note:{note_rel}",
    )


def deterministic_wikilink_violations(
    vault_dir: Path,
    note_rel: str,
    note_text: str,
) -> list[dict[str, str]]:
    """Return the IX-wikilink-title-corruption violation, if any (067 FR3; no LLM).

    Deterministic backstop for the rc7 ``[[cache-aside pattern]] Theorem``
    corruption: FAIL when the **first** body ``[[TOKEN]]`` is the note's own
    title-acronym resolving (via the deterministic acronym map) to a stem that is
    NOT the note's own title-stem. A first link to a genuinely different concept
    never fires. Mirrors :func:`deterministic_credibility_violations`.
    """
    from research_framework.pipeline.wikilinks import (
        _derive_acronym_or_upper,
        build_acronym_map,
        first_body_wikilink,
        title_self_acronyms,
    )

    try:
        fm, body = parse_frontmatter_str(note_text)
    except FrontmatterParseError:
        return []
    self_stem = Path(note_rel).stem.lower()
    title = str((fm or {}).get("title") or Path(note_rel).stem.replace("-", " "))
    self_acronyms = title_self_acronyms(title)
    if not self_acronyms:
        return []
    first = first_body_wikilink(body if fm else note_text)
    if not first:
        return []
    upper = _derive_acronym_or_upper(first)
    if upper not in self_acronyms:
        return []
    mapping, _ambiguous = build_acronym_map(vault_dir)
    fallback_stem = first.strip().lower()
    resolved = mapping.get(upper, fallback_stem)
    if resolved == self_stem:
        return []
    return [
        {
            "rule_id": "IX-wikilink-title-corruption",
            "location": f"note:{note_rel} first-wikilink:[[{first}]]",
            "subject": first.strip().lower(),
            "message": (
                f"first body wikilink [[{first}]] renames this note's own title "
                f"'{title}' (acronym {upper}) to '{resolved}'"
            ),
        }
    ]


def violation_key(violation: dict[str, Any]) -> tuple[str, str]:
    """Which flaw a violation is, for telling an old one from a new one.

    The key is the rule and its SUBJECT, the thing the rule fired about:

    * ``IX-credibility-*`` / ``IX-citation-malformed``: the cited URL;
    * ``IX-wikilink-title-corruption``: the offending first wikilink's text;
    * anything else (model-reported rules, too): the message, whitespace and case
      folded.

    The location is not part of the key (a note's path and a line move);
    multiplicity is: see :func:`split_pre_existing`.
    """
    subject = violation.get("subject") or violation.get("message") or ""
    return (
        str(violation.get("rule_id") or ""),
        " ".join(str(subject).split()).lower(),
    )


def split_pre_existing(
    current: list[dict[str, Any]], committed: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(new, pre_existing)``: a violation is pre-existing when the committed
    version fires the same rule about the same subject, once per occurrence it
    had. A second occurrence, a new subject or a different rule is new."""
    allowance = Counter(violation_key(v) for v in committed)
    new: list[dict[str, Any]] = []
    old: list[dict[str, Any]] = []
    for v in current:
        key = violation_key(v)
        if allowance[key] > 0:
            allowance[key] -= 1
            old.append(v)
        else:
            new.append(v)
    return new, old


def _pre_existing_record(violation: dict[str, Any]) -> dict[str, str]:
    rule = str(violation.get("rule_id") or "model")
    detail = str(violation.get("message") or violation.get("subject") or "")
    where = str(violation.get("location") or "")
    return {"rule": rule, "detail": f"{detail} ({where})" if where else detail}


CURRENCY_RULE_IDS = ("IX-currency-evidence", "IX-supersession-symmetry")
"""Spec 087 rules a verdict is reached on without a model (FR-007, FR-013)."""

_EVIDENCE_LEVELS = ("primary", "corroborated")


def _head_standing(vault_dir: Path, note_rel: str) -> str | None:
    """The note's ``currency`` at git HEAD, or ``None`` when it had none there."""
    from research_framework.pipeline import vault_git
    from research_framework.vault import note_currency as nc

    head = vault_git.head_content(vault_dir, note_rel)
    if head is None:
        return None
    try:
        head_fm, _ = parse_frontmatter_str(head)
    except FrontmatterParseError:
        return None
    return nc.effective(head_fm)[0]


def _evidence_violation(
    vault_dir: Path,
    note_rel: str,
    fm: dict[str, Any],
    evidence_url: str | None,
    standing: str,
) -> dict[str, str] | None:
    """IX-currency-evidence: why a changed ``superseded``/``retracted`` standing
    is not supported, or ``None`` when its evidence stands."""
    from research_framework.spec.parser import parse as parse_spec
    from research_framework.vault.credibility import (
        CredibilityUnresolved,
        build_credibility_context,
        citation_url,
        effective_level,
        iter_source_url_entries,
    )

    def violation(message: str) -> dict[str, str]:
        return {
            "rule_id": "IX-currency-evidence",
            "location": f"note:{note_rel}",
            "message": f"{standing} without supporting evidence: {message}",
            "severity": "fail",
        }

    if not evidence_url:
        return violation("the update outcome cites no evidence_url")
    cited = next(
        (
            entry
            for entry in iter_source_url_entries(fm)
            if (citation_url(entry) or "").strip() == evidence_url.strip()
        ),
        None,
    )
    if cited is None:
        return violation(f"{evidence_url} is not among the note's source_urls")
    spec_path = vault_dir / "research.spec.md"
    try:
        ctx = build_credibility_context(parse_spec(spec_path), vault_dir)
        level = effective_level(cited, fm, ctx)
    except CredibilityUnresolved:
        return violation(f"the credibility of {evidence_url} cannot be resolved")
    except Exception as exc:  # no readable spec: nothing to resolve a level with
        return violation(
            f"the credibility of {evidence_url} cannot be resolved ({exc})"
        )
    if level.value not in _EVIDENCE_LEVELS:
        return violation(
            f"{evidence_url} is {level.value}; primary or corroborated is required"
        )
    return None


def deterministic_currency_violations(
    vault_dir: Path,
    note_rel: str,
    note_text: str,
    *,
    evidence_url: str | None = None,
    pending: frozenset[str] = frozenset(),
) -> list[dict[str, str]]:
    """IX-currency-evidence and IX-supersession-symmetry (spec 087; no LLM).

    * **IX-currency-evidence** (fail): a note whose ``currency`` is
      ``superseded`` or ``retracted`` AND differs from its value at git HEAD must
      cite the outcome's ``evidence_url`` among its ``source_urls``, and that
      source must resolve to ``primary`` or ``corroborated``. A note whose
      standing did not change is not judged.
    * **IX-supersession-symmetry** (fail): a note naming X in its successor
      field needs X on disk naming it back in ``supersedes``, and the reverse. A
      partner that is not on disk but which ``pending`` (the cycle's reported
      pending wikilinks) names is tolerated THIS cycle with a ``warn``; a link
      that never becomes symmetric is caught by ``vault_health``'s Currency
      section, which scans every note.
    """
    from research_framework.vault import note_currency as nc

    try:
        fm, _body = parse_frontmatter_str(note_text)
    except FrontmatterParseError:
        return []
    if not fm:
        return []
    out: list[dict[str, str]] = []
    standing = nc.effective(fm)[0]
    if standing in (nc.SUPERSEDED, nc.RETRACTED) and standing != _head_standing(
        vault_dir, note_rel
    ):
        found = _evidence_violation(vault_dir, note_rel, fm, evidence_url, standing)
        if found:
            out.append(found)
    out.extend(_symmetry_violations(vault_dir, note_rel, fm, pending))
    return out


def _symmetry_violations(
    vault_dir: Path, note_rel: str, fm: dict[str, Any], pending: frozenset[str]
) -> list[dict[str, str]]:
    from research_framework.vault import note_currency as nc

    mine = nc.ref_slug(Path(note_rel).stem)
    notes = nc.corpus_notes_by_slug(vault_dir)
    out: list[dict[str, str]] = []
    for field_name, back_field in (
        (nc.SUPERSEDED_BY_FIELD, nc.SUPERSEDES_FIELD),
        (nc.SUPERSEDES_FIELD, nc.SUPERSEDED_BY_FIELD),
    ):
        for ref in nc.refs(fm.get(field_name)):
            location = f"note:{note_rel} {field_name}:{ref}"
            partner = notes.get(ref)
            if partner is None:
                tolerated = ref in pending
                out.append(
                    {
                        "rule_id": "IX-supersession-symmetry",
                        "location": location,
                        "message": (
                            f"{field_name} names {ref!r}, which is not in the vault"
                            + (
                                "; it is reported pending, tolerated for this "
                                "cycle only"
                                if tolerated
                                else ""
                            )
                        ),
                        "severity": "warn" if tolerated else "fail",
                    }
                )
                continue
            try:
                partner_fm, _ = parse_frontmatter_str(partner.read_text("utf-8"))
            except (OSError, FrontmatterParseError):
                partner_fm = {}
            if mine not in nc.refs(partner_fm.get(back_field)):
                out.append(
                    {
                        "rule_id": "IX-supersession-symmetry",
                        "location": location,
                        "message": (
                            f"{field_name} names {ref!r}, but that note's "
                            f"{back_field} does not name this one"
                        ),
                        "severity": "fail",
                    }
                )
    return out


def _merge_verifier_verdict(
    agent_verdict: VerifierVerdict,
    shape_violations: list[dict[str, str]],
) -> VerifierVerdict:
    merged_verdict = _merge_shape(agent_verdict, shape_violations)
    merged_verdict.pre_existing = list(agent_verdict.pre_existing)
    return merged_verdict


def _merge_shape(
    agent_verdict: VerifierVerdict,
    shape_violations: list[dict[str, str]],
) -> VerifierVerdict:
    if not shape_violations:
        return agent_verdict
    # spec 066 FR2: only ``severity: fail`` shape violations force ``rejected``;
    # ``severity: warn`` ones attach as advisory verifier_notes without flipping
    # status. Absent ``severity`` defaults to ``fail`` (back-compat with 055).
    fail_violations = [
        v for v in shape_violations if v.get("severity", "fail") != "warn"
    ]
    warn_violations = [
        v for v in shape_violations if v.get("severity", "fail") == "warn"
    ]
    if fail_violations or agent_verdict.status == "rejected":
        merged = list(fail_violations) + list(warn_violations)
        if agent_verdict.status == "rejected":
            merged.extend(agent_verdict.violations)
        return VerifierVerdict(
            note_path=agent_verdict.note_path,
            status="rejected",
            violations=merged,
            suggested_fix=agent_verdict.suggested_fix,
        )
    # Only advisory warnings, and the agent passed: keep status, attach notes.
    merged = list(warn_violations) + list(agent_verdict.violations)
    return VerifierVerdict(
        note_path=agent_verdict.note_path,
        status=agent_verdict.status,
        violations=merged,
        suggested_fix=agent_verdict.suggested_fix,
    )


def _stamp_frontmatter(note_file: Path, status: str, violations: list[dict]) -> None:
    # Holdout from spec 025 B4 canonical parser migration.
    # Reason: read-modify-write must preserve delimiter layout and partial
    # notes; canonical parse raises on missing closing ``---``.
    """Atomically stamp verifier_status (and verifier_notes) into note frontmatter."""
    text = note_file.read_text(encoding="utf-8")
    if text.startswith("---"):
        # The closing delimiter is a `---` LINE. A `---` inside a value (a slug
        # URL such as `kafka---a-guide`) is not one; splitting on the first
        # substring cut the frontmatter there and moved the rest into the body.
        # It also starts at column 0: an indented `---` is a line of a block
        # scalar, so only trailing whitespace is stripped before comparing.
        lines = text.split("\n")
        close = next(
            (i for i in range(1, len(lines)) if lines[i].rstrip() == "---"), None
        )
        if close is not None:
            # Frontmatter that does not parse to a mapping cannot be stamped.
            # Say so with the one error the stage handles, rather than let a
            # YAML error or a TypeError unwind through it.
            try:
                fm = yaml.safe_load("\n".join(lines[1:close])) or {}
            except yaml.YAMLError as exc:
                raise FrontmatterParseError(
                    f"YAML parse error: {exc}", path=note_file
                ) from exc
            if not isinstance(fm, dict):
                raise FrontmatterParseError(
                    f"frontmatter must be a mapping, got {type(fm).__name__}",
                    path=note_file,
                )
            fm["verifier_status"] = status
            if violations:
                fm["verifier_notes"] = [v.get("message", str(v)) for v in violations]
            elif "verifier_notes" in fm:
                del fm["verifier_notes"]
            new_text = (
                "---\n"
                + yaml.dump(fm, default_flow_style=False, allow_unicode=True)
                + "---\n"
                + "\n".join(lines[close + 1 :])
            )
            from .atomic_write import write_text as _aw_text

            _aw_text(note_file, new_text)
            return

    # No frontmatter: prepend it
    fm: dict[str, Any] = {"verifier_status": status}
    if violations:
        fm["verifier_notes"] = [v.get("message", str(v)) for v in violations]
    new_text = "---\n" + yaml.dump(fm) + "---\n" + text
    from .atomic_write import write_text as _aw_text

    _aw_text(note_file, new_text)


def run_verifier_stage(
    vault_dir: Path,
    cycle_num: int,
    research_report: dict,
    scripts_dir: Path | None = None,
    settings: dict | None = None,
) -> VerifierSummary:
    """Run the verifier stage for all notes in the research report.

    For each note:
      1. Call agent_call.py with --stage verifier, --output-file and
         --cost-sidecar (issue #234 — the sidecar is what makes this stage's
         spend visible to the budget guard).
      2. Parse the verdict JSON.
      3. Stamp the note's frontmatter atomically.
      4. Write a cycle manifest to _pipeline/cycles/cycle-NNN-verifier.json.

    Returns an empty VerifierSummary (no verdicts) if verifier is disabled.
    """
    # --- Settings ---
    if settings is None:
        enabled = True
        verifier_cfg: dict[str, Any] = {}
        try:
            verifier_stage = load_vault_settings(vault_dir).stage("verifier")
            enabled = verifier_stage.enabled
            verifier_cfg = dict(verifier_stage.extras)
        except SettingsError:
            pass
    else:
        verifier_cfg = settings.get("stages", {}).get("verifier", {})
        enabled = verifier_cfg.get("enabled", True)

    summary = VerifierSummary(
        cycle=cycle_num,
        timestamp=datetime.now(UTC).isoformat(),
    )

    if not enabled:
        return summary

    timeout_s = verifier_cfg.get("timeout_s", 600)

    if scripts_dir is None:
        scripts_dir = vault_dir / "scripts"

    note_paths = research_report.get("notes_created", []) + research_report.get(
        "notes_updated", []
    )

    # One sidecar per DISPATCH, not per listed note: a skipped note never
    # calls the agent, so it must not burn a number and leave a gap that reads
    # like a lost cost record.
    call_index = 0
    pending = frozenset(
        nc.ref_slug(w)
        for key in ("new_wikilinks_discovered", "unresolved_wikilinks")
        for w in (research_report.get(key) or [])
        if isinstance(w, str)
    )
    for note_rel in note_paths:
        note_file = vault_dir / note_rel
        if not note_file.exists():
            _LOG.warning("verifier skipping missing note: %s", note_rel)
            summary.verdicts.append(
                VerifierVerdict(note_path=note_rel, status="pending")
            )
            continue

        try:
            note_text = note_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            # Like a missing note: there is nothing to verify, and it is not a
            # reason to leave the cycle's remaining notes unverified.
            _LOG.warning("verifier skipping unreadable note %s: %s", note_rel, exc)
            summary.verdicts.append(
                VerifierVerdict(note_path=note_rel, status="pending")
            )
            continue
        shape_violations = deterministic_credibility_violations(
            vault_dir, note_rel, note_text
        )
        shape_violations += deterministic_wikilink_violations(
            vault_dir, note_rel, note_text
        )
        recorded = update_outcomes.recorded_result(vault_dir, cycle_num, note_rel)
        currency_violations = deterministic_currency_violations(
            vault_dir,
            note_rel,
            note_text,
            evidence_url=(recorded or {}).get("evidence_url"),
            pending=pending,
        )
        shape_violations += currency_violations
        # Spec 087: an update is judged by what it changed. For a note an update
        # batch worked, a flaw the committed version already had (same rule, same
        # subject) does not reject it; it is recorded instead.
        committed_text: str | None = None
        pre_existing: list[dict[str, Any]] = []
        if recorded is not None:
            from research_framework.pipeline import vault_git

            committed_text = vault_git.head_content(vault_dir, note_rel)
        if committed_text is not None:
            old = deterministic_credibility_violations(
                vault_dir, note_rel, committed_text
            ) + deterministic_wikilink_violations(vault_dir, note_rel, committed_text)
            judged = [v for v in shape_violations if v not in currency_violations]
            judged, pre_existing = split_pre_existing(judged, old)
            shape_violations = judged + currency_violations
        if any(
            v["rule_id"] in CURRENCY_RULE_IDS and v.get("severity", "fail") != "warn"
            for v in currency_violations
        ):
            # Spec 087 FR-013: this verdict needs no model and nothing a model
            # says can overturn it, so none is asked.
            verdict = VerifierVerdict(note_path=note_rel, status="pending")
        else:
            call_index += 1
            verdict = _call_verifier(
                vault_dir=vault_dir,
                note_file=note_file,
                note_rel=note_rel,
                scripts_dir=scripts_dir,
                timeout_s=timeout_s,
                cycle_num=cycle_num,
                call_index=call_index,
                committed_text=committed_text,
            )
        verdict = _merge_verifier_verdict(verdict, shape_violations)
        if committed_text is not None:
            verdict.pre_existing = [
                _pre_existing_record(v) for v in pre_existing + verdict.pre_existing
            ]
            if verdict.pre_existing:
                update_outcomes.record_pre_existing(
                    vault_dir, cycle_num, note_rel, verdict.pre_existing
                )
        if verdict.status == "rejected" and recorded is not None:
            # An update outcome that did not stand: its note goes back to HEAD
            # with the other rejected notes, and its entry is open again.
            update_outcomes.reject_outcome(
                vault_dir,
                cycle_num,
                note_rel,
                "; ".join(v.get("message", "") for v in verdict.violations[:3]),
            )

        try:
            _stamp_frontmatter(note_file, verdict.status, verdict.violations)
        except FrontmatterParseError as exc:
            # The note is left as it is: there is no frontmatter to stamp into.
            # One such note is not a reason to leave the cycle's remaining
            # notes unverified and its manifest unwritten.
            _LOG.warning(
                "verifier could not stamp %s — left unstamped: %s", note_rel, exc
            )
        summary.verdicts.append(verdict)

    # Write cycle manifest
    cycles_dir = vault_dir / "_pipeline" / "cycles"
    cycles_dir.mkdir(parents=True, exist_ok=True)
    from .atomic_write import write_json as _write_json

    manifest = cycles_dir / f"cycle-{cycle_num:03d}-verifier.json"
    _write_json(manifest, summary.to_dict())

    return summary


# Regex for fenced JSON blocks. Matches both ```json ... ``` (the codex /
# GPT-4 conventional shape) and ``` ... ``` (untagged fence). Non-greedy so
# we capture the SHORTEST fence (closest matching ```) \u2014 important when
# the agent produces multiple fences and we want the first one.
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)\n\s*```", re.DOTALL)


def _extract_json_blob(text: str) -> dict | None:
    """Extract a JSON object from agent output, tolerating common wrappers.

    The verifier silently fell back to ``pending`` whenever ``json.loads``
    failed on the raw agent response. On codex runtimes (which don't
    auto-load ``SKILL.md``) the agent's natural response is narrative
    text, never strict JSON \u2014 so EVERY note dropped to ``pending`` and
    the stub-free-exit signal became permanently broken (user audit,
    2026-05-18; see :mod:`tests.pipeline.test_verifier_json_extraction`).

    This helper tries, in order:

    1. **Strict parse** of the whole text after stripping whitespace.
       Covers agents that emit pure JSON.
    2. **Code-fenced JSON** via the ``` ```json ... ``` ``` regex, scanning
       fence-by-fence so the FIRST valid fence wins. Skips malformed
       fences and falls through.
    3. **Inline balanced-braces extraction** \u2014 walks the text tracking
       brace depth so nested objects parse intact. Catches the
       narrative-with-embedded-JSON case.

    Returns the parsed dict, or ``None`` when no parseable JSON object is
    found. The verifier contract is that the top-level value is an
    OBJECT (``{verdict, violations, suggested_fix}``); top-level arrays
    or non-object scalars are treated as schema mismatches and return
    ``None`` so the caller defaults to ``pending`` deliberately.
    """
    if not text or not text.strip():
        return None

    # Strategy 1: strict parse. If the WHOLE input parses as valid JSON
    # but isn't a dict (e.g. a top-level array, ``null``, a bare number),
    # return None immediately \u2014 don't fall through to the extraction
    # strategies, which would otherwise pluck a child object out of the
    # array and silently honour a schema mismatch.
    #
    # We use a sentinel object (NOT None, because ``null`` is valid JSON)
    # to tell "parse failed" apart from "parsed to literal None".
    _SENTINEL = object()
    stripped = text.strip()
    try:
        parsed: Any = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        parsed = _SENTINEL  # Fall through to extraction strategies.
    if parsed is not _SENTINEL:
        return parsed if isinstance(parsed, dict) else None

    # Strategy 2: code fences. Iterate so malformed fences don't shortcut us
    # past a later well-formed one.
    for match in _JSON_FENCE_RE.finditer(text):
        candidate = match.group(1).strip()
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            continue

    # Strategy 3: balanced-braces walk over the raw text. Find every
    # candidate ``{...}`` that nests correctly and try to parse each. First
    # success wins. Slow but bounded \u2014 verifier outputs are KB-scale at
    # most.
    for start_idx in range(len(text)):
        if text[start_idx] != "{":
            continue
        depth = 0
        in_string = False
        escape = False
        for end_idx in range(start_idx, len(text)):
            ch = text[end_idx]
            if escape:
                escape = False
                continue
            if ch == "\\" and in_string:
                escape = True
                continue
            if ch == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start_idx : end_idx + 1]
                    try:
                        parsed = json.loads(candidate)
                        if isinstance(parsed, dict):
                            return parsed
                    except (json.JSONDecodeError, ValueError):
                        pass
                    break  # try next start position

    return None


def _verifier_inputs(vault_dir: Path, note_text: str) -> dict[str, Any]:
    """The inputs the verifier rules need for one note, read from the vault.

    The source-policy rule needs the note type's policy and the code source
    URL patterns. They come from the cycle's parsed spec, read through
    :func:`~research_framework.spec.parsed.load_parsed_spec` (#9); a type the
    spec does not declare, or a vault without a readable spec, falls back to
    the framework defaults — the hard note types and
    :data:`~research_framework.spec.validator.DEFAULT_REPO_URL_PATTERNS`.
    """
    from research_framework.spec.parsed import ParsedSpecError, load_parsed_spec
    from research_framework.spec.schema import HARD_NOTE_TYPES
    from research_framework.spec.validator import DEFAULT_REPO_URL_PATTERNS

    try:
        note_type = str(parse_frontmatter_str(note_text)[0].get("type") or "")
    except FrontmatterParseError:
        note_type = ""
    spec: dict[str, Any] = {}
    try:
        spec = load_parsed_spec(vault_dir)
    except ParsedSpecError as exc:
        _LOG.warning("verifier: no readable parsed spec (%s); using defaults", exc)
    declared = {
        str(nt.get("name")): str(nt.get("source_policy") or "")
        for nt in spec.get("note_types") or []
        if isinstance(nt, dict)
    }
    policy = declared.get(note_type) or (
        "hard" if note_type in HARD_NOTE_TYPES else "soft"
    )
    patterns = [str(p) for p in spec.get("code_source_url_patterns") or []]
    return {
        "note_type": note_type,
        "source_policy": policy,
        "code_url_patterns": patterns or list(DEFAULT_REPO_URL_PATTERNS),
    }


def _update_context(committed_text: str, note_content: str) -> str:
    """The prompt section for a note an UPDATE revised (spec 087): the diff
    against the committed version, and the rule that only what the update
    added or changed can be rejected."""
    diff = list(
        difflib.unified_diff(
            committed_text.splitlines(),
            note_content.splitlines(),
            "committed",
            "revised",
            lineterm="",
            n=2,
        )
    )
    shown = "\n".join(diff[:400]) + ("\n… (diff truncated)" if len(diff) > 400 else "")
    return (
        "## This note is an UPDATE to an existing note\n\n"
        "It was revised in place; the committed version is the baseline. The change:\n\n"
        f"```diff\n{shown or '(no textual change)'}\n```\n\n"
        "Judge the UPDATE. Reject only for what the update added or changed, and "
        "for an outcome its evidence does not support. A defect that was already in "
        "the committed version (an old wikilink, an old citation without a "
        "credibility level, a truncated token) is NOT a reason to reject: list it "
        'under `"pre_existing"` in your verdict, never in `"violations"`.\n\n'
    )


def _build_verifier_prompt(
    note_content: str,
    *,
    note_type: str,
    source_policy: str,
    code_url_patterns: Sequence[str],
    committed_text: str | None = None,
) -> str:
    """Wrap the note in the verifier's full instructions and their inputs.

    The prompt is self-contained (#12): it carries the verifier skill's
    rules, read from the package by
    :func:`research_framework._assets.skill_instructions`, instead of
    pointing the agent at a skill file, and the inputs those rules need —
    the artifact type, the note's source policy and the code source URL
    patterns. Without the inputs, "default to reject when uncertain" turned
    the source-policy rule into a rejection of every hard-type note. The
    output schema is restated after the rules because it is the contract
    the framework parses on.
    """
    patterns = "\n".join(f"  - `{p}`" for p in code_url_patterns) or "  - (none)"
    return (
        "# Verifier task\n\n"
        "You are the verifier. Apply the rules below to the note under "
        "review.\n\n"
        "## Inputs\n\n"
        "- Artifact type: `note`\n"
        f"- Note type: `{note_type or '(not declared)'}`\n"
        f"- Source policy: `{source_policy}`\n"
        f"- Code source URL patterns (regular expressions):\n{patterns}\n\n"
        "## Verifier rules\n\n"
        f"{skill_instructions('verifier', heading_offset=2)}\n\n"
        "---\n\n"
        "Your response MUST be a single JSON object matching this schema, "
        "with no surrounding narrative:\n\n"
        "```json\n"
        "{\n"
        '  "verdict": "accept" | "reject",\n'
        '  "violations": [\n'
        '    {"rule_id": "<id>", "location": "<line or section>", "message": "<short>"}\n'
        "  ],\n"
        '  "suggested_fix": "<short string or null>"\n'
        + (
            ',  "pre_existing": [{"rule_id": "<id>", "location": "<where>", '
            '"message": "<short>"}]\n'
            if committed_text is not None
            else ""
        )
        + "}\n"
        "```\n\n"
        "If you must include reasoning, place the JSON inside a "
        "`` ```json `` code fence \u2014 the framework will extract it. Default "
        "to `reject` when uncertain and name the rule that triggered the "
        "concern.\n\n"
        "---\n\n"
        + (
            _update_context(committed_text, note_content)
            if committed_text is not None
            else ""
        )
        + "## Note under review\n\n"
        f"{note_content}\n"
    )


def verifier_sidecar_path(vault_dir: Path, cycle_num: int, call_index: int) -> Path:
    """Where this verifier call's cost sidecar goes (spec 028 §5.1 layout).

    The same ``cycles/cycle-NNN/agent-calls/`` directory the scout and
    note-writer stages already write into, which is the ONLY place
    ``budget_guard.list_sidecars_v11`` globs. One file per note, numbered by
    dispatch order, so per-note verifier spend stays separable and no call
    overwrites another's record.
    """
    return (
        vault_dir
        / "_pipeline"
        / "cycles"
        / f"cycle-{cycle_num:03d}"
        / "agent-calls"
        / f"verifier-{call_index}.json"
    )


def _call_verifier(
    *,
    vault_dir: Path,
    note_file: Path,
    note_rel: str,
    scripts_dir: Path,
    timeout_s: int,
    cycle_num: int,
    call_index: int,
    committed_text: str | None = None,
) -> VerifierVerdict:
    """Invoke agent_call.py for a single note and return a VerifierVerdict.

    The prompt is built via :func:`_build_verifier_prompt`, so every runtime
    sees the verifier rules, their inputs and the JSON-output contract inline.
    It is built before any temp file is opened: a missing packaged skill
    raises there and leaves nothing behind. The agent's response is parsed
    via :func:`_extract_json_blob`, which tolerates code-fenced and
    narrative-wrapped JSON.

    ``--cost-sidecar`` is not optional (issue #234). Without it this stage —
    one LLM call per note written in the cycle, so the highest-count dispatch
    the framework makes — spent real money and left no record, so the dollar
    cap could be blown past by verifier calls alone and the run report showed
    none of it. The fake agent hides this in tests because it costs $0.
    """
    note_text = note_file.read_text(encoding="utf-8")
    prompt = _build_verifier_prompt(
        note_text,
        committed_text=committed_text,
        **_verifier_inputs(vault_dir, note_text),
    )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as prompt_f:
        prompt_f.write(prompt)
        prompt_path = Path(prompt_f.name)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as out_f:
        output_path = Path(out_f.name)

    try:
        proc = popen_session(
            [
                sys.executable,
                str(scripts_dir / "agent_call.py"),
                "--vault",
                str(vault_dir),
                "--stage",
                "verifier",
                "--prompt-file",
                str(prompt_path),
                "--output-file",
                str(output_path),
                "--cost-sidecar",
                str(verifier_sidecar_path(vault_dir, cycle_num, call_index)),
            ]
        )
        try:
            proc.wait(timeout=timeout_s)
        finally:
            # On every path, the timeout and Ctrl+C included. agent_call.py
            # runs the agent CLI in a session of its own and forwards a
            # SIGTERM to it; the SIGKILL of ``subprocess.run(timeout=…)``
            # cannot be forwarded, so it killed the wrapper and left the
            # agent running. SIGTERM to the wrapper's group first, then
            # SIGKILL. A no-op once the wrapper has exited and left nothing.
            terminate_process_tree(proc)
    except subprocess.TimeoutExpired:
        _LOG.warning("verifier timed out for %s — stamping pending", note_rel)
        return VerifierVerdict(note_path=note_rel, status="pending")
    except Exception as e:
        _LOG.warning("verifier call failed for %s: %s — stamping pending", note_rel, e)
        return VerifierVerdict(note_path=note_rel, status="pending")
    finally:
        prompt_path.unlink(missing_ok=True)

    # Parse output \u2014 spec-019 / 0.2.31: tolerant JSON extraction handles
    # code-fenced and narrative-wrapped agent responses (the codex shape).
    # Strict json.loads-only parsing was the 0.2.30 silent-fail mode.
    try:
        raw = output_path.read_text(encoding="utf-8")
    except OSError:
        return VerifierVerdict(note_path=note_rel, status="pending")
    finally:
        output_path.unlink(missing_ok=True)
    data = _extract_json_blob(raw)
    if data is None:
        return VerifierVerdict(note_path=note_rel, status="pending")

    return _verdict_from_data(note_rel, data)


def _verdict_from_data(note_rel: str, data: dict[str, Any]) -> VerifierVerdict:
    """The verifier's JSON object as a verdict. ``pre_existing`` (spec 087, the
    flaws an update did not introduce) is optional and tolerated when absent or
    malformed."""
    verdict_str = data.get("verdict", "")
    violations_raw = data.get("violations")
    # `null` (or any non-list) is "no violations listed", not a reason to
    # raise out of the stage and leave the cycle's remaining notes unverified.
    if not isinstance(violations_raw, list):
        violations_raw = []
    # Normalise violations to list[dict]
    violations: list[dict] = []
    for v in violations_raw:
        if isinstance(v, dict):
            violations.append(v)
        else:
            violations.append({"message": str(v)})
    older_raw = data.get("pre_existing")
    older: list[dict] = (
        [v if isinstance(v, dict) else {"message": str(v)} for v in older_raw]
        if isinstance(older_raw, list)
        else []
    )

    if verdict_str == "accept":
        return VerifierVerdict(
            note_path=note_rel,
            status="verified",
            violations=[],
            suggested_fix=data.get("suggested_fix"),
            pre_existing=older,
        )
    elif verdict_str == "reject":
        return VerifierVerdict(
            note_path=note_rel,
            status="rejected",
            violations=violations,
            suggested_fix=data.get("suggested_fix"),
            pre_existing=older,
        )
    else:
        return VerifierVerdict(note_path=note_rel, status="pending")
