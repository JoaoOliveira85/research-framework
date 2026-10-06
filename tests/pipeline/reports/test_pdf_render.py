"""PDF render tests (spec 040 T012/T014)."""

from __future__ import annotations

import importlib.util

import pytest

from research_framework.pipeline.reports.pdf import fpdf2_available, render_pdf

pytest_plugins = ["tests.pipeline.reports.helpers"]

pytestmark = pytest.mark.skipif(not fpdf2_available(), reason="fpdf2 not installed")


def test_pdf_render_structural_facts(reports_vault, tmp_path) -> None:
    md = reports_vault / "_pipeline" / "audit-report.md"
    md.write_text(
        "# Audit\n\n## Coverage Delta\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n",
        encoding="utf-8",
    )
    pdf_path = render_pdf(md)
    assert pdf_path.is_file()
    assert pdf_path.stat().st_size > 100
    raw = pdf_path.read_bytes()
    assert raw.startswith(b"%PDF")
    assert b"/Page" in raw or b"/Kids" in raw


def test_pdf_uses_bundled_core_fonts_only(monkeypatch, reports_vault) -> None:
    md = reports_vault / "_pipeline" / "audit-report.md"
    md.write_text("# Title\n\nBody paragraph.\n", encoding="utf-8")

    def _forbidden_font(*_args, **_kwargs):
        raise AssertionError("system font lookup must not run")

    monkeypatch.setattr(
        "research_framework.pipeline.reports.pdf._import_fpdf",
        lambda: __import__("fpdf").FPDF,
    )
    render_pdf(md)


def test_pdf_fonts_no_system_lookup(monkeypatch, reports_vault) -> None:
    if importlib.util.find_spec("fpdf") is None:
        pytest.skip("fpdf2 not installed")
    md = reports_vault / "_pipeline" / "audit-report.md"
    md.write_text("## Section\n\n- item\n", encoding="utf-8")
    render_pdf(md)
