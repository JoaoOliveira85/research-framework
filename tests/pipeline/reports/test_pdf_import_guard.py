"""PDF import-guard tests (spec 040 T013)."""

from __future__ import annotations

import pytest

from research_framework.pipeline.reports.pdf import (
    PdfUnavailableError,
    maybe_render_pdf,
)

pytest_plugins = ["tests.pipeline.reports.helpers"]


def test_pdf_silent_skip_when_fpdf2_absent(reports_vault, monkeypatch) -> None:
    md = reports_vault / "_pipeline" / "audit-report.md"
    md.write_text("# ok\n", encoding="utf-8")
    monkeypatch.setattr(
        "research_framework.pipeline.reports.pdf.fpdf2_available", lambda: False
    )
    assert maybe_render_pdf(md, require=False) is None
    assert not md.with_suffix(".pdf").exists()


def test_pdf_require_raises_clear_error(reports_vault, monkeypatch) -> None:
    md = reports_vault / "_pipeline" / "audit-report.md"
    md.write_text("# ok\n", encoding="utf-8")
    monkeypatch.setattr(
        "research_framework.pipeline.reports.pdf.fpdf2_available", lambda: False
    )
    with pytest.raises(PdfUnavailableError, match="fpdf2 unavailable"):
        maybe_render_pdf(md, require=True)
