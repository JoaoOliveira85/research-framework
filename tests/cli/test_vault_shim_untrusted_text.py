"""The ``./vault`` shim hands the operator's text to Python as data, never as source.

``_vault_autocommit`` — the helper behind the commit that follows ``ask``,
``write`` and ``sync`` — built its Python by pasting the verb's text into an
unquoted heredoc (``title = \"\"\"${title}\"\"\"``). The text was therefore
*source*:

* ``./vault ask 'define "idempotent"'`` was a ``SyntaxError``: no commit, and
  under ``set -euo pipefail`` the shim died with exit 1 before it could return
  the session's own exit code;
* a topic containing three double quotes ran whatever Python followed them;
* a backslash was read as an escape (``C:\\new`` became ``C:``, a newline,
  ``ew``), and one at the end of the topic was a ``SyntaxError`` again.

Every case drives the *rendered* shim with ``/bin/bash`` — bash 3.2 on macOS,
which is what ``#!/usr/bin/env bash`` resolves to on a stock Mac. No agent is
called: ``PATH`` is a stub ``claude`` plus the system directories, and the
vault's ``scripts/generate_doc.py`` is a stub too.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_framework.generator.scaffold import render_vault_shim

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SYSTEM_BASH = Path("/bin/bash")

pytestmark = [
    pytest.mark.regression,
    pytest.mark.skipif(not _SYSTEM_BASH.is_file(), reason="/bin/bash not available"),
]

#: Exit code of the stubbed session (``claude`` / ``generate_doc.py``). Neither
#: 0 nor 1, so "the shim's own failure" and "success" cannot pass for it.
_SESSION_RC = 7

#: Stands in for the agent: records its argv, leaves a note in the vault for the
#: auto-commit to pick up, and exits with ``_SESSION_RC``.
_SESSION_STUB = """\
import json
import os
import sys
from pathlib import Path

Path(os.environ["RF_TEST_ARGV"]).write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
note = Path(os.environ["RF_TEST_VAULT"]) / "data_vault" / "session-note.md"
note.parent.mkdir(exist_ok=True)
note.write_text("written by the stubbed session\\n", encoding="utf-8")
sys.exit(int(os.environ["RF_TEST_SESSION_RC"]))
"""

#: What an operator — or anything that builds a ``./vault`` command from a note
#: title or a harvested topic — can put in the text. ``RF_TEST_MARK`` names a
#: file that exists only if some layer *executed* the text.
_TEXTS = {
    "double-quotes": 'define "idempotent"',
    "triple-quote-python": (
        'x"""; import os; open(os.environ["RF_TEST_MARK"], "w").write("executed"); """'
    ),
    "command-substitution": 'the cost of $(touch "${RF_TEST_MARK}") today',
    "backticks": 'the cost of `touch "${RF_TEST_MARK}"` today',
    "backslash-escapes": r"why does C:\new\table break",
    "trailing-backslash": "the path C:\\",
    "named-escape": r"what is \N{NOT A NAME}",
    "newline": "first line\nsecond line",
    "leading-dash": "-x --resume what now",
}


def _write_executable(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


@dataclass(frozen=True)
class ShimVault:
    """A throwaway git vault with the rendered shim and a stubbed agent."""

    vault: Path
    env: dict[str, str]
    marker: Path
    session_argv: Path

    def run(self, *argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(_SYSTEM_BASH), str(self.vault / "vault"), *argv],
            cwd=self.vault,
            env=self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            stdin=subprocess.DEVNULL,
            timeout=60,
        )

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.vault), *args],
            env=self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout

    def commit_count(self) -> int:
        return int(self.git("rev-list", "--count", "HEAD"))

    def last_message(self) -> str:
        return self.git("log", "-1", "--format=%B").rstrip("\n")

    def recorded_argv(self) -> list[str]:
        return json.loads(self.session_argv.read_text(encoding="utf-8"))


def _build(tmp_path: Path, vault: Path) -> ShimVault:
    vault.mkdir(parents=True)
    python = shlex.quote(sys.executable)

    # The shim only ever runs `${VAULT_DIR}/.venv/bin/python`; this one is the
    # interpreter running the tests, which has the framework importable.
    venv_bin = vault / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    _write_executable(venv_bin / "python", f'#!/bin/sh\nexec {python} "$@"\n')

    scripts = vault / "scripts"
    scripts.mkdir()
    (scripts / "generate_doc.py").write_text(_SESSION_STUB, encoding="utf-8")

    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    session = tmp_path / "session_stub.py"
    session.write_text(_SESSION_STUB, encoding="utf-8")
    claude = _write_executable(
        stub_bin / "claude",
        f'#!/bin/sh\nexec {python} {shlex.quote(str(session))} "$@"\n',
    )

    shim = vault / "vault"
    shim.write_text(
        render_vault_shim(vault, SimpleNamespace(name="Shim Test Vault")),  # type: ignore[arg-type]
        encoding="utf-8",
    )
    shim.chmod(0o755)

    git = shutil.which("git")
    assert git, "git is required"
    home = tmp_path / "home"
    home.mkdir()
    env = {
        # The stub first, then git's directory and the system ones — never the
        # developer's own PATH, which is where a real `claude` lives.
        "PATH": os.pathsep.join(
            [str(stub_bin), str(Path(git).parent), "/usr/bin", "/bin"]
        ),
        "HOME": str(home),
        "PYTHONPATH": str(_REPO_ROOT / "src"),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "RF_TEST_VAULT": str(vault),
        "RF_TEST_ARGV": str(tmp_path / "session-argv.json"),
        "RF_TEST_MARK": str(tmp_path / "EXECUTED"),
        "RF_TEST_SESSION_RC": str(_SESSION_RC),
    }
    assert shutil.which("claude", path=env["PATH"]) == str(claude)

    built = ShimVault(
        vault=vault,
        env=env,
        marker=tmp_path / "EXECUTED",
        session_argv=tmp_path / "session-argv.json",
    )
    built.git("init", "-q", "-b", "main")
    built.git("add", "-A")
    built.git("commit", "-q", "-m", "bootstrap")
    return built


@pytest.fixture()
def shim_vault(tmp_path: Path) -> ShimVault:
    return _build(tmp_path, tmp_path / "vault")


def _expected_message(verb: str, text: str) -> str:
    """``vault: <verb> — <first line>`` plus the whole text as the body."""
    title = f"{verb} {text}"
    return f"vault: {verb} — {title.splitlines()[0]}\n\n{title}"


@pytest.mark.parametrize("text", list(_TEXTS.values()), ids=list(_TEXTS))
def test_ask_commits_the_literal_question_and_keeps_the_session_exit_code(
    shim_vault: ShimVault, text: str
) -> None:
    proc = shim_vault.run("ask", text)
    combined = proc.stdout + proc.stderr

    assert not shim_vault.marker.exists(), f"the question was executed:\n{combined}"
    assert shim_vault.recorded_argv() == [text]
    assert shim_vault.commit_count() == 2, combined
    assert shim_vault.last_message() == _expected_message("ask", text)
    assert proc.returncode == _SESSION_RC, combined


@pytest.mark.parametrize("text", list(_TEXTS.values()), ids=list(_TEXTS))
def test_write_commits_the_literal_topic_and_keeps_the_generator_exit_code(
    shim_vault: ShimVault, text: str
) -> None:
    proc = shim_vault.run("write", text)
    combined = proc.stdout + proc.stderr

    assert not shim_vault.marker.exists(), f"the topic was executed:\n{combined}"
    vault = str(shim_vault.vault)
    assert shim_vault.recorded_argv() == [
        "--vault",
        vault,
        "--topic",
        text,
        "--output",
        f"{vault}/_output",
    ]
    assert shim_vault.commit_count() == 2, combined
    assert shim_vault.last_message() == _expected_message("write", text)
    assert proc.returncode == _SESSION_RC, combined


@pytest.mark.parametrize("text", list(_TEXTS.values()), ids=list(_TEXTS))
def test_sync_commits_under_the_literal_label_and_exits_zero(
    shim_vault: ShimVault, text: str
) -> None:
    note = shim_vault.vault / "data_vault" / "note.md"
    note.parent.mkdir()
    note.write_text("a note waiting to be synced\n", encoding="utf-8")

    proc = shim_vault.run("sync", text)
    combined = proc.stdout + proc.stderr

    assert not shim_vault.marker.exists(), f"the label was executed:\n{combined}"
    assert shim_vault.commit_count() == 2, combined
    assert shim_vault.last_message() == _expected_message("sync", text)
    assert proc.returncode == 0, combined


def test_a_backslash_in_the_vault_path_does_not_hide_the_repository(
    tmp_path: Path,
) -> None:
    """The vault's own path took the same route into Python source, so a
    directory named ``with\\tab`` was read as ``with<TAB>ab``: no such
    repository, and every auto-commit was silently skipped."""
    built = _build(tmp_path, tmp_path / "with\\tab" / "vault")

    proc = built.run("ask", "anything")
    combined = proc.stdout + proc.stderr

    assert "not a git repo" not in combined, combined
    assert built.commit_count() == 2, combined
    assert built.last_message() == _expected_message("ask", "anything")
    assert proc.returncode == _SESSION_RC, combined


# ---------------------------------------------------------------------------
# The rule behind the cases above, for every heredoc at once: the Python the
# shim runs is fixed text. A value gets there through the environment.
# ---------------------------------------------------------------------------

_HEREDOC = re.compile(
    r"<<-?\s*(?P<quote>['\"]?)(?P<tag>[A-Za-z_][A-Za-z0-9_]*)(?P=quote)"
)
_SENTINEL = "rf-shim-sentinel"


def _python_heredocs(rendered: str) -> list[tuple[int, bool, str]]:
    """``(line, delimiter is quoted, body)`` of each heredoc fed to Python."""
    lines = rendered.splitlines()
    found = []
    for number, line in enumerate(lines, start=1):
        match = _HEREDOC.search(line)
        if match is None or "VENV_PYTHON" not in line:
            continue
        end = lines.index(match["tag"], number)
        found.append((number, bool(match["quote"]), "\n".join(lines[number:end])))
    return found


def test_no_value_is_pasted_into_the_python_the_shim_runs() -> None:
    rendered = render_vault_shim(
        Path(f"/{_SENTINEL}/vault"),
        SimpleNamespace(name=_SENTINEL),  # type: ignore[arg-type]
    )
    heredocs = _python_heredocs(rendered)
    assert heredocs, "no Python heredoc found in the rendered shim: the scan is broken"

    problems = []
    for number, quoted, body in heredocs:
        if not quoted:
            problems.append(
                f"line {number}: unquoted heredoc, the shell expands into the source"
            )
        if _SENTINEL in body:
            problems.append(f"line {number}: a value is rendered into the source")
    assert problems == [], "\n".join(problems)
