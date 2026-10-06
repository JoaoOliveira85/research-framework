"""Resume must re-check the cap that actually paused the run (issue #231).

``handle_budget_marker_on_resume`` re-checked the dollar cap and nothing else.
A ``BUDGET_PAUSED`` written for ``wallclock_exceeded`` or
``codex_token_cap_exceeded`` — or one carrying a bogus ``pause_reason`` /
``schema_version`` — was loaded, discarded, and deleted, and the run resumed
with no check and no output. ``validate_budget_paused_marker`` existed with
zero production callers, against ``budget-marker.contract.md`` §4.2.

Tier 3: real marker files, real settings, real sidecar sums.
"""

from __future__ import annotations

import json
import shutil
import sys
from argparse import Namespace
from pathlib import Path
from typing import Any

import pytest

from research_framework.cli.budget_resume import handle_budget_marker_on_resume
from research_framework.pipeline.budget_guard import (
    BudgetPausedMarker,
    atomic_write_json_marker,
)

_FIXTURE_VAULT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "cost_enforcement" / "vault"
)

#: The fixture vault's cycle-001 sidecars carry exactly one metered-runtime
#: (``codex``) call, worth 200 + 100 tokens. Named so a fixture change that
#: invalidates the token assertions below fails loudly rather than silently
#: making them vacuous.
_FIXTURE_METERED_TOKENS = 300


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    shutil.copytree(_FIXTURE_VAULT, vault)
    return vault


def _write_settings(vault: Path, limits: str) -> None:
    (vault / "settings.yaml").write_text(
        "pipeline:\n  max_cycles: 2\n  budget_usd: 1.0\nlimits:\n" + limits,
        encoding="utf-8",
    )


def _write_marker(vault: Path, marker: BudgetPausedMarker, **overrides: Any) -> Path:
    doc = marker.to_json_dict()
    doc.update(overrides)
    path = vault / "_pipeline/BUDGET_PAUSED"
    atomic_write_json_marker(path, doc)
    return path


def _token_marker() -> BudgetPausedMarker:
    return BudgetPausedMarker(
        pause_reason="codex_token_cap_exceeded",
        cycle_number=1,
        paused_stage="research",
        cumulative_spend_usd=0.0,
        cycle_budget_usd=100.0,
        dispatch_estimate_usd=0.0,
        codex_tokens_cumulative=900_000,
        codex_token_budget=100,
    )


def _wallclock_marker() -> BudgetPausedMarker:
    return BudgetPausedMarker(
        pause_reason="wallclock_exceeded",
        cycle_number=1,
        paused_stage="scout",
        cumulative_spend_usd=0.0,
        cycle_budget_usd=100.0,
        dispatch_estimate_usd=0.0,
        wallclock_elapsed_seconds=99999.0,
        wallclock_cap_seconds=60.0,
    )


@pytest.fixture(autouse=True)
def _headless(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default every test to the unattended shape the framework runs in."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    monkeypatch.delenv("RF_FORCE_BUDGET_ACK", raising=False)


# --------------------------------------------------------------------------
# codex / cursor token cap
# --------------------------------------------------------------------------


def test_resume_refuses_when_the_token_cap_is_still_exceeded(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    _write_settings(vault, "  codex_token_budget: 100\n")
    path = _write_marker(vault, _token_marker())
    rc = handle_budget_marker_on_resume(Namespace(force_budget=False), vault, 1)
    assert rc == 1
    assert path.is_file(), "a refused resume must retain the marker"


def test_token_refusal_names_the_tally_and_the_cap(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _vault(tmp_path)
    _write_settings(vault, "  codex_token_budget: 100\n")
    _write_marker(vault, _token_marker())
    handle_budget_marker_on_resume(Namespace(force_budget=False), vault, 1)
    err = capsys.readouterr().err
    assert str(_FIXTURE_METERED_TOKENS) in err
    assert "codex_token_budget" in err


def test_resume_clears_token_marker_once_the_operator_raised_the_cap(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    _write_settings(vault, "  codex_token_budget: 100000\n")
    path = _write_marker(vault, _token_marker())
    rc = handle_budget_marker_on_resume(Namespace(force_budget=False), vault, 1)
    assert rc == 0
    assert not path.exists()


def test_force_budget_headless_needs_ack_for_a_token_pause(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    _write_settings(vault, "  codex_token_budget: 100\n")
    path = _write_marker(vault, _token_marker())
    rc = handle_budget_marker_on_resume(Namespace(force_budget=True), vault, 1)
    assert rc == 1
    assert path.is_file()


def test_force_budget_with_ack_resumes_over_a_token_pause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RF_FORCE_BUDGET_ACK", "1")
    vault = _vault(tmp_path)
    _write_settings(vault, "  codex_token_budget: 100\n")
    path = _write_marker(vault, _token_marker())
    rc = handle_budget_marker_on_resume(Namespace(force_budget=True), vault, 1)
    assert rc == 0
    assert not path.exists()


# --------------------------------------------------------------------------
# wall-clock cap
# --------------------------------------------------------------------------


def test_resume_refuses_when_the_wallclock_cap_is_still_exceeded(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    _write_settings(vault, "  cycle_wallclock_budget_minutes: 1\n")
    path = _write_marker(vault, _wallclock_marker())
    rc = handle_budget_marker_on_resume(Namespace(force_budget=False), vault, 1)
    assert rc == 1
    assert path.is_file()


def test_resume_clears_wallclock_marker_once_the_operator_raised_the_cap(
    tmp_path: Path,
) -> None:
    """The marker's recorded elapsed is the authority across a process restart.

    ``CycleSpendTally.cycle_started_mono`` is a ``time.monotonic()`` reading:
    it cannot survive the process that wrote it, so resume has nothing to
    recompute the elapsed time from. The elapsed the marker recorded is
    therefore what the CURRENT cap is re-tested against — 99999s against a
    2000-minute (120000s) ceiling clears.
    """
    vault = _vault(tmp_path)
    _write_settings(vault, "  cycle_wallclock_budget_minutes: 2000\n")
    path = _write_marker(vault, _wallclock_marker())
    rc = handle_budget_marker_on_resume(Namespace(force_budget=False), vault, 1)
    assert rc == 0
    assert not path.exists()


def test_wallclock_pause_is_not_cleared_by_a_generous_dollar_cap(
    tmp_path: Path,
) -> None:
    """The bug in one line: a dollar cap the run never hit cleared a time cap."""
    vault = _vault(tmp_path)
    _write_settings(
        vault,
        "  cycle_budget_usd: 1000.0\n  cycle_wallclock_budget_minutes: 1\n",
    )
    path = _write_marker(vault, _wallclock_marker())
    rc = handle_budget_marker_on_resume(Namespace(force_budget=False), vault, 1)
    assert rc == 1
    assert path.is_file()


# --------------------------------------------------------------------------
# malformed markers (contract §4.2)
# --------------------------------------------------------------------------


def test_resume_refuses_a_bogus_pause_reason_and_keeps_the_marker(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    _write_settings(vault, "  cycle_budget_usd: 1000.0\n")
    path = _write_marker(vault, _wallclock_marker(), pause_reason="whatever")
    rc = handle_budget_marker_on_resume(Namespace(force_budget=False), vault, 1)
    assert rc == 1
    assert path.is_file()


def test_resume_refuses_an_unknown_schema_version_and_keeps_the_marker(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    _write_settings(vault, "  cycle_budget_usd: 1000.0\n")
    path = _write_marker(vault, _wallclock_marker(), schema_version="9.9")
    rc = handle_budget_marker_on_resume(Namespace(force_budget=False), vault, 1)
    assert rc == 1
    assert path.is_file()


def test_resume_refuses_a_marker_missing_a_required_field(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    _write_settings(vault, "  cycle_budget_usd: 1000.0\n")
    path = vault / "_pipeline/BUDGET_PAUSED"
    doc = _wallclock_marker().to_json_dict()
    del doc["paused_stage"]
    atomic_write_json_marker(path, doc)
    rc = handle_budget_marker_on_resume(Namespace(force_budget=False), vault, 1)
    assert rc == 1
    assert path.is_file()


def test_resume_refuses_unparseable_marker_json(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    _write_settings(vault, "  cycle_budget_usd: 1000.0\n")
    path = vault / "_pipeline/BUDGET_PAUSED"
    path.write_text("{not json", encoding="utf-8")
    rc = handle_budget_marker_on_resume(Namespace(force_budget=False), vault, 1)
    assert rc == 1
    assert path.is_file()


def test_a_malformed_marker_is_never_forced_past_silently(tmp_path: Path) -> None:
    """``--force-budget`` forces past a CAP, not past an unreadable marker."""
    vault = _vault(tmp_path)
    _write_settings(vault, "  cycle_budget_usd: 1000.0\n")
    path = _write_marker(vault, _wallclock_marker(), pause_reason="whatever")
    rc = handle_budget_marker_on_resume(Namespace(force_budget=True), vault, 1)
    assert rc == 1
    assert path.is_file()


# --------------------------------------------------------------------------
# acknowledgement (the "no message" half of the report)
# --------------------------------------------------------------------------


def test_clearing_a_marker_says_which_cap_was_re_checked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _vault(tmp_path)
    _write_settings(vault, "  cycle_wallclock_budget_minutes: 2000\n")
    _write_marker(vault, _wallclock_marker())
    assert handle_budget_marker_on_resume(Namespace(force_budget=False), vault, 1) == 0
    err = capsys.readouterr().err
    assert "wallclock_exceeded" in err
    assert "BUDGET_PAUSED" in err


def test_headless_refusal_payload_is_machine_readable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _vault(tmp_path)
    _write_settings(vault, "  cycle_wallclock_budget_minutes: 1\n")
    _write_marker(vault, _wallclock_marker())
    handle_budget_marker_on_resume(Namespace(force_budget=False), vault, 1)
    err = capsys.readouterr().err.strip().splitlines()
    payload = json.loads(err[-1])
    assert payload["error"] == "budget_paused"
    assert payload["pause_reason"] == "wallclock_exceeded"
