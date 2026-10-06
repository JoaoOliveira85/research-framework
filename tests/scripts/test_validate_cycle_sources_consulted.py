"""H2 regression: v2 scout + research reports MUST validate
``sources_consulted`` against the spec's required sources.

Background (spec-019 / 0.2.28):

``scripts/validate_cycle.py`` v1 path (``check_termination``) calls
``validate_sources(report, required, optional)`` at line 227-228 to
ensure required sources appear in the agent's ``sources_consulted``
dict.

The v2 path (``check_termination_v2``) — used for ALL post-017 vaults —
NEVER calls ``validate_sources``. ``REQUIRED_REPORT_FIELDS_V2`` only
checks that the KEY ``sources_consulted`` is present; the VALUE can be
``[]``, ``{}``, or even an unrelated type, and validation passes.

This makes the spec's ``required: true`` flag effectively dead for v2:
an agent that skips every required source still produces a "valid"
report.

v0.2.28 wires the v1 ``validate_sources`` (or a v2-shaped equivalent)
into ``check_termination_v2`` for both scout and research phases.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "validate_cycle.py"


def _load_vc():
    module_name = "validate_cycle_sources_consulted_under_test"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


@pytest.fixture(scope="module")
def vc():
    return _load_vc()


def _write_spec_parse(pipeline_dir: Path, sources: list[dict]) -> None:
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    (pipeline_dir / "spec-parse.json").write_text(
        json.dumps({"name": "T", "data_sources": sources}),
        encoding="utf-8",
    )


def _scout_v2_report(sources_consulted) -> dict:
    """A minimal v2 scout report shape that satisfies all structural
    checks EXCEPT for sources_consulted, which the caller controls."""
    return {
        "schema_version": "2.0",
        "cycle": 1,
        "phase": "scout",
        "timestamp": "2026-05-17T22:00:00Z",
        "dimensions_covered": [
            "technical",
            "organizational",
            "domain",
            "market",
            "temporal",
        ],
        "topics_from_code": [
            {
                "id": "CT-1-001",
                "topic_type": "service",
                "source_file": "acme-corp/oebh-service/README.md",
                "source_snippet": "L1-10",
                "proposed_filename": "oebh.md",
            }
        ],
        "intent_from_confluence": [],
        "topics_found": {"new": [], "existing": [], "total": 0},
        "proposed_filenames": ["oebh.md"],
        "sources_consulted": sources_consulted,
        "access_methods_used": {},
        "termination_condition": None,
        "notes_created": [],
        "unresolved_wikilinks": [],
        "budget_consumed_usd": 0.0,
    }


def _required_repo_source() -> dict:
    """The 'Local Team Service Repositories' source the user's
    research.spec.md lists as required priority-1 behaviour."""
    return {
        "name": "Local Team Service Repositories",
        "type": "internal",
        "role": "behaviour",
        "priority": 1,
        "required": True,
        "repos": [
            {
                "name": "oebh-service",
                "url": "https://github.com/acme-corp/oebh-service",
                "local_path": "/x/acme-corp/oebh-service",
            }
        ],
    }


def test_v2_scout_empty_dict_sources_consulted_aborts_with_missing_source(
    vc, tmp_path: Path
) -> None:
    """Pre-v0.2.28 this returned CONTINUE (sources_consulted not
    validated). v0.2.28 must ABORT with an error naming the missing
    required source. Dict form (v1-shaped)."""
    pipeline_dir = tmp_path / "_pipeline"
    _write_spec_parse(pipeline_dir, [_required_repo_source()])

    report = _scout_v2_report(sources_consulted={})
    result = vc.check_termination_v2(
        report,
        max_cycles=5,
        budget_cap=100.0,
        vault_dir=None,
        pipeline_dir=pipeline_dir,
    )

    assert result.status == "ABORT", (
        "v2 scout with empty sources_consulted MUST abort when the "
        f"spec lists a required source. Got {result.status}: {result.reason}"
    )
    combined = " ".join(result.errors)
    assert (
        "local_team_service_repositories" in combined.lower()
        or "required source" in combined.lower()
    ), f"expected error to name the missing required source; got: {combined}"


def test_v2_scout_empty_list_sources_consulted_aborts_with_missing_source(
    vc, tmp_path: Path
) -> None:
    """An agent that emits ``sources_consulted: []`` (LIST — the shape
    the v2 prompt example at line 269 instructs) with no required
    source listed MUST abort."""
    pipeline_dir = tmp_path / "_pipeline"
    _write_spec_parse(pipeline_dir, [_required_repo_source()])

    report = _scout_v2_report(sources_consulted=[])
    result = vc.check_termination_v2(
        report,
        max_cycles=5,
        budget_cap=100.0,
        vault_dir=None,
        pipeline_dir=pipeline_dir,
    )
    assert result.status == "ABORT", (
        f"v2 scout with empty list sources MUST abort; got {result.status}"
    )
    combined = " ".join(result.errors)
    assert "required source" in combined.lower() or "local_team" in combined.lower()


def test_v2_scout_wrong_type_sources_consulted_aborts(vc, tmp_path: Path) -> None:
    """``sources_consulted: "GitHub"`` (string) or ``: 42`` (int) is
    a contract violation. ABORT with a clear shape error."""
    pipeline_dir = tmp_path / "_pipeline"
    _write_spec_parse(pipeline_dir, [_required_repo_source()])

    for wrong in ["GitHub", 42, True]:
        report = _scout_v2_report(sources_consulted=wrong)
        result = vc.check_termination_v2(
            report,
            max_cycles=5,
            budget_cap=100.0,
            vault_dir=None,
            pipeline_dir=pipeline_dir,
        )
        assert result.status == "ABORT", (
            f"sources_consulted={wrong!r} (type {type(wrong).__name__}) "
            f"must abort; got {result.status}"
        )
        combined = " ".join(result.errors)
        assert "sources_consulted" in combined.lower()


def test_v2_scout_dict_with_required_source_searched_continues(
    vc, tmp_path: Path
) -> None:
    """Sanity (dict form): a well-formed sources_consulted with the
    required source marked ``searched: true`` continues."""
    pipeline_dir = tmp_path / "_pipeline"
    _write_spec_parse(pipeline_dir, [_required_repo_source()])

    report = _scout_v2_report(
        sources_consulted={
            "local_team_service_repositories": {
                "searched": True,
                "results_count": 1,
            }
        }
    )
    result = vc.check_termination_v2(
        report,
        max_cycles=5,
        budget_cap=100.0,
        vault_dir=None,
        pipeline_dir=pipeline_dir,
    )
    assert result.status == "CONTINUE", (
        f"well-formed required source must pass; got {result.status}: {result.reason}"
    )


def test_v2_scout_list_with_required_source_name_continues(vc, tmp_path: Path) -> None:
    """Sanity (list form, v2 prompt example shape): a list that
    includes the required source by NAME or normalized key continues."""
    pipeline_dir = tmp_path / "_pipeline"
    _write_spec_parse(pipeline_dir, [_required_repo_source()])

    # Original-name form (matches v2 prompt example: "GitHub repos").
    report = _scout_v2_report(
        sources_consulted=["Local Team Service Repositories", "Confluence"]
    )
    result = vc.check_termination_v2(
        report,
        max_cycles=5,
        budget_cap=100.0,
        vault_dir=None,
        pipeline_dir=pipeline_dir,
    )
    assert result.status == "CONTINUE", (
        f"list form with required source by name must pass; got "
        f"{result.status}: {result.reason}"
    )

    # Normalized-key form (defensive: agent followed v1 convention).
    report = _scout_v2_report(sources_consulted=["local_team_service_repositories"])
    result = vc.check_termination_v2(
        report,
        max_cycles=5,
        budget_cap=100.0,
        vault_dir=None,
        pipeline_dir=pipeline_dir,
    )
    assert result.status == "CONTINUE", (
        f"list form with required source by normalized key must pass; "
        f"got {result.status}: {result.reason}"
    )


def test_v2_scout_required_source_skipped_with_reason_emits_warning(
    vc, tmp_path: Path
) -> None:
    """A required source present in sources_consulted dict but marked
    ``searched: false`` should emit a WARNING (matching v1 behaviour),
    not an abort — the agent acknowledged the source and gave a reason."""
    pipeline_dir = tmp_path / "_pipeline"
    _write_spec_parse(pipeline_dir, [_required_repo_source()])

    report = _scout_v2_report(
        sources_consulted={
            "local_team_service_repositories": {
                "searched": False,
                "reason": "filesystem permission denied",
            }
        }
    )
    result = vc.check_termination_v2(
        report,
        max_cycles=5,
        budget_cap=100.0,
        vault_dir=None,
        pipeline_dir=pipeline_dir,
    )
    assert result.status == "CONTINUE", (
        f"skip-with-reason must warn not abort; got {result.status}"
    )
    combined = " ".join(result.warnings)
    assert (
        "local_team_service_repositories" in combined.lower()
        or "not searched" in combined.lower()
    ), f"expected warning naming the source; got warnings: {result.warnings}"
