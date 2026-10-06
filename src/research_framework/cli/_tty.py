"""TTY detection for budget/approval resume UX (spec 033 FR-016)."""

from __future__ import annotations

import sys


def is_interactive_tty() -> bool:
    """Return True only when both stdin and stdout are interactive TTYs."""
    return sys.stdin.isatty() and sys.stdout.isatty()
