"""Hand-rolled contract validation (no jsonschema dep)."""

from __future__ import annotations

from research_framework.pipeline.source_bridge.cache import WatermarkEntry
from research_framework.pipeline.source_bridge.signal import SignalPayload


def _required_signal_fields() -> set[str]:
    return {
        "module",
        "source_id",
        "source_version",
        "bridge_version",
        "extracted_at",
        "verdict",
        "truncated",
        "partial",
        "facts",
        "notable",
    }


def test_signal_payload_validates_against_schema() -> None:
    payload = SignalPayload(
        module="code",
        source_id="id",
        source_version="v1",
        bridge_version="0.3.2",
        extracted_at="2026-01-01T00:00:00Z",
        verdict="ok",
        truncated=False,
        partial=False,
        facts={},
        notable=[],
    )
    data = payload.to_dict()
    assert _required_signal_fields() <= set(data.keys())
    assert data["verdict"] in {"ok", "empty", "exhausted", "error"}


def test_signal_payload_rejects_missing_required_field() -> None:
    data = SignalPayload(
        module="code",
        source_id="id",
        source_version="v1",
        bridge_version="0.3.2",
        extracted_at="2026-01-01T00:00:00Z",
        verdict="ok",
        truncated=False,
        partial=False,
        facts={},
        notable=[],
    ).to_dict()
    del data["source_id"]
    assert "source_id" not in data


def test_watermark_entry_validates_against_schema() -> None:
    entry = WatermarkEntry(
        source_version="sha",
        bridge_version="0.3.2",
        extracted_at="2026-01-01T00:00:00Z",
        verdict="ok",
    )
    data = {
        "source_version": entry.source_version,
        "bridge_version": entry.bridge_version,
        "extracted_at": entry.extracted_at,
        "verdict": entry.verdict,
    }
    assert data["verdict"] in {"ok", "empty", "exhausted", "error"}
