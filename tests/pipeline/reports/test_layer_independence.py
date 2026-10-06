"""Layer independence integration test (spec 040 T021 / SC-006)."""

from __future__ import annotations

from research_framework.pipeline.reports.deliver import deliver_cycle_reports

pytest_plugins = ["tests.pipeline.reports.helpers"]


def test_layer_failures_do_not_block_markdown(reports_vault, monkeypatch) -> None:
    monkeypatch.setattr(
        "research_framework.pipeline.reports.deliver.maybe_render_pdf",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("pdf boom")),
    )
    monkeypatch.setattr(
        "research_framework.pipeline.reports.deliver.mirror_reports",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("mirror boom")),
    )
    monkeypatch.setattr(
        "research_framework.pipeline.reports.deliver.send_report",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("smtp boom")),
    )
    path = deliver_cycle_reports(reports_vault, 3)
    assert path is not None
    assert path.is_file()
    assert "## Coverage Delta" in path.read_text(encoding="utf-8")
