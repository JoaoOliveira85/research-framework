"""Spec 083 T003-T006 — every state writer lands under ``_pipeline/state/``.

Each test drives a writer through its own public function and asserts the file
is at the :mod:`state_layout` path and not at the pre-083 path (FR-002, FR-004).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from research_framework.generator.scaffold import scaffold
from research_framework.pipeline import state_layout as L
from research_framework.pipeline.budget_guard import (
    ApprovalDecision,
    record_approval_decision,
)
from research_framework.pipeline.coverage import load_targets, save_targets
from research_framework.pipeline.source_bridge.schema_gen import run as schema_gen_run
from research_framework.spec.parser import parse
from research_framework.spec.schema import CoverageCategory, CoverageTargets


def test_scaffold_seeds_coverage_targets_under_state(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    scaffold(parse(sample_spec_path), vault)
    assert L.coverage_targets_path(vault).is_file()
    assert not (vault / "_pipeline" / "coverage-targets.json").exists()


def test_save_and_load_targets_round_trip_at_the_state_path(tmp_path: Path) -> None:
    targets = CoverageTargets(
        categories=[CoverageCategory(name="c", note_type="x", target_count=3)]
    )
    save_targets(tmp_path, targets)
    assert L.coverage_targets_path(tmp_path).is_file()
    assert not (tmp_path / "_pipeline" / "coverage-targets.json").exists()
    assert load_targets(tmp_path).categories[0].name == "c"


_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _write_propose_rejects(vault: Path) -> Path:
    (vault / "_pipeline").mkdir(parents=True, exist_ok=True)
    rejected = [{"rejected_by": "scope_check", "title": "T", "reason": "off scope"}]
    _load_script("topic_propose")._append_persistent_rejects(
        vault, 1, "2026-01-01T00:00:00Z", rejected
    )
    return L.propose_rejects_path(vault)


def _write_approval_decision(vault: Path) -> Path:
    decision = ApprovalDecision("scout", 1, True, "headless")
    assert record_approval_decision(vault, decision)
    return L.approval_decisions_path(vault)


def _write_archive_snapshots(vault: Path) -> Path:
    note = vault / "data_vault" / "Topics" / "n.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        '---\ntitle: n\ntype: concept\nsource_urls:\n  - url: "https://e.com/x"\n---\n',
        encoding="utf-8",
    )
    _load_script("vault_health").run_archive_snapshot_pass(
        vault,
        apply=True,
        offline=False,
        post_fn=lambda url: ("archived", "https://web.archive.org/x", None),
    )
    return L.archive_snapshots_path(vault)


def _write_facts_schema(vault: Path) -> Path:
    spec = vault / "research.spec.md"
    spec.write_text("spec\n", encoding="utf-8")
    schema_gen_run(vault, "code", spec, agent_response={"type": "object"})
    return L.facts_schema_path(vault, "code")


_WRITERS: dict[str, tuple[Callable[[Path], Path], str]] = {
    "propose_rejects": (_write_propose_rejects, "_pipeline/propose-rejects.md"),
    "approval_decisions": (
        _write_approval_decision,
        "_pipeline/approval-decisions.json",
    ),
    "archive_snapshots": (
        _write_archive_snapshots,
        "_pipeline/archive-snapshots.json",
    ),
    "facts_schema": (
        _write_facts_schema,
        "_pipeline/sources/code/facts-schema.json",
    ),
}


@pytest.mark.parametrize("writer", sorted(_WRITERS))
def test_each_small_state_writer_writes_under_state(
    writer: str, tmp_path: Path
) -> None:
    write, legacy_rel = _WRITERS[writer]
    written = write(tmp_path)
    assert written.is_file()
    assert written.relative_to(tmp_path).as_posix().startswith("_pipeline/state/")
    assert not (tmp_path / legacy_rel).exists()


def test_transient_schema_files_stay_out_of_state(tmp_path: Path) -> None:
    spec = tmp_path / "research.spec.md"
    spec.write_text("version one\n", encoding="utf-8")
    schema = L.facts_schema_path(tmp_path, "code")
    schema.parent.mkdir(parents=True)
    schema.write_text(json.dumps({"manually_edited": True}) + "\n", encoding="utf-8")
    cache = tmp_path / "_pipeline" / "sources" / "code"
    cache.mkdir(parents=True)
    (cache / ".schema-gen-hash").write_text(
        json.dumps({"spec_hash": "stale"}) + "\n", encoding="utf-8"
    )
    schema_gen_run(
        tmp_path,
        "code",
        spec,
        agent_response={"type": "object"},
        force_stale_schema=True,
    )
    assert (cache / "facts-schema.regenerated.json").is_file()
    assert (cache / "facts-schema.drift.md").is_file()
    assert sorted(p.name for p in schema.parent.iterdir()) == [schema.name]


def test_seed_creates_the_database_under_state(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    from research_framework.pipeline.source_manager import seed

    seed(tmp_path, parse(sample_spec_path))
    assert L.sources_db_path(tmp_path).is_file()
    assert not (tmp_path / "_pipeline" / "sources.db").exists()


def test_an_orphan_note_is_quarantined_under_state(tmp_path: Path) -> None:
    from research_framework.pipeline.orchestrator import (
        _reconcile_orphan_notes_at_cycle_start,
    )

    note = tmp_path / "data_vault" / "01 - Concepts" / "Orphan.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "---\ntitle: Orphan\nlifecycle:\n  created_at_cycle: 2\n---\nBody.\n",
        encoding="utf-8",
    )
    _reconcile_orphan_notes_at_cycle_start(tmp_path, 2)
    assert not note.exists()
    assert (L.quarantine_dir(tmp_path) / "Orphan.md").is_file()
    assert not (tmp_path / "_pipeline" / "quarantine").exists()
