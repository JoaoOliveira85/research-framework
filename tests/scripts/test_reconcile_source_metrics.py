"""Spec 029 FR-008 — reconcile_source_metrics.py (un-archive wrongly-decayed sources).

The path-substring attribution bug (Bug 2) inflated ``consecutive_empty_cycles``
and wrongly auto-archived still-cited sources. This one-shot, idempotent script
recomputes ``cited_now`` from the CURRENT ``data_vault/`` frontmatter and:
  (a) un-archives ``status='archived' AND cited_now > 0``,
  (b) resets ``consecutive_empty_cycles=0`` where ``cited_now > 0``,
  (c) leaves genuinely-uncited sources untouched.
``--apply`` writes ONLY ``sources.db`` (never the note tree).
"""

from __future__ import annotations

import hashlib
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest
import yaml

from research_framework.pipeline import source_manager as sm
from research_framework.spec.schema import (
    BudgetConfig,
    CoverageTargets,
    NoteTypeConfig,
    ScopeConfig,
    SpecConfig,
)

_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "reconcile_source_metrics.py"
)


@pytest.fixture
def reconcile_mod():
    spec = importlib.util.spec_from_file_location("reconcile_source_metrics", _SCRIPT)
    assert spec and spec.loader, "scripts/reconcile_source_metrics.py must exist (T015)"
    module = importlib.util.module_from_spec(spec)
    sys.modules["reconcile_source_metrics"] = module
    spec.loader.exec_module(module)
    return module


def _seed(vault: Path, sources: list[dict]) -> None:
    (vault / "_pipeline").mkdir(parents=True, exist_ok=True)
    spec = SpecConfig(
        name="t",
        location=vault,
        owner="t",
        scope=ScopeConfig(domain="d", organization="o"),
        note_types=[
            NoteTypeConfig(name="concept", description="", folder="01 - Concepts")
        ],
        data_sources=[],
        search_dimensions=[],
        coverage_targets=CoverageTargets(),
        budget=BudgetConfig(),
    )
    sm.seed(vault, spec)
    sm.append_discovered(vault, sources)


def _set_db(vault: Path, name: str, *, status: str, empty: int) -> None:
    conn = sqlite3.connect(vault / "_pipeline" / "sources.db")
    try:
        conn.execute(
            "UPDATE sources SET status=?, consecutive_empty_cycles=? WHERE name=?",
            (status, empty, name),
        )
        conn.commit()
    finally:
        conn.close()


def _row(vault: Path, name: str) -> tuple[str, int]:
    conn = sqlite3.connect(vault / "_pipeline" / "sources.db")
    try:
        status, empty = conn.execute(
            "SELECT status, consecutive_empty_cycles FROM sources WHERE name=?", (name,)
        ).fetchone()
    finally:
        conn.close()
    return status, int(empty)


def _write_note(vault: Path, filename: str, source_urls: list[str]) -> None:
    folder = vault / "data_vault" / "01 - Concepts"
    folder.mkdir(parents=True, exist_ok=True)
    body = (
        "---\n"
        + yaml.safe_dump(
            {"type": "concept", "source_urls": source_urls}, sort_keys=False
        )
        + "---\n\n# "
        + filename
        + "\n"
    )
    (folder / filename).write_text(body, encoding="utf-8")


def _tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def _wrongful_vault(tmp_path: Path) -> Path:
    """A vault where 'KeptAlive' was wrongly archived but is still cited."""
    vault = tmp_path / "v"
    _seed(
        vault,
        [
            {
                "name": "KeptAlive",
                "type": "external",
                "role": "domain",
                "url": "https://k.example.com/feed",
            },
            {
                "name": "TrulyDead",
                "type": "external",
                "role": "domain",
                "url": "https://d.example.com/feed",
            },
        ],
    )
    _set_db(vault, "KeptAlive", status="archived", empty=5)
    _set_db(vault, "TrulyDead", status="archived", empty=5)
    _write_note(vault, "n.md", ["https://k.example.com/feed"])
    return vault


def test_dryrun_reports_wrongful_archival(reconcile_mod, tmp_path: Path) -> None:
    vault = _wrongful_vault(tmp_path)
    changes = reconcile_mod.reconcile(vault, apply=False)
    by = {c["name"]: c for c in changes}
    assert "KeptAlive" in by, "still-cited archived source must be reported"
    assert by["KeptAlive"]["unarchived"] is True
    assert "TrulyDead" not in by, "genuinely-uncited source must not be reported"
    # dry-run mutates nothing
    assert _row(vault, "KeptAlive") == ("archived", 5)


def test_apply_unarchives_and_resets_db_only(reconcile_mod, tmp_path: Path) -> None:
    vault = _wrongful_vault(tmp_path)
    before = _tree_digest(vault / "data_vault")
    reconcile_mod.reconcile(vault, apply=True)
    assert _row(vault, "KeptAlive") == ("active", 0)
    after = _tree_digest(vault / "data_vault")
    assert before == after, (
        "the note tree must be byte-identical (only sources.db mutated)"
    )


def test_uncited_source_left_untouched(reconcile_mod, tmp_path: Path) -> None:
    vault = _wrongful_vault(tmp_path)
    reconcile_mod.reconcile(vault, apply=True)
    assert _row(vault, "TrulyDead") == ("archived", 5)


def test_clean_vault_zero_false_positives(reconcile_mod, tmp_path: Path) -> None:
    vault = tmp_path / "v"
    _seed(
        vault,
        [
            {
                "name": "Active",
                "type": "external",
                "role": "domain",
                "url": "https://a.example.com/feed",
            }
        ],
    )
    _write_note(vault, "n.md", ["https://a.example.com/feed"])
    changes = reconcile_mod.reconcile(vault, apply=False)
    assert changes == [], "a vault that never ran the buggy code reports no changes"


def test_idempotent(reconcile_mod, tmp_path: Path) -> None:
    vault = _wrongful_vault(tmp_path)
    reconcile_mod.reconcile(vault, apply=True)
    second = reconcile_mod.reconcile(vault, apply=True)
    assert second == [], "a second apply is a no-op"
