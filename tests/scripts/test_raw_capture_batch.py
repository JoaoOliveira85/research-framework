"""Tests for scripts/raw_capture_batch.py (spec 038 US3)."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "raw_capture_batch.py"
RUN_DATE = datetime(2026, 6, 3, 20, 0, 0, tzinfo=UTC)


def _load_module():
    spec = importlib.util.spec_from_file_location("raw_capture_batch", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["raw_capture_batch"] = module
    root_src = Path(__file__).resolve().parents[2] / "src"
    if str(root_src) not in sys.path:
        sys.path.insert(0, str(root_src))
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def rcb():
    return _load_module()


def _build_vault(tmp_path: Path, *, notes: list[tuple[str, str]]) -> Path:
    vault = tmp_path / "vault"
    notes_dir = vault / "data_vault" / "Topics"
    notes_dir.mkdir(parents=True)
    for name, url in notes:
        (notes_dir / name).write_text(
            f'---\ntitle: "{name}"\ntype: concept\nsource_urls:\n  - "{url}"\n---\n\nbody\n',
            encoding="utf-8",
        )
    return vault


def test_dedup_by_sha256_single_capture_for_duplicate_urls(
    tmp_path: Path, rcb, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "https://example.com/shared-post"
    notes = [(f"note-{i:02d}.md", url) for i in range(50)]
    vault = _build_vault(tmp_path, notes=notes)
    calls: list[str] = []

    def fake_capture(u: str, raw_data_dir: Path, source_type: str = "web"):
        calls.append(u)
        payload = raw_data_dir / "2026" / "06" / "post-ab12cd34.html"
        payload.parent.mkdir(parents=True, exist_ok=True)
        payload.write_text("<html></html>", encoding="utf-8")
        return payload, {"payload_kind": "rich", "filename": payload.name}

    monkeypatch.setattr(rcb, "_load_capture", lambda: fake_capture)
    code, manifest = rcb.run_batch(vault, run_date=RUN_DATE, capture_fn=fake_capture)
    assert code == 0
    assert len(calls) == 1
    digest = rcb.url_digest(url)
    entry = manifest["captures"][digest]
    assert entry["status"] == "OK"
    assert len(entry["citing_notes"]) == 50


def test_manifest_schema_and_status_enum(tmp_path: Path, rcb) -> None:
    vault = _build_vault(
        tmp_path,
        notes=[
            ("one.md", "https://example.com/a"),
            ("two.md", "https://example.com/b"),
        ],
    )

    def fake_capture(u: str, raw_data_dir: Path, source_type: str = "web"):
        payload = raw_data_dir / "2026" / "06" / f"{rcb.url_digest(u)[:8]}.html"
        payload.parent.mkdir(parents=True, exist_ok=True)
        payload.write_text("x", encoding="utf-8")
        return payload, {"payload_kind": "thin", "filename": payload.name}

    code, manifest = rcb.run_batch(vault, run_date=RUN_DATE, capture_fn=fake_capture)
    assert code == 0
    assert manifest["schema_version"] == "1.0"
    for entry in manifest["captures"].values():
        assert entry["status"] in {"OK", "FAILED", "PENDING"}
    assert all(e["status"] == "OK" for e in manifest["captures"].values())


def test_idempotent_and_incremental_resume(tmp_path: Path, rcb) -> None:
    vault = _build_vault(
        tmp_path,
        notes=[
            ("ok.md", "https://example.com/ok"),
            ("retry.md", "https://example.com/retry"),
            ("pending.md", "https://example.com/pending"),
        ],
    )
    mpath = rcb.manifest_path(vault, run_date=RUN_DATE)
    mpath.parent.mkdir(parents=True, exist_ok=True)
    ok_digest = rcb.url_digest("https://example.com/ok")
    retry_digest = rcb.url_digest("https://example.com/retry")
    pending_digest = rcb.url_digest("https://example.com/pending")
    mpath.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "cycle": None,
                "generated_at": "2026-06-03T19:00:00Z",
                "captures": {
                    ok_digest: {
                        "url": "https://example.com/ok",
                        "status": "OK",
                        "captured_path": "raw_data/2026/06/ok.html",
                        "captured_at": "2026-06-03T19:00:01Z",
                        "payload_kind": "rich",
                        "citing_notes": ["data_vault/Topics/ok.md"],
                    },
                    retry_digest: {
                        "url": "https://example.com/retry",
                        "status": "FAILED",
                        "captured_path": None,
                        "captured_at": None,
                        "error": "timeout",
                        "citing_notes": ["data_vault/Topics/retry.md"],
                    },
                    pending_digest: {
                        "url": "https://example.com/pending",
                        "status": "PENDING",
                        "captured_path": None,
                        "captured_at": None,
                        "citing_notes": ["data_vault/Topics/pending.md"],
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    calls: list[str] = []

    def fake_capture(u: str, raw_data_dir: Path, source_type: str = "web"):
        calls.append(u)
        if u == "https://example.com/retry":
            payload = raw_data_dir / "2026" / "06" / "retry.html"
            payload.parent.mkdir(parents=True, exist_ok=True)
            payload.write_text("ok", encoding="utf-8")
            return payload, {"payload_kind": "rich", "filename": payload.name}
        if u == "https://example.com/pending":
            return None
        raise AssertionError(f"unexpected capture for {u}")

    code, manifest = rcb.run_batch(vault, run_date=RUN_DATE, capture_fn=fake_capture)
    assert code == 0
    assert "https://example.com/ok" not in calls
    assert calls.count("https://example.com/retry") == 1
    assert calls.count("https://example.com/pending") == 1
    assert manifest["captures"][ok_digest]["status"] == "OK"
    assert manifest["captures"][retry_digest]["status"] == "OK"
    assert manifest["captures"][pending_digest]["status"] == "FAILED"
    assert mpath.is_file()


def test_exit_zero_dry_run_and_bad_args_exit_two(
    tmp_path: Path, rcb, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _build_vault(tmp_path, notes=[("a.md", "https://example.com/fail")])

    def fail_capture(u: str, raw_data_dir: Path, source_type: str = "web"):
        return None

    code, _manifest = rcb.run_batch(vault, run_date=RUN_DATE, capture_fn=fail_capture)
    assert code == 0

    dry_vault = _build_vault(
        tmp_path / "dry", notes=[("b.md", "https://example.com/x")]
    )
    dry_code, _ = rcb.run_batch(dry_vault, run_date=RUN_DATE, dry_run=True)
    assert dry_code == 0
    assert not (dry_vault / "raw_data").exists()

    assert rcb.main(["--vault", str(tmp_path / "missing")]) == 2

    bad_vault = tmp_path / "bad-fm"
    bad_vault.mkdir()
    bad_note = bad_vault / "note.md"
    bad_note.write_text("---\n[not: a mapping\n---\n", encoding="utf-8")

    def broken_collect(*args, **kwargs):
        from research_framework.vault.frontmatter import FrontmatterParseError

        raise FrontmatterParseError("bad yaml")

    monkeypatch.setattr(rcb, "collect_urls", broken_collect)
    assert rcb.run_batch(bad_vault, run_date=RUN_DATE)[0] == 2


def test_cycle_filter_excludes_notes_without_created_at_cycle(
    tmp_path: Path, rcb
) -> None:
    vault = tmp_path / "vault"
    notes_dir = vault / "data_vault" / "Topics"
    notes_dir.mkdir(parents=True)
    (notes_dir / "legacy.md").write_text(
        '---\ntitle: legacy\ntype: concept\nsource_urls:\n  - "https://example.com/legacy"\n---\n\nbody\n',
        encoding="utf-8",
    )
    (notes_dir / "cycle-5.md").write_text(
        '---\ntitle: new\ntype: concept\nsource_urls:\n  - "https://example.com/new"\nlifecycle:\n  created_at_cycle: 5\n---\n\nbody\n',
        encoding="utf-8",
    )
    (notes_dir / "other-cycle.md").write_text(
        '---\ntitle: old\ntype: concept\nsource_urls:\n  - "https://example.com/old"\nlifecycle:\n  created_at_cycle: 4\n---\n\nbody\n',
        encoding="utf-8",
    )

    urls = rcb.collect_urls(vault, cycle=5)
    assert "https://example.com/new" in urls
    assert "https://example.com/legacy" not in urls
    assert "https://example.com/old" not in urls


def test_date_only_since_is_read_as_utc(tmp_path: Path, rcb) -> None:
    """``--since 2026-01-01`` parses to a naive datetime; comparing it with
    the aware note mtime raised TypeError inside a bare ``except Exception``,
    so the documented date form exited 2 with no message."""
    vault = _build_vault(tmp_path, notes=[("a.md", "https://example.com/a")])

    assert rcb.main(["--vault", str(vault), "--since", "2000-01-01", "--dry-run"]) == 0
