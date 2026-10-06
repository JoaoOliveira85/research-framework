"""Tier-6 e2e: fake agent intercepts LLM calls (T043 / US3 scenario 4).

The runtime half of the Principle-IV single-dispatch guard. Its static sibling
(``tests/_helpers/test_llm_dispatch_guard.py``) reads source; this one runs a
fixture cycle with both dispatch seams monkeypatched and fails if a live model
was reached.

Both seams are patched because the framework ships both (issue #292):
``subprocess.Popen`` for the CLI executors, and ``urllib.request.urlopen`` for
``ollama`` / any ``type: api`` executor, which never touches ``subprocess`` at
all. Both read their subject set from ``tests._helpers.llm_dispatch``, so this
guard and the static one cannot drift apart again.
"""

from __future__ import annotations

import subprocess
import urllib.request
from typing import Any

import pytest

from tests._helpers.llm_dispatch import is_inference_url, is_llm_command
from tests.quality.conftest import run_fixture_cycles

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


def test_no_live_claude_or_codex_during_fixture_run(
    tmp_path,
    quality_fixture_env,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No fixture-cycle dispatch may reach a live LLM, by subprocess or HTTP.

    The name is historical (spec 022 / 049 name this test by id and the
    CHANGELOG cites it); the subject is now every shipped executor, not just
    ``claude``/``codex``.
    """
    quality_fixture_env("tech-lite")
    monkeypatch.setenv("FAKE_AGENT_SCOUT_SCENARIO", "happy")
    monkeypatch.setenv("FAKE_AGENT_NOTE_WRITER_SCENARIO", "happy")

    live_binaries: list[list[str]] = []
    inference_urls: list[str] = []
    dispatched: list[list[str]] = []
    real_popen = subprocess.Popen
    real_urlopen = urllib.request.urlopen

    def guarded_popen(*args: Any, **kwargs: Any) -> subprocess.Popen:
        cmd = args[0] if args else kwargs.get("args") or []
        if isinstance(cmd, (list, tuple)) and cmd:
            argv = [str(x) for x in cmd]
            if is_llm_command(argv):
                live_binaries.append(argv)
            elif any(a.endswith("agent_call.py") for a in argv):
                # The fake-agent shim's shape: [python, …/scripts/agent_call.py, …].
                dispatched.append(argv)
        return real_popen(*args, **kwargs)

    def guarded_urlopen(url: Any, *args: Any, **kwargs: Any) -> Any:
        target = getattr(url, "full_url", None) or url
        if is_inference_url(str(target)):
            inference_urls.append(str(target))
        return real_urlopen(url, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", guarded_popen)
    monkeypatch.setattr(urllib.request, "urlopen", guarded_urlopen)
    run_fixture_cycles("tech-lite", tmp_path=tmp_path, max_cycles=3)

    # Non-vacuity: a guard that observed no dispatch at all proves nothing about
    # dispatch being clean. If the cycle stopped spawning agent_call.py, this
    # test must fail loudly rather than pass green on an empty observation.
    assert dispatched, (
        "no agent_call.py dispatch observed during the fixture cycle — the guard "
        "asserted cleanliness over zero traffic"
    )
    assert live_binaries == [], f"live LLM subprocess started: {live_binaries}"
    assert inference_urls == [], f"live inference endpoint called: {inference_urls}"
