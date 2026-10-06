"""Tests for src/research_framework/pipeline/source_manager.py."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from research_framework.spec.schema import (
    BudgetConfig,
    CoverageTargets,
    DataSourceConfig,
    NoteTypeConfig,
    ScopeConfig,
    SpecConfig,
)


def _minimal_spec(data_sources: list[DataSourceConfig] | None = None) -> SpecConfig:
    """Build a minimal SpecConfig for testing."""
    if data_sources is None:
        data_sources = [
            DataSourceConfig(name="Source Alpha", type="internal", role="behaviour"),
            DataSourceConfig(name="Source Beta", type="external", role="intent"),
        ]
    return SpecConfig(
        name="Test Vault",
        location=Path("/tmp/test"),
        owner="tester",
        scope=ScopeConfig(domain="testing", organization="test-org"),
        note_types=[
            NoteTypeConfig(name="concept", description="", folder="01 - Concepts")
        ],
        data_sources=data_sources,
        search_dimensions=[],
        coverage_targets=CoverageTargets(),
        budget=BudgetConfig(),
    )


def _setup_pipeline_dir(vault_dir: Path) -> None:
    """Create _pipeline dir needed by source_manager."""
    (vault_dir / "_pipeline").mkdir(parents=True, exist_ok=True)


def test_seed_creates_db_with_spec_sources(tmp_path: Path) -> None:
    from research_framework.pipeline.source_manager import seed

    _setup_pipeline_dir(tmp_path)
    spec = _minimal_spec()
    seed(tmp_path, spec)

    db_path = tmp_path / "_pipeline" / "sources.db"
    assert db_path.exists()

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT name, locked, status FROM sources ORDER BY name"
    ).fetchall()
    conn.close()

    assert len(rows) == 2
    names = {r[0] for r in rows}
    assert "Source Alpha" in names
    assert "Source Beta" in names
    for _, locked, status in rows:
        assert locked == 1
        assert status == "active"


def test_seed_is_idempotent(tmp_path: Path) -> None:
    from research_framework.pipeline.source_manager import seed

    _setup_pipeline_dir(tmp_path)
    spec = _minimal_spec()
    seed(tmp_path, spec)
    seed(tmp_path, spec)  # second call

    conn = sqlite3.connect(tmp_path / "_pipeline" / "sources.db")
    count = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    conn.close()

    assert count == 2


def test_append_discovered_adds_unlocked(tmp_path: Path) -> None:
    from research_framework.pipeline.source_manager import append_discovered, seed

    _setup_pipeline_dir(tmp_path)
    spec = _minimal_spec()
    seed(tmp_path, spec)

    append_discovered(
        tmp_path,
        [
            {
                "name": "New Source",
                "type": "external",
                "role": "domain",
                "url": "https://example.com",
            }
        ],
    )

    conn = sqlite3.connect(tmp_path / "_pipeline" / "sources.db")
    row = conn.execute(
        "SELECT name, locked FROM sources WHERE name='New Source'"
    ).fetchone()
    count = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    conn.close()

    assert row is not None
    assert row[1] == 0  # locked=0
    assert count == 3


def test_append_discovered_skips_duplicate(tmp_path: Path) -> None:
    from research_framework.pipeline.source_manager import append_discovered, seed

    _setup_pipeline_dir(tmp_path)
    spec = _minimal_spec()
    seed(tmp_path, spec)

    new = [
        {
            "name": "Dup Source",
            "type": "external",
            "role": "domain",
            "url": "https://dup.com",
        }
    ]
    append_discovered(tmp_path, new)
    append_discovered(tmp_path, new)  # duplicate

    conn = sqlite3.connect(tmp_path / "_pipeline" / "sources.db")
    count = conn.execute(
        "SELECT COUNT(*) FROM sources WHERE name='Dup Source'"
    ).fetchone()[0]
    conn.close()

    assert count == 1


def test_active_sources_excludes_archived(tmp_path: Path) -> None:
    from research_framework.pipeline.source_manager import active_sources, seed

    _setup_pipeline_dir(tmp_path)
    spec = _minimal_spec()
    seed(tmp_path, spec)

    # Manually archive one source
    conn = sqlite3.connect(tmp_path / "_pipeline" / "sources.db")
    conn.execute("UPDATE sources SET status='archived' WHERE name='Source Alpha'")
    conn.commit()
    conn.close()

    result = active_sources(tmp_path)
    names = [r["name"] for r in result]
    assert "Source Alpha" not in names
    assert "Source Beta" in names
    assert len(result) == 1


def test_record_cycle_upserts_source_cycles(tmp_path: Path) -> None:
    from research_framework.pipeline.source_manager import record_cycle, seed

    _setup_pipeline_dir(tmp_path)
    spec = _minimal_spec()
    seed(tmp_path, spec)

    research_report = {
        "notes_created": ["data_vault/01 - Concepts/Foo.md"],
        "discovered_sources": [],
    }
    record_cycle(tmp_path, 1, research_report)

    conn = sqlite3.connect(tmp_path / "_pipeline" / "sources.db")
    rows = conn.execute("SELECT name, cycle FROM source_cycles").fetchall()
    conn.close()

    assert len(rows) == 2  # one row per source
    cycles = {r[1] for r in rows}
    assert 1 in cycles


def test_record_cycle_archives_on_decay_threshold(tmp_path: Path) -> None:
    from research_framework.pipeline.source_manager import (
        active_sources,
        append_discovered,
        record_cycle,
        seed,
    )

    _setup_pipeline_dir(tmp_path)

    # Write settings.yaml with decay_after_n_cycles=2
    settings_yaml = tmp_path / "_pipeline" / "settings.yaml"
    settings_yaml.write_text(
        "stages:\n  source_manager:\n    decay_after_n_cycles: 2\n",
        encoding="utf-8",
    )

    # Spec with locked source only; add one discovered (unlocked)
    spec = _minimal_spec(
        data_sources=[
            DataSourceConfig(name="Locked Source", type="internal", role="behaviour")
        ]
    )
    seed(tmp_path, spec)
    append_discovered(
        tmp_path,
        [
            {
                "name": "Ephemeral",
                "type": "external",
                "role": "domain",
                "url": "https://e.com",
            }
        ],
    )

    empty_report = {"notes_created": [], "discovered_sources": []}
    record_cycle(tmp_path, 1, empty_report)
    record_cycle(tmp_path, 2, empty_report)

    result = active_sources(tmp_path)
    names = [r["name"] for r in result]
    assert "Ephemeral" not in names  # archived after 2 empty cycles


def test_locked_source_not_archived(tmp_path: Path) -> None:
    from research_framework.pipeline.source_manager import (
        active_sources,
        record_cycle,
        seed,
    )

    _setup_pipeline_dir(tmp_path)

    settings_yaml = tmp_path / "_pipeline" / "settings.yaml"
    settings_yaml.write_text(
        "stages:\n  source_manager:\n    decay_after_n_cycles: 2\n",
        encoding="utf-8",
    )

    spec = _minimal_spec(
        data_sources=[
            DataSourceConfig(name="Locked", type="internal", role="behaviour")
        ]
    )
    seed(tmp_path, spec)

    empty_report = {"notes_created": [], "discovered_sources": []}
    for i in range(1, 6):
        record_cycle(tmp_path, i, empty_report)

    result = active_sources(tmp_path)
    assert any(r["name"] == "Locked" for r in result)


def test_merge_into_prompt_context_combines_sources(tmp_path: Path) -> None:
    from research_framework.pipeline.source_manager import (
        append_discovered,
        merge_into_prompt_context,
        seed,
    )

    _setup_pipeline_dir(tmp_path)
    spec = _minimal_spec()
    seed(tmp_path, spec)
    append_discovered(
        tmp_path,
        [
            {
                "name": "Discovered X",
                "type": "external",
                "role": "domain",
                "url": "https://x.com",
            }
        ],
    )

    result = merge_into_prompt_context(spec, tmp_path)

    names = [s.name for s in result]
    # Spec sources come first
    assert names.index("Source Alpha") < names.index("Discovered X")
    assert names.index("Source Beta") < names.index("Discovered X")
    assert "Discovered X" in names
    assert len(result) == 3


def test_source_quality_summary_returns_aggregates(tmp_path: Path) -> None:
    from research_framework.pipeline.source_manager import (
        seed,
        source_quality_summary,
    )

    _setup_pipeline_dir(tmp_path)
    spec = _minimal_spec(
        data_sources=[DataSourceConfig(name="Solo", type="internal", role="behaviour")]
    )
    seed(tmp_path, spec)

    # Manually inject source_cycles rows for more predictable totals
    conn = sqlite3.connect(tmp_path / "_pipeline" / "sources.db")
    conn.execute(
        "INSERT INTO source_cycles(name, cycle, notes_generated) VALUES ('Solo', 1, 3)"
    )
    conn.execute(
        "INSERT INTO source_cycles(name, cycle, notes_generated) VALUES ('Solo', 2, 5)"
    )
    conn.commit()
    conn.close()

    summary = source_quality_summary(tmp_path)
    assert len(summary) == 1
    row = summary[0]
    assert row["name"] == "Solo"
    assert row["total_notes_generated"] == 8


def test_scaffold_creates_sources_db(tmp_path: Path) -> None:
    from research_framework.generator.scaffold import scaffold
    from research_framework.spec.parser import parse

    fixtures_dir = Path(__file__).parent.parent / "fixtures"
    spec = parse(fixtures_dir / "sample-spec.md")
    vault = tmp_path / "vault"
    scaffold(spec, vault)

    db_path = vault / "_pipeline" / "sources.db"
    assert db_path.exists()

    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    conn.close()

    assert count == len(spec.data_sources)
