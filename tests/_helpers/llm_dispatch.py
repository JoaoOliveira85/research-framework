"""The single source of truth for "what counts as an LLM dispatch".

Two guards enforce Principle IV's single-dispatch-surface rule, and before
this module they each carried their OWN hand-maintained binary list:

- the **static** tier-2 guard (``tests/_helpers/test_llm_dispatch_guard.py``)
  — an AST scan of ``src/research_framework/**/*.py``;
- the **runtime** interception guard
  (``tests/quality/test_fake_agent_interception.py``) — a ``subprocess.Popen``
  / ``urllib.request.urlopen`` monkeypatch around a fixture cycle.

The two lists disagreed with each other (``cursor-agent`` was in one, not the
other) and both lagged the shipped executor set (neither knew ``opencode``,
spec 064). Both now read this module, which DERIVES its sets from
``scripts/agent_call.py`` — the canonical dispatch surface — so adding a sixth
executor there cannot silently un-guard it.

Two dispatch MODES exist, and a guard that only knows one is blind by
construction:

- **subprocess** — ``claude`` / ``codex`` / ``cursor-agent`` / ``opencode``
  (and ``ollama``'s own CLI, guarded for symmetry) are spawned with the binary
  as ``argv[0]``. Detected by :func:`is_llm_binary` / :func:`is_llm_command`.
- **HTTP** — ``ollama`` and any ``type: api`` executor never touch
  ``subprocess`` at all; ``agent_call._dispatch_http`` POSTs to an inference
  endpoint via ``urllib.request.urlopen``. Detected by
  :func:`is_inference_url`.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_CALL_PATH = REPO_ROOT / "scripts" / "agent_call.py"

_AGENT_CALL: ModuleType | None = None


def load_agent_call() -> ModuleType:
    """Load ``scripts/agent_call.py`` by path (it is a script, not a package).

    Mirrors ``research_framework.benchmark.matrix.valid_runtimes`` — the other
    consumer that already treats ``agent_call.py`` as the runtime registry.
    Cached so repeated guard calls don't re-exec the module.
    """
    global _AGENT_CALL
    if _AGENT_CALL is not None:
        return _AGENT_CALL
    mod_name = f"_llm_dispatch_agent_call_{abs(hash(str(AGENT_CALL_PATH))):x}"
    spec = importlib.util.spec_from_file_location(mod_name, AGENT_CALL_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover — defensive.
        raise RuntimeError(f"cannot load the dispatch registry from {AGENT_CALL_PATH}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec so module-level ``@dataclass`` can resolve
    # ``cls.__module__``; drop it afterwards so we don't leak a synthetic module.
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(mod_name, None)
    _AGENT_CALL = module
    return module


def llm_agent_names() -> frozenset[str]:
    """Every executor name ``agent_call.py`` recognises as an LLM agent.

    This is ``agent_call._LLM_AGENT_NAMES`` verbatim — the set that decides
    whether a dispatch is billed, sidecar-audited and fake-agent-substitutable.
    """
    return frozenset(load_agent_call()._LLM_AGENT_NAMES)


def http_runtimes() -> frozenset[str]:
    """Executor names dispatched over HTTP rather than a CLI subprocess."""
    return frozenset(load_agent_call()._HTTP_RUNTIMES)


def llm_binaries() -> frozenset[str]:
    """Binary names that, as ``argv[0]``, mean "a live LLM was spawned".

    Deliberately the WHOLE agent set, HTTP runtimes included: ``ollama`` ships a
    real CLI, so ``subprocess.run(["ollama", "run", …])`` inside the pipeline
    package is just as much a Principle-IV bypass as a ``claude`` spawn, even
    though the framework's own ollama support goes over HTTP. Guarding a name
    the framework does not itself spawn costs nothing; missing one costs an
    un-audited call.
    """
    return llm_agent_names()


# Path fragments that only appear on a model-inference endpoint. Verified
# absent from every URL literal under ``src/research_framework/`` — the
# legitimate outbound HTTP there (collectors, source preflight, refresh) hits
# feeds and repo APIs, never an inference route.
INFERENCE_PATH_MARKERS: tuple[str, ...] = (
    "/v1/chat/completions",
    "/v1/completions",
    "/v1/responses",
    "/v1/messages",
    "/api/chat",
    "/api/generate",
    "/api/embeddings",
)

# Hosts (and the Ollama default port) that serve nothing but inference.
INFERENCE_HOST_MARKERS: tuple[str, ...] = (
    "api.anthropic.com",
    "api.openai.com",
    "api.mistral.ai",
    "api.cohere.ai",
    "api.groq.com",
    "generativelanguage.googleapis.com",
    "openrouter.ai",
    ":11434",  # ollama's default port, on any host
)


def _basename(argv0: str) -> str:
    """``argv[0]`` → bare binary name, for POSIX and Windows separators alike.

    ``CLAUDE_BIN=/opt/homebrew/bin/claude`` and a bare ``claude`` are the same
    dispatch; both guards must see them the same way.
    """
    text = str(argv0)
    name = PurePosixPath(PureWindowsPath(text).as_posix()).name
    return name or os.path.basename(text)


def is_llm_binary(argv0: object) -> bool:
    """True when ``argv0`` names a live LLM binary (path or bare name)."""
    if not isinstance(argv0, (str, os.PathLike)):
        return False
    return _basename(os.fspath(argv0)) in llm_binaries()


def is_llm_command(cmd: object) -> bool:
    """True when ``cmd`` is an argv sequence whose executable is an LLM binary.

    Only ``cmd[0]`` is inspected. Scanning the joined arg string
    false-positives whenever a path argument merely contains ``claude`` /
    ``codex`` — e.g. a ``$TMPDIR`` like ``/tmp/claude-502/…``. A real live call
    appears as the binary itself; fixture dispatch is
    ``[python, …/scripts/agent_call.py, …]``.
    """
    if isinstance(cmd, (str, bytes, os.PathLike)):
        return False
    try:
        first = next(iter(cmd))  # type: ignore[call-overload]
    except (TypeError, StopIteration):
        return False
    return is_llm_binary(first)


def is_inference_url(url: object) -> bool:
    """True when ``url`` addresses a model-inference endpoint.

    Substring matching on the raw text (not a parsed URL) on purpose: the
    static guard feeds it *fragments* — the halves of a ``base + path``
    concatenation, or an f-string's literal parts — which are never
    well-formed URLs on their own.
    """
    if not isinstance(url, (str, bytes)):
        return False
    text = url.decode("utf-8", "replace") if isinstance(url, bytes) else url
    lowered = text.lower()
    return any(m in lowered for m in INFERENCE_PATH_MARKERS) or any(
        m in lowered for m in INFERENCE_HOST_MARKERS
    )
