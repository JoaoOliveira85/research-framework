"""SignalPayload unit tests."""

from __future__ import annotations

from research_framework.pipeline.source_bridge.signal import (
    NotableObservation,
    SignalPayload,
    apply_payload_size_cap,
)


def test_signal_payload_roundtrip_json() -> None:
    payload = SignalPayload(
        module="code",
        source_id="/repo",
        source_version="abc",
        bridge_version="0.3.2",
        extracted_at="2026-01-01T00:00:00Z",
        verdict="ok",
        truncated=False,
        partial=False,
        facts={"technologies": []},
        notable=[
            NotableObservation(observation="x", confidence="high", evidence_ref="a:1")
        ],
    )
    restored = SignalPayload.from_dict(payload.to_dict())
    assert restored.source_id == "/repo"
    assert restored.notable[0].observation == "x"


def test_payload_truncates_notable_over_100kb() -> None:
    big = "x" * 50_000
    payload = SignalPayload(
        module="code",
        source_id="s",
        source_version="v",
        bridge_version="0.3.2",
        extracted_at="2026-01-01T00:00:00Z",
        verdict="ok",
        truncated=False,
        partial=False,
        facts={},
        notable=[
            NotableObservation(observation=big, confidence="low", evidence_ref="r")
            for _ in range(5)
        ],
    )
    capped = apply_payload_size_cap(payload)
    assert capped.truncated is True
    assert len(capped.notable) < len(payload.notable)
