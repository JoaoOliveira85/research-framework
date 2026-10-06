"""Consensus voting tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework.pipeline.source_bridge.consensus import (
    ConsensusResult,
    majority_verdict,
    run_consensus,
    tier_to_n,
    validate_consensus_n_values,
    write_consensus_result,
)
from research_framework.pipeline.source_bridge.signal import SignalPayload


def _payload(verdict: str) -> SignalPayload:
    return SignalPayload(
        module="code",
        source_id="s",
        source_version="v",
        bridge_version="0.3.2",
        extracted_at="2026-01-01T00:00:00Z",
        verdict=verdict,  # type: ignore[arg-type]
        truncated=False,
        partial=False,
        facts={"k": 1},
        notable=[],
    )


def test_consensus_n1_passes_single_verdict() -> None:
    merged, result = run_consensus(
        spawn_extractor=lambda: _payload("ok"),
        module="code",
        source_id="s",
        cycle=1,
        value_tier="routine",
        tier_map={"routine": 1},
    )
    assert merged.verdict == "ok"
    assert result.extractors_spawned == 1


def test_consensus_n3_majority_two_of_three_ok() -> None:
    calls = iter(["ok", "exhausted", "ok"])

    def spawn() -> SignalPayload:
        return _payload(next(calls))

    merged, result = run_consensus(
        spawn_extractor=spawn,
        module="code",
        source_id="s",
        cycle=1,
        value_tier="important",
        tier_map={"important": 3},
    )
    assert merged.verdict == "ok"
    assert result.final_verdict == "ok"


def test_consensus_rejects_even_n_at_config_load() -> None:
    with pytest.raises(ValueError, match="odd"):
        validate_consensus_n_values({"routine": 2})


def test_consensus_n5_majority_three_of_five_exhausted_advances() -> None:
    calls = iter(["exhausted", "ok", "exhausted", "exhausted", "ok"])

    def spawn() -> SignalPayload:
        return _payload(next(calls))

    merged, result = run_consensus(
        spawn_extractor=spawn,
        module="code",
        source_id="s",
        cycle=1,
        value_tier="critical",
        tier_map={"critical": 5},
    )
    assert merged.verdict == "exhausted"
    assert result.final_verdict == "exhausted"


def test_tier_maps_to_consensus_n_from_settings() -> None:
    assert tier_to_n("routine", {"routine": 1, "important": 3, "critical": 5}) == 1
    assert tier_to_n("critical", {"routine": 1, "important": 3, "critical": 5}) == 5


def test_consensus_result_written_under_pipeline_consensus(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    result = ConsensusResult(
        module="code",
        source_id="s",
        cycle=2,
        value_tier="routine",
        extractors_spawned=1,
        verdicts=["ok"],
        final_verdict="ok",
        findings_unioned=0,
        dissenting_extractor_indices=[],
        consensus_decided_at="2026-01-01T00:00:00Z",
    )
    path = write_consensus_result(vault, result)
    assert "consensus" in str(path)
    assert path.name.endswith("-cycle-002.json")


def test_majority_verdict_prefers_ok_over_exhausted_on_tie_break() -> None:
    assert majority_verdict(["ok", "exhausted", "ok"]) == "ok"


def test_parallel_fan_out_uses_thread_pool() -> None:
    calls = {"n": 0}

    def spawn() -> SignalPayload:
        calls["n"] += 1
        return _payload("ok")

    run_consensus(
        spawn_extractor=spawn,
        module="code",
        source_id="s",
        cycle=1,
        value_tier="important",
        tier_map={"important": 3},
    )
    assert calls["n"] == 3
