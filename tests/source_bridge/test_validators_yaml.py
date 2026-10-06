"""YAML validator tests."""

from __future__ import annotations

import yaml

from research_framework.pipeline.source_bridge.discovery import parse_manifest
from research_framework.pipeline.source_bridge.orchestrator import run_extraction
from research_framework.pipeline.source_bridge.signal import (
    NotableObservation,
    SignalPayload,
)
from research_framework.pipeline.source_bridge.validators import (
    load_yaml_validator,
    validate_payload,
    validate_yaml_rules,
)


def _payload(
    *,
    verdict: str = "ok",
    facts: dict | None = None,
    notable: list | None = None,
) -> SignalPayload:
    # Explicit keyword-only params (not **kwargs) so a typo'd field name fails
    # fast instead of being silently dropped into a false-positive test.
    return SignalPayload(
        module="stub",
        source_id="s",
        source_version="v1",
        bridge_version="0.3.2",
        extracted_at="2026-01-01T00:00:00Z",
        verdict=verdict,
        truncated=False,
        partial=False,
        facts=facts if facts is not None else {},
        notable=notable if notable is not None else [],
    )


def test_yaml_validator_required_buckets_min_items() -> None:
    rules = {"facts": {"technologies": {"required": True, "min_items": 1}}}
    errors = validate_yaml_rules(_payload(facts={"technologies": []}), rules)
    assert errors


def test_yaml_validator_fail_closed_no_cache_write(bridge_vault) -> None:
    (bridge_vault / "stub.validators.yaml").write_text(
        yaml.dump({"facts": {"technologies": {"required": True, "min_items": 99}}}),
        encoding="utf-8",
    )
    run_extraction(bridge_vault, 1)
    sig_dir = bridge_vault / "_pipeline" / "sources" / "stub" / "signals"
    for path in sig_dir.glob("*.json") if sig_dir.is_dir() else []:
        data = yaml.safe_load(path.read_text()) if path.suffix == ".json" else {}
        if isinstance(data, dict) and data.get("verdict") == "ok":
            assert len(data.get("facts", {}).get("technologies", [])) >= 99


def test_yaml_rule_engine_loads_module_validators_yaml(bridge_vault) -> None:
    (bridge_vault / "stub.validators.yaml").write_text("facts: {}\n", encoding="utf-8")
    assert load_yaml_validator(bridge_vault, "stub") is not None


def test_empty_yaml_validator_does_not_trigger_default_fallback(bridge_vault) -> None:
    (bridge_vault / "stub.validators.yaml").write_text("{}\n", encoding="utf-8")
    manifest = parse_manifest(bridge_vault / "modules" / "stub" / "manifest.yaml")
    errors = validate_payload(
        bridge_vault,
        manifest,
        _payload(facts={"technologies": ["x"]}),
    )
    assert errors == []


def test_default_json_schema_only_when_no_validator_files(bridge_vault) -> None:
    manifest = parse_manifest(bridge_vault / "modules" / "stub" / "manifest.yaml")
    errors = validate_payload(
        bridge_vault,
        manifest,
        _payload(facts={}),
    )
    assert errors


def test_notable_only_ok_payload_is_valid(bridge_vault) -> None:
    """Notable-only modules (all Tier-1 ports + github/atlassian) emit
    ``facts: {}`` with observations in ``notable`` — that is a VALID ``ok``
    payload and must not be marked source-health FAILED (pre-rc5 fix)."""
    manifest = parse_manifest(bridge_vault / "modules" / "stub" / "manifest.yaml")
    errors = validate_payload(
        bridge_vault,
        manifest,
        _payload(
            facts={},
            notable=[
                NotableObservation(
                    observation="GitHub release v1.2.3",
                    confidence="high",
                    evidence_ref="https://github.com/o/r/releases/tag/v1.2.3",
                )
            ],
        ),
    )
    assert errors == []


def test_wholly_empty_ok_payload_still_fails(bridge_vault) -> None:
    """A ``verdict: ok`` with neither facts nor notable carries no signal and
    remains a contract violation."""
    manifest = parse_manifest(bridge_vault / "modules" / "stub" / "manifest.yaml")
    errors = validate_payload(bridge_vault, manifest, _payload(facts={}, notable=[]))
    assert errors
