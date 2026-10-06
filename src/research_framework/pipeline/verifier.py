"""Verifier stage: per-note quality check via agent_call.py."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from research_framework.pipeline.process_tree import (
    popen_session,
    terminate_process_tree,
)
from research_framework.pipeline.settings import SettingsError, load_vault_settings
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
            "message": (
                f"first body wikilink [[{first}]] renames this note's own title "
                f"'{title}' (acronym {upper}) to '{resolved}'"
            ),
        }
    ]


def _merge_verifier_verdict(
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
        call_index += 1
        verdict = _call_verifier(
            vault_dir=vault_dir,
            note_file=note_file,
            note_rel=note_rel,
            scripts_dir=scripts_dir,
            timeout_s=timeout_s,
            cycle_num=cycle_num,
            call_index=call_index,
        )
        verdict = _merge_verifier_verdict(verdict, shape_violations)

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


def _build_verifier_prompt(note_content: str) -> str:
    """Wrap the note in explicit verifier instructions.

    On Claude Code, agents auto-load ``.agents/skills/verifier/SKILL.md``
    and produce JSON-compliant output naturally. Codex (and other
    runtimes that don't auto-load skills) need the contract baked into
    the prompt or they default to narrative responses that the framework
    can't parse \u2014 the 0.2.30 silent-fail mode.

    The wrapper is intentionally short and POINTS to the skill file
    rather than restating its rules, so the source of truth stays in
    ``SKILL.md``. The one thing we DO restate inline is the output
    schema, because that's the contract the framework parses on.
    """
    return (
        "# Verifier task\n\n"
        "You are the verifier. Apply the rules in "
        "`.agents/skills/verifier/SKILL.md` to the note below.\n\n"
        "Your response MUST be a single JSON object matching this schema, "
        "with no surrounding narrative:\n\n"
        "```json\n"
        "{\n"
        '  "verdict": "accept" | "reject",\n'
        '  "violations": [\n'
        '    {"rule_id": "<id>", "location": "<line or section>", "message": "<short>"}\n'
        "  ],\n"
        '  "suggested_fix": "<short string or null>"\n'
        "}\n"
        "```\n\n"
        "If you must include reasoning, place the JSON inside a "
        "`` ```json `` code fence \u2014 the framework will extract it. Default "
        "to `reject` when uncertain and name the rule that triggered the "
        "concern.\n\n"
        "---\n\n"
        "## Note under review\n\n"
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
) -> VerifierVerdict:
    """Invoke agent_call.py for a single note and return a VerifierVerdict.

    The prompt is built via :func:`_build_verifier_prompt` so runtimes that
    don't auto-load ``SKILL.md`` (codex) still see the JSON-output contract
    inline. The agent's response is parsed via :func:`_extract_json_blob`,
    which tolerates code-fenced and narrative-wrapped JSON.

    ``--cost-sidecar`` is not optional (issue #234). Without it this stage —
    one LLM call per note written in the cycle, so the highest-count dispatch
    the framework makes — spent real money and left no record, so the dollar
    cap could be blown past by verifier calls alone and the run report showed
    none of it. The fake agent hides this in tests because it costs $0.
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as prompt_f:
        prompt_f.write(_build_verifier_prompt(note_file.read_text(encoding="utf-8")))
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

    if verdict_str == "accept":
        return VerifierVerdict(
            note_path=note_rel,
            status="verified",
            violations=[],
            suggested_fix=data.get("suggested_fix"),
        )
    elif verdict_str == "reject":
        return VerifierVerdict(
            note_path=note_rel,
            status="rejected",
            violations=violations,
            suggested_fix=data.get("suggested_fix"),
        )
    else:
        return VerifierVerdict(note_path=note_rel, status="pending")
