"""Issue #15 — ``research-framework ask [--escalate]`` against a fake-agent vault.

The ask dispatch is real: the vault's own ``/ask`` command, rendered from the
template, sent through ``scripts/agent_call.py`` — which ``build_minimal_vault``
replaces with ``tests/_helpers/fake_agent.py``. The fake reports a
``VAULT-GAP:`` line while ``data_vault/`` is empty and cites a note once one
exists.

The research run is ``orchestrator.run_single_cycle`` recorded in place
(the ``cycle`` verb's own tests do the same), except in the e2e test at the
bottom, which runs the real cycle with the fake agent and watches the gap
become a note and a re-answer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from research_framework.cli import build_parser, main
from research_framework.pipeline.ask_escalation import GAP_LINE_PREFIX
from tests._helpers.vault_factory import build_minimal_vault

_QUESTION = "Which regional consultancies place contract engineers?"

#: A spec that LOADS — ``build_minimal_vault`` writes a deliberately partial
#: one, and ``cycle --target-topics`` refuses a vault whose spec cannot load
#: (spec 074).
_SPEC = """---
name: "Ask Escalation Test"
owner: "test"
topic: |
  A vault used only to prove that ask --escalate researches a reported gap.
goal: |
  Exercise the ask verb.
sources:
  - name: "Web"
    type: external
    kind: strategy_hint
---
"""


def _vault(tmp_path: Path, **kw: Any) -> Path:
    vault = build_minimal_vault(tmp_path, **kw)
    (vault / "research.spec.md").write_text(_SPEC, encoding="utf-8")
    _edit_settings(vault, lambda s: s["stages"].update({"ask": _ASK_STAGE}))
    return vault


#: The read-only block every shipped profile carries; ``ask`` refuses a vault
#: without one rather than dispatch with default_executor's permissions.
_ASK_STAGE = {
    "inherit_args": False,
    "args": ["--tools", "Read,Grep,Glob", "--strict-mcp-config"],
    "retry": 0,
}


def _edit_settings(vault: Path, change: Any) -> None:
    import yaml

    path = vault / "settings.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _record_cycles(
    monkeypatch: pytest.MonkeyPatch,
    rc: int = 0,
    side_effect: Any = None,
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def _fake(vault_dir: Path, cycle_num: int, *args: Any, **kwargs: Any) -> int:
        calls.append({"vault_dir": vault_dir, "cycle_num": cycle_num, **kwargs})
        if side_effect is not None:
            side_effect(vault_dir)
        return rc

    monkeypatch.setattr(
        "research_framework.pipeline.orchestrator.run_single_cycle", _fake
    )
    return calls


def _answers(vault: Path) -> list[str]:
    """Answers in dispatch order: ``ask.md``, then ``ask-2.md`` (FR-005 suffix)."""

    def _order(path: Path) -> tuple[str, int]:
        _, _, n = path.stem.partition("-")
        return (path.parent.parent.name, int(n) if n else 1)

    paths = (vault / "_pipeline" / "ask").glob("*/answers/*.md")
    return [p.read_text(encoding="utf-8") for p in sorted(paths, key=_order)]


def _notes(vault: Path) -> list[Path]:
    return [
        p
        for p in (vault / "data_vault").rglob("*.md")
        if not p.name.startswith("_") and "_templates" not in p.parts
    ]


def _ask(vault: Path, *extra: str) -> int:
    return main(["ask", "--vault", str(vault), *extra, _QUESTION])


def test_without_escalate_a_reported_gap_starts_no_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    vault = _vault(tmp_path)
    cycles = _record_cycles(monkeypatch)

    rc = _ask(vault)

    assert rc == 0
    assert cycles == [], "ask without --escalate must never start a run"
    answers = _answers(vault)
    assert len(answers) == 1 and GAP_LINE_PREFIX in answers[0]
    assert "--escalate" in caplog.text


def test_with_escalate_the_gap_topic_reaches_one_cycle_under_the_ladder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No cap is invented: the cycle gets settings' `pipeline.budget_usd`."""
    vault = _vault(tmp_path)
    settings = vault / "settings.yaml"
    settings.write_text(
        settings.read_text(encoding="utf-8").replace(
            "budget_usd: 10.0", "budget_usd: 3.5"
        ),
        encoding="utf-8",
    )
    assert "budget_usd: 3.5" in settings.read_text(encoding="utf-8")
    cycles = _record_cycles(monkeypatch)

    rc = _ask(vault, "--escalate")

    assert rc == 0
    assert len(cycles) == 1
    call = cycles[0]
    assert call["target_topics"] == [_QUESTION]
    assert call["cycle_num"] == 1
    assert call["budget_cap"] == 3.5
    assert call["spec"] is not None
    # The stand-in cycle wrote nothing, so the re-ask still reports the gap —
    # and is NOT escalated a second time.
    assert len(_answers(vault)) == 2


def test_a_standing_budget_pause_refuses_the_escalation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from research_framework.pipeline.budget_guard import budget_marker_path

    vault = _vault(tmp_path)
    marker = budget_marker_path(vault)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"pause_reason": "cycle_budget_exceeded"}))
    cycles = _record_cycles(monkeypatch)

    rc = _ask(vault, "--escalate")

    assert rc == 2
    assert cycles == []
    assert len(_answers(vault)) == 1, "a refused run must not be followed by a re-ask"


def test_the_lifetime_cycle_ceiling_refuses_the_escalation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(tmp_path, max_cycles=1)
    cycles_dir = vault / "_pipeline" / "cycles"
    cycles_dir.mkdir(parents=True, exist_ok=True)
    (cycles_dir / "cycle-001-quality-report.json").write_text("{}")
    cycles = _record_cycles(monkeypatch)

    rc = _ask(vault, "--escalate")

    assert rc == 2
    assert cycles == []


def test_a_stale_ask_command_is_refused_before_any_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pre-#15 ask.md tells the agent to start a cycle itself."""
    vault = _vault(tmp_path)
    (vault / ".claude" / "commands" / "ask.md").write_text(
        "# /ask\n\n## Question\n\n$ARGUMENTS\n\n## Research Escalation\n\n"
        "research-framework cycle --vault . --cycle 1 --target-topics x\n",
        encoding="utf-8",
    )
    cycles = _record_cycles(monkeypatch)

    rc = _ask(vault, "--escalate")

    assert rc == 2
    assert cycles == []
    assert _answers(vault) == []


def test_ask_has_no_budget_flag_of_its_own() -> None:
    """The ceiling is the vault's ladder; an escalation cannot carry its own cap."""
    parser = build_parser()
    sub = next(a for a in parser._actions if a.dest == "command")
    options = {
        opt for action in sub.choices["ask"]._actions for opt in action.option_strings
    }
    assert options == {"-h", "--help", "--vault", "--escalate"}


def test_a_cycle_that_terminates_with_1_is_followed_by_a_re_ask(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """1 is the runner's TERMINATE (Condition A/B/C met), a finished cycle."""
    vault = _vault(tmp_path)
    cycles = _record_cycles(monkeypatch, rc=1)

    rc = _ask(vault, "--escalate")

    assert rc == 0
    assert len(cycles) == 1
    assert len(_answers(vault)) == 2


def test_a_budget_pause_inside_the_cycle_is_reported_as_a_pause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`pause_for_budget` writes its marker and exits 1 — the ceiling holding."""
    from research_framework.pipeline.budget_guard import budget_marker_path

    def _pause(vault_dir: Path) -> None:
        marker = budget_marker_path(vault_dir)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("{}", encoding="utf-8")
        raise SystemExit(1)

    vault = _vault(tmp_path)
    _record_cycles(monkeypatch, side_effect=_pause)

    rc = _ask(vault, "--escalate")

    assert rc == 1
    assert len(_answers(vault)) == 1, "a paused run must not be followed by a re-ask"
    assert "paused" in caplog.text and "BUDGET_PAUSED" in caplog.text


def test_the_lifetime_dollar_ceiling_refuses_the_escalation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Recorded spend at `pipeline.budget_usd` means no new cycle starts."""
    vault = _vault(tmp_path)  # budget_usd: 10.0
    calls = vault / "_pipeline" / "cycles" / "cycle-001" / "agent-calls"
    calls.mkdir(parents=True)
    (calls / "scout.json").write_text(json.dumps({"cost_usd": 10.0}))
    cycles = _record_cycles(monkeypatch)

    rc = _ask(vault, "--escalate")

    assert rc == 2
    assert cycles == []
    assert len(_answers(vault)) == 1
    assert "pipeline.budget_usd" in capsys.readouterr().err


@pytest.mark.parametrize("escalate", [True, False])
def test_a_vault_without_a_stages_ask_block_is_refused_before_any_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    escalate: bool,
) -> None:
    """Without the block the headless ask inherits default_executor — on the
    shipped claude profile, bypassPermissions — so a vault that refreshed its
    ask.md but not its settings would dispatch with full permissions."""
    vault = _vault(tmp_path)
    _edit_settings(vault, lambda s: s["stages"].pop("ask"))
    cycles = _record_cycles(monkeypatch)

    rc = _ask(vault, *(["--escalate"] if escalate else []))

    assert rc == 2
    assert cycles == []
    assert _answers(vault) == []
    err = capsys.readouterr().err
    assert "stages.ask" in err and "CHANGELOG" in err


@pytest.mark.parametrize(
    "budget",
    [pytest.param(0, id="zero"), pytest.param(None, id="unset")],
)
def test_a_zero_or_unset_budget_usd_means_no_lifetime_pre_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, budget: int | None
) -> None:
    """Spec 061: a zero or absent `pipeline.budget_usd` is UNLIMITED."""
    vault = _vault(tmp_path)

    def _set(settings: dict) -> None:
        if budget is None:
            settings["pipeline"].pop("budget_usd", None)
        else:
            settings["pipeline"]["budget_usd"] = budget

    _edit_settings(vault, _set)
    calls = vault / "_pipeline" / "cycles" / "cycle-001" / "agent-calls"
    calls.mkdir(parents=True)
    (calls / "scout.json").write_text(json.dumps({"cost_usd": 1000.0}))
    cycles = _record_cycles(monkeypatch)

    rc = _ask(vault, "--escalate")

    assert rc == 0
    assert len(cycles) == 1, "no lifetime ceiling means the cycle must start"


def test_a_missing_vault_is_named_in_the_error(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    missing = tmp_path / "no-such-vault"

    rc = main(["ask", "--vault", str(missing), _QUESTION])

    assert rc == 2
    err = capsys.readouterr().err
    assert str(missing) in err and "not found" in err


@pytest.mark.e2e
@pytest.mark.parametrize(
    "max_cycles",
    [
        pytest.param(5, id="cycle-continues"),
        # Cycle 1 of 1 always meets Condition A, so the runner returns 1.
        pytest.param(1, id="last-allowed-cycle-terminates"),
    ],
)
def test_an_escalated_gap_produces_a_note_and_a_re_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, max_cycles: int
) -> None:
    """The whole path: gap line -> real cycle (fake agent) -> note -> re-answer."""
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    vault = _vault(
        tmp_path, num_categories=1, num_targets_per_category=2, max_cycles=max_cycles
    )
    assert _notes(vault) == []

    rc = _ask(vault, "--escalate")

    assert rc == 0
    assert _notes(vault), "the escalated cycle wrote no note"
    first, second = _answers(vault)
    assert GAP_LINE_PREFIX in first
    assert GAP_LINE_PREFIX not in second
    assert "data_vault/" in second, "the re-answer must cite the new note"
    # Spec 073: the discovered topic lands in the managed region, nowhere else.
    from research_framework.pipeline.spec_append import BEGIN_MARKER

    spec_text = (vault / "research.spec.md").read_text(encoding="utf-8")
    assert BEGIN_MARKER in spec_text
    assert _QUESTION in spec_text
