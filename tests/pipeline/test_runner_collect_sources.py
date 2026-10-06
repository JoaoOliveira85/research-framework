"""``collect`` must not report success for work it cannot do.

Issue #223.  The collect phase runs one collector — RSS, driven from a
``sources.yaml`` no vault has.  Every other declared source (web fetch, GitHub,
arXiv, Reddit, HN) was logged "not yet implemented" at ``INFO``, invisible
under the shipped non-TTY ``WARNING`` default, and the phase then reported
``done, items_new=0``.

On the 2026-09-01 fleet run that produced ``rss: 0`` and ``files_processed: 0``
on 7 of 7 vaults, a downstream report saying "No context tree available", and
an operator who had been told the phase succeeded.

An operator must be able to tell "collected nothing because nothing was
declared" from "collected nothing because I cannot read what you declared".
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from research_framework.collectors import CollectResult
from research_framework.pipeline.runner import (
    DONE,
    FAILED,
    SKIPPED,
    STATE_FILE,
    run_collect,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _spec_parse(vault: Path, *sources: tuple[str, str]) -> None:
    path = vault / "_pipeline" / "spec-parse.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "data_sources": [
                    {"name": name, "type": "external", "access_method": access}
                    for name, access in sources
                ]
            }
        ),
        encoding="utf-8",
    )


def _phase(vault: Path) -> dict:
    state = json.loads((vault / STATE_FILE).read_text(encoding="utf-8"))
    return state["phases"]["collect"]


def _rss(fetched: int = 0, errors: tuple[str, ...] = ()):
    return patch(
        "research_framework.collectors.rss.collect",
        return_value=CollectResult(fetched=fetched, skipped_existing=0, errors=errors),
    )


# ---------------------------------------------------------------------------
# sources the runner cannot collect
# ---------------------------------------------------------------------------


class TestUncollectableSourcesAreNotSuccess:
    def test_declared_web_and_github_sources_make_the_phase_skipped(
        self, tmp_path: Path
    ) -> None:
        _spec_parse(
            tmp_path,
            ("Vendor docs", "web fetch"),
            ("Reference repos", "GitHub API"),
        )

        with _rss():
            rc = run_collect(tmp_path, quiet=True)

        rec = _phase(tmp_path)
        assert rec["status"] == SKIPPED, "7/7 vaults were told this succeeded"
        assert rc == 0, "the phase did not fail — it did not run"

    def test_each_uncollectable_source_is_named_in_the_summary(
        self, tmp_path: Path
    ) -> None:
        _spec_parse(
            tmp_path,
            ("Vendor docs", "web fetch"),
            ("Reference repos", "GitHub API"),
        )

        with _rss():
            run_collect(tmp_path, quiet=True)

        unsupported = _phase(tmp_path)["summary"]["unsupported_sources"]
        assert [entry["name"] for entry in unsupported] == [
            "Vendor docs",
            "Reference repos",
        ]
        assert unsupported[0]["access_method"] == "web fetch"

    def test_they_are_named_at_warning_not_info(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """INFO is invisible under the non-TTY default the weekly run uses."""
        _spec_parse(tmp_path, ("Vendor docs", "web fetch"))

        with _rss(), caplog.at_level(logging.WARNING):
            run_collect(tmp_path, quiet=True)

        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warnings
        assert "Vendor docs" in caplog.text

    def test_the_skip_reason_says_which_kind_of_nothing_this_is(
        self, tmp_path: Path
    ) -> None:
        _spec_parse(tmp_path, ("Vendor docs", "web fetch"))

        with _rss():
            run_collect(tmp_path, quiet=True)

        reason = _phase(tmp_path)["summary"]["skipped_reason"]
        assert "Vendor docs" in reason or "1" in reason
        assert "declared" in reason.lower()

    def test_a_supported_source_alongside_an_unsupported_one_still_collects(
        self, tmp_path: Path
    ) -> None:
        """Partial capability is DONE with a warning, not SKIPPED: something
        was actually collected and extract has input."""
        _spec_parse(
            tmp_path,
            ("Vendor blog", "RSS feed"),
            ("Reference repos", "GitHub API"),
        )

        with _rss(fetched=4):
            rc = run_collect(tmp_path, quiet=True)

        rec = _phase(tmp_path)
        assert rc == 0
        assert rec["status"] == DONE
        assert rec["summary"]["items_new"] == 4
        assert len(rec["summary"]["unsupported_sources"]) == 1


# ---------------------------------------------------------------------------
# the honest zero
# ---------------------------------------------------------------------------


class TestNothingDeclaredIsNotTheSameAsNothingUnderstood:
    def test_a_vault_declaring_nothing_is_done(self, tmp_path: Path) -> None:
        with _rss():
            rc = run_collect(tmp_path, quiet=True)

        rec = _phase(tmp_path)
        assert rc == 0
        assert rec["status"] == DONE
        assert rec["summary"]["unsupported_sources"] == []

    def test_an_empty_rss_feed_is_done_not_skipped(self, tmp_path: Path) -> None:
        """Zero items from a source the runner CAN read is a real answer."""
        _spec_parse(tmp_path, ("Vendor blog", "RSS feed"))

        with _rss(fetched=0):
            run_collect(tmp_path, quiet=True)

        assert _phase(tmp_path)["status"] == DONE

    def test_the_declared_sources_are_recorded_either_way(self, tmp_path: Path) -> None:
        _spec_parse(
            tmp_path,
            ("Vendor blog", "RSS feed"),
            ("Reference repos", "GitHub API"),
        )

        with _rss():
            run_collect(tmp_path, quiet=True)

        assert _phase(tmp_path)["summary"]["declared_sources"] == 2


# ---------------------------------------------------------------------------
# real failures stay failures
# ---------------------------------------------------------------------------


class TestErrorsStillFail:
    def test_a_collector_error_is_failed_not_skipped(self, tmp_path: Path) -> None:
        _spec_parse(tmp_path, ("Vendor docs", "web fetch"))

        with _rss(errors=("feed timeout",)):
            rc = run_collect(tmp_path, quiet=True)

        assert rc == 1
        assert _phase(tmp_path)["status"] == FAILED
