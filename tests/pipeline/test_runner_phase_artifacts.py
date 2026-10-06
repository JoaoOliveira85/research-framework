"""A phase is done when it produced something, not when it exited 0.

Issue #222.  The scout, research and report phases were marked ``done`` purely
on the agent's exit code.  The runner never checked that ``scout-report.json``
or ``research-report.json`` existed, that they parsed, or that a single note
had been written.  On the 2026-09-01 fleet run reference-vault's research phase ran
for 34 seconds, wrote nothing, and is recorded ``done``.

The cycle path has refused to do this since spec 019: it validates through
``validate_cycle`` and warns when declared ``data_sources`` were not consulted.
The pipeline path had no equivalent check at all.

The stand-in agent is a plain Python script: what is under test is the
runner's acceptance criteria, so the agent's only job here is to exit 0 while
writing (or not writing) a given artifact.  No LLM is reached.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from research_framework.pipeline.runner import (
    DONE,
    FAILED,
    STATE_FILE,
    WAITING,
    _blank_state,
    _save_state,
    run_finish,
    run_resume,
    run_scout,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EXIT_ZERO_WRITE_NOTHING = "import sys; sys.exit(0)\n"


def _vault(tmp_path: Path, *, agent: str = _EXIT_ZERO_WRITE_NOTHING) -> Path:
    """A vault with a stand-in agent and every stage's prompt source present."""
    script = tmp_path / "scripts" / "agent_call.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(agent, encoding="utf-8")

    prompts = tmp_path / "_pipeline" / "prompts"
    prompts.mkdir(parents=True, exist_ok=True)
    (prompts / "scout-prompt.md").write_text(
        "Scout cycle {CYCLE_NUM} → {SCOUT_REPORT}\n", encoding="utf-8"
    )
    (prompts / "dfs-prompt.md").write_text(
        "Research cycle {CYCLE_NUM}: {SCOUT_REPORT} → {RESEARCH_REPORT}\n",
        encoding="utf-8",
    )
    agent_def = tmp_path / ".claude" / "commands" / "report.md"
    agent_def.parent.mkdir(parents=True, exist_ok=True)
    agent_def.write_text("# Weekly Report Agent\n", encoding="utf-8")
    return tmp_path


def _phase(vault: Path, name: str) -> dict:
    state = json.loads((vault / STATE_FILE).read_text(encoding="utf-8"))
    return state["phases"][name]


def _write_scout_report(vault: Path, **overrides: object) -> Path:
    doc: dict = {
        "schema_version": "2.0",
        "phase": "scout",
        "topics_found": {"new": [{"title": "A topic"}], "existing": [], "total": 1},
        "sources_consulted": ["Vendor changelogs"],
    }
    doc.update(overrides)
    path = vault / "_pipeline" / "scout-report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return path


def _write_research_report(vault: Path, **overrides: object) -> Path:
    doc: dict = {
        "schema_version": "2.0",
        "phase": "research",
        "notes_created": ["a-topic.md"],
        "notes_updated": [],
    }
    doc.update(overrides)
    path = vault / "_pipeline" / "research-report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return path


def _write_spec_parse(vault: Path, *names: str) -> None:
    path = vault / "_pipeline" / "spec-parse.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "data_sources": [
                    {"name": n, "type": "external", "access_method": "web fetch"}
                    for n in names
                ]
            }
        ),
        encoding="utf-8",
    )


def _awaiting_triage(vault: Path) -> None:
    state = _blank_state("2026-09-01-0300", "2026-09-01T03:00:00Z")
    for phase in ("collect", "extract", "scout"):
        state["phases"][phase]["status"] = DONE
    state["phases"]["triage"]["status"] = WAITING
    _save_state(vault, state)


# ---------------------------------------------------------------------------
# scout
# ---------------------------------------------------------------------------


class TestScoutIsDoneWhenItWroteAQueue:
    def test_exit_zero_with_no_report_is_not_done(self, tmp_path: Path) -> None:
        vault = _vault(tmp_path)

        rc = run_scout(vault, quiet=True)

        assert rc == 1
        rec = _phase(vault, "scout")
        assert rec["status"] == FAILED
        assert any("scout-report.json" in e for e in rec["errors"]), rec["errors"]

    def test_an_unparseable_report_is_not_done(self, tmp_path: Path) -> None:
        vault = _vault(tmp_path)
        report = vault / "_pipeline" / "scout-report.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("{ not json", encoding="utf-8")

        rc = run_scout(vault, quiet=True)

        assert rc == 1
        assert _phase(vault, "scout")["status"] == FAILED

    def test_a_report_with_no_topic_queue_is_not_done(self, tmp_path: Path) -> None:
        """``topics_found.new`` is the queue ``resume`` researches. A report
        that does not carry one leaves the next phase with nothing to read."""
        vault = _vault(tmp_path)
        _write_scout_report(vault, topics_found={"existing": []})

        rc = run_scout(vault, quiet=True)

        assert rc == 1
        assert _phase(vault, "scout")["status"] == FAILED

    def test_a_valid_report_is_done_and_the_queue_size_is_recorded(
        self, tmp_path: Path
    ) -> None:
        vault = _vault(tmp_path)
        _write_scout_report(vault)

        rc = run_scout(vault, quiet=True)

        assert rc == 0
        rec = _phase(vault, "scout")
        assert rec["status"] == DONE
        assert rec["summary"]["topics_found_new"] == 1

    def test_an_empty_queue_is_reported_but_not_a_failure(self, tmp_path: Path) -> None:
        """A scout that honestly found nothing is a valid outcome; a scout that
        wrote nothing is not. The runner has to tell them apart."""
        vault = _vault(tmp_path)
        _write_scout_report(vault, topics_found={"new": [], "existing": [], "total": 0})

        rc = run_scout(vault, quiet=True)

        assert rc == 0
        rec = _phase(vault, "scout")
        assert rec["status"] == DONE
        assert rec["summary"]["topics_found_new"] == 0


class TestDeclaredSourcesThatWereNotConsulted:
    def test_an_unconsulted_source_is_named_at_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """reference-vault declared web, GitHub and official docs; all three came
        back ``searched: false`` and nothing said so."""
        vault = _vault(tmp_path)
        _write_spec_parse(vault, "Vendor changelogs", "GitHub repos")
        _write_scout_report(vault, sources_consulted=["Vendor changelogs"])

        with caplog.at_level(logging.WARNING):
            rc = run_scout(vault, quiet=True)

        assert rc == 0, "an unconsulted source is a warning, not a failure"
        assert "GitHub repos" in caplog.text
        assert _phase(vault, "scout")["summary"]["sources_not_consulted"] == [
            "GitHub repos"
        ]

    def test_the_dict_form_of_sources_consulted_honours_searched_false(
        self, tmp_path: Path
    ) -> None:
        """v2 reports may spell it as a map with a ``searched`` flag; a source
        listed but not searched is not a source consulted."""
        vault = _vault(tmp_path)
        _write_spec_parse(vault, "Vendor changelogs", "GitHub repos")
        _write_scout_report(
            vault,
            sources_consulted={
                "Vendor changelogs": {"searched": True},
                "GitHub repos": {"searched": False},
            },
        )

        run_scout(vault, quiet=True)

        assert _phase(vault, "scout")["summary"]["sources_not_consulted"] == [
            "GitHub repos"
        ]

    def test_nothing_is_warned_when_every_source_was_consulted(
        self, tmp_path: Path
    ) -> None:
        vault = _vault(tmp_path)
        _write_spec_parse(vault, "Vendor changelogs")
        _write_scout_report(vault, sources_consulted=["Vendor changelogs"])

        run_scout(vault, quiet=True)

        assert _phase(vault, "scout")["summary"]["sources_not_consulted"] == []


# ---------------------------------------------------------------------------
# research
# ---------------------------------------------------------------------------


class TestResearchIsDoneWhenItWroteNotes:
    def test_exit_zero_with_no_report_is_not_done(self, tmp_path: Path) -> None:
        vault = _vault(tmp_path)
        _awaiting_triage(vault)

        rc = run_resume(vault, quiet=True)

        assert rc == 1
        rec = _phase(vault, "research")
        assert rec["status"] == FAILED
        assert any("research-report.json" in e for e in rec["errors"]), rec["errors"]

    def test_zero_notes_against_a_non_empty_queue_is_not_done(
        self, tmp_path: Path
    ) -> None:
        """The 34-second no-op: the queue had topics, the agent exited 0, and
        nothing was written."""
        vault = _vault(tmp_path)
        _write_scout_report(vault)
        _awaiting_triage(vault)
        _write_research_report(vault, notes_created=[])

        rc = run_resume(vault, quiet=True)

        assert rc == 1
        rec = _phase(vault, "research")
        assert rec["status"] == FAILED
        assert any("no notes" in e for e in rec["errors"]), rec["errors"]

    def test_zero_notes_against_an_empty_queue_is_done_with_a_reason(
        self, tmp_path: Path
    ) -> None:
        vault = _vault(tmp_path)
        _write_scout_report(vault, topics_found={"new": [], "existing": [], "total": 0})
        _awaiting_triage(vault)
        _write_research_report(vault, notes_created=[])

        rc = run_resume(vault, quiet=True)

        assert rc == 0
        rec = _phase(vault, "research")
        assert rec["status"] == DONE
        assert rec["summary"]["empty_queue_reason"]

    def test_notes_written_is_done_and_counted(self, tmp_path: Path) -> None:
        vault = _vault(tmp_path)
        _write_scout_report(vault)
        _awaiting_triage(vault)
        _write_research_report(vault, notes_created=["a.md", "b.md"])

        rc = run_resume(vault, quiet=True)

        assert rc == 0
        rec = _phase(vault, "research")
        assert rec["status"] == DONE
        assert rec["summary"]["notes_created"] == 2
        assert rec["summary"]["queue_size"] == 1


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


class TestReportIsDoneWhenItWroteAnExport:
    def test_exit_zero_with_no_export_is_not_done(self, tmp_path: Path) -> None:
        vault = _vault(tmp_path)
        _write_research_report(vault)

        rc = run_finish(vault, quiet=True)

        assert rc == 1
        rec = _phase(vault, "report")
        assert rec["status"] == FAILED
        assert any("exports" in e for e in rec["errors"]), rec["errors"]

    def test_an_export_on_disk_is_done_and_named(self, tmp_path: Path) -> None:
        vault = _vault(tmp_path)
        export = vault / "_pipeline" / "exports" / "weekly-2026-09-01.md"
        export.parent.mkdir(parents=True, exist_ok=True)
        export.write_text("# Weekly briefing\n", encoding="utf-8")

        run_finish(vault, quiet=True)

        rec = _phase(vault, "report")
        assert rec["status"] == DONE
        assert rec["summary"]["exports"] == 1


# ---------------------------------------------------------------------------
# no agent at all
# ---------------------------------------------------------------------------


class TestAMissingAgentScriptIsNotAnExitZero:
    """No ``agent_call.py`` to dispatch to means no agent ran — that is not a
    success. It used to come back as exit 0 ("treat as success"), so the phase
    was then judged on whatever artifact was already on disk: a previous run's
    ``scout-report.json`` made a scout that never ran ``done``."""

    def test_a_previous_runs_report_does_not_make_an_undispatched_scout_done(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from research_framework.pipeline import runner

        vault = _vault(tmp_path)
        _write_scout_report(vault)  # last week's queue, still on disk
        monkeypatch.setattr(runner, "_agent_call_script", lambda _vault: None)

        with caplog.at_level(logging.ERROR):
            rc = run_scout(vault, quiet=True)

        assert rc == 1
        assert _phase(vault, "scout")["status"] == FAILED
        assert "agent_call.py" in caplog.text
