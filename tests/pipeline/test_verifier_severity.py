"""Spec 066 FR2 — verifier severity split in ``_merge_verifier_verdict``.

Contract: specs/066-credibility-model-calibration/contracts/credibility-catalog.contract.md §6
Only ``severity: fail`` shape violations flip status to rejected; ``warn`` ones
attach as advisory notes. Absent severity defaults to fail (055 back-compat).
"""

from __future__ import annotations

from research_framework.pipeline.verifier import (
    VerifierVerdict,
    _merge_verifier_verdict,
)


def _warn(rule="IX-credibility-unresolved") -> dict:
    return {
        "rule_id": rule,
        "location": "note:n.md",
        "message": "m",
        "severity": "warn",
    }


def _fail(rule="IX-citation-malformed") -> dict:
    return {
        "rule_id": rule,
        "location": "note:n.md",
        "message": "m",
        "severity": "fail",
    }


def _verified() -> VerifierVerdict:
    return VerifierVerdict(note_path="n.md", status="verified")


def test_warn_only_keeps_verified_status_attaches_note():
    merged = _merge_verifier_verdict(_verified(), [_warn()])
    assert merged.status == "verified"
    assert len(merged.violations) == 1
    assert merged.violations[0]["severity"] == "warn"


def test_fail_violation_flips_to_rejected():
    merged = _merge_verifier_verdict(_verified(), [_fail()])
    assert merged.status == "rejected"


def test_mixed_fail_and_warn_rejected_keeps_both():
    merged = _merge_verifier_verdict(_verified(), [_fail(), _warn()])
    assert merged.status == "rejected"
    rule_ids = {v["rule_id"] for v in merged.violations}
    assert "IX-citation-malformed" in rule_ids
    assert "IX-credibility-unresolved" in rule_ids


def test_absent_severity_defaults_to_fail():
    legacy = {"rule_id": "IX-credibility-malformed", "location": "x", "message": "m"}
    merged = _merge_verifier_verdict(_verified(), [legacy])
    assert merged.status == "rejected"


def test_agent_rejected_stays_rejected_with_warn_shape():
    agent = VerifierVerdict(
        note_path="n.md",
        status="rejected",
        violations=[{"rule_id": "agent-thing", "message": "bad"}],
    )
    merged = _merge_verifier_verdict(agent, [_warn()])
    assert merged.status == "rejected"
    rule_ids = {v.get("rule_id") for v in merged.violations}
    assert "agent-thing" in rule_ids
    assert "IX-credibility-unresolved" in rule_ids


def test_no_shape_violations_returns_agent_verdict_unchanged():
    agent = _verified()
    assert _merge_verifier_verdict(agent, []) is agent
