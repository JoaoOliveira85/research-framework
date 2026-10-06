"""Subprocess-isolated module extractor invocation (research R2)."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import IO, Any

from research_framework.observability import current_bridge_writer, start_capture
from research_framework.pipeline.process_tree import (
    popen_session,
    terminate_process_tree,
)
from research_framework.pipeline.verifier import _extract_json_blob

from .discovery import ModuleManifest
from .signal import SignalPayload

_HEARTBEAT_POLL_SECONDS = 30
_HEARTBEAT_STALL_WARN_SECONDS = 60
_HEARTBEAT_HARD_TIMEOUT_SECONDS = 600
#: How long a pipe reader gets to reach EOF once the extractor's process group
#: has been terminated. Only a process that left the group can still be
#: holding the pipe by then, and nothing can kill that one (``process_tree``),
#: so the read is given up on instead of waited for.
_PIPE_DRAIN_SECONDS = 5.0


class ExtractorError(Exception):
    """Extractor subprocess failed."""

    def __init__(self, message: str, *, partial: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.partial = partial


def salvage_partial_json(text: str) -> dict[str, Any] | None:
    """Recover partial JSON from truncated stdout (D9 salvage)."""
    if not text or not text.strip():
        return None
    blob = _extract_json_blob(text)
    if blob is not None:
        return blob
    stripped = text.strip()
    for end in range(len(stripped), 0, -1):
        chunk = stripped[:end].rstrip(", \n\r\t")
        if not chunk.startswith("{"):
            continue
        try:
            data = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def _status_file_path(module_dir: Path, source_id: str) -> Path:
    safe = source_id.replace("/", "_")[:80]
    return module_dir / f".extract-status-{safe}.json"


def _read_heartbeat_age(status_path: Path) -> float | None:
    if not status_path.is_file():
        return None
    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
        updated = float(data.get("updated_at", 0))
        return time.time() - updated
    except (json.JSONDecodeError, TypeError, ValueError):
        return _HEARTBEAT_STALL_WARN_SECONDS + 1


def _bridge_source_label(source_id: str) -> str:
    """``source_id`` in a form the ``bridge.log`` header line can carry.

    The header is one comma-separated line, so the format contract forbids a
    comma or a newline in the source field and ``BridgeLogWriter`` raises on
    either. A source id is whatever ``sources.yaml`` says — a URL, a path, a
    name — and both are legal there. They are percent-encoded for the log
    rather than refused: a log label must not decide whether a source can be
    extracted.
    """
    label = source_id or "default"
    for char, escaped in ((",", "%2C"), ("\n", "%0A"), ("\r", "%0D")):
        label = label.replace(char, escaped)
    return label


def _bridge_exit_code(returncode: int) -> int:
    """``returncode`` as the ``bridge.log`` footer's ``exit:`` field takes it.

    ``Popen`` reports death by signal N as ``-N``. The footer carries a Unix
    exit code (0-255) and ``BridgeLogWriter`` raises on a negative one, so a
    signal death is written the way a shell reports it: ``128 + N``.
    """
    return 128 - returncode if returncode < 0 else returncode


def _drain_pipe(stream: IO[str] | None, into: list[str]) -> threading.Thread:
    """Read ``stream`` to EOF on a thread of its own, line by line into ``into``.

    A pipe nobody reads fills (64 KiB) and blocks the process writing to it.
    Polling for the extractor's exit and reading its pipes afterwards therefore
    deadlocks on any output larger than that: it cannot exit until it is read.
    """

    def _read() -> None:
        if stream is None:
            return
        try:
            for line in stream:
                into.append(line)
        except (OSError, ValueError):
            return  # closed under us

    thread = threading.Thread(target=_read, name="extractor-pipe", daemon=True)
    thread.start()
    return thread


def invoke_extractor(
    vault_dir: Path,
    manifest: ModuleManifest,
    *,
    command: str,
    stdin_payload: dict[str, Any],
    timeout_seconds: int | None = None,
    source_id: str = "",
) -> dict[str, Any]:
    """Spawn module ``extractor.py`` with JSON stdin/stdout contract."""
    module_dir = vault_dir / "modules" / manifest.name
    script = module_dir / manifest.entry_point
    if not script.is_file():
        raise ExtractorError(f"entry_point missing: {script}")
    timeout = timeout_seconds or manifest.extraction_timeout_seconds
    if timeout <= 0:
        timeout = _HEARTBEAT_HARD_TIMEOUT_SECONDS
    status_path = _status_file_path(module_dir, source_id or "default")
    start = time.monotonic()
    # ``popen_session`` adds ``start_new_session=True`` so the extractor
    # becomes its own process-group leader. This lets ``terminate_process_tree``
    # below kill ALL descendants (e.g. yt-dlp forks, headless browsers) on
    # timeout instead of just the direct python child. See spec 050.
    # bufsize=1 gives line-buffered text-mode pipes per spec 048 FR-007
    # so the capture thread can stream stderr into bridge.log in real time.
    proc = popen_session(
        [sys.executable, str(script), command],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        cwd=str(module_dir),
    )
    try:
        return _drive_extractor(
            proc,
            manifest,
            stdin_payload=stdin_payload,
            source_id=source_id,
            timeout=timeout,
            status_path=status_path,
            start=start,
        )
    finally:
        # Every way out, an exception on our side included: nothing the
        # extractor started may outlive the call. A no-op once the group is
        # empty, which it is on the paths below that already terminated it.
        terminate_process_tree(proc)


def _drive_extractor(
    proc: subprocess.Popen[str],
    manifest: ModuleManifest,
    *,
    stdin_payload: dict[str, Any],
    source_id: str,
    timeout: float,
    status_path: Path,
    start: float,
) -> dict[str, Any]:
    """Feed, watch and collect one spawned extractor (see ``invoke_extractor``)."""
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(stdin_payload))
    proc.stdin.close()

    # stdout is read while the extractor runs, not after it has exited.
    stdout_chunks: list[str] = []
    stdout_thread = _drain_pipe(proc.stdout, stdout_chunks)

    def _stdout_so_far() -> str:
        """What the extractor printed. Bounded: EOF needs every holder of the
        pipe gone, and one that left the process group cannot be killed."""
        stdout_thread.join(timeout=_PIPE_DRAIN_SECONDS)
        return "".join(list(stdout_chunks))

    # Spec 048: if a per-cycle BridgeLogWriter is active in the context,
    # start a daemon thread that drains proc.stderr line-by-line into
    # bridge.log while also accumulating the raw lines into ``transcript``
    # so the legacy ExtractorError message body still has stderr to show.
    # Defensive ``.closed`` check: even though ``publish_bridge_writer``
    # resets the ContextVar on cycle exit, a buggy caller could push a
    # closed writer; we'd rather silently fall back to the legacy path
    # than crash the extractor invocation. The cycle_runner regression
    # path is guarded by ``test_extractor_dispatch_emits_full_framing``.
    bridge_writer = current_bridge_writer.get()
    if bridge_writer is not None and bridge_writer.closed:
        bridge_writer = None
    stderr_transcript: list[str] = []
    capture_thread = None
    stderr_thread = None
    if bridge_writer is None:
        stderr_thread = _drain_pipe(proc.stderr, stderr_transcript)
    else:
        bridge_writer.start_extractor(
            module=manifest.name,
            source=_bridge_source_label(source_id),
            pid=proc.pid,
        )
        capture_thread = start_capture(
            proc,
            module=manifest.name,
            source_id=source_id or "default",
            writer=bridge_writer,
            transcript=stderr_transcript,
        )

    def _close_bridge_killed(reason: str) -> None:
        """Drain remaining stderr, then write the KILLED footer (FR-008)."""
        if bridge_writer is None:
            return
        if capture_thread is not None:
            capture_thread.join(timeout=2.0)
        bridge_writer.end_extractor_killed(
            reason=reason,
            duration_s=time.monotonic() - start,
        )

    last_warn = start
    poll_interval = 0.1
    while proc.poll() is None:
        elapsed = time.monotonic() - start
        if elapsed >= timeout:
            # Spec 050: signal the entire process tree, not just the direct
            # child. yt-dlp / headless browsers spawned by the extractor
            # would otherwise keep stdout open and the read below would
            # block forever after the kill.
            terminate_process_tree(proc)
            _close_bridge_killed("wall-clock cap")
            raise ExtractorError(
                f"extractor exceeded {timeout}s wall clock",
                partial=salvage_partial_json(_stdout_so_far()),
            )
        age = _read_heartbeat_age(status_path)
        if age is not None:
            if age >= _HEARTBEAT_STALL_WARN_SECONDS:
                if time.monotonic() - last_warn >= _HEARTBEAT_STALL_WARN_SECONDS:
                    last_warn = time.monotonic()
            if age >= _HEARTBEAT_HARD_TIMEOUT_SECONDS:
                terminate_process_tree(proc)
                _close_bridge_killed("wall-clock cap")
                raise ExtractorError(
                    "extractor heartbeat hard timeout",
                    partial=salvage_partial_json(_stdout_so_far()),
                )
            time.sleep(_HEARTBEAT_POLL_SECONDS)
        else:
            if elapsed >= _HEARTBEAT_HARD_TIMEOUT_SECONDS:
                terminate_process_tree(proc)
                _close_bridge_killed("wall-clock cap")
                raise ExtractorError(
                    "extractor heartbeat hard timeout",
                    partial=salvage_partial_json(_stdout_so_far()),
                )
            time.sleep(poll_interval)

    # The extractor has exited; what it forked may not have, and would hold
    # the pipes open for as long as it lives (``process_tree``: the group
    # outlives its leader). Terminate the group, then collect.
    terminate_process_tree(proc)
    stdout = _stdout_so_far()

    # Wait for the capture thread to finish draining before computing the
    # stderr text and writing the success footer; otherwise the footer
    # could land before the final body lines.
    if capture_thread is not None:
        capture_thread.join(timeout=5.0)
    if stderr_thread is not None:
        stderr_thread.join(timeout=_PIPE_DRAIN_SECONDS)
    stderr = "".join(list(stderr_transcript))

    if proc.returncode != 0:
        partial = salvage_partial_json(stdout)
        if bridge_writer is not None:
            bridge_writer.end_extractor(
                exit_code=_bridge_exit_code(proc.returncode),
                duration_s=time.monotonic() - start,
                payload_status="error",
            )
        raise ExtractorError(
            f"extractor exited {proc.returncode}: {stderr.strip()}",
            partial=partial,
        )
    data = _parse_extractor_stdout(stdout)
    if data is None:
        partial = salvage_partial_json(stdout)
        if bridge_writer is not None:
            bridge_writer.end_extractor(
                exit_code=proc.returncode,
                duration_s=time.monotonic() - start,
                payload_status="error",
            )
        raise ExtractorError(
            "invalid extractor stdout JSON",
            partial=partial,
        )
    if bridge_writer is not None:
        verdict = data.get("verdict") if isinstance(data, dict) else None
        payload_status = verdict if verdict in ("ok", "empty", "error") else "ok"
        bridge_writer.end_extractor(
            exit_code=proc.returncode,
            duration_s=time.monotonic() - start,
            payload_status=payload_status,
        )
    return data


def _parse_extractor_stdout(stdout: str) -> dict[str, Any] | None:
    blob = _extract_json_blob(stdout)
    if blob is not None:
        return blob
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def get_source_version(
    vault_dir: Path,
    manifest: ModuleManifest,
    source: dict[str, Any],
) -> str:
    data = invoke_extractor(
        vault_dir,
        manifest,
        command="get_source_version",
        stdin_payload={"source": source},
        source_id=str(source.get("path") or source.get("url") or "version"),
    )
    version = data.get("source_version")
    if not version:
        raise ExtractorError("get_source_version missing source_version")
    return str(version)


def extract_source(
    vault_dir: Path,
    manifest: ModuleManifest,
    *,
    source: dict[str, Any],
    source_id: str,
    bridge_version: str,
) -> SignalPayload:
    data = invoke_extractor(
        vault_dir,
        manifest,
        command="extract",
        stdin_payload={"source": source, "source_id": source_id},
        source_id=source_id,
    )
    payload = SignalPayload.from_dict(data)
    payload.module = manifest.name
    payload.source_id = source_id
    payload.bridge_version = bridge_version
    return payload


def partial_to_signal(
    partial: dict[str, Any],
    *,
    manifest: ModuleManifest,
    source_id: str,
    bridge_version: str,
) -> SignalPayload:
    data = dict(partial)
    data.setdefault("module", manifest.name)
    data.setdefault("source_id", source_id)
    data.setdefault("source_version", data.get("source_version", "unknown"))
    data.setdefault("bridge_version", bridge_version)
    data.setdefault("extracted_at", data.get("extracted_at", ""))
    data["verdict"] = "error"
    data["partial"] = True
    data.setdefault("truncated", False)
    data.setdefault("facts", {})
    data.setdefault("notable", [])
    return SignalPayload.from_dict(data)
