"""Tier-2 parity guard: the fake agent must really be a drop-in (issue #262).

``tests/_helpers/fake_agent.py`` claims in its docstring to stand in for
``scripts/agent_call.py``. Three separate surfaces have to hold for that claim
to be true, and until this module each was only asserted by prose:

- **argv** — every flag the real CLI accepts, the fake must accept, and the
  fake must not *demand* one the real CLI leaves optional (``--prompt-file``
  did exactly that: the real dispatcher falls back to stdin).
- **the in-process ``dispatch()``** the shim installs — its signature must
  cover the real one's. It did not carry ``model=``, which
  ``processors/extract.py`` passes on every call, so the extract → agent_call
  seam ``TypeError``ed under the shim and the extract tests worked around it
  by stubbing the bootstrap entirely.
- **the cost sidecar** — the fake wrote schema 1.1 without ``cost_source``
  while the real writer had moved to 1.2, and it wrote a sidecar only on the
  success path, so ``status: "failed"`` telemetry was never exercised.

Each assertion DERIVES its expectation from ``scripts/agent_call.py`` rather
than restating it, so adding a flag, a dispatch parameter or a sidecar key
there fails here instead of silently widening the gap. That derivation is the
whole point: a hand-maintained copy of the contract is what let #259, #260 and
the three gaps above coexist with a green suite.
"""

from __future__ import annotations

import argparse
import inspect
import json
import types
from pathlib import Path

import pytest

from tests._helpers import fake_agent
from tests._helpers.llm_dispatch import load_agent_call

# ---------------------------------------------------------------------------
# Deriving the real contract
# ---------------------------------------------------------------------------


class _ParserCaptured(Exception):
    """Carries the parser out of a ``main()`` we interrupt at ``parse_args``."""

    def __init__(self, parser: argparse.ArgumentParser) -> None:
        super().__init__("parser captured")
        self.parser = parser


def _capture_parser(main, monkeypatch: pytest.MonkeyPatch) -> argparse.ArgumentParser:
    """Return the parser *main* actually parses argv with.

    Intercepting ``parse_args`` rather than calling a ``_build_parser()``
    helper is deliberate: it pins the object the entry point uses, so a
    factory that ``main`` stopped calling cannot satisfy this guard.
    """

    def _spy(self: argparse.ArgumentParser, *args: object, **kwargs: object):
        raise _ParserCaptured(self)

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", _spy)
    with pytest.raises(_ParserCaptured) as excinfo:
        main([])
    return excinfo.value.parser


def _options(parser: argparse.ArgumentParser) -> dict[str, argparse.Action]:
    """Every option string the parser accepts, minus argparse's own ``--help``."""
    return {
        option: action
        for action in parser._actions
        for option in action.option_strings
        if option not in ("-h", "--help")
    }


def _real() -> types.ModuleType:
    return load_agent_call()


@pytest.fixture
def real_options(monkeypatch: pytest.MonkeyPatch) -> dict[str, argparse.Action]:
    return _options(_capture_parser(_real().main, monkeypatch))


@pytest.fixture
def fake_options(monkeypatch: pytest.MonkeyPatch) -> dict[str, argparse.Action]:
    return _options(_capture_parser(fake_agent.main, monkeypatch))


# ---------------------------------------------------------------------------
# argv
# ---------------------------------------------------------------------------


def test_fake_cli_accepts_every_flag_the_real_cli_accepts(
    real_options: dict[str, argparse.Action],
    fake_options: dict[str, argparse.Action],
) -> None:
    missing = sorted(set(real_options) - set(fake_options))
    assert not missing, (
        f"the fake agent rejects flags scripts/agent_call.py accepts: {missing}. "
        "A stage that starts passing one of these would fail under the fake "
        "with an argparse error that reads like a test-harness bug."
    )


def test_fake_cli_requires_nothing_the_real_cli_makes_optional(
    real_options: dict[str, argparse.Action],
    fake_options: dict[str, argparse.Action],
) -> None:
    over_required = sorted(
        option
        for option, action in fake_options.items()
        if action.required and not real_options.get(option, action).required
    )
    assert not over_required, (
        f"the fake agent demands flags the real CLI makes optional: "
        f"{over_required}. The real dispatcher falls back to stdin for the "
        "prompt; a caller that relies on that fails only under the fake."
    )


def test_fake_cli_reads_the_prompt_from_stdin_like_the_real_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``_read_prompt(None)`` reads stdin; the fake must do the same."""
    vault = _minimal_narrator_vault(tmp_path)
    monkeypatch.setattr("sys.stdin", _StdinStub("Cycle 2 plan narration request."))

    rc = fake_agent.main(["--vault", str(vault), "--stage", "research_plan_narrator"])

    assert rc == 0
    assert capsys.readouterr().out.strip()


class _StdinStub:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text


def _minimal_narrator_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "_pipeline").mkdir(parents=True)
    return vault


# ---------------------------------------------------------------------------
# The in-process dispatch() the shim installs
# ---------------------------------------------------------------------------


@pytest.fixture
def shim_dispatch(tmp_path: Path):
    """The ``dispatch`` from a freshly installed shim, loaded as a module."""
    import importlib.util

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    shim_path = fake_agent.install_shim(scripts_dir)
    spec = importlib.util.spec_from_file_location("parity_shim", shim_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.dispatch


def test_shim_dispatch_covers_every_real_dispatch_parameter(shim_dispatch) -> None:
    real = inspect.signature(_real().dispatch).parameters
    shim = inspect.signature(shim_dispatch).parameters
    missing = [name for name in real if name not in shim]
    assert not missing, (
        f"the shim's dispatch() is missing parameters the real one has: "
        f"{missing}. Every caller passing one of these TypeErrors under the "
        "fake — which is why the extract seam had to stub the bootstrap."
    )


def test_shim_dispatch_keeps_the_real_keyword_only_boundary(shim_dispatch) -> None:
    real = inspect.signature(_real().dispatch).parameters
    shim = inspect.signature(shim_dispatch).parameters
    mismatched = sorted(
        name
        for name, param in real.items()
        if name in shim and shim[name].kind is not param.kind
    )
    assert not mismatched, (
        f"the shim's dispatch() binds these differently from the real one: "
        f"{mismatched}. A positional/keyword-only difference makes a call site "
        "that works in production fail under the fake."
    )


def test_shim_dispatch_accepts_the_model_kwarg_extract_passes(
    shim_dispatch, tmp_path: Path
) -> None:
    """``processors/extract.py`` passes ``model=`` on every dispatch."""
    result = shim_dispatch(
        stage="processor_extract",
        prompt="extract this",
        vault_dir=tmp_path,
        timeout_s=30,
        model="claude-sonnet-4-5",
    )
    # No in-process handler for the extract stages — but the call must reach
    # that decision rather than dying in argument binding.
    assert result.exit_code == 1
    assert "no in-process handler" in result.stderr


# ---------------------------------------------------------------------------
# The cost sidecar
# ---------------------------------------------------------------------------


def _real_sidecar_payload() -> dict[str, object]:
    return _real()._build_sidecar_v11_payload(
        stage="scout",
        agent="claude",
        agent_kind="real",
        tier="standard",
        status="ok",
        exit_code=0,
        cost_usd=0.0,
        tokens_in=0,
        tokens_out=0,
        latency_ms=0,
        started_at="2000-01-01T00:00:00Z",
        completed_at="2000-01-01T00:00:01Z",
        cycle=1,
    )


def _fake_sidecar_payload(tmp_path: Path) -> dict[str, object]:
    path = tmp_path / "scout.json"
    fake_agent._write_cost_sidecar_v11(path, stage="scout", cycle=1, scenario="happy")
    return json.loads(path.read_text(encoding="utf-8"))


def test_fake_sidecar_carries_every_key_the_real_sidecar_carries(
    tmp_path: Path,
) -> None:
    missing = sorted(
        set(_real_sidecar_payload()) - set(_fake_sidecar_payload(tmp_path))
    )
    assert not missing, (
        f"the fake's cost sidecar omits keys the real writer always emits: "
        f"{missing}. Every reader of the agent-calls index (budget guard, "
        "digest, run report) sees a shape in tests that production never "
        "produces."
    )


def test_fake_sidecar_declares_the_real_schema_version(tmp_path: Path) -> None:
    assert (
        _fake_sidecar_payload(tmp_path)["schema_version"]
        == _real()._SIDECAR_SCHEMA_VERSION
    )


def test_fake_sidecar_uses_a_real_cost_source_literal(tmp_path: Path) -> None:
    """``cost_source`` is a closed vocabulary; a typo reads as a new source."""
    real = _real()
    literals = {
        value
        for name, value in vars(real).items()
        if name.startswith("_COST_SOURCE_") and isinstance(value, str)
    }
    assert literals, "no _COST_SOURCE_* literals found in scripts/agent_call.py"
    assert _fake_sidecar_payload(tmp_path)["cost_source"] in literals


def test_fake_records_a_failed_stage_in_its_sidecar(tmp_path: Path) -> None:
    """A stage the fake refuses must still leave failure telemetry behind.

    The real dispatcher writes a ``status: "failed"`` sidecar carrying the
    exit code, so a failed stage is visible in the ``agent-calls`` index. The
    fake returned 2 before it ever reached the sidecar block, so nothing
    downstream of a failure was exercised end to end.
    """
    vault = tmp_path / "vault"
    (vault / "_pipeline").mkdir(parents=True)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Cycle 1 prompt.\n", encoding="utf-8")
    sidecar = tmp_path / "agent-calls" / "nonexistent_stage.json"

    rc = fake_agent.main(
        [
            "--vault",
            str(vault),
            "--stage",
            "nonexistent_stage",
            "--prompt-file",
            str(prompt),
            "--cost-sidecar",
            str(sidecar),
        ]
    )

    assert rc == 2
    assert sidecar.is_file(), "no sidecar written for a failed stage"
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["exit_code"] == 2
    assert payload["stderr_excerpt"]
