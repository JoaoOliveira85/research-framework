"""Tier-2: the two LLM-dispatch guards must agree, on every shipped executor.

Issue #292: the static guard (``test_llm_dispatch_guard.py``) and the runtime
interception guard (``tests/quality/test_fake_agent_interception.py``) each
carried a hand-written binary list. The lists disagreed with each other
(``cursor-agent`` in one, not the other) and both lagged the shipped set
(neither knew ``opencode``, and the HTTP executor path was invisible to both).

This module builds each executor's REAL dispatch shape from
``scripts/agent_call.py`` — the same ``_build_command`` / ``_http_endpoint``
the pipeline uses — and asserts both guards classify it the same way. A sixth
executor added to ``agent_call`` fails here until both guards see it, because
the shapes are derived rather than transcribed.
"""

from __future__ import annotations

from typing import Any, get_args

import pytest

from research_framework.pipeline.settings import DefaultAgent
from tests._helpers.llm_dispatch import (
    http_runtimes,
    is_inference_url,
    is_llm_command,
    llm_agent_names,
    llm_binaries,
    load_agent_call,
)
from tests._helpers.test_llm_dispatch_guard import _violations_in_module

# ``agent_call`` reads these to let an operator relocate a binary. They must be
# unset so ``argv[0]`` is the canonical name the guards are asserted against.
_BIN_ENV_VARS = ("CLAUDE_BIN", "CODEX_BIN", "CURSOR_BIN", "OPENCODE_BIN")


@pytest.fixture
def agent_call(monkeypatch: pytest.MonkeyPatch) -> Any:
    for var in _BIN_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    return load_agent_call()


def _cli_runtimes() -> list[str]:
    """Shipped LLM executors dispatched as a CLI subprocess."""
    return sorted(llm_agent_names() - http_runtimes())


def _static_guard_flags(source: str) -> list[str]:
    """Violation kinds the static guard reports for a source snippet."""
    return [v.kind for v in _violations_in_module("probe.py", source)]


# ---------------------------------------------------------------------------
# The shipped set is one set, and every consumer reads it
# ---------------------------------------------------------------------------


def test_guard_subject_set_equals_the_settings_literal() -> None:
    """Closes the loop: settings' ``DefaultAgent`` and the guards' subject set
    are the same names. A new executor added to one and not the other fails."""
    assert llm_binaries() == frozenset(get_args(DefaultAgent))


def test_both_guards_read_the_same_source_of_truth() -> None:
    """Not "the lists happen to match" — there is only ONE list."""
    from tests import _helpers
    from tests._helpers import test_llm_dispatch_guard as static_guard
    from tests.quality import test_fake_agent_interception as runtime_guard

    assert static_guard.llm_binaries is _helpers.llm_dispatch.llm_binaries
    assert runtime_guard.is_llm_command is _helpers.llm_dispatch.is_llm_command
    assert runtime_guard.is_inference_url is _helpers.llm_dispatch.is_inference_url
    # No guard may re-declare a private binary list of its own.
    assert not hasattr(static_guard, "_LLM_BINARIES")
    assert not hasattr(runtime_guard, "_LLM_BINARIES")


def test_every_dispatchable_llm_runtime_is_guarded(agent_call: Any) -> None:
    """``_RUNTIME_ADAPTERS`` ∪ ``_HTTP_RUNTIMES`` minus the non-LLM ``python``
    script adapter is exactly the guarded set — no adapter ships unguarded."""
    dispatchable = set(agent_call._RUNTIME_ADAPTERS) | set(agent_call._HTTP_RUNTIMES)
    assert dispatchable - {"python"} == set(llm_binaries())


# ---------------------------------------------------------------------------
# Per-executor dispatch shapes — built by agent_call, judged by both guards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("runtime", _cli_runtimes())
def test_cli_executor_shape_is_flagged_by_both_guards(
    runtime: str, agent_call: Any, tmp_path: Any
) -> None:
    """Build the runtime's real argv, then assert both guards call it dispatch."""
    executor = {"runtime": runtime, "model": "some-model", "args": []}
    cmd = agent_call._build_command(executor, tmp_path)

    # Runtime guard: the argv it would see from a monkeypatched Popen.
    assert is_llm_command(cmd), f"runtime guard misses {runtime}: {cmd}"

    # Static guard: the same argv written as a subprocess call in source.
    argv = ", ".join(repr(str(part)) for part in cmd)
    source = f"import subprocess\ndef bad():\n    subprocess.run([{argv}])\n"
    assert _static_guard_flags(source) == ["subprocess"], (
        f"static guard misses {runtime}: {cmd}"
    )


def test_http_executor_shape_is_flagged_by_both_guards(agent_call: Any) -> None:
    """The HTTP executor never spawns a subprocess, so neither guard can see it
    through ``argv[0]``. Both must recognise the inference ENDPOINT instead."""
    runtimes = sorted(http_runtimes())
    assert runtimes, "the framework ships at least one HTTP-dispatched runtime"
    for runtime in runtimes:
        executor = {"runtime": runtime, "model": "some-model", "args": []}
        assert agent_call._is_http_executor(executor)
        endpoint = agent_call._http_endpoint(executor)

        # Runtime guard: what a monkeypatched urlopen would see.
        assert is_inference_url(endpoint), f"runtime guard misses {runtime}: {endpoint}"

        # Static guard: the same endpoint posted from source.
        source = (
            "import urllib.request\n"
            "def bad(payload):\n"
            f"    req = urllib.request.Request({endpoint!r}, data=payload)\n"
            "    return urllib.request.urlopen(req)\n"
        )
        # Both the ``Request`` that carries the URL and the ``urlopen`` that
        # sends it are reported — two call sites, one dispatch.
        flags = _static_guard_flags(source)
        assert flags and set(flags) == {"http"}, (
            f"static guard misses {runtime}: {endpoint}"
        )


def test_type_api_executor_endpoint_is_flagged(agent_call: Any) -> None:
    """``type: api`` reaches HTTP dispatch on any runtime name, so the endpoint
    — not the name — has to be what the guards key on."""
    executor = {
        "runtime": "some-vendor",
        "type": "api",
        "base_url": "https://api.openai.com",
        "api_path": "/v1/chat/completions",
        "model": "m",
        "args": [],
    }
    assert agent_call._is_http_executor(executor)
    assert is_inference_url(agent_call._http_endpoint(executor))


def test_fake_agent_dispatch_shape_is_not_flagged() -> None:
    """The negative half of the parity contract: the fixture cycle's own
    dispatch (``[python, …/scripts/agent_call.py, …]``) must stay clean, or the
    runtime guard would fail every e2e run."""
    cmd = ["/usr/bin/python3", "/tmp/vault/scripts/agent_call.py", "--stage", "scout"]
    assert not is_llm_command(cmd)
    # A $TMPDIR that merely contains a binary name is not a dispatch either.
    assert not is_llm_command(["/usr/bin/python3", "/tmp/claude-502/agent_call.py"])
