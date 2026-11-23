"""Update work needs the vault's git history; without it none is planned (the
share falls to new topics) and the entries wait (spec 087, Fix 1)."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from research_framework.pipeline import backlog, currency, research_plan
from research_framework.pipeline.orchestrator import run_single_cycle
from research_framework.spec.schema import NoteTypeConfig, SpecConfig
from tests._helpers.vault_factory import build_minimal_vault, commit_vault

FOLDER = "data_vault/01 - Concepts"


def _vault(
    tmp_path: Path, stems: tuple[str, ...] = ("alpha", "beta")
) -> tuple[Path, SpecConfig]:
    vault = build_minimal_vault(
        tmp_path,
        num_categories=1,
        num_targets_per_category=20,
        max_cycles=1,
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
    category = spec.coverage_targets.categories[0].name
    (vault / FOLDER).mkdir(parents=True, exist_ok=True)
    for stem in stems:
        _write(vault, stem, category)
    return vault, spec


def _write(vault: Path, stem: str, category: str) -> None:
    (vault / FOLDER / f"{stem}.md").write_text(
        "---\ntype: concept\nsummary: s\nsource_urls: [https://example.org/s]\n"
        f"coverage_category: {category}\nas_of: 2020-01-01\ncurrency: current\n---\n\n"
        + "body " * 40
        + "\n",
        encoding="utf-8",
    )


def _queue(vault: Path, *stems: str) -> None:
    assert backlog.update(
        vault,
        "review",
        lambda tx: [
            tx.observe_update(s, "review_due", as_of="2020-01-01") for s in stems
        ],
    )


def _plan(vault: Path, spec: SpecConfig) -> research_plan.ResearchPlan:
    return research_plan.generate_plan(vault, spec, 1)


def _prompts(vault: Path) -> list[str]:
    return [
        p.read_text(encoding="utf-8")
        for p in sorted(
            (vault / "_pipeline" / "cycles").glob("cycle-001-batch-*-dfs.md")
        )
    ]


def test_a_vault_without_git_plans_no_update_batches_and_says_why(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    vault, spec = _vault(tmp_path)
    shutil.rmtree(vault / ".git")  # the scaffold's repository: a plain directory now
    supported, why = currency.updates_supported(vault)
    assert supported is False and "not a git repository" in why

    with caplog.at_level(logging.WARNING, logger="research_framework"):
        run_single_cycle(vault, cycle_num=1, budget_cap=10.0, max_cycles=1, spec=spec)

    plan = (vault / "_pipeline" / "research-plan.md").read_text(encoding="utf-8")
    assert "Update queue" not in plan and "update_quota" not in plan
    assert not [p for p in _prompts(vault) if "\n## Update topics (JSON)\n" in p]
    assert [p for p in _prompts(vault) if "\n## Batch topics (JSON)\n" in p]
    # the share fell to new topics, and the sweep still queued both notes
    assert sorted(r.stem for r in backlog.update_topics(vault)) == ["alpha", "beta"]
    warned = [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.WARNING
        and "no update work is planned" in r.getMessage()
    ]
    assert len(warned) == 1  # one per cycle
    assert "update batches need the vault's git history" in warned[0]
    assert "enable vault_commit" in warned[0]


def test_commit_disabled_is_treated_the_same(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    vault, spec = _vault(tmp_path)
    commit_vault(vault)  # there IS history ...
    assert currency.updates_supported(vault) == (True, "")
    _queue(vault, "alpha", "beta")
    assert _plan(vault, spec).update_quota > 0

    settings = vault / "settings.yaml"  # ... but nothing will keep it current
    settings.write_text(settings.read_text() + "vault_commit:\n  enabled: false\n")

    supported, why = currency.updates_supported(vault)
    assert supported is False and "vault_commit.enabled is false" in why
    plan = _plan(vault, spec)
    assert plan.update_queue == [] and plan.update_quota == 0
    assert [r.stem for r in backlog.update_topics(vault)] == ["alpha", "beta"]

    # a repository with no commit yet is not usable history either
    empty, _ = _vault(tmp_path / "empty")
    shutil.rmtree(empty / ".git")
    subprocess.run(["git", "init", "-q"], cwd=empty, check=True)
    assert "no commits" in currency.updates_supported(empty)[1]


def test_an_uncommitted_note_is_not_dispatched_for_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, spec = _vault(tmp_path, ("committed",))
    commit_vault(vault)
    _write(vault, "fresh", spec.coverage_targets.categories[0].name)  # this cycle's
    _queue(vault, "committed", "fresh")

    plan = _plan(vault, spec)

    assert [u.stem for u in plan.update_queue] == ["committed"]
    # skipped, not failed: still open, untouched, and picked up once committed
    entries: dict[str, Any] = {
        e["stem"]: e
        for e in json.loads(
            (vault / "_pipeline/state/research-backlog.json").read_text("utf-8")
        )["entries"]
        if e["origin"] == "update"
    }
    assert entries["fresh"]["status"] == "open"
    assert "outcome" not in entries["fresh"]
    commit_vault(vault)
    assert [u.stem for u in _plan(vault, spec).update_queue] == ["committed", "fresh"]
