"""End-of-pipeline run report.

Walks ``_pipeline/cycles/`` after the orchestrator's main loop exits and
writes a single ``_pipeline/run-report.md`` that answers the three
operational questions the v0.2.19 pipeline forced operators to grep logs
for:

1. **What did each cycle actually do?** — notes created/updated, scout
   topics, cycle exit decision.
2. **Where did the time go?** — per-cycle total wall time + per-stage
   breakdown (top 3 longest stages per cycle, plus a grand total).
3. **Where did the tokens / dollars go?** — sum of every ``*.cost.json``
   sidecar (scout, research, plus any per-batch sidecars), grouped by
   cycle, with input / output / cache-read tokens itemised.

The report is observational — never raises, never influences exit codes.
Missing or malformed sidecars degrade the row silently (``—`` placeholders
in the table) so partial runs still produce a usable file.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["write_run_report"]

_LOG = logging.getLogger(__name__)


def _normalize_sidecar_tokens(data: dict[str, Any]) -> dict[str, Any]:
    """Map sidecar v1.1 field names to legacy names ``_CycleTokens`` expects."""
    normalized = dict(data)
    if "tokens_in" in data and "input_tokens" not in normalized:
        normalized["input_tokens"] = data.get("tokens_in")
    if "tokens_out" in data and "output_tokens" not in normalized:
        normalized["output_tokens"] = data.get("tokens_out")
    return normalized


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _LOG.warning("run_report: failed to read %s: %s", path, exc)
        return None
    return data if isinstance(data, dict) else None


@dataclass
class _CycleTokens:
    """Sum of token counts across every cost sidecar in one cycle."""

    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    sidecars: int = 0
    duration_ms: int = 0

    def add(self, sidecar: dict[str, Any]) -> None:
        self.sidecars += 1
        self.cost_usd += float(sidecar.get("cost_usd") or 0.0)
        for field_name in (
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        ):
            v = sidecar.get(field_name)
            if isinstance(v, (int, float)):
                setattr(self, field_name, getattr(self, field_name) + int(v))
        dms = sidecar.get("duration_ms")
        if isinstance(dms, (int, float)):
            self.duration_ms += int(dms)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class _CycleRow:
    cycle: int
    timings: dict[str, Any] | None = None
    research: dict[str, Any] | None = None
    scout: dict[str, Any] | None = None
    quality: dict[str, Any] | None = None
    tokens: _CycleTokens = field(default_factory=_CycleTokens)

    @property
    def notes_created(self) -> int:
        return len((self.research or {}).get("notes_created") or [])

    @property
    def notes_updated(self) -> int:
        return len((self.research or {}).get("notes_updated") or [])

    @property
    def topics_new(self) -> int:
        scout = self.scout or {}
        tf = scout.get("topics_found")
        if isinstance(tf, dict):
            new = tf.get("new") or []
            if isinstance(new, list):
                return len(new)
        return 0

    @property
    def total_duration_s(self) -> float | None:
        if not self.timings:
            return None
        v = self.timings.get("total_duration_s")
        return float(v) if isinstance(v, (int, float)) else None

    @property
    def exit_code(self) -> int | None:
        if not self.timings:
            return None
        v = self.timings.get("exit_code")
        return int(v) if isinstance(v, (int, float)) else None

    @property
    def stages(self) -> list[dict[str, Any]]:
        if not self.timings:
            return []
        st = self.timings.get("stages") or []
        return [s for s in st if isinstance(s, dict)]


def _discover_cycles(cycles_dir: Path) -> list[int]:
    """Return the sorted set of cycle numbers that left ANY artefact behind.

    Looks for timings, research, scout, and quality reports — a cycle that
    produced even one of these counts as "ran" and gets a row in the
    report (even if every other file is missing).
    """
    if not cycles_dir.is_dir():
        return []
    found: set[int] = set()
    patterns = (
        ("cycle-", "-timings.json"),
        ("cycle-", "-research.json"),
        ("cycle-", "-scout.json"),
        ("cycle-", "-quality-report.json"),
    )
    for prefix, suffix in patterns:
        for p in cycles_dir.glob(f"{prefix}*{suffix}"):
            stem = p.stem
            mid = stem[len(prefix) :]
            num_part = mid.split("-", 1)[0]
            try:
                found.add(int(num_part))
            except ValueError:
                continue
    return sorted(found)


def _load_cycle_row(cycles_dir: Path, cycle: int) -> _CycleRow:
    c3 = f"{cycle:03d}"
    row = _CycleRow(cycle=cycle)
    row.timings = _safe_read_json(cycles_dir / f"cycle-{c3}-timings.json")
    row.research = _safe_read_json(cycles_dir / f"cycle-{c3}-research.json")
    row.scout = _safe_read_json(cycles_dir / f"cycle-{c3}-scout.json")
    row.quality = _safe_read_json(cycles_dir / f"cycle-{c3}-quality-report.json")

    # Cost sidecars — sidecar v1.1 under agent-calls/ (spec 028).
    agent_calls = cycles_dir / f"cycle-{c3}" / "agent-calls"
    if agent_calls.is_dir():
        for sidecar_path in sorted(agent_calls.glob("*.json")):
            data = _safe_read_json(sidecar_path)
            if data is not None:
                row.tokens.add(_normalize_sidecar_tokens(data))
    return row


def _fmt_seconds(s: float | None) -> str:
    """Render a duration in s as ``Hh MMm SSs`` (or ``MMm SSs`` / ``SSs``)."""
    if s is None or s < 0:
        return "—"
    s_int = int(round(s))
    h, rem = divmod(s_int, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {sec:02d}s"
    if m:
        return f"{m}m {sec:02d}s"
    return f"{sec}s"


def _fmt_int(n: int) -> str:
    return f"{n:,}" if n else "0"


def _fmt_usd(v: float) -> str:
    if v < 0.01:
        return f"${v:.4f}"
    return f"${v:.2f}"


def _exit_label(exit_code: int | None) -> str:
    if exit_code is None:
        return "—"
    return {0: "CONTINUE", 1: "TERMINATE", 2: "ABORT"}.get(exit_code, str(exit_code))


def _exit_status(exit_code: int | None) -> str | None:
    """Map an orchestrator run exit code to the spec-061 lifecycle status.

    Mirrors ``vault_commit`` final-status vocabulary: 0 ⇒ ``complete``,
    1 ⇒ ``constrained`` (budget/cycle cap or source-exhausted), 2 ⇒
    ``aborted``. ``None`` (no overall code supplied) ⇒ ``None``.
    """
    if exit_code is None:
        return None
    return {0: "complete", 1: "constrained", 2: "aborted"}.get(exit_code, "constrained")


def _top_stages(stages: list[dict[str, Any]], n: int) -> list[tuple[str, float]]:
    """Return ``(name, duration_s)`` for the ``n`` longest stages."""
    rows: list[tuple[str, float]] = []
    for s in stages:
        d = s.get("duration_s")
        if not isinstance(d, (int, float)):
            continue
        rows.append((str(s.get("stage") or "?"), float(d)))
    rows.sort(key=lambda x: x[1], reverse=True)
    return rows[:n]


def write_run_report(
    vault_dir: Path,
    *,
    final_exit_code: int | None = None,
    final_exit_reason: str | None = None,
    cycle_budget_configured: int | None = None,
    cycle_budget_source: str | None = None,
    rejected_unresolved: int | None = None,
) -> Path:
    """Write ``_pipeline/run-report.md``; return its path. Never raises.

    Called from the orchestrator's exit paths (success / source-exhausted /
    constrained / abort). ``final_exit_code`` and ``final_exit_reason``
    describe the overall run, not any single cycle (each cycle's own exit
    code is read from its timings sidecar).

    Spec 061 (FR4): when ``cycle_budget_configured``/``_source`` are supplied
    (the resolver provenance), the report records a ``cycle_budget`` object
    ``{configured, source, actual, exit_status}`` — written to the additive
    ``_pipeline/run-report.json`` and echoed as a "Cycle budget:" headline in
    the markdown — so a constrained (``max_cycles`` reached) run is
    distinguishable from a clean completion (spec 063 GA-004 consumes this).
    ``actual`` is the number of cycles that left artifacts behind.
    """
    pipeline_dir = vault_dir / "_pipeline"
    cycles_dir = pipeline_dir / "cycles"
    dest = pipeline_dir / "run-report.md"

    try:
        cycle_nums = _discover_cycles(cycles_dir)
        rows = [_load_cycle_row(cycles_dir, n) for n in cycle_nums]

        cycle_budget = {
            "configured": cycle_budget_configured,
            "source": cycle_budget_source,
            "actual": len(rows),
            "exit_status": _exit_status(final_exit_code),
        }
        _write_run_report_json(
            pipeline_dir,
            final_exit_code=final_exit_code,
            final_exit_reason=final_exit_reason,
            cycle_budget=cycle_budget,
            rejected_unresolved=rejected_unresolved,
        )

        # Grand totals.
        total_duration = sum((r.total_duration_s or 0.0) for r in rows)
        total_cost = sum(r.tokens.cost_usd for r in rows)
        total_input = sum(r.tokens.input_tokens for r in rows)
        total_output = sum(r.tokens.output_tokens for r in rows)
        total_cache_read = sum(r.tokens.cache_read_input_tokens for r in rows)
        total_notes_created = sum(r.notes_created for r in rows)
        total_notes_updated = sum(r.notes_updated for r in rows)
        total_topics_new = sum(r.topics_new for r in rows)

        out: list[str] = []
        out.append("# Run report\n")
        if final_exit_code is not None:
            out.append(
                f"**Run exit**: {_exit_label(final_exit_code)} "
                f"(exit code {final_exit_code})"
            )
            if final_exit_reason:
                out.append(f"  \n*Reason*: {final_exit_reason.strip()}")
            out.append("")

        # Spec 061 FR4: human-readable budget provenance headline.
        if cycle_budget_configured is not None or cycle_budget_source is not None:
            out.append(
                f"**Cycle budget**: configured **{cycle_budget['configured']}** "
                f"(source `{cycle_budget['source']}`), "
                f"actual **{cycle_budget['actual']}** "
                f"→ **{cycle_budget['exit_status']}**\n"
            )

        # Spec 062 FR1: verifier-rejected quarantine headline. Always emit when a
        # count is supplied so a constrained exit cannot hide rejected notes.
        if rejected_unresolved is not None:
            if rejected_unresolved > 0:
                out.append(
                    f"**Verifier**: {rejected_unresolved} note(s) ended the run "
                    f"rejected and were quarantined "
                    f"(see `_pipeline/quarantine/`).\n"
                )
            else:
                out.append(
                    "**Verifier**: 0 notes ended the run rejected "
                    "(indexed corpus is clean).\n"
                )

        out.append("## Totals\n")
        out.append(f"- Cycles run: **{len(rows)}**")
        out.append(f"- Total wall time: **{_fmt_seconds(total_duration)}**")
        out.append(f"- Notes created: **{total_notes_created}**")
        out.append(f"- Notes updated: **{total_notes_updated}**")
        out.append(f"- New scout topics: **{total_topics_new}**")
        out.append(f"- Total cost: **{_fmt_usd(total_cost)}**")
        out.append(
            f"- Tokens — input **{_fmt_int(total_input)}**, "
            f"output **{_fmt_int(total_output)}**, "
            f"cache-read **{_fmt_int(total_cache_read)}**"
        )
        out.append("")

        out.append("## Per-cycle summary\n")
        if not rows:
            out.append("_no cycles ran_\n")
        else:
            out.append(
                "| Cycle | Exit | Wall | Notes (new / upd) | Topics (new) | Cost | Tokens (in / out) |"
            )
            out.append(
                "|------:|:-----|-----:|:------------------|-------------:|-----:|:------------------|"
            )
            for r in rows:
                out.append(
                    f"| {r.cycle} "
                    f"| {_exit_label(r.exit_code)} "
                    f"| {_fmt_seconds(r.total_duration_s)} "
                    f"| {r.notes_created} / {r.notes_updated} "
                    f"| {r.topics_new} "
                    f"| {_fmt_usd(r.tokens.cost_usd)} "
                    f"| {_fmt_int(r.tokens.input_tokens)} / {_fmt_int(r.tokens.output_tokens)} |"
                )
            out.append("")

        # Per-cycle stage breakdown — limited to the 3 longest stages per
        # cycle so the report stays readable on long runs. The full set is
        # always in ``cycle-NNN-timings.json``.
        out.append("## Stage timings (top 3 per cycle)\n")
        any_stages = False
        for r in rows:
            tops = _top_stages(r.stages, n=3)
            if not tops:
                continue
            any_stages = True
            out.append(f"### Cycle {r.cycle}\n")
            for name, dur in tops:
                out.append(f"- `{name}` — {_fmt_seconds(dur)}")
            out.append("")
        if not any_stages:
            out.append("_no timings sidecars recorded_\n")

        from .atomic_write import write_text

        write_text(dest, "\n".join(out) + "\n")
    except Exception as exc:
        _LOG.warning("run_report.write_run_report failed: %s", exc)
    return dest


def _write_run_report_json(
    pipeline_dir: Path,
    *,
    final_exit_code: int | None,
    final_exit_reason: str | None,
    cycle_budget: dict[str, Any],
    rejected_unresolved: int | None = None,
) -> None:
    """Write the additive ``_pipeline/run-report.json`` (spec 061 FR4 / 062 FR1).

    Best-effort and self-contained: a failure here is logged and never
    propagates (the markdown report is the primary surface). The JSON is the
    machine-readable companion that spec 063's GA-004 (cycle_budget) and GA-001
    (``rejected_unresolved``) acceptance gates parse.
    """
    try:
        from .atomic_write import write_json

        payload: dict[str, Any] = {
            "final_exit_code": final_exit_code,
            "final_exit_reason": final_exit_reason,
            "cycle_budget": cycle_budget,
        }
        if rejected_unresolved is not None:
            payload["rejected_unresolved"] = rejected_unresolved
        pipeline_dir.mkdir(parents=True, exist_ok=True)
        write_json(pipeline_dir / "run-report.json", payload)
    except Exception as exc:  # pragma: no cover - defensive
        _LOG.warning("run_report: failed to write run-report.json: %s", exc)
