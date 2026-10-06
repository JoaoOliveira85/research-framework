"""Orchestrator watermark verdict history + source health reporting (spec 038 US1)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import yaml

from research_framework.pipeline.source_bridge.cache import load_watermarks
from research_framework.pipeline.source_bridge.orchestrator import run_extraction
from tests._helpers.fake_module import FAKE_PREFLIGHT_BLOCK, write_fake_extractor

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
                  "corrections": [], "messages": ["auth probe failed"]}))
"""


def _build_vault(
    tmp_path: Path,
    *,
    name: str = "demo",
    payload: dict | None = None,
) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "research.spec.md").write_text("# Spec\n", encoding="utf-8")
    (vault / "settings.yaml").write_text(
        textwrap.dedent(
            f"""
            pipeline:
              max_cycles: 10
              budget_usd: 1.0
            modules: [{name!r}]
            stages:
              source_extraction:
                enabled: true
                tier: basic
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    mod = vault / "modules" / name
    mod.mkdir(parents=True)
    manifest = {
        "name": name,
        "version": "0.1.0",
        "description": "d",
        "triggers": [{"type": "path_pattern", "pattern": ".*"}],
        "entry_point": "extractor.py",
        "preflight": FAKE_PREFLIGHT_BLOCK,
        "default_value_tier": "routine",
        "schema_examples": "few-shot.md",
    }
    (mod / "manifest.yaml").write_text(yaml.dump(manifest), encoding="utf-8")
    (mod / "sources.yaml").write_text(
        yaml.dump({"sources": [{"path": "/tmp/repo", "value_tier": "routine"}]}),
        encoding="utf-8",
    )
    (mod / "preflight.py").write_text(_PF_SUCCESS.strip() + "\n", encoding="utf-8")
    write_fake_extractor(mod, stdout_payload=payload)
    return vault


def test_orchestrator_appends_verdict_after_source_cycle(tmp_path: Path) -> None:
    payload = {
        "module": "demo",
        "source_id": "/tmp/repo",
        "source_version": "v1",
        "bridge_version": "0.8.0",
        "extracted_at": "2026-06-01T00:00:00Z",
        "verdict": "error",
        "truncated": False,
        "partial": False,
        "facts": {"error": "HTTP 401"},
        "notable": [],
    }
    vault = _build_vault(tmp_path, payload=payload)
    run_extraction(vault, cycle=1)
    watermarks = load_watermarks(vault, "demo")
    assert watermarks["/tmp/repo"].recent_cycle_verdicts == ["error"]


def test_orchestrator_retains_only_last_three_verdicts(tmp_path: Path) -> None:
    vault = _build_vault(
        tmp_path,
        payload={
            "module": "demo",
            "source_id": "/tmp/repo",
            "source_version": "v1",
            "bridge_version": "0.8.0",
            "extracted_at": "2026-06-01T00:00:00Z",
            "verdict": "ok",
            "truncated": False,
            "partial": False,
            "facts": {"status": "ready"},
            "notable": [],
        },
    )
    verdicts = ["ok", "empty", "error", "ok"]
    for cycle, verdict in enumerate(verdicts, start=1):
        mod = vault / "modules" / "demo"
        facts: dict = {"status": "ready"} if verdict == "ok" else {}
        if verdict == "error":
            facts = {"error": "HTTP 500"}
        write_fake_extractor(
            mod,
            stdout_payload={
                "module": "demo",
                "source_id": "/tmp/repo",
                "source_version": f"v{cycle}",
                "bridge_version": "0.8.0",
                "extracted_at": "2026-06-01T00:00:00Z",
                "verdict": verdict,
                "truncated": False,
                "partial": False,
                "facts": facts,
                "notable": [],
            },
        )
        run_extraction(vault, cycle=cycle)
    watermarks = load_watermarks(vault, "demo")
    assert watermarks["/tmp/repo"].recent_cycle_verdicts == ["empty", "error", "ok"]


def test_orchestrator_emits_source_health_line_for_error_verdict(
    tmp_path: Path,
) -> None:
    vault = _build_vault(
        tmp_path,
        payload={
            "module": "demo",
            "source_id": "/tmp/repo",
            "source_version": "v1",
            "bridge_version": "0.8.0",
            "extracted_at": "2026-06-01T00:00:00Z",
            "verdict": "error",
            "truncated": False,
            "partial": False,
            "facts": {"error": "HTTP 401"},
            "notable": [],
        },
    )
    summary = run_extraction(vault, cycle=1)
    lines = summary["modules"][0].get("source_health", [])
    assert any("source health: demo FAILED with HTTP 401" in line for line in lines)


def test_orchestrator_omits_empty_and_ok_from_source_health(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "research.spec.md").write_text("# Spec\n", encoding="utf-8")
    (vault / "settings.yaml").write_text(
        "pipeline:\n  max_cycles: 3\n  budget_usd: 1.0\n"
        "modules: [good, empty_mod]\n"
        "stages:\n  source_extraction:\n    enabled: true\n    tier: basic\n",
        encoding="utf-8",
    )
    for name, verdict in (("good", "ok"), ("empty_mod", "empty")):
        mod = vault / "modules" / name
        mod.mkdir(parents=True)
        manifest = {
            "name": name,
            "version": "0.1.0",
            "description": "d",
            "triggers": [{"type": "path_pattern", "pattern": ".*"}],
            "entry_point": "extractor.py",
            "preflight": FAKE_PREFLIGHT_BLOCK,
            "default_value_tier": "routine",
            "schema_examples": "few-shot.md",
        }
        (mod / "manifest.yaml").write_text(yaml.dump(manifest), encoding="utf-8")
        (mod / "sources.yaml").write_text(
            yaml.dump({"sources": [{"path": "/tmp/repo", "value_tier": "routine"}]}),
            encoding="utf-8",
        )
        (mod / "preflight.py").write_text(_PF_SUCCESS.strip() + "\n", encoding="utf-8")
        write_fake_extractor(
            mod,
            stdout_payload={
                "module": name,
                "source_id": "/tmp/repo",
                "source_version": "v1",
                "bridge_version": "0.8.0",
                "extracted_at": "2026-06-01T00:00:00Z",
                "verdict": verdict,
                "truncated": False,
                "partial": False,
                "facts": {"status": "ready"} if verdict == "ok" else {},
                "notable": [],
            },
        )
    summary = run_extraction(vault, cycle=1)
    for mod_stat in summary["modules"]:
        assert mod_stat.get("source_health", []) == []


def _build_vault_fatal_preflight(
    tmp_path: Path,
    *,
    failure_policy: str | None = None,
) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "research.spec.md").write_text("# Spec\n", encoding="utf-8")
    (vault / "settings.yaml").write_text(
        "pipeline:\n  max_cycles: 3\n  budget_usd: 1.0\n"
        "modules: [demo]\n"
        "stages:\n  source_extraction:\n    enabled: true\n    tier: basic\n",
        encoding="utf-8",
    )
    mod = vault / "modules" / "demo"
    mod.mkdir(parents=True)
    manifest: dict = {
        "name": "demo",
        "version": "0.1.0",
        "description": "d",
        "triggers": [{"type": "path_pattern", "pattern": ".*"}],
        "entry_point": "extractor.py",
        "preflight": FAKE_PREFLIGHT_BLOCK,
        "default_value_tier": "routine",
        "schema_examples": "few-shot.md",
    }
    if failure_policy is not None:
        manifest["failure_policy"] = failure_policy
    (mod / "manifest.yaml").write_text(yaml.dump(manifest), encoding="utf-8")
    (mod / "sources.yaml").write_text(
        yaml.dump({"sources": [{"path": "/tmp/repo", "value_tier": "routine"}]}),
        encoding="utf-8",
    )
    write_fake_extractor(
        mod,
        stdout_payload={
            "module": "demo",
            "source_id": "/tmp/repo",
            "source_version": "v1",
            "bridge_version": "0.8.0",
            "extracted_at": "2026-06-01T00:00:00Z",
            "verdict": "ok",
            "truncated": False,
            "partial": False,
            "facts": {"status": "ready"},
            "notable": [],
        },
    )
    (mod / "preflight.py").write_text(_PF_FATAL.strip() + "\n", encoding="utf-8")
    return vault


def test_default_block_cycle_skips_on_fatal_fail(tmp_path: Path) -> None:
    vault = _build_vault_fatal_preflight(tmp_path)
    summary = run_extraction(vault, cycle=1)
    mod = summary["modules"][0]
    assert mod["preflight"]["verdict"] == "fatal_fail"
    assert mod["preflight_policy"] == "block_cycle"
    assert mod.get("preflight_degraded") is None
    assert mod.get("preflight_deferred") is None
    assert summary["extractions"] == 0


def test_degrade_gracefully_warns_and_skips_module(tmp_path: Path) -> None:
    vault = _build_vault_fatal_preflight(tmp_path, failure_policy="degrade_gracefully")
    summary = run_extraction(vault, cycle=1)
    mod = summary["modules"][0]
    assert mod["preflight_policy"] == "degrade_gracefully"
    assert mod.get("preflight_degraded") is True
    assert summary["extractions"] == 0
    assert summary.get("skipped") is not True


def test_defer_marks_retry_and_continues(tmp_path: Path) -> None:
    vault = _build_vault_fatal_preflight(tmp_path, failure_policy="defer")
    summary = run_extraction(vault, cycle=1)
    mod = summary["modules"][0]
    assert mod["preflight_policy"] == "defer"
    assert mod.get("preflight_deferred") is True
    assert summary["extractions"] == 0
