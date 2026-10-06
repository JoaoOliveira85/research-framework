"""FR-001: ``vault digest`` verb (spec 035)."""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest

from research_framework.cli.digest import cmd_digest
from research_framework.pipeline.digest import DateRange, default_output_path

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "digest"


@pytest.fixture
def digest_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    shutil.copytree(FIXTURE, vault)
    return vault


def test_digest_cli_writes_default_path(
    digest_vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "research_framework.cli.digest._today",
        lambda: date(2026, 6, 7),
    )
    args = type(
        "A",
        (),
        {
            "vault": digest_vault,
            "since": "2026-06-01",
            "last_week": False,
            "last_month": False,
            "last_quarter": False,
            "output": None,
        },
    )()
    assert cmd_digest(args) == 0
    out = default_output_path(
        digest_vault, DateRange(date(2026, 6, 1), date(2026, 6, 7))
    )
    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    assert "## Cycle Index" in text
