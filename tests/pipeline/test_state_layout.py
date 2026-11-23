"""Spec 083 T001 — the one module that spells a state path (FR-001, FR-002, FR-004)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from research_framework.pipeline import state_layout as L

_SPEC = (
    Path(__file__).resolve().parents[2]
    / "specs"
    / "083-durable-state-layout"
    / "spec.md"
)


def test_every_artefact_resolves_under_the_state_directory(tmp_path: Path) -> None:
    state = tmp_path / "_pipeline" / "state"
    assert L.state_dir(tmp_path) == state
    for artefact in L.STATE_ARTEFACTS:
        assert artefact.new_rel.startswith("_pipeline/state/"), artefact.name
    by_name = {a.name: a for a in L.STATE_ARTEFACTS}
    accessors = {
        "coverage_targets": L.coverage_targets_path(tmp_path),
        "propose_rejects": L.propose_rejects_path(tmp_path),
        "sources_db": L.sources_db_path(tmp_path),
        "quarantine": L.quarantine_dir(tmp_path),
        "archive_snapshots": L.archive_snapshots_path(tmp_path),
        "approval_decisions": L.approval_decisions_path(tmp_path),
        "cycle_ledger": L.cycle_ledger_path(tmp_path),
        "research_backlog": L.research_backlog_path(tmp_path),
    }
    for name, path in accessors.items():
        assert path == tmp_path / by_name[name].new_rel, name
    assert (
        L.facts_schema_path(tmp_path, "rss")
        == state / "sources" / "rss" / "facts-schema.json"
    )


def _spec_table_rows() -> set[tuple[str, str]]:
    """(new path under state/, legacy path under _pipeline/) per FR-002 row."""
    text = _SPEC.read_text(encoding="utf-8")
    table = text.split("| State | New path under `_pipeline/state/` |", 1)[1]
    table = table.split("\n\n", 1)[0]
    rows: set[tuple[str, str]] = set()
    for line in table.splitlines()[2:]:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 3:
            continue
        new = re.search(r"`([^`]+)`", cells[1])
        # A row with no legacy path opens its last cell with a dash.
        legacy = None if cells[2].startswith("—") else re.search(r"`([^`]+)`", cells[2])
        assert new, line
        rows.add((new.group(1), legacy.group(1) if legacy else ""))
    return rows


# Artefacts a later spec adds to the registry; spec 083's FR-002 table cannot
# list them. Each entry names the spec that declares it.
_DECLARED_BY_A_LATER_SPEC = {
    "research-backlog.pre-migration.md": "spec 084 FR-022",
}


def test_registry_is_the_spec_table() -> None:
    registry = {
        (
            a.new_rel.removeprefix("_pipeline/state/"),
            a.legacy_rel.removeprefix("_pipeline/"),
        )
        for a in L.STATE_ARTEFACTS
        if a.new_rel.removeprefix("_pipeline/state/") not in _DECLARED_BY_A_LATER_SPEC
    }
    assert registry == _spec_table_rows()
    archive = next(a for a in L.STATE_ARTEFACTS if a.name == "research_backlog_archive")
    assert (archive.legacy_rel, archive.moved_by_083) == ("", False)
    assert L.research_backlog_archive_path(Path("v")) == Path(
        "v/_pipeline/state/research-backlog.pre-migration.md"
    )
    backlog = next(a for a in L.STATE_ARTEFACTS if a.name == "research_backlog")
    assert backlog.moved_by_083 is False
    assert all(
        a.moved_by_083
        or a.name in {"research_backlog", "research_backlog_archive", "cycle_ledger"}
        for a in L.STATE_ARTEFACTS
    )


def test_legacy_layout_is_detected_from_any_legacy_path_and_an_unconverted_backlog(
    tmp_path: Path,
) -> None:
    from research_framework.pipeline import backlog

    pipeline = tmp_path / "_pipeline"
    pipeline.mkdir()
    # Spec 084: a Markdown backlog while no store exists is unconverted state.
    md = pipeline / "research-backlog.md"
    md.write_text("# backlog\n", encoding="utf-8")
    assert L.is_legacy_layout(tmp_path) is True
    assert L.legacy_paths_present(tmp_path) == [md]
    with pytest.raises(L.LegacyLayoutError) as unconverted:
        L.require_migrated(tmp_path)
    assert "./vault migrate-layout" in str(unconverted.value)
    assert "_pipeline/research-backlog.md" in str(unconverted.value)

    # Converted (a store exists): the Markdown is a view, never legacy.
    store = L.research_backlog_path(tmp_path)
    store.parent.mkdir(parents=True)
    store.write_text('{"schema_version": "1.0", "entries": []}', encoding="utf-8")
    assert backlog.is_unconverted(tmp_path) is False
    assert L.is_legacy_layout(tmp_path) is False
    L.require_migrated(tmp_path)  # does not raise

    (pipeline / "coverage-targets.json").write_text("{}", encoding="utf-8")
    assert L.is_legacy_layout(tmp_path) is True
    assert L.legacy_paths_present(tmp_path) == [pipeline / "coverage-targets.json"]
    with pytest.raises(L.LegacyLayoutError) as excinfo:
        L.require_migrated(tmp_path)
    assert "./vault migrate-layout" in str(excinfo.value)
    assert "_pipeline/coverage-targets.json" in str(excinfo.value)


def test_a_legacy_facts_schema_or_quarantine_directory_counts(tmp_path: Path) -> None:
    schema = tmp_path / "_pipeline" / "sources" / "rss" / "facts-schema.json"
    schema.parent.mkdir(parents=True)
    schema.write_text("{}", encoding="utf-8")
    assert L.legacy_paths_present(tmp_path) == [schema]

    other = tmp_path / "other"
    (other / "_pipeline" / "quarantine").mkdir(parents=True)
    assert L.is_legacy_layout(other) is True


def test_transient_schema_files_are_not_legacy_state(tmp_path: Path) -> None:
    module = tmp_path / "_pipeline" / "sources" / "rss"
    module.mkdir(parents=True)
    (module / "facts-schema.regenerated.json").write_text("{}", encoding="utf-8")
    (module / "watermarks.json").write_text("{}", encoding="utf-8")
    assert L.is_legacy_layout(tmp_path) is False
