"""A cycle that aborts (exit 2) must say why on stderr (issue #44, spec 070 FR6).

``run_single_cycle`` is the one door every cycle-running verb (`cycle`,
`research`, `generate --resume`) goes through. When the cycle runner returned 2
it logged nothing at ERROR: the step that returned 2 had narrated at INFO (SG-001
FAIL, "ABORT: scout report ...") or not at all (a validator ABORT, an agent that
exited 1), and ``run_cycles`` added only "cycle N aborted (exit 2)" at INFO.
``cli.main`` then saw rc=2 with no ERROR record and no stderr bytes, and printed
its "framework bug" backstop instead of the cause.

These tests assert the stream/severity (ERROR, which survives the non-TTY
WARNING default) and the *facts* named (stage, exit status, gate id, quota),
never the exact wording.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from research_framework.pipeline.abort_diagnosis import (
    diagnose_cycle_abort,
    quota_signature,
)
from research_framework.pipeline.coverage import save_targets
from research_framework.spec.schema import CoverageCategory, CoverageTargets


def _cycles(vault: Path) -> Path:
    d = vault / "_pipeline" / "cycles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _agent_log(vault: Path, stage: str, cycle: int, body: str, code: int) -> None:
    (_cycles(vault) / f"cycle-{cycle:03d}-{stage}.log").write_text(
        "# [03:55:58] launching: python agent_call.py\n"
        f"{body}\n"
        f"# [03:56:00] exited with code {code}\n",
        encoding="utf-8",
    )


# --------------------------------------------------------------------------
# quota / rate-limit signatures
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "You've hit your 5-hour limit · resets 6:40am (Europe/Lisbon)",
        "Claude usage limit reached. Your limit will reset at 3pm",
        '{"type":"error","error":{"type":"rate_limit_error","message":"x"}}',
        '{"type":"error","error":{"type":"overloaded_error"}}',
        "HTTP 429 Too Many Requests",
    ],
)
def test_quota_signatures_are_recognised(line: str) -> None:
    assert quota_signature(f"noise\n[03:56:00] {line}\nmore noise") is not None


@pytest.mark.parametrize(
    "line",
    [
        "Ignoring 14 permissions.allow entries from .claude/settings.json",
        "wrote 429 notes",
        "limit of 5 topics per batch",
    ],
)
def test_ordinary_output_is_not_a_quota_signature(line: str) -> None:
    assert quota_signature(line) is None


# --------------------------------------------------------------------------
# diagnose_cycle_abort — trigger 1: scout agent hit the usage limit
# --------------------------------------------------------------------------


def test_scout_agent_quota_exit_is_named_as_a_quota(tmp_path: Path) -> None:
    _agent_log(
        tmp_path,
        "scout",
        56,
        "[03:56:00] You've hit your 5-hour limit · resets 6:40am (Europe/Lisbon)",
        1,
    )

    text = diagnose_cycle_abort(tmp_path, 56)

    assert "scout" in text
    assert "exited 1" in text
    assert "5-hour limit" in text, "the agent's own words must be quoted"
    assert "quota" in text.lower() and "rate limit" in text.lower()
    assert "cycle-056-scout.json" in text, "the missing report must be named"
    assert "--resume" in text, "the remedy must be named"


def test_agent_failure_without_a_quota_signature_is_not_called_a_quota(
    tmp_path: Path,
) -> None:
    _agent_log(tmp_path, "scout", 3, "[03:56:00] Segmentation fault", 139)

    text = diagnose_cycle_abort(tmp_path, 3)

    assert "exited 139" in text
    assert "Segmentation fault" in text
    assert "quota" not in text.lower()


def test_a_clean_agent_exit_is_not_reported_as_a_failure(tmp_path: Path) -> None:
    _agent_log(tmp_path, "scout", 3, "[03:56:00] all good", 0)

    text = diagnose_cycle_abort(tmp_path, 3)

    assert "exited 0" not in text


# --------------------------------------------------------------------------
# diagnose_cycle_abort — trigger 2: gates / validators / retry exhaustion
# --------------------------------------------------------------------------


def test_failed_scout_step_gate_is_named(tmp_path: Path) -> None:
    (_cycles(tmp_path) / "cycle-056-step-gates.json").write_text(
        json.dumps(
            [
                {
                    "gate_id": "SG-001",
                    "status": "FAIL",
                    "metric_name": "new_topics",
                    "correction_hint": "return at least one new topic",
                    "message": "topics_found.new is empty — note-writer has no topics",
                    "metric_value": 0,
                    "threshold": 1,
                }
            ]
        ),
        encoding="utf-8",
    )

    text = diagnose_cycle_abort(tmp_path, 56)

    assert "SG-001" in text
    assert "topics_found.new is empty" in text


def test_validator_abort_sidecar_reason_is_named(tmp_path: Path) -> None:
    (_cycles(tmp_path) / "cycle-027-research.json.validation.json").write_text(
        json.dumps(
            {
                "status": "ABORT",
                "reason": "Report has 9 structural error(s)",
                "errors": ["missing required field: cycle"],
            }
        ),
        encoding="utf-8",
    )

    text = diagnose_cycle_abort(tmp_path, 27)

    assert "Report has 9 structural error(s)" in text
    assert "missing required field: cycle" in text


def test_a_validator_that_continued_is_not_blamed(tmp_path: Path) -> None:
    (_cycles(tmp_path) / "cycle-027-scout.json.validation.json").write_text(
        json.dumps({"status": "CONTINUE", "reason": "fine", "errors": []}),
        encoding="utf-8",
    )

    assert "fine" not in diagnose_cycle_abort(tmp_path, 27)


def test_specific_retry_abort_reason_is_carried_through(tmp_path: Path) -> None:
    text = diagnose_cycle_abort(
        tmp_path, 56, abort_reason="CG-001 failed after 3 attempts; last metric: 0"
    )

    assert "CG-001 failed after 3 attempts" in text


def test_nothing_recorded_still_gives_a_pointer_not_silence(tmp_path: Path) -> None:
    text = diagnose_cycle_abort(tmp_path, 9)

    assert text.strip()
    assert "cycle-009" in text, "must point at where the cycle's logs live"


# --------------------------------------------------------------------------
# run_single_cycle — the choke point: rc=2 must reach ERROR
# --------------------------------------------------------------------------


def test_aborted_cycle_reports_an_error_naming_the_agent_failure(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Trigger 1 end to end through the real ``run_single_cycle``."""
    from research_framework.pipeline.orchestrator import run_single_cycle

    def scout_hit_quota(vault: Path, cycle: int, _cap: float, _max: int) -> int:
        _agent_log(
            vault,
            "scout",
            cycle,
            "[03:56:00] You've hit your 5-hour limit · resets 6:40am",
            1,
        )
        return 2

    with caplog.at_level(logging.DEBUG):
        rc = run_single_cycle(
            tmp_path,
            cycle_num=56,
            budget_cap=10.0,
            max_cycles=60,
            spec=None,
            cycle_runner=scout_hit_quota,
        )

    assert rc == 2, "the exit code is part of the 077 contract and must not move"
    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    joined = " ".join(errors)
    assert "5-hour limit" in joined
    assert "quota" in joined.lower()
    assert "cycle 56" in joined


def test_cg001_exhaustion_reports_an_error_naming_the_gate(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Trigger 2: the cycle 'completes' three times with no yield, then exit 2."""
    from research_framework.pipeline.orchestrator import run_single_cycle

    save_targets(
        tmp_path,
        CoverageTargets(
            categories=[
                CoverageCategory(
                    name="concepts", note_type="concept", target_count=200, met_count=0
                )
            ]
        ),
    )

    def empty_cycle(vault: Path, cycle: int, _cap: float, _max: int) -> int:
        (_cycles(vault) / f"cycle-{cycle:03d}-research.json").write_text(
            json.dumps({"notes_created": [], "notes_updated": []}), encoding="utf-8"
        )
        return 0

    with caplog.at_level(logging.DEBUG):
        rc = run_single_cycle(
            tmp_path,
            cycle_num=1,
            budget_cap=10.0,
            max_cycles=5,
            spec=None,
            cycle_runner=empty_cycle,
        )

    assert rc == 2
    errors = " ".join(
        r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR
    )
    assert "CG-001" in errors


def test_cli_main_does_not_print_the_framework_bug_backstop_for_an_abort(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The user-visible symptom: the backstop text must be gone, the cause there.

    ``cli.main`` is real, including its ``_ReasonCounter`` / ``_StreamTap``
    backstop; only the parser is a stand-in, so the verb under test is the
    real ``run_single_cycle`` with a runner stub (the ``cycle_runner=`` seam).
    """
    import argparse

    from research_framework import cli
    from research_framework.pipeline.orchestrator import run_single_cycle

    def scout_hit_quota(vault: Path, cycle: int, _cap: float, _max: int) -> int:
        _agent_log(vault, "scout", cycle, "You've hit your 5-hour limit", 1)
        return 2

    class _Parser:
        def parse_args(self, _argv: list[str] | None) -> argparse.Namespace:
            return argparse.Namespace(
                log_level=None,
                verb_default_log_level=None,
                func=lambda _a: run_single_cycle(
                    tmp_path,
                    cycle_num=7,
                    budget_cap=10.0,
                    max_cycles=9,
                    spec=None,
                    cycle_runner=scout_hit_quota,
                ),
            )

    monkeypatch.setattr(cli, "build_parser", lambda: _Parser())

    rc = cli.main([])

    err = capsys.readouterr().err
    assert rc == 2
    # pytest owns the root logger's handlers, so the ERROR record is not
    # written to stderr here; what `main` decides from it is the contract:
    # a reason was reported, so the "framework bug" backstop stays silent.
    assert "framework bug" not in err
