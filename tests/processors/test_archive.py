"""Tests for research_framework.processors.archive."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from research_framework.processors.archive import ArchiveResult, archive

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_raw_item(
    vault: Path,
    source_kind: str,
    stem: str,
    collected_at: str = "2025-01-01",
    original_url: str = "https://example.com/item",
    body: str = "Content body.",
) -> Path:
    raw_dir = vault / "_pipeline" / "raw" / source_kind
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{stem}.md"
    path.write_text(
        f"""---
source_kind: {source_kind}
source_id: {stem}
collected_at: {collected_at}
original_url: {original_url}
title: Test {stem}
---

{body}
""",
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestArchiveFunction:
    def test_moves_old_item_to_archive(self, tmp_path):
        """A raw item older than after_days is moved to the archive dir."""
        # collected_at well in the past
        raw_path = make_raw_item(
            tmp_path, "web", "old-article", collected_at="2024-01-15"
        )

        result = archive(tmp_path, after_days=90)

        assert isinstance(result, ArchiveResult)
        assert result.files_archived == 1
        assert result.files_skipped == 0
        # Raw file should be gone.
        assert not raw_path.exists()
        # Archive file should exist under the right month dir.
        archive_path = (
            tmp_path / "_pipeline" / "archive" / "2024-01" / "web" / "old-article.md"
        )
        assert archive_path.exists()

    def test_skips_recent_item(self, tmp_path):
        """A raw item younger than after_days is NOT archived."""
        today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
        raw_path = make_raw_item(tmp_path, "web", "new-article", collected_at=today)

        result = archive(tmp_path, after_days=90)

        assert result.files_archived == 0
        assert result.files_skipped == 1
        assert raw_path.exists()  # still there

    def test_dry_run_does_not_move(self, tmp_path):
        """Dry run reports candidates but leaves files in place."""
        raw_path = make_raw_item(
            tmp_path, "web", "old-article", collected_at="2024-01-15"
        )

        result = archive(tmp_path, after_days=90, dry_run=True)

        assert result.files_archived == 1  # counted but not moved
        assert raw_path.exists()  # still in raw dir

    def test_archive_correct_month_dir(self, tmp_path):
        """Archive lands in the directory matching collected_at YYYY-MM."""
        make_raw_item(tmp_path, "youtube", "video-abc", collected_at="2025-03-20")
        archive(tmp_path, after_days=30)
        dest = (
            tmp_path / "_pipeline" / "archive" / "2025-03" / "youtube" / "video-abc.md"
        )
        assert dest.exists()

    def test_idempotent_on_already_archived(self, tmp_path):
        """If the item is already in the archive, the raw copy is removed cleanly."""
        raw_path = make_raw_item(
            tmp_path, "web", "old-article", collected_at="2024-01-15"
        )
        # First run — moves the file.
        archive(tmp_path, after_days=90)
        # Restore raw file to simulate a re-run scenario.
        raw_path.write_text(
            "---\nsource_kind: web\nsource_id: old-article\ncollected_at: 2024-01-15\n---\n\nBody.",
            encoding="utf-8",
        )

        result2 = archive(tmp_path, after_days=90)

        assert result2.files_archived >= 1
        assert not raw_path.exists()

    def test_no_raw_dir_returns_empty_result(self, tmp_path):
        result = archive(tmp_path, after_days=90)
        assert result.files_processed == 0
        assert result.files_archived == 0
        assert result.errors == ()

    def test_multiple_source_kinds(self, tmp_path):
        make_raw_item(tmp_path, "web", "old-web", collected_at="2024-06-01")
        make_raw_item(tmp_path, "youtube", "old-video", collected_at="2024-06-01")
        result = archive(tmp_path, after_days=30)
        assert result.files_archived == 2

    def test_source_type_filter(self, tmp_path):
        make_raw_item(tmp_path, "web", "old-web", collected_at="2024-06-01")
        make_raw_item(tmp_path, "youtube", "old-video", collected_at="2024-06-01")
        result = archive(tmp_path, after_days=30, source_types=["web"])
        assert result.files_archived == 1
        # youtube item still in raw dir
        assert (tmp_path / "_pipeline" / "raw" / "youtube" / "old-video.md").exists()


def test_explicit_after_days_is_honoured(tmp_path):
    """``cfg.get("after_days", after_days)`` always found the key in
    ``PROCESSOR_DEFAULTS``, so an explicit argument (and the CLI's
    ``--after-days``) was silently replaced by 90."""
    collected = (
        datetime.now(UTC).date().fromordinal(datetime.now(UTC).date().toordinal() - 30)
    )
    make_raw_item(tmp_path, "web", "month-old", collected_at=collected.isoformat())

    result = archive(tmp_path, after_days=7)

    assert result.files_archived == 1
    assert result.files_skipped == 0


def test_malformed_collected_at_cannot_steer_the_destination(tmp_path):
    """The month directory was ``collected_at[:7]`` unchecked, so a raw item
    whose ``collected_at`` began with ``../../`` (or ``/``) was moved outside
    ``_pipeline/archive/``."""
    import os
    import re

    raw = make_raw_item(tmp_path, "web", "odd", collected_at="../../escape")
    old = datetime.now(UTC).timestamp() - 400 * 86400
    os.utime(raw, (old, old))

    result = archive(tmp_path, after_days=90)

    assert result.files_archived == 1
    archived = list((tmp_path / "_pipeline" / "archive").rglob("odd.md"))
    assert len(archived) == 1, list(tmp_path.rglob("odd.md"))
    month = archived[0].parent.parent.name
    assert re.fullmatch(r"\d{4}-\d{2}", month), month
