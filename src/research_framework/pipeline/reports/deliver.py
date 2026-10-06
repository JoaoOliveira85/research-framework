"""Cycle-end report orchestration (spec 040 — all layers, non-blocking)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from research_framework.pipeline.settings import ReportsSettings, load_vault_settings

from .layer1 import compose_report, write_audit_report
from .mirror import mirror_reports
from .pdf import PdfUnavailableError, maybe_render_pdf
from .smtp import send_report

_LOG = logging.getLogger(__name__)


def _load_reports_settings(vault_dir: Path) -> ReportsSettings | None:
    try:
        return load_vault_settings(vault_dir).reports
    except Exception:
        return None


def deliver_cycle_reports(
    vault_dir: Path,
    cycle_num: int,
    *,
    require_pdf: bool = False,
    rendered_at: datetime | None = None,
) -> Path | None:
    """Render Layer 1 + optional PDF/mirror/SMTP; never raises (SC-006)."""
    stamp = rendered_at or datetime.now(UTC)
    reports_settings = _load_reports_settings(vault_dir)
    try:
        markdown = compose_report(
            vault_dir,
            up_to_cycle=cycle_num,
            rendered_at=stamp,
        )
        md_path = write_audit_report(vault_dir, markdown)
    except Exception as exc:
        _LOG.warning("audit report render failed: %s", exc)
        return None

    pdf_path: Path | None = None
    try:
        pdf_path = maybe_render_pdf(md_path, require=require_pdf)
    except PdfUnavailableError:
        if require_pdf:
            _LOG.error(
                "fpdf2 unavailable; install with pip install research-framework[reports]"
            )
    except Exception as exc:
        _LOG.warning("PDF render failed: %s", exc)

    try:
        mirror_reports(vault_dir, target=None, settings=reports_settings)
    except Exception as exc:
        _LOG.warning("mirror delivery failed: %s", exc)

    try:
        send_report(
            vault_dir,
            markdown_path=md_path,
            pdf_path=pdf_path,
            settings=reports_settings,
        )
    except Exception as exc:
        _LOG.warning("SMTP delivery failed: %s", exc)

    return md_path


__all__ = ["deliver_cycle_reports"]
