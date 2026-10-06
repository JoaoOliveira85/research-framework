#!/usr/bin/env python3
"""Runtime-agnostic agent dispatcher used by the cycle runner.

This is the single entry point responsible for honouring a vault's
`settings.yaml`. `run_cycle.sh` used to call `claude --print …` directly,
which silently ignored the `--settings codex` profile the generator
wrote into the vault. The dispatcher closes that gap:

1. Loads `<vault>/settings.yaml` (the profile baked at generation time).
2. Resolves the executor for the requested `--stage` name by merging
   the per-stage block over `default_executor`.
3. Builds the CLI invocation for the effective runtime (`claude`,
   `codex`, or `python` for script stages) using a small per-runtime
   adapter. Adapters are isolated so adding a new runtime is a single
   function plus a registry entry.
4. Runs the subprocess with the prompt piped on stdin (avoids argv-
   length and shell-escape pitfalls for the large rendered prompts the
   scout/DFS stages produce).

Environment overrides (read):

    CLAUDE_BIN / CODEX_BIN  — path to the respective CLI (default:
                              the plain binary name, found on $PATH).
    AGENT_CALL_DEBUG=1      — print the resolved command + model to
                              stderr before exec'ing (no secrets leaked).

Environment published to the runtime child (written):

    RESEARCH_FRAMEWORK_VAULT — the vault this call is dispatching against.
    RESEARCH_FRAMEWORK_STAGE — the stage name from ``--stage``.

    The CLI runtimes receive the prompt and nothing else, so this is the
    only channel that tells the spawned agent what it is working on. See
    ``_set_call_context``.

Exit code is propagated from the underlying CLI. Stdout/stderr stream
through unchanged so piping the cycle runner's output to `tee` keeps working.

Usage:
    python3 agent_call.py --vault <dir> --stage scout \\
        --prompt-file /tmp/scout-prompt.md
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

try:
    import yaml
except ImportError as e:  # pragma: no cover — yaml ships with every vault's scripts.
    print(
        f"ERROR: agent_call.py needs PyYAML (got ImportError: {e}). "
        "Install it into the environment running the cycle.",
        file=sys.stderr,
    )
    sys.exit(2)


# ---------------------------------------------------------------------------
# Process-tree timeout enforcement (spec 050)
# ---------------------------------------------------------------------------
#
# The bare ``subprocess.run(..., timeout=N)`` and ``proc.kill()`` patterns
# only signal the DIRECT child. If that child (e.g. ``codex exec``) has
# spawned grandchildren — its sandbox, MCP servers, headless scrapers —
# those keep running AND keep the inherited stdout/stderr pipes open. The
# parent's subsequent ``communicate()`` then blocks forever waiting for
# EOF on the pipe, even though the timeout has nominally fired.
#
# Symptom we hit in the wild (cycle 003 of feeds-vault, 2026-05-31): the
# 60-minute ``note_writer`` timeout fired correctly, but ``agent_call.py``
# stayed alive for another 3h 17m as a zombie because codex's grandchildren
# never released the pipe. Heartbeat thread kept printing "still alive"
# the whole time.
#
# The fix below is two-pronged:
#
# 1. Launch every subprocess with ``start_new_session=True`` so it becomes
#    the leader of a fresh process group. Any descendant that does NOT
#    call ``setsid`` itself stays in that group.
# 2. On timeout, ``os.killpg(pgid, SIGKILL)`` reaches the whole group.
#    Once everyone in the group is dead, the write-end of the pipe is
#    fully closed and ``communicate()`` unblocks immediately.
#
# The group outlives its leader. The direct child exiting says nothing
# about what it spawned: a leader that exits on its own, or dies on the
# SIGTERM, leaves every descendant it forked alive in the group, still
# holding the pipes. So the group is signalled whether or not its leader
# is still running, and the SIGKILL is skipped only once the group itself
# is empty. That needs the group id after the leader is gone, when the
# kernel no longer answers ``getpgid(pid)`` (macOS refuses even for an
# unreaped zombie), so ``_popen_session`` records it on the ``Popen``
# object: the child called ``setsid`` before ``exec``, so the id is its
# own pid. POSIX keeps a pid reserved while a process group with that id
# exists, so signalling a group that still has members cannot reach a
# stranger. An empty group's id is free for reuse, so terminate as soon as
# the leader is known to have exited, not some time later.
#
# Best-effort caveat: a grandchild that calls ``setsid`` (or otherwise
# escapes the group) cannot be killed without crawling the process tree
# (which would require ``psutil`` — banned by Principle V). Nothing here
# can stop it, so whoever reads the child's pipes must bound that read
# rather than wait for an EOF the escaped process may never send.


_TREE_GRACE_S = 2.0
#: Grace for the child when we are the one being stopped. Whoever sent our
#: SIGTERM SIGKILLs us ``_TREE_GRACE_S`` later (``pipeline/process_tree.py``),
#: and the child's group has to be dead before that.
_TREE_UNWIND_GRACE_S = 1.0
_TREE_KILL_TIMEOUT_S = 3.0
_TREE_DRAIN_TIMEOUT_S = 2.0
_GROUP_POLL_S = 0.05


# The call currently being dispatched, published to the runtime child's
# environment by ``_child_env`` (see ``_set_call_context``). Deliberately a
# module global rather than ``os.environ``: ``dispatch()`` runs IN-process for
# some callers (``plan_narrator``), and mutating the interpreter's own
# environment there would leak one stage's context into everything the host
# process does afterwards.
_CALL_CONTEXT: dict[str, str] = {}

#: Env keys the dispatcher publishes downward. ``RESEARCH_FRAMEWORK_REPO_ROOT``
#: (the fake-agent shim's escape hatch) already set the naming precedent.
CALL_CONTEXT_VAULT_ENV = "RESEARCH_FRAMEWORK_VAULT"
CALL_CONTEXT_STAGE_ENV = "RESEARCH_FRAMEWORK_STAGE"


def _set_call_context(vault_dir: Path | None, stage: str | None) -> None:
    """Record which vault and stage the next spawn belongs to.

    Every runtime CLI we drive is told the prompt and nothing else, so an
    agent — or a test double standing in for one — has no way to know which
    vault it is writing or which stage it is playing except by reading prose
    out of the prompt. Publishing the pair explicitly is what lets the fake
    live at the CLI-BINARY seam (issue #270) instead of replacing
    ``agent_call.py`` wholesale, which is what kept the whole dispatcher —
    argv construction, stream-json framing, sidecar v1.2 — off every e2e path.

    Set on entry to each public dispatch (``run`` / ``dispatch``); passing
    ``None`` clears it.
    """
    _CALL_CONTEXT.clear()
    if vault_dir is not None:
        _CALL_CONTEXT[CALL_CONTEXT_VAULT_ENV] = str(vault_dir)
    if stage is not None:
        _CALL_CONTEXT[CALL_CONTEXT_STAGE_ENV] = stage


def _child_env() -> dict[str, str]:
    """The ambient environment plus the current call context."""
    return {**os.environ, **_CALL_CONTEXT}


def _popen_session(cmd: list[str], **kwargs: Any) -> subprocess.Popen[str]:
    """``subprocess.Popen`` wrapper that creates a fresh session on POSIX.

    Makes ``proc`` the leader of a new process group whose pgid equals
    ``proc.pid``. Callers can then ``os.killpg(proc.pid, sig)`` to signal
    the whole tree on timeout. No-op on Windows (we don't support it,
    but the guard keeps tests portable).

    Every CLI spawn in this module funnels through here (``_run_in_session_
    with_timeout`` included), so this is also the one place that injects the
    call context — no per-call-site plumbing to forget.
    """
    if sys.platform != "win32":
        kwargs.setdefault("start_new_session", True)
    kwargs.setdefault("env", _child_env())
    proc = subprocess.Popen(cmd, **kwargs)
    if sys.platform != "win32" and kwargs.get("start_new_session"):
        try:
            proc._rf_session_pgid = proc.pid  # type: ignore[attr-defined]
        except AttributeError:  # a test double that refuses new attributes
            pass
    return proc


def _session_pgid(proc: subprocess.Popen[str]) -> int | None:
    """The group ``_popen_session`` created for ``proc``, if it may be signalled.

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


def _signal_process_tree(proc: subprocess.Popen[str], sig: int) -> None:
    """Send ``sig`` to the entire process group rooted at ``proc``.

    A group ``_popen_session`` created is signalled whether or not its leader
    is still alive. For any other process this falls back to signalling just
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


def _terminate_process_tree(
    proc: subprocess.Popen[str],
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

    _signal_process_tree(proc, signal.SIGTERM)
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
        _signal_process_tree(proc, signal.SIGKILL)
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


class _PipeDrain(threading.Thread):
    """Drains one of the child's pipes on its own thread, line by line.

    A pipe nobody reads fills (64 KiB) and blocks the child that is writing
    to it, and a pipe read on the waiting thread makes the wait depend on the
    child producing output. So every pipe gets a reader of its own, and the
    thread that waits for the child does nothing else.
    """

    def __init__(
        self,
        stream: Any,
        *,
        keep: bool,
        on_line: Callable[[str], None] | None = None,
        on_error: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(daemon=True)
        self._stream = stream
        self._keep = keep
        self._on_line = on_line
        self._on_error = on_error
        self._abandoned = False
        #: When the read now in flight began; ``None`` while a line is being
        #: delivered. Lets ``finish`` tell a pipe that has gone quiet from a
        #: consumer that is merely slow.
        self.reading_since: float | None = time.monotonic()
        self.lines: list[str] = []
        self.error: BaseException | None = None

    def run(self) -> None:
        try:
            lines = iter(self._stream)
            while True:
                self.reading_since = time.monotonic()
                try:
                    line = next(lines)
                except StopIteration:
                    return
                self.reading_since = None
                if self._abandoned:
                    return
                if self._keep:
                    self.lines.append(line)
                if self._on_line is not None and self.error is None:
                    try:
                        self._on_line(line)
                    except BaseException as exc:  # re-raised by _supervise_child
                        self.error = exc
                        if self._on_error is not None:
                            self._on_error()
        except (OSError, ValueError):
            return  # the pipe was closed under us

    def finish(self, since: float, patience: float) -> bool:
        """Wait for EOF; ``False`` if the pipe had to be given up on.

        EOF needs every holder of the write end gone, and one that left the
        process group cannot be killed. So a read that has seen nothing for
        ``patience`` seconds after ``since`` — when the group was terminated —
        is abandoned. A reader busy delivering a line is waited for: that is
        our own consumer being slow, not the child holding on.
        """
        while self.is_alive():
            self.join(_GROUP_POLL_S)
            started = self.reading_since
            if started is None:
                continue
            if time.monotonic() - max(started, since) > patience:
                self._abandoned = True
                return False
        return True


def _feed_stdin(stdin: Any, text: str) -> None:
    """Write the prompt and close the pipe.

    A child that exits without reading its prompt is not an error here (its
    exit code is the story), which is what ``communicate()`` assumes too.
    """
    try:
        stdin.write(text)
    except (OSError, ValueError):
        pass
    finally:
        try:
            stdin.close()
        except (OSError, ValueError):
            pass


@dataclass(frozen=True)
class _ChildOutcome:
    """What a supervised child left behind."""

    returncode: int
    stdout: str | None
    stderr: str | None
    timed_out: bool


def _supervise_child(
    cmd: list[str],
    *,
    input: str | None = None,
    timeout: float | None = None,
    capture_stdout: bool = False,
    capture_stderr: bool = False,
    on_stdout_line: Callable[[str], None] | None = None,
) -> _ChildOutcome:
    """Run ``cmd`` to the end of the call: bounded, drained, nothing left behind.

    The one place a runtime child is waited on. Three properties, each the
    fix for a way this used to hang (L-005, L-038):

    * **The clock does not depend on the child.** The calling thread only
      waits, with the timeout. A deadline consulted when a line of output
      arrives is never consulted for a child that has gone silent.
    * **Every pipe has its own reader.** The prompt is fed, and stdout and
      stderr are drained, on separate threads, so no pipe can fill and block
      the child while we wait on another one.
    * **The call ends when the child does.** Whether it exited, ran out of
      time, or we are being unwound by Ctrl+C, its whole process group is
      terminated: nothing it spawned may outlive it, and that is also what
      lets the readers see EOF. They then get a bounded time to finish —
      a descendant that left the group still holds the pipe and cannot be
      killed, so waiting for its EOF would be waiting for it.

    ``on_stdout_line`` runs on the reader thread. If it raises, the child's
    process group is killed there and then — output that cannot be delivered
    is not worth waiting for — and the exception is re-raised here once the
    pipes are drained.
    """
    reads_stdout = capture_stdout or on_stdout_line is not None
    proc = _popen_session(
        cmd,
        stdin=subprocess.PIPE if input is not None else None,
        stdout=subprocess.PIPE if reads_stdout else None,
        stderr=subprocess.PIPE if capture_stderr else None,
        text=True,
        errors="replace",
        bufsize=1,
    )

    feeder: threading.Thread | None = None
    if input is not None:
        feeder = threading.Thread(
            target=_feed_stdin, args=(proc.stdin, input), daemon=True
        )
        feeder.start()
    out: _PipeDrain | None = None
    if reads_stdout:
        out = _PipeDrain(
            proc.stdout,
            keep=capture_stdout,
            on_line=on_stdout_line,
            on_error=lambda: _signal_process_tree(proc, signal.SIGKILL),
        )
        out.start()
    err: _PipeDrain | None = None
    if capture_stderr:
        err = _PipeDrain(proc.stderr, keep=True)
        err.start()

    timed_out = False
    returncode: int | None = None
    grace_s = _TREE_GRACE_S
    try:
        try:
            returncode = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
    except BaseException:
        # Unwound from outside: Ctrl+C, or the SIGTERM ``_run_as_script``
        # turns into an exception. The sender is on a clock of its own.
        grace_s = _TREE_UNWIND_GRACE_S
        raise
    finally:
        try:
            _terminate_process_tree(proc, grace_s=grace_s)
        except BaseException:
            # Unwound out of the grace period itself (a second Ctrl+C, or our
            # SIGTERM landing while a timeout was being enforced). No more
            # patience: the group is killed before we go.
            _signal_process_tree(proc, signal.SIGKILL)
            raise
        since = time.monotonic()
        for drain, stream in ((out, proc.stdout), (err, proc.stderr)):
            if drain is not None and drain.finish(since, _TREE_DRAIN_TIMEOUT_S):
                try:
                    stream.close()
                except Exception:
                    pass
        if feeder is not None:
            feeder.join(max(0.0, since + _TREE_DRAIN_TIMEOUT_S - time.monotonic()))

    if out is not None and out.error is not None:
        raise out.error
    if returncode is None:
        reaped = proc.returncode
        returncode = reaped if isinstance(reaped, int) else -int(signal.SIGKILL)
    return _ChildOutcome(
        returncode=returncode,
        stdout="".join(list(out.lines)) if out is not None and capture_stdout else None,
        stderr="".join(list(err.lines)) if err is not None else None,
        timed_out=timed_out,
    )


def _echo_stdout_line(line: str) -> None:
    """Pass one line of the child's stdout on to ours, as it arrives."""
    sys.stdout.write(line)
    sys.stdout.flush()


def _run_in_session_with_timeout(
    cmd: list[str],
    *,
    input: str | None = None,
    capture_output: bool = False,
    text: bool = True,
    timeout: float | None = None,
    tee_stdout: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Drop-in replacement for ``subprocess.run`` that kills the whole tree.

    Semantics match ``subprocess.run`` on the success path, in text mode. On
    timeout ``subprocess.TimeoutExpired`` is raised with whatever output was
    captured before the kill. Either way the child's process group is gone
    when this returns — see ``_supervise_child``.

    ``tee_stdout`` (without ``capture_output``) returns the child's stdout and
    also passes every line through to ours as it arrives; stderr stays
    inherited. For a caller that has to read what the child printed without
    taking the stream away from whoever is watching our own output.
    """
    if not text:
        raise ValueError("_run_in_session_with_timeout only runs in text mode")
    tee = tee_stdout and not capture_output
    outcome = _supervise_child(
        cmd,
        input=input,
        timeout=timeout,
        capture_stdout=capture_output or tee,
        capture_stderr=capture_output,
        on_stdout_line=_echo_stdout_line if tee else None,
    )
    if outcome.timed_out:
        raise subprocess.TimeoutExpired(
            cmd, timeout, output=outcome.stdout, stderr=outcome.stderr
        )
    return subprocess.CompletedProcess(
        cmd, outcome.returncode, outcome.stdout, outcome.stderr
    )


# ---------------------------------------------------------------------------
# Executor resolution
# ---------------------------------------------------------------------------

DEFAULT_EXECUTOR: dict[str, Any] = {
    "runtime": "claude",
    "model": "sonnet",
    "args": [],
    "timeout_s": 3600,
}


def _load_settings(vault_dir: Path) -> dict[str, Any]:
    """Load `<vault>/settings.yaml`. Missing file is fatal — the generator
    always writes one, so its absence means the vault is malformed."""
    # Holdout from spec 025 B7: merges default_executor + per-stage args with
    # additive precedence and env overrides; not expressible as VaultSettings alone.
    settings_path = vault_dir / "settings.yaml"
    if not settings_path.is_file():
        raise FileNotFoundError(
            f"settings.yaml not found at {settings_path}. "
            "Re-run `rv generate` — every vault must carry its own settings."
        )
    with settings_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{settings_path}: top-level must be a mapping.")
    return data


def _apply_stage_model_override(
    settings: dict[str, Any],
    stage: str,
    model: str | None,
) -> dict[str, Any]:
    """Return settings with an ephemeral per-call ``stages.<stage>.model`` override."""
    if model is None:
        return settings
    merged = dict(settings)
    stages_raw = merged.get("stages") or {}
    stages = dict(stages_raw) if isinstance(stages_raw, dict) else {}
    stage_cfg_raw = stages.get(stage) or {}
    stage_cfg = dict(stage_cfg_raw) if isinstance(stage_cfg_raw, dict) else {}
    stage_cfg["model"] = model
    stages[stage] = stage_cfg
    merged["stages"] = stages
    return merged


def _resolve_executor(settings: dict[str, Any], stage: str) -> dict[str, Any]:
    """Return the effective executor config for ``stage``.

    Precedence:

    - Scalar keys (``runtime``, ``model``, ``timeout_s``, …):
      ``stages.<stage>`` > ``default_executor`` > ``DEFAULT_EXECUTOR``.
    - ``args`` is **additive**, not replacement: the final list is
      ``default_executor.args + stages.<stage>.args``. This is what
      lets a profile encode runtime-wide flags (e.g. Codex's
      ``--skip-git-repo-check`` + ``--sandbox workspace-write``) in
      ``default_executor.args`` once, while individual stages still
      add their own tuning (e.g. ``-c model_reasoning_effort=low``)
      without wiping the runtime flags out.

    Unknown stages fall through to the default cleanly.
    """
    merged: dict[str, Any] = dict(DEFAULT_EXECUTOR)

    default = settings.get("default_executor") or {}
    stages = settings.get("stages") or {}
    stage_cfg = stages.get(stage) if isinstance(stages, dict) else None
    if not isinstance(stage_cfg, dict):
        stage_cfg = {}

    # Scalar keys: merge with stage winning.
    if isinstance(default, dict):
        merged.update(
            {k: v for k, v in default.items() if v is not None and k != "args"}
        )
    merged.update({k: v for k, v in stage_cfg.items() if v is not None and k != "args"})

    # Args: additive. Validate each list up front so errors point at the
    # actual offending source (default vs stage) rather than a merged blob.
    def _coerce_args(source_name: str, raw: Any) -> list[str]:
        if raw is None:
            return []
        if not isinstance(raw, list):
            raise ValueError(
                f"stage '{stage}': {source_name}.args must be a list, got {raw!r}"
            )
        return [str(a) for a in raw]

    default_args = _coerce_args(
        "default_executor", default.get("args") if isinstance(default, dict) else None
    )
    stage_args = _coerce_args(f"stages.{stage}", stage_cfg.get("args"))
    merged["args"] = default_args + stage_args
    return merged


# ---------------------------------------------------------------------------
# Per-runtime adapters — each returns the argv list ready for subprocess.run
# ---------------------------------------------------------------------------


def _claude_cmd(executor: dict[str, Any]) -> list[str]:
    """Build the invocation for the Anthropic Claude CLI.

    Matches the pattern the old `run_cycle.sh` used: `claude --model
    <m> --print` reading the prompt from stdin. Extra ``args`` from the
    settings file are inserted before ``--print`` so callers can wire
    in any supported Claude CLI flag per stage.
    """
    bin_path = os.environ.get("CLAUDE_BIN") or "claude"
    cmd = [bin_path, "--model", str(executor["model"])]
    cmd.extend(str(a) for a in executor["args"])
    cmd.append("--print")
    return cmd


def _claude_cmd_with_cost(executor: dict[str, Any]) -> list[str]:
    """Same as _claude_cmd but in stream-json mode so the wrapper can
    parse a final ``result`` event for ``total_cost_usd``. Streaming is
    preserved via line-by-line forwarding in _run_claude_with_cost."""
    cmd = _claude_cmd(executor)
    cmd.extend(["--output-format", "stream-json", "--verbose"])
    return cmd


def _has_cd_flag(args: list[str]) -> bool:
    """True if the operator already pinned codex's working root themselves.

    Honour an explicit ``-C`` / ``--cd`` / ``--cd=<dir>`` in ``args`` so we
    never inject a second (conflicting) working-root flag.
    """
    return any(a in ("-C", "--cd") or a.startswith("--cd=") for a in args)


def _codex_cmd(executor: dict[str, Any], vault_dir: Path | None = None) -> list[str]:
    """Build the invocation for the OpenAI Codex CLI.

    Uses `codex exec` (the canonical non-interactive subcommand). The
    `-c key=value` overrides that the Codex settings profile uses for
    reasoning effort are just extra ``args`` — they get inserted
    verbatim between `exec` and the model flag, which is where Codex
    expects config overrides.

    The vault is pinned as codex's *working root* via ``--cd <vault_dir>``.
    Under ``--sandbox workspace-write`` (the profile default) writes are
    confined to that working root, so this is what lets the agent write the
    vault while staying *contained* to it. Without ``--cd``, codex inherits
    the orchestrator's cwd (typically ``~`` / ``~/Documents``) and
    ``workspace-write`` can't reach a vault that lives in a *sibling*
    directory — which is exactly why operators were forced onto
    ``--sandbox danger-full-access``. That mode runs every model-issued
    command UNsandboxed with full-disk read+write+network, the behavioural
    pattern that got 15 git-ignored vault scripts quarantined by endpoint
    security ~43s into a scout on 2026-06-05 (see CHANGELOG ``[1.0.0rc2]``).
    Pinning the working root lets the contained ``workspace-write`` default
    work, so the agent can no longer *write* anything outside the vault.
    (Reads stay open OS-wide under ``workspace-write`` — code-first vaults
    still read repos outside the vault; only writes are confined.)

    ``vault_dir`` is optional so the registry / direct callers keep working;
    an explicit operator ``-C`` / ``--cd`` in ``args`` wins (no double flag).
    """
    bin_path = os.environ.get("CODEX_BIN") or "codex"
    cmd: list[str] = [bin_path, "exec"]
    args = [str(a) for a in executor["args"]]
    # Pin the sandbox working root to the vault (see docstring) unless the
    # operator already set one explicitly.
    if vault_dir is not None and not _has_cd_flag(args):
        cmd.extend(["--cd", str(vault_dir)])
    # Config overrides (`-c model_reasoning_effort=low`, sandbox toggles,
    # …) need to come before the model flag to apply cleanly.
    cmd.extend(args)
    cmd.extend(["--model", str(executor["model"])])
    return cmd


def _python_cmd(executor: dict[str, Any]) -> list[str]:
    """Script-type executor: `type: script` + `script_path` + `args`.

    Used for deterministic stages (e.g. source-relevance classifier
    that's already a python script). The prompt gets piped on stdin so
    the script reads it the same way agent runs do.
    """
    script = executor.get("script_path")
    if not script:
        raise ValueError(
            "executor type='script' requires 'script_path' in settings.yaml"
        )
    cmd = [sys.executable, str(script)]
    cmd.extend(str(a) for a in executor["args"])
    return cmd


# Spec 052: recommended cursor tier→model map. The tier system
# (settings.yaml::tiers) is runtime-agnostic and resolves UPSTREAM into an
# explicit ``executor["model"]`` (exactly like the codex profile), so this is a
# documented recommendation for a cursor vault's ``tiers:`` block, not a runtime
# resolver. Model ids verified via ``cursor-agent --list-models`` (2026-06-08).
_CURSOR_MODEL_TIERS: dict[str, str] = {
    "basic": "composer-2.5-fast",
    "normal": "gpt-5.4-high",
    "flagship": "claude-opus-4-8-thinking-high",
}


def _has_workspace_flag(args: list[str]) -> bool:
    """True if the operator already pinned cursor's workspace themselves."""
    return any(a in ("-w", "--workspace") or a.startswith("--workspace=") for a in args)


def _cursor_cmd(executor: dict[str, Any], vault_dir: Path | None = None) -> list[str]:
    """Build the invocation for the Cursor agent CLI (spec 052).

    Headless shape (probed 2026-06-08): ``cursor-agent -p --output-format json
    --model <m> --trust [args…]`` reading the prompt from **stdin**. ``-p`` is
    print/non-interactive; ``--trust`` is REQUIRED headless (otherwise the CLI
    prompts for workspace trust). Extra ``args`` from settings (e.g. ``--force``,
    ``--sandbox``, ``--approve-mcps``) are appended verbatim.

    The vault is pinned as cursor's ``--workspace`` (the analogue of codex's
    ``--cd``) so the agent can write notes into a vault that lives in a sibling
    directory of the orchestrator's cwd — the write-confinement footgun that
    forced codex onto ``danger-full-access`` (CHANGELOG ``[1.0.0rc2]``). An
    explicit operator ``--workspace`` in ``args`` wins (no double flag).
    """
    bin_path = os.environ.get("CURSOR_BIN") or "cursor-agent"
    args = [str(a) for a in executor["args"]]
    cmd: list[str] = [bin_path, "-p", "--output-format", "json"]
    cmd.extend(["--model", str(executor["model"]), "--trust"])
    if vault_dir is not None and not _has_workspace_flag(args):
        cmd.extend(["--workspace", str(vault_dir)])
    cmd.extend(args)
    return cmd


def _cursor_cmd_with_cost(
    executor: dict[str, Any], vault_dir: Path | None = None
) -> list[str]:
    """Same as _cursor_cmd but in stream-json mode so the wrapper can parse the
    terminal ``result`` event for real ``usage`` tokens (live text is tee'd as
    it arrives). Cursor emits no per-call dollar (flat-rate)."""
    cmd = _cursor_cmd(executor, vault_dir)
    # Swap the base ``--output-format json`` for ``stream-json``.
    idx = cmd.index("json")
    cmd[idx] = "stream-json"
    return cmd


# ---------------------------------------------------------------------------
# Spec 064: opencode — the 4th first-class executor. A provider-agnostic
# agentic CLI: ``opencode run --format json --model <provider/model> --dir
# <vault>``. The model PROVIDER (ollama / openai / anthropic / …) is a config
# value opencode consumes, so one adapter reaches every provider. opencode
# emits NDJSON ``step_finish`` events — its OWN shape, distinct from the
# claude/cursor ``result`` event — so it has its own streaming branch + parser
# (which is why it is NOT in _STREAMING_AGENTS). Containment is ``--dir`` (the
# codex ``--cd`` / cursor ``--workspace`` analogue), never a full-disk mode.
# ---------------------------------------------------------------------------


def _has_dir_flag(args: list[str]) -> bool:
    """True if the operator already pinned opencode's working dir themselves."""
    return any(a == "--dir" or a.startswith("--dir=") for a in args)


def _opencode_cmd(executor: dict[str, Any], vault_dir: Path | None = None) -> list[str]:
    """Build the invocation for the opencode CLI (spec 064).

    Headless shape (probed against opencode v1.16.2): ``opencode run --format
    json --model <provider/model> --dir <vault> [--variant <effort>] [--agent
    <name>] <args>`` reading the prompt from **stdin**. ``--format json`` emits
    NDJSON events (``step_finish`` carries tokens + cost). ``--dir`` pins the
    agent's working root to the vault — the analogue of codex ``--cd`` / cursor
    ``--workspace`` — so writes stay vault-contained without a full-disk mode.
    An explicit operator ``--dir`` in ``args`` wins (no double flag).
    """
    bin_path = os.environ.get("OPENCODE_BIN") or "opencode"
    args = [str(a) for a in executor.get("args") or []]
    cmd: list[str] = [bin_path, "run", "--format", "json"]
    cmd.extend(["--model", str(executor["model"])])
    if vault_dir is not None and not _has_dir_flag(args):
        cmd.extend(["--dir", str(vault_dir)])
    variant = executor.get("variant")
    if variant:
        cmd.extend(["--variant", str(variant)])
    agent = executor.get("agent")
    if agent:
        cmd.extend(["--agent", str(agent)])
    cmd.extend(args)
    return cmd


# Spec 064 FR-015 — opencode preflight (fail-closed before dispatch).
# Containment/cost are framework-owned, but the model PROVIDER + its credentials
# live in opencode's own config (~/.config/opencode), so provider checks are
# best-effort "where derivable ahead of dispatch". Binary-on-PATH is fully
# derivable; local endpoint reachability is a fast socket probe; hosted creds
# are inferred from the conventional env var OR opencode's auth store.
#
# ``_OPENCODE_LOCAL_PROVIDERS`` is the DEFAULT list of provider prefixes treated
# as local ($0, real tokens, ``cost_source: runtime``); it is OVERRIDABLE per
# vault via ``settings.opencode.yaml::local_providers`` (cost contract rule 1).
# ``_resolve_local_providers`` reads that key (falling back to the default), and
# both ``_opencode_cost_class`` + ``_opencode_preflight`` accept the resolved set
# so a vault that, say, points an OpenAI-compatible provider at a local Ollama
# box can declare it local and get the honest $0 classification.
_OPENCODE_LOCAL_PROVIDERS = frozenset({"ollama", "local", "lmstudio", "llamacpp"})
_OPENCODE_HOSTED_CRED_ENV: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def _resolve_local_providers(settings: dict[str, Any]) -> frozenset[str]:
    """``settings.opencode.yaml::local_providers`` if present, else the default.

    An explicit empty list disables local-provider classification (every call is
    treated as metered). An invalid/missing key falls back to
    ``_OPENCODE_LOCAL_PROVIDERS``. Returned prefixes are lowercased to match
    ``_opencode_provider_from_model``.
    """
    raw = settings.get("local_providers")
    if raw is None:
        return _OPENCODE_LOCAL_PROVIDERS
    if not isinstance(raw, list):
        return _OPENCODE_LOCAL_PROVIDERS
    return frozenset(str(p).strip().lower() for p in raw if str(p).strip())


def _opencode_provider_from_model(model: str) -> str:
    """``provider`` from an opencode ``provider/model`` string (lowercased)."""
    return str(model or "").split("/", 1)[0].strip().lower()


def _opencode_binary_resolvable(bin_name: str) -> bool:
    """True iff the configured opencode binary can actually be spawned.

    For a bare command name rely on ``shutil.which`` (it already requires the X
    bit on the PATH-resolved hit). For an explicit path (anything with a path
    separator) require BOTH that the file exists AND that it carries the
    executable bit — ``Path.is_file`` alone passed for a non-executable file
    in the CWD, producing a false-positive that the dispatch then failed on.
    """
    has_sep = os.sep in bin_name or (os.altsep is not None and os.altsep in bin_name)
    if has_sep:
        p = Path(bin_name)
        return p.is_file() and os.access(p, os.X_OK)
    return shutil.which(bin_name) is not None


def _opencode_provider_reachable(base_url: str, *, timeout: float = 2.0) -> bool:
    """Fast TCP-connect reachability probe for a local provider endpoint.

    Parses ``host:port`` from ``base_url`` and attempts a short socket connect.
    Network-free in tests (monkeypatched). Returns True on connect, False on any
    socket error.
    """
    try:
        parsed = urllib.parse.urlsplit(
            base_url if "//" in base_url else "http://" + base_url
        )
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 11434
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _opencode_has_auth(provider: str) -> bool:
    """Best-effort: does opencode's auth store hold credentials for ``provider``?

    Reads opencode's ``auth.json`` (XDG data dir). Returns True when the provider
    is present OR when the store can't be located/parsed — *benefit of the doubt*
    so a misread store never produces a false-positive preflight failure (opencode
    is the real source of truth for hosted creds).
    """
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    auth_path = Path(data_home) / "opencode" / "auth.json"
    try:
        store = json.loads(auth_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True  # can't determine → don't fail closed on a guess
    return provider in store if isinstance(store, dict) else True


def _opencode_preflight(
    executor: dict[str, Any],
    *,
    local_providers: frozenset[str] | None = None,
) -> tuple[bool, str | None]:
    """``(ok, reason)`` fail-closed gate for an opencode run (FR-015).

    Order: (1) binary on PATH (or absolute path is executable); (2) local
    provider endpoint reachable; (3) hosted provider has credentials (env var
    OR opencode auth store). ``ok=True`` ⇒ ``reason is None``. ``local_providers``
    overrides the default set (see ``_resolve_local_providers``).
    """
    locals_set = (
        local_providers if local_providers is not None else _OPENCODE_LOCAL_PROVIDERS
    )
    bin_name = os.environ.get("OPENCODE_BIN") or "opencode"
    if not _opencode_binary_resolvable(bin_name):
        return (
            False,
            f"opencode binary '{bin_name}' not found on PATH (or not executable). "
            "Install opencode (https://opencode.ai) or set OPENCODE_BIN to its "
            "absolute path (with the executable bit set).",
        )
    provider = _opencode_provider_from_model(str(executor.get("model") or ""))
    if provider in locals_set:
        base_url = (
            os.environ.get("OLLAMA_BASE_URL")
            or str(executor.get("base_url") or "")
            or "http://127.0.0.1:11434"
        )
        if not _opencode_provider_reachable(base_url):
            return (
                False,
                f"local provider '{provider}' endpoint {base_url} is unreachable. "
                "Start the server (e.g. `ollama serve`) or fix base_url / "
                "OLLAMA_BASE_URL before running a cycle.",
            )
    elif provider in _OPENCODE_HOSTED_CRED_ENV:
        env_var = _OPENCODE_HOSTED_CRED_ENV[provider]
        if not os.environ.get(env_var) and not _opencode_has_auth(provider):
            return (
                False,
                f"hosted provider '{provider}' has no credentials: set {env_var} "
                f"or run `opencode auth login` for {provider} before a cycle.",
            )
    return (True, None)


# Cache key now includes the resolved local_providers set so a vault that
# overrides the list doesn't get a stale verdict from an earlier cycle's
# default set (and vice versa). Keyed per (bin, provider, base_url, locals).
_OPENCODE_PREFLIGHT_CACHE: dict[
    tuple[str, str, str, frozenset[str]], tuple[bool, str | None]
] = {}


def _opencode_preflight_cached(
    executor: dict[str, Any],
    *,
    local_providers: frozenset[str] | None = None,
) -> tuple[bool, str | None]:
    """``_opencode_preflight`` memoised per (bin, provider, base_url, locals)
    for this process — the reachability probe runs once per cycle, not per
    stage."""
    locals_set = (
        local_providers if local_providers is not None else _OPENCODE_LOCAL_PROVIDERS
    )
    key = (
        os.environ.get("OPENCODE_BIN") or "opencode",
        _opencode_provider_from_model(str(executor.get("model") or "")),
        os.environ.get("OLLAMA_BASE_URL") or str(executor.get("base_url") or ""),
        locals_set,
    )
    if key not in _OPENCODE_PREFLIGHT_CACHE:
        _OPENCODE_PREFLIGHT_CACHE[key] = _opencode_preflight(
            executor, local_providers=locals_set
        )
    return _OPENCODE_PREFLIGHT_CACHE[key]


def _parse_opencode_ndjson(text: str) -> dict[str, Any] | None:
    """Accumulate opencode's NDJSON ``--format json`` stream into usage totals.

    opencode emits one JSON object per line; the cost-bearing event is
    ``type: "step_finish"`` carrying ``part.tokens.{input,output}`` + a real
    ``part.cost`` (0 for local, models.dev pricing for metered). A multi-step
    agentic run emits one per step (each a real API call) — SUM across them.
    Robust to malformed lines and a missing terminal event (verified shape,
    ``research.md`` R1). Returns ``{tokens_in, tokens_out, cost_usd, n_steps}``
    or ``None`` when zero ``step_finish`` events were seen (caller → estimator).
    """
    tokens_in = tokens_out = n_steps = 0
    cost_usd = 0.0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(event, dict) or event.get("type") != "step_finish":
            continue
        part = event.get("part") or {}
        tokens = part.get("tokens") or {}
        tokens_in += int(tokens.get("input") or 0)
        tokens_out += int(tokens.get("output") or 0)
        try:
            cost_usd += float(part.get("cost") or 0.0)
        except (TypeError, ValueError):
            pass
        n_steps += 1
    if n_steps == 0:
        return None
    return {
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": cost_usd,
        "n_steps": n_steps,
    }


def _opencode_cost_class(
    model: str,
    usage: dict[str, Any] | None,
    *,
    local_providers: frozenset[str] | None = None,
) -> tuple[float, int, int, str]:
    """Classify one opencode call's cost (spec 064 FR-006/007; cost contract).

    opencode has NO static cost class — it depends on the resolved provider:
      1. local provider (ollama/local/…)        → measured ``cost`` (≈$0) + real
                                                    tokens ⇒ ``runtime``.
      2. metered + real dollar (opencode's       → that dollar + real tokens ⇒
         models.dev pricing, the common case)      ``runtime``.
      3. metered + tokens but no/zero dollar      → real tokens, dollar deferred
                                                    to the estimator ⇒
                                                    ``runtime_tokens``.
      4. no parseable usage                        → ``(0,0,0,"none")``; caller
                                                    falls back to the estimator —
                                                    NEVER a silent ``runtime`` $0.

    ``local_providers`` overrides the default set so a vault can declare its own
    local-provider prefixes via ``settings.opencode.yaml::local_providers``
    (cost contract rule 1, "overridable in settings.opencode.yaml").
    """
    if usage is None:
        return (0.0, 0, 0, _COST_SOURCE_NONE)
    tokens_in = int(usage.get("tokens_in") or 0)
    tokens_out = int(usage.get("tokens_out") or 0)
    cost = float(usage.get("cost_usd") or 0.0)
    provider = _opencode_provider_from_model(model)
    locals_set = (
        local_providers if local_providers is not None else _OPENCODE_LOCAL_PROVIDERS
    )
    if provider in locals_set:
        return (cost, tokens_in, tokens_out, _COST_SOURCE_RUNTIME)
    if cost > 0:
        return (cost, tokens_in, tokens_out, _COST_SOURCE_RUNTIME)
    return (0.0, tokens_in, tokens_out, _COST_SOURCE_RUNTIME_TOKENS)


def _resolve_opencode_cost(
    stdout: str,
    model: str,
    estimate_fn: Callable[[], tuple[float, int] | None],
    *,
    local_providers: frozenset[str] | None = None,
) -> tuple[float, int, int, str]:
    """Resolve one opencode call's final ``(cost_usd, tokens_in, tokens_out,
    cost_source)`` from its NDJSON stdout. Shared by both dispatch surfaces
    (``dispatch()`` and the CLI ``run()`` the benchmark uses) so opencode cost is
    honest everywhere. ``estimate_fn`` is the spec-033 estimator, called LAZILY —
    only the metered tokens-only / no-usage arms need it; the common local-$0
    path never pays for it. ``local_providers`` propagates the per-vault override
    (see ``_resolve_local_providers``)."""
    usage = _parse_opencode_ndjson(stdout)
    cost, tin, tout, source = _opencode_cost_class(
        model, usage, local_providers=local_providers
    )
    if source == _COST_SOURCE_RUNTIME:
        return (cost, tin, tout, _COST_SOURCE_RUNTIME)
    est = estimate_fn()
    if source == _COST_SOURCE_RUNTIME_TOKENS:
        dollar = est[0] if est is not None else 0.0
        return (dollar, tin, tout, _COST_SOURCE_RUNTIME_TOKENS)
    if est is not None:
        return (est[0], est[1], 0, _COST_SOURCE_ESTIMATED)
    return (0.0, 0, 0, _COST_SOURCE_NONE)


def _extract_opencode_text(ndjson: str) -> str:
    """opencode's assistant answer, concatenated from its NDJSON ``text`` events.

    opencode (``--format json``) emits the model's actual output in
    ``type: "text"`` events (``part.text``); the surrounding step/tool/finish
    events are control envelope. Stage consumers (and the spec-056 benchmark
    scorers) need the ANSWER, not the raw event stream — so the dispatch + CLI
    paths surface THIS as the stage output instead of the raw NDJSON. Returns
    ``""`` when there are no text events (e.g. a pure tool-write turn whose real
    output is a file the agent wrote, not stdout)."""
    parts: list[str] = []
    for raw in ndjson.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(event, dict) and event.get("type") == "text":
            text = (event.get("part") or {}).get("text")
            if text:
                parts.append(str(text))
    return "".join(parts)


# `type: cli` is the default; when `type: script` is set, dispatch to
# _python_cmd regardless of runtime.
_RUNTIME_ADAPTERS: dict[str, Callable[[dict[str, Any]], list[str]]] = {
    "claude": _claude_cmd,
    "codex": _codex_cmd,
    "cursor-agent": _cursor_cmd,
    "opencode": _opencode_cmd,
    "python": _python_cmd,
}


def _build_command(
    executor: dict[str, Any], vault_dir: Path | None = None
) -> list[str]:
    if executor.get("type") == "script":
        return _python_cmd(executor)
    runtime = str(executor["runtime"])
    if runtime == "codex":
        # Codex alone needs the vault path to pin its sandbox working root
        # (``--cd``); the other adapters are vault-agnostic. Kept in
        # _RUNTIME_ADAPTERS too so the unknown-runtime listing stays correct.
        return _codex_cmd(executor, vault_dir)
    if runtime == "cursor-agent":
        # Cursor pins its writable root via ``--workspace`` (spec 052) — same
        # sibling-directory write-confinement need as codex's ``--cd``.
        return _cursor_cmd(executor, vault_dir)
    if runtime == "opencode":
        # Spec 064: opencode pins its working root via ``--dir`` — same
        # write-confinement need as codex's ``--cd`` / cursor's ``--workspace``.
        return _opencode_cmd(executor, vault_dir)
    adapter = _RUNTIME_ADAPTERS.get(runtime)
    if adapter is None:
        raise ValueError(
            f"unknown runtime '{runtime}' — supported: "
            f"{sorted(_RUNTIME_ADAPTERS)}. Edit settings.yaml to pick one, "
            "or extend _RUNTIME_ADAPTERS in agent_call.py to add support."
        )
    return adapter(executor)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _read_prompt(prompt_file: Path | None) -> str:
    if prompt_file is not None:
        return prompt_file.read_text(encoding="utf-8")
    return sys.stdin.read()


# ---------------------------------------------------------------------------
# Programmatic dispatch API (spec 025 A1/A2 — contracts/llm-dispatch.contract.md)
# ---------------------------------------------------------------------------

_CURSOR_AGENT = "cursor-agent"
# Spec 047 v1: the first non-CLI runtime. A LOCAL Ollama server reached over
# HTTP (OpenAI-compatible /v1/chat/completions or native /api/chat). It is an
# LLM agent (guarded), but NOT a streaming CLI and NOT a flat-rate CLI — it has
# its own dispatch branch (``_dispatch_http``).
_OLLAMA = "ollama"
# Spec 064: opencode is an LLM agent reached via the CLI adapter. It is
# deliberately ABSENT from _STREAMING_AGENTS / _FLAT_RATE_AGENTS / _HTTP_RUNTIMES
# — its cost class is resolved PER CALL (local $0 vs metered) by
# ``_opencode_cost_class`` (spec 064 FR-006/007), and it has its own NDJSON
# ``step_finish`` streaming parser rather than the claude/cursor ``result`` one.
_OPENCODE = "opencode"
_LLM_AGENT_NAMES = frozenset({"claude", "codex", _CURSOR_AGENT, _OLLAMA, _OPENCODE})
# Runtimes that emit stream-json with a terminal ``result`` event (live text +
# usage). Both route through the streaming dispatch/CLI path (spec 052).
_STREAMING_AGENTS = frozenset({"claude", _CURSOR_AGENT})
# Flat-rate runtimes: they report REAL token usage but NO per-call dollar, so
# the dollar is taken from the spec-033 estimator and flagged
# ``cost_source: runtime_tokens`` (spec 052).
_FLAT_RATE_AGENTS = frozenset({_CURSOR_AGENT})
# Spec 047 v1: runtimes dispatched over HTTP instead of a CLI subprocess. They
# return REAL token counts and (being local) a TRUE $0 cost ⇒ ``cost_source:
# runtime`` (both measured). Handled by ``_is_http_executor`` / ``_dispatch_http``.
#
# Spec 064 NOTE: this raw-HTTP Ollama path is kept DORMANT but harmless — it is
# *non-agentic* (returns text, cannot write the stage output files a cycle needs).
# To reach Ollama (or any provider) in a real cycle, use the ``opencode`` executor
# (``settings.opencode.yaml``, ``--model ollama/<model>``), which runs an agent
# loop with filesystem tools. Spec 047 is tombstoned (superseded by 064).
_HTTP_RUNTIMES = frozenset({_OLLAMA})
# Spec 028 rc3 amendment (A3): bumped 1.1 → 1.2 for the additive ``cost_source``
# discriminator. Consumers read fields with ``.get()`` so 1.1 readers tolerate it.
_SIDECAR_SCHEMA_VERSION = "1.2"
# cost_source literal (spec FR-028C): where the sidecar's cost_usd came from.
_COST_SOURCE_RUNTIME = "runtime"  # measured from the runtime's own signal
_COST_SOURCE_ESTIMATED = "estimated"  # spec-033 estimator fallback
_COST_SOURCE_NONE = "none"  # estimator also failed (emits a WARNING)
# Spec 052: real tokens measured from the runtime, but the dollar is an estimate
# (flat-rate runtime emits no per-call price). Honest middle ground between
# ``runtime`` (both measured) and ``estimated`` (neither measured).
_COST_SOURCE_RUNTIME_TOKENS = "runtime_tokens"
_DETERMINISTIC_SIDECAR_TIMESTAMPS = (
    "2000-01-01T00:00:00Z",
    "2000-01-01T00:00:01Z",
)
_BATCH_SIDECAR_RE = re.compile(r"-batch-(\d+)\.json$")
_STAGE_SUFFIX_RE = re.compile(r"-(\d+)\.json$")


@dataclass(frozen=True)
class AgentCallResult:
    """Outcome of a single ``dispatch()`` invocation."""

    stdout: str
    stderr: str
    exit_code: int
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0


@dataclass
class StreamCostResult:
    """Parsed stream-json terminal state from a Claude invocation.

    ``saw_result`` is True iff a terminal ``{"type": "result"}`` event was
    observed in the stream. Pytest exit code 0 alone is NOT a sufficient
    success signal — claude can exit cleanly mid-stream (network blip,
    truncated tool output) without emitting the terminal envelope. The
    sidecar's ``status: "ok"`` must require ``saw_result`` to be True
    AND ``exit_code == 0``; otherwise ``status: "failed"``.
    """

    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: int | None = None
    session_id: str | None = None
    is_error: bool = False
    stdout_text: str = ""
    #: The terminal event's ``result`` string: the runtime's final answer, which
    #: is what it prints to stdout in plain ``--print`` mode. Empty when no
    #: terminal event was seen or it carried no text.
    result_text: str = ""
    saw_result: bool = False


def _vault_dir_from_cycle_dir(cycle_dir: Path) -> Path:
    """``<vault>/_pipeline/cycles/cycle-NNN`` → vault root."""
    return cycle_dir.parent.parent.parent


def _resolve_agent_name(
    agent: str | None,
    settings: dict[str, Any],
    stage: str,
) -> str:
    if agent:
        return agent
    env_agent = (os.environ.get("RESEARCH_FRAMEWORK_DEFAULT_AGENT") or "").strip()
    if env_agent in _LLM_AGENT_NAMES:
        return env_agent
    executor = _resolve_executor(settings, stage)
    return str(executor.get("runtime") or "claude")


def _executor_for_dispatch(
    settings: dict[str, Any],
    stage: str,
    agent_name: str,
) -> dict[str, Any]:
    executor = dict(_resolve_executor(settings, stage))
    executor["runtime"] = agent_name
    return executor


def _iso_utc_ms_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_cycle_num(cycle_dir: Path) -> int:
    m = re.search(r"cycle-(\d+)", cycle_dir.name)
    return int(m.group(1)) if m else 1


# Issue #157: marker assembled at import time so this file does NOT itself
# contain the literal substring (ruff would otherwise constant-fold adjacent
# string literals back into one). The fake-agent shim template
# (tests/_helpers/fake_agent.py::_SHIM_TEMPLATE) defines this name at module
# scope; the production agent_call.py never references it as a single token.
# Without this split, the heuristic recursively self-matches and tags every
# real cursor-agent / claude / codex dispatch as agent_kind=fake with the
# 2000-01-01 sentinel timestamps (the rc7 reference-vault validation symptom).
_FAKE_SHIM_MARKER = "".join(("_BAKED", "_REPO", "_ROOT"))


def _detect_agent_kind(
    agent_name: str, vault_dir: Path | None = None
) -> Literal["fake", "real"]:
    """Explicit fake vs real signal (spec 028 FR-002 / research R6)."""
    if agent_name == "fake" or agent_name not in _LLM_AGENT_NAMES:
        return "fake"
    if vault_dir is not None:
        shim = vault_dir / "scripts" / "agent_call.py"
        if shim.is_file():
            text = shim.read_text(encoding="utf-8", errors="replace")
            if _FAKE_SHIM_MARKER in text:
                return "fake"
    return "real"


def _started_at_for(agent_kind: Literal["fake", "real"]) -> str:
    """Wall-clock 'now' as ISO8601 ms (real) or the deterministic sentinel (fake).

    Must be called at the moment dispatch starts — paired with
    ``_completed_at_for`` called when dispatch finishes — so that the
    sidecar reports a meaningful elapsed wall-clock window. Previously
    both timestamps came from a single ``_iso_utc_ms_now()`` pair at
    completion time, hiding the actual start instant.
    """
    if agent_kind == "fake":
        return _DETERMINISTIC_SIDECAR_TIMESTAMPS[0]
    return _iso_utc_ms_now()


def _completed_at_for(agent_kind: Literal["fake", "real"]) -> str:
    """Wall-clock 'now' as ISO8601 ms (real) or the deterministic sentinel (fake).

    Paired with ``_started_at_for``; see that function's docstring.
    """
    if agent_kind == "fake":
        return _DETERMINISTIC_SIDECAR_TIMESTAMPS[1]
    return _iso_utc_ms_now()


def _sidecar_timestamps(
    agent_kind: Literal["fake", "real"],
    *,
    started_mono: float,
    completed_mono: float,
) -> tuple[str, str]:
    """DEPRECATED — collapses started/completed into a single wall-clock pair
    taken at the moment of call. Retained for backward compatibility with
    existing tests; new code should use ``_started_at_for`` /
    ``_completed_at_for`` separately at the actual start and end of the
    dispatched call.
    """
    if agent_kind == "fake":
        return _DETERMINISTIC_SIDECAR_TIMESTAMPS
    del started_mono, completed_mono  # wall clock used for real agents
    return _iso_utc_ms_now(), _iso_utc_ms_now()


def _allocate_sidecar_path(cycle_dir: Path, stage: str) -> Path:
    """Filesystem-backed per-call path (FR-005); batch files excluded."""
    agent_calls = cycle_dir / "agent-calls"
    agent_calls.mkdir(parents=True, exist_ok=True)
    base = agent_calls / f"{stage}.json"
    if not base.exists():
        return base
    max_suffix = 1
    prefix = f"{stage}-"
    for path in agent_calls.glob(f"{stage}-*.json"):
        name = path.name
        if "-batch-" in name:
            continue
        if name == f"{stage}.json":
            continue
        m = _STAGE_SUFFIX_RE.search(name)
        if m and name.startswith(prefix):
            max_suffix = max(max_suffix, int(m.group(1)))
    return agent_calls / f"{stage}-{max_suffix + 1}.json"


def _batch_fields_from_path(sidecar_path: Path) -> tuple[int | None, int | None]:
    m = _BATCH_SIDECAR_RE.search(sidecar_path.name)
    if not m:
        return None, None
    return int(m.group(1)), None


def _build_sidecar_v11_payload(
    *,
    stage: str,
    agent: str,
    agent_kind: Literal["fake", "real"],
    tier: str,
    status: Literal["ok", "failed"],
    exit_code: int,
    cost_usd: float,
    tokens_in: int,
    tokens_out: int,
    latency_ms: int,
    started_at: str,
    completed_at: str,
    cycle: int,
    cost_source: str = _COST_SOURCE_RUNTIME,
    stderr_excerpt: str | None = None,
    batch_index: int | None = None,
    topic_count: int | None = None,
    duration_ms: int | None = None,
    timed_out: bool | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": _SIDECAR_SCHEMA_VERSION,
        "stage": stage,
        "agent": agent,
        "agent_kind": agent_kind,
        "tier": tier,
        "status": status,
        "exit_code": int(exit_code),
        "cost_usd": round(max(0.0, float(cost_usd)), 4),
        "cost_source": cost_source,
        "tokens_in": max(0, int(tokens_in)),
        "tokens_out": max(0, int(tokens_out)),
        "latency_ms": max(0, int(latency_ms)),
        "started_at": started_at,
        "completed_at": completed_at,
        "cycle": int(cycle),
    }
    if stderr_excerpt:
        payload["stderr_excerpt"] = stderr_excerpt[:500]
    if batch_index is not None:
        payload["batch_index"] = int(batch_index)
    if topic_count is not None:
        payload["topic_count"] = int(topic_count)
    if duration_ms is not None:
        payload["duration_ms"] = int(duration_ms)
    if timed_out is not None:
        payload["timed_out"] = bool(timed_out)
    return payload


def _write_sidecar_v11(path: Path, payload: dict[str, Any]) -> None:
    """Atomic write via temp file + os.replace (spec 028 §1.3)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
                fh.write("\n")
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
    except Exception as e:  # pragma: no cover - filesystem edge case
        print(
            f"WARN: failed to write cost sidecar at {path}: {e}",
            file=sys.stderr,
        )


def _emit_sidecar_v11(
    path: Path,
    *,
    stage: str,
    agent: str,
    agent_kind: Literal["fake", "real"],
    tier: str,
    status: Literal["ok", "failed"],
    exit_code: int,
    cost_usd: float,
    tokens_in: int,
    tokens_out: int,
    latency_ms: int,
    started_at: str,
    completed_at: str,
    cycle: int,
    cost_source: str = _COST_SOURCE_RUNTIME,
    stderr_excerpt: str | None = None,
    batch_index: int | None = None,
    topic_count: int | None = None,
    duration_ms: int | None = None,
    timed_out: bool | None = None,
) -> None:
    payload = _build_sidecar_v11_payload(
        stage=stage,
        agent=agent,
        agent_kind=agent_kind,
        tier=tier,
        status=status,
        exit_code=exit_code,
        cost_usd=cost_usd,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
        started_at=started_at,
        completed_at=completed_at,
        cycle=cycle,
        cost_source=cost_source,
        stderr_excerpt=stderr_excerpt,
        batch_index=batch_index,
        topic_count=topic_count,
        duration_ms=duration_ms,
        timed_out=timed_out,
    )
    _write_sidecar_v11(path, payload)


def _apply_stream_event(
    event: dict[str, Any],
    result: StreamCostResult,
    *,
    capture_text: bool = True,
) -> str:
    """Apply one parsed stream-json event to ``result`` in-place.

    Shared by ``_consume_claude_stream`` (batch parse of a captured
    iterable, ``capture_text=True``) and ``_run_claude_with_cost``
    (incremental, ``capture_text=False`` because the caller tees text
    to stdout itself). Returns the extracted human-readable text so
    the caller can write it elsewhere if desired.
    """
    text = _extract_text_from_event(event)
    if capture_text and text:
        result.stdout_text += text
        if not text.endswith("\n"):
            result.stdout_text += "\n"
    if event.get("type") == "result":
        result.result_text = text
        result.cost_usd = float(event.get("total_cost_usd") or 0.0)
        dms = event.get("duration_ms")
        if isinstance(dms, (int, float)):
            result.duration_ms = int(dms)
        result.session_id = event.get("session_id")
        result.is_error = bool(event.get("is_error"))
        usage = event.get("usage") or {}
        if isinstance(usage, dict):
            # claude uses snake_case (input_tokens); cursor-agent uses camelCase
            # (inputTokens). Read both so one parser serves both runtimes
            # (spec 052). cursor carries no total_cost_usd ⇒ cost_usd stays 0.0
            # and the flat-rate dollar is supplied later by the estimator.
            result.tokens_in = int(
                usage.get("input_tokens") or usage.get("inputTokens") or 0
            )
            result.tokens_out = int(
                usage.get("output_tokens") or usage.get("outputTokens") or 0
            )
        result.saw_result = True
    return text


def _consume_claude_stream(stdout_iterable: Iterable[str]) -> StreamCostResult:
    """Shared stream-json parser for CLI and ``dispatch()`` (FR-001).

    Eagerly consumes ``stdout_iterable`` to completion; callers that need
    timeout-bounded reads must wrap the iterable (e.g. with a deadline
    guard) or use the incremental form (``_apply_stream_event``) directly.
    """
    result = StreamCostResult()
    for raw in stdout_iterable:
        line = raw.rstrip("\n")
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            result.stdout_text += line + "\n"
            continue
        _apply_stream_event(event, result)
    return result


def _codex_cost_from_output(stdout: str) -> tuple[float, int, int] | None:
    """Spec 028 rc3 A1: best-effort parse of a codex per-call cost/token signal.

    Codex's cost-output shape is unverified (plan F4 residual unknown — mirrors
    the spec-052 cursor-agent Q1). This parser looks for the robust, parseable
    case: a JSON object on its own line carrying ``total_cost_usd``/``cost_usd``
    (optionally with ``usage.{input,output}_tokens`` or ``tokens_in``/
    ``tokens_out``). Returns ``(cost_usd, tokens_in, tokens_out)`` on a hit, else
    ``None`` (the A2 estimate then stands). No-ops cleanly on arbitrary text.
    """
    if not stdout:
        return None
    for raw in stdout.splitlines():
        line = raw.strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        cost = obj.get("total_cost_usd")
        if cost is None:
            cost = obj.get("cost_usd")
        if cost is None:
            continue
        try:
            cost_f = float(cost)
        except (TypeError, ValueError):
            continue
        usage = obj.get("usage") if isinstance(obj.get("usage"), dict) else {}
        tin = usage.get("input_tokens", obj.get("tokens_in", 0))
        tout = usage.get("output_tokens", obj.get("tokens_out", 0))
        try:
            return cost_f, int(tin or 0), int(tout or 0)
        except (TypeError, ValueError):
            return cost_f, 0, 0
    return None


def _cursor_cost_from_output(stdout: str) -> tuple[int, int] | None:
    """Spec 052: parse cursor-agent's REAL token usage from its json /
    stream-json output.

    Cursor emits a ``result`` object/event carrying
    ``usage.{inputTokens,outputTokens}`` (camelCase) but NO dollar figure
    (flat-rate subscription). Returns ``(tokens_in, tokens_out)`` from the LAST
    matching usage block (the terminal result), else ``None``. No-ops cleanly on
    arbitrary text. The dollar is supplied separately by the spec-033 estimator.
    """
    if not stdout:
        return None
    found: tuple[int, int] | None = None
    for raw in stdout.splitlines():
        line = raw.strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        usage = obj.get("usage")
        if not isinstance(usage, dict):
            continue
        tin = usage.get("inputTokens")
        tout = usage.get("outputTokens")
        if tin is None and tout is None:
            continue
        try:
            found = (int(tin or 0), int(tout or 0))
        except (TypeError, ValueError):
            continue
    return found


def _fallback_estimate(
    vault_dir: Path | None,
    *,
    cycle_num: int,
    stage: str,
    prompt_text: str,
    agent: str,
    tier: str,
) -> tuple[float, int] | None:
    """Spec 028 rc3 A2: the spec-033 estimator value used when a non-claude
    runtime emits no parseable cost. Returns ``(cost_usd, codex_tokens)`` or
    ``None`` if estimation is unavailable (import/settings failure)."""
    if vault_dir is None:
        return None
    try:
        from research_framework.pipeline.cost_estimator import estimate_dispatch
        from research_framework.pipeline.settings import load_vault_settings

        limits = load_vault_settings(vault_dir).limits
        est = estimate_dispatch(
            vault_dir=vault_dir,
            cycle_num=cycle_num,
            stage=stage,
            prompt_text=prompt_text,
            agent=agent,
            tier=tier,
            limits=limits,
        )
        return float(est.cost_usd), int(est.codex_tokens)
    except Exception as exc:  # pragma: no cover - defensive
        print(
            f"WARN: cost estimator fallback failed for {stage}: {exc}", file=sys.stderr
        )
        return None


def _resolve_cost(
    *,
    stream: StreamCostResult | None,
    runtime_cost: tuple[float, int, int] | None,
    estimate: tuple[float, int] | None,
    agent_name: str,
    stage: str,
    exit_code: int,
    timed_out: bool,
    warn: bool = True,
) -> tuple[float, int, int, str]:
    """Spec 028 rc3 (FR-028A/B/C): collapse the cost signals into one
    ``(cost_usd, tokens_in, tokens_out, cost_source)`` tuple.

    Precedence:
      1. claude stream OR a parsed codex signal ⇒ ``runtime`` (measured).
      2. else the spec-033 estimator value ⇒ ``estimated`` (never silent $0).
      3. else 0.0 ⇒ ``none`` (+ a one-time WARNING when ``warn`` is set and the
         call actually completed — error/timeout paths stay quiet).
    """
    if stream is not None:
        if agent_name in _FLAT_RATE_AGENTS:
            # Spec 052: cursor reports REAL tokens via the stream but NO dollar
            # (flat-rate). Keep the real tokens; take the dollar from the
            # spec-033 estimator so the dollar cap still has a number; flag the
            # mixed provenance. An honest flat-rate $0 stands if the estimator
            # was unavailable (never crashes, never a misleading "runtime" $).
            dollar = estimate[0] if estimate is not None else 0.0
            return (
                dollar,
                stream.tokens_in,
                stream.tokens_out,
                _COST_SOURCE_RUNTIME_TOKENS,
            )
        return (
            stream.cost_usd,
            stream.tokens_in,
            stream.tokens_out,
            _COST_SOURCE_RUNTIME,
        )
    if runtime_cost is not None:
        cost_usd, tokens_in, tokens_out = runtime_cost
        return cost_usd, tokens_in, tokens_out, _COST_SOURCE_RUNTIME
    if estimate is not None:
        cost_usd, codex_tokens = estimate
        return cost_usd, codex_tokens, 0, _COST_SOURCE_ESTIMATED
    if warn and agent_name != "claude" and not timed_out and exit_code == 0:
        print(
            f"WARN: no cost signal for {agent_name} stage '{stage}' and the "
            "estimator was unavailable — sidecar cost_source=none (cost_usd=0)",
            file=sys.stderr,
        )
    return 0.0, 0, 0, _COST_SOURCE_NONE


def _write_dispatch_sidecar_for_result(
    cycle_dir: Path,
    *,
    stage: str,
    agent_name: str,
    agent_kind: Literal["fake", "real"],
    tier: str,
    cycle_num: int,
    started_mono: float,
    completed_mono: float,
    started_at: str,
    completed_at: str,
    exit_code: int,
    stream: StreamCostResult | None,
    stderr_excerpt: str | None,
    timed_out: bool = False,
    runtime_cost: tuple[float, int, int] | None = None,
    estimate: tuple[float, int] | None = None,
    resolved_cost: tuple[float, int, int, str] | None = None,
) -> None:
    latency_ms = int((completed_mono - started_mono) * 1000)
    if resolved_cost is not None:
        # Spec 064: opencode resolves its own per-call cost class (local vs
        # metered) before this point — use it verbatim so the sidecar carries the
        # right cost_source instead of the runtime/estimate dichotomy above.
        cost_usd, tokens_in, tokens_out, cost_source = resolved_cost
    else:
        cost_usd, tokens_in, tokens_out, cost_source = _resolve_cost(
            stream=stream,
            runtime_cost=runtime_cost,
            estimate=estimate,
            agent_name=agent_name,
            stage=stage,
            exit_code=exit_code,
            timed_out=timed_out,
        )
    # status: "ok" requires exit_code == 0 AND (for stream callers) a
    # terminal `result` event was observed. Stream callers pass a
    # ``StreamCostResult`` — its ``saw_result`` flag gates "ok". Non-stream
    # callers (codex / python / fake) pass ``stream=None``; for them
    # exit_code == 0 alone is sufficient because their CLIs don't emit a
    # mid-stream terminal envelope. ``timed_out=True`` always forces
    # "failed" regardless of exit_code.
    if timed_out:
        status: Literal["ok", "failed"] = "failed"
    elif stream is not None:
        status = "ok" if exit_code == 0 and stream.saw_result else "failed"
    else:
        status = "ok" if exit_code == 0 else "failed"
    sidecar_path = _allocate_sidecar_path(cycle_dir, stage)
    _emit_sidecar_v11(
        sidecar_path,
        stage=stage,
        agent=agent_name,
        agent_kind=agent_kind,
        tier=tier,
        status=status,
        exit_code=exit_code,
        cost_usd=cost_usd,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
        started_at=started_at,
        completed_at=completed_at,
        cycle=cycle_num,
        cost_source=cost_source,
        stderr_excerpt=stderr_excerpt,
    )


# ---------------------------------------------------------------------------
# Spec 047 v1 — HTTP/API dispatch (the single non-CLI branch).
#
# These helpers add ONE guarded HTTP path at the existing dispatch point; they
# do NOT introduce a parallel dispatcher (FR-008/009). A local Ollama server is
# the v1 backend; the OpenAI-compatible and Ollama-native response shapes are
# both parsed so ``api_path`` can point at either endpoint.
# ---------------------------------------------------------------------------


def _is_http_executor(executor: dict[str, Any]) -> bool:
    """True when this executor must be dispatched over HTTP, not a CLI subprocess.

    Triggered by ``type: api`` (the ``communication.mode: http`` profile) OR by a
    ``runtime`` in ``_HTTP_RUNTIMES``. ``type: script`` always wins as non-HTTP.
    """
    if not isinstance(executor, dict):
        return False
    etype = str(executor.get("type") or "").lower()
    if etype == "script":
        return False
    if etype == "api":
        return True
    return str(executor.get("runtime") or "").lower() in _HTTP_RUNTIMES


def _http_endpoint(executor: dict[str, Any]) -> str:
    """Resolve ``{base_url}{api_path}``.

    ``OLLAMA_BASE_URL`` overrides ``base_url`` when set (run-time override without
    editing the profile); ``api_path`` defaults to the OpenAI-compatible
    ``/v1/chat/completions``. The join collapses to a single slash.
    """
    base = (
        os.environ.get("OLLAMA_BASE_URL")
        or str(executor.get("base_url") or "")
        or "http://127.0.0.1:11434"
    )
    path = str(executor.get("api_path") or "/v1/chat/completions")
    return base.rstrip("/") + "/" + path.lstrip("/")


def _http_post_json(
    url: str, payload: dict[str, Any], *, timeout: float
) -> dict[str, Any]:
    """POST ``payload`` as JSON and return the decoded JSON response.

    Honours the ``OLLAMA_HTTP_FIXTURE`` file seam: when set, the file is returned
    verbatim and NO network call is made (the hermetic path for the CLI/subprocess
    tests). Raises ``OSError``/``urllib.error.URLError`` on a transport failure.
    """
    fixture = os.environ.get("OLLAMA_HTTP_FIXTURE")
    if fixture:
        with open(fixture, encoding="utf-8") as fh:
            return json.load(fh)
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed http(s) endpoint from settings.
        return json.loads(resp.read().decode("utf-8"))


def _parse_http_response(obj: dict[str, Any]) -> tuple[str, int, int]:
    """``(text, tokens_in, tokens_out)`` from either the OpenAI-compatible or the
    Ollama-native chat response shape."""
    if not isinstance(obj, dict):
        return "", 0, 0
    choices = obj.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else {}
        text = str((message or {}).get("content") or "")
        usage = obj.get("usage") or {}
        return (
            text,
            int(usage.get("prompt_tokens") or 0),
            int(usage.get("completion_tokens") or 0),
        )
    # Ollama-native ``/api/chat`` shape.
    message = obj.get("message") or {}
    text = str(message.get("content") or "") if isinstance(message, dict) else ""
    return (
        text,
        int(obj.get("prompt_eval_count") or 0),
        int(obj.get("eval_count") or 0),
    )


def _dispatch_http(
    executor: dict[str, Any], prompt: str, *, timeout_s: float
) -> tuple[str, int, int]:
    """One HTTP chat-completion round-trip → ``(text, tokens_in, tokens_out)``.

    Raises on a transport/parse error; the caller maps that to exit code 2.
    """
    url = _http_endpoint(executor)
    payload = {
        "model": str(executor.get("model") or ""),
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    obj = _http_post_json(url, payload, timeout=timeout_s)
    return _parse_http_response(obj)


def dispatch(
    stage: str,
    prompt: str,
    *,
    tier: str = "standard",
    agent: str | None = None,
    model: str | None = None,
    vault_dir: Path | None = None,
    cycle_dir: Path | None = None,
    timeout_s: int | None = None,
) -> AgentCallResult:
    """Run one LLM stage programmatically and optionally write a cost sidecar.

    Contract: ``specs/028-dispatch-telemetry/contracts/dispatch-protocol.contract.md``.
    """
    if vault_dir is None:
        if cycle_dir is None:
            raise ValueError("dispatch() requires vault_dir or cycle_dir")
        vault_dir = _vault_dir_from_cycle_dir(cycle_dir)

    _set_call_context(vault_dir, stage)
    settings = _apply_stage_model_override(_load_settings(vault_dir), stage, model)
    agent_name = _resolve_agent_name(agent, settings, stage)
    agent_kind = _detect_agent_kind(agent_name, vault_dir)
    executor = _executor_for_dispatch(settings, stage, agent_name)
    effective_timeout = int(timeout_s or executor.get("timeout_s") or 600)
    cycle_num = _parse_cycle_num(cycle_dir) if cycle_dir is not None else 1

    # ``started_at`` is captured here, BEFORE any subprocess work. Previously
    # we generated both start + end timestamps from a single
    # ``_sidecar_timestamps()`` call at completion time, hiding the real
    # start instant. ``_completed_at_for`` is called at every exit point.
    started_mono = time.monotonic()
    started_at = _started_at_for(agent_kind)
    stream: StreamCostResult | None = None
    stdout = ""
    stderr = ""
    exit_code = 0

    # Spec 047 v1: HTTP/API runtimes (Ollama) dispatch here, BEFORE the
    # streaming/CLI branches — they never build a CLI command. Local ⇒ TRUE $0
    # with REAL tokens from the API ``usage`` block ⇒ cost_source: runtime.
    if agent_kind == "real" and _is_http_executor(executor):
        try:
            stdout, tokens_in_http, tokens_out_http = _dispatch_http(
                executor, prompt, timeout_s=effective_timeout
            )
            exit_code = 0
        except Exception as exc:  # transport/parse failure → exit 2, honest $0.
            stdout = ""
            stderr = f"ollama http dispatch failed: {exc}"
            exit_code = 2
            tokens_in_http = tokens_out_http = 0
        completed_mono = time.monotonic()
        completed_at = _completed_at_for(agent_kind)
        latency_ms = int((completed_mono - started_mono) * 1000)
        runtime_cost = (
            (0.0, tokens_in_http, tokens_out_http) if exit_code == 0 else None
        )
        if cycle_dir is not None:
            _write_dispatch_sidecar_for_result(
                cycle_dir,
                stage=stage,
                agent_name=agent_name,
                agent_kind=agent_kind,
                tier=tier,
                cycle_num=cycle_num,
                started_mono=started_mono,
                completed_mono=completed_mono,
                started_at=started_at,
                completed_at=completed_at,
                exit_code=exit_code,
                stream=None,
                stderr_excerpt=stderr if exit_code != 0 else None,
                runtime_cost=runtime_cost,
            )
        return AgentCallResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            cost_usd=0.0,
            tokens_in=tokens_in_http,
            tokens_out=tokens_out_http,
            latency_ms=latency_ms,
        )

    # Spec 064 FR-015: opencode fails closed BEFORE spawning when its binary /
    # provider / creds aren't usable. Cached per process so the reachability
    # probe runs once (the first call gates the cycle), not per stage. On
    # failure a telemetry sidecar IS written when ``cycle_dir`` is provided
    # (parity with the FileNotFoundError / TimeoutExpired arms below) so the
    # cycle's agent-calls index never has an invisible failed stage.
    if agent_kind == "real" and agent_name == _OPENCODE:
        ok, reason = _opencode_preflight_cached(
            executor, local_providers=_resolve_local_providers(settings)
        )
        if not ok:
            completed_mono = time.monotonic()
            completed_at = _completed_at_for(agent_kind)
            stderr_excerpt = f"opencode preflight failed: {reason}"
            if cycle_dir is not None:
                _write_dispatch_sidecar_for_result(
                    cycle_dir,
                    stage=stage,
                    agent_name=agent_name,
                    agent_kind=agent_kind,
                    tier=tier,
                    cycle_num=cycle_num,
                    started_mono=started_mono,
                    completed_mono=completed_mono,
                    started_at=started_at,
                    completed_at=completed_at,
                    exit_code=2,
                    stream=None,
                    stderr_excerpt=stderr_excerpt,
                )
            return AgentCallResult(
                stdout="",
                stderr=stderr_excerpt,
                exit_code=2,
                cost_usd=0.0,
                tokens_in=0,
                tokens_out=0,
                latency_ms=int((completed_mono - started_mono) * 1000),
            )

    # Spec 052: claude AND cursor-agent stream NDJSON with a terminal result
    # event, so both take the streaming path (live text + usage capture).
    use_stream = agent_kind == "real" and agent_name in _STREAMING_AGENTS
    if use_stream:
        cmd = (
            _cursor_cmd_with_cost(executor, vault_dir)
            if agent_name == _CURSOR_AGENT
            else _claude_cmd_with_cost(executor)
        )
        live = StreamCostResult()
        stream = live

        def _on_stream_line(raw: str) -> None:
            line = raw.rstrip("\n")
            if not line:
                return
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                live.stdout_text += line + "\n"
                return
            _apply_stream_event(event, live)

        try:
            # The stream is consumed under ``_supervise_child``, not on this
            # thread. Reading stdout here made the read loop the clock: the
            # deadline was only looked at when the agent printed a line, so
            # an agent that went silent was never timed out. The prompt was
            # written and stderr left unread on the same thread, so an agent
            # that did not read its prompt, or that wrote more than a pipe's
            # worth of stderr, blocked the call for good.
            outcome = _supervise_child(
                cmd,
                input=prompt,
                timeout=effective_timeout,
                capture_stderr=True,
                on_stdout_line=_on_stream_line,
            )
        except FileNotFoundError:
            completed_mono = time.monotonic()
            completed_at = _completed_at_for(agent_kind)
            latency_ms = int((completed_mono - started_mono) * 1000)
            if cycle_dir is not None:
                _write_dispatch_sidecar_for_result(
                    cycle_dir,
                    stage=stage,
                    agent_name=agent_name,
                    agent_kind=agent_kind,
                    tier=tier,
                    cycle_num=cycle_num,
                    started_mono=started_mono,
                    completed_mono=completed_mono,
                    started_at=started_at,
                    completed_at=completed_at,
                    exit_code=2,
                    stream=None,
                    stderr_excerpt=f"runtime binary '{cmd[0]}' not found",
                )
            return AgentCallResult(
                stdout="",
                stderr=f"runtime binary '{cmd[0]}' not found",
                exit_code=2,
                latency_ms=latency_ms,
            )
        stdout = live.stdout_text
        if outcome.timed_out:
            # The agent's whole process group is already gone:
            # ``_supervise_child`` terminates it before returning.
            completed_mono = time.monotonic()
            completed_at = _completed_at_for(agent_kind)
            latency_ms = int((completed_mono - started_mono) * 1000)
            if cycle_dir is not None:
                _write_dispatch_sidecar_for_result(
                    cycle_dir,
                    stage=stage,
                    agent_name=agent_name,
                    agent_kind=agent_kind,
                    tier=tier,
                    cycle_num=cycle_num,
                    started_mono=started_mono,
                    completed_mono=completed_mono,
                    started_at=started_at,
                    completed_at=completed_at,
                    exit_code=2,
                    stream=stream,
                    stderr_excerpt="timed out",
                    timed_out=True,
                )
            return AgentCallResult(
                stdout=stdout,
                stderr="timed out",
                exit_code=2,
                cost_usd=live.cost_usd,
                tokens_in=live.tokens_in,
                tokens_out=live.tokens_out,
                latency_ms=latency_ms,
            )
        # The answer, once. A stream-json runtime says it twice: in its
        # assistant events and again as the terminal event's ``result``, which
        # is what it prints in plain ``--print`` mode and what every other
        # runtime hands back here. Prefer that; fall back to what was streamed
        # when the terminal event carries no text.
        stdout = live.result_text or live.stdout_text
        stderr = outcome.stderr or ""
        exit_code = int(outcome.returncode)
    else:
        cmd = _build_command(executor, vault_dir)
        try:
            # ``_run_in_session_with_timeout`` replaces ``subprocess.run``
            # so a timeout actually kills the whole process tree, not just
            # the direct child. See the module-level comment block on
            # spec 050.
            result = _run_in_session_with_timeout(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
            )
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            exit_code = int(result.returncode)
        except FileNotFoundError:
            completed_mono = time.monotonic()
            completed_at = _completed_at_for(agent_kind)
            latency_ms = int((completed_mono - started_mono) * 1000)
            if cycle_dir is not None:
                _write_dispatch_sidecar_for_result(
                    cycle_dir,
                    stage=stage,
                    agent_name=agent_name,
                    agent_kind=agent_kind,
                    tier=tier,
                    cycle_num=cycle_num,
                    started_mono=started_mono,
                    completed_mono=completed_mono,
                    started_at=started_at,
                    completed_at=completed_at,
                    exit_code=2,
                    stream=None,
                    stderr_excerpt=f"runtime binary '{cmd[0]}' not found",
                )
            return AgentCallResult(
                stdout="",
                stderr=f"runtime binary '{cmd[0]}' not found",
                exit_code=2,
                latency_ms=latency_ms,
            )
        except subprocess.TimeoutExpired:
            completed_mono = time.monotonic()
            completed_at = _completed_at_for(agent_kind)
            latency_ms = int((completed_mono - started_mono) * 1000)
            if cycle_dir is not None:
                _write_dispatch_sidecar_for_result(
                    cycle_dir,
                    stage=stage,
                    agent_name=agent_name,
                    agent_kind=agent_kind,
                    tier=tier,
                    cycle_num=cycle_num,
                    started_mono=started_mono,
                    completed_mono=completed_mono,
                    started_at=started_at,
                    completed_at=completed_at,
                    exit_code=2,
                    stream=None,
                    stderr_excerpt="timed out",
                    timed_out=True,
                )
            return AgentCallResult(
                stdout="",
                stderr="timed out",
                exit_code=2,
                latency_ms=latency_ms,
            )

    completed_mono = time.monotonic()
    completed_at = _completed_at_for(agent_kind)
    latency_ms = int((completed_mono - started_mono) * 1000)

    # Spec 028 rc3: for a real non-claude runtime (stream is None) that
    # completed, try to parse codex's own cost (A1); else fall back to the
    # spec-033 estimate (A2) so the sidecar never silently records $0
    # (FR-028B). Resolved once here and reused for both the sidecar and the
    # returned result so in-process callers see the same number.
    runtime_cost: tuple[float, int, int] | None = None
    estimate: tuple[float, int] | None = None
    opencode_resolved: tuple[float, int, int, str] | None = None
    if stream is None and agent_kind == "real" and exit_code == 0:
        if agent_name == _OPENCODE:
            # Spec 064: opencode emits NDJSON ``step_finish`` events on stdout.
            # The shared resolver classifies them (local / metered-real-dollar /
            # tokens-only / no-usage) into a FULL resolved cost so the sidecar
            # carries the right cost_source and never a silent $0 (FR-006/007).
            opencode_resolved = _resolve_opencode_cost(
                stdout,
                str(executor.get("model") or ""),
                lambda: _fallback_estimate(
                    vault_dir,
                    cycle_num=cycle_num,
                    stage=stage,
                    prompt_text=prompt,
                    agent=agent_name,
                    tier=tier,
                ),
                local_providers=_resolve_local_providers(settings),
            )
        else:
            runtime_cost = _codex_cost_from_output(stdout)
            if runtime_cost is None:
                estimate = _fallback_estimate(
                    vault_dir,
                    cycle_num=cycle_num,
                    stage=stage,
                    prompt_text=prompt,
                    agent=agent_name,
                    tier=tier,
                )
    elif (
        stream is not None
        and agent_name in _FLAT_RATE_AGENTS
        and agent_kind == "real"
        and exit_code == 0
    ):
        # Spec 052: cursor's REAL tokens are already in ``stream``; the dollar
        # is a flat-rate estimate. _resolve_cost merges them into
        # cost_source: runtime_tokens (real tokens, estimated dollar).
        estimate = _fallback_estimate(
            vault_dir,
            cycle_num=cycle_num,
            stage=stage,
            prompt_text=prompt,
            agent=agent_name,
            tier=tier,
        )

    if cycle_dir is not None:
        stderr_excerpt = stderr if exit_code != 0 and stderr else None
        _write_dispatch_sidecar_for_result(
            cycle_dir,
            stage=stage,
            agent_name=agent_name,
            agent_kind=agent_kind,
            tier=tier,
            cycle_num=cycle_num,
            started_mono=started_mono,
            completed_mono=completed_mono,
            started_at=started_at,
            completed_at=completed_at,
            exit_code=exit_code,
            stream=stream,
            stderr_excerpt=stderr_excerpt,
            runtime_cost=runtime_cost,
            estimate=estimate,
            resolved_cost=opencode_resolved,
        )

    # ``warn=False``: if no cost signal existed the sidecar writer already
    # emitted the single WARNING (or, headless, nobody needs a duplicate).
    if opencode_resolved is not None:
        cost_usd, tokens_in, tokens_out, _ = opencode_resolved
    else:
        cost_usd, tokens_in, tokens_out, _ = _resolve_cost(
            stream=stream,
            runtime_cost=runtime_cost,
            estimate=estimate,
            agent_name=agent_name,
            stage=stage,
            exit_code=exit_code,
            timed_out=False,
            warn=cycle_dir is None,
        )

    # Spec 064: opencode's stage output is its assistant TEXT, not the raw NDJSON
    # event stream — extract it so stdout-based consumers (verifier verdict,
    # benchmark scorers) get the answer. Cost was already resolved from the raw
    # NDJSON above. (Empty for pure tool-write turns, whose output is a file.)
    if agent_name == _OPENCODE:
        stdout = _extract_opencode_text(stdout)

    return AgentCallResult(
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        cost_usd=cost_usd,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
    )


def _write_cost_sidecar(path: Path, payload: dict[str, Any]) -> None:
    """Legacy alias — prefer ``_write_sidecar_v11`` for new writes."""
    _write_sidecar_v11(path, payload)


def _extract_text_from_event(event: dict[str, Any]) -> str:
    """Return any human-readable text inside a stream-json event.

    Claude's stream-json mixes assistant messages, tool calls, and a
    terminal `result` envelope. We forward only the bits a human would
    want to see live — assistant text content and the final result text
    — so the cost-capture path doesn't degrade the `tee`'d log into a
    wall of JSON.
    """
    etype = event.get("type")
    if etype == "assistant":
        message = event.get("message") or {}
        content = message.get("content") or []
        chunks: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text") or ""
                if text:
                    chunks.append(text)
        return "".join(chunks)
    if etype == "result":
        return str(event.get("result") or "")
    return ""


def _run_claude_with_cost(
    cmd: list[str],
    prompt: str,
    timeout_s: int,
    cost_sidecar: Path,
    *,
    stage: str,
    tier: str,
    cycle: int,
    vault_dir: Path,
    batch_index: int | None = None,
    topic_count: int | None = None,
    agent: str = "claude",
    output_file: Path | None = None,
) -> int:
    """Run a stream-json runtime and write sidecar v1.1 (the CLI/run() path).

    Serves claude AND cursor-agent (spec 052) — ``agent`` selects the runtime.
    Stream events are parsed incrementally as they arrive — previously the
    function buffered every line into ``captured_lines`` and then re-parsed
    the entire list at the end, which doubled memory for long sessions.
    The wait itself belongs to ``_supervise_child``: the timeout fires
    whether or not the agent is printing (a deadline checked per stdout line
    never fired for an agent that had gone silent), and the agent's process
    group is gone when it returns.

    Cost provenance: claude's terminal event carries ``total_cost_usd``
    (``cost_source: runtime``); cursor-agent is flat-rate (real tokens, no
    dollar) so the dollar comes from the spec-033 estimator and the source is
    ``runtime_tokens``.

    ``output_file`` receives the agent's answer after an exit 0, as on every
    other runtime. The agent's stdout is an event stream here, so the answer
    is the terminal event's ``result`` text — what the runtime prints in plain
    ``--print`` mode — or, when that is empty, the text it streamed before.
    """
    started_mono = time.monotonic()
    agent_kind = _detect_agent_kind(agent, vault_dir)
    started_at = _started_at_for(agent_kind)

    stream = StreamCostResult()
    # The streamed text is only kept when somebody asked for it in a file.
    keep_text = output_file is not None

    def _forward_stream_line(raw: str) -> None:
        line = raw.rstrip("\n")
        if not line:
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            if keep_text:
                stream.stdout_text += line + "\n"
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
            return
        text = _apply_stream_event(event, stream, capture_text=keep_text)
        if text:
            sys.stdout.write(text)
            if not text.endswith("\n"):
                sys.stdout.write("\n")
            sys.stdout.flush()

    # stderr is not captured: the agent inherits ours, so there is no pipe
    # of it to fill.
    outcome = _supervise_child(
        cmd, input=prompt, timeout=timeout_s, on_stdout_line=_forward_stream_line
    )
    timed_out = outcome.timed_out
    rc = 2 if timed_out else outcome.returncode
    completed_mono = time.monotonic()
    completed_at = _completed_at_for(agent_kind)
    path_batch, _ = _batch_fields_from_path(cost_sidecar)
    bi = batch_index if batch_index is not None else path_batch
    # status: "ok" requires exit 0 AND not timed-out AND a terminal stream
    # result event was observed. Pytest's "exit 0" alone is unreliable —
    # claude can exit cleanly mid-stream without emitting the terminal
    # envelope (network blip, truncated tool output), in which case the
    # cost data we report is stale / zero.
    ok = rc == 0 and not timed_out and stream.saw_result
    status: Literal["ok", "failed"] = "ok" if ok else "failed"
    # Cost provenance (spec 052): claude reports a real dollar in-stream; cursor
    # is flat-rate (real tokens, estimated dollar ⇒ cost_source runtime_tokens).
    cost_usd = stream.cost_usd
    cost_source = _COST_SOURCE_RUNTIME
    if agent in _FLAT_RATE_AGENTS:
        est = _fallback_estimate(
            vault_dir,
            cycle_num=cycle,
            stage=stage,
            prompt_text=prompt,
            agent=agent,
            tier=tier,
        )
        cost_usd = est[0] if est is not None else 0.0
        cost_source = _COST_SOURCE_RUNTIME_TOKENS
    payload = _build_sidecar_v11_payload(
        stage=stage,
        agent=agent,
        agent_kind=agent_kind,
        tier=tier,
        status=status,
        cost_source=cost_source,
        exit_code=int(rc),
        cost_usd=cost_usd,
        tokens_in=stream.tokens_in,
        tokens_out=stream.tokens_out,
        latency_ms=int((completed_mono - started_mono) * 1000),
        started_at=started_at,
        completed_at=completed_at,
        cycle=cycle,
        batch_index=bi,
        topic_count=topic_count,
        duration_ms=stream.duration_ms,
        timed_out=timed_out if timed_out else None,
    )
    _write_sidecar_v11(cost_sidecar, payload)
    if timed_out:
        raise subprocess.TimeoutExpired(cmd, timeout_s)
    if output_file is not None and rc == 0:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            output_file.write_text(
                stream.result_text or stream.stdout_text, encoding="utf-8"
            )
        except OSError as e:
            print(
                f"WARN: failed to write output file {output_file}: {e}",
                file=sys.stderr,
            )
    return int(rc)


def _cycle_from_sidecar_path(cost_sidecar: Path) -> int:
    for parent in cost_sidecar.parents:
        m = re.search(r"cycle-(\d+)", parent.name)
        if m:
            return int(m.group(1))
    return 1


def _stage_tier(settings: dict[str, Any], stage: str) -> str:
    stages = settings.get("stages") or {}
    stage_cfg = stages.get(stage) if isinstance(stages, dict) else None
    if isinstance(stage_cfg, dict) and stage_cfg.get("tier"):
        return str(stage_cfg["tier"])
    return "standard"


def _run_http(
    vault_dir: Path,
    stage: str,
    executor: dict[str, Any],
    prompt: str,
    tier: str,
    *,
    cost_sidecar: Path | None,
    output_file: Path | None,
    batch_index: int | None,
    topic_count: int | None,
) -> int:
    """Spec 047 v1 — the CLI ``run()`` path for an HTTP/API runtime (Ollama).

    Mirrors the non-stream CLI tail (sidecar + output file) but dispatches over
    HTTP and never reaches ``_build_command``. Local ⇒ ``cost_usd: 0.0`` with
    REAL tokens ⇒ ``cost_source: runtime``.
    """
    agent_name = str(executor.get("runtime") or _OLLAMA)
    # HTTP path => agent_kind is ALWAYS "real": the fake-agent test shim is a
    # separate agent_call.py with no HTTP code, so it can never reach here.
    # (Spec 047 v1: the _detect_agent_kind vault-shim heuristic used to
    # mislabel HTTP calls "fake" — with 2000-01-01 sentinel timestamps and
    # latency_ms=0 — whenever the surrounding vault happened to carry a fake
    # shim, even though the dispatch itself was a real network call.)
    agent_kind: Literal["fake", "real"] = "real"
    cycle_num = _cycle_from_sidecar_path(cost_sidecar) if cost_sidecar else 1
    timeout_s = int(executor.get("timeout_s") or 3600)
    started_mono = time.monotonic()
    started_at = _started_at_for(agent_kind)
    try:
        stdout, tokens_in, tokens_out = _dispatch_http(
            executor, prompt, timeout_s=timeout_s
        )
        exit_code = 0
    except Exception as exc:
        print(f"ERROR: ollama http dispatch failed: {exc}", file=sys.stderr)
        stdout, tokens_in, tokens_out, exit_code = "", 0, 0, 2
    completed_at = _completed_at_for(agent_kind)
    latency_ms = int((time.monotonic() - started_mono) * 1000)
    if cost_sidecar is not None:
        bi, tc = batch_index, topic_count
        if bi is None:
            bi, _ = _batch_fields_from_path(cost_sidecar)
        _emit_sidecar_v11(
            cost_sidecar,
            stage=stage,
            agent=agent_name,
            agent_kind=agent_kind,
            tier=tier,
            status="ok" if exit_code == 0 else "failed",
            exit_code=exit_code,
            cost_usd=0.0,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            started_at=started_at,
            completed_at=completed_at,
            cycle=cycle_num,
            cost_source=_COST_SOURCE_RUNTIME,
            batch_index=bi,
            topic_count=tc,
        )
    if output_file is not None and exit_code == 0:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            output_file.write_text(stdout, encoding="utf-8")
        except OSError as e:
            print(
                f"WARN: failed to write output file {output_file}: {e}",
                file=sys.stderr,
            )
    return exit_code


def run(
    vault_dir: Path,
    stage: str,
    prompt_file: Path | None,
    cost_sidecar: Path | None = None,
    output_file: Path | None = None,
    *,
    batch_index: int | None = None,
    topic_count: int | None = None,
) -> int:
    _set_call_context(vault_dir, stage)
    settings = _load_settings(vault_dir)
    executor = _resolve_executor(settings, stage)
    runtime = str(executor.get("runtime") or "")
    prompt = _read_prompt(prompt_file)
    tier = _stage_tier(settings, stage)

    # Spec 047 v1: HTTP/API runtimes (Ollama) dispatch here, before any CLI
    # command construction (``_build_command`` would reject the unknown runtime).
    if _is_http_executor(executor):
        return _run_http(
            vault_dir,
            stage,
            executor,
            prompt,
            tier,
            cost_sidecar=cost_sidecar,
            output_file=output_file,
            batch_index=batch_index,
            topic_count=topic_count,
        )

    # Spec 064 FR-015: opencode fails closed before spawning (binary / provider /
    # creds). Exit 2 with no sidecar is the "unavailable" signal (a benchmark cell
    # then reports skipped, not a misleading $0).
    if runtime == _OPENCODE and _detect_agent_kind(runtime, vault_dir) == "real":
        ok, reason = _opencode_preflight_cached(
            executor, local_providers=_resolve_local_providers(settings)
        )
        if not ok:
            print(f"ERROR: opencode preflight failed: {reason}", file=sys.stderr)
            return 2

    capture = cost_sidecar is not None and executor.get("type") != "script"
    # Spec 052: claude + cursor-agent both take the streaming-cost path.
    stream_capture = capture and runtime in _STREAMING_AGENTS

    if stream_capture and runtime == _CURSOR_AGENT:
        cmd = _cursor_cmd_with_cost(executor, vault_dir)
    elif stream_capture:
        cmd = _claude_cmd_with_cost(executor)
    else:
        cmd = _build_command(executor, vault_dir)

    if os.environ.get("AGENT_CALL_DEBUG") == "1":
        print(
            f"[agent_call] stage={stage} runtime={executor.get('runtime')} "
            f"model={executor.get('model')} cmd={cmd[0]}…"
            + (f" cost_sidecar={cost_sidecar}" if cost_sidecar else ""),
            file=sys.stderr,
        )

    cycle_num = _cycle_from_sidecar_path(cost_sidecar) if cost_sidecar else 1

    try:
        if stream_capture:
            assert cost_sidecar is not None
            rc = _run_claude_with_cost(
                cmd,
                prompt,
                int(executor.get("timeout_s") or 3600),
                cost_sidecar,
                stage=stage,
                tier=tier,
                cycle=cycle_num,
                vault_dir=vault_dir,
                batch_index=batch_index,
                topic_count=topic_count,
                agent=runtime,
                output_file=output_file,
            )
            return int(rc)
        capture_output = output_file is not None
        # A non-claude runtime reports its cost on stdout (opencode's
        # ``step_finish`` events, a codex cost line). With a sidecar to fill
        # the stream has to be read for it even when no output file was asked
        # for — and passed through, because our stdout is the caller's only
        # record of it. Same condition as the cost parse below.
        tee_stdout = (
            cost_sidecar is not None
            and runtime != "claude"
            and _detect_agent_kind(runtime or "unknown", vault_dir) == "real"
        )
        # ``_run_in_session_with_timeout`` replaces ``subprocess.run`` so a
        # timeout actually terminates the entire process group, not just the
        # direct child. Previously a timed-out codex would leave its sandbox
        # + MCP grandchildren holding the stdout pipe, and the next
        # ``communicate()`` blocked for hours until the OS reaped them. See
        # spec 050.
        result = _run_in_session_with_timeout(
            cmd,
            input=prompt,
            text=True,
            timeout=int(executor.get("timeout_s") or 3600),
            capture_output=capture_output,
            tee_stdout=tee_stdout,
        )
    except FileNotFoundError:
        # Binary missing on PATH — give a pointer instead of a raw trace.
        print(
            f"ERROR: runtime binary '{cmd[0]}' not found on PATH.\n"
            "Install it, or set CLAUDE_BIN / CODEX_BIN / CURSOR_BIN to the "
            "binary path.",
            file=sys.stderr,
        )
        return 2
    except subprocess.TimeoutExpired:
        print(
            f"ERROR: stage '{stage}' exceeded timeout {executor.get('timeout_s')}s",
            file=sys.stderr,
        )
        if cost_sidecar is not None and not stream_capture:
            # The streaming path has written its own. Exit 2 with no sidecar
            # means "runtime unavailable" to our callers; a call that ran and
            # was killed is not that, and must leave a record. Nothing was
            # measured, hence ``none``.
            agent_kind = _detect_agent_kind(runtime or "unknown", vault_dir)
            bi = batch_index
            if bi is None:
                bi, _ = _batch_fields_from_path(cost_sidecar)
            _emit_sidecar_v11(
                cost_sidecar,
                stage=stage,
                agent=runtime or "unknown",
                agent_kind=agent_kind,
                tier=tier,
                status="failed",
                exit_code=2,
                cost_usd=0.0,
                tokens_in=0,
                tokens_out=0,
                latency_ms=0,
                started_at=_started_at_for(agent_kind),
                completed_at=_completed_at_for(agent_kind),
                cycle=cycle_num,
                cost_source=_COST_SOURCE_NONE,
                stderr_excerpt="timed out",
                batch_index=bi,
                topic_count=topic_count,
                timed_out=True,
            )
        return 2
    if cost_sidecar is not None:
        agent_kind = _detect_agent_kind(runtime or "unknown", vault_dir)
        # Non-stream runtimes (codex / python / fake) execute via
        # subprocess.run which already returned by this point. We capture
        # started_at + completed_at separately so the fake-agent sentinel
        # pair ("2000-01-01T00:00:00Z" / "...:01Z") still differs across
        # the two timestamps (previously both came from the same call,
        # making the wall-clock window appear zero-width).
        started_at = _started_at_for(agent_kind)
        completed_at = _completed_at_for(agent_kind)
        bi, tc = batch_index, topic_count
        if bi is None:
            bi, _ = _batch_fields_from_path(cost_sidecar)
        status: Literal["ok", "failed"] = "ok" if result.returncode == 0 else "failed"
        # Spec 028 rc3: a real non-claude CLI dispatch must not record a silent
        # $0 (FR-028B). Try codex's own cost (A1); else the spec-033 estimate
        # (A2). Fake/claude paths keep the prior 0.0/"runtime" shape.
        runtime_name = runtime or "unknown"
        cli_cost, cli_tin, cli_tout = 0.0, 0, 0
        cli_source = _COST_SOURCE_RUNTIME
        if (
            agent_kind == "real"
            and runtime_name == _OPENCODE
            and result.returncode == 0
        ):
            # Spec 064: opencode cost on the CLI path too (the benchmark uses
            # run(), not dispatch()) — honest cost_source, never a silent $0.
            cli_cost, cli_tin, cli_tout, cli_source = _resolve_opencode_cost(
                getattr(result, "stdout", "") or "",
                str(executor.get("model") or ""),
                lambda: _fallback_estimate(
                    vault_dir,
                    cycle_num=cycle_num,
                    stage=stage,
                    prompt_text=prompt,
                    agent=runtime_name,
                    tier=tier,
                ),
                local_providers=_resolve_local_providers(settings),
            )
        elif (
            agent_kind == "real" and runtime_name != "claude" and result.returncode == 0
        ):
            parsed = _codex_cost_from_output(getattr(result, "stdout", "") or "")
            if parsed is not None:
                cli_cost, cli_tin, cli_tout = parsed
                cli_source = _COST_SOURCE_RUNTIME
            else:
                est = _fallback_estimate(
                    vault_dir,
                    cycle_num=cycle_num,
                    stage=stage,
                    prompt_text=prompt,
                    agent=runtime_name,
                    tier=tier,
                )
                if est is not None:
                    cli_cost, cli_tin, cli_tout = est[0], est[1], 0
                    cli_source = _COST_SOURCE_ESTIMATED
                else:
                    cli_source = _COST_SOURCE_NONE
        _emit_sidecar_v11(
            cost_sidecar,
            stage=stage,
            agent=runtime_name,
            agent_kind=agent_kind,
            tier=tier,
            status=status,
            exit_code=int(result.returncode),
            cost_usd=cli_cost,
            tokens_in=cli_tin,
            tokens_out=cli_tout,
            latency_ms=0,
            started_at=started_at,
            completed_at=completed_at,
            cycle=cycle_num,
            cost_source=cli_source,
            batch_index=bi,
            topic_count=tc,
        )
    if output_file is not None and result.returncode == 0:
        # Spec 064: write opencode's extracted assistant text (not the raw NDJSON
        # event stream) so the stage output / benchmark scorer gets the answer.
        out_text = (
            _extract_opencode_text(result.stdout or "")
            if runtime == _OPENCODE
            else (result.stdout or "")
        )
        output_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            output_file.write_text(out_text, encoding="utf-8")
        except OSError as e:
            print(
                f"WARN: failed to write output file {output_file}: {e}",
                file=sys.stderr,
            )
    return int(result.returncode)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dispatch a pipeline stage to the runtime picked in settings.yaml.",
    )
    parser.add_argument("--vault", required=True, type=Path, help="Vault directory.")
    parser.add_argument(
        "--stage",
        required=True,
        help="Stage name (e.g. 'scout', 'dfs_prompt_gen', 'note_writer'). "
        "Looked up under 'stages.<name>' in settings.yaml; falls back to "
        "default_executor when absent.",
    )
    parser.add_argument(
        "--prompt-file",
        type=Path,
        default=None,
        help="Path to the rendered prompt. If omitted, prompt is read from stdin.",
    )
    parser.add_argument(
        "--cost-sidecar",
        type=Path,
        default=None,
        help=(
            "Optional path where this invocation's cost data is written as "
            "JSON ({cost_usd, input_tokens, output_tokens, ...}). When set, "
            "the claude runtime is switched to stream-json so the wrapper "
            "can capture the final 'result' event. Other runtimes write a "
            "sentinel sidecar (cost_usd=0) for symmetric downstream handling."
        ),
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        default=None,
        dest="output_file",
        help=(
            "Optional path where the agent's stdout is written as UTF-8 text "
            "after a successful run (exit code 0). Absent by default — "
            "behaviour is unchanged when omitted. Used by verifier.py to read "
            "structured JSON output from the agent without parsing stdout."
        ),
    )
    parser.add_argument(
        "--batch-index",
        type=int,
        default=None,
        help="1-indexed batch number for per-batch sidecars (note_writer).",
    )
    parser.add_argument(
        "--topic-count",
        type=int,
        default=None,
        help="Topics processed in this batch (optional batch discriminator).",
    )
    args = parser.parse_args(argv)
    try:
        return run(
            args.vault,
            args.stage,
            args.prompt_file,
            args.cost_sidecar,
            args.output_file,
            batch_index=args.batch_index,
            topic_count=args.topic_count,
        )
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


class _Terminated(BaseException):
    """We were told to stop (SIGTERM). Unwinds the main thread as Ctrl+C does."""

    def __init__(self, signum: int) -> None:
        super().__init__(signum)
        self.signum = signum


def _run_as_script(argv: list[str] | None = None) -> int:
    """``main()`` for the process that IS the dispatcher: SIGTERM stops the agent.

    The runtime child lives in a session of its own (``_popen_session``), so a
    SIGTERM sent to this process, or to its process group, never reaches it.
    Python's default for SIGTERM is to die on the spot, without running a
    single ``finally``: a stage timeout in the pipeline killed this wrapper
    and left the agent running — spending, and writing into the vault.

    Here SIGTERM unwinds the main thread instead, the way SIGINT already
    does, so ``_supervise_child`` terminates the child's process group on the
    way out. We then die of that same signal: to whoever sent it, the exit
    status is what it always was.

    ``main()`` and ``dispatch()`` do not install this themselves. Both also
    run inside a host process (the runner, a test) whose signal handling is
    not ours to replace.
    """
    unwinding = False

    def _on_sigterm(signum: int, _frame: Any) -> None:
        nonlocal unwinding
        if unwinding:
            return  # a second signal must not cut the cleanup short
        unwinding = True
        raise _Terminated(signum)

    signal.signal(signal.SIGTERM, _on_sigterm)
    try:
        return main(argv)
    except _Terminated as stop:
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()
            except (OSError, ValueError):
                pass
        signal.signal(stop.signum, signal.SIG_DFL)
        os.kill(os.getpid(), stop.signum)
        return 128 + stop.signum  # only if the signal is somehow not delivered


if __name__ == "__main__":
    sys.exit(_run_as_script())
