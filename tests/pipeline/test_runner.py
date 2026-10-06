"""Tests for research_framework.pipeline.runner (015g)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from research_framework.collectors import CollectResult
from research_framework.pipeline.runner import (
    DONE,
    FAILED,
    FRAMEWORK_VERSION,
    PENDING,
    STATE_FILE,
    WAITING,
    AgentCallOutcome,
    _atomic_write_json,
    _blank_state,
    _make_run_id,
    _render_stage_prompt,
    _save_state,
    run_collect,
    run_extract,
    run_finish,
    run_full,
    run_resume,
    run_scout,
    status,
)
from research_framework.processors.extract import ExtractResult
from research_framework.processors.verify import VerifyResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_stage_artifact(vault: Path, stage: str) -> None:
    """Write what ``stage``'s agent is told to write.

    Since issue #222 a phase is done only when its artifact is on disk, so a
    ``_call_agent`` mock that merely returns 0 no longer stands in for an
    agent — it stands in for the no-op the runner now refuses. These tests are
    about prompt rendering and dispatch arguments, so the stand-in does the one
    thing the runner checks afterwards.
    """
    pipeline = vault / "_pipeline"
    if stage == "scout":
        _atomic_write_json(
            pipeline / "scout-report.json",
            {"topics_found": {"new": [{"title": "A topic"}], "existing": []}},
        )
    elif stage == "research":
        _atomic_write_json(
            pipeline / "research-report.json", {"notes_created": ["a-topic.md"]}
        )
    elif stage == "report":
        export = pipeline / "exports" / "weekly-report.md"
        export.parent.mkdir(parents=True, exist_ok=True)
        export.write_text("# Weekly briefing\n", encoding="utf-8")


def _agent_writes_its_artifact(
    vault: Path,
    *,
    stage: str,
    quiet: bool,
    prompt_file: Path | None,
    run_dir: Path | None = None,
) -> AgentCallOutcome:
    """A stand-in dispatch, mirroring ``_call_agent``'s real signature.

    ``run_dir`` is accepted because the real one takes it (spec 080 FR-010:
    the sidecar goes under the run directory). A double that could not be
    called the same way would pass while the caller changed underneath it.
    """
    _write_stage_artifact(vault, stage)
    return AgentCallOutcome(returncode=0)


def _assert_dispatched(mock_agent, vault: Path, stage: str) -> None:
    """One dispatch, for *stage*, into this vault's current run directory.

    These callers do not seed a state file, so ``_load_state`` mints a fresh
    minute-granular ``run_id`` from the clock and the exact directory name is
    not knowable from the test. What matters is the shape: the dispatch went
    to the run directory, not to a flat ``_pipeline/`` path.
    """
    mock_agent.assert_called_once()
    _, kwargs = mock_agent.call_args
    assert kwargs["stage"] == stage
    assert kwargs["prompt_file"] is None
    run_dir = kwargs["run_dir"]
    assert run_dir is not None
    assert run_dir.parent == vault / "_pipeline" / "runs"


def _run_prompt(vault: Path, stage: str, run_id: str = "2026-05-14-1500") -> Path:
    """Where spec 080 puts a rendered prompt: under the run directory.

    Was ``_pipeline/<stage>-prompt.rendered.md``, which the next run
    overwrote. The behaviour these tests assert — the placeholders are
    substituted and the file is handed to the agent via ``--prompt-file`` —
    is unchanged; only the path moved (spec 080 § Relationship to 075).
    """
    return vault / "_pipeline" / "runs" / run_id / "prompts" / f"{stage}.rendered.md"


def _make_state(tmp_path: Path, *, phases: dict | None = None) -> dict:
    """Write a pipeline-state.json to tmp_path and return the state dict."""
    state = _blank_state("2026-05-14-1500", "2026-05-14T15:00:00Z")
    if phases:
        for phase_name, updates in phases.items():
            state["phases"][phase_name].update(updates)
    _save_state(tmp_path, state)
    return state


# ---------------------------------------------------------------------------
# status()
# ---------------------------------------------------------------------------


class TestStatus:
    def test_returns_pending_dict_when_no_state_file(self, tmp_path: Path) -> None:
        result = status(tmp_path)
        assert result["run_id"] is None
        assert result["framework_version"] == FRAMEWORK_VERSION
        phases = result["phases"]
        for phase in (
            "collect",
            "extract",
            "scout",
            "triage",
            "research",
            "verify",
            "report",
        ):
            assert phases[phase]["status"] == PENDING

    def test_reads_existing_state_file(self, tmp_path: Path) -> None:
        _make_state(
            tmp_path,
            phases={
                "collect": {"status": DONE, "summary": {"items_new": 5}},
                "triage": {"status": WAITING},
            },
        )
        result = status(tmp_path)
        assert result["phases"]["collect"]["status"] == DONE
        assert result["phases"]["collect"]["summary"] == {"items_new": 5}
        assert result["phases"]["triage"]["status"] == WAITING
        assert result["phases"]["research"]["status"] == PENDING

    def test_returns_error_dict_on_invalid_json(self, tmp_path: Path) -> None:
        state_path = tmp_path / "_pipeline" / "pipeline-state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text("not json", encoding="utf-8")
        result = status(tmp_path)
        assert "error" in result

    @pytest.mark.parametrize("body", ["[]", "null", "42", '"done"'])
    def test_returns_error_dict_on_json_that_is_not_an_object(
        self, tmp_path: Path, body: str
    ) -> None:
        """Valid JSON, wrong shape: the same answer as invalid JSON, not a crash."""
        state_path = tmp_path / "_pipeline" / "pipeline-state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(body, encoding="utf-8")
        result = status(tmp_path)
        assert "error" in result

    def test_reports_errors_persisted_on_a_failed_phase(self, tmp_path: Path) -> None:
        """Issue #245: the persisted `errors[]` must round-trip through
        `status()` — it always did, but the TTY renderer downstream dropped
        it, which made this the read side of the bug."""
        _make_state(
            tmp_path,
            phases={
                "verify": {
                    "status": FAILED,
                    "errors": ["verify processor error: boom"],
                }
            },
        )
        result = status(tmp_path)
        assert result["phases"]["verify"]["errors"] == ["verify processor error: boom"]

    def test_computes_phase_duration_from_started_and_finished(
        self, tmp_path: Path
    ) -> None:
        _make_state(
            tmp_path,
            phases={
                "collect": {
                    "status": DONE,
                    "started_at": "2026-09-01T10:00:00Z",
                    "finished_at": "2026-09-01T10:01:05Z",
                }
            },
        )
        result = status(tmp_path)
        collect = result["phases"]["collect"]
        assert collect["started_at"] == "2026-09-01T10:00:00Z"
        assert collect["finished_at"] == "2026-09-01T10:01:05Z"
        assert collect["duration_s"] == 65.0

    def test_duration_is_none_when_phase_never_finished(self, tmp_path: Path) -> None:
        """A phase still `in_progress` (or killed before writing
        `finished_at`) has no duration — that must read as unknown, not 0
        or a stale number."""
        _make_state(
            tmp_path,
            phases={
                "scout": {
                    "status": "in_progress",
                    "started_at": "2026-09-01T10:00:00Z",
                }
            },
        )
        result = status(tmp_path)
        assert result["phases"]["scout"]["duration_s"] is None

    def test_duration_is_none_when_state_file_absent(self, tmp_path: Path) -> None:
        result = status(tmp_path)
        for phase in result["phases"].values():
            assert phase["duration_s"] is None
            assert phase["errors"] == []


# ---------------------------------------------------------------------------
# Atomicity
# ---------------------------------------------------------------------------


class TestAtomicWrite:
    def test_writes_valid_json(self, tmp_path: Path) -> None:
        dest = tmp_path / "_pipeline" / "pipeline-state.json"
        data = {"hello": "world"}
        _atomic_write_json(dest, data)
        assert dest.exists()
        assert json.loads(dest.read_text()) == data

    def test_state_is_valid_after_phase_transition(self, tmp_path: Path) -> None:
        """State file must be valid JSON after every save."""
        state = _blank_state(_make_run_id(), "2026-05-14T00:00:00Z")
        _save_state(tmp_path, state)

        state_path = tmp_path / "_pipeline" / "pipeline-state.json"
        parsed = json.loads(state_path.read_text())
        assert parsed["framework_version"] == FRAMEWORK_VERSION
        assert "phases" in parsed

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        dest = tmp_path / "a" / "b" / "c.json"
        _atomic_write_json(dest, {"x": 1})
        assert dest.exists()


# ---------------------------------------------------------------------------
# run_full() — end-to-end with mocks
# ---------------------------------------------------------------------------


class TestRunFull:
    @pytest.fixture
    def vault(self, tmp_path: Path) -> Path:
        """Minimal tmp vault with _pipeline dir."""
        (tmp_path / "_pipeline" / "raw" / "rss").mkdir(parents=True, exist_ok=True)
        return tmp_path

    def _mock_collect_result(self) -> CollectResult:
        return CollectResult(fetched=5, skipped_existing=2, errors=())

    def _mock_extract_result(self, vault: Path) -> ExtractResult:
        ct = vault / "_pipeline" / "extracted" / "context-tree.md"
        ct.parent.mkdir(parents=True, exist_ok=True)
        ct.write_text("# Context Tree\n", encoding="utf-8")
        return ExtractResult(
            files_processed=5,
            files_skipped=0,
            context_tree_path=ct,
            errors=(),
        )

    def test_full_pipeline_writes_correct_state(self, vault: Path) -> None:
        with (
            patch(
                "research_framework.pipeline.runner._drive_collect",
            ) as mock_collect,
            patch(
                "research_framework.pipeline.runner._drive_extract",
            ) as mock_extract,
            patch(
                "research_framework.pipeline.runner._drive_scout",
            ) as mock_scout,
        ):

            def _set_done(vlt, state, *, quiet):
                state["phases"]["collect"]["status"] = DONE
                _save_state(vlt, state)
                return 0

            def _set_extract_done(vlt, state, *, quiet):
                state["phases"]["extract"]["status"] = DONE
                _save_state(vlt, state)
                return 0

            def _set_scout_done(vlt, state, *, quiet):
                state["phases"]["scout"]["status"] = DONE
                _save_state(vlt, state)
                return 0

            mock_collect.side_effect = _set_done
            mock_extract.side_effect = _set_extract_done
            mock_scout.side_effect = _set_scout_done

            rc = run_full(vault, quiet=True)

        assert rc == 0
        state_path = vault / "_pipeline" / "pipeline-state.json"
        assert state_path.exists()
        state = json.loads(state_path.read_text())
        assert state["phases"]["collect"]["status"] == DONE
        assert state["phases"]["extract"]["status"] == DONE
        assert state["phases"]["scout"]["status"] == DONE
        assert state["phases"]["triage"]["status"] == WAITING
        assert state["phases"]["research"]["status"] == PENDING
        assert state["phases"]["verify"]["status"] == PENDING
        assert state["phases"]["report"]["status"] == PENDING

    def test_full_pipeline_with_collector_mock(self, vault: Path) -> None:
        """Integration-style: mock at the collector boundary."""
        mock_collect = MagicMock(return_value=self._mock_collect_result())

        def fake_extract(vlt, **kwargs):
            return self._mock_extract_result(vlt)

        with (
            patch("research_framework.collectors.rss.collect", mock_collect),
            patch("research_framework.processors.extract.extract", fake_extract),
            patch(
                "research_framework.pipeline.runner._call_agent",
                side_effect=_agent_writes_its_artifact,
            ),
        ):
            rc = run_full(vault, quiet=True)

        assert rc == 0
        state = json.loads((vault / "_pipeline" / "pipeline-state.json").read_text())
        assert state["phases"]["triage"]["status"] == WAITING


# ---------------------------------------------------------------------------
# run_resume()
# ---------------------------------------------------------------------------


class TestRunResume:
    def test_resume_transitions_triage_to_done(self, tmp_path: Path) -> None:
        _make_state(
            tmp_path,
            phases={
                "collect": {"status": DONE},
                "extract": {"status": DONE},
                "scout": {"status": DONE},
                "triage": {"status": WAITING},
            },
        )

        with patch(
            "research_framework.pipeline.runner._drive_research"
        ) as mock_research:

            def _research_done(vlt, state, *, quiet):
                state["phases"]["research"]["status"] = DONE
                _save_state(vlt, state)
                return 0

            mock_research.side_effect = _research_done
            rc = run_resume(tmp_path, quiet=True)

        assert rc == 0
        state = json.loads((tmp_path / "_pipeline" / "pipeline-state.json").read_text())
        assert state["phases"]["triage"]["status"] == DONE
        assert state["phases"]["research"]["status"] == DONE

    def test_resume_calls_research_driver(self, tmp_path: Path) -> None:
        _make_state(tmp_path, phases={"triage": {"status": WAITING}})

        with patch(
            "research_framework.pipeline.runner._call_agent",
            side_effect=_agent_writes_its_artifact,
        ) as mock_agent:
            run_resume(tmp_path, quiet=True)

        # No _pipeline/prompts/dfs-prompt.md in this bare tmp vault, so there
        # is nothing to render — prompt_file is None and _call_agent reports
        # the gap. TestStagePromptRendering covers the rendered case.
        mock_agent.assert_called_once_with(
            tmp_path,
            stage="research",
            quiet=True,
            prompt_file=None,
            run_dir=tmp_path / "_pipeline" / "runs" / "2026-05-14-1500",
        )

    def test_resume_success_prints_finish_as_the_next_step(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Issue #285: `resume` runs research only (#245) and used to end
        silently, leaving `full`'s printed "then: resume" trail as the only
        guidance anywhere — an operator who followed it never learned that
        `finish` (verify + report) exists. `resume` must now name it."""
        _make_state(tmp_path, phases={"triage": {"status": WAITING}})

        with (
            patch("research_framework.pipeline.runner._drive_research", return_value=0),
            caplog.at_level(logging.INFO),
        ):
            rc = run_resume(tmp_path, quiet=False)

        assert rc == 0
        assert "finish" in caplog.text
        assert str(tmp_path) in caplog.text

    def test_resume_failure_does_not_print_finish_guidance(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A failed research phase has nothing for `finish` to build on —
        pointing the operator at it anyway would suggest the run is further
        along than it is."""
        _make_state(tmp_path, phases={"triage": {"status": WAITING}})

        with (
            patch("research_framework.pipeline.runner._drive_research", return_value=1),
            caplog.at_level(logging.INFO),
        ):
            rc = run_resume(tmp_path, quiet=False)

        assert rc == 1
        assert "finish" not in caplog.text

    def test_resume_quiet_suppresses_finish_guidance(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        _make_state(tmp_path, phases={"triage": {"status": WAITING}})

        with (
            patch("research_framework.pipeline.runner._drive_research", return_value=0),
            caplog.at_level(logging.INFO),
        ):
            run_resume(tmp_path, quiet=True)

        assert "finish" not in caplog.text


# ---------------------------------------------------------------------------
# run_collect / run_extract / run_scout individually
# ---------------------------------------------------------------------------


class TestIndividualPhases:
    def test_run_collect_updates_state(self, tmp_path: Path) -> None:
        mock_result = CollectResult(fetched=3, skipped_existing=0, errors=())
        with patch(
            "research_framework.collectors.rss.collect", return_value=mock_result
        ):
            rc = run_collect(tmp_path, quiet=True)
        assert rc == 0
        state = json.loads((tmp_path / "_pipeline" / "pipeline-state.json").read_text())
        assert state["phases"]["collect"]["status"] == DONE
        assert state["phases"]["collect"]["summary"]["items_new"] == 3

    def test_run_collect_records_errors(self, tmp_path: Path) -> None:
        mock_result = CollectResult(
            fetched=0, skipped_existing=0, errors=("feed timeout",)
        )
        with patch(
            "research_framework.collectors.rss.collect", return_value=mock_result
        ):
            rc = run_collect(tmp_path, quiet=True)
        assert rc == 1
        state = json.loads((tmp_path / "_pipeline" / "pipeline-state.json").read_text())
        assert state["phases"]["collect"]["status"] == FAILED
        assert "feed timeout" in state["phases"]["collect"]["errors"]

    def test_run_extract_updates_state(self, tmp_path: Path) -> None:
        ct = tmp_path / "_pipeline" / "extracted" / "context-tree.md"
        ct.parent.mkdir(parents=True, exist_ok=True)
        ct.write_text("# CT\n", encoding="utf-8")
        mock_result = ExtractResult(
            files_processed=4, files_skipped=0, context_tree_path=ct, errors=()
        )
        with patch(
            "research_framework.processors.extract.extract", return_value=mock_result
        ):
            rc = run_extract(tmp_path, quiet=True)
        assert rc == 0
        state = json.loads((tmp_path / "_pipeline" / "pipeline-state.json").read_text())
        assert state["phases"]["extract"]["status"] == DONE

    def test_run_scout_calls_agent(self, tmp_path: Path) -> None:
        with patch(
            "research_framework.pipeline.runner._call_agent",
            side_effect=_agent_writes_its_artifact,
        ) as mock_agent:
            rc = run_scout(tmp_path, quiet=True)
        # No _pipeline/prompts/scout-prompt.md in this bare tmp vault, so
        # there's nothing to render — prompt_file is None.
        _assert_dispatched(mock_agent, tmp_path, "scout")
        assert rc == 0

    def test_run_scout_renders_and_passes_prompt_file(self, tmp_path: Path) -> None:
        """The actual bug fix: when a scout-prompt.md template exists, it
        must be rendered (placeholders substituted) and handed to
        _call_agent via --prompt-file, not left for agent_call.py to read
        from an empty/closed stdin."""
        template = tmp_path / "_pipeline" / "prompts" / "scout-prompt.md"
        template.parent.mkdir(parents=True, exist_ok=True)
        template.write_text(
            "Scout cycle {CYCLE_NUM}. Write JSON to {SCOUT_REPORT}.\n",
            encoding="utf-8",
        )

        with patch(
            "research_framework.pipeline.runner._call_agent",
            side_effect=_agent_writes_its_artifact,
        ) as mock_agent:
            rc = run_scout(tmp_path, quiet=True)

        assert rc == 0
        _, kwargs = mock_agent.call_args
        prompt_file = kwargs["prompt_file"]
        assert prompt_file is not None
        rendered = prompt_file.read_text(encoding="utf-8")
        assert "{CYCLE_NUM}" not in rendered
        assert "{SCOUT_REPORT}" not in rendered
        assert "Scout cycle 1." in rendered

    def test_call_agent_fails_fast_without_prompt_file(self, tmp_path: Path) -> None:
        """No prompt_file means no subprocess is spawned at all — the
        pre-fix behaviour silently forwarded an empty stdin to a live
        `claude --print` call and failed with a confusing inner-CLI error."""
        from research_framework.pipeline.runner import _call_agent

        with patch(
            "research_framework.pipeline.runner._dispatch_agent"
        ) as mock_dispatch:
            outcome = _call_agent(
                tmp_path, stage="research", quiet=True, prompt_file=None
            )

        assert outcome.returncode == 2
        mock_dispatch.assert_not_called()

    def test_run_finish_runs_verify_then_report(self, tmp_path: Path) -> None:
        _make_verify_result = VerifyResult(
            files_processed=10,
            notes_checked=10,
            auto_fixes_applied=0,
            structural_flags=0,
            malformed_count=0,
            verdict="PASS",
            report={},
            errors=(),
        )
        with (
            patch(
                "research_framework.processors.verify.verify",
                return_value=_make_verify_result,
            ),
            patch(
                "research_framework.pipeline.runner._call_agent",
                side_effect=_agent_writes_its_artifact,
            ) as mock_agent,
        ):
            rc = run_finish(tmp_path, quiet=True)
        assert rc == 0
        # No .claude/commands/report.md in this bare tmp vault, so there is
        # nothing to render — see TestStagePromptRendering for the rendered
        # case.
        _assert_dispatched(mock_agent, tmp_path, "report")
        state = json.loads((tmp_path / "_pipeline" / "pipeline-state.json").read_text())
        assert state["phases"]["verify"]["status"] == DONE
        assert state["phases"]["report"]["status"] == DONE


# ---------------------------------------------------------------------------
# Stage prompt rendering (research / report)
# ---------------------------------------------------------------------------


class TestStagePromptRendering:
    """`pipeline resume` / `pipeline finish` used to reach the agent with no
    prompt at all: `_drive_research` and `_drive_report` hardcoded
    `prompt_file=None`, so every run died on

        ERROR: no rendered prompt available for stage 'research'; this
        pipeline runner has no template wired up for it yet ...

    These lock the wiring in the same shape as the scout tests above: a
    source on disk must be rendered (placeholders substituted, artifacts
    named) and handed to `_call_agent` via `--prompt-file`.
    """

    def _write_dfs_prompt(self, vault: Path) -> Path:
        template = vault / "_pipeline" / "prompts" / "dfs-prompt.md"
        template.parent.mkdir(parents=True, exist_ok=True)
        template.write_text(
            "DFS research cycle {CYCLE_NUM}.\n"
            "Read the scout report at `{SCOUT_REPORT}`.\n"
            "Write the JSON report to: `{RESEARCH_REPORT}`\n",
            encoding="utf-8",
        )
        return template

    def _write_report_agent(self, vault: Path) -> Path:
        agent = vault / ".claude" / "commands" / "report.md"
        agent.parent.mkdir(parents=True, exist_ok=True)
        agent.write_text("# Weekly Report Agent\n\nProduce the briefing.\n", "utf-8")
        return agent

    # -- research ----------------------------------------------------------

    def test_research_renders_dfs_prompt_and_passes_prompt_file(
        self, tmp_path: Path
    ) -> None:
        self._write_dfs_prompt(tmp_path)
        _make_state(tmp_path, phases={"triage": {"status": WAITING}})

        with patch(
            "research_framework.pipeline.runner._call_agent",
            side_effect=_agent_writes_its_artifact,
        ) as mock_agent:
            rc = run_resume(tmp_path, quiet=True)

        assert rc == 0
        _, kwargs = mock_agent.call_args
        prompt_file = kwargs["prompt_file"]
        assert prompt_file is not None
        assert prompt_file == _run_prompt(tmp_path, "research")
        rendered = prompt_file.read_text(encoding="utf-8")
        assert "{CYCLE_NUM}" not in rendered
        assert "{SCOUT_REPORT}" not in rendered
        assert "{RESEARCH_REPORT}" not in rendered
        assert "DFS research cycle 1." in rendered

    def test_research_prompt_names_the_queue_artifact_the_pipeline_writes(
        self, tmp_path: Path
    ) -> None:
        """The queue is `_pipeline/scout-report.json` — the file `_drive_scout`
        told the scout agent to write. It is NOT a Topic Radar note; a
        pipeline run never produces one."""
        self._write_dfs_prompt(tmp_path)
        _make_state(tmp_path, phases={"triage": {"status": WAITING}})

        with patch(
            "research_framework.pipeline.runner._call_agent",
            side_effect=_agent_writes_its_artifact,
        ):
            run_resume(tmp_path, quiet=True)

        rendered = _run_prompt(tmp_path, "research").read_text(encoding="utf-8")
        assert str(tmp_path / "_pipeline" / "scout-report.json") in rendered
        assert str(tmp_path / "_pipeline" / "research-report.json") in rendered

    def test_research_phase_is_done_when_the_agent_succeeds(
        self, tmp_path: Path
    ) -> None:
        self._write_dfs_prompt(tmp_path)
        _make_state(tmp_path, phases={"triage": {"status": WAITING}})

        with patch(
            "research_framework.pipeline.runner._call_agent",
            side_effect=_agent_writes_its_artifact,
        ):
            rc = run_resume(tmp_path, quiet=True)

        assert rc == 0
        state = json.loads((tmp_path / "_pipeline" / "pipeline-state.json").read_text())
        assert state["phases"]["research"]["status"] == DONE

    # -- report ------------------------------------------------------------

    def test_report_renders_the_agent_definition_and_passes_prompt_file(
        self, tmp_path: Path
    ) -> None:
        self._write_report_agent(tmp_path)
        verify_result = VerifyResult(
            files_processed=1,
            notes_checked=1,
            auto_fixes_applied=0,
            structural_flags=0,
            malformed_count=0,
            verdict="PASS",
            report={},
            errors=(),
        )
        with (
            patch(
                "research_framework.processors.verify.verify",
                return_value=verify_result,
            ),
            patch(
                "research_framework.pipeline.runner._call_agent",
                side_effect=_agent_writes_its_artifact,
            ) as mock_agent,
        ):
            rc = run_finish(tmp_path, quiet=True)

        assert rc == 0
        _, kwargs = mock_agent.call_args
        prompt_file = kwargs["prompt_file"]
        assert prompt_file is not None
        assert prompt_file == _run_prompt(tmp_path, "report", kwargs["run_dir"].name)
        rendered = prompt_file.read_text(encoding="utf-8")
        # The agent definition's own body survives verbatim ...
        assert "Produce the briefing." in rendered
        # ... under a run-context block naming this run's real artifacts.
        assert "## Pipeline run context" in rendered
        assert str(tmp_path / "_pipeline" / "scout-report.json") in rendered
        assert str(tmp_path / STATE_FILE) in rendered

    def test_report_context_block_precedes_the_agent_definition(
        self, tmp_path: Path
    ) -> None:
        self._write_report_agent(tmp_path)
        dest = _render_stage_prompt(tmp_path, "report")
        assert dest is not None
        rendered = dest.read_text(encoding="utf-8")
        assert rendered.index("## Pipeline run context") < rendered.index(
            "# Weekly Report Agent"
        )

    # -- absent / unrenderable sources -------------------------------------

    @pytest.mark.parametrize("stage", ["scout", "research", "report"])
    def test_missing_source_renders_nothing(self, tmp_path: Path, stage: str) -> None:
        assert _render_stage_prompt(tmp_path, stage) is None

    def test_unknown_stage_renders_nothing(self, tmp_path: Path) -> None:
        assert _render_stage_prompt(tmp_path, "collect") is None

    def test_render_failure_degrades_to_no_prompt_file(self, tmp_path: Path) -> None:
        """An unreadable / unwritable source must not crash the phase: it
        degrades to `prompt_file=None` so `_call_agent` emits the actionable
        'missing or failed to render' error and the phase is recorded FAILED."""
        self._write_dfs_prompt(tmp_path)

        with patch(
            "research_framework.pipeline._helpers._scout_prompts._render_prompt",
            side_effect=OSError("disk full"),
        ):
            assert _render_stage_prompt(tmp_path, "research") is None

    def test_research_phase_fails_when_rendering_fails(self, tmp_path: Path) -> None:
        self._write_dfs_prompt(tmp_path)
        _make_state(tmp_path, phases={"triage": {"status": WAITING}})

        with (
            patch(
                "research_framework.pipeline._helpers._scout_prompts._render_prompt",
                side_effect=OSError("disk full"),
            ),
            patch(
                "research_framework.pipeline.runner._dispatch_agent"
            ) as mock_dispatch,
        ):
            rc = run_resume(tmp_path, quiet=True)

        assert rc == 1
        mock_dispatch.assert_not_called()
        state = json.loads((tmp_path / "_pipeline" / "pipeline-state.json").read_text())
        assert state["phases"]["research"]["status"] == FAILED
        assert state["phases"]["research"]["errors"] == [
            "research agent exited with code 2"
        ]

    @pytest.mark.parametrize(
        ("stage", "expected_source"),
        [
            ("scout", "_pipeline/prompts/scout-prompt.md"),
            ("research", "_pipeline/prompts/dfs-prompt.md"),
            ("report", ".claude/commands/report.md"),
        ],
    )
    def test_call_agent_names_the_missing_source(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        stage: str,
        expected_source: str,
    ) -> None:
        """The old message ('no template wired up for it yet') told the
        operator nothing actionable. Name the file that is missing."""
        from research_framework.pipeline.runner import _call_agent

        with caplog.at_level(logging.ERROR):
            outcome = _call_agent(tmp_path, stage=stage, quiet=True, prompt_file=None)

        assert outcome.returncode == 2
        assert expected_source in caplog.text
        assert "no template wired up" not in caplog.text
