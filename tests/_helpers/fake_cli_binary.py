"""Fake at the CLI-BINARY seam, not at ``agent_call.py`` (issue #270).

``fake_agent.install_shim`` replaces the vault's whole ``scripts/agent_call.py``
with a stub. That is cheap and fast, and it is why the *dispatcher* — argv
construction per runtime, the prompt-on-stdin convention, stream-json framing,
the cost parser, sidecar v1.2, the failure sidecar, the ``dispatch()``
signature — has never executed on an e2e path. Two shipped defects lived in
exactly that blind spot: a ``NameError`` in the shim's ``dispatch`` (#259) and
a missing ``model`` kwarg (#262).

This module moves the fake one level DOWN. The vault keeps the real
``agent_call.py``; what gets replaced is the leaf ``claude`` / ``codex``
binary. Everything above the fork is production code.

Three properties make it a seam rather than a hole:

1. **The stub validates the argv it is handed.** ``parse_argv`` encodes what
   each real CLI requires — ``--model <m>`` and ``--print`` for claude, the
   ``exec`` subcommand for codex — and refuses anything else with exit 2. If
   ``_claude_cmd`` regresses, the test that drives it goes red instead of
   quietly passing on a stub that ignores argv.
2. **The stub writes no telemetry.** No cost sidecar, no cost line on stdout.
   Every sidecar a binary-seam test reads was written by ``agent_call.py``, so
   asserting on one is asserting on production code.
3. **It fails closed.** No call context in the environment ⇒ exit 2, not a
   cheerful exit 0 having done nothing.

The stub reaches the stage behaviour by delegating to :mod:`tests._helpers.
fake_agent` — the canned scenarios stay in one place. What it does NOT reuse
is that module's sidecar writer, for reason 2.

**Which tier uses which fake.** The in-process fake stays the default for the
fast loop and for the quality fixtures (issue #270 says so explicitly): it is
one process, no PATH manipulation, no subprocess per stage. The binary seam is
for the tier-5 pack, where the cost of a subprocess buys the dispatcher's own
coverage.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import stat
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import IO

from tests._helpers import fake_agent

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_CALL_PATH = REPO_ROOT / "scripts" / "agent_call.py"

#: Runtimes this module can fake. Kept to the two the issue names; a third
#: needs its own ``parse_argv`` branch, not a default-allow fallback.
SUPPORTED_RUNTIMES: tuple[str, ...] = ("claude", "codex")

#: Written by ``agent_call._set_call_context``; read here. Named as literals
#: rather than imported so a rename in the dispatcher shows up as a red test
#: (``test_agent_call_publishes_the_call_context_to_its_child``) instead of a
#: silently-agreeing constant.
VAULT_ENV = "RESEARCH_FRAMEWORK_VAULT"
STAGE_ENV = "RESEARCH_FRAMEWORK_STAGE"

#: Dollar figure the fake claude reports in its terminal stream-json event.
#: Default $0 matches what the in-process fake records, so migrating a test to
#: this seam does not silently change its budget arithmetic.
COST_ENV = "FAKE_CLI_COST_USD"


class ArgvContractError(RuntimeError):
    """The dispatcher built an argv the real CLI would have rejected."""


@dataclass(frozen=True)
class ArgvShape:
    """What the stub understood from the argv it was handed."""

    runtime: str
    model: str
    stream_json: bool
    workdir: str | None = None


# ---------------------------------------------------------------------------
# argv contracts
# ---------------------------------------------------------------------------


def _flag_value(argv: list[str], flag: str) -> str | None:
    if flag in argv:
        idx = argv.index(flag)
        if idx + 1 < len(argv):
            return argv[idx + 1]
    return None


def _require_model(runtime: str, argv: list[str]) -> str:
    model = _flag_value(argv, "--model")
    if not model or model.startswith("-"):
        raise ArgvContractError(
            f"{runtime}: no `--model <name>` in argv {argv!r}. The dispatcher "
            "must name a model; without one the real CLI falls back to the "
            "operator's default and the vault's settings.yaml is ignored."
        )
    return model


def parse_argv(runtime: str, argv: Iterable[str]) -> ArgvShape:
    """Read *argv* as the real CLI would, raising on a shape it would reject.

    This is the assertion the seam is worth having. A fake binary that
    shrugged at its argv would let ``_claude_cmd`` drop ``--print`` (the real
    CLI then waits for an interactive session and the stage hangs) without a
    single test noticing.
    """
    args = [str(a) for a in argv]
    if runtime == "claude":
        model = _require_model(runtime, args)
        if "--print" not in args:
            raise ArgvContractError(
                f"claude: no `--print` in argv {args!r}. Non-interactive "
                "dispatch requires it; the real CLI would sit waiting for a "
                "terminal that a pipeline subprocess does not have."
            )
        stream_json = _flag_value(args, "--output-format") == "stream-json"
        if stream_json and "--verbose" not in args:
            raise ArgvContractError(
                "claude: `--output-format stream-json` without `--verbose`; "
                "the real CLI emits no per-event stream in that combination, "
                "so the cost parser would see nothing."
            )
        return ArgvShape(runtime="claude", model=model, stream_json=stream_json)
    if runtime == "codex":
        if not args or args[0] != "exec":
            raise ArgvContractError(
                f"codex: argv {args!r} does not start with the `exec` "
                "subcommand — the canonical non-interactive entry point."
            )
        model = _require_model(runtime, args)
        return ArgvShape(
            runtime="codex",
            model=model,
            stream_json=False,
            workdir=_flag_value(args, "--cd"),
        )
    raise ArgvContractError(
        f"{runtime!r} is not a faked runtime; add a branch to parse_argv "
        f"(supported: {', '.join(SUPPORTED_RUNTIMES)})"
    )


# ---------------------------------------------------------------------------
# stream-json framing
# ---------------------------------------------------------------------------


def stream_json_events(
    text: str, *, cost_usd: float, tokens_in: int, tokens_out: int, is_error: bool
) -> str:
    """The NDJSON a real ``claude --output-format stream-json`` would emit.

    Shapes match what ``agent_call._extract_text_from_event`` and
    ``_apply_stream_event`` read: an ``assistant`` envelope carrying text
    blocks, then the terminal ``result`` envelope carrying ``total_cost_usd``
    and ``usage``. The real parser does the reading — that is the point.
    """
    events: list[dict[str, object]] = []
    if text:
        events.append(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": text}]},
            }
        )
    events.append(
        {
            "type": "result",
            "subtype": "error_during_execution" if is_error else "success",
            "is_error": is_error,
            "result": "",
            "total_cost_usd": cost_usd,
            "duration_ms": 1,
            "session_id": "fake-cli-binary",
            "usage": {"input_tokens": tokens_in, "output_tokens": tokens_out},
        }
    )
    return "".join(json.dumps(event) + "\n" for event in events)


# ---------------------------------------------------------------------------
# the stub entry point
# ---------------------------------------------------------------------------


def _call_context() -> tuple[Path, str] | None:
    vault = os.environ.get(VAULT_ENV)
    stage = os.environ.get(STAGE_ENV)
    if not vault or not stage:
        return None
    return Path(vault), stage


def stub_main(
    runtime: str,
    argv: Iterable[str],
    *,
    stdin: IO[str] | None = None,
    stdout: IO[str] | None = None,
) -> int:
    """Body of the installed fake binary. Returns its exit code."""
    out = stdout if stdout is not None else sys.stdout
    try:
        shape = parse_argv(runtime, argv)
    except ArgvContractError as exc:
        print(f"fake-cli: {exc}", file=sys.stderr)
        return 2

    context = _call_context()
    if context is None:
        print(
            f"fake-cli {runtime}: no call context. Expected {VAULT_ENV} and "
            f"{STAGE_ENV} in the environment — agent_call.py publishes both "
            "before spawning a runtime. Exiting 2 rather than reporting a "
            "success that wrote nothing.",
            file=sys.stderr,
        )
        return 2
    vault, stage = context

    prompt = (stdin if stdin is not None else sys.stdin).read()
    with tempfile.TemporaryDirectory(prefix="fake-cli-binary-") as scratch:
        prompt_file = Path(scratch) / "prompt.md"
        prompt_file.write_text(prompt, encoding="utf-8")
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            # No --cost-sidecar: the REAL dispatcher owns telemetry here.
            rc = fake_agent.main(
                [
                    "--vault",
                    str(vault),
                    "--stage",
                    stage,
                    "--prompt-file",
                    str(prompt_file),
                ]
            )
    text = captured.getvalue()

    if shape.stream_json:
        out.write(
            stream_json_events(
                text,
                cost_usd=float(os.environ.get(COST_ENV) or 0.0),
                tokens_in=len(prompt.split()),
                tokens_out=len(text.split()),
                is_error=rc != 0,
            )
        )
    else:
        # Verbatim: on the non-stream path agent_call copies this stdout into
        # --output-file, and a stage whose product is JSON (the verifier) must
        # not find a cost line stapled to it.
        out.write(text)
    out.flush()
    return rc


# ---------------------------------------------------------------------------
# installation
# ---------------------------------------------------------------------------


_LAUNCHER = '''#!/usr/bin/env python3
"""Fake `{runtime}` CLI — see tests/_helpers/fake_cli_binary.py.

Deliberately thin: all behaviour lives in the importable helper so the tests
can drive it without spawning, and so this file has nothing in it to drift.
"""
import sys

sys.path.insert(0, {repo_root!r})

from tests._helpers.fake_cli_binary import stub_main  # noqa: E402

raise SystemExit(stub_main({runtime!r}, sys.argv[1:]))
'''


def install(
    bin_dir: Path, *, runtimes: Iterable[str] = SUPPORTED_RUNTIMES
) -> dict[str, Path]:
    """Write an executable fake CLI per runtime into *bin_dir*.

    The file is named as the binary it fakes (``claude``, not
    ``fake_claude``) — PATH resolution is half of what is under test.
    """
    bin_dir = Path(bin_dir)
    bin_dir.mkdir(parents=True, exist_ok=True)
    installed: dict[str, Path] = {}
    for runtime in runtimes:
        if runtime not in SUPPORTED_RUNTIMES:
            raise ValueError(
                f"{runtime!r} has no parse_argv branch; supported: "
                f"{', '.join(SUPPORTED_RUNTIMES)}"
            )
        target = bin_dir / runtime
        target.write_text(
            _LAUNCHER.format(runtime=runtime, repo_root=str(REPO_ROOT)),
            encoding="utf-8",
        )
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
        installed[runtime] = target
    return installed


def activate(
    monkeypatch, bin_dir: Path, *, runtimes: Iterable[str] = SUPPORTED_RUNTIMES
) -> dict[str, Path]:
    """Install the stubs and make the dispatcher find them, both ways.

    ``PATH`` covers the bare-name lookup the adapters do by default;
    ``CLAUDE_BIN`` / ``CODEX_BIN`` cover the per-profile override the module
    docstring documents. Setting both means a test cannot pass because of an
    ambient real ``claude`` on the developer's PATH.
    """
    bin_dir = Path(bin_dir).resolve()
    installed = install(bin_dir, runtimes=runtimes)
    monkeypatch.setenv("PATH", os.pathsep.join([str(bin_dir), os.environ["PATH"]]))
    for runtime, path in installed.items():
        monkeypatch.setenv(f"{runtime.upper()}_BIN", str(path))
    return installed


# ---------------------------------------------------------------------------
# reading the dispatcher back
# ---------------------------------------------------------------------------

_AGENT_CALL: ModuleType | None = None


def load_agent_call() -> ModuleType:
    """Import ``scripts/agent_call.py`` by path (it is a script, not a package).

    Same trick, same reason, as ``tests/_helpers/llm_dispatch.load_agent_call``:
    the tests assert against the argv the REAL adapters build, so they have to
    be able to call them.
    """
    global _AGENT_CALL
    if _AGENT_CALL is not None:
        return _AGENT_CALL
    name = f"_fake_cli_agent_call_{abs(hash(str(AGENT_CALL_PATH))):x}"
    spec = importlib.util.spec_from_file_location(name, AGENT_CALL_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover — defensive
        raise RuntimeError(f"cannot load the dispatcher from {AGENT_CALL_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    _AGENT_CALL = module
    return module


__all__ = [
    "COST_ENV",
    "STAGE_ENV",
    "SUPPORTED_RUNTIMES",
    "VAULT_ENV",
    "ArgvContractError",
    "ArgvShape",
    "activate",
    "install",
    "load_agent_call",
    "parse_argv",
    "stream_json_events",
    "stub_main",
]
