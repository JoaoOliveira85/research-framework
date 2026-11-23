"""An update is judged by what it changed (spec 087, defect 4): a flaw the
committed note already had does not reject the update, and is recorded."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from research_framework.pipeline import verifier
from research_framework.pipeline.verifier import (
    VerifierVerdict,
    _verdict_from_data,
    split_pre_existing,
    violation_key,
)
from tests.pipeline.test_verifier import _credibility_spec

REL = "data_vault/cap-theorem.md"
SIBLING = "data_vault/cache-aside-pattern.md"
GOOD = "https://good.example/a"
GOOD_ENTRY = f"{{url: {GOOD}, credibility: commentary}}"
BOGUS = "https://old.example/b"


def _note(*, body: str, sources: str = f"[{GOOD_ENTRY}]") -> str:
    return (
        "---\ntitle: CAP Theorem\ntype: concept\n"
        f"source_urls: {sources}\nas_of: 2020-01-01\ncurrency: current\n---\n{body}\n"
    )


OLD_LINK_BODY = "The [[CAP]] Theorem is about distributed systems."
BOGUS_SOURCE = f"[{{url: {BOGUS}, credibility: bogus}}]"  # IX-credibility-malformed


def _vault(tmp_path: Path, committed: str, revised: str) -> Path:
    vault = tmp_path / "vault"
    (vault / "data_vault").mkdir(parents=True)
    (vault / "data_vault" / "cache-aside-pattern.md").write_text(
        "---\ntitle: Cache-Aside Pattern\ntype: concept\n---\nBody.\n"
    )
    (vault / REL).write_text(committed, encoding="utf-8")
    _credibility_spec(vault)
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "base"]):
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@e.invalid", *args],
            cwd=vault,
            check=True,
            capture_output=True,
        )
    (vault / REL).write_text(revised, encoding="utf-8")
    cycles = vault / "_pipeline" / "cycles"
    cycles.mkdir(parents=True)
    row = {
        "note": "cap-theorem",
        "path": REL,
        "outcome": "revised",
        "status": "passed",
        "reason": "",
        "sources_consulted": [],
        "evidence_url": None,
        "superseded_by": None,
        "change": "",
        "row": {"note": "cap-theorem", "outcome": "revised"},
    }
    (cycles / "cycle-001-update-outcomes.json").write_text(
        json.dumps({"cycle": 1, "results": [row]})
    )
    (cycles / "cycle-001-research.json").write_text(
        json.dumps({"notes_created": [], "notes_updated": [REL]})
    )
    return vault


def _run(
    vault: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    report: dict[str, Any] | None = None,
    model: VerifierVerdict | None = None,
) -> tuple[verifier.VerifierSummary, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []

    def fake_model(**kwargs: Any) -> VerifierVerdict:
        calls.append(kwargs)
        return model or VerifierVerdict(note_path=kwargs["note_rel"], status="verified")

    monkeypatch.setattr(verifier, "_call_verifier", fake_model)
    summary = verifier.run_verifier_stage(
        vault,
        1,
        report or {"notes_created": [], "notes_updated": [REL]},
        settings={"stages": {"verifier": {"enabled": True}}},
    )
    return summary, calls


def _sidecar_row(vault: Path) -> dict[str, Any]:
    doc = json.loads(
        (vault / "_pipeline/cycles/cycle-001-update-outcomes.json").read_text()
    )
    return doc["results"][0]


def test_an_old_acronym_self_link_does_not_reject_a_good_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(
        tmp_path,
        _note(body=OLD_LINK_BODY),
        _note(body=OLD_LINK_BODY + " Consistency, availability, partition tolerance."),
    )

    summary, calls = _run(vault, monkeypatch)

    (verdict,) = summary.verdicts
    assert verdict.status == "verified"
    assert not [v for v in verdict.violations if v.get("severity", "fail") != "warn"]
    assert [p["rule"] for p in verdict.pre_existing] == ["IX-wikilink-title-corruption"]
    # the model is told it is an update, and shown the committed text's diff
    assert calls and "The [[CAP]] Theorem" in calls[0]["committed_text"]
    # nothing is lost: the sidecar keeps it, and the report row carries it too
    assert _sidecar_row(vault)["pre_existing"][0]["rule"] == (
        "IX-wikilink-title-corruption"
    )
    report = json.loads(
        (vault / "_pipeline/cycles/cycle-001-research.json").read_text()
    )
    assert report["update_outcome_results"][0]["pre_existing"]
    # and the entry is not reopened: the update stood
    assert _sidecar_row(vault)["status"] == "passed"


def test_an_old_failing_citation_does_not_reject_but_a_second_one_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    committed = _note(body="Body text.", sources=BOGUS_SOURCE)
    # a good update that leaves the old flaw alone
    ok = _vault(
        tmp_path / "ok",
        committed,
        _note(body="Body text, revised.", sources=BOGUS_SOURCE),
    )
    summary, _ = _run(ok, monkeypatch)
    assert summary.verdicts[0].status == "verified"
    assert [p["rule"] for p in summary.verdicts[0].pre_existing] == [
        "IX-credibility-malformed"
    ]

    # the SAME rule about the SAME subject, once more than before: new
    twice = _vault(
        tmp_path / "twice",
        committed,
        _note(body="Revised.", sources=f"[{BOGUS_SOURCE[1:-1]}, {BOGUS_SOURCE[1:-1]}]"),
    )
    summary, calls = _run(twice, monkeypatch)
    assert summary.verdicts[0].status == "rejected"
    assert len(summary.verdicts[0].violations) == 1  # only the extra occurrence
    assert len(summary.verdicts[0].pre_existing) == 1

    # the same rule about a DIFFERENT subject: new
    other = _vault(
        tmp_path / "other",
        committed,
        _note(
            body="Revised.",
            sources=f"[{BOGUS_SOURCE[1:-1]}, {{url: https://new.example/c, credibility: bogus}}]",
        ),
    )
    summary, _ = _run(other, monkeypatch)
    assert summary.verdicts[0].status == "rejected"
    assert (
        violation_key(summary.verdicts[0].violations[0])[1] == "https://new.example/c"
    )


def test_a_different_violation_introduced_by_the_update_rejects_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(
        tmp_path,
        _note(body=OLD_LINK_BODY),
        # keeps the old self-link AND adds a malformed citation URL
        _note(
            body=OLD_LINK_BODY,
            sources=f"[{GOOD_ENTRY}, {{url: not-a-url}}]",
        ),
    )

    summary, _ = _run(vault, monkeypatch)

    (verdict,) = summary.verdicts
    assert verdict.status == "rejected"
    assert {v["rule_id"] for v in verdict.violations} == {"IX-citation-malformed"}
    assert [p["rule"] for p in verdict.pre_existing] == ["IX-wikilink-title-corruption"]
    assert _sidecar_row(vault)["status"] == "failed"  # reopened, as before


def test_an_old_missing_credibility_level_is_recorded_not_stamped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = f"[{GOOD_ENTRY}, https://old.example/nocred]"
    vault = _vault(
        tmp_path,
        _note(body="Body.", sources=source),
        _note(body="Body, revised.", sources=source),
    )

    summary, _ = _run(vault, monkeypatch)

    (verdict,) = summary.verdicts
    assert verdict.status == "verified"
    assert any(p["rule"] == "IX-credibility-unresolved" for p in verdict.pre_existing)
    assert not [
        v for v in verdict.violations if v["rule_id"] == "IX-credibility-unresolved"
    ]


def test_the_model_can_name_older_defects_and_may_leave_the_list_out() -> None:
    with_list = _verdict_from_data(
        "n.md",
        {
            "verdict": "accept",
            "violations": [],
            "pre_existing": [
                {"rule_id": "IX-x", "location": "l", "message": "old"},
                "a bare string",
                7,
            ],
        },
    )
    assert with_list.status == "verified"
    assert [p.get("message") for p in with_list.pre_existing] == [
        "old",
        "a bare string",
        "7",
    ]

    without = _verdict_from_data(
        "n.md", {"verdict": "reject", "violations": [{"message": "m"}]}
    )
    assert without.status == "rejected" and without.pre_existing == []

    malformed = _verdict_from_data(
        "n.md", {"verdict": "accept", "pre_existing": "not a list"}
    )
    assert malformed.status == "verified" and malformed.pre_existing == []


def test_the_key_is_the_rule_and_its_subject_and_counts_occurrences() -> None:
    a = {"rule_id": "R", "subject": "https://X.example/", "location": "one"}
    same = {"rule_id": "R", "subject": "https://x.example/", "location": "two"}
    other_subject = {"rule_id": "R", "subject": "https://y.example/"}
    other_rule = {"rule_id": "S", "subject": "https://x.example/"}
    no_subject = {"rule_id": "T", "message": "Cited  vault note 'XML' is missing"}

    assert violation_key(a) == violation_key(same)
    assert violation_key(no_subject)[1] == "cited vault note 'xml' is missing"
    new, old = split_pre_existing([same, same, other_subject, other_rule], [a])
    assert old == [same] and new == [same, other_subject, other_rule]


def test_a_new_topic_note_is_judged_exactly_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    (vault / "data_vault").mkdir(parents=True)
    (vault / SIBLING).write_text(
        "---\ntitle: Cache-Aside Pattern\ntype: concept\n---\nBody.\n"
    )
    (vault / REL).write_text(_note(body=OLD_LINK_BODY), encoding="utf-8")
    report = {"notes_created": [REL], "notes_updated": []}

    summary, calls = _run(vault, monkeypatch, report=report)

    (verdict,) = summary.verdicts
    assert verdict.status == "rejected"  # the flaw is NEW in a new note
    assert verdict.pre_existing == []
    # and the model call for a new note carries no committed text
    clean = tmp_path / "clean"
    (clean / "data_vault").mkdir(parents=True)
    (clean / REL).write_text(_note(body="No links here."), encoding="utf-8")
    _, clean_calls = _run(clean, monkeypatch, report=report)
    assert clean_calls[0]["committed_text"] is None


def test_the_update_prompt_asks_for_the_change_and_a_pre_existing_list() -> None:
    committed = _note(body="Old body.")
    revised = _note(body="Old body. A new sentence.")

    update = verifier._build_verifier_prompt(
        revised,
        note_type="concept",
        source_policy="soft",
        code_url_patterns=[],
        committed_text=committed,
    )
    plain = verifier._build_verifier_prompt(
        revised, note_type="concept", source_policy="soft", code_url_patterns=[]
    )

    assert "## This note is an UPDATE to an existing note" in update
    assert "+A new sentence" not in update  # the diff is of whole lines
    assert "+Old body. A new sentence." in update and "-Old body." in update
    assert '"pre_existing"' in update and "Reject only for what the update" in update
    assert "```diff" not in plain and "## This note is an UPDATE" not in plain


def test_a_confirmed_note_is_never_run_through_whole_note_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``confirmed`` changes nothing, so it is not in ``notes_updated`` (which is
    derived from the passing non-confirmed outcomes) and the verifier never sees
    the note: an old flaw cannot reject it."""
    from research_framework.pipeline import update_outcomes

    vault = _vault(tmp_path, _note(body=OLD_LINK_BODY), _note(body=OLD_LINK_BODY))
    row = _sidecar_row(vault)
    row["outcome"] = "confirmed"
    results_path = vault / "_pipeline/cycles/cycle-001-update-outcomes.json"
    results_path.write_text(json.dumps({"cycle": 1, "results": [row]}))
    report_path = vault / "_pipeline/cycles/cycle-001-research.json"
    update_outcomes._patch_report(
        report_path, {"notes_created": [], "notes_updated": [REL]}, [row]
    )
    report = json.loads(report_path.read_text())
    assert report["notes_updated"] == []  # derived: a confirmed note is no content

    summary, calls = _run(vault, monkeypatch, report=report)

    assert summary.verdicts == [] and calls == []
    assert _sidecar_row(vault)["status"] == "passed"
