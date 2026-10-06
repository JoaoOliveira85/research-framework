"""Human-only baseline updates for the quality harness (spec 022 FR-007)."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .baseline import diff_against_baseline, load_baseline_json
from .determinism import canonical_json_write
from .models import BaselineJSON, CurrentJSON, MetricDiff
from .runner import (
    _BASELINES_DIR,
    _DEFAULT_OUTPUT_DIR,
    REGISTERED_FIXTURES,
    collect_fixture_current,
)

__all__ = ("update_baseline",)


def update_baseline(
    fixture: str,
    *,
    reason: str,
    actor: str,
    dry_run: bool,
    yes: bool,
) -> int:
    """Run harness for one fixture and optionally bless a new baseline (FR-007)."""
    if yes and not os.environ.get("CI"):
        print(
            "error: --yes is only allowed when $CI is set (prevents accidental "
            "local non-interactive baseline updates)",
            file=sys.stderr,
        )
        return 2

    if fixture not in REGISTERED_FIXTURES:
        registered = ", ".join(sorted(REGISTERED_FIXTURES))
        print(
            f"error: unknown quality fixture {fixture!r}; registered: {registered}",
            file=sys.stderr,
        )
        return 2

    if not dry_run and not reason.strip():
        print("error: --reason is required unless --dry-run", file=sys.stderr)
        return 2

    resolved_actor = actor.strip() or _default_actor()
    out_dir = _DEFAULT_OUTPUT_DIR.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        current, crashed = collect_fixture_current(fixture, output_dir=out_dir)
    except Exception:
        import traceback

        traceback.print_exc(file=sys.stderr)
        return 2
    if crashed:
        # A crashed cycle's metrics are not a measurement of the pipeline;
        # blessing them would lower the gate every later run is held to.
        print(
            f"error: {fixture} cycle crashed — refusing to diff or bless its "
            f"metrics as a baseline (see the preserved workspace path above)",
            file=sys.stderr,
        )
        return 2

    baseline_path = _BASELINES_DIR / f"{fixture}.baseline.json"
    baseline: BaselineJSON | None = None
    if baseline_path.is_file():
        try:
            baseline = load_baseline_json(baseline_path)
        except Exception as exc:
            print(f"error: could not read baseline: {exc}", file=sys.stderr)
            return 2

    report = None
    if baseline is not None:
        report = diff_against_baseline(current, baseline)

    diff_text = _format_baseline_diff(fixture, current, baseline, report)
    print(diff_text)

    if dry_run:
        return 0

    if not yes and not _stdin_is_tty():
        print(
            "error: non-interactive terminal; use --yes in CI or run from a TTY",
            file=sys.stderr,
        )
        return 2

    if not yes:
        try:
            answer = (
                input(f"Apply baseline update for {fixture}? [y/N] ").strip().lower()
            )
        except (EOFError, KeyboardInterrupt):
            print("baseline not updated", file=sys.stderr)
            return 1
        if answer not in {"y", "yes"}:
            print("baseline not updated", file=sys.stderr)
            return 1

    payload = _current_to_baseline_payload(
        current,
        reason=reason.strip(),
        actor=resolved_actor,
    )
    _atomic_write_baseline(baseline_path, payload)
    print(f"Wrote baseline: {baseline_path}")
    return 0


def _default_actor() -> str:
    for key in ("GIT_AUTHOR_NAME", "USER"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return "unknown"


def _stdin_is_tty() -> bool:
    try:
        return sys.stdin.isatty()
    except AttributeError:
        return False


def _is_improvement_only(report: Any) -> bool:
    """True when no metric regressed (pass/warn only) and at least one improved."""
    fx = next(iter(report.fixtures.values()), None)
    if fx is None:
        return False
    has_improvement = False
    for diff in fx.metric_diffs.values():
        if diff.verdict == "fail":
            return False
        if diff.verdict == "warn":
            return False
        if _metric_improved(diff):
            has_improvement = True
    return has_improvement


def _metric_improved(diff: MetricDiff) -> bool:
    if diff.delta_pct == "n/a" or not isinstance(diff.delta_pct, (int, float)):
        return False
    if diff.direction == "higher_is_better":
        return diff.current > diff.baseline
    if diff.direction == "lower_is_better":
        return diff.current < diff.baseline
    return False


def _format_baseline_diff(
    fixture: str,
    current: CurrentJSON,
    baseline: BaselineJSON | None,
    report: Any | None,
) -> str:
    lines = [f"=== Baseline update diff: {fixture} ==="]
    if baseline is None:
        lines.append("(no existing baseline — this run would create a new file)")
        lines.append(f"  coverage_targets_hash: {current.coverage_targets_hash}")
        return "\n".join(lines)

    if report is None:
        return "\n".join(lines)

    fx = report.fixtures.get(fixture)
    if fx is None:
        return "\n".join(lines)

    for key in sorted(fx.metric_diffs):
        diff = fx.metric_diffs[key]
        lines.append(
            f"  {key}: {diff.baseline} → {diff.current} "
            f"({diff.delta_pct}% Δ, {diff.verdict})"
        )
    if _is_improvement_only(report):
        lines.append("  (improvement detected — baseline would not auto-update)")
    return "\n".join(lines)


def _current_to_baseline_payload(
    current: CurrentJSON,
    *,
    reason: str,
    actor: str,
) -> dict[str, Any]:
    return {
        "schema_version": current.schema_version,
        "fixture": current.fixture,
        "baseline_commit": _git_head_short(),
        "last_updated": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_updated_by": actor,
        "last_updated_reason": reason,
        "coverage_targets_hash": current.coverage_targets_hash,
        "metrics": current.metrics,
    }


def _git_head_short() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=_BASELINES_DIR.parents[3],
        )
        return proc.stdout.strip()[:40]
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _atomic_write_baseline(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        canonical_json_write(tmp, payload)
        os.replace(tmp, path)
    except BaseException:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise
