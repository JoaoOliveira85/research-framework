"""Say why a cycle aborted (exit 2) — issue #44, spec 070 FR6.

The steps that return 2 from the cycle runner narrate at INFO, or not at all
(an agent that exited 1, a validator ABORT whose reason went to a subprocess's
stdout). ``run_single_cycle`` is the one choke point every cycle-running verb
passes through, so it asks this module to reconstruct the cause from what the
cycle left on disk and reports it at ERROR.

Everything here is best-effort and read-only: a diagnosis that cannot be built
degrades to a pointer at the cycle's logs, never an exception.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .step_gate_log import read_step_gates

__all__ = ["diagnose_cycle_abort", "quota_signature"]

# What the agent CLIs print when the account, not the framework, is the limit.
_QUOTA_PATTERNS = (
    re.compile(r"hit your[^\n]{0,40}\blimit", re.IGNORECASE),
    re.compile(r"usage limit (?:reached|exceeded)", re.IGNORECASE),
    re.compile(r"rate_limit_error|overloaded_error", re.IGNORECASE),
    re.compile(r"too many requests", re.IGNORECASE),
    re.compile(r"rate limit(?:ed| exceeded| reached)", re.IGNORECASE),
)
_STAMP = re.compile(r"^\[\d{2}:\d{2}:\d{2}\]\s*")
_EXIT_LINE = re.compile(r"^# \[[^\]]*\] exited with code (-?\d+)\s*$", re.MULTILINE)
_GENERIC_REASON = "cycle_runner returned structural error"
_AGENT_STAGES = ("scout", "research")
_TAIL_BYTES = 64 * 1024


def quota_signature(text: str) -> str | None:
    """The first line of *text* that looks like a quota / rate-limit message."""
    for line in text.splitlines():
        if any(p.search(line) for p in _QUOTA_PATTERNS):
            return _STAMP.sub("", line).strip()[:200]
    return None


def _tail(path: Path) -> str:
    try:
        with path.open("rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - _TAIL_BYTES))
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _last_output_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        stripped = _STAMP.sub("", line).strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:200]
    return ""


def _agent_findings(cycles_dir: Path, cycle: int) -> tuple[list[str], bool]:
    findings: list[str] = []
    quota = False
    for stage in _AGENT_STAGES:
        text = _tail(cycles_dir / f"cycle-{cycle:03d}-{stage}.log")
        codes = _EXIT_LINE.findall(text)
        if not codes or int(codes[-1]) == 0:
            continue
        code = int(codes[-1])
        signature = quota_signature(text)
        if signature:
            quota = True
            findings.append(
                f"{stage} agent exited {code} (agent output: {signature!r}; "
                "this is a quota/rate limit, not a framework fault)"
            )
            continue
        last = _last_output_line(text)
        detail = f" (last agent output: {last!r})" if last else ""
        findings.append(f"{stage} agent exited {code}{detail}")
    return findings, quota


def _validator_findings(cycles_dir: Path, cycle: int) -> list[str]:
    findings: list[str] = []
    for sidecar in sorted(cycles_dir.glob(f"cycle-{cycle:03d}-*.json.validation.json")):
        try:
            doc = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict) or doc.get("status") != "ABORT":
            continue
        report = sidecar.name.removesuffix(".validation.json")
        errors = [str(e) for e in (doc.get("errors") or [])][:3]
        tail = f" ({'; '.join(errors)})" if errors else ""
        findings.append(f"validator ABORT on {report}: {doc.get('reason', '')}{tail}")
    return findings


def diagnose_cycle_abort(vault_dir: Path, cycle: int, *, abort_reason: str = "") -> str:
    """One paragraph: what ended *cycle*, and what would fix it."""
    cycles_dir = vault_dir / "_pipeline" / "cycles"
    cycle_3 = f"{cycle:03d}"
    parts: list[str] = []

    agent, quota = _agent_findings(cycles_dir, cycle)
    parts += agent

    for stage in _AGENT_STAGES:
        log = cycles_dir / f"cycle-{cycle_3}-{stage}.log"
        report = cycles_dir / f"cycle-{cycle_3}-{stage}.json"
        if log.is_file() and not report.is_file():
            parts.append(f"{stage} report cycle-{cycle_3}-{stage}.json was not written")

    try:
        for gate in read_step_gates(cycles_dir, cycle):
            if str(gate.status or "").upper() == "FAIL":
                parts.append(f"gate {gate.gate_id} FAIL: {gate.message}")
    except Exception:  # noqa: BLE001 - diagnosis must never raise
        pass

    parts += _validator_findings(cycles_dir, cycle)

    if abort_reason and abort_reason != _GENERIC_REASON:
        parts.append(abort_reason)

    if not parts:
        parts.append(
            "no specific cause was recorded by the step that stopped it; read "
            f"{cycles_dir}/cycle-{cycle_3}-*.log and cycle-{cycle_3}/cycle.log"
        )

    remedy = (
        "wait for the limit to reset, then re-run with --resume"
        if quota
        else "fix the cause above, then re-run with --resume"
    )
    return f"{'; '.join(parts)}. To continue: {remedy}."
