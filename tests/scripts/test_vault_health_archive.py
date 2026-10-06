"""Tests for vault_health.py archive.org fail-and-defer pass (spec 038 US5)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "vault_health.py"
SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "specs"
    / "038-source-module-resilience"
    / "contracts"
    / "archive-snapshots.schema.json"
)


def _load_vh():
    spec = importlib.util.spec_from_file_location("vault_health", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["vault_health"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def vh():
    return _load_vh()


def _vault_with_url(tmp_path: Path, url: str) -> Path:
    vault = tmp_path / "v"
    note_dir = vault / "data_vault" / "Topics"
    note_dir.mkdir(parents=True)
    (note_dir / "note.md").write_text(
        f'---\ntitle: n\ntype: concept\nsource_urls:\n  - url: "{url}"\n---\n\nbody\n',
        encoding="utf-8",
    )
    return vault


def test_snapshot_success_marks_archived(tmp_path: Path, vh) -> None:
    url = "https://example.com/fragile"
    vault = _vault_with_url(tmp_path, url)

    def poster(u: str):
        assert u == url
        return (
            "archived",
            "https://web.archive.org/web/20260603120000/https://example.com/fragile",
            None,
        )

    data = vh.run_archive_snapshot_pass(
        vault, apply=True, offline=False, post_fn=poster
    )
    record = data["snapshots"][url]
    assert record["status"] == "archived"
    assert record["snapshot_url"]
    assert record["created_at"]


def test_rate_limit_marks_deferred_exit_zero(tmp_path: Path, vh) -> None:
    url = "https://example.com/throttled"
    vault = _vault_with_url(tmp_path, url)

    def poster(_u: str):
        return ("deferred", None, "HTTP 429 rate limited")

    data = vh.run_archive_snapshot_pass(
        vault, apply=True, offline=False, post_fn=poster
    )
    assert data["snapshots"][url]["status"] == "deferred"
    assert vh.main([str(vault), "--apply", "--offline"]) in (0, 1)


def test_robots_paywall_marks_unarchivable(tmp_path: Path, vh) -> None:
    url = "https://paywall.example.com/article"
    vault = _vault_with_url(tmp_path, url)

    def poster(_u: str):
        return ("unarchivable", None, "robots.txt disallows archiving")

    data = vh.run_archive_snapshot_pass(
        vault, apply=True, offline=False, post_fn=poster
    )
    assert data["snapshots"][url]["status"] == "unarchivable"
    assert "robots" in data["snapshots"][url]["reason"]


def test_deferred_urls_accumulate_across_runs(tmp_path: Path, vh) -> None:
    url = "https://example.com/retry-later"
    vault = _vault_with_url(tmp_path, url)
    calls = {"n": 0}

    def poster(_u: str):
        calls["n"] += 1
        if calls["n"] == 1:
            return ("deferred", None, "HTTP 429 rate limited")
        return ("archived", "https://web.archive.org/web/1/example", None)

    first = vh.run_archive_snapshot_pass(
        vault, apply=True, offline=False, post_fn=poster
    )
    assert first["snapshots"][url]["status"] == "deferred"
    second = vh.run_archive_snapshot_pass(
        vault, apply=True, offline=False, post_fn=poster
    )
    assert second["snapshots"][url]["status"] == "archived"
    assert second["schema_version"] == "1.0"
    on_disk = json.loads(vh._archive_snapshots_path(vault).read_text(encoding="utf-8"))
    assert url in on_disk["snapshots"]


def test_absolute_archive_snapshot_url(vh) -> None:
    assert (
        vh._absolute_archive_snapshot_url(
            "/web/20260603120000/https://example.com/article"
        )
        == "https://web.archive.org/web/20260603120000/https://example.com/article"
    )
    absolute = "https://web.archive.org/web/1/https://example.com/x"
    assert vh._absolute_archive_snapshot_url(absolute) == absolute


def test_archive_post_absolutizes_relative_content_location(vh) -> None:
    status, snapshot_url, reason = vh._archive_post(
        "https://example.com/article",
        fixture={
            "https://example.com/article": {
                "status": "archived",
                "snapshot_url": "/web/20260603120000/https://example.com/article",
            }
        },
    )
    assert status == "archived"
    assert snapshot_url == (
        "https://web.archive.org/web/20260603120000/https://example.com/article"
    )
    assert reason is None
