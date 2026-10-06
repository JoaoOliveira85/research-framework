"""Spec 063 US1 (T005–T012) — the six framework-generic gates.

Each gate FAILs/WARNs on the seeded defect in the rc1 snapshot and PASSes on the
clean twin (SC-001). The gates are LLM-call-free; the tier-2 dispatch guard test
stays green independently (no claude/codex subprocess is introduced here).
"""

from __future__ import annotations

import subprocess

import pytest

from research_framework.cli import acceptance


def _by_id(vault):
    return {g.gate_id: g for g in acceptance.run_generic_gates(vault)}


# --- GA-001 rejected-notes-in-corpus ---------------------------------------


def test_ga001_fails_on_rejected_note(snapshot_vault):
    g = _by_id(snapshot_vault)["GA-001"]
    assert g.status == "FAIL"
    assert g.metric_value == 1
    assert any("Cohort Drift" in p for p in g.evidence_paths)


def test_ga001_passes_clean(clean_vault):
    assert _by_id(clean_vault)["GA-001"].status == "PASS"


# --- GA-002 duplicate-notes -------------------------------------------------


def test_ga002_fails_on_os_sibling(snapshot_vault):
    g = _by_id(snapshot_vault)["GA-002"]
    assert g.status == "FAIL"
    assert any("Fingerprint Variant 2.md" in p for p in g.evidence_paths)


def test_ga002_passes_clean(clean_vault):
    assert _by_id(clean_vault)["GA-002"].status == "PASS"


# --- GA-003 git-integrity ---------------------------------------------------


def _git(path, *args):
    subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def test_ga003_warns_without_git(snapshot_vault):
    # The static fixture has no .git — integrity is not assessable: advisory
    # WARN (the scorecard vocabulary is PASS/FAIL/WARN), never a silent PASS.
    assert _by_id(snapshot_vault)["GA-003"].status == "WARN"


def test_ga003_fails_on_untracked_and_dup_cycle_commits(clean_vault):
    # clean_vault already has one "research: cycle 1" commit; add a second for
    # the same cycle = topology defect, plus an untracked note under data_vault/.
    (clean_vault / "data_vault" / "03 - Concepts" / "Extra.md").write_text(
        "x", encoding="utf-8"
    )
    _git(clean_vault, "add", "-A")
    _git(clean_vault, "commit", "-m", "research: cycle 1")
    (clean_vault / "data_vault" / "03 - Concepts" / "Untracked.md").write_text(
        "y", encoding="utf-8"
    )
    g = acceptance.gate_git_integrity(clean_vault)
    assert g.status == "FAIL"
    assert "cycle 1" in g.message


def test_ga003_passes_on_clean_repo(clean_vault):
    assert acceptance.gate_git_integrity(clean_vault).status == "PASS"


# --- GA-004 run-completion --------------------------------------------------


def test_ga004_warns_on_constrained_below_configured(snapshot_vault):
    """Issue #159 + spec 061 FR4: the snapshot's actual=6 < configured=12
    constrained exit is now a WARN (cap tripped early — legitimate but the
    run didn't use its full cycle budget). Pre-rc8 this was a noisy FAIL."""
    g = _by_id(snapshot_vault)["GA-004"]
    assert g.status == "WARN"
    assert g.metric_value == "6/12"
    # Vocabulary alignment: message must use 'complete' (spec 061 FR4), not
    # the stale 'done' phrasing the original gate carried.
    assert "done" not in g.message.lower()


def test_ga004_passes_on_complete(clean_vault):
    assert _by_id(clean_vault)["GA-004"].status == "PASS"


def test_ga004_zero_cycle_clean_exit_is_not_fail(clean_vault):
    import json

    rr = clean_vault / "_pipeline" / "run-report.json"
    payload = json.loads(rr.read_text(encoding="utf-8"))
    payload["cycle_budget"] = {
        "configured": 12,
        "source": "settings.yaml::pipeline.max_cycles",
        "actual": 0,
        "exit_status": "complete",
    }
    rr.write_text(json.dumps(payload), encoding="utf-8")
    assert acceptance.gate_run_completion(clean_vault).status == "PASS"


def test_ga004_passes_on_constrained_at_exact_configured(clean_vault):
    """Spec 061 FR4 canonical constrained shape: actual == configured. The
    operator set a cap of N and used exactly N cycles — that's the *intended*
    constrained outcome, not a failure."""
    import json

    rr = clean_vault / "_pipeline" / "run-report.json"
    payload = json.loads(rr.read_text(encoding="utf-8"))
    payload["cycle_budget"] = {
        "configured": 6,
        "source": "flag",
        "actual": 6,
        "exit_status": "constrained",
    }
    rr.write_text(json.dumps(payload), encoding="utf-8")
    g = acceptance.gate_run_completion(clean_vault)
    assert g.status == "PASS"
    assert g.metric_value == "6/6"
    assert "FR4" in g.message or "configured cap" in g.message


def test_ga004_warns_on_constrained_below_configured_unit(clean_vault):
    """Issue #159: a constrained exit with actual < configured (e.g. the rc7
    dollar-cap-tripped-at-cycle-4-of-6 case) is WARN, not FAIL. The run
    finished honestly; the cap just tripped early."""
    import json

    rr = clean_vault / "_pipeline" / "run-report.json"
    payload = json.loads(rr.read_text(encoding="utf-8"))
    payload["cycle_budget"] = {
        "configured": 6,
        "source": "flag",
        "actual": 4,
        "exit_status": "constrained",
    }
    rr.write_text(json.dumps(payload), encoding="utf-8")
    g = acceptance.gate_run_completion(clean_vault)
    assert g.status == "WARN"
    assert g.metric_value == "4/6"
    assert "tripped early" in g.message or "did not use its full" in g.message


def test_ga004_fails_on_aborted_status(clean_vault):
    """An 'aborted' exit_status (structural error) remains FAIL."""
    import json

    rr = clean_vault / "_pipeline" / "run-report.json"
    payload = json.loads(rr.read_text(encoding="utf-8"))
    payload["cycle_budget"] = {
        "configured": 6,
        "source": "flag",
        "actual": 2,
        "exit_status": "aborted",
    }
    rr.write_text(json.dumps(payload), encoding="utf-8")
    g = acceptance.gate_run_completion(clean_vault)
    assert g.status == "FAIL"
    assert "aborted" in g.message
    assert "not 'complete'" in g.message  # vocabulary alignment


def test_ga004_fails_on_missing_run_report(tmp_path):
    """Absent ``_pipeline/run-report.json`` ⇒ run didn't finalise ⇒ FAIL."""
    vault = tmp_path / "v"
    (vault / "_pipeline").mkdir(parents=True)
    g = acceptance.gate_run_completion(vault)
    assert g.status == "FAIL"
    assert "did not finalise" in g.message


def test_ga004_message_never_uses_stale_done_vocabulary(snapshot_vault):
    """Issue #159 root-cause regression: the spec 061 FR4 vocabulary uses
    'complete', not 'done'. The FAIL/WARN messages must never mention 'done'
    (the stale term that produced the rc7 noise)."""
    for fixture in [snapshot_vault]:
        g = _by_id(fixture)["GA-004"]
        assert "'done'" not in g.message, (
            f"GA-004 message still uses stale 'done' vocabulary: {g.message!r}"
        )


# --- GA-005 cost-telemetry --------------------------------------------------


def test_ga005_fails_on_zero_cost(snapshot_vault):
    g = _by_id(snapshot_vault)["GA-005"]
    assert g.status == "FAIL"
    assert g.metric_value == 0.0


def test_ga005_passes_with_cost_and_tokens(clean_vault):
    assert _by_id(clean_vault)["GA-005"].status == "PASS"


# --- GA-006 template-drift (WARN) ------------------------------------------


def test_ga006_warns_on_drift(snapshot_vault):
    g = _by_id(snapshot_vault)["GA-006"]
    assert g.status == "WARN"
    assert g.metric_value >= 1


def test_ga006_passes_when_matched(clean_vault):
    assert _by_id(clean_vault)["GA-006"].status == "PASS"


# --- Exit-code aggregation (T012) ------------------------------------------


def test_exit_code_one_iff_any_fail(snapshot_vault):
    card = acceptance.build_scorecard(snapshot_vault)
    assert card["overall"]["exit_code"] == 1
    assert card["overall"]["fail_count"] >= 1


def test_clean_exit_zero(clean_vault):
    card = acceptance.build_scorecard(clean_vault)
    assert card["overall"]["exit_code"] == 0
    assert card["overall"]["status"] == "PASS"


def test_warn_does_not_block_unless_strict(snapshot_vault):
    # Build a WARN-only vault: remove the FAIL triggers, keep template drift.
    import json

    # Neutralise GA-001 (rejected note), GA-002 (dup), GA-004, GA-005.
    (snapshot_vault / "data_vault" / "03 - Concepts" / "Cohort Drift.md").unlink()
    (
        snapshot_vault / "data_vault" / "03 - Concepts" / "Fingerprint Variant 2.md"
    ).unlink()
    rr = snapshot_vault / "_pipeline" / "run-report.json"
    payload = json.loads(rr.read_text(encoding="utf-8"))
    payload["cycle_budget"]["actual"] = 12
    payload["cycle_budget"]["exit_status"] = "complete"
    payload["rejected_unresolved"] = 0
    rr.write_text(json.dumps(payload), encoding="utf-8")
    sidecar = (
        snapshot_vault
        / "_pipeline"
        / "cycles"
        / "cycle-006"
        / "agent-calls"
        / "note_writer-001.json"
    )
    s = json.loads(sidecar.read_text(encoding="utf-8"))
    s.update({"cost_usd": 0.5, "tokens_in": 10, "tokens_out": 5})
    sidecar.write_text(json.dumps(s), encoding="utf-8")

    relaxed = acceptance.build_scorecard(snapshot_vault, strict=False)
    assert relaxed["overall"]["warn_count"] >= 1
    assert relaxed["overall"]["exit_code"] == 0  # WARN never blocks by default

    strict = acceptance.build_scorecard(snapshot_vault, strict=True)
    assert strict["overall"]["exit_code"] == 1  # --strict promotes WARN to blocking


@pytest.mark.parametrize("vault_fixture", ["snapshot_vault", "clean_vault"])
def test_gates_are_llm_free(vault_fixture, request, monkeypatch):
    """No gate spawns a subprocess other than git (determinism + Principle IV)."""
    vault = request.getfixturevalue(vault_fixture)
    real_run = subprocess.run

    def _guard(cmd, *a, **k):
        argv = cmd if isinstance(cmd, (list, tuple)) else [cmd]
        exe = str(argv[0]) if argv else ""
        assert "claude" not in exe and "codex" not in exe, f"LLM dispatch: {argv}"
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(subprocess, "run", _guard)
    acceptance.run_generic_gates(vault)
