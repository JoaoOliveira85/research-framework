"""Regression tests for the v0.2.23 streaming + heartbeat logging redesign
in :func:`research_framework.pipeline.cycle_runner._run_script`.

Background: v0.2.22 and earlier ran every subprocess via
``subprocess.run(stdout=PIPE)`` and wrote the buffered output to disk only
**after** the subprocess exited. A scout run that takes 15 minutes left
``cycle-NNN-scout.log`` at zero bytes for the entire time, and a parent
crash mid-subprocess left the log empty forever. The user could not tell
"agent thinking" from "process dead" with ``tail -f``.

These tests lock the streaming behaviour in:

- Lines reach disk WHILE the subprocess is still running (not at exit).
- Each line carries an ``[HH:MM:SS]`` UTC timestamp.
- A startup ``# launching: …`` header and exit ``# exited with code N``
  footer bracket the run.
- The heartbeat thread emits ``[heartbeat]`` lines when the subprocess is
  silent (cadence controlled by ``RV_HEARTBEAT_S`` env var).
- If the subprocess cannot be launched (missing binary) the old
  ``_StepError`` is raised — external contract preserved.
- The log is line-buffered so a parent crash before subprocess exit still
  leaves the most-recent-line on disk.
"""

from __future__ import annotations

import os
import re
import sys
import textwrap
import time
from pathlib import Path

import pytest

import research_framework.pipeline._helpers.script_runner as _sr
from research_framework.pipeline.cycle_runner import (
    _hms,
    _resolve_script,
    _run_script,
    _StepError,
)


def _write_python_script(tmp_path: Path, body: str, name: str = "stub.py") -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    p.chmod(0o755)
    return p


# ---------------------------------------------------------------------------
# Timestamp prefix
# ---------------------------------------------------------------------------


def test_hms_format_is_HHMMSS_utc() -> None:
    """Sanity check on the timestamp helper used by every log line."""
    ts = _hms()
    assert re.fullmatch(r"\d{2}:\d{2}:\d{2}", ts), f"unexpected timestamp shape: {ts!r}"


def test_every_subprocess_line_carries_a_timestamp_prefix(tmp_path: Path) -> None:
    """Every output line from the subprocess MUST be prefixed with
    ``[HH:MM:SS]``. Without this, post-mortems can't attribute slow steps
    to specific log lines.
    """
    script = _write_python_script(
        tmp_path,
        """
        import sys
        for i in range(3):
            print(f"line {i}", flush=True)
        sys.exit(0)
        """,
    )
    log_file = tmp_path / "stub.log"
    rc = _run_script(sys.executable, script, env=os.environ.copy(), log_file=log_file)
    assert rc == 0, "subprocess should exit cleanly"

    content = log_file.read_text(encoding="utf-8")
    body_lines = [
        line
        for line in content.splitlines()
        if line.startswith("[") and not line.startswith("# [")
    ]
    assert len(body_lines) >= 3, f"expected ≥ 3 body lines, got {body_lines!r}"
    for line in body_lines:
        assert re.match(r"^\[\d{2}:\d{2}:\d{2}\] ", line), (
            f"expected [HH:MM:SS] prefix, got {line!r}"
        )


def test_header_and_footer_bracket_the_run(tmp_path: Path) -> None:
    """The log MUST start with a ``# launching: …`` header and end with a
    ``# exited with code N`` footer so post-mortems can read elapsed
    wall-clock time and the final exit code from the log alone.
    """
    script = _write_python_script(
        tmp_path,
        """
        print("hello")
        """,
    )
    log_file = tmp_path / "stub.log"
    _run_script(sys.executable, script, env=os.environ.copy(), log_file=log_file)

    content = log_file.read_text(encoding="utf-8")
    lines = content.splitlines()
    assert lines[0].startswith("# ["), f"missing header: {lines[0]!r}"
    assert "launching:" in lines[0], f"header missing 'launching:': {lines[0]!r}"
    assert any(
        line.startswith("# [") and "exited with code" in line for line in lines
    ), f"missing footer in log:\n{content}"


# ---------------------------------------------------------------------------
# Streaming — lines reach disk WHILE the subprocess runs
# ---------------------------------------------------------------------------


def test_lines_are_visible_on_disk_while_subprocess_still_running(
    tmp_path: Path,
) -> None:
    """The crux of the v0.2.23 fix: lines must be on disk before the
    subprocess exits. We have the stub emit one line, sleep, then emit
    another and exit. The first line MUST be readable from another process
    while the stub is still sleeping.

    Failure mode this prevents: ``cycle-NNN-scout.log`` sitting at 0 bytes
    for 15 minutes while the agent thinks, then suddenly filling at exit.
    """
    sentinel = tmp_path / "first_line_seen.flag"
    script = _write_python_script(
        tmp_path,
        f"""
        import sys, time
        print("first line — should be visible immediately", flush=True)
        # Wait until the test harness has read the line from disk.
        sentinel = r"{sentinel}"
        import pathlib
        p = pathlib.Path(sentinel)
        for _ in range(50):
            if p.exists():
                break
            time.sleep(0.1)
        print("second line — written after sentinel flag observed", flush=True)
        sys.exit(0)
        """,
    )
    log_file = tmp_path / "stream.log"

    # Run _run_script in a background thread so we can inspect the log
    # while the subprocess is still alive.
    import threading

    result: dict[str, int] = {}

    def _runner() -> None:
        result["rc"] = _run_script(
            sys.executable, script, env=os.environ.copy(), log_file=log_file
        )

    t = threading.Thread(target=_runner, daemon=True)
    t.start()

    # Wait for the first line to land on disk. With block-buffered logging
    # (the v0.2.22 bug) this would hang until the subprocess exits — which
    # our subprocess will never do unless the sentinel appears.
    deadline = time.monotonic() + 5.0
    seen_first = False
    while time.monotonic() < deadline:
        if log_file.exists() and "first line" in log_file.read_text(encoding="utf-8"):
            seen_first = True
            break
        time.sleep(0.05)

    assert seen_first, (
        "first line never reached disk while subprocess was alive — "
        "streaming regression"
    )
    # Now signal the subprocess to finish.
    sentinel.touch()
    t.join(timeout=10)
    assert not t.is_alive(), "subprocess thread did not exit in 10s"
    assert result.get("rc") == 0, f"unexpected exit code: {result!r}"


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


def test_heartbeat_emits_alive_line_for_silent_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A subprocess that produces no output for longer than the heartbeat
    cadence MUST cause ``[heartbeat] … still alive`` lines to land in the
    log so ``tail -f`` shows activity.

    We crank ``RV_HEARTBEAT_S=1`` and have the stub sleep silently for
    2.5s, then exit. The log MUST contain at least one heartbeat line.
    """
    monkeypatch.setenv("RV_HEARTBEAT_S", "1")
    script = _write_python_script(
        tmp_path,
        """
        import sys, time
        time.sleep(2.5)
        print("done", flush=True)
        sys.exit(0)
        """,
    )
    log_file = tmp_path / "silent.log"
    rc = _run_script(sys.executable, script, env=os.environ.copy(), log_file=log_file)
    assert rc == 0
    content = log_file.read_text(encoding="utf-8")
    heartbeats = [line for line in content.splitlines() if "[heartbeat]" in line]
    assert heartbeats, (
        "expected ≥ 1 heartbeat line for 2.5s-silent subprocess with "
        f"RV_HEARTBEAT_S=1; got:\n{content}"
    )
    for hb in heartbeats:
        assert "still alive" in hb
        assert "pid=" in hb
        assert "elapsed=" in hb


def test_heartbeat_does_not_fire_on_fast_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A subprocess that finishes well before the heartbeat cadence MUST
    NOT produce a heartbeat line — the heartbeat is an "I'm still alive"
    signal, not noise."""
    monkeypatch.setenv("RV_HEARTBEAT_S", "30")
    script = _write_python_script(
        tmp_path,
        """
        print("quick", flush=True)
        """,
    )
    log_file = tmp_path / "quick.log"
    rc = _run_script(sys.executable, script, env=os.environ.copy(), log_file=log_file)
    assert rc == 0
    content = log_file.read_text(encoding="utf-8")
    assert "[heartbeat]" not in content, (
        f"heartbeat fired on fast subprocess (cadence 30s, run < 1s):\n{content}"
    )


# ---------------------------------------------------------------------------
# Crash-safety
# ---------------------------------------------------------------------------


def test_log_is_line_buffered_so_partial_output_survives_subprocess_crash(
    tmp_path: Path,
) -> None:
    """If the subprocess prints a line then crashes (non-zero exit),
    every line printed BEFORE the crash MUST be on disk. The footer
    records the non-zero exit code.
    """
    script = _write_python_script(
        tmp_path,
        """
        import sys
        print("line before crash", flush=True)
        sys.exit(7)
        """,
    )
    log_file = tmp_path / "crash.log"
    rc = _run_script(sys.executable, script, env=os.environ.copy(), log_file=log_file)
    assert rc == 7, f"expected exit 7, got {rc}"
    content = log_file.read_text(encoding="utf-8")
    assert "line before crash" in content, f"output before crash was lost:\n{content}"
    assert "exited with code 7" in content, (
        f"footer should record non-zero exit code:\n{content}"
    )


def test_missing_python_binary_raises_step_error_preserving_v0222_contract(
    tmp_path: Path,
) -> None:
    """If the Python interpreter itself cannot be launched (binary missing
    / not executable), ``_run_script`` MUST raise :class:`_StepError`
    rather than letting an ``OSError`` propagate. This is the external
    contract every call-site in ``cycle_runner.py`` relies on for its
    abort paths.

    Note: a missing *script* arg passes the interpreter check and Python
    exits 2 on its own — that path is exercised by
    ``test_log_is_line_buffered_so_partial_output_survives_subprocess_crash``.
    The OSError path requires a missing *binary*, which we trigger here
    by pointing at a non-existent interpreter path.
    """
    fake_python = tmp_path / "no-such-python"
    script = _write_python_script(tmp_path, "print('unreachable')\n")
    log_file = tmp_path / "missing.log"
    with pytest.raises(_StepError):
        _run_script(str(fake_python), script, env=os.environ.copy(), log_file=log_file)


# ---------------------------------------------------------------------------
# Backwards compatibility
# ---------------------------------------------------------------------------


def test_subprocess_with_no_log_file_still_runs_and_returns_exit_code(
    tmp_path: Path,
) -> None:
    """Call sites that don't pass ``log_file`` must keep working — they
    bypass the streaming path and inherit stdout directly.
    """
    script = _write_python_script(
        tmp_path,
        """
        import sys; sys.exit(13)
        """,
    )
    rc = _run_script(sys.executable, script, env=os.environ.copy(), log_file=None)
    assert rc == 13


# ---------------------------------------------------------------------------
# Packaged-script fallback (regression: 2026-06-05 reference-vault run)
#
# Vault-local ``scripts/`` are regenerable + git-ignored + agent-writable
# (``danger-full-access``). On the 2026-06-05 overnight run, 15 of them
# vanished mid-scout (external sweep) and the next step crashed with
# ``can't open file '.../scripts/validate_cycle.py'`` → cycle abort. The
# immutable copy ships in the wheel under ``_data/scripts/``; ``_run_script``
# must fall back to it so a regenerable artifact never aborts a cycle.
# ---------------------------------------------------------------------------


def test_resolve_script_returns_existing_path_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An on-disk vault script is used verbatim — the packaged fallback is
    not even consulted (no asset_path lookup for the happy path)."""

    def _boom(_name: str) -> Path:
        raise AssertionError("asset_path must not be called for an existing script")

    monkeypatch.setattr(_sr, "asset_path", _boom)
    existing = _write_python_script(tmp_path, "print('hi')\n", name="validate_cycle.py")
    assert _resolve_script(existing) == existing


def test_resolve_script_falls_back_to_packaged_when_vault_copy_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When ``<vault>/scripts/<name>`` is gone but the packaged copy exists,
    the resolver returns the packaged path (same basename)."""
    packaged = tmp_path / "pkg_scripts"
    packaged.mkdir()
    (packaged / "validate_cycle.py").write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setattr(_sr, "asset_path", lambda _name: packaged)

    missing_vault_script = tmp_path / "vault" / "scripts" / "validate_cycle.py"
    assert not missing_vault_script.exists()
    assert _resolve_script(missing_vault_script) == packaged / "validate_cycle.py"


def test_resolve_script_returns_original_when_no_packaged_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If neither the vault copy nor a packaged copy exists, the original
    (missing) path is returned so the caller surfaces the normal
    missing-file behaviour rather than a surprise redirect."""
    empty_pkg = tmp_path / "empty_pkg"
    empty_pkg.mkdir()
    monkeypatch.setattr(_sr, "asset_path", lambda _name: empty_pkg)
    missing = tmp_path / "vault" / "scripts" / "nope.py"
    assert _resolve_script(missing) == missing


def test_resolve_script_is_graceful_when_asset_path_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A source/checkout with no packaged ``scripts`` asset makes
    ``asset_path`` raise ``FileNotFoundError``; the resolver swallows it and
    returns the original path (never propagates the lookup failure)."""

    def _raise(_name: str) -> Path:
        raise FileNotFoundError("scripts")

    monkeypatch.setattr(_sr, "asset_path", _raise)
    missing = tmp_path / "vault" / "scripts" / "validate_cycle.py"
    assert _resolve_script(missing) == missing


def test_run_script_runs_packaged_fallback_for_missing_vault_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: ``_run_script`` invoked with a missing vault script
    actually executes the packaged copy (rc 0) instead of crashing with
    Python's ``can't open file`` exit code 2. The log records the packaged
    path so post-mortems can see the fallback fired."""
    packaged = tmp_path / "pkg_scripts"
    packaged.mkdir()
    _write_python_script(
        packaged,
        """
        import sys
        print("packaged validate ran", flush=True)
        sys.exit(0)
        """,
        name="validate_cycle.py",
    )
    monkeypatch.setattr(_sr, "asset_path", lambda _name: packaged)

    missing_vault_script = tmp_path / "vault" / "scripts" / "validate_cycle.py"
    log_file = tmp_path / "validate.log"
    rc = _run_script(
        sys.executable,
        missing_vault_script,
        "--vault",
        str(tmp_path),
        env=os.environ.copy(),
        log_file=log_file,
    )
    assert rc == 0, "fallback should run the packaged copy and exit 0, not 2"
    content = log_file.read_text(encoding="utf-8")
    assert "packaged validate ran" in content
    assert str(packaged / "validate_cycle.py") in content


def test_run_script_missing_script_without_fallback_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Contract preserved: with no packaged fallback available, a missing
    script still yields Python's own exit code 2 (``can't open file``) — the
    fallback only *adds* resilience, it never masks a genuinely absent
    script."""
    empty_pkg = tmp_path / "empty_pkg"
    empty_pkg.mkdir()
    monkeypatch.setattr(_sr, "asset_path", lambda _name: empty_pkg)
    missing = tmp_path / "scripts" / "validate_cycle.py"
    log_file = tmp_path / "missing.log"
    rc = _run_script(sys.executable, missing, env=os.environ.copy(), log_file=log_file)
    assert rc == 2
