"""Spec 063 T004 — the scorecard validates against acceptance-scorecard.schema.json.

No ``jsonschema`` dependency (Principle V): a focused validator covers the subset
of draft-2020-12 the contract uses (type/const/enum/required/additionalProperties/
properties/items/minimum/maximum).
"""

from __future__ import annotations

import json
from pathlib import Path

from research_framework.cli.acceptance import build_scorecard, run_acceptance

SCHEMA = (
    Path(__file__).parent.parent.parent
    / "specs"
    / "063-acceptance-harness"
    / "contracts"
    / "acceptance-scorecard.schema.json"
)

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


def _check_type(value, type_spec) -> bool:
    names = type_spec if isinstance(type_spec, list) else [type_spec]
    for name in names:
        py = _TYPES[name]
        if name == "integer" and isinstance(value, bool):
            continue
        if name in ("number", "integer") and isinstance(value, bool):
            continue
        if isinstance(value, py):
            return True
    return False


def validate(instance, schema, path="$") -> list[str]:
    """Return a list of validation errors (empty when the instance conforms)."""
    errors: list[str] = []
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: {instance!r} != const {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in enum {schema['enum']}")
    if "type" in schema and not _check_type(instance, schema["type"]):
        errors.append(f"{path}: {instance!r} not of type {schema['type']}")
        return errors
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: {instance} < minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: {instance} > maximum {schema['maximum']}")
    if isinstance(instance, dict):
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in instance:
                errors.append(f"{path}: missing required '{req}'")
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in props:
                    errors.append(f"{path}: unexpected property '{key}'")
        for key, sub in props.items():
            if key in instance:
                errors += validate(instance[key], sub, f"{path}.{key}")
    if isinstance(instance, list) and "items" in schema:
        for i, item in enumerate(instance):
            errors += validate(item, schema["items"], f"{path}[{i}]")
    return errors


def _schema() -> dict:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def test_snapshot_scorecard_validates(snapshot_vault):
    card = build_scorecard(snapshot_vault)
    errors = validate(card, _schema())
    assert errors == [], errors


def test_clean_scorecard_validates(clean_vault):
    card = build_scorecard(clean_vault)
    errors = validate(card, _schema())
    assert errors == [], errors


def test_scorecard_has_versioned_kind(snapshot_vault):
    card = build_scorecard(snapshot_vault)
    assert card["schema_version"] == "1.0"
    assert card["kind"] == "acceptance-scorecard"
    assert {g["gate_id"] for g in card["generic_gates"]} == {
        "GA-001",
        "GA-002",
        "GA-003",
        "GA-004",
        "GA-005",
        "GA-006",
    }


def test_run_acceptance_writes_report_artifacts(snapshot_vault):
    rc = run_acceptance(snapshot_vault, json_output=True)
    assert rc == 1  # the snapshot has FAIL gates
    acc = snapshot_vault / "_pipeline" / "acceptance"
    jsons = list(acc.glob("report-*.json"))
    mds = list(acc.glob("REPORT-*.md"))
    assert jsons, "expected a report-<date>.json"
    assert mds, "expected a REPORT-<date>.md"
    written = json.loads(jsons[0].read_text(encoding="utf-8"))
    assert validate(written, _schema()) == []


def test_determinism_same_state_same_verdicts(snapshot_vault):
    a = build_scorecard(snapshot_vault)
    b = build_scorecard(snapshot_vault)
    assert a["generic_gates"] == b["generic_gates"]
    assert a.get("ledger_reconciliation") == b.get("ledger_reconciliation")
    assert a.get("citation_grading") == b.get("citation_grading")
