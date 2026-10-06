"""Speckit CLI entry point (spec 025 B5 subpackage)."""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading

from ..spec.simple import load as load_spec
from ..spec.validator import validate
from . import _log_level
from ._common import force_line_buffered_stdio as _force_line_buffered_stdio
from ._parser import build_parser
from .research_phase3 import _run_phase3
from .research_resume import _resolve_resume_cycle, _resume

__all__ = [
    "build_parser",
    "main",
    "_force_line_buffered_stdio",
    "_resume",
    "_resolve_resume_cycle",
    "_run_phase3",
    "load_spec",
    "validate",
]

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def _configure_root_logger(level: int) -> None:
    """Wire ``logging.basicConfig`` once per process (FR-001 / FR-002).

    Idempotent against re-entry: if any handler is already attached to
    the root logger (e.g. pytest's ``LogCaptureHandler``), this is a
    no-op so the parent's capture mechanism stays intact. See
    ``specs/048-observability-v1/contracts/logger-wiring.contract.md``.
    """
    if logging.root.handlers:
        return
    logging.basicConfig(
        level=level,
        format=_LOG_FORMAT,
        stream=sys.stderr,
    )


class _ReasonCounter(logging.Handler):
    """Counts log records that could be an exit REASON (spec 070 FR6).

    Records filtered out by the logger's level never reach ``emit``, so this
    counts what the operator could *see*, not what the code tried to say. That
    distinction is the whole of F5: ``_constrained_exit`` narrated its reasoning
    entirely at ``INFO`` while ``_log_level.resolve`` had dropped the level to
    ``WARNING`` because stdout was redirected.

    The handler level is ``ERROR``, not ``NOTSET``, and that is the fix for
    issue #243. Counting every emitted record pinned "something was said at
    some point" rather than "the exit reason was reported" — one unrelated
    deprecation WARNING at startup was enough to certify a mute rc=1 as
    diagnosed. A ``WARNING`` is by definition advisory; only an ``ERROR`` (or a
    direct write to stderr, counted separately by ``_StreamTap``) can be the
    reason a run refused to continue.

    The two reviewers who filed #243 asked for different floors — ``>=
    WARNING`` from one, "an unrelated WARNING must not silence it" from the
    other. Those cannot both hold, and the second came with a demonstration,
    so ``ERROR`` is the floor. Every rejection path that reports through
    ``logging`` now does so at ``ERROR`` (see issue #242).
    """

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.count = 0

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
        self.count += 1


class _StreamTap:
    """Transparent text-stream wrapper that counts bytes written (spec 070 FR6).

    Everything except ``write`` delegates, so ``isatty()`` (which
    ``_log_level._detect_default_level`` consults) and ``fileno()`` keep
    behaving exactly as the wrapped stream does.

    Only ``sys.stderr`` is tapped. ``_configure_root_logger`` binds its handler
    to the real stream before the tap is installed, so log records never
    inflate this count — it is exactly the bytes a verb ``print``\\ ed itself.
    """

    def __init__(self, wrapped: object) -> None:
        self._wrapped = wrapped
        self.written = 0

    def write(self, s: str) -> int:
        if s:
            self.written += len(s)
        return self._wrapped.write(s)  # type: ignore[attr-defined,no-any-return]

    def __getattr__(self, name: str) -> object:
        return getattr(self._wrapped, name)


# Two runtimes reach this backstop and they leave different records. The
# `cycle` verbs finish by writing `_pipeline/run-report.md`
# (`orchestrator._finalise_run_report`); the `pipeline` verbs never write that
# file at all — their record is `_pipeline/pipeline-state.json`, which
# `runner._close_phase` names in its own ERROR line. Naming one file for both
# sent operators of a failed weekly run looking for something that does not
# exist (issue #219).
# Spec 080 D4/FR-009: the hint is a static string and cannot name a run
# directory it does not know, so it names the pattern rather than a path that
# might not exist. `<run_id>` is the value in `pipeline-state.json`.
_SILENT_EXIT_HINT = (
    "error: the command exited with status {rc} without reporting a reason.\n"
    "This is a framework bug (spec 070 FR6) — every non-zero exit should say "
    "what it rejected and what would make it valid.\n"
    "Re-run with `--log-level info` to see the full trace. The run's own "
    "record is `<vault>/_pipeline/runs/<run_id>/run-report.md` for `pipeline` "
    "verbs (its `run_id` is in `<vault>/_pipeline/pipeline-state.json`) and "
    "`<vault>/_pipeline/run-report.md` for `cycle` verbs.\n"
)


class _Terminated(KeyboardInterrupt):
    """SIGTERM: unwinds the main thread exactly as Ctrl+C does."""

    def __init__(self, signum: int) -> None:
        super().__init__(signum)
        self.signum = signum


def _on_sigterm(signum: int, _frame: object) -> None:
    raise _Terminated(signum)


def _unwind_on_sigterm() -> bool:
    """Make SIGTERM an interrupt; ``True`` if the handler is ours to remove.

    The stages this process dispatches run in sessions of their own
    (``popen_session``), so a SIGTERM sent to it reaches none of them, and
    Python's default for SIGTERM is to die on the spot without running a
    single ``finally``. ``kill <pid>`` left ``agent_call.py`` and the agent
    running — spending, and writing into the vault — with nothing left to
    supervise them.

    Ctrl+C never had that problem: ``KeyboardInterrupt`` unwinds the main
    thread, and every supervised wait terminates its child's process group on
    the way out. So SIGTERM is turned into the same unwind (the exception is a
    ``KeyboardInterrupt``: a terminated cycle is recorded as interrupted) and
    ``main`` then dies of the signal it was sent.

    Not installed off the main thread, where signals cannot be handled, nor
    over a handler somebody else installed: ``main`` also runs inside host
    processes whose signal handling is not ours to replace.
    """
    if threading.current_thread() is not threading.main_thread():
        return False
    if signal.getsignal(signal.SIGTERM) is not signal.SIG_DFL:
        return False
    signal.signal(signal.SIGTERM, _on_sigterm)
    return True


def _die_of(signum: int) -> int:
    """End as the signal would have ended us: its sender sees that status."""
    signal.signal(signum, signal.SIG_DFL)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError):
            pass
    os.kill(os.getpid(), signum)
    return 128 + signum  # only if the signal is somehow not delivered


def main(argv: list[str] | None = None) -> int:
    _force_line_buffered_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    level = _log_level.resolve(
        getattr(args, "log_level", None),
        verb_default=getattr(args, "verb_default_log_level", None),
    )
    # Configure logging BEFORE attaching the counter: ``_configure_root_logger``
    # no-ops when the root logger already has handlers, and the counter is one.
    _configure_root_logger(level)
    logger = logging.getLogger(__name__)
    logger.debug("CLI entry; log level resolved to %s", logging.getLevelName(level))

    counter = _ReasonCounter()
    logging.root.addHandler(counter)
    real_err = sys.stderr
    err_tap = _StreamTap(real_err)
    sys.stderr = err_tap  # type: ignore[assignment]
    handles_sigterm = _unwind_on_sigterm()
    try:
        rc = args.func(args)
    except NotImplementedError as exc:
        print(str(exc), file=sys.stderr)
        rc = 2
    except _Terminated as stop:
        # Whatever this command had dispatched is gone by now: the unwind
        # went through the waits that supervise it.
        print(f"terminated by {signal.Signals(stop.signum).name}", file=real_err)
        rc = _die_of(stop.signum)
    finally:
        if handles_sigterm:
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
        sys.stderr = real_err
        logging.root.removeHandler(counter)

    # FR6 backstop: a non-zero exit that never reported a reason is
    # indistinguishable from a crashed interpreter. Say *something*.
    #
    # "Reported a reason" is deliberately narrow (issue #243): bytes the verb
    # wrote to stderr, or a record at ERROR. stdout does not count — FR6 names
    # stderr, and stdout is the stream `> run.log` takes away in the same
    # breath as it drops the log level (`_log_level` FR-005). A verb whose only
    # rejection goes to stdout is the bug this backstop is for, not an excuse
    # to stay quiet.
    if rc and not (err_tap.written or counter.count):
        print(_SILENT_EXIT_HINT.format(rc=rc), file=sys.stderr, end="")
    return rc


if __name__ == "__main__":
    sys.exit(main())
