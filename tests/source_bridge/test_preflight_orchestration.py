"""`run_extraction` spawns each module's preflight and honours the verdict
table (spec 051 FR4, T037).

success → run normally; warning → run + record corrections; fatal_fail → skip
ONLY that module (others still run). A crashing / timing-out / garbage-emitting
preflight maps to fatal_fail (fail-closed).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import yaml

from research_framework.pipeline.source_bridge.orchestrator import run_extraction
from tests._helpers.fake_module import write_fake_extractor

_PF_SUCCESS = """
import json, sys
sys.stdin.read()
print(json.dumps({"schema_version": "1.0", "verdict": "success",
                  "corrections": [], "messages": []}))
"""
_PF_FATAL = """
import json, sys
sys.stdin.read()
print(json.dumps({"schema_version": "1.0", "verdict": "fatal_fail",
                  "corrections": [], "messages": ["unusable config"]}))
"""
_PF_WARNING = """
import json, sys
sys.stdin.read()
print(json.dumps({"schema_version": "1.0", "verdict": "warning",
                  "corrections": [{"original": "a", "suggested": "b",
                                   "reason": "typo", "applied": False}],
                  "messages": ["heads up"]}))
"""
_PF_CRASH = """
import sys
sys.stdin.read()
raise SystemExit(3)
"""
_PF_GARBAGE = """
import sys
sys.stdin.read()
print("this is not json")
"""
_PF_HANG = """
import sys, time
sys.stdin.read()
time.sleep(10)
"""


def _build_vault(tmp_path: Path, modules: list[tuple]) -> Path:
    """modules: (name, preflight_body[, timeout_seconds])."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "research.spec.md").write_text("# Spec\n", encoding="utf-8")
    names = [m[0] for m in modules]
    (vault / "settings.yaml").write_text(
        textwrap.dedent(
            f"""
            pipeline:
              max_cycles: 3
              budget_usd: 1.0
            modules: {names}
            stages:
              source_extraction:
                enabled: true
                tier: basic
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    for entry in modules:
        name, pf_body = entry[0], entry[1]
        timeout = entry[2] if len(entry) > 2 else 5
        mod = vault / "modules" / name
        mod.mkdir(parents=True)
        manifest = {
            "name": name,
            "version": "0.1.0",
            "description": "d",
            "triggers": [{"type": "path_pattern", "pattern": ".*"}],
            "entry_point": "extractor.py",
            "preflight": {"entry_point": "preflight.py", "timeout_seconds": timeout},
            "default_value_tier": "routine",
            "schema_examples": "few-shot.md",
        }
        (mod / "manifest.yaml").write_text(yaml.dump(manifest), encoding="utf-8")
        (mod / "sources.yaml").write_text(
            yaml.dump({"sources": [{"path": "/tmp/repo", "value_tier": "routine"}]}),
            encoding="utf-8",
        )
        write_fake_extractor(mod)  # writes extractor.py + a success preflight.py
        (mod / "preflight.py").write_text(pf_body.strip() + "\n", encoding="utf-8")
    return vault


def _stat(summary: dict, name: str) -> dict:
    return next(m for m in summary["modules"] if m["name"] == name)


def test_success_preflight_runs_module(tmp_path: Path) -> None:
    summary = run_extraction(_build_vault(tmp_path, [("good", _PF_SUCCESS)]), cycle=1)
    assert _stat(summary, "good")["preflight"]["verdict"] == "success"
    assert summary["extractions"] >= 1


def test_fatal_preflight_skips_module_no_extraction(tmp_path: Path) -> None:
    summary = run_extraction(_build_vault(tmp_path, [("broken", _PF_FATAL)]), cycle=1)
    assert _stat(summary, "broken")["preflight"]["verdict"] == "fatal_fail"
    assert summary["extractions"] == 0  # skipped — nothing processed


def test_fatal_in_one_module_does_not_block_others(tmp_path: Path) -> None:
    summary = run_extraction(
        _build_vault(tmp_path, [("broken", _PF_FATAL), ("good", _PF_SUCCESS)]),
        cycle=1,
    )
    assert _stat(summary, "broken")["preflight"]["verdict"] == "fatal_fail"
    assert _stat(summary, "good")["preflight"]["verdict"] == "success"
    assert summary["extractions"] >= 1  # good still ran


def test_warning_preflight_runs_and_records_corrections(tmp_path: Path) -> None:
    summary = run_extraction(_build_vault(tmp_path, [("warned", _PF_WARNING)]), cycle=1)
    stat = _stat(summary, "warned")
    assert stat["preflight"]["verdict"] == "warning"
    assert stat["preflight"]["corrections"][0]["suggested"] == "b"
    assert summary["extractions"] >= 1  # warning still runs the module


def test_crashing_preflight_is_fatal_fail(tmp_path: Path) -> None:
    summary = run_extraction(_build_vault(tmp_path, [("crash", _PF_CRASH)]), cycle=1)
    assert _stat(summary, "crash")["preflight"]["verdict"] == "fatal_fail"
    assert summary["extractions"] == 0


def test_garbage_preflight_is_fatal_fail(tmp_path: Path) -> None:
    summary = run_extraction(
        _build_vault(tmp_path, [("garbage", _PF_GARBAGE)]), cycle=1
    )
    assert _stat(summary, "garbage")["preflight"]["verdict"] == "fatal_fail"


def test_timing_out_preflight_is_fatal_fail(tmp_path: Path) -> None:
    # timeout_seconds=1, preflight sleeps 10 → tree-killed → fatal_fail
    summary = run_extraction(_build_vault(tmp_path, [("hang", _PF_HANG, 1)]), cycle=1)
    assert _stat(summary, "hang")["preflight"]["verdict"] == "fatal_fail"
    assert summary["extractions"] == 0


def test_malformed_timeout_seconds_does_not_crash(tmp_path: Path) -> None:
    """A non-int timeout_seconds (e.g. "30s") must fail closed / default, not
    raise out of run_preflight and crash the cycle (Copilot #1)."""
    summary = run_extraction(
        _build_vault(tmp_path, [("good", _PF_SUCCESS, "30s")]), cycle=1
    )
    assert _stat(summary, "good")["preflight"]["verdict"] == "success"


def test_refresh_sources_preflight_sweep_reports_per_module(tmp_path: Path) -> None:
    """The refresh-sources sweep (T044) runs each module's preflight and
    reports a per-module verdict, independent of the collector loop."""
    from research_framework.cli.refresh_sources import _preflight_sweep

    vault = _build_vault(tmp_path, [("broken", _PF_FATAL), ("good", _PF_SUCCESS)])
    rows = {r["module"]: r for r in _preflight_sweep(vault)}
    assert rows["broken"]["verdict"] == "fatal_fail"
    assert rows["good"]["verdict"] == "success"
