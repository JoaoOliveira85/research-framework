"""Tier 3: ``vault_health`` reports notes past review per category and the
supersession links that never became symmetric (spec 087 FR-007, FR-019; T010)."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from research_framework.spec.schema import NoteTypeConfig
from tests._helpers.vault_factory import build_minimal_vault

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def vh() -> Any:
    path = ROOT / "scripts" / "vault_health.py"
    spec = importlib.util.spec_from_file_location("_vault_health_currency", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def _note(vault: Path, name: str, category: str, **fm: str) -> None:
    folder = vault / "data_vault" / "01 - Concepts"
    folder.mkdir(parents=True, exist_ok=True)
    lines = ["type: concept", f"coverage_category: {category}", "summary: s"]
    lines += [f"{k}: {v}" for k, v in fm.items()]
    (folder / f"{name}.md").write_text(
        "---\n" + "\n".join(lines) + "\n---\n\nBody.\n", encoding="utf-8"
    )


def _vault(tmp_path: Path) -> tuple[Path, str]:
    vault = build_minimal_vault(
        tmp_path,
        num_categories=1,
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
    import json

    category = json.loads(
        (vault / "_pipeline/state/coverage-targets.json").read_text("utf-8")
    )["categories"][0]["name"]
    return vault, category


def test_health_lists_notes_past_review_per_category(vh: Any, tmp_path: Path) -> None:
    vault, category = _vault(tmp_path)
    today = datetime.now(UTC).date().isoformat()
    _note(vault, "fresh", category, as_of=today, currency="current")
    _note(vault, "stale", category, as_of="2020-01-01", currency="current")
    _note(
        vault,
        "old-news",
        category,
        as_of="2020-01-01",
        currency="superseded",
        superseded_by="[successor]",
    )
    _note(
        vault,
        "successor",
        category,
        as_of=today,
        currency="current",
        supersedes="[old-news]",
    )
    before = {p: p.read_bytes() for p in (vault / "data_vault").rglob("*.md")}

    report = vh.run(vault, offline=True)
    text = (vault / "_pipeline" / "health-report.md").read_text(encoding="utf-8")

    assert [row.category for row in report.currency] == [category]
    row = report.currency[0]
    assert (row.past_review, row.uncountable) == (1, 1)
    assert "## Currency" in text
    assert f"- {category}: 1 past review, 1 superseded or retracted" in text
    assert "- past review: `data_vault/01 - Concepts/stale.md`" in text
    assert report.supersession_links == []  # symmetric
    assert report.set_aside == []
    assert before == {
        p: p.read_bytes() for p in (vault / "data_vault").rglob("*.md")
    }  # read-only


def test_health_lists_updates_set_aside_with_their_reason(
    vh: Any, tmp_path: Path
) -> None:
    from research_framework.pipeline import backlog

    vault, category = _vault(tmp_path)
    _note(vault, "stuck", category, as_of="2020-01-01", currency="current")
    backlog.observe_update(vault, "review", stem="stuck", reason="review_due")
    for cycle in (1, 2):
        backlog.record_update_failure(vault, "stuck", "commentary only", cycle=cycle)

    report = vh.run(vault, offline=True)
    text = (vault / "_pipeline" / "health-report.md").read_text(encoding="utf-8")

    assert [(s.stem, s.attempts, s.last_failure) for s in report.set_aside] == [
        ("stuck", 2, "commentary only")
    ]
    assert "### updates set aside after 2 failed attempts (1)" in text
    assert "- stuck: review_due; last failure (cycle 2): commentary only" in text
    # advisory: it needs a person, and does not flip the exit code
    assert report.unresolved_count == replace(report, set_aside=[]).unresolved_count


def test_health_reports_a_link_that_never_became_symmetric(
    vh: Any, tmp_path: Path
) -> None:
    vault, category = _vault(tmp_path)
    _note(vault, "old-news", category, currency="superseded", superseded_by="[ghost]")
    _note(vault, "orphan-successor", category, supersedes="[old-news]")
    _note(vault, "half", category, supersedes="[not-superseded]")
    _note(vault, "not-superseded", category)

    report = vh.run(vault, offline=True)
    text = (vault / "_pipeline" / "health-report.md").read_text(encoding="utf-8")

    problems = {
        (link.note, link.field, link.target) for link in report.supersession_links
    }
    assert ("old-news", "superseded_by", "ghost") in problems  # never on disk
    assert ("orphan-successor", "supersedes", "old-news") in problems  # one-sided
    assert ("half", "supersedes", "not-superseded") in problems
    assert "one-sided supersession links" in text
    assert report.unresolved_count >= 3
