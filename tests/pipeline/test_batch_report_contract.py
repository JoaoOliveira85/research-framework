"""Contract tests for per-batch JSON (T052, US4, feature 017).

Validates ``contracts/batch-report.schema.json`` with stdlib-only checks plus
an explicit ``accepted`` ↔ no-``FAIL`` biconditional (not expressible in JSON Schema).
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import pytest

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "specs"
    / "017-vault-quality-fix"
    / "contracts"
    / "batch-report.schema.json"
)


def _root_schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _topic(title: str, cat: str = "concepts", score: float = 0.5) -> dict:
    return {
        "title": title,
        "category": cat,
        "priority_score": score,
        "provenance": "spec_gap",
    }


def _gate(
    gate_id: str,
    status: str,
    *,
    fail_hint: str = "",
) -> dict:
    g: dict = {
        "gate_id": gate_id,
        "status": status,
        "metric_name": "m",
        "metric_value": 0,
        "message": "msg",
    }
    if status == "FAIL":
        g["correction_hint"] = fail_hint or "fixit"
    return g


def _validate_batch_report(d: dict) -> tuple[bool, str]:
    schema = _root_schema()
    required = list(schema["required"])
    props = dict(schema["properties"])
    if d.get("schema_version") != "1":
        return False, "schema_version"
    for k in required:
        if k not in d:
            return False, f"missing:{k}"
    if schema.get("additionalProperties") is False:
        extra = set(d.keys()) - set(props.keys())
        if extra:
            return False, f"extra:{extra}"
    cn = d.get("cycle_number")
    bn = d.get("batch_number")
    if not isinstance(cn, int) or cn < 1:
        return False, "cycle_number"
    if not isinstance(bn, int) or bn < 1:
        return False, "batch_number"

    topics = d.get("topics")
    if not isinstance(topics, list) or not (3 <= len(topics) <= 10):
        return False, "topics_len"
    cat_pat = re.compile(r"^[a-z][a-z0-9_-]*$")
    for t in topics:
        if not isinstance(t, dict):
            return False, "topic_shape"
        for rk in ("title", "category", "priority_score", "provenance"):
            if rk not in t:
                return False, f"topic:{rk}"
        if not isinstance(t["title"], str) or len(t["title"]) < 1:
            return False, "topic:title"
        if not isinstance(t.get("category"), str) or not cat_pat.match(t["category"]):
            return False, "topic:category"
        sc = t.get("priority_score")
        if not isinstance(sc, (int, float)) or not (0 <= float(sc) <= 1):
            return False, "topic:score"
        if t.get("provenance") not in (
            "spec_gap",
            "harvest_orphan",
            "auto_promoted",
        ):
            return False, "topic:provenance"
        if set(t.keys()) - {
            "title",
            "category",
            "priority_score",
            "provenance",
            "source_hints",
            "citation_count",
        }:
            return False, "topic:extra"
        if "source_hints" in t:
            sh = t["source_hints"]
            if not isinstance(sh, list) or not all(isinstance(x, str) for x in sh):
                return False, "topic:source_hints"
        if "citation_count" in t:
            cc = t["citation_count"]
            if not isinstance(cc, int) or cc < 0:
                return False, "topic:citation_count"

    nw = d.get("notes_written")
    if not isinstance(nw, list):
        return False, "notes_written"
    note_pat = re.compile(r"^[a-z0-9_-]+\.md$")
    for fn in nw:
        if not isinstance(fn, str) or not note_pat.match(fn):
            return False, "notes_written:pattern"

    st = d.get("skipped_topics")
    if not isinstance(st, list):
        return False, "skipped_topics"
    allowed_skip = {
        "no_sources",
        "exclusion_match",
        "duplicate_filename",
        "agent_skipped",
        "context_overflow",
        "agent_chose_alternative",
    }
    for row in st:
        if not isinstance(row, dict) or set(row.keys()) - {
            "topic",
            "reason",
            "detail",
        }:
            return False, "skipped_row"
        if row.get("reason") not in allowed_skip:
            return False, "skipped_reason"

    sg = d.get("sg_gate_results")
    if not isinstance(sg, list):
        return False, "sg_gate_results"
    gid_pat = re.compile(r"^[CS]G-\d{3}$")
    statuses = {"PASS", "WARN", "FAIL", "NA"}
    for gr in sg:
        if not isinstance(gr, dict):
            return False, "gate:not_object"
        for gk in ("gate_id", "status", "metric_name", "metric_value", "message"):
            if gk not in gr:
                return False, f"gate:{gk}"
        if not isinstance(gr["gate_id"], str) or not gid_pat.match(gr["gate_id"]):
            return False, "gate:gate_id"
        if gr["status"] not in statuses:
            return False, "gate:status"
        if not isinstance(gr["metric_name"], str):
            return False, "gate:metric_name"
        mv = gr["metric_value"]
        if not isinstance(mv, (int, float, str, bool)):
            return False, "gate:metric_value"
        if gr["status"] == "FAIL" and not str(gr.get("correction_hint", "")).strip():
            return False, "gate:fail_hint"

    for key in ("started_at", "finished_at"):
        raw = d.get(key, "")
        if not isinstance(raw, str):
            return False, key
        try:
            datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return False, f"{key}:iso"

    acc = d.get("accepted")
    if not isinstance(acc, bool):
        return False, "accepted:type"
    has_fail = any(isinstance(x, dict) and x.get("status") == "FAIL" for x in sg)
    if acc == has_fail:
        return False, "accepted_biconditional"

    cdir = d.get("correction_directive_in")
    if not isinstance(cdir, str):
        return False, "correction_directive_in"

    return True, ""


class TestValidBatchReport:
    def test_minimal_valid_accepted_passes(self) -> None:
        topics = [_topic(f"topic{i}", "concepts", 0.5 + i * 0.01) for i in range(3)]
        r = {
            "schema_version": "1",
            "cycle_number": 1,
            "batch_number": 1,
            "started_at": "2026-05-15T10:00:00Z",
            "finished_at": "2026-05-15T10:05:00Z",
            "topics": topics,
            "notes_written": ["alpha_note.md", "b-2.md", "c_3.md"],
            "skipped_topics": [],
            "sg_gate_results": [
                _gate("SG-004", "PASS"),
                _gate("SG-005", "PASS"),
            ],
            "accepted": True,
            "correction_directive_in": "",
        }
        ok, why = _validate_batch_report(r)
        assert ok, why


class TestBatchModuleIntegration:
    """Fails until ``pipeline.batch`` serializes on-disk reports (T055/T056)."""

    def test_batch_module_defines_report_writer(self) -> None:
        import importlib

        try:
            importlib.import_module("research_framework.pipeline.batch")
        except ModuleNotFoundError:
            pytest.fail(
                "research_framework.pipeline.batch must exist for batch report emission"
            )


class TestInvalidBatchReport:
    def test_topics_len_two_invalid(self) -> None:
        topics = [_topic("a"), _topic("b")]
        r = {
            "schema_version": "1",
            "cycle_number": 1,
            "batch_number": 1,
            "started_at": "2026-05-15T10:00:00Z",
            "finished_at": "2026-05-15T10:05:00Z",
            "topics": topics,
            "notes_written": ["a.md", "b.md", "c.md"],
            "skipped_topics": [],
            "sg_gate_results": [_gate("SG-005", "PASS")],
            "accepted": True,
            "correction_directive_in": "",
        }
        ok, why = _validate_batch_report(r)
        assert not ok
        assert "topics_len" in why

    def test_topics_len_eleven_invalid(self) -> None:
        topics = [_topic(f"t{i}") for i in range(11)]
        r = {
            "schema_version": "1",
            "cycle_number": 1,
            "batch_number": 1,
            "started_at": "2026-05-15T10:00:00Z",
            "finished_at": "2026-05-15T10:05:00Z",
            "topics": topics,
            "notes_written": ["a.md", "b.md", "c.md"],
            "skipped_topics": [],
            "sg_gate_results": [_gate("SG-005", "PASS")],
            "accepted": True,
            "correction_directive_in": "",
        }
        ok, why = _validate_batch_report(r)
        assert not ok

    def test_notes_written_uppercase_invalid(self) -> None:
        topics = [_topic(f"t{i}") for i in range(3)]
        r = {
            "schema_version": "1",
            "cycle_number": 1,
            "batch_number": 1,
            "started_at": "2026-05-15T10:00:00Z",
            "finished_at": "2026-05-15T10:05:00Z",
            "topics": topics,
            "notes_written": ["Invalid Name.md"],
            "skipped_topics": [],
            "sg_gate_results": [_gate("SG-005", "PASS")],
            "accepted": True,
            "correction_directive_in": "",
        }
        ok, why = _validate_batch_report(r)
        assert not ok

    def test_accepted_true_with_sg_fail_invalid(self) -> None:
        topics = [_topic(f"t{i}") for i in range(3)]
        r = {
            "schema_version": "1",
            "cycle_number": 1,
            "batch_number": 1,
            "started_at": "2026-05-15T10:00:00Z",
            "finished_at": "2026-05-15T10:05:00Z",
            "topics": topics,
            "notes_written": ["a.md"],
            "skipped_topics": [],
            "sg_gate_results": [_gate("SG-005", "FAIL")],
            "accepted": True,
            "correction_directive_in": "",
        }
        ok, why = _validate_batch_report(r)
        assert why == "accepted_biconditional"

    def test_accepted_false_with_no_fail_invalid(self) -> None:
        topics = [_topic(f"t{i}") for i in range(3)]
        r = {
            "schema_version": "1",
            "cycle_number": 1,
            "batch_number": 1,
            "started_at": "2026-05-15T10:00:00Z",
            "finished_at": "2026-05-15T10:05:00Z",
            "topics": topics,
            "notes_written": ["a.md", "b.md"],
            "skipped_topics": [],
            "sg_gate_results": [_gate("SG-005", "PASS")],
            "accepted": False,
            "correction_directive_in": "",
        }
        ok, why = _validate_batch_report(r)
        assert why == "accepted_biconditional"
