"""Tier 4: ``./vault coverage`` recounts in memory, shows the currency columns
and writes nothing (spec 087 FR-018/FR-019; Principle XII; T010)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from research_framework.cli import main
from research_framework.spec.schema import NoteTypeConfig
from tests._helpers.vault_factory import build_minimal_vault


def _snapshot(vault: Path) -> dict[str, str]:
    return {
        p.relative_to(vault).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(vault.rglob("*"))
        if p.is_file() and ".git" not in p.parts
    }


def _note(vault: Path, name: str, category: str, **fm: str) -> None:
    folder = vault / "data_vault" / "01 - Concepts"
    folder.mkdir(parents=True, exist_ok=True)
    lines = ["type: concept", f"coverage_category: {category}", "summary: s"]
    lines += [f"{k}: {v}" for k, v in fm.items()]
    (folder / f"{name}.md").write_text(
        "---\n" + "\n".join(lines) + "\n---\n\nBody.\n", encoding="utf-8"
    )


def test_coverage_reports_past_review_and_superseded_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = build_minimal_vault(
        tmp_path,
        num_categories=1,
        num_targets_per_category=10,
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
    category = json.loads(
        (vault / "_pipeline/state/coverage-targets.json").read_text("utf-8")
    )["categories"][0]["name"]
    today = datetime.now(UTC).date().isoformat()
    _note(vault, "fresh", category, as_of=today, currency="current")
    _note(vault, "stale-one", category, as_of="2020-01-01", currency="current")
    _note(vault, "stale-two", category, as_of="2020-02-01", currency="declining")
    _note(vault, "replaced", category, as_of="2020-01-01", currency="superseded")
    _note(vault, "withdrawn", category, as_of="2020-01-01", currency="retracted")
    before = _snapshot(vault)

    rc = main(["coverage", "--vault", str(vault)])

    out = capsys.readouterr().out
    assert rc == 1  # 3 countable notes of 10: the gate is closed, as it should be
    assert before == _snapshot(vault)  # nothing was written (Principle XII)
    header = next(line for line in out.splitlines() if line.startswith("Category"))
    assert "Past review" in header and "Superseded" in header
    row = next(line for line in out.splitlines() if line.startswith(category))
    cells = row.split()
    # target 10, met 3 (superseded and retracted do not count): recounted from
    # disk, though the persisted file still says 0
    assert cells[1:3] == ["10", "3"]
    assert cells[3:5] == ["2", "2"]  # two past review, two superseded/retracted


def test_a_vault_without_review_intervals_still_shows_the_columns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = build_minimal_vault(
        tmp_path, num_categories=1, num_targets_per_category=2, max_cycles=1
    )
    main(["coverage", "--vault", str(vault)])
    out = capsys.readouterr().out
    assert "Past review" in out and "Superseded" in out
