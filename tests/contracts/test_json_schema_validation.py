"""Tier-2 contract tests wiring committed JSON Schemas to real artifacts (#295).

Before this file, 7 of the 20 committed ``*.schema.json`` files under
``specs/*/contracts/`` had no non-prose referent anywhere in the tree — no
code, no test, no other schema ``$ref``. ``jsonschema`` was not a dependency
and nothing in the repo ever called ``jsonschema.validate`` on anything: all
20 schemas were prose. Five of the seven describe artifacts the framework
still writes today; this module validates each of those five against REAL
output from the production code that writes them (not a hand-typed literal
that merely looks like the shape).

The other two (``tiers.schema.json``, ``consensus-result.schema.json``) were
reported in issue #295 as having no writer at all — verification for this fix
found that claim stale: both describe live, actively-used surfaces
(``settings.yaml::tiers`` via ``pipeline.settings._parse_tiers``, and
``_pipeline/sources/<module>/consensus/*.json`` via
``source_bridge.consensus.write_consensus_result``, called from
``source_bridge.orchestrator``). Both are wired here instead of being
deleted.

``agent-call-record.schema.json`` (spec 020) is NOT wired here: verification
found it describes a shape the shipped sidecar writer never actually used —
``tests/scripts/test_agent_call_sidecar_v1.py`` wires the schema that matches
reality (``tests/fixtures/contracts/agent-call-sidecar-1.1.schema.json``,
spec 028). ``agent-call-record.schema.json`` now carries a ``$comment``
tombstone pointing at the winner rather than being deleted, since the
directory it names is real, just not in that shape.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
import yaml

from research_framework.pipeline import runner
from research_framework.pipeline.preflight import PreflightResult, SourceCheck
from research_framework.pipeline.settings import load_vault_settings
from research_framework.pipeline.source_bridge.cache import (
    WatermarkEntry,
    load_watermarks,
    save_watermarks,
)
from research_framework.pipeline.source_bridge.consensus import ConsensusResult
from research_framework.pipeline.source_bridge.validators import load_yaml_validator

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_schema(*relative_parts: str) -> dict:
    path = REPO_ROOT.joinpath(*relative_parts)
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# pipeline-state.schema.json — _pipeline/pipeline-state.json, written by
# pipeline/runner.py (runner._blank_state / runner._save_state). Authored under
# spec 015g; it now lives with spec 075, which supersedes 015g as the runner's
# owning document. A schema a test opens cannot live in specs/_archive/ — the
# archive rule is "no tracked file outside specs/ opens a file inside it"
# (specs/_archive/README.md), and this was the one violation of it (#295).
# ---------------------------------------------------------------------------


def test_blank_pipeline_state_validates_against_schema() -> None:
    schema = _load_schema(
        "specs", "075-pipeline-runner", "contracts", "pipeline-state.schema.json"
    )
    state = runner._blank_state("2026-09-07-1200", "2026-09-07T12:00:00Z")
    jsonschema.validate(state, schema)


def test_real_saved_pipeline_state_file_validates_after_a_phase_transition(
    tmp_path: Path,
) -> None:
    """A state file the real runner writes and reads back, not just the

    blank shape — one phase moved through in_progress -> done with a
    populated summary and an error, exercising the fuller PhaseRecord shape.
    """
    schema = _load_schema(
        "specs", "075-pipeline-runner", "contracts", "pipeline-state.schema.json"
    )
    vault = tmp_path / "vault"
    vault.mkdir()
    state = runner._load_state(vault)
    runner._set_phase(
        state,
        "collect",
        phase_status=runner.DONE,
        started_at="2026-09-07T12:00:00Z",
        finished_at="2026-09-07T12:00:05Z",
        summary={"collected": 3},
        errors=["a transient warning, recorded but non-fatal"],
    )
    runner._save_state(vault, state)

    written = json.loads((vault / runner.STATE_FILE).read_text(encoding="utf-8"))
    jsonschema.validate(written, schema)


# ---------------------------------------------------------------------------
# preflight.schema.json — spec 017, _pipeline/preflight.json, written by
# pipeline/preflight.py (PreflightResult.to_json_path), read by
# pipeline/preconditions.py.
# ---------------------------------------------------------------------------


def test_real_preflight_result_validates_against_schema(tmp_path: Path) -> None:
    schema = _load_schema(
        "specs", "017-vault-quality-fix", "contracts", "preflight.schema.json"
    )
    result = PreflightResult(
        generated_at="2026-09-07T12:00:00Z",
        framework_version="1.1.1",
        sources=[
            SourceCheck(
                name="Hacker News RSS",
                role="required",
                type="rss",
                status="ok",
                detail="200 OK",
                checked_at="2026-09-07T12:00:00Z",
                elapsed_ms=120,
            ),
            SourceCheck(
                name="Optional Blog",
                role="enrichment",
                type="web",
                status="degraded",
                detail="slow response",
                checked_at="2026-09-07T12:00:01Z",
                elapsed_ms=4800,
            ),
        ],
        required_unreachable_count=0,
        enrichment_unreachable_count=0,
        overall_status="warn",
    )
    out_path = tmp_path / "preflight.json"
    result.to_json_path(out_path)
    written = json.loads(out_path.read_text(encoding="utf-8"))
    jsonschema.validate(written, schema)


# ---------------------------------------------------------------------------
# watermark.schema.json — spec 020, per-module <vault>/_pipeline/sources/
# <module>/watermarks.json, written/read by source_bridge/cache.py.
# ---------------------------------------------------------------------------


def test_real_saved_watermarks_file_validates_against_schema(tmp_path: Path) -> None:
    """save_watermarks uses dataclasses.asdict on every WatermarkEntry —

    this caught the schema missing `recent_cycle_verdicts` (added by this
    same fix): every real watermarks.json carries that field, and the
    schema's `additionalProperties: false` rejected it before the fix.
    """
    schema = _load_schema(
        "specs", "020-code-bridge", "contracts", "watermark.schema.json"
    )
    watermarks = {
        "https://example.com/feed.xml": WatermarkEntry(
            source_version="etag-abc123",
            bridge_version="1.4.0",
            extracted_at="2026-09-07T12:00:00Z",
            verdict="ok",
            consensus={"n": 3, "majority": 2, "agreed_at": "2026-09-07T12:00:05Z"},
            consecutive_empty_cycles=0,
            recent_cycle_verdicts=["ok", "ok", "empty"],
        ),
    }
    save_watermarks(tmp_path, "rss", watermarks)
    written = json.loads(
        (tmp_path / "_pipeline" / "sources" / "rss" / "watermarks.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(written, schema)

    # Round-trips through the real reader too.
    reloaded = load_watermarks(tmp_path, "rss")
    assert reloaded["https://example.com/feed.xml"].recent_cycle_verdicts == [
        "ok",
        "ok",
        "empty",
    ]


# ---------------------------------------------------------------------------
# validator-yaml.schema.json — spec 020, <vault>/<module>.validators.yaml,
# read by source_bridge/validators.py::load_yaml_validator.
# ---------------------------------------------------------------------------


def test_real_loaded_validator_yaml_validates_against_schema(tmp_path: Path) -> None:
    schema = _load_schema(
        "specs", "020-code-bridge", "contracts", "validator-yaml.schema.json"
    )
    yaml_path = tmp_path / "rss.validators.yaml"
    yaml_path.write_text(
        yaml.safe_dump(
            {
                "facts": {
                    "headlines": {"required": True, "min_items": 1, "max_items": 50},
                },
                "notable": {"min_items": 0, "require_evidence_ref": True},
            }
        ),
        encoding="utf-8",
    )
    loaded = load_yaml_validator(tmp_path, "rss")
    assert loaded is not None
    jsonschema.validate(loaded, schema)


# ---------------------------------------------------------------------------
# consensus-result.schema.json — spec 020, _pipeline/sources/<module>/
# consensus/<id>-cycle-NNN.json. Issue #295 reported "no such writer found";
# verification found source_bridge/consensus.py::write_consensus_result IS
# called (source_bridge/orchestrator.py) — the artifact is real.
# ---------------------------------------------------------------------------


def test_real_consensus_result_validates_against_schema() -> None:
    schema = _load_schema(
        "specs", "020-code-bridge", "contracts", "consensus-result.schema.json"
    )
    result = ConsensusResult(
        module="rss",
        source_id="https://example.com/feed.xml",
        cycle=3,
        value_tier="important",
        extractors_spawned=3,
        verdicts=["ok", "ok", "empty"],
        final_verdict="ok",
        findings_unioned=12,
        dissenting_extractor_indices=[2],
        consensus_decided_at="2026-09-07T12:00:05Z",
    )
    jsonschema.validate(result.to_dict(), schema)


# ---------------------------------------------------------------------------
# tiers.schema.json — settings.yaml::tiers, loaded by
# pipeline/settings.py::load_vault_settings (_parse_tiers). Issue #295
# characterized this as validated only "by hand" with no committed contract
# it round-trips against — it does now.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tiers_yaml",
    [
        None,  # absent -> defaults
        {
            "basic": "claude-haiku-4-5",
            "normal": "claude-sonnet-5",
            "flagship": "claude-opus-5",
        },
        {
            "basic": "claude-haiku-4-5",
            "normal": "claude-sonnet-5",
            "flagship": "claude-opus-5",
            "cheap-local": "ollama/llama3",  # vault authors may add custom tiers
        },
    ],
)
def test_real_loaded_tiers_validates_against_schema(
    tmp_path: Path, tiers_yaml: dict | None
) -> None:
    schema = _load_schema("specs", "020-code-bridge", "contracts", "tiers.schema.json")
    settings_dict: dict = {"pipeline": {"max_cycles": 5, "budget_usd": 10.0}}
    if tiers_yaml is not None:
        settings_dict["tiers"] = tiers_yaml
    (tmp_path / "settings.yaml").write_text(
        yaml.safe_dump(settings_dict), encoding="utf-8"
    )
    settings = load_vault_settings(tmp_path)
    jsonschema.validate(settings.tiers, schema)


# ---------------------------------------------------------------------------
# run-receipt-1.0.schema.json — spec 080 FR-007, `_pipeline/runs/<run_id>/
# run.json`, written by pipeline/run_receipt.py on every phase close. Validated
# against a receipt the REAL runner wrote, the way #326 wired the state schema:
# a hand-typed literal that merely looks like the shape proves nothing about
# the producer.
# ---------------------------------------------------------------------------


def test_real_run_receipt_validates_against_schema(tmp_path: Path) -> None:
    from research_framework.pipeline import run_receipt
    from research_framework.pipeline.runner import PHASES, run_full

    schema = _load_schema("tests", "contracts", "run-receipt-1.0.schema.json")

    vault = tmp_path / "vault"
    script = vault / "scripts" / "agent_call.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("import sys; sys.exit(0)\n", encoding="utf-8")
    (vault / "data_vault").mkdir(parents=True, exist_ok=True)

    run_full(vault, quiet=True)

    state = json.loads(
        (vault / "_pipeline" / "pipeline-state.json").read_text(encoding="utf-8")
    )
    receipt_path = run_receipt.run_dir_for(vault, state["run_id"]) / "run.json"
    jsonschema.validate(json.loads(receipt_path.read_text(encoding="utf-8")), schema)
    # And every phase the runner knows about is described, not just the ones
    # that happened to run.
    written = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert set(written["phases"]) == set(PHASES)


def test_a_two_point_zero_receipt_is_refused(tmp_path: Path) -> None:
    """ADR-0013: additive within a major, a new schema file per major. A
    consumer pinned to 1.x must refuse a 2.0 payload rather than read it
    optimistically."""
    schema = _load_schema("tests", "contracts", "run-receipt-1.0.schema.json")
    payload = {
        "schema_version": "2.0",
        "run_id": "r",
        "vault": "/v",
        "started_at": None,
        "finished_at": None,
        "framework_version": "1.3.0",
        "reconstructed": False,
        "verbs": [],
        "phases": {},
        "artifacts": {
            "scout_report": None,
            "research_report": None,
            "verify_report": None,
            "latest_export": None,
            "context_tree": None,
        },
        "cost": {"total_usd": 0.0, "sidecars_read": 0, "sidecars_missing": 0},
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)
