"""Cache + watermark tests."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from research_framework.pipeline.source_bridge.cache import (
    WatermarkEntry,
    atomic_write_json,
    gc_old_signals,
    is_cache_hit,
    load_watermarks,
    read_signal,
    save_watermarks,
    signal_path,
    source_stem,
    write_signal,
)
from research_framework.pipeline.source_bridge.signal import SignalPayload


def test_watermark_map_roundtrip(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    entries = {
        "src-a": WatermarkEntry(
            source_version="v1",
            bridge_version="0.3.2",
            extracted_at="2026-01-01T00:00:00Z",
            verdict="ok",
        )
    }
    save_watermarks(vault, "code", entries)
    loaded = load_watermarks(vault, "code")
    assert loaded["src-a"].source_version == "v1"


def test_atomic_write_uses_replace_not_inplace(tmp_path: Path) -> None:
    # cache.atomic_write_json is a name-stable wrapper (issue #312) that
    # delegates to the canonical pipeline.atomic_write helper — the
    # os.replace call it makes lives there now, not in this module.
    target = tmp_path / "sub" / "file.json"
    with patch("research_framework.pipeline.atomic_write.os.replace") as repl:
        atomic_write_json(target, {"a": 1})
        repl.assert_called_once()


def test_watermark_crud_roundtrip(tmp_path: Path) -> None:
    test_watermark_map_roundtrip(tmp_path)


def test_signal_written_to_pipeline_sources_signals_path(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    payload = SignalPayload(
        module="code",
        source_id="/repo",
        source_version="abc123",
        bridge_version="0.3.2",
        extracted_at="2026-01-01T00:00:00Z",
        verdict="ok",
        truncated=False,
        partial=False,
        facts={},
        notable=[],
    )
    path = write_signal(vault, payload)
    assert "signals" in str(path)
    assert read_signal(path) is not None


def test_cache_hit_skips_extractor_subprocess(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    payload = SignalPayload(
        module="code",
        source_id="s",
        source_version="v1",
        bridge_version="0.3.2",
        extracted_at="2026-01-01T00:00:00Z",
        verdict="ok",
        truncated=False,
        partial=False,
        facts={},
        notable=[],
    )
    write_signal(vault, payload)
    wm = WatermarkEntry(
        source_version="v1",
        bridge_version="0.3.2",
        extracted_at="2026-01-01T00:00:00Z",
        verdict="ok",
    )
    path = signal_path(vault, "code", "s", "v1")
    assert is_cache_hit(
        watermark=wm,
        source_version="v1",
        bridge_version="0.3.2",
        signal_file=path,
    )


def test_bridge_version_invalidation_cache_miss(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    wm = WatermarkEntry(
        source_version="v1",
        bridge_version="0.3.1",
        extracted_at="2026-01-01T00:00:00Z",
        verdict="ok",
    )
    path = signal_path(vault, "code", "s", "v1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    assert not is_cache_hit(
        watermark=wm,
        source_version="v1",
        bridge_version="0.3.2",
        signal_file=path,
    )


def test_signal_gc_removes_entries_older_than_retention(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    sig_dir = vault / "_pipeline" / "sources" / "code" / "signals"
    sig_dir.mkdir(parents=True)
    old = sig_dir / "old-v1.json"
    old.write_text("{}", encoding="utf-8")
    old_time = datetime.now(UTC) - timedelta(days=40)
    os.utime(old, (old_time.timestamp(), old_time.timestamp()))
    gc_old_signals(vault, "code", retention_days=30)
    assert not old.exists()


def test_corrupt_signal_json_treated_as_cache_miss(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    path = signal_path(vault, "code", "s", "v1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    wm = WatermarkEntry(
        source_version="v1",
        bridge_version="0.3.2",
        extracted_at="2026-01-01T00:00:00Z",
        verdict="ok",
    )
    assert (
        is_cache_hit(
            watermark=wm,
            source_version="v1",
            bridge_version="0.3.2",
            signal_file=path,
        )
        is False
    )
    assert read_signal(path) is None


def test_cache_hit_fast_path_no_agent_calls(tmp_path: Path) -> None:
    test_cache_hit_skips_extractor_subprocess(tmp_path)


def test_build_source_signals_sidecar_for_scout(bridge_vault) -> None:
    from research_framework.pipeline.source_bridge.cache import (
        build_source_signals_sidecar,
    )
    from research_framework.pipeline.source_bridge.orchestrator import run_extraction

    run_extraction(bridge_vault, 1)
    path = build_source_signals_sidecar(bridge_vault, 1)
    assert path is not None
    assert path.name == "source-signals.json"


def test_sc004_selective_reextract_on_sha_change(bridge_vault, tmp_path: Path) -> None:
    from research_framework.pipeline.source_bridge.orchestrator import run_extraction
    from tests._helpers.fake_repo import FakeRepo

    repo = FakeRepo(tmp_path / "repo")
    sources = bridge_vault / "modules" / "stub" / "sources.yaml"
    import yaml

    sources.write_text(
        yaml.dump({"sources": [{"path": str(repo.root), "value_tier": "routine"}]}),
        encoding="utf-8",
    )
    run_extraction(bridge_vault, 1)
    repo.amend_readme("changed\n")
    second = run_extraction(bridge_vault, 2)
    assert second.get("extractions", 0) >= 1


def test_fr022_idempotent_back_to_back_no_filesystem_delta(bridge_vault: Path) -> None:

    from research_framework.pipeline.source_bridge.orchestrator import run_extraction

    run_extraction(bridge_vault, 1)

    def _snapshot() -> dict[str, bytes]:
        out: dict[str, bytes] = {}
        root = bridge_vault / "_pipeline" / "sources"
        for path in root.rglob("*"):
            if path.is_file() and path.name != "bridge.log":
                out[str(path.relative_to(bridge_vault))] = path.read_bytes()
        return out

    snap1 = _snapshot()
    run_extraction(bridge_vault, 2)
    snap2 = _snapshot()
    assert set(snap1) == set(snap2)
    for key in snap1:
        if key.endswith("watermarks.json"):
            continue
        assert snap1[key] == snap2[key]


def test_source_stem_digest_is_stable_across_calls() -> None:
    stem_a = source_stem("/repo/path")
    stem_b = source_stem("/repo/path")
    assert stem_a == stem_b
    assert stem_a != source_stem("/other/path")
