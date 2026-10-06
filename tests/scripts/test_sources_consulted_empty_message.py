"""An absent `sources_consulted` must say so once, not N times (spec 070 family).

`feeds-vault` cycle 9 aborted with seven errors of the form

    ERROR: required source 'hacker_news' not in sources_consulted

which reads as "the agent skipped seven sources". It had not: there was no
`cycle-009-research.json` at all. The message described a symptom per-source
instead of naming the cause once, and it sent a reader (this one) down the wrong
path — as far as recommending the operator change their vault's research design.

`validate_sources_v2` already handled the *missing key* case with a single clear
error. It did not handle the *empty* one, and `validate_sources` handled
neither. Same defect family as spec 070 F5/F4: the framework describing what it
observed rather than what happened.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from validate_cycle import validate_sources, validate_sources_v2  # noqa: E402

REQUIRED = ["arxiv", "hacker_news", "reddit", "wikipedia"]


@pytest.mark.parametrize("validator", [validate_sources, validate_sources_v2])
@pytest.mark.parametrize(
    "report",
    [
        {},  # no key at all — the cycle-9 shape
        {"sources_consulted": {}},  # present but empty
        {"sources_consulted": None},  # written as null
    ],
    ids=["absent", "empty-dict", "null"],
)
def test_absent_block_gives_one_error_naming_the_cause(validator, report) -> None:
    errors, _warnings = validator(report, REQUIRED, [])
    assert len(errors) == 1, f"expected one cause, got {len(errors)} symptoms"
    assert "sources_consulted" in errors[0]
    assert "not in sources_consulted" not in errors[0], (
        "per-source phrasing implies the agent skipped them; it never reported"
    )


@pytest.mark.parametrize("validator", [validate_sources, validate_sources_v2])
def test_empty_list_shape_is_also_one_error(validator) -> None:
    errors, _ = validator({"sources_consulted": []}, REQUIRED, [])
    assert len(errors) == 1


@pytest.mark.parametrize("validator", [validate_sources, validate_sources_v2])
def test_a_genuinely_partial_report_still_names_each_missing_source(validator) -> None:
    """Regression: when the agent DID report, per-source errors are correct —
    that is a real omission and naming each one is the useful behaviour."""
    report = {"sources_consulted": {"arxiv": {"searched": True, "results_count": 3}}}
    errors, _ = validator(report, REQUIRED, [])
    assert len(errors) == 3
    assert all("not in sources_consulted" in e for e in errors)
    assert not any("arxiv" in e for e in errors)


def test_no_required_sources_means_no_error() -> None:
    """An empty block is only a problem when something was required."""
    for validator in (validate_sources, validate_sources_v2):
        errors, _ = validator({"sources_consulted": {}}, [], [])
        assert errors == []
