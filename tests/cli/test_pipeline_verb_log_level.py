"""Issue #241 — a headless pipeline run must still narrate.

`_log_level` FR-005 defaults to `WARNING` whenever stdout is not a TTY, and
every phase summary, the triage prompt, the verify verdict and the "not yet
implemented" collect lines are `INFO`. An "autonomous pipeline" runs from
cron / launchd / systemd — never on a TTY — so the mode the framework exists
for is the one mode in which it says nothing at all.

The fix is per-verb, not global: the `pipeline` verbs declare `INFO` as their
own default, and an explicit `--log-level` still wins. Nothing changes for the
verbs whose non-TTY quiet is intentional.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from research_framework.cli import _log_level
from research_framework.cli._parser import build_parser


def test_verb_default_survives_a_redirected_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    assert _log_level.resolve(None) == logging.WARNING
    assert _log_level.resolve(None, verb_default="info") == logging.INFO


def test_explicit_flag_still_beats_the_verb_default() -> None:
    assert _log_level.resolve("warning", verb_default="info") == logging.WARNING
    assert _log_level.resolve("debug", verb_default="info") == logging.DEBUG


def test_verb_default_is_validated_like_any_other_value() -> None:
    with pytest.raises(ValueError):
        _log_level.resolve(None, verb_default="chatty")


def test_pipeline_subcommand_declares_the_info_default(tmp_path: Path) -> None:
    args = build_parser().parse_args(["pipeline", str(tmp_path), "full"])
    assert args.log_level is None
    assert args.verb_default_log_level == "info"


def test_other_verbs_keep_the_tty_aware_default(tmp_path: Path) -> None:
    args = build_parser().parse_args(
        ["generate", "--spec", str(tmp_path / "s.md"), "--output", str(tmp_path)]
    )
    assert getattr(args, "verb_default_log_level", None) is None


def test_main_resolves_the_pipeline_default_off_a_tty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """End to end: the narrative reaches the run's output under cron."""
    import argparse

    from research_framework import cli

    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    seen: list[int] = []

    def _narrating_verb(_args: object) -> int:
        seen.append(
            logging.getLogger("research_framework.pipeline.runner").getEffectiveLevel()
        )
        return 0

    class _Parser:
        def parse_args(self, _argv: list[str] | None) -> argparse.Namespace:
            return argparse.Namespace(
                log_level=None,
                verb_default_log_level="info",
                func=_narrating_verb,
            )

    monkeypatch.setattr(cli, "build_parser", lambda: _Parser())
    monkeypatch.setattr(cli, "_configure_root_logger", lambda level: seen.append(level))

    assert cli.main([]) == 0
    assert seen[0] == logging.INFO, "the pipeline verbs must wire INFO off a TTY"
