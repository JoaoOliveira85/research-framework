"""Tests for scripts/topic_harvest.py."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "topic_harvest.py"
_SRC_DIR = str(Path(__file__).parent.parent.parent / "src")


def _run(vault: Path, cycle: int) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": _SRC_DIR}
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(vault), str(cycle)],
        capture_output=True,
        text=True,
        env=env,
    )


def _seed_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "data_vault" / "concept").mkdir(parents=True)
    (vault / "_pipeline" / "cycles").mkdir(parents=True)
    (vault / "_pipeline" / "research-backlog.md").write_text(
        "# Research Backlog\n\nTopics deferred from scout passes.\n",
        encoding="utf-8",
    )
    return vault


def _write_research(vault: Path, cycle: int, created: list[str], **extra) -> None:
    report = {
        "cycle": cycle,
        "phase": "research",
        "notes_created": created,
        "notes_updated": [],
    }
    report.update(extra)
    (vault / "_pipeline" / "cycles" / f"cycle-{cycle:03d}-research.json").write_text(
        json.dumps(report), encoding="utf-8"
    )


def _read_manifest(vault: Path, cycle: int) -> dict:
    path = vault / "_pipeline" / "cycles" / f"cycle-{cycle:03d}-harvest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_ranks_followups_by_citation_count(tmp_path: Path) -> None:
    """Topics cited by more distinct notes appear first."""
    vault = _seed_vault(tmp_path)
    (vault / "data_vault" / "concept" / "A.md").write_text(
        "See [[Alpha]] and [[Beta]].\n", encoding="utf-8"
    )
    (vault / "data_vault" / "concept" / "B.md").write_text(
        "Also [[Alpha]].\n", encoding="utf-8"
    )
    (vault / "data_vault" / "concept" / "C.md").write_text(
        "Mentions [[Alpha]] only.\n", encoding="utf-8"
    )
    _write_research(vault, 1, ["concept/A.md", "concept/B.md", "concept/C.md"])

    r = _run(vault, 1)
    assert r.returncode == 0, r.stderr

    m = _read_manifest(vault, 1)
    assert [f["title"] for f in m["followups"]] == ["Alpha", "Beta"]
    assert m["followups"][0]["citation_count"] == 3
    assert m["followups"][1]["citation_count"] == 1


def test_normalizes_wikilink_shapes(tmp_path: Path) -> None:
    """[[X]], [[X.md]], [[folder/X]], [[X|alias]], [[X#anchor]] all collapse to X."""
    vault = _seed_vault(tmp_path)
    (vault / "data_vault" / "concept" / "N.md").write_text(
        "[[Foo]] [[Foo.md]] [[sub/Foo]] [[Foo|alias]] [[Foo#section]]\n",
        encoding="utf-8",
    )
    _write_research(vault, 1, ["concept/N.md"])

    r = _run(vault, 1)
    assert r.returncode == 0, r.stderr

    m = _read_manifest(vault, 1)
    titles = [f["title"] for f in m["followups"]]
    assert titles == ["Foo"], titles
    # Same note cites all shapes — counted once per note.
    assert m["followups"][0]["citation_count"] == 1


def test_skips_wikilinks_to_existing_notes(tmp_path: Path) -> None:
    """A wikilink whose target file exists must not appear as a followup."""
    vault = _seed_vault(tmp_path)
    (vault / "data_vault" / "concept" / "Foo.md").write_text(
        "# Foo\n", encoding="utf-8"
    )
    (vault / "data_vault" / "concept" / "N.md").write_text(
        "Refers to [[Foo]] which already exists.\n", encoding="utf-8"
    )
    _write_research(vault, 1, ["concept/N.md"])

    r = _run(vault, 1)
    assert r.returncode == 0, r.stderr

    m = _read_manifest(vault, 1)
    assert m["followups"] == []


def test_includes_coverage_gaps(tmp_path: Path) -> None:
    """Unmet categories surface with shortfall, ordered required-first."""
    vault = _seed_vault(tmp_path)
    (vault / "_pipeline" / "coverage-targets.json").write_text(
        json.dumps(
            {
                "categories": [
                    {
                        "name": "optional_cat",
                        "note_type": "concept",
                        "target_count": 5,
                        "met_count": 1,
                        "required": False,
                    },
                    {
                        "name": "architecture",
                        "note_type": "concept",
                        "target_count": 5,
                        "met_count": 2,
                        "required": True,
                    },
                    {
                        "name": "met_cat",
                        "note_type": "concept",
                        "target_count": 3,
                        "met_count": 3,
                        "required": True,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    (vault / "data_vault" / "concept" / "N.md").write_text(
        "No wikilinks here.\n", encoding="utf-8"
    )
    _write_research(vault, 1, ["concept/N.md"])

    r = _run(vault, 1)
    assert r.returncode == 0, r.stderr

    m = _read_manifest(vault, 1)
    gap_names = [g["name"] for g in m["coverage_gaps"]]
    assert gap_names == ["architecture", "optional_cat"]
    assert m["coverage_gaps"][0]["shortfall"] == 3

    backlog = (vault / "_pipeline" / "research-backlog.md").read_text(encoding="utf-8")
    assert "architecture" in backlog
    assert "Unmet coverage categories" in backlog


def test_merges_researcher_flagged_links(tmp_path: Path) -> None:
    """new_wikilinks_discovered entries appear, deduped against wikilink harvest."""
    vault = _seed_vault(tmp_path)
    (vault / "data_vault" / "concept" / "N.md").write_text(
        "Cites [[Alpha]].\n", encoding="utf-8"
    )
    _write_research(
        vault,
        1,
        ["concept/N.md"],
        new_wikilinks_discovered=["Alpha", "Gamma"],  # Alpha dedupes; Gamma is new
    )

    r = _run(vault, 1)
    assert r.returncode == 0, r.stderr

    m = _read_manifest(vault, 1)
    by_title = {f["title"]: f for f in m["followups"]}
    assert by_title["Alpha"]["reason"] == "missing_wikilink_target"
    assert by_title["Gamma"]["reason"] == "researcher_flagged"


def test_preserves_manual_backlog_entries(tmp_path: Path) -> None:
    """Only the managed block is replaced; manual bullets outside survive."""
    vault = _seed_vault(tmp_path)
    (vault / "_pipeline" / "research-backlog.md").write_text(
        "# Research Backlog\n\n- Manual entry I added by hand\n",
        encoding="utf-8",
    )
    (vault / "data_vault" / "concept" / "N.md").write_text(
        "See [[Ghost]].\n", encoding="utf-8"
    )
    _write_research(vault, 1, ["concept/N.md"])

    assert _run(vault, 1).returncode == 0
    # Run a second time for the same cycle — must still be idempotent and keep manual line.
    assert _run(vault, 1).returncode == 0

    backlog = (vault / "_pipeline" / "research-backlog.md").read_text(encoding="utf-8")
    assert "Manual entry I added by hand" in backlog
    assert backlog.count("topic-harvest:cycle=001") == 2  # one start + one end marker
    assert backlog.count("Ghost") == 1


def test_skipped_when_no_research_json(tmp_path: Path) -> None:
    vault = _seed_vault(tmp_path)
    r = _run(vault, 2)
    assert r.returncode == 0
    assert "skipped" in r.stdout.lower()
    assert not (vault / "_pipeline" / "cycles" / "cycle-002-harvest.json").exists()


# ---------------------------------------------------------------------------
# Auto-promotion of high-citation orphans → coverage-targets.json
# (constitution v1.3.0 § "Coverage Targets — Dynamic extension via
# backlog promotion")
# ---------------------------------------------------------------------------


def _seed_coverage_targets(vault: Path, categories: list[dict]) -> None:
    """Write a `coverage-targets.json` matching the structure
    `research_framework.pipeline.coverage.load_targets` expects."""
    payload = {"categories": categories}
    (vault / "_pipeline" / "coverage-targets.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _seed_settings_threshold(vault: Path, threshold: int | None) -> None:
    """Write a minimal settings.yaml so the script reads the override.
    `threshold=None` writes a settings file without the field, which
    should fall back to the default."""
    if threshold is None:
        body = "schema_version: 1\n"
    else:
        body = (
            "schema_version: 1\n"
            "pipeline:\n"
            f"  backlog_promotion_threshold: {threshold}\n"
        )
    (vault / "settings.yaml").write_text(body, encoding="utf-8")


def test_promotes_high_citation_orphans_to_coverage_targets(
    tmp_path: Path,
) -> None:
    """An orphan cited by ≥ threshold notes becomes a new
    `CoverageCategory` with `note_type: concept` and `target_count: 1`."""
    vault = _seed_vault(tmp_path)
    _seed_coverage_targets(
        vault,
        [
            {
                "name": "services",
                "note_type": "service",
                "target_count": 1,
                "met_count": 1,
            }
        ],
    )
    _seed_settings_threshold(vault, 2)

    # Two notes, both wikilinking [[Zone System]] (cited 2x → meets
    # threshold) and one wikilinking [[Random Aside]] (cited 1x → below).
    notes = vault / "data_vault" / "concept"
    notes.mkdir(parents=True, exist_ok=True)
    (notes / "Note A.md").write_text(
        "---\ntitle: A\n---\n\nA references [[Zone System]] and [[Stop Bath]].",
        encoding="utf-8",
    )
    (notes / "Note B.md").write_text(
        "---\ntitle: B\n---\n\nB references [[Zone System]] and [[Stop Bath]] "
        "and [[Random Aside]].",
        encoding="utf-8",
    )
    _write_research(vault, 1, ["concept/Note A.md", "concept/Note B.md"])

    r = _run(vault, 1)
    assert r.returncode == 0, r.stdout + r.stderr

    coverage = json.loads((vault / "_pipeline" / "coverage-targets.json").read_text())
    names = {c["name"] for c in coverage["categories"]}
    assert "zone-system" in names, names
    assert "stop-bath" in names, names
    assert "random-aside" not in names, names
    assert "services" in names  # original category preserved


def test_promotion_is_idempotent(tmp_path: Path) -> None:
    """Re-running the harvester on the same cycle does not duplicate
    promotions in coverage-targets.json."""
    vault = _seed_vault(tmp_path)
    _seed_coverage_targets(vault, [])
    _seed_settings_threshold(vault, 2)

    notes = vault / "data_vault" / "concept"
    notes.mkdir(parents=True, exist_ok=True)
    (notes / "A.md").write_text("[[Zone System]]", encoding="utf-8")
    (notes / "B.md").write_text("[[Zone System]]", encoding="utf-8")
    _write_research(vault, 1, ["concept/A.md", "concept/B.md"])

    _run(vault, 1)
    _run(vault, 1)

    coverage = json.loads((vault / "_pipeline" / "coverage-targets.json").read_text())
    zone_entries = [c for c in coverage["categories"] if c["name"] == "zone-system"]
    assert len(zone_entries) == 1


def test_promotion_threshold_is_configurable(tmp_path: Path) -> None:
    """Setting `pipeline.backlog_promotion_threshold: 3` in settings.yaml
    raises the bar — a 2x-cited orphan should NOT be promoted."""
    vault = _seed_vault(tmp_path)
    _seed_coverage_targets(vault, [])
    _seed_settings_threshold(vault, 3)

    notes = vault / "data_vault" / "concept"
    notes.mkdir(parents=True, exist_ok=True)
    (notes / "A.md").write_text("[[Twice Cited]]", encoding="utf-8")
    (notes / "B.md").write_text("[[Twice Cited]]", encoding="utf-8")
    _write_research(vault, 1, ["concept/A.md", "concept/B.md"])

    _run(vault, 1)

    coverage = json.loads((vault / "_pipeline" / "coverage-targets.json").read_text())
    names = {c["name"] for c in coverage["categories"]}
    assert "twice-cited" not in names


def test_harvest_reads_a_non_default_corpus_dir(tmp_path: Path) -> None:
    """A vault that named its corpus `cases/` still gets its wikilinks harvested.

    The script hardcoded `data_vault/`, so such a vault resolved none of its
    touched notes and harvested nothing (#251).
    """
    vault = tmp_path / "vault"
    (vault / "cases" / "concept").mkdir(parents=True)
    (vault / "_pipeline" / "cycles").mkdir(parents=True)
    (vault / "_pipeline" / "spec-parse.json").write_text(
        json.dumps({"vault_corpus_dir": "cases"}), encoding="utf-8"
    )
    (vault / "_pipeline" / "research-backlog.md").write_text(
        "# Research Backlog\n", encoding="utf-8"
    )
    (vault / "cases" / "concept" / "A.md").write_text(
        "See [[Alpha]].\n", encoding="utf-8"
    )
    _write_research(vault, 1, ["concept/A.md"])

    r = _run(vault, 1)
    assert r.returncode == 0, r.stderr

    m = _read_manifest(vault, 1)
    assert [f["title"] for f in m["followups"]] == ["Alpha"]
