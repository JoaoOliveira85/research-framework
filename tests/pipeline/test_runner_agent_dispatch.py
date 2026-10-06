"""Tier-3 integration: the pipeline runner's real dispatch to a real agent.

Everything here runs the production
``research_framework.pipeline.runner`` code path unmodified — real prompt
rendering, real ``_call_agent``, a real ``subprocess.run`` — against a vault
built by ``tests/_helpers/vault_factory.build_minimal_vault`` with the
fake ``agent_call.py`` shim installed in place of the real one. The only
test-only customization is that fake at the subprocess boundary; no LLM is
reached and no money is spent.

This is the regression gate for the shipped bug where
``research-framework pipeline <vault> resume`` and ``... finish`` both died
before dispatch with

    ERROR: no rendered prompt available for stage 'research'; this pipeline
    runner has no template wired up for it yet, so there is nothing to send
    the agent. Skipping.

``_drive_research`` / ``_drive_report`` passed ``prompt_file=None``
unconditionally, so the weekly pipeline (collect → extract → scout → triage
→ research → verify → report) was not runnable end to end headlessly. The
fake shim reads its ``--prompt-file`` and exits 2 when it cannot, so a green
run here is positive proof that a *rendered file* reached the agent.

Deliberately unmarked (no ``e2e``): it drives a single stage, costs well
under a second, and must run in the ``pytest -m "not e2e"`` CI loop that
gates every PR.
"""

from __future__ import annotations

import json
from pathlib import Path

from research_framework.pipeline.runner import (
    DONE,
    PENDING,
    WAITING,
    _blank_state,
    _save_state,
    run_finish,
    run_resume,
)
from tests._helpers.vault_factory import build_minimal_vault

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _vault_awaiting_triage(tmp_path: Path) -> Path:
    """A generated vault parked exactly where ``run_full`` leaves the operator."""
    vault = build_minimal_vault(tmp_path)
    state = _blank_state("2026-08-31-1200", "2026-08-31T12:00:00Z")
    for phase in ("collect", "extract", "scout"):
        state["phases"][phase]["status"] = DONE
    state["phases"]["triage"]["status"] = WAITING
    _save_state(vault, state)
    return vault


def _phase(vault: Path, name: str) -> dict:
    state = json.loads(
        (vault / "_pipeline" / "pipeline-state.json").read_text(encoding="utf-8")
    )
    return state["phases"][name]


# ---------------------------------------------------------------------------
# resume → research
# ---------------------------------------------------------------------------


class TestResumeReachesTheResearchAgent:
    def test_resume_dispatches_with_a_rendered_prompt_file(
        self, tmp_path: Path
    ) -> None:
        vault = _vault_awaiting_triage(tmp_path)

        rc = run_resume(vault, quiet=True)

        assert rc == 0, _phase(vault, "research")["errors"]
        assert _phase(vault, "research")["status"] == DONE
        assert _phase(vault, "triage")["status"] == DONE

    def test_the_research_agent_writes_the_report_it_was_told_to_write(
        self, tmp_path: Path
    ) -> None:
        """Issue #261: a DONE phase used to prove only that a prompt file
        existed — the fake exited 0 for ``research`` without writing anything.
        The artifact is the proof."""
        vault = _vault_awaiting_triage(tmp_path)

        run_resume(vault, quiet=True)

        report = vault / "_pipeline" / "research-report.json"
        assert report.is_file(), _phase(vault, "research")["errors"]
        doc = json.loads(report.read_text(encoding="utf-8"))
        assert doc["phase"] == "research"
        assert doc["schema_version"] == "2.0"

    def test_the_rendered_research_prompt_points_at_the_queue_artifact(
        self, tmp_path: Path
    ) -> None:
        """The queue is the scout report this pipeline actually writes, not a
        Topic Radar note (a cycle-orchestrator artifact a pipeline run never
        produces)."""
        vault = _vault_awaiting_triage(tmp_path)

        run_resume(vault, quiet=True)

        # Spec 080 FR-003: the rendered prompt lives under the run directory,
        # not at a flat `_pipeline/` path the next run overwrites.
        rendered = (
            vault
            / "_pipeline"
            / "runs"
            / "2026-08-31-1200"
            / "prompts"
            / "research.rendered.md"
        )
        assert rendered.is_file()
        text = rendered.read_text(encoding="utf-8")
        assert str(vault / "_pipeline" / "scout-report.json") in text
        assert str(vault / "_pipeline" / "research-report.json") in text
        assert "{SCOUT_REPORT}" not in text
        assert "{RESEARCH_REPORT}" not in text
        assert "{CYCLE_NUM}" not in text


# ---------------------------------------------------------------------------
# finish → verify + report
# ---------------------------------------------------------------------------


class TestFinishReachesTheReportAgent:
    def test_finish_runs_verify_then_dispatches_the_report_agent(
        self, tmp_path: Path
    ) -> None:
        vault = _vault_awaiting_triage(tmp_path)

        run_finish(vault, quiet=True)

        # Verify stays processor-driven and untouched by this fix — it still
        # writes its own summary shape. (The verdict itself is a property of
        # the fixture vault's notes, not of this wiring.) Issue #218 widened
        # that shape from {verdict, notes_checked} to everything that produced
        # the verdict; the two keys this test cares about are still there.
        assert {"verdict", "notes_checked"} <= set(_phase(vault, "verify")["summary"])
        # The report agent is now reached, and its phase no longer fails for
        # want of a prompt — whatever verify concluded.
        assert _phase(vault, "report")["status"] == DONE, _phase(vault, "report")[
            "errors"
        ]

    def test_the_report_agent_writes_the_weekly_export(self, tmp_path: Path) -> None:
        """Same proof for ``report`` (issue #261). The stage's own agent
        definition names ``_pipeline/exports/`` as its output; the fake writes
        a fixed-name export there so a no-op is distinguishable from a run."""
        vault = _vault_awaiting_triage(tmp_path)

        run_finish(vault, quiet=True)

        export = vault / "_pipeline" / "exports" / "weekly-report.md"
        assert export.is_file(), _phase(vault, "report")["errors"]
        assert "type: weekly-report" in export.read_text(encoding="utf-8")

    def test_finish_still_skips_the_research_phase(self, tmp_path: Path) -> None:
        """``run_finish`` runs verify + report only. Wiring a research prompt
        must not turn ``finish`` into a second research run."""
        vault = _vault_awaiting_triage(tmp_path)

        run_finish(vault, quiet=True)

        assert _phase(vault, "research")["status"] == PENDING
        assert not (vault / "_pipeline" / "research-prompt.rendered.md").exists()

    def test_the_rendered_report_prompt_carries_the_run_context(
        self, tmp_path: Path
    ) -> None:
        vault = _vault_awaiting_triage(tmp_path)

        run_finish(vault, quiet=True)

        rendered = (
            vault
            / "_pipeline"
            / "runs"
            / "2026-08-31-1200"
            / "prompts"
            / "report.rendered.md"
        )
        assert rendered.is_file()
        text = rendered.read_text(encoding="utf-8")
        # The vault's own report agent definition is the stage behaviour ...
        assert "Weekly Report Agent" in text
        # ... prefixed by the artifacts this single-shot run actually has.
        assert "## Pipeline run context" in text
        assert str(vault / "_pipeline" / "scout-report.json") in text
        assert str(vault / "_pipeline" / "pipeline-state.json") in text


class TestTheReportIsToldWhatTheRunDid:
    """Spec 080 US4 / FR-015…FR-017 (issue #224).

    On 2026-09-01 reference-vault's weekly report claimed **45 notes added for a
    run whose research phase created 0**, and printed "No context tree
    available" twice. The report agent was never told what the run did, so it
    reconstructed a narrative from the only thing it could see — the
    repository's git history — and that narrative was about a different week.

    The fix is an enforcement boundary, not a rewrite of the agent: the prose
    stays the agent's, the FACTS are handed to it. A report that then claims
    additions contradicts the input printed above it.
    """

    @staticmethod
    def _report_prompt(vault: Path) -> str:
        path = (
            vault
            / "_pipeline"
            / "runs"
            / "2026-08-31-1200"
            / "prompts"
            / "report.rendered.md"
        )
        assert path.is_file()
        return path.read_text(encoding="utf-8")

    def test_the_rendered_report_prompt_carries_the_runs_own_counts(
        self, tmp_path: Path
    ) -> None:
        vault = _vault_awaiting_triage(tmp_path)

        run_resume(vault, quiet=True)
        run_finish(vault, quiet=True)

        text = self._report_prompt(vault)
        assert "## What this run did" in text
        assert "Phase outcomes:" in text
        assert "note(s) and updated" in text
        assert "Verify verdict:" in text

    def test_a_zero_note_run_is_named_as_such_in_the_report_context(
        self, tmp_path: Path
    ) -> None:
        """FR-016. Said in a sentence, before any instruction to summarise
        additions — the 45-notes report is what an unstated zero produces."""
        vault = _vault_awaiting_triage(tmp_path)
        run_resume(vault, quiet=True)
        # Rewrite the research summary to the shape the incident had: the
        # phase ran and produced nothing.
        state_path = vault / "_pipeline" / "pipeline-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["phases"]["research"]["summary"] = {
            "notes_created": 0,
            "notes_updated": 0,
        }
        state_path.write_text(json.dumps(state), encoding="utf-8")

        run_finish(vault, quiet=True)

        text = self._report_prompt(vault)
        assert "**This run created no notes.**" in text
        assert "Do not describe additions" in text

    def test_the_report_context_names_the_receipts_verify_report(
        self, tmp_path: Path
    ) -> None:
        """FR-017. `_pipeline/logs/verify-*.md` was in the agent definition's
        `reads:` for months and has never been written by anything."""
        vault = _vault_awaiting_triage(tmp_path)

        run_finish(vault, quiet=True)

        text = self._report_prompt(vault)
        assert "verify-report.json" in text
        assert "verify-*.md" not in text

    def test_the_context_is_absent_rather_than_invented_without_a_receipt(
        self, tmp_path: Path
    ) -> None:
        """A run whose receipt cannot be read gets the artifact block and no
        facts block — an empty section is a smaller lie than a fabricated one.
        """
        from research_framework.pipeline.runner import _run_context_block

        vault = _vault_awaiting_triage(tmp_path)

        text = _run_context_block(vault, "report", None)

        assert "## Pipeline run context" in text
        assert "## What this run did" not in text
