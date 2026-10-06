"""The run receipt — one directory per pipeline run (spec 080, issue #221).

On 2026-09-01 the weekly runner failed ``verify`` on seven of eight live
vaults and left, per vault, a seven-line ``pipeline-state.json`` with
``errors: []`` and zero bytes on stderr. The reporting work that followed
fixed *what* the runner records. This module fixes *where*: everything a run
produces goes under ``_pipeline/runs/<run_id>/``, and one file in there says
what the run cost.

The layout (spec 080 FR-003)::

    _pipeline/runs/<run_id>/
        run.json                    the machine receipt (FR-007)
        run-report.md               its rendering for a human (FR-008)
        verbs.log                   which verbs wrote here, in order
        logs/<stage>.log            the merged agent output
        prompts/<stage>.rendered.md the prompt the agent was sent
        agent-calls/<stage>.json    the cost sidecar
        verify-report.json          the verify processor's full report

``run.json`` is **a pure function of the state file plus what is on disk**
(FR-006). It adds derived facts — durations, costs, paths — and restates
nothing an operator could not recompute. That is what makes it safe to
rewrite on every phase close: there is no accumulated state to lose. The one
thing not derivable from the state file is which verbs wrote into the run, so
that is on disk too, in ``verbs.log``, rather than being carried in memory.

Cost is a **lower bound by construction** (FR-013, D5). The ``claude`` runtime
reports real cost; the others estimate. A run total therefore mixes
provenances, and every rendering of it says so rather than presenting a
number that looks exact. A sidecar that was requested and is missing is
``null`` and counted, never read as a free call.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)

#: The receipt envelope version. Evolution follows ADR-0013: additive within
#: a major, a new schema file per major, ``schema_version`` in the payload.
RECEIPT_SCHEMA_VERSION = "1.0"

#: Terminal phase statuses — a run is finished when every phase is one of
#: these. Kept as strings rather than importing from ``runner`` to avoid a
#: cycle: ``runner`` imports this module.
_TERMINAL = frozenset({"done", "failed", "skipped"})

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def runs_root(vault: Path) -> Path:
    """``<vault>/_pipeline/runs`` — the parent of every run directory."""
    return vault / "_pipeline" / "runs"


def run_dir_for(vault: Path, run_id: str) -> Path:
    """The run directory for *run_id*, derived from the state file alone.

    FR-001: no new top-level key is added to ``pipeline-state.json``. The
    ``run_id`` it already carries is the join key, and this is the whole
    derivation.
    """
    return runs_root(vault) / run_id


def allocate_run_id(vault: Path, base_run_id: str) -> str:
    """A ``run_id`` whose directory does not exist yet (FR-002).

    ``_make_run_id`` is minute-granular, so two ``full`` runs inside one
    minute shared an id and the second simply overwrote the first's state
    (D1). Nothing noticed, because there was nothing to collide with. Now
    there is: a directory that already exists for a fresh ``run_id`` is a
    collision, and the id gains ``-2``, ``-3``, … until it is free.
    """
    if not run_dir_for(vault, base_run_id).exists():
        return base_run_id
    suffix = 2
    while run_dir_for(vault, f"{base_run_id}-{suffix}").exists():
        suffix += 1
    return f"{base_run_id}-{suffix}"


def ensure_run_dir(vault: Path, run_id: str) -> tuple[Path | None, bool]:
    """Create the run directory and its subdirectories.

    Returns ``(path, reconstructed)``. ``reconstructed`` is True when the
    directory did not exist and this call made it — which for ``resume`` and
    ``finish`` means the run predates this spec (FR-004) and is recorded as
    such in the receipt rather than being refused.

    Returns ``(None, False)`` when the directory cannot be created. The
    receipt is observational: an unwritable run directory downgrades the
    record, it never changes a phase's status or a run's exit code.
    """
    target = run_dir_for(vault, run_id)
    existed = target.exists()
    try:
        for sub in ("logs", "prompts", "agent-calls"):
            (target / sub).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _LOG.warning("  WARN: could not create the run directory %s: %s", target, exc)
        return None, False
    return target, not existed


def stage_path(run_dir: Path, subdir: str, stem: str, ext: str) -> Path:
    """A per-stage path that never overwrites an earlier one (FR-005).

    A stage re-driven by hand inside one run (``pipeline <vault> scout`` after
    ``full``) must not erase what the first pass recorded — that record is
    often the reason the operator is re-driving. The later file takes a
    numeric suffix on the STAGE, not on the whole filename, so the three
    artifacts of one re-drive sort together and read alike::

        scout.log       scout.json       scout.rendered.md
        scout-2.log     scout-2.json     scout-2.rendered.md

    That is the same shape ``agent_call.py``'s ``_allocate_sidecar_path``
    already uses for sidecar collisions.
    """
    base = run_dir / subdir / f"{stem}{ext}"
    if not base.exists():
        return base
    suffix = 2
    while (run_dir / subdir / f"{stem}-{suffix}{ext}").exists():
        suffix += 1
    return run_dir / subdir / f"{stem}-{suffix}{ext}"


def _suffix_of(name: str, stem: str, ext: str) -> int | None:
    """``scout-3.log`` → 3, given ``stem="scout"`` and ``ext=".log"``."""
    if not name.startswith(f"{stem}-") or not name.endswith(ext):
        return None
    middle = name[len(stem) + 1 : len(name) - len(ext)]
    return int(middle) if middle.isdigit() else None


def _latest_stage_file(run_dir: Path, subdir: str, stem: str, ext: str) -> Path | None:
    """The newest of ``<stem><ext>``, ``<stem>-2<ext>``, … or ``None``."""
    base = run_dir / subdir / f"{stem}{ext}"
    if not base.exists():
        return None
    best, best_n = base, 1
    try:
        candidates = list((run_dir / subdir).glob(f"{stem}-*{ext}"))
    except OSError:
        return best
    for candidate in candidates:
        n = _suffix_of(candidate.name, stem, ext)
        if n is not None and n > best_n:
            best, best_n = candidate, n
    return best


# ---------------------------------------------------------------------------
# The verb log
# ---------------------------------------------------------------------------


#: Written into a run directory that was created by a verb other than
#: ``full`` — the run began before the directory existed (FR-004).
RECONSTRUCTED_MARKER = "reconstructed"


def mark_reconstructed(run_dir: Path) -> None:
    """Record that this directory was made after the run it describes began."""
    try:
        (run_dir / RECONSTRUCTED_MARKER).write_text(
            "This run began before its directory existed (spec 080 FR-004); "
            "anything the earlier phases wrote is not here.\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def record_verb(run_dir: Path | None, verb: str) -> None:
    """Append *verb* to the run's ``verbs.log`` if it is not already last.

    FR-007's ``verbs`` field is the one fact about a run that the state file
    does not carry, so it lives on disk beside the artifacts rather than in
    memory — which is what keeps ``build_receipt`` a pure function of state
    plus disk (FR-006).
    """
    if run_dir is None:
        return
    try:
        existing = read_verbs(run_dir)
        if existing and existing[-1] == verb:
            return
        with (run_dir / "verbs.log").open("a", encoding="utf-8") as fh:
            fh.write(verb + "\n")
    except OSError as exc:
        _LOG.warning("  WARN: could not record the verb in %s: %s", run_dir, exc)


def read_verbs(run_dir: Path) -> list[str]:
    try:
        raw = (run_dir / "verbs.log").read_text(encoding="utf-8")
    except OSError:
        return []
    return [line.strip() for line in raw.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------


def read_sidecar_cost(path: Path | None) -> tuple[float | None, str | None]:
    """``(cost_usd, cost_source)`` from a spec-078 sidecar.

    ``(None, None)`` when the path is absent, unreadable or does not carry a
    numeric ``cost_usd`` — spec 078 FR-015's rule that no zero is silent
    applies to the reader as much as to the writer, so a sidecar that cannot
    be read is unknown cost, never free.
    """
    if path is None:
        return None, None
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None
    if not isinstance(payload, dict):
        return None, None
    cost = payload.get("cost_usd")
    if not isinstance(cost, int | float) or isinstance(cost, bool):
        return None, None
    source = payload.get("cost_source")
    return float(cost), source if isinstance(source, str) else None


# ---------------------------------------------------------------------------
# The receipt
# ---------------------------------------------------------------------------


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def _duration_s(started_at: Any, finished_at: Any) -> float | None:
    start, end = _parse_ts(started_at), _parse_ts(finished_at)
    if start is None or end is None:
        return None
    return max(0.0, (end - start).total_seconds())


def _rel_or_none(path: Path | None) -> str | None:
    return str(path) if path is not None else None


def _existing(path: Path) -> str | None:
    return str(path) if path.exists() else None


def _latest_export(vault: Path) -> str | None:
    exports = vault / "_pipeline" / "exports"
    try:
        candidates = sorted(
            (p for p in exports.glob("*.md") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
        )
    except OSError:
        return None
    return str(candidates[-1]) if candidates else None


def build_receipt(
    vault: Path,
    state: dict[str, Any],
    *,
    phases: tuple[str, ...],
    framework_version: str,
) -> dict[str, Any]:
    """Derive ``run.json`` from the state file and what is on disk (FR-006/7).

    Deterministic for a fixed input: every value is either copied from
    *state*, read from a file, or computed from those two. Nothing is
    generated here — no timestamp of its own, no counter — so building the
    receipt twice from the same inputs yields the same document, which is
    what makes rewriting it on every phase close safe.
    """
    run_id = state.get("run_id")
    run_dir = run_dir_for(vault, run_id) if isinstance(run_id, str) else None

    phase_records: dict[str, Any] = {}
    total = 0.0
    read_count = 0
    missing_count = 0

    for phase in phases:
        rec = state.get("phases", {}).get(phase, {})
        summary = rec.get("summary")
        summary = summary if isinstance(summary, dict) else None
        sidecar = (summary or {}).get("cost_sidecar")
        sidecar_path = Path(sidecar) if isinstance(sidecar, str) else None

        cost, source = read_sidecar_cost(sidecar_path)
        if sidecar_path is not None:
            if cost is None:
                missing_count += 1
            else:
                read_count += 1
                total += cost

        log = prompt = None
        if run_dir is not None:
            log = _latest_stage_file(run_dir, "logs", phase, ".log")
            prompt = _latest_stage_file(run_dir, "prompts", phase, ".rendered.md")

        phase_records[phase] = {
            "status": rec.get("status", "pending"),
            "started_at": rec.get("started_at"),
            "finished_at": rec.get("finished_at"),
            "duration_s": _duration_s(rec.get("started_at"), rec.get("finished_at")),
            "cost_usd": cost,
            "cost_source": source,
            "sidecar": _rel_or_none(sidecar_path),
            "log": _rel_or_none(log),
            "prompt": _rel_or_none(prompt),
            "errors": list(rec.get("errors", []) or []),
            "summary": summary,
        }

    every_phase_terminal = all(phase_records[p]["status"] in _TERMINAL for p in phases)
    finished = [
        phase_records[p]["finished_at"]
        for p in phases
        if isinstance(phase_records[p]["finished_at"], str)
    ]
    finished_at = max(finished) if (every_phase_terminal and finished) else None

    artifacts = {
        "scout_report": _existing(vault / "_pipeline" / "scout-report.json"),
        "research_report": _existing(vault / "_pipeline" / "research-report.json"),
        "verify_report": (
            _existing(run_dir / "verify-report.json") if run_dir is not None else None
        ),
        "latest_export": _latest_export(vault),
        "context_tree": _existing(
            vault / "_pipeline" / "extracted" / "context-tree.md"
        ),
    }

    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "run_id": run_id,
        "vault": str(vault.resolve()),
        "started_at": state.get("started_at"),
        "finished_at": finished_at,
        "framework_version": framework_version,
        "reconstructed": (
            (run_dir / RECONSTRUCTED_MARKER).exists() if run_dir is not None else False
        ),
        "verbs": read_verbs(run_dir) if run_dir is not None else [],
        "phases": phase_records,
        "artifacts": artifacts,
        "cost": {
            "total_usd": round(total, 4),
            "sidecars_read": read_count,
            "sidecars_missing": missing_count,
        },
    }


def _fmt_cost(value: float | None) -> str:
    return "unknown" if value is None else f"${value:.4f}"


def _fmt_duration(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value < 60:
        return f"{value:.0f}s"
    return f"{value // 60:.0f}m{value % 60:02.0f}s"


def render_run_report(receipt: dict[str, Any]) -> str:
    """``run-report.md`` — the receipt for a human (FR-008).

    Three questions, in the order an operator asks them after an unattended
    night: which phase failed and why, how long each phase took, what it
    cost. Every path it names is absolute, because the reader may be reading
    this over ssh in a directory that is not the vault.
    """
    phases: dict[str, Any] = receipt.get("phases", {})
    failed = [name for name, rec in phases.items() if rec.get("status") == "failed"]
    cost = receipt.get("cost", {})
    lower_bound = int(cost.get("sidecars_missing") or 0) > 0

    lines: list[str] = [
        f"# Pipeline run {receipt.get('run_id')}",
        "",
        f"- Vault: `{receipt.get('vault')}`",
        f"- Started: {receipt.get('started_at') or 'unknown'}",
        f"- Finished: {receipt.get('finished_at') or '(still open)'}",
        f"- Framework: {receipt.get('framework_version')}",
        f"- Verbs: {', '.join(receipt.get('verbs') or []) or '(none recorded)'}",
    ]
    if receipt.get("reconstructed"):
        lines.append(
            "- This directory was reconstructed: the run began before it "
            "existed, so anything the earlier phases wrote is not here."
        )
    lines += ["", "## What failed", ""]
    if not failed:
        lines.append(
            "Nothing. Every phase that ran reached a terminal state "
            "without recording an error."
        )
    else:
        for name in failed:
            errors = phases[name].get("errors") or []
            first = (
                errors[0] if errors else "(no reason recorded — that is itself a bug)"
            )
            lines.append(f"- **{name}** — {first}")
            if len(errors) > 1:
                lines.append(f"  - and {len(errors) - 1} more error(s); see `run.json`")

    lines += [
        "",
        "## How long each phase took",
        "",
        "| Phase | Status | Duration |",
        "| --- | --- | --- |",
    ]
    for name, rec in phases.items():
        lines.append(
            f"| {name} | {rec.get('status')} | {_fmt_duration(rec.get('duration_s'))} |"
        )

    lines += [
        "",
        "## What it cost",
        "",
        "| Phase | Cost | Source |",
        "| --- | --- | --- |",
    ]
    for name, rec in phases.items():
        if rec.get("sidecar") is None:
            continue
        lines.append(
            f"| {name} | {_fmt_cost(rec.get('cost_usd'))} | "
            f"{rec.get('cost_source') or 'unknown'} |"
        )
    total_label = _fmt_cost(cost.get("total_usd"))
    if lower_bound:
        total_label += (
            f" — a **lower bound**: {cost.get('sidecars_missing')} sidecar(s) "
            "could not be read"
        )
    lines += ["", f"**Total: {total_label}**", ""]
    if not lower_bound and int(cost.get("sidecars_read") or 0) > 0:
        lines.append(
            "Costs mix provenances — the `claude` runtime reports real spend, "
            "the others estimate. The `Source` column says which is which."
        )
        lines.append("")

    lines += ["## Artifacts", ""]
    for name, path in (receipt.get("artifacts") or {}).items():
        lines.append(f"- {name}: {f'`{path}`' if path else '(none)'}")
    lines.append("")
    return "\n".join(lines)


def write_receipt(
    vault: Path,
    state: dict[str, Any],
    *,
    phases: tuple[str, ...],
    framework_version: str,
) -> Path | None:
    """Write ``run.json`` and ``run-report.md``; return the receipt path.

    Never raises and never changes an exit code: an unwritable run directory
    costs the operator the record, not the run (spec 080 § Edge cases).
    """
    run_id = state.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        return None
    run_dir = run_dir_for(vault, run_id)
    if not run_dir.exists():
        return None
    receipt = build_receipt(
        vault, state, phases=phases, framework_version=framework_version
    )
    from .atomic_write import write_json, write_text

    try:
        write_json(run_dir / "run.json", receipt)
        write_text(run_dir / "run-report.md", render_run_report(receipt))
    except OSError as exc:
        _LOG.warning("  WARN: could not write the run receipt to %s: %s", run_dir, exc)
        return None
    return run_dir / "run.json"


# ---------------------------------------------------------------------------
# Retention (FR-020)
# ---------------------------------------------------------------------------


def prunable_runs(
    vault: Path,
    *,
    keep: int,
    older_than_days: int,
    current_run_id: str | None,
) -> list[Path]:
    """Run directories outside BOTH bounds, newest first excluded.

    Cap-N *and* age, each a ceiling in its own right — the same shape #307
    chose for research branches, so an operator learns one retention policy
    rather than two. A directory survives if it is among the newest *keep* OR
    younger than *older_than_days*. The run named by the current state file is
    never prunable, whatever the bounds say.
    """
    root = runs_root(vault)
    if not root.is_dir():
        return []
    try:
        dirs = sorted(
            (p for p in root.iterdir() if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return []
    cutoff = datetime.now(tz=UTC).timestamp() - older_than_days * 86400
    out: list[Path] = []
    for index, path in enumerate(dirs):
        if current_run_id is not None and path.name == current_run_id:
            continue
        if index < keep:
            continue
        try:
            if path.stat().st_mtime >= cutoff:
                continue
        except OSError:
            continue
        out.append(path)
    return out
