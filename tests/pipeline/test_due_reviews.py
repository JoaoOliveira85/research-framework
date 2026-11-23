"""Tier 3: the due-review sweep (spec 087 FR-010, T004)."""

from __future__ import annotations

import json
import socket
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from research_framework.pipeline import backlog, currency, research_plan, state_layout
from research_framework.pipeline.coverage import load_targets
from research_framework.pipeline.orchestrator import run_single_cycle
from research_framework.spec.schema import NoteTypeConfig, SpecConfig
from tests._helpers.cycle_runner_stub import no_op_cycle_runner
from tests._helpers.vault_factory import build_minimal_vault

TODAY = date(2026, 11, 23)


def _spec(**intervals: int | None) -> SpecConfig:
    return SpecConfig.from_dict(
        {
            "name": "due",
            "owner": "tests",
            "note_types": [
                {
                    "name": name,
                    "folder": f"{i:02d} - {name}",
                    **({} if days is None else {"review_after_days": days}),
                }
                for i, (name, days) in enumerate(intervals.items(), 1)
            ],
        }
    )


def _note(
    vault: Path, stem: str, *, ntype: str = "concept", **frontmatter: Any
) -> Path:
    path = vault / "data_vault" / "01 - Concepts" / f"{stem}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"type: {ntype}", "summary: s"]
    lines += [f"{k}: {v}" for k, v in frontmatter.items()]
    path.write_text("---\n" + "\n".join(lines) + "\n---\n\nBody.\n", encoding="utf-8")
    return path


def _update_entries(vault: Path) -> list[dict[str, Any]]:
    path = state_layout.research_backlog_path(vault)
    if not path.exists():
        return []
    entries = json.loads(path.read_text(encoding="utf-8"))["entries"]
    return [e for e in entries if e["origin"] == "update"]


def test_a_note_past_its_interval_gets_one_review_due_entry(tmp_path: Path) -> None:
    _note(tmp_path, "old", as_of="2026-01-01", currency="current")
    _note(tmp_path, "fresh", as_of="2026-11-01", currency="current")
    spec = _spec(concept=90)

    assert currency.queue_due_reviews(tmp_path, spec, TODAY) == 1
    assert currency.queue_due_reviews(tmp_path, spec, TODAY) == 1  # second cycle

    entries = _update_entries(tmp_path)
    assert [e["id"] for e in entries] == ["update:old"]
    assert entries[0]["reason"] == "review_due"
    assert entries[0]["as_of"] == "2026-01-01"
    assert entries[0]["status"] == "open"
    assert entries[0]["status_by"] == "review"
    assert [r.stem for r in backlog.update_topics(tmp_path)] == ["old"]


def test_superseded_retracted_unstamped_and_interval_less_notes_are_not_queued(
    tmp_path: Path,
) -> None:
    _note(tmp_path, "superseded", as_of="2020-01-01", currency="superseded")
    _note(tmp_path, "retracted", as_of="2020-01-01", currency="retracted")
    _note(tmp_path, "unstamped")
    _note(tmp_path, "malformed", as_of="not-a-date")
    _note(tmp_path, "other-type", ntype="source", as_of="2020-01-01")
    _note(tmp_path, "alias", as_of="2020-01-01", note_type="alias")
    _note(tmp_path, "exempt", as_of="2020-01-01", verifier_status="exempt")
    _note(tmp_path, "due-one", as_of="2020-01-01", currency="declining")
    (tmp_path / "data_vault" / "_index.md").write_text("no frontmatter\n")
    spec = _spec(concept=30, source=None)

    assert currency.queue_due_reviews(tmp_path, spec, TODAY) == 1
    assert [e["id"] for e in _update_entries(tmp_path)] == ["update:due-one"]

    # nothing declares an interval: nothing queued, no store created
    bare = tmp_path / "bare"
    _note(bare, "old", as_of="2020-01-01")
    assert currency.queue_due_reviews(bare, _spec(concept=None), TODAY) == 0
    assert not state_layout.research_backlog_path(bare).exists()


def test_the_sweep_calls_no_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = build_minimal_vault(tmp_path)  # installs the fake agent shim
    _note(vault, "old", as_of="2020-01-01")
    spec = _spec(concept=30)

    def forbidden(*_a: object, **_k: object) -> None:
        raise AssertionError("the due sweep must not dispatch or touch the network")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)

    assert currency.queue_due_reviews(vault, spec, TODAY) == 1


def test_the_planner_sees_counts_recomputed_before_it_plans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = build_minimal_vault(
        tmp_path,
        num_categories=1,
        spec_overrides={
            "note_types": [
                NoteTypeConfig(
                    name="concept",
                    description="d",
                    folder="01 - Concepts",
                    min_word_count=30,
                    review_after_days=30,
                )
            ]
        },
    )
    spec = SpecConfig.from_dict(
        json.loads((vault / "_pipeline" / "spec-parse.json").read_text("utf-8"))
    )
    category = load_targets(vault).categories[0]
    for stem in ("a", "b"):
        _note(
            vault,
            stem,
            coverage_category=category.name,
            as_of="2020-01-01",
            currency="current",
        )
    assert load_targets(vault).categories[0].met_count == 0  # stale on disk

    seen: dict[str, Any] = {}
    real = research_plan.generate_plan

    def spy(vault_dir: Path, spec_: SpecConfig, cycle: int) -> Any:
        seen["met"] = load_targets(vault_dir).categories[0].met_count
        seen["queued"] = [e["id"] for e in _update_entries(vault_dir)]
        return real(vault_dir, spec_, cycle)

    monkeypatch.setattr(research_plan, "generate_plan", spy)

    run_single_cycle(
        vault,
        cycle_num=1,
        budget_cap=10.0,
        max_cycles=2,
        spec=spec,
        cycle_runner=no_op_cycle_runner(0),
    )

    assert seen["met"] == 2
    assert seen["queued"] == ["update:a", "update:b"]


def test_a_failing_sweep_does_not_stop_the_cycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    vault = build_minimal_vault(tmp_path)
    spec = SpecConfig.from_dict(
        json.loads((vault / "_pipeline" / "spec-parse.json").read_text("utf-8"))
    )

    def boom(*_a: object, **_k: object) -> int:
        raise RuntimeError("sweep exploded")

    monkeypatch.setattr(currency, "queue_due_reviews", boom)

    run_single_cycle(
        vault,
        cycle_num=1,
        budget_cap=10.0,
        max_cycles=2,
        spec=spec,
        cycle_runner=no_op_cycle_runner(0),
    )

    # the no-op runner yields nothing, so the cycle may fail CG-001; what
    # matters is that the plan was still written after the sweep failed
    assert (vault / "_pipeline" / "research-plan.md").is_file()
    assert "sweep exploded" in caplog.text
