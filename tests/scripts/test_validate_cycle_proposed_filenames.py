"""Principle VI's pre-write enforcement is mandatory (issue #293).

Constitution Principle VI names exactly one enforcement point:

    Two notes for the same concept MUST NOT exist. The naming convention is
    enforced **before DFS writes any file**. ``proposed_filenames`` in the
    scout JSON is the coordination mechanism. If two agents are running in
    parallel, their topic lists MUST be non-overlapping.

That check lived in ``scripts/validate_cycle.py`` behind ``if proposed and …``
with the field in none of the required-field lists, so a scout report that
omitted the key — or sent ``[]`` — skipped the only pre-write enforcement of a
constitutional principle, silently. It also compared proposals against the
vault on disk only, so it could not see two entries colliding *within* one
list, which is what the parallel-agent clause is about.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_validate_cycle() -> Any:
    path = REPO_ROOT / "scripts" / "validate_cycle.py"
    spec = importlib.util.spec_from_file_location("_vc_principle_vi", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


@pytest.fixture(scope="module")
def vc() -> Any:
    return _load_validate_cycle()


@pytest.fixture
def scout_v2() -> dict:
    """A minimal, otherwise-valid v2 scout report."""
    return {
        "schema_version": "2",
        "cycle": 1,
        "phase": "scout",
        "timestamp": "2026-09-06T00:00:00Z",
        "dimensions_covered": [
            "technical",
            "organizational",
            "domain",
            "market",
            "temporal",
        ],
        "topics_from_code": [],
        "intent_from_confluence": [],
        "proposed_filenames": [],
        "sources_consulted": [],
        "budget_consumed_usd": 0.0,
    }


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    (tmp_path / "data_vault").mkdir(parents=True)
    return tmp_path


def _topic(idx: int) -> dict:
    return {
        "id": f"CT-1-{idx:03d}",
        "topic_type": "concept",
        "source_file": "acme/svc/README.md",
        "source_snippet": "lines 1-3",
    }


# ---------------------------------------------------------------------------
# The field is required, not optional
# ---------------------------------------------------------------------------


def test_proposed_filenames_is_a_required_scout_field(vc: Any) -> None:
    """No optional field may be the only enforcement of a MUST NOT principle."""
    assert "proposed_filenames" in vc.REQUIRED_REPORT_FIELDS_V2


def test_scout_report_without_proposed_filenames_is_a_structural_error(
    vc: Any, scout_v2: dict
) -> None:
    scout_v2.pop("proposed_filenames")
    errors = vc.validate_report_structure_v2(scout_v2)
    assert any("proposed_filenames" in e for e in errors), errors


def test_research_report_still_does_not_need_it(vc: Any) -> None:
    """The DFS consumes ``proposed_filenames``; it does not re-emit them.
    Demanding scout-only fields back from a research report is the v0.2.19
    footgun ``REQUIRED_REPORT_FIELDS_V2_RESEARCH`` exists to avoid."""
    assert "proposed_filenames" not in vc.REQUIRED_REPORT_FIELDS_V2_RESEARCH
    research = {
        "schema_version": "2",
        "cycle": 1,
        "phase": "research",
        "timestamp": "2026-09-06T00:00:00Z",
        "sources_consulted": [],
        "budget_consumed_usd": 0.0,
    }
    assert vc.validate_report_structure_v2(research) == []


# ---------------------------------------------------------------------------
# The check runs on an empty list too
# ---------------------------------------------------------------------------


def test_empty_list_while_claiming_new_topics_is_an_error(
    vc: Any, scout_v2: dict, vault: Path
) -> None:
    """``[]`` is the other spelling of "skip the coordination mechanism"."""
    scout_v2["topics_from_code"] = [_topic(1), _topic(2)]
    scout_v2["proposed_filenames"] = []
    result = vc.check_termination_v2(scout_v2, 5, 10.0, vault, None)
    assert result.status == "ABORT"
    assert any("proposed_filenames is empty" in e for e in result.errors), result.errors


def test_empty_list_with_no_claimed_topics_is_fine(
    vc: Any, scout_v2: dict, vault: Path
) -> None:
    """A scout that genuinely found nothing proposes nothing — not a violation."""
    result = vc.check_termination_v2(scout_v2, 5, 10.0, vault, None)
    assert not any("proposed_filenames" in e for e in result.errors), result.errors


def test_v1_report_claiming_topics_with_no_proposals_is_an_error(vc: Any) -> None:
    """The v1 path carried a byte-identical copy of the same short-circuit."""
    errors = vc._filename_collision_errors(
        {"phase": "scout", "topics_found": {"new": ["Alpha", "Beta"]}}, None
    )
    assert any("proposed_filenames is empty" in e for e in errors), errors


def test_a_research_report_is_not_asked_for_proposals(vc: Any) -> None:
    """The DFS consumes ``proposed_filenames``; leaving them empty on a research
    report is not a Principle-VI skip."""
    errors = vc._filename_collision_errors(
        {"phase": "research", "topics_from_code": [_topic(1)]}, None
    )
    assert errors == []


def test_a_terminating_scout_is_not_asked_for_proposals(vc: Any) -> None:
    """No DFS write follows a termination, so there is nothing to coordinate."""
    errors = vc._filename_collision_errors(
        {
            "phase": "scout",
            "topics_from_code": [_topic(1)],
            "termination_condition": "B",
            "proposed_filenames": [],
        },
        None,
    )
    assert errors == []


# ---------------------------------------------------------------------------
# The list is checked against itself — the parallel-agent clause
# ---------------------------------------------------------------------------


def test_intra_list_duplicate_is_an_error(vc: Any, scout_v2: dict, vault: Path) -> None:
    """Principle VI's parallel-agent clause ("their topic lists MUST be
    non-overlapping") had no implementation while the check only compared
    proposals to files already on disk."""
    scout_v2["topics_from_code"] = [_topic(1), _topic(2)]
    scout_v2["proposed_filenames"] = ["Widget.md", "Widget.md"]
    result = vc.check_termination_v2(scout_v2, 5, 10.0, vault, None)
    assert result.status == "ABORT"
    assert any("duplicate entries" in e for e in result.errors), result.errors


def test_intra_list_duplicate_is_named_once(vc: Any) -> None:
    errors = vc._filename_collision_errors(
        {"proposed_filenames": ["A.md", "A.md", "A.md", "B.md"]}, None
    )
    joined = " ".join(errors)
    assert joined.count("'A.md'") == 1
    assert "B.md" not in joined


def test_distinct_proposals_are_clean(vc: Any, scout_v2: dict, vault: Path) -> None:
    scout_v2["topics_from_code"] = [_topic(1), _topic(2)]
    scout_v2["proposed_filenames"] = ["Widget.md", "Gadget.md"]
    result = vc.check_termination_v2(scout_v2, 5, 10.0, vault, None)
    assert result.status != "ABORT", result.errors


# ---------------------------------------------------------------------------
# The original on-disk collision check still fires
# ---------------------------------------------------------------------------


def test_collision_with_an_existing_note_still_aborts(
    vc: Any, scout_v2: dict, vault: Path
) -> None:
    (vault / "data_vault" / "Widget.md").write_text("existing")
    scout_v2["topics_from_code"] = [_topic(1)]
    scout_v2["proposed_filenames"] = ["Widget.md"]
    result = vc.check_termination_v2(scout_v2, 5, 10.0, vault, None)
    assert result.status == "ABORT"
    assert any("collision with existing notes" in e for e in result.errors)


def test_non_list_proposed_filenames_is_an_error(vc: Any) -> None:
    errors = vc._filename_collision_errors({"proposed_filenames": "Widget.md"}, None)
    assert any("must be a list" in e for e in errors), errors


# ---------------------------------------------------------------------------
# Both code paths share one implementation
# ---------------------------------------------------------------------------


def test_v1_and_v2_paths_share_the_collision_implementation(vc: Any) -> None:
    """The two blocks were byte-identical copies; a fix to one silently left
    the other behind. There is now a single helper both call."""
    source = (REPO_ROOT / "scripts" / "validate_cycle.py").read_text(encoding="utf-8")
    assert source.count("_filename_collision_errors(report, vault_dir)") == 2
    assert source.count("def _filename_collision_errors") == 1
