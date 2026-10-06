"""SMTP report delivery (spec 040 FR-016..018)."""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from research_framework.pipeline.settings import ReportsSettings

_LOG = logging.getLogger(__name__)


def _smtp_credentials() -> tuple[str | None, str | None]:
    return os.environ.get("RF_SMTP_USER"), os.environ.get("RF_SMTP_PASSWORD")


def _five_line_summary(markdown_path: Path) -> str:
    text = markdown_path.read_text(encoding="utf-8")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    picked: list[str] = []
    for line in lines:
        if line.startswith("#"):
            continue
        if line.startswith("_rendered-at:"):
            continue
        picked.append(line)
        if len(picked) >= 5:
            break
    while len(picked) < 5:
        picked.append("(no further summary lines)")
    return "\n".join(picked[:5])


def send_report(
    vault_dir: Path,
    *,
    markdown_path: Path,
    pdf_path: Path | None = None,
    settings: ReportsSettings | None = None,
) -> bool:
    """Send one report email when SMTP is enabled and creds are present."""
    if settings is None or not settings.smtp.enabled:
        return False
    smtp = settings.smtp
    if not smtp.recipient or not smtp.server or smtp.port is None:
        _LOG.warning("SMTP enabled but recipient/server/port incomplete — skipping")
        return False
    user, password = _smtp_credentials()
    if not user or not password:
        _LOG.warning("SMTP enabled but RF_SMTP_USER/PASSWORD unset — skipping")
        return False
    msg = EmailMessage()
    msg["Subject"] = f"Vault report — {vault_dir.name}"
    msg["From"] = smtp.from_address or user
    msg["To"] = smtp.recipient
    msg.set_content(_five_line_summary(markdown_path))
    attach = pdf_path if pdf_path and pdf_path.is_file() else markdown_path
    msg.add_attachment(
        attach.read_bytes(),
        maintype="application",
        subtype="octet-stream",
        filename=attach.name,
    )
    try:
        with smtplib.SMTP(smtp.server, smtp.port, timeout=30) as client:
            # No context means ssl._create_stdlib_context(): no certificate or
            # hostname check, so the login below would go to any MITM.
            client.starttls(context=ssl.create_default_context())
            client.login(user, password)
            client.send_message(msg)
        return True
    except (OSError, smtplib.SMTPException) as exc:
        # OSError covers an unreachable/closed server; SMTPException covers
        # auth + protocol failures (e.g. bad creds → SMTPAuthenticationError,
        # which is NOT an OSError). Contract §6: any failure logs + continues.
        _LOG.warning("SMTP delivery failed: %s", exc)
        return False


__all__ = ["send_report"]
