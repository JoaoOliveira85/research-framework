"""Tier-2 digest integration tests (spec 035)."""

from __future__ import annotations

import socket
import sqlite3
import subprocess
import time
from datetime import date, datetime
from pathlib import Path

import pytest

from research_framework.cli.digest import _parse_args_range, cmd_digest
from research_framework.pipeline.digest import (
    DateRange,
    build_digest,
    default_output_path,
    run_digest,
)
from research_framework.pipeline.digest.scope import (
    clamp_since,
    enumerate_cycles,
    parse_iso_date,
)

from .digest_helpers import (
    FIXTURE_RANGE,
    FIXTURE_RENDERED_AT,
    normalized_digest,
    render_fixture,
)

pytest_plugins = ["tests.pipeline.digest_helpers"]

_SECTIONS = (
    "## Strongest Signals",
    "## Gaps",
    "## New Notes by Category",
    "## Source Quality Drift",
    "## Coverage Delta",
    "## Cost Summary",
    "## Cycle Index",
)


def test_repeat_run_byte_identical(digest_vault: Path) -> None:
    rendered = datetime.fromisoformat(FIXTURE_RENDERED_AT)
    first, _ = build_digest(
        digest_vault, date_range=FIXTURE_RANGE, rendered_at=rendered
    )
    second, _ = build_digest(
        digest_vault, date_range=FIXTURE_RANGE, rendered_at=rendered
    )
    assert normalized_digest(first) == normalized_digest(second)


def test_digest_offline(digest_vault: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked(*_args, **_kwargs):
        raise OSError("network disabled in test")

    monkeypatch.setattr(socket, "socket", _blocked)
    markdown = render_fixture(digest_vault)
    assert "## Strongest Signals" in markdown


def test_last_week_desugars(
    digest_vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "research_framework.cli.digest._today",
        lambda: date(2026, 6, 7),
    )
    args = type(
        "A",
        (),
        {
            "vault": digest_vault,
            "since": None,
            "last_week": True,
            "last_month": False,
            "last_quarter": False,
            "output": None,
        },
    )()
    dr = _parse_args_range(args)
    assert dr.start == date(2026, 5, 31)
    assert dr.end == date(2026, 6, 7)


def test_no_cycles_exit_zero_no_file(digest_vault: Path) -> None:
    result = run_digest(
        digest_vault,
        date_range=DateRange(start=date(2026, 7, 1), end=date(2026, 7, 7)),
    )
    assert result.exit_code == 0
    assert result.message == "No cycles in scope"
    assert result.output_path is None


def test_future_since_is_a_usage_error(
    digest_vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec 077 D6/T005: a `--since` the operator cannot have meant is class 2
    (usage), not class 1. It used to exit 1 with "No cycles in scope" — the
    same words an empty range prints on stdout with exit 0."""
    monkeypatch.setattr(
        "research_framework.cli.digest._today",
        lambda: date(2026, 6, 1),
    )
    args = type(
        "A",
        (),
        {
            "vault": digest_vault,
            "since": "2026-06-02",
            "last_week": False,
            "last_month": False,
            "last_quarter": False,
            "output": None,
        },
    )()
    assert cmd_digest(args) == 2


def test_scope_filesystem_enumeration(digest_vault: Path) -> None:
    cycles = enumerate_cycles(digest_vault, FIXTURE_RANGE)
    assert [c.number for c in cycles] == [1, 2, 3]
    for cycle in cycles:
        assert cycle.quality_report_path.is_file()


def test_scope_clamps_pre_vault_since(digest_vault: Path) -> None:
    clamped = clamp_since(digest_vault, parse_iso_date("2020-01-01"))
    assert clamped == date(2026, 6, 1)


def test_drift_from_sources_db(digest_vault: Path) -> None:
    markdown = render_fixture(digest_vault)
    assert "youtube-rss" in markdown
    assert "degraded transition" in markdown


def test_drift_db_locked_omits_section(
    digest_vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "research_framework.pipeline.digest.sections._try_connect_sources_db",
        lambda *_args, **_kwargs: None,
    )
    markdown = render_fixture(digest_vault)
    assert "## Source Quality Drift" not in markdown
    assert "sources.db locked" in markdown


def test_drift_db_without_its_tables_omits_section(digest_vault: Path) -> None:
    """A sources.db with no tables in it raised `no such table: sources` out of
    both the drift section and the strongest-signals ranking, and no digest
    was written. Like a locked database, it now omits the drift section with
    a footer note, and the ranking runs without referencing deltas."""
    db = digest_vault / "_pipeline" / "sources.db"
    db.unlink()
    sqlite3.connect(db).close()

    markdown = render_fixture(digest_vault)

    assert "## Source Quality Drift" not in markdown
    assert "sources.db unreadable" in markdown
    assert "no such table: sources" in markdown


def test_end_to_end_fixture(digest_vault: Path, tmp_path: Path) -> None:
    out = default_output_path(digest_vault, FIXTURE_RANGE)
    markdown = render_fixture(digest_vault, output=out)
    assert out.is_file()
    assert out.name == "digest-2026-06-01--2026-06-07.md"
    for heading in _SECTIONS:
        assert heading in markdown
    assert "Alpha Signal" in markdown
    assert "services" in markdown.lower()
    assert "$0.60" in markdown or "0.60" in markdown


def test_missing_cycle_report_footer_warning(digest_vault: Path) -> None:
    markdown = render_fixture(digest_vault)
    assert "cycle-003-report.md missing" in markdown
    assert "(no report)" in markdown


def test_no_agent_dispatch(digest_vault: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    real_run = subprocess.run

    def _spy(cmd, *args, **kwargs):
        cmd_text = " ".join(str(c) for c in cmd) if isinstance(cmd, list) else str(cmd)
        if "agent_call" in cmd_text or " claude" in cmd_text or " codex" in cmd_text:
            calls.append(cmd_text)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", _spy)
    render_fixture(digest_vault)
    assert calls == []


def test_digest_under_5s(digest_vault: Path) -> None:
    start = time.perf_counter()
    render_fixture(digest_vault)
    assert time.perf_counter() - start < 5.0


def test_coverage_renders_as_percentages_of_the_category_target(
    digest_vault: Path,
) -> None:
    """The fixture's quality reports carry ``fill_pct`` on the stored 0..1 scale.

    The digest printed that fraction with a ``%`` after it (half-filled read
    "0.5%") and never rendered a real percentage for a pipeline-written report.
    """
    markdown = render_fixture(digest_vault)

    assert (
        "- **services** (regressed): 50% → 25% (target 4) — last touched cycle 3"
        in markdown
    )
    assert "- **flows** (stagnant): 0% → 0% (target 3)" in markdown
    assert "| concepts | 20% | 40% | +20% |" in markdown
    assert "| services | 50% | 25% | -25% |" in markdown


def _section(markdown: str, heading: str) -> str:
    start = markdown.index(heading)
    return markdown[start : markdown.index("\n## ", start + 1)]


def test_notes_are_read_from_the_corpus_folder_the_vault_declares(
    digest_vault: Path,
) -> None:
    """``vault.corpus_dir`` names the corpus folder; ``data_vault`` is the default.

    The digest listed notes from ``data_vault/`` whatever the vault declared,
    so a vault with its own corpus folder got "No data in scope." under
    Strongest Signals and New Notes by Category.
    """
    expected = render_fixture(digest_vault)
    (digest_vault / "data_vault").rename(digest_vault / "notes")
    (digest_vault / "_pipeline" / "spec-parse.json").write_text(
        '{"vault_corpus_dir": "notes"}', encoding="utf-8"
    )

    markdown = render_fixture(digest_vault)

    for heading in ("## Strongest Signals", "## New Notes by Category"):
        assert "No data in scope." not in _section(expected, heading)
        assert _section(markdown, heading) == _section(expected, heading)


def test_schema_migrated_annotation(digest_vault: Path) -> None:
    targets = digest_vault / "coverage-targets.json"
    text = targets.read_text(encoding="utf-8")
    targets.write_text(
        text.replace('"cycle_number"', '"schema_version_legacy"') + "\n",
        encoding="utf-8",
    )
    markdown = render_fixture(digest_vault)
    assert "## Coverage Delta" in markdown
    assert "[schema-migrated]" in markdown
