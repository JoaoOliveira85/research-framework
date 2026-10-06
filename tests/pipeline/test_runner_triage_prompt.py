"""Issue #240 — the triage pause must name the artifact it is talking about.

`run_full` ended by telling the operator to "Open the radar, approve/defer
queue items". A `pipeline` run never writes a Topic Radar — that is a
cycle-orchestrator artifact, and `_STAGE_PROMPT_SOURCES`' own comment steers
the research stage away from it. The real queue is `scout-report.json`'s
`topics_found.new`, which `resume` researches in full, unconditionally: on
reference-vault that was 107 topics in one single-shot pass.

The message can only be made honest here, not a gate — a real approve/defer
protocol changes the contract across three stages and wants a spec. So the
pause names the file, names the list, says what happens to it, and says what
resuming means today.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from research_framework.pipeline.runner import run_full


def _vault_with_queue(tmp_path: Path, topics: list[str]) -> Path:
    vault = tmp_path / "vault"
    (vault / "_pipeline").mkdir(parents=True)
    (vault / "_pipeline" / "scout-report.json").write_text(
        json.dumps({"topics_found": {"new": [{"title": t} for t in topics]}}),
        encoding="utf-8",
    )
    return vault


def _pause_message(vault: Path, caplog: pytest.LogCaptureFixture) -> str:
    with (
        patch("research_framework.pipeline.runner._drive_collect", return_value=0),
        patch("research_framework.pipeline.runner._drive_extract", return_value=0),
        patch("research_framework.pipeline.runner._drive_scout", return_value=0),
        caplog.at_level(logging.INFO),
    ):
        run_full(vault, quiet=False)
    return "\n".join(r.getMessage() for r in caplog.records)


def test_pause_names_the_real_triage_artifact(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    vault = _vault_with_queue(tmp_path, ["Kafka rebalance protocol", "Raft"])
    message = _pause_message(vault, caplog)

    assert "radar" not in message.lower(), (
        "a pipeline run never writes a Topic Radar; naming one sends the "
        "operator looking for a file that does not exist"
    )
    assert "_pipeline/scout-report.json" in message
    assert "topics_found.new" in message
    assert "research-framework pipeline" in message and "resume" in message


def test_pause_reports_the_size_of_the_queue_it_will_research(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """107 topics in one pass is the defect; the operator must see the number."""
    vault = _vault_with_queue(tmp_path, [f"topic {n}" for n in range(107)])
    assert "107" in _pause_message(vault, caplog)


def test_pause_survives_a_missing_or_unreadable_scout_report(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A failed scout must still leave a usable instruction, not a traceback."""
    vault = tmp_path / "vault"
    (vault / "_pipeline").mkdir(parents=True)
    (vault / "_pipeline" / "scout-report.json").write_text(
        "{not json", encoding="utf-8"
    )

    message = _pause_message(vault, caplog)
    assert "_pipeline/scout-report.json" in message
    assert "radar" not in message.lower()


def test_the_pipeline_agent_definition_points_at_the_same_artifact() -> None:
    """The vault-facing `/pipeline` command carried the same misdirection."""
    import research_framework

    template = (
        Path(research_framework.__file__).parent / "agents" / "pipeline.md.j2"
    ).read_text(encoding="utf-8")

    scout_section = template.split("### `/pipeline scout`", 1)[1].split("###", 1)[0]
    assert "topics_found.new" in scout_section
    assert "review the Topic Radar" not in scout_section
