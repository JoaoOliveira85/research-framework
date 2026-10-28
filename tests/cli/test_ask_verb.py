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
    return vault


def _record_cycles(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def _fake(vault_dir: Path, cycle_num: int, *args: Any, **kwargs: Any) -> int:
        calls.append({"vault_dir": vault_dir, "cycle_num": cycle_num, **kwargs})
        return 0

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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    vault = _vault(tmp_path)
    cycles = _record_cycles(monkeypatch)

    rc = _ask(vault)

    assert rc == 0
    assert cycles == [], "ask without --escalate must never start a run"
    answers = _answers(vault)
    assert len(answers) == 1 and GAP_LINE_PREFIX in answers[0]
    assert "--escalate" in capsys.readouterr().err


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


@pytest.mark.e2e
def test_an_escalated_gap_produces_a_note_and_a_re_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole path: gap line -> real cycle (fake agent) -> note -> re-answer."""
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    vault = _vault(tmp_path, num_categories=1, num_targets_per_category=2)
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
