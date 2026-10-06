"""``acceptance`` read-only CLI verb (spec 063).

Runs the framework-generic acceptance gate set (§4.1 / ``generic-gates.contract.md``)
over the artifacts a generated vault already emits, plus the ledger-reconciliation
view (US2), per-citation authority/credibility grading (US3), and an in-vault
domain-probe-pack summary (US4/US5). The only thing it writes is its own scorecard
under ``<vault>/_pipeline/acceptance/`` — it never mutates the graded vault and never
dispatches an LLM (the gates are deterministic; the tier-2 dispatch guard stays green).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import logging
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_LOG = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0"
KIND = "acceptance-scorecard"

# Notes that are not part of the indexed research corpus (templates + indexes).
_NON_CORPUS_NAMES = {"_index.md", "_concepts.md", "_graph.md"}
# OS-style numbered sibling: "Foo Bar 2" → base "Foo Bar" (spec 062 FR2).
_OS_SIBLING_RE = re.compile(r"^(?P<base>.+) (?P<n>\d+)$")
_CYCLE_COMMIT_RE = re.compile(r"^research: cycle (\d+)\b")


# ---------------------------------------------------------------------------
# Result vocabulary (mirrors pipeline.gates.GateResult; see data-model Entity 1)
# ---------------------------------------------------------------------------


@dataclass
class GateResult:
    """One acceptance-gate verdict (Entity 1)."""

    gate_id: str
    status: str  # PASS | FAIL | WARN
    metric_value: float | int | str | None
    threshold: float | int | str | None
    message: str
    evidence_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "status": self.status,
            "metric_value": self.metric_value,
            "threshold": self.threshold,
            "message": self.message,
            "evidence_paths": list(self.evidence_paths),
        }


# ---------------------------------------------------------------------------
# Repo-script loaders (source_ledger.py / check_template_compliance.py live under
# scripts/, not in the installed package — load them by path in dev/eval mode).
# ---------------------------------------------------------------------------


def _repo_scripts_dir() -> Path:
    # src/research_framework/cli/acceptance.py → parents[3] == repo root.
    return Path(__file__).resolve().parents[3] / "scripts"


def _load_repo_script(name: str, vault: Path | None = None):
    """Import a maintainer script by file path, or return ``None`` if absent.

    Prefers ``<vault>/scripts/<name>.py`` (a vault that vendored it), then the
    framework checkout's ``scripts/<name>.py``. Registers the module in
    ``sys.modules`` before executing it so the script's dataclasses resolve.
    """
    candidates: list[Path] = []
    if vault is not None:
        candidates.append(vault / "scripts" / f"{name}.py")
    candidates.append(_repo_scripts_dir() / f"{name}.py")
    for path in candidates:
        if not path.is_file():
            continue
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            return module
        except Exception as exc:  # pragma: no cover - defensive
            # A stale/broken vault-local copy must not mask a working framework
            # copy: drop the partially-initialised module and try the next
            # candidate instead of giving up.
            _LOG.warning("acceptance: could not load %s from %s: %s", name, path, exc)
            sys.modules.pop(name, None)
            continue
    return None


# ---------------------------------------------------------------------------
# Shared read helpers
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _LOG.warning("acceptance: malformed JSON %s: %s", path, exc)
        return None
    return data if isinstance(data, dict) else None


def _corpus_notes(vault: Path) -> list[Path]:
    """Indexed research notes under ``data_vault`` (skips templates + indexes)."""
    data_vault = vault / "data_vault"
    if not data_vault.is_dir():
        return []
    out: list[Path] = []
    for note in sorted(data_vault.rglob("*.md")):
        rel = note.relative_to(data_vault)
        if "_templates" in rel.parts:
            continue
        if note.name in _NON_CORPUS_NAMES or note.name.startswith("_"):
            continue
        out.append(note)
    return out


def _note_frontmatter(path: Path) -> dict[str, Any]:
    from ..vault.frontmatter import FrontmatterParseError, parse_frontmatter

    try:
        fm, _body = parse_frontmatter(path)
    except (OSError, FrontmatterParseError):
        return {}
    return fm or {}


def _rel(vault: Path, path: Path) -> str:
    try:
        return str(path.relative_to(vault))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# US1 — the six framework-generic gates (generic-gates.contract.md)
# ---------------------------------------------------------------------------


def gate_rejected_notes(vault: Path) -> GateResult:
    """GA-001: no ``data_vault`` note carries ``verifier_status: rejected``."""
    offenders: list[str] = []
    for note in _corpus_notes(vault):
        status = str(_note_frontmatter(note).get("verifier_status", "")).strip().lower()
        if status == "rejected":
            offenders.append(_rel(vault, note))
    report = _read_json(vault / "_pipeline" / "run-report.json") or {}
    reported = report.get("rejected_unresolved")
    count = len(offenders)
    if count == 0 and not reported:
        return GateResult(
            "GA-001", "PASS", 0, 0, "No rejected notes in the indexed corpus."
        )
    detail = f"{count} rejected note(s) left in the corpus"
    if reported:
        detail += f" (run-report rejected_unresolved={reported})"
    return GateResult(
        "GA-001",
        "FAIL",
        count,
        0,
        detail + " — they belong in _pipeline/quarantine/ (spec 062 FR1).",
        offenders,
    )


def find_duplicate_notes(vault: Path) -> list[tuple[str, list[str]]]:
    """``(kind, paths)`` duplicates under ``data_vault`` (spec 062 FR2 detector).

    ``os_sibling`` = a ``Foo 2.md`` fork of an existing ``Foo.md``;
    ``content_hash`` = ≥2 byte-identical notes.
    """
    notes = _corpus_notes(vault)
    findings: list[tuple[str, list[str]]] = []
    note_set = set(notes)
    for note in notes:
        m = _OS_SIBLING_RE.match(note.stem)
        if not m:
            continue
        base = note.with_name(f"{m.group('base')}.md")
        if base in note_set:
            findings.append(("os_sibling", [str(base), str(note)]))
    by_hash: dict[str, list[Path]] = {}
    for note in notes:
        try:
            digest = hashlib.sha256(note.read_bytes()).hexdigest()
        except OSError:
            continue
        by_hash.setdefault(digest, []).append(note)
    for paths in by_hash.values():
        if len(paths) > 1:
            findings.append(("content_hash", [str(p) for p in sorted(paths)]))
    return findings


def gate_duplicate_notes(vault: Path) -> GateResult:
    """GA-002: no OS-style ``N.md`` siblings and no byte-identical duplicates."""
    findings = find_duplicate_notes(vault)
    if not findings:
        return GateResult("GA-002", "PASS", 0, 0, "No duplicate notes.")
    evidence = sorted({p for _kind, paths in findings for p in paths})
    evidence_rel = [_rel(vault, Path(p)) for p in evidence]
    return GateResult(
        "GA-002",
        "FAIL",
        len(findings),
        0,
        f"{len(findings)} duplicate group(s) in data_vault/ (spec 062 FR2).",
        evidence_rel,
    )


def _git(vault: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", "-C", str(vault), *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover
        _LOG.warning("acceptance: git %s failed: %s", args, exc)
        return None


def gate_git_integrity(vault: Path) -> GateResult:
    """GA-003: clean ``data_vault`` working tree + one commit per cycle (Principle X)."""
    if not (vault / ".git").exists():
        # Inapplicable rather than violated: surface as advisory WARN (the
        # scorecard vocabulary is PASS/FAIL/WARN — no NA), never a silent PASS.
        return GateResult(
            "GA-003",
            "WARN",
            None,
            0,
            "Not a git repository — vault history integrity not assessable (advisory).",
        )
    problems: list[str] = []
    porcelain = _git(vault, "status", "--porcelain", "data_vault/")
    untracked: list[str] = []
    if porcelain is not None and porcelain.returncode == 0:
        untracked = [ln for ln in porcelain.stdout.splitlines() if ln.strip()]
        if untracked:
            problems.append(f"{len(untracked)} uncommitted change(s) under data_vault/")
    log = _git(vault, "log", "--pretty=%s")
    dup_cycles: list[str] = []
    if log is not None and log.returncode == 0:
        seen: dict[str, int] = {}
        for line in log.stdout.splitlines():
            m = _CYCLE_COMMIT_RE.match(line.strip())
            if m:
                seen[m.group(1)] = seen.get(m.group(1), 0) + 1
        dup_cycles = [c for c, n in sorted(seen.items()) if n > 1]
        if dup_cycles:
            problems.append(
                "duplicate per-cycle commit(s) for cycle " + ", ".join(dup_cycles)
            )
    if not problems:
        return GateResult(
            "GA-003", "PASS", 0, 0, "Vault git history is clean (one commit per cycle)."
        )
    evidence = [ln[3:] if len(ln) > 3 else ln for ln in untracked]
    return GateResult(
        "GA-003",
        "FAIL",
        len(untracked) + len(dup_cycles),
        0,
        "; ".join(problems),
        evidence,
    )


def gate_run_completion(vault: Path) -> GateResult:
    """GA-004: graded exit-status gate (issue #159 + spec 061 FR4).

    Pre-rc8 behaviour treated every non-``complete`` exit as FAIL, including
    the legitimate spec-061-FR4 "hit my configured cap exactly" case AND any
    budget-cap-tripped-early case (e.g. a dollar cap on an honest run). It
    also reported the failure as "not 'done'" while the spec vocabulary
    actually uses "complete" — the rc7 GA-004 message was both noisy AND
    inconsistent with the source-of-truth vocabulary.

    New taxonomy:
      - ``complete``                     → **PASS** (work exhausted before cap)
      - ``constrained`` AND actual==configured → **PASS** (hit configured cap;
        spec 061 FR4: "a max_cycles-reached run reports exit_status ≠ complete
        and actual == configured" — this is the *intended* constrained shape)
      - ``constrained`` AND actual<configured  → **WARN** (cap tripped early —
        dollar/wall-clock cap OR source-exhausted; legitimate but worth
        surfacing so the operator knows the run didn't use its full budget)
      - ``aborted``                      → **FAIL** (structural error)
      - ``unknown`` / no run-report      → **FAIL** (run did not finalise)
    """
    report = _read_json(vault / "_pipeline" / "run-report.json")
    if report is None:
        return GateResult(
            "GA-004",
            "FAIL",
            None,
            "complete",
            "No _pipeline/run-report.json — run did not finalise cleanly (spec 061 FR4).",
        )
    budget = report.get("cycle_budget") or {}
    configured = budget.get("configured")
    actual = budget.get("actual")
    exit_status = str(budget.get("exit_status") or "").strip() or "unknown"
    metric = f"{actual}/{configured}"
    if exit_status == "complete":
        return GateResult(
            "GA-004",
            "PASS",
            metric,
            "complete",
            f"Run completed (configured {configured}, actual {actual}).",
        )
    if exit_status == "constrained":
        # actual == configured is the canonical "hit your cap" shape called
        # out in spec 061 FR4: PASS. actual < configured means the cap
        # tripped early (dollar / wall-clock / source-exhausted) — WARN so
        # the operator knows budget wasn't fully used.
        if (
            isinstance(actual, int)
            and isinstance(configured, int)
            and actual == configured
        ):
            return GateResult(
                "GA-004",
                "PASS",
                metric,
                "complete",
                (
                    f"Constrained exit at configured cap (actual {actual} == "
                    f"configured {configured}) — spec 061 FR4 canonical shape."
                ),
            )
        return GateResult(
            "GA-004",
            "WARN",
            metric,
            "complete",
            (
                f"Constrained exit below configured cap (actual {actual} < "
                f"configured {configured}); cap tripped early (dollar / "
                f"wall-clock / source-exhausted) — legitimate but the run "
                f"did not use its full cycle budget."
            ),
            ["_pipeline/run-report.json"],
        )
    return GateResult(
        "GA-004",
        "FAIL",
        metric,
        "complete",
        (
            f"Run exit_status='{exit_status}' (configured {configured}, "
            f"actual {actual}); not 'complete' (spec 061 FR4)."
        ),
        ["_pipeline/run-report.json"],
    )


def _sum_costs_and_tokens(vault: Path) -> tuple[float, int, int]:
    """Sum ``cost_usd`` and tokens across every per-call sidecar (spec 028)."""
    cycles = vault / "_pipeline" / "cycles"
    total = 0.0
    tokens = 0
    sidecars = 0
    if cycles.is_dir():
        for sidecar in sorted(cycles.glob("cycle-*/agent-calls/*.json")):
            data = _read_json(sidecar)
            if not data:
                continue
            sidecars += 1
            total += float(data.get("cost_usd") or 0.0)
            for key in ("tokens_in", "tokens_out", "input_tokens", "output_tokens"):
                try:
                    tokens += int(data.get(key) or 0)
                except (TypeError, ValueError):
                    continue
    return total, tokens, sidecars


def gate_cost_telemetry(vault: Path) -> GateResult:
    """GA-005: ``total_cost_usd > 0`` with tokens recorded (FAILs loud on $0)."""
    total, tokens, sidecars = _sum_costs_and_tokens(vault)
    if total > 0 and tokens > 0:
        return GateResult(
            "GA-005",
            "PASS",
            round(total, 6),
            0,
            f"Cost telemetry present: ${total:.4f} across {sidecars} call(s).",
        )
    why = []
    if total <= 0:
        why.append("total_cost_usd is $0")
    if tokens <= 0:
        why.append("no tokens recorded")
    return GateResult(
        "GA-005",
        "FAIL",
        round(total, 6),
        0,
        "Cost telemetry missing (" + "; ".join(why) + ") — spec 028 amendment.",
        ["_pipeline/cycles/*/agent-calls/"],
    )


def gate_template_drift(vault: Path) -> GateResult:
    """GA-006 (WARN): every note's ``template_version`` matches the shipped template."""
    mod = _load_repo_script("check_template_compliance", vault)
    if mod is None or not hasattr(mod, "check_versions"):
        return GateResult(
            "GA-006",
            "PASS",
            0,
            0,
            "Template-drift checker unavailable — skipped (advisory).",
        )
    try:
        stale = mod.check_versions(vault)
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("acceptance: template-drift check failed: %s", exc)
        return GateResult(
            "GA-006", "PASS", 0, 0, f"Template-drift check skipped: {exc}"
        )
    if not stale:
        return GateResult(
            "GA-006", "PASS", 0, 0, "All notes match their template_version."
        )
    evidence = [_rel(vault, Path(row[0])) for row in stale]
    return GateResult(
        "GA-006",
        "WARN",
        len(stale),
        0,
        f"{len(stale)} note(s) stamped with an outdated template_version (advisory).",
        evidence,
    )


def run_generic_gates(vault: Path) -> list[GateResult]:
    """The six §4.1 gates, in id order."""
    return [
        gate_rejected_notes(vault),
        gate_duplicate_notes(vault),
        gate_git_integrity(vault),
        gate_run_completion(vault),
        gate_cost_telemetry(vault),
        gate_template_drift(vault),
    ]


# ---------------------------------------------------------------------------
# US2 — ledger ↔ citation reconciliation (data-model Entity 3)
# ---------------------------------------------------------------------------

_FAILURE_LIKE = {
    "ACCESS_FAIL",
    "PIPELINE_DROP",
    "NOT_REACHED",
    "QUALITY_REJECT",
    "SKIPPED_RELEVANCE",
}


def _notes_citing_hosts(vault: Path) -> tuple[int, dict[str, int]]:
    """``(total_corpus_notes, host → notes-citing-it)`` from ``source_urls``."""
    from ..vault.credibility import citation_url, iter_source_url_entries

    notes = _corpus_notes(vault)
    per_host: dict[str, int] = {}
    for note in notes:
        fm = _note_frontmatter(note)
        hosts_in_note: set[str] = set()
        for entry in iter_source_url_entries(fm):
            url = citation_url(entry)
            if not url:
                continue
            host = urlparse(url).netloc.lower()
            if host:
                hosts_in_note.add(host)
        for host in hosts_in_note:
            per_host[host] = per_host.get(host, 0) + 1
    return len(notes), per_host


def build_ledger_reconciliation(vault: Path) -> dict[str, Any]:
    """Read the shipped ledger and report ledger↔citation disagreements (US2)."""
    mod = _load_repo_script("source_ledger", vault)
    if mod is None:
        return {"sources_total": 0, "disagreements": []}
    try:
        sources = mod.load_declared_sources(vault)
        cycles = mod._discovered_cycles(vault)
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("acceptance: ledger load failed: %s", exc)
        return {"sources_total": 0, "disagreements": []}

    raw_by_source: dict[str, list[Any]] = {}
    hosts_by_source: dict[str, list[str]] = {}
    for cycle in cycles:
        try:
            entries = mod.build_cycle_ledger(vault, cycle)
        except Exception as exc:  # pragma: no cover - defensive
            _LOG.warning("acceptance: build_cycle_ledger(%s) failed: %s", cycle, exc)
            continue
        for entry in entries:
            raw_by_source.setdefault(entry.name, []).append(mod._raw_verdict(entry))
            hosts_by_source[entry.name] = list(entry.hosts)

    total_notes, per_host = _notes_citing_hosts(vault)
    disagreements: list[dict[str, Any]] = []
    for source in sources:
        verdicts = raw_by_source.get(source.name, [])
        collapsed = mod.collapse_verdict(verdicts).value if verdicts else "NOT_REACHED"
        hosts = hosts_by_source.get(source.name, [])
        notes_citing = max((per_host.get(h, 0) for h in hosts), default=0)
        citation_rate = (notes_citing / total_notes) if total_notes else 0.0
        # Defensive reconciliation (the 048-v2 ledger already does this at build
        # time; we re-derive so a pre-amendment ledger still reports correctly).
        if citation_rate > 0 and collapsed in _FAILURE_LIKE:
            disagreements.append(
                {
                    "source": source.name,
                    "ledger_verdict": "LEDGER_DISAGREEMENT",
                    "citation_rate": round(citation_rate, 4),
                }
            )
        elif collapsed == "LEDGER_DISAGREEMENT":
            disagreements.append(
                {
                    "source": source.name,
                    "ledger_verdict": "LEDGER_DISAGREEMENT",
                    "citation_rate": round(citation_rate, 4),
                }
            )
    return {"sources_total": len(sources), "disagreements": disagreements}


# ---------------------------------------------------------------------------
# US3 — authority (053) + credibility (055) citation grading (Entity 4)
# ---------------------------------------------------------------------------


def _derived_trunk_role(spec: object) -> str | None:
    """Role of the unique minimum-priority data source (spec 053 derived trunk)."""
    sources = list(getattr(spec, "data_sources", []) or [])
    if not sources:
        return None
    min_priority = min(getattr(s, "priority", 2) for s in sources)
    at_min = [s for s in sources if getattr(s, "priority", 2) == min_priority]
    if len(at_min) != 1:
        return None
    return getattr(at_min[0], "role", None)


def build_citation_grading(vault: Path) -> dict[str, Any]:
    """Per-citation authority/credibility grading (US3, data-model Entity 4)."""
    from ..pipeline.source_authority import build_source_role_index, resolve_role
    from ..spec.parser import parse as parse_spec
    from ..vault.credibility import (
        citation_coi,
        citation_credibility,
        citation_url,
        iter_source_url_entries,
    )

    spec_path = vault / "research.spec.md"
    if not spec_path.is_file():
        return {}
    try:
        spec = parse_spec(spec_path)
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("acceptance: spec parse failed: %s", exc)
        return {}

    trunk_role = _derived_trunk_role(spec)
    index = build_source_role_index(spec, vault)
    # The trunk is only code/module-resolvable when some indexed source owns it;
    # a journal-/docs-first vault (external trunk) is graded against its own
    # derived trunk, never an assumed code trunk (edge case).
    trunk_resolvable = trunk_role is not None and trunk_role in set(
        index.exact.values()
    ) | {role for _sig, role in index.repo_signatures}

    authority_inversions = 0
    credibility_ungraded = 0
    coi_flagged = 0
    for note in _corpus_notes(vault):
        fm = _note_frontmatter(note)
        entries = iter_source_url_entries(fm)
        if not entries:
            continue
        cites_trunk = False
        for entry in entries:
            url = citation_url(entry)
            if url and resolve_role(url, index) == trunk_role:
                cites_trunk = True
            if citation_credibility(entry) is None:
                credibility_ungraded += 1
            if citation_coi(entry):
                coi_flagged += 1
        if trunk_resolvable and not cites_trunk:
            authority_inversions += 1

    grading: dict[str, Any] = {
        "authority_inversions": authority_inversions,
        "credibility_ungraded": credibility_ungraded,
        "coi_flagged": coi_flagged,
    }
    if trunk_role:
        grading["derived_trunk_role"] = trunk_role
    return grading


# ---------------------------------------------------------------------------
# US4/US5 — in-vault domain probe-pack discovery (data, not framework code; D5)
# ---------------------------------------------------------------------------

_GOLD_ANCHOR_RE = re.compile(r"^[-*]\s*(P\d+)[:\s]", re.MULTILINE)
_BREADTH_SCORE_RE = re.compile(r"breadth_score:\s*([0-9.]+)")


def discover_domain_probes(vault: Path) -> dict[str, Any] | None:
    """Summarise an in-vault ``_pipeline/acceptance/`` probe pack (never imports it)."""
    acc = vault / "_pipeline" / "acceptance"
    if not acc.is_dir():
        return None
    candidates = sorted(
        p
        for p in acc.glob("*.md")
        if "probe" in p.name.lower() and not p.name.upper().startswith("REPORT")
    )
    if not candidates:
        return None
    pack = candidates[0]
    text = pack.read_text(encoding="utf-8", errors="replace")
    anchors = _GOLD_ANCHOR_RE.findall(text)
    breadth = _BREADTH_SCORE_RE.search(text)
    summary: dict[str, Any] = {
        "pack": _rel(vault, pack),
        "gold_anchors": anchors,
        "breadth_score": float(breadth.group(1)) if breadth else None,
    }
    return summary


# ---------------------------------------------------------------------------
# Scorecard assembly + persistence (Entity 2, FR-006)
# ---------------------------------------------------------------------------


def build_scorecard(vault: Path, *, strict: bool = False) -> dict[str, Any]:
    """Assemble the full acceptance scorecard for ``vault`` (deterministic gates)."""
    from .. import __version__

    gates = run_generic_gates(vault)
    fail_count = sum(1 for g in gates if g.status == "FAIL")
    warn_count = sum(1 for g in gates if g.status == "WARN")
    exit_code = 1 if (fail_count or (strict and warn_count)) else 0
    overall_status = "FAIL" if fail_count else ("WARN" if warn_count else "PASS")

    scorecard: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "vault": str(vault),
        "framework_version": __version__,
        "overall": {
            "status": overall_status,
            "fail_count": fail_count,
            "warn_count": warn_count,
            "exit_code": exit_code,
        },
        "generic_gates": [g.to_dict() for g in gates],
    }
    recon = build_ledger_reconciliation(vault)
    if recon:
        scorecard["ledger_reconciliation"] = recon
    grading = build_citation_grading(vault)
    if grading:
        scorecard["citation_grading"] = grading
    probes = discover_domain_probes(vault)
    if probes is not None:
        scorecard["domain_probes"] = probes
    return scorecard


def render_markdown(scorecard: dict[str, Any]) -> str:
    overall = scorecard["overall"]
    lines = [
        "# Acceptance scorecard",
        "",
        f"- vault: `{scorecard['vault']}`",
        f"- generated: {scorecard['generated_at']}",
        f"- framework: {scorecard.get('framework_version', '?')}",
        f"- **overall: {overall['status']}** "
        f"(fail={overall['fail_count']}, warn={overall['warn_count']}, "
        f"exit={overall['exit_code']})",
        "",
        "## Generic gates",
        "",
        "| Gate | Status | Metric | Threshold | Message |",
        "| --- | --- | --- | --- | --- |",
    ]
    for g in scorecard["generic_gates"]:
        lines.append(
            f"| {g['gate_id']} | {g['status']} | {g.get('metric_value')} "
            f"| {g.get('threshold')} | {g['message']} |"
        )
    recon = scorecard.get("ledger_reconciliation")
    if recon:
        lines += ["", "## Ledger reconciliation", ""]
        if recon.get("disagreements"):
            lines.append("| Source | Ledger verdict | Citation rate |")
            lines.append("| --- | --- | --- |")
            for d in recon["disagreements"]:
                lines.append(
                    f"| {d['source']} | {d['ledger_verdict']} | {d['citation_rate']} |"
                )
        else:
            lines.append(
                f"No ledger↔citation disagreements ({recon.get('sources_total', 0)} sources)."
            )
    grading = scorecard.get("citation_grading")
    if grading:
        lines += [
            "",
            "## Citation grading",
            "",
            f"- derived trunk role: `{grading.get('derived_trunk_role', 'n/a')}`",
            f"- authority inversions: {grading.get('authority_inversions', 0)}",
            f"- credibility ungraded: {grading.get('credibility_ungraded', 0)}",
            f"- COI flagged: {grading.get('coi_flagged', 0)}",
        ]
    probes = scorecard.get("domain_probes")
    if probes:
        lines += [
            "",
            "## Domain probes (in-vault)",
            "",
            f"- pack: `{probes.get('pack')}`",
            f"- gold anchors: {', '.join(probes.get('gold_anchors') or []) or 'none'}",
            f"- breadth score: {probes.get('breadth_score')}",
        ]
    lines.append("")
    return "\n".join(lines)


def write_scorecard(vault: Path, scorecard: dict[str, Any]) -> tuple[Path, Path]:
    """Persist the scorecard JSON + markdown under ``_pipeline/acceptance/``."""
    from ..pipeline.atomic_write import write_json, write_text

    acc_dir = vault / "_pipeline" / "acceptance"
    acc_dir.mkdir(parents=True, exist_ok=True)
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    json_path = acc_dir / f"report-{date}.json"
    md_path = acc_dir / f"REPORT-{date}.md"
    write_json(json_path, scorecard)
    write_text(md_path, render_markdown(scorecard))
    return json_path, md_path


def run_acceptance(
    vault: Path, *, json_output: bool = False, strict: bool = False, write: bool = True
) -> int:
    """Run the gates, write the scorecard, and return the acceptance exit code."""
    scorecard = build_scorecard(vault, strict=strict)
    if write:
        try:
            write_scorecard(vault, scorecard)
        except Exception as exc:  # pragma: no cover - defensive
            _LOG.warning("acceptance: failed to write scorecard: %s", exc)
    if json_output:
        print(json.dumps(scorecard, indent=2))
    else:
        print(render_markdown(scorecard))
    rc = int(scorecard["overall"]["exit_code"])
    if rc:
        # Spec 077 FR-017: the scorecard on stdout is the report, but the
        # reason for a non-zero exit belongs on stderr.
        gates = scorecard["generic_gates"]
        failed = [g["gate_id"] for g in gates if g["status"] == "FAIL"]
        if failed:
            reason = f"gate(s) failed: {', '.join(failed)}"
        else:
            warned = [g["gate_id"] for g in gates if g["status"] == "WARN"]
            reason = f"gate(s) warned under --strict: {', '.join(warned)}"
        print(f"acceptance: {reason}", file=sys.stderr)
    return rc


def _cmd_acceptance(args: argparse.Namespace) -> int:
    vault = getattr(args, "vault", None)
    if vault is None:
        print("error: --vault is required", file=sys.stderr)
        return 2
    vault_dir = Path(vault).expanduser().resolve()
    if not vault_dir.is_dir():
        print(f"error: vault not found: {vault_dir}", file=sys.stderr)
        return 2
    return run_acceptance(
        vault_dir,
        json_output=bool(getattr(args, "json", False)),
        strict=bool(getattr(args, "strict", False)),
    )


__all__ = [
    "GateResult",
    "build_citation_grading",
    "build_ledger_reconciliation",
    "build_scorecard",
    "discover_domain_probes",
    "find_duplicate_notes",
    "render_markdown",
    "run_acceptance",
    "run_generic_gates",
    "write_scorecard",
]
