"""Tests for `CycleQualityReport` serialization (T038, feature 017).

Per `data-model.md` E-005 and `contracts/cycle-quality-report.schema.json`:

- Written JSON validates under a hand-rolled subset of the contract (required
  keys, gate enums, structural invariants).
- Gate keys support batched SG suffixes like ``SG-004#1``.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path


def _root_schema() -> dict:
    p = (
        Path(__file__).resolve().parents[2]
        / "specs"
        / "017-vault-quality-fix"
        / "contracts"
        / "cycle-quality-report.schema.json"
    )
    return json.loads(p.read_text(encoding="utf-8"))


def _gate_result_schema(root: dict) -> dict:
    return root["$defs"]["gate_result"]


def _matches_gate_result(payload: dict, schema: dict) -> tuple[bool, str]:
    for k in schema.get("required", []):
        if k not in payload:
            return False, f"gate_result missing: {k}"
    if schema.get("additionalProperties") is False:
        allowed = set(schema.get("properties", {}).keys())
        if set(payload.keys()) - allowed:
            return False, "gate_result extra keys"
    st_en = schema.get("properties", {}).get("status", {}).get("enum", [])
    if st_en and payload.get("status") not in st_en:
        return False, "bad gate status"
    if payload.get("status") == "FAIL" and not (
        payload.get("correction_hint") and str(payload["correction_hint"]).strip()
    ):
        return False, "FAIL needs correction_hint"
    gid_pat = schema.get("properties", {}).get("gate_id", {}).get("pattern")
    if gid_pat and not re.match(gid_pat, str(payload.get("gate_id", ""))):
        return False, "gate_id pattern"
    return True, ""


def _matches_cycle_report(payload: dict, root: dict) -> tuple[bool, str]:
    for k in root.get("required", []):
        if k not in payload:
            return False, f"report missing required: {k}"
    if root.get("additionalProperties") is False:
        allowed = set(root.get("properties", {}).keys())
        extra = set(payload.keys()) - allowed
        if extra:
            return False, f"unexpected report keys: {sorted(extra)}"
    if payload.get("schema_version") != "1":
        return False, "schema_version"
    gates = payload.get("gates")
    if not isinstance(gates, dict) or len(gates) < 12:
        return False, "gates minProperties"
    gate_key_re = re.compile(r"^[CS]G-\d{3}(#\d+)?$")
    grs = _gate_result_schema(root)
    for gk, gv in gates.items():
        if not gate_key_re.match(gk):
            return False, f"bad gate key {gk!r}"
        if not isinstance(gv, dict):
            return False, "gate value not object"
        dv = dict(gv)
        base_id = gk.split("#", 1)[0]
        dv["gate_id"] = base_id
        ok, why = _matches_gate_result(dv, grs)
        if not ok:
            return False, f"{gk}: {why}"
    cs = payload.get("coverage_snapshot")
    if not isinstance(cs, dict):
        return False, "coverage_snapshot"
    cat_re = re.compile(r"^[a-z][a-z0-9_-]*$")
    for ck, cv in cs.items():
        if not cat_re.match(ck):
            return False, f"bad category key {ck!r}"
        if not isinstance(cv, dict):
            return False, "category not object"
        for rk in ("target", "met", "fill_pct", "delta_this_cycle"):
            if rk not in cv:
                return False, f"{ck} missing {rk}"
    qs = payload.get("queryability_score")
    if not isinstance(qs, int) or qs < 0 or qs > 100:
        return False, "queryability_score"
    qt = payload.get("queryability_trajectory")
    if qt not in ("improving", "stable", "regressing"):
        return False, "queryability_trajectory"
    rc = payload.get("retry_count")
    if not isinstance(rc, int) or rc < 0 or rc > 2:
        return False, "retry_count"
    if payload.get("aborted") is True:
        if rc != 2:
            return False, "aborted requires retry_count==2"
        ar = payload.get("abort_reason", "")
        if not str(ar).strip():
            return False, "aborted requires non-empty abort_reason"
    nw, na, nr = (
        payload.get("notes_written"),
        payload.get("notes_accepted"),
        payload.get("notes_rejected"),
    )
    if nw != na + nr:
        return False, "notes_written != accepted+rejected"
    batches = payload.get("batches")
    if not isinstance(batches, list):
        return False, "batches"
    bpat = re.compile(r"^cycle-\d{3}-batch-\d{3}\.json$")
    for b in batches:
        if not isinstance(b, str) or not bpat.match(b):
            return False, f"bad batch ref {b!r}"
    return True, ""


def _touch_fixture_cycle(vault: Path, *, cycle: int, n_batches: int) -> None:
    """Lay down minimal batch JSON artifacts for ``write_report`` to ingest."""
    cyc = vault / "_pipeline" / "cycles"
    cyc.mkdir(parents=True, exist_ok=True)
    for b in range(1, n_batches + 1):
        topics = [
            {
                "title": f"t{b}_{i}",
                "category": "concepts",
                "priority_score": 0.5,
                "provenance": "spec_gap",
            }
            for i in range(3)
        ]
        doc = {
            "schema_version": "1",
            "cycle_number": cycle,
            "batch_number": b,
            "started_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "finished_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "topics": topics,
            "notes_written": [f"b{b}_n{i}.md" for i in range(3)],
            "skipped_topics": [],
            "sg_gate_results": [],
            "accepted": True,
            "correction_directive_in": "",
        }
        name = f"cycle-{cycle:03d}-batch-{b:03d}.json"
        (cyc / name).write_text(json.dumps(doc), encoding="utf-8")


class TestCycleQualityReportSchema:
    """Contract checks on ``write_report`` output."""

    def test_write_report_produces_schema_shape(self, tmp_path: Path) -> None:
        from research_framework.pipeline.quality_report import write_report

        dv = tmp_path / "data_vault"
        dv.mkdir(parents=True, exist_ok=True)
        pipe = tmp_path / "_pipeline"
        (pipe / "cycles").mkdir(parents=True, exist_ok=True)
        _touch_fixture_cycle(tmp_path, cycle=1, n_batches=2)
        out = write_report(tmp_path, cycle_number=1)
        assert out.is_file()
        data = json.loads(out.read_text(encoding="utf-8"))
        root = _root_schema()
        ok, why = _matches_cycle_report(data, root)
        assert ok, why

    def test_abort_invariant_enforced_in_payload(self) -> None:
        root = _root_schema()

        def sg(gid: str, st: str) -> dict:
            d = {
                "gate_id": gid,
                "status": st,
                "metric_name": "m",
                "metric_value": 0,
                "message": "ok",
            }
            if st == "FAIL":
                d["correction_hint"] = "must fix"
            return d

        gates: dict[str, dict] = {
            "SG-001": sg("SG-001", "PASS"),
            "SG-002": sg("SG-002", "PASS"),
            "SG-003": sg("SG-003", "NA"),
            "SG-004#1": sg("SG-004", "PASS"),
            "SG-004#2": sg("SG-004", "WARN"),
            "SG-005#1": sg("SG-005", "PASS"),
            "CG-001": sg("CG-001", "FAIL"),
            "CG-002": sg("CG-002", "PASS"),
            "CG-003": sg("CG-003", "PASS"),
            "CG-004": sg("CG-004", "PASS"),
            "CG-005": sg("CG-005", "PASS"),
            "CG-006": sg("CG-006", "PASS"),
            "CG-007": sg("CG-007", "PASS"),
        }
        payload = {
            "schema_version": "1",
            "cycle_number": 9,
            "framework_version": "0.0.0",
            "generated_at": "2026-05-15T12:00:00Z",
            "cycle_started_at": "2026-05-15T11:00:00Z",
            "cycle_finished_at": "2026-05-15T12:00:00Z",
            "gates": gates,
            "coverage_snapshot": {
                "concepts": {
                    "target": 10,
                    "met": 3,
                    "fill_pct": 0.3,
                    "delta_this_cycle": 1,
                },
            },
            "notes_written": 4,
            "notes_accepted": 1,
            "notes_rejected": 3,
            "batches": ["cycle-009-batch-001.json"],
            "queryability_score": 0,
            "queryability_trajectory": "stable",
            "degraded_sources": [],
            "retry_count": 2,
            "aborted": True,
            "abort_reason": "CG-001 still failing after two retries",
        }
        ok2, why = _matches_cycle_report(payload, root)
        assert ok2, why


class TestQualityReportNoteCounts:
    """``notes_written`` balance (E-005)."""

    def test_notes_balance_in_report(self, tmp_path: Path) -> None:
        from research_framework.pipeline.quality_report import write_report

        dv = tmp_path / "data_vault"
        dv.mkdir(parents=True, exist_ok=True)
        _touch_fixture_cycle(tmp_path, cycle=3, n_batches=2)
        out = write_report(tmp_path, cycle_number=3)
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["notes_written"] == data["notes_accepted"] + data["notes_rejected"]


class TestQualityReportGateCardinality:
    """At least 5 SG + 7 CG entries (batched SG keys use ``#N``)."""

    def test_at_least_twelve_gate_results(self, tmp_path: Path) -> None:
        from research_framework.pipeline.quality_report import write_report

        dv = tmp_path / "data_vault"
        dv.mkdir(parents=True, exist_ok=True)
        _touch_fixture_cycle(tmp_path, cycle=4, n_batches=2)
        out = write_report(tmp_path, cycle_number=4)
        data = json.loads(out.read_text(encoding="utf-8"))
        assert len(data["gates"]) >= 12
        keys = list(data["gates"].keys())
        assert any(k.startswith("SG-004#") for k in keys)


class TestCoverageVelocityScope:
    """CG-004 measures progress where a target remains (spec 017 FR-023)."""

    @staticmethod
    def _cg004(vault: Path, *, before: dict[str, int], after: dict[str, int]) -> dict:
        """Cycle 2's CG-004 for a vault whose ``met`` counts moved before → after.

        Both categories have targets: ``concepts`` 5 notes, ``flows`` 100.
        """
        from research_framework.pipeline.coverage import save_targets
        from research_framework.pipeline.quality_report import write_report
        from research_framework.spec.schema import CoverageCategory, CoverageTargets

        targets = {"concepts": 5, "flows": 100}
        cycles = vault / "_pipeline" / "cycles"
        cycles.mkdir(parents=True, exist_ok=True)
        (vault / "data_vault").mkdir(parents=True, exist_ok=True)
        previous = {
            "coverage_snapshot": {
                name: {"target": targets[name], "met": met}
                for name, met in before.items()
            }
        }
        (cycles / "cycle-001-quality-report.json").write_text(
            json.dumps(previous), encoding="utf-8"
        )
        save_targets(
            vault,
            CoverageTargets(
                categories=[
                    CoverageCategory(
                        name=name,
                        note_type="concept",
                        target_count=targets[name],
                        met_count=met,
                    )
                    for name, met in after.items()
                ]
            ),
        )
        out = write_report(vault, cycle_number=2)
        return json.loads(out.read_text(encoding="utf-8"))["gates"]["CG-004"]

    def test_a_category_that_was_already_met_does_not_fail_the_cycle(
        self, tmp_path: Path
    ) -> None:
        """A met category has no progress left to make.

        Every category was scored, so the zero delta of a finished one was the
        cycle's minimum and CG-004 reported "no positive coverage delta" on
        every cycle after the first category filled — here a cycle that added
        50 notes to the only category with a target left.
        """
        gate = self._cg004(
            tmp_path,
            before={"concepts": 5, "flows": 10},
            after={"concepts": 5, "flows": 60},
        )

        assert gate["status"] == "PASS", gate["message"]

    def test_a_complete_vault_has_no_velocity_to_fail(self, tmp_path: Path) -> None:
        """CG-001 already says so: all targets met, nothing is mandated."""
        gate = self._cg004(
            tmp_path,
            before={"concepts": 5, "flows": 100},
            after={"concepts": 5, "flows": 100},
        )

        assert gate["status"] == "PASS", gate["message"]

    def test_an_unfilled_category_that_stood_still_fails(self, tmp_path: Path) -> None:
        """The gate's purpose is unchanged: a target that remains must move."""
        gate = self._cg004(
            tmp_path,
            before={"concepts": 2, "flows": 10},
            after={"concepts": 2, "flows": 60},
        )

        assert gate["status"] == "FAIL"


class TestWordCountReadsTheDeclaredCorpus:
    """CG-006 counts the words of the notes where the vault keeps them."""

    def test_a_vault_with_its_own_corpus_dir_is_not_failed_for_thin_notes(
        self, tmp_path: Path
    ) -> None:
        """``vault.corpus_dir`` names the corpus folder; ``data_vault`` is the default.

        The word count looked under ``data_vault/`` whatever the vault
        declared, found nothing, and scored every note of the cycle at zero
        words: CG-006 FAILed each cycle with "expand notes" for notes that
        were long enough.
        """
        from research_framework.pipeline.quality_report import write_report

        pipe = tmp_path / "_pipeline"
        (pipe / "cycles").mkdir(parents=True)
        (pipe / "spec-parse.json").write_text(
            json.dumps({"vault_corpus_dir": "notes"}), encoding="utf-8"
        )
        note_dir = tmp_path / "notes" / "01 - Concepts"
        note_dir.mkdir(parents=True)
        body = " ".join(["word"] * 300)
        (note_dir / "Long Enough.md").write_text(
            f"---\ntitle: Long Enough\ntype: concept\n---\n\n{body}\n",
            encoding="utf-8",
        )
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        batch = {
            "schema_version": "1",
            "cycle_number": 1,
            "batch_number": 1,
            "started_at": now,
            "finished_at": now,
            "topics": [{"title": "Long Enough", "category": "concepts"}],
            "notes_written": ["notes/01 - Concepts/Long Enough.md"],
            "skipped_topics": [],
            "sg_gate_results": [],
            "accepted": True,
            "correction_directive_in": "",
        }
        (pipe / "cycles" / "cycle-001-batch-001.json").write_text(
            json.dumps(batch), encoding="utf-8"
        )

        out = write_report(tmp_path, cycle_number=1)

        gate = json.loads(out.read_text(encoding="utf-8"))["gates"]["CG-006"]
        assert gate["status"] == "PASS", gate["message"]
