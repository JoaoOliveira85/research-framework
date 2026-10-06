"""Tests for SG-003 abstraction gate (T027, feature 017).

Per R-007 / FR-022: compare canonical filenames derived from
``topics_found.new`` titles against ``spec.forbidden_filename_prefixes``, or
against the framework starter set when the spec declares none (#296).
Thresholds come from ``settings.yaml`` under
``pipeline.gates.sg_003_abstraction_warn_pct`` (default 20) and
``sg_003_abstraction_fail_pct`` (default 60) — never hardcode vault
prefixes in framework code.

Target: ``research_framework.pipeline.gates_step.SG003_topic_abstraction_check``.
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


def _minimal_spec(*, forbidden: list[str]) -> SpecConfig:
    return SpecConfig(
        name="sg003-test",
        location=Path("."),
        owner="tester",
        scope=ScopeConfig(domain="d", organization="o"),
        note_types=[NoteTypeConfig(name="concept", description="", folder="c/")],
        data_sources=[DataSourceConfig(name="s", type="external", priority=2)],
        search_dimensions=["domain", "market"],
        coverage_targets=CoverageTargets(
            categories=[CoverageCategory(name="x", note_type="concept", target_count=1)]
        ),
        budget=BudgetConfig(),
        forbidden_filename_prefixes=list(forbidden),
    )


def _titles_scout(prefix_titles: list[str], other_titles: list[str]) -> dict:
    new: list[dict] = [{"title": t} for t in prefix_titles + other_titles]
    return {"topics_found": {"new": new}, "proposed_filenames": []}


def _write_settings(
    vault_dir: Path,
    *,
    warn_pct: int = 20,
    fail_pct: int = 60,
    abstraction_enabled: bool | None = None,
) -> None:
    gates: dict = {
        "sg_003_abstraction_warn_pct": warn_pct,
        "sg_003_abstraction_fail_pct": fail_pct,
    }
    if abstraction_enabled is not None:
        gates["abstraction_enabled"] = abstraction_enabled
    body = {"pipeline": {"gates": gates}}
    vault_dir.mkdir(parents=True, exist_ok=True)
    (vault_dir / "settings.yaml").write_text(
        yaml.safe_dump(body, sort_keys=False),
        encoding="utf-8",
    )


class TestSG003TopicAbstractionCheck:
    """Abstraction ratio vs configurable warn/fail bands."""

    def test_na_only_when_the_vault_switches_the_gate_off(self, tmp_path: Path) -> None:
        """An empty spec key no longer means "inactive" — a settings key does.

        Keying inactivity off ``forbidden_filename_prefixes`` made SG-003 NA on
        every vault the generator produces, because nothing writes that key
        (#296).
        """
        from research_framework.pipeline.gates_step import SG003_topic_abstraction_check

        _write_settings(tmp_path, abstraction_enabled=False)
        spec = _minimal_spec(forbidden=[])
        report = _titles_scout(["svc_anything"], ["Clean Topic"])
        r = SG003_topic_abstraction_check(report, spec, tmp_path)
        assert r.gate_id == "SG-003"
        assert r.status == "NA"
        ok, why = _matches_schema(r.to_dict(), _gate_result_schema())
        assert ok, why

    def test_empty_spec_list_uses_the_framework_prefixes(self, tmp_path: Path) -> None:
        from research_framework.pipeline.gates_step import SG003_topic_abstraction_check

        _write_settings(tmp_path)
        spec = _minimal_spec(forbidden=[])
        report = _titles_scout(["svc_a", "svc_b", "tbl_c"], ["Clean Topic"])
        r = SG003_topic_abstraction_check(report, spec, tmp_path)
        assert r.status == "FAIL"
        assert r.correction_hint

    def test_warns_when_ratio_strictly_above_warn_and_at_or_below_fail(
        self, tmp_path: Path
    ) -> None:
        from research_framework.pipeline.gates_step import SG003_topic_abstraction_check

        _write_settings(tmp_path)
        spec = _minimal_spec(forbidden=["oms_"])
        # 5 topics, 2 forbidden-shaped titles → 40% (20% < 40% ≤ 60%)
        report = _titles_scout(
            ["oms_one", "oms_two"],
            ["nice-topic-one", "nice-two", "nice-three"],
        )
        r = SG003_topic_abstraction_check(report, spec, tmp_path)
        assert r.status == "WARN"

    def test_fails_when_ratio_above_fail_pct_with_correction_hint(
        self, tmp_path: Path
    ) -> None:
        from research_framework.pipeline.gates_step import SG003_topic_abstraction_check

        _write_settings(tmp_path)
        spec = _minimal_spec(forbidden=["oms_"])
        # 5 topics, 4 oms_* → 80% > 60%
        report = _titles_scout(
            ["oms_a", "oms_b", "oms_c", "oms_d"],
            ["ok-topic"],
        )
        r = SG003_topic_abstraction_check(report, spec, tmp_path)
        assert r.status == "FAIL"
        assert r.correction_hint
        assert "oms_" in r.correction_hint
        ok, why = _matches_schema(r.to_dict(), _gate_result_schema())
        assert ok, why

    def test_never_uses_hardcoded_prefix_list_from_spec_only(
        self, tmp_path: Path
    ) -> None:
        from research_framework.pipeline.gates_step import SG003_topic_abstraction_check

        _write_settings(tmp_path)
        spec_a = _minimal_spec(forbidden=["oms_"])
        spec_b = _minimal_spec(forbidden=["zzz_"])
        report = _titles_scout(
            ["oms_one", "oms_two"],
            ["alpha", "beta", "gamma"],
        )
        ra = SG003_topic_abstraction_check(report, spec_a, tmp_path)
        rb = SG003_topic_abstraction_check(report, spec_b, tmp_path)
        assert ra.status == "WARN"
        assert rb.status == "PASS"

    def test_reads_warn_and_fail_percent_from_settings_yaml(
        self, tmp_path: Path
    ) -> None:
        from research_framework.pipeline.gates_step import SG003_topic_abstraction_check

        # 40% forbidden ratio: default thresholds → WARN (20 < 40 ≤ 60).
        _write_settings(tmp_path, warn_pct=20, fail_pct=60)
        spec = _minimal_spec(forbidden=["oms_"])
        report = _titles_scout(
            ["oms_lo", "oms_hi"],
            ["a", "b", "c"],
        )
        r_default = SG003_topic_abstraction_check(report, spec, tmp_path)

        # Raise warn band to 50% so 40% now passes.
        _write_settings(tmp_path, warn_pct=50, fail_pct=80)
        r_lenient = SG003_topic_abstraction_check(report, spec, tmp_path)

        assert r_default.status == "WARN"
        assert r_lenient.status == "PASS"
