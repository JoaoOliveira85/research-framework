"""Spec 070 FR6 — a non-zero CLI exit must report its REASON on stderr.

F5 in spec 070: `generate --resume` exited 1 with **zero bytes** on stdout and
stderr, indistinguishable from a crashed interpreter. Two layers are tested
here:

1. ``_ReasonCounter`` / stream-tap plumbing in :func:`research_framework.cli.main`
   — the backstop that fires for ANY verb.
2. A real subprocess invocation, so the guard is proven end-to-end through
   ``python -m research_framework.cli`` with stdout redirected (the exact
   condition that suppressed the diagnostics, per ``_log_level`` FR-005).

Issue #243 sharpened what the guard measures. It used to fire only when the
whole process wrote *zero bytes anywhere*, which pins "something was said at
some point", not "the exit reason was reported": one unrelated early WARNING,
or a rejection printed to a redirected stdout, silenced it while FR6 was
plainly broken. The condition is now stderr bytes plus records at ``ERROR``,
and the assertions below are on the STREAM and the SEVERITY, never on message
text, so the guard cannot rot when the wording changes (tasks.md T005).
"""

from __future__ import annotations

import logging
import subprocess
import sys

import pytest

from research_framework import cli


def _parser_returning(func):
    """A parser whose only verb dispatches to *func*, for the in-process path."""
    import argparse

    def _build():
        parser = argparse.ArgumentParser()
        parser.add_argument("verb")
        parser.set_defaults(func=func)
        return parser

    return _build


def _silent_failure(_args: object) -> int:
    """A verb that returns non-zero without writing anything."""
    return 1


def test_reason_counter_counts_only_error_records() -> None:
    """A WARNING is not an exit reason; only ``ERROR`` and above count."""
    counter = cli._ReasonCounter()
    logger = logging.getLogger("spec070.counter.test")
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    logger.addHandler(counter)
    try:
        logger.info("narration")
        logger.warning("an advisory, not a reason to exit 1")
        assert counter.count == 0
        logger.error("this run is rejecting something")
        assert counter.count == 1
    finally:
        logger.removeHandler(counter)


def test_stream_tap_counts_writes_and_delegates() -> None:
    """The tap must count bytes and stay transparent for everything else."""
    import io

    underlying = io.StringIO()
    tap = cli._StreamTap(underlying)

    assert tap.written == 0
    tap.write("")
    assert tap.written == 0

    tap.write("hello")
    assert tap.written == 5
    assert underlying.getvalue() == "hello"

    # Delegation: attributes the tap does not define fall through.
    tap.flush()
    assert tap.getvalue() == "hello"


def test_main_guard_fires_for_silent_nonzero_rc(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """End of the FR6 contract, exercised through ``main`` itself."""
    import argparse

    class _Parser:
        def parse_args(self, _argv: list[str] | None) -> argparse.Namespace:
            return argparse.Namespace(log_level="warning", func=_silent_failure)

    monkeypatch.setattr(cli, "build_parser", lambda: _Parser())

    rc = cli.main([])
    captured = capsys.readouterr()

    assert rc == 1
    assert len(captured.err) > 0, "FR6: a non-zero exit must diagnose itself"


def test_main_guard_silent_when_verb_already_spoke(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The guard is a backstop — it must not double-report."""
    import argparse

    def _loud_failure(_args: object) -> int:
        print("error: the verb already explained itself", file=sys.stderr)
        return 1

    class _Parser:
        def parse_args(self, _argv: list[str] | None) -> argparse.Namespace:
            return argparse.Namespace(log_level="warning", func=_loud_failure)

    monkeypatch.setattr(cli, "build_parser", lambda: _Parser())

    rc = cli.main([])
    captured = capsys.readouterr()

    assert rc == 1
    assert captured.err.count("error:") == 1, "guard must not append a second report"


def test_main_guard_silent_when_the_reason_was_logged_at_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The orchestrator reports through ``logging``, not ``print`` (issue #242)."""
    import argparse

    def _logged_failure(_args: object) -> int:
        logging.getLogger("spec070.reason").error("constrained exit — budget cap")
        return 1

    class _Parser:
        def parse_args(self, _argv: list[str] | None) -> argparse.Namespace:
            return argparse.Namespace(log_level="warning", func=_logged_failure)

    monkeypatch.setattr(cli, "build_parser", lambda: _Parser())

    rc = cli.main([])
    captured = capsys.readouterr()

    assert rc == 1
    assert "framework bug" not in captured.err, (
        "an ERROR-level reason IS a reported reason; the backstop must stay quiet"
    )


def test_main_guard_fires_after_an_unrelated_warning(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Issue #243: the zero-bytes guard was silenced by any earlier output.

    A deprecation WARNING at startup is not a diagnosis of the exit that
    follows it. Under the old condition it was enough to suppress the
    backstop, so a mute rc=1 after one went unreported.
    """
    import argparse

    def _warn_then_fail_silently(_args: object) -> int:
        logging.getLogger("spec070.unrelated").warning(
            "settings.yaml key `budget.max_usd` is deprecated"
        )
        return 1

    class _Parser:
        def parse_args(self, _argv: list[str] | None) -> argparse.Namespace:
            return argparse.Namespace(
                log_level="warning", func=_warn_then_fail_silently
            )

    monkeypatch.setattr(cli, "build_parser", lambda: _Parser())

    rc = cli.main([])
    captured = capsys.readouterr()

    assert rc == 1
    assert "framework bug" in captured.err, (
        "FR6: an unrelated WARNING does not tell the operator why rc=1"
    )


def test_main_guard_fires_when_the_verb_only_spoke_on_stdout(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Issue #243: stdout is exactly the stream spec 070 F5 loses.

    `pipeline ... > run.log` redirects stdout AND drops the log level to
    WARNING (``_log_level`` FR-005). A rejection printed there is invisible in
    the terminal, so counting it as "reported" made the guard blind to the one
    failure mode it exists for.
    """
    import argparse

    def _stdout_only_failure(_args: object) -> int:
        print("[phase 3 gate] coverage targets unmet")
        return 1

    class _Parser:
        def parse_args(self, _argv: list[str] | None) -> argparse.Namespace:
            return argparse.Namespace(log_level="warning", func=_stdout_only_failure)

    monkeypatch.setattr(cli, "build_parser", lambda: _Parser())

    rc = cli.main([])
    captured = capsys.readouterr()

    assert rc == 1
    assert len(captured.err) > 0, "FR6: nothing reached stderr"


def test_main_guard_quiet_on_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """rc == 0 with no output is legitimate — the guard must stay out of it."""
    import argparse

    class _Parser:
        def parse_args(self, _argv: list[str] | None) -> argparse.Namespace:
            return argparse.Namespace(log_level="warning", func=lambda _a: 0)

    monkeypatch.setattr(cli, "build_parser", lambda: _Parser())

    rc = cli.main([])
    captured = capsys.readouterr()

    assert rc == 0
    assert captured.err == ""
    assert captured.out == ""


@pytest.mark.slow
def test_subprocess_nonzero_exit_is_never_silent(tmp_path) -> None:
    """FR6 end-to-end: redirected stdout must not silence a failing run.

    Uses a deliberately invalid ``--resume`` (no vault, no state) so the run
    fails before doing any work. Asserts on bytes, not wording.
    """
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "research_framework.cli",
            "generate",
            "--spec",
            str(tmp_path / "missing.spec.md"),
            "--output",
            str(tmp_path),
            "--resume",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert proc.returncode != 0
    # `stdout + stderr > 0` — the assertion this replaces — is precisely the OR
    # that lets F5's failure mode through (stdout redirected, stderr empty).
    assert len(proc.stderr) > 0, "FR6: a non-zero exit wrote nothing to stderr"


def test_the_hint_names_the_run_receipt_for_pipeline_verbs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec 080 FR-009 / D4.

    The hint is a static string built before any verb runs, so it cannot name
    a run directory it has not seen. What it can do is stop naming
    `run-report.md` for `pipeline` verbs — a file the runner never wrote,
    which is the whole reason #219 filed the backstop as broken — and name the
    pattern the receipt actually lives at, plus where to find the `run_id`
    that completes it.
    """
    monkeypatch.setattr(cli, "build_parser", _parser_returning(_silent_failure))

    rc = cli.main(["anything"])

    assert rc == 1
    err = capsys.readouterr().err
    assert "_pipeline/runs/<run_id>/run-report.md" in err
    assert "pipeline-state.json" in err, "the run_id has to come from somewhere"
