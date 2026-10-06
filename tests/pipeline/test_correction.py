"""Tests for correction directives (T039, feature 017).

Per `data-model.md` E-006 and `contracts/correction-directive.schema.json`:

- Construction rejects empty ``failing_gate_ids`` or ``required_actions``.
- ``to_prompt_block()`` is Markdown with headings; lists failing gates and
  required actions verbatim.
- Expired directives are filtered by ``gc_expired``; persistence paths split
  cycle-wide vs per-batch under ``_pipeline/corrections/``.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from research_framework.pipeline.gates import GateResult


def _directive_schema() -> dict:
    p = (
        Path(__file__).resolve().parents[2]
        / "specs"
        / "017-vault-quality-fix"
        / "contracts"
        / "correction-directive.schema.json"
    )
    return json.loads(p.read_text(encoding="utf-8"))


def _matches_directive(d: dict, schema: dict) -> tuple[bool, str]:
    for k in schema.get("required", []):
        if k not in d:
            return False, f"missing {k}"
    if schema.get("additionalProperties") is False:
        allowed = set(schema.get("properties", {}).keys())
        if set(d.keys()) - allowed:
            return False, "extra keys"
    if d.get("schema_version") != "1":
        return False, "schema_version"
    fg = d.get("failing_gate_ids")
    if not isinstance(fg, list) or len(fg) < 1:
        return False, "failing_gate_ids"
    ra = d.get("required_actions")
    if not isinstance(ra, list) or len(ra) < 1:
        return False, "required_actions"
    gpat = re.compile(r"^[CS]G-\d{3}$")
    for g in fg:
        if not isinstance(g, str) or not gpat.match(g):
            return False, "gate id in list"
    return True, ""


class TestCorrectionDirectiveConstruction:
    """Validation rules on the dataclass."""

    def test_requires_non_empty_failing_gate_ids(self) -> None:
        from research_framework.pipeline.correction import CorrectionDirective

        with pytest.raises(ValueError, match="failing_gate"):
            CorrectionDirective(
                cycle_number=1,
                batch_number=None,
                failing_gate_ids=[],
                diagnosis="d",
                required_actions=["act"],
                forbidden_actions=[],
                expires_after_cycle=2,
            )

    def test_requires_non_empty_required_actions(self) -> None:
        from research_framework.pipeline.correction import CorrectionDirective

        with pytest.raises(ValueError, match="required_actions"):
            CorrectionDirective(
                cycle_number=1,
                batch_number=1,
                failing_gate_ids=["CG-001"],
                diagnosis="d",
                required_actions=[],
                forbidden_actions=[],
                expires_after_cycle=2,
            )


class TestCorrectionDirectivePromptMarkdown:
    """Injectable Markdown for agent prompts."""

    def test_to_prompt_block_lists_gates_and_actions(self) -> None:
        from research_framework.pipeline.correction import CorrectionDirective

        d = CorrectionDirective(
            cycle_number=3,
            batch_number=2,
            failing_gate_ids=["CG-001", "SG-005"],
            diagnosis="Cycle behind on yield and frontmatter",
            required_actions=["Write ≥ minimum notes", "Fix frontmatter"],
            forbidden_actions=["Do not skip sources"],
            expires_after_cycle=4,
        )
        md = d.to_prompt_block()
        assert "#" in md
        assert "CG-001" in md
        assert "SG-005" in md
        assert "Write ≥ minimum notes" in md
        assert "Fix frontmatter" in md


class TestBuildDirectivePersistence:
    """``build_directive`` writes JSON under ``_pipeline/corrections/``."""

    def test_cycle_wide_path_cycle_only(self, tmp_path: Path) -> None:
        from research_framework.pipeline.correction import build_directive

        corr = tmp_path / "_pipeline" / "corrections"
        corr.mkdir(parents=True, exist_ok=True)
        fails = [
            GateResult(
                gate_id="CG-002",
                status="FAIL",
                metric_name="cats",
                metric_value=1,
                threshold=5,
                message="single category",
                correction_hint="broaden categories",
            )
        ]
        path = build_directive(
            tmp_path,
            failing_gates=fails,
            cycle=7,
            batch=None,
        )
        assert path == corr / "cycle-007.json"
        assert path.is_file()
        data = json.loads(path.read_text(encoding="utf-8"))
        ok, why = _matches_directive(data, _directive_schema())
        assert ok, why

    def test_per_batch_path_includes_batch_index(self, tmp_path: Path) -> None:
        from research_framework.pipeline.correction import build_directive

        corr = tmp_path / "_pipeline" / "corrections"
        corr.mkdir(parents=True, exist_ok=True)
        fails = [
            GateResult(
                gate_id="SG-005",
                status="FAIL",
                metric_name="fm",
                metric_value=0,
                threshold=1,
                message="missing keys",
                correction_hint="add frontmatter",
            )
        ]
        path = build_directive(tmp_path, failing_gates=fails, cycle=4, batch=12)
        assert path == corr / "cycle-004-batch-012.json"
        assert path.is_file()


class TestGcExpiredDirectives:
    """Drop persisted directives past ``expires_after_cycle``."""

    def test_gc_removes_expired_files(self, tmp_path: Path) -> None:
        from research_framework.pipeline.correction import gc_expired

        corr = tmp_path / "_pipeline" / "corrections"
        corr.mkdir(parents=True, exist_ok=True)
        stale = {
            "schema_version": "1",
            "cycle_number": 1,
            "batch_number": None,
            "failing_gate_ids": ["CG-001"],
            "diagnosis": "old",
            "required_actions": ["x"],
            "forbidden_actions": [],
            "expires_after_cycle": 2,
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        (corr / "cycle-001.json").write_text(json.dumps(stale), encoding="utf-8")
        removed = gc_expired(tmp_path, current_cycle=5)
        assert removed >= 1
        assert not (corr / "cycle-001.json").exists()

    def test_boundary_keeps_current_cycle_directive(self, tmp_path: Path) -> None:
        from research_framework.pipeline.correction import gc_expired

        corr = tmp_path / "_pipeline" / "corrections"
        corr.mkdir(parents=True, exist_ok=True)
        fresh = {
            "schema_version": "1",
            "cycle_number": 3,
            "batch_number": 1,
            "failing_gate_ids": ["CG-003"],
            "diagnosis": "active",
            "required_actions": ["y"],
            "forbidden_actions": [],
            "expires_after_cycle": 10,
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        p = corr / "cycle-003-batch-001.json"
        p.write_text(json.dumps(fresh), encoding="utf-8")
        gc_expired(tmp_path, current_cycle=3)
        assert p.is_file()
