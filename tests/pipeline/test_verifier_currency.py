"""Tier 3: the verifier's currency rules (spec 087 FR-007, FR-013; T009).

``IX-currency-evidence`` and ``IX-supersession-symmetry`` reach their verdict
without a model; a fail rejects the note whatever a model would say.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from research_framework.pipeline import backlog, verifier
from research_framework.pipeline.verifier import VerifierVerdict
from tests._helpers.vault_factory import build_minimal_vault, commit_vault

FOLDER = "data_vault/01 - Concepts"
OLD = f"{FOLDER}/old-approach.md"
NEW = f"{FOLDER}/new-approach.md"


def _note(
    *,
    currency: str = "current",
    sources: str = "[https://example.org/a]",
    extra: str = "",
    body: str = "The body.",
) -> str:
    return (
        "---\n"
        "type: concept\n"
        "summary: s\n"
        f"source_urls: {sources}\n"
        "as_of: 2020-01-01\n"
        f"currency: {currency}\n"
        f"{extra}"
        "---\n\n"
        f"# Note\n\n{body}\n"
    )


def _source(url: str, level: str) -> str:
    return f"[{{url: {url}, credibility: {level}}}]"


def _vault(tmp_path: Path) -> Path:
    vault = build_minimal_vault(tmp_path, num_categories=1, max_cycles=1)
    (vault / FOLDER).mkdir(parents=True, exist_ok=True)
    (vault / OLD).write_text(_note(), encoding="utf-8")
    (vault / NEW).write_text(_note(extra="supersedes: []\n"), encoding="utf-8")
    commit_vault(vault)
    # the update batch closed the entry (UG-001) and recorded its outcome
    assert backlog.update(
        vault,
        "review",
        lambda tx: tx.observe_update("old-approach", "review_due", as_of="2020-01-01"),
    )
    assert backlog.close_update(vault, "old-approach", "superseded", cycle=1)
    return vault


def _record(vault: Path, evidence: str | None) -> None:
    cycles = vault / "_pipeline" / "cycles"
    cycles.mkdir(parents=True, exist_ok=True)
    row = {
        "note": "old-approach",
        "path": OLD,
        "outcome": "superseded",
        "status": "passed",
        "reason": "",
        "sources_consulted": [],
        "evidence_url": evidence,
        "superseded_by": "new-approach",
        "change": "",
        "row": {"note": "old-approach", "outcome": "superseded"},
    }
    (cycles / "cycle-001-update-outcomes.json").write_text(
        json.dumps({"cycle": 1, "results": [row]}), encoding="utf-8"
    )
    (cycles / "cycle-001-research.json").write_text(
        json.dumps({"notes_created": [], "notes_updated": [OLD]}), encoding="utf-8"
    )


def _supersede(vault: Path, level: str, *, symmetric: bool = True) -> str:
    url = "https://example.org/proof"
    (vault / OLD).write_text(
        _note(
            currency="superseded",
            sources=_source(url, level),
            extra="superseded_by: [new-approach]\n",
        ),
        encoding="utf-8",
    )
    if symmetric:
        (vault / NEW).write_text(
            _note(extra="supersedes: [old-approach]\n"), encoding="utf-8"
        )
    return url


def _stage(
    vault: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    model_status: str = "verified",
    report: dict[str, Any] | None = None,
) -> tuple[verifier.VerifierSummary, list[str]]:
    calls: list[str] = []

    def fake_model(**kwargs: Any) -> VerifierVerdict:
        calls.append(kwargs["note_rel"])
        return VerifierVerdict(note_path=kwargs["note_rel"], status=model_status)

    monkeypatch.setattr(verifier, "_call_verifier", fake_model)
    summary = verifier.run_verifier_stage(
        vault,
        1,
        report or {"notes_created": [], "notes_updated": [OLD]},
        settings={"stages": {"verifier": {"enabled": True}}},
    )
    return summary, calls


def _entry(vault: Path) -> dict[str, Any]:
    path = vault / "_pipeline" / "state" / "research-backlog.json"
    return next(
        e
        for e in json.loads(path.read_text("utf-8"))["entries"]
        if e["id"] == "update:old-approach"
    )


def test_supersession_on_commentary_alone_is_rejected_without_a_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(tmp_path)
    _record(vault, _supersede(vault, "commentary"))

    summary, model_calls = _stage(vault, monkeypatch, model_status="verified")

    assert model_calls == []  # no model was asked, and none could overturn it
    (verdict,) = summary.verdicts
    assert verdict.status == "rejected"
    assert [v["rule_id"] for v in verdict.violations][:1] == ["IX-currency-evidence"]
    assert "commentary" in verdict.violations[0]["message"]
    # the update did not stand: the entry is open again, with the reason
    entry = _entry(vault)
    assert entry["status"] == "open"
    assert "outcome" not in entry
    assert entry["outcome_history"][0]["outcome"] == "superseded"
    assert "commentary" in entry["outcome_history"][0]["rejected"]
    results = json.loads(
        (vault / "_pipeline/cycles/cycle-001-update-outcomes.json").read_text("utf-8")
    )["results"]
    assert results[0]["status"] == "failed"
    assert "verifier" in results[0]["reason"]
    report = json.loads(
        (vault / "_pipeline/cycles/cycle-001-research.json").read_text("utf-8")
    )
    assert report["notes_updated"] == []


@pytest.mark.parametrize(
    ("setup", "why"),
    [
        ("no_evidence", "cites no evidence_url"),
        ("not_among_sources", "is not among the note's source_urls"),
        ("unvetted", "unvetted"),
    ],
)
def test_missing_foreign_or_unvetted_evidence_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, setup: str, why: str
) -> None:
    vault = _vault(tmp_path)
    url = _supersede(vault, "unvetted" if setup == "unvetted" else "primary")
    evidence = {
        "no_evidence": None,
        "not_among_sources": "https://example.org/elsewhere",
        "unvetted": url,
    }[setup]
    _record(vault, evidence)

    summary, model_calls = _stage(vault, monkeypatch)

    assert model_calls == []
    assert summary.verdicts[0].status == "rejected"
    assert why in summary.verdicts[0].violations[0]["message"]


@pytest.mark.parametrize("level", ["corroborated", "primary"])
def test_supersession_with_a_corroborated_source_stands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, level: str
) -> None:
    vault = _vault(tmp_path)
    _record(vault, _supersede(vault, level))

    summary, model_calls = _stage(vault, monkeypatch)

    assert model_calls == [OLD]  # the model is still consulted for what it knows
    assert summary.verdicts[0].status == "verified"
    entry = _entry(vault)
    assert (entry["status"], entry["outcome"]) == ("resolved", "superseded")


def test_the_model_cannot_rescue_a_failed_rule_but_may_still_reject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(tmp_path)
    _record(vault, _supersede(vault, "primary"))

    summary, _ = _stage(vault, monkeypatch, model_status="rejected")

    assert summary.verdicts[0].status == "rejected"
    assert _entry(vault)["status"] == "open"


def test_a_one_sided_supersession_link_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(tmp_path)
    _record(vault, _supersede(vault, "primary", symmetric=False))

    summary, model_calls = _stage(vault, monkeypatch)

    assert model_calls == []
    (verdict,) = summary.verdicts
    assert verdict.status == "rejected"
    rules = {v["rule_id"] for v in verdict.violations}
    assert rules == {"IX-supersession-symmetry"}
    assert "does not name this one" in verdict.violations[0]["message"]

    # and the reverse: a successor claiming a note that does not name it back
    (vault / NEW).write_text(_note(extra="supersedes: [old-approach]\n"), "utf-8")
    (vault / OLD).write_text(_note(), encoding="utf-8")
    summary, _ = _stage(
        vault,
        monkeypatch,
        report={"notes_created": [NEW], "notes_updated": []},
    )
    assert summary.verdicts[0].status == "rejected"
    assert summary.verdicts[0].violations[0]["rule_id"] == "IX-supersession-symmetry"


def test_a_successor_reported_pending_is_tolerated_this_cycle_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(tmp_path)
    _record(vault, _supersede(vault, "primary"))
    (vault / NEW).unlink()  # the successor is not written yet

    absent, _ = _stage(vault, monkeypatch)
    assert absent.verdicts[0].status == "rejected"

    pending, _ = _stage(
        vault,
        monkeypatch,
        report={
            "notes_created": [],
            "notes_updated": [OLD],
            "new_wikilinks_discovered": ["[[New Approach]]"],
        },
    )
    assert pending.verdicts[0].status == "verified"
    warned = [v for v in pending.verdicts[0].violations if v.get("severity") == "warn"]
    assert warned and "tolerated for this cycle only" in warned[0]["message"]


def test_a_note_whose_standing_did_not_change_is_not_judged_by_the_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = build_minimal_vault(tmp_path, num_categories=1, max_cycles=1)
    (vault / FOLDER).mkdir(parents=True, exist_ok=True)
    # superseded at HEAD already, with no evidence recorded anywhere
    (vault / OLD).write_text(
        _note(currency="superseded", extra="superseded_by: [new-approach]\n"), "utf-8"
    )
    (vault / NEW).write_text(_note(extra="supersedes: [old-approach]\n"), "utf-8")
    commit_vault(vault)
    (vault / OLD).write_text(
        _note(
            currency="superseded",
            extra="superseded_by: [new-approach]\n",
            body="A typo fixed.",
        ),
        encoding="utf-8",
    )

    summary, model_calls = _stage(vault, monkeypatch)

    assert model_calls == [OLD]
    assert summary.verdicts[0].status == "verified"
    assert not [
        v
        for v in summary.verdicts[0].violations
        if v["rule_id"] == "IX-currency-evidence"
    ]
