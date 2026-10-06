"""Issue #157 — ``_detect_agent_kind`` must not self-mark production as fake.

Spec 028 ``agent_kind`` is the honesty signal: ``real`` means "this dispatch
hit a billed runtime", ``fake`` means "test/stub". The vault-shim heuristic
in ``_detect_agent_kind`` substring-matched ``"fake_agent"`` against the
contents of ``<vault>/scripts/agent_call.py`` — but that string ALSO appears
in the production shim itself (in the very line that does the check), causing
every real cursor-agent / claude / codex dispatch on a production vault to
be tagged ``agent_kind: "fake"`` with sentinel ``2000-01-01T00:00:00Z``
timestamps. Surfaced live by the rc7 reference-vault validation run (umbrella #152).

Mirrors the same kind of regression the Ollama HTTP path already guards
against (see ``test_run_ollama_stays_real_even_with_fake_shim`` — the comment
at lines 2286-2291 of ``scripts/agent_call.py`` explicitly describes this
class of bug).

The fix tightens the heuristic to match a marker that ONLY the fake-agent
shim carries (``_BAKED_REPO_ROOT`` from the install-time template), so the
production shim no longer self-matches.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_SHIM_PATH = REPO_ROOT / "scripts" / "agent_call.py"


def _load_agent_call():
    spec = importlib.util.spec_from_file_location("agent_call", PRODUCTION_SHIM_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["agent_call"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def agent_call():
    return _load_agent_call()


# ---------------------------------------------------------------------------
# The bug: production shim self-detects as fake
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "runtime",
    ["cursor-agent", "claude", "codex", "ollama", "opencode"],
)
def test_production_shim_classifies_every_llm_runtime_as_real(
    agent_call, tmp_path: Path, runtime: str
) -> None:
    """A vault carrying the PRODUCTION ``scripts/agent_call.py`` must
    classify every LLM runtime as ``real``.

    Pre-fix, the substring check matched the production shim's own
    ``if "fake_agent" in text or "tests._helpers" in text:`` line, so the
    function self-detected as fake. This regression specifically guards
    the rc7 cursor-agent path that landed ``agent_kind: "fake"`` /
    sentinel timestamps in every sidecar.
    """
    vault = tmp_path / "v"
    (vault / "scripts").mkdir(parents=True)
    (vault / "scripts" / "agent_call.py").write_text(
        PRODUCTION_SHIM_PATH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    assert agent_call._detect_agent_kind(runtime, vault) == "real", (
        f"production shim must classify {runtime!r} as 'real'; got 'fake' "
        f"(self-referential substring bug — see issue #157)"
    )


def test_production_shim_classifies_unknown_agent_as_fake(
    agent_call, tmp_path: Path
) -> None:
    """The pre-existing ``agent_name not in _LLM_AGENT_NAMES`` early-return
    is unchanged: an unknown runtime IS fake (e.g. the literal string
    ``"fake"`` from a settings stub)."""
    vault = tmp_path / "v"
    (vault / "scripts").mkdir(parents=True)
    (vault / "scripts" / "agent_call.py").write_text(
        PRODUCTION_SHIM_PATH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    assert agent_call._detect_agent_kind("fake", vault) == "fake"
    assert agent_call._detect_agent_kind("bogus-runtime", vault) == "fake"


# ---------------------------------------------------------------------------
# The fake-detection path still works
# ---------------------------------------------------------------------------


def test_fake_agent_shim_still_classifies_as_fake(agent_call, tmp_path: Path) -> None:
    """The fix tightens the heuristic without breaking the fake-detection
    path. ``tests._helpers.fake_agent.install_shim`` writes a shim whose
    template carries the ``_BAKED_REPO_ROOT`` marker; the production
    shim never references that name, so the marker uniquely identifies
    the test stub."""
    from tests._helpers import fake_agent

    vault = tmp_path / "v"
    (vault / "scripts").mkdir(parents=True)
    fake_agent.install_shim(vault / "scripts")

    for runtime in ["cursor-agent", "claude", "codex"]:
        assert agent_call._detect_agent_kind(runtime, vault) == "fake", (
            f"fake-agent shim must classify {runtime!r} as 'fake'; got 'real'"
        )


def test_no_vault_dir_defaults_to_real_for_known_runtimes(agent_call) -> None:
    """When called without a vault_dir (e.g. benchmark harness, contract
    tests), the shim heuristic doesn't apply — a known LLM runtime is
    'real' on the trust of the agent name alone."""
    for runtime in ["cursor-agent", "claude", "codex", "ollama"]:
        assert agent_call._detect_agent_kind(runtime, None) == "real"
    assert agent_call._detect_agent_kind("fake", None) == "fake"


# ---------------------------------------------------------------------------
# Self-reference guard (the actual root-cause invariant)
# ---------------------------------------------------------------------------


def test_production_agent_call_does_not_contain_fake_marker_substring() -> None:
    """Issue #157 root-cause invariant: the production scripts/agent_call.py
    MUST NOT contain the fake-shim marker as a contiguous substring.

    The marker is assembled at import time from string-tuple ``"".join(...)``
    so the literal form doesn't appear in the source. If a future refactor
    regresses this (e.g. inlining the literal back, or collapsing the join
    to a single ``"_BAK" + "ED_..."`` form that Ruff constant-folds), this
    test fails before the bug reaches production.

    The marker name is itself reconstructed from parts so THIS test file
    can be safely referenced from agent_call.py without contaminating it.
    """
    text = PRODUCTION_SHIM_PATH.read_text(encoding="utf-8")
    forbidden = "".join(("_BAKED", "_REPO", "_ROOT"))
    assert forbidden not in text, (
        f"production scripts/agent_call.py contains {forbidden!r} as a "
        f"contiguous substring — _FAKE_SHIM_MARKER must be assembled at "
        f"import time (see issue #157 for why)."
    )
