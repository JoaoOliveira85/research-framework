"""Shared helpers for digest tests (spec 035)."""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest

from research_framework.pipeline.digest import DateRange, run_digest
from research_framework.pipeline.digest.render import strip_rendered_at_line

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "digest"
FIXTURE_RANGE = DateRange(start=date(2026, 6, 1), end=date(2026, 6, 7))
FIXTURE_RENDERED_AT = "2026-06-07T12:00:00+00:00"


@pytest.fixture
def digest_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    shutil.copytree(FIXTURE_ROOT, vault)
    return vault


def render_fixture(vault: Path, *, output: Path | None = None) -> str:
    from datetime import datetime

    rendered = datetime.fromisoformat(FIXTURE_RENDERED_AT)
    if output is None:
        result = run_digest(vault, date_range=FIXTURE_RANGE, rendered_at=rendered)
        assert result.markdown is not None
        return result.markdown
    result = run_digest(
        vault,
        date_range=FIXTURE_RANGE,
        output_path=output,
        rendered_at=rendered,
    )
    assert result.markdown is not None
    return result.markdown


def normalized_digest(markdown: str) -> str:
    return strip_rendered_at_line(markdown)
