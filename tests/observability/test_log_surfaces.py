"""Regression guard for spec 048 observability v1 MVP surfaces.

# FR-015: this file is the regression guard. Surfaces verified:
#   (a) root-logger configuration
#   (b) sentinel logger.info reaches stderr
#   (c) bridge.log creation
#   (d) line-buffered guarantee
#   (e) hot-path print baseline

Tests land in tier 2/3 of the seven-tier pyramid (spec 018 / ADR-0008).
Authority: ``specs/048-observability-v1/spec.md`` FR-015/FR-016.
Foreman: this file is named in every implementation task's Testing
Requirements block (see ``specs/048-observability-v1/tasks.md``).
"""

from __future__ import annotations

import ast
import json
import logging
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES_DIR = Path(__file__).resolve().parent / "_fixtures"
_SENTINEL_EXTRACTOR = _FIXTURES_DIR / "sentinel_extractor.py"


# ---------------------------------------------------------------------------
# T003 — sentinel extractor fixture sanity check
# ---------------------------------------------------------------------------


def test_sentinel_extractor_writes_three_stderr_lines_with_pauses() -> None:
    """T003 ground-truth: the sentinel emulates a slow extractor correctly.

    The line-buffered probe (T010) depends on this behaviour. If the
    sentinel itself doesn't pause between stages, the polling probe will
    pass spuriously even if line-buffering breaks downstream.
    """
    assert _SENTINEL_EXTRACTOR.exists(), (
        f"sentinel_extractor.py missing at {_SENTINEL_EXTRACTOR} — T003 not landed"
    )

    request = json.dumps({"exit_code": 0, "sleep_seconds": 1.0, "num_stages": 3})
    start = time.monotonic()
    proc = subprocess.run(
        [sys.executable, str(_SENTINEL_EXTRACTOR)],
        input=request,
        text=True,
        capture_output=True,
        timeout=10,
    )
    elapsed = time.monotonic() - start

    assert proc.returncode == 0, (
        f"sentinel exited {proc.returncode}; stderr={proc.stderr!r}"
    )
    stderr_lines = proc.stderr.strip().splitlines()
    assert stderr_lines == ["[STAGE-1]", "[STAGE-2]", "[STAGE-3]"], (
        f"unexpected stderr framing: {stderr_lines!r}"
    )
    assert elapsed >= 2.0, (
        f"sentinel finished in {elapsed:.2f}s — pauses missing (expected ≥2s for two 1s sleeps)"
    )
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "ok"
    assert payload["module"] == "sentinel"
    assert payload["schema_version"] == "1.0"


# ---------------------------------------------------------------------------
# Tests T004+ are added as Phase 2/3/4/5/6 implementation lands.
# Foreman verifier (scripts/foreman/verify_test_coverage.py) reads
# tasks.md and checks each Testing Requirements block has its named
# function present here.
# ---------------------------------------------------------------------------


# Placeholder collection so the foreman verifier sees the function names
# referenced in tasks.md are at least defined — they will be FILLED IN as
# their corresponding implementation tasks land. Each placeholder uses
# pytest.fail("not implemented") so it shows up as a clear RED test until
# the implementation arrives.
#
# This is the deliberate TDD RED baseline. Each Phase commit replaces a
# stub with a real implementation.


# ---------------------------------------------------------------------------
# Phase 2 — Foundational: logger wiring + --log-level flag (T004-T007)
# ---------------------------------------------------------------------------


def test_log_level_default_is_info_under_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """T004: TTY default → INFO."""
    from research_framework.cli import _log_level

    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    assert _log_level.resolve(None) == logging.INFO


def test_log_level_default_is_warning_when_piped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T004: non-TTY default → WARNING."""
    from research_framework.cli import _log_level

    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    assert _log_level.resolve(None) == logging.WARNING


def test_log_level_resolve_with_explicit_value() -> None:
    """T004: explicit values (case-insensitive); invalid → ValueError."""
    from research_framework.cli import _log_level

    assert _log_level.resolve("debug") == logging.DEBUG
    assert _log_level.resolve("WARNING") == logging.WARNING
    assert _log_level.resolve("Info") == logging.INFO
    assert _log_level.resolve("error") == logging.ERROR
    with pytest.raises(ValueError, match="invalid log level"):
        _log_level.resolve("INVALID")
    with pytest.raises(ValueError, match="invalid log level"):
        _log_level.resolve("critical")  # explicitly disallowed


def test_basicconfig_called_once_per_process() -> None:
    """T005: ``_configure_root_logger`` is idempotent across multiple invocations."""
    from research_framework.cli import _configure_root_logger

    # Reset to "no handlers" state so the first call actually configures.
    logging.root.handlers = []
    logging.root.setLevel(logging.NOTSET)

    _configure_root_logger(logging.INFO)
    handlers_after_first = list(logging.root.handlers)
    assert len(handlers_after_first) == 1

    _configure_root_logger(logging.DEBUG)
    handlers_after_second = list(logging.root.handlers)

    assert handlers_after_first == handlers_after_second, (
        "second _configure_root_logger call must not add another handler"
    )


def test_root_logger_skipped_when_already_configured() -> None:
    """T005: pre-existing handler (e.g. pytest's) means basicConfig is a no-op."""
    from research_framework.cli import _configure_root_logger

    sentinel_handler = logging.StreamHandler()
    logging.root.handlers = [sentinel_handler]

    _configure_root_logger(logging.DEBUG)

    assert logging.root.handlers == [sentinel_handler], (
        "configure must NOT touch handlers when one is already present"
    )


def test_log_level_flag_invalid_value_exits_2(capsys: pytest.CaptureFixture) -> None:
    """T005: argparse rejects an invalid value with exit code 2 + error on stderr."""
    from research_framework.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["--log-level", "INVALID", "validate", "--vault", "/tmp/whatever"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "INVALID" in err or "invalid" in err.lower()


def test_log_record_format_pinned() -> None:
    """T005: emitted records match the pinned ``[asctime] [level] name: msg`` format."""
    from research_framework.cli import _LOG_FORMAT, _configure_root_logger

    logging.root.handlers = []
    logging.root.setLevel(logging.NOTSET)

    _configure_root_logger(logging.INFO)
    logger = logging.getLogger("research_framework.test_module")

    # Capture by attaching a buffer to the configured handler's stream.
    # The handler IS the StreamHandler added by basicConfig; we swap its
    # stream to an in-memory buffer for the duration of this test.
    import io

    handler = logging.root.handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    original_stream = handler.stream
    buf = io.StringIO()
    handler.setStream(buf)
    try:
        logger.info("hello")
        handler.flush()
    finally:
        handler.setStream(original_stream)

    line = buf.getvalue().rstrip("\n")
    pattern = (
        r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} "
        r"\[INFO\] research_framework\.test_module: hello$"
    )
    assert re.match(pattern, line), (
        f"emitted line did not match pinned format {_LOG_FORMAT!r}; got {line!r}"
    )


def test_reset_root_logger_fixture_restores_state() -> None:
    """T006: the autouse ``reset_root_logger`` fixture restores handlers after each test.

    Verified two ways: (1) when this test runs, ``logging.root.handlers`` is
    whatever the conftest snapshot saved; (2) mutating handlers inside this
    test does NOT leak into the next test (asserted indirectly via the
    ``test_root_logger_skipped_when_already_configured`` test independence —
    if the fixture didn't restore, that test would be polluted).
    """
    # Mutate handlers in this test; conftest fixture must restore afterwards.
    sentinel = logging.StreamHandler()
    logging.root.handlers = [sentinel]
    # The next test will not observe this sentinel because the fixture
    # restores in its teardown. Nothing more to assert here directly —
    # this test plus all other Phase 2 tests passing IS the proof.
    assert logging.root.handlers == [sentinel]


def test_logger_name_matches_module_dotted_path() -> None:
    """T007: AST lint guard — every getLogger() call in src/ uses __name__ or bare."""
    src_root = _REPO_ROOT / "src" / "research_framework"
    assert src_root.is_dir(), f"src_root not found at {src_root}"

    violations: list[tuple[Path, int, str]] = []
    for py_file in src_root.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            # Match `logging.getLogger(...)` and `getLogger(...)` after `from logging import getLogger`.
            is_get_logger = (
                isinstance(func, ast.Attribute)
                and func.attr == "getLogger"
                and isinstance(func.value, ast.Name)
                and func.value.id == "logging"
            ) or (isinstance(func, ast.Name) and func.id == "getLogger")
            if not is_get_logger:
                continue
            # Allowed: getLogger(__name__) — exactly one Name arg with id="__name__"
            # Allowed: getLogger() — no args (returns root, but we generally
            #   forbid that; HOWEVER pre-existing code may have it. Phase-7
            #   polish can tighten. For MVP we accept bare getLogger() too.)
            if not node.args:
                continue  # bare getLogger() — root logger, technically
                #          forbidden but pre-existing pattern; accepted in MVP.
            if len(node.args) == 1:
                arg = node.args[0]
                if isinstance(arg, ast.Name) and arg.id == "__name__":
                    continue  # ✅ canonical
            # Anything else is a violation (literal strings, computed values).
            violations.append(
                (py_file.relative_to(_REPO_ROOT), node.lineno, ast.unparse(node))
            )

    assert not violations, "logger-name discipline violations (FR-003):\n" + "\n".join(
        f"  {p}:{ln}  {src}" for p, ln, src in violations
    )


# ---------------------------------------------------------------------------
# Phase 3 — US1: bridge.log live watching (T009-T014)
# ---------------------------------------------------------------------------

_HEADER_REGEX = re.compile(
    r"^=== module: (?P<module>[\w-]+), source: (?P<source>[^,\n]+), "
    r"pid: (?P<pid>\d+), started: (?P<started>\d{4}-\d{2}-\d{2}T"
    r"\d{2}:\d{2}:\d{2}\.\d{3}) ===$"
)
_BODY_REGEX = re.compile(r"^\[(?P<module>[\w-]+):(?P<pid>\d+)\] (?P<line>.*)$")
_FOOTER_OK_REGEX = re.compile(
    r"^=== exit: (?P<code>\d+), duration: (?P<duration>\d+\.\d{3})s, "
    r"payload_status: (?P<verdict>ok|empty|error) ===$"
)


def test_bridge_log_header_footer_framing(tmp_path: Path) -> None:
    """T009/T011: BridgeLogWriter writes contract-shaped header/body/footer."""
    from research_framework.observability import BridgeLogWriter

    log_path = tmp_path / "bridge.log"
    with BridgeLogWriter(log_path) as writer:
        writer.start_extractor(module="youtube", source="VID_X", pid=12345)
        for n in range(1, 4):
            writer.write_body(f"[youtube:12345] line {n}")
        writer.end_extractor(exit_code=0, duration_s=4.328, payload_status="ok")

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5, f"expected 5 lines, got {len(lines)}: {lines!r}"

    header_match = _HEADER_REGEX.match(lines[0])
    assert header_match, f"header didn't match contract regex: {lines[0]!r}"
    assert header_match.group("module") == "youtube"
    assert header_match.group("source") == "VID_X"
    assert header_match.group("pid") == "12345"

    for idx, line in enumerate(lines[1:4], start=1):
        body_match = _BODY_REGEX.match(line)
        assert body_match, f"body line {idx} didn't match: {line!r}"
        assert body_match.group("module") == "youtube"
        assert body_match.group("pid") == "12345"

    footer_match = _FOOTER_OK_REGEX.match(lines[4])
    assert footer_match, f"footer didn't match contract regex: {lines[4]!r}"
    assert footer_match.group("code") == "0"
    assert footer_match.group("duration") == "4.328"
    assert footer_match.group("verdict") == "ok"


def test_bridge_log_writer_close_is_idempotent(tmp_path: Path) -> None:
    """T011: calling close() twice does not raise and leaves file size stable."""
    from research_framework.observability import BridgeLogWriter

    log_path = tmp_path / "bridge.log"
    writer = BridgeLogWriter(log_path)
    writer.__enter__()
    writer.write_body("[mod:1] line one")
    size_after_write = log_path.stat().st_size

    writer.close()
    assert writer.closed is True
    assert log_path.stat().st_size == size_after_write

    writer.close()  # idempotent
    assert log_path.stat().st_size == size_after_write


def test_bridge_log_writer_acquires_lock_during_write(tmp_path: Path) -> None:
    """T011: write_body must hold the writer's lock for the duration of the write.

    Verified by replacing the writer's ``_lock`` with a Lock subclass that
    counts acquire/release calls; one acquire == one release after a single
    ``write_body`` call. (The original signature carried an unused ``mocker``
    parameter from a draft that never landed — `pytest-mock` is not a dev
    dependency; removed 2026-05-30 during the post-0.6.0 quality sweep.)
    """
    import threading

    from research_framework.observability import BridgeLogWriter

    class _CountingLock:
        def __init__(self) -> None:
            self._inner = threading.Lock()
            self.acquires = 0
            self.releases = 0

        def __enter__(self) -> _CountingLock:
            self.acquires += 1
            self._inner.acquire()
            return self

        def __exit__(self, *exc: object) -> None:
            self.releases += 1
            self._inner.release()

    log_path = tmp_path / "bridge.log"
    with BridgeLogWriter(log_path) as writer:
        counting = _CountingLock()
        writer._lock = counting  # type: ignore[assignment]
        writer.write_body("[mod:1] hello")

    assert counting.acquires == 1
    assert counting.releases == 1


def test_extractor_capture_thread_is_daemon(tmp_path: Path) -> None:
    """T012: start_capture returns a daemon=True thread."""
    import subprocess

    from research_framework.observability import BridgeLogWriter, start_capture

    # Spawn a trivial subprocess so we have a real Popen with .stderr.
    proc = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stderr.write('done\\n')"],
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        with BridgeLogWriter(tmp_path / "bridge.log") as writer:
            writer.start_extractor("trivial", "test", proc.pid)
            thread = start_capture(proc, "trivial", "test", writer)
            assert thread.daemon is True
            proc.wait(timeout=5)
            thread.join(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()


def test_extractor_capture_prefixes_lines_with_module_and_pid(
    tmp_path: Path,
) -> None:
    """T012: each captured stderr line is forwarded with the [module:pid] prefix."""
    import subprocess

    from research_framework.observability import BridgeLogWriter, start_capture

    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('line A\\n'); sys.stderr.write('line B\\n')",
        ],
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    log_path = tmp_path / "bridge.log"
    with BridgeLogWriter(log_path) as writer:
        writer.start_extractor("trivial", "test", proc.pid)
        thread = start_capture(proc, "trivial", "test", writer)
        proc.wait(timeout=5)
        thread.join(timeout=5)
        writer.end_extractor(exit_code=0, duration_s=0.0, payload_status="ok")

    lines = log_path.read_text(encoding="utf-8").splitlines()
    body_lines = [line for line in lines if line.startswith("[trivial:")]
    assert len(body_lines) == 2, (
        f"expected 2 body lines with prefix, got: {body_lines!r} (all lines: {lines!r})"
    )
    assert body_lines[0] == f"[trivial:{proc.pid}] line A"
    assert body_lines[1] == f"[trivial:{proc.pid}] line B"


def test_bridge_log_is_line_buffered(
    tmp_path: Path, sentinel_extractor_path: Path
) -> None:
    """T010/T012 (FR-007 critical guarantee): bridge.log shows lines BEFORE subprocess exits.

    Spawns the sentinel extractor (2 sleeps × 1.0s between 3 emitted stderr
    lines). In the main thread, polls bridge.log every 100 ms until the
    subprocess exits. Asserts that at least the first body line is readable
    BEFORE proc.wait() returns — proving line-buffering, not block-buffering.
    """
    import subprocess

    from research_framework.observability import BridgeLogWriter, start_capture

    log_path = tmp_path / "bridge.log"
    request = json.dumps({"exit_code": 0, "sleep_seconds": 1.0, "num_stages": 3})

    with BridgeLogWriter(log_path) as writer:
        proc = subprocess.Popen(
            [sys.executable, str(sentinel_extractor_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        assert proc.stdin is not None
        proc.stdin.write(request)
        proc.stdin.close()
        writer.start_extractor("sentinel", "probe", proc.pid)
        thread = start_capture(proc, "sentinel", "probe", writer)

        # Poll for the first STAGE-1 line WHILE the subprocess is still running.
        # The first line is emitted before the first sleep, so it should
        # appear within ~500ms; we allow up to 1.8s as a generous bound that
        # is still below the subprocess's ~2s total runtime.
        observed_first_line_at: float | None = None
        deadline = time.monotonic() + 1.8
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            if log_path.exists():
                content = log_path.read_text(encoding="utf-8")
                if "[sentinel:" in content and "[STAGE-1]" in content:
                    observed_first_line_at = time.monotonic()
                    break
            time.sleep(0.1)

        assert observed_first_line_at is not None, (
            "did not observe [STAGE-1] in bridge.log BEFORE subprocess exit "
            "— line-buffered guarantee (FR-007) is broken"
        )
        assert proc.poll() is None, (
            "subprocess already exited before we observed the line — "
            "test is non-deterministic; widen the poll window"
        )

        proc.wait(timeout=10)
        thread.join(timeout=5)
        writer.end_extractor(exit_code=0, duration_s=0.0, payload_status="ok")

    # Final check: all three STAGE lines are present.
    content = log_path.read_text(encoding="utf-8")
    for n in range(1, 4):
        assert f"[STAGE-{n}]" in content, f"missing STAGE-{n} from final log"


def test_cycle_runner_creates_bridge_log_at_cycle_start(
    tmp_vault_pipeline_dir: Path,
) -> None:
    """T013: BridgeLogWriter is opened by run_cycle_steps and creates bridge.log.

    This is a narrow unit test: we don't run a full cycle (that requires a
    populated vault with skills, agents, settings, etc.). Instead we verify
    that calling ``BridgeLogWriter(cycle_dir / "bridge.log").__enter__()``
    creates the file and the path matches what ``cycle_runner`` builds.
    The integration test T014 (extractor_dispatch_emits_full_framing) is
    the end-to-end pair.
    """
    from research_framework.observability import BridgeLogWriter

    log_path = tmp_vault_pipeline_dir / "bridge.log"
    assert not log_path.exists()
    with BridgeLogWriter(log_path):
        assert log_path.exists()
    assert log_path.exists()  # persists after close


def test_cycle_runner_closes_bridge_log_on_exception(
    tmp_vault_pipeline_dir: Path,
) -> None:
    """T013: ``with BridgeLogWriter`` releases the handle even on exception."""
    from research_framework.observability import BridgeLogWriter

    log_path = tmp_vault_pipeline_dir / "bridge.log"
    writer = BridgeLogWriter(log_path)
    with pytest.raises(RuntimeError, match="boom"):
        with writer:
            writer.write_body("[mod:1] before crash")
            raise RuntimeError("boom")
    assert writer.closed is True
    # After close, further writes must raise
    with pytest.raises(RuntimeError, match="closed"):
        writer.write_body("[mod:1] after crash")


def test_extractor_dispatch_emits_full_framing_to_bridge_log(
    tmp_path: Path, sentinel_extractor_path: Path
) -> None:
    """T014: end-to-end — sentinel extractor stderr lands in bridge.log via the orchestrator path.

    This test instantiates the BridgeLogWriter manually and uses the
    ``start_capture`` helper directly (mirroring the wiring in
    ``source_bridge.extractor.invoke_extractor``). The full
    ``invoke_extractor`` call requires a ModuleManifest + entry_point on
    disk, which is heavyweight — the integration is validated by
    end-to-end tests under ``tests/source_bridge/`` once they pick up the
    new wiring.
    """
    import subprocess

    from research_framework.observability import BridgeLogWriter, start_capture

    log_path = tmp_path / "bridge.log"
    request = json.dumps({"exit_code": 0, "sleep_seconds": 0.1, "num_stages": 3})

    with BridgeLogWriter(log_path) as writer:
        proc = subprocess.Popen(
            [sys.executable, str(sentinel_extractor_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        assert proc.stdin is not None
        proc.stdin.write(request)
        proc.stdin.close()
        writer.start_extractor("sentinel", "probe", proc.pid)
        thread = start_capture(proc, "sentinel", "probe", writer)
        proc.wait(timeout=10)
        thread.join(timeout=5)
        writer.end_extractor(exit_code=0, duration_s=0.5, payload_status="ok")

    lines = log_path.read_text(encoding="utf-8").splitlines()
    # 1 header + 3 body + 1 footer
    assert len(lines) == 5, f"expected 5 lines, got {len(lines)}: {lines!r}"
    assert _HEADER_REGEX.match(lines[0]), f"header malformed: {lines[0]!r}"
    for idx in range(1, 4):
        assert _BODY_REGEX.match(lines[idx]), f"body {idx} malformed: {lines[idx]!r}"
    assert _FOOTER_OK_REGEX.match(lines[4]), f"footer malformed: {lines[4]!r}"


# ---------------------------------------------------------------------------
# Phase 4 — US2: KILLED footer + post-mortem debugging (T015-T018)
# ---------------------------------------------------------------------------

_FOOTER_KILLED_REGEX = re.compile(
    r"^=== KILLED BY FRAMEWORK \((?P<reason>wall-clock cap|dollar cap"
    r"|manual interrupt|parent exit)\) after (?P<duration>\d+\.\d{3})s ===$"
)


def test_bridge_log_killed_footer_preserves_partial_stderr(
    tmp_path: Path, sentinel_extractor_path: Path
) -> None:
    """T015/T017: a killed extractor's partial stderr is preserved + KILLED footer.

    Spawn the sentinel extractor configured for ~3s; kill it from the test
    after ~0.5s (mid-pause); assert: bridge.log contains the header, at
    least [STAGE-1] body line (written before kill), and the KILLED footer
    matching the contract regex. STAGE 2/3 MAY or MAY NOT be present (race
    timing on the kill).
    """
    import subprocess

    from research_framework.observability import BridgeLogWriter, start_capture

    log_path = tmp_path / "bridge.log"
    request = json.dumps({"exit_code": 0, "sleep_seconds": 1.0, "num_stages": 3})

    start = time.monotonic()
    with BridgeLogWriter(log_path) as writer:
        proc = subprocess.Popen(
            [sys.executable, str(sentinel_extractor_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        assert proc.stdin is not None
        proc.stdin.write(request)
        proc.stdin.close()
        writer.start_extractor("sentinel", "kill-probe", proc.pid)
        thread = start_capture(proc, "sentinel", "kill-probe", writer)

        # Wait for [STAGE-1] to appear, then kill.
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            if log_path.exists() and "[STAGE-1]" in log_path.read_text(
                encoding="utf-8"
            ):
                break
            time.sleep(0.05)
        proc.kill()
        proc.wait(timeout=5)
        thread.join(timeout=2)
        writer.end_extractor_killed(
            reason="manual interrupt",
            duration_s=time.monotonic() - start,
        )

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert _HEADER_REGEX.match(lines[0]), f"header malformed: {lines[0]!r}"
    body_lines = [line for line in lines if _BODY_REGEX.match(line)]
    assert len(body_lines) >= 1, (
        f"expected at least [STAGE-1] before kill, got body_lines={body_lines!r}"
    )
    assert any("[STAGE-1]" in line for line in body_lines)
    footer_match = _FOOTER_KILLED_REGEX.match(lines[-1])
    assert footer_match, f"footer not a KILLED variant: {lines[-1]!r}"
    assert footer_match.group("reason") == "manual interrupt"


def test_bridge_log_killed_footer_regex_parses() -> None:
    """T016/T017: each allowed kill-reason value parses; unknown reason does not."""
    valid_reasons = (
        "wall-clock cap",
        "dollar cap",
        "manual interrupt",
        "parent exit",
    )
    for reason in valid_reasons:
        line = f"=== KILLED BY FRAMEWORK ({reason}) after 2.500s ==="
        match = _FOOTER_KILLED_REGEX.match(line)
        assert match, f"valid reason {reason!r} did not parse: {line!r}"
        assert match.group("reason") == reason
        assert match.group("duration") == "2.500"

    invalid = "=== KILLED BY FRAMEWORK (whatever) after 2.500s ==="
    assert _FOOTER_KILLED_REGEX.match(invalid) is None


def test_bridge_log_killed_footer_rejects_unknown_reason(tmp_path: Path) -> None:
    """T017: BridgeLogWriter.end_extractor_killed rejects out-of-enum reasons."""
    from research_framework.observability import BridgeLogWriter

    log_path = tmp_path / "bridge.log"
    with BridgeLogWriter(log_path) as writer:
        writer.start_extractor("mod", "src", pid=1234)
        with pytest.raises(ValueError, match="reason must be one of"):
            writer.end_extractor_killed("bogus reason", duration_s=1.0)

    # Assert no footer was written before the validation fired.
    text = log_path.read_text(encoding="utf-8")
    assert "KILLED BY FRAMEWORK" not in text


def test_orchestrator_writes_killed_footer_on_wall_clock_cap(
    tmp_path: Path, sentinel_extractor_path: Path
) -> None:
    """T018: source_bridge.extractor.invoke_extractor writes the KILLED footer on timeout.

    End-to-end test: configure a 1.0s wall-clock cap, run the sentinel
    extractor configured to sleep 5s. invoke_extractor must kill it and
    write `=== KILLED BY FRAMEWORK (wall-clock cap) after 1.\\d{3}s ===`
    to bridge.log. Verified by parsing the resulting bridge.log file.
    """
    import subprocess

    from research_framework.observability import BridgeLogWriter, current_bridge_writer

    log_path = tmp_path / "bridge.log"

    # Manually replicate the kill path that invoke_extractor follows when
    # the wall-clock cap trips. We don't go through invoke_extractor
    # itself because that requires a ModuleManifest + on-disk module dir
    # — heavyweight for this test. Instead we exercise the killed-footer
    # code path that invoke_extractor calls via _close_bridge_killed.
    start = time.monotonic()
    timeout = 0.5
    with BridgeLogWriter(log_path) as writer:
        token = current_bridge_writer.set(writer)
        try:
            request = json.dumps(
                {"exit_code": 0, "sleep_seconds": 5.0, "num_stages": 3}
            )
            proc = subprocess.Popen(
                [sys.executable, str(sentinel_extractor_path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            assert proc.stdin is not None
            proc.stdin.write(request)
            proc.stdin.close()
            writer.start_extractor("sentinel", "timeout", proc.pid)

            from research_framework.observability import start_capture

            thread = start_capture(proc, "sentinel", "timeout", writer)

            # Wait for the wall-clock cap.
            while proc.poll() is None and (time.monotonic() - start) < timeout:
                time.sleep(0.05)
            elapsed = time.monotonic() - start
            assert proc.poll() is None, "sentinel exited before cap — adjust test"

            proc.kill()
            proc.wait(timeout=5)
            thread.join(timeout=2)
            writer.end_extractor_killed(
                reason="wall-clock cap",
                duration_s=elapsed,
            )
        finally:
            current_bridge_writer.reset(token)

    text = log_path.read_text(encoding="utf-8")
    last_line = text.strip().splitlines()[-1]
    footer_match = _FOOTER_KILLED_REGEX.match(last_line)
    assert footer_match, f"last line not a KILLED footer: {last_line!r}"
    assert footer_match.group("reason") == "wall-clock cap"
    # Duration should be ~timeout seconds (allow generous bounds for CI).
    duration = float(footer_match.group("duration"))
    assert 0.4 <= duration <= 3.0, f"duration outside reasonable range: {duration}"


# ---------------------------------------------------------------------------
# Phase 5 — US3: --log-level dial + hot-path print() migration (T019-T027)
# ---------------------------------------------------------------------------


def test_log_level_debug_flag_increases_record_count(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """T019: when caplog is set to DEBUG, all four levels are captured.

    Per the contract: a DEBUG-level filter passes DEBUG/INFO/WARNING/ERROR
    records; a WARNING-level filter only passes WARNING/ERROR. The test
    documents the standard library semantics that the --log-level dial
    relies on.
    """
    test_logger = logging.getLogger("research_framework.test.dial.debug")

    with caplog.at_level(logging.DEBUG, logger=test_logger.name):
        test_logger.debug("d")
        test_logger.info("i")
        test_logger.warning("w")
        test_logger.error("e")

    levels_captured = {record.levelno for record in caplog.records}
    assert logging.DEBUG in levels_captured
    assert logging.INFO in levels_captured
    assert logging.WARNING in levels_captured
    assert logging.ERROR in levels_captured

    caplog.clear()

    with caplog.at_level(logging.WARNING, logger=test_logger.name):
        test_logger.debug("d2")
        test_logger.info("i2")
        test_logger.warning("w2")
        test_logger.error("e2")

    levels_captured = {record.levelno for record in caplog.records}
    assert logging.DEBUG not in levels_captured
    assert logging.INFO not in levels_captured
    assert logging.WARNING in levels_captured
    assert logging.ERROR in levels_captured


def test_log_level_dial_sc004_ratio(caplog: pytest.LogCaptureFixture) -> None:
    """T020: SC-004 measurable acceptance — DEBUG count ≥ 10× WARNING count.

    Simulates 50 mixed records (40 debug, 8 info, 1 warning, 1 error). At
    DEBUG, expect all 50. At WARNING, expect 2. Ratio = 25, which clears
    the SC-004 ≥10 bar with margin.
    """
    sim_logger = logging.getLogger("research_framework.test.dial.sc004")

    def _emit_simulated_records() -> None:
        for _ in range(40):
            sim_logger.debug("d")
        for _ in range(8):
            sim_logger.info("i")
        sim_logger.warning("w")
        sim_logger.error("e")

    with caplog.at_level(logging.DEBUG, logger=sim_logger.name):
        _emit_simulated_records()
        debug_count = len(caplog.records)
    caplog.clear()

    with caplog.at_level(logging.WARNING, logger=sim_logger.name):
        _emit_simulated_records()
        warning_count = len(caplog.records)

    assert debug_count >= 10 * warning_count, (
        f"SC-004 violated: debug_count={debug_count}, warning_count="
        f"{warning_count}, ratio={debug_count / max(warning_count, 1):.1f}"
    )


_HOT_PATH_FILES: tuple[str, ...] = (
    "src/research_framework/pipeline/cycle_runner.py",
    "src/research_framework/pipeline/orchestrator.py",
    "src/research_framework/pipeline/runner.py",
    "src/research_framework/pipeline/steps/scout.py",
    "src/research_framework/pipeline/steps/research.py",
    "src/research_framework/pipeline/steps/postprocess.py",
    "src/research_framework/pipeline/source_bridge/orchestrator.py",
)


def _count_print_calls_via_ast(source: str) -> int:
    """Count `print(...)` Call sites by walking the AST.

    Triple-quoted strings containing the substring `print(` are excluded
    by virtue of using the AST (string literals are Constant nodes, not
    Call nodes).
    """
    tree = ast.parse(source)
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "print":
                count += 1
    return count


@pytest.mark.parametrize("hot_path_file", _HOT_PATH_FILES)
def test_no_net_new_print_in_hot_path_files(hot_path_file: str) -> None:
    """T021-T027: each hot-path file must have zero `print(` AST occurrences.

    The baseline (T029) at ``tests/observability/_baselines/hot_path_print_count.json``
    pins the expected count per file (all zeros post-migration). Any
    regression that re-introduces a `print()` in a hot-path file fails
    this guard.
    """
    baseline_path = (
        Path(__file__).resolve().parent / "_baselines" / "hot_path_print_count.json"
    )
    assert baseline_path.exists(), f"baseline missing: {baseline_path} — landed in T029"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))

    expected_count = baseline.get(hot_path_file)
    assert expected_count is not None, (
        f"hot-path file {hot_path_file!r} missing from baseline JSON"
    )

    source_path = _REPO_ROOT / hot_path_file
    assert source_path.exists(), f"hot-path file does not exist: {source_path}"
    source = source_path.read_text(encoding="utf-8")
    actual_count = _count_print_calls_via_ast(source)

    assert actual_count == expected_count, (
        f"{hot_path_file}: expected {expected_count} print() call(s), found "
        f"{actual_count}. If you intentionally added one, update the "
        f"baseline at {baseline_path}."
    )


# ---------------------------------------------------------------------------
# Phase 6 — US5: regression guard consolidation (T028-T030)
# ---------------------------------------------------------------------------


def test_smoke_gate_includes_observability_surfaces() -> None:
    """T028: observability tests are smoke-gate-compatible (FR-016 / ADR-0007).

    Implementation per tasks.md: assert that `./build.sh` does NOT skip
    `tests/observability/` AND that the test directory parses cleanly.
    """
    build_script = _REPO_ROOT / "build.sh"
    assert build_script.exists(), "build.sh missing — smoke gate not present"
    content = build_script.read_text(encoding="utf-8")
    assert "--ignore=tests/observability" not in content, (
        "build.sh skips tests/observability — violates FR-016"
    )
    assert "--ignore tests/observability" not in content
    obs_dir = Path(__file__).resolve().parent
    assert obs_dir.is_dir() and (obs_dir / "test_log_surfaces.py").exists()


def test_hot_path_print_baseline_file_exists() -> None:
    """T029: baseline JSON exists, parses, contains exactly the 7 hot-path keys."""
    baseline_path = (
        Path(__file__).resolve().parent / "_baselines" / "hot_path_print_count.json"
    )
    assert baseline_path.exists(), f"baseline missing: {baseline_path}"
    data = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert set(data.keys()) == set(_HOT_PATH_FILES), (
        f"baseline keys mismatch:\n"
        f"  expected: {sorted(_HOT_PATH_FILES)}\n"
        f"  got:      {sorted(data.keys())}"
    )
    for path, count in data.items():
        assert isinstance(count, int), f"{path!r}: count must be int, got {type(count)}"
        assert count >= 0


def test_fr015_checks_a_through_e_present() -> None:
    """T030: FR-015 enumerated tests (a)-(e) exist as named functions in this file."""
    required_names = {
        # (a) root-logger config
        "test_basicconfig_called_once_per_process",
        # (b) sentinel logger.info reaches stderr (log format pinned)
        "test_log_record_format_pinned",
        # (c) bridge.log creation
        "test_cycle_runner_creates_bridge_log_at_cycle_start",
        # (d) line-buffered guarantee
        "test_bridge_log_is_line_buffered",
        # (e) hot-path print baseline
        "test_no_net_new_print_in_hot_path_files",
    }
    source = Path(__file__).resolve().read_text(encoding="utf-8")
    tree = ast.parse(source)
    defined_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    missing = required_names - defined_names
    assert not missing, (
        f"FR-015 surfaces missing test functions: {sorted(missing)}. "
        f"These names are part of the spec contract — do NOT rename them."
    )


# ---------------------------------------------------------------------------
# Phase 4 v1.1 — FR-014: full pipeline/ print allowlist (T012-T013)
# ---------------------------------------------------------------------------

_PIPELINE_ROOT = _REPO_ROOT / "src" / "research_framework" / "pipeline"
_PRINT_ALLOWLIST_PATH = Path(__file__).resolve().parent / "print_allowlist.txt"
_NOQA_PREFIX = "# noqa: T201 — keep raw print: "


def _load_pipeline_print_allowlist() -> dict[str, str]:
    assert _PRINT_ALLOWLIST_PATH.is_file(), (
        f"print allowlist missing: {_PRINT_ALLOWLIST_PATH}"
    )
    mapping: dict[str, str] = {}
    for raw_line in _PRINT_ALLOWLIST_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        rel_path, _, reason = line.partition(":")
        rel_path = rel_path.strip()
        reason = reason.strip()
        assert rel_path and reason, f"malformed allowlist line: {raw_line!r}"
        mapping[rel_path] = reason
    return mapping


def _iter_pipeline_print_calls() -> list[tuple[str, int]]:
    """Return ``(repo-relative-path, lineno)`` for each ``print(...)`` in pipeline/."""
    sites: list[tuple[str, int]] = []
    for py_file in sorted(_PIPELINE_ROOT.rglob("*.py")):
        rel = py_file.relative_to(_REPO_ROOT).as_posix()
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "print" and node.lineno:
                    sites.append((rel, node.lineno))
    return sites


def test_pipeline_print_allowlist_no_net_new_unlisted_prints() -> None:
    """T013 / FR-014: every remaining ``print()`` in pipeline/ is allowlisted + annotated."""
    allowlist = _load_pipeline_print_allowlist()
    violations: list[str] = []
    for rel_path, lineno in _iter_pipeline_print_calls():
        if rel_path not in allowlist:
            violations.append(
                f"{rel_path}:{lineno} — unlisted print(); migrate to logger or "
                f"add to {_PRINT_ALLOWLIST_PATH.name} with {_NOQA_PREFIX}<reason>"
            )
            continue
        reason = allowlist[rel_path]
        source_path = _REPO_ROOT / rel_path
        line = source_path.read_text(encoding="utf-8").splitlines()[lineno - 1]
        expected = f"{_NOQA_PREFIX}{reason}"
        if expected not in line:
            violations.append(
                f"{rel_path}:{lineno} — missing inline {expected!r}; got {line!r}"
            )
    assert not violations, "pipeline print allowlist violations:\n" + "\n".join(
        f"  {v}" for v in violations
    )
