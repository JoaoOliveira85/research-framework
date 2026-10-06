"""Markdown → PDF renderer via optional fpdf2 (spec 040 FR-009..012)."""

from __future__ import annotations

import logging
import re
from pathlib import Path

_LOG = logging.getLogger(__name__)

_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_UNAVAILABLE_MSG = (
    "fpdf2 unavailable; install with pip install research-framework[reports]"
)


class PdfUnavailableError(RuntimeError):
    """Raised when PDF was explicitly requested but fpdf2 is missing."""


def fpdf2_available() -> bool:
    try:
        import fpdf  # noqa: F401

        return True
    except ImportError:
        return False


def _import_fpdf():
    from fpdf import FPDF

    return FPDF


def _strip_inline_links(text: str) -> tuple[str, list[tuple[int, int, str]]]:
    links: list[tuple[int, int, str]] = []
    out: list[str] = []
    pos = 0
    for match in _LINK_RE.finditer(text):
        out.append(text[pos : match.start()])
        label = match.group(1)
        url = match.group(2)
        start = sum(len(part) for part in out)
        out.append(label)
        end = start + len(label)
        links.append((start, end, url))
        pos = match.end()
    out.append(text[pos:])
    return "".join(out), links


def _render_markdown_to_pdf(markdown: str, pdf_path: Path) -> None:
    FPDF = _import_fpdf()
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)
    in_code = False
    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            pdf.set_font("Courier", size=9)
            pdf.multi_cell(pdf.epw, 5, line)
            continue
        if line.startswith("### "):
            pdf.ln(2)
            pdf.set_font("Helvetica", style="B", size=12)
            pdf.multi_cell(pdf.epw, 6, line[4:])
            pdf.set_font("Helvetica", size=10)
            continue
        if line.startswith("## "):
            pdf.ln(3)
            pdf.set_font("Helvetica", style="B", size=14)
            pdf.multi_cell(pdf.epw, 7, line[3:])
            pdf.set_font("Helvetica", size=10)
            continue
        if line.startswith("# "):
            pdf.ln(4)
            pdf.set_font("Helvetica", style="B", size=16)
            pdf.multi_cell(pdf.epw, 8, line[2:])
            pdf.set_font("Helvetica", size=10)
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if cells and all(set(c) <= {"-", ":", " "} for c in cells):
                continue
            row = " | ".join(cells)
            pdf.set_font("Helvetica", size=9)
            pdf.multi_cell(pdf.epw, 5, row)
            pdf.set_font("Helvetica", size=10)
            continue
        if line.startswith("- "):
            plain, links = _strip_inline_links(line[2:])
            pdf.multi_cell(pdf.epw, 5, f"- {plain}")
            for _start, _end, url in links:
                pdf.link(x=pdf.get_x(), y=pdf.get_y(), w=1, h=1, link=url)
            continue
        if not line.strip():
            pdf.ln(2)
            continue
        plain, links = _strip_inline_links(line)
        pdf.multi_cell(pdf.epw, 5, plain)
        for _start, _end, url in links:
            pdf.link(x=pdf.get_x(), y=pdf.get_y(), w=1, h=1, link=url)
    pdf.output(str(pdf_path))


def render_pdf(markdown_path: Path, *, pdf_path: Path | None = None) -> Path:
    """Render ``markdown_path`` to a sibling ``.pdf`` file."""
    if not fpdf2_available():
        raise PdfUnavailableError(_UNAVAILABLE_MSG)
    dest = pdf_path or markdown_path.with_suffix(".pdf")
    text = markdown_path.read_text(encoding="utf-8")
    _render_markdown_to_pdf(text, dest)
    return dest


def maybe_render_pdf(
    markdown_path: Path,
    *,
    require: bool = False,
) -> Path | None:
    """Render PDF when fpdf2 is installed; silent skip otherwise (FR-011)."""
    if not fpdf2_available():
        if require:
            _LOG.error(_UNAVAILABLE_MSG)
            raise PdfUnavailableError(_UNAVAILABLE_MSG)
        return None
    try:
        return render_pdf(markdown_path)
    except Exception as exc:
        if require:
            raise
        _LOG.warning("PDF render skipped: %s", exc)
        return None


__all__ = [
    "PdfUnavailableError",
    "fpdf2_available",
    "maybe_render_pdf",
    "render_pdf",
]
