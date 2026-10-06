"""Shared helpers for spec 040 report tests."""

from __future__ import annotations

import shutil
from datetime import date, datetime
from pathlib import Path

import pytest

from research_framework.pipeline.digest.scope import DateRange
from research_framework.pipeline.reports.layer1 import (
    compose_report,
    write_audit_report,
)

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "reports"
FIXTURE_RANGE = DateRange(start=date(2026, 6, 1), end=date(2026, 6, 7))
FIXTURE_RENDERED_AT = "2026-06-07T12:00:00+00:00"


@pytest.fixture
def reports_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    shutil.copytree(FIXTURE_ROOT, vault)
    return vault


def render_fixture(vault: Path, *, up_to_cycle: int | None = 3) -> str:
    rendered = datetime.fromisoformat(FIXTURE_RENDERED_AT)
    return compose_report(
        vault,
        date_range=FIXTURE_RANGE,
        up_to_cycle=up_to_cycle,
        rendered_at=rendered,
    )


def write_fixture(vault: Path, *, up_to_cycle: int | None = 3) -> Path:
    markdown = render_fixture(vault, up_to_cycle=up_to_cycle)
    return write_audit_report(vault, markdown)
