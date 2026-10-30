"""Issue #15 — ``./vault ask`` starts a research run only under ``--escalate``.

Drives the *rendered* shim with ``/bin/bash`` (3.2 on a stock Mac). Nothing
real runs: ``claude`` is a stub that records its argv, and the vault's
``.venv/bin/python`` records any ``-m research_framework.cli`` call instead of
running it (every other use — the auto-commit heredoc — goes to the real
interpreter).
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_framework.generator.scaffold import render_vault_shim

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SYSTEM_BASH = Path("/bin/bash")

pytestmark = pytest.mark.skipif(
    not _SYSTEM_BASH.is_file(), reason="/bin/bash not available"
)

_CLAUDE_RC = 7
_FRAMEWORK_RC = 5


def _executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture()
def shim(tmp_path: Path):
    vault = tmp_path / "vault"
    venv_bin = vault / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    python = shlex.quote(sys.executable)
    framework_log = tmp_path / "framework-argv.json"
    claude_log = tmp_path / "claude-argv.json"
    _executable(
        venv_bin / "python",
        "#!/bin/sh\n"
        'if [ "$1" = "-m" ] && [ "$2" = "research_framework.cli" ]; then\n'
        f'  exec {python} -c \'import json,sys; open(sys.argv[1],"w").write('
        f"json.dumps(sys.argv[4:])); sys.exit({_FRAMEWORK_RC})' "
        f'{shlex.quote(str(framework_log))} "$@"\n'
        "fi\n"
        f'exec {python} "$@"\n',
    )
    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    _executable(
        stub_bin / "claude",
        f"#!/bin/sh\nexec {python} -c 'import json,sys; "
        f'open(sys.argv[1],"w").write(json.dumps(sys.argv[2:])); '
        f'sys.exit({_CLAUDE_RC})\' {shlex.quote(str(claude_log))} "$@"\n',
    )
    _executable(
        vault / "vault",
        render_vault_shim(vault, SimpleNamespace(name="Ask Shim Vault")),  # type: ignore[arg-type]
    )
    git = shutil.which("git")
    assert git
    env = {
        "PATH": os.pathsep.join(
            [str(stub_bin), str(Path(git).parent), "/usr/bin", "/bin"]
        ),
        "HOME": str(tmp_path),
        "PYTHONPATH": str(_REPO_ROOT / "src"),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }

    def run(*argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(_SYSTEM_BASH), str(vault / "vault"), *argv],
            cwd=vault,
            env=env,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=60,
        )

    def argv_of(log: Path) -> list[str] | None:
        return json.loads(log.read_text()) if log.is_file() else None

    return SimpleNamespace(
        vault=vault,
        run=run,
        framework=lambda: argv_of(framework_log),
        claude=lambda: argv_of(claude_log),
    )


def test_ask_without_escalate_opens_the_session_and_calls_no_framework_verb(
    shim,
) -> None:
    proc = shim.run("ask", "What is X?")

    assert proc.returncode == _CLAUDE_RC, proc.stderr
    assert shim.claude() == ["What is X?"]
    assert shim.framework() is None, (
        "ask without --escalate must not reach the framework"
    )


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(("--escalate", "What is X?"), id="flag-first"),
        pytest.param(("What is X?", "--escalate"), id="flag-last"),
    ],
)
def test_ask_escalate_forwards_to_the_framework_verb(shim, argv) -> None:
    proc = shim.run("ask", *argv)

    assert proc.returncode == _FRAMEWORK_RC, proc.stderr
    assert shim.claude() is None, "the escalation is the framework's, not a session"
    assert shim.framework() == [
        "ask",
        "--vault",
        str(shim.vault),
        "--escalate",
        "--",
        "What is X?",
    ]


def test_a_question_that_looks_like_a_flag_reaches_the_verb_as_text(shim) -> None:
    proc = shim.run("ask", "--escalate", "-x --resume what now")

    assert proc.returncode == _FRAMEWORK_RC, proc.stderr
    assert shim.framework()[-2:] == ["--", "-x --resume what now"]


def test_ask_escalate_without_a_question_is_a_usage_error(shim) -> None:
    proc = shim.run("ask", "--escalate")

    assert proc.returncode == 2
    assert shim.framework() is None
    assert shim.claude() is None
    assert "--escalate" in proc.stderr


def test_ask_with_no_arguments_still_opens_an_empty_session(shim) -> None:
    """bash 3.2 + ``set -u``: an empty argument array must not be "unbound"."""
    proc = shim.run("ask")

    assert proc.returncode == _CLAUDE_RC, proc.stderr
    assert shim.claude() == []
    assert shim.framework() is None
