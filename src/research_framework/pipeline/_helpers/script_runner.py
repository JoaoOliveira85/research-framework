"""Subprocess script runner with heartbeat logging and process-tree cleanup."""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from research_framework._assets import asset_path

from ..process_tree import popen_session, terminate_process_tree

_LOG = logging.getLogger(__name__)

#: How long the script's output gets to arrive once its process group has
#: been terminated. Only a descendant that left the group still holds the
#: pipe by then, and it cannot be killed (see ``process_tree``).
_OUTPUT_DRAIN_TIMEOUT_S = 5.0


def _subprocess():
    from research_framework.pipeline import cycle_runner as _cr

    return _cr.subprocess


class _StepError(Exception):
    """Raised when a script cannot be launched (missing file, bad permissions, etc.)."""


def _hms() -> str:
    """``HH:MM:SS`` UTC timestamp for log-line prefixes (cheap, no date noise)."""
    return datetime.now(UTC).strftime("%H:%M:%S")


def _heartbeat_interval_s() -> float:
    """Heartbeat cadence; overridable via ``RV_HEARTBEAT_S`` for tests."""
    raw = os.environ.get("RV_HEARTBEAT_S", "30")
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 30.0


@contextmanager
def _heartbeat_writer(log_handle, pid: int, *, label: str):
    """Append ``[heartbeat] pid=… elapsed=…s still alive`` while the body runs.

    Wires a daemon thread that wakes up every ``RV_HEARTBEAT_S`` (default 30s).
    Each wake either emits the heartbeat line and flushes (so ``tail -f`` shows
    activity on a silent subprocess) or exits if the body has signalled stop.

    The thread is best-effort — any IOError while writing is swallowed so a
    broken pipe in the log doesn't kill the cycle. The thread is daemonic so
    a parent crash never leaks it.
    """
    stop = threading.Event()
    started = time.time()
    interval = _heartbeat_interval_s()

    def _loop() -> None:
        while not stop.wait(interval):
            elapsed = time.time() - started
            line = (
                f"[{_hms()}] [heartbeat] {label} pid={pid} "
                f"elapsed={elapsed:.0f}s — still alive\n"
            )
            try:
                log_handle.write(line)
                log_handle.flush()
            except (OSError, ValueError):
                return
            try:
                sys.stdout.write(line)
                sys.stdout.flush()
            except (OSError, ValueError):
                pass

    t = threading.Thread(target=_loop, daemon=True, name=f"heartbeat-{label}-{pid}")
    t.start()
    try:
        yield
    finally:
        stop.set()
        t.join(timeout=2.0)


def _resolve_script(script: Path) -> Path:
    """Resolve a helper-script path, falling back to the packaged copy.

    Vault-local ``scripts/`` are *regenerable* and git-ignored (the scaffold
    tracks ``data_vault/`` only), and they live inside the agent's writable,
    ``danger-full-access`` workspace. That makes them removable out from under
    a long unattended run: a corporate DLP/AV sweep, a sandbox cleanup, a
    stray ``git clean -x``, or an errant agent command can delete them
    mid-cycle. The *immutable* copy that ships in the wheel under
    ``research_framework/_data/scripts/`` is still available in that case.

    So when the vault copy is gone, fall back to the packaged copy of the same
    basename — a regenerable artifact must never abort a cycle. (This cost a
    full reference-vault run on 2026-06-05: 15 untracked vault scripts vanished 43s
    into the scout and the next step crashed with ``can't open file
    '.../scripts/validate_cycle.py'`` → cycle abort. Business, whose scripts
    survived, completed all six cycles on the identical bundle.)

    Returns ``script`` unchanged when it exists, or when no packaged fallback
    can be found — the caller then surfaces the original missing-file
    behaviour (``python`` exits 2) rather than a surprise.
    """
    if script.exists():
        return script
    try:
        packaged = asset_path("scripts") / script.name
    except FileNotFoundError:
        return script
    if packaged.exists() and packaged != script:
        _LOG.warning(
            "vault script %s is missing; falling back to packaged copy %s "
            "(regenerable artifact — vault scripts/ is git-ignored and "
            "agent-writable; see _resolve_script)",
            script,
            packaged,
        )
        return packaged
    return script


def _run_script(
    python_bin: str,
    script: Path,
    *args: object,
    env: dict[str, str],
    log_file: Path | None = None,
) -> int:
    """Run a Python helper script, streaming stdout+stderr to ``log_file`` live.

    Streaming contract (v0.2.23, per ``specs/018-testing-strategy``):

    - Each subprocess line is prefixed with ``[HH:MM:SS]`` and flushed to BOTH
      the log file and the parent's stdout immediately. ``tail -f $LOG`` works
      in real time during agent execution, not only after the subprocess exits.
    - The log file is opened with ``buffering=1`` (line-buffered) so every line
      reaches disk synchronously — if the parent crashes mid-subprocess the
      log captures every line printed before the crash.
    - A daemon heartbeat thread appends ``[heartbeat] pid=… elapsed=…s``
      every 30s while the subprocess is silent (overridable via the
      ``RV_HEARTBEAT_S`` env var for tests). This distinguishes "agent is
      thinking for 10 minutes" from "process is dead" when watching the log.
    - On parent interrupt or exception the subprocess is terminated (then
      killed after 5s) so we never orphan an agent worker.
    - The call ends when the script does. Its output is drained on a reader
      thread while the caller waits for the exit, and the script's process
      group is terminated after a clean exit too: nothing it spawned
      outlives it, or keeps the call waiting on the pipe it inherited.
    - Startup and exit lines (``# [HH:MM:SS] launching: …``,
      ``# [HH:MM:SS] exited with code …``) bracket the run so post-mortems
      can read elapsed wall-clock time from the log alone.

    Returns the subprocess exit code. Raises :class:`_StepError` if the
    subprocess cannot be launched (missing file, bad permissions, etc.) —
    same external contract as the v0.2.22 implementation.
    """
    script = _resolve_script(script)
    cmd = [python_bin, str(script)] + [str(a) for a in args]
    label = script.name
    sp = _subprocess()

    if log_file is None:
        # No log file requested: keep the lightweight code path. stdout/stderr
        # are inherited so the user still sees output in real time; the kernel
        # handles buffering.
        try:
            return sp.run(cmd, env=env).returncode
        except OSError as e:
            _LOG.error("could not launch %s: %s", script, e)
            raise _StepError(str(e)) from e

    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_file.open("w", encoding="utf-8", buffering=1)
    try:
        header = f"# [{_hms()}] launching: {' '.join(cmd)}\n# log_file: {log_file}\n"
        log_handle.write(header)
        log_handle.flush()
        try:
            sys.stdout.write(header)
            sys.stdout.flush()
        except (OSError, ValueError):
            pass

        try:
            # Spec 050: ``popen_session`` adds ``start_new_session=True`` so
            # the child becomes its own process-group leader. The cleanup
            # path in the ``finally`` block below then signals the WHOLE
            # tree on a parent interrupt instead of orphaning grandchildren
            # (codex sandbox, MCP servers, etc.) that keep the stdout pipe
            # alive and stall the parent's read loop for hours.
            proc = popen_session(
                cmd,
                env=env,
                stdout=sp.PIPE,
                stderr=sp.STDOUT,
                bufsize=1,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as e:
            _LOG.error("could not launch %s: %s", script, e)
            raise _StepError(str(e)) from e

        def _drain() -> None:
            assert proc.stdout is not None  # nosec — Popen guarantees this
            try:
                for raw_line in proc.stdout:
                    if not raw_line:
                        continue
                    # Preserve any newline the subprocess emitted so log
                    # formatting stays sane; if the subprocess used the
                    # rare bare-CR pattern (some progress-bar libs) we
                    # still want one log line per emission.
                    stamped = f"[{_hms()}] {raw_line}"
                    if not stamped.endswith("\n"):
                        stamped += "\n"
                    try:
                        log_handle.write(stamped)
                        log_handle.flush()
                    except (OSError, ValueError):
                        pass
                    try:
                        sys.stdout.write(stamped)
                        sys.stdout.flush()
                    except (OSError, ValueError):
                        pass
            except (OSError, ValueError):
                return  # the pipe was closed under us

        # The output is drained on a thread of its own and this thread only
        # waits for the script. Reading the pipe here made the wait depend on
        # EOF, which needs every holder of the write end gone: a script that
        # exited while something it had spawned still held its stdout kept the
        # pipeline here for that descendant's whole lifetime (L-005).
        reader = threading.Thread(
            target=_drain, daemon=True, name=f"output-{label}-{proc.pid}"
        )
        reader.start()
        try:
            with _heartbeat_writer(log_handle, proc.pid, label=label):
                try:
                    returncode = proc.wait()
                finally:
                    # On every path. Unwound by Ctrl+C or a bug, the script
                    # is still running and must not be orphaned. After a
                    # clean exit whatever it left in its process group would
                    # run on, holding the pipe the reader is waiting on; an
                    # empty group makes this a no-op. SIGTERM to the whole
                    # group, the grace window, then SIGKILL — see spec 050 +
                    # post-mortem 2026-05-30.
                    try:
                        terminate_process_tree(proc)
                    except OSError:
                        pass
        finally:
            # Bounded: a descendant that left the group still holds the pipe
            # and cannot be killed, so its EOF may never come.
            reader.join(timeout=_OUTPUT_DRAIN_TIMEOUT_S)

        footer = f"# [{_hms()}] exited with code {returncode}\n"
        try:
            log_handle.write(footer)
            log_handle.flush()
            sys.stdout.write(footer)
            sys.stdout.flush()
        except (OSError, ValueError):
            pass

        return returncode
    finally:
        try:
            log_handle.close()
        except OSError:
            pass
