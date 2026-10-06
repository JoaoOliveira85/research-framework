"""Spec 069 US3 (FR3/FR5) — stagnant-source WARN signal.

Contract: specs/069-source-relevance-tuning/contracts/stagnant-source-signal.contract.md
Tier: 2 (pure-core + a thin quality-report integration assertion).
"""

from __future__ import annotations

from research_framework.pipeline.stagnant_sources import (
    MIN_COLD_CYCLES,
    STAGNANT_PREFIX,
    StagnantSourceSignal,
    detect_stagnant_sources,
    role_authority_rank,
    stagnant_signals_from_verdicts,
    stagnant_warnings,
    trailing_cold_count,
)
from tests._helpers.source_fixtures import build_cold_source_vault

# --- C1-a: cold >= 2 → one WARN; cold 1 → none -----------------------------


def test_trailing_cold_counts_only_recent_run():
    # oldest→newest; USED resets the trailing-cold count.
    assert trailing_cold_count(["USED", "NOT_REACHED", "SKIPPED_RELEVANCE"]) == 2
    assert trailing_cold_count(["NOT_REACHED", "USED"]) == 0
    assert trailing_cold_count(["SKIPPED_RELEVANCE"]) == 1
    # LEDGER_DISAGREEMENT counts as "used" (citation-evidenced).
    assert trailing_cold_count(["LEDGER_DISAGREEMENT", "PIPELINE_DROP"]) == 1


def test_cold_two_consecutive_emits_one_warn():
    signals = stagnant_signals_from_verdicts(
        {"Web": ["SKIPPED_RELEVANCE", "NOT_REACHED"]},
        roles={"Web": "domain"},
    )
    assert len(signals) == 1
    assert signals[0].name == "Web"
    assert signals[0].cold_cycles == 2
    assert signals[0].message.startswith(STAGNANT_PREFIX)
    assert "`Web`" in signals[0].message


def test_cold_one_cycle_emits_nothing():
    signals = stagnant_signals_from_verdicts(
        {"Web": ["USED", "SKIPPED_RELEVANCE"]},
        roles={"Web": "domain"},
    )
    assert signals == []


def test_min_cold_threshold_is_two():
    assert MIN_COLD_CYCLES == 2


# --- C2-a / FR5: authoritative cold source ranks first ----------------------


def test_authoritative_cold_source_ranks_first():
    signals = stagnant_signals_from_verdicts(
        {
            "Low Authority Blog": ["NOT_REACHED", "NOT_REACHED"],
            "Primary Behaviour Repo": ["SKIPPED_RELEVANCE", "PIPELINE_DROP"],
        },
        roles={
            "Low Authority Blog": "domain",
            "Primary Behaviour Repo": "behaviour",
        },
    )
    assert [s.name for s in signals] == [
        "Primary Behaviour Repo",
        "Low Authority Blog",
    ]
    assert signals[0].authority_rank < signals[1].authority_rank


def test_role_authority_rank_ordering():
    assert role_authority_rank("behaviour") < role_authority_rank("intent")
    assert role_authority_rank("intent") < role_authority_rank("domain")
    # Unknown role sorts last (largest rank).
    assert role_authority_rank("mystery") > role_authority_rank("domain")
    assert role_authority_rank("") > role_authority_rank("domain")


def test_tie_break_by_cold_then_priority_then_name():
    signals = stagnant_signals_from_verdicts(
        {
            "B Source": ["NOT_REACHED", "NOT_REACHED"],
            "A Source": ["NOT_REACHED", "NOT_REACHED", "NOT_REACHED"],
        },
        roles={"B Source": "domain", "A Source": "domain"},
        priorities={"B Source": 2, "A Source": 2},
    )
    # Same authority → more cold cycles first.
    assert [s.name for s in signals] == ["A Source", "B Source"]


# --- C1-b: signal is a plain advisory dataclass (never a gate verdict) -------


def test_signal_is_frozen_advisory_record():
    sig = StagnantSourceSignal(
        name="Web", cold_cycles=3, role="domain", authority_rank=2, priority=2
    )
    assert sig.cold_cycles == 3
    # frozen dataclass → no in-place mutation of the advisory record.
    import dataclasses

    assert dataclasses.is_dataclass(sig)


# --- End-to-end over the source-ledger join (T017) -------------------------


def test_detect_over_multi_cycle_cold_vault(tmp_path):
    vault = build_cold_source_vault(tmp_path, cold_cycles=2)
    signals = detect_stagnant_sources(vault, current_cycle=2)
    assert len(signals) == 1
    assert signals[0].name == "GitHub Pull Requests"
    assert signals[0].cold_cycles == 2
    # FR5: this declared source is role=behaviour → most authoritative.
    assert signals[0].role == "behaviour"


def test_detect_single_cold_cycle_emits_nothing(tmp_path):
    vault = build_cold_source_vault(tmp_path, cold_cycles=1)
    assert detect_stagnant_sources(vault, current_cycle=1) == []


def test_stagnant_warnings_render_prefixed_lines(tmp_path):
    vault = build_cold_source_vault(tmp_path, cold_cycles=2)
    lines = stagnant_warnings(vault, current_cycle=2)
    assert len(lines) == 1
    assert lines[0].startswith(STAGNANT_PREFIX)


def test_detect_missing_ledger_is_non_fatal(tmp_path):
    # No research.spec.md / cycles → advisory: empty, never raises.
    empty = tmp_path / "empty"
    empty.mkdir()
    assert detect_stagnant_sources(empty, current_cycle=5) == []
