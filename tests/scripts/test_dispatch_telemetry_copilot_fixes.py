"""Regression tests for the 6 Copilot review findings on PR #28.

Each test maps directly to one of the inline comments left by GitHub
Copilot on the dispatch-telemetry / sidecar v1.1 implementation. The
tests live in a separate file so that future code review can trace
"this PR addressed Copilot finding X" without scanning the broader
test suite.

Mapping:
  1. test_started_at_is_captured_at_dispatch_start                 → agent_call.py:343
  2. test_dispatch_kills_subprocess_and_times_out_under_deadline   → agent_call.py:615
  3. test_dispatch_timeout_kills_orphaned_process                  → agent_call.py:648
  4. test_run_claude_with_cost_parses_stream_incrementally         → agent_call.py:833
  5. test_research_step_passes_batch_flags_to_note_writer          → steps/research.py:199
  6. test_status_ok_requires_terminal_result_event                 → agent_call.py:520
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "agent_call.py"
RESEARCH_STEP_PATH = (
    REPO_ROOT / "src" / "research_framework" / "pipeline" / "steps" / "research.py"
)


def _load_agent_call():
    spec = importlib.util.spec_from_file_location("agent_call", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["agent_call"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def ac():
    return _load_agent_call()


@pytest.fixture
def claude_vault(tmp_path: Path) -> Path:
    """A vault whose default_executor is claude/sonnet (triggers stream path)."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text(
        "default_executor:\n"
        "  type: cli\n"
        "  runtime: claude\n"
        "  model: sonnet\n"
        "  timeout_s: 60\n",
        encoding="utf-8",
    )
    return vault


@pytest.fixture
def cycle_dir_for(claude_vault: Path) -> Path:
    cycle = claude_vault / "_pipeline" / "cycles" / "cycle-001"
    cycle.mkdir(parents=True)
    return cycle


# ---------------------------------------------------------------------------
# Fix 1 — started_at captured at dispatch start, not completion
# ---------------------------------------------------------------------------


def test_started_at_is_captured_at_dispatch_start(ac, claude_vault, cycle_dir_for):
    """The sidecar's ``started_at`` MUST reflect the wall clock at the moment
    dispatch BEGAN, and ``completed_at`` the moment it ended. Previously
    both timestamps were generated from a single ``_iso_utc_ms_now()``
    pair called at completion time, so any consumer reading ``started_at``
    saw a value indistinguishable from ``completed_at`` (modulo ms).
    """
    # Stub the wall-clock helper to return distinct values per call.
    timestamps = iter(
        [
            "2026-01-01T00:00:00.000Z",  # _started_at_for(real)
            "2026-01-01T00:00:05.500Z",  # _completed_at_for(real)
        ]
    )
    events = [
        '{"type":"result","subtype":"success","total_cost_usd":0.001,'
        '"usage":{"input_tokens":1,"output_tokens":1}}',
    ]
    fake_proc = MagicMock()
    fake_proc.stdin = MagicMock()
    fake_proc.stdout = iter(line + "\n" for line in events)
    fake_proc.stderr = MagicMock(read=MagicMock(return_value=""))
    fake_proc.wait.return_value = 0
    with (
        patch.object(ac, "_iso_utc_ms_now", side_effect=lambda: next(timestamps)),
        patch.object(ac.subprocess, "Popen", return_value=fake_proc),
    ):
        result = ac.dispatch(
            "plan_narrator", "hi", vault_dir=claude_vault, cycle_dir=cycle_dir_for
        )
    assert result.exit_code == 0
    sidecar = cycle_dir_for / "agent-calls" / "plan_narrator.json"
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["started_at"] == "2026-01-01T00:00:00.000Z"
    assert payload["completed_at"] == "2026-01-01T00:00:05.500Z"
    assert payload["started_at"] != payload["completed_at"], (
        "Both timestamps came from the same _iso_utc_ms_now() pair; "
        "this is the bug Copilot flagged on agent_call.py:343."
    )


# ---------------------------------------------------------------------------
# Fix 2 — Stream consumption respects the timeout deadline
# ---------------------------------------------------------------------------


def test_dispatch_aborts_on_deadline_during_stream_read(
    ac, claude_vault, cycle_dir_for
):
    """``dispatch()`` (claude path) must enforce the dispatch timeout while
    the stream is still open. Previously the read loop blocked indefinitely
    on ``proc.stdout`` and ``proc.wait(timeout=...)`` was never reached.

    The wait is bounded by the dispatch timeout, and the fake process reports
    it running out the way ``Popen.wait`` does: by raising ``TimeoutExpired``.
    An earlier version of this test faked the clock instead and pinned the
    number of ``time.monotonic()`` calls, which is how a deadline that was
    only consulted when a line arrived went unnoticed. The real clock against
    a real silent child is covered by ``test_agent_call_process_tree.py::
    TestStreamingCallsAreSupervised``.
    """
    fake_proc = MagicMock()
    fake_proc.stdin = MagicMock()
    fake_proc.stdout = iter(['{"type":"assistant","message":{"content":[]}}\n'])
    fake_proc.stderr = MagicMock(read=MagicMock(return_value=""))
    fake_proc.poll.return_value = None
    fake_proc.wait.side_effect = subprocess.TimeoutExpired("claude", 10)
    with (
        patch.object(ac.subprocess, "Popen", return_value=fake_proc),
        # The deadline-abort path calls the real _terminate_process_tree;
        # with a MagicMock proc its .pid coerces to 1 -> os.killpg(1, ...),
        # which on Linux kills the test runner's own process group. Patch it
        # out (as test_dispatch_timeout_kills_orphaned_process already does);
        # the kill mechanism is covered by test_agent_call_process_tree.py.
        patch.object(ac, "_terminate_process_tree"),
    ):
        result = ac.dispatch(
            "plan_narrator",
            "hi",
            vault_dir=claude_vault,
            cycle_dir=cycle_dir_for,
            timeout_s=10,
        )
    fake_proc.wait.assert_called_once_with(timeout=10)
    assert result.exit_code == 2
    assert result.stderr == "timed out"
    sidecar = cycle_dir_for / "agent-calls" / "plan_narrator.json"
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    # timed_out implies status=failed regardless of any partial cost data.
    assert payload["status"] == "failed", (
        "TimeoutExpired must force status='failed' (Copilot PR #28 review)."
    )


# ---------------------------------------------------------------------------
# Fix 3 — Timeout path must kill the orphaned subprocess
# ---------------------------------------------------------------------------


def test_dispatch_timeout_kills_orphaned_process(ac, claude_vault, cycle_dir_for):
    """When the dispatch timeout fires, the ENTIRE process tree must be
    signalled — not just the direct child — otherwise the post-mortem
    2026-05-30 hang resurfaces (grandchildren keep stdout pipes open and
    ``communicate()`` blocks for hours).

    The test asserts ``_terminate_process_tree`` is invoked on timeout.
    The internal implementation (SIGTERM → grace → SIGKILL → force-close)
    is exercised by the dedicated tests in
    ``tests/scripts/test_agent_call_process_tree.py``.
    """
    fake_proc = MagicMock()
    fake_proc.stdin = MagicMock()
    fake_proc.stdout = iter(['{"type":"assistant","message":{"content":[]}}\n'])
    fake_proc.stderr = MagicMock(read=MagicMock(return_value=""))
    fake_proc.poll.return_value = None  # still running when timeout fires
    fake_proc.wait.side_effect = subprocess.TimeoutExpired("claude", 10)
    with (
        patch.object(ac.subprocess, "Popen", return_value=fake_proc),
        patch.object(ac, "_terminate_process_tree") as mock_kill_tree,
    ):
        ac.dispatch(
            "plan_narrator",
            "hi",
            vault_dir=claude_vault,
            cycle_dir=cycle_dir_for,
            timeout_s=10,
        )
    # Which process is terminated is the contract; how long it is given to
    # leave gracefully is the supervisor's business.
    mock_kill_tree.assert_called_once()
    assert mock_kill_tree.call_args.args == (fake_proc,)


# ---------------------------------------------------------------------------
# Fix 4 — _run_claude_with_cost parses stream events incrementally
# ---------------------------------------------------------------------------


def test_apply_stream_event_is_incremental(ac):
    """``_apply_stream_event`` updates a ``StreamCostResult`` in-place per
    event so callers can react to each event as it arrives, rather than
    buffering the entire stream and parsing at the end.
    """
    state = ac.StreamCostResult()
    # Initial state — no result event seen yet.
    assert state.saw_result is False
    assert state.cost_usd == 0.0
    ac._apply_stream_event(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
        state,
        capture_text=False,
    )
    # Still no terminal result.
    assert state.saw_result is False
    assert state.cost_usd == 0.0
    ac._apply_stream_event(
        {
            "type": "result",
            "subtype": "success",
            "total_cost_usd": 0.99,
            "usage": {"input_tokens": 42, "output_tokens": 7},
        },
        state,
        capture_text=False,
    )
    # Terminal envelope observed — cost + saw_result both updated.
    assert state.saw_result is True
    assert state.cost_usd == pytest.approx(0.99)
    assert state.tokens_in == 42
    assert state.tokens_out == 7


def test_run_claude_with_cost_does_not_buffer_all_lines(ac):
    """The streaming loop in ``_run_claude_with_cost`` should NOT collect
    every line into a ``captured_lines`` list before parsing — that
    behaviour both doubled memory usage and defeated the timeout (the
    read loop blocked indefinitely while ``proc.wait(timeout=...)``
    was never reached). The fix replaces that buffer with an incremental
    call to ``_apply_stream_event`` per event.
    """
    src = SCRIPT_PATH.read_text(encoding="utf-8")
    func_start = src.index("def _run_claude_with_cost(")
    func_end = src.index("\ndef _cycle_from_sidecar_path(", func_start)
    func_body = src[func_start:func_end]
    # Strip the docstring (which explains the OLD behaviour as motivation)
    # before searching for variable usage — the regression check is about
    # whether the executable code still maintains the captured_lines list.
    body_no_docstring = re.sub(r'"""[\s\S]*?"""', "", func_body, count=1)
    assert (
        "captured_lines = [" not in body_no_docstring
        and "captured_lines.append" not in body_no_docstring
    ), (
        "`_run_claude_with_cost` is still buffering all stdout lines "
        "before parsing (Copilot PR #28 review)."
    )
    # And the function should call `_apply_stream_event` (the incremental
    # shared parser) directly inside its read loop.
    assert "_apply_stream_event" in body_no_docstring, (
        "`_run_claude_with_cost` should use the shared `_apply_stream_event` "
        "helper for incremental parsing."
    )


# ---------------------------------------------------------------------------
# Fix 5 — Per-batch note_writer dispatch passes --batch-index / --topic-count
# ---------------------------------------------------------------------------


def test_research_step_passes_batch_flags_to_note_writer():
    """The per-batch note_writer dispatch in ``pipeline/steps/research.py``
    must pass ``--batch-index`` and ``--topic-count`` to ``agent_call.py``
    so the per-batch sidecar reports which batch and how many topics this
    invocation covered.

    Previously agent_call.py derived ``batch_index`` from the filename
    (e.g. ``note_writer-batch-3.json``) but ``topic_count`` had no
    derivation path and ended up null in every per-batch sidecar.
    """
    src = RESEARCH_STEP_PATH.read_text(encoding="utf-8")
    # Locate the per-batch dispatch — must contain BOTH new flags within
    # the same _run_script(...) invocation.
    match = re.search(
        r'_run_script\([^)]*?"--stage",\s*"note_writer".*?'
        r'"--batch-index",.*?"--topic-count",',
        src,
        re.DOTALL,
    )
    assert match is not None, (
        "Per-batch note_writer dispatch in research.py is missing "
        "--batch-index / --topic-count flags (Copilot PR #28 review)."
    )


# ---------------------------------------------------------------------------
# Fix 6 — status='ok' requires a terminal result event AND exit_code==0
# ---------------------------------------------------------------------------


def test_status_ok_requires_terminal_result_event(ac, claude_vault, cycle_dir_for):
    """If the stream-json output never contained a terminal
    ``{"type": "result"}`` envelope, the sidecar's ``status`` MUST be
    ``failed`` even if the subprocess exited 0. Pytest-style exit-code-
    only success checks are unreliable here: claude can exit cleanly
    mid-stream (network blip, truncated tool output) without emitting
    the terminal envelope, in which case the cost data we report would
    be stale / zero.
    """
    events = [
        '{"type":"assistant","message":{"content":[{"type":"text","text":"hi"}]}}',
        # NOTE: no terminal {"type":"result"} envelope.
    ]
    fake_proc = MagicMock()
    fake_proc.stdin = MagicMock()
    fake_proc.stdout = iter(line + "\n" for line in events)
    fake_proc.stderr = MagicMock(read=MagicMock(return_value=""))
    fake_proc.wait.return_value = 0  # exit 0 despite missing result
    with patch.object(ac.subprocess, "Popen", return_value=fake_proc):
        result = ac.dispatch(
            "plan_narrator", "hi", vault_dir=claude_vault, cycle_dir=cycle_dir_for
        )
    assert result.exit_code == 0  # exit_code propagates from proc.wait
    sidecar = cycle_dir_for / "agent-calls" / "plan_narrator.json"
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["status"] == "failed", (
        "Missing terminal `result` envelope must force status='failed' even "
        "when exit_code==0 (Copilot PR #28 review)."
    )
    assert payload["exit_code"] == 0


def test_status_ok_when_result_envelope_present(ac, claude_vault, cycle_dir_for):
    """Counterpart: a stream WITH a terminal result envelope and exit 0
    MUST produce status='ok'. Guards against an over-tightening of the
    fix that would always force 'failed' for the stream path."""
    events = [
        '{"type":"assistant","message":{"content":[{"type":"text","text":"hi"}]}}',
        '{"type":"result","subtype":"success","total_cost_usd":0.01,'
        '"usage":{"input_tokens":5,"output_tokens":5}}',
    ]
    fake_proc = MagicMock()
    fake_proc.stdin = MagicMock()
    fake_proc.stdout = iter(line + "\n" for line in events)
    fake_proc.stderr = MagicMock(read=MagicMock(return_value=""))
    fake_proc.wait.return_value = 0
    with patch.object(ac.subprocess, "Popen", return_value=fake_proc):
        result = ac.dispatch(
            "plan_narrator", "hi", vault_dir=claude_vault, cycle_dir=cycle_dir_for
        )
    assert result.exit_code == 0
    sidecar = cycle_dir_for / "agent-calls" / "plan_narrator.json"
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert payload["cost_usd"] == pytest.approx(0.01)


# ---------------------------------------------------------------------------
# Side-effect tests for the StreamCostResult.saw_result field
# ---------------------------------------------------------------------------


def test_stream_cost_result_defaults_saw_result_false(ac):
    """``saw_result`` defaults to ``False`` so callers that forget to
    check it default to the safe (failed) interpretation."""
    s = ac.StreamCostResult()
    assert s.saw_result is False


def test_consume_claude_stream_sets_saw_result_when_terminal_event_present(ac):
    """The batch parser (``_consume_claude_stream``) also updates
    ``saw_result`` so dispatch() can rely on the same flag whether the
    stream was consumed incrementally or all at once."""
    lines = [
        '{"type":"assistant","message":{"content":[]}}',
        '{"type":"result","subtype":"success","total_cost_usd":0.5,'
        '"usage":{"input_tokens":1,"output_tokens":1}}',
    ]
    result = ac._consume_claude_stream(line + "\n" for line in lines)
    assert result.saw_result is True
    assert result.cost_usd == pytest.approx(0.5)


def test_consume_claude_stream_saw_result_false_without_terminal(ac):
    lines = [
        '{"type":"assistant","message":{"content":[]}}',
    ]
    result = ac._consume_claude_stream(line + "\n" for line in lines)
    assert result.saw_result is False
    assert result.cost_usd == 0.0
