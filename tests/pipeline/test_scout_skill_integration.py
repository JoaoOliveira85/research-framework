"""Integration test: scout-shaped report + spec → SG-003 (T029, feature 017).

End-to-end wiring without agent calls: a fixture scout JSON whose
``topics_found.new`` titles all match ``spec.forbidden_filename_prefixes``
must yield SG-003 FAIL and a ``correction_hint`` that names the violating
prefix(es) so the orchestrator can build a directive.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from research_framework.spec.schema import (
    BudgetConfig,
    CoverageCategory,
    CoverageTargets,
    DataSourceConfig,
    NoteTypeConfig,
    ScopeConfig,
    SpecConfig,
)


def _gate_result_schema() -> dict:
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


class TestScoutReportAbstractionIntegration:
    """SG-003 FAIL carries prefix diagnostics for correction directives."""

    def test_all_topics_forbidden_prefixes_fail_with_hint_listing_prefixes(
        self, tmp_path: Path
    ) -> None:
        from research_framework.pipeline.gates_step import SG003_topic_abstraction_check

        prefixes = ["oms_", "erp_", "cms_"]
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "settings.yaml").write_text(
            yaml.safe_dump(
                {
                    "pipeline": {
                        "gates": {
                            "sg_003_abstraction_warn_pct": 20,
                            "sg_003_abstraction_fail_pct": 60,
                        }
                    }
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        spec = SpecConfig(
            name="integration",
            location=tmp_path,
            owner="tester",
            scope=ScopeConfig(domain="d", organization="o"),
            note_types=[NoteTypeConfig(name="concept", description="", folder="c/")],
            data_sources=[DataSourceConfig(name="s", type="external", priority=2)],
            search_dimensions=["domain"],
            coverage_targets=CoverageTargets(
                categories=[
                    CoverageCategory(
                        name="concepts",
                        note_type="concept",
                        target_count=5,
                    )
                ]
            ),
            budget=BudgetConfig(),
            forbidden_filename_prefixes=prefixes,
        )
        report = {
            "topics_found": {
                "new": [
                    {"title": "oms_cassandra_harness"},
                    {"title": "erp_kafka_bundle_topic"},
                    {"title": "cms_orbit_adapter"},
                ],
            },
            "proposed_filenames": [],
        }
        r = SG003_topic_abstraction_check(report, spec, tmp_path)
        assert r.gate_id == "SG-003"
        assert r.status == "FAIL"
        ok, why = _matches_schema(r.to_dict(), _gate_result_schema())
        assert ok, why
        hint = r.correction_hint
        for p in prefixes:
            assert p in hint, f"expected violating prefix {p!r} in correction_hint"
