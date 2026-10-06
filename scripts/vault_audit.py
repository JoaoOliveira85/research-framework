#!/usr/bin/env python3
"""Unified vault audit — deterministic validators + optional Haiku quality checks."""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


def _run_check(name: str, cmd: list[str]) -> dict[str, Any]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        return {
            "rc": result.returncode,
            "output": (result.stdout + result.stderr).strip(),
        }
    except FileNotFoundError as exc:
        return {"rc": 2, "output": f"ERROR: script not found — {exc}"}


def _status(rc: int) -> str:
    return "PASS" if rc == 0 else "FAIL"


def _count_issues(output: str) -> str:
    """Count lines that look like issue reports (heuristic)."""
    lines = [ln for ln in output.splitlines() if ln.strip()]
    # If output mentions a specific count, try to extract it
    for line in lines:
        lower = line.lower()
        if (
            "violation" in lower
            or "error" in lower
            or "issue" in lower
            or "warning" in lower
        ):
            return "see detail"
    return "0" if not output else "-"


def _quality_report_paths(cycles_dir: Path) -> list[tuple[int, Path]]:
    """``cycle-NUM-quality-report.json`` files in cycle order."""
    if not cycles_dir.is_dir():
        return []
    out: list[tuple[int, Path]] = []
    for p in cycles_dir.glob("cycle-*-quality-report.json"):
        m = re.match(r"cycle-(\d+)-quality-report\.json\Z", p.name)
        if m:
            out.append((int(m.group(1)), p))
    out.sort(key=lambda x: x[0])
    return out


def _load_quality_reports(
    paths: list[tuple[int, Path]],
) -> list[tuple[int, dict[str, Any]]]:
    loaded: list[tuple[int, dict[str, Any]]] = []
    for cycle_num, path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            loaded.append((cycle_num, data))
    return loaded


def _pipeline_quality_reports_section(vault_dir: Path) -> str:
    cycles_dir = vault_dir / "_pipeline" / "cycles"
    paths = _quality_report_paths(cycles_dir)
    count = len(paths)
    lines: list[str] = [f"- **Quality report files:** {count}"]

    reports = _load_quality_reports(paths)
    if not reports:
        lines.extend(
            [
                "- **CG-003 (abstraction gate, latest):** N/A",
                "- **Queryability scores (by cycle):** N/A",
                "- **Queryability trajectory (latest):** N/A",
                "- **Aborted cycles (total across reports):** 0",
                "- **Retry count (sum across reports):** 0",
            ]
        )
        return "\n".join(lines)

    latest = reports[-1][1]
    gates = latest.get("gates")
    cg3_line = "N/A"
    if isinstance(gates, dict):
        cg3 = gates.get("CG-003")
        if isinstance(cg3, dict):
            st = cg3.get("status", "?")
            mv = cg3.get("metric_value", "?")
            cg3_line = f"{st} (metric_value={mv})"

    score_parts = []
    for cycle_num, data in reports:
        qs = data.get("queryability_score", "?")
        score_parts.append(f"cycle {cycle_num:03d}: {qs}")
    scores_str = ", ".join(score_parts)

    traj = latest.get("queryability_trajectory", "N/A")
    if traj is None:
        traj = "N/A"

    abort_total = sum(1 for _, d in reports if d.get("aborted") is True)
    retry_sum = sum(int(d.get("retry_count") or 0) for _, d in reports)

    lines.extend(
        [
            f"- **CG-003 (abstraction gate, latest):** {cg3_line}",
            f"- **Queryability scores (by cycle):** {scores_str}",
            f"- **Queryability trajectory (latest):** {traj}",
            f"- **Aborted cycles (total across reports):** {abort_total}",
            f"- **Retry count (sum across reports):** {retry_sum}",
        ]
    )
    return "\n".join(lines)


def _source_quality_table(sources: list[dict[str, Any]]) -> str:
    if not sources:
        return "_No sources.db found or no sources registered._"
    active = [s for s in sources if s.get("status") != "archived"]
    archived = [s for s in sources if s.get("status") == "archived"]
    lines = [
        f"**{len(active)} active, {len(archived)} archived**\n",
        "| Name | Type | Role | Notes Generated | Cycles Active | Last Useful Cycle |",
        "|------|------|------|-----------------|---------------|-------------------|",
    ]
    for s in sources:
        lines.append(
            f"| {s['name']} | {s.get('type', '-')} | {s.get('role', '-')} "
            f"| {s.get('total_notes_generated', 0)} "
            f"| {s.get('cycles_active', 0)} "
            f"| {s.get('last_useful_cycle') or '-'} |"
        )
    return "\n".join(lines)


def _build_report(
    vault_dir: Path,
    results: dict[str, dict[str, Any]],
    source_summary: list[dict[str, Any]],
    llm_results: dict[str, Any],
) -> str:
    timestamp = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d %H:%M UTC")
    vault_name = vault_dir.name

    # Summary table rows
    def _row(label: str, rc: int, detail: str) -> str:
        return f"| {label} | {_status(rc)} | {detail} |"

    active_count = sum(1 for s in source_summary if s.get("status") != "archived")
    archived_count = sum(1 for s in source_summary if s.get("status") == "archived")
    source_detail = (
        f"{active_count} active, {archived_count} archived"
        if source_summary
        else "no sources.db"
    )
    source_status = "INFO" if not source_summary else "PASS"

    llm_status = "SKIP"
    llm_detail = "not requested"
    if llm_results:
        llm_status = llm_results.get("content_quality", {}).get("status", "SKIP")
        llm_detail = llm_results.get("content_quality", {}).get("note", "-")

    overall_rcs = [r["rc"] for r in results.values()]
    # rc != 0, not > 0: a signal-killed check has a negative returncode.
    if any(rc != 0 for rc in overall_rcs):
        overall = "FAIL"
    elif llm_status == "WARN":
        overall = "WARN"
    else:
        overall = "PASS"

    summary_rows = "\n".join(
        [
            _row(
                "Frontmatter validation",
                results["validate_vault"]["rc"],
                _count_issues(results["validate_vault"]["output"]),
            ),
            _row(
                "Template compliance",
                results["template_compliance"]["rc"],
                _count_issues(results["template_compliance"]["output"]),
            ),
            _row(
                "Acronym links",
                results["acronym_links"]["rc"],
                _count_issues(results["acronym_links"]["output"]),
            ),
            _row(
                "Vault health",
                results["vault_health"]["rc"],
                _count_issues(results["vault_health"]["output"]),
            ),
            f"| Source quality | {source_status} | {source_detail} |",
            f"| Content quality (LLM) | {llm_status} | {llm_detail} |",
        ]
    )

    def _section(title: str, content: str) -> str:
        return f"## {title}\n\n{content or '_No output._'}\n"

    parts = [
        f"# Vault Audit — {vault_name} — {timestamp}\n",
        "## Summary\n",
        "| Category | Status | Issues |",
        "|----------|--------|--------|",
        summary_rows,
        f"\n**Overall: {overall}**\n",
        _section("Frontmatter Validation", results["validate_vault"]["output"]),
        _section("Template Compliance", results["template_compliance"]["output"]),
        _section("Acronym Links", results["acronym_links"]["output"]),
        _section("Vault Health", results["vault_health"]["output"]),
        _section("Source Quality", _source_quality_table(source_summary)),
        _section(
            "Pipeline Quality Reports", _pipeline_quality_reports_section(vault_dir)
        ),
    ]

    if llm_results:
        note = llm_results.get("content_quality", {}).get(
            "note", "LLM checks not yet wired."
        )
        parts.append(
            _section("Content Quality (Haiku)", f"**Status: {llm_status}**\n\n{note}")
        )
    else:
        parts.append(
            _section(
                "Content Quality (Haiku)",
                "**Status: SKIP**\n\nPass `--full` to enable LLM-assisted quality checks.",
            )
        )

    return "\n".join(parts)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Unified vault audit — deterministic validators + optional Haiku quality checks.",
        usage="vault_audit.py <vault_dir> [--full] [--no-llm] [--output PATH] [--sample-size N]",
    )
    parser.add_argument("vault_dir", help="Path to the vault directory to audit.")
    parser.add_argument("--full", action="store_true", help="Run LLM-assisted checks.")
    parser.add_argument(
        "--no-llm", action="store_true", help="Skip LLM checks even if --full passed."
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="Write report to PATH (default: _pipeline/audit-report.md).",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=10,
        metavar="N",
        help="Notes per type sampled for LLM checks (default: 10).",
    )
    args = parser.parse_args(argv)

    vault_dir = Path(args.vault_dir).resolve()
    if not vault_dir.exists():
        print(f"ERROR: vault not found: {vault_dir}", file=sys.stderr)
        sys.exit(2)

    python = sys.executable
    # Prefer vault's own scripts bundle; fall back to this script's sibling directory
    scripts = vault_dir / "scripts"
    if not scripts.exists():
        scripts = Path(__file__).parent

    results: dict[str, dict[str, Any]] = {}
    for name, cmd in [
        (
            "validate_vault",
            [python, str(scripts / "validate_vault.py"), str(vault_dir)],
        ),
        (
            "template_compliance",
            [python, str(scripts / "check_template_compliance.py"), str(vault_dir)],
        ),
        (
            "acronym_links",
            [python, str(scripts / "check_acronym_links.py"), str(vault_dir)],
        ),
        (
            "vault_health",
            [python, str(scripts / "vault_health.py"), str(vault_dir), "--offline"],
        ),
    ]:
        results[name] = _run_check(name, cmd)

    # Source quality
    source_summary: list[dict[str, Any]] = []
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from research_framework.pipeline.source_manager import (
            source_quality_summary,
        )

        source_summary = source_quality_summary(vault_dir)
    except Exception:
        pass

    # LLM checks (placeholder — wire real Haiku call here later)
    llm_results: dict[str, Any] = {}
    if args.full and not args.no_llm:
        llm_results["content_quality"] = {
            "status": "SKIP",
            "note": "LLM checks not yet wired — run with `--no-llm` for deterministic-only audit.",
        }

    report = _build_report(vault_dir, results, source_summary, llm_results)

    output_path = (
        Path(args.output)
        if args.output
        else vault_dir / "_pipeline" / "audit-report.md"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"Audit report written to {output_path}")

    any_fail = any(r["rc"] != 0 for r in results.values())
    sys.exit(1 if any_fail else 0)


if __name__ == "__main__":
    main()
