"""Tier-2 tests for the orchestrator-side preflight payload parser
(spec 051 FR4, T029).

Module preflight subprocesses emit the ``PreflightResult`` JSON shape directly
(they can't import from ``src/``); the bridge parses it here into frozen
dataclasses. ``from_json`` is the trust boundary — it must reject malformed
payloads (the orchestrator treats a parse failure as ``fatal_fail``,
fail-closed). Contract: ``contracts/preflight.contract.md`` §3 +
``contracts/preflight-result.schema.json``.
"""

from __future__ import annotations

import pytest

from research_framework.pipeline.source_bridge.preflight_types import (
    PreflightResult,
    SourceCorrection,
)

# ---------------------------------------------------------------------------
# Convenience constructors
# ---------------------------------------------------------------------------


class TestConstructors:
    def test_success(self) -> None:
        r = PreflightResult.success()
        assert r.verdict == "success"
        assert r.corrections == [] and r.messages == []
        assert r.schema_version == "1.0"

    def test_warning_carries_corrections_and_messages(self) -> None:
        corr = SourceCorrection(
            original="a", suggested="b", reason="typo", applied=True
        )
        r = PreflightResult.warning(corrections=[corr], messages=["note"])
        assert r.verdict == "warning"
        assert r.corrections == [corr]
        assert r.messages == ["note"]

    def test_fatal_accepts_a_single_string_or_list(self) -> None:
        assert PreflightResult.fatal("boom").messages == ["boom"]
        assert PreflightResult.fatal(["a", "b"]).verdict == "fatal_fail"


# ---------------------------------------------------------------------------
# from_json — happy paths
# ---------------------------------------------------------------------------


class TestFromJsonValid:
    def test_minimal_success(self) -> None:
        r = PreflightResult.from_json(
            {
                "schema_version": "1.0",
                "verdict": "success",
                "corrections": [],
                "messages": [],
            }
        )
        assert r.verdict == "success"

    def test_warning_with_correction(self) -> None:
        r = PreflightResult.from_json(
            {
                "schema_version": "1.0",
                "verdict": "warning",
                "corrections": [
                    {
                        "original": "arxiv.org/list/cs.AI",
                        "suggested": "rss.arxiv.org/rss/cs.AI",
                        "reason": "not an RSS endpoint",
                        "applied": True,
                    }
                ],
                "messages": ["corrected arxiv feed URL"],
            }
        )
        assert r.verdict == "warning"
        assert r.corrections[0].suggested == "rss.arxiv.org/rss/cs.AI"
        assert r.corrections[0].applied is True

    def test_round_trip_to_dict(self) -> None:
        r = PreflightResult.warning(
            corrections=[
                SourceCorrection(original="x", suggested="y", reason="z", applied=False)
            ],
            messages=["m"],
        )
        assert PreflightResult.from_json(r.to_dict()) == r


# ---------------------------------------------------------------------------
# from_json — rejects malformed payloads (fail-closed boundary)
# ---------------------------------------------------------------------------


class TestFromJsonRejects:
    def test_wrong_schema_version(self) -> None:
        with pytest.raises(ValueError, match="schema_version"):
            PreflightResult.from_json(
                {
                    "schema_version": "2.0",
                    "verdict": "success",
                    "corrections": [],
                    "messages": [],
                }
            )

    def test_invalid_verdict(self) -> None:
        with pytest.raises(ValueError, match="verdict"):
            PreflightResult.from_json(
                {
                    "schema_version": "1.0",
                    "verdict": "maybe",
                    "corrections": [],
                    "messages": [],
                }
            )

    def test_corrections_not_a_list(self) -> None:
        with pytest.raises(ValueError, match="corrections"):
            PreflightResult.from_json(
                {
                    "schema_version": "1.0",
                    "verdict": "success",
                    "corrections": {},
                    "messages": [],
                }
            )

    def test_correction_missing_required_key(self) -> None:
        with pytest.raises(ValueError):
            PreflightResult.from_json(
                {
                    "schema_version": "1.0",
                    "verdict": "warning",
                    "corrections": [{"original": "a", "suggested": "b"}],
                    "messages": [],
                }
            )

    def test_not_a_mapping(self) -> None:
        with pytest.raises(ValueError):
            PreflightResult.from_json(["not", "a", "dict"])  # type: ignore[arg-type]

    def test_non_boolean_applied_rejected(self) -> None:
        # trust boundary: "false"/0/1 must NOT be silently coerced
        for bad in ("false", 0, 1, "true"):
            with pytest.raises(ValueError, match="applied"):
                PreflightResult.from_json(
                    {
                        "schema_version": "1.0",
                        "verdict": "warning",
                        "corrections": [
                            {
                                "original": "a",
                                "suggested": "b",
                                "reason": "r",
                                "applied": bad,
                            }
                        ],
                        "messages": [],
                    }
                )
