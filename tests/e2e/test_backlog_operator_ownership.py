"""Spec 084 acceptance 4, end to end.

An operator-added entry (with a field the framework does not know) and a
harvest entry an operator set to ``dropped`` survive, byte-equal in the fields
the operator set, a real cycle (fake agent, its own harvest step), a second
harvest, a propose run, a quarantine sweep and a ``re-grade``. The dropped
entry is not reopened when the harvest sees its topic again.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from research_framework.cli.regrade import run_regrade
from research_framework.pipeline import backlog
from research_framework.pipeline import state_layout as L
from research_framework.pipeline.cycle_runner import run_cycle_steps
from research_framework.pipeline.orchestrator import _quarantine_rejected_notes
from tests._helpers.vault_factory import build_minimal_vault
from tests.scripts.test_topic_propose import (
    _stub_agent,
    _write_settings,
    _write_spec,
    topic_propose,  # noqa: F401 - fixture
)

pytestmark = pytest.mark.e2e

REPO = Path(__file__).resolve().parents[2]

OPERATOR = {
    "id": "topic:operator topic",
    "title": "Operator Topic",
    "origin": "operator",
    "status": "open",
    "status_by": "operator",
    "status_written": "open",
    "detail": "Look at the vendor's changelog first.",
    "owner": "me",
    "labels": ["keep", "q3"],
}
DROPPED = {
    "id": "topic:dropped topic",
    "title": "Dropped Topic",
    "origin": "harvest",
    "status": "dropped",
    "status_by": "operator",
    "status_written": "dropped",
    "citation_count": 1,
    "reviewer": "me",
}


def _entries(vault: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(L.research_backlog_path(vault).read_text(encoding="utf-8"))
    return {e["id"]: e for e in data["entries"]}


def _assert_operator_fields_intact(vault: Path, stage: str) -> None:
    entries = _entries(vault)
    for original in (OPERATOR, DROPPED):
        kept = entries[original["id"]]
        for key, value in original.items():
            assert kept[key] == value, f"{stage}: {original['id']}.{key} changed"
    assert entries[DROPPED["id"]]["status"] == "dropped", stage


def _run_harvest(vault: Path, cycle: int) -> None:
    env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
    done = subprocess.run(
        [
            sys.executable,
            str(vault / "scripts" / "topic_harvest.py"),
            str(vault),
            str(cycle),
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert done.returncode == 0, done.stderr


def test_operator_fields_survive_a_cycle_a_sweep_and_a_regrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    topic_propose,  # noqa: F811
) -> None:
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    vault = build_minimal_vault(
        tmp_path, num_categories=1, num_targets_per_category=3, max_cycles=1
    )
    store = L.research_backlog_path(vault)
    data = json.loads(store.read_text(encoding="utf-8"))
    data["entries"] += [dict(OPERATOR), dict(DROPPED)]
    store.write_text(json.dumps(data), encoding="utf-8")

    # 1. A whole cycle with the fake agent, including its harvest step.
    rc = run_cycle_steps(vault, cycle_num=1, budget_cap=100.0, max_cycles=1)
    assert rc in (0, 1)
    _assert_operator_fields_intact(vault, "cycle")

    # 2. A second harvest that sees both topics again.
    note = vault / "data_vault" / "Cites Both.md"
    note.write_text(
        "See [[Dropped Topic]] and [[Operator Topic]] and [[Brand New Topic]].\n",
        encoding="utf-8",
    )
    cycles = vault / "_pipeline" / "cycles"
    (cycles / "cycle-002-research.json").write_text(
        json.dumps(
            {"cycle": 2, "phase": "research", "notes_created": ["Cites Both.md"]}
        ),
        encoding="utf-8",
    )
    _run_harvest(vault, 2)
    _assert_operator_fields_intact(vault, "harvest")
    entries = _entries(vault)
    assert entries["topic:brand new topic"]["status"] == "open"
    assert entries[DROPPED["id"]]["status"] == "dropped"  # seen again, not reopened

    # 3. A propose run that also suggests the operator's own topic.
    _write_settings(vault)
    _write_spec(vault, ["thermodynamics"])
    proposals = [
        {
            "title": title,
            "relation_type": "variant",
            "parent_note": "data_vault/Cites Both.md",
            "justification": "why",
            "degree": 1,
        }
        for title in ("Operator Topic", "Fresh Tangent")
    ]
    result = topic_propose.propose(vault, 2, agent_caller=_stub_agent(proposals))
    assert result["accepted"] == 1
    _assert_operator_fields_intact(vault, "propose")
    assert "topic:fresh tangent" in _entries(vault)

    # 4. A quarantine sweep, twice.
    rejected = vault / "data_vault" / "Bad Note.md"
    rejected.write_text(
        "---\ntitle: Bad Note\ntype: concept\nverifier_status: rejected\n"
        "verifier_notes: unsupported claim\n---\nBody.\n",
        encoding="utf-8",
    )
    assert _quarantine_rejected_notes(vault) == 1
    assert _quarantine_rejected_notes(vault) == 0
    _assert_operator_fields_intact(vault, "sweep")
    assert _entries(vault)["quarantine:Bad Note"]["status"] == "open"

    # 5. ./vault re-grade reinstates one stem and touches only its entry.
    quarantined = L.quarantine_dir(vault) / "Fastify.md"
    quarantined.write_text(
        "---\ntitle: Fastify\ntype: concept\nverifier_status: rejected\n"
        "verifier_notes:\n  - citation lacks credibility and no source default applies\n"
        "source_urls:\n  - url: https://fastify.dev/\n---\nBody.\n",
        encoding="utf-8",
    )
    assert backlog.observe_quarantine(vault, stem="Fastify", kind="rewrite")
    assert run_regrade(vault, notes=["Fastify.md"]) == 0
    _assert_operator_fields_intact(vault, "regrade")
    after = _entries(vault)
    assert after["quarantine:Fastify"]["status"] == "resolved"
    assert after["quarantine:Bad Note"]["status"] == "open"
