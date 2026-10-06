"""A failed pipeline phase must be legible from outside the state file.

Two defects, one symptom (issues #218 and #219).

**#218** — ``_drive_verify`` copied ``verdict`` and ``notes_checked`` into the
phase summary and threw ``VerifyResult.report`` away.  That report is the only
carrier of the per-note flag detail, and spec 015f § Path conventions has
promised since 2026 that verify output lives under ``_pipeline/logs/``.
Nothing ever wrote it.

**#219** — every ``_drive_*`` driver persisted its ``errors`` list into
``pipeline-state.json`` and then said nothing above ``INFO``.  A cron run
redirects stdout, so the operator's entire record of a failed weekly run was a
JSON file they had no reason to open.  These pin the ERROR record and, with
it, the absolute path of the state file that holds the rest.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from research_framework.collectors import CollectResult
from research_framework.pipeline.runner import (
    DONE,
    FAILED,
    STATE_FILE,
    _blank_state,
    _save_state,
    run_collect,
    run_extract,
    run_finish,
)
from research_framework.processors.extract import ExtractResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _phase(vault: Path, name: str) -> dict:
    state = json.loads((vault / STATE_FILE).read_text(encoding="utf-8"))
    return state["phases"][name]


def _broken_note(vault: Path, rel: str = "04 - Concepts/Broken.md") -> Path:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\ntitle: [unclosed\n---\n\nBody.\n", encoding="utf-8")
    return path


def _verify_only(vault: Path) -> None:
    """Blank state for a ``finish`` run.

    The bare tmp vault carries no ``.claude/commands/report.md``, so the report
    phase never reaches a subprocess: ``_render_stage_prompt`` returns ``None``
    and ``_call_agent`` refuses before dispatch.  Nothing here asserts on that
    phase — it is only the second half of ``run_finish``.
    """
    _save_state(vault, _blank_state("2026-09-01-0300", "2026-09-01T03:00:00Z"))


# ---------------------------------------------------------------------------
# #218 — the verify report reaches disk and the summary
# ---------------------------------------------------------------------------


class TestVerifyReportIsPersisted:
    def test_a_verify_run_writes_its_report_under_the_run_directory(
        self, tmp_path: Path
    ) -> None:
        """Spec 015f § Path conventions promised this file in 2026 and nothing
        wrote it until #218. Spec 080 FR-003 moved it from
        ``_pipeline/logs/verify-<ts>.json`` to ``<run_dir>/verify-report.json``,
        so an operator opening one directory finds it; the per-note flag detail
        it carries is why it exists and is unchanged."""
        _broken_note(tmp_path)
        _verify_only(tmp_path)

        run_finish(tmp_path, quiet=True)

        reports = sorted(
            (tmp_path / "_pipeline" / "runs").glob("*/verify-report*.json")
        )
        assert reports, "the verify report is the run's own record of the verdict"
        doc = json.loads(reports[0].read_text(encoding="utf-8"))
        assert doc["verdict"] == "FAIL"
        assert doc["results"], "the per-note flag detail is the point of the file"

    def test_the_summary_names_the_report_it_wrote(self, tmp_path: Path) -> None:
        _broken_note(tmp_path)
        _verify_only(tmp_path)

        run_finish(tmp_path, quiet=True)

        summary = _phase(tmp_path, "verify")["summary"]
        assert Path(summary["report_path"]).is_file()

    def test_the_summary_carries_what_produced_the_verdict(
        self, tmp_path: Path
    ) -> None:
        """``{verdict, notes_checked}`` cannot distinguish "one malformed note"
        from "9066 flags over 840 notes"."""
        _broken_note(tmp_path)
        _verify_only(tmp_path)

        run_finish(tmp_path, quiet=True)

        summary = _phase(tmp_path, "verify")["summary"]
        for key in (
            "verdict",
            "notes_checked",
            "structural_flags",
            "malformed_count",
            "auto_fixes_applied",
            "fail_threshold",
            "flags_by_check",
        ):
            assert key in summary, key

    def test_the_phase_errors_are_no_longer_empty_on_fail(self, tmp_path: Path) -> None:
        _broken_note(tmp_path)
        _verify_only(tmp_path)

        run_finish(tmp_path, quiet=True)

        rec = _phase(tmp_path, "verify")
        assert rec["status"] == FAILED
        assert rec["errors"], "the 7/7 live-vault shape was errors=[]"


# ---------------------------------------------------------------------------
# #219 — a failed phase says so at ERROR
# ---------------------------------------------------------------------------


class TestPhaseFailuresAreLoggedAtError:
    def test_a_failed_collect_logs_its_errors_at_error(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        result = CollectResult(fetched=0, skipped_existing=0, errors=("feed timeout",))
        with (
            patch("research_framework.collectors.rss.collect", return_value=result),
            caplog.at_level(logging.ERROR),
        ):
            rc = run_collect(tmp_path, quiet=True)

        assert rc == 1
        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert errors, "a non-TTY run emitted zero bytes for this failure"
        assert "feed timeout" in caplog.text

    def test_a_failed_phase_names_the_state_file_that_holds_the_record(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The FR6 backstop used to point at ``run-report.md``, which the
        pipeline runner never writes.  Name the file it does write."""
        result = CollectResult(fetched=0, skipped_existing=0, errors=("feed timeout",))
        with (
            patch("research_framework.collectors.rss.collect", return_value=result),
            caplog.at_level(logging.ERROR),
        ):
            run_collect(tmp_path, quiet=True)

        assert str(tmp_path / STATE_FILE) in caplog.text

    def test_a_failed_extract_logs_at_error_too(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """One helper, not seven bespoke patches — so every driver inherits it."""
        with (
            patch(
                "research_framework.processors.extract.extract",
                side_effect=RuntimeError("context tree write failed"),
            ),
            caplog.at_level(logging.ERROR),
        ):
            rc = run_extract(tmp_path, quiet=True)

        assert rc == 1
        assert "context tree write failed" in caplog.text
        assert str(tmp_path / STATE_FILE) in caplog.text

    def test_a_failed_verify_logs_at_error(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        _broken_note(tmp_path)
        _verify_only(tmp_path)

        with caplog.at_level(logging.ERROR):
            run_finish(tmp_path, quiet=True)

        records = [
            r
            for r in caplog.records
            if r.levelno >= logging.ERROR and "verify" in r.getMessage()
        ]
        assert records, "the 2026-09-01 incident: FAIL, 0s, empty errors, no log"

    def test_quiet_does_not_silence_a_failure(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """``--quiet`` suppresses narration.  It is not a licence to swallow
        the reason a run exited non-zero."""
        result = CollectResult(fetched=0, skipped_existing=0, errors=("feed timeout",))
        with (
            patch("research_framework.collectors.rss.collect", return_value=result),
            caplog.at_level(logging.ERROR),
        ):
            run_collect(tmp_path, quiet=True)

        assert "feed timeout" in caplog.text

    def test_a_successful_phase_says_nothing_at_error(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        ct = tmp_path / "_pipeline" / "extracted" / "context-tree.md"
        ct.parent.mkdir(parents=True, exist_ok=True)
        ct.write_text("# CT\n", encoding="utf-8")
        ok = ExtractResult(
            files_processed=4, files_skipped=0, context_tree_path=ct, errors=()
        )
        with (
            patch("research_framework.processors.extract.extract", return_value=ok),
            caplog.at_level(logging.ERROR),
        ):
            rc = run_extract(tmp_path, quiet=True)

        assert rc == 0
        assert _phase(tmp_path, "extract")["status"] == DONE
        assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []
