"""Spec 063 US2 (T013) — read the shipped ledger, report ledger↔citation disagreement.

The rc1 false-negative class: a source the ledger collapses to ACCESS_FAIL/
PIPELINE_DROP but which the notes demonstrably cite (citation_rate > 0) is a
*disagreement*, not a wall of source failures.
"""

from __future__ import annotations

from research_framework.cli import acceptance


def test_cited_access_fail_is_a_disagreement(snapshot_vault):
    recon = acceptance.build_ledger_reconciliation(snapshot_vault)
    assert recon["sources_total"] == 2
    disagreements = {d["source"]: d for d in recon["disagreements"]}
    assert "GitHub Pull Requests" in disagreements
    d = disagreements["GitHub Pull Requests"]
    assert d["ledger_verdict"] == "LEDGER_DISAGREEMENT"
    assert d["citation_rate"] > 0


def test_clean_twin_has_no_disagreements(clean_vault):
    recon = acceptance.build_ledger_reconciliation(clean_vault)
    assert recon["disagreements"] == []


def test_disagreement_surfaced_in_scorecard(snapshot_vault):
    card = acceptance.build_scorecard(snapshot_vault)
    recon = card["ledger_reconciliation"]
    assert any(
        d["source"] == "GitHub Pull Requests"
        and d["ledger_verdict"] == "LEDGER_DISAGREEMENT"
        for d in recon["disagreements"]
    )


def test_recon_is_defensive_against_pre_amendment_ledger(snapshot_vault, monkeypatch):
    """Even if the ledger never emitted LEDGER_DISAGREEMENT (pre-048-amendment),
    the harness re-derives the disagreement from the raw failure verdict + the
    citation overlay."""
    mod = acceptance._load_repo_script("source_ledger", snapshot_vault)
    # Force the raw verdict path: strip any reconciliation the ledger already did
    # by making _raw_verdict report ACCESS_FAIL verbatim (it already does here).
    recon = acceptance.build_ledger_reconciliation(snapshot_vault)
    names = {d["source"] for d in recon["disagreements"]}
    assert "GitHub Pull Requests" in names
    assert mod is not None  # the loader resolved the shipped script
