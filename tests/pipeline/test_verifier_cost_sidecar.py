"""Verifier spend must reach the budget guard (issue #234).

The verifier stage dispatched ``agent_call.py`` with ``--output-file`` and no
``--cost-sidecar``, so per-note verifier LLM spend produced no telemetry at
all: invisible to ``budget_guard``'s dollar cap and to the run report. The
fake agent hid it because a fake call costs $0 either way, which is why these
tests make the stub emit a NON-ZERO cost and then assert the guard's own
tally — a test that only checked the file existed would not have caught the
class the issue names.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from research_framework.pipeline.budget_guard import (
    CycleSpendTally,
    refresh_actuals,
    sum_sidecar_actuals_usd,
)
from research_framework.pipeline.verifier import run_verifier_stage

_ACCEPT = {"verdict": "accept", "violations": [], "suggested_fix": None}
_COST_PER_CALL = 0.03


def _make_note(vault: Path, rel_path: str) -> Path:
    note = vault / rel_path
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\ntitle: Alpha\ntype: concept\nsummary: A concept.\n---\n\nBody.\n",
        encoding="utf-8",
    )
    return note


def _make_scripts_dir(tmp_path: Path) -> Path:
    scripts = tmp_path / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "agent_call.py").write_text("# stub\n")
    return scripts


def _spending_agent(sidecar_paths: list[Path]):
    """Stand in for ``agent_call.py``: writes a verdict AND a v1.1 sidecar.

    Mirrors what the real dispatcher does on a metered call — the sidecar
    shape is spec 028's, the same one ``list_sidecars_v11`` reads.
    """

    def _fake_run(cmd, **kwargs):
        if "--output-file" in cmd:
            Path(cmd[cmd.index("--output-file") + 1]).write_text(json.dumps(_ACCEPT))
        if "--cost-sidecar" in cmd:
            path = Path(cmd[cmd.index("--cost-sidecar") + 1])
            sidecar_paths.append(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.1",
                        "stage": "verifier",
                        "agent": "claude",
                        "agent_kind": "real",
                        "tier": "basic",
                        "status": "ok",
                        "exit_code": 0,
                        "cost_usd": _COST_PER_CALL,
                        "tokens_in": 900,
                        "tokens_out": 300,
                        "latency_ms": 10,
                        "started_at": "2026-01-01T00:00:00Z",
                        "completed_at": "2026-01-01T00:00:01Z",
                        "cycle": 1,
                    }
                ),
                encoding="utf-8",
            )
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b""
        return mock

    return _fake_run


def _run(vault: Path, notes: list[str], cycle: int = 1) -> list[Path]:
    for rel in notes:
        _make_note(vault, rel)
    scripts_dir = _make_scripts_dir(vault)
    seen: list[Path] = []
    with patch(
        "research_framework.pipeline.verifier.popen_session",
        side_effect=_spending_agent(seen),
    ):
        run_verifier_stage(
            vault,
            cycle,
            {"notes_created": notes, "notes_updated": []},
            scripts_dir=scripts_dir,
        )
    return seen


def test_verifier_dispatch_passes_a_cost_sidecar(tmp_path: Path) -> None:
    seen = _run(tmp_path, ["data_vault/01 - Concepts/Alpha.md"])
    assert seen, "verifier dispatched without --cost-sidecar"


def test_verifier_sidecar_lands_where_the_budget_guard_globs(tmp_path: Path) -> None:
    """``list_sidecars_v11`` only sees ``cycles/cycle-NNN/agent-calls/*.json``."""
    seen = _run(tmp_path, ["data_vault/01 - Concepts/Alpha.md"], cycle=7)
    expected_dir = tmp_path / "_pipeline" / "cycles" / "cycle-007" / "agent-calls"
    assert seen[0].parent == expected_dir


def test_verifier_spend_is_tallied_by_the_budget_guard(tmp_path: Path) -> None:
    """The assertion the issue asks for: TALLIED, not merely written."""
    notes = [
        "data_vault/01 - Concepts/Alpha.md",
        "data_vault/01 - Concepts/Beta.md",
        "data_vault/01 - Concepts/Gamma.md",
    ]
    _run(tmp_path, notes)
    assert sum_sidecar_actuals_usd(tmp_path, 1) == len(notes) * _COST_PER_CALL


def test_verifier_tokens_reach_the_dollar_tally_used_pre_dispatch(
    tmp_path: Path,
) -> None:
    """``refresh_actuals`` is what ``CycleBudgetSession`` re-reads each call."""
    _run(tmp_path, ["data_vault/01 - Concepts/Alpha.md"])
    tally = CycleSpendTally(cycle_num=1)
    refresh_actuals(tmp_path, 1, tally)
    assert tally.actual_usd == _COST_PER_CALL


def test_one_note_one_sidecar_no_overwrites(tmp_path: Path) -> None:
    """Per-note calls must not collide on a single filename.

    A shared name would leave the tally reading one call's cost for the whole
    stage — a quieter version of the same invisibility.
    """
    notes = [
        "data_vault/01 - Concepts/Alpha.md",
        "data_vault/01 - Concepts/Beta.md",
        "data_vault/01 - Concepts/Gamma.md",
    ]
    seen = _run(tmp_path, notes)
    assert len(seen) == len(notes)
    assert len({p.name for p in seen}) == len(notes)


def test_a_missing_note_does_not_consume_a_sidecar_index(tmp_path: Path) -> None:
    """Skipped notes never dispatch, so they never claim a sidecar name."""
    notes = ["data_vault/01 - Concepts/Alpha.md", "data_vault/nope/Missing.md"]
    _make_note(tmp_path, notes[0])
    scripts_dir = _make_scripts_dir(tmp_path)
    seen: list[Path] = []
    with patch(
        "research_framework.pipeline.verifier.popen_session",
        side_effect=_spending_agent(seen),
    ):
        summary = run_verifier_stage(
            tmp_path,
            1,
            {"notes_created": notes, "notes_updated": []},
            scripts_dir=scripts_dir,
        )
    assert len(seen) == 1
    assert len(summary.verdicts) == 2
