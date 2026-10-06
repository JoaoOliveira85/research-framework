"""CLI tests for `research_framework pipeline` subcommand (015g)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from research_framework.cli import build_parser, main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_state(vault: Path, phases: dict | None = None) -> None:
    from research_framework.pipeline.runner import (
        _blank_state,
        _save_state,
    )

    state = _blank_state("2026-05-14-1500", "2026-05-14T15:00:00Z")
    if phases:
        for name, updates in phases.items():
            state["phases"][name].update(updates)
    _save_state(vault, state)


# ---------------------------------------------------------------------------
# Parser smoke tests
# ---------------------------------------------------------------------------


class TestPipelineParser:
    def test_parser_accepts_status(self, tmp_path: Path) -> None:
        parser = build_parser()
        args = parser.parse_args(["pipeline", str(tmp_path), "status"])
        assert args.pipeline_cmd == "status"
        assert args.vault == tmp_path

    def test_parser_accepts_full_with_budget_cap(self, tmp_path: Path) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["pipeline", str(tmp_path), "full", "--budget-cap", "5.0"]
        )
        assert args.pipeline_cmd == "full"
        assert args.budget_cap == 5.0

    def test_parser_accepts_quiet_flag(self, tmp_path: Path) -> None:
        parser = build_parser()
        args = parser.parse_args(["pipeline", str(tmp_path), "collect", "--quiet"])
        assert args.quiet is True

    def test_parser_accepts_json_flag_on_status(self, tmp_path: Path) -> None:
        parser = build_parser()
        args = parser.parse_args(["pipeline", str(tmp_path), "status", "--json"])
        assert args.json is True

    def test_parser_json_flag_defaults_false(self, tmp_path: Path) -> None:
        parser = build_parser()
        args = parser.parse_args(["pipeline", str(tmp_path), "status"])
        assert args.json is False

    @pytest.mark.parametrize(
        "cmd",
        ["full", "collect", "extract", "scout", "resume", "finish", "status"],
    )
    def test_all_subcommands_accepted(self, tmp_path: Path, cmd: str) -> None:
        parser = build_parser()
        args = parser.parse_args(["pipeline", str(tmp_path), cmd])
        assert args.pipeline_cmd == cmd


# ---------------------------------------------------------------------------
# status subcommand
# ---------------------------------------------------------------------------


class TestPipelineStatusCLI:
    def test_status_json_output_for_nonexistent_state(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        rc = main(["pipeline", str(tmp_path), "status", "--json"])
        assert rc == 0
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert "phases" in parsed
        for phase in (
            "collect",
            "extract",
            "scout",
            "triage",
            "research",
            "verify",
            "report",
        ):
            assert phase in parsed["phases"]

    def test_status_reflects_written_state(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        _write_state(
            tmp_path,
            phases={
                "collect": {"status": "done", "summary": {"items_new": 7}},
                "triage": {"status": "waiting"},
            },
        )
        rc = main(["pipeline", str(tmp_path), "status", "--json"])
        assert rc == 0
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["phases"]["collect"]["status"] == "done"
        assert parsed["phases"]["triage"]["status"] == "waiting"

    def test_status_returns_0(self, tmp_path: Path) -> None:
        rc = main(["pipeline", str(tmp_path), "status"])
        assert rc == 0

    def test_status_nonexistent_vault_returns_2(self) -> None:
        rc = main(["pipeline", "/nonexistent/vault/path", "status"])
        assert rc == 2

    def test_status_default_output_is_text_not_json_regardless_of_tty(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Issue #245: format is an explicit `--json` choice, not an accident
        of whether stdout happens to be a TTY (every cron/launchd run is a
        pipe, and used to be silently forced into JSON with no opt-out)."""
        rc = main(["pipeline", str(tmp_path), "status"])
        assert rc == 0
        out = capsys.readouterr().out
        with pytest.raises(json.JSONDecodeError):
            json.loads(out)
        assert "Pipeline status" in out

    def test_status_json_flag_forces_json_even_off_a_tty(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        rc = main(["pipeline", str(tmp_path), "status", "--json"])
        assert rc == 0
        parsed = json.loads(capsys.readouterr().out)
        assert "phases" in parsed

    def test_status_text_output_shows_errors_and_duration(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Issue #245: `pipeline status` is the one command an operator uses
        to ask why a run failed — a persisted `errors[]` and a phase's
        duration must be visible in the default (text) rendering, not just
        buried in `--json` output."""
        _write_state(
            tmp_path,
            phases={
                "verify": {
                    "status": "failed",
                    "started_at": "2026-09-01T10:00:00Z",
                    "finished_at": "2026-09-01T10:00:42Z",
                    "errors": ["verify processor error: malformed frontmatter"],
                    "summary": {"verdict": "FAIL"},
                },
            },
        )
        rc = main(["pipeline", str(tmp_path), "status"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "verify processor error: malformed frontmatter" in out
        assert "42s" in out

    def test_status_json_includes_duration_and_errors(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        _write_state(
            tmp_path,
            phases={
                "collect": {
                    "status": "done",
                    "started_at": "2026-09-01T10:00:00Z",
                    "finished_at": "2026-09-01T10:01:05Z",
                    "errors": [],
                },
            },
        )
        rc = main(["pipeline", str(tmp_path), "status", "--json"])
        assert rc == 0
        parsed = json.loads(capsys.readouterr().out)
        collect = parsed["phases"]["collect"]
        assert collect["duration_s"] == 65.0
        assert collect["errors"] == []


# ---------------------------------------------------------------------------
# Dispatches to runner functions
# ---------------------------------------------------------------------------


class TestPipelineDispatch:
    def test_collect_dispatches_to_runner(self, tmp_path: Path) -> None:
        with patch(
            "research_framework.pipeline.runner.run_collect", return_value=0
        ) as mock_run:
            rc = main(["pipeline", str(tmp_path), "collect", "--quiet"])
        mock_run.assert_called_once_with(tmp_path, quiet=True)
        assert rc == 0

    def test_extract_dispatches_to_runner(self, tmp_path: Path) -> None:
        with patch(
            "research_framework.pipeline.runner.run_extract", return_value=0
        ) as mock_run:
            rc = main(["pipeline", str(tmp_path), "extract"])
        mock_run.assert_called_once_with(tmp_path, quiet=False)
        assert rc == 0

    def test_scout_dispatches_to_runner(self, tmp_path: Path) -> None:
        with patch(
            "research_framework.pipeline.runner.run_scout", return_value=0
        ) as mock_run:
            rc = main(["pipeline", str(tmp_path), "scout"])
        mock_run.assert_called_once_with(tmp_path, quiet=False)
        assert rc == 0

    def test_resume_dispatches_to_runner(self, tmp_path: Path) -> None:
        with patch(
            "research_framework.pipeline.runner.run_resume", return_value=0
        ) as mock_run:
            rc = main(["pipeline", str(tmp_path), "resume"])
        mock_run.assert_called_once_with(tmp_path, quiet=False)
        assert rc == 0

    def test_finish_dispatches_to_runner(self, tmp_path: Path) -> None:
        with patch(
            "research_framework.pipeline.runner.run_finish", return_value=0
        ) as mock_run:
            rc = main(["pipeline", str(tmp_path), "finish"])
        mock_run.assert_called_once_with(tmp_path, quiet=False)
        assert rc == 0

    def test_full_dispatches_to_runner(self, tmp_path: Path) -> None:
        with patch(
            "research_framework.pipeline.runner.run_full", return_value=0
        ) as mock_run:
            rc = main(["pipeline", str(tmp_path), "full"])
        mock_run.assert_called_once_with(tmp_path, quiet=False)
        assert rc == 0

    def test_runner_error_propagates_exit_code(self, tmp_path: Path) -> None:
        with patch("research_framework.pipeline.runner.run_collect", return_value=1):
            rc = main(["pipeline", str(tmp_path), "collect"])
        assert rc == 1


class TestPipelineDryRunIsPruneRunsOnly:
    """`--dry-run` is a `prune-runs` flag. `pipeline <v> full --dry-run` parsed
    cleanly and then ran the real, paid pipeline — an operator asking for a
    rehearsal got the performance."""

    @pytest.mark.parametrize(
        "cmd", ["full", "collect", "extract", "scout", "resume", "finish"]
    )
    def test_dry_run_on_a_run_verb_is_refused(
        self, tmp_path: Path, cmd: str, capsys: pytest.CaptureFixture
    ) -> None:
        with patch(
            f"research_framework.pipeline.runner.run_{cmd}", return_value=0
        ) as mock_run:
            rc = main(["pipeline", str(tmp_path), cmd, "--dry-run"])
        assert rc == 2
        mock_run.assert_not_called()
        assert "--dry-run" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# --budget-cap is refused, never silently accepted (issue #232)
# ---------------------------------------------------------------------------


class TestPipelineBudgetCapIsRefused:
    """`pipeline --budget-cap` had no consumer anywhere in ``runner.py``.

    ``run_full`` took the parameter, the parser advertised it as "passed to
    agent invocations", and nothing read it — the fifth instance of the
    "accepted and silently ignored" class the 1.1.0 CHANGELOG records. It
    cannot be honoured yet: no ``pipeline`` phase writes a cost sidecar
    (issues #220/#221), so there is nothing to tally a cap against. Spec 074's
    precedent for exactly this shape is to refuse loudly.
    """

    @pytest.mark.parametrize(
        "cmd", ["full", "collect", "extract", "scout", "resume", "finish"]
    )
    def test_budget_cap_is_refused_with_exit_2(self, tmp_path: Path, cmd: str) -> None:
        with patch(
            f"research_framework.pipeline.runner.run_{cmd}", return_value=0
        ) as mock_run:
            rc = main(["pipeline", str(tmp_path), cmd, "--budget-cap", "3.5"])
        assert rc == 2
        mock_run.assert_not_called()

    def test_refusal_names_the_flag_and_a_surface_that_works(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        main(["pipeline", str(tmp_path), "full", "--budget-cap", "3.5"])
        err = capsys.readouterr().err
        assert "--budget-cap" in err
        assert "limits.cycle_budget_usd" in err

    def test_pipeline_still_runs_without_the_flag(self, tmp_path: Path) -> None:
        with patch(
            "research_framework.pipeline.runner.run_full", return_value=0
        ) as mock_run:
            rc = main(["pipeline", str(tmp_path), "full"])
        assert rc == 0
        mock_run.assert_called_once()

    def test_run_full_no_longer_advertises_a_budget_cap_parameter(self) -> None:
        """A dead keyword is an invitation to believe it does something."""
        import inspect

        from research_framework.pipeline.runner import run_full

        assert "budget_cap" not in inspect.signature(run_full).parameters

    def test_parser_help_does_not_claim_the_flag_is_forwarded(self) -> None:
        """`--help` said "passed to agent invocations". It was passed nowhere."""
        parser = build_parser()
        subs = [
            a for a in parser._actions if a.choices and "pipeline" in (a.choices or {})
        ]
        assert subs, "could not find the `pipeline` subparser"
        actions = [
            a for a in subs[0].choices["pipeline"]._actions if a.dest == "budget_cap"
        ]
        assert actions, "`--budget-cap` is gone from the parser entirely"
        help_text = actions[0].help or ""
        assert "passed to agent invocations" not in help_text
        assert "not implemented" in help_text.lower()


class TestPipelineStatusCarriesTheRunReceipt:
    """Spec 080 FR-018/FR-019 (issue #221).

    ``status`` is the one command an operator uses to ask "what happened".
    Until the receipt existed it could not answer "and what did it cost",
    because nothing recorded it. These keys are additions to the `status`
    dictionary, NOT to `pipeline-state.json`, whose schema stays
    `additionalProperties: false`.
    """

    @staticmethod
    def _vault_with_a_run(tmp_path: Path) -> tuple[Path, str]:
        from research_framework.pipeline.runner import _blank_state, _save_state

        vault = tmp_path / "vault"
        (vault / "_pipeline").mkdir(parents=True, exist_ok=True)
        state = _blank_state("2026-09-10-0900", "2026-09-10T09:00:00Z")
        run_dir = vault / "_pipeline" / "runs" / "2026-09-10-0900"
        (run_dir / "agent-calls").mkdir(parents=True, exist_ok=True)
        sidecar = run_dir / "agent-calls" / "scout.json"
        sidecar.write_text(
            json.dumps({"cost_usd": 0.75, "cost_source": "runtime"}), encoding="utf-8"
        )
        state["phases"]["scout"].update(
            {
                "status": "done",
                "started_at": "2026-09-10T09:00:00Z",
                "finished_at": "2026-09-10T09:00:30Z",
                "summary": {
                    "cost_sidecar": str(sidecar),
                    "cost_usd": 0.75,
                    "cost_source": "runtime",
                },
            }
        )
        (run_dir / "run.json").write_text("{}", encoding="utf-8")
        _save_state(vault, state)
        return vault, str(run_dir)

    def test_status_json_carries_cost_and_run_dir(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        vault, run_dir = self._vault_with_a_run(tmp_path)

        rc = main(["pipeline", str(vault), "status", "--json"])

        assert rc == 0
        doc = json.loads(capsys.readouterr().out)
        assert doc["run_dir"] == run_dir
        assert doc["receipt"] == str(Path(run_dir) / "run.json")
        assert doc["phases"]["scout"]["cost_usd"] == 0.75
        assert doc["phases"]["scout"]["cost_source"] == "runtime"
        assert doc["cost_total_usd"] == 0.75
        assert doc["cost_is_lower_bound"] is False

    def test_status_cost_keys_are_null_without_a_state_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """FR-019: one shape, whether or not there is a run to describe —
        #247's fleet view reads this, and a key that is sometimes absent is a
        key every consumer has to guard."""
        vault = tmp_path / "vault"
        vault.mkdir()

        rc = main(["pipeline", str(vault), "status", "--json"])

        assert rc == 0
        doc = json.loads(capsys.readouterr().out)
        assert doc["run_dir"] is None
        assert doc["receipt"] is None
        assert doc["cost_total_usd"] is None
        assert doc["phases"]["scout"]["cost_usd"] is None

    def test_status_text_renders_cost_per_phase_and_total(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        vault, run_dir = self._vault_with_a_run(tmp_path)

        main(["pipeline", str(vault), "status"])

        out = capsys.readouterr().out
        assert "$0.7500" in out
        assert run_dir in out

    def test_a_missing_sidecar_makes_the_total_a_lower_bound(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """FR-013. The label is the whole point: an operator adding up eight
        vaults' totals must not be adding up numbers that quietly omit a
        phase."""
        from research_framework.pipeline.runner import _blank_state, _save_state

        vault = tmp_path / "vault"
        (vault / "_pipeline").mkdir(parents=True, exist_ok=True)
        run_dir = vault / "_pipeline" / "runs" / "2026-09-10-0900" / "agent-calls"
        run_dir.mkdir(parents=True, exist_ok=True)
        readable = run_dir / "scout.json"
        readable.write_text(json.dumps({"cost_usd": 0.5}), encoding="utf-8")

        state = _blank_state("2026-09-10-0900", "2026-09-10T09:00:00Z")
        state["phases"]["scout"].update(
            {
                "status": "done",
                "summary": {"cost_sidecar": str(readable), "cost_usd": 0.5},
            }
        )
        state["phases"]["research"].update(
            {
                "status": "done",
                "summary": {"cost_sidecar": "/gone/research.json", "cost_usd": None},
            }
        )
        _save_state(vault, state)

        main(["pipeline", str(vault), "status"])

        out = capsys.readouterr().out
        assert "$0.5000" in out
        assert "lower bound" in out.lower()

    def test_a_run_with_no_readable_sidecar_reports_unknown_not_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`$0.0000` is a number an operator adds up across eight vaults.
        `unknown` is not."""
        from research_framework.pipeline.runner import _blank_state, _save_state

        vault = tmp_path / "vault"
        (vault / "_pipeline").mkdir(parents=True, exist_ok=True)
        state = _blank_state("2026-09-10-0900", "2026-09-10T09:00:00Z")
        state["phases"]["scout"].update(
            {
                "status": "done",
                "summary": {"cost_sidecar": "/gone/scout.json", "cost_usd": None},
            }
        )
        _save_state(vault, state)

        main(["pipeline", str(vault), "status"])

        out = capsys.readouterr().out
        assert "unknown" in out
        assert "$0.0000" not in out
