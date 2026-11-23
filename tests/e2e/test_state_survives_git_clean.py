"""Spec 083 T015 (acceptance US1, US2): state survives ``git clean -fdx``.

Two fake-agent cycles on a scaffolded vault, a commit, then two copies: one is
left alone (the twin), one is ``git clean -fdx``'d and has its scripts
re-installed. Everything a later run depends on and used to recompute from the
ignored ``_pipeline/cycles/`` tree must read the same on both.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from research_framework.cli.research_resume import _resolve_resume_cycle
from research_framework.generator.scripts import copy_scripts
from research_framework.pipeline import (
    cycle_ledger,
    source_manager,
    state_layout,
    vault_commit,
)
from research_framework.pipeline.orchestrator import (
    _cumulative_sidecar_cost,
    _persistent_reject_titles,
    run_single_cycle,
)
from research_framework.spec.schema import SpecConfig
from tests._helpers.vault_factory import build_minimal_vault

pytestmark = pytest.mark.e2e


def _git(vault: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(vault), *args], check=True, capture_output=True, text=True
    ).stdout


def _two_cycle_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    vault = build_minimal_vault(
        tmp_path, num_categories=2, num_targets_per_category=2, max_cycles=3
    )
    spec = SpecConfig.from_dict(
        json.loads((vault / "_pipeline" / "spec-parse.json").read_text("utf-8"))
    )
    for n in (1, 2):
        rc = run_single_cycle(
            vault, cycle_num=n, budget_cap=10.0, max_cycles=3, spec=spec
        )
        assert rc in (0, 1)
    # The fake agent records a cost of 0.0. Give each sidecar a real spend and
    # close the cycles again, as the orchestrator does after a paid cycle.
    for n in (1, 2):
        for sidecar in sorted(
            (vault / "_pipeline" / "cycles" / f"cycle-{n:03d}" / "agent-calls").glob(
                "*.json"
            )
        ):
            doc = json.loads(sidecar.read_text("utf-8"))
            doc["cost_usd"] = 0.25 * n
            sidecar.write_text(json.dumps(doc), encoding="utf-8")
        cycle_ledger.close_cycle(vault, n)
    _git(vault, "config", "user.email", "t@e.com")
    _git(vault, "config", "user.name", "T")
    return vault


def _commit(vault: Path) -> None:
    result = vault_commit.commit_command_output(vault, command="test", summary="state")
    assert result.ok, result.error


def _observed(vault: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    from research_framework.cli.regrade import run_regrade

    capsys.readouterr()  # drop what the cycles printed
    run_regrade(vault, dry_run=True, json_output=True)
    regrade = json.loads(capsys.readouterr().out)
    regrade.pop("vault")  # the two copies live at different paths
    return {
        "resume_anchor": _resolve_resume_cycle(
            argparse.Namespace(output=vault, vault_dir=vault, cycle=None)
        ),
        "lifetime_spend": _cumulative_sidecar_cost(vault, up_to=2),
        "scout_exclusions": _persistent_reject_titles(vault),
        "backlog": (vault / "_pipeline" / "research-backlog.md").read_bytes(),
        "sources": sorted(
            (s["name"], s["url"]) for s in source_manager.active_sources(vault)
        ),
        "regrade": regrade,
    }


def test_a_cleaned_vault_continues_like_its_twin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = _two_cycle_vault(tmp_path / "origin", monkeypatch)
    state = state_layout.state_dir(vault)
    # What a later run reads, written the way the verbs write it.
    (state / "propose-rejects.md").write_text(
        "- **Rejected topic** — cycle 002 (2026-01-02): out of scope\n",
        encoding="utf-8",
    )
    quarantine = state_layout.quarantine_dir(vault)
    quarantine.mkdir(parents=True, exist_ok=True)
    (quarantine / "orphan.md").write_text(
        "---\ntitle: Orphan\n---\nbody\n", encoding="utf-8"
    )
    source_manager.append_discovered(
        vault,
        [
            {
                "name": "Found Site",
                "type": "web",
                "role": "intent",
                "url": "https://x.test",
            }
        ],
    )
    _commit(vault)
    assert _git(vault, "status", "--porcelain", "--", "_pipeline/state").strip() == ""

    twin = tmp_path / "twin"
    cleaned = tmp_path / "cleaned"
    shutil.copytree(vault, twin, symlinks=True)
    shutil.copytree(vault, cleaned, symlinks=True)
    _git(cleaned, "clean", "-fdx", "-q")
    assert not (cleaned / "_pipeline" / "cycles").exists()  # the scratch is gone
    copy_scripts(cleaned)  # the reinstall

    expected = _observed(twin, capsys)
    actual = _observed(cleaned, capsys)

    assert expected["resume_anchor"] == 3
    assert expected["lifetime_spend"] > 0
    assert expected["scout_exclusions"] == ["Rejected topic"]
    assert ("Found Site", "https://x.test") in expected["sources"]
    assert expected["regrade"], "the twin's re-grade saw nothing to compare"
    assert actual == expected


def test_only_state_is_tracked_under_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    vault = build_minimal_vault(
        tmp_path, num_categories=2, num_targets_per_category=2, max_cycles=3
    )
    spec = SpecConfig.from_dict(
        json.loads((vault / "_pipeline" / "spec-parse.json").read_text("utf-8"))
    )
    assert run_single_cycle(
        vault, cycle_num=1, budget_cap=10.0, max_cycles=3, spec=spec
    ) in (0, 1)
    _git(vault, "config", "user.email", "t@e.com")
    _git(vault, "config", "user.name", "T")
    _commit(vault)

    tracked = set(_git(vault, "ls-files", "_pipeline/").split())
    on_disk = {
        p.relative_to(vault).as_posix()
        for p in (vault / "_pipeline").rglob("*")
        if p.is_file()
    }
    state_prefix = f"{state_layout.STATE_DIR}/"
    sidecars = {t for t in on_disk if t.endswith(("-wal", "-shm"))}
    # Tracked: everything under state/ (but not SQLite sidecars) plus the one
    # transitional exception, the Markdown backlog (FR-019, until spec 084).
    expected_tracked = {
        f for f in on_disk if f.startswith(state_prefix) and f not in sidecars
    } | {"_pipeline/research-backlog.md"}
    assert tracked == expected_tracked
    # Every other _pipeline/ file is ignored, none is merely untracked.
    ignored = set(
        _git(
            vault,
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "_pipeline/",
        ).split()
    )
    assert on_disk - tracked == ignored
    assert (
        _git(vault, "ls-files", "--others", "--exclude-standard", "_pipeline/").strip()
        == ""
    )
    assert "_pipeline/state/coverage-targets.json" in tracked
    assert "_pipeline/cycles" not in " ".join(tracked)

    # The scaffolded .gitignore names no file under _pipeline/ (one directory
    # re-include, two sidecar patterns, and the transitional backlog line).
    lines = [
        ln.strip()
        for ln in (vault / ".gitignore").read_text().splitlines()
        if "_pipeline" in ln and not ln.lstrip().startswith("#")
    ]
    assert sorted(lines) == sorted(
        [
            "!_pipeline/",
            "_pipeline/*",
            "!_pipeline/state/",
            "_pipeline/state/*.db-wal",
            "_pipeline/state/*.db-shm",
            "!_pipeline/research-backlog.md",
        ]
    )
