"""Python validator tests."""

from __future__ import annotations

import textwrap

from research_framework.pipeline.source_bridge.discovery import parse_manifest
from research_framework.pipeline.source_bridge.signal import SignalPayload
from research_framework.pipeline.source_bridge.validators import validate_payload


def _payload() -> SignalPayload:
    return SignalPayload(
        module="stub",
        source_id="s",
        source_version="v1",
        bridge_version="0.3.2",
        extracted_at="2026-01-01T00:00:00Z",
        verdict="ok",
        truncated=False,
        partial=False,
        facts={"x": 1},
        notable=[],
    )


def test_python_validator_returns_errors_list(bridge_vault) -> None:
    (bridge_vault / "stub.validators.py").write_text(
        textwrap.dedent(
            """
            def validate(payload):
                return ["bad fact"]
            """
        ),
        encoding="utf-8",
    )
    manifest = parse_manifest(bridge_vault / "modules" / "stub" / "manifest.yaml")
    errors = validate_payload(bridge_vault, manifest, _payload())
    assert "bad fact" in errors


def test_python_validator_exception_retry_once_then_isolate(bridge_vault) -> None:
    (bridge_vault / "stub.validators.py").write_text(
        textwrap.dedent(
            """
            _N = 0
            def validate(payload):
                global _N
                _N += 1
                raise RuntimeError("boom")
            """
        ),
        encoding="utf-8",
    )
    manifest = parse_manifest(bridge_vault / "modules" / "stub" / "manifest.yaml")
    errors = validate_payload(bridge_vault, manifest, _payload())
    assert errors


def test_dynamic_import_validate_callable(bridge_vault) -> None:
    (bridge_vault / "stub.validators.py").write_text(
        "def validate(payload):\n    return []\n",
        encoding="utf-8",
    )
    manifest = parse_manifest(bridge_vault / "modules" / "stub" / "manifest.yaml")
    assert validate_payload(bridge_vault, manifest, _payload()) == []


def test_validator_isolated_call_retries_once(bridge_vault) -> None:
    test_python_validator_exception_retry_once_then_isolate(bridge_vault)
