"""Process-tree-aware subprocess termination helpers (spec 050).

Why this module exists
======================

A plain ``subprocess.Popen(...)`` followed by ``proc.kill()`` only signals
the **direct child**. If that child has spawned grandchildren — sandbox
processes, MCP servers, web scrapers, ``yt-dlp`` forks — those keep
running AND keep the inherited stdout/stderr pipes open. The parent's
subsequent ``proc.stdout.read()`` or ``proc.communicate()`` then blocks
forever waiting for EOF, because EOF only fires when the LAST writer
closes the pipe.

We observed this in the wild on 2026-05-31 (feeds-vault cycle 003): the
60-minute ``note_writer`` timeout fired correctly, but
``scripts/agent_call.py`` stayed alive for another 3h 17m as a zombie
because codex's grandchildren never released the pipe.

The same trap applies to ``pipeline/source_bridge/extractor.py`` (which
spawns module extractors that may shell out to e.g. ``yt-dlp``) and to
the KeyboardInterrupt cleanup path in ``pipeline/_cycle_helpers.py``.

The fix
=======

1. Launch every long-running subprocess with ``start_new_session=True``
   so it becomes the leader of a fresh process group whose pgid equals
   the proc's PID. Any descendant that does NOT itself call ``setsid``
   stays inside that group.
2. On timeout / cleanup, ``os.killpg(pgid, SIGKILL)`` signals the
   entire group at once. Once everyone in the group is dead, the
   write-end of the pipe is fully closed and the parent's read calls
   unblock immediately.

The group outlives its leader
=============================

The direct child exiting says nothing about what it spawned. A leader
that exits on its own, or dies on the SIGTERM, leaves every descendant
it forked alive in the group — still holding the pipes. So the group is
signalled whether or not its leader is still running, and the SIGKILL
is skipped only once the group itself is empty.

That needs the group id after the leader is gone, when the kernel no
longer answers ``getpgid(pid)`` (macOS refuses even for an unreaped
zombie). ``popen_session`` therefore records it on the ``Popen`` object:
the child called ``setsid`` before ``exec``, so the id is its own pid.
POSIX keeps a pid reserved while a process group with that id exists, so
signalling a group that still has members cannot reach a stranger. An
empty group's id is free for reuse, so terminate as soon as the leader is
known to have exited, not some time later.

Best-effort caveat
==================

A grandchild that calls ``setsid`` (or otherwise escapes the group)
cannot be killed without crawling the process tree, which would require
``psutil`` — banned by Constitution Principle V (no new runtime
dependencies). Nothing here can stop it, so a caller that reads the
child's pipes must bound that read itself rather than wait for an EOF
the escaped process may never send.
"""

from __future__ import annotations

import errno
import os
import signal
import subprocess
import sys
import time
from typing import Any

_TREE_GRACE_S = 2.0
_TREE_KILL_TIMEOUT_S = 3.0
_GROUP_POLL_S = 0.05

#: The real class, bound before any test replaces ``subprocess.Popen``.
_Popen = subprocess.Popen


def popen_session(cmd: list[str], **kwargs: Any) -> subprocess.Popen[str]:
    """``subprocess.Popen`` wrapper that creates a fresh session on POSIX.

    Makes ``proc`` the leader of a new process group whose pgid equals
    ``proc.pid``. Callers can then ``os.killpg(proc.pid, sig)`` to signal
    the whole tree on timeout. No-op on Windows (we don't support it,
    but the guard keeps tests portable).
    """
    if sys.platform != "win32":
        kwargs.setdefault("start_new_session", True)
    proc = subprocess.Popen(cmd, **kwargs)
    # Only a child this call really started has a group to remember. A test
    # double's ``pid`` is just a number: remembered here, it is signalled as a
    # process group — a stranger's — by every ``terminate_process_tree``.
    if (
        sys.platform != "win32"
        and kwargs.get("start_new_session")
        and isinstance(proc, _Popen)
    ):
        try:
            proc._rf_session_pgid = proc.pid  # type: ignore[attr-defined]
        except AttributeError:  # a test double that refuses new attributes
            pass
    return proc


def _session_pgid(proc: subprocess.Popen[Any]) -> int | None:
    """The group ``popen_session`` created for ``proc``, if it may be signalled.

    ``None`` for a process this module did not start, and for any id that
    would turn a cleanup into a suicide: init's group, our own group, our
    own pid. The exact-type check is deliberate — a ``MagicMock`` attribute
    is not an ``int`` but coerces to 1.
    """
    pgid = getattr(proc, "_rf_session_pgid", None)
    if type(pgid) is not int or not hasattr(os, "killpg"):
        return None
    if pgid <= 1 or pgid == os.getpgrp() or pgid == os.getpid():
        return None
    return pgid


def _signal_group(pgid: int, sig: int) -> bool:
    """``killpg`` that reports whether there was anything left to signal."""
    try:
        os.killpg(pgid, sig)
    except OSError:
        # ESRCH: the group is empty. EPERM: what macOS answers for a group
        # holding only zombies. Either way nothing in it is still running.
        return False
    return True


def signal_process_tree(proc: subprocess.Popen[Any], sig: int) -> None:
    """Send ``sig`` to the entire process group rooted at ``proc``.

    A group ``popen_session`` created is signalled whether or not its leader
    is still alive. For any other process this falls back to signalling only
    the direct child if killpg is unavailable or the pgid lookup races with
    proc exit.
    """
    session_pgid = _session_pgid(proc)
    if session_pgid is not None:
        if not _signal_group(session_pgid, sig):
            try:
                proc.send_signal(sig)
            except (ProcessLookupError, OSError):
                pass
        return
    if proc.poll() is not None:
        return
    pgid: int | None = None
    if hasattr(os, "getpgid") and hasattr(os, "killpg"):
        try:
            pgid = os.getpgid(proc.pid)
        except (OSError, ProcessLookupError):
            pgid = None
        # Never signal init's group (pgid <= 1) or our OWN process group:
        # terminating a child's tree must target the child's isolated group,
        # never ours. Guards against a bogus proc.pid (e.g. a test MagicMock
        # whose .pid coerces to 1 -> getpgid(1)==1) becoming a suicidal
        # killpg that kills the caller — and, on Linux CI where the runner
        # process tree sits in group 1, the whole job (exit 143).
        if pgid is not None and (pgid <= 1 or pgid == os.getpgrp()):
            pgid = None
    if pgid is not None:
        try:
            os.killpg(pgid, sig)
            return
        except ProcessLookupError:
            return
        except PermissionError:
            pass
        except OSError as e:
            if e.errno == errno.ESRCH:
                return
    try:
        proc.send_signal(sig)
    except (ProcessLookupError, OSError):
        pass


def terminate_process_tree(
    proc: subprocess.Popen[Any],
    *,
    grace_s: float = _TREE_GRACE_S,
    kill_timeout_s: float = _TREE_KILL_TIMEOUT_S,
) -> bool:
    """Best-effort: kill ``proc`` AND its descendants. Returns True if proc exited.

    Sends SIGTERM to the process group, waits ``grace_s`` for graceful
    exit, then SIGKILLs the group if anything in it is still alive — the
    leader having exited, before the call or on the SIGTERM, is not the
    group being empty.
    """
    session_pgid = _session_pgid(proc)
    if session_pgid is None and proc.poll() is not None:
        return True

    signal_process_tree(proc, signal.SIGTERM)
    grace_deadline = time.monotonic() + grace_s
    try:
        proc.wait(timeout=grace_s)
        exited = True
    except subprocess.TimeoutExpired:
        exited = False

    if exited and session_pgid is not None:
        while _signal_group(session_pgid, 0) and time.monotonic() < grace_deadline:
            time.sleep(_GROUP_POLL_S)
        if _signal_group(session_pgid, 0):
            _signal_group(session_pgid, signal.SIGKILL)

    if not exited:
        signal_process_tree(proc, signal.SIGKILL)
        try:
            proc.wait(timeout=kill_timeout_s)
            exited = True
        except subprocess.TimeoutExpired:
            exited = False

    if not exited:
        # The leader itself survived SIGKILL. Close our pipe handles so
        # nothing in this process waits on them.
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
    return exited
