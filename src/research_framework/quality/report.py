"""Regression report I/O and stdout summary (spec 022 US1, T021–T022)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any, TextIO

from .determinism import canonical_json_dumps
from .models import RegressionReport

__all__ = (
    "print_regression_summary",
    "write_regression_report",
)

_VERDICT_RANK = {"pass": 0, "warn": 1, "fail": 2}
_INDICATOR = {"pass": "✓", "warn": "⚠  WARN", "fail": "✗  FAIL"}


def write_regression_report(report: RegressionReport, output_dir: Path) -> Path:
    """Write ``regression-report.json`` under *output_dir* (atomic)."""
    path = output_dir / "regression-report.json"
    _atomic_canonical_json_write(path, _report_to_dict(report))
    return path


def print_regression_summary(
    report: RegressionReport,
    stream: TextIO | None = None,
    *,
    color: bool | None = None,
) -> None:
    """Pretty-print harness results per regression-report contract § 3."""
    if stream is None:
        stream = sys.stdout
    use_color = color if color is not None else False
    if color is None and hasattr(stream, "isatty") and stream.isatty():
        use_color = True
    if not (hasattr(stream, "isatty") and stream.isatty()):
        use_color = False

    def _c(text: str, code: str) -> str:
        if not use_color:
            return text
        return f"\033[{code}m{text}\033[0m"

    fixture_names = sorted(report.fixtures)
    lines: list[str] = [
        "=== Quality Harness Run ===",
        f"  Harness version : {report.harness_version}",
        f"  Timestamp       : {report.run_timestamp}",
        f"  Fixtures        : {len(fixture_names)} ({', '.join(fixture_names)})",
        "",
    ]
    pass_n = warn_n = fail_n = 0
    for name in fixture_names:
        fx = report.fixtures[name]
        status = fx.verdict.upper()
        if fx.verdict == "pass":
            pass_n += 1
        elif fx.verdict == "warn":
            warn_n += 1
        else:
            fail_n += 1
        lines.append(f"--- {name} ---")
        lines.append(
            f"  Status: {_c(status, '32' if fx.verdict == 'pass' else '33' if fx.verdict == 'warn' else '31')}"
        )
        for key in sorted(fx.metric_diffs):
            diff = fx.metric_diffs[key]
            delta = diff.delta_pct
            delta_s = (
                f"{delta:+.1f}%" if isinstance(delta, (int, float)) else str(delta)
            )
            ind = _INDICATOR.get(diff.verdict, "?")
            lines.append(
                f"  {key:<32}= {diff.current:<8} "
                f"(baseline {diff.baseline}, Δ {delta_s})  {ind}"
            )
        # A gated metric with nothing to divide carries no verdict. Say so
        # rather than letting its absence read as a pass (issue #268).
        for key in sorted(fx.unmeasured):
            lines.append(f"  {key:<32}= {'—':<8} (UNMEASURED: {fx.unmeasured[key]})  ∅")
        lines.append(f"  Summary: {fx.summary}")
        lines.append("")

    top = report.verdict.upper()
    lines.extend(
        [
            f"=== Verdict: {_c(top, '31' if report.verdict == 'fail' else '33' if report.verdict == 'warn' else '32')} ===",
            f"  {len(fixture_names)} fixtures checked: "
            f"{pass_n} pass, {warn_n} warn, {fail_n} fail",
            "  Regression report: _pipeline/quality/regression-report.json",
        ]
    )
    stream.write("\n".join(lines) + "\n")
    stream.flush()


def _report_to_dict(report: RegressionReport) -> dict[str, Any]:
    fixtures: dict[str, Any] = {}
    for name, fx in sorted(report.fixtures.items()):
        metric_diffs: dict[str, Any] = {}
        for key, diff in sorted(fx.metric_diffs.items()):
            metric_diffs[key] = {
                "baseline": diff.baseline,
                "current": diff.current,
                "delta_pct": diff.delta_pct,
                "direction": diff.direction,
                "verdict": diff.verdict,
            }
        fixtures[name] = {
            "verdict": fx.verdict,
            "metric_diffs": metric_diffs,
            "summary": fx.summary,
            "unmeasured": dict(sorted(fx.unmeasured.items())),
        }
    return {
        "schema_version": report.schema_version,
        "run_timestamp": report.run_timestamp,
        "harness_version": report.harness_version,
        "verdict": report.verdict,
        "fixtures": fixtures,
    }


def _atomic_canonical_json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = canonical_json_dumps(payload).encode("utf-8")
    with tempfile.NamedTemporaryFile(
        dir=path.parent, delete=False, suffix=".tmp"
    ) as tf:
        tmp = Path(tf.name)
        tf.write(content)
    try:
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
