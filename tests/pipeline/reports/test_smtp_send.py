"""SMTP delivery tests (spec 040 T018-T020)."""

from __future__ import annotations

from email import message_from_bytes

from research_framework.pipeline.reports.smtp import send_report
from research_framework.pipeline.settings import (
    ReportsSettings,
    ReportsSmtpSettings,
)

from .helpers import write_fixture

pytest_plugins = ["tests.pipeline.reports.helpers"]


class _FakeSMTP:
    instances: list[_FakeSMTP] = []

    def __init__(self, *_args, **_kwargs) -> None:
        self.messages: list[bytes] = []
        self.tls_context = None
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def starttls(self, *, context=None) -> None:
        self.tls_context = context

    def login(self, *_args, **_kwargs) -> None:
        return None

    def send_message(self, msg) -> None:
        self.messages.append(msg.as_bytes())


def _smtp_settings(**overrides) -> ReportsSettings:
    base = ReportsSmtpSettings(
        enabled=True,
        recipient="ops@example.com",
        server="smtp.example.com",
        port=587,
        from_address="vault@example.com",
    )
    for key, val in overrides.items():
        base = ReportsSmtpSettings(**{**base.__dict__, key: val})
    return ReportsSettings(smtp=base)


def test_smtp_send_one_message(reports_vault, monkeypatch, tmp_path) -> None:
    _FakeSMTP.instances.clear()
    monkeypatch.setenv("RF_SMTP_USER", "user")
    monkeypatch.setenv("RF_SMTP_PASSWORD", "secret")
    monkeypatch.setattr(
        "research_framework.pipeline.reports.smtp.smtplib.SMTP", _FakeSMTP
    )
    md = write_fixture(reports_vault)
    pdf = md.with_suffix(".pdf")
    pdf.write_bytes(b"%PDF-1.4 test")
    assert send_report(
        reports_vault,
        markdown_path=md,
        pdf_path=pdf,
        settings=_smtp_settings(),
    )
    sent = message_from_bytes(_FakeSMTP.instances[0].messages[0])
    assert sent["To"] == "ops@example.com"
    raw = _FakeSMTP.instances[0].messages[0].decode("utf-8", errors="replace")
    assert "ops@example.com" in raw
    assert "attachment" in raw.lower()
    assert raw.count("\n") >= 5


def test_smtp_starttls_verifies_the_server_certificate(
    reports_vault, monkeypatch
) -> None:
    """``starttls()`` with no context uses ``ssl._create_stdlib_context()``:
    no certificate or hostname check, so ``RF_SMTP_PASSWORD`` went to
    whoever answered on the path. The context must verify both."""
    import ssl

    _FakeSMTP.instances.clear()
    monkeypatch.setenv("RF_SMTP_USER", "user")
    monkeypatch.setenv("RF_SMTP_PASSWORD", "secret")
    monkeypatch.setattr(
        "research_framework.pipeline.reports.smtp.smtplib.SMTP", _FakeSMTP
    )
    md = write_fixture(reports_vault)
    assert send_report(reports_vault, markdown_path=md, settings=_smtp_settings())
    context = _FakeSMTP.instances[0].tls_context
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_smtp_failure_non_blocking(reports_vault, monkeypatch) -> None:
    monkeypatch.setenv("RF_SMTP_USER", "user")
    monkeypatch.setenv("RF_SMTP_PASSWORD", "secret")

    class _BoomSMTP:
        def __init__(self, *_a, **_k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def starttls(self, *, context=None):
            raise OSError("unreachable")

    monkeypatch.setattr(
        "research_framework.pipeline.reports.smtp.smtplib.SMTP", _BoomSMTP
    )
    md = write_fixture(reports_vault)
    assert (
        send_report(
            reports_vault,
            markdown_path=md,
            settings=_smtp_settings(),
        )
        is False
    )


def test_smtp_bad_credentials_non_blocking(reports_vault, monkeypatch) -> None:
    """Auth failure raises SMTPException (not OSError) — still swallowed (§6)."""
    import smtplib

    monkeypatch.setenv("RF_SMTP_USER", "user")
    monkeypatch.setenv("RF_SMTP_PASSWORD", "wrong")

    class _AuthBoomSMTP:
        def __init__(self, *_a, **_k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def starttls(self, *, context=None):
            return None

        def login(self, *_a, **_k):
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    monkeypatch.setattr(
        "research_framework.pipeline.reports.smtp.smtplib.SMTP", _AuthBoomSMTP
    )
    md = write_fixture(reports_vault)
    assert (
        send_report(
            reports_vault,
            markdown_path=md,
            settings=_smtp_settings(),
        )
        is False
    )


def test_smtp_unconfigured_noop(reports_vault) -> None:
    md = write_fixture(reports_vault)
    assert (
        send_report(
            reports_vault,
            markdown_path=md,
            settings=ReportsSettings(),
        )
        is False
    )
