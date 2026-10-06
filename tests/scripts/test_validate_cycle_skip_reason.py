"""Spec 070 F4/FR5 — a skipped required source must carry a real reason.

`no reason given` was emitted verbatim for five of nine sources, every cycle.
It reads as a bug in the message rather than an absence of information, and it
cannot distinguish "the researcher judged it irrelevant" from "the fetch
failed" from "the source was never offered to the agent".
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from validate_cycle import _skip_reason, validate_sources  # noqa: E402


def test_recorded_reason_is_passed_through_verbatim() -> None:
    assert _skip_reason({"searched": False, "reason": "HTTP 503"}) == "HTTP 503"


def test_missing_reason_says_so_explicitly() -> None:
    msg = _skip_reason({"searched": False})
    assert "no reason given" not in msg
    assert "sources_consulted" in msg, "name where the gap actually is"
    assert "not" in msg and "recoverable" in msg


def test_blank_reason_is_treated_as_missing() -> None:
    assert _skip_reason({"searched": False, "reason": "   "}) == _skip_reason(
        {"searched": False}
    )


def test_warning_text_no_longer_contains_the_old_placeholder() -> None:
    report = {"sources_consulted": {"w3c_community_groups": {"searched": False}}}
    _errors, warnings = validate_sources(report, ["w3c_community_groups"], [])
    assert len(warnings) == 1
    assert "no reason given" not in warnings[0]
    assert "w3c_community_groups" in warnings[0]


def test_searched_source_emits_no_warning() -> None:
    report = {"sources_consulted": {"s": {"searched": True}}}
    _errors, warnings = validate_sources(report, ["s"], [])
    assert warnings == []
