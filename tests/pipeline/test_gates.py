"""Tests for the `GateResult` framework primitive (T007, feature 017).

Per `data-model.md` E-004 and `contracts/cycle-quality-report.schema.json`
`#/$defs/gate_result`:

- `gate_id` matches `^[CS]G-\\d{3}$`.
- `status` is one of PASS / WARN / FAIL / NA.
- `status == "FAIL"` MUST have non-empty `correction_hint`.
- The dataclass round-trips losslessly through `to_dict()` and is
  schema-conformant against the JSON contract.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _gate_result_schema() -> dict:
    """Load the JSON schema for `gate_result` from the feature contracts."""
    contracts = (
        Path(__file__).resolve().parents[2]
        / "specs"
        / "017-vault-quality-fix"
        / "contracts"
        / "cycle-quality-report.schema.json"
    )
    schema = json.loads(contracts.read_text(encoding="utf-8"))
    return schema["$defs"]["gate_result"]


def _matches_schema(payload: dict, schema: dict) -> tuple[bool, str]:
    """Hand-rolled schema check (avoids adding `jsonschema` as a dep).

    Validates:
      - all `required` keys present
      - no extra keys when `additionalProperties: false`
      - status enum membership
      - gate_id pattern
      - correction_hint required when status == FAIL
    """
    for k in schema.get("required", []):
        if k not in payload:
            return False, f"missing required key: {k}"
    if schema.get("additionalProperties") is False:
        allowed = set(schema.get("properties", {}).keys())
        extras = set(payload.keys()) - allowed
        if extras:
            return False, f"unexpected keys: {sorted(extras)}"
    props = schema.get("properties", {})
    if "status" in payload and "enum" in props.get("status", {}):
        if payload["status"] not in props["status"]["enum"]:
            return False, f"invalid status: {payload['status']!r}"
    if "gate_id" in payload and "pattern" in props.get("gate_id", {}):
        if not re.match(props["gate_id"]["pattern"], payload["gate_id"]):
            return False, f"gate_id {payload['gate_id']!r} fails pattern"
    if payload.get("status") == "FAIL" and not payload.get("correction_hint"):
        return False, "status=FAIL requires non-empty correction_hint"
    return True, ""


# ---------------------------------------------------------------------------
# GateResult construction & invariants
# ---------------------------------------------------------------------------


class TestGateResultConstruction:
    """Each status value constructs cleanly under the documented invariants."""

    def test_pass_status_constructs(self) -> None:
        from research_framework.pipeline.gates import GateResult

        r = GateResult(
            gate_id="CG-001",
            status="PASS",
            metric_name="notes_written",
            metric_value=27,
            threshold=25,
            message="cycle yield met",
        )
        assert r.status == "PASS"

    def test_warn_status_constructs(self) -> None:
        from research_framework.pipeline.gates import GateResult

        r = GateResult(
            gate_id="SG-003",
            status="WARN",
            metric_name="abstraction_pct",
            metric_value=0.35,
            threshold=0.20,
            message="35% of topics match a forbidden prefix",
        )
        assert r.status == "WARN"

    def test_fail_status_requires_non_empty_correction_hint(self) -> None:
        from research_framework.pipeline.gates import GateResult

        with pytest.raises(ValueError, match="correction_hint"):
            GateResult(
                gate_id="CG-002",
                status="FAIL",
                metric_name="categories_touched",
                metric_value=1,
                threshold=3,
                message="single-category cycle",
                correction_hint="",  # empty → reject
            )

    def test_fail_status_with_correction_hint_constructs(self) -> None:
        from research_framework.pipeline.gates import GateResult

        r = GateResult(
            gate_id="CG-002",
            status="FAIL",
            metric_name="categories_touched",
            metric_value=1,
            threshold=3,
            message="single-category cycle",
            correction_hint="produce notes in ≥ 3 categories next cycle",
        )
        assert r.correction_hint  # non-empty

    def test_na_status_constructs(self) -> None:
        from research_framework.pipeline.gates import GateResult

        r = GateResult(
            gate_id="SG-003",
            status="NA",
            metric_name="abstraction_pct",
            metric_value="n/a",
            threshold=None,
            message="forbidden_filename_prefixes empty; gate inactive",
        )
        assert r.status == "NA"


class TestGateIdValidation:
    """`gate_id` MUST match `^[CS]G-\\d{3}$`."""

    @pytest.mark.parametrize(
        "valid_id", ["CG-001", "CG-007", "SG-001", "SG-005", "CG-999"]
    )
    def test_valid_ids(self, valid_id: str) -> None:
        from research_framework.pipeline.gates import GateResult

        GateResult(
            gate_id=valid_id,
            status="PASS",
            metric_name="x",
            metric_value=1,
            threshold=0,
            message="ok",
        )

    @pytest.mark.parametrize(
        "invalid_id",
        [
            "CG001",
            "CG-1",
            "CG-1234",
            "cg-001",
            "XG-001",
            "CG_001",
            "",
            "CG-00",
        ],
    )
    def test_invalid_ids_rejected(self, invalid_id: str) -> None:
        from research_framework.pipeline.gates import GateResult

        with pytest.raises(ValueError, match="gate_id"):
            GateResult(
                gate_id=invalid_id,
                status="PASS",
                metric_name="x",
                metric_value=1,
                threshold=0,
                message="ok",
            )


# ---------------------------------------------------------------------------
# Schema conformance (round-trip JSON matches the contract)
# ---------------------------------------------------------------------------


class TestGateResultJsonContract:
    def test_to_dict_matches_schema(self) -> None:
        from research_framework.pipeline.gates import GateResult

        r = GateResult(
            gate_id="CG-001",
            status="PASS",
            metric_name="notes_written",
            metric_value=27,
            threshold=25,
            message="met cycle yield quota",
        )
        ok, why = _matches_schema(r.to_dict(), _gate_result_schema())
        assert ok, why

    def test_fail_to_dict_includes_correction_hint(self) -> None:
        from research_framework.pipeline.gates import GateResult

        r = GateResult(
            gate_id="CG-002",
            status="FAIL",
            metric_name="categories_touched",
            metric_value=1,
            threshold=3,
            message="single-category cycle",
            correction_hint="produce notes in ≥ 3 categories next cycle",
        )
        d = r.to_dict()
        assert d["correction_hint"]
        ok, why = _matches_schema(d, _gate_result_schema())
        assert ok, why

    def test_na_to_dict_matches_schema(self) -> None:
        from research_framework.pipeline.gates import GateResult

        r = GateResult(
            gate_id="SG-003",
            status="NA",
            metric_name="abstraction_pct",
            metric_value="n/a",
            threshold=None,
            message="forbidden_filename_prefixes empty",
        )
        ok, why = _matches_schema(r.to_dict(), _gate_result_schema())
        assert ok, why


# ---------------------------------------------------------------------------
# run_gate runner converts exceptions to FAIL with diagnostic correction_hint
# ---------------------------------------------------------------------------


class TestRunGate:
    """`run_gate(callable, *args)` catches exceptions and converts to FAIL."""

    def test_successful_callable_returns_its_result(self) -> None:
        from research_framework.pipeline.gates import GateResult, run_gate

        def good() -> GateResult:
            return GateResult(
                gate_id="CG-001",
                status="PASS",
                metric_name="x",
                metric_value=1,
                threshold=0,
                message="ok",
            )

        r = run_gate(good)
        assert r.status == "PASS"

    def test_exception_becomes_fail_with_diagnostic_hint(self) -> None:
        from research_framework.pipeline.gates import run_gate

        def bad() -> None:
            raise RuntimeError("scout report missing")

        r = run_gate(bad)
        assert r.status == "FAIL"
        assert "RuntimeError" in r.correction_hint
        assert "scout report missing" in r.correction_hint
