"""TTY helper tests (spec 033 FR-016)."""

from __future__ import annotations

import sys

import pytest

from research_framework.cli._tty import is_interactive_tty


@pytest.mark.parametrize(
    ("stdin_tty", "stdout_tty", "expected"),
    [
        (True, True, True),
        (True, False, False),
        (False, True, False),
        (False, False, False),
    ],
)
def test_is_interactive_tty_requires_both_stdin_and_stdout(
    monkeypatch: pytest.MonkeyPatch,
    stdin_tty: bool,
    stdout_tty: bool,
    expected: bool,
) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: stdin_tty)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: stdout_tty)
    assert is_interactive_tty() is expected
