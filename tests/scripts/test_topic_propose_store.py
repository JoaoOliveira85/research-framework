"""Spec 084 T005: the propose stage records accepted proposals in the store."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research_framework.pipeline import backlog
from research_framework.pipeline import state_layout as L

from .test_topic_propose import _seed_vault, _stub_agent, topic_propose  # noqa: F401


def _entries(vault: Path) -> list[dict[str, Any]]:
    data = json.loads(L.research_backlog_path(vault).read_text(encoding="utf-8"))
    return data["entries"]


def _proposal(title: str, **extra: Any) -> dict[str, Any]:
    return {
        "title": title,
        "relation_type": "variant",
        "parent_note": "data_vault/concept/Oven.md",
        "justification": f"Why {title} matters.",
        "degree": 1,
        **extra,
    }


def test_an_accepted_proposal_is_an_open_proposal_entry(
    tmp_path: Path,
    topic_propose,  # noqa: F811
) -> None:
    vault = _seed_vault(tmp_path, out_of_scope=["thermodynamics"])
    backlog.create_empty(vault)

    result = topic_propose.propose(
        vault, 1, agent_caller=_stub_agent([_proposal("Gas Oven")])
    )

    assert result["accepted"] == 1
    (entry,) = _entries(vault)
    assert entry["id"] == "topic:gas oven"
    assert entry["origin"] == "proposal"
    assert entry["status"] == "open"
    assert entry["relation"] == "variant"
    assert entry["parent_note"] == "Oven"
    assert entry["detail"] == "Why Gas Oven matters."
    assert entry["first_seen_cycle"] == 1
    view = backlog.view_path(vault).read_text(encoding="utf-8")
    assert "**Gas Oven**" in view
    assert "[[Oven]]" in view


def test_dedupe_sees_resolved_and_dropped_titles(
    tmp_path: Path,
    topic_propose,  # noqa: F811
) -> None:
    vault = _seed_vault(tmp_path, out_of_scope=["thermodynamics"])
    backlog.create_empty(vault)
    store = L.research_backlog_path(vault)
    data = json.loads(store.read_text(encoding="utf-8"))
    for title, status in (("Gas Oven", "resolved"), ("Air Fryer", "dropped")):
        data["entries"].append(
            {
                "title": title,
                "origin": "operator",
                "status": status,
                "status_by": "operator",
                "status_written": status,
            }
        )
    store.write_text(json.dumps(data), encoding="utf-8")

    result = topic_propose.propose(
        vault,
        1,
        agent_caller=_stub_agent(
            [_proposal("gas   OVEN"), _proposal("Air Fryer"), _proposal("Steam Oven")]
        ),
    )

    assert result["accepted"] == 1
    manifest = json.loads(
        (vault / "_pipeline" / "cycles" / "cycle-001-propose.json").read_text("utf-8")
    )
    assert [p["title"] for p in manifest["proposals"]] == ["Steam Oven"]
    assert {r["rejected_by"] for r in manifest["rejected"]} == {"dedupe_backlog"}
    assert len(manifest["rejected"]) == 2
    statuses = {e["title"]: e["status"] for e in _entries(vault)}
    assert statuses["Gas Oven"] == "resolved"
    assert statuses["Air Fryer"] == "dropped"
