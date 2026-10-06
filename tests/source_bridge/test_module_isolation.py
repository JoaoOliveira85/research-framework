"""Module isolation protocol tests."""

from __future__ import annotations

from pathlib import Path

from research_framework.pipeline.source_bridge.isolation import isolated_call


def test_isolated_call_retries_once_then_returns_none(tmp_path: Path) -> None:
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        raise RuntimeError("boom")

    result = isolated_call(
        flaky,
        vault_dir=tmp_path,
        module="code",
        source_id="s",
        kind="extractor",
    )
    assert result is None
    assert calls["n"] == 2


def test_isolated_call_double_failure_surfaces_without_crash(tmp_path: Path) -> None:
    def always_fail() -> None:
        raise ValueError("fail")

    result = isolated_call(
        always_fail,
        vault_dir=tmp_path,
        module="code",
        source_id="s",
        kind="extractor",
    )
    assert result is None


def test_bridge_log_append_only_per_module(tmp_path: Path) -> None:
    vault = tmp_path / "vault"

    def fail() -> None:
        raise RuntimeError("x")

    isolated_call(
        fail,
        vault_dir=vault,
        module="code",
        source_id="s1",
        kind="extractor",
    )
    log_path = vault / "_pipeline" / "sources" / "code" / "bridge.log"
    assert log_path.is_file()
    first_size = log_path.stat().st_size
    isolated_call(
        fail,
        vault_dir=vault,
        module="code",
        source_id="s2",
        kind="extractor",
    )
    assert log_path.stat().st_size > first_size


def test_sc005_all_sources_fail_isolation_cycle_continues(bridge_vault) -> None:
    from research_framework.pipeline.source_bridge.orchestrator import run_extraction
    from tests._helpers.fake_module import write_fake_extractor

    write_fake_extractor(
        bridge_vault / "modules" / "stub",
        fail_attempts={1, 2},
    )
    summary = run_extraction(bridge_vault, 1)
    assert "modules" in summary
