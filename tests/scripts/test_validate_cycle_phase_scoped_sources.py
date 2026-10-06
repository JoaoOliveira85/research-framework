"""spec-019 / 0.2.30 — sources_consulted enforcement MUST be phase-scoped.

Background — user trial-run failure 2026-05-18:

The user's reference-vault spec lists 13 data sources. Two are
``priority=1, role=behaviour`` (local repos), two are ``priority=2,
role=intent`` (PR conversations, Confluence notes), and nine are
``priority=2, role=domain`` (Spring docs, Oracle Java, Cassandra,
OWASP — external reference documentation).

The scout phase walks code (behaviour) and intent surfaces (PRs,
Confluence). It does NOT consult docs sources — those are for the
research/DFS phase to fetch when writing notes.

The 0.2.28 H2 enforcement uniformly demanded every ``required: true``
source appear in every cycle's ``sources_consulted``. This forced the
scout to claim it had consulted the docs sources it never touches, OR
abort the cycle. The user hit this in cycle 1 of every release since
0.2.28.

0.2.30 makes the enforcement phase-aware:
- scout reports require sources with role in {behaviour, intent}.
- research reports require all ``required: true`` sources.
- role=domain sources are docs-only and not required for scout.

A spec without explicit ``role`` defaults to ``behaviour`` (the
backwards-compatible interpretation: pre-role-aware specs treated all
sources as scout-relevant).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "validate_cycle.py"


def _load_vc():
    module_name = "validate_cycle_phase_scoped_under_test"
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


def _write_spec_with_roles(pipeline_dir: Path) -> None:
    """Mirror the user's reference-vault spec shape: mixed roles + priorities."""
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    (pipeline_dir / "spec-parse.json").write_text(
        json.dumps(
            {
                "name": "reference-vault",
                "data_sources": [
                    {
                        "name": "Local Team Service Repositories",
                        "required": True,
                        "role": "behaviour",
                        "priority": 1,
                    },
                    {
                        "name": "GitHub Pull Requests and Review Conversations",
                        "required": True,
                        "role": "intent",
                        "priority": 2,
                    },
                    {
                        "name": "Spring Framework Reference Documentation",
                        "required": True,
                        "role": "domain",
                        "priority": 2,
                    },
                    {
                        "name": "Oracle Java Documentation",
                        "required": True,
                        "role": "domain",
                        "priority": 2,
                    },
                    {
                        "name": "OWASP Developer and Security Guidance",
                        "required": True,
                        "role": "domain",
                        "priority": 2,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def test_spec_data_sources_scout_phase_excludes_domain_sources(
    tmp_path: Path, vc
) -> None:
    """Bug B fix: when phase=scout, ``_spec_data_sources`` MUST return
    only ``role in {behaviour, intent}`` sources as required.

    The user's failure was the scout being asked to list docs sources
    (role=domain) it never consults. Phase-scoping removes that
    nonsensical requirement.
    """
    pipeline = tmp_path / "_pipeline"
    _write_spec_with_roles(pipeline)
    required, optional = vc._spec_data_sources(pipeline, phase="scout")
    required_lower = {r.lower() for r in required}
    # Behaviour + intent must be present.
    assert any("local_team" in r or "local team" in r for r in required_lower), (
        f"behaviour source missing from scout's required list: {required}"
    )
    assert any("github" in r or "pull request" in r for r in required_lower), (
        f"intent source missing from scout's required list: {required}"
    )
    # Domain sources must NOT be in scout's required list.
    domain_substrings = ["spring", "oracle", "owasp"]
    for sub in domain_substrings:
        assert not any(sub in r for r in required_lower), (
            f"domain source matching '{sub}' must NOT be required for the "
            f"scout phase — scout doesn't consult docs. Got: {required}"
        )


def test_spec_data_sources_research_phase_includes_all_sources(
    tmp_path: Path, vc
) -> None:
    """Symmetric guarantee: research phase requires ALL ``required: true``
    sources regardless of role. The docs sources scout skipped are the
    research phase's responsibility.
    """
    pipeline = tmp_path / "_pipeline"
    _write_spec_with_roles(pipeline)
    required, optional = vc._spec_data_sources(pipeline, phase="research")
    required_lower = {r.lower() for r in required}
    for sub in ["local_team", "github", "spring", "oracle", "owasp"]:
        assert any(sub in r or sub.replace("_", " ") in r for r in required_lower), (
            f"research phase MUST require source matching '{sub}'; got {required}"
        )


def test_spec_data_sources_no_phase_argument_preserves_legacy_behaviour(
    tmp_path: Path, vc
) -> None:
    """Backwards compat: callers that don't pass ``phase`` MUST get the
    pre-0.2.30 behaviour (all required sources).

    The non-v2 ``check_termination`` path still calls
    ``_spec_data_sources`` without phase — we cannot break it.
    """
    pipeline = tmp_path / "_pipeline"
    _write_spec_with_roles(pipeline)
    required, optional = vc._spec_data_sources(pipeline)
    required_lower = {r.lower() for r in required}
    for sub in ["spring", "oracle", "owasp"]:
        assert any(sub in r for r in required_lower), (
            "no-phase call must include domain sources (legacy behaviour); "
            f"got {required}"
        )


def test_scout_report_passes_when_only_behaviour_and_intent_consulted(
    tmp_path: Path, vc
) -> None:
    """End-to-end: a scout report listing only behaviour + intent
    sources passes ``check_termination_v2``. This is the exact shape
    the user's cycle 1 scout produced — under 0.2.28/0.2.29 it
    aborted; under 0.2.30 it must CONTINUE.
    """
    pipeline = tmp_path / "_pipeline"
    _write_spec_with_roles(pipeline)
    report = {
        "schema_version": "2.0",
        "cycle": 1,
        "phase": "scout",
        "timestamp": "2026-05-18T12:00:00Z",
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
                "source_file": "acme/svc/README.md",
                "source_snippet": "x",
            }
        ],
        "intent_from_confluence": [],
        # Principle VI (issue #293): a continuing scout MUST propose the
        # filenames its DFS will write, so the pre-write collision check can run.
        "proposed_filenames": ["Svc.md"],
        "sources_consulted": [
            "Local Team Service Repositories",
            "GitHub Pull Requests and Review Conversations",
        ],
        "termination_condition": None,
        "budget_consumed_usd": 1.0,
    }
    result = vc.check_termination_v2(
        report,
        max_cycles=5,
        budget_cap=50.0,
        vault_dir=tmp_path,
        pipeline_dir=pipeline,
    )
    assert result.status != "ABORT", (
        f"scout listing behaviour+intent sources MUST not abort under "
        f"phase-scoped enforcement; got status={result.status} "
        f"reason={result.reason} errors={result.errors}"
    )


def test_scout_report_aborts_when_behaviour_source_missing(tmp_path: Path, vc) -> None:
    """Phase scoping doesn't *weaken* enforcement — a scout that fails
    to list a required behaviour source still aborts. This is the
    correctness boundary: scoping isn't permissiveness.
    """
    pipeline = tmp_path / "_pipeline"
    _write_spec_with_roles(pipeline)
    report = {
        "schema_version": "2.0",
        "cycle": 1,
        "phase": "scout",
        "timestamp": "2026-05-18T12:00:00Z",
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
                "source_file": "acme/svc/README.md",
                "source_snippet": "x",
            }
        ],
        "intent_from_confluence": [],
        # Principle VI (issue #293): a continuing scout MUST propose the
        # filenames its DFS will write, so the pre-write collision check can run.
        "proposed_filenames": ["Svc.md"],
        "sources_consulted": [
            "GitHub Pull Requests and Review Conversations",
        ],
        "termination_condition": None,
        "budget_consumed_usd": 1.0,
    }
    result = vc.check_termination_v2(
        report,
        max_cycles=5,
        budget_cap=50.0,
        vault_dir=tmp_path,
        pipeline_dir=pipeline,
    )
    assert result.status == "ABORT"
    assert any(
        "local_team_service_repositories" in e.lower() or "local team" in e.lower()
        for e in result.errors
    ), f"missing behaviour source must be named in errors: {result.errors}"


def test_research_report_aborts_when_domain_source_missing(tmp_path: Path, vc) -> None:
    """Symmetric: research-phase reports MUST require docs sources.
    The 0.2.30 leniency applies only to scout, not research.
    """
    pipeline = tmp_path / "_pipeline"
    _write_spec_with_roles(pipeline)
    report = {
        "schema_version": "2.0",
        "cycle": 1,
        "phase": "research",
        "timestamp": "2026-05-18T12:00:00Z",
        "sources_consulted": [
            "Local Team Service Repositories",
            "GitHub Pull Requests and Review Conversations",
            # Missing all three domain sources.
        ],
        "termination_condition": "C",
        "budget_consumed_usd": 60.0,
    }
    result = vc.check_termination_v2(
        report,
        max_cycles=5,
        budget_cap=50.0,
        vault_dir=tmp_path,
        pipeline_dir=pipeline,
    )
    assert result.status == "ABORT"
    domain_errors = [
        e
        for e in result.errors
        if any(s in e.lower() for s in ["spring", "oracle", "owasp"])
    ]
    assert len(domain_errors) >= 3, (
        f"research-phase MUST require all 3 missing domain sources; "
        f"got {len(domain_errors)} domain errors out of {result.errors}"
    )
