"""SignalPayload envelope (contracts/signal-payload.schema.json)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

Verdict = Literal["ok", "empty", "exhausted", "error"]
Confidence = Literal["high", "medium", "low"]

_SIGNAL_CAP_BYTES = 100 * 1024


@dataclass
class NotableObservation:
    observation: str
    confidence: Confidence
    evidence_ref: str


@dataclass
class SignalPayload:
    module: str
    source_id: str
    source_version: str
    bridge_version: str
    extracted_at: str
    verdict: Verdict
    truncated: bool
    partial: bool
    facts: dict[str, Any]
    notable: list[NotableObservation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["notable"] = [asdict(n) for n in self.notable]
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SignalPayload:
        notable_raw = data.get("notable") or []
        notable = [
            NotableObservation(
                observation=str(item["observation"]),
                confidence=item["confidence"],  # type: ignore[arg-type]
                evidence_ref=str(item["evidence_ref"]),
            )
            for item in notable_raw
        ]
        return cls(
            module=str(data["module"]),
            source_id=str(data["source_id"]),
            source_version=str(data["source_version"]),
            bridge_version=str(data["bridge_version"]),
            extracted_at=str(data["extracted_at"]),
            verdict=data["verdict"],  # type: ignore[arg-type]
            truncated=bool(data["truncated"]),
            partial=bool(data["partial"]),
            facts=dict(data.get("facts") or {}),
            notable=notable,
        )


def apply_payload_size_cap(payload: SignalPayload) -> SignalPayload:
    """Truncate ``notable`` when serialized size exceeds 100 KB (research R4)."""
    encoded = payload.to_json().encode("utf-8")
    if len(encoded) <= _SIGNAL_CAP_BYTES:
        return payload
    notable = list(payload.notable)

    def _serialized_size(items: list[NotableObservation]) -> int:
        trial = SignalPayload(
            module=payload.module,
            source_id=payload.source_id,
            source_version=payload.source_version,
            bridge_version=payload.bridge_version,
            extracted_at=payload.extracted_at,
            verdict=payload.verdict,
            truncated=payload.truncated,
            partial=payload.partial,
            facts=payload.facts,
            notable=items,
        )
        return len(trial.to_json().encode("utf-8"))

    while notable and _serialized_size(notable) > _SIGNAL_CAP_BYTES:
        notable.pop()
    return SignalPayload(
        module=payload.module,
        source_id=payload.source_id,
        source_version=payload.source_version,
        bridge_version=payload.bridge_version,
        extracted_at=payload.extracted_at,
        verdict=payload.verdict,
        truncated=True,
        partial=payload.partial,
        facts=payload.facts,
        notable=notable,
    )


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
