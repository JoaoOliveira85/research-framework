"""Spec 025 US8 (B5): byte-identical --help and argparse topology preservation."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from research_framework.cli import build_parser

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _subprocess_env() -> dict[str, str]:
    """Force subprocess to import research_framework from the local worktree.

    Without this, an editable `pip install -e .` from a sibling worktree
    (common during parallel-spec development) bleeds into the subprocess
    and shows a different subcommand registry than `build_parser()` does
    in-process. Pin `PYTHONPATH` to the local `src/` so the subprocess
    sees the same code the in-process tests see.
    """
    env = os.environ.copy()
    src_path = str(_REPO_ROOT / "src")
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{src_path}{os.pathsep}{existing}" if existing else src_path
    # argparse wraps to ``shutil.get_terminal_size()``, which reads $COLUMNS
    # before falling back to 80. Now that the goldens hold real help text
    # (issue #264) rather than one-line rejections, a developer running under
    # a wide terminal that exports COLUMNS would otherwise get a spurious
    # byte-diff. Pin the width the goldens were generated at.
    env["COLUMNS"] = "80"
    return env


# Pre-B5 subcommand registration order (SC-009 / contract §5 option 1).
_EXPECTED_SUBCOMMANDS: tuple[str, ...] = (
    "generate",
    "coverage",
    "validate",
    "reindex",
    "check-skills",
    "cycle",
    "inventory",
    "onboard",
    "regenerate-agents",
    "prune",
    "parse-spec",
    "pipeline",
    "quality-baseline-update",
    "quality-fixture-init",
    "refresh-sources",
    "regenerate-shim",
    "status",
    "digest",
    "acceptance",
    "wikilinks",
    "re-grade",
    # Appended after the pre-B5 registry, never inserted into it: SC-009 pins
    # that prefix order, so a new verb goes on the end (issue #237's `pause`,
    # issue #189's `export`).
    "pause",
    "export",
)


def _cli_argv(*args: str) -> list[str]:
    return [sys.executable, "-m", "research_framework.cli", *args]


def _run_help(*args: str) -> bytes:
    result = subprocess.run(
        _cli_argv(*args),
        cwd=_REPO_ROOT,
        capture_output=True,
        check=False,
        env=_subprocess_env(),
    )
    return result.stdout + result.stderr


_CHOOSE_FROM_RE = re.compile(rb"\(choose from ([^)]*)\)")


def _normalize_choice_quotes(blob: bytes) -> bytes:
    """Strip the per-choice quoting inside argparse ``(choose from …)`` errors.

    Python 3.13 dropped the ``repr()`` quoting of the *choices* list in
    ``invalid choice`` errors: ``(choose from 'a', 'b')`` (≤3.12) became
    ``(choose from a, b)`` (3.13+). The goldens here exist to lock the
    subcommand **registry + order** (spec 025 US8 / SC-009), not argparse's
    incidental formatting, and the framework supports Python ≥3.11. Normalise
    both sides so the assertion is Python-version-independent while still
    failing if any choice name is added, removed, or reordered.
    """

    def _strip(match: re.Match[bytes]) -> bytes:
        inner = match.group(1).replace(b"'", b"")
        return b"(choose from " + inner + b")"

    return _CHOOSE_FROM_RE.sub(_strip, blob)


def _subparser_action(parser: argparse.ArgumentParser) -> argparse._SubParsersAction:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    raise AssertionError("top-level subparsers action not found")


def test_help_byte_identical() -> None:
    golden = (_FIXTURES / "help_output_pre_025.txt").read_bytes()
    actual = _run_help("--help")
    assert _normalize_choice_quotes(actual) == _normalize_choice_quotes(golden)


# One verb per shape the operator surface has: a positional-plus-many-flags
# verb (`generate`), a required-flag verb with a gate vocabulary
# (`acceptance`), the narrowest verb (`cycle`), and one with a mutually
# exclusive group (`digest`). Spec 025 T076 named `research`, `audit`, `vault`
# and `quality` — those are `cli/` MODULE names, not verbs, and the goldens
# generated from them were argparse invalid-choice ERRORS (issue #264).
_HELP_GOLDEN_SUBCOMMANDS: tuple[str, ...] = (
    "generate",
    "acceptance",
    "cycle",
    "digest",
)


def _subcommand_golden(subcommand: str) -> Path:
    return _FIXTURES / f"help_{subcommand}.txt"


@pytest.mark.parametrize("subcommand", _HELP_GOLDEN_SUBCOMMANDS)
def test_subcommand_help_byte_identical(subcommand: str) -> None:
    golden = _subcommand_golden(subcommand).read_bytes()
    actual = _run_help(subcommand, "--help")
    assert _normalize_choice_quotes(actual) == _normalize_choice_quotes(golden)


@pytest.mark.parametrize("subcommand", _HELP_GOLDEN_SUBCOMMANDS)
def test_subcommand_golden_pins_help_and_not_an_argparse_error(
    subcommand: str,
) -> None:
    """The goldens must hold each verb's real ``--help``, not a rejection.

    For four releases they held argparse ``invalid choice`` errors for verbs
    that do not exist, so ``test_subcommand_help_byte_identical`` pinned the
    subcommand *registry* four more times over and no verb's flags or help
    text were pinned anywhere — despite spec 025 US8 / SC-009 claiming they
    were. A golden that never mentions the verb it is named for cannot catch
    drift in that verb.
    """
    golden = _subcommand_golden(subcommand).read_text(encoding="utf-8")
    assert "invalid choice" not in golden, (
        f"help_{subcommand}.txt is an argparse rejection, not help output. "
        "Regenerate it against a registered verb."
    )
    assert golden.startswith(f"usage: research-framework {subcommand} ")


def test_argparse_topology_unchanged() -> None:
    parser = build_parser()
    sub = _subparser_action(parser)
    names = [action.dest for action in sub._choices_actions]
    assert names == list(_EXPECTED_SUBCOMMANDS)
    # spec 048: added global --log-level. Top-level actions = help + log_level + subparsers.
    assert len(parser._actions) == 3


def test_external_import_path() -> None:
    parser = build_parser()
    assert isinstance(parser, argparse.ArgumentParser)


def _placeholder_values(action: argparse.Action) -> list[str]:
    """A value argparse will accept for *action*, whatever its type/choices."""
    if action.choices:
        return [str(next(iter(action.choices)))]
    if action.type is int:
        return ["1"]
    if action.type is float:
        return ["1.0"]
    return ["placeholder"]


def _minimal_argv(name: str, subparser: argparse.ArgumentParser) -> list[str]:
    """The shortest argv that parses under *subparser*.

    Synthesised from the parser rather than hand-listed, so a new subcommand
    (or a new required flag on an existing one) is covered the moment it is
    registered — the alternative is a second table to keep in step with the
    first, which is how the tautology this replaces survived.
    """
    argv = [name]
    for action in subparser._actions:
        if isinstance(action, argparse._HelpAction):
            continue
        if action.option_strings:
            if action.required:
                argv.append(action.option_strings[-1])
                argv.extend(_placeholder_values(action))
        elif action.nargs not in ("?", "*"):
            argv.extend(_placeholder_values(action))
    return argv


@pytest.mark.parametrize("subcommand", _EXPECTED_SUBCOMMANDS)
def test_parsed_namespace_carries_a_callable_handler(subcommand: str) -> None:
    """``main`` calls ``args.func(args)``; every verb must put one there.

    The previous version of this test asserted
    ``getattr(action, "func", None) is not None or action.dest is not None``
    against the *registration* action — whose right-hand clause is always
    true, so it could not fail. A subcommand registered without
    ``set_defaults(func=...)`` shipped green and crashed at ``args.func``.
    Parse the verb's minimal argv and interrogate the namespace ``main``
    actually reads instead.
    """
    parser = build_parser()
    subparser = _subparser_action(parser).choices[subcommand]
    namespace = parser.parse_args(_minimal_argv(subcommand, subparser))
    handler = getattr(namespace, "func", None)
    assert callable(handler), (
        f"`research-framework {subcommand}` parses to a namespace with no "
        "callable `func`. main() would raise AttributeError at args.func — "
        "the subparser is missing its set_defaults(func=...)."
    )
