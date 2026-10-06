"""Cloud mirror delivery tests (spec 040 T015-T017)."""

from __future__ import annotations

from research_framework.pipeline.reports.mirror import mirror_reports
from research_framework.pipeline.settings import ReportsMirrorSettings, ReportsSettings

from .helpers import write_fixture

pytest_plugins = ["tests.pipeline.reports.helpers"]


def test_mirror_copy_all_expected_files(reports_vault, tmp_path) -> None:
    write_fixture(reports_vault)
    target = tmp_path / "mirror"
    assert mirror_reports(reports_vault, target=str(target))
    assert (target / "_pipeline" / "audit-report.md").is_file()
    assert (
        target / "_pipeline" / "digests" / "digest-2026-06-01--2026-06-07.md"
    ).is_file()
    assert (target / "_pipeline" / "cycles" / "cycle-001-report.md").is_file()
    assert not (reports_vault / "mirror-touch").exists()


def test_mirror_failure_non_blocking(reports_vault, tmp_path, monkeypatch) -> None:
    write_fixture(reports_vault)
    target = tmp_path / "locked"

    def _fail_copy(*_args, **_kwargs):
        raise OSError("target unavailable")

    monkeypatch.setattr(
        "research_framework.pipeline.reports.mirror.shutil.copy2", _fail_copy
    )
    monkeypatch.setattr(
        "research_framework.pipeline.reports.mirror.time.sleep", lambda *_: None
    )
    assert mirror_reports(reports_vault, target=str(target)) is False


def test_mirror_unset_target_noop(reports_vault) -> None:
    write_fixture(reports_vault)
    settings = ReportsSettings(mirror=ReportsMirrorSettings(target=None))
    assert mirror_reports(reports_vault, target=None, settings=settings) is False
