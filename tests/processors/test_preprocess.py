"""Tests for research_framework.processors.preprocess."""

from __future__ import annotations

from pathlib import Path

from research_framework.processors.preprocess import (
    PreprocessResult,
    _dedupe_by_content_hash,
    _dedupe_by_url,
    _is_english,
    _strip_reddit_metadata,
    _strip_srt_artifacts,
    preprocess,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_raw_item(
    vault: Path,
    source_kind: str,
    stem: str,
    body: str = "Hello world this is English content.",
    source_id: str | None = None,
    collected_at: str = "2026-05-01",
    original_url: str = "https://example.com/item",
) -> Path:
    """Create a synthetic raw pipeline item."""
    sid = source_id or stem
    raw_dir = vault / "_pipeline" / "raw" / source_kind
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{stem}.md"
    path.write_text(
        f"""---
source_kind: {source_kind}
source_id: {sid}
collected_at: {collected_at}
original_url: {original_url}
title: Test Item {stem}
---

{body}
""",
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestIsEnglish:
    def test_english_text(self):
        assert _is_english("Hello world, this is a test of English language detection.")

    def test_non_english_text(self):
        # Mostly non-ASCII (Cyrillic)
        assert not _is_english("Привет мир, это тест обнаружения русского языка." * 5)

    def test_short_text_passes(self):
        assert _is_english("Hi")  # < 20 alpha chars — benefit of the doubt


class TestStripRedditMetadata:
    def test_strips_score_line(self):
        text = "**Score:** 123\nActual content here."
        result = _strip_reddit_metadata(text)
        assert "**Score:**" not in result
        assert "Actual content here." in result

    def test_strips_user_header(self):
        text = "**u/someuser** (45 likes):\nComment body."
        result = _strip_reddit_metadata(text)
        assert "**u/someuser**" not in result
        assert "Comment body." in result


class TestStripSrtArtifacts:
    def test_strips_timestamps(self):
        text = "00:00:01,000 --> 00:00:03,000\nHello world"
        result = _strip_srt_artifacts(text)
        assert "-->" not in result
        assert "Hello world" in result

    def test_strips_sequence_numbers(self):
        text = "1\n00:00:01,000 --> 00:00:02,000\nContent"
        result = _strip_srt_artifacts(text)
        lines = [line for line in result.splitlines() if line.strip()]
        assert "1" not in lines

    def test_strips_html_tags(self):
        text = "<i>italic text</i>"
        result = _strip_srt_artifacts(text)
        assert "<i>" not in result
        assert "italic text" in result


class TestDedupeByContentHash:
    def test_keeps_unique_items(self, tmp_path):
        make_raw_item(tmp_path, "web", "item1", body="Unique content A")
        make_raw_item(tmp_path, "web", "item2", body="Unique content B")
        raw_files = list((tmp_path / "_pipeline" / "raw" / "web").glob("*.md"))
        kept, dupes = _dedupe_by_content_hash(raw_files)
        assert len(kept) == 2
        assert dupes == 0

    def test_removes_duplicates(self, tmp_path):
        # Same body → same hash → one duplicate
        make_raw_item(tmp_path, "web", "item1", body="Identical content here.")
        make_raw_item(tmp_path, "web", "item2", body="Identical content here.")
        raw_files = sorted((tmp_path / "_pipeline" / "raw" / "web").glob("*.md"))
        kept, dupes = _dedupe_by_content_hash(raw_files)
        assert len(kept) == 1
        assert dupes == 1


class TestDedupeByUrl:
    def test_removes_url_duplicates(self, tmp_path):
        make_raw_item(tmp_path, "web", "item1", original_url="https://example.com/page")
        make_raw_item(tmp_path, "web", "item2", original_url="https://example.com/page")
        raw_files = sorted((tmp_path / "_pipeline" / "raw" / "web").glob("*.md"))
        kept, dupes = _dedupe_by_url(raw_files)
        assert len(kept) == 1
        assert dupes == 1

    def test_keeps_different_urls(self, tmp_path):
        make_raw_item(tmp_path, "web", "item1", original_url="https://example.com/a")
        make_raw_item(tmp_path, "web", "item2", original_url="https://example.com/b")
        raw_files = sorted((tmp_path / "_pipeline" / "raw" / "web").glob("*.md"))
        kept, dupes = _dedupe_by_url(raw_files)
        assert len(kept) == 2
        assert dupes == 0


# ---------------------------------------------------------------------------
# Integration-style: preprocess() end-to-end
# ---------------------------------------------------------------------------


class TestPreprocessFunction:
    def test_processes_raw_files(self, tmp_path):
        make_raw_item(
            tmp_path, "web", "article1", body="Article about machine learning trends."
        )
        make_raw_item(
            tmp_path,
            "youtube",
            "video1",
            body="Video transcript about neural networks.",
        )

        result = preprocess(tmp_path)

        assert isinstance(result, PreprocessResult)
        assert result.files_processed == 2
        assert result.errors == ()

        # Excerpt files should exist.
        assert (
            tmp_path / "_pipeline" / "extracted" / "excerpts" / "web" / "article1.txt"
        ).exists()
        assert (
            tmp_path / "_pipeline" / "extracted" / "excerpts" / "youtube" / "video1.txt"
        ).exists()

    def test_skips_already_processed(self, tmp_path):
        make_raw_item(tmp_path, "web", "article1")
        # First run
        result1 = preprocess(tmp_path)
        assert result1.files_processed == 1
        # Second run — should skip
        result2 = preprocess(tmp_path)
        assert result2.files_processed == 0
        assert result2.files_skipped == 1

    def test_force_reprocesses(self, tmp_path):
        make_raw_item(tmp_path, "web", "article1")
        preprocess(tmp_path)
        result = preprocess(tmp_path, force=True)
        assert result.files_processed == 1

    def test_dry_run_writes_nothing(self, tmp_path):
        make_raw_item(tmp_path, "web", "article1")
        result = preprocess(tmp_path, dry_run=True)
        assert result.files_processed == 0
        assert not (
            tmp_path / "_pipeline" / "extracted" / "excerpts" / "web" / "article1.txt"
        ).exists()

    def test_deduplication_collapses_duplicates(self, tmp_path):
        # Two items with identical bodies → only one should be processed.
        make_raw_item(tmp_path, "web", "item1", body="Identical content in both files.")
        make_raw_item(tmp_path, "web", "item2", body="Identical content in both files.")

        result = preprocess(tmp_path, dedupe_strategy="content_hash")

        assert result.duplicates_removed == 1
        assert result.files_processed == 1

    def test_non_english_flagged(self, tmp_path):
        non_english = "Привет мир это тест обнаружения языка " * 10
        make_raw_item(tmp_path, "web", "russian", body=non_english)
        result = preprocess(tmp_path)
        assert result.non_english >= 1

    def test_returns_result_with_no_raw_files(self, tmp_path):
        result = preprocess(tmp_path)
        assert result.files_processed == 0
        assert result.errors == ()

    def test_missing_required_frontmatter_produces_errors(self, tmp_path):
        # Write a raw item missing source_kind / source_id / collected_at.
        raw_dir = tmp_path / "_pipeline" / "raw" / "web"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "bad.md").write_text(
            "---\ntitle: Missing fields\n---\n\nBody.", encoding="utf-8"
        )
        result = preprocess(tmp_path)
        # Validation errors should be present.
        assert any(
            "source_kind" in e or "source_id" in e or "collected_at" in e
            for e in result.errors
        )


def test_explicit_url_dedupe_strategy_is_honoured(tmp_path):
    """Same URL, different bodies: only the ``url`` strategy collapses them.
    ``cfg.get("dedupe_strategy", dedupe_strategy)`` always returned the
    ``content_hash`` default, so an explicit ``url`` (and the CLI flag) was
    silently ignored."""
    make_raw_item(
        tmp_path, "web", "a", body="First body.", original_url="https://x.io/p"
    )
    make_raw_item(
        tmp_path, "web", "b", body="Other body.", original_url="https://x.io/p"
    )

    result = preprocess(tmp_path, dedupe_strategy="url")

    assert result.duplicates_removed == 1
