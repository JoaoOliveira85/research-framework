"""Value-tier consensus voting (FR-019–FR-021, D2)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from .cache import atomic_write_json, module_sources_dir
from .signal import SignalPayload, Verdict

ValueTier = Literal["routine", "important", "critical"]

_DEFAULT_TIER_N = {"routine": 1, "important": 3, "critical": 5}
_VERDICT_RANK = {"ok": 0, "empty": 1, "exhausted": 2, "error": 3}


@dataclass
class ConsensusResult:
    module: str
    source_id: str
    cycle: int
    value_tier: ValueTier
    extractors_spawned: int
    verdicts: list[Verdict]
    final_verdict: Verdict
    findings_unioned: int
    dissenting_extractor_indices: list[int]
    consensus_decided_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def tier_to_n(
    value_tier: ValueTier,
    tier_map: dict[str, int] | None = None,
) -> int:
    mapping = dict(_DEFAULT_TIER_N)
    if tier_map:
        mapping.update(tier_map)
    return mapping[value_tier]


def validate_consensus_n_values(tier_map: dict[str, int]) -> None:
    """FR-020: all configured N must be odd."""
    for label, n in tier_map.items():
        if n % 2 == 0:
            raise ValueError(f"consensus N for tier {label!r} must be odd, got {n}")


def majority_verdict(verdicts: list[Verdict]) -> Verdict:
    """M-of-N majority; ties broken toward less-severe verdict (ok < exhausted)."""
    counts = Counter(verdicts)
    max_count = max(counts.values())
    candidates = [v for v, c in counts.items() if c == max_count]
    return min(candidates, key=lambda v: _VERDICT_RANK[v])


def union_findings(payloads: list[SignalPayload]) -> int:
    total = 0
    for payload in payloads:
        total += len(payload.notable)
        total += len(payload.facts)
    return total


def _failed_extractor_payload(
    *,
    module: str,
    source_id: str,
    source_version: str,
    bridge_version: str,
) -> SignalPayload:
    return SignalPayload(
        module=module,
        source_id=source_id,
        source_version=source_version,
        bridge_version=bridge_version,
        extracted_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        verdict="error",
        truncated=False,
        partial=True,
        facts={},
        notable=[],
    )


def run_consensus(
    *,
    spawn_extractor: Callable[[], SignalPayload | None],
    module: str,
    source_id: str,
    cycle: int,
    value_tier: ValueTier,
    tier_map: dict[str, int] | None = None,
    bridge_version: str = "",
    source_version: str = "",
) -> tuple[SignalPayload, ConsensusResult]:
    n = tier_to_n(value_tier, tier_map)
    with ThreadPoolExecutor(max_workers=n) as pool:
        futures = [pool.submit(spawn_extractor) for _ in range(n)]
        payloads = []
        for fut in futures:
            payload = fut.result()
            if payload is None:
                payload = _failed_extractor_payload(
                    module=module,
                    source_id=source_id,
                    source_version=source_version,
                    bridge_version=bridge_version,
                )
            payloads.append(payload)
    verdicts = [p.verdict for p in payloads]
    final = majority_verdict(verdicts)
    dissent = [i for i, v in enumerate(verdicts) if v != final]
    winner = next(p for p in payloads if p.verdict == final)
    merged = SignalPayload(
        module=winner.module,
        source_id=winner.source_id,
        source_version=winner.source_version,
        bridge_version=winner.bridge_version,
        extracted_at=winner.extracted_at,
        verdict=final,
        truncated=any(p.truncated for p in payloads),
        partial=any(p.partial for p in payloads),
        facts={k: v for p in payloads for k, v in p.facts.items()},
        notable=[obs for p in payloads for obs in p.notable],
    )
    result = ConsensusResult(
        module=module,
        source_id=source_id,
        cycle=cycle,
        value_tier=value_tier,
        extractors_spawned=n,
        verdicts=verdicts,
        final_verdict=final,
        findings_unioned=union_findings(payloads),
        dissenting_extractor_indices=dissent,
        consensus_decided_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    return merged, result


def write_consensus_result(vault_dir: Path, result: ConsensusResult) -> Path:
    consensus_dir = module_sources_dir(vault_dir, result.module) / "consensus"
    consensus_dir.mkdir(parents=True, exist_ok=True)
    safe_id = result.source_id.replace("/", "_")[:80]
    path = consensus_dir / f"{safe_id}-cycle-{result.cycle:03d}.json"
    atomic_write_json(path, result.to_dict())
    return path
